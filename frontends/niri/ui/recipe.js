.pragma library

// The recipe that the wizard hands to the backend's `install`.
//
// installer.qml collects the choices and calls build(); the backend
// (installer/main.go) decodes the result, adds the account's groups, and
// pipes it to `fisherman -`. Kept out of installer.qml so that a test can
// run it without a QML engine: installer/compliance_test.go sends the
// choices of shared/recipe/fixtures/compliance.json through this file and
// then through the backend, and the result must be the recipe that every
// frontend writes for them (shared/recipe/README.md, "The compliance
// fixture").

// The image keys of a catalog leaf: the image, the image that updates
// follow, and the leaf's `recipe` keys for this machine, which the backend's
// `catalog` command computed (the NVIDIA rule, the Flatpak list rule).
// `filesystem` is left to the wizard, which starts at the leaf's value and
// lets the user change it.
function leafKeys(leaf) {
    const keys = Object.assign({ image: leaf.imgref, targetImgref: leaf.imgref }, leaf.recipe || {})
    delete keys.filesystem
    return keys
}

// The recipe keys of the Session step's picks (#292). None without a pick:
// the installed system keeps the image's values.
function regionKeys(picked) {
    const keys = {}
    picked = picked || {}
    if (picked.locale) keys.locale = picked.locale
    if (picked.keyboard) keys.keyboard = { layout: picked.keyboard }
    if (picked.timezone) keys.timezone = picked.timezone
    return keys
}

// The recipe for the wizard's choices `c`:
//   disk, filesystem, btrfsSubvolumes, encType, passphraseNeeded,
//   passphrase, hostname, distroID, imageKeys (leafKeys(), or the live or
//   fallback keys, or null), region (the Session step's picks),
//   needsUserCreation, username, fullname, password.
function build(c) {
    const recipe = {
        disk: c.disk,
        filesystem: c.filesystem,
        // Subvolumes only on btrfs, whatever the row says.
        btrfsSubvolumes: c.filesystem === "btrfs" && !!c.btrfsSubvolumes,
        encryption: c.passphraseNeeded
            ? { type: c.encType, passphrase: c.passphrase }
            : { type: c.encType },
        hostname: c.hostname,
        distroID: c.distroID || "linux",
        // true makes bootc boot the installed system with selinux=0.
        selinuxDisabled: false
        // No additionalImageStores: fisherman exposes the host's stores.
    }
    // image, targetImgref, bootloader, composeFsBackend, and flatpaks,
    // flatpakVarPath and imageType when the leaf gives them. A key that
    // is not there stays out: an absent `flatpaks` lets fisherman apply
    // its default, and that is not the same as an empty list. An empty
    // image installs the running system, which fisherman accepts only
    // on live media (probe's live.is_live).
    Object.assign(recipe, c.imageKeys || {})
    // ZFS is experimental in fisherman (no VM test boots it): the
    // user picked it, and the recipe says that it accepts that.
    if (c.filesystem === "zfs")
        recipe.experimental = ["zfs"]
    // The Session step's picks: locale, keyboard, timezone (#292).
    Object.assign(recipe, regionKeys(c.region))
    // The account: left out when the image makes its own first user,
    // and with no username (the schema's "empty skips"). No groups
    // here: the backend writes the shared list or the operator's.
    if (c.needsUserCreation && c.username)
        recipe.user = {
            username: c.username,
            fullname: c.fullname || "",
            password: c.password || ""
        }
    return recipe
}
