# What burrow needs from wolf for a terminal (bw06)

burrowd, burrow's ssh server, grants a client's `pty-req` (RFC 4254 §6.2) only once wolf can open a
pseudo-terminal, size it, set its modes, and put a program in a session of its own. At burrow's pin (wolf
0.2.37, wolf-std `2411d868`) none of that is reachable from wolf-std; this file says exactly what burrow will
call, on which hosts, and what it was measured to need. The design and the measurements are in
[bw06-the-terminal.md](bw06-the-terminal.md) and its evidence under `notes/bw06/evidence/`.

burrow calls all of it from one module (`src/ptyhost`), so the names the wolf change finally chooses touch one
file. burrow calls these only in burrowd's native and release builds; its unit tests on the checked machine and
lupin never reach them, so a refusal by name there is enough.

## Who calls, and how

- **The holder** (one process per connection, already running as the logged-in user, never root, never a session
  leader) opens the pty when the client's `pty-req` arrives, sets its size, and keeps the master for the whole
  session: it reads the master, writes the client's bytes to it (non-blocking), waits on it with
  `signal.wait_fds`, sets a new size on each `window-change`, and closes it after the program has ended.
- **The program's child** (a `process.fork` of the holder, not yet exec'd) calls the new session call, opens the
  slave by its name with `fs.open_mode(name, 3)` (which, the runtime passing no `O_NOCTTY`, makes the slave its
  controlling terminal), sets the client's modes on the slave, and then `os_exec`s the shell with the slave on
  descriptors 0, 1 and 2. A spawn in a new session cannot serve here: the slave must be opened between the
  `setsid` and the exec.

## 1. Open a pty

