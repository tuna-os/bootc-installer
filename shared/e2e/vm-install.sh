#!/bin/bash
# Install a frontend's recipe FOR REAL and boot the result.
#
#   vm-install.sh <e2e-recipe-<frontend>.json> <frontend>
#
# This is fisherman's own bootcrew VM test (fisherman/justfile,
# bootcrew-ci-test) fed with the recipe a frontend actually produced in the
# E2E (<frontend>) job, instead of one generated from a matrix entry. Two
# fields are rewritten and nothing else:
#   disk   -> the loop device this runner just created;
#   image  -> the pre-built SSH-enabled canary that matches the recipe's
#             boot stack (composefs -> dakota, otherwise centos-bootc), so
#             the VM can be reached over SSH afterwards.
# additionalImageStores is dropped (no live medium here) and flatpaks are
# emptied (post-install downloads, not the install). Filesystem, bootloader,
# composefs, encryption, hostname and user come from the frontend, and are
# what fisherman installs.
set -euo pipefail
RECIPE_IN=$(readlink -f "${1:?recipe path}")   # absolute: the rest of this runs from fisherman/
FRONTEND=${2:?frontend name}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
FISH="$REPO/fisherman"
OUT=/tmp/tuna-e2e-vm
mkdir -p "$OUT"

cd "$FISH"
just setup-ssh-keys
just build
DISK_FILE=/tmp/tuna-e2e-vm-disk.img
just setup-loop "$DISK_FILE"
LOOPDEV=$(cat /tmp/bootcrew-loopdev.txt)

python3 - "$RECIPE_IN" "$LOOPDEV" "$OUT/recipe.json" <<'PY'
import json, sys
src, loopdev, dst = sys.argv[1:4]
r = json.load(open(src))
r["disk"] = loopdev
r.pop("additionalImageStores", None)
# The install-and-boot verdict is about the layout, bootloader and image; a
# Flatpak list would only add minutes of downloads after the install.
r["flatpaks"] = []
composefs = bool(r.get("composeFsBackend"))
r["image"] = ("ghcr.io/tuna-os/fisherman/dakota:ssh-enabled" if composefs
              else "ghcr.io/tuna-os/fisherman/centos-bootc:ssh-enabled")
# A frontend recipe may carry the live-ISO defaults; the canary images do
# not ship a matching bootloader for the other stack.
r["bootloader"] = "systemd" if composefs else "grub2"
if composefs and r.get("filesystem") == "xfs":
    r["filesystem"] = "btrfs"   # composefs needs fs-verity; xfs is rejected
json.dump(r, open(dst, "w"), indent=2)
print(json.dumps(r, indent=2))
PY
COMPOSEFS=$(python3 -c 'import json,sys; print(str(bool(json.load(open(sys.argv[1])).get("composeFsBackend"))).lower())' "$OUT/recipe.json")
PASSPHRASE=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("encryption",{}).get("passphrase",""))' "$OUT/recipe.json")

echo "=== installing $FRONTEND's recipe onto $LOOPDEV"
sudo /tmp/fisherman "$OUT/recipe.json" 2>&1 | tee "$OUT/install.log"

echo "=== enabling SSH in the installed system"
# fisherman's script writes root's authorized_keys into the stateroot var
# (the tree the booted guest mounts as /var) and an sshd_config.d drop-in.
# Needs the submodule at 7c3c738 or later: the older script wrote the key
# into the deployment's own var/, which the guest never sees, so sshd ran
# and rejected every probe until boot-verify timed out.
bash scripts/enable-ssh-installed.sh "$LOOPDEV" "$COMPOSEFS" /tmp/bootcrew-ssh/id_rsa.pub "$PASSPHRASE"
just verify-installation "$LOOPDEV" "$COMPOSEFS" "$PASSPHRASE"

# Same BLS patch as fisherman's bootcrew-ci-test: console=ttyS0 so the
# serial log in the artifact shows the kernel and systemd (without it the
# log stops at GRUB's "Booting ..."), and enforcing=0 because the files the
# SSH-enable step wrote from this Ubuntu runner carry no SELinux labels the
# guest's policy would let sshd_t read. Permissive keeps the gap visible as
# AVC denials in the journal instead of a silent boot-verify timeout.
echo "=== patching BLS entries (serial console, permissive SELinux)"
patch_bls() {
  local part="$1" label="$2" mnt patched=0 conf
  mnt=$(mktemp -d)
  sudo mount "$part" "$mnt" 2>/dev/null || { rmdir "$mnt"; return; }
  for conf in "$mnt"/loader/entries/*.conf; do
    [ -f "$conf" ] || continue
    if ! sudo grep -q "console=ttyS0" "$conf"; then
      sudo sed -i 's/^options /options console=ttyS0,115200 console=tty0 /' "$conf"
      patched=1
    fi
    if ! sudo grep -Eq "selinux=0|enforcing=0" "$conf"; then
      sudo sed -i 's/^options /options enforcing=0 /' "$conf"
      patched=1
    fi
    if [ "$patched" -eq 1 ]; then
      echo "  patched ($label): $(basename "$conf")"
      sudo grep "^options" "$conf"
    fi
  done
  [ "$patched" -eq 0 ] && echo "  no BLS entries on $label (or already patched)"
  sudo umount "$mnt"
  rmdir "$mnt"
}
patch_bls "${LOOPDEV}p1" EFI
if [ "$(sudo blkid -s TYPE -o value "${LOOPDEV}p2" 2>/dev/null)" != "crypto_LUKS" ]; then
  patch_bls "${LOOPDEV}p2" boot
fi

echo "=== booting it"
bash scripts/boot-verify.sh 2222 /tmp/bootcrew-ssh/id_rsa 600 2G "$LOOPDEV" "e2e-$FRONTEND" "$PASSPHRASE" 2>&1 | tee "$OUT/boot.log"

just cleanup-loop
rm -f "$DISK_FILE"
echo "OK: $FRONTEND's recipe installed and booted"
