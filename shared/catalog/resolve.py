#!/usr/bin/env python3
"""Reference resolver for the image catalog contract (shared/catalog/README.md).

Pure Python, standard library only, no network. It is the executable form of
the README: a frontend in any language must read `fixtures/catalog.json` to
the answers in `fixtures/expected.json`, and this file is what wrote them.

    python3 shared/catalog/resolve.py                 # print expected.json
    python3 shared/catalog/resolve.py --write         # rewrite the fixture
    python3 shared/catalog/resolve.py --leaves FILE   # resolved leaves of FILE

Nothing here imports a frontend, and no frontend has to import this.
"""

import argparse
import json
import os
import sys

CONTRACT_VERSION = 1

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_CATALOG = os.path.join(HERE, "fixtures", "catalog.json")
FIXTURE_EXPECTED = os.path.join(HERE, "fixtures", "expected.json")

BUNDLED = "<bundled>"
FLATPAK_INFO = "/.flatpak-info"

# Catalog key -> the value a leaf has when neither it nor a parent sets the
# key. `needs_user_creation` is True: an install with no account and no
# first-boot setup leaves nobody to sign in as.
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

# The keys of `extras`, which are the keys of the recipe's `extras` object
# (fisherman's recipe.Extras). A key that is not here is not copied:
# fisherman refuses a recipe key that it does not know.
EXTRAS = ("printServices", "oemSetup", "audioNames", "bootSplash")

BOOTLOADERS = ("", "grub2", "systemd")
FILESYSTEMS = ("xfs", "ext4", "btrfs", "zfs")


class CatalogError(ValueError):
    """The catalog does not follow the contract."""


# ── Search path ──────────────────────────────────────────────────────────────

def search_paths(in_flatpak, xdg_config_home, bundled=BUNDLED):
    """The ordered list of catalog files. The first that loads is used."""
    etc = "/run/host/etc" if in_flatpak else "/etc"
    return [
        f"{etc}/bootc-installer/images.json",
        f"{etc}/tuna-installer/images.json",
        f"{xdg_config_home.rstrip('/')}/bootc-installer/images.json",
        bundled,
    ]


def default_search_paths(bundled, environ=None, home=None):
    """`search_paths` for the process that runs this code."""
    environ = os.environ if environ is None else environ
    home = home or os.path.expanduser("~")
    xdg = environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return search_paths(os.path.exists(FLATPAK_INFO), xdg, bundled)


def load(path):
    with open(path, encoding="utf-8") as stream:
        catalog = json.load(stream)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("images"), list):
        raise CatalogError(f"{path}: a catalog is an object with an `images` list")
    return catalog


def load_first(paths):
    """Return (catalog, path) for the first path that loads, else (None, None).

    A file that is missing, unreadable or not a catalog does not stop the
    search: the next path is tried.
    """
    for path in paths:
        try:
            return load(path), path
        except (OSError, ValueError):
            continue
    return None, None


# ── Flatpak lists ────────────────────────────────────────────────────────────

def resolve_flatpaks(value, aliases):
    """Return (list or None, url).

    A list is the list. `@name` is looked up in `aliases`: a list there is
    the list. A URL (from an alias or written directly) cannot be read
    offline, so the list is None and the URL is reported for the record. An
    unknown alias, or no value, is None too. None means: leave `flatpaks`
    out of the recipe.
    """
    if isinstance(value, str) and value.startswith("@"):
        value = (aliases or {}).get(value[1:])
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise CatalogError("`flatpaks` must be a list of application ids")
        return list(value), ""
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return None, value
    return None, ""


# ── Extras ───────────────────────────────────────────────────────────────────

