#!/bin/bash
# Install a frontend's recipe FOR REAL and boot the result.
#
#   vm-install.sh <e2e-recipe-<frontend>.redacted.json> <frontend>
#
# This is fisherman's own bootcrew VM test (fisherman/justfile,
# bootcrew-ci-test) fed with the recipe a frontend actually produced in the
# E2E (<frontend>) job, instead of one generated from a matrix entry.
#
# The recipe is installed as the frontend wrote it (#322). The E2E catalog
# (shared/e2e/catalog.json) names the SSH-enabled canary and its bootloader,
# so the frontend's own `image`, `bootloader` and `flatpaks` are what the
# VM boots. One value can need a substitution: `disk`, the loop device of
# the runner that ran the frontend. This script attaches its disk at that
# same path when it is free, and then nothing changes. When the path is
# taken, the disk is the next free loop device and `disk` is the only
# value that changes. `check-recipe.py --vm` writes the copy and proves it:
# the frontend's bytes, with at most that one value replaced.
#
# A leaf with no `flatpaks` gives a recipe with no key, and fisherman then
# copies the system Flatpaks of this runner, as on a real machine (the
# runner has none). The recipe has no setBootNext: the runner is not live
# media, so fisherman leaves its firmware alone.
#
# Artifacts (#270). The input has no secret: the frontend job published a
# copy with each secret replaced by a marker, and `check-recipe.py --vm`
# restores the driver's test values (test-credentials.json) into a private
# directory. The recipe, the logs and boot-verify.sh's files stay there.
# On exit, publish.py copies to $OUT, the directory that the job uploads,
# only the recipe summary and the allowlisted logs, with each secret value
# replaced by the marker. The console gets the same redaction.
set -euo pipefail
RECIPE_IN=$(readlink -f "${1:?recipe path}")   # absolute: the rest of this runs from fisherman/
FRONTEND=${2:?frontend name}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
FISH="$REPO/fisherman"
OUT=/tmp/tuna-e2e-vm   # publication staging: the job uploads this, nothing else
rm -rf "$OUT"
mkdir -p "$OUT"
PRIV=$(mktemp -d /tmp/tuna-e2e-vm-private.XXXXXX)   # 0700: never uploaded
export ARTIFACTS_DIR="$PRIV/bootcrew"               # boot-verify.sh writes its logs here
mkdir -p "$ARTIFACTS_DIR"
publish_and_clean() {
  local rc=$?
  set +e
  # Only allowlisted names, redacted. A log that sudo wrote becomes ours to read.
  sudo chown -R "$(id -u):$(id -g)" "$PRIV" 2>/dev/null
  python3 "$HERE/publish.py" stage --recipe "$PRIV/recipe.json" --frontend "$FRONTEND" \
    --out "$OUT" "$PRIV/install.log" "$PRIV/boot.log" "$ARTIFACTS_DIR"/*.log
  sudo rm -rf "$PRIV"
  exit "$rc"
}
trap publish_and_clean EXIT
# field <recipe> <python expression over r>: one value of a recipe.
field() { python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' "$@"; }

cd "$FISH"
just setup-ssh-keys
just build
DISK_FILE=/tmp/tuna-e2e-vm-disk.img
WANT=$(field "$RECIPE_IN" 'r.get("disk", "")')
if [[ "$WANT" =~ ^/dev/loop[0-9]+$ ]] && [ -b "$WANT" ] && ! sudo losetup "$WANT" >/dev/null 2>&1; then
  # The frontend's disk path is free here: attach the disk there, so the
  # recipe needs no change at all.
  truncate -s 120G "$DISK_FILE"   # fisherman's DISK_SIZE (justfile)
  sudo losetup "$WANT" "$DISK_FILE"
  echo "$WANT" > /tmp/bootcrew-loopdev.txt
  echo "Loop device: $WANT (the recipe's own disk)"
else
  echo "The recipe's disk ${WANT:-<none>} is not a free loop device here; using the next free one"
  just setup-loop "$DISK_FILE"
fi
LOOPDEV=$(cat /tmp/bootcrew-loopdev.txt)

python3 "$HERE/check-recipe.py" --vm "$RECIPE_IN" "$LOOPDEV" "$PRIV/recipe.json" --frontend "$FRONTEND"
# The log shows the recipe summary: no secret, only allowlisted keys.
python3 "$HERE/publish.py" summary "$PRIV/recipe.json" --frontend "$FRONTEND"
# GitHub masks the values in the job log too, for a line that no redact
# pipe covers. The workflow command line itself is not shown in the log.
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  python3 -c 'import json,sys
r = json.load(open(sys.argv[1]))
for block, key in (("encryption", "passphrase"), ("user", "password")):
    v = (r.get(block) or {}).get(key) if isinstance(r.get(block), dict) else None
    if isinstance(v, str) and v:
        print("::add-mask::" + v)' "$PRIV/recipe.json"
fi
# redact: the console copy of a stream, with the recipe's secrets replaced.
redact() { python3 "$HERE/publish.py" redact-stream --recipe "$PRIV/recipe.json"; }
COMPOSEFS=$(field "$PRIV/recipe.json" 'str(bool(r.get("composeFsBackend"))).lower()')
PASSPHRASE=$(field "$PRIV/recipe.json" '(r.get("encryption") or {}).get("passphrase", "")')

# Guest checks (fisherman's BOOTCREW_GUEST_CHECKS, sourced by boot-verify.sh
# once SSH answers). region.sh: the booted system has the recipe's locale,
# keyboard layout and time zone, and its LUKS root is open (#325).
E2E_LOCALE=$(field "$PRIV/recipe.json" 'r.get("locale", "")')
E2E_KEYBOARD=$(field "$PRIV/recipe.json" '(r.get("keyboard") or {}).get("layout", "")')
E2E_TIMEZONE=$(field "$PRIV/recipe.json" 'r.get("timezone", "")')
E2E_ENCRYPTED=$(field "$PRIV/recipe.json" 'str((r.get("encryption") or {}).get("type", "none") != "none").lower()')
export E2E_LOCALE E2E_KEYBOARD E2E_TIMEZONE E2E_ENCRYPTED
BOOTCREW_GUEST_CHECKS=""
if [ -n "$E2E_LOCALE$E2E_KEYBOARD$E2E_TIMEZONE" ] || [ "$E2E_ENCRYPTED" = "true" ]; then
  BOOTCREW_GUEST_CHECKS="$HERE/vm-checks/region.sh"
fi
export BOOTCREW_GUEST_CHECKS
# A LUKS boot waits for the prompt and the typed passphrase: fisherman's
# centos-bootc-luks-user matrix entry gives it 800 s.
VM_TIMEOUT=600
if [ -n "$PASSPHRASE" ]; then VM_TIMEOUT=800; fi

echo "=== installing $FRONTEND's recipe onto $LOOPDEV"
sudo /tmp/fisherman "$PRIV/recipe.json" 2>&1 | tee "$PRIV/install.log" | redact

echo "=== enabling SSH in the installed system"
# fisherman's script writes root's authorized_keys into the stateroot var
# (the tree the booted guest mounts as /var) and an sshd_config.d drop-in.
# Needs the submodule at 7c3c738 or later: the older script wrote the key
# into the deployment's own var/, which the guest never sees, so sshd ran
# and rejected every probe until boot-verify timed out.
bash scripts/enable-ssh-installed.sh "$LOOPDEV" "$COMPOSEFS" /tmp/bootcrew-ssh/id_rsa.pub "$PASSPHRASE" 2>&1 | redact
just verify-installation "$LOOPDEV" "$COMPOSEFS" "$PASSPHRASE" 2>&1 | redact

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
bash scripts/boot-verify.sh 2222 /tmp/bootcrew-ssh/id_rsa "$VM_TIMEOUT" 2G "$LOOPDEV" "e2e-$FRONTEND" "$PASSPHRASE" 2>&1 | tee "$PRIV/boot.log" | redact

just cleanup-loop
rm -f "$DISK_FILE"
echo "OK: $FRONTEND's recipe installed and booted"
