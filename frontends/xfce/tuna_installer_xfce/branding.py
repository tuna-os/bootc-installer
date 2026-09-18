"""Product branding: a branding.json first, os-release second, neutral last.

Canonical copy: shared/branding/branding.py. bootc_installer/utils/branding.py
and frontends/xfce/tuna_installer_xfce/branding.py are byte-identical copies
(tests/unit/test_shared_branding.py enforces it). The contract, the key
table and the fixtures the other languages test against are in
shared/branding/README.md.

Two layers:

- identity: name, id, vendor, URLs, logo, default hostname and image;
- flavour: `copy` (every user-facing line a product may rebrand, with
  {name}/{disk} placeholders), `assets` (artwork paths), `store_url` and
  locale-specific `confirm_quotes`.

The neutral copy lives in shared/branding/copy-defaults.json; COPY_DEFAULTS
below is that file verbatim (the same test checks it), so this module needs
no data file at runtime.

No GTK, no gettext, nothing but the standard library, so every frontend and
every test can import it as-is.
"""

import json
import os
import shlex
from dataclasses import asdict, dataclass, field

ENV_FILE = "BOOTC_INSTALLER_BRANDING"
ENV_NAME = "BOOTC_INSTALLER_PRODUCT_NAME"

# Host first: inside a Flatpak /etc is the runtime's, the host's is under
# /run/host. The first readable file wins; files are not merged.
BRANDING_PATHS = [
    "/run/host/etc/bootc-installer/branding.json",
    "/run/host/usr/share/bootc-installer/branding.json",
    "/etc/bootc-installer/branding.json",
    "/usr/share/bootc-installer/branding.json",
]
OS_RELEASE_PATHS = [
    "/run/host/etc/os-release",
    "/run/host/usr/lib/os-release",
    "/etc/os-release",
    "/usr/lib/os-release",
]

NEUTRAL_NAME = "Linux"
NEUTRAL_ID = "linux"

KEYS = (
    "name", "id", "vendor", "home_url", "docs_url", "support_url",
    "logo", "default_hostname", "default_image",
)

# Common to every frontend. Anything one desktop alone can show goes under
# extensions.<frontend> in the branding file.
ASSET_KEYS = ("welcome_image", "complete_image", "store_qr")

# shared/branding/copy-defaults.json, verbatim.
COPY_DEFAULTS_JSON = r'''{
  "_comment": "Neutral defaults for every user-facing line a product may rebrand. Every frontend renders every key (docs/PARITY.md). A branding.json `copy` object overrides any key; an empty string hides the line. Placeholders: {name} = product name, {disk} = the disk that will be erased. Copies of this file in each frontend tree must stay byte-identical (tests/unit/test_shared_branding.py). Frontend-specific lines live under `extensions.<frontend>` in the branding file, never here.",
  "welcome_title": "Welcome to {name}",
  "welcome_subtitle": "",
  "welcome_install": "Install {name}",
  "welcome_install_subtitle": "Installs to your internal disk.",
  "welcome_button": "Get started",
  "confirm_title": "Confirm installation",
  "confirm_subtitle": "",
  "confirm_body": "",
  "confirm_warning": "Everything on {disk} will be erased. This cannot be undone.",
  "confirm_button": "Install",
  "progress_title": "Installing {name}…",
  "progress_note": "Do not power off the computer.",
  "done_title": "{name} is installed",
  "done_subtitle": "Remove the installation media and restart the computer.",
  "done_restart": "Restart now",
  "done_failed_title": "Installation failed",
  "store_label": "Visit the store"
}
'''
COPY_DEFAULTS = {k: v for k, v in json.loads(COPY_DEFAULTS_JSON).items() if not k.startswith("_")}


@dataclass(frozen=True)
class Branding:
    name: str = NEUTRAL_NAME
    id: str = NEUTRAL_ID
    vendor: str = ""
    home_url: str = ""
    docs_url: str = ""
    support_url: str = ""
    logo: str = ""
    default_hostname: str = NEUTRAL_ID
    default_image: str = ""
    store_url: str = ""
    copy: dict = field(default_factory=lambda: dict(COPY_DEFAULTS))
    assets: dict = field(default_factory=lambda: {k: "" for k in ASSET_KEYS})
    confirm_quotes: dict = field(default_factory=dict)
    # extensions.<frontend>: keys only that frontend renders (GNOME's tour
    # pages, install video and credits). Not part of the parity contract;
    # a frontend reads its own object and ignores the others.
    extensions: dict = field(default_factory=dict)
    # Where `name` came from: "env", "file", "os-release" or "default".
    # Diagnostics only; not part of the cross-language contract.
    source: str = "default"

    def as_dict(self) -> dict:
        """The scalar identity keys only (what fixtures/expected.json `expect` lists)."""
        d = asdict(self)
        for k in ("source", "store_url", "copy", "assets", "confirm_quotes", "extensions"):
            d.pop(k)
        return d

    def text(self, key: str, **values) -> str:
        """A copy line with {name} (and any given placeholder) filled in."""
        values.setdefault("name", self.name)
        line = self.copy.get(key, COPY_DEFAULTS.get(key, ""))
        for k, v in values.items():
            line = line.replace("{" + k + "}", str(v))
        return line

    def quote_for(self, language: str) -> str:
        """A locale-specific confirm subtitle, or the plain one.

        `language` is a locale like "pt_BR.UTF-8"; the longest matching key of
        confirm_quotes wins ("pt_BR" before "pt"). Deterministic: the first
        line, so screenshots and tests are stable; callers wanting variety
        pick from `confirm_quotes` themselves.
        """
        lang = (language or "").split(".")[0].split("@")[0]
        for candidate in (lang, lang.split("_")[0]):
            lines = self.confirm_quotes.get(candidate) if candidate else None
            if lines:
                return lines[0]
        return self.text("confirm_subtitle")


