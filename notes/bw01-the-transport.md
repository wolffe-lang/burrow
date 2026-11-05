# bw01 — the map and the transport (B0, B1)

## Prediction

Written 2026-11-05 19:03Z, before the toolchain, the oracle or any code, from
RFC 4253, 8731, 8709, 8308, 4344 and OpenSSH's protocol notes alone. Every
number below is a prediction; the evidence index records hits and misses.

**The oracle.** OpenSSH built from its signed release tarball with its own
default `configure` (only the install prefix set), in an Ubuntu 24.04 image
pinned by digest. The release is the last one whose tarball still carries
`PROTOCOL.chacha20poly1305` and `PROTOCOL.certkeys` at its top level, so the
oracle and the notes it implements come from one signed archive.

**The algorithm lists exchanged.** burrow's KEXINIT, in this order:

| list | burrow sends |
|---|---|
| kex | `curve25519-sha256,curve25519-sha256@libssh.org,ext-info-c,kex-strict-c-v00@openssh.com` |
| host key | `ssh-ed25519` |
| cipher (both) | `chacha20-poly1305@openssh.com` |
| MAC (both) | `hmac-sha2-256` (never used: the AEAD ignores the MAC, `PROTOCOL.chacha20poly1305` "Negotiation"; RFC 4253 §7.1 wants a non-empty list) |
| compression (both) | `none` |
| languages | empty |
| first_kex_packet_follows | false |

The pinned `sshd`'s KEXINIT, with ed25519, ecdsa and rsa host keys: kex led by
the hybrid post-quantum methods (`mlkem768x25519-sha256`, then
`sntrup761x25519-sha512`), then `curve25519-sha256` and its `@libssh.org`
alias, the three `ecdh-sha2-nistp*`, and `ext-info-s` and
`kex-strict-s-v00@openssh.com` at the end; no finite-field Diffie-Hellman. Host
keys `rsa-sha2-512,rsa-sha2-256,ecdsa-sha2-nistp256,ssh-ed25519`. Ciphers led
by `chacha20-poly1305@openssh.com`, then AES-CTR and AES-GCM. MACs led by the
`-etm` variants and including `hmac-sha2-256`. Compression `none,zlib@openssh.com`.
The negotiation chooses `curve25519-sha256`, `ssh-ed25519`,
`chacha20-poly1305@openssh.com` both ways, MAC `hmac-sha2-256` (ignored) and
`none`.

**Packets to a NEWKEYS.** Three binary packets each way: KEXINIT (sequence 0),
KEX_ECDH_INIT / KEX_ECDH_REPLY (1), NEWKEYS (2), after the two version lines.
With minimum padding the frames are: KEX_ECDH_INIT `packet_length` 44
(payload 37, padding 6); KEX_ECDH_REPLY `packet_length` 188 (payload 179:
the 51-byte ed25519 key blob, the 32-byte Q_S and the 83-byte signature
blob, each as a string; padding 8); NEWKEYS `packet_length` 12 (padding 10).
OpenSSH's own frames may carry more than minimum padding; the row records it.
After NEWKEYS the server sends EXT_INFO first, then SERVICE_ACCEPT, so the
handshake row sees five packets from the server and four from burrow
(KEXINIT, ECDH_INIT, NEWKEYS, SERVICE_REQUEST). EXT_INFO names
`server-sig-algs`, `publickey-hostbound@openssh.com` and `ping@openssh.com`.

**Alignment under chacha20-poly1305.** RFC 4253 §6 makes the whole
`packet_length || padding_length || payload || padding` a multiple of 8 even
for stream ciphers, and the chacha20-poly1305 note does not change that, so
burrow aligns `4 + packet_length`. Prediction: OpenSSH's encrypted frames obey
the same rule, and the SERVICE_REQUEST frame is `packet_length` 28 (payload 17,
padding 10) plus the 16-byte tag. A miss here (OpenSSH aligning
`packet_length` alone, as the encrypt-then-MAC modes do) is a recorded
difference, and burrow's receive check follows the measurement.

