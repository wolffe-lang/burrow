"""fakeclient — a scripted SSH client for burrowd's hostile-client rows.

burrow's own code, written from the same specifications as
tools/vectorgen.py and built on its primitives and tools/fakeserver.py's
Wire (X25519, Ed25519, ChaCha20 and Poly1305 from RFC 7748, 8032 and 8439;
the exchange hash and key derivation from RFC 4253 and 8731;
chacha20-poly1305@openssh.com from OpenSSH's PROTOCOL note). It speaks just
enough of a client to reach each stage, then does what a row's script says:
the misbehaviour a real client never shows.

    c = FakeClient(port)
    c.kex()                         # or c.kex(strict=False)
    c.service()
    c.query(user, seed) / c.signed(user, seed, session_id=..., signer=...)

Pure Python: slow (a few MB a second), so rows move kilobytes.
"""
import hashlib
import os
import pathlib
import socket
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vectorgen as v  # noqa: E402
from fakeserver import Reader, Wire, string, u32  # noqa: E402

V_C = b"SSH-2.0-fakeclient_0"


def blob_of(seed):
    return string(b"ssh-ed25519") + string(v.ed25519_public(seed))


def public_line(seed, comment="hostile"):
    import base64
    return f"ssh-ed25519 {base64.b64encode(blob_of(seed)).decode()} {comment}\n"


class FakeClient:
    def __init__(self, port, timeout=30):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.w = Wire(self.s)
        self.session_id = None
        # Every message received, as (type, payload), whichever step read
        # it: a DISCONNECT that ends kex() early is still the row's to see.
        self.received = []

    def _recv(self):
        p = self.w.recv()
        self.received.append((p[0], p))
        return p

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass

    def kex(self, strict=True, ext_info=True):
        self.s.sendall(V_C + b"\r\n")
        v_s = self.w.line()
        kexl = ["curve25519-sha256"] + (["ext-info-c"] if ext_info else []) + (["kex-strict-c-v00@openssh.com"] if strict else [])
        i_c = v.kexinit(os.urandom(16), kexl, ["ssh-ed25519"], ["chacha20-poly1305@openssh.com"], ["hmac-sha2-256"], ["none"])
        self.w.send(i_c)
        i_s = self._recv()
        if i_s[0] != 20:
            raise ValueError(f"message {i_s[0]} instead of KEXINIT")
        secret = os.urandom(32)
        q_c = v.x25519_base(secret)
        self.w.send(bytes([30]) + string(q_c))
        reply = self._recv()
        if reply[0] != 31:
            raise ValueError(f"message {reply[0]} instead of KEX_ECDH_REPLY")
        r = Reader(reply[1:])
        k_s, q_s, sig = r.string(), r.string(), r.string()
        x = v.x25519(secret, q_s)
        k_mp = v.mpint_unsigned(x)
        h = hashlib.sha256(string(V_C) + string(v_s) + string(i_c) + string(i_s) + string(k_s)
                           + string(q_c) + string(q_s) + k_mp).digest()
        self.session_id = h
        self.w.send(bytes([21]))
        if self._recv() != bytes([21]):
            raise ValueError("no NEWKEYS from the server")
        self.w.tx_key, self.w.rx_key = v.derive(k_mp, h, b"C", h, 64), v.derive(k_mp, h, b"D", h, 64)
        self.w.tx_seq = self.w.rx_seq = 0
        self.k_s = k_s
        return h

    def recv(self):
        """The next message, skipping EXT_INFO and global requests."""
        while True:
            p = self._recv()
            if p[0] in (7, 80, 2):
                continue
            return p

    def service(self):
        self.w.send(bytes([5]) + string(b"ssh-userauth"))
        p = self.recv()
        if p[0] != 6:
            raise ValueError(f"message {p[0]} instead of SERVICE_ACCEPT")

    @staticmethod
    def head(user, method=b"publickey"):
        return bytes([50]) + string(user.encode()) + string(b"ssh-connection") + string(method)

    def query(self, user, seed):
        self.w.send(self.head(user) + b"\x00" + string(b"ssh-ed25519") + string(blob_of(seed)))
        return self.recv()

    def signed(self, user, seed, session_id=None, signer=None):
        """The signed request for `seed`'s key, its signature by `signer`'s
        key (default the same) over `session_id` (default the real one)."""
        blob = blob_of(seed)
        sid = session_id if session_id is not None else self.session_id
        data = string(sid) + self.head(user) + b"\x01" + string(b"ssh-ed25519") + string(blob)
        sig = v.ed25519_sign(signer if signer is not None else seed, data)
        self.w.send(self.head(user) + b"\x01" + string(b"ssh-ed25519") + string(blob)
                    + string(string(b"ssh-ed25519") + string(sig)))
        return self.recv()

    def open_session(self, window=2097152, maxpkt=32768):
        self.w.send(bytes([90]) + string(b"session") + u32(0) + u32(window) + u32(maxpkt))

    def request(self, peer, kind, want, *fields):
        self.w.send(bytes([98]) + u32(peer) + string(kind) + (b"\x01" if want else b"\x00") + b"".join(fields))

    def data(self, peer, data):
        self.w.send(bytes([94]) + u32(peer) + string(data))

    def until_end(self, seconds=10):
        """Every message until the server ends the connection: a list of
        (type, payload); a DISCONNECT is the last."""
        self.s.settimeout(seconds)
        got = []
        try:
            while True:
                p = self._recv()
                got.append((p[0], p))
                if p[0] == 1:
                    break
        except (EOFError, socket.timeout, OSError, ValueError, struct.error):
            pass
        return got


def disconnect_of(got):
    """(reason code, text) of the DISCONNECT among `got`, or None."""
    for t, p in got:
        if t == 1:
            r = Reader(p[1:])
            return r.u32(), r.string().decode("utf-8", "replace")
    return None
