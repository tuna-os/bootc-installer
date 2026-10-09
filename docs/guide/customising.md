# Customise the installer for your image

You can ship the installer on a live ISO, in a bootc image or in an appliance.
In all cases, put files in `/etc/bootc-installer/` in your OS tree.
The installer reads them from the host when it starts.

| Path | What it changes |
|---|---|
| `/etc/bootc-installer/images.json` | The image catalog. It replaces the catalog in the Flatpak. |
| `/etc/bootc-installer/recipe.json` | The default recipe values (the sys-recipe). |
| `$XDG_CONFIG_HOME/bootc-installer/images.json` | The catalog for one user. Use it to develop and test. |
| `/etc/bootc-installer/install-video.webm` | The video on the progress screen. |
| `/etc/bootc-installer/live-iso-mode` | Offline mode for a live ISO. Refer to [Live ISO](../live-iso.md). |

## Your own image catalog

Put an `images.json` in `/etc/bootc-installer/`.
The installer then shows only your images.

**`/etc/bootc-installer/images.json`**
```json
{
  "default_image": "ghcr.io/my-org/my-image:stable",
  "fallback_flatpaks": [],
  "images": [
    {
      "name": "My Distro",
      "icon": "/usr/share/pixmaps/my-distro.svg",
      "needs_user_creation": true,
      "children": [
        {
          "name": "Stable",
          "imgref": "ghcr.io/my-org/my-image:stable",
          "desc": "The stable release"
        },
        {
          "name": "Nightly",
          "imgref": "ghcr.io/my-org/my-image:nightly",
          "desc": "Latest nightly build"
        }
      ]
    }
  ]
}
```

This example for Bluefin shows only Bluefin variants, and selects LTS first:

```json
{
  "default_image": "ghcr.io/ublue-os/bluefin:lts",
  "fallback_flatpaks": [],
  "images": [
    {
      "name": "Bluefin",
      "icon": "/usr/share/pixmaps/bluefin.png",
      "flatpaks": "https://raw.githubusercontent.com/projectbluefin/common/refs/heads/main/system_files/bluefin/usr/share/ublue-os/homebrew/system-flatpaks.Brewfile",
      "needs_user_creation": true,
      "children": [
        {
          "name": "Stable",
          "imgref": "ghcr.io/ublue-os/bluefin:stable"
        },
        {
          "name": "LTS",
          "imgref": "ghcr.io/ublue-os/bluefin:lts"
        },
        {
          "name": "Dakota (experimental)",
          "imgref": "ghcr.io/projectbluefin/dakota:latest",
          "composefs": true,
          "bootloader": "systemd",
          "filesystem": "btrfs",
          "needs_user_creation": false
        }
      ]
    }
  ]
}
```

## Default recipe values

Put a partial recipe at `/etc/bootc-installer/recipe.json`.
The installer merges it with the output of the wizard.
These values are the defaults, and the user can change each of them.

**`/etc/bootc-installer/recipe.json`**
```json
{
  "hostname": "bluefin",
  "selinuxDisabled": false,
  "unifiedStorage": true,
  "flatpaks": [
    "org.mozilla.firefox",
    "org.gnome.Console"
  ]
}
```

This example for Bazzite sets btrfs and TPM2 LUKS as the defaults, and sets the hostname:

```json
{
  "hostname": "bazzite",
  "filesystem": "btrfs",
  "btrfsSubvolumes": true,
  "encryption": { "type": "tpm2-luks" },
  "unifiedStorage": true
}
```

For an install with no wizard, refer to [Autoinstall](recipes.md#autoinstall).

## Add an image to the default catalog

The default catalog is [`fisherman/data/images.json`](https://github.com/tuna-os/fisherman/blob/dev/data/images.json).
It is in the `fisherman` submodule, so send the change to [tuna-os/fisherman](https://github.com/tuna-os/fisherman) first.
Then update the submodule pointer in this repository.

The catalog is a tree of groups.
Each leaf is an image:

```jsonc
{
  "name": "My Distro",
  "subtitle": "Optional subtitle",
  "icon": "resource:///org/bootcinstaller/Installer/images/my-distro.svg",
  "flatpaks": ["org.mozilla.firefox", "org.gnome.Console"],
  "needs_user_creation": true,
  "children": [
    {
      "name": "Stable",
      "imgref": "ghcr.io/my-org/my-image:latest",
      "desc": "Optional description shown as tooltip"
    },
    {
      "name": "Composefs Edition",
      "imgref": "ghcr.io/my-org/my-image-composefs:latest",
      "composefs": true,
      "bootloader": "systemd",
      "filesystem": "btrfs",
      "needs_user_creation": false
    }
  ]
}
```

A child gets these fields from the nearest parent group:

| Field | Description |
|---|---|
| `flatpaks` | A URL to a Flatpak list, or an array of app IDs. |
| `icon` | A `resource:///…/images/name.svg` path, an absolute path or an XDG icon name. |
| `needs_user_creation` | Show the account screen. The default is `false`. |
| `composefs` | Use the composefs backend. |
| `bootloader` | `"grub2"` or `"systemd"`. |
| `filesystem` | `"xfs"` or `"btrfs"`. |

Put the SVG or PNG icon in `fisherman/data/images/`.
Then add it to `bootc_installer/bootc-installer.gresource.xml`.

We welcome pull requests that add images, icons or Flatpak lists.
