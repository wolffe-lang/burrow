#!/usr/bin/env python3
"""Owned children, lossless argv verification and nonce-bound exec reports."""
import ctypes
import json
import os
from pathlib import Path
import secrets
import select
import signal
import struct
import subprocess
import sys
import time


class OwnershipError(RuntimeError):
    pass


def argv_vector(value):
    return isinstance(value, (tuple, list)) and bool(value) and all(type(x) is str for x in value) and bool(value[0])


def parse_darwin_argv(raw):
    """KERN_PROCARGS2: native int argc, exec path, NUL padding, argc strings.

    Stop at argc: the remaining environment is neither decoded nor returned.
    Empty tail arguments and embedded spaces remain distinct argv elements.
    """
    if len(raw) < 6:
        raise OwnershipError("short process-arguments result")
    argc = struct.unpack_from("=i", raw)[0]
    if not 1 <= argc <= 65536:
        raise OwnershipError("invalid process argc")
    end = raw.find(b"\0", 4)
    if end < 5:
        raise OwnershipError("missing process exec path")
    pos = end + 1
    while pos < len(raw) and raw[pos] == 0:
        pos += 1
    result = []
    for _ in range(argc):
        end = raw.find(b"\0", pos)
        if end < 0:
            raise OwnershipError("truncated process argv")
        result.append(os.fsdecode(raw[pos:end]))
        pos = end + 1
    if not argv_vector(result):
        raise OwnershipError("invalid process argv")
    return tuple(result)


def darwin_argv(pid):
    # Read the one requested PID through the Darwin sysctl ABI. No process
    # table enumeration and no lossy parsing of ps's display string.
    library = ctypes.CDLL(None, use_errno=True)
    query = library.sysctl
    query.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p,
                      ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
    query.restype = ctypes.c_int
    argmax = ctypes.c_int()
    size = ctypes.c_size_t(ctypes.sizeof(argmax))
    mib = (ctypes.c_int * 2)(1, 8)  # CTL_KERN, KERN_ARGMAX
    if query(mib, 2, ctypes.byref(argmax), ctypes.byref(size), None, 0) != 0 or not 0 < argmax.value <= 16 * 1024 * 1024:
        raise OwnershipError("cannot size Darwin process argv")
    capacity = argmax.value + 4096
    buf = ctypes.create_string_buffer(capacity)
    size = ctypes.c_size_t(capacity)
    mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2, exact PID
    if query(mib, 3, buf, ctypes.byref(size), None, 0) != 0 or size.value > capacity:
        raise OwnershipError(f"cannot read argv for PID {pid} (errno {ctypes.get_errno()})")
    return parse_darwin_argv(buf.raw[:size.value])


def command_line(pid):
    if type(pid) is not int or pid <= 0:
        raise OwnershipError("not a positive child PID")
    if sys.platform.startswith("linux"):
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        if not raw or not raw.endswith(b"\0"):
            raise OwnershipError(f"PID {pid} has no live command line")
        return tuple(os.fsdecode(x) for x in raw[:-1].split(b"\0"))
    if sys.platform == "darwin":
        return darwin_argv(pid)
    raise OwnershipError("unsupported host for child argv verification")


def parent_pid(pid):
    if type(pid) is not int or pid <= 0:
        raise OwnershipError("not a positive child PID")
    if sys.platform.startswith("linux"):
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    elif sys.platform == "darwin":
        r = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "ppid="], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            return int(r.stdout.strip())
    raise OwnershipError(f"cannot verify parent of PID {pid}")


def feed(stream, data):
    try:
        stream.write(data)
    finally:
        stream.close()


def deliver(pid, name):
    if type(pid) is not int or pid <= 0 or name not in ("TERM", "KILL"):
        raise OwnershipError("invalid individual signal invocation")
    r = subprocess.run(["/bin/kill", "-" + name, str(pid)], capture_output=True, text=True)
    if r.returncode:
        raise OwnershipError(f"individual {name} to PID {pid} failed: {r.stderr.strip()}")


class ExecReport:
    def __init__(self, fd, nonce, pid, parent):
        self.fd, self.nonce, self.pid, self.parent = fd, nonce, pid, parent
        self.value = None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def validate(self, data):
        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1 or \
                type(data.get("pid")) is not int or data["pid"] != self.pid or \
                type(data.get("ppid")) is not int or data["ppid"] != self.parent or not argv_vector(data.get("argv")):
            raise OwnershipError("exec report does not bind child, parent, nonce and argv")
        return data

    def get(self):
        if self.value is not None:
            return self.value
        deadline = time.monotonic() + 3
        def read_exact(n):
            result = b""
            while len(result) < n:
                left = deadline - time.monotonic()
                if left <= 0 or not select.select([self.fd], [], [], left)[0]:
                    raise OwnershipError("exec report timed out")
                part = os.read(self.fd, n - len(result))
                if not part:
                    raise OwnershipError("exec report ended early")
                result += part
            return result
        try:
            n = struct.unpack("!I", read_exact(4))[0]
            if not 0 < n <= 4096:
                raise OwnershipError("invalid exec-report frame length")
            value = self.validate(json.loads(read_exact(n)))
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.fd], [], [], left)[0] or os.read(self.fd, 1) != b"":
                raise OwnershipError("exec report did not end after its frame")
            self.value = value
            return self.value
        finally:
            self.close()


