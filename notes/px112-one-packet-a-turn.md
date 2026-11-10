# px112 — one packet a turn: transport messages never stall a session

On PAX, `ssh host` at a terminal (the pty refused, the login shell served) sometimes hung after a line was typed. The
cause is burrow's, on both sides of a session, and measured black box:

- The pinned OpenSSH clients obscure keystroke timing in a session that asked for a pty (`ssh_config(5)`,
  `ObscureKeystrokeTiming`, on by default): after each keystroke they send fake packets every 20 ms for a while. burrowd
  advertises `ping@openssh.com` (`PROTOCOL` §1.9), so the fake packets are PINGs, each answered with a PONG.
- `transport.next` handles a transport message (IGNORE, DEBUG, UNIMPLEMENTED, PING, a re-exchange) itself and then reads
  the socket again, until a message for the layer above arrives. burrowd's session calls it whenever the socket is
  readable. While PINGs keep arriving, or after one and then silence, burrowd never gets back to the command's output
  or to the input it holds: the command's answer waits in its pipe while the client waits for it.
- A packet capture on PAX's tap showed it: the typed line arrives, then a PING every 20 ms, each answered, and no
  output. A command that answered within 20 ms of the line got its output out before the first PING, which is why the
  rows on Linux had passed. On Linux, with the same client and burrowd, a line that makes the shell wait a second
  (`sleep 1; …`) hangs every time with the client's default, and runs with `-o ObscureKeystrokeTiming=no` or with
  `-T` (no pty request, no chaff).
- It predates the shell: any session that asked for a pty, typed into, whose command takes longer than 20 ms to answer
  (`ssh -t host cat`, typed into) stalls the same way since B5.
- burrow, the client, has the same shape: its session calls `transport.next` whenever the server's side is readable,
  so a server's IGNORE or PING followed by silence, or a stream of them, keeps it from reading its own standard input.
  OpenSSH's `sshd` sends neither unasked, so den and the rows never met it; a server that does would stall an upload.
  A re-exchange the peer starts is handled the same way and so had the same exposure: after it, the reader waits for
  the peer's next packet before it serves its own side again.

## Prediction

Written 2026-11-10 before any change, at trunk `7ea08ba`.

- **The change:** `transport.step`, at most one packet: a message kept from a re-exchange first, else one packet read and
  handled; a transport message gives back nothing, anything else is the message for the layer above. Both sessions'
  turns (`src/ssession`, burrowd's; `src/session`, burrow's) call it in place of `transport.next` and go on with the
  turn when it gives back nothing. Everything before the session (the exchange, authentication, the channel's open and
  its first answers) keeps `transport.next`, where waiting for the next message is what the protocol asks.
- **The rows, red at the rows tip and green after:**
  - `tools/check-server`'s `session-shell-pty-slow`: `ssh host` at a terminal, `sleep 1; echo slow; exit 4` typed once
    the session has answered: through `sshd` (PermitTTY no) `slow` and status 4; through burrowd the same, but for its
    no-pty line. Red: burrowd's session never answers (the row's deadline).
  - `tools/check-server-hostile`'s `hostile-transport-mid-session`: a scripted client runs `sleep 1; echo out`, then
    (one connection) sends one IGNORE and nothing more, and (another) sends a PING every 20 ms for three seconds; in both
    the command's output arrives within two seconds, while the PINGs are still coming. Red: no output in either.
  - `tools/check-hostile`'s `transport-mid-session`: a scripted server, once the command runs, sends one IGNORE and
    waits; burrow's standard input reaches it within two seconds. Red: nothing arrives.
- **Unchanged:** every other row; the time a session takes (a turn still waits at most 5 ms on the socket and 5 ms on
  the command or standard input).
- **Not covered by a row:** a re-exchange started by the peer in the middle of a one-way stream. It takes the same path
  as a PING (handled inside one packet's step), so the change covers it; no row makes the pinned OpenSSH start one at a
  moment the rows control.

## Evidence

Development takes on the Linux build host's light slot (two CPUs, the pinned container), the rows tip `74db8f8` and then
the code's head `9b20646`, one log (sha256 `e2a4e8cf…`): toolchain, oracle, the native build, every unit test, the
client's hostile rows, and the new and neighbouring rows of `tools/check-server` and `tools/check-server-hostile`.

**Red at the rows tip, by name** (each row stops at its first case, one IGNORE):

```text
FAIL transport-mid-session one IGNORE: burrow's input did not reach the server within 2 s ({'input-at': None, 'pongs': 0}); server None
FAIL hostile-transport-mid-session one IGNORE: the command's output did not arrive within 2 s (got [93]…, 0 PONGs)
FAIL session-shell-pty-slow exit -9 through burrowd, 4 through sshd; burrowd stderr 'PTY allocation request failed on channel 0 |  | [row: timed out]', sshd's 'PTY allocation request failed on channel 0 | Connection to 127.0.0.1 closed.'
```

**Green at `9b20646`:** every unit test, every client hostile row, and

```text
PASS transport-mid-session (one IGNORE: input at 0.00 s; a PING every 20 ms: input at 0.00 s, 135 PONGs)
PASS hostile-transport-mid-session (one IGNORE: output at 1.01 s; a PING every 20 ms: output at 1.00 s, 138 PONGs)
PASS session-shell-pty-slow (exit 4, stderr 'PTY allocation request failed on channel 0 | Connection to 127.0.0.1 closed.')
```

with `session-cat-64m`, `server-rekey`, `session-shell`, `session-shell-pty`, `session-pty-refused` and the
hostile session rows beside them.

**The prediction, scored:** each of the three rows red at the rows tip by name and green at the head, as predicted;
nothing else moved. The PING stream's half of each hostile row was not reached at the rows tip (each row stops at its
first case); at the head both halves pass, a PONG for each PING.

## Done-when

- [x] The prediction, committed first (`4a10a88`).
- [x] The three rows red at the rows tip by name, green at the head.
- [x] README, MAP, SOURCES, CHANGELOG; the shell note's stale macOS line.
- [ ] The gauntlet green at the final head; the plant (burrowd's session back on `transport.next`) red by name: the
  PR's records.
