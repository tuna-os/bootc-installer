# AGENTS.md — agent guide for frontends/kde (formerly tuna-os/tuna-installer-kde)

> **Monorepo note.** This directory is one of five frontends in
> `tuna-os/bootc-installer`. Every path below is relative to THIS directory.
> Workflows referenced as `screenshots.yml` / `publish-flatpak.yml` / `ci.yml`
> are now `.github/workflows/screenshots-kde.yml`, `publish-flatpak.yml` (`frontend: kde`)
> (plus `ci-niri.yml` for the niri Go backend) at the repository root, running with
> `working-directory: frontends/kde`. The shared recipe schema and screen
> contract live in `../../shared/`. Do not add a `.github/` here.

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

CMake compiles three data files in from `../../shared/`:
`branding/copy-defaults.json`, `recipe/encryption-choices.json` and
`account/groups.json`. This tree has no copy of them. A build without the
monorepo around it sets `-DTUNA_SHARED_DIR=<path to shared/>`. The Flatpak
manifest does that: it has `shared/` as a second source.

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

Steps: welcome → disk → encryption → account → confirm → progress → done.
The disk step shows the image catalog when a manifest is there and the host
is not live media. `../../shared/catalog/README.md` is the contract for the
catalog: the search path, the fields that go into the recipe, the image
selected at the start and the row labels. `src/imagecatalog.{h,cpp}` reads
it, and `test_backend` holds it to `shared/catalog/fixtures`. A leaf also
gives the filesystem choices: the disk step shows a picker when there is
more than one. The account step writes the recipe's `user` block. Its groups
are `../../shared/account/groups.json`, which CMake compiles in, or
`user.groups` of
`/etc/bootc-installer/recipe.json`. The account is necessary unless the
image creates its own first user (`needs_user_creation: false`). The wizard
then skips the step and the recipe has no block. The welcome step also has
the hardware gates, the region and language pickers and the connectivity
check. The pickers go into the recipe as `locale`, `keyboard.layout` and
`timezone` (#292), the live check sends them to `fisherman validate`, and the
confirm step lists them.

## How fisherman runs

`src/fisherman.{h,cpp}` is the one resolver. No other file names the binary.
A native run uses `/usr/local/bin/fisherman`: `pkexec` for the install, and
`sudo -n` only on live media. In a Flatpak, the resolver copies
`/app/bin/fisherman` to `$XDG_CACHE_HOME/bootc-installer/fisherman`. The
host then computes the SHA256 of the copy. Probe, validate and install use
the copy only when the two hashes are equal. Do not use `HOME/.cache`.

The progress step has a Cancel button. It asks first. A confirmed cancel
sends SIGTERM to the process group of the wrapper, then SIGKILL after five
seconds. Exit code 130, or a signal after a cancel, shows the cancelled
page (`done_cancelled_title`), not the failure page. Another exit code
after a cancel is a failure.

## Strings

Put each string that a person reads in `qsTr()` (QML) or `tr()` (C++).
`test_backend` (`qmlStringsGoThroughQsTr`) fails on a bare literal in a
text, label or title property. The template is `i18n/tuna-installer-kde.ts`.
After you change a marked string, run
`python3 ../../shared/i18n/templates.py kde` from this directory and commit
the template. Then run `python3 ../../shared/i18n/catalogs.py fr kde` to
update the French catalog `i18n/tuna-installer-kde_fr.ts`. CMake compiles
each catalog to a `.qm` file (`TUNA_TRANSLATIONS`, on by default; it needs
Qt Linguist Tools), and `src/translations.cpp` loads the file for the
locale. `test_backend` (`shippedCatalogLoadsAndTranslates`) loads the
catalog that the build compiled. See `../../shared/i18n/README.md`.

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

- **The recipe can contain a LUKS passphrase.** It must never be logged,
  retained or written to a file. The controller runs `fisherman -` and
  writes the JSON to the process's stdin, then closes it
  (`../../shared/recipe/README.md`).
- **The confirmation screen is the destructive-action boundary.** Back
  navigation is disabled once `fisherman` starts.
- **The progress module advances to "finished" only after the process exits** —
  not on a parsed progress line.
- **The recovery key stays out of the log file and the clipboard copy.**
  `appendLine` writes the redacted form of a `recovery_key` event
  (`src/redact.{h,cpp}`, `../../shared/progress/recovery-key-cases.json`).
  The key is in memory for the done page and its acknowledgement.

The recipe schema is shared with the other frontends
(`../../shared/recipe/fisherman-recipe.schema.json`, and the
[installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md)).
A field added here must exist there too, or the sibling installers diverge.
Encryption types come from `../../shared/recipe/encryption-choices.json`
(fisherman's file), which CMake compiles into `recipe.cpp`; branch on
`Recipe::needsPassphrase()` / `needsTpm2()`, never on the type's name. On
live media (the probe's `live.is_live`, `InstallerController.isLive`)
`image` is left out and fisherman installs the running system. Never fill
`additionalImageStores`: fisherman exposes the host's offline stores.

## Validation is fisherman's

The hostname, username, filesystem and encryption rules are `fisherman
validate --json --partial -` (`src/validate.{h,cpp}`). The controller
sends those fields on stdin 300 ms after a change (the username, never
the user's password) and exposes `hostnameProblem`, `encryptionProblem`
and `usernameProblem`, worded by the copy key `validate_<code>`. The
encryption and account steps show their problem and hold Next on it; the
confirm step shows the hostname's. Only the passphrase and password
confirmations (and requiring an account) are rules of this frontend. Do not add a rule of your own to `Recipe::validationError()`.

## Disks, TPM and minimum requirements

These come from `fisherman probe --json`, not from this frontend. `src/probe.cpp`
runs `fisherman probe --json` without privileges, through the resolver in
`src/fisherman.h`. `InstallerController` reads TPM and the
requirements from it at startup. `DiskModel` runs the probe again each time the
disk step opens. Show the eligible disks in fisherman's order, with
`size_label` exactly as given. Do not add a disk filter or a size formatter. If
the probe fails, the disk step shows the reason. `test_backend`
(`probeFixtures`) renders the shared fixtures, and
`../../shared/probe/README.md` is the contract. The capture sets
`BOOTC_INSTALLER_FAKE_PROBE` to `shared/probe/fixtures/laptop.json`.

The confirm step also asks fisherman about the selected image (#266):
`InstallerController::checkSource()` runs `fisherman probe --json --source`
off the UI thread, and `src/sourcecheck.{h,cpp}` reads its `capabilities`
and `bootc_store` (#267). The step shows `sourceRows`. Only a blocked source
holds Install. A reply for an older visit, or for another source, is
dropped.

The confirm step offers the system that this computer runs as a second
install source (#267): `refreshReuse()` reads the plain probe through
`sourcecheck::reuseSource()`, never on live media and never as the
default. `installRecipe()` is what the install and the source check get:
the wizard's recipe, with `sourceReuse` when the user picked the copy.
fisherman checks the pick (`reuseProblem`, `validate_source_reuse_<code>`),
and a copy needs no network. The done step says "installed, restart
required" and never "verified": `receiptLines` is `done_verification` and
the line for fisherman's `receipt` event (#269). `test_backend`
(`sourceCheckCases`, `bootcStoreCases`, `verificationCases`,
`sourceReuseCases`, `progressReproducesTheSharedReceiptCases`) reads the
shared case files.

The confirm step also shows fisherman's install plan (tuna-os/fisherman#371):
`requestPlan()` runs `fisherman plan --json -` without privileges, the
recipe on stdin, with a timeout. `src/plan.{h,cpp}` is a port of
`../../shared/python/bootc_shared/plan.py`: `planRows` in the
`confirm_plan_*` copy keys, and `confirmedRecipe()` (what Install writes)
binds `diskIdentity` only when the plan is for the recipe's disk, and
`planBinding` (the plan's `binding`) unless the plan is for another disk.
No plan, no binding. `test_backend` (`plan*`) reads fisherman's golden plans.

The progress step shows fisherman's `source_reuse` events for a copy of
this computer's system (`reuseLines`, `sourcecheck::sourceReuseLines`,
#267). The copy does not move the bar. While `copyCancel` is true, the
cancel dialog says `progress_reuse_cancel`: the disk does not change.
`test_backend` reads `../../shared/progress/source-reuse-cases.json`.
After a confirmed cancel, only exit code 130 or a signal is a cancel
(`outcomeOf`).

## Visual verification

`screenshots.yml` builds the real QML modules with `tests/capture.cpp`, renders
every step offscreen, and checks the pixels for meaningful content. It also
writes `texts.json` (the item text of each step) and `audit.json` (its pixel
verdict). The workflow then runs `../../shared/walkthrough/report_from_pngs.py`,
which writes `docs/screenshots/walkthrough-kde.json`, the parity report the
shared installer matrix consumes. A UI change that breaks capture thus breaks
the cross-installer report, not only the screenshots of this tree.

## Branding

Nothing in this tree names a product. `src/branding.{h,cpp}` (`InstallerController` reads it once at startup) resolves the product name,
the recipe's `distroID`, the hostname seed and the default image from a `branding.json`
under `/etc/bootc-installer/` (host first), then `os-release`, then a
neutral "Linux"; the contract and the fixtures it is tested against are in
`shared/branding/` at the monorepo root. `BOOTC_INSTALLER_BRANDING` points
tests at a file, `BOOTC_INSTALLER_PRODUCT_NAME` overrides the name for the
screenshot harness.
Flavour text (welcome, confirm, progress and done lines, the Install button)
is branding copy too: every rebrandable line is a key of
`shared/branding/copy-defaults.json`, read through the same resolver, and
`docs/PARITY.md` records which keys this frontend renders. Add a new
user-facing line the product might want to own as a copy key, not a
literal.
