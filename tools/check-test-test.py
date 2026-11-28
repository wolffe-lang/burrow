#!/usr/bin/env python3
"""Exercise the real unit wrapper in a private, fake-toolchain checkout.

The fakes speak the pinned wolf-test/0 and conform-run protocol 1 shapes.
They never run wolf code, SSH, a login shell, or a signal operation.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
FILES = ["src/a_test.lu", "src/b_test.lu"]


def report():
    rows = []
    for f in FILES:
        rows += [{"event": "suite", "file": f, "schema": "wolf-test/0", "tests": 1},
                 {"detail": "exit(0)", "event": "test", "file": f, "name": "main",
                  "schema": "wolf-test/0", "status": "pass"}]
    rows.append({"event": "summary", "failed": 0, "filtered_out": 0, "native": 0,
                 "passed": 2, "rejected": 0, "schema": "wolf-test/0",
                 "stopped_early": False, "unsupported": 0})
    return rows


def observation():
    return {"commit": "3fc86f7", "diagnostics": [], "file": FILES[0], "impl": "wolfgang",
            "impl_version": "0.2.39", "phase_reached": "run", "protocol": 1,
            "seeded": False, "stdout_inline": "", "stdout_sha256": "0" * 64,
            "verdict": "exit(0)", "warnings": []}


def config(fallback=False):
    rows = report()
    if fallback:
        rows[1].update(detail="exit(0) [native]", native="step budget exhausted")
        rows[-1]["native"] = 1
    return {"rows": rows, "retry": json.dumps(observation()), "retry_rc": 0,
            "test_rc": 0, "native_rc": 0, "lupin_rc": 0, "hook_rc": 0}


FAKE = r'''#!/usr/bin/env python3
import json, pathlib, sys
p = pathlib.Path(__file__).resolve().parent
c = json.loads((p / "fixture.json").read_text())
a = sys.argv[1:]
kind = pathlib.Path(__file__).name
if a == ["--version"]:
    print(c[kind + "_version"])
    sys.exit(0)
with (p / "trace").open("a") as t:
    t.write(kind + " " + " ".join(a) + "\n")
if kind == "lupin":
    sys.exit(c["lupin_rc"])
if a[0] == "test":
    print(c.get("raw", "\n".join(json.dumps(r) for r in c["rows"])))
    sys.exit(c["test_rc"])
if a[0] == "conform-run":
    print(c["retry"])
    print("fixture retry stderr", file=sys.stderr)
    sys.exit(c["retry_rc"])
if a[0] == "build":
    out = pathlib.Path(a[a.index("-o") + 1])
    out.write_text("#!/bin/sh\nexit " + str(c["native_rc"]) + "\n")
    out.chmod(0o755)
    sys.exit(0)
sys.exit(88)
'''
HOOK = '''import json, pathlib, sys
p = pathlib.Path(__file__).resolve().parent.parent / ".wolf-bin"
with (p / "trace").open("a") as f:
    f.write("wrapper regression hook\\n")
sys.exit(json.loads((p / "fixture.json").read_text())["hook_rc"])
'''


def run_fixture(c):
    parent = ROOT / "target" / "unit-wrapper-fixtures"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as d:
        root = Path(d)
        (root / "tools").mkdir()
        (root / "src").mkdir()
        (root / "home").mkdir()
        (root / "tmp").mkdir()
        for f in FILES:
            (root / f).write_text("//! member: false\nfn main() {}\n")
        for name in ("check-test", "lib-toolchain.sh", "lib-toml.sh", "check-test-results.py"):
            source = ROOT / "tools" / name
            if source.exists():
                shutil.copyfile(source, root / "tools" / name)
        shutil.copyfile(ROOT / "wolf-toolchain.toml", root / "wolf-toolchain.toml")
        # Identity verification is still the real library. Only this throwaway
        # tree has fake programs and the fixture's empty runtime marker.
        pins = {}
        section = None
        for line in (root / "wolf-toolchain.toml").read_text().splitlines():
            if line.startswith("["):
                section = line.strip("[]")
            elif " = " in line:
                k, v = line.split(" = ", 1)
                if (section in ("wolf", "lupin") and k == "version_line") or (section == "std" and k == "rev"):
                    pins[section] = json.loads(v)
        c = copy.deepcopy(c)
        c.update(wolf_version=pins["wolf"], lupin_version=pins["lupin"])
        binpath = root / ".wolf-bin"
        (binpath / "std").mkdir(parents=True)
        (binpath / "std" / "STD-REV").write_text(pins["std"] + "\n")
        (binpath / "libwolf_rt.a").touch()
        (binpath / "fixture.json").write_text(json.dumps(c))
        for name in ("wolf", "lupin"):
            (binpath / name).write_text(FAKE)
            (binpath / name).chmod(0o755)
        (root / "tools" / "check-test-test.py").write_text(HOOK)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(root / "home"),
               "TMPDIR": str(root / "tmp"), "SHELL": "/bin/sh", "LC_ALL": "C"}
        p = subprocess.run(["/bin/sh", str(root / "tools" / "check-test")], cwd=root,
                           env=env, capture_output=True, text=True, timeout=20)
        trace = (binpath / "trace").read_text() if (binpath / "trace").exists() else ""
        return p.returncode, p.stdout + p.stderr, trace


def require(c, passed, trace=()):
    rc, output, calls = run_fixture(c)
    if (rc == 0) != passed or any(x not in calls for x in trace):
        raise AssertionError(f"exit {rc}, wanted {'pass' if passed else 'failure'}; trace {calls!r}; output {output[-1800:]!r}")


def positive():
    require(config(), True)
    require(config(True), True)


def unsupported():
    c = config(True)
    r = observation()
    r.update(verdict="unsupported", phase_reached="mem", stdout_inline=None, stdout_sha256=None)
    c["retry"] = json.dumps(r)
    require(c, False)


def retry_observation():
    for text in ("", "not JSON", json.dumps(observation()) + "\n{", json.dumps(observation()) + "\nnoise",
                 "[" + json.dumps(observation()) + "]", json.dumps(observation()) * 2,
                 json.dumps(observation())[:-1] + ',"verdict":"exit(1)"}'):
        c = config(True)
        c["retry"] = text
        require(c, False)
    for key, value in (("verdict", "exit(1)"), ("verdict", "exit(0) [native]"), ("phase_reached", "mem"),
                       ("file", FILES[1]), ("protocol", True), ("impl_version", "0.0.0"),
                       ("diagnostics", [{}]), ("impl", "other")):
        c = config(True)
        r = observation()
        r[key] = value
        c["retry"] = json.dumps(r)
        require(c, False)
    c = config(True)
    c["retry_rc"] = 1
    require(c, False)


def inventory():
    cases = []
    c = config()
    c["rows"] = c["rows"][:2] + [dict(c["rows"][-1], passed=1)]
    cases.append(c)
    c = config()
    c["rows"].insert(2, c["rows"][1])
    cases.append(c)
    c = config()
    c["rows"].pop()
    cases.append(c)
    for key, value in (("passed", 1), ("native", 1), ("filtered_out", 1), ("stopped_early", True), ("failed", False)):
        c = config()
        c["rows"][-1][key] = value
        cases.append(c)
    c = config()
    c["raw"] = "\n".join(json.dumps(r) for r in c["rows"]) + "\n{"
    cases.append(c)
    c = config()
    c["raw"] = "noise\n" + "\n".join(json.dumps(r) for r in c["rows"])
    cases.append(c)
    for idx, key, value in ((1, "schema", "other"), (0, "tests", 2), (1, "detail", "unknown"),
                            (1, "file", "src/unknown_test.lu"), (1, "name", "other")):
        c = config()
        c["rows"][idx][key] = value
        cases.append(c)
    for c in cases:
        require(c, False)


def independent():
    c = config(True)
    c["retry"] = json.dumps(dict(observation(), verdict="unsupported"))
    require(c, False, ("wolf build", "lupin run src/a_test.lu", "lupin run src/b_test.lu"))
    for key in ("native_rc", "lupin_rc", "test_rc"):
        c = config()
        c[key] = 1
        require(c, False)


def wired():
    c = config()
    c["hook_rc"] = 1
    require(c, False, ("wrapper regression hook",))


def main():
    failures = 0
    for name, fn in (("checked-positive-controls", positive),
                     ("checked-exit-zero-unsupported", unsupported),
                     ("checked-retry-observation", retry_observation),
                     ("checked-inventory", inventory),
                     ("checked-backends-independent", independent),
                     ("checked-wrapper-wired", wired)):
        try:
            fn()
            print("PASS " + name, flush=True)
        except Exception as e:
            failures += 1
            print(f"FAIL {name} {e}", flush=True)
    return min(failures, 100)


if __name__ == "__main__":
    sys.exit(main())
