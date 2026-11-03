# The developer machine of evaluations/environment/Dockerfile with a Linux desktop session and GitHub Desktop on it,
# set up the way its user left it: a notes-app repository with changes in progress.
FROM reality-check-evaluation-machine:eval
ARG DEBIAN_FRONTEND=noninteractive
USER root

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
