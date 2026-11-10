# AGENTS.md — agent guide for frontends/xfce (formerly tuna-os/tuna-installer-xfce)

> **Monorepo note.** This directory is one of five frontends in
> `tuna-os/bootc-installer`. Every path below is relative to THIS directory.
> Workflows referenced as `screenshots.yml` / `publish-flatpak.yml` / `ci.yml`
> are now `.github/workflows/screenshots-xfce.yml`, `publish-flatpak.yml` (`frontend: xfce`)
> (plus `ci-niri.yml` for the niri Go backend) at the repository root, running with
> `working-directory: frontends/xfce`. The shared recipe schema and screen
> contract live in `../../shared/`. Do not add a `.github/` here.

A **GTK3 / PyGObject wizard** that drives the
[fisherman](https://github.com/tuna-os/fisherman) bootc install backend.
Deliberately the plainest of the TunaOS installer frontends: no libadwaita, it
follows the system GTK theme, and per [`DESIGN.md`](DESIGN.md) the trawl line is
the entire brand budget.

Human docs: [`README.md`](README.md) (flow, offline behaviour, Flatpak),
[`DESIGN.md`](DESIGN.md), [`docs/gui-walkthrough.md`](docs/gui-walkthrough.md).

## Layout

| Path | Lines | What |
|---|---|---|
| `tuna_installer_xfce/app.py` | ~560 | the window, navigation, the install process and its cancel |
| `tuna_installer_xfce/pages.py` | ~1050 | the eight pages |
| `tuna_installer_xfce/core.py` | ~900 | catalog, recipe construction, fisherman invocation, the probe's live and offline facts |
| `tuna_installer_xfce/gates.py` | ~300 | requirement gates and dialogs |
| `tuna_installer_xfce/i18n.py` | ~50 | gettext: the `_()` that each string goes through |
| `tuna_installer_xfce/trawlline.py` | ~70 | the one piece of brand |
| `tests/gui/` | | `capture-screens.py` (imports `../../shared/walkthrough/`) |

```bash
sudo dnf install -y python3-gobject gtk3   # Fedora
./tuna-installer-xfce
```

`core.py` is the part worth reading first — it is where the recipe is decided,
and it is GTK-free enough to reason about without a display.

## How it invokes fisherman: one resolver

`core.fisherman_command(purpose)` is the only place that builds a fisherman
command, for `probe`, `validate` and `install`. It calls
`bootc_shared.fisherman_host.command`, which GNOME also uses, so the two
frontends cannot differ. `tests/test_core.py` holds the argv for each case,
and fails when another module names the binary.

- **Outside Flatpak:** `/usr/local/bin/fisherman` for the probe and the
  checks. The install is `bash -c 'pkexec /usr/local/bin/fisherman -; exit
  $?'`. On live media (`live.is_live` of the probe) it is `sudo -n` in place
  of `pkexec`.
- **Inside Flatpak:** `core.stage_fisherman()` copies the bundled
  `/app/bin/fisherman` to `$XDG_CACHE_HOME/bootc-installer/fisherman` and
  compares its SHA256 with `flatpak-spawn --host sha256sum`. All three
  purposes then run that copy through `flatpak-spawn --host`. Do not make the
  path from `HOME/.cache`. The stage step also refuses a `HOME` that is a
  symlink or that a different user owns. If the stage step fails, nothing
  runs: the destination page and the result page give the reason.

The install runs in a bash that this frontend owns, in its own process group
(`app.spawn_fisherman`). fisherman cancels when its parent dies, so a cancel
signals that group.

The recipe goes to fisherman on stdin: `spawn_fisherman` writes the JSON and
closes the pipe. Nothing writes it to a file.

fisherman's output goes to `~/.local/state/tuna-installer/install.log`
through `core.open_install_log()`. That object removes the recovery key
from each line (`bootc_shared.redact`, #337). The log pane and the tail on
the result page do not show the key. Only the recovery-key panel of the
done page shows it. Do not add a second writer of fisherman's output:
`tests/test_recovery_key_log.py` sends the shared transcript through the
real output handler and fails when the key is in the file.

You can test the Flatpak path only from a built Flatpak:

```bash
flatpak-builder --user --install --force-clean build \
  flatpak/org.tunaos.InstallerXfce.json
flatpak run org.tunaos.InstallerXfce
```

Runtime is `org.gnome.Platform` (it ships GTK3 + PyGObject).

## Image catalog and account

`core.load_catalog()` follows `shared/catalog/README.md`: the search path
(with `/run/host/etc` in a Flatpak), the fields that reach the recipe, the
NVIDIA rule, the offline Flatpak-list rule, and the selection at the start.
The reader is `bootc_shared.catalog`, which GNOME also uses; `core.Catalog`
and `core.ImageLeaf` are the view of it that the pages read.
`tests/unit/test_shared_python_catalog.py` at the repository root holds the
reader to `shared/catalog/fixtures/`, and `tests/test_catalog_contract.py`
holds the recipe that this frontend writes for each leaf. Do not read `fallback_flatpaks`, do not download a list, and do
not select the first row.

`core.DEFAULT_GROUPS` is the list in `shared/account/groups.json`, read
through `bootc_shared.account`. `tests/test_account.py` fails when the two
differ.

## The shared Python package

`bootc_shared` (`../../shared/python/`) has the code that this frontend
shares with GNOME: `probe`, `validate`, `progress`, `readiness`, `branding`
and `account`, and also `catalog`, `hardware`, `network`, `fisherman_host`
and `redact`. Import it; do not copy a module into this tree. In a
checkout, `tuna_installer_xfce/__init__.py` puts `shared/python` on the
path. The Flatpak manifest copies the package, and the data files that it
reads, to `/app/lib/tuna-installer-xfce/bootc_shared/`. When a module reads
a new data file, add the file to `bootc_shared/_data.py` and to the
manifest; `tests/unit/test_shared_python_package.py` at the repository root
fails when the two differ.

## Cancel, autoinstall and strings

- The progress page has a Cancel button. It asks first
  (`gates.ConfirmCancelDialog`). Exit code 130, or the death of the wrapper
  after a confirmed cancel, shows the cancelled page (`done_cancelled_title`).
- `--autoinstall` runs `fisherman validate --json -` on the whole recipe
  before it starts (`core.recipe_problems`).
- Each user-facing literal goes through `_()` from
  `tuna_installer_xfce/i18n.py`. `tests/test_i18n.py` fails on a bare
  literal. Do not use `_` as a parameter or variable name in those modules.
- The keyboard combo applies to the live session only. The recipe has no
  locale field yet, so do not add a control that only stores a value.

## Disks, TPM and minimum requirements

These come from `fisherman probe --json`, not from this frontend. `core.probe()`
runs it one time, without privileges, as `/usr/local/bin/fisherman probe --json`
(prefixed with `flatpak-spawn --host` in a Flatpak). It reads the answer through
`bootc_shared.probe`. Show the eligible disks in fisherman's order,
with `size_label` exactly as given. Do not add a disk filter or a size
formatter. If the probe fails, the destination page shows the reason and
offers no disk. `tests/test_probe.py` renders the shared fixtures, and
`../../shared/probe/README.md` is the contract. A capture sets
`BOOTC_INSTALLER_FAKE_PROBE` to a fixture file.

## Offline and live-ISO installs

Live media and the offline images are fisherman's facts: `core.is_live()`,
`core.live_image()` and `core.offline_images()` read the probe's `live` and
`offline` sections. On live media an **empty `image` means "install the
running system"**, which fisherman accepts only there. The recipe never
carries `additionalImageStores`: fisherman exposes the host's offline
stores itself. Do not look for either in this frontend; inside a Flatpak it
sees the runtime's `/etc` and `/usr`, not the host's
(`tests/unit/test_no_frontend_detection.py`).

## Validation is fisherman's

The identity page sends the hostname and username, and the encryption page
the encryption choice, passphrase and filesystem, to
`fisherman validate --json --partial -` (`LiveCheck` of `bootc_shared.validate`). A problem
shows under the field, worded by the copy key `validate_<code>`, and holds
Next. The password (not empty, typed the same two times) and the
passphrase confirmation are this frontend's rules. Encryption choices come from `encryption-choices.json`; branch on
`core.needs_passphrase()` / `core.needs_tpm2()`, never on the type's name.

## Visual verification

`screenshots.yml` renders every screen headlessly from the real wizard and
emits the parity report the shared installer matrix consumes, so a UI change
that breaks capture breaks that cross-installer report too. `tests/test_core.py`
and `tests/test_readiness.py` are real GTK-free unit tests; the screenshot job
runs the whole `tests/` suite under `xvfb-run` before it captures.

The capture waits for GTK to paint each page (the frame clock's
`after-paint`, then an X sync) before grabbing it, with theme animations
off. Do not go back to "drain until no events are pending": GTK3 paints on
a timed source, so the grab then read the previous page, and CI committed
three pairs of identical frames that the widget-tree text still credited.
A frame that is pixel-identical to the one before it fails the job.

Navigation: Back is hidden on welcome, progress and done; the Back/Next bar
is hidden on progress and done. The progress page carries its own Cancel,
and the done page carries its own Close and
Restart now (`done_restart`), Restart held until a recovery key is
acknowledged (`tests/test_navigation.py`).

## Sibling contract

Recipe JSON and screen sequence are shared with `tuna-installer-kde`, `-niri`
and `-cosmic` through the
[installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md).
A field added here must exist there too. All real disk work belongs in
fisherman — keep it there.

## Branding

Nothing in this tree names a product. `bootc_shared.branding`, the shared resolver that `core.BRANDING` exposes, resolves the product name,
the recipe's `distroID`, the hostname seed from a `branding.json`
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
