"""Backend plumbing shared by every page: catalog, disks, live and offline
facts, recipe emission, validation and fisherman invocation. See
../INSTALLER-FRONTENDS.md."""

import json
import os
import shlex
import subprocess

from bootc_shared import account as shared_account
from bootc_shared import branding, fisherman_host, hardware, progress, redact
from bootc_shared import catalog as shared_catalog
from bootc_shared import probe as fisherman_probe
from bootc_shared import validate as fisherman_validate

from tuna_installer_xfce.i18n import _

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
#
# How fisherman is reached is decided in ONE function, fisherman_command(),
# for the probe, the validate checks and the install (#290):
#
#   native    /usr/local/bin/fisherman; the install escalates with pkexec,
#             and with `sudo -n` only on live media (fisherman's
#             live.is_live), where the live user has passwordless sudo and
#             may have no polkit agent.
#   Flatpak   the fisherman this Flatpak built (/app/bin/fisherman), copied
#             to $XDG_CACHE_HOME/bootc-installer/fisherman and checked on
#             the host by SHA256 before anything runs it. The host needs no
#             fisherman of its own, and the binary is the one this build's
#             progress and validate contracts were written against.
#
# The rules are bootc_shared.fisherman_host, which GNOME also uses. This
# module keeps the paths of this process, the one stage per run, and the
# transport: stdout and stderr come back through the pipes (no log path).
FISHERMAN_PATH = fisherman_host.FISHERMAN_PATH
BUNDLED_FISHERMAN = fisherman_host.BUNDLED_FISHERMAN
StageError = fisherman_host.StageError
fisherman_stage_dir = fisherman_host.stage_dir
_sha256 = fisherman_host.sha256
_host_sha256 = fisherman_host.host_sha256


def staged_fisherman_path(environ=None):
    return os.path.join(fisherman_stage_dir(environ), "fisherman")


def stage_fisherman(source=None, environ=None, host_sha256=None):
    """Copy the bundled fisherman to the app cache and return its path
    (fisherman_host.stage). The user's home base, the cache directory and
    the file must be the user's own, and the host must see the same bytes.
    StageError when any step fails; nothing may run the staged file then.
    """
    return fisherman_host.stage(source, environ=environ, host_hash=host_sha256)


_stage_cache = {}


def staged_fisherman():
    """The staged, host-verified fisherman; staged on the first call. A
    failure is not remembered, so a later call tries again."""
    if "path" not in _stage_cache:
        _stage_cache["path"] = stage_fisherman()
    return _stage_cache["path"]


FISHERMAN_PURPOSES = fisherman_host.PURPOSES


def fisherman_command(purpose, *, in_flatpak=None, live=None, host_path=None):
    """The argv that runs fisherman for `purpose` (fisherman_host.command).

    "probe", "validate" and "validate-full" run unprivileged, never through
    pkexec or sudo. "install" runs with privileges and reads the recipe on
    stdin. In a Flatpak `host_path` is the staged binary (staged here when
    not given; StageError when that fails). `live` is fisherman's
    live.is_live and matters only for a native install.
    """
    if purpose not in FISHERMAN_PURPOSES:
        raise ValueError(f"unknown fisherman purpose {purpose!r}")
    if in_flatpak is None:
        in_flatpak = IN_FLATPAK
    if in_flatpak and not host_path:
        host_path = staged_fisherman()
    if not in_flatpak and purpose == "install" and live is None:
        live = is_live()
    return fisherman_host.command(purpose, in_flatpak=in_flatpak, live=bool(live),
                                  host_path=host_path)


def validate_argv():
    """`fisherman validate --json --partial -` for the pages' live checks. A
    page's fields go to it as a partial recipe on stdin
    (shared/recipe/README.md); fisherman owns the hostname, username,
    filesystem and encryption rules. When staging failed the command cannot
    run, the check reports that, and it blocks nothing: the destination
    page already shows why no disk is offered."""
    try:
        return fisherman_command("validate")
    except StageError:
        return fisherman_validate.argv(["flatpak-spawn", "--host", FISHERMAN_PATH])


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
            _probe_cache["answer"] = (
                fisherman_probe.run(fisherman_command("probe")), None)
        except (fisherman_probe.ProbeError, StageError) as exc:
            _probe_cache["answer"] = (None, str(exc))
    return _probe_cache["answer"]


