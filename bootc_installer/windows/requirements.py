"""The text of the RAM, CPU and UEFI gate windows.

fisherman decides which minimum requirements a machine misses
(`fisherman probe --json`, `system.unmet`); GNOME blocks with one window per
item, as it always has. What each window says is the shared copy every
frontend shows: requirements_title, then the line for the item.
"""

from types import SimpleNamespace

from bootc_installer.utils import copy as copy_text
from bootc_installer.utils.recipe import RecipeLoader


def requirements_text(key: str, recipe: dict | None = None) -> str:
    holder = SimpleNamespace(recipe=RecipeLoader().raw if recipe is None else recipe)
    lines = [copy_text.text(holder, "requirements_title"), copy_text.text(holder, key)]
    return "\n".join(line for line in lines if line)
