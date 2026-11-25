"""fishermand Varlink client: the daemon backend (tuna-os/fisherman#512).

The legacy backend shells out to `fisherman` (`fisherman probe`,
`fisherman validate`, `fisherman -` on stdin). This module talks to
`fishermand` over Varlink instead (JSON objects on a UNIX socket, NUL
terminated; `shared/client/README.md`). Passphrases and recovery keys pass
through call parameters; neither this module nor its callers log them.

Socket choice, in order: explicit paths, `$FISHERMAND_SOCKET_DIR`, then the
defaults below. The daemon serves every interface on every socket, so one
path is enough; four knobs exist because gnome-setup connects per
interface. The spec (`shared/flow/screens.yaml`) leaves the Fisherman
socket path unset, so every path here is configurable and tests inject a
temporary directory.
"""

import json
import os
import sys

DEFAULT_SOCKETS = {
    "fisherman": "/run/fisherman/io.tunaos.Fisherman",
    "sysinstall": "/run/systemd/io.systemd.SysInstall",
    "cryptenroll": "/run/systemd/io.systemd.CryptEnroll",
    "shutdown": "/run/systemd/io.systemd.Shutdown",
}

# The file name each socket gets under --socket-dir: the interface name
# (fishermand --socket-dir puts all four there under those names).
SOCKET_FILES = {
    "fisherman": "io.tunaos.Fisherman",
    "sysinstall": "io.systemd.SysInstall",
    "cryptenroll": "io.systemd.CryptEnroll",
    "shutdown": "io.systemd.Shutdown",
}

SOCKET_DIR_ENV = "FISHERMAND_SOCKET_DIR"


def _client_dir():
    """Where varlink_client.py and sizes.py live: the shared client sources
    in a checkout, the installed copies in the Flatpak (flatpak/
    org.tunaos.InstallerXfce.json copies them next to bootc_shared)."""
    here = os.path.dirname(os.path.abspath(__file__))
    checkout = os.path.normpath(os.path.join(
        here, "..", "..", "..", "shared", "client", "python"))
    if os.path.isfile(os.path.join(checkout, "varlink_client.py")):
        return checkout
    flatpak = "/app/lib/tuna-installer-xfce/varlink"
    if os.path.isfile(os.path.join(flatpak, "varlink_client.py")):
        return flatpak
    return checkout


def _load_client():
    directory = _client_dir()
    if directory not in sys.path:
        sys.path.insert(0, directory)
    import varlink_client
    return varlink_client

def resolve_sockets(socket_dir=None, **overrides):
    """The four socket paths: explicit keywords win, then `socket_dir` (or
    `$FISHERMAND_SOCKET_DIR`), then the defaults. Unknown keywords fail."""
    unknown = set(overrides) - set(DEFAULT_SOCKETS)
    if unknown:
        raise ValueError(f"unknown sockets: {sorted(unknown)}")
    base = socket_dir or os.environ.get(SOCKET_DIR_ENV)
    sockets = dict(DEFAULT_SOCKETS)
    if base:
        for name in sockets:
            sockets[name] = os.path.join(base, SOCKET_FILES[name])
    sockets.update({k: v for k, v in overrides.items() if v is not None})
    return sockets


class DaemonError(Exception):
    """fishermand could not be reached, or answered out of protocol."""