def has_tpm():
    """fisherman's tpm.usable; False when the probe failed.

    BOOTC_INSTALLER_FAKE_TPM is honoured by fisherman itself, and a capture
    can point BOOTC_INSTALLER_FAKE_PROBE at a fixture with a usable TPM.
    """
    result, _error = probe()
    return fisherman_probe.tpm_usable(result) if result else False


def is_live():
    """Whether the host booted from live media: fisherman's live.is_live.

    Only then may the recipe leave `image` empty, which installs the running
    system; fisherman rejects an empty image anywhere else. This frontend
    used to ask `bootc status` and read /proc/cmdline itself, inside its
    Flatpak sandbox. False when the probe failed."""
    result, _error = probe()
    return fisherman_probe.is_live(result) if result else False


def live_image():
    """The booted image on live media (live.live_image); "" otherwise or
    when bootc could not name it."""
    result, _error = probe()
    return fisherman_probe.live_image(result) if result else ""


def offline_images():
    """Image refs in the host's offline stores (probe's offline.images), for
    the "[available offline]" tag. fisherman exposes those stores to the
    install itself when the recipe leaves additionalImageStores out."""
    result, _error = probe()
    return set(fisherman_probe.offline_images(result)) if result else set()


def unmet_requirements():
    """fisherman's system.unmet ("ram", "cpu", "uefi"); empty when the probe
    failed, so a failed probe never warns."""
    result, _error = probe()
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
_TRANSCRIPT_PATH = progress.transcript_path()


def _load_dry_run_transcript():
    """The dry-run transcript as a list of lines, each ending in a newline."""
    with open(_TRANSCRIPT_PATH, encoding="utf-8") as fh:
        return [line for line in fh.read().splitlines(keepends=True) if line.strip()]


DRY_RUN_TRANSCRIPT = _load_dry_run_transcript()

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
    return [*shared_catalog.search_paths(in_flatpak, xdg_config_home), *bundled]


def images_json_paths():
    """The catalog files for this process: bootc_shared.catalog's list
    (FISHERMAN_IMAGES_PATH first, the override that a capture and the E2E
    driver set, so a test never reads the machine's own catalog), then
    this frontend's bundled catalogs."""
    return [*shared_catalog.default_search_paths(flatpak=IN_FLATPAK), *BUNDLED_CATALOGS]


# --- product branding --------------------------------------------------------
#
# Nothing here names a product. shared/branding/README.md (monorepo) is the
# contract: a branding.json under /etc/bootc-installer (host first, since this
# ships as a Flatpak) names the product, seeds the hostname and the recipe's
# distroID; keys it does not set come from os-release; the last resort is a
# neutral "Linux". bootc_shared.branding is the resolver.


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


# The desktop's own network tool, in the order tried: the NetworkManager
# editor an Xfce session ships, then the settings panels of the other
# desktops this installer runs on. Best effort (#301): the confirm page
# says so when the host has none of them.
NETWORK_TOOLS = (
    ("nm-connection-editor",),
    ("gnome-control-center", "wifi"),
    ("systemsettings", "kcm_networkmanagement"),
    ("cosmic-settings", "network"),
)


def host_spawn(argv):
    """Start a command on the host and do not wait for it."""
    if IN_FLATPAK:
        argv = ["flatpak-spawn", "--host"] + list(argv)
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def open_network_settings():
    """Open the first of NETWORK_TOOLS the host has. Returns its name, or ""
    when the host has none or it could not start."""
    for tool in NETWORK_TOOLS:
        try:
            found = host_run(["sh", "-c", 'command -v "$1" >/dev/null 2>&1', "sh", tool[0]],
                             timeout=10)
            if found.returncode != 0:
                continue
            host_spawn(list(tool))
        except (OSError, subprocess.SubprocessError):
            continue
        return tool[0]
    return ""


