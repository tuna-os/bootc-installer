# The image catalog: one reader for five frontends

A catalog (`images.json`) is a tree of images that a user can install. Each
frontend reads the same catalog and must write the same recipe for the same
leaf. This directory holds the contract, a fixture and a reference resolver.

| File | What |
|---|---|
| `fixtures/catalog.json` | A small catalog that uses each rule on this page. |
| `fixtures/expected.json` | The answers for that catalog: the search paths, the default selection, each resolved leaf and the recipe keys for it. |
| `resolve.py` | The reference resolver, in plain Python with no network. It writes `expected.json`. |

`tests/unit/test_shared_catalog.py` holds `expected.json` to `resolve.py`,
and reads fisherman's bundled catalog with the same code. Each frontend has
a test in its own language that reads the two fixture files. A frontend
does not import `resolve.py`.

## Where the catalog is

Try these files in order. Use the first file that is a JSON object with an
`images` list. A file that is missing or that does not parse does not stop
the search.

| Order | Path | Who writes it |
|---|---|---|
| 1 | `<etc>/bootc-installer/images.json` | the ISO or the operator |
| 2 | `<etc>/tuna-installer/images.json` | the legacy name of the same file |
| 3 | `$XDG_CONFIG_HOME/bootc-installer/images.json` | a developer, for a test |
| 4 | the catalog in the package | the frontend build (`fisherman/data/images.json`) |

`<etc>` is `/etc` in a native run. In a Flatpak (`/.flatpak-info` is
there) it is `/run/host/etc`: the sandbox has its own `/etc`, and the
manifests give `--filesystem=host`, which puts the host's files below
`/run/host`. When `XDG_CONFIG_HOME` is empty, use `$HOME/.config`.

The system file is first because an ISO that ships a catalog must get that
catalog. A file in a home directory must not replace it.

### The override for a test or an operator

When the environment variable `FISHERMAN_IMAGES_PATH` names a file, try that
file before path 1. The other rules do not change: when the file is missing
or is not a catalog, the search continues with path 1. A capture harness and
an end-to-end driver set the variable, so that a test does not read the
catalog of the machine. An operator can set it to try a catalog with no
change to `/etc`. The variable is not a product setting: an ISO ships its
catalog at path 1.

All five frontends read the variable: the Python reader
(`shared/python/bootc_shared/catalog.py`, for GNOME and XFCE), KDE, Niri
and COSMIC. `fixtures/expected.json` has the cases in `override`, and the
catalog test of each frontend runs them.

The Python frontends have one reader, `bootc_shared.catalog`.
`tests/unit/test_shared_python_catalog.py` runs it against `fixtures/`.

## Leaves and inheritance

A node is a leaf when it has `imgref`, or when it has `tag` and a `registry`
is in scope. The image reference of a tag leaf is `<registry>:<tag>`. Any
other node is a group, and its `children` are nodes.

A leaf takes each field in the table from the nearest node that sets it:
the leaf first, then its parent, then that parent's parent. A value of
`false`, `""` or `[]` is a value and stops the search.

## Fields that each frontend must use

| Catalog field | Default | Recipe key | Rule |
|---|---|---|---|
| `imgref`, or `registry` + `tag` | none | `image`, `targetImgref` | See "Image and NVIDIA image". |
| `nvidia_imgref` | `""` | `image`, `targetImgref` | See "Image and NVIDIA image". |
| `bootloader` | `""` | `bootloader` | `grub2`, `systemd`, or `""` for fisherman's default. |
| `composefs` | `false` | `composeFsBackend` | Copy the value. fisherman does not find it from the image. |
| `filesystem` | `""` | `filesystem` | The filesystem that is selected before the user picks one. |
| `filesystems` | `[]` | `filesystem` | The filesystems that the user can pick. |
| `default_hostname` | `""` | `hostname` | The first value of the hostname field. |
| `flatpaks` | not set | `flatpaks` | See "Flatpak lists". |
| `flatpak_var_path` | `""` | `flatpakVarPath` | Write the key only when the value is not empty. |
| `needs_user_creation` | `true` | `user` | See "The account". |
| `image_type` | `bootc` | `imageType` | Write the key only when the value is not `bootc`. |
| `extras` | not set | `extras` | See "Desktop extras". |

