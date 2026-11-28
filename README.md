# burrow

An ssh client and server written in [wolf](https://github.com/wolffe-lang/wolf-lang):
a minimal, OpenSSH-compatible `ssh`, an Ed25519 `burrow-keygen` and a
server for commands, `burrowd`, static for PAX and the same on Linux and
macOS. Its first user is
[den](https://github.com/wolffe-lang/den), which starts an `ssh` program
through an argv vector and speaks git's protocol v2 over its pipes; its
second is a person typing `ssh` on PAX.

**State: B5, the server for commands** ([burrowd](#burrowd-the-server-for-commands), below), with passwords from `/etc/shadow` for B6, the server on PAX, and (B7) a terminal for an interactive session, each program in a session of its own. **B4, den over burrow:** burrow connects, verifies the server's host
key against known_hosts (the user's files and then the system's,
`/etc/ssh/ssh_known_hosts` and `/etc/ssh/ssh_known_hosts2`, as `ssh` reads
them; plain and hashed entries; strict by default, `accept-new` and `no` as
`ssh` has them), logs in with an Ed25519 key in OpenSSH's own format, runs
one command with stdin, stdout and stderr as raw bytes, and exits with the
command's status. Linked as `ssh` on PATH, it
carries [den](https://github.com/wolffe-lang/den)'s clone, fetch and push
over `ssh://` and scp-like URLs byte for byte as the pinned OpenSSH client
does, and a static build is ready for PAX. It takes the command line den
passes:

```sh
ssh [-TtVv] [-e escape_char] [-F configfile] [-i identity_file] [-l login_name] [-o option] [-p port] [--] destination [command [argument ...]]
burrow-keygen -t ed25519 [-q] [-f path] [-C comment] [-N ""]
burrow-keygen -y -f path        # the public line
burrow-keygen -l -f path        # the fingerprint
```

`-V` prints `burrow_<version>, burrow (wolf)` on stderr and exits 0, as
`ssh -V` prints its one line, before any file is read or connection made.

`-o` and `~/.ssh/config` (`Host` and `Match host` blocks) take `BatchMode`,
`ClearAllForwardings`, `ConnectTimeout`, `ControlMaster no`, `ControlPath
none`, `EscapeChar`, `GlobalKnownHostsFile`, `HashKnownHosts`, `HostKeyAlias`,
`Hostname`, `IdentitiesOnly`, `IdentityFile`, `Port`, `RekeyLimit`,
`RequestTTY`, `SendEnv`, `SetEnv`, `StrictHostKeyChecking`, `UpdateHostKeys
no`, `User` and `UserKnownHostsFile`. Anything else is refused by name, never
ignored.

With no command, burrow starts the login shell. Under `-T`, or with stdin
not a terminal, it asks for no pseudo-terminal, as `ssh -T` does: stdin,
stdout and stderr pass as raw bytes, and burrow exits with the shell's
status. So `ssh -T git@github.com` with a key GitHub knows prints GitHub's
greeting (`Hi …! You've successfully authenticated, but GitHub does not
provide shell access.`) and exits 1, the status GitHub sends, as `ssh` does;
without a key it is refused authentication as `ssh` refuses it. Without `-T`
and with stdin not a terminal, burrow prints the line `ssh` prints
(`Pseudo-terminal will not be allocated because stdin is not a terminal.`)
and does the same.

At a terminal, with no command, burrow asks for a pseudo-terminal, as `ssh`
does; `-t` asks for one for a command when stdin is a terminal, `-tt`
always (`RequestTTY` `auto`, `yes`, `force`; `-T` is `no`). The request
carries `TERM`, the window's size and the local terminal's modes. While the
session holds the pty, the local terminal is raw: the remote side echoes and
edits the line, ^C, ^\ and ^Z reach it as bytes, and each change of the
window's size is sent on. The terminal is put back as it was found however
the session ends, and `Connection to HOST closed.` follows, as `ssh` writes
it. The escape character (`~` unless `-e` or `EscapeChar` say otherwise,
`none` for none) is read at the start of a line: `~.` ends the connection,
`~?` lists the escapes, and `~~` sends one `~`. `ssh`'s other escapes are
refused by name (`escape_unsupported`). A server that refuses the pty gets
`ssh`'s line for it; where `-t` or `-tt` asked for it, burrow then gives up
as `ssh` does, and a login shell goes on without one. As `ssh` does by
default (`ObscureKeystrokeTiming`), burrow sends what is typed on a fixed
20 ms grid and, with nothing to send on a tick, a PING of the same size, for
one to three seconds after the last key, so the packets do not give away
when keys were pressed; `ObscureKeystrokeTiming no` turns it off, and
`interval:N` sets the grid. There is no agent or forwarding
([MAP](docs/MAP.md)).

## burrowd, the server for commands

`burrowd` serves commands over ssh, the server's half of the same profile:
the pinned OpenSSH `ssh`, burrow, and git over either log in to it as they
log in to `sshd`. It takes `sshd(8)`'s flags that mean something for it,
and a subset of `sshd_config(5)`:

```sh
burrowd [-DeqTtV] [-E log_file] [-f config_file] [-g login_grace_time]
        [-h host_key_file] [-o option] [-p port]
```

`-D` changes nothing (burrowd never detaches), `-e` logs to stderr, `-E`
appends to a file, `-t` checks the configuration and the host key, `-T`
prints the effective settings in `sshd -T`'s shape. The configuration
(default `/etc/burrowd/burrowd_config`; when it is absent the defaults
stand) takes `AcceptEnv`, `AuthorizedKeysFile` (`%h`, `%u`, `%%`),
`HostKey`, `ListenAddress`, `LoginGraceTime`, `MaxAuthTries`,
`MaxStartups`, `PasswordAuthentication` (`no` unless a line says `yes`),
`PermitRootLogin no`, `PermitTTY` (`yes` unless a line says `no`, as
`sshd`), `PidFile`, `Port`, `RekeyLimit`, `SetEnv`,
`StrictModes`, and the one value burrowd has of the keywords for what it
does not do (`KbdInteractiveAuthentication no`, `PermitEmptyPasswords no`,
`DisableForwarding yes`, `PrintMotd no`, `PrintLastLog no` and the rest). Any other value, or any other
`sshd_config(5)` keyword, is `config_unsupported`; a keyword that page does
not list is `config_unknown`; either stops burrowd at start, exit 1.

What it does, and what it refuses:

- **Host key:** one Ed25519 key made by `burrow-keygen` or `ssh-keygen`
  (default `/etc/burrowd/ssh_host_ed25519_key`), required, checked for its
  mode and owner as `sshd` checks them, its fingerprint printed at start in
  `ssh-keygen -l`'s shape. burrowd never makes a key.
- **Listening:** loopback (`127.0.0.1` and `::1`) unless `ListenAddress`
  names another address; listening wider is a configuration line written on
  purpose.
- **Authentication:** public keys only (`ssh-ed25519`), from
  `authorized_keys` as `sshd(8)` documents the file, with StrictModes on:
  a writable home, `~/.ssh` or file, or one another user owns, admits no
  key. Of the options, `command="…"` is honoured (the client's command in
  `SSH_ORIGINAL_COMMAND`); `no-pty` and `restrict` refuse that key a pty and
  `pty` grants it again, read left to right as the pinned `sshd` reads them;
  the restrictions burrowd enforces anyway (`no-port-forwarding` and the
  like) are taken; a line with any option
  burrowd cannot enforce (`from=`, `environment=`, `expiry-time=` and the
  rest) admits nothing. **Root is refused, always**, alike to every other
  refusal (`Permission denied (publickey).`): root logs in as a user and
  runs `sudo`.
- **Passwords, only where the configuration says `PasswordAuthentication
  yes`:** the account's password from `/etc/shadow`, as crypt(5)'s `$7$`
  (scrypt, wolf-std's), the form PAX's `passwd` writes; another method
  (a stock Ubuntu account's `$y$`, `$6$` and the rest) is refused by name,
  as are an empty, unset (`*`) or expired password, and a `$7$` string
  dearer than N = 2^17, r = 8, p = 1. Every failure counts toward
  `MaxAuthTries` and costs the same one hash, whether or not the account
  exists, so the time to an answer says nothing about which accounts do.
  One password is checked at a time across the server, in a process of its
  own, so a hundred connections cost one hash's memory. burrowd changes no
  password: a client's change request is refused, and an expired password
  is changed at the console with `passwd`. It needs burrowd run as root
  (only root reads `/etc/shadow`); otherwise the line stops it at start.
- **Locked and expired accounts:** as `sshd(8)` describes it, an account
  whose `/etc/shadow` password starts with `!` (`passwd -l`), or whose
  expiry date has passed, is refused by every method, a key included. An
  account whose field is `*`, or that has no line, may still log in with a
  key.
- **The session:** one session channel and one program on it: the
  client's command (`exec`), or with no command the account's login shell
  (`shell`; `-sh` for `/bin/sh`), on a pty when the client asked for one.
  With no pty its stdin, stdout and stderr are raw bytes, and its exit
  status or signal goes back. A forced command
  runs in the shell's place too. `env` accepts `GIT_PROTOCOL` only.
  `SetEnv NAME=VALUE …` sets variables in every session, as `sshd_config(5)`
  describes and the pinned `sshd` does: they replace burrowd's defaults
  (`HOME`, `USER`, `LOGNAME`, `PATH`, `MAIL`, `SHELL`) and an accepted
  `GIT_PROTOCOL`, never `SSH_CONNECTION` or a forced command's
  `SSH_ORIGINAL_COMMAND`. Only the first `SetEnv` line counts, and in it the
  first value of a name; a malformed line, the first or a later one, stops
  burrowd at start, `config_unsupported` by file and line. A subsystem,
  X11, the agent and every forwarding are refused by name, and the program
  still runs where `sshd` runs it. `XDG_RUNTIME_DIR` is set to
  `/run/user/UID` when that is a directory (not a link) owned by the
  account with mode 0700, and left unset otherwise, as PAX's console login
  and a Linux login's PAM session set it; the pinned `sshd`, built with no
  PAM, sets none (one of the [named differences](docs/MAP.md#where-burrowd-differs-from-the-pinned-sshd-by-name)).
- **A terminal** (RFC 4254 §6.2, §6.7, §8): a `pty-req` is granted where
  `PermitTTY` and the key allow it. The pty takes the client's size and
  every terminal mode it sends that the host has (the rest passed over, as
  `sshd` passes them over); the program leads a session of its own with the
  pty's slave as its controlling terminal and its stdin, stdout and stderr,
  with `TERM` (when the client sent one) and `SSH_TTY` set. Line editing,
  echo, Ctrl-C, Ctrl-Z and job control are the terminal's, as through
  `sshd`; `window-change` resizes it (SIGWINCH). The session ends when the
  program does: what the pty still holds is sent, then the status, and the
  pty is closed, which hangs up anything the program left on it. A refused
  pty is named (`pty_refused` by `PermitTTY no` or the key, `pty_failed`
  when the host gives none, `pty_malformed`, `pty_twice`, `pty_late`), and
  a shell after it says on its first line of stderr that it has no
  terminal. A pty's session is written to utmp and wtmp at its start and
  end, and a refused password to btmp, as `sshd` writes them (the monitor,
  root, writes them), so `who`, `last` and `lastb` list them; there is no
  lastlog entry, motd or last-login line.
- **A session of its own:** every program, on a pty or not, leads a session
  of its own, as `sshd` gives it; with no pty it has no controlling
  terminal (`/dev/tty` does not open), so nothing it does reaches the
  terminal burrowd was started from. burrowd leads a process group of its
  own at start (unless a person runs it in a terminal's foreground). Where
  PAX starts burrowd at boot from the console's session, no program run over
  ssh reaches the console. Every program also starts with the default
  disposition of every signal burrowd does not own, whatever burrowd was
  started with (a shell's `burrowd … &` ignores SIGINT and SIGQUIT).
- **Limits:** `LoginGraceTime` (120 s), `MaxAuthTries` (6) and `MaxStartups`
  (10:30:100), as `sshd` has them.
- **Memory:** the listener keeps the memory it started with. Each pass of
  its loop runs in a region freed at the pass's end, and an ended connection
  is taken out of its table in place, so it does not grow with idle time or
  with connections (rows hold it within 64 KiB over a minute idle and 32 KiB
  over three hundred logins, 80 KiB on macOS; before, it grew about 3 KiB a second idle and about 2 KiB
  a connection, and every new session's processes started at its size).
- **The log:** one line per connection: the time (UTC), the client's
  address and port, the user, the key's fingerprint (`key password` for a
  password login), the outcome by name and the exit status. Never a private
  key, a password, the command, an environment value or a byte of the
  session.

**Privilege separation.** On Linux (and on PAX, as B6 brings it there),
burrowd running as root never parses a byte from the network as root:

```text
burrowd (root, the listener)       never holds the host key's private half
 └─ per connection: monitor (root) reads authorized_keys and /etc/shadow; checks modes and the signature; logs
     ├─ worker (account burrowd)   every byte before authentication; asks the monitor
     ├─ holder (root, holds nothing) then the session, with the user's uid, gid and groups
     │   └─ the program             the user's shell: -c and the command, or a login shell
     └─ checker (root, one at a time across the server) one password's hash, then exits
```

The worker and the holder are forked before the monitor reads the host
key, so neither ever holds it; the session takes the user's ids with no
way back. It needs an unprivileged account named `burrowd` (burrowd refuses
to start as root without it). On PAX the user and group IDs are enforced
for honest programs but are not yet a boundary against an attacker, so
there this separation is defence in depth, not a guarantee.

**macOS, and burrowd without root.** wolf-std cannot change a process's
user on macOS, so there burrowd serves only the user who runs it, and
refuses to start as root (`privileges_unsupported`). Run without root on
Linux, it does the same: the same processes, all as that user.

## What it speaks, and what it refuses

burrow speaks one modern profile, the one every primitive in wolf-std
already covers:

| layer | burrow speaks | source |
|---|---|---|
| key exchange | `curve25519-sha256` | RFC 8731 |
| host key | `ssh-ed25519` | RFC 8709 |
| cipher | `chacha20-poly1305@openssh.com` | OpenSSH `PROTOCOL.chacha20poly1305`, RFC 8439 |
| user key | `ssh-ed25519` | RFC 8709, RFC 4252 |

Anything outside that list is refused by name, never negotiated down to.
There is no RSA (`ssh-rsa`, `rsa-sha2-*`) at first.

The security posture:

- **Host keys:** strict `known_hosts` checking is the default. An unknown or
  changed host key refuses the connection, by name.
- **Strict kex:** OpenSSH's `kex-strict-c-v00@openssh.com` (the Terrapin
  mitigation) is always offered, and a server without it is refused unless a
  flag says otherwise.
- **Key material:** private keys never appear in logs or test rows. Test keys
  are generated per run.
- **Comparisons:** MAC and tag comparisons are constant time.

**No post-quantum key exchange yet** (burrow#14). OpenSSH clients newer
than the pinned 10.0p2 warn on every connection to a server that offers no
post-quantum key exchange, burrowd among them. OpenSSH 10.2p1, run against
burrowd, prints three lines on stderr:

```text
** WARNING: connection is not using a post-quantum key exchange algorithm.
** This session may be vulnerable to "store now, decrypt later" attacks.
** The server may need to be upgraded. See https://openssh.com/pq.html
```

The warning is about the future: someone who records the session today
could decrypt it once a quantum computer can break X25519. The session is
otherwise encrypted and authenticated as before: `curve25519-sha256`, the
server's Ed25519 host key checked against `known_hosts`, and
`chacha20-poly1305@openssh.com`. That client's `ssh_config(5)` documents
`WarnWeakCrypto`; `-o WarnWeakCrypto=no-pq-kex` turns off this one warning
and leaves the others on. The pinned 10.0p2's `ssh_config(5)` has no
`WarnWeakCrypto`.

## Build and test

The toolchain and the oracle are pinned by digest (`wolf-toolchain.toml`,
`burrow-oracle.toml`); every tool refuses a binary that does not match.

```sh
tools/fetch-toolchain                 # wolf 0.2.39, lupin 0.1.61, the std at its pin
tools/build --all                     # target/{native,release}/{burrow,burrow-keygen,burrowd}, rows/
tools/check-test                      # src/*_test.lu: checked machine, native, lupin
tools/in-container tools/fetch-oracle # OpenSSH 10.0p2, built in the pinned image
tools/in-container tools/fetch-den    # den at its pin (burrow-den.toml), built by its own tools
tools/gate                            # the whole gauntlet, in the container
```

`tools/check-test` first tests its own result handling with an isolated fake
compiler, then validates the complete pinned compiler report against every
`src/*_test.lu` file and its summary. A native fallback is retried checked-only;
only an executed passing observation counts. Unsupported, missing or malformed
observations fail the gate even when the compiler exits zero. Native and lupin
results remain independent. The monitor's six verification assertions run in
separate test files under the unchanged checked step budget; no assertion or
vector is removed. Original stdout, stderr and retry JSON are kept separately
under `target/tests/`.

`tools/gate` runs every step and prints each one's `START` and
`END … exit=N`, stopping at the first that fails: the toolchain and oracle
digests, the CI planner's tests, the vectors (`tools/vectorgen.py`
regenerates `src/kexvec` byte for byte from the RFCs, `tools/nistvec.py`
`src/sha1vec` from NIST's vectors), that the documents name no internal
work-item id (`tools/check-public-text`), formatting, both compiler tiers, the
version each program prints, the release path's dry run
(`tools/check-release --dry`, below), the unit rows, the transport, session and hostile-peer rows on both tiers, the
server's rows and its hostile-client rows on both tiers, git through
burrowd, den over burrow on both tiers, GitHub read only, the live push,
the static build, and the three measurements against the pinned `ssh` and
`sshd`. A step that cannot
run where the gauntlet runs (GitHub unreachable, the live variables unset)
prints `SKIP <step> reason=…` at column 0 instead: never a pass.

The transport rows (`tools/check-transport`) hold burrow to the pinned
`sshd`, each row starting its own on a loopback port with keys made for that
run: the handshake, the host key fingerprint, banner lines, refusals by name
for unknown and changed host keys, a bad signature, every negotiation
failure, a stripped strict-kex indicator, injected messages under strict
kex, a flipped tag byte, re-exchanges started by either side under traffic,
and a byte comparison of the plaintext handshake with what the pinned `ssh`
sends. burrow has no strict-kex waiver on any tier: `--no-strict-kex` is an
unknown option, and only the row program `rows/kexprobe` (never installed)
waives it, to show a stripped indicator still breaks the exchange hash.
Each test option (`--test-traffic`, `--test-preauth`, `--test-window`)
changes load or window size only, and a row holds each one inert for
security: with the option given, strict kex, the host key checks,
negotiation, the login and the key file's mode are refused as without it,
and no private key line reaches the output. The session rows (`tools/check-session`) hold authentication, keys,
known_hosts, the session and the command line to the pinned `sshd`, `ssh`
and `ssh-keygen`: keys made by either tool, refused keys and servers, the
banner, appended known_hosts lines read by the pinned `ssh`, the system
known_hosts files (found only there, changed there, against the user's file
either way, under `accept-new`, by default, by `-o` and by `Host` block), 64
MiB through `cat` compared by digest, interleaved stdout and stderr, exit
codes and signals, `SendEnv`, the shell with no pty (a script on stdin, raw
bytes, a greeting then an exit status as GitHub's server sends them, a
signal, stdin a pipe and stdin a terminal), den's exact argv,
`~/.ssh/config`, and each refusal's exit code and line against `ssh`'s. The hostile-peer rows
(`tools/check-hostile`) run burrow against a scripted server that never
adjusts its window, sends data after CLOSE, oversize packets and data, an
unrequested USERAUTH_SUCCESS, an `exit-status` for another channel, `x11`
and agent channel opens, a refused shell request, and an IGNORE or a stream of PINGs while it waits for
burrow's input. `tools/measure-session` holds login to first
byte and `cat` throughput to stated margins against the pinned `ssh`;
`tools/measure-handshake` compares the cost of a handshake (evidence only).

**den over burrow** (`tools/check-den`, B4): den, at the commit
`burrow-den.toml` pins and built by its own tools at its own toolchain pin
(`tools/fetch-den`, which also holds den's git oracle to its digest), runs
each of its ssh rows twice, with PATH's `ssh` a link to burrow and then to
the pinned `ssh`, against one pinned `sshd` with `AcceptEnv GIT_PROTOCOL`
and den's own fixture shape (service wrappers into den's pinned git,
which pass on only the `GIT_PROTOCOL` that arrived). Clone over `ssh://`
with a user and a port, through a `Host` alias, scp-like with and without a
user, a checkout, paths with a space, a quote and a semicolon; incremental
fetch; push over both forms; `--force-with-lease` stale and matching;
`--atomic` accepted and refused; a push den rejects and one the server
rejects; and the v0 refusal. Each compares den's exit code, stdout and
stderr byte for byte, the local and server repositories (refs, objects,
fsck) and what each service received. Four more rows record the command
`sshd` is sent (an `authorized_keys` `command=`, which sees it in
`SSH_ORIGINAL_COMMAND`) and hold it to git's form, `git-upload-pack
'PATH'`: the program word bare when it is plain and quoted when it is not,
which is what GitHub's ssh service accepts. `tools/check-github` holds burrow
to the pinned `ssh` against GitHub's real server, read only and with no
key: GitHub's published host key, and the same refusal. `tools/check-live`
pushes to a live fixture and clones it back through both clients, from
`BURROW_LIVE_SSH_URL` and `BURROW_LIVE_SSH_KEY` alone (it never prints
either, and removes its work files, whose clones name the URL, when it
ends), holds `ssh -T git@github.com` with the fixture's key to the pinned
`ssh` (the greeting compared byte for byte, and kept only with its name
replaced), and runs the push's steps against a loopback `sshd` as a
self-test.
`tools/check-static` holds the static binaries' shape and runs den rows
through the static `burrow`, and server rows through the static `burrowd`;
`tools/measure-den` compares den's clone through burrow with its clone
through the pinned `ssh`.

**burrowd held to `sshd`** (B5): each row of `tools/check-server` starts
burrowd and the pinned `sshd` side by side on loopback ports, with one host
key, one account and one `authorized_keys` made for the run, and runs the
pinned `ssh` against both with the same arguments: the version, the
offered and refused algorithms, a re-exchange under traffic, the host key's
mode, owner and fingerprint, a host key made by `burrow-keygen`, keys
accepted and refused (StrictModes on the home, `~/.ssh` and the file, an
unlisted key, root, an unknown user, MaxAuthTries, LoginGraceTime, a
forced command, an option burrowd cannot honour), 64 MiB through `cat`,
interleaved streams, exit codes and signals, the session's environment
(with and without `SetEnv`, whose `-T` lines and refusals are held to
`sshd`'s too) and `id`, every refused request, the login shell with no pty (a script on
stdin, its `$0`, a forced command in its place, `ssh host` at a terminal
with the pty refused, and a slow answer while the client's keystroke-timing
PINGs arrive), and (B7) a terminal: `ssh -tt` with and without TERM, the
size and the whole `stty -a` from a client's terminal and a window change,
a full-screen program reading its size and a key, Ctrl-C to a trap and to a
program it ends, the login shell at a terminal, the session's end with a
child left on the pty, 20000 lines before the end, the client's end of
input, `no-pty`, `restrict` and `pty` on a key, and the program's session
of its own; MaxStartups, `-T`'s limits, the log line and
the processes' users; and passwords, each run's own, given to the
pinned `ssh` by its askpass program's environment: the right one, a wrong
one, wrong then right, MaxAuthTries and LoginGraceTime with passwords,
root's, a locked or expired account (by password and by key), an expired,
empty or unset password, a `$y$` or over-cap string (refused where `sshd`
admits them), the shipped cost, `PasswordAuthentication no`, and the start
refused without root; no password in any log, output or record. The
listener's memory is measured beside `sshd`'s: its anonymous resident
memory (RssAnon, which the kernel's reclaim of file-backed pages cannot
lower) within 64 KiB after a minute idle and 32 KiB across three hundred logins;
and `XDG_RUNTIME_DIR` from the account's runtime directory, set, unset for
a wrong mode, a wrong owner and no directory.
`tools/check-server-hostile` runs burrowd against a
scripted client that never finishes the exchange, leaves out strict kex,
sends an oversize packet, signs over another session or with another key,
sends `exec` before authentication, changes the user mid-authentication,
sends data before the channel or the command, overruns the window, asks
every refused request at once, asks for a second program after a shell, sends an IGNORE or a stream of PINGs
while a command's output waits, asks to change a password, sends an
overlong one, sends twenty wrong ones at once (one check at a time), times
a wrong password for a real, root, unknown and locked account (the same
one hash each), and opens a thousand connections that never
send a version line. `tools/check-server-git` clones, fetches and pushes
(and has a push refused) through burrowd and through `sshd`, and compares
the repositories. `tools/measure-server` times connect to first byte and
`cat` through burrowd, `sshd` and a one-process build of burrowd (a row
program, never installed), and a password login at PAX's cost through
burrowd and `sshd`, interleaved, against stated margins.
`tools/check-server-local` runs burrowd as the invoking user with burrow as
the client, on macOS and anywhere without the pinned container, its
memory rows included (footprint(1)'s dirty memory on macOS).

## CI

Unlabelled pull requests run one cheap job that points at the local
gauntlet. The `ci` or `full-matrix` label runs the full set: the Linux
gauntlet in the pinned container (the server's rows and its hostile-client
rows among them) and the macOS unit rows. den over burrow, git through
burrowd, GitHub, the live push and the measurements are the local
gauntlet's (den's
git oracle is built in den's own image, whose digest a runner is not held
to reproduce). Trunk pushes run
it when CI, tools or pins change, and the nightly runs it always; a red
nightly opens an issue.

Every remote fetch of CI and the container (the base image, apt's lists and
packages, the toolchain archives and the std, OpenSSH's tarball) is tried a
bounded number of times with growing pauses, each try under a connect and a
total time limit (`ci/fetch-retry`, and the same policy inline in
`ci/oracle.Containerfile`). A fetch that still fails ends its step with
`FAIL fetch of … failed after N tries`, and the Linux job's rows do not run
after it.

## Releases

A release starts from a `vX.Y.Z` tag on trunk, pushed by hand, and ends
as a draft; publishing the draft is a separate step, also by hand. burrow
takes the release path the other wolf tools take: the shared draft-only
workflow of [homebrew-wolf](https://github.com/wolffe-lang/homebrew-wolf),
at one pinned commit. `.github/workflows/release.yml` first runs the
release gate, `release-gate.yml`: the whole of `ci.yml`, copied by that
commit's release adapter and bound to the tag's commit. Then the shared
workflow builds the release tier (`tools/build --release`) on Linux x86-64
and macOS arm64, checks that `burrow -V` and `burrowd -V` print the tag's
version, packs each archive twice and compares the bytes, writes its
SHA-256, and puts both archives on one draft release. Clean runners with
no checkout and no compiler then download the draft's archives, compare
their digests and run them. Each archive holds burrow, burrowd and
burrow-keygen, the licence, this README, the CHANGELOG and the toolchain
pins, with a `BUILD.json` naming the commit and the compiler.
`.github/release.json` names the build, the binaries, the version line and
the smoke commands; 0.1.0 is marked experimental, so its draft is a
prerelease.

Three more workflows check the path before a tag. `release-wiring.yml`
runs on every pull request: the release gate must still be `ci.yml`'s exact
copy, both callers must name the same pinned commit, and the manifest's
version must have its CHANGELOG section. `release-rehearsal.yml`, started
by hand on a branch, runs the same build and the clean-runner smoke from
that branch, with no tag, no draft, no token and only read permission.
`release-public-smoke.yml`, started by hand after publishing, downloads the
public release with no token and runs it again. And `tools/check-release
--dry`, a step of the gauntlet, does the same work on the machine at
hand: it checks that the workflows name one commit and that the commit's
smoke job reads a draft the way that works (write permission for the job,
the token only in the download step), fetches that commit, runs its
adapter check, builds and packs this host's archive and runs the clean
smoke, with no upload. It builds from a copy of the tree without `.git`,
so its `BUILD.json` names no commit; the rehearsal does. CI's Linux and
macOS jobs run it too, on the bare hosted runners the release build uses:
on Linux from a fresh checkout outside the container, its toolchain fetched
as the release build fetches it.

## Clean room

burrow is written from specifications and from black-box runs of OpenSSH,
never from another implementation's code.

**Read:** the SSH RFCs 4250, 4251, 4252, 4253, 4254 and 4256, 4344, 4419
(for reading), 8308 (extension negotiation), 8332 (read only, to refuse its
names), 8709 (Ed25519 keys), 8731 (curve25519-sha256) and 9142; OpenSSH's
protocol notes, which are specifications rather than code: `PROTOCOL`,
`PROTOCOL.chacha20poly1305`, `PROTOCOL.key`, `PROTOCOL.agent` (for reading)
and `PROTOCOL.certkeys` (to refuse its names), read from a release
tarball's top level; the man pages `ssh(1)`, `ssh-keygen(1)`,
`ssh_config(5)`, `sshd(8)` and `sshd_config(5)`; and, for hashed
known_hosts names, FIPS 180-4 and RFC 2104 with NIST's published vectors.
No SHA-1 or HMAC library's source is read.

**Never read:** any `.c` or `.h` file of OpenSSH, nor the code or tests of
any other ssh implementation (dropbear, libssh, libssh2, Go's
`x/crypto/ssh`, paramiko, asyncssh, russh, thrussh, Twisted conch, PuTTY,
wolfSSH and the rest). Test vectors are our own.

wolf-std's crypto modules are the organisation's own code and are read and
used: `std.x.crypto.curve25519` (X25519 and Ed25519),
`std.x.crypto.chacha20` (ChaCha20, Poly1305) and `std.x.crypto.sha2`.

**The oracle:** OpenSSH's `ssh`, `sshd` and `ssh-keygen`, pinned by version
and digest and run in a container as black boxes. A test row holds burrow's
bytes, behaviour and exit status to the pinned OpenSSH client talking to the
same pinned `sshd`, on loopback ports the test owns, with keys generated for
that run; a server row holds burrowd's to the pinned `sshd`'s, through the
same pinned `ssh`. Two rows contact a real host, and say so: `tools/check-github`
(GitHub, read only, no key) and `tools/check-live` (the live fixture, from
its variables only). den's own sources are read as the consumer's, and git
is used only as den's pinned binary, a black box.

## Licence

GPL-3.0-or-later (`LICENSE`), with the wolf Training Data Permission
(`LICENSE-TRAINING-DATA`).
