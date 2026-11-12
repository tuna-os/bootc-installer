# shared/ changelog

Each change to a contract in `shared/` gets an entry here, newest first.
[README.md](README.md) has the rules ("How a contract changes").

An entry that changes `recipe/fisherman-recipe.schema.json` has a line of
the form `Recipe schema sha256:` with the hash of the file after the change
(`sha256sum shared/recipe/fisherman-recipe.schema.json`). The newest such
line must match the file. `tests/unit/test_shared_contract_docs.py` makes
sure that it does. Do not edit the hash of an old entry: add an entry.

The history before 2026-11-10 comes from `git log`. It has the recipe
schema only.

## 2026-11-12: the receipt event, and installs from the bootc storage of this computer

- Added: the recipe field `sourceReuse` (`store`, `digest`, `platform`)
  and the `experimental` entry `bootc_store_reuse`
  (tuna-os/fisherman#384, #443). With `sourceReuse`, the recipe must also
  have `bootc_store_reuse` in `experimental`, an empty `image` and a
  `targetImgref`.
- Added: `progress/receipt-cases.json`, written by
  `progress/generate-fraction-cases.py`. It pins what a parser keeps of the
  `receipt` event (tuna-os/fisherman#441) and the lines of the done page.
  Its first six cases are fisherman's own events. Each parser reads it
  (#269).
- Added: `progress/outcome-cases.json`. It pins how an install ended. The
  exit code decides, never a `complete` event. GNOME and XFCE call the new
  `bootc_shared.progress.install_outcome()`. KDE, COSMIC and Niri test
  their rule against the file. One case is not in the file: exit code 1 after a
  confirmed cancel. Four frontends call it a cancel, COSMIC a failure.
- Added: `probe/source-reuse-cases.json` and two `frontend-reuse-*`
  inventories in `probe/fixtures/bootc-store/`.
  `probe/generate-source-check-cases.py` writes the case file. The cases
  pin the item that a frontend offers as a second install source. They also
  pin the recipe after the pick. Each frontend reads them (#267).
- Added: copy keys `done_receipt_<state>`, `done_receipt_reason_<reason>`,
  `source_reuse_title`, `source_reuse_download`,
  `source_reuse_download_detail`, `source_reuse_local`,
  `source_reuse_local_detail`, `source_reuse_install_from`, and the 26
  `validate_source_reuse_<code>` lines. Each frontend renders them.
- Changed: `done_verification` says only that nothing checked the new
  system. The receipt line says what the install set up for the check.
- The fisherman pin moved to `cddfa7b` (tuna-os/fisherman#441, #443).

Recipe schema sha256: `da4ed42217d25a9ab9e6402d9ac82827e5fee8d5d5e2eef84940111d8574826a`

## 2026-11-11: probe, the check of the selected image and this computer's bootc storage; completion

- Added: `probe/capabilities-cases.json`, `probe/bootc-store-cases.json`,
  the fixtures in `probe/fixtures/capabilities/` and
  `probe/fixtures/bootc-store/`, and `probe/generate-source-check-cases.py`.
  They hold the readers of the `capabilities` (tuna-os/fisherman#383) and
  `bootc_store` (tuna-os/fisherman#384) objects of `fisherman probe
  --json`. All five frontends use them: GNOME and XFCE through
  `bootc_shared.source_check`, KDE, COSMIC and Niri through a port (#266,
  #267).
- Added: `completion/`, with `verification-cases.json`, its fixtures and
  the readers of a `fisherman verify --json` result
  (tuna-os/fisherman#385). All five frontends have a reader. No page reads
  a result yet (#269).
- Added: copy keys `done_verification`, `source_install_from`,
  `source_update_ref`, `source_live_host`, `source_check_<state>`,
  `source_check_reason_<reason>`, `source_check_default_<name>`,
  `bootc_store_listed` and `bootc_store_kind_<kind>`, and the placeholder
  `{value}`. All five frontends render them.
- The fisherman pin moved to `ae82391` (tuna-os/fisherman#436, #437,
  #438). `tests/unit/test_shared_source_check.py` holds each copied fixture
  to fisherman's golden file.
- Changed: `probe/fixtures/laptop.json` is fisherman's new golden output,
  with `capabilities` and `bootc_store`. `container.json`, `vm.json`,
  `pure-live-oci.json` and the answer of the e2e shim got the two objects
  too: a host without bootc for the container and the shim, the laptop's
  for the two live fixtures. A plain probe selects no source.

## 2026-11-10: fixtures for rules that drifted; one E2E and one capture catalog

- Added: `progress/error-cases.json`. It pins the `error` event: a parser
  keeps the last one as `message`, `code` and `field`, and the bar does not
  move. The Python parser already did this. KDE, COSMIC and Niri now keep
  the event too, and their tests read the file.
- Added: `network/targets.json` and `network/README.md`. They pin the
  network check. They give the targets for an image reference, in order.
  They also give the timeout (5 s) and the two variables that stop the
  check. The five frontends
  had four different rules; the commit message lists each change.
- Added: `probe/fixtures/pci/`. PCI sysfs trees and the NVIDIA answer for
  each. No rule changed.
- Added: `override` in `catalog/fixtures/expected.json`, for
  `FISHERMAN_IMAGES_PATH`. COSMIC reads the variable again. KDE now goes on
  with the search path when the file is missing or broken.
- Added: `e2e/catalog.json`, the one catalog of the five E2E drivers, and
  `walkthrough/capture-catalog.json`, the one catalog of the capture
  harnesses. The capture catalog names no real product.

## 2026-11-10: branding copy, the ZFS label

- Added: `filesystem_zfs_label`, "ZFS (experimental)": the name of ZFS in
  the filesystem picker and on the confirm page. fisherman accepts ZFS
  only with `"experimental": ["zfs"]` in the recipe. GNOME, XFCE, COSMIC
  and Niri show it; KDE offers no ZFS.

## 2026-11-10: branding copy, the validate codes of fisherman `7f9021b`

- Added: `validate_<code>` lines for the new codes of `fisherman validate`:
  `var_disk_encryption_unsupported`, `var_disk_unsupported_composefs`,
  `custom_mount_target_duplicate`, `custom_mount_partition_duplicate`,
  `custom_mount_not_persistable`, `zfs_experimental`,
  `experimental_unsupported`, `locale_invalid`, `keyboard_layout_required`,
  `keyboard_layout_invalid`, `keyboard_variant_invalid`,
  `keyboard_model_invalid`, `timezone_invalid` and
  `kept_filesystem_unusable`. A frontend with no line for a code shows
  fisherman's `message`, as before.

## 2026-11-10: recipe schema, the fields of fisherman `7f9021b`, and closed objects

The fisherman pin moved to `7f9021b` (tuna-os/fisherman#429, #432, #433,
#434, #435). That fisherman refuses a key that it does not know
(`recipe_unknown_field`).

- Added: `extras`, with `printServices`, `oemSetup`, `audioNames` and
  `bootSplash`. A frontend copies the object from the catalog leaf
  (`catalog/README.md`).
- Added: `experimental`, a list that accepts `zfs`. A recipe with
  `filesystem` `zfs` on the automatic layout must have it.
- Added: `locale`, `keyboard` (`layout`, `variant`, `model`) and `timezone`,
  with fisherman's patterns.
- Added: `copyNetworkProfiles`, `copyBluetoothPairings` and `setBootNext`.
  A frontend leaves them out. fisherman then applies its rule for live
  media.
- Changed: each object has `additionalProperties: false`. A recipe that has
  an unknown key was valid before. It is not valid now, because fisherman
  refuses it.
- Changed: the description of `flatpaks`. No key copies the Flatpaks of the
  host. `[]` copies none. A list with entries copies all of them.

Recipe schema sha256: `55a4169f5661764ccdc4e385b561b45328f4f39d3b5ed62b557cbea0dc455245`

## 2026-11-10: data files, COSMIC reads `shared/`; the key out of Niri's log

- Removed: COSMIC's copies of `branding/copy-defaults.json`,
  `recipe/encryption-choices.json` and `account/groups.json`. Its `build.rs`
  takes them from `shared/`. Niri keeps its copies; `go generate ./...`
  refreshes them. No contract changed.
- COSMIC's and Niri's `install.log` and Copy log now follow
  `progress/recovery-key-cases.json`, and their tests read it (#337).

## 2026-11-10: data files, KDE reads `shared/`

- Removed: KDE's copies of `recipe/fisherman-recipe.schema.json` (no code
  read it), `branding/copy-defaults.json`, `recipe/encryption-choices.json`
  and `account/groups.json`. The KDE build compiles the three data files
  in from `shared/`. No contract changed. A schema change no longer has a
  KDE copy to follow.

## 2026-11-10: progress, the recovery key in a log

- Added: `progress/recovery-key-cases.json` and
  `progress/recovery-key-transcript.ndjson`. They pin the redacted form of
  the `recovery_key` event in a log file and in a copy of the log
  (`progress/README.md`, "Recovery key in a log"; #337).
- GNOME and KDE test against them. XFCE, Niri and COSMIC keep a log file
  and do not yet.

## 2026-11-10: GNOME and XFCE share the catalog reader, the fisherman command and the log redaction

- Added: `python/bootc_shared/catalog.py`, `hardware.py`, `network.py`,
  `fisherman_host.py` and `redact.py`, and `logo_source` in `branding.py`.
  GNOME and XFCE had each written this logic; the two use these modules now.
- Added: `catalog/README.md` documents `FISHERMAN_IMAGES_PATH`, the catalog
  file that is tried first. GNOME reads it now. COSMIC does not read it.
- Changed, XFCE: the install log, the log pane and the log tail do not have
  the recovery key (#337). A catalog field of the wrong type gets its
  default. The stage of fisherman refuses a `HOME` that is not the user's
  own.
- Changed, GNOME: the install on live media outside a Flatpak runs
  `sudo -n`, as the other four frontends do. The connection check probes
  the registry of the selected image first. The NVIDIA image of a leaf
  finds that leaf. A path in the install command is quoted with
  `shlex.quote`.
- Changed, both: an empty `VANILLA_SKIP_CONN_CHECK` or
  `TUNA_INSTALLER_SKIP_CONN_CHECK`, or the value `0`, does not turn the
  connection check off. Each frontend reads the two names.

## 2026-11-10: one Python package, `python/bootc_shared`

- Changed: the Python code of five contracts moved to one package.
  `probe/fisherman_probe.py` is now `python/bootc_shared/probe.py`,
  `recipe/fisherman_validate.py` is `validate.py`,
  `progress/progress_parser.py` is `progress.py`, `readiness/readiness.py`
  is `readiness.py`, and `branding/branding.py` is `branding.py`. The
  module `account.py` is new and reads `account/groups.json`.
- Removed: the copies of those files in the GNOME and XFCE trees, and the
  tests that compared the copies. The two frontends import the package.
  `branding.py` reads `branding/copy-defaults.json`, and has no embedded
  copy of it.
- Not changed: the data files, the fixtures and the behaviour. KDE, COSMIC
  and Niri read the same paths as before. Their source comments that name
  `shared/progress/progress_parser.py` now name a file that moved.

## 2026-11-10: recipe schema, `override` and `unifiedStorage`

- Added: `override`, a list that accepts `too_small` and `uefi`. It names
  the target checks that the caller accepts as failed. The fisherman with
  the target checks reads it (tuna-os/fisherman#429). An older fisherman
  ignores it, so no frontend writes it before the pin moves.
- Changed: the description of `unifiedStorage`. fisherman does not pass a
  bootc flag for it, and it refuses `true` (tuna-os/fisherman#366). A
  frontend leaves the field out. The type did not change.

Recipe schema sha256: `4b30f4bb1d4a81ed2ab5ba38725d3f69e2d97e55c4f233075be530c70fe534f5`

## 2026-11-10: this changelog starts

- `README.md` and this file are new. No contract changed.

## 2026-10-15: recipe schema, `distroID` and `brewTap` patterns

- Added: a `pattern` on `distroID` and on `brewTap`. They are fisherman's
  rules (`fisherman/docs/VALIDATE.md`). A recipe that fisherman accepted
  before is still valid.

Recipe schema sha256: `3d552eb5c2af5f4b5579ca24e6d5c48a596d3b05263825c904aaadb9bcde8c89`

## 2026-10-15: recipe schema, fisherman's validation rules

- Changed: `filesystem` accepts `xfs`, `ext4`, `btrfs` and `zfs`. Before,
  it accepted `xfs` and `btrfs`.
- Changed: `hostname` has a maximum length of 64 and takes labels with
  dots between them.
- Added: a `pattern` on `user.username`.
- Changed: the description of `additionalImageStores`. A frontend leaves
  the field out, and fisherman finds the stores on the host.

Recipe schema sha256: `e9e12d22676ba34688c7770bd8e6966cca1689b45962ea85ba3cc30a8fdbed50`

## 2026-10-09: recipe schema moves to `shared/recipe/`

- Added: `recipe/fisherman-recipe.schema.json` as the canonical copy. The
  KDE frontend keeps a byte-identical copy.

Recipe schema sha256: `b39a60bdae9f5e0779fc7e794ef8f36bf90e3696f4495a90382ef5ce646f243c`
