# Sources

Every document burrow was written from, by number and version, and what was
read in it. Nothing else was consulted. The clean-room rule is in the
[README](../README.md#clean-room): no ssh implementation's code or tests are
ever read; OpenSSH is used only as a pinned black box (`burrow-oracle.toml`).

The RFC texts were fetched from `https://www.rfc-editor.org/rfc/rfcNNNN.txt`
on 2026-11-05; the digest is of the text file as fetched.

## SSH RFCs

| document | sha256 of the text | read for B1 |
|---|---|---|
| RFC 4250, SSH Assigned Numbers | `eb3a9d7c3e1fae53c038d5ae62a73e62280d1dde8b246129969c95e4d0909341` | §4.1 message numbers, §4.2.2 disconnect reason codes |
| RFC 4251, SSH Architecture | `23a5052796d29edc2f0ff4f5be557df244544d129cfc26ed51971a6485eff4ef` | §5 data types (byte, boolean, uint32, uint64, string, mpint, name-list, with §5's examples), §6 algorithm naming |
| RFC 4252, SSH Authentication | `a36b882cf77b107335d49921b5e955b4ba78e253205dfbce5096ebc0e78bdf14` | §5, §5.1 and §5.2: the request format and the `none` method the rekey rows log in with; the rest with B2 |
| RFC 4253, SSH Transport Layer | `b471173305154f6c66facffcf7a4a25fc5c32765cb30542120be6c20a88f1ed3` | §4.2 version exchange, §5.1 the 1.99 version, §6 and §6.1 the binary packet protocol, §6.4 sequence numbers, §7 and §7.1 negotiation and first_kex_packet_follows, §7.2 key derivation, §7.3 NEWKEYS, §8 the exchange hash, §9 re-exchange, §10 service request, §11 DISCONNECT, IGNORE, DEBUG, UNIMPLEMENTED, §12 message numbers |
| RFC 4254, SSH Connection | `bfc727e9350067eaa49edeecc3d32f1e3518dd57cf3c36ceed02177156c5703f` | §4 global requests (declined until B3); the rest with B3 |
| RFC 4256, keyboard-interactive | `000091bd78ea7a4c71e2c0bd2c20998f0d0d775c71160b0f6c18fbe12d5a1233` | fetched; not needed by B1 |
| RFC 4344, SSH Transport Encryption Modes | `be7136101f41619175421f0343866bd9a4eee0b32b74a29f29e8fd26e7ef01ce` | §3 rekeying: §3.1 the 2^32-packet bound (2^31 on receipt), §3.2 the block bound |
| RFC 4419, DH group exchange | `20b76eff3be0c2311636e03604b1ddb9d5368fadd75a39c0c831fa7e04da0ad6` | fetched for reading; burrow refuses its method names |
| RFC 8308, Extension Negotiation | `c7d36121bcd0f242af19d660a3bbafb3c829d78df6f32fbd3e5c71a408e0ce8c` | §2.1 to §2.5: the `ext-info-c` indicator, EXT_INFO's format and order, unknown extensions ignored |
| RFC 8332, rsa-sha2 | `b194d8da7a5b07cf6763954b687fb2380565c8277d52c105a8eacdf00ffc44d9` | fetched, to name the RSA algorithms burrow refuses |
| RFC 8709, Ed25519 and Ed448 keys | `ea4aa3a8feec6bd5b1cc7847a6d08cd0afae49d12220cac1e2c39bc72c29fd3d` | §4 public key format, §5 and §6 signature format, §7 verification |
| RFC 8731, curve25519-sha256 | `26dcf1e8481d83e0b2403e41df47df3fb08cae154d1e464631a23b3cd025f9d1` | whole: §3 the method, the all-zero abort, string-encoded public values, §3.1 the shared secret as an mpint |
| RFC 9142, key exchange guidance | `68226c742986b83511fbc958cfa8bf5b51a8fdefdcae146d7ea41f2e4be79026` | §3.1.1 curve25519-sha256 (SHOULD), §3.5 ext-info (SHOULD), §4's table |

RFC 8731 says its exchange hash has the structure of RFC 5656 §4. RFC 5656 is
not on the reading list and was not read: burrow's hash is RFC 4253 §8's with
`e` and `f` replaced by the string-encoded Q_C and Q_S of RFC 8731 §3, and the
handshake rows against the pinned `sshd` confirm it.

## The primitives' specifications

Read for the independent vector generator (`tools/vectorgen.py`), which
implements each from its text; burrow itself uses wolf-std's
implementations.

| document | sha256 of the text | read |
|---|---|---|
| RFC 7748, Elliptic Curves for Security | `279ca0ecc5e92e2962e27b846986aeb74729d9dd34bd4a04a362f80dcb596ad3` | §5 X25519 and the §5.2 test vector, §6.1 |
| RFC 8032, EdDSA | `ed63657ff389301282b169b0abde9b5dd2c7e4d524fdfa5da6ff3094fc93c4c3` | §5.1 Ed25519 key generation, signing and verification, §7.1 TEST 1 |
| RFC 8439, ChaCha20 and Poly1305 | `25bef70fbf7a07ff45c2fe4cb7c6ce954eac687413d8610603268b4e4415324c` | §2.3 the block function, §2.4 the cipher and §2.4.2's vector, §2.5 Poly1305 and §2.5.2's vector |

## OpenSSH's protocol notes

The notes are read from a release tarball's top level, the tarball's
signature verified first. Only these files were extracted; no `.c` or `.h`
file of any release was opened.

| file | from | version line | read |
|---|---|---|---|
| `PROTOCOL` | openssh-10.0p2.tar.gz | `$OpenBSD: PROTOCOL,v 1.55 2024/01/08` | §1 transport changes: §1.5 `-etm` MACs, §1.7, §1.8 `curve25519-sha256@libssh.org` (identical to RFC 8731), §1.9 ping, §1.10 strict kex, §1.11 EXT_INFO during authentication; §5.1 public key format |
| `PROTOCOL.chacha20poly1305` | openssh-10.0p2.tar.gz | `$OpenBSD: PROTOCOL.chacha20poly1305,v 1.5 2020/02/21` | whole |
| `PROTOCOL` | openssh-10.6p2.tar.gz | `$OpenBSD: PROTOCOL,v 1.60 2026/02/09` | §1 (its strict-kex and chacha20-poly1305 sections now point at Internet-Drafts, which were not read) |
| `PROTOCOL.key`, `PROTOCOL.agent`, `PROTOCOL.certkeys` | openssh-10.0p2.tar.gz | | extracted; read with B2 |

The tarballs: `openssh-10.0p2.tar.gz` sha256
`021a2e709a0edf4250b1256bd5a9e500411a90dddabea830ed59cef90eb9d85c` and
`openssh-10.6p2.tar.gz` sha256
`9ae44872090cf2f06b3cf9ff147e7f16f309671340763ed2f99248398ae29d5b`, each
with a good signature by `7168B983815A5EEF59A4ADFD2A3F414E736060BA` from
`RELEASE_KEY.asc` (sha256
`c4a6f4692c9b8e75ec096add049fe0314b3ceff9410321f1e85907cf7a864269`).

## The oracle, as a black box

`ssh -vvv` and `sshd -ddd`-level logs of the pinned build (their own debug
output, not their code), `ssh -V`, and `ssh-keygen -l` fingerprints. The
oracle's lists in `docs/MAP.md` were measured this way (`tools/oracle-probe`).

## Organisation code

wolf-std at the pinned commit `5b3a59942b2ee69b99682544341ce8a12c984e9e`:
`std/x/crypto/{curve25519,chacha20,sha2}`, `std/net`, `std/fs`, `std/env`,
`std/base64`, `std/time` and `std/rand`'s header. The toolchain scripts and
the CI planner are adapted from scent, whose own came from aspen; each file
says so in its first lines.
