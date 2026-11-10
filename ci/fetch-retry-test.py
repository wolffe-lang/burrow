#!/usr/bin/env python3
"""fetch-retry-test — ci/fetch-retry's rows, against a loopback HTTP server
and a local git repository (tl38). python3, curl and git only.

    python3 -I ci/fetch-retry-test.py

Each row prints `PASS Fn …` or `FAIL Fn …`; the exit is 1 when any row
failed. The pauses between tries are 0 s here (BURROW_FETCH_PAUSES), so
the rows hold the number of tries, the classes and the lines, not the
waits.

  F1   a URL that answers 200: one request, the bytes
  F2   503 twice, then 200: two retry lines, fetched on try 3
  F3   always 503: exit 3, the named failure, three requests, no file left
  F4   404: exit 4, one request, not retried
  F5   a closed port: exit 3, class connect
  F6   half a body, then a stall, under a 2 s limit: exit 3, class timeout
  F7   git: a pinned commit from a local repository
  F8   git: a repository URL that answers 503: exit 3, class HTTP 503
  F9   git: a commit the repository does not have: exit 4, one try
  F10  run: fails twice, then succeeds
  F11  run: always fails; outlives its limit: exit 3, classes exit 1, timeout
"""
import http.server
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
HELPER = ROOT / "ci" / "fetch-retry"
HITS = {}
LOCK = threading.Lock()
FAILED = []


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        key = path.split("/")[1]
        with LOCK:
            HITS[key] = HITS.get(key, 0) + 1
            n = HITS[key]
        if key == "ok" or (key == "flaky" and n > 2):
            body = f"{key}\n".encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif key in ("flaky", "down", "down.git"):
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif key == "stall":
            self.send_response(200)
            self.send_header("Content-Length", "100000")
            self.end_headers()
            self.wfile.write(b"x" * 10)
            self.wfile.flush()
            time.sleep(8)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


def row(name, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}", flush=True)
    if not ok:
        FAILED.append(name)


def helper(env, *args, cwd=None):
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, "-I", str(HELPER), *args], env=env, cwd=cwd,
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - t0


def git(env, *args, cwd=None):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.name=row", "-c", "user.email=row@example.invalid",
                           *args], env=env, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def hits(key):
    with LOCK:
        return HITS.get(key, 0)


