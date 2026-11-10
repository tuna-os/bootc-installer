"""Backend plumbing shared by every page: catalog, disks, live and offline
facts, recipe emission, validation and fisherman invocation. See
../INSTALLER-FRONTENDS.md."""

import json
import os
import shlex
import subprocess

from tuna_installer_xfce import branding, fisherman_probe, fisherman_validate

IN_FLATPAK = os.path.exists("/.flatpak-info")

# Dry run: the wizard behaves normally but NEVER launches fisherman.
#
# This exists because reaching the progress page is not a neutral act here.
# ProgressPage.on_enter() calls win.start_install(), so merely NAVIGATING to
# that page partitions a disk — there is no confirmation between the two. Any
# harness that drives this wizard the obvious way destroys the machine it runs
# on, and tests/gui/capture-screens.py has been working around exactly that by
# monkeypatching InstallerWindow.start_install to a no-op before showing a
# single page.
#
# A monkeypatch in one test script is not a safety property. It protects only
# the callers that remember to apply it, and it is invisible to anything
# driving the real binary — which is precisely what the live-ISO walkthrough
# harness in tuna-os/tunaOS does, over a QEMU keyboard, with no ability to
# patch anything. The interlock has to live in the app.
#
# So it does, and it follows the siblings: tuna-installer-cosmic refuses
# Message::StartInstall outright while TUNA_CAPTURE_DIR is set
# (src/capture.rs), and tuna-installer-kde drives its progress page through
# loadDemoState() rather than a real install. This is the same idea with the
# env var named for what it does rather than for the harness that wanted it.
#
# It is deliberately NOT just a refusal. A harness that reaches the progress
# page and sees nothing cannot tell "install suppressed" from "install
# crashed", and the `install` and `done` screens are two of the six in the
# tunaOS screen contract that no frontend has ever been credited with
# reaching. Under a dry run the progress page plays a representative fisherman
# transcript and completes, so those screens can finally be measured without a
# disk anywhere near it.
# Read at CALL time, not import time, and deliberately so.
#
# This was a module-level constant on the first attempt and the capture job
# caught it immediately: capture-screens.py imports core near the top to stub
# host_run, then set the env var further down, so the constant had already been
# evaluated as False and the guard refused to run. An import-time read makes
# the interlock depend on module import ORDER, which is an invisible property
# no caller can see and every new caller can get wrong — a poor foundation for
# the one check standing between a test harness and a partitioned disk.
def dry_run():
    return os.environ.get("TUNA_INSTALLER_DRY_RUN", "") not in ("", "0")


# Hardware facts -- the disks that may be installed to, TPM 2.0, and the
# RAM/CPU/UEFI requirements -- are fisherman's: `fisherman probe --json`,
# run once, unprivileged, on the host (shared/probe/README.md). This frontend
# used to run its own lsblk with its own filter (it offered zram), format
# sizes in SI "GB", and probed the TPM itself. None of that is here now.
#
# There is no fallback scan when the probe fails: the destination page shows
# the reason instead and offers no disk.
FISHERMAN_PATH = "/usr/local/bin/fisherman"
# fisherman, unprivileged, on the host: for `probe --json` and
# `validate --json`. Never through pkexec or sudo.
FISHERMAN_UNPRIVILEGED = (["flatpak-spawn", "--host"] if IN_FLATPAK else []) + [FISHERMAN_PATH]
PROBE_ARGV = FISHERMAN_UNPRIVILEGED + ["probe", "--json"]
# `fisherman validate --json --partial -`: a page's fields as a partial
# recipe on stdin (shared/recipe/README.md). fisherman owns the hostname,
# username, filesystem and encryption rules.
VALIDATE_ARGV = fisherman_validate.argv(FISHERMAN_UNPRIVILEGED)

# The encryption types in display order, with needs_passphrase and
# needs_tpm2: a byte-identical copy of fisherman's
# data/encryption-choices.json (tests/unit/test_encryption_choices.py).
ENCRYPTION_CHOICES = fisherman_validate.load_choices()


