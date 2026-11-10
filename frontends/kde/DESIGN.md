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

The seven modules are:

1. `welcome`
2. `disk`
3. `encryption`
4. `account`
5. `confirm`
6. `progress`
7. `done`

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

The wizard keeps its seven modules; the GNOME steps that have no module here
are folded into the existing ones rather than added as new steps:

- The **image catalog** is on the **disk** step. The contract is
  `shared/catalog/README.md`, and `src/imagecatalog.{h,cpp}` reads it. The
  wizard skips the account step when the selected leaf sets
  `needs_user_creation: false`. A leaf without the flag gets `true`. The
  frontend does not download a Flatpak list: for a URL, the recipe has no
  `flatpaks` key and fisherman applies its default. The leaf also gives the
  filesystem and its choices, and the NVIDIA image on a machine with an
  NVIDIA GPU.
- The **hardware gates** live on the **welcome** step: unmet RAM/CPU hold
  Next until an explicit override is ticked (the cpu/ram windows), while a
  non-UEFI boot has no continue path, only power off (the unsupported
  window). The **power off** and **copy install log** actions mirror
  `dialog_poweroff.py` and `dialog_output.py`. **Cancel** on the progress
  step and a window close during an install each ask first. A confirmed
  cancel signals the process group of the wrapper. fisherman stops when its
  parent stops. The done step then shows the cancelled page.
- **Language, keyboard and timezone** are on the **welcome** step. They
  are wizard state, not recipe state: the recipe has no field for them yet
  (#292). Nothing applies them. The welcome step says so, and the confirm
  step does not list them. The **connectivity check** holds Next on the
  welcome step and Install on the confirm step, only when the install needs
  the network. It tries the registry of the selected image first. The
  message has a "Network settings" action that opens the Plasma tool on the
  host.
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

## Visual verification

The screenshot workflow builds the real QML modules with `tests/capture.cpp`,
renders every step offscreen, and checks the resulting pixels for meaningful
content. It also produces `docs/screenshots/walkthrough-kde.json`, the parity
report consumed by the shared installer matrix. See
[`docs/gui-walkthrough.md`](docs/gui-walkthrough.md) for the capture contract,
current screenshots, and safety rationale.
