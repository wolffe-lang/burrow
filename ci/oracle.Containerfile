# The oracle's build and run image, and burrow's: Ubuntu 24.04 by digest (clang and
# lld for the release tier), its packages
# from the Ubuntu snapshot archive at one instant (burrow-oracle.toml).
FROM docker.io/library/ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55
ARG SNAPSHOT=20261101T000000Z
# Each of apt's four network phases (the live mirrors' lists and
# ca-certificates, which the snapshot's HTTPS needs; then the snapshot's
# lists and packages) is tried up to 4 times, 30, 90 and 270 s apart, each
# try under a total limit, with apt's own retries and a 30 s connect and
# idle timeout per file. Packages are fetched with --download-only under
# the limit and installed with no network after it. The last failure is
# named: `FAIL fetch of WHAT failed after 4 tries (last: exit N)`
# (ci/fetch-retry's policy and lines; python3 is not in the image yet).
RUN set -eu; \
    apt="apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30"; \
    pkgs="build-essential clang lld ca-certificates curl git gnupg python3 procps zlib1g-dev libssl-dev xz-utils"; \
    tries() { \
        what=$1 limit=$2; shift 2; n=1; \
        while :; do \
            if timeout -k 30 "$limit" "$@"; then \
                [ "$n" = 1 ] || echo "fetch-retry: $what: fetched on try $n of 4"; return 0; \
            else rc=$?; fi; \
            case $rc in 124 | 137) last="timeout after $limit s" ;; *) last="exit $rc" ;; esac; \
            if [ "$n" -ge 4 ]; then echo "FAIL fetch of $what failed after 4 tries (last: $last)"; return 1; fi; \
            case $n in 1) pause=30 ;; 2) pause=90 ;; *) pause=270 ;; esac; \
            echo "fetch-retry: $what: try $n of 4 failed ($last); again in $pause s"; \
            sleep "$pause"; n=$((n + 1)); \
        done; \
    }; \
    tries "the live mirrors' package lists" 300 $apt update --error-on=any; \
    tries "ca-certificates from the live mirrors" 600 $apt install -y --no-install-recommends --download-only ca-certificates; \
    DEBIAN_FRONTEND=noninteractive $apt install -y --no-install-recommends ca-certificates; \
    sed -i -e "s#http://archive.ubuntu.com/ubuntu/#https://snapshot.ubuntu.com/ubuntu/${SNAPSHOT}/#" \
           -e "s#http://security.ubuntu.com/ubuntu/#https://snapshot.ubuntu.com/ubuntu/${SNAPSHOT}/#" \
           /etc/apt/sources.list.d/ubuntu.sources; \
    tries "the snapshot's package lists (${SNAPSHOT})" 300 $apt update --error-on=any; \
    tries "the snapshot's packages (${SNAPSHOT})" 600 $apt install -y --no-install-recommends --allow-downgrades --download-only $pkgs; \
    DEBIAN_FRONTEND=noninteractive $apt install -y --no-install-recommends --allow-downgrades $pkgs; \
    rm -rf /var/lib/apt/lists/*; \
    dpkg-query -W -f '${Package} ${Version}\n' > /oracle-packages.txt
# sshd's privilege separation wants its user and an empty root-owned dir.
RUN useradd -r -d /var/empty -s /usr/sbin/nologin sshd && mkdir -p -m 755 /var/empty
# The rows' login: an account with an empty password, which the rows' sshd
# admits through RFC 4252's `none` method only where a row allows it.
RUN useradd -m -s /bin/sh burrowtest && passwd -d burrowtest
ENV LC_ALL=C
WORKDIR /work/burrow
