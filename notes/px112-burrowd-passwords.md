# px112 — burrowd: password authentication against /etc/shadow (for B6)

burrowd (B5) is key-only. Putting it on PAX (B6) needs a way in before any
key is there: an account's password, checked against `/etc/shadow` with
wolf-std's scrypt in crypt(5)'s `$7$` form, the hash PAX's own `login`,
`su`, `sudo` and `passwd` use. This note is that half of B6; PAX's half (the
image, the boot start, the first-boot host key, den's two services and the
rows under KVM) is PAX's own note.

## Prediction

Written 2026-11-09 before any change, at trunk `84e2978`, from RFC 4252 §5,
§5.1 and §8, `sshd(8)` (its account-accessibility paragraph and LOGIN
PROCESS), `sshd_config(5)` (`PasswordAuthentication`,
`PermitEmptyPasswords`, `MaxAuthTries`, `LoginGraceTime`,
`PermitRootLogin`, `UsePAM`, `KbdInteractiveAuthentication`), `ssh(1)`
(`SSH_ASKPASS`, `SSH_ASKPASS_REQUIRE`) and `ssh_config(5)`
(`NumberOfPasswordPrompts`, `PreferredAuthentications`), all from the signed
`openssh-10.0p2.tar.gz` by the digests in [SOURCES](../docs/SOURCES.md);
shadow(5) from Ubuntu 24.04's `passwd` package (4.13+dfsg1-4ubuntu3.2,
the page's sha256 `52c0c09aed98bdb56af7ea2a8497f9e1ffe90e2f0a920f8484cd887c381afdbc`);
crypt(5)'s `$7$` as wolf-std's sc80 reads it; and from wolf-std
at `2411d868` (`std.x.crypto.passwd`, `std.x.crypto.scrypt`). Every
behaviour of the pinned `ssh` and `sshd` below is a prediction; the
evidence section scores each.

### What changes

