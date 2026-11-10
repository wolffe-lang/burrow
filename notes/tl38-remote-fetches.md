# tl38 — remote fetches that do not red a run

Three red runs this month had nothing wrong in burrow. Each was a remote archive misbehaving under the Linux
job's image build:

- **2026-11-06, the nightly** (run 42221632377): the Ubuntu snapshot archive was slow (about 126 kB/s) and answered
  `libgc1` with `502 Bad Gateway` after apt's own three tries. The build took 21 minutes before it failed. Then every
  row step after it, run under `!cancelled()`, built the image again, and the job spent another 24 minutes failing.
- **2026-11-10, burrow#15's first PR run** (run 42759990403, attempt 1): the bootstrap `apt-get update`, which reads
  the live mirrors to get `ca-certificates` before the snapshot is reachable over HTTPS, met `security.ubuntu.com`
  mid-sync: `File has unexpected size (1426608 != 1426588). Mirror sync in progress?`. Nothing retried it.
- **2026-11-10, the nightly** (run 42824846433): the snapshot archive answered `503 Service Unavailable` to every
  package for more than five minutes. apt's own retries were spent in the first minute. burrow#20 is that night's
  issue.

In every case the log's last lines were twelve row steps failing for want of an image, not the fetch that failed.

## Prediction

Written 2026-11-10 at 20:57Z, before any change, on trunk `9c647a2`.

### What changes

- **`ci/fetch-retry`**, new: one fetch, tried a bounded number of times with growing pauses, each try under a
  connect timeout and a total time limit. Three forms:
  - `url URL OUT`: curl, `--connect-timeout 20`, `--max-time 300`, and a floor of 1 KiB/s over 60 s, so a stalled
    transfer ends as a timeout. It tries again on a connection or name failure, a timeout, a reset or TLS drop,
    and HTTP 408, 425, 429 and 5xx. Any other HTTP status (a 404 means a wrong URL or pin) is not retried.
  - `git DIR REPO REV`: `git fetch --depth 1` with git's own low-speed floor, under a 600 s limit, its stderr
    classed as pax's `tools/fetch-retry` classes it (a refusal such as `not our ref` never retried). When REV is a
    full commit id, the commit fetched must be REV.
  - `run WHAT -- CMD…`: any command (the base image's `docker pull`); every failure is tried again.

  Five tries, 5, 15, 45 and 120 s apart (185 s of pauses in all). Each failed try prints
  `fetch-retry: WHAT: try N of 5 failed (CLASS); again in S s`, and the last one
  `FAIL fetch of WHAT failed after 5 tries (last: CLASS)`, exit 3. A failure that is not retried prints
  `FAIL fetch of WHAT failed (CLASS), not retried`, exit 4. A wrong commit is exit 5.
- **`ci/fetch-retry-test.py`**, new, committed before the helper: its rows against a loopback HTTP server and a
  local git repository, with the pauses set to 0 s. It runs in the `plan-test` job and in the local gauntlet's
  `planner` step.
- **`ci/oracle.Containerfile`**: each of apt's four network phases (the bootstrap's package lists and its
  `ca-certificates`, then the snapshot's lists and its packages) runs with `Acquire::Retries=5` and a 30 s
  connect and idle timeout per transfer, is tried up to 4 times, 30, 90 and 270 s apart, and each try has a total
  limit (300 s for lists, 600 s for packages). `apt-get update` runs with `--error-on=any`, so a list that failed
  to download is an error, never a stale list used quietly. The packages are fetched with `--download-only`
  under the limit, then installed with no network, so the time limit never stops dpkg mid-install. The last
  failure prints `FAIL fetch of … failed after 4 tries (last exit N)`.
  What is downloaded does not change: the same base image digest, the same live bootstrap, the same snapshot
  instant and the same package list.
- **`tools/fetch-toolchain`**: the wolf and lupin archives and the std's commit come through `ci/fetch-retry`; the
  std's fetched commit is now compared with the pin (it was fetched by id but never compared).
- **`tools/fetch-oracle`**: the tarball, its signature and the key come through `ci/fetch-retry`. Their digests are
  checked twice, as before.
- **`tools/fetch-den`**: den's pinned commit comes through `ci/fetch-retry` (a local gauntlet step; hosted CI does not
  run it).
