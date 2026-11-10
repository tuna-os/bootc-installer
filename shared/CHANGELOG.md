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
