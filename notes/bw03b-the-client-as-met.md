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
