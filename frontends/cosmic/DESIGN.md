# TunaOS COSMIC installer design

This repository contains the libcosmic frontend for the
[fisherman](https://github.com/tuna-os/fisherman) bootc installation backend.
The frontend gathers and validates the user's choices, writes the fisherman
recipe, and presents the backend's progress and result.

## Flow

The pages follow `../../shared/flow/screens.yaml`. `Page::ORDER` in
`src/main.rs` has twenty-one pages: the eighteen screens of the shared flow
and three pages that only the legacy backend shows. A page with nothing to
show is skipped, not shown blank (see `page_visible`). `Page::flow_id()` is
the shared screen id. The readiness stamp reports it as `page=`.

| # | Page | Screen id | Shows when |
|---|---|---|---|
| 1 | Requirements | `requirements` | A gate of the probe is not met. RAM and CPU offer "continue anyway". Firmware offers power off and the firmware setup. |
| 2 | Welcome | `try-or-install` | Always. **Try** quits the wizard, and the live session continues. |
| 3 | Choose a system | (legacy) `image` | Not on live media, and only when there is a choice. `../../shared/catalog/README.md` is the contract. |
| 4 | Language | `language` | Always. |
| 5 | Keyboard | `keyboard` | Always. |
| 6 | Time zone | `timezone` | Always. On the daemon backend it also has the location switch. |
| 7 | Network | `network` | Not on live media, and not when this computer can copy its own system. |
| 8 | Disclaimer | `prerelease` | `RELEASE_TYPE` of os-release is `pre-release` or `experiment`. |
| 9 | Terms of use | `eula` | The medium has `/usr/share/tuna-installer/eula.xml`, or the file that `TUNA_EULA_FILE` names. The box holds Continue. |
| 10 | Intel RST | `rst` | The daemon reports Intel RST. The page warns and continues. |
| 11 | Select a disk | `disk` | Always. |
| 12 | Existing data | `wipe-or-free` | Daemon backend: the disk has data and free space. |
| 13 | Disk encryption | `encryption` | Daemon backend: only with no TPM 2.0. Legacy backend: always. |
| 14 | Options | (legacy) `options` | Legacy backend: the filesystem. |
| 15 | Account | `account` | See "The first user". |
| 16 | Tour | (legacy) `tour` | The selected image has slides. |
| 17 | Confirm | `confirm` | Always. Its button is the destructive one. |
| 18 | Installing | `install` | After Confirm. **Cancel** asks first. The slug of the page is `installing`. |
| 19 | Recovery key | `recovery-key` | The install ended well and the disk is encrypted. The key, a QR code and a box that holds **Done**. |
| 20 | Handoff | `handoff` | The install ended well. |
| 21 | Finished | `done` | Always. Three states: installed, cancelled and failed. |

A pick on the language, keyboard and time zone pages changes the live
session through `localectl` and `timedatectl` (best effort, never a gate)
and goes to the installed system.

The **Exit** button in the header asks first. During a legacy install it
signals the process group of the wrapper and then quits, so no root install
stays behind.

There is no phone companion. The COSMIC port sent the account password
over plain HTTP on the LAN, and #293 removed it.

The header bar shows the current step and overall progress. Navigation is
reversible through Confirm. After the install starts, no page offers Back.

## The two backends

`fishermand::use_daemon()` reads the switch one time for each process.

| `TUNA_INSTALLER_BACKEND` | Backend |
|---|---|
| `daemon` | The `fishermand` Varlink daemon. |
| `legacy` | The recipe on the stdin of `fisherman -`. |
| `auto`, or not set | The daemon when its socket is there. If not, the legacy backend. |

The older `TUNA_USE_FISHERMAND=1` still selects the daemon when
`TUNA_INSTALLER_BACKEND` names no backend. The capture mode and the unit
tests do not follow the socket. `TUNA_FISHERMAN_SOCKET` names one socket
for all calls, and `FISHERMAN_SOCKET_DIR` names a directory with the four
sockets.

On the daemon backend:

- `Probe` and `Requirements` give the disks, the TPM, Intel RST, live media
  and the handoff mode.
- `Validate` checks the fields. The problems come back as data. The
  confirm page sends the whole config (`partial: false`). A problem holds
  **Install**, and so does a daemon that does not answer. The page does not
  ask the `fisherman` command for a plan or a source check.
- With a TPM 2.0 the disk seals with no prompt. With no TPM the encryption
  page starts at the passphrase type. An empty passphrase holds Continue.
- `installMode` is the pick of the existing-data page. When that page does
  not show, the mode is `erase`: an empty disk, or a disk with no free
  space. Confirm says which of the two happens to the data.
- `ConfigureTarget` gets the user, the hostname, the locale, the keymap and
  the time zone before `Install`. It gets `privacy.locationServices` only
  after the user moved the location switch.
- `Install` streams the events. **Cancel** sends `Cancel` on a second
  connection. The page leaves only on the terminal event.
- A failed install shows the daemon's `reason` in words: `device_lost`,
  `repart_failed`, `luks_failed`, or that the daemon does not answer. The
  step id says whether the disk changed. **Try again** goes back to Confirm.
- The recovery-key page calls `MakeRecoveryKey` when it opens and `Enroll`
  on **Done**. With no key the page offers **Try again** and no **Done**.
- The handoff page shows the mode of `Probe` (`migrate`, `soft_reboot` or
  `reboot`; an unknown mode is `reboot`). **Continue** calls `Handoff` with
  no mode. A failure offers **Close** and **Restart**.

The legacy backend keeps its pages and its recipe. It has no data facts,
so it does not show the RST and existing-data pages.

## The first user

The installer makes the first user. That is the rule of tunaOS: its images
ship the first-boot tool of KDE and mask the unit of that tool, because
each installer frontend makes the account.

The wizard skips the account page in two cases only:

- The catalog says that the image makes its own first user
  (`needs_user_creation: false`).
- On the daemon backend, the medium sets
  `TUNA_FIRSTBOOT_TOOL=cosmic-initial-setup`. Confirm, handoff and the
  finished page then say that the account comes at the first start.

The wizard does not look for `cosmic-initial-setup` on the medium. A tool
that is installed does not prove that it runs and makes a user. A skip on
that evidence installs a system that nobody can sign in to.

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
