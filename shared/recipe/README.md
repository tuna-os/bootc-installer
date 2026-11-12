# The recipe: schema, validation and encryption choices

Every frontend builds one JSON recipe and gives it to fisherman. fisherman
owns the rules for that recipe. This directory holds what a frontend needs
to write the recipe and to show fisherman's answer about it.

| File | What |
|---|---|
| `fisherman-recipe.schema.json` | The recipe schema. This is the only copy (`tests/unit/test_shared_recipe_schema.py`). |
| `encryption-choices.json` | fisherman's `data/encryption-choices.json`, byte for byte: the encryption types in display order, with `needs_passphrase`, `needs_tpm2` and the branding `copy_key`. |
| `../python/bootc_shared/validate.py` | The Python reader for `fisherman validate --json` and the choices file. GNOME and XFCE import it as `bootc_shared.validate`. |

## From the image catalog to the recipe

`shared/catalog/README.md` has the table of catalog fields that each
frontend must copy into the recipe, the catalog search path and the rule
for the image selected at the start. One default applies everywhere: when
the catalog does not set `needs_user_creation`, the installer creates an
account. `shared/catalog/fixtures/` holds a catalog and the recipe keys that
each frontend must write for each leaf. `shared/account/README.md` has the
groups of that account.

## Give the recipe to fisherman on stdin

A frontend writes no recipe file. It runs fisherman with `-` and writes the
JSON to the wrapper's stdin, then closes stdin:

```sh
bash -c 'pkexec /usr/local/bin/fisherman -; exit $?'
# in a Flatpak:
flatpak-spawn --host bash -c 'pkexec /usr/local/bin/fisherman -; exit $?'
```

`pkexec`, `sudo` and `flatpak-spawn --host` pass stdin through. fisherman
reads to EOF, so the writer must close its end. The recipe can hold the LUKS
passphrase and the user password, so it must not go into a temporary file or
onto the command line.

The cancel contract does not change: start the wrapper in its own process
group and kill that group to cancel. fisherman then exits 130 (see the cancel section of
`fisherman/docs/JSON-PROGRESS-FORMAT.md`).

## Image stores and live media are fisherman's facts

- Leave `additionalImageStores` out. fisherman then exposes the offline
  stores it finds on the host, the same ones `fisherman probe --json` lists
  under `offline.stores`. Write the field only when the ISO's own recipe
  names stores. `[]` turns the discovery off.
- An empty `image` tells fisherman to install the image that the live
  media booted. fisherman rejects it (`image_required`) unless the host
  booted from live media. A frontend reads that from the probe: send an
  empty `image` only when `live.is_live` is true, and show
  `live.live_image` as the image.
- A tag such as "available offline" comes from the probe's
  `offline.images`.

A frontend that looked for these itself ran inside its Flatpak sandbox,
where the host's `/etc` and `/usr` are not visible, so it found nothing.
GNOME also treated every ostree host as live media.
`tests/unit/test_no_frontend_detection.py` fails if a frontend does that
again.

## Validate while the user types

`fisherman validate --json --partial -` checks only the fields that are
present. It reads nothing from the machine and needs no root. Send the page
as a partial recipe on stdin:

```console
$ echo '{"hostname":"-router"}' | fisherman validate --json --partial -
{"protocol_version":1,"valid":false,"errors":[{"field":"hostname","code":"hostname_label_hyphen","message":"…"}]}
```

Show each problem through the copy key `validate_<code>`
(`shared/branding/copy-defaults.json`). Show fisherman's `message` for a
code that has no copy line. If the check cannot run, show nothing and do not
block: the install runs the same rules before it touches a disk. Run the
check off the UI thread, after a short pause in the typing.

The schema, the codes and the rules are in `fisherman/docs/VALIDATE.md`.
The frontend still owns these rules, which are not fisherman's: the user
password is not empty, it matches its confirmation, and how strong it is.

| Frontend | Fields it validates | How |
|---|---|---|
| GNOME | hostname (disk page), username (user page) | `fisherman_validate.LiveCheck` |
| KDE | passphrase (encryption step), username (account step), hostname (confirm step) | `InstallerController::runValidate`, a `QProcess` |
| COSMIC | hostname, passphrase (options page), username (account page) | `validate::check`, on a blocking task |
| Niri | hostname, username, passphrase | the backend's `validate` command, from a QML `Process` |
| XFCE | hostname, username, passphrase | `fisherman_validate.LiveCheck` |

## Encryption choices

Offer the types in the order of `encryption-choices.json`. Offer a
`needs_tpm2` type only when the probe says `tpm.usable`. Show the
passphrase field only for a `needs_passphrase` type. The label is the copy
key `<copy_key>_label`, the description `<copy_key>_description`.

