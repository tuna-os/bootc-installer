# image_finals.py
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

"""What the image page hands to the other steps.

The catalog reader is bootc_shared.catalog (shared/python/), which XFCE
also uses. This module is the GNOME half: the `finals` of the image step,
which the Processor, the disk page and the user step read.
"""

from bootc_shared import catalog


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
        "pretty_name": leaf["product"] or catalog.pretty_from_imgref(leaf["imgref"]),
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
        "pretty_name": catalog.pretty_from_imgref(imgref),
        "carousel": None,
        "needs_user_creation": True,
        "composefs_backend": False,
        "image_type": "bootc",
        "bootloader": "",
        "image_filesystem": "",
        "icon": None,
    }
