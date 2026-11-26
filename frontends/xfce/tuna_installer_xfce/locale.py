"""Keyboard, locale, timezone and connectivity checks.

GTK-free helpers:

- The identity page offers a language, a keyboard layout and a time zone
  from these lists. A pick goes into the recipe's `locale`,
  `keyboard.layout` or `timezone` (#292). The keyboard pick also switches
  the live session (setxkbmap), so the passphrase a person types next is
  the one they mean.
- has_connectivity() is the probe behind the confirm page's network gate;
  needs_network() says when that gate applies.

Every external command has a fallback that needs no daemon: localectl and
timedatectl are absent from minimal live media, and this module must still
offer something on a system that has neither.
"""

import json
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
    found = (_run(["localectl", "list-x11-keymap-layouts", "--no-pager"])
             or sorted(keyboard_names(), key=lambda v: keyboard_label(v).casefold()))
    if found:
        return found
    return ["us", "gb", "de", "fr", "es", "it", "pt", "br", "ru", "pl",
            "cz", "se", "no", "dk", "fi", "hu", "gr", "tr", "ua", "il",
            "ara", "jp", "cn"]


XKB_LISTS = ("/usr/share/X11/xkb/rules/evdev.lst",
             "/usr/share/X11/xkb/rules/base.lst")
# The name of each language in that language, as COSMIC shows it.
LANGUAGES = {
    "af": "Afrikaans", "ar": "العربية", "be": "Беларуская", "bg": "Български",
    "bn": "বাংলা", "bs": "Bosanski", "ca": "Català", "cs": "Čeština", "cy": "Cymraeg",
    "da": "Dansk", "de": "Deutsch", "el": "Ελληνικά", "en": "English",
    "eo": "Esperanto", "es": "Español", "et": "Eesti", "eu": "Euskara", "fa": "فارسی",
    "fi": "Suomi", "fr": "Français", "ga": "Gaeilge", "gl": "Galego", "gu": "ગુજરાતી",
    "he": "עברית", "hi": "हिन्दी", "hr": "Hrvatski", "hu": "Magyar", "hy": "Հայերեն",
    "id": "Bahasa Indonesia", "is": "Íslenska", "it": "Italiano", "ja": "日本語",
    "ka": "ქართული", "kk": "Қазақша", "km": "ខ្មែរ", "kn": "ಕನ್ನಡ", "ko": "한국어",
    "lt": "Lietuvių", "lv": "Latviešu", "mk": "Македонски", "ml": "മലയാളം",
    "mr": "मराठी", "ms": "Bahasa Melayu", "nb": "Norsk bokmål", "ne": "नेपाली",
    "nl": "Nederlands", "nn": "Norsk nynorsk", "pa": "ਪੰਜਾਬੀ", "pl": "Polski",
    "pt": "Português", "ro": "Română", "ru": "Русский", "sk": "Slovenčina",
    "sl": "Slovenščina", "sq": "Shqip", "sr": "Српски", "sv": "Svenska", "ta": "தமிழ்",
    "te": "తెలుగు", "th": "ไทย", "tr": "Türkçe", "uk": "Українська", "ur": "اردو",
    "uz": "Oʻzbekcha", "vi": "Tiếng Việt", "zh": "中文",
}
_names = {}


def keyboard_names():
    """{layout: name} from the XKB rules ("de": "German"), {} without them."""
    if "keyboard" not in _names:
        names, inside = {}, False
        for path in XKB_LISTS:
            try:
                with open(path, encoding="utf-8") as rules:
                    for line in rules:
                        if line.startswith("!"):
                            inside = line.split()[1:] == ["layout"]
                        elif inside and len(line.split(None, 1)) == 2:
                            code, name = line.split(None, 1)
                            if code != "custom":
                                names[code] = name.strip()
            except (OSError, UnicodeDecodeError):
                continue
            if names:
                break
        _names["keyboard"] = names
    return _names["keyboard"]


def keyboard_label(layout):
    """"German" for "de"; the bare code when XKB has no name for it."""
    return keyboard_names().get(layout, layout)


ISO_CODES_DIRS = ("/usr/share/iso-codes/json", "/app/share/iso-codes/json")
_iso = {}


def _iso_names(standard, key, field="name"):
    """{code: English name} from iso-codes (`iso_3166-1`, `iso_639-3`), the
    package GNOME's runtime and every desktop image ship; {} without it."""
    cache = (standard, key, field)
    if cache not in _iso:
        names = {}
        for base in ISO_CODES_DIRS:
            try:
                with open(os.path.join(base, standard + ".json"), encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            for row in data.get(standard.replace("iso_", ""), []):
                if row.get(key):
                    names[row[key].lower()] = row.get("common_name") or row.get(field, "")
            break
        _iso[cache] = names
    return _iso[cache]


def territory_name(code):
    """"Germany" for "DE"; the code itself without iso-codes."""
    return _iso_names("iso_3166-1", "alpha_2").get(code.lower()) or code


def language_label(name):
    """"Deutsch (Germany)" for "de_DE.UTF-8": the language in its own words
    where the table has it, else iso-codes' name, and the country's name
    (standard A2: no locale codes for people). The locale name itself only
    when neither knows the language."""
    code, _, territory = name.split(".")[0].split("@")[0].partition("_")
    language = (LANGUAGES.get(code) or _iso_names("iso_639-3", "alpha_2").get(code)
                or _iso_names("iso_639-3", "alpha_3").get(code))
    if not language:
        return name
    return f"{language} ({territory_name(territory)})" if territory else language


def is_language(name):
    """C and POSIX are locales, and no person's language."""
    return name.split(".")[0] not in ("C", "POSIX")


def timezone_label(zone):
    """"Buenos Aires (America/Argentina)": the city first, as a person looks
    for it. The zone's own name stays the value of the row."""
    area, _, city = zone.rpartition("/")
    city = city.replace("_", " ")
    return f"{city} ({area.replace('_', ' ')})" if area else city


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

def apply_language(language):
    """Switch the live session to `language` (localectl set-locale).
    Best-effort like apply_keyboard_layout: False, never an exception."""
    try:
        out = subprocess.run(["localectl", "set-locale", f"LANG={language}"],
                             capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


def apply_timezone(zone):
    """Switch the live session to `zone` (timedatectl set-timezone).
    Best-effort: False, never an exception."""
    try:
        out = subprocess.run(["timedatectl", "set-timezone", zone],
                             capture_output=True, timeout=10)
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
    return sorted(zones + ["UTC"])


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
