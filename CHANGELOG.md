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
- B2, authentication and keys: `publickey` with `ssh-ed25519` (the query,
  then the signed request), `server-sig-algs` honoured, the banner shown as
  `ssh` shows it; OpenSSH's private key format for unencrypted Ed25519 keys,
  read and written; `burrow-keygen -t ed25519`, `-y` and `-l`; known_hosts
  hashed names (with SHA-1 and HMAC-SHA1 from FIPS 180-4 and RFC 2104),
  `@revoked` and `@cert-authority`, and lines appended under `accept-new`
  and `no`.
- B3, the session and the command line: one command on a session channel,
  `env` and `exec`, stdin, stdout and stderr byte-clean, both windows, EOF
  and CLOSE in either order, the exit status and signals mapped as `ssh`
  maps them; the command line and `~/.ssh/config` den uses; every refusal
  by name with `ssh`'s line beside it.
- The transport writes its state in place, so a session runs each turn in a
  region and a transfer of any size holds a packet's worth of memory; a
  re-exchange no longer lets a later message overtake the ones it kept.
- The session rows against the pinned OpenSSH, hostile-peer rows against a
  scripted server, NIST's SHA-1 vectors, and the measurement against `ssh`.
- B1's `--no-strict-kex` leaves the command line on every tier (it is now
  `option_unknown`); the downgrade row's waiver moves to a row program,
  `rows/kexprobe`, never installed. Rows hold each test option inert for
  security.
- B4, den over burrow: den's clone, fetch and push over `ssh://` and
  scp-like URLs, with burrow linked as `ssh`, held byte for byte to the
  pinned OpenSSH client against the pinned `sshd` (`tools/check-den`, den
  pinned in `burrow-den.toml` and built by its own tools).
- With no command, burrow now logs in before it refuses
  (`shell_unsupported`), so a keyless `ssh -T git@github.com` is refused
  authentication as `ssh` refuses it; GitHub's real server, read only,
  against its published host key (`tools/check-github`).
- The live push row (`tools/check-live`), from its two variables only, with
  a loopback self-test; the static build's check for PAX
  (`tools/check-static`); den's clone through burrow measured against the
  pinned `ssh` (`tools/measure-den`).
