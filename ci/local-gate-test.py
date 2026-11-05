#!/usr/bin/env python3
# Adapted from wolffe-lang/scent eb888dfc ci/local-gate-test.py; own code.
"""Prediction: PRs are cheap without an opt-in label; opt-ins keep the full
set, module pushes run nothing, and shared-path pushes run full CI. Explicit
publication/deployment exceptions keep their original push/job bytes. Every
original command, matrix, budget and nightly/release check is preserved.
"""
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "ci/local-gate-baseline.json").read_text())
GATE = "github.event_name != 'pull_request' || contains(github.event.pull_request.labels.*.name, 'full-matrix') || contains(github.event.pull_request.labels.*.name, 'ci') || contains(github.event.pull_request.labels.*.name, 'release-matrix')"
EVENT = "github.event_name == 'pull_request' && !contains(github.event.pull_request.labels.*.name, 'release-matrix') && 'push' || github.event_name"
CHEAP = f"      - name: local evidence gate\n        if: ${{{{ !({GATE}) }}}}\n        run: echo 'Local gauntlet evidence is the gate; request ci or full-matrix for CI.'\n"


def blocks(text):
    return dict(re.findall(r"^  ([A-Za-z0-9_-]+):\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", text.split("\njobs:\n", 1)[1], re.M | re.S))


def event_block(text, event):
    header = text.split("\non:\n", 1)[1].split("\njobs:\n", 1)[0]
    m = re.search(r"^  " + event + r":[^\n]*\n(.*?)(?=^  [A-Za-z_]+:|^[A-Za-z_]+:|\Z)", header, re.M | re.S)
    return m[0] if m else None


def patterns(text):
    push = event_block(text, "push")
    m = re.search(r"^    paths:\n((?:      - .*\n)+)", push or "", re.M)
    return [l.strip()[2:].strip("'\"") for l in m[1].splitlines()] if m else None


def matches(path, globs):
    if globs is None:
        return True
    selected = False
    for pattern in globs:
        negative = pattern.startswith("!")
        p = pattern.lstrip("!")
        if fnmatch.fnmatchcase(path, p) or (p.startswith("**/") and fnmatch.fnmatchcase(path, p[3:])):
            selected = not negative
    return selected


def expression(expr, event, labels=()):
    expr = expr.strip().removeprefix("${{").removesuffix("}}").strip()
    expr = re.sub(r"contains\(github.event.pull_request.labels\.\*\.name, '([^']+)'\)", lambda m: repr(m[1] in labels), expr)
    expr = expr.replace("github.event_name", repr(event)).replace("!cancelled()", "True")
    expr = expr.replace("&&", " and ").replace("||", " or ")
    return eval(re.sub(r"!(?!=)", " not ", expr), {"__builtins__": {}}, {})


