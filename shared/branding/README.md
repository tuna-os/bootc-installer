# Branding contract

Every frontend shows a product name, seeds a hostname, writes a `distroID`
into the fisherman recipe and links to a website. None of that may be
hardcoded to a product. Each frontend resolves it the same way, in this
order, per key:

1. **A branding file**, `branding.json`. The first readable one wins, no
   merging across files:
   - the path in `$BOOTC_INSTALLER_BRANDING` (tests and screenshot harnesses);
   - `/run/host/etc/bootc-installer/branding.json`
   - `/run/host/usr/share/bootc-installer/branding.json`
   - `/etc/bootc-installer/branding.json`
   - `/usr/share/bootc-installer/branding.json`

   Host paths come first because every frontend ships as a Flatpak, where
   `/etc` is the runtime's. A live-ISO builder that wants to name the
   product, pick the default image or point at its own docs drops one file
   under `/etc/bootc-installer/`.
2. **`os-release`**, for every key the file does not set: the first readable
   of `/run/host/etc/os-release`, `/run/host/usr/lib/os-release`,
   `/etc/os-release`, `/usr/lib/os-release`.
3. **Neutral defaults**, never a product name.

`$BOOTC_INSTALLER_PRODUCT_NAME`, when set and non-empty, overrides `name`
only. The screenshot workflows use it so the committed walkthrough does not
read "Install Ubuntu 24.04 LTS" from the runner's os-release.

## Keys

| Key | `branding.json` | `os-release` fallback | neutral default |
|---|---|---|---|
| `name` | `name` | `PRETTY_NAME`, else `NAME` | `Linux` |
| `id` | `id` | `ID` | `linux` |
| `vendor` | `vendor` | `VENDOR_NAME`, else `NAME` | `""` |
| `home_url` | `home_url` | `HOME_URL` | `""` |
| `docs_url` | `docs_url` | `DOCUMENTATION_URL` | `""` |
| `support_url` | `support_url` | `SUPPORT_URL` | `""` |
| `logo` | `logo` (icon name or path) | `LOGO` | `""` |
| `default_hostname` | `default_hostname` | `DEFAULT_HOSTNAME`, else `ID` | `linux` |
| `default_image` | `default_image` (OCI reference) | none | `""` |

Values are strings; an empty or missing value in the file falls through to
the next source. Unknown keys are ignored, so a file may carry
frontend-specific extras. `shared/branding/branding.schema.json` is the
schema.

What each frontend does with them:

- `name`: every title and sentence that names the product ("Install
  {name}", "{name} is installed", window title).
- `id`: the recipe's `distroID`.
- `default_hostname`: the hostname field's initial value (GNOME derives a
  hardware name and uses this only as the fallback stem).
- `default_image`: the image installed when the frontend offers no catalog
  choice and the system is not a live ISO (Niri, COSMIC). Empty means the
  frontend must have another source or refuse to install.
- `home_url`, `docs_url`, `support_url`, `vendor`: about dialogs and help
  rows; a row whose URL is empty is hidden.
- `logo`: welcome and done page artwork; a themed icon name or an absolute
  path.

## Implementations

One per language, each reading the same fixtures under `fixtures/`:

| Frontend | Resolver | Test |
|---|---|---|
| GNOME | `bootc_installer/utils/branding.py` (byte-identical copy of `branding.py`) | `tests/unit/test_shared_branding.py` |
| XFCE | `frontends/xfce/tuna_installer_xfce/branding.py` (byte-identical copy) | `frontends/xfce/tests/test_branding.py` |
| Niri | `frontends/niri/installer/branding.go` | `frontends/niri/installer/branding_test.go` |
| KDE | `frontends/kde/src/branding.{h,cpp}` | `frontends/kde/tests/test_backend.cpp` |
| COSMIC | `frontends/cosmic/src/branding.rs` | its `#[cfg(test)]` module |

`fixtures/expected.json` lists the outcome for three cases: file plus
os-release, os-release only, nothing readable. A resolver that disagrees
with it is wrong, whichever language it is in.
