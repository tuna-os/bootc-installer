"""Backend plumbing shared by every page: catalog, disks, offline stores,
recipe emission, and fisherman invocation. See ../INSTALLER-FRONTENDS.md."""

import json
import os
import shlex
import subprocess
import tempfile

from tuna_installer_xfce import branding, tpm_probe

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


# The TPM probe, as a function for the same reason dry_run() is one, and with
# an override for the same reason BOOTC_DEMO exists.
#
# The two TPM encryption choices are hidden when this is false, so a capture
# taken on a machine without a TPM -- every CI runner -- silently renders a
# two-option encryption page. The screenshots are what docs/PARITY.md is read
# off, so this frontend was recorded as having no TPM support at all, when in
# fact it offers both TPM modes and has since the encryption page was written.
# The capture harness sets the override so the walkthrough shows what the
# installer can actually do rather than what the runner's hardware allows.
#
# It only ever makes the options VISIBLE. Choosing one still writes an ordinary
# recipe, and fisherman is what fails, later and loudly, if there is no TPM to
# enrol against.
# The probe itself is shared/tpm/README.md: read tpm_version_major and accept
# only "2". Testing /sys/class/tpm/tpm0 for existence, which this did, is true
# for a TPM 1.2 device too, so a 1.2 machine was offered tpm2-luks and the
# install failed at enrolment -- after the disk had been partitioned.
def has_tpm(root="/"):
    if tpm_probe.fake_tpm_requested():
        return True
    return tpm_probe.probe_tpm2(root)

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
FISHERMAN_CMD = (
    ["flatpak-spawn", "--host", "pkexec", "/usr/local/bin/fisherman"]
    if IN_FLATPAK
    else ["sudo", "/usr/local/bin/fisherman"]
)

IMAGES_JSON_PATHS = [
    os.environ.get("FISHERMAN_IMAGES_PATH", ""),
    os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                 "tuna-installer/images.json"),
    "/etc/tuna-installer/images.json",
    "/app/share/fisherman/data/images.json",
    "/usr/share/fisherman/data/images.json",
]

OFFLINE_STORES_FILE = "/etc/tuna-installer/offline-stores"
OFFLINE_STORES_ENV = "TUNA_OFFLINE_STORES"
OFFLINE_STORE_DEFAULT = "/usr/share/tuna-installer/oci-store"


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

class ImageNode:
    """One entry of images.json with root->leaf field inheritance resolved.

    Current images.json uses registry+tag; older files use imgref. Handle both.
    """

    def __init__(self, raw, parent=None):
        self.name = raw.get("name", "")
        self.desc = raw.get("desc", "")
        self.subtitle = raw.get("subtitle", "")
        p = parent
        self.registry = raw.get("registry") or (p.registry if p else "")
        tag = raw.get("tag", "")
        self.imgref = raw.get("imgref") or (f"{self.registry}:{tag}" if self.registry and tag else "")
        self.flatpaks = raw.get("flatpaks") or (p.flatpaks if p else "")
        self.bootloader = raw.get("bootloader") or (p.bootloader if p else "")
        self.filesystem = raw.get("filesystem") or (p.filesystem if p else "")
        self.composefs = raw.get("composefs", p.composefs if p else False)
        self.needs_user_creation = raw.get(
            "needs_user_creation", p.needs_user_creation if p else True)
        self.children = [ImageNode(c, self) for c in raw.get("children", [])]

    def is_leaf(self):
        return bool(self.imgref) and not self.children

    def leaves(self):
        if self.is_leaf():
            yield self
        for c in self.children:
            yield from c.leaves()


def load_catalog():
    """Return (default_image, fallback_flatpaks, [ImageNode]) or Nones."""
    for path in IMAGES_JSON_PATHS:
        if path and os.path.exists(path):
            with open(path) as f:
                raw = json.load(f)
            nodes = [ImageNode(n) for n in raw.get("images", [])]
            return raw.get("default_image", ""), raw.get("fallback_flatpaks", []), nodes
    return "", [], []


# --- offline / live-ISO detection --------------------------------------------

def live_iso_image():
    """Return the running bootc image ref when booted from live media, else None.

    Live-ISO mode means the recipe may omit `image` entirely (bootc installs
    the running container)."""
    r = host_run(["bootc", "status", "--json"])
    if r.returncode != 0:
        return None
    try:
        status = json.loads(r.stdout)
        booted = status.get("status", {}).get("booted") or {}
        ref = booted.get("image", {}).get("image", {}).get("image", "")
    except (json.JSONDecodeError, AttributeError):
        return None
    if not ref:
        return None
    with open("/proc/cmdline") as f:
        live = "rd.live.image" in f.read()
    return ref if (live or os.path.exists("/run/ostree-live")) else None


def offline_stores():
    """Paths of embedded OCI stores present on this medium."""
    stores = []
    env = os.environ.get(OFFLINE_STORES_ENV, "")
    if env:
        stores += env.split(":")
    if os.path.exists(OFFLINE_STORES_FILE):
        with open(OFFLINE_STORES_FILE) as f:
            stores += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    stores.append(OFFLINE_STORE_DEFAULT)
    return [s for s in dict.fromkeys(stores) if os.path.isdir(s)]


def offline_images(stores):
    """Set of image refs available across the given store roots."""
    refs = set()
    for store in stores:
        r = host_run(["podman", "images", "--root", store, "--format", "json"])
        if r.returncode != 0:
            continue
        try:
            for img in json.loads(r.stdout):
                refs.update(img.get("Names") or [])
        except json.JSONDecodeError:
            continue
    return refs


# --- disks --------------------------------------------------------------------