def needs_passphrase(enc_type):
    return fisherman_validate.needs_passphrase(enc_type, ENCRYPTION_CHOICES)


def needs_tpm2(enc_type):
    return fisherman_validate.needs_tpm2(enc_type, ENCRYPTION_CHOICES)

_probe_cache = {}


def probe(refresh=False):
    """(result, error): the probe result, or None and the reason it failed."""
    if refresh or "answer" not in _probe_cache:
        try:
            _probe_cache["answer"] = (fisherman_probe.run(PROBE_ARGV), None)
        except fisherman_probe.ProbeError as exc:
            _probe_cache["answer"] = (None, str(exc))
    return _probe_cache["answer"]


def has_tpm():
    """fisherman's tpm.usable; False when the probe failed.

    BOOTC_INSTALLER_FAKE_TPM is honoured by fisherman itself, and a capture
    can point BOOTC_INSTALLER_FAKE_PROBE at a fixture with a usable TPM.
    """
    result, _ = probe()
    return fisherman_probe.tpm_usable(result) if result else False


def is_live():
    """Whether the host booted from live media: fisherman's live.is_live.

    Only then may the recipe leave `image` empty, which installs the running
    system; fisherman rejects an empty image anywhere else. This frontend
    used to ask `bootc status` and read /proc/cmdline itself, inside its
    Flatpak sandbox. False when the probe failed."""
    result, _ = probe()
    return fisherman_probe.is_live(result) if result else False


def live_image():
    """The booted image on live media (live.live_image); "" otherwise or
    when bootc could not name it."""
    result, _ = probe()
    return fisherman_probe.live_image(result) if result else ""


def offline_images():
    """Image refs in the host's offline stores (probe's offline.images), for
    the "[available offline]" tag. fisherman exposes those stores to the
    install itself when the recipe leaves additionalImageStores out."""
    result, _ = probe()
    return set(fisherman_probe.offline_images(result)) if result else set()


def unmet_requirements():
    """fisherman's system.unmet ("ram", "cpu", "uefi"); empty when the probe
    failed, so a failed probe never warns."""
    result, _ = probe()
    return fisherman_probe.unmet_requirements(result) if result else []


def requirements_warning():
    """The welcome page's warning text, or "" when every requirement is met."""
    unmet = unmet_requirements()
    if not unmet:
        return ""
    keys = {"ram": "requirements_ram", "cpu": "requirements_cpu",
            "uefi": "requirements_uefi"}
    lines = [BRANDING.text("requirements_title")]
    lines += [BRANDING.text(keys[item]) for item in unmet if item in keys]
    return "\n".join(line for line in lines if line)


# A representative fisherman transcript for the dry run, in fisherman's real
# wire format: newline-delimited JSON on stdout, one event per line
# (shared/progress/README.md). ProgressPage.append_log parses it with exactly
# the parser a real install goes through, so the dry run exercises the real
# code path rather than a private one.
#
# It used to be nine hand-written "[n/9] Partitioning /dev/vda" lines,
# described in this comment as "fisherman's own prefix format". It is not:
# fisherman has never written that prefix, and the step COUNT is not fixed at
# nine either (cmd/fisherman/main.go computes total_steps from the recipe).
# The transcript matched the frontend's own regex rather than the backend, so
# the screenshot harness photographed a moving bar that no real install could
# produce.
#
# This file is generated from fisherman's own progress emitter and weight
# profile, not written by hand, so the percentages are the ones a real
# uncached auto-layout install emits. `timestamp` and `elapsed_ms` are frozen
# to keep the fixture stable; nothing in the parser reads either.
_TRANSCRIPT_PATH = os.path.join(os.path.dirname(__file__), "dry-run-transcript.ndjson")


def _load_dry_run_transcript():
    """The dry-run transcript as a list of lines, each ending in a newline."""
    with open(_TRANSCRIPT_PATH, encoding="utf-8") as fh:
        return [line for line in fh.read().splitlines(keepends=True) if line.strip()]


