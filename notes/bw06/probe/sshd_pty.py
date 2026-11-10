#!/usr/bin/env python3
"""sshd_pty — bw06 phase 1: what the pinned sshd does with a terminal, black box.

    tools/in-container python3 -I notes/bw06/probe/sshd_pty.py

The pinned ssh against the pinned sshd alone (no burrowd), as root in the
pinned container, the rows' account and per-run keys (tools/serverlib.py),
`PermitTTY yes`, `PrintMotd no` and `PrintLastLog no`. Each case prints one
`CASE <name>` block: the exit status, stdout and stderr as Python byte
literals (the pty's number written N), and what the case measured beside
them. Nothing here is a row: it is evidence for the prediction in
notes/bw06-the-terminal.md, and the rows to come are written from it.
"""
import fcntl
import os
import pathlib
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import oraclelib  # noqa: E402
import serverlib  # noqa: E402

WORK = ROOT / "target" / "bw06-probe"
BASE = ["PermitTTY yes", "PrintMotd no", "PrintLastLog no"]


def n(b):
    return re.sub(rb"/dev/pts/\d+", b"/dev/pts/N", b)


def show(name, rc, out, err, extra=""):
    print(f"CASE {name}")
    print(f"  exit {rc}")
    print(f"  stdout {n(out)!r}")
    print(f"  stderr {n(err)!r}")
    if extra:
        for line in extra.splitlines():
            print(f"  {line}")
    sys.stdout.flush()


class Rig:
    def __init__(self, extra=(), key_line_prefix=""):
        self.dir = WORK / f"sshd-{len(list(WORK.glob('sshd-*'))) if WORK.exists() else 0}"
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o711)
        self.key = self.dir / "id_user"
        if self.key.exists():
            self.key.unlink()
            pathlib.Path(str(self.key) + ".pub").unlink()
        serverlib.keygen(self.key)
        pub = pathlib.Path(str(self.key) + ".pub").read_text()
        serverlib.install_keys([key_line_prefix + pub])
        self.sshd = oraclelib.Sshd(self.dir / "sshd", list(extra) + BASE + serverlib.SSHD_BASE,
                                   host_keys=("ed25519",), authorized=[str(self.key) + ".pub"])

    def __enter__(self):
        self.sshd.__enter__()
        self.kh = self.dir / "known_hosts"
        self.kh.write_text(self.sshd.known_hosts_line())
        return self

    def __exit__(self, *e):
        self.sshd.__exit__()

    def argv(self, args, opts=()):
        return [serverlib.SSH, "-F", "none", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                "-o", f"UserKnownHostsFile={self.kh}", "-o", "StrictHostKeyChecking=yes", "-i", str(self.key)] + \
            list(opts) + ["-p", str(self.sshd.port), "-l", serverlib.USER, "127.0.0.1"] + list(args)

    def env(self, extra=None):
        e = {"PATH": "/usr/bin:/bin", "HOME": str(self.dir), "USER": "root", "LC_ALL": "C"}
        e.update(extra or {})
        return e


def set_winsize(fd, rows, cols):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def at_terminal(rig, args, steps, env=None, rows=40, cols=132, modes=None, timeout=30):
    """ssh with its stdin a pty of this probe's own (sized, its modes set),
    stdout and stderr pipes; `steps` is a list of (wait_for, action):
    once `wait_for` shows on stdout, `action(master, proc)` runs."""
    master, slave = pty.openpty()
    set_winsize(slave, rows, cols)
    if modes:
        modes(slave)
    proc = subprocess.Popen(rig.argv(args), stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=rig.env(env))
    os.close(slave)
    got = {proc.stdout.fileno(): b"", proc.stderr.fileno(): b""}
    live = set(got)
    i = 0
    deadline = time.monotonic() + timeout
    while live and time.monotonic() < deadline:
        for fd in select.select(sorted(live), [], [], 0.1)[0]:
            d = os.read(fd, 65536)
            if d:
                got[fd] += d
            else:
                live.discard(fd)
        if i < len(steps) and steps[i][0] in got[proc.stdout.fileno()]:
            steps[i][1](master, proc)
            i += 1
    if live:
        proc.kill()
        got[proc.stderr.fileno()] += b"\n[probe: timed out]"
    rc = proc.wait(timeout=10)
    os.close(master)
    return rc, got[proc.stdout.fileno()], got[proc.stderr.fileno()]


def typed(data, pause=0.0):
    def act(master, proc):
        if pause:
            time.sleep(pause)
        os.write(master, data)
    return act


def run(rig, args, inp=None, env=None, timeout=30):
    return serverlib.run(rig.argv(args), inp=inp, env=rig.env(env), timeout=timeout)


def account_procs():
    out = subprocess.run(["ps", "-u", serverlib.USER, "-o", "pid=,stat=,comm="], capture_output=True, text=True).stdout
    return [l.split(None, 2) for l in out.splitlines() if l.strip()]


def pts_names():
    return sorted(p.name for p in pathlib.Path("/dev/pts").iterdir() if p.name.isdigit())


