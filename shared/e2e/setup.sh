#!/bin/bash
# Prepare a runner for the end-to-end jobs (see README.md).
#
#   1. build the real fisherman from the submodule;
#   2. install fisherman-shim.sh where the frontends look for fisherman;
#   3. create a loop disk so the recipe's `disk` exists and validates;
#   4. write the `fisherman probe --json` answer that offers it;
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
# What the shim prints for `fisherman probe --json` (shared/probe/README.md):
# the loop disk as the one eligible target, a machine that meets every
# requirement, no TPM. The real probe would exclude it twice over (a loop
# device, and under fisherman's 50 GiB minimum), and would list the runner's
# own disk, which a frontend that picks the first disk would then hand over.
python3 - "$LOOPDEV" > "$DIR/probe.json" <<'PY'
import json, sys
dev = sys.argv[1]
size = 20 * 1024 ** 3
print(json.dumps({
    "protocol_version": 1,
    "disks": [{
        "path": dev, "size_bytes": size, "size_label": "20 GiB",
        "model": "E2E loop disk", "vendor": "", "transport": "virtio",
        "transport_label": "VirtIO", "removable": False, "read_only": False,
        "eligible": True,
    }],
    "tpm": {"present": False, "version": "", "usable": False},
    "system": {"ram_bytes": 8 * 1024 ** 3, "cpu_threads": 4, "cpu_cores": 4,
               "uefi": True, "meets_requirements": True, "unmet": []},
    "live": {"is_live": False, "live_image": ""},
    "offline": {"stores": [], "images": []},
}, indent=2))
PY

# Frontends run these by name; the fake ones must win the PATH lookup.
echo "== PATH prefix: $HERE/fake-bin"
if [ -n "${GITHUB_PATH:-}" ]; then
  echo "$HERE/fake-bin" >> "$GITHUB_PATH"
fi
if [ -n "${GITHUB_ENV:-}" ]; then
  { echo "TUNA_E2E_DIR=$DIR"; echo "TUNA_E2E_DISK=$LOOPDEV"; echo "TUNA_E2E_DISK_NAME=$NAME"; } >> "$GITHUB_ENV"
fi
echo "TUNA_E2E_DISK=$LOOPDEV"