def parse_os_release(text: str) -> dict:
    """KEY=value pairs from os-release text, quotes and escapes removed.

    Lines that do not parse are skipped rather than failing the whole file:
    a stray quote in a comment must not cost the product its name.
    """
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        try:
            parts = shlex.split(value)
            value = parts[0] if parts else ""
        except ValueError:
            value = value.strip("\"'")
        if key:
            out[key] = value.strip()
    return out


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def from_sources(file_data, os_release_text, name_override="") -> Branding:
    """Pure resolution: the merge rule from README.md, no filesystem access.

    file_data: the parsed branding.json (a dict) or None.
    os_release_text: os-release contents or None.
    """
    file_data = file_data if isinstance(file_data, dict) else {}
    osr = parse_os_release(os_release_text) if os_release_text else {}

    def pick(key, *os_keys, default=""):
        value = _clean(file_data.get(key))
        if value:
            return value, "file"
        for os_key in os_keys:
            value = _clean(osr.get(os_key))
            if value:
                return value, "os-release"
        return default, "default"

    name, source = pick("name", "PRETTY_NAME", "NAME", default=NEUTRAL_NAME)
    override = _clean(name_override)
    if override:
        name, source = override, "env"
    id_, _ = pick("id", "ID", default=NEUTRAL_ID)
    vendor, _ = pick("vendor", "VENDOR_NAME", "NAME")
    home_url, _ = pick("home_url", "HOME_URL")
    docs_url, _ = pick("docs_url", "DOCUMENTATION_URL")
    support_url, _ = pick("support_url", "SUPPORT_URL")
    logo, _ = pick("logo", "LOGO")
    default_hostname, _ = pick("default_hostname", "DEFAULT_HOSTNAME", "ID", default=NEUTRAL_ID)
    default_image, _ = pick("default_image")
    store_url, _ = pick("store_url")

    # Flavour: a present string key overrides, even when empty (that is how a
    # product hides a line); anything else keeps the neutral default.
    copy = dict(COPY_DEFAULTS)
    file_copy = file_data.get("copy")
    if isinstance(file_copy, dict):
        for k, v in file_copy.items():
            if isinstance(v, str) and k in COPY_DEFAULTS:
                copy[k] = v.strip()
    assets = {k: "" for k in ASSET_KEYS}
    file_assets = file_data.get("assets")
    if isinstance(file_assets, dict):
        for k, v in file_assets.items():
            if isinstance(v, str):
                assets[k] = v.strip()
    extensions = {}
    file_ext = file_data.get("extensions")
    if isinstance(file_ext, dict):
        for k, v in file_ext.items():
            if isinstance(v, dict):
                extensions[k] = {ek: ev for ek, ev in v.items() if isinstance(ev, str)}
    quotes = {}
    file_quotes = file_data.get("confirm_quotes")
    if isinstance(file_quotes, dict):
        for k, v in file_quotes.items():
            if isinstance(v, list):
                lines = [s.strip() for s in v if isinstance(s, str) and s.strip()]
                if lines:
                    quotes[k] = lines

    return Branding(
        name=name, id=id_, vendor=vendor, home_url=home_url, docs_url=docs_url,
        support_url=support_url, logo=logo, default_hostname=default_hostname,
        default_image=default_image, store_url=store_url, copy=copy, assets=assets,
        confirm_quotes=quotes, extensions=extensions, source=source,
    )


def _read_text(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _read_branding_file(paths) -> dict | None:
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def resolve(branding_paths=None, os_release_paths=None, env=None) -> Branding:
    """The branding for this machine. Every argument exists for tests."""
    env = os.environ if env is None else env
    if branding_paths is None:
        explicit = _clean(env.get(ENV_FILE))
        branding_paths = [explicit] if explicit else BRANDING_PATHS
    if os_release_paths is None:
        os_release_paths = OS_RELEASE_PATHS

    file_data = _read_branding_file(branding_paths)
    os_release_text = None
    for path in os_release_paths:
        text = _read_text(path)
        if text is not None and text.strip():
            os_release_text = text
            break
    return from_sources(file_data, os_release_text, env.get(ENV_NAME, ""))
