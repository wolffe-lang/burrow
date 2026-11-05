# burrow

An ssh client written in [wolf](https://github.com/wolffe-lang/wolf-lang):
a minimal, OpenSSH-compatible `ssh` and an Ed25519 `burrow-keygen`, static
for PAX and the same on Linux and macOS. Its first user is
[den](https://github.com/wolffe-lang/den), which starts an `ssh` program
through an argv vector and speaks git's protocol v2 over its pipes; its
second is a person typing `ssh` on PAX.

**State: the repository scaffold.** Nothing is implemented yet.

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
