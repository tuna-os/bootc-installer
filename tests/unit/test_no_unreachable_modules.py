"""Every GNOME module and Blueprint template is one the installer can reach (#312).

About 4,300 lines of wizard code were installed, translated and unit-tested,
and no recipe could show them: pages that `utils/builder.py` did not
register, a locale table that imported a package of another project, a
second launcher that imported modules that do not exist. These tests fail
when such code comes back:

- each module under `bootc_installer/` is imported, directly or through
  other modules, by the launcher (`bootc-installer.in`);
- each launcher in the package is installed, and imports only modules that
  exist;
- each Blueprint template is loaded by a Python class, and the GResource
  bundle lists the same templates as the Blueprint sources.
"""

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
PKG = ROOT / "bootc_installer"


def _module_name(path):
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    return ".".join(parts)


def _modules():
    return {_module_name(p): p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts}


def _imports(path, package):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*parts, base] if base else parts)
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _launchers():
    return sorted(PKG.glob("*.in"))


def _launcher_imports(path):
    # A launcher is Python with meson placeholders: `'@VERSION@'` parses.
    return _imports(path, "bootc_installer")


def _reachable():
    modules = _modules()
    seen = set()
    stack = []
    for launcher in _launchers():
        stack.extend(_launcher_imports(launcher))
    while stack:
        name = stack.pop()
        for candidate in (name, f"{name}.__init__", name.rsplit(".", 1)[0]):
            if candidate in modules and candidate not in seen:
                seen.add(candidate)
                package = candidate.rsplit(".", 1)[0]
                if candidate.endswith(".__init__"):
                    package = candidate[: -len(".__init__")]
                stack.extend(_imports(modules[candidate], package))
    return seen


def test_every_module_is_reachable_from_the_launcher():
    unreachable = sorted(
        name for name in set(_modules()) - _reachable()
        if not name.endswith("__init__")
    )
    assert unreachable == [], (
        "modules that nothing the launcher runs imports; register them in "
        "utils/builder.py and the bundled recipe.json, or delete them"
    )


def test_every_launcher_is_installed_and_imports_what_exists():
    meson = (PKG / "meson.build").read_text(encoding="utf-8")
    modules = _modules()
    for launcher in _launchers():
        if launcher.name == "_version.py.in":
            continue
        assert f"input: '{launcher.name}'" in meson, launcher.name
        for name in _launcher_imports(launcher):
            if not name.startswith("bootc_installer"):
                continue
            # meson writes `_version.py` from `_version.py.in`.
            exists = (
                name in modules
                or f"{name}.__init__" in modules
                or name.rsplit(".", 1)[0] in modules
                or name == "bootc_installer._version"
            )
            assert exists, f"{launcher.name} imports {name}, which does not exist"


def _blueprints():
    return sorted(p.stem for p in (PKG / "gtk").glob("*.blp"))


def test_every_blueprint_is_loaded_by_a_class():
    sources = "\n".join(p.read_text(encoding="utf-8") for p in PKG.rglob("*.py"))
    unused = [b for b in _blueprints() if f"/gtk/{b}.ui" not in sources]
    assert unused == []


def test_the_gresource_lists_the_blueprints_and_nothing_else():
    xml = (PKG / "bootc-installer.gresource.xml").read_text(encoding="utf-8")
    listed = sorted(re.findall(r"<file>gtk/([^<]+)\.ui</file>", xml))
    assert listed == _blueprints()
    meson = (PKG / "meson.build").read_text(encoding="utf-8")
    compiled = sorted(re.findall(r"'gtk/([^']+)\.blp'", meson))
    assert compiled == _blueprints()


def test_every_registered_template_is_a_page_the_builder_can_build():
    """The other side of the contract: every name in the bundled recipe is
    a template that `utils/builder.py` registers."""
    import json

    builder = ast.parse((PKG / "utils" / "builder.py").read_text(encoding="utf-8"))
    templates = next(
        node.value for node in ast.walk(builder)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "templates" for t in node.targets)
    )
    registered = {k.value for k in templates.keys}
    recipe = json.loads((ROOT / "recipe.json").read_text(encoding="utf-8"))
    used = {step["template"] for step in recipe["steps"].values()}
    assert used <= registered
