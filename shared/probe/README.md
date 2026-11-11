# Hardware facts: `fisherman probe --json`

Every frontend gets its disk list, TPM presence and minimum-requirements
check from one command: `fisherman probe --json`. fisherman owns the schema
and the rules: [`fisherman/docs/PROBE.md`](../../fisherman/docs/PROBE.md).
This file says how a frontend runs the command and what it shows.

Before this, each frontend parsed `lsblk` itself. There were five disk
filters, and three frontends offered zram or the live USB as install targets.
Sizes appeared in three different units. Niri never showed the disk model.
Only GNOME checked RAM, CPU and UEFI. The rules are now in fisherman, and a
frontend only shows the result.

## Run it

The probe needs no root, and it writes nothing. Run it as the desktop user.
Do not run it through `pkexec` or `sudo`.

| Frontend | Command |
|---|---|
| GNOME, Flatpak | `flatpak-spawn --host ~/.cache/bootc-installer/fisherman probe --json` (the binary that the install stages) |
| GNOME, host | `/usr/local/bin/fisherman probe --json` |
| KDE, COSMIC, Niri, XFCE | `/usr/local/bin/fisherman probe --json`, prefixed with `flatpak-spawn --host` in a Flatpak |

Each frontend runs the same fisherman binary that it runs for the install.
The probe runs on the host, so `lsblk` sees the host's mounts and the
`boot_disk` rule can find the live USB.

Run the probe one time, when the wizard starts. Use that result for the disk
page, the encryption page and the requirements check. KDE, COSMIC and Niri
run the probe again each time the disk page opens, so they also show a disk
that you connect later.

## What a frontend shows

`fixtures/<name>.expected.json` shows what a frontend must render from `fixtures/<name>.json`:
the disks, `tpm_usable`, `unmet`, `live_image` and `offline_images`.
Each frontend's tests load the fixture through that frontend's own reader,
and must produce the same list.

- **Disks:** show only `eligible: true` disks, in the order that fisherman
  gives. Do not filter, sort or hide more disks. An unknown `excluded_reason`
  means that the disk is not eligible.
- **Name:** use `model`. If `model` is empty, use `path`. Do not use
  `vendor`, because it can be a PCI ID such as `0x1af4`.
- **Size:** use `size_label` exactly as fisherman gives it, for example
  `465.8 GiB`. The unit is binary (1 GiB = 2^30 bytes), and the label says so. Do not format `size_bytes` yourself. GNOME's partition picker shows
  partition sizes, which the probe does not report. For those sizes,
  `format_size` in `fisherman_probe.py` applies the same rule, and a test
  checks it against every label in the fixtures.
- **Bus:** `transport_label` (`NVMe`, `SATA`, `USB`, ...), where the
  frontend has space for it.
