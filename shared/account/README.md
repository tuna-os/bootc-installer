# The first account: groups

`groups.json` holds the supplementary groups that each frontend writes into
`user.groups` of the recipe when the installer creates the first account.
`shared/catalog/README.md` says when the installer creates that account.

## The default list

`default_groups` is the list. `wheel` and `sudo` are the two admin groups:
Fedora and its family use `wheel`, Debian and Ubuntu use `sudo`. `docker`,
`incus-admin`, `libvirt` and `dialout` are for developer images. fisherman
removes each group that the image does not have, so one list is correct for
all images. A frontend sends the full list and does not look at the image.

## The operator's list

An ISO builder can set the groups. The file is
`<etc>/bootc-installer/recipe.json`, and the key is `user.groups`. `<etc>` is
`/etc` in a native run and `/run/host/etc` in a Flatpak, as for the catalog.

- If `user.groups` is a list of strings, it replaces the default list. An
  empty list means no supplementary group.
- If the file is not there or does not parse, use the default list. Do the
  same when the value at that key is not a list of strings.
- The frontend reads only that key from the file for this rule.

`cases` in `groups.json` gives an operator file (`null` for no file) and the
groups that the recipe must have. Each frontend has a test that reads them.
`tests/unit/test_shared_account.py` runs the same cases against a reference
function, and makes sure that the GNOME list is in the shared one.