class Daemon:
    """One fishermand, reached through its four sockets.

    One connection carries one call at a time, so streaming calls
    (`Install`, `ListCandidateDevices` with subscribe) own their
    connection for the stream, and `cancel()` opens a second one. Every
    method returns plain dicts and lists of the JSON replies.
    """

    def __init__(self, sockets=None, **overrides):
        self.sockets = resolve_sockets(**(sockets or {}), **overrides)
        self._client = _load_client()

    def _connection(self, name):
        try:
            return self._client.Connection(self.sockets[name])
        except OSError as exc:
            raise DaemonError(f"cannot reach {name} at "
                              f"{self.sockets[name]}: {exc}") from exc

    def available(self):
        """Whether a daemon answers GetInfo on the Fisherman socket."""
        try:
            with self._connection("fisherman") as connection:
                connection.get_info()
        except (DaemonError, self._client.ProtocolError, ValueError):
            return False
        return True

    def requirements(self):
        with self._connection("fisherman") as connection:
            return connection.call("io.tunaos.Fisherman.Requirements", {})

    def probe(self):
        with self._connection("fisherman") as connection:
            return connection.call("io.tunaos.Fisherman.Probe", {})

    def list_candidates(self, definitions=(), subscribe=False):
        """Yield SysInstall candidate devices, in the daemon's order. With
        `subscribe` the stream stays open (`action` add/ready/remove)."""
        with self._connection("sysinstall") as connection:
            yield from connection.call_more(
                "io.systemd.SysInstall.ListCandidateDevices",
                {"definitions": list(definitions), "subscribe": subscribe})

    def validate(self, config, partial=True):
        with self._connection("fisherman") as connection:
            return connection.call("io.tunaos.Fisherman.Validate",
                                   {"config": config, "partial": partial})

    def configure_target(self, **choices):
        """Store account/locale choices; only the given keys are sent. The
        daemon answers validation problems as data, like Validate."""
        with self._connection("fisherman") as connection:
            return connection.call("io.tunaos.Fisherman.ConfigureTarget",
                                   dict(choices))

    def install(self, config):
        """Yield Install events (dicts) until the terminal one (complete,
        failed or cancelled). Needs `more`; the last reply has no
        `continues` flag."""
        with self._connection("fisherman") as connection:
            yield from connection.call_more(
                "io.tunaos.Fisherman.Install",
                {"config": config, "confirmed": True})

    def cancel(self):
        """Ask a running install to stop and clean up. Idempotent: safe to
        call when idle. Opens its own connection, as the install owns its."""
        with self._connection("fisherman") as connection:
            return connection.call("io.tunaos.Fisherman.Cancel", {})

    def make_recovery_key(self):
        with self._connection("cryptenroll") as connection:
            return connection.call(
                "io.systemd.CryptEnroll.MakeRecoveryKey", {})["recoveryKey"]

    def enroll_recovery_key(self, node, recovery_key, unlock_password=""):
        """Enrol a recovery key, unlocking with the empty password the
        installer set (what gnome-setup does after its disk-passphrase
        page). Returns the reply parameters."""
        with self._connection("cryptenroll") as connection:
            return connection.call("io.systemd.CryptEnroll.Enroll", {
                "node": node, "mechanism": "recovery",
                "recoveryKey": recovery_key,
                "unlockPassword": unlock_password})

    def handoff(self, mode=None):
        """Hand over to the installed system. `mode` is migrate, soft_reboot
        or reboot; omitted, the daemon picks. Only valid after a completed
        install."""
        parameters = {} if mode is None else {"mode": mode}
        with self._connection("fisherman") as connection:
            return connection.call("io.tunaos.Fisherman.Handoff", parameters)

    def shutdown(self, action):
        """`reboot`, `poweroff` or `soft_reboot` over io.systemd.Shutdown."""
        methods = {"reboot": "Reboot", "poweroff": "PowerOff",
                   "soft_reboot": "SoftReboot"}
        try:
            method = methods[action]
        except KeyError:
            raise ValueError(f"unknown shutdown action {action!r}") from None
        with self._connection("shutdown") as connection:
            return connection.call("io.systemd.Shutdown." + method, {})


# Recipe types use dashes (shared/recipe/encryption-choices.json); the
# daemon uses underscores (io.tunaos.Fisherman.varlink, type Encryption).
# The names come from the file, not from a list kept here.
def daemon_encryption_type(recipe_type):
    return (recipe_type or "none").replace("-", "_")