**What strict kex changes.** Both sides advertise it, so: the first packet
burrow receives must be KEXINIT; any other message during the initial kex,
including IGNORE, DEBUG and UNIMPLEMENTED, ends the connection, by name; and
the sequence numbers reset to 0 after every NEWKEYS, both directions, so the
first encrypted packet each way is number 0 instead of 3. Without strict kex
(a server that lacks it, refused unless a flag allows it) the first encrypted
packets would be numbers 3.

**The rekey points.** burrow starts a key re-exchange when either direction
reaches 1 GiB since the last NEWKEYS (RFC 4253 §9) or 2^31 packets (RFC 4344
§3.1, well before the 32-bit sequence number wraps), after an hour (§9), and
whenever the server sends KEXINIT. ChaCha20's 512-bit block puts RFC 4344
§3.2's block bound out of reach. A test-only `RekeyLimit` brings the byte
bound down to a few KiB so a row can cross it several times under traffic; the
session identifier stays the first H through every rekey, and with strict kex
each NEWKEYS resets the sequence numbers again.

**The rows B1 shows against the pinned `sshd`.** All green at the final head:

- the handshake reaches SERVICE_ACCEPT for `ssh-userauth`, and the `sshd` log
  names the negotiated `curve25519-sha256`, `ssh-ed25519` and
  `chacha20-poly1305@openssh.com`;
- the host key fingerprint burrow prints (`SHA256:` and unpadded base64) is
  the one `ssh-keygen -l` prints for the run's host key;
- mutation rows, each refused by name with exit 255 and a DISCONNECT the
  `sshd` log records with its reason code: a flipped tag byte
  (`mac_mismatch`), a known_hosts entry for another key (`host_key_changed`),
  no entry at all (`host_key_unknown`), a server offering only refused
  algorithms (`no_common_kex`, `no_common_hostkey`, `no_common_cipher`), the
  server's `kex-strict-s-v00@openssh.com` stripped in flight
  (`strict_kex_missing`), and an IGNORE injected before the server's KEXINIT
  and before its NEWKEYS (`strict_kex_violation`);
- a rekey under traffic: burrow-initiated at the test `RekeyLimit` and
  `sshd`-initiated at its own `RekeyLimit`, both carried through with the
  session staying up;
- the byte-level transcript against the pinned OpenSSH `ssh` told to offer
  burrow's lists: the KEXINIT payloads equal except the 16 cookie bytes and
  the version line's software field; KEX_ECDH_INIT and NEWKEYS payloads equal
  in length and type, differing only in Q_C.

**Vectors.** An independent Python generator, written from RFC 4253 §7.2 and
§8, RFC 8731 and the chacha20-poly1305 note with its own ChaCha20 and Poly1305
from RFC 8439, agrees with burrow byte for byte on every fixed input: H, the
six derived keys (the 64-byte cipher keys need the second hash round), and
sealed packets.

**The cost of a handshake** (evidence only): std's curve25519 is ten
checked-`int` limbs with a double-and-add Ed25519 verify, so burrow's
handshake CPU is 10x to 100x OpenSSH's own crypto; but `sshd`'s fork and
re-exec per connection dominates wall time on loopback, so the wall-time
ratio to OpenSSH's `ssh` reaching the same point is between 1.2x and 3x at
`--release`.

**The tools.** The audit does not know `burrow` yet (the orchestrator adds it
when CI lands). std's `rand` is a seeded PCG32 with no entropy, and std has no
entropy source at the pinned release; burrow reads `/dev/urandom` and refuses
by name where there is none.

## Forbidden

No ssh implementation's code or tests were read: no `.c` or `.h` file of any
OpenSSH release (only the build read them), nothing of dropbear, libssh,
libssh2, Go's `x/crypto/ssh`, paramiko, asyncssh, russh, thrussh, conch,
PuTTY or wolfSSH. From the OpenSSH tarballs only the top-level `PROTOCOL*`
notes were extracted. RFC 5656, which RFC 8731 cites for the exchange hash's
structure, is not on the reading list and was not read. No real host was
contacted: every row runs its own `sshd` on a loopback port in the pinned
container, with keys made for that run, and nothing reaches GitHub. Private
keys stay in each row's run directory; rows print fingerprints only. The plant
branch has no PR and no CI run.

