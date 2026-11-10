# Recipes and autoinstall

The wizard writes a JSON recipe, and fisherman reads it.
You can also write a recipe by hand.
Use a hand-written recipe for automation, or to configure a live ISO.

The JSON schema is in [`shared/recipe/fisherman-recipe.schema.json`](../../shared/recipe/fisherman-recipe.schema.json).
All five frontends use this schema.

## Examples

### Bluefin or Bluefin-LTS, XFS, GRUB2, no encryption

This is the smallest recipe.

```json
{
  "disk": "/dev/sda",
  "filesystem": "xfs",
  "btrfsSubvolumes": false,
  "encryption": { "type": "none" },
  "image": "ghcr.io/projectbluefin/bootcos:latest",
  "targetImgref": "ghcr.io/projectbluefin/bootcos:latest",
  "selinuxDisabled": false,
  "composeFsBackend": false,
  "bootloader": "grub2",
  "hostname": "bootcos",
  "flatpaks": [],
  "user": {
    "username": "tuna",
    "fullname": "Tuna User",
    "password": "hunter2",
    "groups": ["wheel"]
  }
}
```

### Dakota: systemd-boot, composefs and btrfs

```json
{
  "disk": "/dev/nvme0n1",
  "filesystem": "btrfs",
  "btrfsSubvolumes": false,
  "encryption": { "type": "none" },
  "image": "ghcr.io/projectbluefin/dakota:latest",
  "targetImgref": "ghcr.io/projectbluefin/dakota:latest",
  "selinuxDisabled": false,
  "composeFsBackend": true,
  "bootloader": "systemd",
  "hostname": "bootcos",
  "flatpaks": [],
  "user": { "username": "", "fullname": "", "password": "", "groups": [] }
}
```

The value `"bootloader": "systemd"` selects the layout with 2 partitions.
It also sets the GPT type of the root partition for auto-discovery.
The value `"composeFsBackend": true` gives `--composefs-backend` to bootc.
The user fields are empty because Dakota has its own setup at first boot.

### Bluefin-LTS with btrfs and TPM2 encryption

```json
{
  "disk": "/dev/nvme0n1",
  "filesystem": "btrfs",
  "btrfsSubvolumes": true,
  "encryption": { "type": "tpm2-luks" },
  "image": "ghcr.io/projectbluefin/bootcos:latest",
  "targetImgref": "ghcr.io/projectbluefin/bootcos:latest",
  "selinuxDisabled": false,
  "composeFsBackend": false,
  "bootloader": "grub2",
  "hostname": "bootcos",
  "flatpaks": ["org.mozilla.firefox", "org.gnome.Console"],
  "user": {
    "username": "tuna",
    "fullname": "Tuna User",
    "password": "hunter2",
    "groups": ["wheel"]
  }
}
```

### TPM2 encryption with a passphrase as the fallback

```json
{
  "disk": "/dev/sda",
  "filesystem": "xfs",
  "btrfsSubvolumes": false,
  "encryption": {
    "type": "tpm2-luks-passphrase",
    "passphrase": "my-recovery-passphrase"
  },
  "image": "ghcr.io/projectbluefin/bootcos:latest",
  "targetImgref": "ghcr.io/projectbluefin/bootcos:latest",
  "selinuxDisabled": false,
  "composeFsBackend": false,
  "bootloader": "grub2",
  "hostname": "bootcos",
  "flatpaks": [],
  "user": { "username": "", "fullname": "", "password": "", "groups": [] }
}
```

## Field reference

| Field | Type | Description |
|---|---|---|
| `disk` | string | The block device for the install, for example `"/dev/sda"`. fisherman erases this disk. |
| `filesystem` | string | The root file system: `"xfs"` or `"btrfs"`. |
| `btrfsSubvolumes` | bool | Make the `@`, `@home` and `@snapshots` subvolumes. Only for btrfs. |
| `encryption.type` | string | `"none"`, `"luks-passphrase"`, `"tpm2-luks"` or `"tpm2-luks-passphrase"`. |
| `encryption.passphrase` | string | Necessary for `luks-passphrase` and `tpm2-luks-passphrase`. |
| `image` | string | The OCI image to install. podman pulls it. |
| `targetImgref` | string | The image reference for updates in the new OS. Usually it is the same as `image`. |
| `selinuxDisabled` | bool | Give `--disable-selinux` to bootc. Use it for an install from a different distribution. |
| `unifiedStorage` | bool | Leave it out. fisherman does not give `--experimental-unified-storage` to bootc, and it refuses a recipe that has `true` here. |
| `composeFsBackend` | bool | Give `--composefs-backend` to bootc. Images that use composefs, for example Dakota, need it. |
| `bootloader` | string | `"grub2"` (the default) or `"systemd"` for systemd-boot images. |
| `hostname` | string | The hostname of the new OS. |
| `flatpaks` | array | The Flatpak app IDs to copy from the live system to the new OS. |
| `user.username` | string | The user to make. If it is empty, fisherman makes no user. |
| `user.fullname` | string | The full name of the user. |
| `user.password` | string | The password as plain text. fisherman makes a hash of it during the install. |
| `user.groups` | array | More groups for the user, for example `["wheel", "docker"]`. |

## Autoinstall

Give a full recipe with `--autoinstall`.
The installer does not show the wizard:

```bash
flatpak run org.bootcinstaller.Installer --autoinstall /path/to/recipe.json
```

> **Warning:** An autoinstall erases the disk in the recipe and asks for no confirmation.
> Make sure that `disk` is the correct device.

The installer checks the recipe before it starts.
It reads the file and asks `fisherman validate` about each field.
If the file has a problem, the result page gives the reason. The installer does not change the disk.

In the Flatpak, a path below `/etc/` is the `/etc` of the host.
The installer reads `/run/host/etc/...` for you.

To start an autoinstall at boot, add a systemd user unit to the live image.
A user unit starts in the desktop session of the live user, so the installer has a display.
A system unit has no display and cannot show the window.

**`/usr/lib/systemd/user/bootc-installer-auto.service`**
```ini
[Unit]
Description=Unattended bootc install
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=flatpak run org.bootcinstaller.Installer --autoinstall /etc/bootc-installer/autoinstall.json

[Install]
WantedBy=graphical-session.target
```

Enable the unit for each user when you build the image:

```bash
systemctl --global enable bootc-installer-auto.service
```

The installer starts fisherman with `pkexec`.
Without a polkit rule, `pkexec` asks for a password and the install waits.
Add the rule for the live user that [Live ISO integration](../live-iso.md#polkit-setup) gives.
The rule must allow the action `org.freedesktop.policykit.exec`.

To set only some default values and keep the wizard, use a partial recipe.
Refer to [Customise the installer for your image](customising.md).
