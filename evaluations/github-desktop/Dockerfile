# The common developer machine of evaluations/environment/Dockerfile, with a Linux desktop session and GitHub
# Desktop on it, set up the way its user left it: a notes-app repository with changes in progress.
# The steps up to the user are a copy of the common Dockerfile: a Dockerfile cannot build FROM another one that
# needs the universe's CA context, and a Compose service built only to be a base would be a universe service too.
FROM docker:29-dind AS dind

FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git gnupg python3 sudo \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        containerd.io docker-buildx-plugin docker-ce docker-ce-cli docker-compose-plugin iptables \
    && rm -rf /var/lib/apt/lists/*
# Moves the container's processes out of the root cgroup so a nested dockerd can delegate cgroup v2 controllers.
COPY --from=dind /usr/local/bin/dind /usr/local/bin/dind
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# The universe's certificate authority, provided by `launch` as the `dtu-ca` build context, so installs from
# github.com URLs the gateway answers for are trusted.
COPY --from=dtu-ca ca.crt /usr/local/share/ca-certificates/digital-twin-universe.crt
RUN update-ca-certificates

RUN useradd -m -s /bin/bash -G docker,sudo user \
    && echo "user ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/user \
    && chmod 0440 /etc/sudoers.d/user

# The desktop session, with the AT-SPI accessibility bus that computer use reads windows through.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb openbox dbus dbus-x11 libglib2.0-bin at-spi2-core libatk-adaptor libxi6 libxtst6 xcompmgr \
    && rm -rf /var/lib/apt/lists/*

# GitHub Desktop's Linux build, MIT licensed. Its app ships unpacked, which the seeded defect relies on.
ARG GITHUB_DESKTOP_URL=https://github.com/shiftkey/desktop/releases/download/release-3.4.13-linux1/GitHubDesktop-linux-amd64-3.4.13-linux1.deb
ARG GITHUB_DESKTOP_SHA256=8b5577761c7900cac2896b5fbc1d88f5aea48b6ce771437262be2a66ab38d987
RUN curl -fsSL "$GITHUB_DESKTOP_URL" -o /tmp/github-desktop.deb \
    && echo "$GITHUB_DESKTOP_SHA256  /tmp/github-desktop.deb" | sha256sum -c - \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/github-desktop.deb libasound2t64 libxss1 libgbm1 \
    && rm -rf /var/lib/apt/lists/* /tmp/github-desktop.deb

COPY start-desktop.sh /usr/local/bin/start-desktop
COPY make-repo.sh /tmp/make-repo.sh

USER user
RUN git config --global user.name "Dana Tester" \
    && git config --global user.email dana@example.com \
    && git config --global init.defaultBranch main \
    && bash /tmp/make-repo.sh /home/user/projects/notes-app
COPY --chown=user:user projects-README.md /home/user/projects/README.md
# GitHub Desktop past its first run: sign-in skipped, identity from git config, usage stats off, and status icons
# off so it fetches no repository in the background. It opens straight on the main window.
COPY ghd-profile.zip /tmp/ghd-profile.zip
RUN python3 -m zipfile -e /tmp/ghd-profile.zip "/home/user/.config/GitHub Desktop"

USER root
ARG SEED_BUG=0
COPY seed-discard-bug.sh /tmp/seed-discard-bug.sh
RUN if [ "$SEED_BUG" = 1 ]; then bash /tmp/seed-discard-bug.sh; fi \
    && rm /tmp/seed-discard-bug.sh /tmp/make-repo.sh /tmp/ghd-profile.zip

USER user
WORKDIR /home/user/project
# The nested daemon's data cannot live on the container's own overlay filesystem.
VOLUME /var/lib/docker
