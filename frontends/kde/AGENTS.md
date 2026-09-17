# AGENTS.md — agent guide for tuna-os/tuna-installer-kde

A **thin Qt 6 / Kirigami wizard** that drives the
[fisherman](https://github.com/tuna-os/fisherman) bootc install backend. The
UI collects choices, writes a recipe JSON, and streams `fisherman`'s output.
All the disk work lives in fisherman — keep it there.

Human docs: [`README.md`](README.md) (build, tests, recipe),
[`DESIGN.md`](DESIGN.md) (architecture and the backend boundary),
[`docs/gui-walkthrough.md`](docs/gui-walkthrough.md) (capture contract),
[`runbooks/`](runbooks/).

## Build and test

```bash
# Fedora deps — Kirigami and Kirigami Addons are QML-only; nothing links KF6,
# they resolve at runtime from the QML import path.
sudo dnf install -y cmake gcc-c++ ninja-build \
    qt6-qtbase-devel qt6-qtdeclarative-devel \
    kf6-kirigami kf6-kirigami-addons kf6-qqc2-desktop-style breeze-icons

cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build
./build/tuna-installer-kde

# Backend unit tests (CTest / QtTest)
cmake -B build -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON
cmake --build build && ctest --test-dir build --output-on-failure

# Offscreen screenshot harness
cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_CAPTURE=ON
cmake --build build && ./build/tuna-installer-capture
```

`biome.json` lints and formats **JSON only** (`**/*.json`) — there is no
JavaScript toolchain here despite appearances.

## The module contract

Each wizard step is a self-contained module at
`modules/<name>/contents/ui/main.qml` whose root is a
`TunaComponents.SetupModule` exposing `nextEnabled` and `contentItem`.
`src/qml/Wizard.qml` drives them with hand-rolled slide animations rather than
a `SwipeView`. `src/components/setupmodule.h` is deliberately a near-copy of
KDE KISS's `SetupModule`, so the shape is upstream's — follow it when adding a
step rather than inventing a new one.

Steps: welcome → disk → encryption → confirm → progress → done.

### QML gotchas already paid for

- **`contentItem` must be a plain `Item`, not a `ScrollView`,** for short
  steps. Inside a `ScrollView` the content item collapses to its implicit
  height, so centring stops centring — the first CI render came out jammed
  against the top with the lower half empty.
- **No hardcoded pixel metrics.** Use `Kirigami.Units` throughout, and
  Kirigami Addons `FormCard` for form layout. No forced Fusion style.

## Backend boundary — treat as a safety rule

`InstallerController` (`src/installercontroller.cpp`) owns recipe state and the
install process. Three rules from [`DESIGN.md`](DESIGN.md) are safety
properties, not preferences:

- **The recipe can contain a LUKS passphrase.** It must never be logged or
  retained; the controller removes the temp recipe when the process exits.
- **The confirmation screen is the destructive-action boundary.** Back
  navigation is disabled once `fisherman` starts.
- **The progress module advances to "finished" only after the process exits** —
  not on a parsed progress line.

The recipe schema is shared with the other frontends
(`fisherman-recipe.schema.json`, and the
[installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md)).
A field added here must exist there too, or the sibling installers diverge.
Encryption types: `none`, `luks-passphrase`, `tpm2-luks`,
`tpm2-luks-passphrase`. On a live ISO `image` may be omitted, and bootc
installs the running container offline.

## Visual verification

`screenshots.yml` builds the real QML modules with `tests/capture.cpp`, renders
every step offscreen, and checks the pixels for meaningful content. It also
emits `docs/screenshots/walkthrough-kde.json`, the parity report the shared
installer matrix consumes — so a UI change that breaks capture breaks the
cross-installer report, not just this repo's screenshots.
