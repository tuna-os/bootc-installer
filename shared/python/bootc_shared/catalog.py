"""The image catalog (`images.json`) as the Python frontends read it.

The contract is shared/catalog/README.md: where the catalog is, what a leaf
inherits, which fields reach the recipe and which image is selected at the
start. tests/unit/test_shared_python_catalog.py reads the contract's fixture
through this module and compares the result with
shared/catalog/fixtures/expected.json. shared/catalog/resolve.py stays the
strict reference that writes that fixture; this module is the reader that
ships.

No GTK and no network here. A frontend never downloads a Flatpak list; a
list that is not in the catalog itself is left out of the recipe.

The reader is lenient: a catalog is a file from the host, so a node that is
not an object is skipped, and a field of the wrong type gets its default
with a warning. A caller that must not go on with a wrong catalog (the
GNOME Processor, when it has no image page to trust) asks for `strict`, and
gets a CatalogError.
"""

import json
import logging
import os

logger = logging.getLogger("Installer::Catalog")

FLATPAK_INFO = "/.flatpak-info"

# A catalog file that is tried before each other place: the override for a
# test harness or an operator (shared/catalog/README.md, "Where the catalog
# is"). A capture or an E2E driver sets it so that the test does not read
# the catalog of the machine.
OVERRIDE_ENV = "FISHERMAN_IMAGES_PATH"

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
    "extras": None,
}

# The switches of `extras`: the keys of the recipe's `extras` object.
# fisherman refuses a recipe key that it does not know, so no other key of
# a catalog object is copied.
EXTRAS = ("printServices", "oemSetup", "audioNames", "bootSplash")


class CatalogError(ValueError):
    """A catalog that a strict caller must not use."""


# ── Where the catalog is ─────────────────────────────────────────────────────

def in_flatpak() -> bool:
    return os.path.exists(FLATPAK_INFO)


def search_paths(flatpak: bool, xdg_config_home: str) -> list:
    """The catalog files, in the order they are tried. The package's own
    catalog comes after them (the caller has it).

    The system file is first: an ISO that ships a catalog must get that
    catalog, and a file in a home directory must not replace it.
    """
    etc = "/run/host/etc" if flatpak else "/etc"
    return [
        f"{etc}/bootc-installer/images.json",
        f"{etc}/tuna-installer/images.json",
        f"{xdg_config_home.rstrip('/')}/bootc-installer/images.json",
    ]


def default_search_paths(environ=None, home=None, flatpak=None) -> list:
    """`search_paths` for this process, with the OVERRIDE_ENV file first
    when the variable names one."""
    environ = os.environ if environ is None else environ
    home = home or os.path.expanduser("~")
    xdg = environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    override = environ.get(OVERRIDE_ENV, "")
    paths = search_paths(in_flatpak() if flatpak is None else flatpak, xdg)
    return ([override] if override else []) + paths


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
        catalog = load(path) if path else None
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


# ── Desktop extras ───────────────────────────────────────────────────────────

def resolve_extras(value):
    """The recipe's `extras` object for a catalog `extras` value, or None.

    The value is the object of the nearest node that has one: objects are
    not merged, and a switch that the object leaves out is off. `{}` turns
    the four off. None (no node has the object, or the value is not an
    object of booleans) means: leave `extras` out of the recipe, and
    fisherman looks the image up in the catalog that it finds.
    """
    if not isinstance(value, dict):
        return None
    if not all(isinstance(value.get(key, False), bool) for key in EXTRAS):
        logger.warning("images.json: `extras` has a switch that is not true or false; "
                       "it is not used")
        return None
    return {key: value.get(key, False) for key in EXTRAS}


# ── Leaves ───────────────────────────────────────────────────────────────────

def pretty_from_imgref(imgref: str) -> str:
    """'registry.example/os/atlas-dx:latest' -> 'Atlas DX'. A reference
    with no registry ('atlas-dx:latest') gives the same name."""
    if not isinstance(imgref, str):
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


def _typed(context: dict, strict=False) -> dict:
    """`context` with each value of the wrong type replaced by its default.
    A catalog is a file from the host: a wrong type must not reach a
    widget or the recipe. With `strict` a wrong type is a CatalogError."""
    clean = dict(context)
    for key, default in INHERITED.items():
        value = clean.get(key, default)
        if key in ("flatpaks", "extras"):
            continue
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, list):
            ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        else:
            ok = isinstance(value, str)
        if not ok:
            if strict:
                raise CatalogError(f"images.json: `{key}` has the wrong type")
            logger.warning("images.json: `%s` has the wrong type; the default is used", key)
            clean[key] = list(default) if isinstance(default, list) else default
    return clean


