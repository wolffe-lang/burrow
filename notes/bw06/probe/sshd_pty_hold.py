#!/usr/bin/env python3
"""sshd_pty_hold — bw06 phase 1, second round: what is left of a pty session's
background child after the pinned sshd ends the session.

    tools/in-container python3 -I notes/bw06/probe/sshd_pty_hold.py

The first round (sshd_pty.py) found no process of the account left after a
session whose background child ignored SIGHUP. This round looks from inside
the session and after it, and checks the method with a control that must
leave a process behind.
"""
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sshd_pty  # noqa: E402
from sshd_pty import Rig, run, show  # noqa: E402


def procs():
    out = subprocess.run(["ps", "-e", "-o", "pid=,user=,pgid=,sid=,tty=,stat=,comm="], capture_output=True, text=True).stdout
    return [l.split() for l in out.splitlines() if " burrowtest " in f" {l} " or "sleep" in l]


def sig_ign(pid):
    try:
        for l in pathlib.Path(f"/proc/{pid}/status").read_text().splitlines():
            if l.startswith("SigIgn:"):
                return l.split()[1]
    except OSError:
        return "gone"
    return "?"


def main():
    with Rig() as rig:
        inside = "(trap '' HUP; exec sleep 6) & sleep 0.3; ps -o pid=,pgid=,sid=,tty=,stat=,comm= -u burrowtest; grep SigIgn /proc/$!/status; echo started"
        for name, args, inp in (
            ("control-T-nohup", ["-T", "nohup sleep 4 >/dev/null 2>&1 </dev/null & echo started"], None),
            ("tt-hup-ignored-child", ["-tt", inside], None),
            ("tt-hup-ignored-child-detached-stdio", ["-tt", "(trap '' HUP; exec sleep 6) </dev/null >/dev/null 2>&1 & echo started"], None),
            ("tt-plain-child", ["-tt", "sleep 6 & sleep 0.3; echo started"], None),
            ("tt-setsid-child", ["-tt", "setsid sleep 6 & sleep 0.3; echo started"], None),
        ):
            t0 = time.monotonic()
            rc, out, err = run(rig, args, inp=inp)
            took = time.monotonic() - t0
            time.sleep(0.5)
            left = procs()
            extra = f"took {took:.1f} s; after 0.5 s: {left}"
            for p in left:
                if p and p[-1] == "sleep":
                    extra += f"; sleep {p[0]} SigIgn {sig_ign(p[0])}"
            show(name, rc, out, err, extra)
            time.sleep(6.5)
    print("END")


if __name__ == "__main__":
    main()
