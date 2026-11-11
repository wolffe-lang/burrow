## Unreleased

- burrowd grants a terminal (RFC 4254 §6.2, §6.7, §8): a `pty-req` where
  `PermitTTY` (now `yes` or `no`, `yes` by default as `sshd`) and the key
  allow it (`no-pty` and `restrict` refuse it, `pty` after `restrict` grants
  it). The pty takes the client's size and every terminal mode it sends that
  the host has; the program runs on it as the leader of a session of its
  own with the pty as its controlling terminal, with TERM and `SSH_TTY`;
  `window-change` resizes it; the session ends with the program, and the pty
  is closed. Malformed and late requests are refused by name, the
  connection kept.
- Every program burrowd runs leads a session of its own, as `sshd` gives
  it: with no pty it has no controlling terminal, so nothing it does reaches
  the terminal burrowd was started from (PAX's console).
- Pin wolf 0.2.39, lupin 0.1.61 and wolf-std's sessions and ptys (sc81).
- burrowd takes `SetEnv` (`sshd_config(5)`): `NAME=VALUE` variables set in
  every session, over burrowd's defaults and the accepted `GIT_PROTOCOL`,
  never over `SSH_CONNECTION` or a forced command's `SSH_ORIGINAL_COMMAND`;
  the first line and the first value of a name win; quotes and a trailing
  `#` as the pinned `sshd` reads them; a malformed line refused at start by
  file and line; `burrowd -T` prints a `setenv` line per variable. On PAX
  a command over ssh gets the console's `WOLF_STD`, `LUPIN_STD` and
  `DEN_TLS_ROOTS` this way, with no `. /etc/shrc;` before it.
- Each session's program leads a process group of its own, and burrowd
  leads its own at start. A job-control stop a program draws on burrowd's
  terminal (on PAX, a bare `sudo` over ssh, which asks on the console)
  stopped burrowd's whole group, its listener included, until the machine
  restarted; it now stops that program alone. A stopped program is no
  longer taken for an ended one (its log line read `status 278`, a stop
  by SIGTTOU): its session waits for its end. A session of its own for
  each program, as `sshd` gives, waits for a toolchain call.
- A session reads at most one packet a turn, on both sides. burrowd's
  session stalled when the client sent PINGs (OpenSSH obscures keystroke
  timing that way in a session that asked for a pty) or one IGNORE and then
  nothing while the command's answer waited, so `ssh host` typed into could
  hang; burrow's session likewise stopped reading its standard input after
  a server's IGNORE or PING.
- burrowd serves a shell (RFC 4254 §6.5 `shell`) with no pty: with no
  command, the account's login shell (`-sh`), its stdin, stdout and stderr
  the channel's. A forced command runs in its place; a second program on
  the channel is `exec_twice`; `pty-req` stays `pty_refused`, and a shell
  after it starts with one line on stderr saying it has no terminal.
  `shell_refused` leaves the server's names (burrow, the client, keeps it).
- burrowd checks passwords from `/etc/shadow` where its configuration
  says `PasswordAuthentication yes` (its default stays `no`): crypt(5)'s
  `$7$` (wolf-std's scrypt, the form PAX writes), capped at PAX's shipped
  cost, one check at a time in a process of its own, the same work for
  every refusal; locked and expired accounts refused by every method, as
  `sshd(8)` describes; change requests refused; the log's `key password`.
  The std pin moves to wolf-std `2411d868` for `std.x.crypto.passwd`.
- The repository scaffold: licence, README and its clean-room list.
- Pin wolf 0.2.37, lupin 0.1.59 and the bundled std, and OpenSSH 10.0p2 as
  the black-box oracle, built from its signed tarball in a pinned image.
- B1, the transport: the version exchange, the binary packet protocol,
  `curve25519-sha256`, `ssh-ed25519` host keys against known_hosts,
  `chacha20-poly1305@openssh.com`, strict kex, ext-info, re-exchange at
  RFC 4253 and 4344's limits and on the server's request, and disconnects
  with reason codes; every refusal by name.
- Independent vectors from the RFCs, the transport rows against the pinned
  `sshd`, and tiered CI.
- B2, authentication and keys: `publickey` with `ssh-ed25519` (the query,
  then the signed request), `server-sig-algs` honoured, the banner shown as
  `ssh` shows it; OpenSSH's private key format for unencrypted Ed25519 keys,
  read and written; `burrow-keygen -t ed25519`, `-y` and `-l`; known_hosts
  hashed names (with SHA-1 and HMAC-SHA1 from FIPS 180-4 and RFC 2104),
  `@revoked` and `@cert-authority`, and lines appended under `accept-new`
  and `no`.
- B3, the session and the command line: one command on a session channel,
  `env` and `exec`, stdin, stdout and stderr byte-clean, both windows, EOF
  and CLOSE in either order, the exit status and signals mapped as `ssh`
  maps them; the command line and `~/.ssh/config` den uses; every refusal
  by name with `ssh`'s line beside it.
- The transport writes its state in place, so a session runs each turn in a
  region and a transfer of any size holds a packet's worth of memory; a
  re-exchange no longer lets a later message overtake the ones it kept.
- The session rows against the pinned OpenSSH, hostile-peer rows against a
  scripted server, NIST's SHA-1 vectors, and the measurement against `ssh`.
- B1's `--no-strict-kex` leaves the command line on every tier (it is now
  `option_unknown`); the downgrade row's waiver moves to a row program,
  `rows/kexprobe`, never installed. Rows hold each test option inert for
  security.
- B4, den over burrow: den's clone, fetch and push over `ssh://` and
  scp-like URLs, with burrow linked as `ssh`, held byte for byte to the
  pinned OpenSSH client against the pinned `sshd` (`tools/check-den`, den
  pinned in `burrow-den.toml` and built by its own tools).
- With no command, burrow now logs in before it refuses
  (`shell_unsupported`), so a keyless `ssh -T git@github.com` is refused
  authentication as `ssh` refuses it; GitHub's real server, read only,
  against its published host key (`tools/check-github`).
- The live push row (`tools/check-live`), from its two variables only, with
  a loopback self-test; the static build's check for PAX
  (`tools/check-static`); den's clone through burrow measured against the
  pinned `ssh` (`tools/measure-den`).
- den pinned at `ac2332b`, which sends git's command form (the program word
  bare when it is plain), so den's push through burrow reaches GitHub's
  receive-pack; rows hold the command `sshd` is sent to that form
  (`den-command-*`), and the live row removes its work files when it ends.
