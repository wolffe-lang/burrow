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
