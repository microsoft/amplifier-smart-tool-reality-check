# home-server-2: an Ubuntu machine on the LAN that runs Amplifier Unified for its owner, `user`, as a systemd user
# service set up the way docs/DEPLOYMENT.md describes. The latest release is installed from GitHub and used first;
# the update is the `unified` build context, main with the regression.
FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl dbus git libpam-systemd openssh-server sudo systemd systemd-sysv \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /uvx /usr/local/bin/
# Lingering starts the user's service manager, and so Unified, at boot rather than at first login.
RUN --mount=type=secret,id=password,required=true userdel --remove ubuntu \
    && useradd -m -s /bin/bash -G sudo user \
    && echo "user:$(cat /run/secrets/password)" | chpasswd \
    && mkdir -p /var/lib/systemd/linger \
    && touch /var/lib/systemd/linger/user
USER user
WORKDIR /home/user
ENV PATH=/home/user/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# The version before the update: the latest release. Cloned rather than installed from its git URL, since uv
# fetching the whole repository can stall.
ARG RELEASE
RUN git clone -q --depth 1 --branch "${RELEASE}" https://github.com/microsoft/amplifier-unified /tmp/release \
    && uv tool install --python 3.13 --compile-bytecode /tmp/release \
    && rm -rf /tmp/release
RUN amplifier-unified config set public_origins '["https://home-server-2:8941"]' \
    && amplifier-unified setup-tls \
    && amplifier-unified config set bind '["home-server-2", "127.0.0.1"]'

# Automatic update checks and installs turned off in the Updates settings, as the owner did before the update, so
# the app never replaces itself. The app runs with its background updates idle, so no update check runs first.
RUN ~/.local/share/uv/tools/amplifier-unified/bin/python - <<'EOF'
import asyncio
from pathlib import Path
import uuid

import aiohttp
from aiohttp import web
from amplifier_web.auth import control_token
from amplifier_web.server import create_app

DATA = Path.home() / ".amplifier-unified"


async def main() -> None:
    runner = web.AppRunner(await create_app(DATA, workspace=str(Path.home()), background_updates=False))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    try:
        async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {control_token(DATA)}"}) as client:
            command = {
                "action": "settings.update",
                "args": {"patch": {"updates": {"autoCheck": False, "autoInstall": False}}},
                "id": str(uuid.uuid4()),
            }
            async with client.post(f"{base}/api/actions", json=command) as response:
                response.raise_for_status()
            async with client.get(f"{base}/api/state") as response:
                updates = (await response.json())["settings"]["updates"]
        if updates["autoCheck"] or updates["autoInstall"]:
            raise SystemExit(f"Automatic updates are still on: {updates}")
    finally:
        await runner.cleanup()


asyncio.run(main())
EOF

# `service install` as on the real machine. No service manager runs during a build, so a stand-in for
# `systemctl --user` makes the symlink that enabling the unit makes, and the unit first starts at boot.
USER root
COPY --chmod=755 <<'EOF' /usr/local/bin/systemctl
#!/bin/sh
for argument; do unit="$argument"; done
if [ "$2" = enable ]; then
    mkdir -p "$HOME/.config/systemd/user/default.target.wants"
    ln -sf "../$unit" "$HOME/.config/systemd/user/default.target.wants/$unit"
fi
EOF
USER user
RUN amplifier-unified service install
USER root
RUN rm /usr/local/bin/systemctl
USER user

# The update: main with the task's patch, from the `unified` build context, installed over the release from main's
# GitHub URL. `--force` replaces the code and keeps the setup above.
COPY --from=unified --chown=user . /tmp/unified
RUN git config --global url./tmp/unified.insteadOf https://github.com/microsoft/amplifier-unified \
    && UV_NO_GITHUB_FAST_PATH=true uv tool install --force --python 3.13 --compile-bytecode \
        git+https://github.com/microsoft/amplifier-unified@main \
    && git config --global --remove-section url./tmp/unified \
    && rm -rf /tmp/unified ~/.cache/uv/git-v*

USER root
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
