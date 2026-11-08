"""fakeserver — a scripted SSH server for burrow's hostile-peer rows.

burrow's own code, written from the same specifications as tools/vectorgen.py
and built on its primitives (X25519, Ed25519, ChaCha20 and Poly1305 from RFC
7748, 8032 and 8439; the exchange hash and key derivation from RFC 4253 and
8731; chacha20-poly1305@openssh.com from OpenSSH's PROTOCOL note). It speaks
just enough of the transport (curve25519-sha256, ssh-ed25519, strict kex),
accepts any publickey request (it is the client under test, not the server,
that a row judges), opens one session channel, and then does what a row's
script says: the misbehaviour a real server never shows.

    with FakeServer(script) as f:     # f.port, f.host_line(), f.record
        ... run burrow against 127.0.0.1:f.port ...

Pure Python: slow (a few MB a second), so rows move kilobytes.
"""
import os
import pathlib
import socket
import struct
import sys
import threading
import base64
import hashlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vectorgen as v  # noqa: E402


def string(b):
    return struct.pack(">I", len(b)) + b


def u32(n):
    return struct.pack(">I", n)


class Reader:
    def __init__(self, b):
        self.b, self.i = b, 0

    def u8(self):
        self.i += 1
        return self.b[self.i - 1]

    def u32(self):
        self.i += 4
        return struct.unpack(">I", self.b[self.i - 4:self.i])[0]

    def string(self):
        n = self.u32()
        self.i += n
        return self.b[self.i - n:self.i]

    def boolean(self):
        return self.u8() != 0


class Wire:
    """One connection: plaintext, then chacha20-poly1305 both ways."""

    def __init__(self, sock):
        self.s, self.buf = sock, b""
        self.tx_key = self.rx_key = None
        self.tx_seq = self.rx_seq = 0

    def need(self, n):
        while len(self.buf) < n:
            got = self.s.recv(65536)
            if not got:
                raise EOFError("the client closed the connection")
            self.buf += got

    def line(self):
        while b"\n" not in self.buf:
            self.need(len(self.buf) + 1)
        i = self.buf.index(b"\n")
        out, self.buf = self.buf[:i + 1], self.buf[i + 1:]
        return out.rstrip(b"\r\n")

    def frame(self, payload):
        return v.frame(payload, pad_byte=0, sealed=self.tx_key is not None)

    def encode(self, payload):
        f = self.frame(payload)
        out = v.chachapoly_seal(self.tx_key, self.tx_seq, f) if self.tx_key else f
        self.tx_seq += 1
        return out

    def send(self, payload):
        self.s.sendall(self.encode(payload))

    def recv(self):
        if self.rx_key is None:
            self.need(4)
            n = struct.unpack(">I", self.buf[:4])[0]
            self.need(4 + n)
            body, self.buf = self.buf[4:4 + n], self.buf[4 + n:]
        else:
            k2, k1 = self.rx_key[:32], self.rx_key[32:]
            nonce = v.nonce_of(self.rx_seq)
            self.need(4)
            n = struct.unpack(">I", v.chacha20_xor(k1, 0, nonce, self.buf[:4]))[0]
            self.need(4 + n + 16)
            enc, tag = self.buf[:4 + n], self.buf[4 + n:4 + n + 16]
            if v.poly1305(v.chacha20_block(k2, 0, nonce)[:32], enc) != tag:
                raise ValueError("bad tag from the client")
            body = v.chacha20_xor(k2, 1, nonce, enc[4:])
            self.buf = self.buf[4 + n + 16:]
        self.rx_seq += 1
        pad = body[0]
        return body[1:len(body) - pad]


