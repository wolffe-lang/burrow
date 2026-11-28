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
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent

# Cleanup infrastructure, not a signal witness. Rescue remains cooperative.
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


def check_state(step, pid, expected, observed, condition=None):
    valid = observed == expected if condition is None else condition
    if not valid:
        raise AssertionError(f"step={step} pid={pid} expected={expected!r} observed={observed!r}")


def load_helper():
    spec = importlib.util.spec_from_file_location("localproc_live", ROOT / "tools" / "localproc.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def read_line(p, seconds=3, step="reply", expected=None):
    ready = bool(select.select([p.stdout], [], [], seconds)[0])
    if not ready:
        check_state(step, p.pid, f"reply within {seconds}s", {"ready": False, "returncode": p.poll()}, False)
    reply = p.stdout.readline()
    if expected is not None and reply != expected:
        rc = p.poll()
        observed = {"reply": reply, "returncode": rc}
        if rc is not None:
            observed["stderr"] = p.stderr.read().decode(errors="replace")
        elif p.stderr is not None and select.select([p.stderr], [], [], 0)[0]:
            observed["stderr_available"] = os.read(p.stderr.fileno(), 65536).decode(errors="replace")
        check_state(step, p.pid, expected, observed, False)
    return reply


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
    script = directory / "cleanup child.py"
    bootstrap = "import runpy\nrunpy.run_path(" + repr(str(ROOT / "tools" / "localproc.py")) + ", run_name='child_exec_report')['report_self']()\n"
    script.write_text(bootstrap + CHILD)
    events = []
    victim_owned = m.spawn_reported([sys.executable, "-I", str(script), str(release), "stubborn"],
                                    record=events.append, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=env)
    canary_owned = m.spawn_reported([sys.executable, "-I", str(script), str(canary_release), "canary"],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    victim, canary = victim_owned.proc, canary_owned.proc
    try:
        read_line(victim, step="start/victim", expected=b"FIXTURE_READY\n")
        read_line(canary, step="start/canary", expected=b"FIXTURE_READY\n")
        for owned in (victim_owned, canary_owned):
            try:
                report = owned.exec_report.get()
            except Exception as e:
                check_state("report read", owned.pid, "complete bound exec report", f"{type(e).__name__}: {e}", False)
            check_state("report read/ownership", owned.pid, (owned.pid, os.getpid()), (report.get("pid"), report.get("ppid")))
            check_state("report read/argv tail", owned.pid, owned.argv[1:], tuple(report["argv"][1:]))
        print("PASS local-exec-report-live (nonce-bound post-exec argv, including a script path with spaces)", flush=True)
        group = os.getpgrp()
        groups = (os.getpgid(victim.pid), os.getpgid(canary.pid), group)
        check_state("start/process groups", (victim.pid, canary.pid), (group, group, group), groups)
        real_deliver = m.deliver
        real_run = subprocess.run
        def guard_run(argv, **kwargs):
            if argv[0] == "/bin/kill":
                check_state("escalation/dispatch", victim.pid,
                            {"argc": 3, "signal": ("-TERM", "-KILL"), "target": str(victim.pid)}, argv,
                            len(argv) == 3 and argv[1] in ("-TERM", "-KILL") and argv[2] == str(victim.pid))
            elif argv[0] == "/bin/ps":
                check_state("escalation/inspection", victim.pid, ["-p", str(victim.pid)], argv[1:3])
            else:
                check_state("escalation/dispatcher program", victim.pid, ("/bin/kill", "/bin/ps"), argv, False)
            return real_run(argv, **kwargs)
        def guarded_deliver(pid, name):
            check_state("escalation/recorded target", victim.pid, {"type": "positive int", "pid": victim.pid},
                        {"type": type(pid).__name__, "pid": pid}, type(pid) is int and pid == victim.pid and pid > 0)
            check_state("escalation/signal", pid, ("TERM", "KILL"), name, name in ("TERM", "KILL"))
            real_deliver(pid, name)
        def blocked_group(*args):
            check_state("escalation/group guard", victim.pid, "no group invocation", args, False)
        with patch.object(m, "deliver", side_effect=guarded_deliver), \
             patch("subprocess.run", side_effect=guard_run), patch("os.killpg", side_effect=blocked_group):
            rc = victim_owned.stop(grace=0.1)
        check_state("escalation/result", victim.pid, (-9, -9), (rc, victim.returncode))
        identities = [e for e in events if e["event"] == "identity"]
        attempts = [e for e in events if e["event"] == "signal"]
        check_state("escalation/attempts", victim.pid, (2, ["TERM", "KILL"]),
                    (len(identities), [e["signal"] for e in attempts]))
        check_state("escalation/verified PIDs", victim.pid, {victim.pid}, {e["pid"] for e in identities + attempts})
        check_state("reap/victim", victim.pid, True, identity_gone(victim.pid))
        canary.stdin.write(b"ping\n")
        canary.stdin.flush()
        read_line(canary, step="canary/reply", expected=b"PONG\n")
        print("PASS local-cleanup-escalation (fresh identity before TERM and separate KILL)", flush=True)
        print("PASS local-cleanup-bystander (same-group canary answered after victim reaped)", flush=True)
    finally:
        release.touch()
        canary_release.touch()
        victim_owned.wait(timeout=10)
        canary_owned.wait(timeout=10)
        for p in (victim, canary):
            p.stdin.close()
            p.stdout.close()
            p.stderr.close()
    check_state("reap/final", (victim.pid, canary.pid), (True, True),
                (identity_gone(victim.pid), identity_gone(canary.pid)))


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
                   [sys.executable, "-I", str(directory / "cleanup child.py"), str(release), kind])
        before = fds()
        try:
            try:
                result = fn([], argv=command, timeout=0.25 if kind == "stubborn" else 3, lifecycle=events, report_client=True)
            except d["Fail"] as e:
                check_state(f"terminal/{kind}/result", os.getpid(), "normal must not fail", str(e), kind != "normal")
                wanted = "timed out" if kind == "stubborn" else "keeper"
                check_state(f"terminal/{kind}/failure reason", os.getpid(), f"Fail containing {wanted!r}", str(e), wanted in str(e))
            else:
                check_state(f"terminal/{kind}/exit", os.getpid(), ("normal", 3), (kind, result[0]))
            check_state(f"terminal/{kind}/descriptor receipt", os.getpid(), {"event": "fds-closed", "count": 0}, events[-1] if events else None)
            after = fds()
            check_state(f"terminal/{kind}/descriptor count", os.getpid(), before, after)
            starts = [e for e in events if e.get("event") == "launched"]
            waits = [e for e in events if e.get("event") == "reaped"]
            check_state(f"terminal/{kind}/launch and reap receipts", os.getpid(), "both nonempty",
                        {"starts": starts, "waits": waits}, bool(starts) and bool(waits))
            for e in starts:
                check_state(f"terminal/{kind}/reap {e['role']}", e["pid"], True, identity_gone(e["pid"]))
            if kind != "missing":
                client = [i for i,e in enumerate(events) if e.get("role") == "client" and e.get("event") == "reaped"]
                keeper = [i for i,e in enumerate(events) if e.get("role") == "keeper" and e.get("event") == "reaped"]
                check_state(f"terminal/{kind}/reap order", os.getpid(), "client receipt before keeper receipt",
                            {"client": client, "keeper": keeper}, bool(client) and bool(keeper) and client[0] < keeper[0])
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
            frames = traceback.extract_tb(e.__traceback__)
            site = frames[-2] if len(frames) > 1 and frames[-1].name == "check_state" else (frames[-1] if frames else None)
            location = f" at {Path(site.filename).name}:{site.lineno} ({site.name})" if site else ""
            print(f"FAIL local-live-lifecycle {type(e).__name__}: {e}{location}", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
