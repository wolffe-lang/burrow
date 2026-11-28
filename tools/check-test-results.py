#!/usr/bin/env python3
"""Validate the pinned compiler's complete unit and checked observations.

No compiler is invoked here. The shell wrapper retains each original stream
and runs native/lupin independently, including after a checked refusal.
"""
import hashlib
import json
from pathlib import Path
import sys


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"non-JSON numeric constant {value}")


def decode(text):
    value = json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
    require(type(value) is dict, "observation is not an object")
    return value


def integer(value):
    return type(value) is int and value >= 0


def suite(path, rc):
    require(rc == 0, f"wolf test exited {rc}; checked cells not verified")
    expected = {str(p) for p in Path("src").glob("*_test.lu")}
    require(bool(expected), "no test files discovered")
    # Parsing completes before any row is emitted: a valid prefix cannot hide
    # a malformed suffix or a second summary.
    records = [decode(line) for line in Path(path).read_text().splitlines() if line.strip()]
    suites, tests, summaries = {}, {}, []
    for i, r in enumerate(records):
        require(r.get("schema") == "wolf-test/0", "unexpected test schema")
        event = r.get("event")
        if event == "summary":
            summaries.append(r)
            require(i == len(records) - 1, "summary is not last")
            continue
        require(event in ("suite", "test"), f"unexpected event {event!r}")
        f = r.get("file")
        require(type(f) is str, "missing test filename")
        table = suites if event == "suite" else tests
        require(f not in table, f"duplicate {event} for {f}")
        table[f] = r
        if event == "suite":
            require(type(r.get("tests")) is int and r["tests"] == 1, f"unexpected suite count for {f}")
        else:
            require(f in suites, f"test before suite for {f}")
            require(r.get("name") == "main", f"unexpected test name for {f}")
    require(set(suites) == expected and set(tests) == expected, "test inventory differs from src/*_test.lu")
    require(len(summaries) == 1, "missing or duplicate summary")
    s = summaries[0]
    for k in ("passed", "failed", "rejected", "unsupported", "filtered_out", "native"):
        require(integer(s.get(k)), f"invalid summary {k}")
    require(s.get("stopped_early") is False and s["filtered_out"] == 0, "incomplete test run")
    counts = {"pass": 0, "fail": 0, "rejected": 0, "unsupported": 0}
    fallbacks = 0
    rows = []
    for f, r in sorted(tests.items()):
        status, detail = r.get("status"), r.get("detail")
        require(status in counts, f"unknown status for {f}")
        counts[status] += 1
        if status != "pass":
            rows.append((f, "fail", str(detail)))
        elif detail == "exit(0) [native]":
            require(type(r.get("native")) is str and bool(r["native"]), f"missing native-fallback reason for {f}")
            fallbacks += 1
            rows.append((f, "retry", r["native"]))
        else:
            require(detail == "exit(0)" and "native" not in r, f"not a checked pass for {f}")
            rows.append((f, "pass", detail))
    require([s[k] for k in ("passed", "failed", "rejected", "unsupported")] ==
            [counts[k] for k in ("pass", "fail", "rejected", "unsupported")], "summary disagrees with test rows")
    require(s["native"] == fallbacks, "native-fallback count disagrees with test rows")
    for f, verdict, detail in rows:
        print(f"{f}\t{verdict}\t{json.dumps(detail)}")
    print(f"summary\t{len(tests)}\t{fallbacks}")


def retry(path, rc, filename, version, revision):
    require(rc == 0, f"checked process exited {rc}")
    r = decode(Path(path).read_text())
    require(type(r.get("protocol")) is int and r["protocol"] == 1, "unexpected observation protocol")
    require(r.get("file") == filename, "checked observation names another file")
    require(r.get("impl") == "wolfgang" and r.get("impl_version") == version and
            r.get("commit") == revision[:7], "checked observation identity differs from pin")
    require(r.get("verdict") == "exit(0)" and r.get("phase_reached") == "run", f"not executed checked: {r.get('verdict')!r} at {r.get('phase_reached')!r}")
    require("native" not in r and not any(k.startswith("x-unsupported") for k in r), "fallback or unsupported metadata")
    require(r.get("diagnostics") == [] and r.get("warnings") == [] and r.get("seeded") is False,
            "unexpected diagnostics, warnings or seed mode")
    stdout, digest = r.get("stdout_inline"), r.get("stdout_sha256")
    require("stdout_inline" in r and "stdout_sha256" in r and
            ((stdout is None and digest is None) or
             (type(stdout) is str and digest == hashlib.sha256(stdout.encode()).hexdigest())),
            "missing or inconsistent executed stdout")
    print(f"PASS {filename} [checked retry] exit(0)")


def main():
    try:
        mode, path, rc, *args = sys.argv[1:]
        if mode == "suite":
            require(not args, "unexpected suite arguments")
            suite(path, int(rc))
        elif mode == "retry":
            retry(path, int(rc), *args)
        else:
            raise ValueError("unknown observation mode")
    except (ValueError, TypeError, KeyError, OSError) as e:
        mode = sys.argv[1] if len(sys.argv) > 1 else "suite"
        filename = sys.argv[4] if mode == "retry" and len(sys.argv) > 4 else "inventory"
        print(f"FAIL checked-{mode} {filename}: {e}; checked result UNMEASURED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