def recipe_to_config(recipe, install_mode=None):
    """The daemon's Install/Validate Config for a legacy recipe dict.

    Only keys the daemon owns are carried: disk, encryption, user and
    hostname. Filesystem, locale, keyboard and time zone are target
    configuration, not install configuration; they travel over
    ConfigureTarget. `install_mode` is erase or free_space, from the
    wipe-or-free page; omitted, the key is left out. Groups have no daemon
    field: wheel membership becomes `admin`."""
    recipe = recipe or {}
    config = {}
    if recipe.get("disk"):
        config["disk"] = recipe["disk"]
    if install_mode is not None:
        if install_mode not in ("erase", "free_space"):
            raise ValueError(f"unknown install mode {install_mode!r}")
        config["installMode"] = install_mode
    encryption = recipe.get("encryption") or {}
    enc_type = daemon_encryption_type(encryption.get("type"))
    entry = {"type": enc_type}
    if encryption.get("passphrase"):
        entry["passphrase"] = encryption["passphrase"]
    config["encryption"] = entry
    user = recipe.get("user") or {}
    if user.get("username"):
        config["user"] = {
            "username": user["username"],
            "fullName": user.get("fullname") or None,
            "password": user.get("password") or None,
            "admin": "wheel" in (user.get("groups") or []),
        }
    if recipe.get("hostname"):
        config["hostname"] = recipe["hostname"]
    return config


def recipe_to_target(recipe):
    """The ConfigureTarget choices for a legacy recipe dict: user, hostname,
    locale, keymap, time zone. Only picked values are sent."""
    recipe = recipe or {}
    choices = {}
    user = recipe.get("user") or {}
    if user.get("username"):
        choices["user"] = {
            "username": user["username"],
            "fullName": user.get("fullname") or None,
            "password": user.get("password") or None,
        }
        groups = user.get("groups") or []
        if groups:
            choices["user"]["admin"] = "wheel" in groups
    if recipe.get("hostname"):
        choices["hostname"] = recipe["hostname"]
    if recipe.get("locale"):
        choices["locale"] = recipe["locale"]
    keyboard = recipe.get("keyboard") or {}
    if keyboard.get("layout"):
        choices["keymap"] = keyboard["layout"]
    if recipe.get("timezone"):
        choices["timeZone"] = recipe["timezone"]
    privacy = recipe.get("privacy") or {}
    if isinstance(privacy, dict) and "locationServices" in privacy:
        choices["privacy"] = {
            "locationServices": bool(privacy["locationServices"])}
    if recipe.get("autologin"):
        choices["autologin"] = True
    return choices


TRANSPORT_LABELS = {
    "ata": "ATA", "sata": "SATA", "nvme": "NVMe", "usb": "USB",
    "mmc": "MMC", "virtio": "VirtIO",
}


def gate_to_unmet(gates):
    """Legacy `system.unmet` ids (ram, cpu, uefi) for Requirements gates."""
    ids = {"ram": "ram", "cpu": "cpu", "firmware": "uefi"}
    return [ids[gate["id"]] for gate in gates or []
            if not gate.get("ok") and gate.get("id") in ids]


