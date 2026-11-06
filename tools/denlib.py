"""denlib — den, its pinned git and den's fixture shape, for burrow's B4
rows (tools/check-den, tools/check-live, tools/measure-den).

den is the binary tools/fetch-den built at burrow-den.toml's pin; the git
is den's pinned git 2.56.0 (.den/git, by digest). A Fixture is den's
fixture shape under a row's directory: service wrappers `upload`,
`receive` and `upload-v0` that `exec env -i` into the pinned git with a
fixed environment, passing on only the GIT_PROTOCOL that arrived (and
logging it), and the repositories they serve, owned by the image's
`burrowtest`.
"""
import hashlib
import os
import pathlib
import pwd
import shutil
import subprocess
import tomllib
import zlib

import oraclelib

ROOT = oraclelib.ROOT
PIN = tomllib.loads((ROOT / "burrow-den.toml").read_text())
DEN = ROOT / ".den" / "den" / "target" / "native" / "den"
GIT_ROOT = ROOT / ".den" / "git"
GIT_BIN = GIT_ROOT / "opt" / "git" / "bin"
GIT = GIT_BIN / "git"
EXEC_PATH = GIT_ROOT / "opt" / "git" / "libexec" / "git-core"
USER = "burrowtest"
# The pinned ssh reads ~/.ssh from the passwd entry, never $HOME (measured,
# bw03); burrow reads $HOME (R-bw02-4). The client is the container's own
# user, so each row installs its .ssh there and sets HOME to it: both
# clients read the same files. Only ever inside the pinned container.
PW_HOME = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir)
class Fail(Exception):
    pass


def check(cond, why):
    if not cond:
        raise Fail(why)


def tail(b, n=400):
    s = b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b)
    return s.strip()[-n:].replace("\n", " | ")


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def require_den():
    """den and its git at their pins, by digest, or a named refusal."""
    stamp = ROOT / ".den" / "STAMP"
    if not stamp.exists() or not DEN.exists() or not GIT.exists():
        raise SystemExit("denlib: .den/ is not staged: run tools/in-container tools/fetch-den")
    if sha(GIT) != PIN["git"]["binary_sha256"]:
        raise SystemExit(f"denlib: .den/git does not hold the pin ({sha(GIT)})")
    lines = stamp.read_text().split("\n")
    if lines[0] != f"den {PIN['den']['rev']} {sha(DEN)}":
        raise SystemExit("denlib: .den/STAMP does not name this den binary at the pin: run tools/fetch-den")


def install_home(src):
    """The row's ~/.ssh and ~/.gitconfig as the container user's own."""
    if os.environ.get("BURROW_IN_CONTAINER") != "1":
        raise SystemExit("denlib: refusing to install a row's ~/.ssh outside the pinned container")
    clear_home()
    shutil.copytree(src / ".ssh", PW_HOME / ".ssh", symlinks=True)
    shutil.copy2(src / ".gitconfig", PW_HOME / ".gitconfig")


def clear_home():
    if os.environ.get("BURROW_IN_CONTAINER") != "1":
        return
    for name in (".ssh", ".gitconfig"):
        p = PW_HOME / name
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.exists():
            shutil.rmtree(p)


def ids():
    p = pwd.getpwnam(USER)
    return p.pw_uid, p.pw_gid


def chown_tree(path):
    uid, gid = ids()
    os.chown(path, uid, gid)
    for dirpath, dirnames, filenames in os.walk(path):
        for n in dirnames + filenames:
            os.chown(os.path.join(dirpath, n), uid, gid, follow_symlinks=False)


def git_env(fixture):
    fx = fixture.fx
    return {"PATH": f"{GIT_BIN}:/usr/bin:/bin", "GIT_EXEC_PATH": str(EXEC_PATH), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": str(fx / "gitconfig-root"), "HOME": str(fx / "root-home"), "LC_ALL": "C", "TZ": "UTC",
            "GIT_AUTHOR_NAME": "Den Tester", "GIT_AUTHOR_EMAIL": "den@example.invalid",
            "GIT_COMMITTER_NAME": "Den Tester", "GIT_COMMITTER_EMAIL": "den@example.invalid",
            "GIT_AUTHOR_DATE": "1700000000 +0000", "GIT_COMMITTER_DATE": "1700000000 +0000"}


