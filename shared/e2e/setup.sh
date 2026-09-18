#!/bin/bash
# Prepare a runner for the end-to-end jobs (see README.md).
#
#   1. build the real fisherman from the submodule;
#   2. install fisherman-shim.sh where the frontends look for fisherman;
#   3. create a loop disk so the recipe's `disk` exists and validates;
#   4. write the lsblk fixture that names it;
#   5. print the PATH prefix the frontend must run with.
#
# Works as root (Fedora container) or as a sudoer (ubuntu runner).
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
DIR=/tmp/tuna-e2e
LIB=/usr/local/lib/tuna-e2e

as_root() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi; }

as_root mkdir -p "$DIR" "$LIB"
as_root chmod 1777 "$DIR"

echo "== building fisherman from the submodule"
( cd "$REPO/fisherman/fisherman" && go build -o /tmp/tuna-e2e-fisherman ./cmd/fisherman/ )
as_root install -m 0755 /tmp/tuna-e2e-fisherman "$LIB/fisherman.real"
as_root install -m 0755 "$HERE/fisherman-shim.sh" /usr/local/bin/fisherman
"$LIB/fisherman.real" --help >/dev/null 2>&1 || true
echo "   $(/usr/local/bin/fisherman validate /dev/null 2>&1 | head -1 || true)"

echo "== loop disk"
DISK_FILE="$DIR/disk.img"
if [ -e /dev/loop-control ] && as_root losetup --find >/dev/null 2>&1; then
  truncate -s 20G "$DISK_FILE"
  LOOPDEV=$(as_root losetup --find --show "$DISK_FILE")
  as_root chmod 0666 "$LOOPDEV" || true
else
  # No loop devices (unprivileged container). fisherman's Validate() only
  # requires the path to exist, so a file stands in; the VM job uses a real
  # loop device regardless.
  truncate -s 20G "$DISK_FILE"
  LOOPDEV="$DISK_FILE"
fi
echo "$LOOPDEV" > "$DIR/loopdev"
echo "   $LOOPDEV"

NAME=$(basename "$LOOPDEV")
cat > "$DIR/lsblk.json" <<JSON
{"blockdevices": [
  {"name": "$NAME", "path": "$LOOPDEV", "size": 21474836480, "model": "E2E loop disk",
   "type": "disk", "rm": false, "mountpoints": [null], "tran": "virtio"}
]}
JSON

# Frontends run these by name; the fake ones must win the PATH lookup.
echo "== PATH prefix: $HERE/fake-bin"
if [ -n "${GITHUB_PATH:-}" ]; then
  echo "$HERE/fake-bin" >> "$GITHUB_PATH"
fi
if [ -n "${GITHUB_ENV:-}" ]; then
  { echo "TUNA_E2E_DIR=$DIR"; echo "TUNA_E2E_DISK=$LOOPDEV"; echo "TUNA_E2E_DISK_NAME=$NAME"; } >> "$GITHUB_ENV"
fi
echo "TUNA_E2E_DISK=$LOOPDEV"
