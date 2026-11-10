# catalog.py
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation at version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""The image catalog as the GNOME frontend reads it.

The contract is shared/catalog/README.md: where the catalog is, what a leaf
inherits, which fields reach the recipe and which image is selected at the
start. tests/unit/test_gnome_catalog_contract.py reads the contract's
fixture through this module and the Processor and compares the result with
shared/catalog/fixtures/expected.json.

No GTK and no network here: the image page, the Processor, the user step
and the headless tests all import it. A frontend never downloads a Flatpak
list; a list that is not in the catalog itself is left out of the recipe.
"""

import json
import logging
import os

logger = logging.getLogger("Installer::Catalog")

FLATPAK_INFO = "/.flatpak-info"

# Catalog key -> the value a leaf has when neither it nor a parent sets it.
# `needs_user_creation` is True: an install with no account and no
# first-boot setup leaves nobody to sign in as (#288).
INHERITED = {
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


# ── Where the catalog is ─────────────────────────────────────────────────────

def in_flatpak() -> bool:
    return os.path.exists(FLATPAK_INFO)


def search_paths(flatpak: bool, xdg_config_home: str) -> list:
    """The catalog files, in the order they are tried. The package's own
    catalog comes after them (the caller has it, as a GResource).

    The system file is first: an ISO that ships a catalog must get that
    catalog, and a file in a home directory must not replace it.
    """
    etc = "/run/host/etc" if flatpak else "/etc"
    return [
        f"{etc}/bootc-installer/images.json",
        f"{etc}/tuna-installer/images.json",
        f"{xdg_config_home.rstrip('/')}/bootc-installer/images.json",
    ]


def default_search_paths(environ=None, home=None) -> list:
    """`search_paths` for this process."""
    environ = os.environ if environ is None else environ
    home = home or os.path.expanduser("~")
    xdg = environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return search_paths(in_flatpak(), xdg)


def is_catalog(value) -> bool:
    """A catalog is a JSON object with an `images` list."""
    return isinstance(value, dict) and isinstance(value.get("images"), list)


def load(path: str):
    """The catalog at `path`, or None: a file that is missing, does not
    parse or is not a catalog does not stop the search."""
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, ValueError) as error:
        if not isinstance(error, FileNotFoundError):
            logger.warning("Cannot read the catalog at %s: %s", path, error)
        return None
    if not is_catalog(value):
        logger.warning("%s is not a catalog (an object with an `images` list)", path)
        return None
    return value


def load_first(paths):
    """(catalog, path) for the first path that holds a catalog, else
    (None, None)."""
    for path in paths:
        catalog = load(path)
        if catalog is not None:
            return catalog, path
    return None, None


# ── Flatpak lists ────────────────────────────────────────────────────────────

def resolve_flatpaks(value, aliases=None):
    """The Flatpak list of a leaf, or None.

    A list is the list ([] included). `@name` is looked up in `aliases`: a
    list there is the list. A URL, an alias that does not exist, or no
    value gives None, which means: leave `flatpaks` out of the recipe, and
    fisherman applies its own default.
    """
    if isinstance(value, str) and value.startswith("@"):
        value = (aliases or {}).get(value[1:])
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


# ── Leaves ───────────────────────────────────────────────────────────────────

def pretty_from_imgref(imgref: str) -> str:
    """'registry.example/os/atlas-dx:latest' -> 'Atlas DX'."""
    if not isinstance(imgref, str) or "/" not in imgref:
        return imgref
    slug = imgref.rsplit("/", 1)[-1].split("@", 1)[0].split(":", 1)[0]
    parts = [part for part in slug.replace("_", "-").split("-") if part]
    if not parts:
        return imgref
    return " ".join(part.capitalize() if index == 0 else part.upper()
                    for index, part in enumerate(parts))


def filesystem_choices(filesystem, filesystems) -> list:
    """What the user can pick. [] means the page offers its own list."""
    if filesystems:
        return list(filesystems)
    return [filesystem] if filesystem else []


def default_filesystem(filesystem, filesystems) -> str:
    """What is selected before the user picks. "" means the page default."""
    if filesystem:
        return filesystem
    return filesystems[0] if filesystems else ""


def _typed(context: dict) -> dict:
    """`context` with each value of the wrong type replaced by its default.
    A catalog is a file from the host: a wrong type must not reach a
    widget or the recipe."""
    clean = dict(context)
    for key, default in INHERITED.items():
        value = clean.get(key, default)
        if key == "flatpaks":
            continue
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, list):
            ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        else:
            ok = isinstance(value, str)
        if not ok:
            logger.warning("images.json: `%s` has the wrong type; the default is used", key)
            clean[key] = list(default) if isinstance(default, list) else default
    return clean


def _leaf(node, context, product, owns_registry, aliases, path):
    name = node.get("name", "")
    name = name.strip() if isinstance(name, str) else ""
    own = node.get("imgref")
    if own:
        imgref, channel = own, ""
        product = name or pretty_from_imgref(imgref)
    else:
        imgref = f"{context['registry']}:{node['tag']}"
        # A tag leaf that sets its own registry is its own product.
        channel = "" if owns_registry else name
        product = product or pretty_from_imgref(imgref)
    context = _typed(context)
    return {
        "imgref": imgref,
        "name": name,
        "product": product,
        "channel": channel,
        "label": f"{product} {channel}".strip(),
        "path": path,
        "breadcrumb": " › ".join(path),
        "nvidia_imgref": context["nvidia_imgref"],
        "bootloader": context["bootloader"],
        "composefs": context["composefs"],
        "filesystem": default_filesystem(context["filesystem"], context["filesystems"]),
        "filesystems": filesystem_choices(context["filesystem"], context["filesystems"]),
        "default_hostname": context["default_hostname"],
        "flatpaks": resolve_flatpaks(context["flatpaks"], aliases),
        "flatpak_var_path": context["flatpak_var_path"],
        "needs_user_creation": context["needs_user_creation"],
        "image_type": context["image_type"],
    }


def walk(images, aliases=None):
    """Yield (node, leaf) for each installable leaf of an `images` tree, in
    catalog order. `leaf` has the inherited fields; `node` is the object of
    the tree, so a page can find the leaf of the node it draws.

    A leaf takes each field from the nearest node that sets it: itself,
    then its parent, and so on. `false`, "" and [] are values and stop the
    search. A node with `tag` and no registry in scope is not a leaf.
    """
    aliases = aliases if isinstance(aliases, dict) else {}

    def visit(nodes, inherited, product, path):
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            context = dict(inherited)
            for key in INHERITED:
                if key in node and node[key] is not None:
                    context[key] = node[key]
            name = node.get("name", "")
            name = name if isinstance(name, str) else ""
            here = path + [name] if name else path
            # The product is the name of the nearest node that sets a
            # registry: the name of a tag leaf is a channel ("Stable").
            owns_registry = bool(node.get("registry"))
            node_product = name.strip() if owns_registry else product
            registry = context["registry"] if isinstance(context["registry"], str) else ""
            if node.get("imgref") or ("tag" in node and registry):
                yield node, _leaf(node, context, node_product, owns_registry, aliases, here)
                continue
            if "tag" in node:
                logger.warning("images.json: node %r has `tag` and no `registry` in scope",
                               node.get("name"))
                continue
            yield from visit(node.get("children", []), context, node_product, here)

    yield from visit(images, dict(INHERITED), "", [])


def leaves(catalog) -> list:
    """Each installable leaf of `catalog`, in order, with inherited fields."""
    if not isinstance(catalog, dict):
        return []
    return [leaf for _node, leaf in walk(catalog.get("images", []), catalog.get("aliases"))]


def find(catalog, imgref):
    """The leaf for `imgref`, or None."""
    if not imgref:
        return None
    for leaf in leaves(catalog):
        if leaf["imgref"] == imgref:
            return leaf
    return None


# ── Selection and the account ────────────────────────────────────────────────

def default_imgref(catalog, branding_default_image=""):
    """The leaf selected at the start, or None: the user must then choose.

    The branding's `default_image` first, then the catalog's. Each counts
    only when the catalog has that leaf. Never the first row.
    """
    catalog = catalog if isinstance(catalog, dict) else {}
    known = {leaf["imgref"] for leaf in leaves(catalog)}
    for candidate in (branding_default_image, catalog.get("default_image", "")):
        if candidate and candidate in known:
            return candidate
    return None


def needs_user_creation(catalog, imgref) -> bool:
    """Whether the installer creates the first account for `imgref`. True
    for an image that the catalog does not have."""
    leaf = find(catalog, imgref) if catalog else None
    return True if leaf is None else leaf["needs_user_creation"]


# ── Image and NVIDIA image ───────────────────────────────────────────────────

def source_and_target(imgref, nvidia_imgref, has_nvidia=False, is_live=False,
                      offline_images=()):
    """(image, targetImgref) for a leaf on this machine.

    With an NVIDIA GPU the two are the NVIDIA image. Without one, the
    NVIDIA image is the source only on live media whose store has it and
    not the base image; updates then follow the base image. In each other
    case the two are the base image (#314).
    """
    if not nvidia_imgref:
        return imgref, imgref
    if has_nvidia:
        return nvidia_imgref, nvidia_imgref
    if is_live and nvidia_imgref in offline_images and imgref not in offline_images:
        return nvidia_imgref, imgref
    return imgref, imgref


# ── What the image page hands to the other steps ─────────────────────────────

def leaf_finals(leaf: dict, icon=None, carousel=None) -> dict:
    """The image step's finals for a selected leaf.

    `flatpaks` is there only when the catalog has the list itself: without
    the key the Processor writes no `flatpaks`, and fisherman applies its
    default. `image_filesystem` is the image's one filesystem; it is empty
    when the leaf offers a choice, and the disk page then decides.
    """
    choices = leaf["filesystems"]
    finals = {
        "selected_image": leaf["imgref"],
        "pretty_name": leaf["product"] or pretty_from_imgref(leaf["imgref"]),
        "nvidia_imgref": leaf["nvidia_imgref"],
        "flatpak_var_path": leaf["flatpak_var_path"],
        "carousel": carousel,
        "needs_user_creation": leaf["needs_user_creation"],
        "composefs_backend": leaf["composefs"],
        "image_type": leaf["image_type"],
        "bootloader": leaf["bootloader"],
        "image_filesystem": leaf["filesystem"] if len(choices) <= 1 else "",
        "default_filesystem": leaf["filesystem"],
        "icon": icon,
        "default_hostname": leaf["default_hostname"],
        "supported_filesystems": list(choices),
    }
    if leaf["flatpaks"] is not None:
        finals["flatpaks"] = list(leaf["flatpaks"])
    return finals


def custom_image_finals(imgref: str) -> dict:
    """The image step's finals for an image the user typed. It is not in
    the catalog, so the installer creates an account, and no Flatpak list
    is written."""
    return {
        "custom_image": imgref,
        "pretty_name": pretty_from_imgref(imgref),
        "carousel": None,
        "needs_user_creation": True,
        "composefs_backend": False,
        "image_type": "bootc",
        "bootloader": "",
        "image_filesystem": "",
        "icon": None,
    }
