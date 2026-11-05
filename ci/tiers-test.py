#!/usr/bin/env python3
# Adapted from wolffe-lang/burrow eb888dfc ci/tiers-test.py (aspen 476edee3's); own code.
"""ci/tiers-test.py — the planner's own proof (wolf-lang's tl21 test, as
scent cut it, cut again to burrow's workflow). python3 only.

  T1  the tiers by event: a trunk push, the nightly, a dispatch with no
      jobs and the `full-matrix` label are full; another label's
      `labeled` event is a noop; a dispatch naming jobs is partial, and
      refuses a job the workflow does not have.
  T2  the pull-request tiers by path: code is pr (linux, plan-test);
      prose alone is noop; prose beside code is pr.
  T3  full wins: a path no rule names; changed paths that cannot be read.
  T4  the wiring of .github/workflows/ci.yml: every job but `plan` needs
      it and runs only when the plan names it; `tier` needs every job,
      runs on `!cancelled()` and calls the verdict; cancel-in-progress is
      for pull requests only; the trunk push, the nightly, the label and
      the dispatch input are there; macos is no pull-request job.
  T6  the verdict: green for a full, a pr, a noop and a partial run; red
      for a chosen job failed or skipped, a job that ran unasked, a failed
      plan, a plan with no tier, a full that chose less.
  T8  ci/nightly-red.sh against a stand-in `gh` : no open
      issue opens one; an open one is commented on; a label that exists is
      no failure; the script refuses without its environment; the
      nightly-red job runs on a failed schedule only, after the verdict.

Exit 0 when every check passes, 1 otherwise.
"""
import json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "ci", "tiers.py")
WF = open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
KEYS = ("EVENT", "ACTION", "LABEL", "LABELS", "HEAD_SHA", "IN_JOBS", "NEEDS")
fails = 0
ALL = ["plan-test", "linux", "macos"]
PR = ["plan-test", "linux"]


def say(ok, what):
    global fails
    print("tiers-test: %s %s" % ("PASS" if ok else "FAIL", what))
    fails += not ok


def env(**more):
    e = {k: v for k, v in os.environ.items() if k not in KEYS}
    e.update(more)
    return e


def plan(paths=None, **kw):
    args = [sys.executable, PLAN, "plan", "--json"]
    for k, v in kw.items():
        args += ["--" + k.replace("_", "-"), v]
    if paths is not None:
        args += ["--paths-from", "-"]
    r = subprocess.run(args, input="\n".join(paths or []) + "\n", capture_output=True, text=True, env=env())
    if r.returncode != 0:
        return {"tier": "ERROR %d" % r.returncode, "jobs": []}
    return json.loads(r.stdout)


def verdict(needs):
    r = subprocess.run([sys.executable, PLAN, "verdict"], capture_output=True, text=True,
                       env=env(NEEDS=json.dumps(needs)))
    return r.returncode


def needs_for(tier, chosen, results=None):
    n = {"plan": {"result": "success", "outputs": {"tier": tier, "jobs": json.dumps(chosen)}}}
    for j in ALL:
        n[j] = {"result": (results or {}).get(j, "success" if j in chosen else "skipped")}
    return n


# T1
for ev in ("push", "schedule", "workflow_dispatch"):
    p = plan(event=ev)
    say(p["tier"] == "full" and p["jobs"] == ALL, "T1 %s is full" % ev)
p = plan(["src/burrow.lu"], event="pull_request", action="labeled", label="full-matrix", labels="full-matrix")
say(p["tier"] == "full" and p["jobs"] == ALL, "T1 the full-matrix label is full")
p = plan(["src/burrow.lu"], event="pull_request", action="labeled", label="docs", labels="docs")
say(p["tier"] == "noop" and p["jobs"] == [], "T1 another label is a noop")
p = plan(event="workflow_dispatch", jobs="linux")
say(p["tier"] == "partial" and p["jobs"] == ["linux"], "T1 a dispatch naming linux is partial")
p = plan(event="workflow_dispatch", jobs="windows")
say(p["tier"].startswith("ERROR"), "T1 a dispatch naming no job of the workflow is refused")
# T2
p = plan(["src/kex/kex.lu", "tools/check-transport"], event="pull_request", action="synchronize")
say(p["tier"] == "pr" and p["jobs"] == PR, "T2 code is pr")
p = plan(["README.md", "notes/bw01-the-transport.md", "CHANGELOG.md", "docs/MAP.md"], event="pull_request", action="opened")
say(p["tier"] == "noop", "T2 prose alone is a noop")
p = plan(["README.md", "src/burrow.lu"], event="pull_request", action="opened")
say(p["tier"] == "pr", "T2 prose beside code is pr")
# T3
p = plan(["somewhere/new"], event="pull_request", action="opened")
say(p["tier"] == "full", "T3 a path no rule names is full")
r = subprocess.run([sys.executable, PLAN, "plan", "--json", "--event", "pull_request", "--action", "opened"],
                   capture_output=True, text=True, env=env())
