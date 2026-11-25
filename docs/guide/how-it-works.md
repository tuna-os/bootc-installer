# How a recipe install works

This page is about the recipe path, which the live ISOs and the Flatpaks use.
[Architecture](../architecture.md) has the daemon path of the image-based medium.

The recipe path has two parts:

| Part | Language | Job |
|---|---|---|
| A frontend | Python, C++, Rust or QML and Go | The wizard. It collects your choices and writes a JSON recipe. |
| `fisherman/` | Go | The backend. It reads the recipe and writes the OS to the disk. It runs as root. |

`fisherman` is a git submodule.
Its source is in [tuna-os/fisherman](https://github.com/tuna-os/fisherman).

## Two boot stacks

| Stack | Images | Bootloader | Root file system | Layout |
|---|---|---|---|---|
| **systemd-boot** | [Dakota](https://github.com/projectbluefin/dakota) | systemd-boot and UKI | btrfs and composefs | 2 partitions: EFI and root |
| **GRUB2** | Bluefin, Bluefin-LTS, Bazzite | GRUB2 | XFS or btrfs | 3 partitions: EFI, `/boot` and root |

The installer selects the stack from two recipe fields: `bootloader` and `composeFsBackend`.
You do not have to do more steps.

### Dakota

Dakota is the next Project Bluefin variant.
It uses a sealed image.
The installer does these steps differently for Dakota:

- It uses systemd-boot with a UKI (Unified Kernel Image).
- It gives `--composefs-backend` to bootc.
- It formats the root partition as btrfs.
- It makes 2 partitions: an EFI partition of 2 GiB in FAT32, and a root partition.
- It sets the GPT type of the root partition to the Linux root GUID for the CPU architecture. Thus systemd-boot finds the root with no more configuration.
- It does not make a user account. Dakota has its own setup at first boot.

The recipe fields for Dakota are `"bootloader": "systemd"` and `"composeFsBackend": true`.

## The install steps

fisherman does these steps from the recipe.
The number of steps changes with the recipe: encryption, a second disk and the TPM each add a step.
Thus a frontend reads the percentage from fisherman and does not count steps.

1. **Partition.** The layout comes from the boot stack:
   - systemd-boot: 2 GPT partitions, EFI (2 GiB FAT32) and root. systemd-boot can read the EFI partition in FAT32, so there is no `/boot` partition.
   - GRUB2: 3 GPT partitions, EFI (FAT32), `/boot` (ext4) and root. GRUB cannot read new XFS features (`nrext64`, `exchange`, `rmapbt`). Also, `bootupctl` must find the `/boot` UUID on a raw block device, not on a LUKS mapper device.
2. **Format.** fisherman formats the EFI partition with `mkfs.fat -F32`. For GRUB2 images, it also formats `/boot` with `mkfs.ext4`.
3. **Encrypt.** This step is optional. fisherman runs `cryptsetup luksFormat` and `luksOpen`.
4. **Format root.** fisherman runs `mkfs.xfs` or `mkfs.btrfs`. With btrfs, it can also make named subvolumes.
5. **Mount.** fisherman mounts all partitions under `/mnt/fisherman-target`.
6. **Install with bootc.** fisherman runs `bootc install to-filesystem --skip-finalize` in a privileged podman container. The `--skip-finalize` flag keeps the target writable for the next steps.
7. **Post-install.** fisherman sets the hostname and copies the Flatpaks. It also does the first-boot tasks below.
8. **Finalize.** fisherman runs `fstrim`, mounts the root read-only, then runs `fsfreeze` and `fsthaw`. This does the work of `bootc install finalize`, which does nothing upstream at this time.

> **Scratch space:** fisherman keeps OCI blobs in `/var/fisherman-tmp` while it pulls an image.
> This directory is on the disk, and fisherman bind-mounts it to `/var/tmp`.
> Do not move the scratch space to `/run`. `/run` is a tmpfs with a limit of about half the RAM, and large images do not fit.

## Encryption

| Mode | What you get |
|---|---|
| `none` | No encryption. |
| `luks-passphrase` | LUKS2 with your passphrase. |
| `tpm2-luks` | LUKS2. The TPM2 unlocks the disk at boot, so there is no passphrase prompt. The installer shows a recovery key, and you must confirm it before you restart. |
| `tpm2-luks-passphrase` | LUKS2. The TPM2 unlocks the disk, and your passphrase is the fallback. There is no recovery key: the passphrase does that job. |

## Fast first boot

fisherman can do these tasks after the install.
Some tasks are only for live media.
Some tasks are only for a desktop image: the recipe key `extras`, or the entry of the image in the catalog, turns them on.
An image that is not in a catalog gets no `extras` task.
Refer to [Recipes](recipes.md) for the keys.

| Task | When | What it does |
|---|---|---|
| **Bluetooth** | `copyBluetoothPairings`. No key: only on live media | Copies `/var/lib/bluetooth` to the new OS. Paired devices connect again at first boot. |
| **Wi-Fi** | `copyNetworkProfiles`. No key: only on live media | Copies the NetworkManager `.nmconnection` files. Saved networks connect again at first boot. |
| **Audio names** | `extras.audioNames` | Adds WirePlumber rules that give ALSA devices names that people can read. The rules also hide S/PDIF and Pro Audio sinks. |
| **Live audio** | `extras.audioNames`, on live media | Applies the same audio rules to the live session immediately. |
| **OEM hardware** | `extras.oemSetup` | Finds ASUS and Framework hardware. Then it adds the correct brew packages for the first login. |
| **Printers** | `extras.printServices` | Enables `cups-browsed`, `avahi-daemon` and `ipp-usb` when the image has them. USB printers and AirPrint work immediately. |

fisherman does not make caches in the new OS.
The image must have its font, icon, schema and linker caches.

## Windows data

This installer does not copy data from Windows.
It erases the whole target disk.
To keep Windows and move your files into the new system, use [wootc](https://github.com/tuna-os/wootc).

## Phone companion

The GNOME, COSMIC and XFCE frontends have it.
The installer starts a local HTTPS server on port 8443 with a self-signed certificate.
It shows a QR code.
When you scan the code, your phone opens a form.
Type your account data and settings there.
The phone sends the data as JSON.

The installer puts the name, the username and the password on the account page, and uses the hostname.
The page shows only when the image needs an account.
The server listens on the LAN address of the computer only, and it accepts one form.

## Video during the install

In the legacy GNOME frontend, the progress screen plays an AV1 or VP9 video.
A distribution sets its own video in `branding.json`, under `extensions.gnome.video`.
Refer to [`shared/branding/README.md`](../../shared/branding/README.md).
The installer first makes sure that GStreamer has the codecs.
If the codecs are not available, it shows a static progress screen.

## Offline install from a live ISO

The file `/etc/bootc-installer/live-iso-mode` tells the installer that it runs on a live ISO.
Then the installer does not pull from the network.
fisherman finds the image stores of the ISO by itself.
The installer sends `additionalImageStores` only when the recipe of the ISO names stores.
Refer to [Live ISO](../live-iso.md) to build an ISO of this type.
