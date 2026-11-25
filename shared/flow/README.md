# Shared installer flow

This is the flow spec for the four native frontends (KDE, COSMIC, Niri,
XFCE). It comes from [gnome-setup](https://github.com/hanthor/gnome-setup)
(branch `utah`), read from its source. Issue: tuna-os/installer#442.
Daemon: tuna-os/fisherman#512.

`screens.yaml` is the machine-readable spec. This file explains it. A test
(`tests/unit/test_shared_flow.py`) holds the two to each other.

## What a screen is

Each screen has a stable id with the same meaning in every frontend. Layout,
widgets, motion and words follow the toolkit. The order below is the order of
`screens.yaml`. A frontend skips a screen that has nothing to show. It never shows a blank one.

A frontend reports the screen id as `page=` in the readiness stamp. The stamp
itself is in section 1 of `docs/INSTALLER-FRONTENDS.md` in tunaOS.

| # | Id | Shows when | Varlink call |
|---|---|---|---|
| 0 | `requirements` | A gate is unmet | `io.tunaos.Fisherman.Requirements` |
| 1 | `try-or-install` | Always on live media | none |
| 2 | `language` | Always | `ConfigureTarget` |
| 3 | `keyboard` | Always | `ConfigureTarget` |
| 4 | `timezone` | Always | `ConfigureTarget` |
| 5 | `network` | The image needs a download | none (host) |
| 6 | `prerelease` | os-release says pre-release or experiment | none |
| 7 | `eula` | The image ships an EULA file | none |
| 8 | `rst` | `Probe` reports Intel RST | `Probe` |
| 9 | `disk` | Always | `Probe`, `SysInstall.ListCandidateDevices` |
| 10 | `wipe-or-free` | The disk has data and free space | none |
| 11 | `encryption` | No TPM 2 | `Validate`, `CryptEnroll.Enroll` |
| 12 | `account` | No first-boot tool owns the user | `Validate`, `ConfigureTarget` |
| 13 | `confirm` | Always | `Validate` |
| 14 | `install` | After confirm | `Install`, `Cancel` |
| 15 | `recovery-key` | The disk is encrypted | `CryptEnroll.MakeRecoveryKey`, `Enroll` |
| 16 | `handoff` | After the install | `Handoff`, `Shutdown.SoftReboot` |
| 17 | `done` | The install ended | `Shutdown.Reboot` |

The tables use short names. `screens.yaml` has the full names, the inputs
and outputs, the skip rules, the failure states and the accessibility names.
Field names of `io.tunaos.Fisherman` are proposals until the daemon lands.

## Required screens

The harness needs six: `try-or-install`, `disk`, `confirm`, `install`,
`recovery-key` and `done`. A frontend records the others until the owners promote them. `installer-screens.proposed.yaml` holds the proposed content of
`tests/installer-screens.yaml` in tunaOS. That file is in another repository,
so this copy is a proposal. It keeps the six old ids as `aliases`, because
the walkthrough script and `shared/walkthrough/parity_report.py` read them.

## Where this spec differs from gnome-setup

Issue #442 says that the order matches gnome-setup. These points are not so.
Each comes from the source of gnome-setup.

- `timezone`, `network`, `privacy` and `user` are in `data/pages.conf`. No
  page builds them. The loader logs `unsupported page` and drops them.
- `window.rs` sets the mode to `live-initial-setup` (a TODO). So `installer-welcome` never runs. A single class builds both welcome ids.
- `language`, `keyboard`, `prerelease` and `eula` come before
  `try-or-install`. This spec keeps the order of #442.
- `rst` comes before `disk`, and it does not block. It warns and continues.
  This spec puts `rst` before `disk` and does not block.
- The disk passphrase comes after the install. gnome-setup enrols it with
  `CryptEnroll.Enroll`. It unlocks with the empty password that sysinstall set. A native frontend asks before `confirm`.
- There is no `confirm` page. A dialog asks, in three kinds. A forced erase
  has a three second countdown on its button.
- The EULA page has an accept box. It gates Next.
- The keyboard page has no test field.
- gnome-setup has no cancel, no retry and no `handoff`. A failure shows the
  error text and stops.
- The recovery key page shows an empty key if `MakeRecoveryKey` fails. The
  spec makes that a failure state.
- gnome-setup sets language and keyboard in the live session through
  systemd-localed. `SysInstall.Run` then copies locale, keymap and time zone
  to the target. It has no `ConfigureTarget`.

## Frontends today

Status is `have`, `partial` or `missing`, from the code of each frontend.
`DESIGN.md` of KDE and COSMIC is stale: both say that the recipe has no
locale field, and it has one.

| Screen | KDE | COSMIC | Niri | XFCE |
|---|---|---|---|---|
| `requirements` | partial | have | partial | partial |
| `try-or-install` | missing | partial | have | missing |
| `language` | partial | have | have | partial |
| `keyboard` | partial | have | have | partial |
| `timezone` | partial | have | have | partial |
| `network` | partial | have | have | partial |
| `prerelease` | missing | missing | have | missing |
| `eula` | missing | missing | have | missing |
| `rst` | missing | missing | have | missing |
| `disk` | have | have | have | have |
| `wipe-or-free` | missing | missing | have | missing |
| `encryption` | partial | partial | have | have |
| `account` | have | have | have | have |
| `confirm` | have | have | have | have |
| `install` | have | have | have | have |
| `recovery-key` | partial | partial | have | partial |
| `handoff` | missing | missing | have | missing |
| `done` | have | have | have | have |

The other frontends keep the `recovery-key` in a panel on the done page,
with a copy button and an acknowledgement box, and have no QR code. Niri
shows a QR code and counts as `have`.

The page counts in the port issues differ from the code:

- KDE has seven modules. Language, keyboard and time zone are on its welcome
  module. A network gate and a requirements gate exist.
- COSMIC has fourteen pages, as #444 says.
- Niri has nine steps, not seven. Its Session step holds keyboard, language,
  time zone and network.
- XFCE has eight pages, not seven. Its identity page holds language,
  keyboard and time zone in an expander.

## Test contract

The harness is Utah's `raw_e2e.py` over AT-SPI. These rules come from the
Utah run of gnome-setup (projectbluefin/utah#1437).

1. Dump the AT-SPI tree inside the guest. Click from the host with QMP
   `input-send-event` on a USB tablet. Wayland refuses input that a program inside the guest sends.
2. One name can belong to many nodes. `Done` can be a panel, a button and a label,
   and the QR dialog adds a second button. Match `role=button` and sensitive.
   Prefer the node in the topmost dialog.
3. Some values are labels whose name equals their text. The recovery key is
   one. Match it by shape, not by a node named `Recovery Key`. The shape is
   in `screens.yaml`.
4. Classify the page from its text on every poll. Test for failure before
   done. Do not use fixed click lists.
5. A size from a toolkit holds a no-break space. Normalise it before you
   compare. Use the helper in `shared/client`.
6. Where a toolkit has no AT-SPI, record that. Fall back to QEMU key events
   and OCR, as `scripts/installer-walkthrough.py` does.

Toolkit status, not yet checked on a live frontend:

| Toolkit | Frontend | AT-SPI |
|---|---|---|
| GTK 4 | gnome-setup | yes, Utah drives it |
| Qt 6 Quick | KDE, Niri | expected for KDE. Quickshell: unchecked |
| libcosmic | COSMIC | `a11y` (accesskit) is on. Unchecked |
| GTK 3 | XFCE | expected. Unchecked |

Related issues: tuna-os/tunaOS#4901 to #4904.

## Mock daemon

The mock lives in tuna-os/fisherman. This spec names the scenarios that it
must offer in `mock_scenarios` of `screens.yaml`. Each has a name and the
screens that it reaches. The list covers the failure states: device lost,
repart error, no TPM, RST present, existing data, cancel and handoff.

## Open questions

- Does the daemon keep an unencrypted choice? The legacy recipe does.
- Where does the EULA file live for a native frontend?
- Which step ids does `Install` stream? The legacy ones are in
  `shared/branding/copy-defaults.json`. SysInstall has its own phases.
- What is the socket path of `io.tunaos.Fisherman`?
- Does `Probe` report the handoff mode, TPM, RST and offline media?