def git(fx, *args, cwd=None, data=b""):
    """The pinned git, as root, on the row's own repositories."""
    p = subprocess.run([str(GIT), *map(str, args)], cwd=cwd, input=data, env=git_env(fx), capture_output=True, timeout=60)
    if p.returncode != 0:
        raise Fail(f"git {' '.join(map(str, args))} exited {p.returncode}: {tail(p.stderr)}")
    return p.stdout


class Fixture:
    """den's fixture shape under a row's directory: owned service wrappers
    into the pinned git, and the repositories they serve."""

    def __init__(self, d):
        self.d = d
        self.fx = d / "fixture"
        for name in ("bin", "home", "root-home", "empty-template", "empty-hooks", "tmp", "template"):
            (self.fx / name).mkdir(parents=True, exist_ok=True)
        self.srv = d / "srv"
        (self.fx / "gitconfig").write_text(
            "[user]\n\tname = Den Tester\n\temail = den@example.invalid\n[core]\n\thooksPath = "
            f"{self.fx / 'empty-hooks'}\n[init]\n\tdefaultBranch = main\n\ttemplateDir = {self.fx / 'empty-template'}\n")
        (self.fx / "gitconfig-root").write_text((self.fx / "gitconfig").read_text() + "[safe]\n\tdirectory = *\n")
        fixed = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(self.fx / "gitconfig"),
                 "GIT_EXEC_PATH": str(EXEC_PATH), "GIT_AUTHOR_NAME": "Den Tester", "GIT_AUTHOR_EMAIL": "den@example.invalid",
                 "GIT_COMMITTER_NAME": "Den Tester", "GIT_COMMITTER_EMAIL": "den@example.invalid",
                 "GIT_AUTHOR_DATE": "1700000000 +0000", "GIT_COMMITTER_DATE": "1700000000 +0000",
                 "HOME": str(self.fx / "home"), "TMPDIR": str(self.fx / "tmp"), "LC_ALL": "C", "TZ": "UTC",
                 "PATH": f"{GIT_BIN}:/usr/bin:/bin"}
        assigns = " ".join(f"'{k}={v}'" for k, v in fixed.items())
        self.log = self.fx / "protocol.log"
        for name, service, keep in (("upload", "git-upload-pack", True), ("receive", "git-receive-pack", True),
                                    ("upload-v0", "git-upload-pack", False)):
            check((GIT_BIN / service).exists(), f"no {service} in the pinned git")
            text = "#!/bin/sh\nset -eu\n"
            if not keep:
                text += "unset GIT_PROTOCOL\n"
            text += (f"printf '%s %s\\n' {name} \"${{GIT_PROTOCOL-<unset>}}\" >>'{self.log}'\n"
                     "proto=\n[ -z \"${GIT_PROTOCOL+x}\" ] || proto=\"GIT_PROTOCOL=$GIT_PROTOCOL\"\n"
                     f"exec env -i {assigns} ${{proto:+\"$proto\"}} '{GIT_BIN / service}' \"$@\"\n")
            p = self.fx / "bin" / name
            p.write_text(text)
            p.chmod(0o755)
        self.upload = str(self.fx / "bin" / "upload")
        self.receive = str(self.fx / "bin" / "receive")
        self.upload_v0 = str(self.fx / "bin" / "upload-v0")
        for name in ("home", "tmp"):
            chown_tree(self.fx / name)
        self.reset_log()

    def reset_log(self):
        self.log.write_text("")
        uid, gid = ids()
        os.chown(self.log, uid, gid)
        os.chmod(self.log, 0o644)

    def path(self, repo):
        return self.fx / "template" / repo

    def seed(self, repo="plain.git"):
        """Two commits, `main` at the first (den's ssh-peer seed): their ids."""
        path = self.path(repo)
        git(self, "init", "-q", "--bare", "-b", "main", path)
        commits = []
        for data in (b"first\n", b"first\nsecond\n"):
            blob = git(self, "hash-object", "-w", "--stdin", cwd=path, data=data).strip().decode()
            tree = git(self, "mktree", cwd=path, data=f"100644 blob {blob}\ta\n".encode()).strip().decode()
            parent = ["-p", commits[0]] if commits else []
            commits.append(git(self, "commit-tree", tree, *parent, "-m", "second" if commits else "first", cwd=path).strip().decode())
        git(self, "update-ref", "refs/heads/main", commits[0], cwd=path)
        return commits

    def empty(self, repo):
        git(self, "init", "-q", "--bare", "-b", "main", self.path(repo))

    def reset_server(self):
        if self.srv.exists():
            shutil.rmtree(self.srv)
        shutil.copytree(self.fx / "template", self.srv, symlinks=True)
        chown_tree(self.srv)
        self.reset_log()

    def served(self, repo):
        return str(self.srv / repo)


