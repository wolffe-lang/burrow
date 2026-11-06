# burrow

An ssh client written in [wolf](https://github.com/wolffe-lang/wolf-lang):
a minimal, OpenSSH-compatible `ssh` and an Ed25519 `burrow-keygen`, static
for PAX and the same on Linux and macOS. Its first user is
[den](https://github.com/wolffe-lang/den), which starts an `ssh` program
through an argv vector and speaks git's protocol v2 over its pipes; its
second is a person typing `ssh` on PAX.

**State: B3, auth, keys and one command on a session channel.** burrow
connects, verifies the server's host key against known_hosts (plain and
hashed entries; strict by default, `accept-new` and `no` as `ssh` has them),
logs in with an Ed25519 key in OpenSSH's own format, runs one command with
stdin, stdout and stderr as raw bytes, and exits with the command's status.
It takes the command line den passes:

```sh
ssh [-Tv] [-F configfile] [-i identity_file] [-l login_name] [-o option] [-p port] [--] destination [command [argument ...]]
burrow-keygen -t ed25519 [-q] [-f path] [-C comment] [-N ""]
burrow-keygen -y -f path        # the public line
burrow-keygen -l -f path        # the fingerprint
```

`-o` and `~/.ssh/config` (`Host` and `Match host` blocks) take `BatchMode`,
`ClearAllForwardings`, `ConnectTimeout`, `ControlMaster no`, `ControlPath
none`, `HashKnownHosts`, `HostKeyAlias`, `Hostname`, `IdentitiesOnly`,
`IdentityFile`, `Port`, `RekeyLimit`, `SendEnv`, `SetEnv`,
`StrictHostKeyChecking`, `UpdateHostKeys no`, `User` and
`UserKnownHostsFile`. Anything else is refused by name, never ignored. No
interactive shell, pty, agent or forwarding: den over burrow is B4
([MAP](docs/MAP.md)).

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
tools/build --all                     # target/{native,release}/{burrow,burrow-keygen}, rows/kexprobe
tools/check-test                      # src/*_test.lu: checked machine, native, lupin
tools/in-container tools/fetch-oracle # OpenSSH 10.0p2, built in the pinned image
tools/gate                            # the whole gauntlet, in the container
```

`tools/gate` runs every step and prints each one's `START` and
`END … exit=N`, stopping at the first that fails: the toolchain and oracle
digests, the CI planner's tests, the vectors (`tools/vectorgen.py`
regenerates `src/kexvec` byte for byte from the RFCs, `tools/nistvec.py`
`src/sha1vec` from NIST's vectors), formatting, both compiler tiers, the
unit rows, the transport, session and hostile-peer rows on both tiers, and
the measurement against the pinned `ssh`.

The transport rows (`tools/check-transport`) hold burrow to the pinned
`sshd`, each row starting its own on a loopback port with keys made for that
run: the handshake, the host key fingerprint, banner lines, refusals by name
for unknown and changed host keys, a bad signature, every negotiation
failure, a stripped strict-kex indicator, injected messages under strict
kex, a flipped tag byte, re-exchanges started by either side under traffic,
and a byte comparison of the plaintext handshake with what the pinned `ssh`
sends. burrow has no strict-kex waiver on any tier: `--no-strict-kex` is an
unknown option, and only the row program `rows/kexprobe` (never installed)
waives it, to show a stripped indicator still breaks the exchange hash.
Each test option (`--test-traffic`, `--test-preauth`, `--test-window`)
changes load or window size only, and a row holds each one inert for
security: with the option given, strict kex, the host key checks,
negotiation, the login and the key file's mode are refused as without it,
and no private key line reaches the output. The session rows (`tools/check-session`) hold authentication, keys,
known_hosts, the session and the command line to the pinned `sshd`, `ssh`
and `ssh-keygen`: keys made by either tool, refused keys and servers, the
banner, appended known_hosts lines read by the pinned `ssh`, 64 MiB through
`cat` compared by digest, interleaved stdout and stderr, exit codes and
signals, `SendEnv`, den's exact argv, `~/.ssh/config`, and each refusal's
exit code and line against `ssh`'s. The hostile-peer rows
(`tools/check-hostile`) run burrow against a scripted server that never
adjusts its window, sends data after CLOSE, oversize packets and data, an
unrequested USERAUTH_SUCCESS, an `exit-status` for another channel, and
`x11` and agent channel opens. `tools/measure-session` holds login to first
byte and `cat` throughput to stated margins against the pinned `ssh`;
`tools/measure-handshake` compares the cost of a handshake (evidence only).

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
names), 8709 (Ed25519 keys), 8731 (curve25519-sha256) and 9142; OpenSSH's
protocol notes, which are specifications rather than code: `PROTOCOL`,
`PROTOCOL.chacha20poly1305`, `PROTOCOL.key`, `PROTOCOL.agent` (for reading)
and `PROTOCOL.certkeys` (to refuse its names), read from a release
tarball's top level; the man pages `ssh(1)`, `ssh-keygen(1)`,
`ssh_config(5)` and `sshd(8)`'s known_hosts section; and, for hashed
known_hosts names, FIPS 180-4 and RFC 2104 with NIST's published vectors.
No SHA-1 or HMAC library's source is read.

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