def resolve_extras(value, where="extras"):
    """The four switches of an `extras` object, or None when no node set one.

    The nearest node that has the object gives all of it: the objects of a
    node and of its parent are not merged, so a switch that the nearest
    object leaves out is off. `{}` is an object and turns the four off.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CatalogError(f"{where}: `extras` must be an object")
    for key in EXTRAS:
        if not isinstance(value.get(key, False), bool):
            raise CatalogError(f"{where}: `extras.{key}` must be true or false")
    return {key: value.get(key, False) for key in EXTRAS}


# ── Leaves ───────────────────────────────────────────────────────────────────

def _pretty_from_imgref(imgref):
    slug = imgref.rsplit("/", 1)[-1].split("@", 1)[0].split(":", 1)[0]
    parts = [part for part in slug.replace("_", "-").split("-") if part]
    if not parts:
        return imgref
    return " ".join(part.capitalize() if index == 0 else part.upper()
                    for index, part in enumerate(parts))


def _leaf(node, context, product, owns_registry, aliases, path):
    name = node.get("name", "")
    name = name.strip() if isinstance(name, str) else ""
    own = node.get("imgref")
    if own:
        imgref, channel = own, ""
        product = name or _pretty_from_imgref(imgref)
    else:
        imgref = f"{context['registry']}:{node['tag']}"
        # A tag leaf that sets its own registry is its own product.
        channel = "" if owns_registry else name
        product = product or _pretty_from_imgref(imgref)
    flatpaks, flatpaks_url = resolve_flatpaks(context["flatpaks"], aliases)
    for key in ("nvidia_imgref", "bootloader", "filesystem", "default_hostname",
                "flatpak_var_path", "image_type"):
        if not isinstance(context[key], str):
            raise CatalogError(f"{imgref}: `{key}` must be a string")
    for key in ("composefs", "needs_user_creation"):
        if not isinstance(context[key], bool):
            raise CatalogError(f"{imgref}: `{key}` must be true or false")
    filesystems = context["filesystems"]
    if not isinstance(filesystems, list):
        raise CatalogError(f"{imgref}: `filesystems` must be a list")
    if context["bootloader"] not in BOOTLOADERS:
        raise CatalogError(f"{imgref}: bootloader {context['bootloader']!r}")
    for filesystem in [context["filesystem"], *filesystems]:
        if filesystem and filesystem not in FILESYSTEMS:
            raise CatalogError(f"{imgref}: filesystem {filesystem!r}")
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
        "filesystem": default_filesystem(context["filesystem"], filesystems),
        "filesystems": filesystem_choices(context["filesystem"], filesystems),
        "default_hostname": context["default_hostname"],
        "flatpaks": flatpaks,
        "flatpaks_url": flatpaks_url,
        "flatpak_var_path": context["flatpak_var_path"],
        "needs_user_creation": context["needs_user_creation"],
        "image_type": context["image_type"],
        "extras": resolve_extras(context["extras"], imgref),
    }


def filesystem_choices(filesystem, filesystems):
    """What the user may pick. [] means the frontend offers its own list."""
    if filesystems:
        return list(filesystems)
    return [filesystem] if filesystem else []


def default_filesystem(filesystem, filesystems):
    """What is selected before the user picks. "" means the frontend default."""
    if filesystem:
        return filesystem
    return filesystems[0] if filesystems else ""


def leaves(catalog):
    """Every installable leaf, in catalog order, with inherited fields."""
    aliases = catalog.get("aliases") or {}
    found = []

    def walk(nodes, inherited, product, path):
        if not isinstance(nodes, list):
            raise CatalogError("`images` and `children` must be lists")
        for node in nodes:
            if not isinstance(node, dict):
                raise CatalogError("a catalog node must be an object")
            context = dict(inherited)
            for key in INHERITED:
                if key in node and node[key] is not None:
                    context[key] = node[key]
            name = node.get("name", "")
            here = path + [name] if name else path
            # The product is the name of the nearest node that sets a
            # registry: a tag leaf's own name is a channel ("Stable").
            owns_registry = bool(node.get("registry"))
            node_product = name.strip() if owns_registry and isinstance(name, str) else product
            if node.get("imgref") or ("tag" in node and context["registry"]):
                found.append(_leaf(node, context, node_product, owns_registry, aliases, here))
                continue
            walk(node.get("children", []), context, node_product, here)

    walk(catalog.get("images", []), dict(INHERITED), "", [])
    return found


def find(catalog, imgref):
    """The leaf for `imgref`, or None."""
    for leaf in leaves(catalog):
        if leaf["imgref"] == imgref:
            return leaf
    return None


# ── Selection ────────────────────────────────────────────────────────────────

def default_imgref(catalog, branding_default_image=""):
    """The leaf selected at start, or None: then the user must choose."""
    known = {leaf["imgref"] for leaf in leaves(catalog)}
    for candidate in (branding_default_image, catalog.get("default_image", "")):
        if candidate and candidate in known:
            return candidate
    return None


def needs_user_creation(catalog, imgref):
    """Whether the install of `imgref` creates an account. Unknown: True."""
    leaf = find(catalog, imgref) if catalog else None
    return True if leaf is None else leaf["needs_user_creation"]


# ── Recipe ───────────────────────────────────────────────────────────────────

def source_and_target(leaf, has_nvidia=False, is_live=False, offline_images=()):
    """Return (image, targetImgref) for a leaf on this machine."""
    base, nvidia = leaf["imgref"], leaf["nvidia_imgref"]
    if not nvidia:
        return base, base
    if has_nvidia:
        return nvidia, nvidia
    if is_live and nvidia in offline_images and base not in offline_images:
        # Only the NVIDIA image is on the media. Install it without a
        # download; the first update moves the system to the base image.
        return nvidia, base
    return base, base


def recipe_fragment(leaf, has_nvidia=False, is_live=False, offline_images=()):
    """The recipe keys a frontend writes for `leaf`, before any user edit.

    Returns {"recipe": {...}, "absent": [...]}. A key in `absent` must not be
    in the recipe at all.
    """
    image, target = source_and_target(leaf, has_nvidia, is_live, offline_images)
    recipe = {
        "image": image,
        "targetImgref": target,
        "bootloader": leaf["bootloader"],
        "composeFsBackend": leaf["composefs"],
    }
    absent = []
    if leaf["filesystem"]:
        recipe["filesystem"] = leaf["filesystem"]
    if leaf["flatpaks"] is None:
        absent.append("flatpaks")
    else:
        recipe["flatpaks"] = leaf["flatpaks"]
    if leaf["flatpak_var_path"]:
        recipe["flatpakVarPath"] = leaf["flatpak_var_path"]
    else:
        absent.append("flatpakVarPath")
    if leaf["image_type"] != "bootc":
        recipe["imageType"] = leaf["image_type"]
    if leaf["extras"] is None:
        absent.append("extras")
    else:
        recipe["extras"] = dict(leaf["extras"])
    return {"recipe": recipe, "absent": absent}


# A missing key and these values mean the same thing to fisherman.
EMPTY = {"bootloader": "", "composeFsBackend": False, "imageType": "bootc"}


def recipe_matches(recipe, fragment):
    """Problems (a list of strings) when `recipe` does not carry `fragment`."""
    problems = []
    for key, want in fragment["recipe"].items():
        got = recipe.get(key, EMPTY.get(key)) if key in EMPTY else recipe.get(key)
        if key == "extras" and isinstance(got, dict):
            # A switch that the recipe leaves out is off. Any other key is
            # one that fisherman refuses.
            unknown = sorted(set(got) - set(EXTRAS))
            if unknown:
                problems.append(f"extras: unknown keys {unknown!r}")
            got = {name: got.get(name, False) for name in EXTRAS}
        if got != want:
            problems.append(f"{key}: expected {want!r}, found {got!r}")
    for key in fragment["absent"]:
        if key in recipe:
            problems.append(f"{key}: must be left out, found {recipe[key]!r}")
    return problems


# ── The fixture ──────────────────────────────────────────────────────────────

def machine_cases(leaf):
    cases = [{"has_nvidia": False, "is_live": False, "offline_images": []}]
    if leaf["nvidia_imgref"]:
        base, nvidia = leaf["imgref"], leaf["nvidia_imgref"]
        cases += [
            {"has_nvidia": True, "is_live": False, "offline_images": []},
            {"has_nvidia": True, "is_live": True, "offline_images": [nvidia]},
            {"has_nvidia": False, "is_live": True, "offline_images": [nvidia]},
            {"has_nvidia": False, "is_live": True, "offline_images": [base, nvidia]},
            {"has_nvidia": False, "is_live": True, "offline_images": [base]},
        ]
    return cases


def expected(catalog):
    """Everything a frontend must agree with for `catalog`."""
    all_leaves = leaves(catalog)
    catalog_default = catalog.get("default_image", "")
    brandings = ["", "registry.example/os/not-in-the-catalog:1"]
    brandings += [leaf["imgref"] for leaf in all_leaves if leaf["imgref"] != catalog_default][:1]
    without_default = {key: value for key, value in catalog.items() if key != "default_image"}
    selection = [
        {"branding_default_image": branding, "catalog_default_image": catalog_default,
         "selected": default_imgref(catalog, branding)}
        for branding in brandings
    ] + [
        {"branding_default_image": branding, "catalog_default_image": "",
         "selected": default_imgref(without_default, branding)}
        for branding in brandings
    ]
    return {
        "contract_version": CONTRACT_VERSION,
        "search_paths": [
            {"in_flatpak": flatpak, "xdg_config_home": xdg,
             "paths": search_paths(flatpak, xdg)}
            for flatpak, xdg in ((False, "/home/user/.config"),
                                 (True, "/home/user/.var/app/org.example.Installer/config"))
        ],
        "default_selection": selection,
        "unknown_image": {"imgref": "registry.example/os/not-in-the-catalog:1",
                          "needs_user_creation": needs_user_creation(
                              catalog, "registry.example/os/not-in-the-catalog:1")},
        "leaves": [
            {"imgref": leaf["imgref"], "leaf": leaf,
             "cases": [{"inputs": inputs, **recipe_fragment(leaf, **inputs)}
                       for inputs in machine_cases(leaf)]}
            for leaf in all_leaves
        ],
    }


def dumps(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help="rewrite fixtures/expected.json")
    parser.add_argument("--leaves", metavar="FILE",
                        help="print the resolved leaves of a catalog file")
    args = parser.parse_args(argv)
    if args.leaves:
        sys.stdout.write(dumps(leaves(load(args.leaves))))
        return 0
    text = dumps(expected(load(FIXTURE_CATALOG)))
    if args.write:
        with open(FIXTURE_EXPECTED, "w", encoding="utf-8") as stream:
            stream.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
