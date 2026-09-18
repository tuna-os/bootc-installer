"""Flavour text for the views: recipe["branding"]["copy"] with placeholders filled.

The RecipeLoader puts the resolved branding (shared/branding/README.md) under
recipe["branding"]; views call text(window, key, disk=...) and never carry a
product string of their own. Missing branding (unit tests that build a bare
recipe) falls back to the neutral defaults.
"""

from bootc_installer.utils.branding import COPY_DEFAULTS


def _branding(window) -> dict:
    recipe = getattr(window, "recipe", None)
    if isinstance(recipe, dict):
        b = recipe.get("branding")
        if isinstance(b, dict):
            return b
    return {}


def product_name(window) -> str:
    b = _branding(window)
    if b.get("name"):
        return b["name"]
    recipe = getattr(window, "recipe", None)
    if isinstance(recipe, dict) and recipe.get("distro_name"):
        return recipe["distro_name"]
    return "Linux"


def text(window, key: str, **values) -> str:
    """A copy line for `key` with {name} and any given placeholder filled in."""
    b = _branding(window)
    copy = b.get("copy") if isinstance(b.get("copy"), dict) else {}
    line = copy.get(key, COPY_DEFAULTS.get(key, ""))
    values.setdefault("name", product_name(window))
    for k, v in values.items():
        line = line.replace("{" + k + "}", str(v))
    return line


def confirm_subtitle(window, language: str = "") -> str:
    """The confirm subtitle for the selected language: a confirm_quotes line
    when the branding has one for that language, else copy.confirm_subtitle."""
    b = _branding(window)
    quotes = b.get("confirm_quotes") if isinstance(b.get("confirm_quotes"), dict) else {}
    lang = (language or "").split(".")[0].split("@")[0]
    for candidate in (lang, lang.split("_")[0]):
        lines = quotes.get(candidate) if candidate else None
        if lines:
            import random
            return random.choice(lines)
    return text(window, "confirm_subtitle")
