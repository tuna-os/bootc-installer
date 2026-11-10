# image.py
#
# Copyright 2024 mirkobrombin muhdsalm
#
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundationat version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import logging
import re

from gi.repository import Adw, Gio, Gtk

from bootc_shared import catalog

from bootc_installer.utils import image_finals

logger = logging.getLogger("Installer::Image")


# ── Load the image catalog ────────────────────────────────────────────────────
# The contract is shared/catalog/README.md; bootc_shared.catalog (shared/python/)
# is this frontend's reader. Structure: {"default_image", "aliases",
# "images": [recursive tree]}. Each node is a group {"name", "children", ...}
# or a leaf {"name", "imgref" | "tag", ...}; a leaf inherits from its parents.
#
# The files, in the order they are tried (the first that is a catalog wins):
#   <etc>/bootc-installer/images.json             the ISO or the operator
#   <etc>/tuna-installer/images.json              the legacy name of that file
#   $XDG_CONFIG_HOME/bootc-installer/images.json  a developer, for a test
#   the catalog in the package (GResource)
# <etc> is /run/host/etc in a Flatpak. The system file is first: a file in a
# home directory must not replace the catalog an ISO ships (#298).

def _load_manifest():
    import pathlib

    # 1-3. The files of the contract, system file first.
    manifest, path = catalog.load_first(catalog.default_search_paths())
    if manifest is not None:
        logger.info(f"Loaded image manifest from {path}")
        return manifest

    # 4. Bundled GResource (default shipped with the installer).
    try:
        data = Gio.resources_lookup_data(
            "/org/bootcinstaller/Installer/images.json",
            Gio.ResourceLookupFlags.NONE,
        )
        manifest = json.loads(data.get_data().decode())
        if catalog.is_catalog(manifest):
            logger.debug("Loaded image manifest from GResource")
            return manifest
        logger.warning("images.json in the GResource is not a catalog")
    except Exception:
        logger.warning("Could not load images.json from GResource, trying filesystem")

    # The same bundled catalog as a file: the installed data path
    # (flatpak: /app/share/bootc-installer/images.json), then the source
    # tree for a run from the repository.
    dev_path = pathlib.Path(__file__).resolve().parent.parent.parent / "fisherman" / "data" / "images.json"
    for bundled in ("/app/share/bootc-installer/images.json",
                    "/usr/share/bootc-installer/images.json", str(dev_path)):
        manifest = catalog.load(bundled)
        if manifest is not None:
            logger.info(f"Loaded image manifest from {bundled}")
            return manifest

    logger.error("Failed to load image manifest from all sources")
    return {"images": []}


def _resolve_aliases(obj: object, aliases: dict) -> None:
    """Recursively replace ``@alias_name`` strings with values from *aliases*.

    Any string value (in a dict or list) that starts with ``@`` is treated as
    an alias reference.  Unknown aliases are left as-is so the parser can
    surface a meaningful error later rather than silently corrupting data.

    This runs once at manifest-load time so the rest of the codebase never
    needs to know about the alias syntax.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str) and value.startswith("@"):
                resolved = aliases.get(value[1:])
                if resolved is not None:
                    obj[key] = resolved
                else:
                    logger.warning(f"images.json: unknown alias '{value}'")
            else:
                _resolve_aliases(value, aliases)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            if isinstance(value, str) and value.startswith("@"):
                resolved = aliases.get(value[1:])
                if resolved is not None:
                    obj[i] = resolved
                else:
                    logger.warning(f"images.json: unknown alias '{value}'")
            else:
                _resolve_aliases(value, aliases)


_MANIFEST = _load_manifest()

# Resolve @alias references before anything else reads the manifest.
_aliases = _MANIFEST.get("aliases", {})
if _aliases:
    _resolve_aliases(_MANIFEST, _aliases)

_IMAGE_TREE = _MANIFEST["images"]
_DEFAULT_IMAGE = _MANIFEST.get("default_image", "")
_APP_NAME = _MANIFEST.get("app_name", "bootc Installer")


# ── Icon helpers ─────────────────────────────────────────────────────────────

def _find_icon_for_imgref(imgref: str) -> "str | None":
    """Search the manifest tree for imgref and return its inherited icon, or None."""
    def _search(nodes, icon_ctx=None):
        for node in nodes:
            node_icon = node.get("icon", icon_ctx)
            if node.get("imgref") == imgref:
                return node_icon
            if "children" in node:
                result = _search(node["children"], node_icon)
                if result is not None:
                    return result
        return None
    if not imgref:
        return None
    return _search(_MANIFEST.get("images", []))


# ── Pretty name helpers ───────────────────────────────────────────────────────

def _catalog_pretty_name(name, imgref):
    """Keep the selected catalog's identity; derive a name only as fallback."""
    return name.strip() if isinstance(name, str) and name.strip() else _imgref_to_pretty_name(imgref)


