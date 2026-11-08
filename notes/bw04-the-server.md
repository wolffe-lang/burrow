# bw04 — the server, for commands (B5)

## Prediction

Written 2026-11-08 04:10Z, at trunk `0d98ce9`, before any server code and
before any run of the pinned OpenSSH for this lane, from RFC 4251–4254,
8308, 8709 and 8731 (the server's duties in each), OpenSSH's `PROTOCOL`
(§1.9, §1.10, §1.11, §2.1, §2.2, §2.5, §3.1), `sshd(8)` (LOGIN PROCESS,
AUTHORIZED_KEYS FILE FORMAT, FILES), `sshd_config(5)` (the keywords named
below and their defaults) and `ssh(1)` (ENVIRONMENT), all from the signed
`openssh-10.0p2.tar.gz`; and from wolf-std at the pin (`std.net`,
`std.process`, `std.fs`, `std.signal`, `std.os.users`) for what a server can
be built from. Every behaviour of the pinned `ssh` and `sshd` below is a
prediction; the evidence index will record each hit and miss.

### What the pin gives a server, and what it does not

Measured by reading wolf-std at `5b3a599`, not yet by running it:

- `net.listen`/`listen_with` (an `exists` and a `denied` row),
  `net.accept`, `net.wait` over raw handles, `set_deadline`: enough for a
  listener and a blocking connection.
- `process.fork` (linux and macOS; `busy` while a task lives, so burrowd
  spawns no task), `process.exec` with an argument vector, an environment
  of its own and a descriptor map, `process.pipe`, `fs.set_nonblock` and
  `fs.write_some`, `process.wait_status_core` and `poll_core` (an end by a
  signal as `-N`, `-(256 + N)` with a core), `signal.wait_fds` (files, with
  `child()` to wake on SIGCHLD).
- `process.set_ids(uid, gid, groups)`: one call, one safe order, no way
  back, and **`unsupported` on every host but linux** (macOS has no way to
  read a drop back). So on macOS burrowd cannot become another user at
  all.
- `std.os.users`: passwd and group lines parsed, `groups_of` for the
  supplementary groups.
- **No peer address.** `std.net` has no `peer_address`, at the pin or on
  wolf-std's trunk today: the local port is the only address a socket
  reports. `SSH_CONNECTION` and the log line both need the client's
  address and port (R-bw04-7).
- **No way to hand an accepted socket across `exec`.** `start_with` and
  `adopt_listener` carry listeners only, and a connected stream cannot be
  adopted as a `net.Socket`. So every process that touches the connection
  is a `fork` of the one that accepted it, never an `exec` of a fresh
  image, and what a process holds in memory when it forks is what its
  child holds (the process model below is shaped by this).

### The process model (R-bw04-2's recommendation, A)

```text
burrowd (root, the listener)            never reads the host key's private half
 └─ per connection: monitor (root)      reads authorized_keys, passwd and group; checks modes;
     │                                  verifies the user's signature; writes the log line
     ├─ worker (the unprivileged         every byte the client sends before authentication:
     │   account, set_ids, cwd /)        version, KEXINIT, ECDH, service, USERAUTH_REQUEST
     ├─ holder (root, holds nothing)     forked before the monitor reads the host key; after
     │   └─ becomes the session          authentication it takes the user's uid, gid and groups
     │      (the user)                   (set_ids, no way back) and the worker's transport state
     │       └─ the command              fork, then exec of the user's shell with -c
     └─ (the monitor reads the host key after both forks, and signs exchange hashes for the
         worker and, at re-exchanges, for the session)
```

- **The listener never holds the host key's private half.** At start a
  forked checker child loads the key, applies `sshd(8)`'s mode and owner
  checks, prints its fingerprint in `ssh-keygen -l`'s shape, and exits; the
  listener learns only its verdict. So a fork of the listener holds no key.
- **The worker and the holder are forked before the monitor reads the key,**
  so neither holds it: the worker parses as an account that owns nothing,
  and the session, which the user may trace, never had it.
- **The monitor's requests** are fixed-format messages over two pipes, each
  length-bounded: `sign(H)` (the first H becomes the session identifier
  the monitor holds), `authorized(user, blob)` (a query: the monitor's
  answer is yes or no, never why), `verify(user, blob, signature,
  signed data)` (the monitor checks that the signed data begins with its
  own session identifier and names the same user, `ssh-connection`,
  `publickey`, TRUE, `ssh-ed25519` and blob, that the blob is authorized,
  and the signature; it counts the tries), `authenticated(state)` (the
  worker's transport state: keys, sequence numbers, rekey counters,
  buffered input; the worker then exits), and from the session `sign(H)`
  at a re-exchange and `ended(status)`. A re-exchange's signature is the one
  the monitor gives after authentication: the user's session can ask the
  monitor to sign a hash for as long as it lives, as with any server whose
  post-authentication process re-keys without the host key (named in MAP).
- **The listener counts unauthenticated connections** (MaxStartups) from a
  pipe per monitor: one byte at authentication, end of file at its end.
  `process.poll_core` reaps.
- **Without root** (any host), or on macOS, where `set_ids` is
  `unsupported`: the same processes, all as the invoking user, serving that
  user alone, as `sshd(8)`'s `-h` describes a non-root `sshd`. burrowd as
  root on macOS refuses to start (`privileges_unsupported`).
- **(B), for the measurement only:** one process per connection, root until
  authentication, the host key in it, the command forked as the user. It
  is built as a row program (`target/<tier>/rows/burrowd-oneproc`, never
  installed or built `--static`, as `rows/kexprobe` is), so the trade-off
  is measured, not argued.

### The server's state machine (one connection)

1. **Version** (RFC 4253 §4.2): burrowd sends `SSH-2.0-burrowd_0.0.0` CR LF
   at once, then its KEXINIT without waiting. The client's first line must
   be its identification (§4.2 lets only the server send other lines):
   anything else, a NUL, a line over 255 bytes, or a protoversion other than
   2.0 or 1.99 is refused by name (`version_*`, as the client's names).
2. **KEXINIT:** kex `curve25519-sha256`, `curve25519-sha256@libssh.org`,
   `kex-strict-s-v00@openssh.com`; host key `ssh-ed25519`; cipher
   `chacha20-poly1305@openssh.com` both ways; MAC `hmac-sha2-256` (unused
   under the AEAD, as the client's); compression `none`; no `ext-info-s`
   (burrowd takes no EXT_INFO from a client and ignores one if sent).
   Negotiation is §7.1's with the client's lists first. **Strict kex is
   required:** a client's first KEXINIT without
   `kex-strict-c-v00@openssh.com` is `strict_kex_missing` (DISCONNECT 3);
   with it, anything but the exchange's own messages in the first exchange
   is `strict_kex_violation`, and every NEWKEYS resets that direction's
   sequence number.
3. **ECDH** (RFC 8731): KEX_ECDH_INIT with a 32-byte Q_C (else
   `kex_failed`), X25519 with a fresh secret (an all-zero result
   `kex_failed`), H = SHA-256(V_C, V_S, I_C, I_S, K_S, Q_C, Q_S, K), the
   monitor's Ed25519 signature on H (RFC 8709 §6), KEX_ECDH_REPLY.
4. **NEWKEYS** both ways; then, if the client offered `ext-info-c`,
   EXT_INFO as the next packet (RFC 8308 §2.4) with `server-sig-algs` =
   `ssh-ed25519` and `ping@openssh.com` = `0`. No
   `publickey-hostbound@openssh.com`: the pinned `ssh` then signs with plain
   `publickey` (`PROTOCOL` §3.1: "when advertised").
5. **Service:** `ssh-userauth` is accepted; any other is `service_refused`
   (DISCONNECT 7). A client KEXINIT before authentication is answered
   UNIMPLEMENTED, as the pinned `sshd` answers it (bw01's finding); one
   after authentication starts a re-exchange.
6. **Authentication** (RFC 4252), the methods list always exactly
   `publickey`:
   - `none`, `password`, `keyboard-interactive`, `hostbased` and any other
     method: USERAUTH_FAILURE `publickey`, FALSE; the attempt is logged by
     its method's name.
   - `publickey` without a signature (§7's query): PK_OK when the monitor
     says the key is authorized, else FAILURE. With a signature: SUCCESS
     when the monitor verifies it, else FAILURE.
   - A user or service that changes between requests (§5) ends the
     connection (`auth_changed`), as predicted for the pinned `sshd`.
   - The tries: after the sixth failure (`MaxAuthTries 6`), DISCONNECT 2.
     Which requests count is measured against the pinned `sshd` and
     burrowd follows it.
   - The grace: `LoginGraceTime 120` from the accept; the monitor ends the
     worker and closes the socket when it passes.
7. **The session**, as the user, with the transport state the worker
   handed over (RFC 4254):
   - GLOBAL_REQUEST: `no-more-sessions@openssh.com` noted (no further
     session opens); `tcpip-forward`, `streamlocal-forward@openssh.com` and
     any other refused (REQUEST_FAILURE when a reply is wanted).
   - CHANNEL_OPEN: one `session` channel, confirmed with window 0 and
     maximum packet 32768, as the pinned `sshd` confirms (bw02's finding);
     every other type (`direct-tcpip`, `direct-streamlocal@openssh.com`,
     `x11`, `auth-agent@openssh.com`, …) and a second session are
     OPEN_FAILURE 1 (administratively prohibited).
   - CHANNEL_REQUEST on it: `env` (only R-bw04-4's names; others ignored
     and logged); `exec` (once: the command started, SUCCESS, then
     WINDOW_ADJUST of 2 MiB); `pty-req`, `shell`, `subsystem`, `x11-req`,
     `auth-agent-req@openssh.com`, `signal`, `break` and any other: FAILURE
     when a reply is wanted, logged by name; `window-change` and
     `eow@openssh.com` (no more input to the command: its stdin closed)
     taken.
   - Data both ways within both windows; client EOF closes the command's
     stdin; the command's stdout and stderr ends send EOF; its exit sends
     `exit-status` (or `exit-signal`: the signal's name without `SIG`, the
     core flag, an empty message) and then CLOSE; the client's CLOSE is
     answered once, in either order.

### The split: client-only, shared, server-only

| | modules |
|---|---|
| shared, unchanged | `wire`, `packet`, `chachapoly`, `entropy`, `keyfile` (the host key is an `openssh-key-v1` Ed25519 file; `public_of_line` reads an `authorized_keys` key) |
| shared, extended | `kex` (the server's proposal; negotiation over (client, server) whichever side calls it, each side's strict and ext-info indicators read; KEX_ECDH_INIT parsed and REPLY built; EXT_INFO built), `hostkey` (the signature blob on H), `version` (burrowd's identification; the client's line, with no lines before it), `auth` (`signed_data` is role-neutral already; the request is parsed server-side in a new module), `refuse` (the server's names, in a block of their own) |
| shared engine, with a role | `transport`: the connection's buffers, packets, pending queue, `next`/`send`/`write`/`try_next`, IGNORE/DEBUG/PING/DISCONNECT and the rekey bounds are role-neutral; `dial`, `start`, the client's `exchange`, `check_known_hosts`, `service` and reading the server's EXT_INFO stay the client's. The server's role adds its own constructor from an accepted socket, `start` and exchange (with the monitor as its signer), sending EXT_INFO, answering SERVICE_REQUEST, and UNIMPLEMENTED for a pre-authentication KEXINIT; a re-exchange inside `next` runs the exchange of the connection's role. The role is a field of `Conn`, set by its constructor, so `Options` and the client's call sites do not change. |
| client-only, untouched | `config`, `channel`, `session`, `auth.login`, `sha1`, `src/burrow.lu`, `src/keygen.lu` |
| server-only, new | `src/burrowd.lu` (the program: listener, monitor, worker, holder, session), `sconfig` (the command line and `burrowd_config`), `akeys` (`authorized_keys` and StrictModes), `account` (passwd, group), `monitor` (its requests and answers, both ends), `sauth` (authentication's state machine, no I/O), `schannel` (the session channel's state machine, no I/O), `ssession` (the command, its pipes, the waits), `slog` (the log line), `peer` (the client's address, R-bw04-7) |

Files shared with the client lane working beside this one, and how: in
`src/transport/transport.lu`, new `Conn` fields at the end of the struct
and of `dial`'s literal, new functions, and a role test where a KEXINIT
arrives (the client lane edits `Options` and `check_known_hosts` only);
`src/refuse/refuse.lu`, a block of new names after the client's; `src/kex`,
`src/hostkey`, `src/version` (the client lane does not touch them);
`tools/build` and `tools/gate` (new programs and steps);
`.github/workflows/ci.yml` and `ci/local-gate-baseline.json` (R-bw04-8);
and `README.md`, `docs/MAP.md`, `docs/SOURCES.md`, `CHANGELOG.md`, each in a
section of its own. `tools/fakeserver.py`, `config`, `channel` and
`session` are not touched.

### The command line and the configuration (R-bw04-1's recommendation, A)

`burrowd [-DeqTtV] [-E log_file] [-f config_file] [-g login_grace_time]
[-h host_key_file] [-o option] [-p port]`, each as `sshd(8)` has it: `-D`
is accepted and changes nothing (burrowd never detaches), `-e` logs to
stderr, `-E` appends to a file, `-T` prints the effective configuration
for the keywords burrowd has, in `sshd -T`'s lower-case shape (a row holds
the limits' lines to the pinned `sshd -T`), `-t` checks the configuration
and the host key and exits. sshd's other flags (`-4 -6 -C -c -d -G -i -u`)
are `option_unsupported`. The configuration file is a subset of
`sshd_config(5)`, first value wins: `AcceptEnv`, `AuthorizedKeysFile`
(tokens `%h`, `%u`, `%%`), `HostKey` (one), `ListenAddress`,
`LoginGraceTime`, `MaxAuthTries`, `MaxStartups`, `PermitRootLogin`,
`PidFile`, `Port`, `RekeyLimit`, `StrictModes`, and the keywords whose one
value burrowd has (`PasswordAuthentication no`,
`KbdInteractiveAuthentication no`, `PubkeyAuthentication yes`,
`PermitTTY no`, `X11Forwarding no`, `AllowTcpForwarding no`,
`AllowAgentForwarding no`, `AllowStreamLocalForwarding no`,
`DisableForwarding yes`, `PermitUserEnvironment no`, `PerSourcePenalties no`,
`UsePAM no`, `HostbasedAuthentication no`, `PermitEmptyPasswords no`,
`Ciphers`, `KexAlgorithms`, `HostKeyAlgorithms` and
`PubkeyAcceptedAlgorithms` naming burrowd's own). Another value of one of
those is `config_unsupported`; a keyword `sshd_config(5)` lists and burrowd
lacks is `config_unsupported` too; one it does not list is
`config_unknown`. Every refusal at start exits 1, as `sshd` exits.

### Every refusal, by name

Each is one log line's `outcome`. Where the pinned `sshd` sends a
DISCONNECT for the same condition, burrowd sends the same reason code and
the same text, so the pinned `ssh` prints the same bytes, and the name is
in the log alone (R-bw04-5); where `sshd` has no such condition, the text is
`burrowd: <name>: <detail>`. The pinned `ssh`'s lines below are predicted
(`PORT` stands for the row's port); every row holds burrowd's to `sshd`'s.

**At start** (exit 1, nothing listens):

| name | when |
|---|---|
| `host_key_missing` | no `HostKey` file (the pinned `sshd`: `sshd: no hostkeys available -- exiting.`) |
| `host_key_permissions` | the file is group- or world-accessible, or owned by another user than root (or the running user when not root) |
| `host_key_unreadable`, `host_key_malformed`, `host_key_unsupported`, `host_key_encrypted` | keyfile's refusals of the host key file, by their own reason |
| `config_unknown`, `config_unsupported`, `option_unknown`, `option_unsupported`, `usage` | the configuration or the command line |
| `listen_failed` | the address cannot be bound |
| `privileges_unsupported` | root on a host where `set_ids` is `unsupported` (macOS) |
| `preauth_user_missing` | root, and the unprivileged account (`burrowd`) is not in passwd |

**Per connection**, with the pinned `ssh`'s predicted lines:

| name | when | the pinned `ssh` prints, exit 255 |
|---|---|---|
| `startups_exceeded` | MaxStartups drops the connection before any byte | `kex_exchange_identification: Connection closed by remote host`, `Connection closed by 127.0.0.1 port PORT` |
| `grace_expired` | not authenticated within LoginGraceTime | `Connection closed by 127.0.0.1 port PORT` (`sshd` sends no DISCONNECT) |
| `version_malformed`, `version_too_long`, `version_unsupported` | the client's identification | (a scripted client only) |
| `strict_kex_missing` | no `kex-strict-c-v00@openssh.com` in the client's first KEXINIT | `Received disconnect from 127.0.0.1 port PORT:3: burrowd: strict_kex_missing: …`, `Disconnected from 127.0.0.1 port PORT` |
| `no_common_kex`, `no_common_hostkey`, `no_common_cipher`, `no_common_compression` | negotiation | the client finds it first: `Unable to negotiate with 127.0.0.1 port PORT: no matching cipher found. Their offer: chacha20-poly1305@openssh.com` (and `key exchange method`, `host key type`) |
| `strict_kex_violation`, `kex_failed`, `message_unexpected`, `malformed`, `mac_mismatch`, `packet_too_long`, `packet_too_short`, `padding_short`, `padding_overrun`, `unaligned`, `sequence_wrapped` | the shared transport refusals, against a scripted client | DISCONNECT with the client's codes (MAP) |
| `service_refused` | a service other than `ssh-userauth` | (a scripted client) |
| `auth_method_refused` | `none`, `password`, `keyboard-interactive`, `hostbased`, others (logged, not final) | `burrowtest@127.0.0.1: Permission denied (publickey).` once every method `ssh` has is spent |
| `auth_key_unlisted`, `auth_user_unknown`, `auth_root_refused`, `auth_strict_modes`, `auth_key_unsupported` | no matching line; no such account; root (R-bw04-3); a group- or world-writable home, `.ssh` or file, or one another user owns; a key that is not `ssh-ed25519` — all alike to the client, so no account is disclosed (RFC 4252 §5) | `burrowtest@127.0.0.1: Permission denied (publickey).` |
| `auth_sig_bad` | a signature that does not verify over the session identifier: another session's, another key's, a changed field | the same, for a scripted client |
| `auth_tries_exceeded` | MaxAuthTries | `Received disconnect from 127.0.0.1 port PORT:2: Too many authentication failures`, `Disconnected from authenticating user burrowtest 127.0.0.1 port PORT` |
| `auth_changed` | the user or service changed between requests | (a scripted client) |
| `nologin` | `/etc/nologin` exists (LOGIN PROCESS, step 3): its text on stderr, the session ends | its text, exit 1 |
| `channel_type_refused`, `session_limit` | a channel other than one session | `-W`: `channel 0: open failed: administratively prohibited: open failed`, `stdio forwarding failed` |
| `forward_refused` | `tcpip-forward` and the like | `-R` with `ExitOnForwardFailure=yes`: `Error: remote port forwarding failed for listen port 0` |
| `pty_refused` | `pty-req` (`-tt`) | `PTY allocation request failed on channel 0`, and the command runs (exit as the command's) |
| `shell_refused` | `shell` (no command) | `shell request failed on channel 0` |
| `subsystem_refused` | `subsystem` (`-s … sftp`) | `subsystem request failed on channel 0` |
| `x11_refused` | `x11-req` (`-X`) | `X11 forwarding request failed on channel 0`, and the command runs |
| `agent_refused` | `auth-agent-req@openssh.com` (`-A`) | nothing; the command runs |
| `env_refused` | an `env` name outside R-bw04-4's list (logged, not final) | nothing |
| `exec_twice` | a second `exec` on the channel | (a scripted client) |
| `exec_failed` | the user's shell cannot be started | the pinned `sshd`'s text for it, measured |
| `channel_unknown`, `channel_closed`, `window_exceeded`, `channel_packet_too_large`, `window_overflow` | the client's channel misbehaves (data for no channel, after its EOF or CLOSE, past burrowd's window or maximum packet) | (a scripted client) |
| `disconnected`, `closed`, `timeout`, `io` | the client's DISCONNECT, the socket's end, a deadline, a failure | (none sent) |

A session that ran ends with outcome `ok` and its exit status (or signal).

**`authorized_keys`** is read as `sshd(8)` documents it, from
`AuthorizedKeysFile` (default `.ssh/authorized_keys .ssh/authorized_keys2`,
relative to the home), by the monitor as root: comments and empty lines
skipped, lines up to 8 KiB, an optional options field, then the key. Only
`ssh-ed25519` keys can match. Of the options, `command="…"` is honoured
(the client's command in `SSH_ORIGINAL_COMMAND`), and `restrict`, `no-pty`,
`no-port-forwarding`, `no-agent-forwarding`, `no-X11-forwarding` and
`no-user-rc` are taken (burrowd allows none of those anyway). A line with
any other option (`from=`, `environment=`, `expiry-time=`,
`cert-authority`, `principals=`, `permitopen=`, `permitlisten=`,
`tunnel=`, `pty`, …) is not used, and the log says so: a restriction
burrowd cannot enforce never admits a key. StrictModes (on, the default)
refuses the files when the home, `~/.ssh` or the file is group- or
world-writable, or owned by another user than the account or root.

### The log

One line per connection, written by the monitor when the connection ends,
to stderr (`-e`) or the `-E` file:

```text
2026-11-08T04:10:00Z burrowd[PID]: from 127.0.0.1 port 51234 user burrowtest key SHA256:… outcome ok status 0
```

The time in UTC (`date -u`'s ISO form), the client's address and port
(R-bw04-7), the user as sent (bytes outside printable ASCII as `\ooo`, at
most 64 bytes, so a name cannot forge a line), the fingerprint of the key
that authenticated (or of the last key offered, else `-`), the outcome by
name, and the exit status (`status N`, `signal TERM`, or `-`). Never a
private key, the command, an environment value, or a byte of the session.
At start, one line: the host key's `ssh-keygen -l` line (`256 SHA256:…
comment (ED25519)`) and the addresses it listens on.

### The rows (`tools/check-server`), each held to the pinned `sshd`

Each row starts the pinned `sshd` and burrowd on their own loopback ports
in the pinned container, with **the same** per-run Ed25519 host key (sshd
given that key alone), the same `authorized_keys` in the account's own
`~/.ssh` (StrictModes on, both), the same account, the equivalent
configuration, and runs the pinned `ssh` against each with the same
arguments and the same `known_hosts` (one line per port). It compares
stdout bytes, stderr lines with the port written `PORT`, and the exit
status. A row prints `PASS`/`FAIL <row>` at column 0. Rows on both tiers.

- **Transport:** `server-true` (`ssh host true`, exit 0, nothing on
  either stream; `ssh -v` names `curve25519-sha256`, `ssh-ed25519`,
  `chacha20-poly1305@openssh.com` and strict kex for both), `server-version`
  (`-v`'s `remote software version burrowd_0.0.0`), `server-ext-info`
  (`-vvv` shows `server-sig-algs=<ssh-ed25519>`), `server-refused-cipher`,
  `server-refused-kex`, `server-refused-hostkey` (the client offering only
  `aes128-ctr`, only `ecdh-sha2-nistp256`, only `rsa-sha2-256`, held to
  `sshd` configured with burrowd's one algorithm of each), and
  `server-rekey` (4 MiB through `cat` at the client's `RekeyLimit=256K`, and
  again at burrowd's and `sshd`'s own `RekeyLimit 256K`: the bytes equal,
  burrowd's debug line counting at least 15 exchanges each way).
  `server-strict-kex-required` is burrowd's alone (the pinned `sshd`
  admits a client without strict kex): the client's indicator stripped by
  `tools/mitm.py` is refused by name.
- **The host key:** `hostkey-required` (no file: both refuse to start,
  exit 1), `hostkey-mode` (0644: both refuse), `hostkey-owner` (another
  user's file), `hostkey-fingerprint` (burrowd's start line equals
  `ssh-keygen -l` and `burrow-keygen -l` of the same file), and keys made
  by `ssh-keygen` and by `burrow-keygen` both serve.
- **Authentication:** `auth-accepted` (both key makers),
  `auth-unlisted`, `auth-ssh-dir-writable` (0777 `.ssh`),
  `auth-home-group-writable`, `auth-keys-file-writable`,
  `auth-keys-owner` (the file another account's), `auth-tries` (seven
  unlisted keys offered; held to `sshd`'s count and text),
  `auth-grace` (`LoginGraceTime 2`, the client held after the exchange by
  `tools/mitm.py`), `auth-root` (root's own key listed: refused, held to
  `PermitRootLogin no`), `auth-methods` (`PreferredAuthentications=
  password,keyboard-interactive`), `auth-unknown-user`,
  `auth-forced-command` (`command="…"` in `authorized_keys`, with
  `SSH_ORIGINAL_COMMAND`, as bw03's recorder row), `auth-nologin`.
- **The session:** `session-cat-64m` (64 MiB of random bytes through `cat`,
  compared by digest with the input and with `sshd`'s output),
  `session-interleaved` (stdout and stderr interleaved, byte for byte),
  `session-exit-codes` (0, 1 and 127: stdout, stderr and status equal —
  including the shell's `not found` line, whose first word is the shell's
  `argv[0]`, predicted to be its base name as `sshd` passes it),
  `session-sigterm` (`kill -TERM $$`: exit 255, nothing printed; burrowd's
  log says `signal TERM`), `session-env` (the session's `env`, names and
  values with ports written `PORT`: HOME, LOGNAME, MAIL, PATH, SHELL,
  SSH_CONNECTION, USER and the shell's own; `GIT_PROTOCOL` sent by
  `SendEnv` arrives; `LANG` sent by `SendEnv` does not, under both
  servers' `AcceptEnv GIT_PROTOCOL`; predicted difference: the pinned
  `sshd` also sets `SSH_CLIENT`, which `ssh(1)` does not document, and
  burrowd does not — the row names it), `session-id` (`id` inside the
  session), `session-stdin-held` (8 MiB sent to a command that sleeps
  before it reads: the bytes arrive whole and burrowd's resident memory
  stays under 32 MiB), `session-pty-refused` (`-tt … true`),
  `session-shell-refused` (no command; `sshd` cannot be configured to refuse
  a shell, so this row holds the pinned `ssh`'s line and status to the
  prediction above, and the scripted server control of the client lane
  shows the same line), `session-subsystem-refused`, `session-x11-refused`,
  `session-agent-refused`, `session-forward-refused` (`-R` and `-W`, held to
  `DisableForwarding yes`).
- **git** (`tools/check-server-git`): the image's git (Ubuntu 24.04's from
  the snapshot the image pins, its version in the image's package list)
  with `core.sshCommand` the pinned `ssh`: clone of a bare repository,
  fetch of a second commit, push of a third, and a push the server's
  `receive.denyNonFastForwards` rejects, through burrowd and through
  `sshd`; git's stdout, stderr and status equal, the refs and every object
  equal, `fsck` clean, and `GIT_PROTOCOL=version=2` reaching
  `git-upload-pack` (a wrapper logs it) through `env`.
- **Limits:** `limits-defaults` (`burrowd -T`'s `logingracetime 120`,
  `maxauthtries 6`, `maxstartups 10:30:100` equal `sshd -T`'s lines),
  `limits-startups` (`MaxStartups 3`: three held connections, the fourth
  refused as `sshd` refuses it, and a login succeeds once they end).
- **The log:** `log-line` (one line per connection with every field; the
  run's marker string sent through `cat` and the private key's lines
  absent from the log), and each refusal row's outcome name in it.
- **Privileges:** `priv-session` (`/proc/self/status` inside the session:
  every uid and gid the user's, `Groups` the user's, `CapEff` zero; held to
  `sshd`'s session), `priv-worker` (during a held connection, the worker's
  `/proc/PID/status` has the unprivileged account's ids and the holder's
  root's, and neither process's memory was forked after the host key was
  read: the monitor's log at debug names the order).

**Hostile clients** (`tools/fakeclient.py`, a scripted client built on
`tools/vectorgen.py`'s primitives, and `tools/check-server-hostile`), each
red first against a burrowd that lacks the check: never finishing the
exchange (the grace ends it, `grace_expired`), an oversize packet
(`packet_too_long`), a signed request over another session identifier and
one signed by a key other than the one named (`auth_sig_bad`), channel
data before the channel is confirmed (`channel_unknown`), data past
burrowd's window (`window_exceeded`), an `exec` before authentication
(`message_unexpected`, DISCONNECT 2), a user changed mid-authentication
(`auth_changed`), and a thousand connections that never send a version
line (at most 100 unauthenticated monitors at any time, the listener still
up, and a login succeeding after them).

**macOS** (the Mac, behind its lock): burrowd built and run as the
invoking user on loopback; burrow's own client logs in, runs `true`, the
64 MiB `cat` and the exit codes, and the git rows' clone and push run
through it. There is no pinned `sshd` there; these rows hold burrowd to
its Linux behaviour, not to an oracle.

### Measured (`tools/measure-server`)

Interleaved rounds through the pinned `ssh` against burrowd (release) and
the pinned `sshd`, on one quiet block with nothing beside it, the minimum
of each; the server's CPU is the listener's reaped children's
(`/proc/PID/stat`'s `cutime` and `cstime`), over 20 logins a round to stay
above the clock's tick.

| measure | predicted | margin |
|---|---|---|
| connect to the first byte of `echo`, wall, burrowd / sshd | 0.8x to 3x (sshd re-executes itself per connection; burrowd forks four times and does its X25519 and two Ed25519 operations in checked-`int` code) | at most 6x |
| server CPU per login | 2x to 10x sshd's | at most 25x |
| 64 MiB through `cat`, wall | 3x to 6x sshd's (bw02's client rate: 1.19 s release) | at most 12x |
| 64 MiB through `cat`, server CPU | 5x to 20x | at most 50x |
| R-bw04-2: (A) / (B), connect to first byte, wall | 1.00x to 1.15x (three more forks and six pipe round trips, under 3 ms) | reported, not gated |

### Rulings to recommend

- **R-bw04-1, the name and the binary.** (A) `burrowd`, installed beside
  `ssh` (on PAX `/bin/burrowd`); (B) another name. Recommended: (A), with
  the flags above mirroring `sshd`'s, its configuration a subset of
  `sshd_config(5)` read from `-f` (default `/etc/burrowd/burrowd_config`;
  absent is the defaults, where `sshd` refuses to start without one) and its
  host key from `HostKey` (default `/etc/burrowd/ssh_host_ed25519_key`).
- **R-bw04-2, pre-authentication isolation.** (A) a separate process with
  no privileges; (B) one process, root until authentication. Recommended:
  **(A) on linux and PAX**, as the process model above, measured against
  (B) built as a row program. What PAX supports for it, from its kernel
  README at its trunk: `fork` (a copy of every page, no copy-on-write),
  `execve`, `wait4`, pipes, AF_UNIX socketpairs, `setresuid`,
  `setresgid` and `setgroups` (px103's credentials, which that lane calls
  enforced for honest programs and not yet a boundary against an
  attacker), `PR_SET_NO_NEW_PRIVS` and `PR_SET_DUMPABLE`; no `chroot`
  (refused by name for root), so the worker runs in `/` and not in an empty
  root. macOS cannot do (A) or drop to the user at all (`set_ids` is
  `unsupported`), so burrowd there serves the invoking user alone.
- **R-bw04-3, root over the network.** (A) refused always; (B) refused by
  default, with a line allowing key-only root. Recommended: **(A)**:
  `PermitRootLogin` takes `no` only; root logs in as a user and runs `sudo`
  (PAX has it since px103). Refused alike to the client (`Permission
  denied (publickey).`), named in the log.
- **R-bw04-4, accepted `env` names.** (A) `GIT_PROTOCOL` only; (B) also
  `LANG` and `LC_*`. Recommended: **(A)**: `AcceptEnv` takes
  `GIT_PROTOCOL` only, so an `sshd_config` line `AcceptEnv GIT_PROTOCOL`
  means the same to both servers; other names are logged (`env_refused`)
  and dropped, and the session's locale is the shell's default.
- **R-bw04-5, the refusal's text.** (A) where `sshd` sends a DISCONNECT for
  the same condition, the same code and text, the name in the log alone,
  and `burrowd: <name>: <detail>` elsewhere; (B) the name in every
  DISCONNECT. Recommended: (A), so the client's bytes match `sshd`'s.
- **R-bw04-6, the default listen address.** (A) loopback (`127.0.0.1` and
  `::1`) unless `ListenAddress` names another; (B) every address, as
  `sshd`. Recommended: (A): a LAN listener is a line the installer writes on
  purpose (B6, on PAX), and no row of this lane binds one.
- **R-bw04-7, the client's address.** wolf-std has no peer address.
  (A) on linux, `/proc/net/tcp` and `tcp6`, the entry whose inode is the
  connection's (one of `/proc/self/fd`'s sockets, the listener closed in
  the monitor), and elsewhere `UNKNOWN` and port 0, named in the log; and a
  wolf-std issue for `net.peer_address` (getpeername; PAX answers it); (B)
  wait for std. Recommended: (A) now; PAX, which has no `/proc/net`, needs
  the std call for B6's log.
- **R-bw04-8, CI.** (A) the server rows join the labelled Linux job beside
  the transport and session rows (the footprint `cross-cutting`, a
  `full-matrix` run before the merge); (B) the local gauntlet only (the
  footprint `module`). Recommended: (A): the rows need only the pinned
  image, as the client's do; the git rows and the measurement stay local,
  as den's rows do.

### Hosts

| hardware | for |
|---|---|
| Apple silicon laptop, macOS arm64 | editing, commits, the macOS builds and rows, behind its build lock |
| Linux x86-64 laptop, 8 cores | the oracle rows in the pinned container, one slot, when the host is free |
| Linux x86-64 desktop, i7-12700KF | the oracle rows and the measurement, a six-CPU block by its lock names; the measurement with the block's light lock held |

## Forbidden

No ssh implementation's code or tests were read: no `.c` or `.h` file of
any OpenSSH release, nothing of dropbear or any other server or client,
and no ssh library's tests. From the signed `openssh-10.0p2.tar.gz` only
the man pages `sshd.8`, `sshd_config.5`, `ssh.1` and `ssh-keygen.1` and
the `PROTOCOL`, `PROTOCOL.chacha20poly1305` and `PROTOCOL.key` notes were
extracted, by name. The pinned `ssh`, `sshd` and `ssh-keygen` are run as
black boxes only. wolf-std's `net`, `process`, `fs`, `signal`, `env` and
`os.users` were read as the organisation's own code, and PAX's kernel
README and its px103, px104 and px105 notes for what PAX supports. No
listening socket outside loopback: every row binds `127.0.0.1` or `::1`.

## Inputs verified

- The tarball's signature (`VALIDSIG 7168B983815A5EEF59A4ADFD2A3F414E736060BA`)
  and digest were checked before the pages were extracted. New on the
  reading list: `sshd_config.5`, sha256
  `9f499c39e00e92f05621c0b259f4d0b05d1cedf34b376fde31fa2787a0d1978c`.
  The other pages, notes and RFCs agree with the digests in
  [SOURCES](../docs/SOURCES.md).
- The toolchain, std and OpenSSH pins are unchanged from trunk `0d98ce9`.

## Done-when

- [ ] The prediction, committed first.
- [ ] The transport's server role: version, KEXINIT, strict kex required,
  the host key's signature on H, EXT_INFO, rekeying both ways, DISCONNECT.
- [ ] The host key: made by `burrow-keygen`, required, its fingerprint at
  start, its mode and owner checked.
- [ ] Authentication, key-only, against `authorized_keys` with StrictModes;
  root refused; the methods list `publickey` only.
- [ ] The session channel, commands only; every other request refused by
  name.
- [ ] git over the server, against the same through `sshd`.
- [ ] The limits and the log line.
- [ ] Privileges: the session as the user, no way back; R-bw04-2.
- [ ] Hostile clients, red first.
- [ ] Measured against `sshd`, with margins.
- [ ] For B6: the px lane's items.
- [ ] README, MAP, SOURCES and CHANGELOG.
- [ ] The final-head gauntlet record, the plant record and the audit: in
  the PR body.
