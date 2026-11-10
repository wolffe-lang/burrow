# px116 — burrowd: `SetEnv`, the system's variables in every session

On PAX a command run over ssh gets burrowd's bare environment (`HOME`, `USER`, `LOGNAME`, `PATH`, `MAIL`, `SHELL`,
`SSH_CONNECTION`), while the console's shell also has what `/etc/shrc` exports: `WOLF_STD`, `LUPIN_STD` and
`DEN_TLS_ROOTS`. So `ssh host wolf build` resolves another standard library than the console's, and fails, unless the
caller prefixes `. /etc/shrc;` (pax#334). `sshd_config(5)` has the keyword for exactly this, `SetEnv`: variables the
server sets in every session's environment, before the user's shell or command runs. burrowd takes it here; PAX
writes the three variables into its `burrowd_config` from the same text `/etc/shrc` exports.

## Prediction

Written 2026-11-10 before any change, at trunk `9c647a2`, from `sshd_config(5)`'s DESCRIPTION (first value wins;
arguments in double quotes) and its `SetEnv` entry ("one or more environment variables to set in child sessions …
as `NAME=VALUE`. The environment value may be quoted … Environment variables set by SetEnv override the default
environment and any variables specified by the user via AcceptEnv or PermitUserEnvironment"), `sshd(8)`'s LOGIN
PROCESS (step 5, the basic environment), and RFC 4254 §6.4 (`env`), all from the signed `openssh-10.0p2.tar.gz` by
the digests in [SOURCES](../docs/SOURCES.md), unchanged. The pinned `sshd` was measured as a black box first
(`sshd -t`, `sshd -T` and `env` in a session, on the Linux build host's oracle container); every burrowd behaviour
below is a prediction held to those measurements by the rows, and the evidence section scores each.

### The pinned `sshd`, measured

| configuration | `sshd -t` | `sshd -T` | a session's `env` |
|---|---|---|---|
| `SetEnv A=1 B=2` | 0 | `setenv A=1`, `setenv B=2` | `A=1`, `B=2` |
| `SetEnv A=1` then `SetEnv B=2` (two lines) | 0 | `setenv A=1` | `A=1`, no `B`: the first line wins, as for any keyword |
| `setenv A=1`, `SetEnv=A=1` | 0 | `setenv A=1` | |
| `SetEnv A="x y" B=2`, `SetEnv "A=x y" B=2` | 0 | `setenv A=x y`, `setenv B=2` | `A=x y` |
| `SetEnv A=` | 0 | `setenv A=` | `A=` (empty) |
| `SetEnv A=1 A=2` | 0 | `setenv A=1` | `A=1` once: the first value of a name wins |
| `SetEnv A=b=c`, `SetEnv A-B=1`, `SetEnv A=x#y` | 0 | as written | |
| `SetEnv A=1 # c` | 0 | `setenv A=1` | an argument that starts with `#` ends the line |
| `SetEnv FOO`, `SetEnv =x`, `SetEnv none`, `SetEnv A=1 FOO` | 255, `FILE line N: Invalid environment.` | | |
| `SetEnv A="x` | 255, `FILE line N: invalid quotes` | | |
| `SetEnv` alone | 255, `no argument after keyword "SetEnv"` | | |
| `SetEnv PATH=… HOME=… USER=… LOGNAME=… SHELL=… MAIL=… GIT_PROTOCOL=…`, the client sending `GIT_PROTOCOL` | | | each overridden, the client's `GIT_PROTOCOL` too; the shell still starts in the account's home |
| `SetEnv SSH_CONNECTION=…` | | | the real `SSH_CONNECTION`: sshd sets it after `SetEnv` |
| `SetEnv SSH_ORIGINAL_COMMAND=…` under a forced command | | | the client's command: also set after `SetEnv` |

### What changes

- **sconfig:** `SetEnv` is taken (it was `config_unsupported`). Its arguments are split on blanks, double quotes
  around a whole argument or part of one; an argument that starts with `#` ends the list. Each must be `NAME=VALUE`
  with a name before the `=`; the value may be empty. Only the first `SetEnv` line counts (sshd_config's rule);
  within it, the first value of a name wins. A malformed line stops burrowd at start, exit 1, as
  `config_unsupported` with the file, the line and the argument (`FILE line N: SetEnv FOO: not NAME=VALUE`), the
  name every other bad value of a keyword has; an unbalanced quote likewise (`… invalid quotes`).
- **`burrowd -T`:** one `setenv NAME=VALUE` line per variable, in the line's order, as `sshd -T`.
- **The session's environment** (ssession, both programs: a command and the login shell): burrowd's defaults, then
  the accepted `env` names, then `SetEnv`'s variables, each replacing one of the same name; then `SSH_CONNECTION`
  and, under a forced command, `SSH_ORIGINAL_COMMAND`, which `SetEnv` cannot replace. One entry per name.
- **README and MAP:** `SetEnv` in the keyword list; the session's environment in that order.

### The rows

Red at the rows tip (burrowd refuses `SetEnv` as `config_unsupported`), committed before the code:

- `tools/check-server`:
  - `config-setenv`: `burrowd -T`'s `setenv` lines held to `sshd -T`'s for the accepted forms above (one line,
    two lines, quotes both ways, an empty value, a repeated name, a trailing comment); every refused form above
    refused by both (`sshd -t` 255; `burrowd -t` 1, `config_unsupported`, the file and line in its words).
  - `session-setenv`: a session's `env`, sorted, held to `sshd`'s with the same `SetEnv` line (the three PAX
    variables, one value with a space, `PATH` and `HOME` replaced, `GIT_PROTOCOL` replaced over the client's, an
    empty value, a repeated name, `SSH_CONNECTION` named and kept), the only difference `SSH_CLIENT`, as in
    `session-env`; and the same for a shell (`ssh -T host` with `env` on standard input).
  - `session-setenv-forced`: a forced-command key, `SetEnv SSH_ORIGINAL_COMMAND=…`: the client's command, as
    through `sshd`.
- `src/sconfig_test.lu`: `SetEnv` accepted, `-T`'s lines, the first line winning, the refusals by name and line.
  The merge of the four sources gets its own unit assertions with the code (a new function).

### Unchanged

Every other row: `session-env` (no `SetEnv`: the environment as before), the client, the transport, the limits.

## Decisions (recommended, implemented)

1. **The refusal's name for a malformed `SetEnv`:** (A) `config_unsupported`, as every other bad value of a keyword
   burrowd takes (`LoginGraceTime soon`, `Port x`), the detail saying what is wrong; (B) a new name,
   `config_invalid`. Recommended (A): one name for every value refused, and the detail carries the file, the line
   and the argument.
2. **Two `SetEnv` lines:** (A) the first wins, as `sshd` measured and `sshd_config(5)` says of every keyword not
   noted otherwise; (B) they accumulate, as `AcceptEnv` does (its entry says so). Recommended (A).

## Evidence

Development takes on the Linux build host, block B (six CPUs), the pinned container: the oracle probe at trunk
`9c647a2` (log sha256 `f1109e5c…`, and a second for a malformed later line), the rows tip `18f7de7` (log
`a368c770…`) and the code's head `e09e563` (log `fa2528e8…`), each with toolchain, oracle and the build. The
final gauntlet and the plant are the PR's records.

**Red at the rows tip, by name:**

```text
check-test: src/sconfig_test.lu [checked] fail (trap(assert))
FAIL config-setenv one: burrowd -T exit 1, stdout b'', stderr 'burrowd: config_unsupported: …/one.burrowd_config line 1: SetEnv, which burrowd does not have'
FAIL session-setenv harness: RuntimeError: burrowd exited 1: burrowd: config_unsupported: …/burrowd_config line 1: SetEnv, which burrowd does not have
FAIL session-setenv-forced harness: RuntimeError: burrowd exited 1: burrowd: config_unsupported: …/burrowd_config line 1: SetEnv, which burrowd does not have
```

`session-env` held. **A later malformed line** was measured after the first rows (the second probe): `sshd -t`
refuses `SetEnv FOO` after a `SetEnv A=1` that already won (`line 2: Invalid environment.`), and `SetEnv B="x`
likewise (`invalid quotes`). The row gained those two cases, red first (`1c48ad7`), and burrowd checks every
`SetEnv` line it reads, keeping only the first.

**At the code's head `e09e563`:** the build (native and release, warnings denied) and `wolf fmt --check` green;
`session-setenv` and `session-setenv-forced` green on both tiers, with `session-env`, `auth-forced-command`,
`auth-forced-shell` and `session-shell` beside them and every other server row (70 rows a tier, the hostile
client's 18):

```text
PASS session-setenv (command: equal but ['SSH_CLIENT']; shell: equal but ['SSH_CLIENT'])
PASS session-setenv-forced (exit 0, stdout b'forced: 1 echo asked\n')
```

One case stayed red, the row's and the unit's, not the server's: `SetEnv =x`. The row wanted the argument `=x`
refused as itself; burrowd read the line in `sshd_config(5)`'s `keyword=value` form, the keyword, its `=` and the
argument `x`, and refused `x` (`SetEnv x: not NAME=VALUE`). `sshd` refuses both readings alike (`Invalid
environment.`), so its answer cannot tell them apart; the separator rule decides it. The case became `SetEnv =x`
refused as `x`, and an empty name became `SetEnv A=1 =x` (`3e7da5d`, `6bf04f7`).

**The prediction, scored:** every behaviour in the table as predicted, through burrowd and through `sshd` alike,
and one the prediction did not have: a malformed `SetEnv` line after the first is refused too (measured, then
held). The refusal's name and the first-line rule went as recommended.

**Seen beside it, not this change's:** burrowd skips a later line of any other keyword unread, so
`LoginGraceTime 5` then `LoginGraceTime soon`, or `Port 2222` then `Port x`, start burrowd, where the pinned
`sshd -t` refuses both (`line 2: invalid time value.`, `line 2: Badly formatted port number.`), and likewise for
`MaxAuthTries`, `StrictModes` and `PasswordAuthentication` (measured at `e09e563`, burrowd and `sshd` on the same
files). Filed as burrow#22, not fixed here.