DRY_RUN_TRANSCRIPT = _load_dry_run_transcript()

# Flatpak runtimes ship no pkexec; escalate host-side. The live ISO symlinks
# the flatpak-bundled fisherman to /usr/local/bin and installs the polkit
# policy for it (tunaOS customize-live.sh).
#
# Under Flatpak, pkexec runs inside a host-side bash rather than straight
# from `flatpak-spawn --host pkexec ...`. fisherman runs as root, so this
# process can never signal it; fisherman cancels itself when its PARENT dies
# (tuna-os/fisherman#267). Launched directly, that parent was the host's
# flatpak-session-helper, which nothing here can kill. With the wrapper it is
# this bash. The wrapper does no redirection: stdout and stderr still come
# back through flatpak-spawn's pipes, as before.
#
# `-`: fisherman reads the recipe from stdin (tuna-os/fisherman#276). The
# app writes the JSON to the wrapper's stdin and closes it, so no file ever
# holds the passphrase or the user password. bash, pkexec, sudo and
# flatpak-spawn all pass stdin through.
FISHERMAN_WRAPPER_SCRIPT = 'pkexec /usr/local/bin/fisherman -; exit $?'
FISHERMAN_CMD = (
    ["flatpak-spawn", "--host", "bash", "-c", FISHERMAN_WRAPPER_SCRIPT]
    if IN_FLATPAK
    else ["sudo", "/usr/local/bin/fisherman", "-"]
)

# Where the catalog is (shared/catalog/README.md, "Where the catalog is"):
# the system file, its legacy name, a developer's file, then the catalog in
# the package. In a Flatpak the host's /etc is at /run/host/etc; the sandbox
# has its own. This list used to be the legacy name only, with no prefix, so
# an ISO's /etc/bootc-installer/images.json was invisible (#298).
BUNDLED_CATALOGS = (
    "/app/share/fisherman/data/images.json",
    "/usr/share/fisherman/data/images.json",
)


def catalog_search_paths(in_flatpak=None, xdg_config_home=None, bundled=BUNDLED_CATALOGS):
    """The ordered list of catalog files. The first that loads is used."""
    if in_flatpak is None:
        in_flatpak = IN_FLATPAK
    if not xdg_config_home:
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config")
    etc = "/run/host/etc" if in_flatpak else "/etc"
    return [
        f"{etc}/bootc-installer/images.json",
        f"{etc}/tuna-installer/images.json",
        f"{xdg_config_home.rstrip('/')}/bootc-installer/images.json",
        *bundled,
    ]


def images_json_paths():
    """`catalog_search_paths()` for this process. FISHERMAN_IMAGES_PATH is
    the harness override (the capture and the E2E driver set it); it is
    first so a test never reads the machine's own catalog."""
    override = os.environ.get("FISHERMAN_IMAGES_PATH", "")
    return ([override] if override else []) + catalog_search_paths()


# --- product branding --------------------------------------------------------
#
# Nothing here names a product. shared/branding/README.md (monorepo) is the
# contract: a branding.json under /etc/bootc-installer (host first, since this
# ships as a Flatpak) names the product, seeds the hostname and the recipe's
# distroID; keys it does not set come from os-release; the last resort is a
# neutral "Linux". tuna_installer_xfce/branding.py is a byte-identical copy of
# the shared resolver.


def resolve_branding():
    """Resolve once per call; the module-level BRANDING is the cached answer."""
    return branding.resolve()


# Resolved once at import: the files do not change under a running installer,
# and every page title needs the same answer.
BRANDING = resolve_branding()
PRODUCT_NAME = BRANDING.name


def host_run(argv, **kwargs):
    """Run a command on the host, crossing the sandbox boundary if needed."""
    if IN_FLATPAK:
        argv = ["flatpak-spawn", "--host"] + argv
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


