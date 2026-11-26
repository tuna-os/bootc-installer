# Installer walkthroughs against the mock daemon

Each page below shows one installer, page by page. The pictures come from
the real installer against the mock daemon (`fishermand --mock`). The mock
writes to no disk. The disks, the machine and the recovery key are
fixtures. `tools/walkthrough/README.md` tells how CI makes the pictures.

| Installer | Toolkit | Walkthrough |
|---|---|---|
| GNOME | gnome-setup (GTK 4, libadwaita) | [gnome](gnome/README.md) |
| KDE Plasma | Kirigami (Qt 6) | [kde](kde/README.md) |
| COSMIC | libcosmic | [cosmic](cosmic/README.md) |
| niri | Quickshell (Qt 6) | [niri](niri/README.md) |
| XFCE | GTK 3 | [xfce](xfce/README.md) |

The pictures of real installs in a virtual machine are a different set.
The image-installer E2E test of tuna-os/tunaOS makes them for each run that
passes, as a run artifact.