def _imgref_to_pretty_name(imgref: str) -> str:
    """Derive a human-readable name from an OCI image reference.

    'ghcr.io/ublue-os/bluefin-dx:latest' → 'Bluefin DX'
    First word: Title Case. Subsequent words: ALL CAPS.
    """
    try:
        if "/" not in imgref:
            return imgref
        slug = imgref.split("/")[-1].split(":")[0]   # e.g. "bluefin-dx"
        parts = slug.replace("_", "-").split("-")
        return " ".join(
            p.capitalize() if i == 0 else p.upper()
            for i, p in enumerate(parts)
        )
    except Exception:
        return imgref


def _count_leaves(nodes: list) -> int:
    """Count the selectable leaf image nodes in the tree."""
    return sum(1 for _ in catalog.walk(nodes))


_LEAF_COUNT = _count_leaves(_IMAGE_TREE)


def _make_icon(icon_spec: str, size: int = 32) -> "Gtk.Image | None":
    """Return a GtkImage for an icon spec, or None if blank/unresolvable.

    Supported formats:
      resource:///org/bootcinstaller/Installer/images/foo.svg  — bundled GResource
      /absolute/path/to/icon.svg                       — filesystem (distro override)
      icon-name-symbolic                               — XDG icon theme name
    """
    if not icon_spec:
        return None
    img = Gtk.Image()
    img.set_pixel_size(size)
    try:
        from bootc_installer.utils.icons import set_image_icon
        set_image_icon(img, icon_spec)
        return img
    except Exception as e:
        logger.warning(f"Could not load icon {icon_spec!r}: {e}")
        return None