def report_self():
    """Called by cooperating code after its own exec, before doing row work."""
    fd_text = os.environ.pop("BURROW_LOCAL_REPORT_FD", None)
    nonce = os.environ.pop("BURROW_LOCAL_REPORT_NONCE", None)
    if fd_text is None and nonce is None:
        return
    fd = int(fd_text)
    try:
        data = json.dumps({"version": 1, "nonce": nonce, "pid": os.getpid(), "ppid": os.getppid(),
                           "argv": command_line(os.getpid())}, ensure_ascii=True).encode()
        if len(data) > 4096:
            raise OwnershipError("exec report is too large")
        pending = memoryview(struct.pack("!I", len(data)) + data)
        while pending:
            n = os.write(fd, pending)
            if n <= 0:
                raise OwnershipError("exec report write failed")
            pending = pending[n:]
    finally:
        os.close(fd)


def spawn_reported(argv, record=None, **kwargs):
    supplied_env = kwargs.pop("env", None)
    env = dict(os.environ if supplied_env is None else supplied_env)
    r, w = os.pipe()
    nonce = secrets.token_hex(16)
    env.update(BURROW_LOCAL_REPORT_FD=str(w), BURROW_LOCAL_REPORT_NONCE=nonce)
    inherited = tuple(kwargs.pop("pass_fds", ())) + (w,)
    try:
        p = subprocess.Popen(argv, env=env, pass_fds=inherited, **kwargs)
    except Exception:
        os.close(r)
        raise
    finally:
        os.close(w)
    return OwnedChild(p, record, ExecReport(r, nonce, p.pid, os.getpid()))


class OwnedChild:
    def __init__(self, proc, record=None, exec_report=None):
        if type(proc.pid) is not int or proc.pid <= 0 or not argv_vector(proc.args):
            raise OwnershipError("child needs a positive recorded PID and argv")
        self.proc, self.pid, self.parent = proc, proc.pid, os.getpid()
        self.argv = tuple(os.fspath(x) for x in proc.args)
        self.exec_report = exec_report
        self.record = record or (lambda event: None)
        self.record({"event": "launched", "pid": self.pid, "parent": self.parent, "argv": self.argv})

    def refusal(self, reason, index=None):
        # Keep the reader-facing failure concise; no full command/environment
        # dump now that the hosted framework mismatch has been established.
        data = {"event": "identity-refused", "pid": self.pid, "reason": reason}
        if index is not None:
            data["argument"] = index
        return OwnershipError(json.dumps(data, sort_keys=True))

    def signal(self, name):
        if self.proc.poll() is not None:
            return
        try:
            if parent_pid(self.pid) != self.parent:
                raise self.refusal("not the recorded direct child")
            actual = command_line(self.pid)
        except (OSError, OwnershipError):
            if self.proc.poll() is not None:
                return
            raise
        if not argv_vector(actual):
            raise self.refusal("lossless argv unavailable")
        if tuple(actual[1:]) != self.argv[1:]:
            index = next((i for i in range(1, min(len(actual), len(self.argv))) if actual[i] != self.argv[i]),
                         min(len(actual), len(self.argv)))
            raise self.refusal("argument tail differs", index)
        source = "launch"
        if actual[0] != self.argv[0]:
            if self.exec_report is None:
                raise self.refusal("executable differs without a child report", 0)
            data = self.exec_report.get()
            if data.get("pid") != self.pid or data.get("ppid") != self.parent or not argv_vector(data.get("argv")) or \
                    tuple(data["argv"][1:]) != self.argv[1:] or actual[0] != data["argv"][0]:
                raise self.refusal("post-exec report differs", 0)
            source = "child-report"
        self.record({"event": "identity", "pid": self.pid, "parent": self.parent,
                     "command": actual, "argv0_source": source})
        self.record({"event": "signal", "pid": self.pid, "signal": name})
        try:
            deliver(self.pid, name)
        except OwnershipError:
            if self.proc.poll() is None:
                raise

    def close_report(self):
        if self.exec_report is not None:
            self.exec_report.close()

    def wait(self, timeout=None):
        rc = self.proc.wait(timeout=timeout)
        self.close_report()
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
    def emit(event):
        data = json.dumps(event).encode() + b"\n"
        if len(data) > 65536:
            raise OwnershipError("oversize keeper receipt")
        os.write(out_fd, data)
    signal.signal(signal.SIGINT, lambda *args: None)
    signal.signal(signal.SIGQUIT, lambda *args: None)
    reported = os.environ.pop("BURROW_LOCAL_REPORT_CLIENT", "0") == "1"
    child = spawn_reported(argv, record=emit) if reported else OwnedChild(subprocess.Popen(argv), emit)
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
        child.close_report()
        os.close(out_fd)
        os.close(go_fd)


def main():
    report_self()
    if len(sys.argv) < 6 or sys.argv[1] != "keeper" or sys.argv[4] != "--":
        return 64
    return keeper(int(sys.argv[2]), int(sys.argv[3]), sys.argv[5:])


if __name__ == "__main__":
    sys.exit(main())