def probe_to_legacy(probe_reply, gates=()):
    """The legacy `fisherman probe --json` dict for a daemon Probe reply.

    Feeds the readers every existing page uses (bootc_shared.probe):
    eligible disks with title/size/transport labels, tpm.usable,
    system.unmet/uefi (from Requirements gates), live and an empty offline
    section. The daemon names no offline image stores and no bootc context,
    so those stay empty; pages that need them keep the legacy backend.
    Daemon-only facts (freeBytes, minimalSizeBytes, existingData, intelRst)
    ride along verbatim for the pages that read them."""
    probe_reply = probe_reply or {}
    disks = []
    for disk in probe_reply.get("disks") or []:
        transport = disk.get("transport") or ""
        disks.append({
            "path": disk.get("path", ""),
            "size_bytes": disk.get("sizeBytes", 0),
            "size_label": disk.get("sizeLabel", ""),
            "model": disk.get("model", ""),
            "vendor": disk.get("vendor", ""),
            "transport": transport,
            "transport_label": TRANSPORT_LABELS.get(transport,
                                                   transport.upper()),
            "removable": bool(disk.get("removable")),
            "read_only": False,
            "eligible": bool(disk.get("eligible")),
            "excluded_reason": disk.get("excludedReason") or "",
            "free_bytes": disk.get("freeBytes", 0),
            "minimal_size_bytes": disk.get("minimalSizeBytes", 0),
            "intel_rst": bool(disk.get("intelRst")),
            "existing_data": disk.get("existingData") or {},
        })
    tpm = probe_reply.get("tpm") or {}
    live = probe_reply.get("live") or {}
    unmet = gate_to_unmet(gates)
    firmware = next((g for g in gates or [] if g.get("id") == "firmware"),
                    None)
    return {
        "protocol_version": probe_reply.get("protocolVersion", 1),
        "disks": disks,
        "tpm": {"present": bool(tpm.get("present")),
                "version": tpm.get("version") or "",
                "usable": bool(tpm.get("usable"))},
        "system": {"uefi": bool(firmware.get("ok")) if firmware else True,
                   "meets_requirements": not unmet,
                   "unmet": unmet},
        "live": {"is_live": bool(live.get("isLive")),
                 "live_image": live.get("liveImage") or ""},
        "offline": {"stores": [], "images": []},
        "intel_rst": {"detected": bool((probe_reply.get("intelRst") or {})
                                       .get("detected")),
                      "affected_disks": list((probe_reply.get("intelRst") or {})
                                            .get("affectedDisks") or [])},
        "handoff": probe_handoff(probe_reply),
    }


HANDOFF_MODES = ("migrate", "soft_reboot", "reboot")


def probe_handoff(probe_reply):
    """The handoff mode for the handoff page, as {"mode", "reason"}: the
    daemon decides the mode and reports it in Probe. A missing or unknown
    field means reboot."""
    raw = (probe_reply or {}).get("handoff") or {}
    mode = str(raw.get("mode") or "reboot").replace("-", "_")
    if mode not in HANDOFF_MODES:
        mode = "reboot"
    return {"mode": mode, "reason": raw.get("reason") or ""}


def daemon_event_to_line(event):
    """One legacy progress-protocol line (dict) for a daemon Install event.

    Lets the install page reuse its parser, log pane and bar
    (shared/progress/README.md): step_started becomes a `step` line with
    the daemon's own overallPct, progress a `substep`, warning and
    step_finished `info` lines, complete a `complete` line, failed an
    `error` line carrying the daemon's reason as the code. Cancelled needs
    no line: the caller ends the install as a cancel."""
    kind = (event or {}).get("event", "")
    step_id = event.get("stepId")
    overall = event.get("overallPct")
    message = event.get("message") or ""
    line = {"timestamp": "1970-01-01T00:00:00Z", "elapsed_ms": 0}
    if kind == "step_started":
        line.update({"type": "step",
                     "step": (event.get("stepIndex") or 0) + 1,
                     "total_steps": event.get("totalSteps") or 0,
                     "step_name": message or (step_id or ""),
                     "step_id": step_id or ""})
        if overall is not None:
            line["overall_pct"] = overall
    elif kind == "progress":
        line.update({"type": "substep", "message": message})
        if overall is not None:
            line["overall_pct"] = overall
    elif kind in ("step_finished", "warning"):
        line.update({"type": "info",
                     "message": message or (step_id or "")})
    elif kind == "complete":
        line.update({"type": "complete", "message": message,
                     "overall_pct": 100})
    elif kind == "failed":
        line.update({"type": "error", "message": message,
                     "code": event.get("reason") or "install_failed",
                     "step_id": step_id or "",
                     "disk_changed": False,
                     "cleanup": event.get("nextAction") or ""})
    elif kind == "cancelled":
        line.update({"type": "info", "message": message or "Cancelled"})
    else:
        line.update({"type": "info", "message": message or kind})
    return line


TERMINAL_EVENTS = ("complete", "failed", "cancelled")


def is_terminal(event):
    """Whether an Install event ends the install."""
    return (event or {}).get("event") in TERMINAL_EVENTS


def line_text(line):
    """The JSON wire text of a translated legacy line."""
    return json.dumps(line)
