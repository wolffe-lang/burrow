# px112 — a process group of its own, for every session and for burrowd

On PAX, burrowd is started at boot by a hook pid 1 runs. pid 1's session has the console as its controlling terminal,
so burrowd, every session's program and everything they start are in that session, with the console as their terminal.
They are also in the hook's process group, a background group of that terminal. A program run over ssh that touches the
terminal draws a job-control stop for the whole group: `sudo` writes its prompt to the console and then turns the
console's echo off, and SIGTTOU stops the group. That group holds burrowd's listener, so burrowd stops answering until
the machine is restarted.

Measured on PAX under QEMU (a probe of the merged burrowd): over ssh, `/proc/self/stat` reads process group 2, session
1, the console's tty number. After a bare `sudo` over ssh, `sudo`'s prompt was on the console, every new connection
timed out at the banner, and at the console every process of group 2 read `T (stopped)`: the hook, the listener, the
session's monitor and holder, the shell and `sudo`.

The real fix is a session of its own for every program burrowd runs (`setsid` before the program starts, as `sshd`
does), with no controlling terminal at all. The toolchain at burrow's pin has no call for that. Until it has one, this
change does what the pin allows:

## Prediction

Written 2026-11-10 before any change, at `ba2edcc`.

- **The change:**
  - Each session's program leads a process group of its own (`process.lead_group` in the forked child, before it
    becomes the program).
  - burrowd itself leads a group of its own at start, away from the group that started it. A session leader (started
    by `setsid`) may not move and stays as it is.
  - A job-control stop drawn by a session's program then stops that program's group alone: burrowd keeps listening,
    and the other sessions keep running.
- **What it does not fix**, named here and in the README:
  - The program's session and controlling terminal are still burrowd's. On PAX that is the console.
  - A bare `sudo` over ssh still writes its prompt on the console and is stopped there. The client that ran it still
    waits until it is interrupted (`~.`).
  - Every ssh session of a user shares the terminal and session that `sudo` keys its timestamp by.
  - All of that waits for a new session per program.
- **The rows, red at the rows tip and green after:**
  - `tools/check-server`'s `session-own-group`, held to `sshd`: the session's shell leads its process group, and
    `tty_nr` is 0 in the rows' container.
  - `server-own-group`: burrowd's listener leads its group.
  - `session-terminal-stop`: burrowd started as on PAX, in a background group of a session whose controlling terminal
    (a pseudo-terminal of the row's own) another group holds in the foreground. A program over ssh runs
    `stty -echo </dev/tty`, as `sudo` sets the terminal before it reads a password. The program is stopped, and a
    second connection is answered within 15 seconds. Red: the second connection times out, the listener stopped with
    the program.
  - The `session-own-session` row this branch first carried (a session of its own) waits for that toolchain call. It
    is taken out here and comes back with the real fix.
- **Unchanged:** every other row, the signals a session's `kill` and `signal` reach, and the exit status.

## Evidence

Development takes on the Linux build host's light slots (two CPUs, the pinned container): the rows tip `f103f72` (log
sha256 `bd9ccf45…`) and the code's head `1a1ce14` (log sha256 `26356060…`), each with toolchain, oracle, the native build, every
unit test and the session rows beside the new ones. Those commits are the branch before its rebase onto `610e7a1` (the
`limits-startups` row's fix below it), kept on `px112-session-before-rebase`; the rebase moved no line of this change,
and the same two commits are now `0e02704` and `1d6958c`.

**Red at the rows tip, by name:**

```text
FAIL session-own-group stdout differs: burrowd b'pgrp_is_shell=no tty_nr=0\n', sshd b'pgrp_is_shell=yes tty_nr=0\n'
FAIL server-own-group burrowd 179 is in group 1 (the row's is 1)
FAIL session-terminal-stop the second connection after the stop: exit -999, stdout b'', stderr '[row: timed out]' (the listener's state T)
```

The last is PAX's console hang on Linux: the program's `stty` was stopped, and burrowd's listener with it (state `T`).

**Green at `1a1ce14`:**

```text
PASS session-own-group (exit 0, pgrp_is_shell=yes tty_nr=0)
PASS server-own-group (burrowd 179 leads group 179; the row's is 1)
PASS session-terminal-stop (stty stopped (1), the listener S, the second connection answered)
```

with `session-sigterm`, `session-exit-codes`, `session-shell-pty`, `session-id`, `session-cat-64m` and the hostile session
rows beside them.

**The prediction, scored:** each row red at the rows tip by name and green at the head, as predicted; nothing else moved.
What the change does not fix is as predicted and named in the README.

## The first final take: a stop is not an end

The first final take at `74f81ea` went red on `session-terminal-stop` alone (`no stty in state T (stopped)`; record
sha256 `d70b38d4…`), with the listener in `S` and the second connection answered. Two findings from that
take's evidence:

- **The row looked too late.** It looked for the stopped `stty` after the first client had been ended at its 8 s
  deadline. With the client gone, the session's holder ends, which leaves the stopped program's group orphaned, and
  POSIX has the kernel send such a group SIGHUP and SIGCONT: the `stty` was gone before the row looked. The development
  takes happened to look first.
- **burrowd took the stop for the program's end.** The first session's log line reads `status 278`: std's `poll`
  reports a stopped child as `256 + N` (`N` 22, SIGTTOU), and the session's reaping read any change as the end, so it
  stopped watching a program that was only waiting to be continued. Before this change the stop stopped the session
  too, so nothing was left to misread it.

Written before either change, at `74f81ea`:

- **The row:** `session-terminal-stop` looks for the stopped `stty` and asks for the second connection while the first
  session is live; then it ends the stopped program (SIGKILL to its group) and asks that the first session's line name
  that end, `signal KILL`. Red at the code as it is: `status 278`.
- **The change:** the session's reaping passes over a stop (`process.is_stopped`), so a stopped program stays the
  session's until it ends.
- **Unchanged:** every other row; what this does not fix (the client that ran the stopped program still waits; the
  prompt still lands on the console).

## Done-when

- [x] The prediction, committed first (`641d66c`, `f231a22` after the rebase).
- [x] The three rows red at the rows tip by name, green at the head.
- [x] README (what this does not fix), MAP, CHANGELOG.
- [ ] The gauntlet green at the final head; the plant (the program back in burrowd's group) red by name: the PR's
  records.
