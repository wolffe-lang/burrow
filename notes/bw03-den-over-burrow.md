# bw03 — den over burrow (B4)

## Prediction

Written 2026-11-06 05:22Z, at trunk `2077c87`, before any B4 code and
before any run of the pinned OpenSSH, of den or of GitHub for this lane,
from den's `src/transport/ssh.lu` and `src/transport/channel.lu`, den's
`src/wiregit/command.lu` (where `--upload-pack=` is read), den's
`tools/ssh-test.py` and `tools/ssh-peer.py` (its ssh rows and their
fixture), bw02's note and `cli-den-argv`, `ssh(1)` and `ssh_config(5)`.
Every behaviour of den, the pinned `ssh` and GitHub's server below is a
prediction; the evidence index records each hit and miss.

### den's argv and environment, exactly

den starts `ssh` through PATH (`process.from_argv`, no shell) with stdin
and stdout as pipes and stderr inherited. For every SSH URL form the argv
is the same eighteen words, then the endpoint:

```text
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no
    -o ControlMaster=no -o ControlPath=none -o ClearAllForwardings=yes
    -o ConnectTimeout=30 -o SendEnv=GIT_PROTOCOL [-p PORT] -- HOST 'PROGRAM' 'PATH'
```

| URL form | HOST | `-p` | PATH |
|---|---|---|---|
| `ssh://host/path` | `host` | none | `/path` |
| `ssh://user@host/path` | `user@host` (den keeps the user in the destination; it never passes `-l`) | none | `/path` |
| `ssh://[user@]host:port/path` | as above | `-p port`, before `--` | `/path` |
| scp-like `[user@]host:path` | `[user@]host` | none (the form has no port: a `Host` block gives one) | `path` as written, absolute or relative to the login's home |

- **PROGRAM** is `git-upload-pack` or `git-receive-pack`, or the value of
  `--upload-pack=` (clone and fetch) or `--receive-pack=` (push): den puts the
  override into `DEN_UPLOAD_PACK` or `DEN_RECEIVE_PACK` for the command's
  duration, and the transport reads it from there. A literal executable,
  never a shell command.
- **Quoting:** each remote word single-quoted, `'` written `'\''`; NUL, CR
  and LF refused by den before any process starts. burrow joins the words
  with single spaces into the `exec` request (`ssh(1)`), so the remote shell
  sees exactly `'PROGRAM' 'PATH'`.
- **Environment:** den's own, plus `GIT_PROTOCOL=version=2` set around the
  process start for both services (restored after), so the pinned `ssh` and
  burrow both send one `env` request, `GIT_PROTOCOL` = `version=2`, before
  `exec`, for upload-pack and receive-pack alike. `git receive-pack` does not
  speak v2 and serves its v0 advertisement whatever it is given; den's push
  reads that framing.
- No `-i`, `-l`, `-F`, `UserKnownHostsFile` or `-T`: identities, host keys
  and any `Host` block come from `$HOME/.ssh`.

### What burrow-as-`ssh` must do with each

burrow, built at its head and linked as `ssh` in a directory first on
PATH, takes every word above as bw02 left it (`cli-den-argv` already runs
that argv): the eight options; `-p`; `--`; HOST as `[user@]host`, with a
`Host` block's `HostName`, `Port` and `User` applied for an alias (first
value wins, so a user in HOST beats the block's `User`); the known_hosts
lookup under `[127.0.0.1]:PORT` for a port other than 22, strict; the login
with `~/.ssh/id_ed25519`; one session channel, the `env` request, the
`exec` request with the joined command; stdin, stdout and stderr as raw
bytes; and the remote's exit status as its own. Its messages say `ssh:`
under that name.

**Predicted: den's rows need no burrow change.** Every den row below
passes through burrow at `2077c87` as through the pinned `ssh`, byte for
byte. Two places could break it, and the rows watch both:

