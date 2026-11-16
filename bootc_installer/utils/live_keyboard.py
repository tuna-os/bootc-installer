"""The keyboard layout the live session types with now (#411).

A recipe without a keyboard step (the Dakota ISO's has welcome, image,
disk and encryption) used to send no `keyboard`. The LUKS passphrase was
typed in whatever layout the live session had, and the installed system's
prompt at boot used the image's default, so a passphrase typed in another
layout did not match (projectbluefin/dakota#1299). The encryption page
now records this layout, and `region_fields` sends it when no keyboard
step chose one. fisherman then writes it to vconsole.conf and, for an
encrypted install, rd.vconsole.keymap.
"""

from __future__ import annotations

import ast
import logging

from bootc_installer.utils.host import HostExecutor, Scope, default_executor

logger = logging.getLogger("Installer::LiveKeyboard")

SCHEMA = "org.gnome.desktop.input-sources"


def _sources(text: str) -> list:
    """`gsettings get` output of an a(ss) key, as a list of (type, id)."""
    text = (text or "").strip()
    if text.startswith("@a(ss)"):
        text = text[len("@a(ss)"):].strip()
    try:
        value = ast.literal_eval(text) if text else []
    except (ValueError, SyntaxError):
        return []
    if not isinstance(value, (list, tuple)):
        return []
    return [tuple(v) for v in value
            if isinstance(v, (list, tuple)) and len(v) == 2
            and all(isinstance(p, str) for p in v)]


def parse_active_layout(sources_text: str, mru_text: str = "") -> dict | None:
    """The active XKB layout as the recipe's `keyboard`, or None.

    GNOME Shell keeps the source in use first in `mru-sources`; it is one of
    `sources`. Without that, the first of `sources` is the one in use. Only
    `xkb` sources have an XKB layout ("de" or "de+neo"); an input method
    (`ibus`) does not, and neither does an empty list.
    """
    sources = _sources(sources_text)
    mru = _sources(mru_text)
    active = next((s for s in mru if s in sources), None) or (sources[0] if sources else None)
    if active is None or active[0] != "xkb" or not active[1]:
        return None
    layout, _, variant = active[1].partition("+")
    if not layout:
        return None
    keyboard = {"layout": layout}
    if variant:
        keyboard["variant"] = variant
    return keyboard


def active_layout(executor: HostExecutor | None = None) -> dict | None:
    """Ask the host session for its active layout. None when it cannot say."""
    executor = executor or default_executor()
    answers = []
    for key in ("sources", "mru-sources"):
        result = executor.run(["gsettings", "get", SCHEMA, key], scope=Scope.HOST, timeout=3)
        if not result.ok:
            logger.info("Cannot read %s %s: %s", SCHEMA, key, result.describe())
            if key == "sources":
                return None
            answers.append("")
            continue
        answers.append(result.stdout)
    return parse_active_layout(*answers)