# --- image catalog -----------------------------------------------------------
#
# shared/catalog/README.md is the contract and shared/catalog/fixtures/ the
# answers every frontend must give; tests/test_catalog_contract.py reads the
# fixture through this parser. Nothing here downloads anything, and
# `fallback_flatpaks` is never read.

# Catalog key -> the value a leaf has when neither it nor a parent sets it.
# needs_user_creation is True: an install with no account and no first-boot
# setup leaves nobody to sign in as (#288).
_INHERITED = {
    "registry": "",
    "nvidia_imgref": "",
    "bootloader": "",
    "composefs": False,
    "filesystem": "",
    "filesystems": [],
    "default_hostname": "",
    "flatpaks": None,
    "flatpak_var_path": "",
    "needs_user_creation": True,
    "image_type": "bootc",
}


def resolve_flatpaks(value, aliases):
    """The list a catalog `flatpaks` value names, or None.

    A list is the list, `[]` included. `@name` is the list `aliases.name`
    holds. A URL, an alias that is a URL, an alias that does not exist and
    no value are all None: the recipe then has no `flatpaks` key and
    fisherman applies its own default. A frontend does not download a list.
    """
    if isinstance(value, str) and value.startswith("@"):
        value = (aliases or {}).get(value[1:])
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def _pretty_from_imgref(imgref):
    slug = imgref.rsplit("/", 1)[-1].split("@", 1)[0].split(":", 1)[0]
    parts = [part for part in slug.replace("_", "-").split("-") if part]
    if not parts:
        return imgref
    return " ".join(part.capitalize() if index == 0 else part.upper()
                    for index, part in enumerate(parts))


class ImageLeaf:
    """One installable image, with the fields it inherits resolved."""

    def __init__(self, node, context, product, owns_registry, aliases, path):
        name = node.get("name", "")
        self.name = name.strip() if isinstance(name, str) else ""
        self.desc = node.get("desc", "") or ""
        self.subtitle = node.get("subtitle", "") or ""
        own = node.get("imgref")
        if own:
            self.imgref, self.channel = own, ""
            self.product = self.name or _pretty_from_imgref(own)
        else:
            self.imgref = f"{context['registry']}:{node['tag']}"
            # A tag leaf that sets its own registry is its own product.
            self.channel = "" if owns_registry else self.name
            self.product = product or _pretty_from_imgref(self.imgref)
        # Product and channel: a tag leaf's own name is a channel ("Stable"),
        # and fifteen leaves of the bundled catalog have that one (#289).
        self.label = f"{self.product} {self.channel}".strip()
        self.path = list(path)
        self.breadcrumb = " \u203a ".join(path) or self.label
        self.nvidia_imgref = context["nvidia_imgref"] or ""
        self.bootloader = context["bootloader"] or ""
        self.composefs = bool(context["composefs"])
        declared = context["filesystem"] or ""
        choices = [fs for fs in context["filesystems"] or [] if isinstance(fs, str)]
        # What the user may pick ([] means this frontend's own list), and
        # what is selected before they pick ("" means this frontend's
        # default): shared/catalog/README.md, "Filesystem".
        self.filesystems = choices or ([declared] if declared else [])
        self.filesystem = declared or (choices[0] if choices else "")
        self.default_hostname = context["default_hostname"] or ""
        self.flatpaks = resolve_flatpaks(context["flatpaks"], aliases)
        self.flatpak_var_path = context["flatpak_var_path"] or ""
        self.needs_user_creation = bool(context["needs_user_creation"])
        self.image_type = context["image_type"] or "bootc"


def catalog_leaves(raw):
    """Every installable leaf of a parsed images.json, in catalog order."""
    aliases = raw.get("aliases") if isinstance(raw.get("aliases"), dict) else {}
    found = []

    def walk(nodes, inherited, product, path):
        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                continue
            context = dict(inherited)
            for key in _INHERITED:
                # A value of false, "" or [] is a value and stops the search.
                if key in node and node[key] is not None:
                    context[key] = node[key]
            name = node.get("name", "")
            name = name if isinstance(name, str) else ""
            here = path + [name] if name else path
            # The product is the name of the nearest node that sets a
            # registry.
            owns_registry = bool(node.get("registry"))
            node_product = name.strip() if owns_registry else product
            if node.get("imgref") or ("tag" in node and context["registry"]):
                found.append(ImageLeaf(node, context, node_product, owns_registry,
                                       aliases, here))
                continue
            walk(node.get("children", []), context, node_product, here)

    walk(raw.get("images", []), dict(_INHERITED), "", [])
    return found


