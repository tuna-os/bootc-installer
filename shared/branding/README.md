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

## Flavour text, assets and the store

Everything a product might want to say in its own voice is a `copy` key.
The neutral lines are in `copy-defaults.json`; a `branding.json` sets any
subset under `"copy"`, and a key it sets to `""` hides that line wherever a
frontend can hide it. `{name}` is the product name and `{disk}` the disk
about to be erased.

| Key | Where it shows |
|---|---|
| `welcome_title`, `welcome_subtitle` | welcome heading and line under it |
| `welcome_install`, `welcome_install_subtitle`, `welcome_button` | the install row (GNOME) or the forward button |
| `confirm_title`, `confirm_subtitle`, `confirm_body`, `confirm_warning`, `confirm_button` | the last page before the disk is written |
| `progress_title`, `progress_note` | while fisherman runs |
| `recovery_key_title`, `recovery_key_body`, `recovery_key_copy`, `recovery_key_ack` | the recovery-key panel after a TPM enrolment |
| `done_title`, `done_subtitle`, `done_restart`, `done_failed_title` | the done page |
| `store_label` | the store link on the done page, shown only when `store_url` is set |

`confirm_quotes` maps a language tag (`"pt_BR"`) to lines used as the
confirm subtitle in that language. `assets` holds absolute host paths
(`welcome_image`, `complete_image`, `store_qr`); an empty or missing asset
hides or skips the element. `store_url` has no os-release fallback.

The aim is that every key above is rendered by every frontend, so a
product branded once reads the same on GNOME, KDE, COSMIC, Niri and Xfce.
`docs/PARITY.md` is the matrix and it is not all yes yet: the keys a
frontend still hardcodes are listed as `KNOWN_GAPS` in
`tests/unit/test_copy_coverage.py`, which fails both on a gap that is not
listed and on a listed gap that has since been closed. Nothing one desktop
alone can show is in the contract.
What a single frontend renders on top goes under `extensions.<frontend>`
in the branding file, read only by that frontend: today `extensions.gnome`
carries the tour page text, the install video and the credits file. Each
language embeds a byte-identical copy of `copy-defaults.json` (checked by
the identity test), so no frontend needs a data file at runtime. Niri's QML
cannot read a file at all, so its fallback table is generated into
`frontends/niri/ui/installer.qml` by `generate-qml-defaults.py`; run it
after any edit here, alongside the other copies.

`examples/bluefin/` is a complete branding for Bluefin, lifted from what
the GNOME frontend used to hardcode; its README says how a live ISO ships
it.

## Pinning branding for screenshots

A capture resolves branding exactly as the installer does, so an unpinned
capture is branded by the machine that took it. `shared/walkthrough/capture-branding.json`
is the pin, and both GTK capture harnesses point `BOOTC_INSTALLER_BRANDING`
at it (with `setdefault`, so a workflow naming a real product's file wins).

Pin the **whole object**, not `BOOTC_INSTALLER_PRODUCT_NAME`. That variable
covers `name` and nothing else, which is how the committed
`docs/screenshots/01-welcome.png` came to show the Ubuntu logo above
"Welcome to TunaOS" — os-release's `LOGO=ubuntu-logo` was never overridden.
XFCE showed the same fault in text: its heading read "Welcome to Ubuntu
24.04.5 LTS" next to a body reading "installs TunaOS", because only the one
f-string that reads `core.PRODUCT_NAME` had been pinned and every copy key
still came from the host.

`tests/unit/test_shared_branding.py::CaptureBrandingPinTest` resolves the pin
against a deliberately foreign os-release and fails if any host value
survives. Niri needs no env pin — its capture stubs the whole branding object
in `tests/qml-stubs`, which is why its walkthrough was always right.

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
