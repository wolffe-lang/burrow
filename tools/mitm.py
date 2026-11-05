"""mitm — a loopback TCP relay that can record, and can tamper with, the
plaintext part of an SSH transport (RFC 4253 §4.2 and §6), for burrow's
mutation and transcript rows. Written from the RFCs; it understands only
the version line and unencrypted binary packets, which is all the
tampering needs: everything after the server's NEWKEYS is relayed as bytes.

    with mitm.Relay(upstream_port, server_hook=Hook(...)) as r:
        connect the client to r.port ...
        r.c2s, r.s2c   # every byte relayed each way (after tampering)
"""
import socket
import struct
import threading
import time


def frame(payload, padlen=None):
    """A plaintext RFC 4253 §6 frame: whole frame a multiple of 8, padding >= 4."""
    if padlen is None:
        padlen = 4
        while (5 + len(payload) + padlen) % 8:
            padlen += 1
    return struct.pack(">IB", 1 + len(payload) + padlen, padlen) + payload + b"\x00" * padlen


def ignore_packet(data=b"burrow row"):
    return frame(bytes([2]) + struct.pack(">I", len(data)) + data)


def read_namelists(payload):
    """KEXINIT's ten name-lists, as (start, end) offsets of each string's bytes."""
    at = 17
    spans = []
    for _ in range(10):
        n = struct.unpack(">I", payload[at:at + 4])[0]
        spans.append((at + 4, at + 4 + n))
        at += 4 + n
    return spans


def kexinit_without(payload, name):
    """The KEXINIT payload with `name` removed from its kex name-list."""
    spans = read_namelists(payload)
    s, e = spans[0]
    names = [n for n in payload[s:e].decode().split(",") if n != name]
    lst = ",".join(names).encode()
    return payload[:s - 4] + struct.pack(">I", len(lst)) + lst + payload[e:]


class Hook:
    """What to do to the server's plaintext stream. Every field is optional:
    banner      bytes sent to the client before the server's version line
    version     bytes sent INSTEAD of the server's version line (CR LF included)
    on_packet   fn(msg_type, payload) -> list of frames to send in its place
    flip_first_sealed_tag  flip the last byte of the server's first sealed packet
    """

    def __init__(self, banner=b"", version=None, on_packet=None, flip_first_sealed_tag=False):
        self.banner = banner
        self.version = version
        self.on_packet = on_packet
        self.flip = flip_first_sealed_tag


