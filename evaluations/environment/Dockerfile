# A developer's Linux machine: Docker, Python, uv, and sudo, and nothing of reality-check or what it may reach for.
# What the agent decides it needs, such as a browser, it installs itself, as it would on a person's machine.
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
USER user
WORKDIR /home/user/project
# The nested daemon's data cannot live on the container's own overlay filesystem.
VOLUME /var/lib/docker