## Inputs verified

Footprint: cross-cutting

- wolf 0.2.37 (`e2757a7`), lupin 0.1.59 (`668fb75`), the bundled std
  `5b3a599`: release metadata read twice, asset ids and digests agreeing; the
  archives held to their digests by `tools/fetch-toolchain`, the binaries to
  their version lines.
- OpenSSH 10.0p2: the tarball, its signature (a good signature by
  `7168B983815A5EEF59A4ADFD2A3F414E736060BA`) and `RELEASE_KEY.asc`, each read
  twice; built four times by its own default `configure` in the pinned image
  (two hosts, three image revisions), giving the same `ssh`, `sshd` and
  `ssh-keygen` digests every time.
- The image: Ubuntu 24.04 by digest, its packages from the Ubuntu snapshot
  archive at `20261101T000000Z`.
- The RFC and note texts by sha256 in [SOURCES](../docs/SOURCES.md).

**Why 10.0p2.** It is the last release whose tarball carries
`PROTOCOL.chacha20poly1305` and `PROTOCOL.certkeys` at its top level: from
10.1p1 on, `PROTOCOL` points at Internet-Drafts for chacha20-poly1305 and
strict kex instead. So the oracle and the notes it implements come from one
signed archive (R-bw01-1). It is built from the tarball, not taken from a
distribution package, so that no distribution patch is in the oracle and the
build is pinned by the same digests on every host.

Commits, in order:

- `12bed00` the prediction.
- `4e759a5` `36d5a8f` the toolchain pin and its tools.
- `c6c328d` `c3f8e2f` `157999d` the oracle pin, its build, its digests.
- `69af611` `28782c1` the row-owned `sshd` and the oracle probe.
- `94ae784` `a101b8d` wire (the row first, then the module).
- `8333a9f` `ae57121` `108e079` version and refuse.
- `a4afe45` `0c4ce85` the independent vector generator and its vectors.
- `feb07db` `a4fb027` `4a6e559` packet and chachapoly.
- `38d9132` `ec147ac` `bbb7fad` `8aeaf10` kex and hostkey.
- `fa3f77e` `15a0286` the build and test tools, the transport rows and relay.
- `8f4a88e` `d5d6264` `7d5a51c` entropy, transport, the CLI.
- `cf12e0d` `57edc4f` the measured sealed alignment (row, then fix).
- `a694025` `a0ee0e7` harness fixes.
- `fcd8c7a` `d9ddc64` the image's row login; tiered CI.
- `dcead87` `de9579a` `1d3aa38` the rekey rows after a `none` login; the
  pre-auth refusal; `--test-auth-none`.
- `b407a98` `aedc712` the smallest sealed frame (row, then fix).
- `89d6617` `6a9e19e` `4a5cf85` DISCONNECT and EXT_INFO rows; global requests.
- `33c6129` `6f2e70e` `8a893c4` the rekey bounds (row, then module).
- `b04e5be` `3df870d` the gate and the cost measurement.
- `f1b7fbb` `e6b6b9d` `e5f5f9e` `38219fd` SOURCES, MAP, README, CHANGELOG.
- `5f92197` the image's clang and lld (the release tier links with them); this note.

## Evidence index

**The rows.** Seven unit rows (`src/*_test.lu`: wire, version, packet,
kex, hostkey, messages, rekey) pass on the checked machine, natively and on
lupin; none falls back to native. Twenty-one transport rows
(`tools/check-transport`) pass against the pinned `sshd` on both tiers. The
final head's gauntlet record and its `END` lines are in the PR body.

