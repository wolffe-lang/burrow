# px112 — burrowd: a shell with no pty (for the next PAX stick)

burrowd serves commands only (B5): a `shell` request is refused by name (`shell_refused`), and so is a
`pty-req` (`pty_refused`). On PAX that means no interactive form at all: `ssh host`, `ssh -t host` and
`ssh -T host` all end with status 255 (pax's tests/mpx5-burrowd, row B12). This change serves the `shell`
request without a pty, as `sshd` does for `ssh -T`: the account's login shell, its standard input, output
and error the channel's. A `pty-req` stays refused by name until PAX has ptys, and when a shell starts
after a refused pty, burrowd says so in plain words on the session's standard error.

## Prediction

Written 2026-11-10 before any change, at trunk `87c2c7e`, from RFC 4254 §6.5 ("Starting a Shell or a
Command": `shell` starts "the user's default shell (typically defined in /etc/passwd)"; "Only one of these
requests can succeed per channel"), `sshd(8)` (its description: an interactive shell or a command "via the
user's shell using its -c option"; LOGIN PROCESS step 9; `command="command"` in AUTHORIZED_KEYS FILE FORMAT:
"this option applies to shell, command or subsystem execution", the client's command "available in the
SSH_ORIGINAL_COMMAND environment variable"), `ssh(1)`'s `-T` and `-t`, and `ssh_config(5)`'s `RequestTTY`,
all from the signed `openssh-10.0p2.tar.gz` by the digests in [SOURCES](../docs/SOURCES.md). Every
behaviour of the pinned `ssh` and `sshd` below is a prediction; the evidence section scores each.

### What changes

- **schannel:** a `shell` request before any program is accepted, once, as `exec` is: CHANNEL_SUCCESS when a
  reply is wanted, the window opened, the program started. A second program on the channel (`shell` or
  `exec` after either) is refused, CHANNEL_FAILURE, named `exec_twice` (RFC 4254 §6.5: only one succeeds).
  `pty-req` stays `pty_refused`; `window-change` and `break` stay taken and ignored.
- **ssession:** for a shell, the account's shell is run as a login shell: `argv[0]` its base name with a
  leading `-` (`-sh` for `/bin/sh`), no `-c`, no further arguments; for a command, as now
  (`sh -c COMMAND`). The environment, the home directory, `/etc/nologin` and the account's ids are the
  command's.
- **A forced command** (`command="…"` on the key's line) runs for a shell request too, never the shell:
  `sh -c FORCED`. `SSH_ORIGINAL_COMMAND` is not set for a shell request (there is no command to carry);
  held to the pinned `sshd`.
- **The plain words:** when a shell starts on a channel whose `pty-req` was refused, burrowd's first bytes on
  the channel's standard error are one line,
  `burrowd: no pty here: this shell runs without a terminal (no line editing, no job control)`.
  Only then: a command after a refused pty (`ssh -t host CMD`) stays byte for byte `sshd`'s (`PermitTTY no`),
  and so does a shell with no pty request (`ssh -T host`).
- **The log line** for a shell is a command's: the outcome, the status; `refused pty_refused` when a pty was
  asked for.
- **burrow, the client,** is unchanged: with no command it already requests a shell with no pty.

### The client-visible lines, predicted

The pinned `ssh` (OpenSSH 10.0p2, the oracle) against burrowd and the pinned `sshd`, an account whose shell
is `/bin/sh`:

| case | both servers | named difference |
|---|---|---|
| `ssh -T host` with `echo out; echo err >&2; exit 3` on standard input | `out` on stdout, `err` on stderr, status 3 | none |
| `ssh -T host` with `echo $0` on standard input | `-sh` | none |
| `ssh -T host` with `echo ${SSH_ORIGINAL_COMMAND-unset}` | `unset` | none |
| a forced-command key, `ssh -T host` with a script on standard input | the forced command's output; the script is its standard input | none |
| `ssh -tt host echo ran` (`PermitTTY no` on `sshd`) | `PTY allocation request failed on channel 0`, then `ran` | none (as B5) |
| `ssh host` at a terminal, `exit 4` typed | burrowd: `PTY allocation request failed on channel 0`, burrowd's plain line, status 4 | `sshd` grants the pty: recorded, not held |

### The rows

Red at the rows tip (burrowd refuses every shell), committed before the code:

- `tools/check-server`: `session-shell` (the first three table rows, byte for byte to `sshd`),
  `auth-forced-shell` (a forced command for a shell request, `SSH_ORIGINAL_COMMAND` unset, held to `sshd`:
  the security row, red first), `session-shell-pty` (`ssh host` on a pseudo-terminal of the row's own, as a
  person types it: the PTY line, burrowd's plain line, `exit 4`'s status; `sshd`'s answer recorded beside it).
  `session-shell-refused` goes: a shell is served now.
- `tools/check-server-hostile`: the refusals row stops listing `shell_refused`; `hostile-program-twice`: a
  scripted client's `shell` and then `exec` on one channel, the second refused (`exec_twice`), the shell's
  output still arriving.
- `tools/check-server-local` (macOS): `local-no-command` becomes `local-shell`: burrow with no command and
  `exit 3` on standard input, status 3.
- `src/schannel_test.lu`: `shell` accepted once, `exec` after it `exec_twice`, `pty-req` still refused.

### Risks, named (the ruling's three)

1. **A forced-command key must never get a shell.** `sshd(8)` applies `command=` to shell requests, and so
   does burrowd: `auth-forced-shell` holds it, red first, and the plant removes exactly that check.
2. **No pty.** The shell has no line editing, no job control and no prompt it can draw on a terminal it does
   not have; ^C at the client is a byte on the shell's standard input, not a signal, so a stuck command ends
   only with the session (`~.` at the client). What pelt prints when it reads a pipe (a prompt or none) is
   PAX's to measure (its tests/mpx5-burrowd).
3. **It amends B5's rule** ("commands only") ahead of B7. ptys (px111, then B7) build on it: a `pty-req`
   granted then makes the same shell interactive.

### Choices to recommend

- **`argv[0]`:** (A) `-sh`, the login form, as `sshd` (predicted, held by `session-shell`); (B) `sh`.
  Recommended: (A).
- **The plain words:** (A) one line on standard error only when a shell starts after a refused pty; (B) also
  for a command after a refused pty (`ssh -t host CMD`), which would differ from `sshd` byte for byte; (C)
  none. Recommended: (A).
- **A second program:** (A) `exec_twice` for `shell` or `exec` after either; (B) a new name.
  Recommended: (A).

## Evidence

Development takes on the Linux build host's light slot (two CPUs, the pinned container), the rows
tip `00ef865` and then the code's head `2204d73`, one log (sha256 `2064bb87…`): toolchain, oracle,
the native build, every unit test, and the new and neighbouring rows of `tools/check-server` and
`tools/check-server-hostile`. The final gauntlet and the plant are the PR's records.

**Red at the rows tip, by name:**

```text
check-test: src/schannel_test.lu [checked] fail (trap(assert))
FAIL auth-forced-shell exit 255 through burrowd, 0 through sshd; burrowd stderr 'shell request failed on channel 0', sshd's ''
FAIL session-shell exit 255 through burrowd, 3 through sshd; burrowd stderr 'shell request failed on channel 0', sshd's 'err'
FAIL session-shell-pty burrowd's stderr does not hold its no-pty line once: exit 255, 'PTY allocation request failed on channel 0 | shell request failed on channel 0'
FAIL hostile-program-twice message 100 instead of CHANNEL_SUCCESS for the shell
```

`auth-forced-command`, `session-pty-refused` and the six-refusal `hostile-requests-refused` held.

**Green at `2204d73`:** every unit test on every tier; then

```text
PASS auth-forced-shell (exit 0, stdout b'forced: unset\necho shell ran\n')
PASS session-shell (a script on stdin: exit 3, stdout b'out\n'; echo $0: exit 0, stdout b'-sh\n'; SSH_ORIGINAL_COMMAND: exit 0, stdout b'unset\n'; stdin not a terminal: exit 5, stdout b'piped\n')
PASS session-shell-pty (exit 4, stderr 'PTY allocation request failed on channel 0 | Connection to 127.0.0.1 closed.'; burrowd adds 'burrowd: no pty here: this shell runs without a terminal (no line editing, no job control)')
PASS hostile-program-twice (the shell served, exec and shell after it refused (exec_twice), the shell's status 5)
```

**The predictions, scored:**

- Hit: `ssh -T host` with a script on stdin is byte for byte alike through both servers: `out`,
  `err`, status 3.
- Hit: `$0` is `-sh` through the pinned `sshd`, the login form, and burrowd matches.
- Hit: `SSH_ORIGINAL_COMMAND` is unset for a shell request, through `sshd` with and without a forced
  command (`forced: unset`).
- Hit: a forced command runs for a shell request through `sshd`, the client's script its stdin, read
  as data; burrowd matches.
- Hit: `ssh -tt host echo ran` is unchanged: no line from burrowd for a command after a refused pty.
- Miss, in the rig's favour: the last table row said `sshd` grants the pty at a terminal. The rows'
  `sshd` runs `PermitTTY no`, so it refuses it as burrowd does, and the row holds the two alike, but
  for burrowd's line. Both print `Connection to 127.0.0.1 closed.` at the end, as `ssh` does when its
  stdin is a terminal.
- Unpredicted, measured: `ssh host` with stdin a pipe (no `-T`) asks for no pty, and runs the same
  shell through both servers (`piped`, status 5).

**The choices** were ruled as recommended, and the code has them: `argv[0]` `-sh`, as `sshd`; the
plain line only for a shell after a refused pty, so a command after one stays byte for byte `sshd`'s;
`exec_twice` for a second program; the line's wording as written.

## Done-when

- [x] The prediction, committed first (`3d13d19`).
- [x] The rows red at the rows tip by name, green at the head; the forced-command row among the red.
- [x] README, MAP, SOURCES, CHANGELOG.
- [ ] The gauntlet green at the final head; the plant (the forced command skipped for a shell) red by
  name: the PR's records.
- [ ] `tools/check-server-local` on macOS (`local-shell`): not taken here; the Mac builds only.