`tests/unit/test_encryption_choices.py` holds the shared copy to the
submodule's file, and each frontend's copy to the shared one.

### GNOME live-media storage adapter

When the image step is absent, the GNOME system recipe may specify canonical
`composeFsBackend` (boolean), `bootloader`, `filesystem`, `imageType`, and
`flatpakVarPath`. These describe the image being installed, independently of
branding. For each field the adapter prefers explicit image-step metadata,
then the top-level system recipe, then matching image-catalog metadata.
An explicit `false` backend flag is preserved. Catalog matching follows nested
inheritance and registry/tag shorthand; unrelated first rows never choose the
backend. Matching uses the selected reference before NVIDIA and local-source
overrides. Empty strings fall through; malformed types and unsupported
filesystem/bootloader names stop recipe generation before fisherman launches.

Root filesystem values are the existing fisherman schema values (`xfs`,
`ext4`, `btrfs`, `zfs`); an image requirement overrides the disk picker and clears
stale btrfs subvolume selection when necessary. Manual mounts are retained.
The adapter does not infer a filesystem from the backend or relax fisherman
validation: for example, composefs plus XFS remains invalid. Sealed images may
use ext4 with either bootc storage backend, as specified by the image producer.
`local_imgref` changes the install source only (including an `oci:/...` source);
`targetImgref` continues to identify the selected update-tracking image.

## Install from the bootc storage of this computer

`sourceReuse` (`store` `bootc`, `digest`, `platform`) tells fisherman to
copy an image that the bootc of this computer keeps, instead of a download
(fisherman `docs/SOURCE-REUSE.md`). It is experimental. A recipe with it
has `bootc_store_reuse` in `experimental`, an empty `image`, and the
catalog's update reference as `targetImgref`, as the schema says. A frontend writes it only when the user picks this computer's
system on the confirm page. It is never the default, and never on live
media. `../probe/README.md` ("Install from the bootc storage of this
computer") says which item qualifies.

## The compliance fixture

`fixtures/compliance.json` holds the choices of a person for each case, and
the one recipe that every frontend must write for them. The image is a leaf
of `../catalog/fixtures/catalog.json`. The other choices are the machine,
the disk, the filesystem, the encryption, the hostname, the account, the
language, the keyboard layout and the time zone. One case has an
account, LUKS and the three region values. One case has an image that
makes its own first user and offers a choice of filesystems.

Each frontend makes the choices with its own recipe code, in its own test:

| Frontend | Test | What it drives |
|---|---|---|
| GNOME | `tests/unit/test_recipe_compliance.py` | the finals of each page, then the `Processor` |
| XFCE | `frontends/xfce/tests/test_recipe_compliance.py` | the real setup page, then `InstallerWindow.build_recipe` |
| KDE | `recipeCompliance` in `frontends/kde/tests/test_backend.cpp` | the setters of `InstallerController`, then `installRecipe()` |
| COSMIC | `frontends/cosmic/src/recipe_compliance.rs` | `Recipe::apply_leaf` and the methods of each page, then `for_fisherman()` |
| Niri | `frontends/niri/installer/compliance_test.go` | `ui/recipe.js` under node, then the Go backend's `install` code |

Two recipes that fisherman reads in the same way can have different bytes.
For example, one frontend writes `"composeFsBackend": false` and a
different one does not write the key. The `normalise` table of the fixture
has two rules:

1. `absent_equals`: remove a key at the path `key` when its value is
   `value`. The type must also be the same, so `0` is not `false`.
2. `absent_without`: remove an object at the path `key` when it has no key
   `needs` after rule 1. An account with no username is no account.

After the two rules, a test writes the keys in sorted order with no spaces,
and compares the bytes with the expected recipe. The expected recipe is
already in that form. `compliance.py` is the reference normaliser.
`tests/unit/test_recipe_compliance.py` also holds the fixture to the
catalog fixture, to `../account/groups.json` and to the schema. It sends
each expected recipe to `fisherman validate --json --partial -` when
`FISHERMAN_BIN` names a binary.

The password of the account is a complete crypt(3) hash. GNOME sends a hash
without a change, and it hashes a password in plain text. The other four
frontends send the password as the person typed it. Thus a password in
plain text gives two recipes, and the fixture does not test that case.

The `Recipe compliance` workflow runs the five tests and the fisherman
check, and its last job fails when one frontend writes a different recipe.
`promote.yml` needs that job. Each frontend's own test job also runs its
test. When you change what a frontend writes, change the fixture in the same
pull request, and make the other four frontends agree.
