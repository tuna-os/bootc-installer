"""Product branding: a branding.json first, os-release second, neutral last.

Canonical copy: shared/branding/branding.py. bootc_installer/utils/branding.py
and frontends/xfce/tuna_installer_xfce/branding.py are byte-identical copies
(tests/unit/test_shared_branding.py enforces it). The contract, the key
table and the fixtures the other languages test against are in
shared/branding/README.md.

No GTK, no gettext, nothing but the standard library, so every frontend and
every test can import it as-is.
"""

import json
import os
import shlex
from dataclasses import asdict, dataclass

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
    # Where `name` came from: "env", "file", "os-release" or "default".
    # Diagnostics only; not part of the cross-language contract.
    source: str = "default"

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("source")
        return d


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
    return Branding(
        name=name, id=id_, vendor=vendor, home_url=home_url, docs_url=docs_url,
        support_url=support_url, logo=logo, default_hostname=default_hostname,
        default_image=default_image, source=source,
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