- The system known_hosts files are read by default, after the user's
  (`/etc/ssh/ssh_known_hosts` and `/etc/ssh/ssh_known_hosts2`, as `ssh`
  reads them), and `GlobalKnownHostsFile` names others; a match in either
  is accepted, new keys go only to the user's file, and the strict default
  is unchanged (burrow#5).
- With no command, burrow starts the login shell with no pseudo-terminal
  (under `-T`, or when stdin is not a terminal), so `ssh -T git@github.com`
  shows GitHub's greeting and exits 1 as `ssh` does; with stdin a terminal
  and no `-T`, it refuses by name (`pty_unsupported`) before connecting.
  `shell_unsupported` is gone; a refused shell request is `shell_refused`.
- B5, `burrowd`, the server for commands: the transport's server role
  (burrowd's identification and KEXINIT, strict kex required, the host
  key's signature on H, EXT_INFO with `server-sig-algs`, re-exchange either
  way), one required Ed25519 host key checked for its mode and owner, its
  fingerprint printed at start; key-only authentication against
  `authorized_keys` with StrictModes, `command=` honoured and options it
  cannot enforce admitting nothing, root refused always; one session
  channel with `exec`, `env` (`GIT_PROTOCOL` only) and the exit status or
  signal, every other request refused by name; LoginGraceTime,
  MaxAuthTries and MaxStartups; one log line per connection; `sshd(8)`'s
  flags and a subset of `sshd_config(5)`, loopback unless told otherwise.
- burrowd's privilege separation: a monitor per connection holds the host
  key, an unprivileged worker parses every byte before authentication, and
  the session takes the user's ids with no way back; on macOS, and without
  root, burrowd serves the user who runs it.
- The server's rows against the pinned `sshd` (`tools/check-server`), a
  scripted hostile client (`tools/check-server-hostile`), git through
  burrowd (`tools/check-server-git`), burrowd's macOS rows
  (`tools/check-server-local`), its static binary, and the measurement
  against `sshd` and a one-process build (`tools/measure-server`).