**The vectors.** `tools/vectorgen.py` implements X25519, Ed25519, ChaCha20
and Poly1305 from RFC 7748, 8032 and 8439 (checking itself against those
RFCs' own vectors), and from them the KEXINIT bytes, H, all six derived keys
(the 64-byte cipher keys take the second hash round), a rekey's keys under
the first session id, and sealed packets. burrow matches every one byte for
byte, and the handshake rows confirm the same derivation against `sshd`.

**The prediction, hit and missed.**

| predicted | measured |
|---|---|
| burrow's lists as tabled | hit: the KEXINIT the transcript row records |
| server kex led by the hybrid PQ methods, then curve25519, the three ECDH, `ext-info-s` and `kex-strict-s-v00` last, no finite-field DH | hit, with a third hybrid name (`sntrup761x25519-sha512@openssh.com`) |
| server host keys `rsa-sha2-512,rsa-sha2-256,ecdsa-sha2-nistp256,ssh-ed25519` | miss on order: `ssh-ed25519,ecdsa-sha2-nistp256,rsa-sha2-512,rsa-sha2-256` |
| server ciphers chacha20, then AES-CTR, then AES-GCM | miss on order: GCM before CTR |
| negotiation chooses curve25519-sha256, ssh-ed25519, chacha20-poly1305 both ways | hit (burrow's `-v` and the `sshd` log) |
| three packets each way to NEWKEYS | hit |
| KEX_ECDH_INIT `packet_length` 44, padding 6; NEWKEYS 12, padding 10 | hit, and the pinned `ssh` sends the same two frames |
| KEX_ECDH_REPLY `packet_length` 188 | not measured: the relay records the client's frames only |
| EXT_INFO first, then SERVICE_ACCEPT; EXT_INFO names `server-sig-algs`, `publickey-hostbound@openssh.com`, `ping@openssh.com` | hit |
| sealed frames aligned as a whole, SERVICE_REQUEST `packet_length` 28 | **miss**: the pinned `sshd` aligns `packet_length` alone under chacha20-poly1305, and the smallest sealed frame is `packet_length` 8; burrow follows the measurement (SERVICE_REQUEST is `packet_length` 24) |
| strict kex: first packet KEXINIT, nothing else in the first exchange, sequence numbers reset at every NEWKEYS | hit: the two injection rows refuse by name; the first sealed packet each way is number 0 |
| rekey at 1 GiB, 2^31 packets, an hour, and on the server's KEXINIT | hit in the rekey row (unit) and both traffic rows |
| rekeys under traffic before authentication | **miss**: the pinned `sshd` treats a client KEXINIT before user authentication as a protocol error and answers UNIMPLEMENTED, and does not rekey there itself; burrow now refuses that by name (`kex_failed`), and the traffic rows log in first with RFC 4252 `none` (R-bw01-3) |
| the transcript: KEXINIT equal after the cookie | hit except compression: the pinned `ssh` offers `none,zlib@openssh.com` even with `Compression=no` |
| a handshake costs 10x to 100x OpenSSH's crypto CPU, 1.2x to 3x its wall time | measured by `tools/measure-handshake` on a quiet block after the final record (a perf job may not share one); the numbers are in the PR body |
| the audit does not know `burrow` | hit (it takes the checkout's path) |

**Rekeys under traffic.** 256 KiB of IGNORE messages after a `none` login:
at `RekeyLimit=32K` burrow started 8 re-exchanges and `sshd` logged 9
NEWKEYS received (the first exchange and the 8); with `sshd`'s own
`RekeyLimit 32K`, the server started 7 and burrow carried each through. Both
rows end with a PING answered by a PONG under the latest keys. After the
login the pinned `sshd` sends a `hostkeys-00@openssh.com` global request,
which burrow declines until it has a connection layer (B3).

**Where constant time matters.** The Poly1305 tag comparison in
`chachapoly.open`, through `wire.ct_eq`, which folds every byte pair into
one accumulator before testing it; nothing is decrypted before the tag
passes. The rest is wolf-std's (with its own `ct:` lines) or public data.

**Rulings.**

- **R-bw01-1, the oracle release.** (a) OpenSSH 10.0p2, the last tarball
  carrying `PROTOCOL.chacha20poly1305` and `PROTOCOL.certkeys`, so the oracle
  and its notes are one signed archive; (b) the current 10.6p2 with the notes
  from 10.0p2; (c) admit the Internet-Drafts 10.1p1+ point at and move to the
  current release. Recommended and implemented: (a); (c) when a lane needs a
  newer server's behaviour.
- **R-bw01-2, the sealed alignment.** RFC 4253 §6 counts `packet_length` in
  the multiple of 8 even for stream ciphers; the pinned `sshd` does not, under
  chacha20-poly1305. (a) follow the oracle (implemented; the RFC rule cannot
  interoperate); (b) the RFC's text. Recommended: (a), stated in MAP.
- **R-bw01-3, the rekey rows' login.** The pinned `sshd` re-exchanges keys
  only after user authentication. (a) log in with RFC 4252 `none` as an
  empty-password account in the image, through the test-only
  `--test-auth-none` (implemented: `none` carries no credential, and the
  account exists only in the row image); (b) leave the traffic rows for B2;
  (c) build the test options out of release binaries. Recommended: (a) now,
  and B2 replaces the `none` login with `publickey` in those rows and drops
  `--test-auth-none`.
- **R-bw01-4, entropy.** wolf-std has no entropy source at the pin. (a)
  `/dev/urandom` through `std.fs`, refused by name where absent (implemented);
  (b) wait for a std surface. Recommended: (a), and a wolf-std issue for an
  OS random source, which PAX will need.
- **R-bw01-5, the MAC list.** (a) `hmac-sha2-256`, never used under the AEAD,
  so the list is not empty as RFC 4253 §7.1 asks (implemented); (b) an empty
  list; (c) OpenSSH's long list, naming MACs burrow lacks. Recommended: (a).
- **R-bw01-6, `-` in softwareversion.** §4.2 forbids it; (a) accept it
  (implemented), since deployed servers send one; (b) refuse. Recommended:
  (a).
- **R-bw01-7, RFC 9142's MUST.** `diffie-hellman-group14-sha256` is refused
  by name, not implemented. Recommended: keep it so unless a target server
  lacks curve25519.

**Issues to file** (for the orchestrator; none filed here):

- wolf-std: an OS entropy source (`std.rand` is a seeded PCG32 only).
- wolf-std: SHA-1, for hashed known_hosts names (B2 can vendor den's, with
  provenance, meanwhile).
- wolf-lang or wolf-interp: `let hour = 3600 * 1000000000`, used as an `int`
  argument, runs natively but traps `overflow` under lupin 0.1.59, which reads
  the bare product as `i32` (`src/rekey_test.lu` at `33c6129`, fixed by an
  annotation in `8a893c4`).
- lane-audit: `burrow` in its tier lists once CI lands.

## Done-when

- [x] The repository: public, GPL-3.0-or-later with the Training Data
  Permission, `trunk` default, the scaffold commit `2f59d2d` on trunk.
- [x] The toolchain pinned by digest; tiered CI from the first PR.
- [x] The oracle container: OpenSSH 10.0p2 built from its signed tarball,
  pinned by digest; `sshd` on row-owned loopback ports with per-run keys.
- [x] The prediction, committed first (`12bed00`).
- [x] B1 row by row, red first: the version exchange, the binary packet
  protocol, negotiation, curve25519-sha256 and its H and keys, ssh-ed25519
  host keys and known_hosts, chacha20-poly1305, strict kex, ext-info,
  rekeying, disconnect, and `-v` debug lines.
- [x] The rows that stay: the handshake to SERVICE_ACCEPT; the mutation rows
  (a flipped tag byte, a wrong host key, a downgraded list, strict-kex
  violations) refused by name; a rekey under traffic, each way; the
  transcript against the pinned `ssh`.
- [x] Independent vectors from a Python generator written from the RFCs.
- [x] The README read and refreshed; MAP and SOURCES.
- [ ] The final-head gauntlet record, the plant record and the audit: in the
  PR body.
