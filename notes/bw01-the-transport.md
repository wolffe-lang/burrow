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
