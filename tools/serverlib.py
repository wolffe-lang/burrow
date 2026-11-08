"""serverlib — burrowd and the pinned sshd side by side, for burrow's server rows.

Each pair shares one per-run Ed25519 host key (sshd given that key alone),
one account (`burrowtest`) with one authorized_keys in its own ~/.ssh under
StrictModes, and equivalent configurations; the pinned ssh is run against
both with the same arguments. Every server binds 127.0.0.1 on a port the
row owns; nothing listens anywhere else. No private key leaves the run
directory: rows print fingerprints and public lines only.

    with serverlib.Pair(run_dir, sshd=[...], burrowd=[...]) as p:
        rb, rs = p.both(["true"])          # (rc, stdout, stderr) each
"""
import os
import pathlib
import pwd
import shutil
import socket
import subprocess
import threading
import time

import oraclelib

ROOT = oraclelib.ROOT
SSH, SSHD, KEYGEN = str(oraclelib.SSH), str(oraclelib.SSHD), str(oraclelib.KEYGEN)
USER = "burrowtest"
PREAUTH = "burrowd"

# What both servers are given unless a row says otherwise: the same
# features, each in its own words. sshd takes the first value it reads, so
# a row's own lines go first and win.
SSHD_BASE = ["AuthorizedKeysFile .ssh/authorized_keys", "StrictModes yes", "PermitRootLogin no",
             "AcceptEnv GIT_PROTOCOL", "PermitTTY no", "X11Forwarding no", "AllowAgentForwarding no",
             "DisableForwarding yes", "HostKeyAlgorithms ssh-ed25519"]
BURROWD_BASE = ["AcceptEnv GIT_PROTOCOL"]


