## Unreleased

- The repository scaffold: licence, README and its clean-room list.
- Pin wolf 0.2.37, lupin 0.1.59 and the bundled std, and OpenSSH 10.0p2 as
  the black-box oracle, built from its signed tarball in a pinned image.
- B1, the transport: the version exchange, the binary packet protocol,
  `curve25519-sha256`, `ssh-ed25519` host keys against known_hosts,
  `chacha20-poly1305@openssh.com`, strict kex, ext-info, re-exchange at
  RFC 4253 and 4344's limits and on the server's request, and disconnects
  with reason codes; every refusal by name.
- Independent vectors from the RFCs, the transport rows against the pinned
  `sshd`, and tiered CI.