- **`.github/workflows/ci.yml`**: the Linux job pulls the base image by digest through `ci/fetch-retry` before it
  builds; the row steps run only when the toolchain and oracle step succeeded, so a failed fetch is the job's last
  failure instead of the first of thirteen; `plan-test` runs `ci/fetch-retry-test.py`.
  `ci/local-gate-baseline.json` records the new job bodies, as every workflow change does.
- **`tools/gate`**: the `planner` step runs `ci/fetch-retry-test.py` too.

### The rows

`ci/fetch-retry-test.py`, red at the rows tip (the helper is missing) and green after:

| row | what | expected |
|---|---|---|
| F1 | a URL that answers 200 | exit 0, the file's bytes, one request |
| F2 | a URL that answers 503 twice, then 200 | exit 0, two `try N of 3 failed (HTTP 503)` lines, `fetched on try 3 of 3`, three requests |
| F3 | a URL that always answers 503 | exit 3, `FAIL fetch of URL failed after 3 tries (last: HTTP 503)`, three requests, no file left |
| F4 | a URL that answers 404 | exit 4, one request, `not retried` |
| F5 | a closed port | exit 3, the class `connect` |
| F6 | a server that sends half a body and stalls, with a 2 s limit | exit 3, the class `timeout` |
| F7 | git: a pinned commit from a local repository | exit 0, `FETCH_HEAD` is the commit |
| F8 | git: a repository URL that answers 503 | exit 3, the class `HTTP 503` |
| F9 | git: a commit the repository does not have | exit 4, one try |
| F10 | run: a command that fails twice, then succeeds | exit 0, `succeeded on try 3 of 3` |
| F11 | run: a command that always fails, and one that outlives its limit | exit 3, the classes `exit 1` and `timeout` |

### The plant, and the green

- **The plant**, `tl38-plant-503`, off the line: the wolf archive's URL in `tools/fetch-toolchain` pointed at a
  server inside the job's container that answers every request with 503, and the cached `.wolf-bin` removed so the
  fetch happens. Dispatched with `jobs=linux`, the smallest run that holds it. Predicted: four `try N of 5 failed
  (HTTP 503); again in S s` lines with S = 5, 15, 45, 120, then
  `FAIL fetch of http://127.0.0.1:8503/…/wolf-0.2.37-x86_64-unknown-linux-gnu.tar.gz failed after 5 tries (last: HTTP 503)`,
  the step red with exit 3 about 190 s after it starts, and every row step after it skipped.
- **The green**: a dispatch at the head with no job named (tier full): `plan-test` with the helper's rows,
  the Linux job from a fresh image (the Containerfile's digest is the image's tag and the cache key, so nothing is
  reused), and the macOS job, whose `tools/fetch-toolchain` runs the helper on the runner itself. The oracle's three
  binary digests still hold: the image's compilers and libraries are the snapshot's, unchanged.

### Risks

1. `apt-get update --error-on=any` needs apt 2.1 or later; the image's apt is 2.7. If it is refused, the build fails
   at once, by name, in the green run.
2. A time limit stops a slow download that is still moving (2026-11-06 ran at 126 kB/s). apt keeps the packages it
   finished in its cache, so the next try starts where the last one stopped.
3. The worst case is long: four tries of the package phase at 600 s and 390 s of pauses is 46.5 minutes, inside the
   job's 60-minute limit only if nothing else is slow. A total outage fails much sooner: each try ends when apt's own
   retries are spent.
4. `tools/fetch-toolchain` now needs `python3` for its fetches. The image, the macOS runner and the local hosts have it.

### Choices, recommended and implemented

