# tuna-installer-kde design

This repository provides a Qt 6 and Kirigami frontend for the `fisherman`
bootc installer. The shared recipe and screen requirements live in the
[installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md).
This document describes how the KDE frontend implements that contract.

## Architecture

`src/qml/Main.qml` creates a `Kirigami.AbstractApplicationWindow` and hosts the
step runner in `src/qml/Wizard.qml`. The wizard follows KDE KISS's modular
pattern: each screen is a `SetupModule` under
`modules/<name>/contents/ui/main.qml`. A module exposes its content and whether
the user may continue; the wizard owns navigation, headings, and the shared
Back and Next buttons.

The eighteen modules have the screen ids of `shared/flow/screens.yaml`, in
its order. The directory drops the dashes where the id has them.

1. `requirements`
2. `try-or-install` (`modules/tryorinstall`)
3. `language`
4. `keyboard`
5. `timezone`
6. `network`
7. `prerelease`
8. `eula`
9. `rst`
10. `disk`
11. `wipe-or-free` (`modules/wipefree`)
12. `encryption`
13. `account`
14. `confirm`
15. `install` (`modules/progress`)
16. `recovery-key` (`modules/recoverykey`)
17. `handoff`
18. `done`

The wizard uses slide transitions between modules instead of `SwipeView`,
matching KISS's behaviour during window resizing. Do not put backend work in a
page-activation hook. Activation may refresh harmless page data, such as the
disk list, but installation starts only when the user selects Install on the
confirmation screen.

## Backend boundary

`InstallerController` exposes recipe state and the installation process to
QML. It writes the selected values to a temporary recipe, launches the
privileged `fisherman` command, streams output to the progress module, and
removes the recipe when the process exits. The recipe can contain a disk
encryption passphrase, so it must not be logged or retained.

The confirmation screen is the destructive-action boundary. Back navigation
is disabled after `fisherman` starts, and the progress module advances to the
finished screen only after the process exits.

## Plasma integration

Use Kirigami, Kirigami Addons, Qt Quick Controls, and `Kirigami.Units` for
layout and sizing. Controls use the Plasma `org.kde.desktop` style and Breeze
theme roles so system colours, fonts, icons, dark mode, and accent preferences
continue to work. Avoid fixed pixel geometry, custom palettes, and application
font overrides.

Use active, direct copy. State the destructive consequence plainly, keep the
Install label exclusive to the confirmation action, and present failures with
the process exit status or actionable backend output.

## Accessibility and interaction

- Preserve a complete keyboard navigation order.
- Never bind Escape or page activation to a destructive action.
- Keep paired passphrase fields and their reveal controls accessible.
- Expose validation before enabling Next or Install.
- Keep focus and warning states visible in both light and dark themes.

## GNOME parity notes

New screens arrive as their own modules with the shared flow's step ids
(try-or-install first); the GNOME steps that still have no module here
are folded into the existing ones rather than added as new steps:

- The **image catalog** is on the **disk** step. The contract is
  `shared/catalog/README.md`, and `src/imagecatalog.{h,cpp}` reads it. The
  wizard skips the account step when the selected leaf sets
  `needs_user_creation: false`. A leaf without the flag gets `true`. The
  frontend does not download a Flatpak list: for a URL, the recipe has no
  `flatpaks` key and fisherman applies its default. The leaf also gives the
  filesystem and its choices, and the NVIDIA image on a machine with an
  NVIDIA GPU.
- The **hardware gates** are the **requirements** step. Unmet RAM or CPU
  holds Next until you tick Continue anyway. A boot without UEFI has only
  Power off. **Cancel** on the install step and a window close during an
  install each ask first.
- **Language, keyboard and time zone** are three steps. Each has a
  `Kirigami.SearchField` over a framed list with a check mark on the
  current row, as the Plasma pickers have. The pick goes to the installed
  system: the recipe carries it, or `ConfigureTarget` on the daemon
  backend. It does not change the live session, so the keyboard step has
  no test field.
- The **network** step shows only when the install needs a download. It
  holds Next while there is no connection. "Network settings" opens the
  Plasma tool on the host.
- The **tour** is the selected leaf's `carousel` slides on the **done**
  screen. Slide titles and descriptions travel; the artwork does not — the
  manifest names GNOME GResource paths (`resource:///...`), which nothing in
  this stack can resolve.
- The **phone companion** (QR + LAN form server) is deliberately not
  implemented: it is a TLS-terminating network service, a new privileged
  surface that belongs in a follow-up spec, not in a parity pass. When it
  lands, render the QR in QML (a small byte-mode encoder over the session
  URL) rather than adding a `python3-segno` equivalent to the Flatpak
  manifest — this stack has no Python, and a new runtime dependency for one
  code is the wrong trade. No manifest change was needed for any of this.

## The daemon backend

`TUNA_INSTALLER_BACKEND=daemon` (or `auto` with the daemon socket there)
moves the backend boundary to `fishermand` over Varlink. The safety rules
stay:

- Only the Install button of the confirm step sends `Install`, with
  `confirmed: true`.
- The wizard leaves the install step on the terminal reply of the stream.
- Secrets go in call parameters. The client logs no parameters.

Three pages follow the daemon and not a choice of this frontend:

- **Encryption.** A usable TPM 2.0 seals the disk, and the step does not
  show. Without one the step asks for a passphrase twice.
- **Existing data.** `fit` of `io.systemd.SysInstall` decides: a free-space
  install, a choice, or a forced erase with a countdown.
- **Handoff.** The daemon reports the mode in `Probe`. The page words it
  and calls `Handoff` with no mode.

`plasma-setup` owns the first user where its unit is enabled on the
medium. The account step then does not show, and the confirm and handoff
steps say who asks. A masked unit does not count: the image then expects
the installer to make the user.

## Visual verification

The screenshot workflow builds the real QML modules with `frontends/kde/tests/capture.cpp`,
renders every step offscreen, and checks the resulting pixels for meaningful
content. It also produces `frontends/kde/docs/screenshots/walkthrough-kde.json`, the parity
report consumed by the shared installer matrix. See
[`docs/gui-walkthrough.md`](docs/gui-walkthrough.md) for the capture contract,
current screenshots, and safety rationale.