class FakeServer:
    """Listens on a loopback port; serves one connection with `script`, a
    function (server, wire) run once the session's exec is accepted (or, for
    `stage="auth"`, right after SERVICE_ACCEPT)."""

    def __init__(self, script, stage="session", window=2097152, maxpkt=32768, shell="accept"):
        self.script, self.stage, self.window, self.maxpkt = script, stage, window, maxpkt
        self.shell = shell
        self.seed = os.urandom(32)
        self.host_pub = v.ed25519_public(self.seed)
        self.k_s = string(b"ssh-ed25519") + string(self.host_pub)
        self.record = {"events": [], "error": None}
        self.lsock = socket.socket()
        self.lsock.bind(("127.0.0.1", 0))
        self.lsock.listen(1)
        self.port = self.lsock.getsockname()[1]

    def host_line(self):
        return f"[127.0.0.1]:{self.port} ssh-ed25519 {base64.b64encode(self.k_s).decode()}\n"

    def __enter__(self):
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.lsock.close()
        self.thread.join(timeout=30)

    def event(self, *e):
        self.record["events"].append(e)

    def serve(self):
        try:
            self.lsock.settimeout(60)
            conn, _ = self.lsock.accept()
            conn.settimeout(30)
            with conn:
                self.run(Wire(conn))
        except Exception as e:  # recorded; the row decides
            self.record["error"] = f"{type(e).__name__}: {e}"

    def kex(self, w):
        v_s = b"SSH-2.0-burrowfake_0"
        w.s.sendall(v_s + b"\r\n")
        v_c = w.line()
        i_s = v.kexinit(os.urandom(16), ["curve25519-sha256", "kex-strict-s-v00@openssh.com"], ["ssh-ed25519"],
                        ["chacha20-poly1305@openssh.com"], ["hmac-sha2-256"], ["none"])
        w.send(i_s)
        i_c = w.recv()
        init = w.recv()
        q_c = Reader(init[1:]).string()
        secret = os.urandom(32)
        q_s = v.x25519_base(secret)
        x = v.x25519(secret, q_c)
        k_mp = v.mpint_unsigned(x)
        h = hashlib.sha256(string(v_c) + string(v_s) + string(i_c) + string(i_s) + string(self.k_s)
                           + string(q_c) + string(q_s) + k_mp).digest()
        sig = string(b"ssh-ed25519") + string(v.ed25519_sign(self.seed, h))
        w.send(bytes([31]) + string(self.k_s) + string(q_s) + string(sig))
        w.send(bytes([21]))
        if w.recv() != bytes([21]):
            raise ValueError("no NEWKEYS from the client")
        # Strict kex: both sequence numbers restart at NEWKEYS.
        w.tx_key, w.rx_key = v.derive(k_mp, h, b"D", h, 64), v.derive(k_mp, h, b"C", h, 64)
        w.tx_seq = w.rx_seq = 0

    def run(self, w):
        self.kex(w)
        req = w.recv()
        self.event("service", req[0])
        w.send(bytes([6]) + string(b"ssh-userauth"))
        if self.stage == "auth":
            return self.script(self, w)
        while True:
            p = w.recv()
            if p[0] != 50:
                raise ValueError(f"message {p[0]} in authentication")
            r = Reader(p[1:])
            r.string(), r.string(), r.string()
            signed = r.boolean()
            alg, blob = r.string(), r.string()
            if not signed:
                w.send(bytes([60]) + string(alg) + string(blob))
                continue
            w.send(bytes([52]))
            break
        p = w.recv()
        if p[0] != 90:
            raise ValueError(f"message {p[0]} instead of CHANNEL_OPEN")
        r = Reader(p[1:])
        r.string()
        self.client_channel = r.u32()
        self.event("open", r.u32(), r.u32())
        w.send(bytes([91]) + u32(self.client_channel) + u32(0) + u32(self.window) + u32(self.maxpkt))
        while True:
            p = w.recv()
            r = Reader(p[1:])
            if p[0] == 98:
                r.u32()
                kind, want = r.string(), r.boolean()
                self.event("request", kind.decode())
                if kind == b"exec":
                    self.event("command", r.string().decode())
                    w.send(bytes([99]) + u32(self.client_channel))
                    break
                if kind == b"shell":
                    # RFC 4254 §6.5; `shell="refuse"` answers CHANNEL_FAILURE.
                    w.send(bytes([100 if self.shell == "refuse" else 99]) + u32(self.client_channel))
                    break
        self.script(self, w)

    # Helpers for scripts.
    def to_client(self, t, *fields):
        return bytes([t]) + u32(self.client_channel) + b"".join(fields)

    def finish(self, w, status=0):
        w.send(self.to_client(98, string(b"exit-status"), b"\x00", u32(status)))
        w.send(self.to_client(96))
        w.send(self.to_client(97))
        self.drain(w)

    def drain(self, w, seconds=10):
        """Reads until the client's CLOSE or the end, recording what came."""
        w.s.settimeout(seconds)
        try:
            while True:
                p = w.recv()
                self.event("got", p[0], len(p))
                if p[0] == 97:
                    return
        except (EOFError, socket.timeout, OSError):
            return