class CatalogRoot:
    """A top-level entry, for the welcome page's tour (tour.py)."""

    def __init__(self, raw):
        self.name = raw.get("name", "") or ""
        self.desc = raw.get("desc", "") or ""
        self.subtitle = raw.get("subtitle", "") or ""


class Catalog:
    """A loaded images.json: its leaves, its default and its top entries."""

    def __init__(self, raw=None, path=""):
        raw = raw if isinstance(raw, dict) else {}
        self.path = path
        self.default_image = raw.get("default_image", "") or ""
        self.leaves = catalog_leaves(raw)
        self.roots = [CatalogRoot(node) for node in raw.get("images", [])
                      if isinstance(node, dict)]

    def find(self, imgref):
        """The leaf for `imgref`, or None. The NVIDIA variant of a leaf is
        that leaf."""
        if not imgref:
            return None
        for leaf in self.leaves:
            if leaf.imgref == imgref:
                return leaf
        for leaf in self.leaves:
            if leaf.nvidia_imgref == imgref:
                return leaf
        return None

    def needs_user_creation(self, imgref):
        """Whether the install of `imgref` creates an account. An image the
        catalog does not have needs one."""
        leaf = self.find(imgref)
        return True if leaf is None else leaf.needs_user_creation

    def default_leaf(self, branding_default_image=""):
        """The leaf selected at start: the branding's default_image, then
        the catalog's, else None. None means the user must choose; this
        frontend used to select the first name in the alphabet (#289)."""
        for candidate in (branding_default_image, self.default_image):
            if not candidate:
                continue
            for leaf in self.leaves:
                if leaf.imgref == candidate:
                    return leaf
        return None


def read_catalog_file(path):
    """The Catalog in `path`, or None when the file is missing, does not
    parse, or is not an object with an `images` list."""
    try:
        with open(path, encoding="utf-8") as stream:
            raw = json.load(stream)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("images"), list):
        return None
    return Catalog(raw, path)


def load_catalog(paths=None):
    """The first catalog on the search path that loads; an empty Catalog
    when none does. A file that does not load does not stop the search."""
    for path in images_json_paths() if paths is None else paths:
        catalog = read_catalog_file(path) if path else None
        if catalog is not None:
            return catalog
    return Catalog()


# --- NVIDIA ------------------------------------------------------------------

PCI_DEVICES = "/sys/bus/pci/devices"
NVIDIA_VENDOR = "0x10de"


def has_nvidia_gpu(pci_devices=PCI_DEVICES):
    """Whether a PCI display device has NVIDIA's vendor id. The probe does
    not report the GPU yet (shared/catalog/README.md, "Image and NVIDIA
    image"), so this reads sysfs, which a Flatpak sees too."""
    try:
        devices = os.listdir(pci_devices)
    except OSError:
        return False
    for device in devices:
        try:
            with open(os.path.join(pci_devices, device, "class")) as stream:
                pci_class = stream.read().strip()
            with open(os.path.join(pci_devices, device, "vendor")) as stream:
                vendor = stream.read().strip()
        except OSError:
            continue
        if pci_class.startswith("0x03") and vendor.lower() == NVIDIA_VENDOR:
            return True
    return False


def source_and_target(leaf, has_nvidia=False, live=False, offline=()):
    """(image, targetImgref) for a leaf on this machine.

    With an NVIDIA GPU both are the NVIDIA image. Without one, the NVIDIA
    image is the source only on live media whose store has it and not the
    base image; updates then follow the base image.
    """
    base, nvidia = leaf.imgref, leaf.nvidia_imgref
    if not nvidia:
        return base, base
    if has_nvidia:
        return nvidia, nvidia
    if live and nvidia in offline and base not in offline:
        return nvidia, base
    return base, base