- den closes its pipes early (the v0 refusal, a push den rejects before
  sending a pack). Predicted: the remote has already written everything
  (git's advertisement fits a pipe), burrow sees stdin's end, sends EOF, and
  the remote exits 0; nothing reaches den's stderr from either client.
- any line burrow writes to stderr that the pinned `ssh` does not (a
  refusal, a debug line): den inherits stderr, so it would show as a
  difference in den's stderr.

**One change predicted, red first:** with no command, burrow refuses
`shell_unsupported` before it connects, so `burrow -T git@github.com`
without a key never reaches GitHub (exit 255, no `Permission denied`
line), where the pinned `ssh` is refused authentication. The fix moves
that refusal after the login (R-bw03-1): a probe without a key is refused
as `ssh` refuses it, and a login with no command still refuses by name,
never starting a shell. `cli-no-command` follows: it logs in first.

### The rows (`tools/check-den`)

den at its trunk `ef0bb0c`, unchanged, built by its own tools at its own
toolchain pin (wolf 0.2.36, std `78b9d3c`). The server is the pinned
`sshd` on a loopback port the row owns, with `AcceptEnv GIT_PROTOCOL`, the
row's client key authorized for the image's `burrowtest`, and den's
fixture shape: owned service wrappers `upload`, `receive` and `upload-v0`
under the row's directory, each `exec env -i` with a fixed environment
(`GIT_EXEC_PATH`, a gitconfig with an empty hook path and template, fixed
author and committer, `LC_ALL=C`, `TZ=UTC`) into den's pinned git 2.56.0
(`den-oracle.toml`, binary sha256 `c4848492…`). One difference from den's
own fixture, on purpose: den's wrappers export `GIT_PROTOCOL=version=2`
themselves, because the host `sshd` den's live rows met did not accept the
variable. Here `sshd` accepts it, so `upload` and `receive` pass on only
what arrived (and log it); every v2 row then proves that `SendEnv`, the
`env` request and `AcceptEnv` carried `version=2`. `upload-v0` unsets it,
as den's does.

The client's `HOME`: `~/.ssh/id_ed25519` (0600) and its `.pub` from
`burrow-keygen`, made for the run; `~/.ssh/known_hosts` with the row
`sshd`'s ed25519 line (`[127.0.0.1]:PORT`); `~/.ssh/config` with
`Host fixture` (`HostName 127.0.0.1`, `Port`, `User burrowtest`) for the
forms that carry no port or user.

Each row runs den twice, through burrow-as-`ssh` and through the pinned
`ssh` (the same `HOME`, key and `sshd`; only PATH's `ssh` differs), with
the server repositories reset from one template and the local destination
at the same path both times, and compares:

- den's exit code, stdout and stderr, byte for byte;
- the local repository: HEAD, every ref, every object by id, kind and
  content, the worktree's files (checkout rows);
- the server repository, read with the pinned git: every ref, every object,
  `fsck --full`;
- the wrappers' log of the `GIT_PROTOCOL` each service received.

Normalisations: none in den's bytes, since the paths are the same both
times. The local repository's `index` (stat data) and `logs/` (reflog
times) are not compared byte for byte; their content is (the worktree
files, the ref values).

| row | den command (`URL` to the row's server) | both clients, predicted |
|---|---|---|
| `den-clone-uri` | `clone -q --bare --upload-pack=UPLOAD ssh://burrowtest@127.0.0.1:PORT/…/plain.git` | exit 0, silent, refs and the first commit's 3 objects as the server's |
| `den-clone-uri-alias` | the same as `ssh://fixture/…/plain.git` (port and user from the `Host` block) | the same |
| `den-clone-scp` | `fixture:/…/plain.git` | the same |
| `den-clone-scp-user` | `burrowtest@fixture:/…/plain.git` | the same |
| `den-clone-checkout` | a non-bare clone | the same, and the worktree's `a` is `first\n` |
| `den-clone-space-path`, `den-clone-quote-path`, `den-clone-literal-path` | repositories named `space repo.git`, `quote'repo.git`, `semi;true.git` | the same: the quoting survives burrow's join |
| `den-fetch-incremental` | `fetch -q --upload-pack=UPLOAD URL refs/heads/main:refs/heads/main` from the first commit to the second | exit 0, the second commit's objects arrive |
| `den-push-uri`, `den-push-scp` | `push -q --receive-pack=RECEIVE URL HEAD:refs/heads/main` to an empty repository | exit 0, the server's `main` and objects are the pushed ones |
| `den-lease-stale` | `--force-with-lease=refs/heads/main:<first>` while the server has the second | nonzero, `stale info` in den's stderr, the server unchanged |
| `den-lease-matching` | `--force-with-lease=refs/heads/main:<second>` rewinding to the first | exit 0, the server's `main` is the first |
| `den-push-atomic` | `push -q --atomic … HEAD:refs/heads/a HEAD:refs/heads/b` | exit 0, both refs created |
| `den-push-atomic-rejected` | `--atomic` with one ref a non-fast-forward | nonzero, neither ref changes |
| `den-push-rejected` | a non-fast-forward without force | nonzero, den's rejection in stderr, the server unchanged |
| `den-push-server-rejected` | `--force` to a server with `receive.denyNonFastForwards` | nonzero, the server's refusal in den's stderr, the server unchanged |
| `den-v0-refusal` | `clone` with `--upload-pack=UPLOAD_V0` | nonzero, `does not advertise protocol v2`, no destination objects |

Every v2 row's wrapper log reads `version=2` for both clients; the
`upload-v0` row's reads none. Rows run on both of burrow's tiers (`den`,
`den-release`), each row printing `PASS`/`FAIL den-<row>` at column 0.

### GitHub, read only, with no key (`tools/check-github`)

`ssh -T git@github.com` and burrow-as-`ssh -T git@github.com`, from a
`HOME` with no identity and a `known_hosts` holding GitHub's published
ed25519 line (`api.github.com/meta`, fetched into SOURCES), strict:

- GitHub offers `curve25519-sha256`, `kex-strict-s-v00@openssh.com`,
  `ssh-ed25519` and `chacha20-poly1305@openssh.com`, and EXT_INFO with a
  `server-sig-algs` naming `ssh-ed25519`, so burrow's profile negotiates
  with it; the ed25519 host key's fingerprint is the published
  `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`, and both clients
  accept it from the published line.
- With no identity, burrow sends `none` (RFC 4252 §5.2) and GitHub answers
  FAILURE listing `publickey`; both exit 255 and both print
  `git@github.com: Permission denied (publickey).` last.
- Red first at `2077c87` (`shell_unsupported`, no connection), green after
  R-bw03-1. Each row SKIPs by name when github.com port 22 does not answer.

### The live push (`tools/check-live`)

`live-push` reads `BURROW_LIVE_SSH_URL` and `BURROW_LIVE_SSH_KEY` from its
environment and SKIPs by name without both. With them: a `HOME` whose
config names the key (`IdentitiesOnly yes`) and GitHub's published
known_hosts line; a synthetic commit (a fixed tree, a per-run nonce in its
blob) pushed by den to `refs/heads/burrow-live/<nonce>/burrow` through
burrow and to `…/ssh` through the pinned `ssh`; den's exit, stdout and
stderr compared; the fixture cloned back by den through each client and
both refs' commits and objects compared with what was pushed; both refs
deleted through burrow at the end. Nothing it prints or keeps holds the URL
or the key path (each is replaced by a placeholder before anything is
written), and a scan of its evidence proves no key material. The key is
made by `burrow-keygen` in the lane's own directory on the Linux host;
only its public line leaves the lane.

### For PAX

`tools/build --static` gives `target/static/burrow` and
`target/static/burrow-keygen`: static ELF executables (no `PT_INTERP`), their
sha256 printed by the gate's `static` step, which also runs two den rows
(`den-clone-uri`, `den-push-uri`) with the static `burrow` as `ssh`. A px
lane installs them as `/bin/ssh` and `/bin/burrow-keygen`. With no
resolver on PAX (wolf-lang#831, wolf-std#4), den keeps the URL
`git@github.com:…` and `~/.ssh/config` maps it: `Host github.com`,
`HostName` an address from `api.github.com/meta`'s `git` ranges, and
`HostKeyAlias github.com`, so the known_hosts line is GitHub's published
one. The console kernel's network (R-px97-17) is the other gap; no root
store is needed (ssh has no X.509). burrow reads `/dev/urandom` (R-bw01-4):
the px lane must find one on PAX. The note drafts that lane's first items.

### Measured (`tools/measure-den`)

A mid-sized fixture made by the pinned git from a fixed seed (300 commits
over 200 text files in 10 directories plus 40 incompressible 256 KiB files:
about 3,300 objects, a pack of about 13 MB, inside den's bounds), cloned by
den (`clone -q --bare`) through release burrow and through the pinned
`ssh`, interleaved, five rounds each, the minimum of each. The client side's
CPU is den's `wait4` rusage, which includes the `ssh` it waits for; den is
the same binary both ways, so the ratio isolates the ssh client. Predicted:
den's own work dominates (inflating, hashing and writing about 3,300
objects), and burrow's decryption of 13 MB costs about 0.25 s CPU against
the pinned `ssh`'s 0.03 s (bw02's `cat` rates), so CPU through burrow / through
`ssh` between 1.02x and 1.3x and wall between 0.95x and 1.4x. The gate's
margins: at most 2x for each. It runs on a quiet block with the light lock
held (a perf step).

### What changes, and what must not

- **burrow:** `tools/check-den`, `tools/fetch-den` (den at its pin, its
  toolchain and build, its git oracle by digest), `tools/check-github`,
  `tools/check-live`, `tools/measure-den`; the pin `burrow-den.toml`; the
  gate's steps; `tools/in-container` passes the two live variables through
  when set; R-bw03-1 in `src/burrow.lu`. No change to the transport, the
  auth, the channel or the session is predicted.
- **den: nothing.** Its trunk `ef0bb0c` is built as it is, and its argv,
  its wrappers' shape and its rows are read, never edited. If den needed a
  change, the lane would hand back with an R-bw03-N.