def main():
    print(f"bw06 probe: {subprocess.run([serverlib.SSH, '-V'], capture_output=True, text=True).stderr.strip()}; "
          f"{os.uname().sysname} {os.uname().release}")
    script = 'tty; echo "TERM=${TERM-unset}"; echo "SSH_TTY=${SSH_TTY-unset}"; stty size; echo out; echo err >&2; exit 3'
    with Rig() as rig:
        for name, env in (("tt-command-no-TERM", None), ("tt-command-TERM-vt100", {"TERM": "vt100"})):
            rc, out, err = run(rig, ["-tt", script], env=env)
            show(name, rc, out, err)
        rc, out, err = run(rig, ["-T", script])
        show("T-command-no-pty", rc, out, err)
        log = rig.sshd.log_text()
        hits = [l for l in log.splitlines() if re.search(r"pty|tty|TERM|window|modes", l)]
        print("CASE sshd-log-pty-lines")
        for l in hits[:60]:
            print(f"  {n(l.encode()).decode()}")
        sys.stdout.flush()

        def odd_modes(fd):
            a = termios.tcgetattr(fd)
            a[6][termios.VINTR] = b"\x07"
            a[6][termios.VERASE] = b"\x08"
            a[0] &= ~termios.IXON
            termios.tcsetattr(fd, termios.TCSANOW, a)

        rc, out, err = at_terminal(rig, ["-tt", "stty size; stty -a; echo ready; read x; stty size"],
                                   [(b"ready", lambda m, p: (set_winsize(m, 50, 100), p.send_signal(signal.SIGWINCH))),
                                    (b"ready", typed(b"go\r", 0.5))], modes=odd_modes)
        show("tt-size-modes-window-change", rc, out, err)

        rc, out, err = at_terminal(rig, ["-tt", "trap 'echo caught INT; exit 7' INT; echo ready; while :; do sleep 1; done"],
                                   [(b"ready", typed(b"\x03", 0.3))])
        show("tt-ctrl-c-trap", rc, out, err)

        rc, out, err = at_terminal(rig, ["-tt", "echo ready; exec sleep 30"], [(b"ready", typed(b"\x03", 0.3))])
        show("tt-ctrl-c-exit-signal", rc, out, err)

        rc, out, err = at_terminal(rig, ["-tt", "stty size; stty raw -echo; k=$(dd bs=1 count=1 2>/dev/null); stty sane; printf 'key=%s\\n' \"$k\""],
                                   [(b"132", typed(b"q", 0.3))])
        show("tt-full-screen-key", rc, out, err)

        rc, out, err = at_terminal(rig, [], [(b"$ ", typed(b"tty; echo $0; exit 4\r", 0.3))])
        show("shell-at-terminal", rc, out, err)

        before = pts_names()
        t0 = time.monotonic()
        rc, out, err = run(rig, ["-tt", "tty; (trap '' HUP; sleep 5) & echo started"])
        took = time.monotonic() - t0
        time.sleep(0.5)
        procs = account_procs()
        after = pts_names()
        show("tt-background-holds-slave", rc, out, err,
             f"took {took:.1f} s; /dev/pts before {before}, after {after}; the account's processes after: {procs}")
        time.sleep(5)

        t0 = time.monotonic()
        rc, out, err = run(rig, ["-tt", "sleep 3 & echo started"])
        took = time.monotonic() - t0
        time.sleep(0.5)
        show("tt-background-no-trap", rc, out, err,
             f"took {took:.1f} s; the account's processes after: {account_procs()}")

        rc, out, err = run(rig, ["-tt", "seq 1 20000; exit 0"], timeout=60)
        show("tt-burst-before-exit", rc, out[-40:], err,
             f"{out.count(b'\\r\\n')} CRLF lines, last {out.rstrip().split(b'\\r\\n')[-1]!r}")

        t0 = time.monotonic()
        rc, out, err = run(rig, ["-tt", "cat; echo cat-ended"], inp=b"one\n", timeout=10)
        show("tt-client-eof", rc, out, err, f"took {time.monotonic() - t0:.1f} s")

        t0 = time.monotonic()
        rc, out, err = run(rig, ["-tt", "cat; echo cat-ended"], inp=b"one\n\x04", timeout=10)
        show("tt-client-ctrl-d-then-eof", rc, out, err, f"took {time.monotonic() - t0:.1f} s")

        rc, out, err = run(rig, ["-tt", "stty -a"])
        show("tt-default-modes-stdin-not-a-terminal", rc, out, err)

    for prefix in ("no-pty ", "restrict "):
        with Rig(key_line_prefix=prefix) as rig:
            rc, out, err = run(rig, ["-tt", "tty; exit 0"])
            show(f"key-{prefix.strip()}", rc, out, err)
    with Rig(key_line_prefix="restrict,pty ") as rig:
        rc, out, err = run(rig, ["-tt", "tty; exit 0"])
        show("key-restrict-pty", rc, out, err)
    with Rig(extra=["PermitTTY no"]) as rig:
        rc, out, err = run(rig, ["-tt", "tty; exit 0"])
        show("PermitTTY-no", rc, out, err)
    print("END")


if __name__ == "__main__":
    main()