# --- the first account -------------------------------------------------------
#
# shared/account/README.md. DEFAULT_GROUPS is `default_groups` of
# shared/account/groups.json; tests/test_account.py fails when the two
# differ. fisherman removes each group the image does not have, so one list
# is correct for every image. This frontend used to send only "wheel", which
# Ubuntu images do not have (#302).
DEFAULT_GROUPS = ("wheel", "sudo", "docker", "incus-admin", "libvirt", "dialout")


def operator_recipe_path(in_flatpak=None):
    """The ISO builder's recipe.json: the host's /etc, also in a Flatpak."""
    if in_flatpak is None:
        in_flatpak = IN_FLATPAK
    etc = "/run/host/etc" if in_flatpak else "/etc"
    return f"{etc}/bootc-installer/recipe.json"


def groups_from_operator_recipe(operator_recipe):
    """The account's groups given the operator's recipe (None for no file).
    `user.groups` replaces the default when it is a list of strings, `[]`
    included; anything else keeps the default."""
    user = operator_recipe.get("user") if isinstance(operator_recipe, dict) else None
    groups = user.get("groups") if isinstance(user, dict) else None
    if isinstance(groups, list) and all(isinstance(group, str) for group in groups):
        return list(groups)
    return list(DEFAULT_GROUPS)


def account_groups(path=None):
    """The supplementary groups of the first account. Only `user.groups` is
    read from the operator's file."""
    try:
        with open(path or operator_recipe_path(), encoding="utf-8") as stream:
            operator_recipe = json.load(stream)
    except (OSError, ValueError):
        operator_recipe = None
    return groups_from_operator_recipe(operator_recipe)


# --- disks --------------------------------------------------------------------

def candidate_disks():
    """(disks, error): the disks fisherman offers, in its order, rendered per
    shared/probe/README.md -- title (model, else path), size_label verbatim."""
    result, error = probe()
    if result is None:
        return [], error
    return fisherman_probe.render_disks(result), None


# --- recipe -------------------------------------------------------------------

# This frontend's own filesystem list and default, for a leaf that names
# neither `filesystem` nor `filesystems`.
FILESYSTEMS = ("xfs", "ext4", "btrfs", "zfs")
DEFAULT_FILESYSTEM = "xfs"


def build_recipe(*, disk, filesystem, btrfs_subvolumes=False,
                 encryption_type="none", passphrase="", image="",
                 target_imgref="", hostname="", bootloader="", composefs=False,
                 flatpaks=None, flatpak_var_path="", image_type="bootc",
                 needs_user=True, username="", fullname="",
                 password="", groups=None, branding=None):
    """Assemble the fisherman recipe from already-resolved values.

    This is the contract with the install backend, the same document every
    frontend builds, so it is the one piece of this frontend most worth
    testing without a display. Callers pass plain values; the widget layer
    reads them off the pages.

      * `btrfsSubvolumes` is only meaningful on btrfs, and is False elsewhere
        regardless of what the Advanced checkbox says.
      * The passphrase is only emitted for an encryption type that takes one
        (`needs_passphrase` in encryption-choices.json), so a stale entry
        left in the box cannot leak into a recipe for an unencrypted install.
      * `targetImgref` is the image that updates follow. It is written
        whenever a catalog image was chosen; "install this system" on live
        media has none and leaves it to fisherman.
      * `bootloader`, `composeFsBackend`, `flatpakVarPath` and `imageType`
        are catalog-leaf properties: an absent key means "let fisherman
        decide", which is not the same as an empty value.
      * `flatpaks` is a list or None. `[]` tells fisherman to copy no
        Flatpak; None (a list this frontend cannot read offline, or no
        value) writes no key, and fisherman applies its own default.
      * The user block is omitted entirely when the image creates its own
        first user, or when no username was typed. `groups` is
        account_groups(): the shared default or the operator's list.
    """
    recipe = {
        "disk": disk,
        "filesystem": filesystem,
        "btrfsSubvolumes": filesystem == "btrfs" and btrfs_subvolumes,
        "encryption": {"type": encryption_type},
        "image": image,
        # True makes bootc boot the installed system with selinux=0.
        "selinuxDisabled": False,
        "hostname": hostname,
        # The branding's id, never a literal: see resolve_branding().
        "distroID": (branding or BRANDING).id,
    }
    if needs_passphrase(encryption_type):
        recipe["encryption"]["passphrase"] = passphrase
    if target_imgref:
        recipe["targetImgref"] = target_imgref
    if bootloader:
        recipe["bootloader"] = bootloader
    if composefs:
        recipe["composeFsBackend"] = True
    if flatpaks is not None:
        recipe["flatpaks"] = list(flatpaks)
    if flatpak_var_path:
        recipe["flatpakVarPath"] = flatpak_var_path
    if image_type and image_type != "bootc":
        recipe["imageType"] = image_type
    if needs_user and username:
        recipe["user"] = {
            "username": username,
            "fullname": fullname,
            "password": password,
            "groups": list(DEFAULT_GROUPS if groups is None else groups),
        }
    return recipe