def _text(node, key) -> str:
    value = node.get(key, "")
    return value if isinstance(value, str) else ""


def _leaf(node, context, product, owns_registry, aliases, path, strict=False):
    name = _text(node, "name").strip()
    context = _typed(context, strict)
    own = node.get("imgref")
    if own:
        imgref, channel = own, ""
        product = name or pretty_from_imgref(imgref)
    else:
        imgref = f"{context['registry']}:{node['tag']}"
        # A tag leaf that sets its own registry is its own product.
        channel = "" if owns_registry else name
        product = product or pretty_from_imgref(imgref)
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
        "extras": resolve_extras(context["extras"]),
    }


def _visit(images, aliases, strict):
    """Yield (node, imgref, nvidia_imgref, build) for each installable
    leaf, in catalog order. build() makes the leaf; a search that wants one
    leaf thus pays for one, and a strict search judges only the types of
    that one."""
    aliases = aliases if isinstance(aliases, dict) else {}

    def visit(nodes, inherited, product, path):
        if not isinstance(nodes, list):
            if strict:
                raise CatalogError("Image metadata must be a list")
            return
        for node in nodes:
            if not isinstance(node, dict):
                if strict:
                    raise CatalogError("Image metadata entry must be an object")
                continue
            context = dict(inherited)
            for key in INHERITED:
                # false, "" and [] are values and stop the search.
                if key in node and node[key] is not None:
                    context[key] = node[key]
            name = _text(node, "name")
            here = path + [name] if name else path
            # The product is the name of the nearest node that sets a
            # registry: the name of a tag leaf is a channel ("Stable").
            owns_registry = bool(node.get("registry"))
            node_product = name.strip() if owns_registry else product
            registry = context["registry"] if isinstance(context["registry"], str) else ""
            own = node.get("imgref")
            if (own and isinstance(own, str)) or ("tag" in node and registry):
                imgref = own or f"{registry}:{node['tag']}"
                nvidia = context["nvidia_imgref"]

                def build(node=node, context=context, node_product=node_product,
                          owns_registry=owns_registry, here=here):
                    return _leaf(node, context, node_product, owns_registry, aliases,
                                 here, strict)
                yield node, imgref, nvidia if isinstance(nvidia, str) else "", build
                continue
            if "tag" in node:
                logger.warning("images.json: node %r has `tag` and no `registry` in scope",
                               node.get("name"))
                continue
            if "children" in node:
                yield from visit(node["children"], context, node_product, here)

    yield from visit(images, dict(INHERITED), "", [])


def walk(images, aliases=None):
    """Yield (node, leaf) for each installable leaf of an `images` tree, in
    catalog order. `leaf` has the inherited fields; `node` is the object of
    the tree, so a page can find the leaf of the node it draws.

    A leaf takes each field from the nearest node that sets it: itself,
    then its parent, and so on. `false`, "" and [] are values and stop the
    search. A node with `tag` and no registry in scope is not a leaf.
    """
    for node, _imgref, _nvidia, build in _visit(images, aliases, False):
        yield node, build()


def leaves(catalog) -> list:
    """Each installable leaf of `catalog`, in order, with inherited fields."""
    if not isinstance(catalog, dict):
        return []
    return [leaf for _node, leaf in walk(catalog.get("images", []), catalog.get("aliases"))]


def find(catalog, imgref, strict=False):
    """The leaf for `imgref`, or None.

    The NVIDIA image of a leaf is that leaf: a leaf whose own reference is
    `imgref` wins, then the first leaf whose `nvidia_imgref` is `imgref`.

    With `strict`, a tree that is not lists of objects, or a wrong type in
    the leaf that is found, is a CatalogError: the caller must not go on
    with a default in place of what the catalog tried to say.
    """
    if not imgref or not isinstance(catalog, dict):
        return None
    variant = None
    for _node, reference, nvidia, build in _visit(catalog.get("images", []),
                                                  catalog.get("aliases"), strict):
        if reference == imgref:
            return build()
        if variant is None and nvidia == imgref:
            variant = build
    return variant() if variant else None


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
