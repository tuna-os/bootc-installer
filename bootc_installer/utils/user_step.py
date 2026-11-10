"""Whether the user step shows: one answer for every page that needs it.

The user page asks it for itself, and the phone companion asks it too: the
companion form collects an account, so it hides when no account is created.
No GTK here, so both pages and the headless tests can import it.
"""

import json
import logging
import os

logger = logging.getLogger("Installer::User")

_IN_FLATPAK = os.path.exists("/.flatpak-info")
_ETC = "/run/host/etc" if _IN_FLATPAK else "/etc"
IMAGES_JSON = f"{_ETC}/bootc-installer/images.json"


def user_step_shows(window, context: dict) -> bool:
    """True when the selected image needs the installer to create a user."""
    context = context or {}
    image_step = getattr(window, "image_step", None)
    if image_step is None or context.get("leaf_count", 2) <= 1:
        # No usable image step: check sys_recipe["images"] first (handles removed
        # image-step cases), then fall back to images.json.
        sys_recipe = context.get("sys_recipe") or getattr(window, "recipe", {})
        recipe_images = sys_recipe.get("images", [])
        if recipe_images:
            nuc = recipe_images[0].get("needs_user_creation", True)
            logger.info("should_show (recipe images): needs_user_creation=%s → show=%s", nuc, nuc)
            return nuc
        # Live ISO mode: read needs_user_creation from /etc/bootc-installer/images.json
        try:
            with open(IMAGES_JSON) as f:
                data = json.load(f)
            images = data.get("images", [data]) if "images" in data else [data]
            nuc = images[0].get("needs_user_creation", True)
            logger.info("should_show (live ISO): needs_user_creation=%s from images.json → show=%s", nuc, nuc)
            return nuc
        except Exception as e:
            logger.warning("should_show: image metadata unavailable (%s) — showing user step", e)
            return True
    nuc = image_step.selected_needs_user_creation
    logger.info("should_show: selected_needs_user_creation=%s → show=%s", nuc, nuc)
    return nuc
