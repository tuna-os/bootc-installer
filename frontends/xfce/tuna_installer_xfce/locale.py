"""Keyboard, locale, timezone and connectivity checks.

GTK-free helpers:

- The identity page offers the keyboard layout and applies it to the live
  session (setxkbmap), so the passphrase a person types is the one they
  mean. It is labelled "this session only": the recipe has no locale,
  keyboard or timezone field yet (tuna-os/fisherman#405), so nothing here
  reaches the installed system.
- The language and timezone readers have no caller in the wizard now. The
  page had a combo for each and nothing read the values (#292), so the
  combos went. The readers stay for the recipe fields.
- has_connectivity() is the probe behind the confirm page's network gate;
  needs_network() says when that gate applies.

Every external command has a fallback that needs no daemon: localectl and
timedatectl are absent from minimal live media, and this module must still
offer something on a system that has neither.
"""

import locale
import os
import socket
import subprocess

from bootc_shared import network


def _run(argv, timeout=10):
    """argv's stdout lines, or [] when it cannot run (missing binary, no
    daemon, non-zero exit). A locale control must degrade, never raise."""
    try:
        out = subprocess.run(argv, capture_output=True, text=True,
                             timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def available_languages():
    """Locale names the live system can switch to (`localectl
    list-locales`), or a short built-in list where localectl is absent."""
    found = _run(["localectl", "list-locales", "--no-pager"])
    if found:
        return found
    return ["C", "en_US.UTF-8"]


def current_language():
    """The session's locale (LANG, else LC_ALL), or en_US.UTF-8."""
    for var in ("LC_ALL", "LANG"):
        value = os.environ.get(var, "")
        if value:
            return value
    name, _enc = locale.getlocale()
    if name and name != "C":
        return name + ".UTF-8"
    return "en_US.UTF-8"


def available_keyboard_layouts():
    """X11 layouts localectl knows, or the layouts a decade-old laptop most
    plausibly has (DESIGN.md's brief) where it knows none."""
    found = _run(["localectl", "list-x11-keymap-layouts", "--no-pager"])
    if found:
        return found
    return ["us", "gb", "de", "fr", "es", "it", "pt", "br", "ru", "pl",
            "cz", "se", "no", "dk", "fi", "hu", "gr", "tr", "ua", "il",
            "ara", "jp", "cn"]


def current_keyboard_layout():
    """The live session's layout (`setxkbmap -query`), or "us"."""
    for line in _run(["setxkbmap", "-query"]):
        key, _, value = line.partition(":")
        if key.strip() == "layout":
            return value.strip().split(",")[0].strip() or "us"
    return "us"


def apply_keyboard_layout(layout):
    """Switch the live session to `layout` so typed passphrases match what
    the installed system will read. Best-effort: False, never an exception,
    when setxkbmap is absent (Wayland live media) or refuses."""
    try:
        out = subprocess.run(["setxkbmap", layout], capture_output=True,
                             timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


def available_timezones():
    """Zone names from timedatectl, or the zoneinfo tree where the daemon is
    absent. Directory entries (regions) are skipped; only zones are offered."""
    found = _run(["timedatectl", "list-timezones", "--no-pager"], timeout=15)
    if found:
        return found
    zones = []
    base = "/usr/share/zoneinfo"
    for root, _dirs, files in os.walk(base):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), base)
            if "/" in rel and not rel.startswith(("posix", "right")):
                zones.append(rel)
    return sorted(zones)


def current_timezone():
    """The live session's zone: /etc/localtime's target, else UTC."""
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return "UTC"
    marker = "/zoneinfo/"
    if marker in target:
        return target.split(marker, 1)[1]
    return "UTC"


# What to probe, and in which order, is bootc_shared.network, which GNOME
# also uses: the registry of the selected image first, then the shared
# targets (#301). Either skipping variable forces True for a harness with
# no route out.
SHARED_TARGETS = network.SHARED_TARGETS
DEFAULT_REGISTRY = network.DEFAULT_REGISTRY
# A network check that the screenshot harness must be able to skip: without
# it the capture would stall on the confirm page in a sandbox with no route
# out.
SKIP_ENV_VARS = network.SKIP_ENV_VARS
registry_target = network.registry_target
connectivity_targets = network.connectivity_targets


def has_connectivity(timeout=5, imgref=""):
    """Whether an install image could be downloaded right now: the first of
    connectivity_targets(imgref) that accepts a connection."""
    return network.has_connectivity(imgref, timeout=timeout,
                                    connect=socket.create_connection)


def needs_network(offline_install):
    """Whether the install must download anything: False on live media or
    when the selected image is already in the host's stores (GNOME's
    conn_check.should_show inverted -- that page shows when True)."""
    return not offline_install


def is_uefi():
    """Whether the machine booted in UEFI mode."""
    return os.path.exists("/sys/firmware/efi")