- **Removable disks:** offer the `removable: true` disks too. fisherman
  already removes the live USB (`boot_disk`), so a frontend must not hide
  removable disks. Frontends warn before erasing one through the
  `confirm_warning_removable` copy key (#251).
- **No eligible disks:** say so on the disk page. Do not skip the page.
- **Minimum size:** fisherman removes disks smaller than 50 GiB
  (`too_small`). Frontends do not apply a minimum of their own.
- **TPM:** offer the `tpm2-luks` encryption types only when `tpm.usable`
  is true.
- **Live media:** `live.is_live` says whether the host booted from live
  media. Only then may the recipe leave `image` empty, which means "install
  the running image". Show `live.live_image` as that image. fisherman
  rejects an empty `image` on any other host (`image_required`). Do not
  look for live media in the frontend: inside a Flatpak it sees the
  runtime, not the host, and `/run/ostree-booted` is on every installed
  ostree host too.
- **Offline images:** `offline.images` lists the image refs in the host's
  offline stores. Use it for an "available offline" tag. Do not pass
  `offline.stores` in the recipe: when `additionalImageStores` is absent,
  fisherman exposes those stores itself (`shared/recipe/README.md`).
- **Requirements:** `system.unmet` lists `ram`, `cpu` and `uefi` in that
  order. If the list is not empty, show the `requirements_title` copy and one
  `requirements_<id>` line for each item (`shared/branding/copy-defaults.json`).
  GNOME blocks with a separate window for each item, as it did before, and
  `IGNORE_RAM` and `IGNORE_CPU` still override it. The other four frontends
  show a warning on the welcome page and let the user continue.

## Source check

The source check is #266. A second probe asks what the bootc of the
selected image can do: `fisherman probe --json --source <image>`, with
`--target-imgref <targetImgref>` when the recipe has one. On live media
with an empty `image`, the flag is `--live-root`. The answer is the
`capabilities` object of tuna-os/fisherman#383, which
[`fisherman/docs/PROBE.md`](../../fisherman/docs/PROBE.md) specifies.

- The probe gets image references only, never the recipe: the recipe has
  the passphrase. The probe pulls nothing, mounts nothing and needs no
  root. No frontend runs `bootc` itself.
- Each frontend probes again each time the confirm page opens, off the UI
  thread. It drops a reply for an older visit. The reader also drops a
  reply for another source or target (state `stale`).
- The reader gives one of these states. `checking` is the state until a
  reply comes.

| State | When | Install |
|---|---|---|
| `ready` | the bootc of the source answered (`execution_root.established`), and nothing blocks | allowed |
| `blocked` | the recipe asks for a feature that fisherman reports as `unsupported` (today `unifiedStorage`) | held |
| `unsupported` | the probe has no `capabilities` (an older fisherman), or a `version` other than 1 | allowed |
| `unavailable` | the probe failed or its output is malformed, or no root that the probe may run is the source's | allowed |
| `stale` | the reply is for another source or target | dropped |

`unavailable` and `unsupported` are never a green check. They do not hold
Install: fisherman checks the recipe again before it touches a disk. The
partial-field check (`fisherman validate --json --partial`) stays as it
is.

A frontend shows these lines:

- `source_install_from`, `source_update_ref` and `source_live_host`, with
  `{value}`: the source, the reference that the new system follows, and
  the image that this computer runs. They are three different images.
- `source_check_<state>`, and the reason line that the reader names
  (`reason_key`). The reason is `execution_root.reason`, or
  `source.digest_reason` when the digest of the source is not known. A
  code with no copy key gets `source_check_reason_unknown`, never the raw
  code.
- With `ready` and `install_defaults.observed`: one
  `source_check_default_<name>` line for each value that the bootc of the
  image reports (root file system, disk setups, boot loader). The lines are
  facts about the image. They do not change the recipe: the catalog and
  fisherman's rules decide it.

[`capabilities-cases.json`](capabilities-cases.json) holds each case:
the fixture, the request, the arguments of the probe and the expected
view. The fixtures in `fixtures/capabilities/` are fisherman's golden
files (`caps-*.json`), and three files that this repository made
(`frontend-*.json`). `generate-source-check-cases.py` writes the case file
from `bootc_shared.source_check`. Run it after a change to the reader or
a fixture.

## bootc storage of this computer

The bootc storage of this computer is #267. The same probe has the
`bootc_store` object of tuna-os/fisherman#384: the images that the bootc
of **this computer** keeps. They are not the target, and they are not the
source.

- Show the items only when the reader's state is `listed`: the
  `bootc_store_listed` line, then each `ref` with
  `bootc_store_kind_<kind>` (`booted`, `deployed`, `stored`, `listed`).
- Do not offer an item as a source, and do not show it as available
  offline. No fisherman install path reads bootc-owned storage yet
  (fisherman's PROBE.md, "Reuse is not implemented"). The reader marks
  each item `installable: false`.
- Do not select or default to the image that this computer runs because
  it is in the list.
- The reader hides an item with no `ref` (fisherman removed a reference
  that had credentials) and counts it in `hidden`.

[`bootc-store-cases.json`](bootc-store-cases.json) holds the cases. The
fixtures in `fixtures/bootc-store/` are fisherman's golden files
(`store-*.json`) and three `frontend-*.json` files.

## When the probe fails

The probe can fail. For example, an older fisherman that has no probe
command exits non-zero with "unknown command". Or the binary is missing. There is no
fallback disk scan. A frontend shows the reason on the disk page and offers
no disks, so the user cannot install. The frontend hides the TPM choices.
It skips the requirements check and shows no warning.

A fallback scan would mean five `lsblk` parsers again, with five filters and
five size formats. They would run only on the machines where the probe
failed, which are the hardest to debug. The
fisherman that a frontend ships with always has the probe, because the
submodule pin is a revision that has it. A frontend that runs an older
fisherman is packaged incorrectly. The error message says so, and a fallback
would hide it.

## Readers

| Frontend | Reader | Test against the fixtures |
|---|---|---|
| GNOME | `bootc_shared.probe` (`shared/python/`), used by `core/system.py` and `core/disks.py` | `tests/unit/test_probe_frontend.py` |
| XFCE | `bootc_shared.probe` (`shared/python/`), used by `core.py` | `tests/test_probe.py` |
| KDE | `src/probe.{h,cpp}` | `tests/test_backend.cpp` (`probeFixtures`) |
| COSMIC | `src/probe.rs` | `cargo test probe` |
| Niri | `installer/probe.go`, sent to the QML by `discover-disks` and `detect` | `go test -run TestProbe` |

The source check and the bootc storage have one reader in each language.
Each test reads the two case files:

| Frontend | Reader | Test |
|---|---|---|
| GNOME, XFCE | `bootc_shared.source_check` | `tests/unit/test_shared_source_check.py`, `tests/unit/test_confirm_view.py`, XFCE `tests/test_source_check.py` |
| KDE | `src/sourcecheck.{h,cpp}` | `tests/test_backend.cpp` (`sourceCheckCases`, `bootcStoreCases`) |
| COSMIC | `src/source_check.rs` | `cargo test source_check` |
| Niri | `installer/sourcecheck.go`, sent to the QML by `source-check` | `go test -run 'SourceCheck|BootcStore'` |

The Python frontends import one reader,
`shared/python/bootc_shared/probe.py`, and `tests/unit/test_shared_probe.py`
runs it against the fixtures. That test also checks the fixtures against
the Go structs in
`fisherman/fisherman/internal/probe`. It also checks that `laptop.json` is
byte-identical to fisherman's own golden output.

## Fixtures

| File | What it is |
|---|---|
| `laptop.json` | fisherman's golden output (`internal/probe/testdata/golden/probe.json`): a laptop booted from a live USB, with every exclusion rule |
| `container.json` | a real `fisherman probe --json` run in a CI container: no eligible disk, no TPM, BIOS boot |
| `vm.json` | hand-built to the schema: a BIOS VM with one disk that has no model, and every requirement unmet |
| `*.expected.json` | what every frontend renders from the fixture of the same name |

## Test seam

`BOOTC_INSTALLER_FAKE_PROBE=<file>` makes every frontend read probe output
from that file and run no process. The screenshot harnesses use
`fixtures/laptop.json`. The end-to-end job does not use this variable: its
fisherman shim answers `probe --json` itself (`shared/e2e/README.md`).
