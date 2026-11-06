# bw02 — auth, keys, channels and the CLI (B2, B3)

## Prediction

Written 2026-11-05 23:35Z, at trunk `f4b1e05`, before any B2 or B3 code and
before any run of the pinned OpenSSH for this lane, from RFC 4252, 4254,
8709, 8308, 4250, OpenSSH's `PROTOCOL` and `PROTOCOL.key`, and the
`ssh(1)`, `ssh-keygen(1)`, `ssh_config(5)` and `sshd(8)` man pages of the
pinned 10.0p2. Every number and behaviour of the pinned OpenSSH below is a
prediction; the evidence index records each hit and miss.

### Authentication (RFC 4252), after SERVICE_ACCEPT

burrow sends no `none` request. For each identity, in order (every `-i`,
then every `IdentityFile` of the applying config blocks, else
`~/.ssh/id_ed25519` if it exists):

1. **The query** (§7): `USERAUTH_REQUEST(50)` user, `ssh-connection`,
   `publickey`, FALSE, `ssh-ed25519`, the 51-byte key blob. Its payload is
   107 + len(user) bytes (117 for the rows' `burrowtest`).
2. The server answers `USERAUTH_PK_OK(60)` echoing the algorithm and blob
   (payload 71 bytes; anything else echoed is `malformed`), or
   `USERAUTH_FAILURE(51)`: the next identity is tried.
3. **The signed request:** the query with TRUE and a signature blob
   (`string "ssh-ed25519"`, `string` 64 bytes; RFC 8709 §6) over
   `string session_id, byte 50, string user, string "ssh-connection",
   string "publickey", bool TRUE, string "ssh-ed25519", string blob`.
   Payload 204 bytes for `burrowtest`.
4. `USERAUTH_SUCCESS(52)` ends authentication; `USERAUTH_FAILURE` with
   partial success FALSE moves to the next identity.

Around that:

- **`server-sig-algs`** (RFC 8308 §3.1), from the EXT_INFO burrow already
  reads after NEWKEYS (and a second one during authentication, `PROTOCOL`
  §1.11): when it is present and lacks `ssh-ed25519`, burrow sends no
  publickey request at all and refuses `auth_sig_alg_unsupported`. When it is
  absent, burrow tries (§3.1 allows trial). The pinned `sshd` lists
  `ssh-ed25519` by default and drops it when `PubkeyAcceptedAlgorithms`
  excludes it.
- **USERAUTH_FAILURE's list:** a list without `publickey` is
  `auth_no_publickey` (with the list); partial success TRUE is
  `auth_partial` (burrow does one method); identities exhausted is
  `auth_refused`, with ssh's line `user@host: Permission denied (list).`
- **USERAUTH_BANNER(53)** is written to stderr as the pinned `ssh` writes
  it, byte for byte (predicted: the text as sent, a missing final newline not
  added, control characters other than CR, LF and TAB escaped).
- **USERAUTH_SUCCESS in answer to a query, or before any request**, is
  `auth_success_unrequested`. Any connection-protocol message (80 and up)
  before SUCCESS is `message_unexpected`.
- burrow uses plain `publickey`, never `publickey-hostbound-v00@openssh.com`
  (`PROTOCOL` §3.1's binding serves agent restrictions; burrow has no agent).
- **The pinned `ssh`**, for comparison, sends `none` first, then its query,
  then the signed request; the row's `sshd` log shows a publickey attempt
  without a signature before the one with it, for both clients.

The rekey rows' `--test-auth-none` login (R-bw01-3) is replaced by publickey
and the option is removed.

### Keys

- **`openssh-key-v1`** (`PROTOCOL.key`): `"openssh-key-v1\0"`, cipher
  `none`, KDF `none`, empty KDF options, N = 1, the public blob, then the
  private section: two equal `checkint`s, `string "ssh-ed25519"`,
  `string A` (32), `string seed || A` (64), `string comment`, and padding
  `1, 2, 3, …` to a multiple of 8 (the block size of `none`, measured). The
  private section's layout is "as for the agent", whose draft is not on the
  reading list: it is measured from the pinned `ssh-keygen`'s files and held
  to RFC 8032 (A must equal the public key of the seed).
- **Armour:** `-----BEGIN OPENSSH PRIVATE KEY-----`, base64 in lines of 70
  characters, `-----END OPENSSH PRIVATE KEY-----`, each line ending in LF.
- **Refused by name**, before any connection, exit 255: `key_unreadable`,
  `key_malformed` (armour, base64, layout or padding), `key_encrypted`
  (cipher or KDF not `none`, named in the detail: the pinned `ssh-keygen -N`
  writes `aes256-ctr` and `bcrypt`), `key_count` (N ≠ 1), `key_checkint`,
  `key_unsupported` (any type but `ssh-ed25519`), `key_mismatch` (the
  header's blob, the section's A and the seed's public key disagree),
  `key_permissions` (group or other may read the file, which the pinned `ssh`
  also refuses to use). No detail ever prints key bytes.
- **`burrow-keygen -t ed25519 [-f path] [-C comment] [-N ""] [-q]`**, plus
  `-y -f` and `-l -f`: a 32-byte seed and a checkint from `/dev/urandom`;
  the private file created new with mode 0600 and the `.pub` with 0644
  (the pinned `ssh-keygen`'s modes under umask 022); the public line
  `ssh-ed25519 <68 base64 characters> <comment>` LF, the shape of
  `ssh-keygen`'s; an existing file refused (`exists`, exit 1, nothing
  written; the pinned `ssh-keygen` asks to overwrite and, with no answer on
  its stdin, exits 1 too). A non-empty `-N` is `passphrase_unsupported`.
  Without `-f` it writes `~/.ssh/id_ed25519` without asking.
- The pinned `ssh-keygen -y -f` prints burrow's public line (with the
  comment); burrow reads `ssh-keygen`'s private file and logs in with it;
  `burrow-keygen -y` and `-l` print what `ssh-keygen -y` and `-l` print for
  the same file.

### known_hosts

- **Read:** plain lines with several comma-separated names, `[host]:port`
  for a port other than 22, `*`, `?` and `!` (B1's), and hashed names
  `|1|base64(salt)|base64(hash)`, where hash = HMAC-SHA1 keyed by the
  20-byte salt over the looked-up name (`host` or `[host]:port`): the
  construction is measured against the pinned `ssh-keygen -H`, since no
  allowed text spells it out.
- **Markers:** `@revoked` naming the presented key is `host_key_revoked`
  (B1 said `host_key_changed`); `@cert-authority` lines vouch for nothing
  (burrow takes no certificates) and are skipped with a debug line, so a
  host known only through one is `host_key_unknown`, as the pinned `ssh`
  refuses it too.
- **SHA-1 and HMAC-SHA1** live in `src/sha1`, written from FIPS 180-4 and
  RFC 2104, held to NIST's published vectors, marked for replacement by
  wolf-std#131, and used only for hashed host names.
- **Append:** under `StrictHostKeyChecking=accept-new`, `no` or `off`, an
  unknown host's line is appended to the first `UserKnownHostsFile` as the
  pinned `ssh` appends it: `name ssh-ed25519 base64` LF, or
  `|1|salt|hash ssh-ed25519 base64` LF under `HashKnownHosts=yes`, with the
  warning `Warning: Permanently added 'name' (ED25519) to the list of known
  hosts.` on stderr. A changed key is refused under `accept-new`; under
  `no`, the pinned `ssh` proceeds with public-key authentication and writes
  nothing, and burrow does the same. The default stays strict (`yes`); `ask`
  behaves as `yes`, since burrow never prompts.

### The session channel (RFC 4254)

- `CHANNEL_OPEN(90) "session"`, sender channel 0, initial window 2 MiB
  (2097152), maximum packet 32768 (payload 24 bytes). The pinned `sshd`
  confirms (`91`) with window 0 and maximum packet 32768, then sends one
  `WINDOW_ADJUST` of 2097152 once the command starts.
- Then `env` requests (`98`, want reply FALSE): each local variable a
  `SendEnv` pattern names, then each `SetEnv` pair; then `exec` (want reply
  TRUE) with the command words joined by single spaces, as `ssh(1)` says.
  burrow waits for `CHANNEL_SUCCESS(99)` before sending any stdin;
  `CHANNEL_FAILURE(100)` is `exec_refused`, `OPEN_FAILURE(92)`
  `channel_open_failed`. No pty is ever requested (`-T` is the only mode;
  `-t` is refused).
- **Data:** stdin to `CHANNEL_DATA(94)` in pieces no larger than the
  server's window and maximum packet, `CHANNEL_DATA` to stdout and
  `EXTENDED_DATA(95)` type 1 to stderr, all as raw bytes. burrow sends
  `WINDOW_ADJUST(93)` for what it has written once that reaches half its
  window, so a 64 MiB `cat` sees at least 63 adjustments each way.
- **End:** stdin's end sends `CHANNEL_EOF(96)`; the server's EOF ends
  output; `CHANNEL_CLOSE(97)` is answered once, in whichever order EOF and
  CLOSE arrive; then burrow sends DISCONNECT 11 `disconnected by user` (the
  line the pinned `sshd` logs for its own client) and exits.
- **Exit:** `exit-status` is burrow's exit code (0, 1 and 255 pass through).
  `exit-signal` makes burrow exit 255 with nothing printed at the default
  level, as the pinned `ssh` does when its remote command is killed. A
  channel that closes with neither is 255.
- **Server-opened channels** (`x11`, `auth-agent@openssh.com`, any type)
  get `OPEN_FAILURE` reason 1 (administratively prohibited), named
  `channel_open_refused` in a debug line, and the session goes on.
  `GLOBAL_REQUEST`s wanting a reply get `REQUEST_FAILURE`; the pinned
  `sshd`'s `hostkeys-00@openssh.com` is ignored (`UpdateHostKeys=no` is the
  only mode).
- **Refused by name, exit 255:** `channel_unknown` (a message for a channel
  burrow did not open), `channel_closed` (data after CLOSE, never written),
  `window_exceeded` (data past burrow's window), `channel_packet_too_large`
  (data past burrow's maximum packet), `window_overflow` (an adjustment past
  2^32 − 1).

### The CLI, and the argv shapes den uses

den's ssh transport (`src/transport/ssh.lu`, vc16) starts `ssh` through
PATH with stdin and stdout as pipes, stderr inherited, `GIT_PROTOCOL=version=2`
in its environment, and these argv shapes:

1. `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no
   -o ControlMaster=no -o ControlPath=none -o ClearAllForwardings=yes
   -o ConnectTimeout=30 -o SendEnv=GIT_PROTOCOL -- HOST 'git-upload-pack'
   'PATH'`
2. the same with `-p PORT` before `--`;
3. HOST as `user@host`;
4. `'git-receive-pack'`, or a program named by `DEN_UPLOAD_PACK` or
   `DEN_RECEIVE_PACK`, in the service's place;

each remote word single-quoted (`'` as `'\''`). den's live-ssh harness also
runs `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no
-o ControlMaster=no -o ControlPath=none -o ClearAllForwardings=yes HOST
python3 -I PATH/control.py` with JSON on stdin. Neither passes `-i`, `-l` or
`UserKnownHostsFile`: identities and host keys come from `~/.ssh`.

burrow's CLI is therefore `ssh [-Tv] [-F configfile] [-i identity_file]
[-l login_name] [-o option] [-p port] [--] destination [command
[argument ...]]`, destination `[user@]host` or `ssh://[user@]host[:port]`.

- **`-o` and `~/.ssh/config` keywords:** `BatchMode`, `ClearAllForwardings`,
  `ConnectTimeout`, `ControlMaster` (`no` only), `ControlPath` (`none`
  only), `HashKnownHosts`, `HostKeyAlias`, `Hostname`, `IdentitiesOnly`,
  `IdentityFile`, `Port`, `RekeyLimit`, `SendEnv`, `SetEnv`,
  `StrictHostKeyChecking`, `UpdateHostKeys` (`no` only), `User`,
  `UserKnownHostsFile`. Anything else, and any other value, is
  `option_unsupported`; an unknown flag is `option_unknown`; both exit 255
  (the pinned `ssh` also exits 255 for a keyword it does not know, and
  accepts the keywords burrow lacks).
- **`~/.ssh/config`** (from `$HOME`; `-F` names another file, `-F none` no
  file): `Host` blocks and `Match host` / `Match all`, first value wins,
  `IdentityFile` and `SendEnv` accumulate. A keyword outside the set above
  in a block that applies, another `Match` criterion, `Include`, or a `%`
  token is `config_unsupported`, by name and line.
- **No command** is refused (`shell_unsupported`): B3 has no interactive
  session.
- **Messages:** every refusal still prints `burrow: <name>: <detail>`
  (B1's contract). Where the pinned `ssh` has a line for the same failure,
  burrow prints that line first, with the program's name where `ssh` prints
  its own (`ssh: connect to host 127.0.0.1 port N: Connection refused`,
  `Host key verification failed.`, `user@host: Permission denied
  (publickey).`); each such row holds burrow's exit code to `ssh`'s and
  finds `ssh`'s last stderr line among burrow's.

### Rows

Unit rows, red first, on the checked machine, native and lupin:
`sha1_test` (FIPS 180-4's examples and NIST's byte vectors, HMAC-SHA1 by
NIST's HMAC vectors), `keyfile_test` (round trips and every key refusal),
`knownhosts_test` (plain, hashed, markers, ports, appended lines),
`auth_test` (the query, the signed data and the signed request against
independent vectors from `tools/vectorgen.py`), `channel_test` (windows,
both EOF and CLOSE orders, exit mapping, every channel refusal),
`config_test` (den's argv shapes, `Host` and `Match`, first value wins, every
CLI and config refusal).

Rows against the pinned `sshd` and `ssh` (`tools/check-session`), each with
its own `sshd`, keys made for the run, and the pinned client run beside
burrow where a row compares:

- auth: a key the server accepts (made by `ssh-keygen` and by
  `burrow-keygen`), a key it refuses, a server offering no `publickey`, a
  server whose `server-sig-algs` lacks `ssh-ed25519`, partial success, the
  banner, and the query-then-signature order in the `sshd` log;
- keys: the public line's shape, `ssh-keygen -y` on burrow's file, modes,
  no overwrite, `-y` and `-l` against `ssh-keygen`'s, an encrypted key, an
  RSA key, an unprotected key;
- known_hosts: hashed entries (made by `ssh-keygen -H`), several names,
  `@revoked`, `@cert-authority`, `accept-new` and `HashKnownHosts` lines
  compared with the lines the pinned `ssh` appends (and the pinned `ssh`
  reading burrow's appended file), `no` with a changed key;
- the session: `cat` of 64 MiB of random bytes (NULs, invalid UTF-8)
  compared by digest with the input and with `ssh`'s output; interleaved
  stdout and stderr compared byte for byte with `ssh`'s; exit 0, 1 and 255;
  a remote killed by a signal; `SendEnv=GIT_PROTOCOL` and `SetEnv`; EOF
  first and CLOSE first; 1 MiB of stderr; rekeys during a session at
  `RekeyLimit=256K`;
- the CLI: den's argv shapes; `ssh://`; `~/.ssh/config` with `Host` and
  `Match host`; an unknown flag, an unknown keyword and an unsupported one;
  connection refused; each held to `ssh`'s exit code and line.

Hostile peers (`tools/fakeserver.py`, a scripted server in Python built on
`tools/vectorgen.py`'s primitives, burrow's own code), each red first: a
server that never adjusts the window (burrow sends no more than the initial
4096 bytes and still exits with the server's status), data after CLOSE
(`channel_closed`, never written), an oversize packet (`packet_too_long`)
and an oversize `CHANNEL_DATA` (`channel_packet_too_large`), data past the
window (`window_exceeded`), USERAUTH_SUCCESS before any request
(`auth_success_unrequested`), `exit-status` on another channel
(`channel_unknown`), and `x11` and `auth-agent@openssh.com` opens
(`OPEN_FAILURE` 1, session completes).

### Measured, against the pinned `ssh` on the same host

Interleaved runs, the child's CPU time from rusage and the wall time, the
minimum of several:

- **login to first byte** (start to the first stdout byte of `echo`):
  burrow / ssh wall between 1.2x and 4x (the `sshd` fork and the
  authentication dominate; burrow's X25519, two Ed25519 operations and
  checked-`int` field arithmetic add a few milliseconds);
- **`cat` throughput:** burrow's CPU per MiB between 10x and 100x `ssh`'s
  (wolf-std's ChaCha20 and Poly1305 are checked-`int` code, OpenSSL's are
  assembly); the 64 MiB row finishes within 60 s at `--release` and 5
  minutes native;
- **linearity:** 16 MiB costs at most 6x the CPU of 4 MiB (no quadratic).

The gate's margins: login wall ratio at most 8x, throughput CPU ratio at
most 200x, linearity at most 6x.

### Constant time

Ed25519 signing is wolf-std's `curve25519.sign`, whose scalar multiplication
adds under a branch on each secret bit (std's own `ct:` line names it an
obligation): burrow's one signature per login is therefore not constant time,
and the note says so. The HMAC-SHA1 comparison of hashed names and the
checkint comparison use `wire.ct_eq`; neither guards a secret. B1's tag check
is unchanged.

### For bw03

den finds burrow as `ssh` on PATH, with `~/.ssh/id_ed25519`,
`~/.ssh/known_hosts` and `~/.ssh/config` under a row's `HOME`; den needs no
change.

### The test options, after review

Written 2026-11-06 01:33Z at `cd4313b`, before any change or run for it.
Review asked which test options the release binary keeps, what each does,
and whether any weakens a security property. Four options reach the
transport or the session:

- **`--no-strict-kex`** (B1's) sets the transport's `allow_no_strict`, so a
  server that does not offer `kex-strict-s-v00@openssh.com` is accepted,
  and with it the prefix-truncation exposure strict kex closes. It weakens
  a security property. wolf 0.2.37 has no tier-conditional compilation (its
  one `cfg` is `cfg(target)`, the host triple), and both tiers compile the
  same source, so the release tier cannot drop the flag while the native
  tier keeps it: it leaves burrow's command line on every tier. It is then
  `option_unknown` (the pinned `ssh`'s `unknown option -- -` line, exit
  255), refused before any connection. The transport keeps
  `allow_no_strict` as a library option, and only `src/kexprobe.lu` sets
  it: a row program built into `target/<tier>/rows/kexprobe`, never
  installed, never built `--static`, never uploaded (CI keeps only
  `target/tests` and `target/evidence`). It runs the exchange alone, so
  `downgrade-caught` still proves that the tampered KEXINIT breaks H.
- **`--test-traffic=BYTES`**, after the login, sends IGNORE messages of a
  fixed 1000-byte pattern, then a PING, waits for the PONG and disconnects,
  in place of a command. It is load only: the exchange, the host key, the
  algorithms and the login run first and unchanged, and the payload holds
  no key bytes.
- **`--test-preauth`**, with `--test-traffic`, sends that traffic once more
  before the login, after the first exchange and SERVICE_ACCEPT. Every
  check before it is unchanged, and the login after it is unchanged.
- **`--test-window=BYTES`** (1 to 2097152) sizes burrow's own window on the
  session channel below the 2 MiB default. It only lowers what the server
  may send before an adjustment.

The rows, red first:

- **`no-strict-kex-refused`** (`check-transport`): `--no-strict-kex`
  against a running `sshd` exits 255 with `burrow: option_unknown:`, and
  `sshd` logs no connection. Red at B1's command line, which accepts the
  flag and logs in.
- **`downgrade-caught`** runs `rows/kexprobe` beside the binary under test
  in place of burrow's flag. Red until the probe exists.
- **`test-traffic-inert`, `test-preauth-inert`, `test-window-inert`**
  (`check-transport`): with the option, each of seven conditions is refused
  by the same name as without it. The conditions:
  - the server's strict kex stripped in flight (`strict_kex_missing`)
  - an unknown host key (`host_key_unknown`, with known_hosts still empty)
  - a changed host key (`host_key_changed`)
  - a flipped signature (`host_key_bad_signature`)
  - no common cipher (`no_common_cipher`)
  - a client key the server does not authorize (`auth_refused`)
  - a key file at mode 0644 (`key_permissions`, before any connection)

  Each row also checks that an honest `sshd` is reached with the option in
  effect, and that no line of the client's private key file appears in any
  output. These rows pass before any change, since the options are inert
  already. So they are seen red by a witness instead: a scratch build in
  which each option also waives strict kex and host-key checking must fail
  each row by name. The witness's log goes in the evidence index, and no
  scratch code is committed.

Predicted for the pinned `sshd`: a PING after SERVICE_ACCEPT and before the
login, at the default rekey limits, is answered with its PONG. The login
that follows is unchanged.

## Forbidden

No ssh implementation's code or tests were read: no `.c` or `.h` file of any
OpenSSH release, nothing of dropbear, libssh, libssh2, Go's `x/crypto/ssh`,
paramiko, asyncssh, russh, thrussh, conch, PuTTY or wolfSSH, and no SHA-1 or
HMAC library's source. From the signed `openssh-10.0p2.tar.gz` only the
`PROTOCOL*` notes (bw01's extraction) and the four man pages were taken, by
name. `PROTOCOL.key` says the private key's own fields follow "the rules used
for SSH agent"; `PROTOCOL.agent` points at an Internet-Draft for those, which
is not on the reading list and was not read: the layout was measured from
the pinned `ssh-keygen`'s files (by lengths and comparisons; no key byte was
printed) and is held to RFC 8032 (R-bw02-1). wolf-std's `sha2` was read, as
the organisation's own code the clean room allows, for wolf's 32-bit word
idioms; its `hmac256` is RFC 2104's formula. Python's `hashlib` and `hmac`
were used as black boxes in tools (to cross-check the copied NIST vectors and
one hashed-name vector), never read. No real host was contacted: every row
runs its own `sshd`, or the scripted `tools/fakeserver.py`, on loopback in
the pinned container, with keys made for that run. Private keys stay in the
run directories; rows print public lines and fingerprints, and the evidence
copies are scanned for key files and private key text. The plant branch has
no PR and no CI run.

## Inputs verified

Footprint: cross-cutting

- The toolchain, std and OpenSSH pins are unchanged from trunk `f4b1e05`
  (wolf 0.2.37, lupin 0.1.59, std `5b3a599`, OpenSSH 10.0p2); the tarball's
  signature (`VALIDSIG 7168B983815A5EEF59A4ADFD2A3F414E736060BA`) and digest
  were checked again before the man pages were extracted.
- FIPS 180-4, RFC 2104, NIST's SHA-1 examples and its CAVP SHA and HMAC
  archives by sha256 in [SOURCES](../docs/SOURCES.md); the man pages too.
- The CI workflow gains the session and hostile-peer rows on both tiers and
  the NIST vector check; `ci/local-gate-baseline.json` moves with it (the
  wiring proof passes).

Commits, in order (the row first wherever a row exists):

- `8fb3d32` the prediction.
- `60e6a3f` NIST's vectors, their generator and the gate's check; `2a475f0`
  the SHA-1 rows against a stub, `d401332` SHA-1 and HMAC-SHA1.
- `a181004` vectorgen's B2 and B3 vectors.
- `2713e86` the key file rows against a stub, `fd5f6d5` `openssh-key-v1`,
  `1e4b9d8` the seed rows split out for the checked machine's budget.
- `308e91f` the known_hosts rows and `@revoked`'s new name against a stub,
  `3eaff68` hashed names, markers, appended lines.
- `d9727a3` the CLI and config rows against a stub, `4a1c08b` the module,
  `45b2d16` literal braces.
- `ad52f07` formatting; `42f79a1` the transport written in place (and the
  pending-order fix, below); `75bef5b` the refusal names.
- `4eabc30` the auth rows against a stub, `b2dab34` publickey.
- `4f61f27` the 4 KiB window's vector; `64649ce` the channel rows against a
  stub, `148097a` the channel.
- `6dce587` the -l and RekeyLimit rows, `3ceee02` the fix.
- `b48c649` the build's second program (a stub).
- `9764f38` the oracle, hostile and measured rows, red against B1's CLI.
- `5bd9f04` burrow-keygen, `8b8ba4e` the session, `30d6189` the CLI.
- `a4ce0e7` README, MAP, SOURCES, CHANGELOG; and this note.

## Evidence index

**The rows.** Fourteen unit rows (`src/*_test.lu`, seven of them B2's and
B3's: `sha1`, `keyfile`, `keyseed`, `knownhosts`, `auth`, `channel`,
`config`) pass on the checked machine, natively and on lupin, none falling
back to native. The transport rows (21, B1's, now logging in with a
per-run client key), the session rows (44) and the hostile-peer rows (8)
pass against the pinned OpenSSH and the scripted server on both tiers. Each
row family was red first: the unit rows at their stub commits, by assertion
(`2a475f0`, `2713e86`, `308e91f`, `d9727a3`, `4eabc30`, `64649ce`,
`6dce587`), and the oracle rows at `9764f38`, against B1's CLI. The final
head's gauntlet record, its `END` lines and the plant record are in the PR
body.

**The prediction, hit and missed.**

| predicted | measured |
|---|---|
| burrow sends no `none`; the query, then the signed request | hit (`auth-order`: `sshd` logs the test before the signature, and no `none`) |
| payloads 117 (query) and 204 (signed) for `burrowtest`, PK_OK 71 | hit (`auth_test`, against vectorgen's vectors) |
| the pinned `ssh` sends `none`, its query, then its signed request | hit, with a detail missed: it signs with `publickey-hostbound-v00@openssh.com` |
| `sshd` drops `ssh-ed25519` from `server-sig-algs` under `PubkeyAcceptedAlgorithms` | hit (`server-sig-algs=<rsa-sha2-256>`); burrow refuses, the pinned `ssh` tries anyway |
| the banner byte for byte, controls other than TAB, LF, CR escaped | hit for controls, as `\ooo`; **miss**: bytes from 0x80 up are escaped too (C locale); burrow follows (`auth-banner`) |
| `openssh-key-v1` as laid out, padded to 8, armour of 70, modes 0600 and 0644 | hit (probe and `keygen-*` rows) |
| `ssh-keygen -N` writes `aes256-ctr` and `bcrypt`; overwrite exits 1; `-y` prints the comment | hit |
| hashed names are HMAC-SHA1 keyed by the 20-byte salt over the name | hit (`kh-accept-new-hashed`; the pinned `ssh` reads burrow's file) |
| appended lines and the warning as `ssh`'s; `no` with a changed key proceeds and writes nothing | hit (`kh-accept-new`, `kh-no-changed`, `kh-alias`) |
| `@cert-authority` alone is unknown | hit (`kh-cert-authority`) |
| confirmation with window 0, maximum packet 32768 | hit |
| exit codes pass through; a signal is 255 with nothing printed | hit (`session-exit-codes`, `session-signal`) |
| DISCONNECT 11 `disconnected by user` | hit (`sshd` logs it for burrow) |
| `ssh` exits 255 on a keyword it lacks and takes the ones burrow lacks | hit (`cli-unknown-keyword`, `cli-unsupported-keyword`) |
| (not predicted) | `-l` wins over `user@host` in the pinned `ssh`; burrow followed (`cli-user-precedence`) |
| (not predicted) | the pinned `ssh` ends its log lines in CR LF; burrow's end in LF, and the rows compare lines (R-bw02-2) |
| (not predicted) | OpenSSH 10's per-source penalties refuse 127.0.0.1 after a few failed logins; the rows' `sshd` sets `PerSourcePenalties no` |
| 64 MiB through `cat` within 60 s at `--release`, 5 minutes native | hit: 1.19 s release, 5.37 s native (the pinned `ssh`: 0.34 s) |
| `cat` CPU 10x to 100x `ssh`'s | in the PR body (the final record's `measure` step) |
| login to first byte, 1.2x to 4x `ssh`'s wall | in the PR body |

**Two misses of B1's, found by B3's rows.**

- **Memory grew with traffic.** B1's transport replaced its buffers and
  formatted a detail sentence per packet, and every allocation landed in
  `main`'s region: 1 MiB of traffic held 52 MB, 8 MiB 397 MB (probe 2, on the
  B1 binary). The transport now writes only in place (its detail is bytes it
  owns, its input is compacted, re-exchange keys are `copy`), so each
  function taking `mut c` is ambient-clean, and the session runs every turn in
  a region of its own: 64 MiB through `cat` peaks at 6.3 MB of RSS native and
  5.0 MB release (`session-cat-64m`, sampled from `VmHWM`; the pinned `ssh`
  7.8 MB).
- **A re-exchange let a later message overtake the ones it kept.** `next`
  checked its queue, then started a due re-exchange that queued what
  arrived before the server's KEXINIT, then read the socket and returned the
  newer packet first: at `RekeyLimit=256K`, two 32 KiB chunks of `cat`'s
  output swapped at every re-exchange (`session-rekey` red at a work-in-
  progress head; the lane's probe 3 found the swap). `next` now looks at its
  queue again after a re-exchange. The history was cut after the fact, so
  the fix sits in the transport commit `42f79a1`, ahead of the row's commit;
  the red is in the lane's run log, not in this branch's history.

**The measurement** (`tools/measure-session`): interleaved rounds against the
pinned `ssh` on one quiet block with nothing beside it, the minimum of five,
the client's own CPU from `wait4` and the wall time; its ratios and their
margins (login wall at most 8x, `cat` CPU at most 200x, burrow's 16 MiB over
4 MiB CPU at most 6x) are the final record's `measure` step, in the PR body.

**Where constant time matters.** B1's tag comparison is unchanged. The user
key's signature is wolf-std's `curve25519.sign`, whose scalar multiplication
adds under a branch on each secret bit (std's own `ct:` line names it): one
signature per login is not constant time, and burrow says so in MAP. burrow's
own code never branches on or indexes by the seed. The hashed-name and
check-word comparisons use `wire.ct_eq`, though neither guards a secret.

**Rulings.**

- **R-bw02-1, the private key's fields.** (a) Measure them from the pinned
  `ssh-keygen`'s files and hold them to RFC 8032 (implemented); (b) admit the
  agent Internet-Draft `PROTOCOL.agent` points at. Recommended: (a).
- **R-bw02-2, the message shapes.** (a) Print the pinned `ssh`'s line where it
  has one (with the program's own name, so `ssh: …` when installed as `ssh`),
  then `burrow: <name>: <detail>`, each ending in LF (implemented; the rows
  hold the exit code and find `ssh`'s last line among burrow's); (b) burrow's
  line alone; (c) `ssh`'s byte for byte, CR LF included. Recommended: (a).
- **R-bw02-3, `server-sig-algs` without `ssh-ed25519`.** (a) Refuse by name
  before any request (implemented: RFC 8308 §3.1 warns of penalties for
  trial); (b) try anyway, as the pinned `ssh` does. Recommended: (a).
- **R-bw02-4, the home directory.** (a) `$HOME` for `~/.ssh` (implemented:
  PAX has no passwd database, and den's rows set `HOME`); (b) the passwd
  entry, as OpenSSH documents for itself. Recommended: (a).
- **R-bw02-5, keywords burrow lacks.** (a) Refused by name in a block that
  applies, unread in one that does not, and a keyword `ssh_config(5)` does
  not list refused anywhere, as `ssh` refuses it (implemented); (b) refused
  anywhere. Recommended: (a), so one unrelated `Host` block does not stop
  burrow.
- **R-bw02-6, waiting on a socket and stdin.** wolf-std has no one wait over
  both at the pin (`net.wait` takes the network table's handles,
  `signal.wait_fds` files). (a) Alternate 5 ms waits when idle (implemented:
  input waits at most 5 ms, the socket not at all once ready); (b) a task
  per direction. Recommended: (a) now, and a wolf-std issue for one wait.
- **R-bw02-7, plain `publickey`.** (a) Sign with `publickey` (implemented);
  (b) `publickey-hostbound-v00@openssh.com`, as the pinned `ssh` does.
  Recommended: (a): the binding serves agent restrictions, and burrow has no
  agent.
- **R-bw02-8, the test options.** `--test-traffic`, `--test-preauth` and
  `--test-window` stay in the release binary, as bw01's did, named in the
  program's header and MAP. Recommended: keep them until a lane moves them
  behind a build flag.
- **R-bw02-9, `@revoked`.** A `@revoked` line holding the presented key
  refuses whatever its host patterns (B1's behaviour, kept). Recommended:
  keep; it is stricter than matching hosts first.
- **R-bw02-10, no command.** Refused (`shell_unsupported`), where the pinned
  `ssh` starts a shell. Recommended: keep until a lane adds a pty session for
  people on PAX.

**Issues to file** (for the orchestrator; none filed here):

- wolf-std: one wait over sockets and files together (R-bw02-6).
- wolf-std: constant-time Ed25519 signing (the scalar multiplication's
  bit-gated add; std records it as an obligation already).
- wolf-std#131 (SHA-1): when it lands, `src/sha1` goes.
- lupin: a bare hex literal in a `wrapping[u64]` struct field's initializer
  is read as `i32` and traps (`src/sha1`'s initial words needed typed
  `let`s); native and the checked machine take it.

## For bw03

**What den's ssh rows need.** den starts `ssh` through PATH, so burrow goes
on PATH under the name `ssh` (a link: its messages then say `ssh:` as the
pinned client's do). den passes neither `-i` nor `UserKnownHostsFile`, so the
rows give burrow a `HOME` with `~/.ssh/id_ed25519` (0600; `burrow-keygen` or
`ssh-keygen` makes it), `~/.ssh/known_hosts` with the server's line (or
`StrictHostKeyChecking=accept-new` in `~/.ssh/config`), and, where the row
needs them, `Host` blocks with `IdentityFile`, `UserKnownHostsFile`,
`Port`, `User`, `Hostname` and `HostKeyAlias`. The environment carries
`GIT_PROTOCOL=version=2`, which den's `-o SendEnv=GIT_PROTOCOL` sends; the
server must `AcceptEnv GIT_PROTOCOL`. The exact argv is in the prediction
above and in `cli-den-argv`, which runs it through burrow-as-`ssh` against
the pinned `sshd` and compares with the pinned `ssh`.

**A draft of bw03 (B4: den over burrow).**

1. The prediction: den's ssh rows through burrow, and what changes.
2. den's ssh-interop leg pointed at burrow against the pinned `sshd` in
   burrow's container (clone, fetch, push, the scp-like and `ssh://` forms,
   leases), with a burrow built at its pinned head; den itself unchanged.
3. The live push to the fixture: its URL and deploy key from environment
   variables, the row SKIPping by name when they are absent; public text
   never names it.
4. `tools/build --static` for PAX, handed to a px lane with the resolver gap
   (wolf-lang#831, wolf-std#4) worked around by an address and
   `HostKeyAlias`.
5. One plant, local, at a den-over-burrow row.

## Done-when

- [x] The prediction, committed first (`8fb3d32`).
- [x] `publickey` with `ssh-ed25519`: the query, then the signed request;
  `server-sig-algs` honoured; FAILURE's list and partial success refused by
  name; the banner as `ssh` shows it.
- [x] OpenSSH's private key format read and written for unencrypted Ed25519
  keys, every other kind refused by name; `burrow-keygen`, its files read by
  the pinned `ssh-keygen`, and `ssh-keygen`'s read by burrow.
- [x] known_hosts: hashed names, markers, several names, ports; SHA-1 and
  HMAC-SHA1 from FIPS 180-4 and RFC 2104 against NIST's vectors; appending
  under `accept-new` and `no`, as `ssh` appends.
- [x] The session channel: `env`, `exec`, byte-clean streams, both windows,
  EOF and CLOSE in both orders, `exit-status` and `exit-signal` as `ssh` maps
  them; 64 MiB through `cat` compared by digest.
- [x] The CLI den uses, `~/.ssh/config`'s `Host` and `Match host`, every
  refusal by name and held to `ssh`'s exit code and line.
- [x] Hostile peers, each refused or survived by name.
- [x] Measured against the pinned `ssh`, with stated margins.
- [x] README, MAP, SOURCES and CHANGELOG refreshed.
- [ ] The final-head gauntlet record, the plant record and the audit: in the
  PR body.