class Relay:
    def __init__(self, upstream_port, server_hook=None):
        self.upstream = upstream_port
        self.hook = server_hook or Hook()
        self.c2s = bytearray()
        self.s2c = bytearray()
        self.events = []
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.done = threading.Event()
        self.hold_client = threading.Event()
        self.hold_client.set()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.done.set()
        try:
            self.listener.close()
        except OSError:
            pass
        self.thread.join(timeout=10)

    def _serve(self):
        self.listener.settimeout(30)
        try:
            client, _ = self.listener.accept()
        except OSError:
            return
        server = socket.create_connection(("127.0.0.1", self.upstream), timeout=30)
        up = threading.Thread(target=self._client_to_server, args=(client, server), daemon=True)
        up.start()
        try:
            self._server_to_client(server, client)
        except OSError:
            pass
        finally:
            up.join(timeout=10)
            for s in (client, server):
                try:
                    s.close()
                except OSError:
                    pass

    def _client_to_server(self, client, server):
        # The client's version line and plaintext packets pass straight
        # through; once its NEWKEYS has gone, later (sealed) bytes wait while
        # the server side holds the client (the flip row's ordering).
        buf = bytearray()
        keyed = False
        try:
            while True:
                data = client.recv(65536)
                if not data:
                    break
                if keyed:
                    self.hold_client.wait(timeout=10)
                    self.c2s += data
                    server.sendall(data)
                    continue
                buf.extend(data)
                out = bytearray()
                while True:
                    if not self.c2s and not out:
                        if b"\n" not in buf:
                            break
                        end = buf.index(b"\n") + 1
                        out += buf[:end]
                        del buf[:end]
                        continue
                    if len(buf) < 5:
                        break
                    n = struct.unpack(">I", buf[:4])[0]
                    if len(buf) < 4 + n:
                        break
                    pkt = bytes(buf[:4 + n])
                    del buf[:4 + n]
                    out += pkt
                    t = pkt[5] if len(pkt) > 5 else -1
                    self.events.append(("c2s", t, n))
                    if t == 21:
                        keyed = True
                        break
                self.c2s += out
                server.sendall(bytes(out))
                if keyed and buf:
                    self.hold_client.wait(timeout=10)
                    self.c2s += buf
                    server.sendall(bytes(buf))
                    buf.clear()
        except OSError:
            pass
        try:
            server.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    def _send(self, client, data):
        self.s2c += data
        client.sendall(data)

    def _server_to_client(self, server, client):
        buf = bytearray()

        def need(n):
            while len(buf) < n:
                data = server.recv(65536)
                if not data:
                    raise EOFError
                buf.extend(data)

        try:
            # The version line (RFC 4253 §4.2).
            while b"\n" not in buf:
                need(len(buf) + 1)
            end = buf.index(b"\n") + 1
            line = bytes(buf[:end])
            del buf[:end]
            if self.hook.banner:
                self._send(client, self.hook.banner)
            self._send(client, self.hook.version if self.hook.version is not None else line)
            # Plaintext packets until the server's NEWKEYS.
            while True:
                need(5)
                n = struct.unpack(">I", buf[:4])[0]
                need(4 + n)
                pkt = bytes(buf[:4 + n])
                del buf[:4 + n]
                padlen = pkt[4]
                payload = pkt[5:4 + n - padlen]
                t = payload[0]
                self.events.append(("s2c", t, len(payload)))
                if t == 21 and self.hook.flip:
                    self.hold_client.clear()
                out = [pkt]
                if self.hook.on_packet:
                    replaced = self.hook.on_packet(t, payload)
                    if replaced is not None:
                        out = replaced
                for f in out:
                    self._send(client, f)
                if t == 21:
                    break
            if self.hook.flip:
                # The server's first sealed packet (EXT_INFO, sent right after
                # its NEWKEYS): collect until 300 ms of quiet, client held.
                server.settimeout(0.3)
                try:
                    while True:
                        data = server.recv(65536)
                        if not data:
                            break
                        buf.extend(data)
                except socket.timeout:
                    pass
                server.settimeout(30)
                if buf:
                    buf[-1] ^= 0x01
                    self.events.append(("flip", len(buf)))
                self._send(client, bytes(buf))
                buf.clear()
                self.hold_client.set()
            if buf:
                self._send(client, bytes(buf))
                buf.clear()
            while True:
                data = server.recv(65536)
                if not data:
                    break
                self._send(client, data)
        except (EOFError, OSError):
            pass
        finally:
            self.hold_client.set()
            try:
                client.shutdown(socket.SHUT_WR)
            except OSError:
                pass


class FakeServer:
    """A loopback listener that sends `script` bytes to the first client and
    records what it sends back, for version-exchange rows with no sshd."""

    def __init__(self, script):
        self.script = script
        self.got = bytearray()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        try:
            self.listener.close()
        except OSError:
            pass
        self.thread.join(timeout=10)

    def _serve(self):
        self.listener.settimeout(30)
        try:
            c, _ = self.listener.accept()
        except OSError:
            return
        c.settimeout(5)
        try:
            c.sendall(self.script)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                data = c.recv(65536)
                if not data:
                    break
                self.got += data
        except OSError:
            pass
        finally:
            c.close()


def plaintext_packets(stream):
    """The version line and the plaintext packets at the front of a
    recorded stream, up to and including the first NEWKEYS: a list of
    (packet_length, padding_length, payload)."""
    end = stream.index(b"\n") + 1
    line = bytes(stream[:end])
    at = end
    out = []
    while at + 5 <= len(stream):
        n = struct.unpack(">I", stream[at:at + 4])[0]
        if at + 4 + n > len(stream):
            break
        padlen = stream[at + 4]
        payload = bytes(stream[at + 5:at + 4 + n - padlen])
        out.append((n, padlen, payload))
        at += 4 + n
        if payload[:1] == b"\x15":
            break
    return line, out