# --- image catalog -----------------------------------------------------------
#
# shared/catalog/README.md is the contract and shared/catalog/fixtures/ the
# answers every frontend must give; tests/test_catalog_contract.py reads the
# fixture through this parser. Nothing here downloads anything, and
# `fallback_flatpaks` is never read.

# The reader is bootc_shared.catalog, which GNOME also uses: the search
# path, what a leaf inherits, the types, the Flatpak-list rule, the default
# selection and the NVIDIA table. What is here is this frontend's view of
# it: objects with attributes, which the pages read.
resolve_flatpaks = shared_catalog.resolve_flatpaks
# The desktop extras (shared/catalog/README.md, "Desktop extras"): the
# leaf's `extras` attribute is the object or None.
EXTRAS = shared_catalog.EXTRAS
resolve_extras = shared_catalog.resolve_extras


class ImageLeaf:
    """One installable image: a view of the leaf that bootc_shared.catalog
    resolved, plus the words of the node itself that a page shows."""

    def __init__(self, node, leaf):
        for key, value in leaf.items():
            setattr(self, key, value)
        self.path = list(leaf["path"])
        self.filesystems = list(leaf["filesystems"])
        self.flatpaks = None if leaf["flatpaks"] is None else list(leaf["flatpaks"])
        # A flat list shows the breadcrumb; a leaf with no name anywhere
        # above it still needs a row label.
        self.breadcrumb = leaf["breadcrumb"] or leaf["label"]
        desc, subtitle = node.get("desc", ""), node.get("subtitle", "")
        self.desc = desc if isinstance(desc, str) else ""
        self.subtitle = subtitle if isinstance(subtitle, str) else ""


def catalog_leaves(raw):
    """Every installable leaf of a parsed images.json, in catalog order."""
    raw = raw if isinstance(raw, dict) else {}
    return [ImageLeaf(node, leaf) for node, leaf in
            shared_catalog.walk(raw.get("images", []), raw.get("aliases"))]


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
        self.raw = raw
        self.path = path
        default_image = raw.get("default_image", "")
        self.default_image = default_image if isinstance(default_image, str) else ""
        self.leaves = catalog_leaves(raw)
        self.roots = [CatalogRoot(node) for node in raw.get("images", [])
                      if isinstance(node, dict)]

    def _view(self, imgref):
        for leaf in self.leaves:
            if leaf.imgref == imgref:
                return leaf
        return None

    def find(self, imgref):
        """The leaf for `imgref`, or None. The NVIDIA variant of a leaf is
        that leaf (bootc_shared.catalog.find)."""
        found = shared_catalog.find(self.raw, imgref)
        return self._view(found["imgref"]) if found else None

    def needs_user_creation(self, imgref):
        """Whether the install of `imgref` creates an account. An image the
        catalog does not have needs one."""
        return shared_catalog.needs_user_creation(self.raw, imgref)

    def default_leaf(self, branding_default_image=""):
        """The leaf selected at start: the branding's default_image, then
        the catalog's, else None. None means the user must choose; this
        frontend used to select the first name in the alphabet (#289)."""
        selected = shared_catalog.default_imgref(self.raw, branding_default_image)
        return self._view(selected) if selected else None


def read_catalog_file(path):
    """The Catalog in `path`, or None when the file is missing, does not
    parse, or is not an object with an `images` list."""
    raw = shared_catalog.load(path)
    return None if raw is None else Catalog(raw, path)


def load_catalog(paths=None):
    """The first catalog on the search path that loads; an empty Catalog
    when none does. A file that does not load does not stop the search."""
    raw, path = shared_catalog.load_first(images_json_paths() if paths is None else paths)
    return Catalog() if raw is None else Catalog(raw, path)


