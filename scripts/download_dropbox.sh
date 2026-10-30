#!/usr/bin/env bash
# Sync pollen tray images from Dropbox into data/raw using rclone.
# One-time setup: run `rclone config` and create a remote of type "dropbox"
# (default name below is "dropbox"; override with RCLONE_REMOTE).
# Usage: scripts/download_dropbox.sh "<path in Dropbox>" [--dry-run]
set -euo pipefail

REMOTE="${RCLONE_REMOTE:-dropbox}"
SRC="${1:?Usage: $0 \"<path in Dropbox>\" [extra rclone flags]}"
shift || true
DEST="$(dirname "$0")/../data/raw"

rclone copy "${REMOTE}:${SRC}" "$DEST" \
  --progress --transfers 8 --checksum "$@"
