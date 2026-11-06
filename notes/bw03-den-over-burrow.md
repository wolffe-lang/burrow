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
one. The console kernel's network is the other gap, PAX's own; no root
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

### The re-pin to den `ac2332b` (R-bw03-7 applied)

Written 2026-11-06 15:26Z, after den's fix merged (den trunk `ac2332b`)
and before any change or run at it, from den's `src/transport/ssh.lu` at
that trunk, its CHANGELOG and `notes/vc22-the-smart-http-transport.md`.

- **What moves:** `burrow-den.toml`'s rev, `ef0bb0c` to `ac2332b`. den's
  own toolchain pin keeps wolf 0.2.36 and moves its std from `78b9d3c` to
  `d4a4d4c`; `tools/fetch-den` builds it with den's own tools, as before.
  den's git oracle is unchanged (2.56.0, `c4848492…`; `den-oracle.toml`
  did not change), so `tools/fetch-den` accepts it.
- **den's argv at `ac2332b`:** the same eighteen words, then `-- HOST
  PROGRAM 'PATH'`: the program word bare when it is plain (letters, digits
  and `._/+-`), quoted when it is not; the path always quoted. ssh(1)
  joins the words with spaces, so the exec request carries
  `git-receive-pack 'PATH'`, git's form.
- **New rows, red first at `ef0bb0c`** (`tools/check-den`,
  `den-command-*`): the row key's `authorized_keys` line carries
  `command="…/record-command"`. sshd(8) (AUTHORIZED_KEYS FILE FORMAT)
  runs that command instead of the client's and puts the client's in
  `SSH_ORIGINAL_COMMAND`; the recorder logs it and runs it under `sh -c`,
  with den's wrappers as `git-upload-pack` and `git-receive-pack` first on
  PATH. Each row is also held byte for byte to the pinned `ssh`, as every
  den row is, and its clone or push succeeds.

  | row | den | the command sshd is sent, predicted at `ac2332b` | at `ef0bb0c` |
  |---|---|---|---|
  | `den-command-upload` | `clone` with no `--upload-pack=` | `git-upload-pack 'PATH'` | red: `'git-upload-pack' 'PATH'` |
  | `den-command-receive` | `push` with no `--receive-pack=` | `git-receive-pack 'PATH'` | red: `'git-receive-pack' 'PATH'` |
  | `den-command-override` | `--upload-pack=` a plain path | `/…/upload 'PATH'` | red: `'/…/upload' 'PATH'` |
  | `den-command-override-quoted` | `--upload-pack=` a path holding a space | `'/…/up load' 'PATH'` | green: quoted at both pins (den's guard) |

- **den's 18 rows:** green at `ac2332b` through both clients, alike, with
  no burrow change. den's other changes between the pins (the smart-HTTP
  and local-path transports, status and branch work) touch no ssh row's
  bytes but one: a failed clone now removes the directory it made, so
  `den-v0-refusal` leaves no destination, through both clients alike.
- **`tools/diag-command-form`, re-run:** den's command is taken from den
  itself at the pin (a recording `ssh` first on PATH prints den's argv to
  den's stderr, held in memory, and exits 255, so nothing connects), and
  den's whole argv then runs through each client: accepted by the
  fixture's server through both (exit 0, a receive-pack advertisement), and
  it is git's form. den's old form through the pinned `ssh` is still
  refused, `Invalid command` (the control).
- **The live row:** green. The base push creates `burrow-live-base` once;
  the per-run pushes are alike through both clients, cloned back alike,
  then deleted.
- **`measure-den`:** inside its 2x margins, CPU near 1.0x.
- **burrow's `src/`:** unchanged.

## Forbidden

No ssh implementation's code or tests were read: no `.c` or `.h` file of
any OpenSSH release, nothing of dropbear, libssh, libssh2, Go's
`x/crypto/ssh`, paramiko, asyncssh, russh, thrussh, conch, PuTTY or
wolfSSH, and no SHA or HMAC library's source. No git source: den's git is
its pinned binary, a black box, and no git documentation was needed. den's
own code and tools were read as the consumer's (SOURCES lists the files);
den was not edited, and its tree is checked clean at its pin by every
`tools/fetch-den`. Two rows contact a real host, by design and only these:
GitHub's server, read only and with no key (the handshake and RFC 4252's
`none` request), and the live fixture, from `BURROW_LIVE_SSH_URL` and
`BURROW_LIVE_SSH_KEY` alone. Keys are made per run by `burrow-keygen`;
private keys stay in 0700 run directories or the container user's own
`~/.ssh`, which each row replaces and clears; evidence copies are scanned
for key files, private key text and (the live row) the fixture's URL, name
and key path. The deploy key was made by `burrow-keygen` in the lane's own
directory on the Linux host, and only its public line left it. The plant
branch has no PR and no CI run.

## Inputs verified

Footprint: cross-cutting

- The toolchain and OpenSSH pins are unchanged from trunk `2077c87` (wolf
  0.2.37, lupin 0.1.59, std `5b3a599`, OpenSSH 10.0p2), each held to its
  digest by `tools/fetch-toolchain` and `tools/fetch-oracle` in every take.
- **A new pin, `burrow-den.toml`:** den at its trunk `ef0bb0c` (fetched by
  that commit alone, checked out clean, built by den's own
  `tools/fetch-toolchain` at its own pin, wolf 0.2.36 `5adf3d9` and std
  `78b9d3c`, and its own `tools/build --native`), and den's git oracle,
  git 2.56.0 with binary sha256
  `c4848492938c4ebfffbefe1fbbaa68b9af90c86d1f6a20e76816c5ff37fcfa60`, the
  digest den's own `den-oracle.toml` pins (checked against it at the pin).
  The tree was built by den's own `tools/fetch-oracle` in den's image and
  reused by copy; `tools/fetch-den` refuses any other digest.
- GitHub's published host key (`ci/github-known-hosts`) and fingerprint,
  from GitHub's meta API and its fingerprints page, by sha256 in SOURCES.
- `tools/in-container` gains a pass-through for three variables, and the
  gate gains its B4 steps; CI's workflow is unchanged (R-bw03-3).

Commits, in order (the row first wherever a row exists):

- `0a0b2ba` the prediction.
- `1e746cd` the den pin; `ce390c5` `6fb9080` `tools/fetch-den`.
- `369d50b` `59ab214` `b22d1ef` `tools/check-den` (rows, the fixture's git
  environment, the passwd home); `3a9687d` the gate's den steps.
- `ba1f956` `882e14d` `tools/check-github`, red against `2077c87`'s burrow;
  `4c4fb9c` the gate's `github` step and its SKIP.
- `9b83991` `cli-no-command` logs in first (red); `8fecc2f` R-bw03-1, the
  fix; `43d4e18` the rejection rows' assertions.
- `e84fa3c` `tools/denlib.py`; `2c035b8` `tools/check-live`; `8eca493`
  `9c881db` `27c8085` `tools/measure-den` and its size; `4aef680`
  `tools/check-static`; `2e0fa05` the gate's last steps; `13a8ef8` counts
  and flushes.
- `a8acd52` `tools/diag-command-form`, the read-only probe of the fixture
  server's command form (R-bw03-7).
- `292e148` `9540a7d` README, `dd05cec` MAP, `c4a4dea` SOURCES, `4a27c96`
  CHANGELOG; and this note.

## Evidence index

**The rows.** den's 18 rows (`tools/check-den`) pass on both of burrow's
tiers, every compared field equal through burrow and through the pinned
`ssh`; two of them pass again through the static `burrow`
(`tools/check-static`). The GitHub rows (2) and the live row's loopback
self-test (1) pass; the live row SKIPs by name without its variables. The
existing families are unchanged in count and green: 14 unit rows, 25
transport rows and 44 session rows on both tiers, 8 hostile-peer rows on
both tiers.

**Red first.**

- den's rows needed no burrow change, as predicted: at `882e14d`, whose
  burrow source is `2077c87`'s, all 18 passed on their first full run. Their
  red is the plant's (below): they are rows that hold behaviour bw02 built.
- `github-host-key` and `github-no-key` were red at `882e14d`, by name:
  burrow refused `shell_unsupported` before connecting. Both passed after
  `8fecc2f`.
- `cli-no-command` was red at `9b83991` (`sshd did not log the login before
  the refusal`) and passed after `8fecc2f`.

**The prediction, hit and missed.**

| predicted | measured |
|---|---|
| den's argv and environment as tabled, for every URL form | hit: each row's command reached the wrappers as den quoted it (paths with a space, a quote and a semicolon too), and each service received `GIT_PROTOCOL=version=2` |
| receive-pack is sent `version=2` too, and serves v0 framing | hit (`receive version=2` in the wrappers' log; den's push reads it) |
| den's rows need no burrow change | hit (above) |
| den's early close (v0 refusal, a push den rejects) puts nothing on its stderr from either client | hit: `den-v0-refusal` and `den-push-rejected` equal through both |
| burrow-as-`ssh` and the pinned `ssh` read the same `$HOME/.ssh` | **miss**: the pinned `ssh` reads `~/.ssh` from the passwd entry, never `$HOME` (its `-v` names `/root/.ssh`); the rows install their `.ssh` as the container user's own (R-bw03-5) |
| a remote's stderr reaches den's stderr alike | hit: `error: denying non-fast-forward …` from the server's receive-pack, byte for byte (`den-push-server-rejected`) |
| with no command, burrow refuses before connecting, so the GitHub rows are red until R-bw03-1 | hit (above) |
| GitHub offers `curve25519-sha256`, strict kex, `ssh-ed25519`, `chacha20-poly1305@openssh.com`, EXT_INFO with `server-sig-algs` | hit, with `publickey-hostbound@openssh.com` too; the pinned `ssh` chose `mlkem768x25519-sha256`, burrow `curve25519-sha256` |
| GitHub's ed25519 fingerprint is the published `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU` | hit, and both clients accepted the published line strictly |
| with no identity both are refused `git@github.com: Permission denied (publickey).`, exit 255 | hit (burrow sent `none`, as RFC 4252 §5.2 names the methods) |
| static binaries with no interpreter | hit: no `PT_INTERP`, no dynamic section; the static `burrow-keygen` also ran on a Linux host whose userland is not the image's (it made the deploy key) |
| the measurement fixture: 300 commits and 40 large files, about 3,300 objects and a 13 MB pack, inside den's bounds | **miss**: 3,243 objects and a 17 MB pack, and den's clone through burrow was SIGKILLed at the container's 12 GiB cap. Through the pinned `ssh` alone, den's peak RSS was 348 MiB at 30 commits, 954 MiB at 60, 3.3 GiB at 120 and 12.2 GiB at 300 (no large files): den's, growing faster than the history, whichever client carries it (den#63, R-bw03-4). The fixture is 60 commits and 8 large files |
| CPU through burrow / through `ssh` between 1.02x and 1.3x, wall between 0.95x and 1.4x, margins 2x | CPU hit (1.04x); wall a miss low (0.83x): den's wall time is mostly I/O and swings 10–45 s between rounds on a shared host, so the wall minimum is noise-bound; both inside the margins |
| the live push and its clone-back alike through both clients | **blocked, by den's command form**: GitHub accepted the deploy key and refused den's first push, `Invalid command: 'git-receive-pack' '<live>'`, through either client (below; R-bw03-7) |

**The live row, first take** (`tools/check-live` at `3beaf84`, the fixture
private and empty, the deploy key added with write access). `<live>` is the
row's redaction of the repository path:

```text
FAIL live-push the base push: exit 128, Invalid command: 'git-receive-pack' '<live>' |   You appear to be using ssh to clone a git:// URL. |   Make sure your core.gitProxy config option and the |   GIT_PROXY_COMMAND environment variable are NOT set. | fatal: Could not read from remote repository. |  | Please make sure you have the correct access rights | and the repository exists.
```

The login succeeded: GitHub answers `Invalid command` only after
authentication and an `exec` request. Its ssh service does not hand the
command to a shell: it parses it, and it takes the program as a bare word,
the form git sends (`git-receive-pack 'PATH'`). den quotes every remote word
(`'git-receive-pack' 'PATH'`), which a POSIX shell accepts, so den's rows
pass against the pinned `sshd`. `tools/diag-command-form` puts each form to
the fixture once, read only (stdin empty: receive-pack advertises and
stops, nothing is pushed). Its run at `a8acd52`:

```text
diag: ssh    den's form: exit 1, stdout 0 bytes (first pkt-len ''), stderr first line "Invalid command: 'git-receive-pack' '<live>'"
diag: ssh    git's form: exit 0, stdout 296 bytes (first pkt-len '0124'), stderr first line ''
diag: burrow git's form: exit 0, stdout 296 bytes (first pkt-len '0124'), stderr first line ''
```

So the pinned `ssh` fails den's form exactly as burrow does, and with git's
form both clients reach GitHub's receive-pack advertisement byte for byte
in size: key login, the session and `exec` work end to end between burrow
and GitHub. (A first run of the same probe from the lane's copy, before the
tool was committed, gave the same three verdicts, with the pinned `ssh`'s
advertisement one byte longer: GitHub's advertisement varies per
connection.) The change is den's (R-bw03-7); the live row waits on it, and
nothing on the fixture changed: it is still empty. Every log, record and
evidence file of these runs was scanned for the URL, the repository path
and name, the key's path and private key text: none.

**The measurement** (`tools/measure-den`, release burrow, at `292e148`, on a
quiet block of the Linux x86-64 host with its light lock held, so nothing
ran beside it): the 60-commit fixture is 811 objects in a 3,056 KiB pack;
five interleaved rounds per client, the minimum of each.

```text
measure-den: through burrow wall 9.950 s, cpu 1.725 s (den and the ssh it waits for)
measure-den: through ssh    wall 12.031 s, cpu 1.660 s (den and the ssh it waits for)
measure-den: burrow / ssh: wall 0.83x (margin 2.0x); cpu 1.04x (margin 2.0x)
```

Per round, CPU ran 1.73–2.96 s through burrow and 1.66–3.68 s through
`ssh`, wall 9.9–30.1 s and 12.0–45.2 s: the first rounds are the slow ones
for both. den's peak RSS was 1,335 MiB each way. burrow's own share is the
difference of the minima, about 0.07 s of CPU for 3 MiB, in line with
bw02's `cat` rate. The final record's `measure-den` step, in the PR body,
is the merge's number.

**Where constant time matters.** Unchanged from bw02: the Poly1305 tag
check through `wire.ct_eq`; the user key's signature is not constant time
(wolf-std's `curve25519.sign`). B4 adds no comparison of secret data.

**Rulings.**

- **R-bw03-1, no command.** burrow refused `shell_unsupported` before it
  connected, so a keyless `ssh -T git@github.com` never reached GitHub.
  (a) Refuse after the login, before any channel (implemented: a keyless
  probe is refused authentication as `ssh` refuses it; a login with no
  command still ends by name, DISCONNECT 11); (b) a `shell` request without
  a pty under `-T`, so `ssh -T git@github.com` with a key prints GitHub's
  greeting as `ssh` does; (c) keep the refusal before connecting, and drop
  the GitHub row. Recommended: (a); (b) when a lane wants interactive use on
  PAX (it amends R-bw02-10).
- **R-bw03-2, the live fixture.** The row needs a private, disposable
  repository with this lane's deploy key (write access), its URL in
  `BURROW_LIVE_SSH_URL` and the key's path in `BURROW_LIVE_SSH_KEY`, both
  set only in the lane's environment. The row writes only
  `refs/heads/burrow-live-base` (a fixed synthetic commit, pushed once and
  then a no-op, because GitHub makes an empty repository's first branch its
  default and refuses to delete it) and `refs/heads/burrow-live/<nonce>/…`,
  which it deletes at the end. (a) As above (implemented); (b) the fixture
  is seeded with a default branch first, and the row writes only its per-run
  refs. Recommended: (a).
- **R-bw03-3, den's rows in CI.** den's git oracle is built by den's own
  tools in den's image, whose packages are not snapshot-pinned, so a fresh
  runner is not held to reproduce its digest. (a) den's rows, GitHub, the
  live row and the measurements run in the local gauntlet only; CI's
  workflow is unchanged (implemented); (b) a CI job that builds den's oracle
  with den's own tools (a digest drift would turn it red for no fault of
  burrow's); (c) build git 2.56.0 from den's verified tarball in burrow's
  snapshot-pinned image, under a digest burrow pins. Recommended: (a) now,
  (c) as a follow-on lane if den's rows should run in CI.
- **R-bw03-4, the measurement's size.** den's clone holds the history in
  memory and its peak RSS grows faster than the history (above). (a) A
  fixture den clones comfortably, 60 commits and 8 incompressible 256 KiB
  files (implemented); (b) wait for a streaming clone in den. Recommended:
  (a), and the den issue below.
- **R-bw03-5, the client's home.** The pinned `ssh` reads `~/.ssh` from the
  passwd entry, burrow from `$HOME` (R-bw02-4). (a) Each row installs its
  `.ssh` as the container user's own and sets `HOME` to that directory, so
  den's argv stays exactly den's (implemented; the tools refuse to do it
  outside the pinned container); (b) pass `-F` and `UserKnownHostsFile` to
  the pinned `ssh` (not den's argv: not the same rows). Recommended: (a).
- **R-bw03-6, the resolver on PAX** (the track's "decide at bw03"). (a)
  No resolver in burrow: `~/.ssh/config`'s `HostName` (an address from
  GitHub's published `git` ranges) and `HostKeyAlias github.com` (no code;
  the px lane's first push uses it); (b) a minimal DNS A/AAAA client in
  burrow over UDP from `/etc/resolv.conf`; (c) wait for wolf-std#4's
  resolver. Recommended: (a) for the first PAX push, then (c); (b) only if
  std's resolver is far off, since it would be burrow's alone.
- **R-bw03-7, den's command form for GitHub.** GitHub's ssh service parses
  the command and refuses den's quoted program word (above). (a) den sends
  the program bare when it is a plain word and quotes it otherwise, the path
  always quoted, as git does; den's own rows are unchanged, since a shell
  sees the same argv; (b) burrow rewrites the command (no: burrow passes
  commands as `ssh` does, and the pinned `ssh` fails the same); (c) drop the
  live row. Recommended and accepted: (a), as den's change in its transport
  lane (vc22, red first: a plain service word sent bare, a non-plain
  override still quoted). bw03 then moves `burrow-den.toml` to that den
  commit, reruns den's rows and takes the live row.

**Issues** (none filed by this lane):

- den#63, filed from this note: a clone's peak RSS grows faster than the
  history. Through the pinned OpenSSH client, a bare clone of a fixed
  fixture peaked at 348 MiB (30 commits, about 500 objects), 954 MiB (60),
  3.3 GiB (120) and 12.2 GiB
  (300 commits, about 3,200 objects), so den's 10,000-object bound is out of
  reach in a 12 GiB container. Its wall time is also mostly not CPU (60
  commits: 21 s wall, 1.3 s CPU). The fixture is `tools/measure-den`'s
  (`--commits`, `--binaries`, `--clients ssh`).
- burrow: none. R-bw03-3's option (c), den's rows in CI from a git built in
  burrow's own snapshot-pinned image, is recorded as a follow-on.

## For the px lane (a draft of its first items)

B4's last row, a typed PAX session pushing to the fixture, is a px lane's.
What it needs from here:

1. **The binaries.** `tools/build --static` at burrow's merged head, in the
   pinned Ubuntu image; `tools/check-static` prints both sha256 digests and
   holds their shape (no interpreter, no dynamic section). Install
   `target/static/burrow` as `/bin/ssh` and `target/static/burrow-keygen` as
   `/bin/burrow-keygen`, held to those digests.
2. **Entropy.** burrow and `burrow-keygen` read `/dev/urandom` and refuse by
   name (`entropy_unavailable`) without it: the first row on PAX is
   `burrow-keygen -t ed25519 -f ~/.ssh/id_ed25519` succeeding, and its
   public line reading back with `-y`.
3. **The home.** `$HOME/.ssh` with that key (0600), a `known_hosts` with
   GitHub's published line (`ci/github-known-hosts`), and a `config`:
   `Host github.com`, `HostName` an address from GitHub's published `git`
   ranges, `HostKeyAlias github.com` (no resolver, R-bw03-6).
4. **The network.** TCP to port 22 from the console kernel, once PAX's
   network lane lands; then `ssh -T git@github.com` without a key, refused
   as `tools/check-github` holds it, is the first network row.
5. **The push.** den on PAX, `GIT_PROTOCOL` sent by `SendEnv`: a synthetic
   ref pushed to the fixture by a typed session and cloned back on Linux
   by `tools/check-live`'s steps, the deploy key made on PAX by
   `burrow-keygen` with only its public half leaving PAX.
6. **The cost.** One handshake and one push timed on PAX against the same
   on Linux, as evidence (wolf-std's checked-`int` X25519 and Ed25519 run
   on PAX's CPU there).

## Done-when

- [x] The prediction, committed first (`0a0b2ba`).
- [x] den's ssh rows through burrow-as-`ssh` against the pinned `sshd`, held
  byte for byte to the pinned `ssh`: clone over both URL forms, a port, a
  user, an alias, a checkout and three hard paths; incremental fetch; push
  over both forms; both leases; `--atomic` accepted and refused; a push den
  rejects and one the server rejects; the v0 refusal. 18 rows, both tiers;
  den unchanged.
- [x] GitHub's real server, read only, with no key: the published host key,
  and the refusal held to the pinned `ssh` (R-bw03-1, red first).
- [ ] The live push to the fixture and its clone-back, through both clients.
  The row and its self-test are green, the deploy key logs in, and git's
  command form reaches GitHub's receive-pack through both clients; den's own
  form is refused by GitHub, and the row waits on den's change (R-bw03-7).
- [x] For PAX: `tools/build --static`, its shape and digests, and the px
  lane's first items (above).
- [x] Measured: den's clone through burrow against the pinned `ssh`, with
  margins: CPU 1.04x, wall 0.83x, each held to 2x (the final record's
  `measure-den` step is in the PR body).
- [ ] The final-head gauntlet record, the plant record and the audit: in the
  PR body.
