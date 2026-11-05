"""oraclelib — the pinned OpenSSH as a black box, for burrow's rows.

Every row makes its own run directory (keys generated for that run), starts
its own `sshd` on a loopback port it binds, and stops it. Nothing here
contacts a host other than 127.0.0.1, and no private key leaves the run
directory: rows print fingerprints, never key material.

    with oraclelib.Sshd(run_dir, extra_config=["RekeyLimit 32K"]) as s:
        s.port, s.host_pub("ed25519"), s.log_text()
"""
import os
import pathlib
import shutil
import socket
import subprocess
import time
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PIN = tomllib.loads((ROOT / "burrow-oracle.toml").read_text())["oracle"]
PREFIX = pathlib.Path(PIN["prefix"])
SSH = PREFIX / "bin" / "ssh"
SSHD = PREFIX / "sbin" / "sshd"
KEYGEN = PREFIX / "bin" / "ssh-keygen"
HOST_KEY_TYPES = ("ed25519", "ecdsa", "rsa")


def require_oracle():
    """The pinned binaries, or a named refusal (a row never runs without them)."""
    for p in (SSH, SSHD, KEYGEN):
        if not p.exists():
            raise SystemExit(f"oraclelib: no oracle at {p}: run tools/in-container tools/fetch-oracle")
    if not (ROOT / ".oracle" / "STAMP").exists():
        raise SystemExit("oraclelib: .oracle/STAMP is missing: the oracle was not verified by tools/fetch-oracle")


def free_port():
    """A loopback port this row owns: bound by the kernel's choice, then released for sshd."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def keygen(path, kind, comment="burrow-row"):
    """A fresh key pair at `path` (no passphrase), made by the pinned ssh-keygen."""
    args = [str(KEYGEN), "-q", "-t", kind, "-N", "", "-C", comment, "-f", str(path)]
    if kind == "rsa":
        args[4:4] = ["-b", "3072"]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)
    return pathlib.Path(str(path) + ".pub")


def fingerprint(pub):
    """`ssh-keygen -l`'s SHA256 fingerprint of a public key file."""
    out = subprocess.run([str(KEYGEN), "-l", "-E", "sha256", "-f", str(pub)], check=True,
                         capture_output=True, text=True).stdout.split()
    return out[1]


class Sshd:
    """One `sshd -D -e` on 127.0.0.1:<port>, its config and keys under `run_dir`."""

    def __init__(self, run_dir, extra_config=(), host_keys=HOST_KEY_TYPES, port=None, log_level="DEBUG3"):
        self.dir = pathlib.Path(run_dir)
        self.extra = list(extra_config)
        self.kinds = list(host_keys)
        self.port = port or free_port()
        self.level = log_level
        self.proc = None

    def __enter__(self):
        require_oracle()
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        os.chmod(self.dir, 0o700)
        for kind in self.kinds:
            keygen(self.dir / f"host_{kind}", kind, comment=f"burrow-row-host-{kind}")
        lines = [
            f"ListenAddress 127.0.0.1:{self.port}",
            f"PidFile {self.dir / 'sshd.pid'}",
            f"LogLevel {self.level}",
            "UsePAM no",
            "PasswordAuthentication no",
            "KbdInteractiveAuthentication no",
            f"AuthorizedKeysFile {self.dir / 'authorized_keys'}",
            "StrictModes no",
        ] + [f"HostKey {self.dir / ('host_' + k)}" for k in self.kinds] + self.extra
        (self.dir / "sshd_config").write_text("\n".join(lines) + "\n")
        (self.dir / "authorized_keys").write_text("")
        self.log = open(self.dir / "sshd.log", "wb")
        self.proc = subprocess.Popen([str(SSHD), "-D", "-e", "-f", str(self.dir / "sshd_config")],
                                     stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise SystemExit(f"oraclelib: sshd exited {self.proc.returncode}: {self.log_text()[-2000:]}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5) as c:
                    c.recv(64)
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise SystemExit("oraclelib: sshd did not listen within 15 s")
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

    def host_pub(self, kind="ed25519"):
        return self.dir / f"host_{kind}.pub"

    def known_hosts_line(self, kind="ed25519"):
        """A known_hosts line for this sshd's `kind` host key, in the
        `[127.0.0.1]:port` form a non-22 port takes."""
        algo, blob = self.host_pub(kind).read_text().split()[:2]
        return f"[127.0.0.1]:{self.port} {algo} {blob}\n"

    def log_text(self):
        try:
            self.log.flush()
        except ValueError:
            pass
        return (self.dir / "sshd.log").read_bytes().decode("utf-8", "replace")
