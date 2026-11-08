# bw03b — the client, as people first meet it (burrow#5, the `-T` shell, #3)

## Prediction

Written 2026-11-08 04:05Z, at trunk `0d98ce9`, before any code and before
any run of the pinned OpenSSH for this lane, from `ssh(1)`,
`ssh_config(5)` and `sshd(8)` of the pinned 10.0p2 (the pages SOURCES
already lists, by sha256), RFC 4254 §6.5, burrow#5, and the record of
burrow#3's red run. Every behaviour of the pinned `ssh`, `sshd` and
GitHub's server below is a prediction; the evidence index records each
hit and miss.

Two rough edges, found the first time burrow was used by hand from PAX:

- With no configuration, burrow ignores the host keys pinned in
  `/etc/ssh/ssh_known_hosts` and says the host key is unknown, so PAX's
  README asks for a `~/.ssh/config` line naming the system file (burrow#5).
- `ssh -T git@github.com` ends in `shell_unsupported` after a good login,
  where OpenSSH prints GitHub's greeting. That command is how people check
  that GitHub took their key.

### 1. The system known_hosts files (burrow#5)

What the pages say:

- `ssh_config(5)`, `GlobalKnownHostsFile`: one or more files, separated by
  whitespace, for the global host key database; the default is
  `/etc/ssh/ssh_known_hosts`, `/etc/ssh/ssh_known_hosts2`.
- `ssh_config(5)`, `UserKnownHostsFile`: the default is
  `~/.ssh/known_hosts`, `~/.ssh/known_hosts2`; `none` ignores the user's
  files.
- `ssh(1)`: host keys are stored in `~/.ssh/known_hosts`, and
  `/etc/ssh/ssh_known_hosts` is "automatically checked"; new hosts are
  added to the user's file.
- `sshd(8)`, SSH_KNOWN_HOSTS FILE FORMAT: authentication is accepted "if
  any matching line has the proper key", and where the files conflict, "if
  valid information can be found from either file".
- `ssh_config(5)`, `StrictHostKeyChecking`: `accept-new` and `no` add new
  keys to the user's file.

What burrow will do:

- **Config:** `GlobalKnownHostsFile` joins the keywords `-o` and the config
  file take (first value wins, whitespace-separated, `~/` expanded as for
  the user's files). When it is unset, `/etc/ssh/ssh_known_hosts` and
  `/etc/ssh/ssh_known_hosts2` are the defaults, after the user's files.
- **The check** reads the user's files and then the global ones, and
  judges their lines together, as today: known when any line naming the
  host holds the presented key; changed only when some line names the host
  with another key and none holds this one; `@revoked` in any file
  refuses. So a user entry that matches wins over a changed system entry,
  and a matching system entry wins over a changed user entry, as `sshd(8)`
  says ("either file").
- **Appending** (`accept-new`, `no`) writes only to the first user file,
  never to a global one, and nothing is appended for a host the global
  file already knows.
- **The strict default is unchanged:** a host in neither file still
  refuses, `host_key_unknown`, with `ssh`'s two lines.
- **The changed-key banner** still names the first user file in its "Add
  correct host key in …" line; whether the pinned `ssh` also names the
  offending global line is measured, and burrow prints what it prints.
- **The pinned build's own default** sits under its configure prefix
  (`--prefix` only, so its system directory is the prefix's `etc`), not
  `/etc/ssh`. The rows hand the pinned `ssh` the man page's default with
  `-o GlobalKnownHostsFile=` where they compare, and `ssh -G` records the
  pinned build's default in the evidence. `GlobalKnownHostsFile none` is
  not in the page: measured, then burrow follows the measurement.

Rows, in `tools/check-session` on both tiers, each against its own pinned
`sshd`, and red at `0d98ce9` where marked:

| row | set-up | both clients, predicted |
|---|---|---|
| `kh-global-default` (red) | no option; the host's line only in `/etc/ssh/ssh_known_hosts`, written by the row as the container's root and removed after | connect, exit 0; the pinned `ssh` given the page's default by `-o` |
| `kh-global-known2` (red) | the line only in `/etc/ssh/ssh_known_hosts2` | connect, exit 0 |
| `kh-global-option` (red) | the line only in a file named by `-o GlobalKnownHostsFile=` | connect, exit 0 |
| `kh-global-config` (red) | the same file named by `GlobalKnownHostsFile` in a `Host` block | connect, exit 0 |
| `kh-neither` | the host in neither file | refused, exit 255, `host_key_unknown`, `ssh`'s last line `Host key verification failed.` |
| `kh-global-changed` (red) | another key for the host in the system file only | refused, exit 255, `host_key_changed`, `ssh`'s last line |
| `kh-user-over-global` | the user's file matches, the system file holds another key | connect, exit 0 |
| `kh-global-over-user` (red) | the system file matches, the user's file holds another key | connect, exit 0 |
| `kh-global-accept-new` (red) | `accept-new`, the host only in the system file | connect, exit 0, the user's file left empty by both |

`src/config_test.lu` gains the defaults, `-o`, the config keyword, first
value wins and `~/`; the existing known_hosts rows (hashed, several names,
`@revoked`, `@cert-authority`, `accept-new`, `no`, `HostKeyAlias`) stay
green unchanged.

### 2. A shell with no pty, for `-T` with no command

What the sources say:

- RFC 4254 §6.5: a `shell` request (want reply TRUE) starts the user's
  default shell; it carries nothing beyond the request header.
- `ssh(1)`: with no command, the server "gives the user a normal shell as
  an interactive session"; `ssh` requests a pty "only … when the client
  has one"; `-T` disables pty allocation; with no pty "the session is
  transparent and can be used to reliably transfer binary data".
- `ssh_config(5)`, `RequestTTY`: `auto`, the default, requests a TTY when
  opening a login session.

What burrow will do with no command:

- **With `-T`:** the session channel, the same `env` requests as for a
  command, then `shell` with want reply TRUE and no `pty-req`. The session
  loop is the one `exec` uses, unchanged: stdin, stdout and stderr as raw
  bytes, both windows, EOF and CLOSE in either order, `exit-status` as the
  exit code, `exit-signal` or no status as 255. A `CHANNEL_FAILURE` to the
  shell request is `shell_refused`, exit 255.
- **Without `-T`, stdin not a terminal:** the line the pinned `ssh` prints
  (predicted: `Pseudo-terminal will not be allocated because stdin is not a
  terminal.`), then the same shell as with `-T`.
- **Without `-T`, stdin a terminal:** refused by name before connecting,
  `pty_unsupported`, exit 255: an interactive shell needs a pseudo-terminal,
  which burrow does not allocate yet (B7), and the refusal says that `-T`
  runs the shell without one. The pinned `ssh` would allocate a pty here: a
  recorded difference.
- **Still refused by name:** `-t` (`option_unsupported`, as today) and
  `RequestTTY` (any value, R-bw03b-2). burrow never sends `pty-req`.
- `shell_unsupported` goes away; `cli-no-command` becomes the pipe row
  below.

Rows, against the pinned `sshd` unless marked, red at `0d98ce9` where
marked:

| row | set-up | predicted |
|---|---|---|
| `shell-stdin` (red) | `-T`, no command, `echo out; echo err >&2; exit 3` on stdin | both: stdout `out\n`, stderr `err\n`, exit 3, byte for byte; `sshd`'s log shows a `shell` request and no `pty-req` |
| `shell-binary` (red) | `-T`, a script on stdin that writes NUL, 0xff and invalid UTF-8 to both streams | both alike, byte for byte |
| `shell-greeting` (red) | `-T`, an `sshd` whose `ForceCommand` writes a greeting to stderr and exits 1, as GitHub's server does | both: exit 1, the same stderr bytes, empty stdout |
| `shell-signal` (red) | `-T`, a shell that kills itself with SIGTERM | both exit 255 |
| `shell-no-tty-pipe` (red; was `cli-no-command`) | no `-T`, stdin `/dev/null` | both print the pseudo-terminal line and exit 0 |
| `shell-terminal-t` (red) | `-T`, stdin a pty, `echo typed; exit 4` written to its master | both: stdout `typed\n`, exit 4, no `pty-req` in `sshd`'s log |
| `shell-terminal-refused` | no `-T`, stdin a pty | burrow: `pty_unsupported`, exit 255, and `sshd` logs no connection; the pinned `ssh` is not run (it would allocate a pty) |
| `cli-t-refused` | `-t` | `option_unsupported`, exit 255 |
| `hostile-shell-refused` (red; `tools/check-hostile`) | the scripted server answers `shell` with `CHANNEL_FAILURE` | `shell_refused`, exit 255 |

`src/channel_test.lu` gains the `shell` request's bytes and its refusal.
GitHub, read only: `github-no-key` stays as it is (both refused
authentication alike).

**The live row** (`tools/check-live`, `live-greeting`, from the fixture's
two variables only, SKIP by name without them): `ssh -T git@github.com`
with the fixture's deploy key, through burrow and through the pinned `ssh`.
Predicted for both: exit 1, empty stdout, and the same stderr bytes, one
line `Hi <name>! You've successfully authenticated, but GitHub does not
provide shell access.` A deploy key's greeting names its repository, so
the row compares the bytes in memory and prints and keeps only the line
with the name replaced, and the evidence scan covers it.

### 3. burrow#3, the nightly red (diagnosed before any code)

The scheduled run of 2026-11-06 at trunk `2077c87` (run 42221632377) went
red in its first Linux step, the oracle image's build. The snapshot
archive answered at about 126 kB/s, apt's default three retries were spent
on one package (`libgc1`, tried at 851 s, 1100 s and 1279 s, then
`Err: 502 Bad Gateway` at 1399 s), and the build failed after 21 minutes.
The toolchain and oracle staging steps then skipped; the next step built
the image again (successfully, another 24 minutes), and every row step
after it ran under `!cancelled()` and stopped at setup (`toolchain:
REFUSED — no wolf`, `FAIL setup no burrow binary`). The next nightly,
2026-11-07 at `0d98ce9` (run 42369416059), is green, with its Linux job
done in six minutes. Nothing in burrow was at fault: the image depends on
the snapshot archive being up at each run, since CI caches the toolchain
and the oracle but rebuilds the image every time. R-bw03b-3 decides what
to do.

### 4. The README and the stick

The README's state paragraph and command line say what `-T` does with no
command (GitHub's greeting, and the exit status the server sends), that
`/etc/ssh/ssh_known_hosts` is read, and `GlobalKnownHostsFile` joins the
keyword list. MAP's refusal list loses `shell_unsupported` and gains
`shell_refused` and `pty_unsupported`. This note drafts the ssh section of
the next PAX stick's README: the key, the hex route for reading a public
key line off PAX's console with `od`, and `ssh -T` to check it, with no
`~/.ssh/config` step.

### What changes, and what bw04 shares

bw04 (the server) works on burrow at the same time. This lane keeps to the
client's config, known_hosts and channel-request paths:

- `src/config/config.lu`, `src/config_test.lu`: the keyword, the defaults.
- `src/transport/transport.lu`: one field in `Options` (the global files)
  and the file loop in `check_known_hosts`; nothing else there.
- `src/channel/channel.lu`, `src/channel_test.lu`: a `shell` request beside
  `exec`, one request outstanding either way.
- `src/session/session.lu`: the plan says `exec` or `shell`.
- `src/burrow.lu`: the no-command branch and the terminal check.
- `src/refuse/refuse.lu`: one name, `shell_refused`, beside
  `exec_refused`.
- `tools/check-session`, `tools/check-hostile`, `tools/fakeserver.py` (its
  answer to a `shell` request), `tools/check-live`: the rows above.
- `README.md`, `docs/MAP.md`, `docs/SOURCES.md`, `CHANGELOG.md` and this
  note.

No gate step, CI file, pin or shared tool changes, so the footprint is
`module`. Nothing timed changes: the session loop is the one `exec` uses,
so `measure` is predicted within its margins as before.

### Rulings to recommend

- **R-bw03b-1, no command on a terminal without `-T`:** (a) refused by name
  before connecting (`pty_unsupported`), pointing at `-T`; (b) as (a) but
  after the login, like the old `shell_unsupported`; (c) start the shell
  without a pty anyway, as with `-T`. Recommended: (a). (c) would give a
  shell with no prompt and no line editing beyond the local terminal's,
  which reads as a hang; (b) spends a connection to say what is known
  before it.
- **R-bw03b-2, `RequestTTY`:** (a) still refused by name, any value, until
  B7; (b) take `no` as `-T` now. Recommended: (a), so the config surface
  grows with the feature.
- **R-bw03b-3, burrow#3:** (a) the named cause above, in this note and on
  the issue, and a follow-on for CI to keep the built image between runs
  (a cross-cutting change: the workflow and its cache key); (b) that
  change in a second, cross-cutting PR from this lane; (c) in this PR.
  Recommended: (a). More apt retries would not have helped (three were
  spent), the next nightly is green, and this PR stays `module` so it can
  merge on local evidence by the stick.
- **R-bw03b-4, the live greeting:** (a) compared in memory, printed and
  kept with the name replaced; (b) exit codes only. Recommended:
  (a).

## For the next stick: the ssh section of PAX's README (a draft)

To replace the SSH paragraph of PAX's README "Pushing to GitHub" once PAX
carries a burrow with this change. The `~/.ssh/config` step goes: burrow
reads `/etc/ssh/ssh_known_hosts`, where GitHub's published key is pinned.

> **SSH** goes through burrow, the org's ssh client, installed as `/bin/ssh`
> with `/bin/burrow-keygen`: den runs `ssh` from `PATH`. GitHub's published
> host key is pinned in `/etc/ssh/ssh_known_hosts`, which burrow reads as
> `ssh` does, after `~/.ssh/known_hosts`; a server answering for github.com
> with another key is refused by name (`host_key_changed`).
>
> 1. Make a key (or copy in an unencrypted Ed25519 key in OpenSSH's format,
>    mode 0600):
>
>    ```sh
>    mkdir -p ~/.ssh && chmod 700 ~/.ssh
>    burrow-keygen -t ed25519 -f ~/.ssh/id_ed25519
>    ```
>
> 2. Get its public line off PAX. The line is base64, whose `0` and `O`, or
>    `l`, `1` and `I`, are easy to misread off the console; in hex it has
>    only `0`–`9` and `a`–`f`:
>
>    ```sh
>    od -An -tx1 -v ~/.ssh/id_ed25519.pub
>    ```
>
>    Type the hex into a file on another machine and turn it back into the
>    line there (`xxd -r -p key.hex > id_ed25519.pub`). Check the copy by
>    its fingerprint: `burrow-keygen -l -f ~/.ssh/id_ed25519` on PAX and
>    `ssh-keygen -l -f id_ed25519.pub` on the other machine print the same
>    `SHA256:…`. Add the line to GitHub, as a deploy key or one of your
>    account's keys.
>
> 3. Check that GitHub takes it:
>
>    ```sh
>    ssh -T git@github.com
>    ```
>
>    prints `Hi <name>! You've successfully authenticated, but GitHub does
>    not provide shell access.` and exits 1: the 1 is GitHub's, and it is
>    what `ssh` gives too. `-T` matters: burrow has no pseudo-terminal yet,
>    so without it, at the console, burrow refuses by name
>    (`pty_unsupported`) before it connects.
>
> 4. Then clone, commit and push as usual:
>
>    ```sh
>    den clone -q git@github.com:OWNER/REPO.git repo
>    ```

## Forbidden

No ssh implementation's code or tests were read: no `.c` or `.h` file of
any OpenSSH release, nothing of dropbear, libssh, libssh2, Go's
`x/crypto/ssh`, paramiko, asyncssh, russh, thrussh, conch, PuTTY or
wolfSSH. The sources were the pages SOURCES lists (`ssh(1)`,
`ssh_config(5)` and `sshd(8)` of 10.0p2, by sha256, the sections this lane
read added there) and RFC 4254 §6.5. The pinned `ssh` and `sshd` were black
boxes: what they print, exit with and log. wolf-std's `io.is_terminal` and
boreutils' `od` options were read as the organisation's own code. Keys are
made per run; private keys stay in 0700 run directories or the container
user's own `~/.ssh`, which each row replaces and clears, and the evidence
copies are scanned for key files and private key text. The live rows read
the fixture's URL and key path only from their two variables, set inside
each job from the lane's 0600 files on the Linux host; GitHub's greeting,
which names the fixture's repository, has its name replaced before it is
compared aloud, printed or kept. Every take ended with a scan of its
checkout and the lane's directory on that host for the URL, the
repository's path and names, the key's path and the key's private lines,
printing counts only. The system known_hosts rows write
`/etc/ssh/ssh_known_hosts` only inside the pinned container, as its root,
and remove it. The plant branch has no PR and no CI run.

## Inputs verified

Footprint: module

- The toolchain and OpenSSH pins are unchanged from trunk `0d98ce9` (wolf
  0.2.37, lupin 0.1.59, std `5b3a599`, OpenSSH 10.0p2), each held to its
  digest by `tools/fetch-toolchain` and `tools/fetch-oracle` in every take;
  den at `burrow-den.toml`'s `ac2332b`, held by `tools/fetch-den`.
- No gate step, CI file, pin or shared tool changes. The paths touched are
  `src/`, `tools/check-session`, `tools/check-hostile`,
  `tools/fakeserver.py`, `tools/check-live`, the README, MAP, SOURCES,
  CHANGELOG and this note.
- The pinned build's own `GlobalKnownHostsFile` default, from `ssh -G`:
  `/work/burrow/.oracle/openssh-10.0p2/etc/ssh_known_hosts` and `…2`, its
  configure prefix's `etc`, as predicted. The rows hand it the page's
  default, `/etc/ssh/ssh_known_hosts /etc/ssh/ssh_known_hosts2`, by `-o`.

| hardware | used for |
|---|---|
| Linux x86-64 desktop, i7-12700KF, 46 GiB | every Linux take: a six-CPU block under both of its lock names, the pinned container capped at 12 GiB, taskset inside; the final record with the block's light lock held too (its perf steps) |
| Apple silicon laptop, macOS arm64 | builds and the unit rows behind the build lock; editing, commits and pushes |

Commits, in order (the row first wherever a row exists):

- `20a8758` the prediction.
- Rows, red first: `83ceb9b` `config_test` (the global files, `-T`,
  `RequestTTY` refused); `f2eca54` `channel_test` (the shell request);
  `e08e83c` the system known_hosts rows; `a0829c5` the shell rows;
  `e7f1d92` the scripted server's answer to a shell request and `6aff61b`
  `shell-refused`; `88704f7` `live-greeting`.
- The fixes: `b5e361c` config; `abb40f4` transport; `5326bcd` refuse;
  `a3fa697` channel; `a9b4d6d` session; `332120b` burrow's no-command
  branch and the terminal check.
- After the first green takes: `793bc19` `shell-no-tty-when`; `49169a5`
  `wolf fmt` on the two test files; `1dbc6bd` `shell-terminal-refused`
  reads only the log burrow's run adds; `a32b8bd` the refusal rows keep
  `ssh`'s whole stderr; `5db0b30` `kh-global-none`.
- `b2ace5e` README (README-only), `5a47aaf` MAP, `79eeae1` SOURCES,
  `fcfd80e` CHANGELOG; and this note.

## Evidence index

**Red at the rows' head** `88704f7` (burrow's code still trunk's), two
takes on the Linux host, each ended by the secrets scan with no hit:

- `unit`: `channel_test.lu` and `config_test.lu` do not compile
  (`channel.shell_msg` and `global_known_hosts` do not exist); the other
  twelve files pass on all three tiers.
- `session`: 15 of 61 rows fail, exactly the predicted reds:
  `kh-global-default`, `kh-global-known2` (`host_key_unknown`: no global
  file read), `kh-global-option`, `kh-global-config` (the keyword refused,
  `option_unsupported` and `config_unsupported`), `kh-global-changed`
  (`host_key_unknown` where `host_key_changed` is wanted),
  `kh-global-over-user` (`host_key_changed`), `kh-global-accept-new` (both
  clients connect, but burrow appends the line `ssh` does not), and every
  shell row (`shell_unsupported`), `shell-terminal-refused` included (no
  `pty_unsupported`). `kh-neither`, `kh-user-over-global` and
  `cli-t-refused` pass at the base, as predicted.
- `hostile`: `shell-refused` red (`shell_unsupported`).
- `live`: `live-push` passes; `live-greeting` red, burrow 255 with
  `shell_unsupported`, the pinned `ssh` exit 1 with GitHub's greeting on
  stderr (its name replaced in memory).

**Green at the fixes.** At `332120b` the take stopped at `fmt` (the two
test files were not canonically formatted: `49169a5`). At `49169a5` every
row passed but `shell-terminal-refused`, whose check read the readiness
probe `oraclelib` makes before any row as a connection (`1dbc6bd`). At
`1dbc6bd`: `fmt`, `build`, `unit` (14 files, three tiers), `session` and
`session-release` (62 rows each), `hostile` and `hostile-release` (9
each), `github` (2) and `live` (2) all exit 0, and the scan finds nothing.

| prediction | measured |
|---|---|
| the host only in a system file connects, by default, by `-o` and by a `Host` block | hit, both clients, both tiers (`kh-global-default`, `-known2`, `-option`, `-config`) |
| a host in neither file refuses with `ssh`'s lines | hit (`kh-neither`), as before the change |
| a changed key in the system file refuses, `host_key_changed` | hit; `ssh`'s last line `Host key verification failed.`, exit 255 |
| a match in either file wins over another key in the other | hit both ways: the pinned `ssh` connects with the user's file matching and the system's changed, and with the system's matching and the user's changed (`kh-user-over-global`, `kh-global-over-user`), as `sshd(8)` says |
| `accept-new` appends nothing for a host the system file knows | hit, both clients (`kh-global-accept-new`) |
| the pinned build's default is under its prefix | hit: `ssh -G` gives `.oracle/openssh-10.0p2/etc/ssh_known_hosts` and `…2` |
| `-T` runs the shell with no `pty-req`, byte-clean, the exit mapped | hit (`shell-stdin`, `shell-binary`, `shell-env`, `shell-signal`; `sshd` logs a shell request and no `pty-req`) |
| a greeting then exit 1, stdin left open | hit: both exit 1 with the same stderr bytes and empty stdout (`shell-greeting`) |
| no `-T`, stdin a pipe: `ssh`'s line, then the shell | hit, with a detail not predicted: the line ends in CR LF (`…not a terminal.\r\n`), and burrow now writes the same bytes |
| when that line comes | measured, not predicted: the pinned `ssh` prints it before connecting (with nothing listening it is its first line), and so does burrow (`shell-no-tty-when`) |
| `-T` at a terminal runs the shell, reading what is typed | hit (`shell-terminal-t`: both exit 4, stdout `typed\n`, no `pty-req`) |
| no `-T` at a terminal: `pty_unsupported` before connecting | hit (`shell-terminal-refused`: exit 255, the refusal names `-T`, and `sshd` logs no connection during burrow's run) |
| a refused shell request is `shell_refused` | hit (`shell-refused`; the scripted server saw one request, `shell`) |
| GitHub, with the fixture's key: exit 1, empty stdout, the greeting on stderr, the same bytes through both clients | hit (`live-greeting`) |
| GitHub without a key: refused authentication alike | hit, unchanged (`github-no-key`) |
| `measure` within its margins | in the final record |

**Not predicted, recorded:** the pinned `ssh` ends its own diagnostic
lines with CR LF when stderr is a pipe (`ssh: connect to host … Connection
refused\r\n`, in `shell-no-tty-when`'s evidence), where burrow's end in LF.
The refusal rows compare by line, so this is not a row's failure; burrow
matches the bytes only for the pseudo-terminal line, the one a shell row
compares byte for byte. Matching the rest is a follow-on, listed below.

## Rulings

- **R-bw03b-1 (a):** no command at a terminal without `-T` is refused by
  name before connecting (`pty_unsupported`), pointing at `-T`.
- **R-bw03b-2 (a):** `RequestTTY` stays refused by name, whatever its
  value, until B7.
- **R-bw03b-3 (a):** burrow#3's cause is named on the issue (the two runs,
  the snapshot archive's outage, the next nightly green), and keeping the
  built image between CI runs is burrow#6, a cross-cutting follow-on.
- **R-bw03b-4 (a):** the live greeting is compared in memory and printed
  and kept only with its name replaced.

## Issues

- burrow#5: closed by this change, at the merge.
- burrow#3: its cause is named; the nightly of 2026-11-07 is green.
- burrow#6 (filed by this lane): keep the built oracle image between CI
  runs.
- To file: burrow's own diagnostic lines end in LF where the pinned `ssh`'s
  end in CR LF on a pipe; and `docs/MAP.md`'s PAX table still says PAX
  has no resolver, where PAX's README now says names resolve as on Linux
  (a stale line this change does not own).

## Done-when

- [x] The prediction committed before the first change (`20a8758`).
- [x] The system known_hosts files read by default, `GlobalKnownHostsFile`
  in `-o` and the config, the strict default unchanged; each row red first.
- [x] The shell with no pty under `-T` (and on a pipe), byte-clean, the exit
  mapped; `-t`, `RequestTTY` and a terminal without `-T` refused by name;
  each row red first, and the live greeting from the fixture's environment.
- [x] burrow#3 diagnosed and its cause named (R-bw03b-3).
- [x] The README, MAP, SOURCES and CHANGELOG refreshed; the stick's ssh
  section drafted above.
- [ ] The final gauntlet green at the head, the plant red by name at
  `kh-global-default`, the macOS record, the PR and the audit: in the PR.
