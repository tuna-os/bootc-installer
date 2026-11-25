# Architecture

This page tells you which programs install a system, and how they talk.
There are two install paths. They use the same frontends.

| | Recipe path (legacy) | Daemon path |
|---|---|---|
| Used by | Live ISOs today, the Flatpaks on an installed system, wootc | The image-based installer medium, which is not published yet |
| Backend | `fisherman`, a command that runs as root | `fishermand`, a Varlink service on the live system |
| Interface | One JSON recipe on standard input, progress as JSON lines | Varlink calls on UNIX sockets |
| What it writes | Runs `bootc install to-filesystem` from a container image | Copies the prepared system of the medium to the disk |
| Encryption | None, passphrase, TPM2, or TPM2 and passphrase | Always encrypted |
| GNOME frontend | `bootc_installer/` in this repository | gnome-setup, which tunaOS builds |

## Frontends

| Desktop | Frontend | Toolkit | App ID | Paths |
|---|---|---|---|---|
| GNOME, Pantheon, Tuna | [gnome-setup](#gnome-setup), built in tunaOS | GTK 4 and libadwaita (Rust) | none, it is in the medium | daemon |
| GNOME | `bootc_installer/` | GTK 4 and libadwaita (Python) | `org.bootcinstaller.Installer` | recipe |
| KDE Plasma | `frontends/kde/` | Qt 6 and Kirigami (C++) | `org.tunaos.InstallerKde` | both |
| COSMIC | `frontends/cosmic/` | libcosmic (Rust) | `org.tunaos.InstallerCosmic` | both |
| niri | `frontends/niri/` | Quickshell QML and Go | `org.tunaos.InstallerNiri` | both |
| XFCE | `frontends/xfce/` | GTK 3 (Python) | `org.tunaos.InstallerXfce` | both |

Each native frontend has the eighteen screens of
[`shared/flow/`](../shared/flow/README.md), with the widgets of its own
desktop.

### Which path a native frontend uses

| Setting | Result |
|---|---|
| Not set, or `auto` | The daemon when its socket is there, else the recipe path |
| `daemon` | The daemon, or an error |
| `legacy` | The recipe path |

The variable is `TUNA_INSTALLER_BACKEND` for KDE, COSMIC and niri.
XFCE reads `BOOTC_INSTALLER_BACKEND`.

### Who makes the user

The frontend makes the first user. A medium can set `TUNA_FIRSTBOOT_TOOL` to
the name of a first-boot tool, for example `plasma-setup`. Then that tool
makes the user, and the account page does not show.

## gnome-setup

GNOME does not have a port in this repository. The medium uses
[GNOME Setup](https://gitlab.gnome.org/Teams/STF/setup) from upstream.
tunaOS builds one upstream commit with a small patch series.
The files are in
[`installer-medium/frontends/gnome-setup/`](https://github.com/tuna-os/tunaOS/tree/main/installer-medium/frontends/gnome-setup)
of tunaOS. It is not a fork. Pantheon and Tuna use the same program.

gnome-setup calls `io.systemd.SysInstall` and `io.systemd.CryptEnroll`.
`fishermand` serves the two, so gnome-setup needs no change to use it.

## fishermand

`fishermand` is in [tuna-os/fisherman](https://github.com/tuna-os/fisherman).
Its [FISHERMAND.md](https://github.com/tuna-os/fisherman/blob/dev/docs/FISHERMAND.md)
is the full reference. The Varlink interfaces of the service are:

| Interface | Socket | Use |
|---|---|---|
| `io.systemd.SysInstall` | `/run/systemd/io.systemd.SysInstall` | List the disks and run an install, as gnome-setup does |
| `io.systemd.CryptEnroll` | `/run/systemd/io.systemd.CryptEnroll` | Enrol a passphrase or a recovery key |
| `io.systemd.Shutdown` | `/run/systemd/io.systemd.Shutdown` | Restart or power off |
| `io.tunaos.Fisherman` | `/run/fisherman/io.tunaos.Fisherman` | The requirements, probe, validate, configure, install, handoff and cancel calls of the native frontends |

The three systemd interfaces hold only the calls that gnome-setup makes.
They are compatible with that client, and they are not a copy of systemd.

The real service does these things:

- It copies the system of the medium to an encrypted partition.
- It stores the user, the locale and the host name in the new system.
- It changes the boot entry, the UUIDs and the crypttab.

It does not migrate the live system, do a soft reboot or use kexec yet.
Thus each install ends with a restart.

`fishermand --mock` serves test data and changes no disk. The tests of the
native frontends use it.

The medium builds `fishermand` from its own pin (`fisherman_ref` in
`tunaos.toml` of tunaOS). The `fisherman` submodule here is a different pin.
It follows the `prod` branch and supplies the command for the recipe path.

## The recipe path

```
 frontend  ──recipe JSON on stdin──▶  fisherman (root)  ──▶  disk
     ▲                                      │
     └───────── progress as JSON lines ─────┘
```

1. The frontend asks `fisherman probe --json` for the disks and the hardware.
2. It checks fields with `fisherman validate` while you type.
3. It writes the recipe to the standard input of fisherman. No file holds the
   recipe, because it has the passphrase and the password.
4. fisherman partitions the disk, runs `bootc install to-filesystem` and
   configures the new system.
5. The frontend shows the progress, the recovery key and the restart button.

In a Flatpak, the frontend starts fisherman on the host with
`flatpak-spawn --host pkexec`.
[How a recipe install works](guide/how-it-works.md) gives each step.

## What is legacy, and for how long

| Part | State | Goes away when |
|---|---|---|
| `bootc_installer/` (`org.bootcinstaller.Installer`) | Live ISOs use it today. It gets fixes. It gets no port to the daemon. | The image-based medium replaces the live ISOs. [ADR 0018](https://github.com/tuna-os/tunaOS/blob/main/docs/adr/0018-image-installer-suite-and-fisherman-retirement.md) in tunaOS has the exit criteria. |
| The recipe path | Supported | [wootc](https://github.com/tuna-os/wootc) moves to a different backend, and the exit criteria above pass |
| `/etc/bootc-installer/` and the `bootc-installer` package name on GHCR | Supported names | No date |

There is no date for the removal of the recipe path.
[The image-based medium](image-medium.md) has the test state.