- **The std pin** (R-px112-1): `std.x.crypto.passwd` is not in the std
  burrow pins (`5b3a5994`, the wolf 0.2.37 archive's) nor in any wolf
  release's bundled std (0.2.38 bundles `d4a4d4ca`, before it). burrow's
  `[std] rev` moves to `2411d868` (sc80's merge, wolf-std's trunk), wolf
  0.2.37 and lupin 0.1.59 unchanged. `tools/fetch-toolchain` already stages
  the std at its pin, never the bundled one, so the change is the pin's one
  line, and every existing row is predicted to hold across it.
- **`PasswordAuthentication`** becomes a keyword with two values. Its
  default stays `no` (R-px112-2): burrowd stays key-only unless a
  configuration says otherwise. `PermitEmptyPasswords no`,
  `KbdInteractiveAuthentication no` and `UsePAM no` keep their one value.
  `yes` needs burrowd run as root (only root reads `/etc/shadow`): run as
  another user, `PasswordAuthentication yes` is refused at start,
  `config_unsupported`, which also covers macOS, where burrowd never runs
  as root. `burrowd -T` prints `passwordauthentication no|yes`.
- **The methods list** in USERAUTH_FAILURE is `publickey,password` when it
  is on (the order the pinned `sshd` sends, predicted; measured by the
  client's `Permission denied (publickey,password).`), else `publickey`.
- **The `password` request** (RFC 4252 §8): `FALSE` and the password is a
  check; `TRUE` with an old and a new password is a change request, which
  burrowd refuses (FAILURE, no partial success, a counted try,
  `auth_password_change_refused`): burrowd changes no password and never
  sends SSH_MSG_USERAUTH_PASSWD_CHANGEREQ (R-px112-5). A password longer
  than 1024 bytes is a FAILURE before any hash (`auth_password_too_long`).
- **Where it is checked** (R-px112-4): the worker, unprivileged, parses the
  request and sends the user and the password to the monitor on a new
  frame, `password`. The monitor alone reads `/etc/passwd` and
  `/etc/shadow` and decides. The hash itself runs in a child the monitor
  forks for that one check and reaps (`checker`): scrypt at PAX's shipped
  cost takes 128 MiB, and the monitor lives as long as the session, so the
  memory leaves with the checker. One check runs at a time across the whole
  server: the listener makes a token pipe holding one byte, a monitor takes
  the byte before it forks a checker and puts it back after reaping it, and
  a monitor that ends holding it (its status pipe says `P` when it takes the
  byte and `p` when it returns it) has it put back by the listener. Waiting
  for the token is inside the login grace time. So a hundred unauthenticated
  connections cost one hash's memory at a time, not a hundred.
- **The cap:** a stored `$7$` string is checked only up to PAX's shipped
  cost, N = 2^17, r = 8, p = 1 (wolf-std's `scrypt.memory` of it,
  134,238,240 octets); a dearer one is `auth_password_over_cap`.
- **Equal work for every refusal:** an unknown user, root, a locked,
  expired, empty, unset, unsupported or over-cap password field each get a
  check of a fixed `$7$` string at the shipped cost (taking the token, as a
  real check does), so the time to a FAILURE does not say which accounts
  exist or which have a password burrowd can check.
- **The account's state** (R-px112-3), read by the monitor from the user's
  `/etc/shadow` line, for every method, as `sshd(8)` describes it ("An
  account is not accessible if it is locked ... a leading `!` on most
  Linuxes"): a password field starting `!` refuses publickey and password
  alike (`auth_account_locked`); an account expiry date (field 8, a day
  after 0) before today refuses both, and so does a password expired for
  longer than its inactivity period (fields 3, 5 and 7 all set), shadow(5)'s
  "no login is possible for the user" (`auth_account_expired`). A field
  that is `*` is not locked
  (`sshd(8)`: a key-only account's field is something other than the lock),
  so a key logs in and a password does not (`auth_password_unset`). An
  account with no shadow line, or a host with no `/etc/shadow` (a PAX image
  booted from its archive), is not locked, and has no password
  (`auth_password_unset`). Only as root: burrowd run as another user reads
  no shadow file and serves its own user as before.
- **The password's own state:** empty (`auth_password_empty`:
  `PermitEmptyPasswords no`), another crypt(5) method or a malformed string
  (`auth_password_unsupported`: burrowd checks `$7$` alone, so a stock
  Ubuntu account's `$y$` is refused by name where `sshd` admits it, a named
  difference), and expired (field 3 is `0`, or field 3 plus field 5 is
  before today, both as shadow(5) has them: `auth_password_expired`; RFC
  4252 §8: "the server MUST NOT allow an expired password to be used";
  shadow(5): "In case of a password expiration, the user is not allowed to
  login using her password", so a key still logs in).
- **The tries and the grace** are B5's: every password FAILURE counts toward
  `MaxAuthTries 6`, and the sixth is `auth_tries_exceeded` (DISCONNECT 2,
  `Too many authentication failures`); `LoginGraceTime 120` holds while a
  client takes its time typing.
- **Root** stays refused always (R-bw04-3): a right password for root is a
  FAILURE (`auth_root_refused`), after the equal-work check.
- **The log line:** a password login writes `key password` where a key
  login writes its fingerprint (R-px112-6), so the line keeps its shape.
  The password is never logged, nor its length, nor the shadow field; a
  failed password is `outcome auth_password_bad`.

### The client-visible lines, predicted

The pinned `ssh` with `-o BatchMode=no -o PreferredAuthentications=password
-o PubkeyAuthentication=no` and the password from `SSH_ASKPASS`
(`SSH_ASKPASS_REQUIRE=force`), `NumberOfPasswordPrompts` at its default 3:

| case | the pinned `ssh` prints, both servers alike | exit |
|---|---|---|
| the right password | the command's output, nothing on stderr | the command's |
| a wrong password, three times | `Permission denied, please try again.` twice, then `burrowtest@127.0.0.1: Permission denied (publickey,password).` | 255 |
| a locked account (`!`), the right password | the same as a wrong password | 255 |
| an expired account (field 8), the right password | the same | 255 |
| root, its right password, `PermitRootLogin no` | the same, `root@127.0.0.1` | 255 |
| an empty field, an empty answer | the same | 255 |
| `NumberOfPasswordPrompts=10`, every answer wrong | `Permission denied, please try again.` five times, then `Received disconnect from 127.0.0.1 port PORT:2: Too many authentication failures` and `Disconnected from 127.0.0.1 port PORT` | 255 |
| `LoginGraceTime 2`, the askpass answering after 5 s | `Connection closed by 127.0.0.1 port PORT` | 255 |
| a locked account, its listed key (publickey) | `burrowtest@127.0.0.1: Permission denied (publickey,password).` | 255 |
| `PasswordAuthentication no` on both | `burrowtest@127.0.0.1: Permission denied (publickey).` | 255 |

Predicted to differ, each named in its row: an expired password (field 3
`0`): `sshd` without PAM admits the password and then, I guess, refuses the
command with a warning that the password has expired; burrowd refuses the
login (`auth_password_expired`), the same three lines as a wrong password.
A `$y$` (yescrypt) password: `sshd` admits it, burrowd refuses it
(`auth_password_unsupported`). A change request (a scripted client's
`TRUE`): both answer USERAUTH_FAILURE without partial success.

### The rows

`tools/check-server` gains the password rows, each held to the pinned
`sshd` with `PasswordAuthentication yes` (and `LogLevel VERBOSE`, so its
own debug lines cannot carry anything of the session), the account's
shadow line made for the row and put back after it:

- `password-accepted` (a command, its stdout and status; the log's `key
  password` and `outcome ok`), `password-wrong`, `password-tries`,
  `password-grace`, `password-root`, `password-locked` (the password, and
  `password-locked-key`: the account's listed key), `password-expired-account`,
  `password-expired` (named difference), `password-empty`,
  `password-unset` (no shadow line: the key still logs in, a password does
  not), `password-unsupported` (`$y$` from the image's own `chpasswd`: named
  difference), `password-over-cap` (a `$7$` string one step past the cap:
  burrowd's alone), `password-off` (`PasswordAuthentication no`: the
  methods list says `publickey` only), `password-start-refused` (burrowd
  run as a user other than root with `PasswordAuthentication yes`: exit 1,
  `config_unsupported`).
- Every password row checks that the password appears in neither server's
  log, nor the client's output, nor the row's evidence copy, compared in
  memory and never printed.
- `tools/check-server-hostile` gains `hostile-password-change` (a `TRUE`
  request: FAILURE without partial success from both), and
  `hostile-password-flood` (twenty connections each sending a wrong
  password at once: every one answered within the grace, at most one
  checker alive at any moment, by `/proc`).
- Unit rows: `sauth_test` (the `password` request parsed, the change form,
  the methods list), `spass_test` (a new module: the shadow line's state,
  locked, expired, empty, unset, unsupported, over the cap, and the check),
  `sconfig_test` (the keyword's two values and `-T`'s line), `slog_test`
  (`key password`).

The rows' passwords are made per run (Python's `secrets`), reach the client
only through the askpass program's environment and the shadow line only
through a row program's standard input (`target/<tier>/rows/mkpw`, wolf-std's
`passwd.hash` at a cost the row names), and are never written to a file,
an argument vector, a log or a record.

Red first: every row above but `password-off` and `password-start-refused`
is red at trunk (burrowd refuses `password` by name, and
`PasswordAuthentication yes` is `config_unsupported`), committed before the
code.

### Measured

| measure | predicted |
|---|---|
| a password login to the first byte, burrowd / `sshd`, release, the shipped cost | 1.0x to 1.5x: both spend the hash (about 0.45 s on the build host's cores, sc80's own witness), burrowd one fork more |
| a wrong password's FAILURE, unknown user / known user, burrowd | 0.8x to 1.25x (the equal-work check) |
| twenty simultaneous wrong passwords, the last FAILURE | about 20 hash times, never more than one checker at once |

### Rulings to recommend

- **R-px112-1, the std.** (A) burrow's std pin to wolf-std `2411d868`,
  the toolchain otherwise unchanged; (B) copy wolf-std's two modules into
  burrow; (C) wait for a wolf release that bundles them. Recommended: (A).
  The footprint is `cross-cutting` (a pin).
- **R-px112-2, the default.** (A) `PasswordAuthentication no` stays
  burrowd's default, and PAX's shipped configuration says `yes`; (B)
  `yes`, as `sshd`. Recommended: (A): B5's posture (no password crosses
  the network unless a configuration asks) stands everywhere a line does
  not say otherwise.
- **R-px112-3, locked accounts.** (A) `sshd(8)`'s rule: a leading `!` or a
  past expiry refuses every method, a key included, by name; (B) the lock
  refuses passwords only. Recommended: (A), held to the pinned `sshd`. On
  PAX an account whose password is locked (`passwd -l`, or an install's
  `n` at the password question) cannot log in with a key either until
  `passwd` gives it one; PAX's note says so.
- **R-px112-4, where and how often the hash runs.** (A) a checker child
  per password, one at a time across the server, capped at PAX's shipped
  cost, with equal work for every refusal; (B) in the monitor, as many at
  once as connections. Recommended: (A).
- **R-px112-5, changing passwords.** (A) refused: a change request is a
  FAILURE and an expired password a refusal by name, the console's
  `passwd` the only way to change one; (B) SSH_MSG_USERAUTH_PASSWD_CHANGEREQ
  and a change written to `/etc/shadow`. Recommended: (A).
- **R-px112-6, the log line.** (A) `key password` in the key field; (B) a
  new `method` field on every line. Recommended: (A): the line's shape and
  every consumer of it are unchanged.

**Answered at the prediction (2026-11-09):** R-px112-1 to R-px112-6, all
as recommended. R-px112-1 makes this change `cross-cutting` (the std pin).
R-px112-3: on PAX, an account an install left locked (`!`) cannot log in
with a key until it has a password; PAX's own note and PR say so.

## Evidence: the prediction's hits and misses

**The red-first take** (the pinned container, a six-CPU block of the Linux
desktop): at the rows tip `5a8ee4a`, `unit` exit 1 (no `spass`, no
`sauth.start_with` or `failure_for`, no `Settings.password_auth`), sixteen
password rows `FAIL` by name (fifteen because burrowd refused
`PasswordAuthentication yes` at start, `password-start-refused` because the
refusal named no root), `password-off` passing as the guard it is, and the
three hostile password rows `FAIL` by name. At the first code head
`99d499e`, on the same block in the same job: `unit` exit 0, the seventeen
password rows and the three hostile ones exit 0.

**Hits.** Every client-visible line predicted equal through both servers
was equal: three prompts' `Permission denied, please try again.` twice and
the final `Permission denied (publickey,password).`, wrong then right,
MaxAuthTries's five retries and `Too many authentication failures`,
`Connection closed by 127.0.0.1 port PORT` at the grace, root, a locked
account by password and by key, an expired account, an empty and an unset
password, and `PasswordAuthentication no`'s `Permission denied
(publickey).`. The pinned `sshd` admits a `$y$` and an over-cap `$7$`
string where burrowd refuses both by name, as predicted. A change request
draws USERAUTH_FAILURE `publickey,password` without partial success from
both.

**The guess, scored.** An expired password (field 3 `0`): the pinned
`sshd`, without PAM, admits it and then ends the session with exit 1 and
`WARNING: Your password has expired.` and `Password change required but no
TTY available.`; burrowd refuses the login (`auth_password_expired`) and a
key still logs in. A named difference, as predicted in kind.

**One at a time.** Twenty wrong passwords sent at once on twenty
connections, at the shipped cost on the native tier: twenty FAILUREs in
20.5 s, never more than one checker alive at any sample (20 ms).

**Added after the first take:** `hostile-password-equal-work` (a wrong
password for a real account, root, an unknown account and a locked one,
each FAILURE's time within 0.5x to 2x of the real account's, the minimum
of three interleaved rounds), and the password login in
`tools/measure-server`. Both are timed by the final gauntlet; their numbers
are in the PR.

**The plant's first record** (the password path's account check removed, at `4ed28a4`): `password-expired-account`
went red by name (the right password let in), but `password-locked` held, for two reasons. wolf-std's `passwd.parse`
refuses a `!` hash itself, so the password was still refused, as `auth_password_unset`. And the row's log check matched
the same account's key attempt (`auth_account_locked`), not the password's own line. The lock rows now read each
attempt's own line (`key password`, `key SHA256:`), so the lock's name is held for the password too.

**Red against a mutant.** The two properties no tip could show red (the
one-at-a-time token and the equal work) are shown red against burrowd with
each removed, in the lane's own take, never committed: the PR names the
rows and the numbers.

## Forbidden

No ssh implementation's code or tests were read: no `.c` or `.h` file of
any OpenSSH release, nothing of dropbear or any other server, and no
shadow-utils, PAM or libxcrypt source. From the signed
`openssh-10.0p2.tar.gz` only the man pages `sshd.8`, `sshd_config.5`,
`ssh.1` and `ssh_config.5` and `PROTOCOL` were extracted, by name; shadow(5)
from Ubuntu's `passwd` package, the page alone. The pinned `ssh`, `sshd`,
Ubuntu's `chpasswd` and its crypt (through python3's `crypt`) ran as black
boxes. No password made by a row was written to a file, an argument
vector, a log or a record; each row checked every log and record for its
passwords in memory. Every server bound loopback.

## Inputs verified

- The tarball's sha256 `021a2e70…` before the pages were extracted; the
  pages' digests in [SOURCES](../docs/SOURCES.md), three unchanged and
  `ssh_config.5` new. shadow(5)'s package and page by sha256 (SOURCES).
- wolf 0.2.37 and lupin 0.1.59 unchanged, by digest; wolf-std at
  `2411d868`, staged by `tools/fetch-toolchain` from its commit (the wolf
  archive bundles `5b3a5994`). The OpenSSH oracle's three binaries by the
  digests in `burrow-oracle.toml`, unchanged.

## Done-when

- [x] The prediction, committed first (`56cb674`); the rulings answered.
- [x] The std pin (`4a11847`) and every earlier row holding across it (the
  final gauntlet).
- [x] Password authentication against `/etc/shadow` with wolf-std's `$7$`,
  capped, one check at a time, equal work for every refusal.
- [x] sshd's defaults for the tries and the grace with passwords; locked
  and expired accounts refused by every method, by name; root refused.
- [x] The rows red first at the rows tip (`5a8ee4a`), green at the head,
  held to the pinned `sshd`; the named differences recorded.
- [x] README, MAP, SOURCES and CHANGELOG.
- [x] The final-head gauntlet record, the plant record and the audit: in
  the PR body.