say(json.loads(r.stdout)["tier"] == "full", "T3 unreadable paths are full")
# T4
jobs = re.findall(r"^  ([a-z-]+):\s*$", WF.split("\njobs:\n", 1)[1], re.M)
say(jobs == ["plan", "plan-test", "linux", "macos", "tier", "nightly-red"], "T4 the jobs, in order: %s" % jobs)
for j in ALL:
    blk = WF.split("\n  %s:\n" % j, 1)[1].split("\n  ", 1)[0] + WF.split("\n  %s:\n" % j, 1)[1].split("\n\n  ", 1)[0]
    say("needs: plan" in blk and "contains(fromJSON(needs.plan.outputs.jobs || '[]'), '%s')" % j in blk,
        "T4 %s needs the plan and runs only when it is named" % j)
tblk = WF.split("\n  tier:\n", 1)[1]
say(all("- %s" % j in tblk for j in ["plan"] + ALL) and "!cancelled()" in tblk and "ci/tiers.py verdict" in tblk,
    "T4 tier needs every job, runs unless cancelled, checks the verdict")
say("cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in WF, "T4 cancel-in-progress for pull requests only")
say("branches: [trunk]" in WF and "schedule:" in WF and "labeled" in WF and "inputs:" in WF,
    "T4 the trunk push, the nightly, the label and the dispatch input")
# T6
say(verdict(needs_for("full", ALL)) == 0, "T6 a green full")
say(verdict(needs_for("pr", PR)) == 0, "T6 a green pr")
say(verdict(needs_for("noop", [])) == 0, "T6 a green noop")
say(verdict(needs_for("partial", ["linux"])) == 0, "T6 a green partial")
say(verdict(needs_for("pr", PR, {"linux": "failure"})) == 1, "T6 a chosen job failed")
say(verdict(needs_for("pr", PR, {"linux": "skipped"})) == 1, "T6 a chosen job skipped")
say(verdict(needs_for("pr", PR, {"macos": "success"})) == 1, "T6 a job that ran unasked")
say(verdict(needs_for("full", PR)) == 1, "T6 a full that chose less")
n = needs_for("pr", PR)
n["plan"]["result"] = "failure"
say(verdict(n) == 1, "T6 a failed plan")
n = needs_for("pr", PR)
n["plan"]["outputs"]["tier"] = ""
say(verdict(n) == 1, "T6 a plan with no tier")
# T8
RED = os.path.join(ROOT, "ci", "nightly-red.sh")
WORKFLOW_NAME = "ci"
FAKE_GH = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG"
case "$1 $2" in
  "label create") exit "${FAKE_LABEL_RC:-0}" ;;
  "issue list") printf '%s' "${FAKE_EXISTING:-}"; [ -n "${FAKE_EXISTING:-}" ] && echo; exit 0 ;;
esac
exit 0
"""


def nightly_red(existing="", label_rc=0):
    d = tempfile.mkdtemp(prefix="tiers-test-gh-")
    try:
        with open(os.path.join(d, "gh"), "w") as f:
            f.write(FAKE_GH)
        os.chmod(os.path.join(d, "gh"), 0o755)
        log = os.path.join(d, "log")
        e = env(PATH=d + os.pathsep + os.environ.get("PATH", ""), FAKE_LOG=log, FAKE_EXISTING=existing,
                FAKE_LABEL_RC=str(label_rc), REPO="wolffe-lang/burrow", WORKFLOW=WORKFLOW_NAME,
                RUN_URL="https://github.com/wolffe-lang/burrow/actions/runs/1")
        r = subprocess.run(["bash", RED], capture_output=True, text=True, env=e)
        calls = open(log).read().splitlines() if os.path.exists(log) else []
        return r.returncode, calls
    finally:
        shutil.rmtree(d, ignore_errors=True)


TITLE = "nightly red: %s on trunk" % WORKFLOW_NAME
rc, calls = nightly_red()
creates = [c for c in calls if c.startswith("issue create")]
say(rc == 0 and len(creates) == 1 and "--title %s" % TITLE in creates[0] and "--label nightly-red" in creates[0]
    and not [c for c in calls if c.startswith("issue comment")],
    "T8 no open issue: one is opened, labelled nightly-red, titled '%s'" % TITLE)
rc, calls = nightly_red(existing="41")
say(rc == 0 and [c for c in calls if c.startswith("issue comment 41 ")] and not [c for c in calls if c.startswith("issue create")],
    "T8 an open issue: a comment on it, no new issue")
rc, calls = nightly_red(label_rc=1)
say(rc == 0 and [c for c in calls if c.startswith("issue create")], "T8 a label that already exists is no failure")
r = subprocess.run(["bash", RED], capture_output=True, text=True, env=env())
say(r.returncode != 0, "T8 the script refuses to run without REPO, WORKFLOW and RUN_URL")
say(re.search(r"^name: %s$" % re.escape(WORKFLOW_NAME), WF, re.M) is not None, "T8 the workflow's name is %s, the title's" % WORKFLOW_NAME)
nblk = WF.split("\n  nightly-red:\n", 1)[1]
say("needs: tier" in nblk and "failure() && github.event_name == 'schedule'" in nblk and "issues: write" in nblk
    and "ci/nightly-red.sh" in nblk, "T8 nightly-red runs after the verdict, on a red schedule only, may write issues")
print("tiers-test: %s" % ("every check passes" if not fails else "%d check(s) FAILED" % fails))
sys.exit(1 if fails else 0)