# --- NVIDIA ------------------------------------------------------------------

# Whether a PCI display device has NVIDIA's vendor id. The probe does not
# report the GPU yet (shared/catalog/README.md, "Image and NVIDIA image"),
# so bootc_shared.hardware reads sysfs, which a Flatpak sees too.
PCI_DEVICES = hardware.PCI_DEVICES
has_nvidia_gpu = hardware.has_nvidia_gpu


def source_and_target(leaf, has_nvidia=False, live=False, offline=()):
    """(image, targetImgref) for a leaf on this machine: the table of
    shared/catalog/README.md, "Image and NVIDIA image"."""
    return shared_catalog.source_and_target(
        leaf.imgref, leaf.nvidia_imgref, has_nvidia, live, offline)


# --- the first account -------------------------------------------------------
#
# shared/account/README.md. DEFAULT_GROUPS is `default_groups` of
# shared/account/groups.json, which bootc_shared.account reads. fisherman
# removes each group the image does not have, so one list is correct for
# every image. This frontend used to send only "wheel", which Ubuntu images
# do not have (#302).
DEFAULT_GROUPS = tuple(shared_account.DEFAULT_GROUPS)


def operator_recipe_path(in_flatpak=None):
    """The ISO builder's recipe.json: the host's /etc, also in a Flatpak."""
    if in_flatpak is None:
        in_flatpak = IN_FLATPAK
    return shared_account.operator_recipe_path(in_flatpak)


def groups_from_operator_recipe(operator_recipe):
    """The account's groups given the operator's recipe (None for no file).
    `user.groups` replaces the default when it is a list of strings, `[]`
    included; anything else keeps the default."""
    return shared_account.resolve_groups(operator_recipe, DEFAULT_GROUPS)


def account_groups(path=None):
    """The supplementary groups of the first account. Only `user.groups` is
    read from the operator's file."""
    return groups_from_operator_recipe(
        shared_account.read_operator_recipe(path or operator_recipe_path()))


class LiveSystem:
    """"Install this system" on live media, laid out the way the ISO builder
    probed the running image: the operator recipe's `bootloader`,
    `composeFsBackend` and `filesystem`. The GNOME frontend reads the same
    three keys (bootc_installer/utils/processor.py). fisherman does not find
    the backend from the image, so without them a composefs-native image
    (tunaOS grouper) goes down bootc's ostree path and fails "bootupd is
    required for ostree-based installs" (#343).

    It has ImageLeaf's backend attributes, so the setup page and the recipe
    read either one the same way."""

    imgref = ""

    def __init__(self, operator_recipe):
        recipe = operator_recipe if isinstance(operator_recipe, dict) else {}
        bootloader = recipe.get("bootloader")
        filesystem = recipe.get("filesystem")
        self.bootloader = bootloader if isinstance(bootloader, str) else ""
        self.composefs = recipe.get("composeFsBackend") is True
        self.filesystem = filesystem if isinstance(filesystem, str) else ""
        # As for a leaf that names one `filesystem`: that one is the choice.
        self.filesystems = [self.filesystem] if self.filesystem else []


def live_system(path=None):
    """The running live image's install layout (LiveSystem) from the
    operator recipe; an absent or unreadable file gives fisherman's
    defaults."""
    return LiveSystem(shared_account.read_operator_recipe(path or operator_recipe_path()))


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
                 extras=None, needs_user=True, username="", fullname="",
                 password="", groups=None, branding=None, locale="",
                 keyboard_layout="", timezone=""):
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
      * `locale`, `keyboard_layout` and `timezone` are the identity
        page's picks; "" writes no key, and the image keeps its own
        (region_fields).
      * `extras` is the leaf's object or None. None writes no key, and
        fisherman looks the image up in the catalog that it finds.
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
    recipe.update(experimental_for(filesystem))
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
    if extras is not None:
        recipe["extras"] = {key: bool(extras.get(key, False)) for key in EXTRAS}
    recipe.update(region_fields(locale=locale, keyboard_layout=keyboard_layout,
                                timezone=timezone))
    if needs_user and username:
        recipe["user"] = {
            "username": username,
            "fullname": fullname,
            "password": password,
            "groups": list(DEFAULT_GROUPS if groups is None else groups),
        }
    return recipe


