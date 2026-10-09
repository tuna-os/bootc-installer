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
  "unifiedStorage": true,
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
  "unifiedStorage": true,
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
  "unifiedStorage": true,
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
  "unifiedStorage": true,
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
| `unifiedStorage` | bool | Give `--experimental-unified-storage` to bootc. The default is `true`. |
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

To start an autoinstall at boot, add a systemd unit to the live image:

**`/usr/lib/systemd/system/bootc-installer-auto.service`**
```ini
[Unit]
Description=Unattended bootc install
After=graphical.target

[Service]
ExecStart=flatpak run org.bootcinstaller.Installer --autoinstall /etc/bootc-installer/autoinstall.json
```

To set only some default values and keep the wizard, use a partial recipe.
Refer to [Customise the installer for your image](customising.md).
