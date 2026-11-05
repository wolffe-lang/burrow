# The oracle's build and run image: Ubuntu 24.04 by digest, its packages
# from the Ubuntu snapshot archive at one instant (burrow-oracle.toml).
FROM docker.io/library/ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55
ARG SNAPSHOT=20261101T000000Z
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates \
 && sed -i -e "s#http://archive.ubuntu.com/ubuntu/#https://snapshot.ubuntu.com/ubuntu/${SNAPSHOT}/#" \
           -e "s#http://security.ubuntu.com/ubuntu/#https://snapshot.ubuntu.com/ubuntu/${SNAPSHOT}/#" \
           /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --allow-downgrades \
      build-essential ca-certificates curl git gnupg python3 procps zlib1g-dev libssl-dev xz-utils \
 && rm -rf /var/lib/apt/lists/* \
 && dpkg-query -W -f '${Package} ${Version}\n' > /oracle-packages.txt
# sshd's privilege separation wants its user and an empty root-owned dir.
RUN useradd -r -d /var/empty -s /usr/sbin/nologin sshd && mkdir -p -m 755 /var/empty
ENV LC_ALL=C
WORKDIR /work/burrow
