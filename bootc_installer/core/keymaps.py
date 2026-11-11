"""The XKB layouts the keyboard step offers.

GnomeDesktop's XkbInfo names them. It is optional: without its typelib the
list comes from xkeyboard-config's own rules file (evdev.xml), which any
system with XKB has. Either way each entry has `xkb_layout` and
`xkb_variant`, the recipe's `keyboard.layout` and `keyboard.variant`.
"""

import xml.etree.ElementTree as ET

try:
    from gi.repository.GnomeDesktop import XkbInfo
except (ImportError, ValueError, AttributeError):
    XkbInfo = None

EVDEV_XML = "/usr/share/X11/xkb/rules/evdev.xml"


def evdev_layouts(path=EVDEV_XML):
    """{"layout" or "layout+variant": (display name, short name, layout,
    variant)} from an xkeyboard-config rules file; {} when it cannot be
    read."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return {}
    found = {}
    for layout in root.iter("layout"):
        item = layout.find("configItem")
        name = item.findtext("name") if item is not None else None
        if not name:
            continue
        short = item.findtext("shortDescription") or name
        found[name] = (item.findtext("description") or name, short, name, "")
        for variant in layout.iter("variant"):
            vitem = variant.find("configItem")
            vname = vitem.findtext("name") if vitem is not None else None
            if vname:
                found[f"{name}+{vname}"] = (vitem.findtext("description") or vname,
                                            vitem.findtext("shortDescription") or short,
                                            name, vname)
    return found


class KeyMaps:
    def __init__(self):
        self.__all_keymaps = self.__get_all_keymaps()

    def __layout_infos(self):
        """{id: (display name, short name, layout, variant)}."""
        if XkbInfo is None:
            return evdev_layouts()
        xkb_info = XkbInfo()
        return {layout: tuple(xkb_info.get_layout_info(layout)[1:5])
                for layout in xkb_info.get_all_layouts()}

    def __get_all_keymaps(self):
        _all_keymaps = {}
        all_keymaps = {}
        cleanup_rules = ["A"]

        for layout, _info in self.__layout_infos().items():
            _all_keymaps[layout] = {}
            _all_keymaps[layout]["display_name"] = _info[0]
            _all_keymaps[layout]["short_name"] = _info[1]
            _all_keymaps[layout]["xkb_layout"] = _info[2]
            _all_keymaps[layout]["xkb_variant"] = _info[3]

        for layout in _all_keymaps:
            country = _all_keymaps[layout]["display_name"].split(" ")[0]

            if country in cleanup_rules:
                continue

            if country not in all_keymaps:
                all_keymaps[country] = {}

            all_keymaps[country][layout] = _all_keymaps[layout]

        all_keymaps = {
            k: v for k, v in sorted(all_keymaps.items(), key=lambda item: item[0])
        }
        return all_keymaps

    @property
    def list_all(self):
        return self.__all_keymaps
