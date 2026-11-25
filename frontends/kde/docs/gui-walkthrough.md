# GUI walkthrough

Every image below is rendered in CI from the **real** QML — the same
`src/qml/Wizard.qml` and step modules under `modules/` that the
shipped installer loads. Only `src/main.cpp` is swapped, for
`frontends/kde/tests/capture.cpp`. Nothing about the UI is mocked or redrawn.

The capture runs on the Qt `offscreen` platform plugin with the software
scenegraph, inside a Fedora container that carries the KF6 runtime (Kirigami,
Kirigami Addons, `org.kde.desktop` Qt Quick Controls style). See
[`.github/workflows/screenshots-kde.yml`](../../../.github/workflows/screenshots-kde.yml).

<p align="center">
  <img src="screenshots/walkthrough.gif" alt="The TunaOS KDE installer, step by step" width="720">
</p>

## The steps

| | |
|---|---|
| ![Requirements](screenshots/00-requirements.png) | **Requirements**: only while a gate is unmet. Low memory or too few CPU cores hold Next until you tick Continue anyway. No UEFI offers only Power off. |
| ![Try or install](screenshots/01-tryorinstall.png) | **Try or install**: the first screen. On live media you keep the live session or install. Off live media it shows the welcome copy and one button. |
| ![Language](screenshots/02-language.png) | **Language**: a search field and a list. The pick goes to the installed system. |
| ![Keyboard layout](screenshots/03-keyboard.png) | **Keyboard layout**: a search field and a list of XKB layouts. |
| ![Time zone](screenshots/04-timezone.png) | **Time zone**: a search field and a list. On the daemon backend the page also has the Location services switch. |
| ![Network](screenshots/05-network.png) | **Network**: only when the install needs a download. Next stays off while there is no connection. Network settings opens the Plasma tool. |
| ![Disclaimer](screenshots/06-prerelease.png) | **Disclaimer**: only when os-release calls the product a pre-release or an experiment. It never holds Next. |
| ![Terms of use](screenshots/07-eula.png) | **Terms of use**: the AppStream agreement of `/usr/share/tuna-installer/eula.xml` (`TUNA_EULA_FILE` moves it). No file, no page. Next stays off until you tick the box. |
| ![Intel RST](screenshots/08-rst.png) | **Intel RST**: the daemon reports NVMe disks that the firmware hides. The page warns and continues to the disk list. |
| ![Target disk](screenshots/09-disk.png) | **Target disk**: one radio row for each disk that the backend offers. On the daemon backend a second card lists the disks that are too small. |
| ![Existing data](screenshots/10-wipefree.png) | **Existing data**: the chosen disk holds data. You install to the free space or erase the disk. A disk that cannot keep its data gives one button with a countdown. Daemon backend only. |
| ![Disk encryption](screenshots/11-encryption.png) | **Disk encryption**: the four recipe choices on the recipe backend. On the daemon backend a TPM 2.0 seals the disk and the page does not show. Without one, the page asks for a passphrase twice. |
| ![User account](screenshots/12-account.png) | **User account**: user name, full name and the password twice. The page does not show when the image makes its own user, or when `plasma-setup` is on the live medium. |
| ![Confirm](screenshots/13-confirm.png) | **Confirm**: each choice, never a password, and the one button that starts an install. |
| ![Installing](screenshots/14-install.png) | **Installing**: the progress bar, the step name and the log. Cancel asks first. The wizard moves on only when the backend ends the install. |
| ![Recovery key](screenshots/15-recovery.png) | **Recovery key**: the key as a label, a copy button and the QR button. Done stays off until you tick the box. On the daemon backend Done enrols the key. |
| ![Handoff](screenshots/16-handoff.png) | **Handoff**: daemon backend only. The page words the mode that the daemon reports in Probe: migrate, soft reboot or reboot. Continue calls Handoff with no mode. |
| ![Finished](screenshots/17-done.png) | **Finished**: installed, cancelled or failed, under the branding artwork. |
| ![Cancel question](screenshots/18-cancel-confirm.png) | **Cancel**: the install step asks before it stops an install. The capture clicks Cancel and checks that the question opens. |
| ![Cancelled](screenshots/19-cancelled.png) | **Cancelled**: the done step after a cancel. It offers Try again. |
| ![Failed](screenshots/20-failed.png) | **Failed**: the done step after a failure, with Try again. |
| ![Recovery key QR](screenshots/21-recovery-qr.png) | **QR code**: the recovery key as a QR code in a dialog. |