`name`, `desc`, `subtitle`, `icon`, `carousel` and `search_extra` are for the
page only. `fallback_flatpaks` is not part of the contract: do not read it
and do not send it.

### Filesystem

- The choices are `filesystems`. If that list is empty, the only choice is
  `filesystem`. If the two are empty, the frontend offers its own list.
- The selected value at the start is `filesystem`. If that is empty, it is
  the first entry of `filesystems`. If the two are empty, the frontend uses
  its own default.
- When the user selects a different leaf, apply the new leaf's value. Do not
  keep the filesystem of the leaf before it.

`expected.json` gives the two results as `filesystems` and `filesystem` in
each leaf.

### Hostname

Use the leaf's `default_hostname`. If it is empty, use `default_hostname`
from `branding.json` (`shared/branding/README.md`). A frontend can add a short
machine suffix, for example `atlas-a7c3`. The user can change the value.

### Image and NVIDIA image

`targetImgref` is always in the recipe. It is the image that updates follow.

| Leaf has `nvidia_imgref` | The machine | `image` | `targetImgref` |
|---|---|---|---|
| no | any | `imgref` | `imgref` |
| yes | has an NVIDIA GPU | `nvidia_imgref` | `nvidia_imgref` |
| yes | no NVIDIA GPU; live media; the store has the NVIDIA image and not the base image | `nvidia_imgref` | `imgref` |
| yes | no NVIDIA GPU; any other case | `imgref` | `imgref` |