class Gate(unittest.TestCase):
    def main(self):
        return (ROOT / ".github/workflows" / BASE["main"]).read_text()

    def test_unlabelled_is_cheap_only(self):
        b = blocks(self.main())
        self.assertIn("plan", b)
        self.assertIn(CHEAP, b["plan"])
        self.assertTrue(expression("!(" + GATE + ")", "pull_request"))
        count = 3 if BASE["new_router"] else len(re.findall(r"^      - ", BASE["workflows"][BASE["main"]]["plan"], re.M)) + 1
        self.assertEqual(b["plan"].count("        if: ${{ " + GATE + " }}"), count)
        for job, body in b.items():
            if job in ["plan"] + BASE["exempt_jobs"]:
                continue
            self.assertIn("    if: ${{ (" + GATE + ")", body, job)
            self.assertFalse(expression(GATE, "pull_request"))

    def test_labelled_means_full_set(self):
        b = blocks(self.main())
        for label in ("ci", "full-matrix"):
            self.assertTrue(expression(GATE, "pull_request", [label]))
            if BASE["planner"]:
                self.assertIn("EVENT: ${{ " + EVENT + " }}", b["plan"])
                event = expression(EVENT, "pull_request", [label])
                self.assertEqual(event, "push")
                r = subprocess.run(BASE["planner"] + ["--event", event, "--json"], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                for key, value in BASE["full"].items():
                    self.assertEqual(json.loads(r.stdout)[key], value, (label, key))
            else:
                self.assertIn("SELECTED " + " ".join(BASE["selected"]), b["plan"])
            for job, body in b.items():
                if job not in ["plan"] + BASE["exempt_jobs"]:
                    self.assertIn("    if: ${{ (" + GATE + ")", body, job)

    def test_off_cross_cutting_push_runs_nothing(self):
        if BASE["preserve_push"]:
            self.assertEqual(event_block(self.main(), "push"), BASE["push_before"])
            self.assertTrue(matches(BASE["module_path"], patterns(self.main())), "publication push is deliberately unchanged")
            return
        self.assertIsNotNone(patterns(self.main()))
        for path in (BASE["module_path"], "notes/example.md", "README.md", "ci/example.md"):
            self.assertFalse(matches(path, patterns(self.main())), path)

    def test_cross_cutting_push_runs_full_set(self):
        self.assertTrue(expression(GATE, "push"))
        if not BASE["preserve_push"]:
            self.assertIsNotNone(patterns(self.main()))
            for path in BASE["cross_paths"]:
                self.assertTrue(matches(path, patterns(self.main())), path)
        for job, body in blocks(self.main()).items():
            if job not in ["plan"] + BASE["exempt_jobs"]:
                self.assertIn("    if: ${{ (" + GATE + ")", body, job)

    def test_original_commands_and_nightlies_preserved(self):
        for name, old_jobs in BASE["workflows"].items():
            text = (ROOT / ".github/workflows" / name).read_text()
            actual = blocks(text)
            expected = set(old_jobs) | ({"plan"} if BASE["new_router"] and name == BASE["main"] else set())
            self.assertEqual(set(actual), expected)
            self.assertIn("  workflow_dispatch:", text)
            if name in BASE["schedules"]:
                self.assertIn(BASE["schedules"][name], text)
            self.assertIsNotNone(event_block(text, "schedule"))
            self.assertIn("types: [opened, synchronize, reopened, labeled]", event_block(text, "pull_request"))
            for job, old in old_jobs.items():
                new = actual[job]
                new = re.sub(r"^    if: \$\{\{ \(" + re.escape(GATE) + r"\)(?: && \((.*)\))? \}\}\n", lambda m: "    if: " + ("${{ " + m[1] + " }}" if re.search(r"^    if: \$\{\{", old, re.M) is not None else m[1]) + "\n" if m[1] else "", new, flags=re.M)
                new = new.replace("        if: ${{ " + GATE + " }}\n", "")
                new = new.replace("          EVENT: ${{ " + EVENT + " }}", "          EVENT: ${{ github.event_name }}")
                new = new.replace(CHEAP, "").replace("      - name: local gate wiring proof\n        run: python3 -I ci/local-gate-test.py\n", "")
                self.assertEqual(new, old, (name, job))
        if BASE["new_router"]:
            self.assertEqual(blocks(self.main())["plan"], BASE["router_body"])
        for name, digest in BASE["unchanged"].items():
            self.assertEqual(hashlib.sha256((ROOT / ".github/workflows" / name).read_bytes()).hexdigest(), digest, name)
        for event in ("schedule", "workflow_dispatch", "push"):
            self.assertTrue(expression(GATE, event))
        self.assertTrue(expression(GATE, "pull_request", ["release-matrix"]))

    def test_deploy_not_selected_for_pull_requests(self):
        if "deploy" not in BASE["exempt_jobs"]:
            return
        old = BASE["workflows"][BASE["main"]]["deploy"]
        self.assertEqual(blocks(self.main())["deploy"], old)
        self.assertIn("github.event_name == 'push'", old)
        self.assertIn("github.ref == 'refs/heads/trunk'", old)
        self.assertEqual(event_block(self.main(), "push"), BASE["push_before"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