The number of a frame is the place of its screen in `shared/flow/screens.yaml`. Frames 18 to 21 show a step again in a different state.

## The daemon scenarios

`tuna-installer-capture` can also photograph the screens that a mock scenario changes. Start `fishermand --mock --scenario <name> --socket-dir <dir>`. Then set `TUNA_CAPTURE_SCENARIO=<name>` and `FISHERMAND_SOCKET_DIR=<dir>` and run the capture. It writes `s-<name>-<page>.png` beside the other frames. This run is for a developer. CI does not have the mock daemon and does not do it.

Every step's header shows "Step N of M · name" and one dot per step.

## What the capture checks

Existence checks are not enough. A sibling repository published a blank page
while its "the PNGs exist and are non-empty" assertion passed. So
`frontends/kde/tests/capture.cpp` reads its own pixels back and fails the build when a screen
did not really render:

- **distinct colours** — a screen that never painted collapses to a handful.
- **ink** — the fraction of sampled pixels far enough (Manhattan distance > 40)
  from the image's own dominant colour to be drawn content. Measuring against
  the image's own background rather than a fixed luma keeps this correct under
  a dark colour scheme.
- **row and column spread** — the fraction of sampled rows, and of sampled
  columns, that contain any ink. This is what actually discriminates. Density
  alone does not: the try-or-install and finished steps are hero pages — one icon, a
  heading, a line of prose — and legitimately score around 1% ink, while a form
  step with a FormCard behind it scores 30%. A blank screen scores zero on all
  four.
- **visible step text** — the strings the current step actually put in its item
  tree. Independent of every pixel ratio above, and the one signal that does
  not move with the container's fonts.

Measured on the six real screens at 1000×700 (CI run 33658389834), and the
thresholds sit below these with margin (see the table at the top of `frontends/kde/tests/capture.cpp`):

| step | class | colours | ink | rows | cols |
|---|---|---|---|---|---|
| 01-welcome | hero | 198 | 0.90% | 9.0% | 45.2% |
| 02-disk | card | 280 | 21.97% | 42.7% | 53.9% |
| 03-encryption | card | 217 | 26.86% | 53.8% | 53.9% |
| 04-confirm | card | 207 | 30.12% | 56.8% | 53.9% |
| 05-progress | card | 244 | 15.34% | 100.0% | 100.0% |
| 06-done | hero | 153 | 0.47% | 7.0% | 38.0% |

### Why the row floor is per-class

The spread floors are **per screen class**, and that is the point rather than a
concession. A single global row floor turned out to measure the container
image's font metrics as much as it measured rendering (#57).

When the workflow moved to `fedora:45`, the three card steps did not move at
all, while both hero pages roughly halved — welcome 23.2% → 9.0%, done 15.5% →
7.0% — taking ink and colour count down with them and leaving columns nearly
untouched. That is the signature of a smaller `Kirigami.Units.gridUnit`, which
is derived from font metrics: a hero page sizes its icon, its spacings and its
wrapped prose off it, so the entire column scales with the font. A card step
barely moves, because its row coverage comes from the card background painting
the rect rather than from text. The done page was rendering perfectly and the
check called it blank.

So the two classes are not measuring the same quantity and cannot share a
floor. Splitting them **tightens** the check where it can bite — the card floor
rises from 8% to 20%, against a sparsest measured 42.7% — and only relaxes it
on the class where the number tracked the font. The semantic text assertion
backs both up: a page that drew nothing carries no text whatever the fonts do.

Every run prints these numbers and the class each floor was applied under, so a
drift is visible in the log before it is a mystery. The capture also clears the output directory before rendering: a run
that dies on the first screen must not leave the previous run's images there
for the artifact upload to publish as its own.

The screenshot artifact is uploaded with `if: always()` — it is needed
precisely when the capture fails.

## Why this cannot start an install

The harness drives navigation through `Wizard.goToStep()`, which moves the
visible step and calls the target module's `onPageActivated()`. Four modules have one. The disk step runs the read-only probe again. The network step checks the connection again. The confirm step asks for the plan and the source check, which read and do not write. The wipe-or-free step resets its countdown. `InstallerController.startInstall()` — the sole path to a
privileged `fisherman` process — has exactly one caller, the Install button's
`onClicked` in `Wizard.qml`, which the harness never presses.

Worth stating explicitly: the sibling XFCE installer *does* kick off an install
from its page-enter hook, so "drive the steps" is not automatically harmless
across this family of frontends.
