FROM debian:bookworm-slim

LABEL maintainer="Brett - github.com/brettmayson"
LABEL org.opencontainers.image.source=https://github.com/brettmayson/arma3server

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
    && \
    apt-get install -y --no-install-recommends --no-install-suggests \
        python3 \
        lib32stdc++6 \
        lib32gcc-s1 \
        libcurl4 \
        wget \
        ca-certificates \
        curl \
        libstdc++6 \
        libssl3 \
        libc6 \
        libavahi-client3 \
    && \
    apt-get clean autoclean \
    && \
    apt-get autoremove -y \
    && \
    rm -rf /var/lib/apt/lists/*

# Official SteamCMD bootstrap. Checksum pins the installer tarball; steamcmd self-updates on first run.
ENV STEAMCMD_URL=https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz
ENV STEAMCMD_SHA256=cebf0046bfd08cf45da6bc094ae47aa39ebf4155e5ede41373b579b8f1071e7c
RUN mkdir -p /steamcmd \
    && wget -qO /tmp/steamcmd_linux.tar.gz "${STEAMCMD_URL}" \
    && echo "${STEAMCMD_SHA256}  /tmp/steamcmd_linux.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/steamcmd_linux.tar.gz -C /steamcmd \
    && rm /tmp/steamcmd_linux.tar.gz \
    && /steamcmd/steamcmd.sh +quit || true

ENV PYTHONUNBUFFERED=1
ENV STEAMCMD_BIN=/steamcmd/steamcmd.sh
ENV STEAM_HOME=/root/Steam

ENV ARMA_BINARY=./arma3server_x64
ENV ARMA_CONFIG=main.cfg
ENV ARMA_PARAMS=
ENV ARMA_PROFILE=main
ENV ARMA_WORLD=empty
ENV ARMA_LIMITFPS=1000
ENV ARMA_CDLC=
ENV HEADLESS_CLIENTS=0
ENV HEADLESS_CLIENTS_PROFILE="\$profile-hc-\$i"
ENV PORT=2302
ENV MODS_LOCAL=true
ENV CLEAR_KEYS=true
ENV MODS_PRESET=
ENV SKIP_INSTALL=false
ENV STEAM_BRANCH=
ENV STEAM_BRANCH_PASSWORD=

EXPOSE 2302/udp
EXPOSE 2303/udp
EXPOSE 2304/udp
EXPOSE 2305/udp
EXPOSE 2306/udp

WORKDIR /arma3

VOLUME /arma3/server
VOLUME /root/Steam

STOPSIGNAL SIGINT

COPY *.py /

CMD ["python3","/launch.py"]