def recipe_for_leaf(leaf, *, has_nvidia=False, live=False, offline=(), **fields):
    """build_recipe() with every catalog field of `leaf` applied: what the
    recipe carries when the user selects that leaf. `fields` are the page
    values (disk, encryption, account); `filesystem` and `hostname` default
    to the leaf's."""
    image, target = source_and_target(leaf, has_nvidia, live, offline)
    fields.setdefault("filesystem", leaf.filesystem or DEFAULT_FILESYSTEM)
    fields.setdefault("hostname", leaf.default_hostname or BRANDING.default_hostname)
    return build_recipe(
        image=image, target_imgref=target, bootloader=leaf.bootloader,
        composefs=leaf.composefs, flatpaks=leaf.flatpaks,
        flatpak_var_path=leaf.flatpak_var_path, image_type=leaf.image_type,
        needs_user=leaf.needs_user_creation, **fields)


def recipe_stdin(recipe):
    """The bytes the app writes to fisherman's stdin (`fisherman -`)."""
    return json.dumps(recipe).encode("utf-8")


def fisherman_argv(in_flatpak=None):
    """The argv that runs fisherman with privileges, the recipe on stdin."""
    if in_flatpak is None:
        return list(FISHERMAN_CMD)
    if in_flatpak:
        return ["flatpak-spawn", "--host", "bash", "-c", FISHERMAN_WRAPPER_SCRIPT]
    return ["sudo", "/usr/local/bin/fisherman", "-"]


def fisherman_shell():
    return " ".join(shlex.quote(a) for a in fisherman_argv())


# --- install log --------------------------------------------------------------
#
# InstallerWindow used to keep fisherman's output only in `self._log_tail`, an
# in-memory list capped at the last 15 lines and shown on the Done page when an
# install fails. Close the app (or lose the display, as happens over a QEMU
# serial console) before reading it and the only record of what fisherman did
# is gone — the same gap already found and fixed in tuna-installer-kde,
# -cosmic, -niri and bootc-installer-asahi's frontends. Persist the full
# transcript to disk so it survives past the wizard process.

INSTALL_LOG_DIR_NAME = "tuna-installer"
INSTALL_LOG_FILE_NAME = "install.log"


def install_log_path():
    """Path to the persistent install log; ensures its directory exists."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state")
    log_dir = os.path.join(base, INSTALL_LOG_DIR_NAME)
    os.makedirs(log_dir, mode=0o700, exist_ok=True)
    return os.path.join(log_dir, INSTALL_LOG_FILE_NAME)


def open_install_log():
    """Open the persistent install log for appending, creating it 0600."""
    path = install_log_path()
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    return os.fdopen(fd, "a")
