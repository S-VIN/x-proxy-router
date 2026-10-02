#!/bin/sh
# Checks what the container cannot run without, then starts the server.
set -eu

if [ -z "${XPR_UI_PORT:-}" ]; then
    echo "Set XPR_UI_PORT, the port of the web interface, e.g. 20800" >&2
    exit 1
fi

# Without a folder of the host the settings would be lost with the container.
if ! awk '$5 == "/data" { found = 1 } END { exit !found }' /proc/self/mountinfo; then
    echo "Mount a folder of the host at /data (XPR_DATA_DIR in .env for compose.yaml): the settings are stored there" >&2
    exit 1
fi

exec python -m server.main