def candidate_disks():
    """Installable disks: real disks, not the live medium, not removable-boot."""
    r = host_run(["lsblk", "-J", "-b", "-o",
                  "NAME,PATH,SIZE,MODEL,TYPE,RM,MOUNTPOINTS,TRAN"])
    if r.returncode != 0:
        return []
    disks = []
    for dev in json.loads(r.stdout).get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        mounts = json.dumps(dev.get("mountpoints", []))
        if "/run/initramfs/live" in mounts or "/run/media/iso" in mounts:
            continue
        disks.append({
            "path": dev["path"],
            "model": (dev.get("model") or "Unknown disk").strip(),
            "size": int(dev.get("size") or 0),
            "transport": dev.get("tran") or "",
        })
    return disks


def human_size(nbytes):
    val, unit = float(nbytes), "B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1000 or unit == "TB":
            break
        val /= 1000
    return f"{val:.1f} {unit}".replace(".0 ", " ")


# --- recipe -------------------------------------------------------------------

def build_recipe(*, disk, filesystem, btrfs_subvolumes=False,
                 encryption_type="none", passphrase="", image="",
                 hostname="", bootloader="", composefs=False, flatpaks="",
                 stores=(), needs_user=True, username="", fullname="",
                 password="", branding=None):
    """Assemble the fisherman recipe from already-resolved values.

    This is the contract with the install backend — the same document the KDE,
    COSMIC and Niri forks each build their own way (tuna-os/tunaOS#1197) — so
    it is the one piece of this frontend most worth being able to test without
    a display. It used to live in `InstallerWindow.build_recipe`, reading
    `Gtk.Entry.get_text()` and `Gtk.CheckButton.get_active()` inline, which
    made every conditional below reachable only by constructing a GTK window.

    Callers pass plain values; the widget layer stays responsible for reading
    them off the pages. The conditionals are the ones that were in the method,
    unchanged:

      * `btrfsSubvolumes` is only meaningful on btrfs, and is False elsewhere
        regardless of what the Advanced checkbox says.
      * The passphrase is only emitted for an encryption type that takes one,
        so a stale entry left in the box cannot leak into a recipe for an
        unencrypted install.
      * `bootloader`, `composeFsBackend` and `flatpaks` are catalog-leaf
        properties: absent keys mean "let fisherman decide", which is not the
        same as an empty value.
      * A `@`-prefixed flatpaks field is a catalog reference, not a package
        list, and is not passed through.
      * The user block is omitted entirely when the image creates its own
        first user, or when no username was typed.
    """
    recipe = {
        "disk": disk,
        "filesystem": filesystem,
        "btrfsSubvolumes": filesystem == "btrfs" and btrfs_subvolumes,
        "encryption": {"type": encryption_type},
        "image": image,
        "selinuxDisabled": True,
        "hostname": hostname,
        # The branding's id, never a literal: see resolve_branding().
        "distroID": (branding or BRANDING).id,
    }
    if "passphrase" in encryption_type:
        recipe["encryption"]["passphrase"] = passphrase
    if bootloader:
        recipe["bootloader"] = bootloader
    if composefs:
        recipe["composeFsBackend"] = True
    if flatpaks and not flatpaks.startswith("@"):
        recipe["flatpaks"] = flatpaks.split()
    # Always pass detected stores; fisherman ignores unhelpful ones (§4B).
    if stores:
        recipe["additionalImageStores"] = stores
    if needs_user and username:
        recipe["user"] = {
            "username": username,
            "fullname": fullname,
            "password": password,
            "groups": ["wheel"],
        }
    return recipe


def write_recipe(recipe):
    """Write the recipe 0600 in a fresh private directory; return its path.

    The recipe may hold a LUKS passphrase and a user password — never put it
    somewhere world-readable.

    The DIRECTORY matters as much as the file mode here. This used to create a
    fixed `<base>/tuna-installer` with `exist_ok=True`, and when
    XDG_RUNTIME_DIR is unset — the default under `sudo` (env_reset strips it),
    from a TTY, and from any launcher that is not a logind session — `base` is
    /tmp, so the path was the constant `/tmp/tuna-installer`. `makedirs` with
    `exist_ok=True` applies its `mode` only when it actually creates the
    directory: a pre-existing 0777 directory was accepted as-is, handing an
    unprivileged local user ownership of the directory every recipe lands in.

    mkstemp kept the file itself unpredictable and 0600, so the passphrase was
    never directly readable. The exposure was control of the PATH, and the path
    is what gets handed to root: `fisherman_argv()` passes it to
    sudo/pkexec fisherman. Owning the directory means unlinking our recipe and
    dropping a different one at the same name in the window before fisherman
    opens it — root then installs an attacker-chosen image, onto an
    attacker-chosen disk, with encryption turned off and a known user password.

    mkdtemp closes that: it creates a 0700 directory with an unpredictable name
    and O_EXCL semantics, so it cannot be pre-created and its mode cannot be
    inherited from someone else's. Callers should remove the returned file's
    directory (see `recipe_dir`) once fisherman has exited.
    """
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    rundir = tempfile.mkdtemp(prefix="tuna-installer-", dir=base)
    fd, path = tempfile.mkstemp(dir=rundir, suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(recipe, f, indent=2)
    os.chmod(path, 0o600)
    return path


def recipe_dir(recipe_path):
    """The private directory `write_recipe` created for `recipe_path`."""
    return os.path.dirname(recipe_path)


def fisherman_argv(recipe_path):
    return FISHERMAN_CMD + [recipe_path]


def fisherman_shell(recipe_path):
    return " ".join(shlex.quote(a) for a in fisherman_argv(recipe_path))


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
