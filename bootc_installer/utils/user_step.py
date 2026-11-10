"""Whether the user step shows: one answer for every page that needs it.

The user page asks it for itself, and the phone companion asks it too: the
companion form collects an account, so it hides when no account is created.
No GTK here, so both pages and the headless tests can import it.

The rule is shared/catalog/README.md, "The account": the flag comes from
the leaf that the user selected. With no image page (live media), it comes
from the leaf of the image that is installed. When no node sets the flag,
or no leaf has that image, the installer creates an account.
"""

import logging

from bootc_shared import catalog

logger = logging.getLogger("Installer::User")

_NODE_KEYS = ("imgref", "tag", "registry", "children")


def _loaded_catalog():
    """The catalog the image page reads (the search path, then the package),
    or the first file of the search path when that module cannot load."""
    try:
        from bootc_installer.defaults.image import _MANIFEST
        if catalog.is_catalog(_MANIFEST):
            return _MANIFEST
    except Exception as error:  # noqa: BLE001 - no GTK, no GResource: read the files
        logger.debug("image catalog module not available: %s", error)
    return catalog.load_first(catalog.default_search_paths())[0]


def account_needed_for(sys_recipe, loaded_catalog=None) -> bool:
    """Whether the installer creates an account when there is no image page.

    The image is the system recipe's `imgref` (on live media the recipe
    loader puts the probe's `live.live_image` there). Its leaf is looked up
    in the recipe's own `images`, then in the catalog. A recipe `images`
    list of one entry that names no image is the metadata of the one image
    there is. Without a leaf the answer is True.
    """
    sys_recipe = sys_recipe if isinstance(sys_recipe, dict) else {}
    imgref = sys_recipe.get("imgref") or ""
    images = sys_recipe.get("images")
    if isinstance(images, list) and images:
        leaf = catalog.find({"images": images}, imgref)
        if leaf is not None:
            return leaf["needs_user_creation"]
        only = images[0] if len(images) == 1 else None
        if isinstance(only, dict) and not any(key in only for key in _NODE_KEYS):
            flag = only.get("needs_user_creation", True)
            return flag if isinstance(flag, bool) else True
    if loaded_catalog is None:
        loaded_catalog = _loaded_catalog()
    return catalog.needs_user_creation(loaded_catalog, imgref)


def user_step_shows(window, context: dict) -> bool:
    """True when the selected image needs the installer to create a user."""
    context = context or {}
    image_step = getattr(window, "image_step", None)
    if image_step is None or context.get("leaf_count", 2) <= 1:
        # No usable image step: the image is the one the recipe names.
        sys_recipe = context.get("sys_recipe") or getattr(window, "recipe", {})
        nuc = account_needed_for(sys_recipe)
        logger.info("should_show (no image step): needs_user_creation=%s → show=%s", nuc, nuc)
        return nuc
    nuc = image_step.selected_needs_user_creation
    logger.info("should_show: selected_needs_user_creation=%s → show=%s", nuc, nuc)
    return nuc