def main():
    if not HELPER.exists():
        row("F0", False, f"{HELPER.relative_to(ROOT)} is missing")
        return 1
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    with tempfile.TemporaryDirectory(prefix="fetch-retry-test.") as tmp:
        tmp = pathlib.Path(tmp)
        (tmp / "home").mkdir()
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp / "home"), "LC_ALL": "C",
               "GIT_CONFIG_NOSYSTEM": "1", "BURROW_FETCH_PAUSES": "0 0", "TMPDIR": str(tmp)}

        out = tmp / "f1"
        rc, log, _ = helper(env, "url", f"{base}/ok", str(out))
        row("F1", rc == 0 and out.read_bytes() == b"ok\n" and hits("ok") == 1,
            f"(exit {rc}, {hits('ok')} request)")

        out = tmp / "f2"
        rc, log, _ = helper(env, "url", f"{base}/flaky", str(out))
        lines = [l for l in log.splitlines() if "failed (HTTP 503); again in 0 s" in l]
        row("F2", rc == 0 and out.exists() and out.read_bytes() == b"flaky\n" and len(lines) == 2
            and f"fetch-retry: {base}/flaky: try 1 of 3 failed (HTTP 503); again in 0 s" in log
            and f"fetch-retry: {base}/flaky: fetched on try 3 of 3" in log and hits("flaky") == 3,
            f"(exit {rc}, {len(lines)} retry lines, {hits('flaky')} requests)")

        out = tmp / "f3"
        rc, log, _ = helper(env, "url", f"{base}/down", str(out))
        want = f"FAIL fetch of {base}/down failed after 3 tries (last: HTTP 503)"
        row("F3", rc == 3 and want in log.splitlines() and hits("down") == 3 and not out.exists(),
            f"(exit {rc}, {hits('down')} requests, named: {want in log.splitlines()}, file left: {out.exists()})")

        out = tmp / "f4"
        rc, log, _ = helper(env, "url", f"{base}/missing", str(out))
        want = f"FAIL fetch of {base}/missing failed (HTTP 404), not retried"
        row("F4", rc == 4 and want in log.splitlines() and hits("missing") == 1 and not out.exists(),
            f"(exit {rc}, {hits('missing')} request, named: {want in log.splitlines()})")

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
        s.close()
        rc, log, _ = helper(env, "url", f"http://127.0.0.1:{closed}/x", str(tmp / "f5"))
        want = f"FAIL fetch of http://127.0.0.1:{closed}/x failed after 3 tries (last: connect)"
        row("F5", rc == 3 and want in log.splitlines(), f"(exit {rc}, named: {want in log.splitlines()})")

        rc, log, secs = helper(dict(env, BURROW_FETCH_MAX_TIME="2"), "url", f"{base}/stall", str(tmp / "f6"))
        want = f"FAIL fetch of {base}/stall failed after 3 tries (last: timeout)"
        row("F6", rc == 3 and want in log.splitlines() and hits("stall") == 3 and secs < 30,
            f"(exit {rc}, {hits('stall')} requests, {secs:.1f} s, named: {want in log.splitlines()})")

        repo = tmp / "repo"
        repo.mkdir()
        git(env, "init", "-q", cwd=repo)
        (repo / "file").write_text("pinned\n")
        git(env, "add", "file", cwd=repo)
        git(env, "commit", "-q", "-m", "pinned", cwd=repo)
        git(env, "config", "uploadpack.allowAnySHA1InWant", "true", cwd=repo)
        pin = git(env, "rev-parse", "HEAD", cwd=repo)
        dst = tmp / "dst"
        dst.mkdir()
        git(env, "init", "-q", cwd=dst)
        rc, log, _ = helper(env, "git", str(dst), repo.as_uri(), pin)
        got = subprocess.run(["git", "-C", str(dst), "rev-parse", "FETCH_HEAD"], env=env, capture_output=True,
                             text=True).stdout.strip()
        row("F7", rc == 0 and got == pin, f"(exit {rc}, FETCH_HEAD {got[:12]}, pin {pin[:12]})")

        rc, log, _ = helper(env, "git", str(dst), f"{base}/down.git", pin)
        want = f"FAIL fetch of {base}/down.git at {pin} failed after 3 tries (last: HTTP 503)"
        row("F8", rc == 3 and want in log.splitlines() and hits("down.git") == 3,
            f"(exit {rc}, {hits('down.git')} requests, named: {want in log.splitlines()})")

        absent = "0123456789abcdef0123456789abcdef01234567"
        rc, log, _ = helper(env, "git", str(dst), repo.as_uri(), absent)
        tries = log.count("not retried")
        row("F9", rc == 4 and "try 1 of 3" not in log and tries == 1 and f"FAIL fetch of {repo.as_uri()} at {absent} failed" in log,
            f"(exit {rc}, not retried: {tries == 1})")

        counter = tmp / "count"
        script = f'n=$(cat {counter} 2>/dev/null || echo 0); n=$((n + 1)); echo $n >{counter}; [ $n -ge 3 ]'
        rc, log, _ = helper(env, "run", "the counter", "--", "sh", "-c", script)
        row("F10", rc == 0 and "fetch-retry: the counter: succeeded on try 3 of 3" in log and counter.read_text().strip() == "3",
            f"(exit {rc}, tries {counter.read_text().strip()})")

        rc, log, _ = helper(env, "run", "a failure", "--", "false")
        want = "FAIL fetch of a failure failed after 3 tries (last: exit 1)"
        rc2, log2, secs = helper(dict(env, BURROW_FETCH_MAX_TIME="1"), "run", "a sleeper", "--", "sleep", "30")
        want2 = "FAIL fetch of a sleeper failed after 3 tries (last: timeout)"
        row("F11", rc == 3 and want in log.splitlines() and rc2 == 3 and want2 in log2.splitlines() and secs < 30,
            f"(exit {rc} and {rc2}, {secs:.1f} s, named: {want in log.splitlines()} {want2 in log2.splitlines()})")
    server.shutdown()
    print(f"fetch-retry-test: {11 - len(FAILED)} of 11 rows pass", flush=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
