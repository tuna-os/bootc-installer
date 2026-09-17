# AGENTS.md — agent guide for tuna-os/tuna-installer-xfce

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
| `tuna_installer_xfce/app.py` | ~557 | the wizard: screens, navigation, GTK wiring |
| `tuna_installer_xfce/core.py` | ~244 | recipe construction, offline/live-ISO detection |
| `tuna_installer_xfce/trawlline.py` | ~70 | the one piece of brand |
| `tests/gui/` | | `capture-screens.py`, `parity_report.py` |

```bash
sudo dnf install -y python3-gobject gtk3   # Fedora
./tuna-installer-xfce
```

`core.py` is the part worth reading first — it is where the recipe is decided,
and it is GTK-free enough to reason about without a display.

## How it invokes fisherman — two different paths

This trips people up because it works one way in development and another when
packaged:

- **Outside Flatpak:** `sudo /usr/local/bin/fisherman`
- **Inside Flatpak:** `pkexec /app/bin/fisherman`, which requires the polkit
  action `org.tunaos.Installer.install` to be installed **on the host** by the
  ISO build — not by this repo.

A change to how the backend is launched has to work in both, and the Flatpak
path can only really be exercised from a built Flatpak:

```bash
flatpak-builder --user --install --force-clean build \
  flatpak/org.tunaos.InstallerXfce.json
flatpak run org.tunaos.InstallerXfce
```

Runtime is `org.gnome.Platform` (it ships GTK3 + PyGObject).

## Offline and live-ISO installs

`core.py` detects live-ISO mode via `bootc status`; an **empty `image` in the
recipe means "install the running system"**, which is the offline path and not
a missing value. It probes embedded OCI stores in this order:

1. `/etc/tuna-installer/offline-stores`
2. `$TUNA_OFFLINE_STORES`
3. `/usr/share/tuna-installer/oci-store`

and passes what it finds as `additionalImageStores`. If you change that
probing, remember the live ISO has no network — a fallback that reaches for a
registry is a broken install, not a slow one.

## Visual verification

`screenshots.yml` renders every screen headlessly from the real wizard and
emits the parity report the shared installer matrix consumes, so a UI change
that breaks capture breaks that cross-installer report too. `tests/test_core.py`
and `tests/test_readiness.py` are real GTK-free unit tests (`pytest tests/`)
but are not run in CI — the screenshot job is the only automated gate.

## Sibling contract

Recipe JSON and screen sequence are shared with `tuna-installer-kde`, `-niri`
and `-cosmic` through the
[installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md).
A field added here must exist there too. All real disk work belongs in
fisherman — keep it there.