@Gtk.Template(resource_path="/org/bootcinstaller/Installer/gtk/default-image.ui")
class BootcDefaultImage(Adw.Bin):
    __gtype_name__ = "BootcDefaultImage"

    btn_next        = Gtk.Template.Child()
    search_entry    = Gtk.Template.Child()
    list_images     = Gtk.Template.Child()
    list_custom     = Gtk.Template.Child()
    row_custom      = Gtk.Template.Child()
    image_url_entry = Gtk.Template.Child()

    def __init__(self, window, distro_info, key, step, **kwargs):
        super().__init__(**kwargs)
        self.__window = window
        self.__distro_info = distro_info
        self.__key = key
        self.__step = step
        self.delta = False

        # The image selected at the start (shared/catalog/README.md): the
        # branding contract's `default_image`, then the catalog's. Each
        # counts only when the catalog has that leaf; with neither, nothing
        # is selected and the user must choose. Never the first row.
        branding = window.recipe.get("branding") if isinstance(
            getattr(window, "recipe", None), dict) else None
        branding_default = branding.get("default_image", "") if isinstance(branding, dict) else ""
        self.__default_candidates = [ref for ref in (branding_default, _DEFAULT_IMAGE) if ref]
        self.__default_image = ""
        self.__selected_imgref = None
        self.__selected_leaf = None      # the resolved catalog leaf (bootc_shared.catalog)
        self.__selected_carousel = None  # per-image carousel slides (None = use recipe default)
        self.__selected_icon = None      # icon spec for selected image (str or None)
        self.__selected_pretty_name = None
        self.__all_expanders = []   # every ExpanderRow widget
        # One tuple for each leaf: (row, check, imgref, flatpaks, icon,
        # carousel, needs_user, composefs, image_type, bootloader,
        # image_filesystem, flatpak_var_path, default_hostname, filesystems,
        # search_str, [ancestor_exps], leaf).
        self.__leaf_rows = []

        # Hidden anchor for the radio CheckButton group.
        self.__radio_anchor = Gtk.CheckButton()

        self.list_images.set_selection_mode(Gtk.SelectionMode.NONE)
        self.__build_list()

        self.search_entry.connect("search-changed", self.__on_search_changed)
        self.row_custom.connect("notify::expanded", self.__on_custom_toggled)
        self.image_url_entry.connect("changed", self.__on_url_changed)
        self.btn_next.connect("clicked", self.__on_next_clicked)

        self.__select_default()
        self.__update_btn_next()

    def __on_next_clicked(self, *args):
        # Rebuild downstream steps so they can react to the selected image
        # (e.g. show/hide user-creation step based on needs_user_creation).
        self.__window.rebuild_ui_after_image()
        self.__window.next()

    # ── Recursive tree construction ───────────────────────────────────────────

    def __build_list(self):
        # bootc_shared.catalog resolves each leaf: what it inherits, its image
        # reference, its Flatpak list. This page draws the tree.
        resolved = {id(node): leaf
                    for node, leaf in catalog.walk(_IMAGE_TREE, _MANIFEST.get("aliases"))}
        for node in _IMAGE_TREE:
            self.__build_node(self.list_images, node, [], "", resolved)

        # Recipe-defined extra images (flat group).
        extra = self.__window.recipe.get("images", [])
        if extra:
            exp = Adw.ExpanderRow(title="Recipe Images")
            self.__all_expanders.append(exp)
            for img, leaf in catalog.walk([i for i in extra if isinstance(i, dict)
                                           and i.get("imgref")]):
                self.__add_leaf(
                    exp, img.get("name", leaf["imgref"]), leaf,
                    img.get("description", ""), "", [exp], img.get("icon"),
                    img.get("carousel"))
            self.list_images.append(exp)

    def __build_node(self, parent, node, ancestors, search_ctx, resolved,
                     icon_ctx=None, carousel_ctx=None):
        """Recursively build ExpanderRow groups and ActionRow leaves."""
        if not isinstance(node, dict):
            return
        # The icon and the carousel are for the page only; they inherit as
        # the contract fields do.
        node_icon = node.get("icon", icon_ctx)
        node_carousel = node.get("carousel", carousel_ctx)

        leaf = resolved.get(id(node))
        if leaf is not None:
            self.__add_leaf(parent, node.get("name") or leaf["imgref"], leaf,
                            node.get("desc", ""), search_ctx, ancestors,
                            node_icon, node_carousel)
            return
        if "tag" in node or "imgref" in node:
            return  # a leaf the catalog reader refused (no registry in scope)

        name = node.get("name", "")
        exp = Adw.ExpanderRow(title=name)
        if "subtitle" in node:
            exp.set_subtitle(node["subtitle"])

        icon_spec = node.get("icon")
        if icon_spec:
            img = _make_icon(icon_spec, size=32)
            if img:
                img.add_css_class("icon-dropshadow")
                exp.add_prefix(img)

        self.__all_expanders.append(exp)

        child_ctx = search_ctx + " " + name
        if "search_extra" in node:
            child_ctx += " " + node["search_extra"]
        child_ancestors = ancestors + [exp]

        for child in node.get("children", []):
            self.__build_node(exp, child, child_ancestors, child_ctx, resolved,
                              node_icon, node_carousel)

        if parent is self.list_images:
            parent.append(exp)
        else:
            parent.add_row(exp)

    def __add_leaf(self, parent, name, leaf, desc, search_ctx, ancestors,
                   icon=None, carousel=None):
        imgref = leaf["imgref"]
        search_str = f"{search_ctx} {name} {desc} {imgref}".lower()

        row = Adw.ActionRow(title=name, subtitle=imgref)
        if desc:
            row.set_tooltip_text(desc)
        row.set_activatable(True)

        check = Gtk.CheckButton()
        check.set_group(self.__radio_anchor)
        row.add_prefix(check)
        row.set_activatable_widget(check)
        check.connect("toggled", self.__on_check_toggled, leaf, icon, carousel)

        # Leaf icon — only for nodes that explicitly define one (e.g. BootcOS variants).
        if icon:
            img = _make_icon(icon, size=24)
            if img:
                row.add_suffix(img)

        if parent is self.list_images:
            parent.append(row)
        else:
            parent.add_row(row)
        self.__leaf_rows.append((
            row, check, imgref, leaf["flatpaks"], icon, carousel,
            leaf["needs_user_creation"], leaf["composefs"], leaf["image_type"],
            leaf["bootloader"], leaf["filesystem"], leaf["flatpak_var_path"],
            leaf["default_hostname"], leaf["filesystems"], search_str,
            list(ancestors), leaf))

    def __select_default(self):
        known = {entry[2]: entry for entry in self.__leaf_rows}
        for candidate in self.__default_candidates:
            entry = known.get(candidate)
            if entry is None:
                continue
            self.__default_image = candidate
            entry[1].set_active(True)
            for exp in entry[15]:
                exp.set_expanded(True)
            return
        # No default image — leave everything collapsed, nothing pre-selected.

    # ── Selection handlers ────────────────────────────────────────────────────

    def __on_check_toggled(self, check, leaf, icon=None, carousel=None):
        if check.get_active():
            self.__selected_leaf = leaf
            self.__selected_imgref = leaf["imgref"]
            self.__selected_icon = icon
            self.__selected_carousel = carousel
            self.__selected_pretty_name = _catalog_pretty_name(leaf["product"], leaf["imgref"])
            logger.info(f"Image selected: {leaf['imgref']} ({self.__selected_pretty_name})")
            if self.row_custom.get_expanded():
                self.row_custom.set_expanded(False)
            self.__update_btn_next()

    def __on_custom_toggled(self, expander, _param):
        if expander.get_expanded():
            self.__radio_anchor.set_active(True)
            self.__selected_leaf = None
            self.__selected_imgref = None
            self.__selected_icon = None
            self.__selected_carousel = None
            self.__selected_pretty_name = None
        self.__update_btn_next()

    def __on_url_changed(self, entry):
        url = entry.get_text().strip()
        valid = bool(url) and re.match(r"^.+/.+:.+$", url) is not None
        if url:
            entry.remove_css_class("error") if valid else entry.add_css_class("error")
        else:
            entry.remove_css_class("error")
        self.__update_btn_next()

    # ── Search / filtering ────────────────────────────────────────────────────

    def __on_search_changed(self, entry):
        query = entry.get_text().lower().strip()

        if not query:
            for exp in self.__all_expanders:
                exp.set_visible(True)
                exp.set_expanded(False)
            for entry_row in self.__leaf_rows:
                entry_row[0].set_visible(True)
            self.__expand_default_path()
            return

        # Determine which leaves match and which expanders are needed.
        visible_expanders = set()
        for entry_row in self.__leaf_rows:
            row, search_str, ancestors = entry_row[0], entry_row[14], entry_row[15]
            if query in search_str:
                row.set_visible(True)
                for exp in ancestors:
                    visible_expanders.add(id(exp))
            else:
                row.set_visible(False)

        for exp in self.__all_expanders:
            if id(exp) in visible_expanders:
                exp.set_visible(True)
                exp.set_expanded(True)
            else:
                exp.set_visible(False)

    def __expand_default_path(self):
        for entry_row in self.__leaf_rows:
            if self.__default_image and entry_row[2] == self.__default_image:
                for exp in entry_row[15]:
                    exp.set_expanded(True)
                return
        # No default image — leave everything collapsed.

    # ── Sensitivity ───────────────────────────────────────────────────────────

    def __update_btn_next(self):
        if self.row_custom.get_expanded():
            url = self.image_url_entry.get_text().strip()
            ok = bool(url) and re.match(r"^.+/.+:.+$", url) is not None
        else:
            ok = self.__selected_imgref is not None
        self.btn_next.set_sensitive(ok)

    # ── Test / finals ─────────────────────────────────────────────────────────

    def should_show(self, context: dict) -> bool:
        return context.get("leaf_count", 2) > 1

    @property
    def skip_screen(self) -> bool:
        """True when the manifest contains only one selectable image."""
        return not self.should_show({"leaf_count": self.leaf_count})

    @property
    def leaf_count(self) -> int:
        return _LEAF_COUNT

    @property
    def selected_needs_user_creation(self) -> bool:
        """True if the installer creates the first account for the selected
        image. The default is True (shared/catalog/README.md): also for an
        image the user typed, and while nothing is selected."""
        if self.__selected_leaf is None:
            return True
        return self.__selected_leaf["needs_user_creation"]

    def test_auto_advance(self):
        self.btn_next.emit("clicked")

    def get_finals(self):
        if self.row_custom.get_expanded():
            return image_finals.custom_image_finals(self.image_url_entry.get_text().strip())
        if self.__selected_leaf is None:
            # Nothing selected: Next is off, and no field of an image goes on.
            return {
                "selected_image": None,
                "pretty_name": None,
                "flatpak_var_path": "",
                "carousel": None,
                "needs_user_creation": True,
                "composefs_backend": False,
                "image_type": "bootc",
                "bootloader": "",
                "image_filesystem": "",
                "icon": None,
                "default_hostname": "",
                "supported_filesystems": [],
            }
        finals = image_finals.leaf_finals(
            self.__selected_leaf, self.__selected_icon, self.__selected_carousel)
        finals["pretty_name"] = self.__selected_pretty_name
        return finals
