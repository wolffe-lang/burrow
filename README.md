# burrow

An ssh client written in [wolf](https://github.com/wolffe-lang/wolf-lang):
a minimal, OpenSSH-compatible `ssh` and an Ed25519 `burrow-keygen`, static
for PAX and the same on Linux and macOS. Its first user is
[den](https://github.com/wolffe-lang/den), which starts an `ssh` program
through an argv vector and speaks git's protocol v2 over its pipes; its
second is a person typing `ssh` on PAX.

**State: B1, the transport.** burrow connects, exchanges keys, verifies the
server's host key against known_hosts, requests the `ssh-userauth` service
and stops there with "not yet implemented: user authentication" (exit 2).
User authentication is B2, channels and the full `ssh` command line are B3,
den over burrow is B4 ([MAP](docs/MAP.md)).

## What it speaks, and what it refuses

burrow speaks one modern profile, the one every primitive in wolf-std
already covers:

| layer | burrow speaks | source |
|---|---|---|
| key exchange | `curve25519-sha256` | RFC 8731 |
| host key | `ssh-ed25519` | RFC 8709 |
| cipher | `chacha20-poly1305@openssh.com` | OpenSSH `PROTOCOL.chacha20poly1305`, RFC 8439 |
| user key | `ssh-ed25519` | RFC 8709, RFC 4252 |

Anything outside that list is refused by name, never negotiated down to.
There is no RSA (`ssh-rsa`, `rsa-sha2-*`) at first.

The security posture:

- **Host keys:** strict `known_hosts` checking is the default. An unknown or
  changed host key refuses the connection, by name.
- **Strict kex:** OpenSSH's `kex-strict-c-v00@openssh.com` (the Terrapin
  mitigation) is always offered, and a server without it is refused unless a
  flag says otherwise.
- **Key material:** private keys never appear in logs or test rows. Test keys
  are generated per run.
- **Comparisons:** MAC and tag comparisons are constant time.

## Build and test

The toolchain and the oracle are pinned by digest (`wolf-toolchain.toml`,
`burrow-oracle.toml`); every tool refuses a binary that does not match.

```sh
tools/fetch-toolchain                 # wolf 0.2.37, lupin 0.1.59, the bundled std
tools/build --all                     # target/native/burrow, target/release/burrow
tools/check-test                      # src/*_test.lu: checked machine, native, lupin
tools/in-container tools/fetch-oracle # OpenSSH 10.0p2, built in the pinned image
tools/gate                            # the whole gauntlet, in the container
```

`tools/gate` runs every step and prints each one's `START` and
`END … exit=N`, stopping at the first that fails: the toolchain and oracle
digests, the CI planner's tests, the vectors (`tools/vectorgen.py`
regenerates `src/kexvec` byte for byte from the RFCs), formatting, both
compiler tiers, the unit rows, and the transport rows on both tiers.

The transport rows (`tools/check-transport`) hold burrow to the pinned
`sshd`, each row starting its own on a loopback port with keys made for that
run: the handshake, the host key fingerprint, banner lines, refusals by name
for unknown and changed host keys, a bad signature, every negotiation
failure, a stripped strict-kex indicator, injected messages under strict
kex, a flipped tag byte, re-exchanges started by either side under traffic,
and a byte comparison of the plaintext handshake with what the pinned `ssh`
sends. `tools/measure-handshake` compares the cost of a handshake with the
pinned `ssh` (evidence only).

## CI

Unlabelled pull requests run one cheap job that points at the local
gauntlet. The `ci` or `full-matrix` label runs the full set: the Linux
gauntlet in the pinned container and the macOS unit rows. Trunk pushes run
it when CI, tools or pins change, and the nightly runs it always; a red
nightly opens an issue.

## Clean room

burrow is written from specifications and from black-box runs of OpenSSH,
never from another implementation's code.

**Read:** the SSH RFCs 4250, 4251, 4252, 4253, 4254 and 4256, 4344, 4419
(for reading), 8308 (extension negotiation), 8332 (read only, to refuse its
names), 8709 (Ed25519 keys), 8731 (curve25519-sha256) and 9142; and
OpenSSH's protocol notes, which are specifications rather than code:
`PROTOCOL`, `PROTOCOL.chacha20poly1305`, `PROTOCOL.key`, `PROTOCOL.agent`
(for reading) and `PROTOCOL.certkeys` (to refuse its names), read from a
release tarball's top level.

**Never read:** any `.c` or `.h` file of OpenSSH, nor the code or tests of
any other ssh implementation (dropbear, libssh, libssh2, Go's
`x/crypto/ssh`, paramiko, asyncssh, russh, thrussh, Twisted conch, PuTTY,
wolfSSH and the rest). Test vectors are our own.

wolf-std's crypto modules are the organisation's own code and are read and
used: `std.x.crypto.curve25519` (X25519 and Ed25519),
`std.x.crypto.chacha20` (ChaCha20, Poly1305) and `std.x.crypto.sha2`.

**The oracle:** OpenSSH's `ssh`, `sshd` and `ssh-keygen`, pinned by version
and digest and run in a container as black boxes. A test row holds burrow's
bytes, behaviour and exit status to the pinned OpenSSH client talking to the
same pinned `sshd`, on loopback ports the test owns, with keys generated for
that run. No row contacts a real host.

## Licence

GPL-3.0-or-later (`LICENSE`), with the wolf Training Data Permission
(`LICENSE-TRAINING-DATA`).
