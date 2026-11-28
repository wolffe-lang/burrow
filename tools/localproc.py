#!/usr/bin/env python3
"""Owned-child lifecycle for local rows. Never signal a group or search by name."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys


class OwnershipError(RuntimeError):
    pass


def command_line(pid):
    """Read only the specified recorded child's command line."""
    if type(pid) is not int or pid <= 0:
        raise OwnershipError("not a positive child PID")
    if sys.platform.startswith("linux"):
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        if not raw or not raw.endswith(b"\0"):
            raise OwnershipError(f"PID {pid} has no live command line")
        return tuple(os.fsdecode(x) for x in raw[:-1].split(b"\0"))
    if sys.platform == "darwin":
        r = subprocess.run(["/bin/ps", "-p", str(pid), "-ww", "-o", "command="],
                           capture_output=True, text=True)
        if r.returncode or not r.stdout.strip():
            raise OwnershipError(f"PID {pid} has no live command line")
        return r.stdout.strip()
    raise OwnershipError("unsupported host for child command-line verification")


def feed(stream, data):
    """Do not leave an input writer open when its child closes the reader."""
    try:
        stream.write(data)
    finally:
        stream.close()


def deliver(pid, name):
    """Exactly one literal decimal PID and one signal in each command."""
    if type(pid) is not int or pid <= 0 or name not in ("TERM", "KILL"):
        raise OwnershipError("invalid individual signal invocation")
    r = subprocess.run(["/bin/kill", "-" + name, str(pid)], capture_output=True, text=True)
    if r.returncode:
        raise OwnershipError(f"individual {name} to PID {pid} failed: {r.stderr.strip()}")


class OwnedChild:
    def __init__(self, proc, record=None):
        if type(proc.pid) is not int or proc.pid <= 0 or not isinstance(proc.args, (list, tuple)) or not proc.args:
            raise OwnershipError("child needs a positive recorded PID and argv")
        self.proc = proc
        self.pid = proc.pid
        self.argv = tuple(os.fspath(x) for x in proc.args)
        self.record = record or (lambda event: None)
        self.record({"event": "launched", "pid": self.pid, "argv": self.argv})

    def signal(self, name):
        # A direct child not yet reaped cannot have its PID reused. Once poll
        # has reaped it, never inspect or signal that numeric PID again.
        if self.proc.poll() is not None:
            return
        try:
            actual = command_line(self.pid)
        except (OSError, OwnershipError):
            if self.proc.poll() is not None:
                return
            raise
        expected = " ".join(self.argv) if isinstance(actual, str) else self.argv
        if actual != expected:
            raise OwnershipError(f"PID {self.pid} command line differs from its launch record")
        self.record({"event": "identity", "pid": self.pid, "command": actual})
        self.record({"event": "signal", "pid": self.pid, "signal": name})
        try:
            deliver(self.pid, name)
        except OwnershipError:
            if self.proc.poll() is None:
                raise

    def wait(self, timeout=None):
        rc = self.proc.wait(timeout=timeout)
        self.record({"event": "reaped", "pid": self.pid, "rc": rc})
        return rc

    def stop(self, grace=2):
        self.signal("TERM")
        try:
            return self.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self.signal("KILL")
            return self.wait(timeout=grace)


def keeper(out_fd, go_fd, argv):
    """Keep the controlling terminal alive until its client is reaped."""
    def emit(event):
        data = json.dumps(event).encode() + b"\n"
        if len(data) > 65536:
            raise OwnershipError("oversize keeper receipt")
        os.write(out_fd, data)
    # This keeper is terminal infrastructure, not a signal witness. Its
    # child's exec restores caught INT/QUIT dispositions to the default.
    signal.signal(signal.SIGINT, lambda *args: None)
    signal.signal(signal.SIGQUIT, lambda *args: None)
    child = OwnedChild(subprocess.Popen(argv), emit)
    pending = b""
    try:
        while child.proc.poll() is None:
            if select.select([go_fd], [], [], 0.05)[0]:
                data = os.read(go_fd, 64)
                pending += data
                if data and pending not in (b"STOP\n", b"RELEASE\n") and any(
                        command.startswith(pending) for command in (b"STOP\n", b"RELEASE\n")):
                    continue
                if pending and pending not in (b"STOP\n", b"RELEASE\n"):
                    raise OwnershipError("unknown keeper control")
                if not data or pending in (b"STOP\n", b"RELEASE\n"):
                    child.stop()
                    break
        rc = child.wait()
        emit({"event": "exit", "pid": child.pid, "rc": rc, "reaped": True})
        # The parent reads termios while this session leader still exists.
        if b"RELEASE\n" not in pending:
            os.read(go_fd, 64)
        return 0
    except Exception as e:
        emit({"event": "error", "pid": child.pid, "reason": str(e)})
        try:
            child.stop()
        except Exception as cleanup:
            emit({"event": "error", "pid": child.pid, "reason": str(cleanup)})
        return 1
    finally:
        os.close(out_fd)
        os.close(go_fd)


def main():
    if len(sys.argv) < 6 or sys.argv[1] != "keeper" or sys.argv[4] != "--":
        return 64
    return keeper(int(sys.argv[2]), int(sys.argv[3]), sys.argv[5:])


if __name__ == "__main__":
    sys.exit(main())
