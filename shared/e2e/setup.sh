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

# The real fisherman's checks read the machine: the full `validate` runs
# lsblk on the target disk (target eligibility, fisherman/docs/VALIDATE.md)
# and refuses the recipe with disk_unverified when lsblk is missing. A
# container image can lack it. Stop here with the reason, not later in the
# frontend's run.
for tool in lsblk; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "::error::shared/e2e/setup.sh: $tool is not installed (util-linux). fisherman validate needs it." >&2
    exit 1
  fi
done

echo "== loop disk"
# fisherman accepts a whole disk or a whole loop device as `disk`, and
# refuses a regular file (`disk_not_disk`, fisherman/docs/VALIDATE.md). So
# there is no fallback to the image file: without a loop device the setup
# stops here, and not later with a recipe that fisherman rejects.
DISK_FILE="$DIR/disk.img"
no_loop() {
  echo "::error::shared/e2e/setup.sh: $1" >&2
  echo "The end-to-end disk must be a loop device: fisherman refuses a regular" >&2
  echo "file as the target disk (disk_not_disk). Run on a host with losetup, or" >&2
  echo "in a container that has the loop devices (docker run --privileged)." >&2
  exit 1
}
command -v losetup >/dev/null 2>&1 || no_loop "losetup is not installed (util-linux)"
[ -e /dev/loop-control ] || no_loop "/dev/loop-control is not there"
truncate -s 20G "$DISK_FILE"
if ! LOOPDEV=$(as_root losetup --find --show "$DISK_FILE" 2>/dev/null); then
  # A container has its own /dev. The kernel can make a loop device there
  # that has no node. Make the nodes that are missing, then try again.
  for sys in /sys/block/loop*; do
    [ -r "$sys/dev" ] || continue
    node="/dev/$(basename "$sys")"
    [ -b "$node" ] || as_root mknod "$node" b $(tr ':' ' ' < "$sys/dev") || true
  done
  LOOPDEV=$(as_root losetup --find --show "$DISK_FILE") \
    || no_loop "losetup cannot attach $DISK_FILE"
fi
[ -b "$LOOPDEV" ] || no_loop "losetup gave '$LOOPDEV', which is not a block device"
as_root chmod 0666 "$LOOPDEV" || true
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
    # The runner has no bootc (fake-bin/bootc fails), no GPU and no DMI name.
    "bootc": {"context": "live-host", "found": False, "version": "",
              "version_reason": "bootc_missing",
              "capabilities": {
                  name: {"status": status, "reason": reason}
                  for name, status, reason in (
                      ("bootc_image_storage", "unknown", "not_established"),
                      ("container_inspect", "unsupported", "bootc_missing"),
                      ("deployment_mount", "unknown", "not_established"),
                      ("install_finalize", "unsupported", "bootc_missing"),
                      ("install_print_configuration", "unsupported", "bootc_missing"),
                      ("unified_storage", "unknown", "not_established"))}},
    "gpus": [],
    "dmi": {"vendor": "", "product": ""},
    # No source selected, on a host without bootc: what `fisherman probe
    # --json` answers on the runner (shared/probe/README.md, "Source
    # check"). The shim gives this answer to a `--source` probe too, so a
    # frontend reads it as a reply for another source and drops it.
    "capabilities": {
        "version": 1,
        "live_host": {"context": "live-host", "is_live": False, "image": "", "digest": "",
                      "identity_reason": "not_bootc_booted", "platform": "", "backend": "",
                      "bootc_version": ""},
        "source": {"selected": False, "ref": "", "transport": "", "locality": "unknown",
                   "store": "", "digest": "", "platform": ""},
        "execution_root": {"context": "none", "established": False,
                           "reason": "no_source_selected", "backend": "", "bootc_version": ""},
        "target": {"update_ref": "", "update_ref_from": "", "state": "not_installed"},
        "features": dict(
            {name: {"status": "unknown", "reason": "no_source_selected", "context": "none"}
             for name in ("bootc_image_storage", "deployment_mount", "finalization",
                          "install_configuration", "native_inspection")},
            unified_storage={"status": "unsupported", "reason": "fisherman_refuses",
                             "context": "fisherman"}),
        "install_defaults": {"observed": False, "root_filesystem": "", "block_setups": [],
                             "bootloader": ""},
        "image": {"observed": False, "kernel_version": "", "kernel_unified": False},
    },
    "bootc_store": {
        "version": 1, "context": "live-host", "available": False, "reason": "bootc_missing",
        "machine_platform": "x86_64",
        "sources": {"bootc_status": "bootc_missing", "store_index": "not_applicable",
                    "image_list": "not_applicable"},
        "ignored_entries": 0, "items": [],
    },
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
