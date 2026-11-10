# TunaOS COSMIC installer design

This repository contains the libcosmic frontend for the
[fisherman](https://github.com/tuna-os/fisherman) bootc installation backend.
The frontend gathers and validates the user's choices, writes the fisherman
recipe, and presents the backend's progress and result.

## Flow

The installer has fourteen screens. A screen with nothing to show is
skipped, not shown blank (see `page_visible`):

1. **Requirements** blocks on fisherman's unmet requirements (RAM, CPU,
   firmware) with one card for each gate. RAM and CPU offer "continue
   anyway". Unsupported firmware offers only power off and a reboot to the
   firmware setup. Shown only while a gate stands.
2. **Welcome** introduces the product that the branding resolver found.
3. **Choose a system** shows the image catalog as a flat list with a search
   box, and a row for a custom image reference. A row shows the breadcrumb
   of the leaf ("Atlas › Stable"), because the name of a tag leaf is a
   channel. The selection at the start is the branding `default_image`,
   then the catalog's `default_image`. If the catalog has neither, nothing
   is selected and Continue is not there. The page is skipped on live media.
   `../../shared/catalog/README.md` is the contract.
4. **Language**, 5. **Keyboard**, 6. **Time zone** change the live session
   through `localectl` and `timedatectl` on the host (best effort, never a
   gate). Each page says that it changes this session only. The installed
   system keeps the image's values until the recipe has fields for them
   (#292).
7. **Network** checks the connection: the registry of the selected image on
   port 443, then `ghcr.io:443`, then `8.8.8.8:53`. Continue is not there
   until the check passes. With no connection the page offers **Network
   settings**, which opens the desktop's own tool on the host, and
   **Recheck**. The page is skipped on live media.
8. **Select a disk** lists the disks that `fisherman probe --json` offers.
9. **Options** has the hostname, the filesystem and the encryption. The
   filesystem list is the list of the selected image, so an image that
   allows ext4 offers it.
10. **Account** creates the first user: the password two times, with a
    reveal button. It is skipped only when the catalog says that the image
    makes its own user (`needs_user_creation: false`). An image that the
    catalog does not have needs an account.
11. **Tour** shows the carousel slides of the selected image, if it has any.
12. **Confirm** shows the choices. Its button is the destructive one.
13. **Installing** pipes the recipe to `fisherman -` on stdin and shows the
    progress. **Cancel** opens a question first. "Stop the installation"
    signals the process group of the wrapper.
14. **Finished** has three states: installed, cancelled and failed.
    fisherman's exit code 130, or a signal after a confirmed cancel, is
    "cancelled" (the copy key `done_cancelled_title`), not a failure.

The **Exit** button in the header also asks first. During an install it
signals the process group of the wrapper and then quits, so no root install
stays behind.

There is no phone companion. The COSMIC port sent the account password
over plain HTTP on the LAN, and #293 removed it.

The header bar shows the current step and overall progress. Navigation is
reversible through Confirm; starting installation is the boundary after which
the UI no longer offers Back or Continue.

## How fisherman runs

`offline::fisherman_argv` is the one resolver. Probe, validation and install
all use it.

| Where | Probe and validation | Install |
|---|---|---|
| Native | `/usr/local/bin/fisherman ...` | `bash -c 'pkexec /usr/local/bin/fisherman -; exit $?'` |
| Native, live media | the same | `bash -c 'sudo -n /usr/local/bin/fisherman -; exit $?'` |
| Flatpak | `flatpak-spawn --host <staged> ...` | `flatpak-spawn --host bash -c "pkexec '<staged>' -; exit $?"` |

In a Flatpak, `<staged>` is `$XDG_CACHE_HOME/bootc-installer/fisherman`: a
copy of the packaged `/app/bin/fisherman`. The installer compares its
SHA256 with the answer of `sha256sum` on the host before it runs the file.
The path never comes from `HOME/.cache`.

## COSMIC integration

The app implements `cosmic::Application` and uses libcosmic widgets, spacing,
colors, and the user's active accent. Structural colors come from the COSMIC
theme rather than fixed RGB values so that light and dark themes remain
legible. The destructive action and status text use the corresponding COSMIC
semantic styles.

The layout is a centered, single-column wizard. Device choices use COSMIC list
items, configuration choices use settings sections, and the installation log
uses monospaced text. Copy is short, factual, and sentence case.

## Product and installation data

The product name, the hostname seed and the default image come from the
branding resolver (`src/branding.rs`, `../../shared/branding/README.md`).
Live media is fisherman's answer (`live.is_live` of the probe). The recipe
then has no `image`, and fisherman installs the booted image without a
download. The catalog leaf of that image still gives the bootloader, the
composefs flag, the filesystem and the account rule. The recipe leaves
`additionalImageStores` out: fisherman finds the stores of the host.

## Capture mode

Setting `TUNA_CAPTURE_DIR` replaces disk and installation data with fixtures
and renders every screen for the
[GUI walkthrough](docs/gui-walkthrough.md). Capture mode refuses
`StartInstall`, so generating documentation cannot start fisherman or modify a
disk. The harness reads back the frame presented by wgpu and rejects blank or
nearly blank renders.

The CI capture runs under Xvfb with Mesa lavapipe. See the walkthrough and the
`capture` recipe in `justfile` for local prerequisites and commands.

## Accessibility and quality

Controls use explicit labels and disabled states to prevent incomplete input
from advancing. Theme-derived semantic colors preserve contrast across COSMIC
themes. Changes to the wizard should be checked with keyboard navigation and
by reviewing all generated screens in both the ordinary and variant-branded
capture artifacts.