def region_fields(locale="", keyboard_layout="", timezone=""):
    """The recipe's `locale`, `keyboard` and `timezone` (#292): a key for
    each value the person picked, none for "". `keyboard` is an XKB layout,
    the name that `localectl list-x11-keymap-layouts` gives."""
    fields = {}
    if locale:
        fields["locale"] = locale
    if keyboard_layout:
        fields["keyboard"] = {"layout": keyboard_layout}
    if timezone:
        fields["timezone"] = timezone
    return fields


def is_region_field(field):
    """Whether a validate problem's field is one of region_fields' keys."""
    return field in ("locale", "keyboard", "timezone") or field.startswith("keyboard.")


def experimental_for(filesystem):
    """The `experimental` key for a filesystem. fisherman refuses zfs
    unless the recipe accepts it (no VM test boots ZFS): `zfs_experimental`.
    The page that picks the filesystem sends it in the same fragment."""
    return {"experimental": ["zfs"]} if filesystem == "zfs" else {}


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
        extras=leaf.extras, needs_user=leaf.needs_user_creation, **fields)


def recipe_problems(recipe):
    """Why a complete recipe (the --autoinstall file) cannot start, as lines
    for the result page; [] when it can.

    The wizard checks a recipe field by field while the person types;
    --autoinstall skipped every check, so a bad file failed inside the root
    process. This asks `fisherman validate --json -`, unprivileged. When
    fisherman cannot be asked the recipe starts: the install runs the same
    rules before it touches a disk.
    """
    if not isinstance(recipe.get("disk"), str) or not recipe["disk"].strip():
        return [_("The recipe names no installation disk.")]
    try:
        result = fisherman_validate.run(fisherman_command("validate-full"), recipe)
    except (fisherman_validate.ValidateError, StageError):
        return []
    lines = [fisherman_validate.render(problem, BRANDING.text)
             for problem in fisherman_validate.problems(result)]
    lines = [line for line in lines if line]
    if not lines and result.get("valid") is False:
        lines = [_("fisherman did not accept the recipe.")]
    return lines


def recipe_stdin(recipe):
    """The bytes the app writes to fisherman's stdin (`fisherman -`)."""
    return json.dumps(recipe).encode("utf-8")


def fisherman_argv(in_flatpak=None, live=None, host_path=None):
    """The argv that runs fisherman with privileges, the recipe on stdin."""
    return fisherman_command("install", in_flatpak=in_flatpak, live=live,
                             host_path=host_path)


def shell_line(argv):
    """`argv` as one shell line, for the install log."""
    return " ".join(shlex.quote(a) for a in argv)


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


class InstallLog:
    """The persistent install log. Each line goes through the recovery-key
    redaction before it reaches the file (#337).

    fisherman prints the TPM recovery key in its output. The key is for the
    recovery-key page and nowhere else: a user attaches this file to a bug
    report. The line keeps its event type and loses the value
    (shared/progress/README.md, "Recovery key in a log"). The redactor
    remembers the key, so a later line that repeats it loses it too.
    """

    def __init__(self, stream):
        self._stream = stream
        self._redactor = redact.LogRedactor()

    def write(self, text):
        """Write `text` (one line, or some lines) without the key, and
        return what was written."""
        clean = "".join(self._redactor.line(line)
                        for line in text.splitlines(keepends=True))
        self._stream.write(clean)
        return clean

    def flush(self):
        self._stream.flush()

    def close(self):
        self._stream.close()


def open_install_log():
    """Open the persistent install log for appending, creating it 0600.
    The object redacts the recovery key from each line it writes."""
    path = install_log_path()
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    return InstallLog(os.fdopen(fd, "a", encoding="utf-8"))
