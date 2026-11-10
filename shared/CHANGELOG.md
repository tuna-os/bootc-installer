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
