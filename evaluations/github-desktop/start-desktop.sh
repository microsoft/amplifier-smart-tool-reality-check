#!/bin/bash
# The user's desktop session: an X server, a D-Bus session bus that starts AT-SPI on demand, a window manager,
# and a compositor. Returns once the session is up and leaves it running.
set -euo pipefail
mkdir -p -m 0700 "$XDG_RUNTIME_DIR"
socket=/tmp/.X11-unix/X${DISPLAY#:}
bus=${DBUS_SESSION_BUS_ADDRESS#unix:path=}

wait_for() {
    for _ in $(seq 1 100); do
        [ -S "$1" ] && return 0
        sleep 0.1
    done
    echo "$1 did not appear; see /tmp/desktop-*.log" >&2
    return 1
}

Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp > /tmp/desktop-xvfb.log 2>&1 &
wait_for "$socket"
dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --nofork --nopidfile > /tmp/desktop-dbus.log 2>&1 &
wait_for "$bus"
openbox > /tmp/desktop-openbox.log 2>&1 &
# Without a compositor, input sent to a window in the foreground paints black blobs into screenshots.
xcompmgr -n > /tmp/desktop-xcompmgr.log 2>&1 &
