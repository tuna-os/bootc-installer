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

## 2026-11-10: progress, the recovery key in a log

- Added: `progress/recovery-key-cases.json` and
  `progress/recovery-key-transcript.ndjson`. They pin the redacted form of
  the `recovery_key` event in a log file and in a copy of the log
  (`progress/README.md`, "Recovery key in a log"; #337).
- GNOME and KDE test against them. XFCE keeps a log file and does not yet.
  COSMIC and Niri keep no log file.

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
