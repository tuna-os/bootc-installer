#!/bin/bash
# Enable SSH in the installed bootc system and inject the CI public key.
#
#   enable-ssh-installed.sh <LOOPDEV> <COMPOSEFS> <SSH_PUBKEY_FILE>
#
# This is fisherman/scripts/enable-ssh-installed.sh with one defect fixed:
# upstream wraps the chroot commands in a single-quoted `sh -c '...'` block
# whose comment reads "if they don't exist", and that apostrophe ends the
# block early. The rest of the lines then run on the RUNNER (Permission
# denied on its /etc/ssh/sshd_config) and bash reports "unexpected EOF
# while looking for matching `'". The chroot body is a quoted heredoc here,
# which cannot be ended by its own contents. fisherman's dev branch already
# carries a script that parses; drop this copy once the submodule pointer
# moves past the pinned commit (the gate this file belongs to is what makes
# that bump safe to take).
set -e

LOOPDEV="${1:?LOOPDEV required}"
COMPOSEFS="${2:?COMPOSEFS required}"
SSH_PUBKEY_FILE="${3:?SSH_PUBKEY_FILE required}"

echo "Enabling SSH in installed system..."

if [[ "$LOOPDEV" == /dev/loop* ]]; then
  ROOT_PART="${LOOPDEV}p3"
else
  ROOT_PART="${LOOPDEV}3"
fi

MOUNT_DIR=$(mktemp -d)
trap 'sudo umount -R "$MOUNT_DIR" 2>/dev/null || true; rmdir "$MOUNT_DIR" 2>/dev/null || true' EXIT

echo "Mounting root filesystem at $MOUNT_DIR..."
sudo mount "$ROOT_PART" "$MOUNT_DIR" || {
  echo "WARNING: Could not mount root partition $ROOT_PART"
  exit 1
}

if [ "$COMPOSEFS" = "true" ] && [ -f "$MOUNT_DIR/etc/hostname" ]; then
  ROOTFS="$MOUNT_DIR"
elif [ -d "$MOUNT_DIR/sysroot/ostree/deploy/default/deploy" ]; then
  ROOTFS=$(sudo ls -d "$MOUNT_DIR/sysroot/ostree/deploy/default/deploy"/*.0 2>/dev/null | head -1)
elif [ -d "$MOUNT_DIR/ostree/deploy/default/deploy" ]; then
  ROOTFS=$(sudo ls -d "$MOUNT_DIR/ostree/deploy/default/deploy"/*.0 2>/dev/null | head -1)
else
  ROOTFS="$MOUNT_DIR"
fi
if [ -z "$ROOTFS" ]; then
  echo "WARNING: Could not find the deployment directory"
  exit 1
fi
echo "Root filesystem: $ROOTFS"

if [ ! -d "$ROOTFS/usr" ] && [ ! -d "$ROOTFS/bin" ] && [ ! -d "$ROOTFS/etc" ]; then
  echo "WARNING: Invalid rootfs - essential directories not found at $ROOTFS"
  sudo ls -la "$ROOTFS" 2>/dev/null | head -20
  exit 1
fi

echo "Configuring sshd in the deployed system..."
# The ssh-enabled canary images already ship sshd; the package install is
# best-effort (no network inside the chroot on CI) and never fatal.
sudo chroot "$ROOTFS" sh -s <<'CHROOT' 2>/dev/null || true
if command -v apt-get >/dev/null 2>&1; then
  apt-get update >/dev/null 2>&1 && apt-get install -y openssh-server 2>&1 | grep -v "^Get:" || true
  systemctl enable ssh 2>/dev/null || true
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y openssh-server openssh-clients 2>&1 | grep -v "^Installing " || true
  systemctl enable sshd 2>/dev/null || true
fi
# Generate host keys when the image ships none.
if [ ! -f /etc/ssh/ssh_host_rsa_key ]; then
  ssh-keygen -A
fi
# CI uses an ephemeral key injected below; never enable password root login.
sed -i "s/^#PermitRootLogin .*/PermitRootLogin prohibit-password/" /etc/ssh/sshd_config 2>/dev/null || true
sed -i "s/^#PasswordAuthentication .*/PasswordAuthentication no/" /etc/ssh/sshd_config 2>/dev/null || true
sed -i "s/^#PubkeyAuthentication .*/PubkeyAuthentication yes/" /etc/ssh/sshd_config 2>/dev/null || true
echo "PermitRootLogin prohibit-password" >> /etc/ssh/sshd_config 2>/dev/null || true
echo "PasswordAuthentication no" >> /etc/ssh/sshd_config 2>/dev/null || true
echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config 2>/dev/null || true
CHROOT

echo "Injecting SSH public key..."
if sudo test -L "$ROOTFS/root"; then
  HOME_DIR="$ROOTFS/var/roothome"
else
  HOME_DIR="$ROOTFS/root"
fi
sudo mkdir -p "$HOME_DIR/.ssh"
sudo cp "$SSH_PUBKEY_FILE" "$HOME_DIR/.ssh/authorized_keys"
sudo chmod 700 "$HOME_DIR/.ssh"
sudo chmod 600 "$HOME_DIR/.ssh/authorized_keys"
echo "SSH enabled in installed system"