1. **The bootstrap.** (A) Keep the live bootstrap and retry it; (B) bootstrap from the snapshot over plain HTTP,
   which apt's signatures make safe, and drop the live mirrors altogether; (C) keep the built image between runs
   (burrow#6). Recommended and implemented: A, since this pass does not change what is downloaded. B and C are each
   a pass of their own; C is the larger saving.
2. **The helper's language.** (A) Python, as `tools/fetch-oracle` and `tools/fetch-den` are; (B) POSIX sh, as pax's
   `tools/fetch-retry` is. Recommended and implemented: A, for a total time limit that works the same on Linux and
   macOS (macOS has no `timeout`) and for rows that run a loopback server in-process.
3. **The numbers.** Five tries 5–120 s apart for single files (185 s of pauses: the 504s seen on GitHub's release
   origin lasted about 20 s, and a 503 spell of a few minutes is covered); four tries 30–270 s apart for apt's
   phases, since apt already retries each file five times inside a try. Recommended and implemented as stated.
4. **The actions.** `actions/checkout`, `actions/cache` and `actions/upload-artifact` are pinned by tag, not by
   commit. Pinning them is out of this pass (it would change what is fetched); each retries on its own.

## Inventory

Every network fetch in burrow's CI and container files, before this pass (where, pinned, retried) and after.

| what | where | pinned by | retried before | after |
|---|---|---|---|---|
| `ubuntu:24.04`, the base image, from Docker Hub | `ci/oracle.Containerfile` `FROM`; `docker build` in CI, `podman build` on a host | image digest | no | CI pulls it first through `ci/fetch-retry run` (5 tries) |
| package lists and `ca-certificates` from the live mirrors (`archive.ubuntu.com`, `security.ubuntu.com`) | `ci/oracle.Containerfile`, the bootstrap | not pinned (the live archive; apt checks its signatures) | apt's default three tries per file; no outer retry; 120 s timeout | `Acquire::Retries=5`, 30 s timeouts, 4 tries 30–270 s apart, a limit per try, `--error-on=any`, a named FAIL |
| package lists and the image's packages from `snapshot.ubuntu.com` | `ci/oracle.Containerfile` | the snapshot instant (`burrow-oracle.toml`); each package by the sha256 in the signed index | as above | as above |
| wolf and lupin release archives from GitHub | `tools/fetch-toolchain` (Linux job in the container, macOS job on the runner, local gauntlet `toolchain`) | sha256 (`wolf-toolchain.toml`) | `curl --retry 3 --retry-delay 5`: no connect or total timeout, a refused connection not retried | `ci/fetch-retry url` |
| wolf-std at its commit, `git fetch` from GitHub | `tools/fetch-toolchain` | the commit id, fetched by id but not compared | no | `ci/fetch-retry git`, the commit compared |
| OpenSSH 10.0p2 tarball, its signature and the release key from `cdn.openbsd.org` | `tools/fetch-oracle` (Linux job, local gauntlet `oracle`) | sha256, read twice, and a VALIDSIG by the pinned fingerprint | `curl --retry 3 --retry-delay 5` | `ci/fetch-retry url` |
| den at its pin, `git fetch` from GitHub | `tools/fetch-den` (local gauntlet `den-pin` only) | the commit id, HEAD compared | no | `ci/fetch-retry git` |
| den's own toolchain | den's `tools/fetch-toolchain`, run by `tools/fetch-den` (local only) | den's own digests | den's own | unchanged: den's code |
| `actions/checkout@v4`, `actions/cache@v4`, `actions/upload-artifact@v4` | `.github/workflows/ci.yml` | tag | the actions' own | unchanged |
| GitHub's issues API | `ci/nightly-red.sh` (a red nightly) | n/a | `gh`'s own | unchanged |
| github.com port 22, and the live push | `tools/check-github`, `tools/check-live` (local gauntlet only) | the published host key | none: a row, SKIP by name when the port does not answer | unchanged: rows, not fetches of inputs |

## Evidence

### The rows

- **Red at the rows tip** `fed7646` (the rows, no helper), on an Apple silicon laptop: `FAIL F0 ci/fetch-retry is
  missing`, exit 1.
- **Green at the helper** `ef44b81`, the same laptop: F1–F11 PASS, `fetch-retry-test: 11 of 11 rows pass`.
- **Green on Ubuntu 24.04**, the hosted `plan-test` job of run 42901561274 (job 130128639078) at `78b2828`:

  ```text
  PASS F1 (exit 0, 1 request)
  PASS F2 (exit 0, 2 retry lines, 3 requests)
  PASS F3 (exit 3, 3 requests, named: True, file left: False)
  PASS F4 (exit 4, 1 request, named: True)
  PASS F5 (exit 3, named: True)
  PASS F6 (exit 3, 3 requests, 6.0 s, named: True)
  PASS F7 (exit 0, FETCH_HEAD d88ac206582a, pin d88ac206582a)
  PASS F8 (exit 3, 3 requests, named: True)
  PASS F9 (exit 4, not retried: True)
  PASS F10 (exit 0, tries 3)
  PASS F11 (exit 3 and 3, 3.0 s, named: True True)
  fetch-retry-test: 11 of 11 rows pass
  ```

- The Containerfile's retry function, joined as the builder joins it and run under `dash` with stub `apt-get`,
  `timeout` and `sleep`: a phase failing once is fetched on try 2 after `again in 30 s`; one failing every time
  prints `again in 30 s`, `90 s`, `270 s` and `FAIL fetch of the snapshot's packages (20261101T000000Z) failed after
  4 tries (last: exit 100)`, exit 1.

### The plant, red by name

`tl38-plant-503` at `76b1b8a` (one commit on `78b2828`: the wolf archive's URL pointed at a server in the container
that answers 503, the stage's stamp removed), dispatched with `jobs=linux`: run 42901662180, `tier partial` red, the
Linux job (130129008209) red at its stage step, exit 3, 186 s after the step began (21:07:13Z to 21:10:19Z), and
every row step after it skipped. The step's log, as printed:

```text
fetch-toolchain: http://127.0.0.1:8503/wolffe-lang/wolf-lang/releases/download/v0.2.37/wolf-0.2.37-x86_64-unknown-linux-gnu.tar.gz
curl: (22) The requested URL returned error: 503
plant-503: GET /wolffe-lang/wolf-lang/releases/download/v0.2.37/wolf-0.2.37-x86_64-unknown-linux-gnu.tar.gz -> 503
fetch-retry: http://127.0.0.1:8503/…/wolf-0.2.37-x86_64-unknown-linux-gnu.tar.gz: try 1 of 5 failed (HTTP 503); again in 5 s
fetch-retry: http://127.0.0.1:8503/…/wolf-0.2.37-x86_64-unknown-linux-gnu.tar.gz: try 2 of 5 failed (HTTP 503); again in 15 s
fetch-retry: http://127.0.0.1:8503/…/wolf-0.2.37-x86_64-unknown-linux-gnu.tar.gz: try 3 of 5 failed (HTTP 503); again in 45 s
fetch-retry: http://127.0.0.1:8503/…/wolf-0.2.37-x86_64-unknown-linux-gnu.tar.gz: try 4 of 5 failed (HTTP 503); again in 120 s
FAIL fetch of http://127.0.0.1:8503/wolffe-lang/wolf-lang/releases/download/v0.2.37/wolf-0.2.37-x86_64-unknown-linux-gnu.tar.gz failed after 5 tries (last: HTTP 503)
##[error]Process completed with exit code 3.
```

(The URL is shortened with `…` here only; the log prints it whole. Each try's `curl: (22)` and `plant-503: GET`
line sit between the retry lines: five requests in all.)

### The hosted run at the head

Run 42901561274, a dispatch at `78b2828` with no job named (tier full):

- `plan` and `plan-test` green (the rows above).
- `linux` (130128639166) green, 21:05:28Z to 21:19:53Z: the base image pulled through `ci/fetch-retry`; the image
  built from the new `RUN` in 67 s with no retry line, its four phases `Fetched 33.8 MB in 1s`, `3089 kB in 1s`,
  `33.6 MB in 7s` and `164 MB in 36s`; `--error-on=any` accepted; `tools/fetch-toolchain` through the helper (both
  archives `sha256 … OK`, the std at `2411d868`); `tools/fetch-oracle` built OpenSSH from a cold cache,
  `signature VALIDSIG 7168B983…`, and its three binaries held to their pins (`ssh a95aff08…`, `sshd 2b783b02…`,
  `ssh-keygen d84e9069…`, `holds the pinned OpenSSH`): the image's toolchain is unchanged. Every row step green.
- `macos`: queued behind the organisation's runners when this was written.

### Scored

| | predicted | measured | |
|---|---|---|---|
| the rows | red at the rows tip, green at the helper | `FAIL F0` at `fed7646`; 11 of 11 on macOS and Ubuntu | held |
| the plant | 4 retry lines 5, 15, 45, 120 s apart, the FAIL line, exit 3, about 190 s, the rows skipped | exactly so, 186 s | held |
| `--error-on=any` | accepted by apt 2.7 | accepted | held |
| the oracle's digests | unchanged | unchanged | held |
| the image | built through the new `RUN` | 67 s, no retry needed on a calm day | held |
| the apt lines' wording | `(last exit N)` | `(last: exit N)`, or `(last: timeout after S s)` for a try stopped at its limit, to read as `ci/fetch-retry`'s lines do | changed after the prediction |

## Done-when

- [x] The prediction, committed first (`4d2a550`)
- [x] `ci/fetch-retry-test.py` red at the rows tip, green at the helper
- [x] The plant red by name in a hosted run, with the retry lines (run 42901662180)
- [ ] The hosted run at the head green, tier full (run 42901561274: `plan`, `plan-test` and `linux` green; `macos` queued)