The third row is the offline install from an ISO that holds only the NVIDIA
image. The first update then moves the system to the base image. Off live
media that row must not apply: it downloads the larger image for no gain
(#314).

"Live media" is `live.is_live` and "the store has" is `offline.images` from
`fisherman probe --json` (`shared/probe/README.md`). A frontend looks for a
PCI display device with vendor `0x10de` below `/sys/bus/pci/devices`. The
probe of fisherman `7f9021b` reports the same devices as `gpus`. No frontend
reads that list yet.

The confirm page shows `image`. It also shows `targetImgref` when the two
are different.

An empty `image` for the image that the live media booted is a different
rule. `shared/recipe/README.md` has it.

### Flatpak lists

`flatpaks` in the catalog is one of three things:

| Catalog value | Recipe |
|---|---|
| a list of application ids, `[]` included | `flatpaks` is that list |
| `@name`, and `aliases.name` is a list | `flatpaks` is that list |
| `@name`, and `aliases.name` is a URL; a URL; an alias that does not exist; no value | no `flatpaks` key |

In the recipe, `[]` tells fisherman to copy no Flatpak. No key tells
fisherman to apply its own default. Thus a frontend must not write `[]` for
a list that it cannot read.

**Decision: a frontend does not download a list.** Twelve nodes of the
bundled catalog point at a Brewfile on a web server. GNOME downloaded and
parsed that file in the page (`bootc_installer/defaults/image.py`). The
other four did not, and each did a different thing. COSMIC sent the three
applications of `fallback_flatpaks`, so a KDE image got GNOME applications.

fisherman's recipe accepts only a list of ids in `flatpaks`. fisherman
already reads the aliases (`internal/images`), runs as root on the host and
has the network that it uses for the image. It is the correct place to read
a remote list, and tuna-os/fisherman#387 tracks the work on image-owned
Flatpak metadata. Until fisherman reads the list, an image with a remote
list gets fisherman's default from all five frontends. That is less than
GNOME did, and it is the same from each frontend.

A frontend never puts a list of its own into the recipe.

### Desktop extras

`extras` is an object with four switches: `printServices`, `oemSetup`,
`audioNames` and `bootSplash`. They turn on the desktop steps that fisherman
does after the install. `fisherman/README.md` ("Desktop extras") says what
each step does.

| Catalog | Recipe |
|---|---|
| the leaf or a parent has `extras` | `extras` is that object |
| no node has `extras` | no `extras` key |

- The object comes from the nearest node that has it. Do not merge the
  object of a node with the object of its parent. A switch that the nearest
  object does not have is off.
- `{}` is an object. It turns the four switches off, and the recipe has the
  key.
- Copy only the four switches. fisherman refuses a recipe key that it does
  not know. A switch that is off can be `false` or can be left out.
- With no key, fisherman finds the image in the catalog on the host and uses
  that entry. An image that the catalog does not have gets no step.

A frontend must write the key. In a Flatpak, the frontend stages fisherman
alone, with no catalog next to it. Without the key, an install from a
Flatpak gets none of the steps. `expected.json` gives the object as `extras`
in each leaf, with the four switches, or `null`.

### The account

`needs_user_creation` says if the installer creates the first account. The
default is `true`: when no node sets the field, the installer creates an
account. `false` is for an image that makes the account at first boot.

- The flag comes from the leaf that the user selected.
- Live media can have no image page. The probe then gives the image as
  `live.live_image`. Find the leaf with that reference in the catalog from the
  search path, and use its flag.
- If no leaf has that reference, the answer is `true`.

When the answer is `true`, the frontend shows the account page and the
recipe has a `user` with a `username`. When it is `false`, the frontend
shows no account page and the recipe has no `user`, or a `user` with an
empty `username`. `shared/account/README.md` has the groups.

## Which image is selected at the start

1. The leaf whose reference is `default_image` of `branding.json`.
2. If there is none, the leaf whose reference is the catalog's
   `default_image`.
3. If there is none, select nothing. The user must choose before the next
   page opens.

A frontend must not select the first row. The bundled catalog has no
`default_image`. Thus a frontend with no `branding.json` starts with no
selection.

## Row labels

A tag leaf has a channel name, such as "Stable". Fifteen leaves of the
bundled catalog have that name. A row must also show the product.

- `product` is the `name` of the nearest node that sets `registry`. For a
  leaf with its own `imgref`, it is the leaf's `name`.
- `channel` is the `name` of a tag leaf. For a leaf with its own `imgref`,
  it is empty.
- `label` is the product, a space, then the channel. Show it on the
  confirm page and in a short list.
- `breadcrumb` is each `name` from the root to the leaf with ` › ` between
  them. Show it in a flat list of the full catalog: `label` is not unique
  there.

## How to read `expected.json`

```text
search_paths[]       in_flatpak, xdg_config_home -> paths ("<bundled>" is your own file)
default_selection[]  branding_default_image, catalog_default_image -> selected (null: nothing)
unknown_image        an image that is not in the catalog -> needs_user_creation
leaves[]             imgref, leaf (the resolved fields), cases[]
  cases[]            inputs (has_nvidia, is_live, offline_images) -> recipe, absent
```

`recipe` holds the keys and values that the frontend's recipe must have
after the user selects that leaf and changes nothing. `absent` holds the
keys that the recipe must not have. For `bootloader: ""`,
`composeFsBackend: false` and `imageType: "bootc"`, a recipe without the key
is also correct. In `extras`, a switch that the recipe does not have is
`false`. A row of `default_selection` with an empty
`catalog_default_image` applies to the fixture catalog with that key
removed.

Change the fixture catalog, then run
`python3 shared/catalog/resolve.py --write`.

## What each frontend must change

| Frontend | Change |
|---|---|
| GNOME | Put the system catalog before the user's. Read the legacy path. Default `needs_user_creation` to `true`. Stop the download of Flatpak lists and the use of `fallback_flatpaks`. Apply the NVIDIA table (#314). |
| KDE | Apply `filesystem` and `filesystems` (#287). Apply the NVIDIA table and `flatpak_var_path`. |
| COSMIC | Read all fields (#286). Default `needs_user_creation` to `true`. Remove the `fallback_flatpaks` list. Select nothing at the start. |
| Niri | Add the `/run/host` prefix (#298). Read `nvidia_imgref`, `flatpak_var_path` and alias lists. Write `targetImgref`. Select nothing at the start. |
| XFCE | Add the `/run/host` prefix and the current path (#298). Read `nvidia_imgref`, `flatpak_var_path`, `default_hostname` and alias lists. Write `targetImgref`. Select nothing at the start. |
