#!/usr/bin/env python3
"""Local terminal safety regressions; no SSH or user shell is started here."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


class SafeCapture(Exception):
    pass


def load_tool():
    return runpy.run_path(str(ROOT / "tools" / "check-server-local"), run_name="local_safety_import")


def helper():
    path = ROOT / "tools" / "localproc.py"
    assert path.exists(), "owned-child dispatcher is missing"
    spec = importlib.util.spec_from_file_location("localproc_safety", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def no_groups():
    for name in ("check-server-local", "localproc.py"):
        path = ROOT / "tools" / name
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in ("killpg", "killall"), f"forbidden group/name dispatcher in {name}:{node.lineno}"
    m = helper()
    calls = []
    class Process:
        pid = 123
        args = ["/fixture/client", "nonce"]
        returncode = None
        def poll(self): return self.returncode
    p = Process()
    child = m.OwnedChild(p, record=calls.append)
    with patch.object(m, "command_line", return_value=tuple(p.args)), patch.object(m, "deliver", side_effect=lambda pid, sig: calls.append((pid, sig))):
        child.signal("TERM")
        child.signal("KILL")
    assert [x for x in calls if isinstance(x, tuple)] == [(123, "TERM"), (123, "KILL")]
    assert len([x for x in calls if isinstance(x, dict) and x.get("event") == "identity"]) == 2


def identities():
    m = helper()
    class Process:
        pid = 123
        args = ["/fixture/client", "nonce"]
        returncode = None
        def poll(self): return self.returncode
    for pid in (0, -1, 123):
        p = Process()
        p.pid = pid
        delivered = []
        try:
            child = m.OwnedChild(p)
            with patch.object(m, "command_line", return_value=("/not-the-child",)), patch.object(m, "deliver", side_effect=lambda *x: delivered.append(x)):
                child.signal("TERM")
        except (m.OwnershipError, ValueError):
            pass
        else:
            raise AssertionError("invalid ownership was accepted")
        assert not delivered
    p = Process()
    p.returncode = 0
    with patch.object(m, "command_line", side_effect=AssertionError("read exited child")), patch.object(m, "deliver", side_effect=AssertionError("signalled exited child")):
        m.OwnedChild(p).signal("TERM")


def reaps():
    m = helper()
    events = []
    class Process:
        pid = 123
        args = ["/fixture/client", "nonce"]
        returncode = None
        waits = 0
        def poll(self): return self.returncode
        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired(self.args, timeout)
            self.returncode = -9
            return self.returncode
    p = Process()
    with patch.object(m, "command_line", return_value=tuple(p.args)), patch.object(m, "deliver", side_effect=lambda pid, sig: events.append((pid, sig))):
        rc = m.OwnedChild(p, record=events.append).stop(grace=0.01)
    assert rc == -9 and p.waits == 2
    assert [x for x in events if isinstance(x, tuple)] == [(123, "TERM"), (123, "KILL")]
    assert any(isinstance(x, dict) and x.get("event") == "reaped" for x in events), "no wait/reap receipt"


def capture_signal(which, tty=b"/dev/ttyfixture"):
    d = load_tool()
    fn = d[which]
    g = fn.__globals__
    class FakeLocal:
        port = 12345
        user = "fixture"
        home = Path("/fixture/home")
        probe = Path("/fixture/local-signal-probe")
        lifecycle = []
        def ssh(self, args, **kwargs):
            raise AssertionError("script signal witness: " + repr(args))
        def lines(self): return ["fixture signal INT"]
    g["L"] = FakeLocal()
    def terminal(args, **kwargs):
        text = " ".join(args)
        assert "trap " not in text and "kill " not in text and "kill -" not in text, "script signal witness: " + text
        if "local-signal-probe" in text:
            raise SafeCapture()
        return 3, tty + b"\r\n40 132\r\nready\r\n50 100\r\n", [], []
    g["on_terminal"] = terminal
    g["restored"] = lambda *a: None
    g["signal_probe_command"] = lambda *a: "exec /fixture/local-signal-probe nonce"
    with patch("os.path.exists", return_value=True), patch("subprocess.run", return_value=SimpleNamespace(stderr="OpenSSH_fixture", stdout="", returncode=0)):
        try:
            fn()
        except SafeCapture:
            return
    raise AssertionError("no probe command was captured")


def keeper_protocol():
    m = helper()
    class Process:
        pid = 123
        args = ["/fixture/client"]
        returncode = None
        def poll(self): return self.returncode
        def wait(self, timeout=None):
            self.returncode = -15
            return self.returncode
    p = Process()
    events = []
    reads = []
    def read(fd, count):
        reads.append(fd)
        assert len(reads) == 1, "unknown control was ignored"
        return b"NOT-A-COMMAND\n"
    def write(fd, data):
        events.append(json.loads(data))
        return len(data)
    with patch.object(m.subprocess, "Popen", return_value=p), \
         patch.object(m.signal, "signal"), patch.object(m.select, "select", return_value=([7], [], [])), \
         patch.object(m.os, "read", side_effect=read), patch.object(m.os, "write", side_effect=write), \
         patch.object(m.os, "close"), patch.object(m, "command_line", return_value=tuple(p.args)), \
         patch.object(m, "deliver"):
        rc = m.keeper(8, 7, p.args)
    assert rc == 1 and any(e.get("event") == "error" and "unknown keeper control" in e.get("reason", "") for e in events)
    assert all(e.get("pid") == 123 for e in events)


def main():
    failed = 0
    rows = (("local-cleanup-single-pid", no_groups),
            ("local-cleanup-identity", identities),
            ("local-cleanup-reaps", reaps),
            ("local-signal-no-script", lambda: capture_signal("local_signal")),
            ("local-tty-no-trap", lambda: capture_signal("local_tty")),
            ("local-tty-paths", lambda: capture_signal("local_tty", b"/dev/pts/17")),
            ("local-keeper-protocol", keeper_protocol))
    for name, fn in rows:
        try:
            fn()
            print("PASS " + name, flush=True)
        except Exception as e:
            failed += 1
            print(f"FAIL {name} {type(e).__name__}: {e}", flush=True)
    return min(failed, 100)


if __name__ == "__main__":
    sys.exit(main())
