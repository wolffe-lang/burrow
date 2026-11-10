# bw06 — a terminal for burrowd's sessions

burrowd serves a command or the login shell, each without a terminal: a `pty-req` is refused by name
(`pty_refused`), and a shell after it says so on stderr. An interactive session (`ssh host` with line
editing, job control, a full-screen program, Ctrl-C) needs burrowd to grant `pty-req`: open a pseudo-terminal,
run the session's program on its slave as the leader of a session of its own with the slave as its
controlling terminal, relay the master's bytes, and apply the client's window changes.

This note is the design, written before any code. Phase 1 adds no product code: the prediction, then two
probes of what the toolchain and the pinned `sshd` do, scored below.

## Prediction

Written 2026-11-10 at 15:30Z, at trunk `9c647a2`, from RFC 4254 §6.2, §6.5, §6.7, §6.9, §6.10 and §8,
RFC 8160 (IUTF8), POSIX's terminal interface (General Terminal Interface; `setsid`, `tcsetattr`,
`posix_openpt`, `grantpt`, `unlockpt`, `ptsname`), `sshd(8)` (LOGIN PROCESS; AUTHORIZED_KEYS FILE FORMAT:
`no-pty`, `pty`, `restrict`), `sshd_config(5)` (`PermitTTY`, `PrintMotd`, `PrintLastLog`), `ssh(1)` (`-t`,
`-tt`), wolf-std at burrow's pin (`2411d868`), wolf 0.2.37's spec (`11-os.md`, `04-abi.md`), wolf-lang's
open change for a new session (wolf-lang#1089, branch `s290`: its spec and its probe records), and PAX's
pseudo-terminal branch (`px111`: its note). Every behaviour of the pinned `ssh` and `sshd` below is a
prediction until the Evidence section scores it.

### 1. What an interactive session needs

1. **`pty-req` (§6.2), before the program.** TERM, the size (columns, rows; pixels), the encoded modes (§8:
   opcode and uint32 pairs, `TTY_OP_END` 0 ends them, an opcode from 160 stops the parse). Zero dimensions
   are ignored. The server allocates the pty when the request comes, so the reply (want_reply) says whether
   it has one. A refusal leaves the session as today (`pty_refused`, the shell's no-pty line).
2. **The pty.** A master (`posix_openpt`), the slave granted and unlocked, the slave's name. Opened by the
   session's holder, which already runs as the user, so the slave is the user's on every host (PAX gives a
   slave the opener's ids and refuses `chown` of `/dev/pts/N`).
3. **The size and the modes, on the pty before the program runs.** The size (`TIOCSWINSZ`); every §8 mode
   the host has: the special characters (VINTR … VDISCARD, 255 for none), the input, local, output and
   control flags, the speeds. A mode the host lacks is skipped, as §8 allows.
4. **`shell` or `exec` (§6.5) on the pty.** The child burrowd forks becomes the leader of a new session
   (`setsid`), with no controlling terminal; it opens the slave by name, which makes the slave its
   controlling terminal (POSIX leaves the open's effect to the host; s290 measured it on linux and macOS,
   px111 serves it on PAX), and its process group the terminal's foreground group. The slave becomes its
   stdin, stdout and stderr; the master and every other descriptor are closed; TERM (and `SSH_TTY`, if
   `sshd` sets it) join the environment; the login shell (`-sh`) or `sh -c COMMAND` runs as today.
5. **The foreground group.** Nothing more for burrowd: the session leader's group holds the foreground, and
   a shell with job control moves it among its jobs itself.
6. **Relaying.** The master's output is the channel's data (stream 0; a pty has no separate stderr, so no
   extended data); the client's data is written to the master, within burrowd's window as for a pipe.
   Line editing, echo, CR/LF translation and the signal keys are the line discipline's, so Ctrl-C (0x03 on
   the channel) is SIGINT for the foreground group, Ctrl-Z a stop, Ctrl-\ a quit.
7. **`window-change` (§6.7).** The new size on the master; the host sends SIGWINCH to the foreground group.
   No reply. Zero dimensions ignored; before a pty or after the end, taken and ignored as today.
8. **`signal` (§6.9) and `break`.** Unchanged: `signal` refused by name, `break` taken and ignored.
9. **The client's EOF.** A pty cannot be half-closed. burrowd does what the pinned `sshd` does (measured in
   phase 1).
10. **The end.** The program's end ends the session, not the master's end of file: when the program is
    reaped (a stop is not an end), burrowd reads what the master still holds, then sends EOF,
    `exit-status` or `exit-signal` (§6.10), CLOSE, and closes the master. Closing it hangs the slave up, so
    whatever the program left holding the slave hears SIGHUP and reads end of file, and the slave's name
    goes.
11. **Who may have one.** `PermitTTY` (default `yes`, as `sshd`); a key line's `no-pty` or `restrict` refuses
    the pty for that key, and `restrict,pty` grants it, as `sshd(8)` describes. A forced command runs on
    the pty like any program.
12. **Not done, named:** no utmp, wtmp or lastlog entry (the session runs as the user, who cannot write
    them), so `who` and `last` do not list burrowd's sessions; no motd and no last-login line
    (`PrintMotd no`, `PrintLastLog no` stay burrowd's only values); X11 and agent forwarding stay refused
    by name.

### 2. What the toolchain at burrow's pin can do

wolf 0.2.37 with wolf-std `2411d868`, per step. "s290" is wolf-lang#1089, open on a 0.2.38 base and in no
release; "px111" is PAX's unmerged pty branch, read from its note, not measured here. The cells marked
*probe* are what phase 1's probe measures (Evidence).

| step | what it needs | at the pin | linux | macOS | PAX |
|---|---|---|---|---|---|
| 1 parse `pty-req`, `window-change`, §8 | burrow's `wire` | yes | yes | yes | yes |
| 2 a master and its slave's name | `posix_openpt`, `grantpt`, `unlockpt`, `ptsname` | **missing**: no builtin; `fs.open_mode("/dev/ptmx", 3)` opens a master, but its slave stays locked and std has no way to unlock or name it (*probe*) | — | — | served by px111 (`/dev/ptmx`, `TIOCGPTN`, `TIOCSPTLCK`) |
| 3a the size | `TIOCSWINSZ` | **missing**: `term.size` reads only | — | — | served (px111) |
| 3b eight modes and VMIN/VTIME | `tcsetattr` | `term.set_mode`: ICANON, ECHO, ISIG, IXON, IEXTEN, ICRNL (inverted), OPOST (inverted), ISTRIP | yes | yes | termios served (px111) |
| 3c the special characters | `c_cc` | **missing**: `term.chars` reads only | — | — | — |
| 3d the other §8 flags (ECHOE, ECHOK, ECHOCTL, ECHOKE, ECHONL, NOFLSH, TOSTOP, PENDIN, ONLCR, OCRNL, ONOCR, ONLRET, INLCR, IGNCR, IXANY, IXOFF, IMAXBEL, IUTF8, IGNPAR, PARMRK, INPCK, CS7, CS8, PARENB, PARODD) and the speeds | `tcsetattr` | **missing** | — | — | — |
| 4a a session of its own | `setsid` | **missing at the pin**; s290's `os_setsid` (wolf-std's `process.lead_session` on its branch) | s290 measured | s290 measured | s290's PAX leg |
| 4b the slave as controlling terminal | an open without `O_NOCTTY` by a session leader | the runtime's opens pass no `O_NOCTTY` (s290's spec); `fs.open_mode(name, 3)` | s290 measured | s290 measured | px111 |
| 4c the slave as stdin, stdout, stderr | `os_exec`'s descriptor map | yes (`process.set_stdin` …) | yes | yes | yes |
| 5 the foreground group | the open in 4b | follows from 4a and 4b | | | |
| 6 relay | read, write, wait on the master | `fs.read_chunk`, `fs.write_some`, `fs.set_nonblock`, `signal.wait_fds` on any descriptor | *probe* | *probe* | px111 polls a master |
| 7 SIGWINCH | the host, on 3a | follows from 3a | | | px111 |
| 10 the end | reap, drain, close | `process.poll_core`, `fs.close` | *probe* (what the master reads after the slave's last close) | *probe* | px111: the rest, then `EIO` |
| 11 `PermitTTY`, key options | burrow's `sconfig`, `akeys` | yes | | | |

**Missing, exactly:** (a) a pty open that grants, unlocks and names the slave; (b) a window-size set; (c) a
special-character set and the flags `term.set_mode` does not reach (or one call taking §8's whole vocabulary);
(d) `os_setsid`, which s290 adds but no release carries; and wolf-std functions over all four at a released
pin. None of (a) to (c) is written anywhere yet: they need a wolf-lang change of their own, released with
s290 so burrow moves its pin once.

**A route that needs no release, measured, not recommended:** wolf 0.2.37 calls C through `extern "c" fn`
under the `ffi` capability (`[abi.c.import]`). burrow could call the C library's `posix_openpt`, `grantpt`,
`unlockpt`, `ptsname`, `ioctl` and `setsid` itself (*probe*: the whole chain, Part F). It would put a C
membrane in a network server whose package now names only `env`, `fs`, `net` and `exec`, with each host's
request numbers and `termios` layout in burrow's own code, on calls the checked machine and lupin refuse by
name.

### 3. What can ship before the release

Nothing interactive. Without (a) there is no pty at all. With a pty and no new session (an `ffi` open, say),
the program would hold a terminal that is not its controlling terminal: `tty` and line editing work, but
Ctrl-C and Ctrl-Z reach no one (the pty has no session, so no foreground group), a shell has no job control
(`tcsetpgrp` fails), `/dev/tty` is still burrowd's own terminal (on PAX the console, where `sudo` asks and
the px112 stop began), no SIGWINCH arrives, and the end hangs nothing up. That is not an interactive session
and it is not offered.

What can be built now, on this branch, and merged only with the code that uses it: the protocol half (§1
steps 1, 7, 11: `pty-req` and `window-change` parsed and kept, §8 decoded, `PermitTTY` and the key options
plumbed), with unit rows that run on the checked machine, native and lupin; and every row below, red.

### 4. burrowd's processes, after

- **listener, monitor, worker:** unchanged, but the monitor's go frame to the holder carries whether this key
  and `PermitTTY` allow a pty.
- **holder (the user):** on `pty-req`, opens the pty, sets the size and modes, keeps TERM; answers SUCCESS,
  or FAILURE with a refusal by name. On `window-change`, sets the master's size.
- **the program (a fork of the holder):** `process.lead_session` (s290) in place of `process.lead_group`, for
  every program, with a pty or without; with a pty, then the slave opened by name (its controlling
  terminal), the slave on 0, 1 and 2, the master and the extra slave descriptor closed, TERM in the
  environment; then the exec, as today. Without a pty the program has no controlling terminal at all
  (`/dev/tty` fails, ENXIO), the session of its own px112's note left for this toolchain call, and the
  `session-own-session` row it took out comes back.
- **The holder relays the master** and ends the session as in §1 step 10. It is never in the program's
  session, so no stop, Ctrl-C or hangup on the pty reaches it or burrowd.
- **The one-process row program** (`src/oneproc.lu`) keeps refusing `pty-req`: its session is root until the
  exec, so a pty it opened would be root's.

### 5. The rows, red first, held to `sshd`

In `tools/check-server`, a new section; each row runs the pinned `ssh` against burrowd and the pinned `sshd`,
both given `PermitTTY yes` (the existing rows keep `PermitTTY no` on both: burrowd's base gets it beside
`sshd`'s), `PrintMotd no` and `PrintLastLog no`, and holds burrowd's exit status, stdout and stderr to
`sshd`'s, the pty's number written N. All red at the rows tip (burrowd refuses the pty), but `auth-no-pty`:

- `session-tty-command`: `ssh -tt host` with a command printing `tty`, TERM, `SSH_TTY`, `stty size`, a
  line on stdout and one on stderr, `exit 3`; stdin not a terminal; once without TERM, once with
  `TERM=vt100`.
- `session-tty-size`: stdin a pty of the row's own sized 40×132 with odd modes (intr ^G, erase ^H, `-ixon`):
  `stty size` and `stty -a` on the far side; the row's pty resized to 50×100 and the client told
  (SIGWINCH); `stty size` again after a typed line.
- `session-tty-full-screen`: a program that reads its size, sets raw mode, reads one key and puts the mode
  back; the row types `q`.
- `session-tty-interrupt`: a program that traps INT; 0x03 typed reaches it (its own status, 7); and `exec
  sleep 30` interrupted (`exit-signal INT`, the client's 255).
- `session-tty-shell`: `ssh host` at the row's pty, `tty; echo $0; exit 4` typed at the prompt.
- `session-tty-gone`: after a session whose program left a child holding the slave and ignoring SIGHUP, the
  session ends when the program does, the slave's name is gone, and burrowd's log line is the program's
  status; a child that does not ignore SIGHUP is gone too.
- `session-tty-burst`: 20000 lines printed just before the exit all arrive.
- `session-tty-eof`: the client's stdin a pipe that ends, as `sshd` answers it.
- `auth-no-pty` (the security row): keys with `no-pty`, with `restrict`, and with `restrict,pty`; the first
  two get `PTY allocation request failed on channel 0` and no pty, the third a pty. Green at the rows tip for
  the first two (burrowd refuses every pty), red for the third.
- `session-tty-refused`: `PermitTTY no` on both servers refuses alike (today's `session-pty-refused`).
- `session-own-session` (back from px112): a command's session is its own, `/dev/tty` fails.

In `tools/check-server-hostile` (a scripted client, burrowd only): `pty-req` with a truncated mode list, an
opcode from 160 followed by junk, zero and over-65535 dimensions, a TERM with control bytes or of 4 KiB;
`pty-req` twice; `pty-req` after the program started; `window-change` before any pty; each refused or
ignored by name, the connection kept. `src/schannel_test.lu`: the parse and the §8 decoder, on all three
machines. `tools/check-server-local` (macOS, the Air): `local-tty` with the system's `ssh` as the client
(burrow's own client still refuses a pty), its version line recorded.

**The plant:** a key's `no-pty` ignored (the pty granted anyway): `auth-no-pty` red by name. A second,
development-only plant: `lead_group` in place of `lead_session`, which turns `session-tty-interrupt` and
`session-tty-shell` red.

### 6. PAX

- **From px111, as it stands (its note):** `/dev/ptmx` and devpts with linux's defaults, `TIOCGPTN`,
  `TIOCSPTLCK`, `TIOCGPTPEER`, termios on either end, `TIOCSWINSZ` with SIGWINCH, `setsid`, `TIOCSCTTY`, an
  open without `O_NOCTTY` taking a free terminal, the background rules, the keys' signals, the hangup at the
  master's last close, the slave's name gone with its master. That is everything burrowd's chain asks of a
  kernel. burrowd on PAX is the static linux binary, so the C library it links (Ubuntu 24.04's `libc.a`)
  makes the calls; the wolf change for (a) to (c) needs a PAX leg on px111's kernel, as s290 had on trunk's.
- **What PAX does not need:** `chown` or `chmod` of `/dev/pts/N` (burrowd opens the pty as the user); a tty
  group (`mesg` and `write` are not asked for).
- **From a later pax lane, once px111 and this work are merged and a wolf release carries the calls:** the
  burrow pin moved to that merge; burrowd's suite grown by the rows' shapes driven from the host through
  QEMU: `tty` names `/dev/pts/0`, `stty size` follows a resize, Ctrl-C ends a foreground `sleep`, pelt's line
  editor and yew read their size and keys, the session's end leaves `/proc/sys/kernel/pty/nr` at 0, and a
  bare `sudo` over `ssh -t` asks on the pty, not the console, while over `ssh -T` it finds no terminal and
  says so instead of stopping on the console. Then the metal check px111's note lists.

### 7. Choices to recommend

1. **Where the pty calls come from.** (A) A wolf-lang change: builtins for (a) to (c), wolf-std functions over
   them, released with s290; burrow moves its pin and stays on wolf-std alone. (B) burrow declares `ffi` and
   calls the C library now (measured to work, Part F). (C) `ffi` for the pty open and size only, s290 for the
   session. (D) Helper programs (`script`, `stty`, `setsid -c`): none on PAX, no window change. Recommended:
   (A).
2. **Before the release.** (A) Develop the protocol half and the rows on this branch; merge nothing until the
   release, then one PR. (B) Merge the protocol half now, still refusing `pty-req`. Recommended: (A).
3. **`PermitTTY`.** (A) Default `yes`, as `sshd`; the rows' base gives both servers `no`. (B) Default `no`
   unless the configuration says `yes`. Recommended: (A).
4. **Key options.** (A) `no-pty` and `restrict` refuse the pty (`pty_refused`), `restrict,pty` grants it, as
   `sshd(8)`. (B) Keep refusing any key line with `pty`. Recommended: (A).
5. **The end.** (A) The program's end (§1 step 10), held to `sshd` by `session-tty-gone`. (B) The master's end
   of file. Recommended: (A).
6. **Modes the host lacks or the call cannot carry.** (A) The wolf change takes §8's whole vocabulary, and
   burrowd applies every mode the host has. (B) The eight `term.set_mode` covers plus the special characters;
   the rest left at the pty's defaults and named. Recommended: (A).
7. **A malformed `pty-req`** (a truncated mode list, a TERM with control bytes or over 255 bytes, a dimension
   over 65535). (A) FAILURE, refused by name (`pty_malformed`), the connection kept. (B) The connection
   ended (`malformed`). Recommended: (A); a malformed message (the request's own fields) stays `malformed`.
8. **motd and last login.** (A) Neither (burrowd's only values stay `no`). (B) `/etc/motd` for a shell on a
   pty. Recommended: (A).
9. **The macOS client.** (A) The system's `ssh`, version recorded. (B) The pinned OpenSSH built on the Air.
   (C) Wait for burrow's own client to take ptys. Recommended: (A).
10. **The plant.** (A) `no-pty` ignored (record). (B) `lead_group` for `lead_session` (development).
    Recommended: (A) as the record's, (B) beside it.

### 8. The two probes, predicted

**Part S, wolf-std alone** (`notes/bw06/probe/ptyprobe.lu`, the pinned toolchain; linux in the pinned
container as root and as the rows' account, and macOS): `/dev/ptmx` opens (mode 3) and is a terminal; its
size reads 0 0; its mode reads. linux: `/proc/self/fdinfo` names the slave's index; the slave's open fails
(`io`, EIO 5), since std cannot unlock it. macOS: std names no slave.

**Part F, the C library through `extern "c"`:** the master opens, grants, unlocks and names its slave
(`/dev/pts/N` on linux, `/dev/ttysN` on macOS). A read of the master before the slave is opened: nothing
to read on linux; on macOS unknown. `TIOCSWINSZ` 40×132 reads back through `term.size` on the master. A
forked child's `setsid` makes its pid its session; the slave's open makes `/dev/tty` open and the
foreground its group; the slave's size is 40 132. A shell on the slave answers `ready`; 0x03 written to the
master reaches its INT trap (`caught INT`, status 7). After the slave's last close the master reads end
(`io`, EIO, on linux; macOS unknown); after the master's close the slave's name is gone.

**The pinned `sshd`** (`notes/bw06/probe/sshd_pty.py`, `PermitTTY yes`, `PrintMotd no`, `PrintLastLog no`):

- `ssh -tt host CMD`, stdin not a terminal: status 3; stdout `/dev/pts/N`, `TERM=unset` (low confidence:
  the client may send an empty TERM and `sshd` may set it), `SSH_TTY=/dev/pts/N`, `0 0` (a zero size
  ignored), `out` and `err` both on stdout, every line ending CR LF; stderr empty (the client prints
  `Connection to … closed.` only when its stdin is a terminal). With `TERM=vt100`: `TERM=vt100`.
- The same with `-T`: `not a tty`, TERM and `SSH_TTY` unset, `stty` failing on stderr, LF line ends.
- At the probe's pty (40×132, intr ^G, erase ^H, `-ixon`): `40 132`; `stty -a` shows `intr = ^G`,
  `erase = ^H`, `-ixon`; after the resize and SIGWINCH, `50 100`.
- Ctrl-C to a trap: `^C` echoed, `caught INT`, status 7. Ctrl-C to `exec sleep 30`: status 255
  (`exit-signal INT`).
- The full-screen probe: `40 132`, then `key=q`, status 0.
- `ssh host` at the probe's pty: the prompt, the typed line echoed, `/dev/pts/N`, `-sh`, status 4.
- A child holding the slave and ignoring SIGHUP: the session ends at once (well under the child's 5 s), the
  slave's name is gone, the child lives on. Without the trap the child is gone (SIGHUP).
- 20000 lines before the exit: all 20000 arrive.
- The client's stdin a pipe ending after `one`: `sshd` writes no end to the pty, `cat` never ends, and the
  probe's 10 s deadline ends the client (low confidence). With a 0x04 byte before the end: `one` twice (the
  echo and `cat`), `cat-ended`, status 0.
- Keys with `no-pty` and with `restrict`: `PTY allocation request failed on channel 0`, `not a tty`, status
  1; `restrict,pty`: a pty. `PermitTTY no`: as `no-pty`.

## Evidence

Phase 1's probes, after the prediction (`3e098c4`):

- **linux:** the pinned container (Ubuntu 24.04 by digest) on two CPUs, linux 7.2.4 x86_64, the pinned
  toolchain staged by `tools/fetch-toolchain` and the oracle by `tools/fetch-oracle`. Take 1 at `54bb2ef`:
  `ptyprobe` as root and as the rows' account, `ptyprobe_ioctl`, and `sshd_pty.py`; take 2 at `94b9cb3`:
  `sshd_pty.py` again (its line count fixed) and `sshd_pty_hold.py`. Raw logs sha256 `5ff246a5…` (take 1)
  and `2795c959…` (take 2); the probes' output is `notes/bw06/evidence/linux-probes.log`.
- **macOS:** an Apple M-series laptop, macOS 26.4.1 arm64, `ptyprobe` built at `efd731b`:
  `notes/bw06/evidence/macos-probe.log`.

**One change to a probe after the prediction:** wolf 0.2.37 refuses to build `extern "c" fn ioctl(fd: i32,
req: u64, ...)` for aarch64-apple-darwin (E0826: "does not support C's unnamed arguments … declare a C
wrapper with a fixed parameter list"). `ptyprobe.lu` therefore sets no size, and `ptyprobe_ioctl.lu` (linux
only) does. That is itself a finding (below).

### Scored

**Part S, wolf-std alone:**

- Hit: `/dev/ptmx` opens with mode 3 and is a terminal, on both hosts.
- Hit on linux, miss on macOS: the master's size reads `0 0` and its mode `287` (canonical, echo, signals,
  flow, extended, min 1) on linux; on macOS both `term.size` and `term.mode` on the master answer `io`.
- Miss, worse than predicted: linux 7.2.4's `/proc/self/fdinfo` for the master holds no `tty-index`, so std
  cannot even name the slave there, let alone unlock it. macOS: no slave name, as predicted. **No route to a
  usable pty exists in wolf-std at the pin, measured on both hosts.**

**Part F, the C library through `extern "c"`:**

- Hit, both hosts: the master opens, is granted and unlocked, and names its slave (`/dev/pts/N`,
  `/dev/ttysN`); as the rows' account exactly as as root.
- Hit (linux) and answered (macOS): a read of the master before any slave open finds nothing to read; no end
  of file on either host, so the holder may wait on the master from the start.
- linux, `ptyprobe_ioctl`: `TIOCSWINSZ` 40×132 on the master reads back 40 132 there and in the child; a
  second size on the master reaches the child as SIGWINCH, and the child reads 50 100. macOS: not
  measurable, E0826.
- Hit, both hosts: the forked child's `setsid` makes it a session leader (its id its pid), the slave's open
  makes `/dev/tty` open and the foreground its group, a shell on the slave answers, and 0x03 on the master
  reaches its INT trap (`^C`, `caught INT`, status 7).
- Hit (linux) and answered (macOS): after the slave's last close the master reads end: `io` (EIO 5) on
  linux, a zero-byte read (end of file) on macOS. The slave's name is gone after the master's close on both.

**The pinned `sshd`:**

- Hit: `ssh -tt host CMD` with stdin not a terminal: status 3; `/dev/pts/N`, `TERM=unset` (an empty client
  TERM is not set), `SSH_TTY=/dev/pts/N`, `0 0`, `out` and `err` both on stdout, CR LF line ends;
  `TERM=vt100` passes through.
- **Miss:** stderr is `Connection to 127.0.0.1 closed.` whenever the pty was granted, stdin a terminal or
  not. It is the client's line, so it is alike through both servers by construction.
- Hit: `-T`: `not a tty`, TERM and `SSH_TTY` unset, `stty`'s complaint on stderr, LF ends.
- Hit: at the probe's pty, `40 132`; `stty -a` shows `intr = ^G`, `erase = ^H`, `-ixon` (and speed 38400,
  the rest as the probe's pty had them); after the resize and SIGWINCH, `50 100`. With stdin not a
  terminal, `stty -a` reads linux's pty defaults (rows 0, columns 0, intr ^C, erase ^?, `ixon`).
- Hit: Ctrl-C to a trap: `^Ccaught INT`, status 7; to `exec sleep 30`: `ready`, `^C`, status 255.
- Hit: the full-screen probe: `40 132`, `key=q`, status 0. `ssh host` at the pty: `$ `, the typed line
  echoed, `/dev/pts/N`, `-sh`, status 4.
- Hit, after a second round: a child that ignores SIGHUP and holds the slave does not hold the session:
  the session ends with the shell (0.5 s, the child's sleep 6 s), the child lives on with no terminal
  (`?`). The first round's child had not yet set its trap when its shell ended, and went with the hangup.
  A child without the trap is gone; one in a session of its own (`setsid sleep`) stays. Inside the session
  the shell leads its session and group on `pts/0` in the foreground (`Ss+`), its child in that group
  (`S+`).
- Hit: 20000 lines printed just before the exit all arrive, in order.
- Hit (low confidence): the client's EOF writes nothing to the pty; `cat` echoes and repeats `one` and never
  ends (the 10 s deadline). With a 0x04 byte first: `one` twice, `cat-ended`, status 0.
- **Miss:** keys with `no-pty` and with `restrict`, and `PermitTTY no`: `PTY allocation request failed on
  channel 0`, status **255** and nothing on stdout: under `-tt` the client gives up when its forced pty is
  refused, and the command never runs. `restrict,pty`: a pty, as predicted.
- `sshd`'s own debug log, seen beside it: it allocates the pty in its privileged process and sets the
  controlling terminal with `TIOCSCTTY`. burrowd's chain takes it by the open instead; the measured shape
  (the program leads its session, the slave its terminal, its group the foreground) is the same.

### What the probes change in the design

- **The pty calls (choice 1):** (A) stands, stronger. wolf-std at the pin cannot name a slave on linux or
  macOS. And (B) is incomplete: through `ffi` burrowd could open the pty, `setsid` and take the terminal on
  both hosts, but on macOS it cannot set a window size or call any `ioctl` without a C object of its own
  (E0826), so `window-change` and the initial size would be linux-only.
- **Which end takes the size and the modes:** linux takes `TIOCSWINSZ` on the master (measured) and reads
  the slave's modes through it; macOS refused `TIOCGWINSZ` and `tcgetattr` on the master (std's `io`). The
  design: the child sets the modes on the slave before its exec; the holder sets sizes on the master on
  linux and PAX, and the wolf change measures which end macOS takes. If only the slave, the holder keeps a
  slave descriptor of its own (opened after the child's, so the child's open takes the terminal).
- **No start-up sync:** the master reads nothing (no end) before the slave's first open, on both hosts, so
  the holder waits on the master from the fork on.
- **The end (choice 5) held to `sshd`:** the program's end, then the master drained until it ends (linux EIO,
  macOS end of file) or a short quiet wait (a child left holding the slave), then CLOSE and the master
  closed. A child that ignores SIGHUP outlives the session without a terminal, as through `sshd`.
- **The client's EOF and `eow@openssh.com` on a pty:** taken and ignored, as `sshd` (the pty cannot be
  half-closed; a 0x04 byte is the client's way to end a program's input).
- **Environment:** TERM only when the client's is non-empty; `SSH_TTY` the slave's name. Speeds are not set:
  `sshd`'s pty reads 38400 either way.
- **Rows:** `auth-no-pty` and `session-tty-refused` expect status 255 and the client's PTY line with no
  output (green at the rows tip, as burrowd refuses every pty; `restrict,pty` red); `session-tty-eof`
  holds the deadline shape (both servers leave `cat` running) and the 0x04 shape; `session-tty-gone`
  settles 0.3 s inside the session before the shell ends (the trap's race), and checks the child lives on
  with no terminal; `session-own-session` holds the `ps` shape (`Ss+` leader, `S+` child) on the pty.

### Done-when (phase 1)

- [x] The prediction, committed first (`3e098c4`), with the probes after it.
- [x] What the toolchain can and cannot do, per step and host, measured where a probe was cheap.
- [x] Options and recommendations (§7), revised by the probes above.
- [ ] Rulings on §7; then phase 2 per the plan: the rows red on this branch, the protocol half, and the
  pty half once a wolf release carries the calls.

## Phase 2a: the protocol half and the rows, before the release

The rulings (2026-11-10) took every recommendation in §7: the pty calls come from a wolf change released with
the new session; this branch carries the protocol half and the red rows and merges nothing until then;
`PermitTTY` defaults to `yes`; `no-pty` and `restrict` refuse a pty and `restrict,pty` grants it; the session
ends at the program's end; §8's whole vocabulary; a malformed `pty-req` is refused by name with the connection
kept; no motd or last-login line; the system's `ssh` on the Air; both plants. What burrow asks of the wolf
change is [bw06-wolf-needs.md](bw06-wolf-needs.md).

### What is on the branch

- **Rows first** (`2bfa5b9` to `a596082`): the unit rows (`ttymodes_test`, `schannel_test`, `akeys_test`,
  `sconfig_test`), `PermitTTY no` in both servers' base (`serverlib`), the terminal rows in `check-server`
  (`session-tty-command`, `-size`, `-full-screen`, `-interrupt`, `-shell`, `-gone`, `-burst`, `-eof`,
  `auth-no-pty`, `session-own-session`) and two in `check-server-hostile` (`hostile-pty-malformed`,
  `hostile-pty-granted`); `hostile-requests-refused` now names `PermitTTY no` for its refusal.
- **The protocol half** (`67dade3` to `844b2cb`): `src/ttymodes` (§8 decoded), `schannel` (the `pty-req` and
  `window-change` parse, `pty_refused`, `pty_malformed`, `pty_twice`, `pty_late`, `window_malformed`),
  `akeys` (`no-pty`, `restrict`, `pty`, left to right), `sconfig` (`PermitTTY`), the key's verdict carried to
  the holder; and the pty half written against the calls the release should bring, bound in one module
  (`src/ptyhost`) that at the pin opens no pty (`pty_failed` after the parse) and leads a group, not a
  session.

### Predicted, before the takes (written 2026-11-10 at 15:56Z)

At the rows tip `a596082` (the code as trunk's):

- The four unit files fail to build (no `ttymodes`; no `allow_pty`, `Step.pty`, `Found.pty`, `permit_tty`).
- Every terminal row and both new hostile rows fail by name before any client runs: burrowd refuses
  `PermitTTY yes` (`config_unsupported`), the rows' harness reporting its exit.
- The neighbouring rows hold with `PermitTTY no` in burrowd's base: `session-pty-refused`,
  `session-shell-pty`, `session-shell`, `session-own-group`, `hostile-requests-refused`.

At the head `844b2cb` (the protocol half; no pty at the pin):

- `fmt`, the native build and every unit test on the checked machine, native and lupin: green.
- `hostile-pty-malformed`: green (four `pty_malformed`, the window change ignored, `pty_late`, the output).
- `auth-no-pty`: its `no-pty` and `restrict` cases alike through both servers (255, the PTY line); its
  `restrict,pty` case red (`sshd` grants, burrowd answers `pty_failed`); `pty,restrict` as `sshd` reads it
  left to right (refused), so alike.
- Red by name, until the release: every other terminal row (the client's `PTY allocation request failed on
  channel 0` and 255 through burrowd against `sshd`'s session), `session-own-session` (the shell leads a
  group, not a session, and `-tt` has no pty), `hostile-pty-granted` (FAILURE for the first `pty-req`).
- Unchanged and green: `session-pty-refused`, `session-shell-pty` and `-slow`, `session-shell`,
  `session-own-group`, `session-terminal-stop`, `session-exit-codes`, `session-sigterm`, `auth-forced-shell`,
  `auth-option-unhonoured`, `hostile-requests-refused`, `hostile-program-twice`,
  `hostile-transport-mid-session`.

### The takes, scored

Development takes on the Linux build host's light slots (two CPUs, the pinned container), not records: the
rows tip `a596082` (build, every unit test, the terminal rows and their neighbours) and the head `844b2cb`
(`fmt` too, and more neighbours). Raw logs sha256 `0f196ab4…` and `7f1c2b5b…`; their rows and steps are
`notes/bw06/evidence/phase2a-takes.log`.

- **The rows tip, as predicted:** the four unit files do not build on any machine (checked, native, lupin;
  lupin names each missing field or call); all ten terminal rows and both new hostile rows fail by name
  before a client runs (`config_unsupported: … PermitTTY yes: burrowd takes no only`);
  `session-own-group`, `session-pty-refused`, `session-shell`, `session-shell-pty` and
  `hostile-requests-refused` pass with `PermitTTY no` in burrowd's base.
- **The head, as predicted:** `fmt` and the native build green; every unit test green on all three machines
  (22 files); `hostile-pty-malformed` green; `auth-no-pty`'s `no-pty` and `restrict` cases alike through both
  servers (255, the PTY line) and its `restrict,pty` case red (`sshd` grants, burrowd `pty_failed`); red by
  name, as they stay until the release: `session-tty-command`, `-size`, `-full-screen`, `-interrupt`,
  `-gone`, `-burst`, `-eof` (burrowd 255 and the PTY line against `sshd`'s session), `session-own-session`
  (`sid_is_shell=no` through burrowd, `yes` through `sshd`, with no pty), `hostile-pty-granted` (FAILURE for
  the first `pty-req`); every neighbour green (`session-pty-refused`, `session-shell-pty` and `-slow`,
  `session-shell`, `session-own-group`, `session-terminal-stop`, `session-exit-codes`, `session-sigterm`,
  `auth-forced-shell`, `auth-option-unhonoured`, `hostile-requests-refused`, `hostile-program-twice`,
  `hostile-transport-mid-session`).
- **One shape not predicted:** `session-tty-shell` through burrowd ends at the row's deadline, not with 255:
  with no pty the shell prints no prompt, so the row never types. Red either way.
- **Not reached:** `auth-no-pty`'s `pty,restrict` case, after the first red case. The row now takes every
  case before it fails (`629c957`), so the next take names each.
- `local-tty` (`tools/check-server-local`, the Air) is written (`8e16b35`), after the protocol half; it is
  red until the release (the pty refused), and its first take belongs to phase 2b.
- **`pty,restrict`, measured** (a light take at `490763d`, `auth-no-pty` alone; raw log sha256
  `1a4de65c…`): `sshd` refuses the pty, as for `no-pty` and `restrict` (255, `PTY allocation request failed on
  channel 0`), so it reads the options left to right, as burrowd's `akeys` does; burrowd answers the same.
  The four cases now: `no-pty`, `restrict` and `pty,restrict` alike through both servers; `restrict,pty`
  red until the release (`sshd` grants, burrowd `pty_failed`).
