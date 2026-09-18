#!/bin/bash
# The fisherman every frontend launches in the end-to-end job.
#
# Installed at /usr/local/bin/fisherman, which is the path all five frontends
# run (sudo outside Flatpak, pkexec inside). It is NOT a fake backend: the
# recipe the frontend hands over is validated by the REAL fisherman built
# from the submodule (`fisherman validate`, the same Validate() the install
# path runs first), and the recipe is kept so a later job can run the real
# install against a loop disk in a VM. What this shim does not do is
# partition the runner it is on: after validating, it streams the nine step
# lines a real install prints, so the frontend's progress parsing, log
# persistence and done-page transition run against the real protocol.
#
# Layout (created by setup.sh):
#   /usr/local/lib/tuna-e2e/fisherman.real   the binary built from fisherman/
#   /tmp/tuna-e2e/                           1777; recipe.json lands here
set -u
REAL=/usr/local/lib/tuna-e2e/fisherman.real
DIR=/tmp/tuna-e2e

case "${1:-}" in
  validate|images|scan|--help|-h|"")
    exec "$REAL" "$@"
    ;;
esac

RECIPE="$1"
mkdir -p "$DIR"
# Keep the recipe exactly as the frontend wrote it. The frontends delete
# their private copy the moment this process exits.
cp "$RECIPE" "$DIR/recipe.json"
chmod 0644 "$DIR/recipe.json"
echo "[e2e] recipe received: $RECIPE ($(wc -c < "$RECIPE") bytes)"

if ! "$REAL" validate "$RECIPE"; then
  echo "[e2e] the real fisherman rejected this recipe" >&2
  exit 3
fi
echo "[e2e] fisherman validate: ok"

DISK=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["disk"])' "$RECIPE")
IMAGE=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("image") or "(running system)")' "$RECIPE")
FS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("filesystem") or "xfs")' "$RECIPE")

# The step lines a real run prints (internal/progress in fisherman). Every
# frontend parses the "[n/9]" prefix for its progress bar.
step() { echo "$1"; sleep 0.2; }
step "[1/9] Partitioning $DISK"
step "  created EFI system partition (1.0 GiB, FAT32)"
step "  created root partition"
step "[2/9] Formatting boot partitions"
step "[3/9] Setting up encryption"
step "[4/9] Formatting root filesystem ($FS)"
step "[5/9] Mounting target at /mnt/fisherman-target"
step "[6/9] Installing image $IMAGE"
step "  pulling layers..."
step "[7/9] Installing bootloader"
step "[8/9] Configuring system"
step "[9/9] Finalizing"
echo "[e2e] install simulated; recipe kept at $DIR/recipe.json"
exit 0