def run(argv, inp=None, env=None, timeout=120, stdin=None):
    """(returncode, stdout, stderr) of argv."""
    p = subprocess.Popen(argv, stdin=stdin if stdin is not None else (subprocess.PIPE if inp is not None else subprocess.DEVNULL),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        out, err = p.communicate(inp, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return (-999, out, err + b"\n[row: timed out]")
    return (p.returncode, out, err)


def ensure_accounts():
    """The unprivileged account burrowd's worker runs as, made in this
    container if absent (the container is the row's own)."""
    try:
        pwd.getpwnam(PREAUTH)
    except KeyError:
        subprocess.run(["useradd", "-r", "-d", "/nonexistent", "-s", "/usr/sbin/nologin", PREAUTH], check=True)


def keygen(path, comment="row"):
    subprocess.run([KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(path)], check=True,
                   stdout=subprocess.DEVNULL)
    return pathlib.Path(str(path) + ".pub")


def account(name=USER):
    return pwd.getpwnam(name)


def install_keys(lines, user=USER, home_mode=0o750, dir_mode=0o700, file_mode=0o600, file_owner=None):
    """The account's ~/.ssh/authorized_keys holding `lines`, with the given
    modes; owned by the account unless `file_owner` (a uid) says otherwise."""
    a = account(user)
    home = pathlib.Path(a.pw_dir)
    home.mkdir(exist_ok=True)
    os.chown(home, a.pw_uid, a.pw_gid)
    os.chmod(home, home_mode)
    d = home / ".ssh"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir()
    os.chown(d, a.pw_uid, a.pw_gid)
    os.chmod(d, dir_mode)
    f = d / "authorized_keys"
    f.write_text("".join(lines))
    os.chown(f, file_owner if file_owner is not None else a.pw_uid, a.pw_gid)
    os.chmod(f, file_mode)
    return f


def free_port():
    return oraclelib.free_port()


class Burrowd:
    """One `burrowd -D -e` on 127.0.0.1:<port>, its config under `run_dir`."""

    def __init__(self, binary, run_dir, host_key, config=(), port=None):
        self.bin = str(binary)
        self.dir = pathlib.Path(run_dir)
        self.key = str(host_key)
        self.config = list(config)
        self.port = port or free_port()
        self.proc = None
        self.skip = 0

    def __enter__(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o711)
        lines = self.config + BURROWD_BASE + ["ListenAddress 127.0.0.1", f"Port {self.port}", f"HostKey {self.key}"]
        (self.dir / "burrowd_config").write_text("\n".join(lines) + "\n")
        self.log = open(self.dir / "burrowd.log", "wb")
        self.proc = subprocess.Popen([self.bin, "-D", "-e", "-f", str(self.dir / "burrowd_config")],
                                     stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"burrowd exited {self.proc.returncode}: {self.log_text()[-2000:]}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5) as c:
                    c.settimeout(2)
                    c.recv(64)
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("burrowd did not listen within 15 s")
        # The probe above is a connection too, logged when its monitor ends:
        # wait for its line, then leave it out of conn_lines.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not self._lines():
            time.sleep(0.05)
        self.skip = len(self._lines())
        return self

    def __exit__(self, *exc):
        self.stop()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if not self.log.closed:
            self.log.close()

    def log_text(self):
        try:
            self.log.flush()
        except ValueError:
            pass
        return (self.dir / "burrowd.log").read_bytes().decode("utf-8", "replace")

    def _lines(self):
        return [x for x in self.log_text().splitlines() if " from " in x]

    def conn_lines(self, settle=3.0):
        """The per-connection log lines (` from `) after the readiness
        probe's, once the monitors have written them."""
        deadline = time.monotonic() + settle
        while True:
            got = self._lines()[self.skip:]
            if got or time.monotonic() > deadline:
                return got
            time.sleep(0.1)


class Pair:
    """The pinned sshd and burrowd with one host key, one account and one
    client key, and a known_hosts naming both."""

    def __init__(self, binary, run_dir, sshd=(), burrowd=(), keys=None, install=True):
        self.binary = binary
        self.dir = pathlib.Path(run_dir)
        self.sshd_extra = list(sshd)
        self.burrowd_extra = list(burrowd)
        self.keys = keys
        self.install = install

    def __enter__(self):
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        os.chmod(self.dir, 0o711)
        self.key = self.dir / "id_user"
        keygen(self.key)
        if self.install:
            install_keys(self.keys if self.keys is not None else [pathlib.Path(str(self.key) + ".pub").read_text()])
        self.sshd = oraclelib.Sshd(self.dir / "sshd", self.sshd_extra + SSHD_BASE, host_keys=("ed25519",),
                                   authorized=[str(self.key) + ".pub"])
        self.sshd.__enter__()
        self.burrowd = Burrowd(self.binary, self.dir / "burrowd", self.sshd.dir / "host_ed25519", self.burrowd_extra)
        try:
            self.burrowd.__enter__()
        except Exception:
            self.sshd.__exit__()
            raise
        line = self.sshd.known_hosts_line()
        self.kh = self.dir / "known_hosts"
        self.kh.write_text(line + line.replace(f"[127.0.0.1]:{self.sshd.port} ", f"[127.0.0.1]:{self.burrowd.port} "))
        return self

    def __exit__(self, *exc):
        self.burrowd.__exit__()
        self.sshd.__exit__()

    def env(self, extra=None):
        e = {"PATH": "/usr/bin:/bin", "HOME": str(self.dir), "USER": "root", "LC_ALL": "C"}
        e.update(extra or {})
        return e

    def ssh(self, port, args, user=USER, keys=None, opts=(), inp=None, env=None, timeout=120, stdin=None):
        argv = [SSH, "-F", "none", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o",
                f"UserKnownHostsFile={self.kh}", "-o", "StrictHostKeyChecking=yes"]
        for k in (keys if keys is not None else [self.key]):
            argv += ["-i", str(k)]
        argv += list(opts) + ["-p", str(port), "-l", user, "127.0.0.1"] + list(args)
        return run(argv, inp=inp, env=self.env(env), timeout=timeout, stdin=stdin)

    def both(self, args, **kw):
        """(burrowd's, sshd's) results for the same arguments, each with its
        own port written PORT in stderr."""
        rb = self.ssh(self.burrowd.port, args, **kw)
        rs = self.ssh(self.sshd.port, args, **kw)
        return norm(rb, self.burrowd.port), norm(rs, self.sshd.port)


def norm(r, port):
    return (r[0], r[1], r[2].replace(str(port).encode(), b"PORT").replace(b"\r\n", b"\n"))


class HoldRelay:
    """A loopback relay to `upstream` that forwards the server's bytes
    always and the client's until the client has sent `budget` bytes,
    then holds them (a client stalled mid-login, for the grace rows)."""

    def __init__(self, upstream, budget):
        self.upstream = upstream
        self.budget = budget
        self.ls = socket.socket()
        self.ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ls.bind(("127.0.0.1", 0))
        self.ls.listen(1)
        self.port = self.ls.getsockname()[1]
        self.stop = threading.Event()
        self.t = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *e):
        self.stop.set()
        self.ls.close()
        self.t.join(timeout=10)

    def _serve(self):
        self.ls.settimeout(30)
        try:
            c, _ = self.ls.accept()
        except OSError:
            return
        s = socket.create_connection(("127.0.0.1", self.upstream))
        sent = [0]

        def up():
            try:
                while not self.stop.is_set():
                    d = c.recv(65536)
                    if not d:
                        break
                    room = self.budget - sent[0]
                    if room > 0:
                        s.sendall(d[:room])
                        sent[0] += min(room, len(d))
            except OSError:
                pass

        threading.Thread(target=up, daemon=True).start()
        try:
            while True:
                d = s.recv(65536)
                if not d:
                    break
                c.sendall(d)
        except OSError:
            pass
        # shutdown first: a close alone neither sends the FIN nor wakes the
        # thread still reading the client.
        for x in (c, s):
            try:
                x.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                x.close()
            except OSError:
                pass