One call that gives back the master's descriptor and the slave's name, with the slave granted and unlocked:
`posix_openpt(O_RDWR | O_NOCTTY)`, `grantpt`, `unlockpt`, `ptsname` (or the host's equivalents), the master
close-on-exec. The slave itself need not be opened by the call; if it is, with `O_NOCTTY`, and burrow will still
open it again by name in the child.

- Rows burrow will name: the host has no pty left or refuses one (`io`, the host's number in `os_error()`);
  windows `unsupported`.
- Hosts: linux, macOS, and PAX (the static linux binary, through its C library: `/dev/ptmx`, `TIOCGPTN`,
  `TIOCSPTLCK`, which PAX's pty branch, px111, serves). PAX gives a slave the opener's ids, and the opener is the
  user, so no `chown` is asked for.
- Measured at the pin: `fs.open_mode("/dev/ptmx", 3)` opens a master on linux and macOS, but nothing in wolf-std
  unlocks or names its slave (linux 7.2.4's `/proc/self/fdinfo` for it carries no `tty-index`). Through the C
  library, the four calls work on both hosts, as root and as an ordinary user.
- Keep, and keep saying in the spec: a runtime open passes no `O_NOCTTY`, so a session leader with no controlling
  terminal that opens a free terminal takes it (s290's spec says so; burrow relies on it on all three hosts).

## 2. The window size

- **Set:** rows, columns, and the two pixel sizes (`TIOCSWINSZ`), each 0 to 65535; the host then sends SIGWINCH
  to the terminal's foreground group. burrow sets it once before the program starts and again on every
  `window-change`.
- **Read:** `term.size` already reads; burrow's rows read it back.
- **Which end, per host, stated in the spec:** on linux the master takes `TIOCSWINSZ` and the child on the slave
  sees the size and the SIGWINCH (measured through the C library). On macOS, wolf-std's `term.size` and
  `term.mode` on a master answer `io` (measured), and the probe could not try `TIOCSWINSZ` at all (wolf 0.2.37
  refuses a variadic `extern "c"` prototype on aarch64-apple-darwin, E0826). The change must measure whether
  macOS takes the size on the master, and say. If it takes it only on the slave, burrow's holder keeps a slave
  descriptor of its own for the session; it needs to know which.

## 3. The modes

The client sends its terminal's modes as RFC 4254 §8's opcode and value pairs (plus RFC 8160's IUTF8). burrow
applies every one the host has, on the slave, before the exec, leaving every other setting as the new pty had
it; a mode the host lacks is skipped, as §8 allows. `term.set_mode` reaches eight of them today (marked `now`).
burrow needs the rest: the special characters and the flags. The call's shape is the wolf change's to choose (a
wider mode, named flags, or §8's numbering as a portable vocabulary); what burrow needs is that each row below
can be set or cleared on its own, and that a call can say which it could not apply.

**Special characters** (`c_cc`; the value is the byte, 255 meaning none, which the host spells as its own
disabled value):

| §8 | name | what it is | note |
|---|---|---|---|
| 1 | VINTR | interrupt (SIGINT) | `term.chars` reads it |
| 2 | VQUIT | quit (SIGQUIT) | reads |
| 3 | VERASE | erase a character | reads |
| 4 | VKILL | kill the line | reads |
| 5 | VEOF | end of file | reads |
| 6 | VEOL | an extra end of line | |
| 7 | VEOL2 | a second extra end of line | |
| 8 | VSTART | resume output | reads |
| 9 | VSTOP | pause output | reads |
| 10 | VSUSP | suspend (SIGTSTP) | reads |
| 11 | VDSUSP | delayed suspend | where the host has it |
| 12 | VREPRINT | reprint the line | reads |
| 13 | VWERASE | erase a word | reads |
| 14 | VLNEXT | next character literally | reads |
| 15 | VFLUSH | flush output | where the host has it |
| 16 | VSWTCH | switch shell layer | where the host has it |
| 17 | VSTATUS | status line | where the host has it |
| 18 | VDISCARD | discard output | reads |

Also VMIN and VTIME (`term.set_mode` sets them now).

**Input flags** (`c_iflag`; value 0 clears, non-zero sets):

| §8 | name | | §8 | name | |
|---|---|---|---|---|---|
| 30 | IGNPAR | | 36 | ICRNL | now (`raw_cr`, inverted) |
| 31 | PARMRK | | 37 | IUCLC | where the host has it |
| 32 | INPCK | | 38 | IXON | now (`flow`) |
| 33 | ISTRIP | now (`strip8`) | 39 | IXANY | |
| 34 | INLCR | | 40 | IXOFF | |
| 35 | IGNCR | | 41 | IMAXBEL | |
| | | | 42 | IUTF8 | RFC 8160 |

**Local flags** (`c_lflag`):

| §8 | name | | §8 | name | |
|---|---|---|---|---|---|
| 50 | ISIG | now (`signals`) | 57 | NOFLSH | |
| 51 | ICANON | now (`canonical`) | 58 | TOSTOP | |
| 52 | XCASE | where the host has it | 59 | IEXTEN | now (`extended`) |
| 53 | ECHO | now (`echo`) | 60 | ECHOCTL | |
| 54 | ECHOE | | 61 | ECHOKE | |
| 55 | ECHOK | | 62 | PENDIN | |
| 56 | ECHONL | | | | |

**Output flags** (`c_oflag`): 70 OPOST (now, `raw_output`, inverted), 71 OLCUC (where the host has it), 72 ONLCR,
73 OCRNL, 74 ONOCR, 75 ONLRET.

**Control flags** (`c_cflag`): 90 CS7, 91 CS8 (the character size), 92 PARENB, 93 PARODD.

**Speeds** (128 TTY_OP_ISPEED, 129 TTY_OP_OSPEED): not needed. The pinned `sshd`'s ptys read 38400 baud whether
or not the client sent its speeds, and so does a new linux pty.

What a byte-for-byte row asks: through the pinned `sshd`, a client at a terminal with `intr ^G`, `erase ^H` and
`-ixon` gets a remote `stty -a` showing exactly those, every other line as the client's terminal had it
(measured; `notes/bw06/evidence/linux-probes.log`, `tt-size-modes-window-change`). burrowd's rows hold its
`stty -a` to that output line for line.

## 4. A session of its own

`os_setsid` (wolf-lang#1089, s290) and wolf-std's `process.lead_session`, called in a forked child that leads no
group. burrowd calls it for every program, with a pty or without: without one the program then has no
controlling terminal at all (`/dev/tty` fails), which is what PAX's console needs.

## 5. The release

The pty calls (1 to 3) and the new session (4) in one wolf release, with wolf-std's functions at a pin that
release bundles or names, so burrow moves its toolchain pin once. lupin and the checked machine may refuse each by
name. A PAX leg on px111's kernel (a fresh pax clone with px111 merged, under QEMU), as s290 had on trunk's: a
static program opens a pty, starts a child in a new session on its slave, sizes it, and sends it 0x03.

## What burrow will bind (provisional names)

burrow's `src/ptyhost` binds, today to refusals and the group call, after the release to wolf-std:

- `open() -> Pty ! {io, unsupported}` with `Pty { master: fs.File, slave: str }`, over the pty open;
- `set_size(master_or_slave, rows, columns, xpixels, ypixels)` over the size set;
- `set_modes(slave, pairs)` over the special characters and the flags, `pairs` §8's decoded list;
- `lead_session()` over `process.lead_session` (today `process.lead_group`, as px112 left it).
