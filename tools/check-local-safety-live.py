#!/usr/bin/env python3
"""Focused real owned-child proofs, without SSH or a login shell."""
import importlib.util
import json
import os
from pathlib import Path
import runpy
import select
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent

# This is cleanup test infrastructure, not a signal witness. Cooperative
# release and a finite deadline keep an independently rescued fixture bounded.
CHILD = r'''
import os, pathlib, select, signal, sys, time
release = pathlib.Path(sys.argv[1])
if sys.argv[2] == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("FIXTURE_READY", flush=True)
if sys.argv[2] == "normal":
    sys.exit(3)
end = time.monotonic() + 8
while time.monotonic() < end and not release.exists():
    if select.select([0], [], [], 0.02)[0]:
        s = os.read(0, 64)
        if s == b"ping\n":
            print("PONG", flush=True)
        if not s:
            time.sleep(0.02)
'''


def load_helper():
    spec = importlib.util.spec_from_file_location("localproc_live", ROOT / "tools" / "localproc.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def read_line(p, seconds=3):
    if not select.select([p.stdout], [], [], seconds)[0]:
        raise AssertionError("fixture did not answer")
    return p.stdout.readline()


def fds():
    path = "/proc/self/fd" if sys.platform.startswith("linux") else "/dev/fd"
    return len(os.listdir(path))


def identity_gone(pid):
    if sys.platform.startswith("linux"):
        return not Path(f"/proc/{pid}").exists()
    return not subprocess.run(["/bin/ps", "-p", str(pid), "-o", "pid="], capture_output=True, text=True).stdout.strip()


def escalation_and_bystander(directory):
    m = load_helper()
    release = directory / "release-stubborn"
    canary_release = directory / "release-canary"
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(directory), "SHELL": "/bin/sh"}
    script = directory / "cleanup-child.py"
    script.write_text(CHILD)
    victim = subprocess.Popen([sys.executable, "-I", str(script), str(release), "stubborn"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    canary = subprocess.Popen([sys.executable, "-I", str(script), str(canary_release), "canary"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    events = []
    try:
        assert read_line(victim) == b"FIXTURE_READY\n"
        assert read_line(canary) == b"FIXTURE_READY\n"
        assert os.getpgid(victim.pid) == os.getpgid(canary.pid) == os.getpgrp()
        real_deliver = m.deliver
        def guarded_deliver(pid, name):
            assert type(pid) is int and pid == victim.pid and pid > 0
            assert name in ("TERM", "KILL")
            real_deliver(pid, name)
        with patch.object(m, "deliver", side_effect=guarded_deliver), patch("os.killpg", side_effect=AssertionError("forbidden group signal")):
            rc = m.OwnedChild(victim, record=events.append).stop(grace=0.1)
        assert rc == -9 and victim.returncode == -9
        identities = [e for e in events if e["event"] == "identity"]
        attempts = [e for e in events if e["event"] == "signal"]
        assert len(identities) == 2 and [e["signal"] for e in attempts] == ["TERM", "KILL"]
        assert all(e["pid"] == victim.pid for e in identities + attempts)
        assert identity_gone(victim.pid)
        canary.stdin.write(b"ping\n")
        canary.stdin.flush()
        assert read_line(canary) == b"PONG\n", "bystander stopped answering"
        print("PASS local-cleanup-escalation (fresh identity before TERM and separate KILL)", flush=True)
        print("PASS local-cleanup-bystander (same-group canary answered after victim reaped)", flush=True)
    finally:
        # Rescue is independent and cooperative, never the dispatcher under test.
        release.touch()
        canary_release.touch()
        victim.wait(timeout=10)
        canary.wait(timeout=10)
        for p in (victim, canary):
            p.stdin.close()
            p.stdout.close()
            p.stderr.close()
    assert identity_gone(victim.pid) and identity_gone(canary.pid)


def terminal_lifecycle(directory):
    d = runpy.run_path(str(ROOT / "tools" / "check-server-local"), run_name="local_live_import")
    fn = d["on_terminal"]
    class Fixture:
        lifecycle = []
        def env(self, extra=None):
            e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(directory), "SHELL": "/bin/sh", "LC_ALL": "C"}
            e.update(extra or {})
            return e
    fn.__globals__["L"] = Fixture()
    for kind in ("normal", "stubborn", "missing"):
        events = []
        release = directory / ("release-terminal-" + kind)
        command = ([str(directory / "missing-program")] if kind == "missing" else
                   [sys.executable, "-I", str(directory / "cleanup-child.py"), str(release), kind])
        before = fds()
        try:
            try:
                result = fn([], argv=command, timeout=0.25 if kind == "stubborn" else 3, lifecycle=events)
            except d["Fail"] as e:
                assert kind != "normal", str(e)
                assert "timed out" in str(e) if kind == "stubborn" else "keeper" in str(e)
            else:
                assert kind == "normal" and result[0] == 3
            assert events[-1] == {"event": "fds-closed", "count": 0}
            assert fds() == before, "terminal descriptors leaked"
            starts = [e for e in events if e.get("event") == "launched"]
            waits = [e for e in events if e.get("event") == "reaped"]
            assert starts and waits
            for e in starts:
                assert identity_gone(e["pid"]), f"recorded {e['role']} PID {e['pid']} survived"
            if kind != "missing":
                client_wait = next(i for i,e in enumerate(events) if e.get("role") == "client" and e.get("event") == "reaped")
                keeper_wait = next(i for i,e in enumerate(events) if e.get("role") == "keeper" and e.get("event") == "reaped")
                assert client_wait < keeper_wait, "keeper exited before client reap acknowledgement"
            print(f"PASS local-terminal-{kind} (recorded children reaped, descriptors closed)", flush=True)
        finally:
            release.touch()
        (directory / (kind + "-events.json")).write_text(json.dumps(events, indent=2))


def main():
    safety = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "check-local-safety.py")])
    if safety.returncode:
        return safety.returncode
    parent = ROOT / "target"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="local-lifecycle-", dir=parent) as tmp:
        p = Path(tmp)
        try:
            escalation_and_bystander(p)
            terminal_lifecycle(p)
        except Exception as e:
            print(f"FAIL local-live-lifecycle {type(e).__name__}: {e}", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