def repo_state(fx, repo, bare=True):
    """HEAD, every ref and every object (id, kind, content digest), read by
    the pinned git; the worktree's files for a checkout."""
    repo = pathlib.Path(repo)
    if not repo.exists():
        return {"absent": True}
    admin = repo if bare else repo / ".git"
    head = (admin / "HEAD").read_text() if (admin / "HEAD").exists() else None
    refs = git(fx, "--git-dir", admin, "for-each-ref", "--format=%(refname) %(objectname)").decode().splitlines()
    names = git(fx, "--git-dir", admin, "rev-list", "--objects", "--all").decode().splitlines() if refs else []
    objects = {}
    for name in names:
        oid = name.split(" ", 1)[0]
        kind = git(fx, "--git-dir", admin, "cat-file", "-t", oid).strip().decode()
        body = git(fx, "--git-dir", admin, "cat-file", kind, oid)
        objects[oid] = (kind, hashlib.sha256(body).hexdigest())
    fsck = subprocess.run([str(GIT), "--git-dir", str(admin), "fsck", "--full", "--no-dangling"], env=git_env(fx),
                          capture_output=True, timeout=60)
    state = {"head": head, "refs": refs, "objects": objects, "fsck": (fsck.returncode, fsck.stdout, fsck.stderr)}
    if not bare:
        files = {}
        for p in sorted(repo.rglob("*")):
            rel = p.relative_to(repo)
            if rel.parts[0] == ".git":
                continue
            if p.is_file():
                files[str(rel)] = hashlib.sha256(p.read_bytes()).hexdigest()
        state["worktree"] = files
    return state


def write_objects(fx, local, source, head):
    """A den repository (`den init --bare`) holding `source`'s objects, loose,
    and `main` at `head` (den's ssh-test local_source)."""
    r = subprocess.run([str(DEN), "init", "-q", "--bare", str(local)], capture_output=True, timeout=60)
    check(r.returncode == 0, f"den init: {tail(r.stderr)}")
    names = git(fx, "--git-dir", source, "rev-list", "--objects", "--all").decode().splitlines()
    for name in names:
        oid = name.split(" ", 1)[0]
        kind = git(fx, "--git-dir", source, "cat-file", "-t", oid).strip().decode()
        body = git(fx, "--git-dir", source, "cat-file", kind, oid)
        raw = kind.encode() + b" " + str(len(body)).encode() + b"\0" + body
        check(hashlib.sha1(raw).hexdigest() == oid, f"object {oid} does not hash to its id")
        p = pathlib.Path(local) / "objects" / oid[:2] / oid[2:]
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(zlib.compress(raw, 1))
    (pathlib.Path(local) / "refs" / "heads" / "main").write_text(head + "\n")
