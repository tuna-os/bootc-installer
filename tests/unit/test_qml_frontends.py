"""Regression guards for the QML frontends (KDE, Niri).

Each guard is a bug that shipped and that no render, capture or unit test
saw, because QML reports it at run time, on the page, in a handler:

* bootc-installer#397: the KDE account page's `onTextChanged` named
  `showPasswordQuality`, which the pinned Kirigami Addons (v1.7.0) lacks. The
  handler threw before it copied the password into the controller, every
  account was created locked, and the greeter rejected the right password.
* bootc-installer#400: niri's `ui/qmldir` listed Theme alone. A directory with a
  qmldir exposes only what it lists, so Quickshell never opened the window.
* The KDE `qt_add_qml_module` lists its QML files by hand: a page that is
  not listed is missing from the resource and Wizard.qml cannot load it.

Falsification: each test names the line to break. Delete the `userPassword`
assignment of a frontend's account page, drop a `Dank*` line from
frontends/niri/ui/qmldir, or add `showPasswordQuality` to a KDE page while the
manifest pins kirigami-addons 1.7, and the matching test fails.
"""

import json
import os
import re
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
KDE = os.path.join(REPO, "frontends", "kde")
NIRI = os.path.join(REPO, "frontends", "niri")

# Properties that a pinned dependency does not have yet, as
# (dependency, property): the release that added it. Naming one in a handler
# is a ReferenceError at run time. Add a row when a release note says a
# property is new; the manifest pin decides whether the row applies.
KIRIGAMI_ADDONS_SINCE = {
    "showPasswordQuality": (1, 8),
}


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as stream:
        return stream.read()


def _qml_files(root):
    found = []
    for base, _dirs, names in os.walk(root):
        found.extend(os.path.join(base, n) for n in names if n.endswith(".qml"))
    return sorted(found)


def _block_after(text, anchor, window=1500):
    """The text from the first `anchor` to the end of its delegate: the next
    `objectName:` line or `window` characters, whichever is first."""
    start = text.index(anchor)
    rest = text[start + len(anchor):start + len(anchor) + window]
    stop = re.search(r"objectName:", rest)
    return rest[:stop.start()] if stop else rest


class KdePasswordReachesTheController(unittest.TestCase):
    def setUp(self):
        self.page = _read(KDE, "modules", "account", "contents", "ui", "main.qml")

    def test_the_account_page_assigns_the_password(self):
        block = _block_after(self.page, 'objectName: "accountPassword"')
        self.assertRegex(block, r"InstallerController\.userPassword\s*=\s*text",
                         "the password field never assigns InstallerController.userPassword")

    def test_the_assignment_is_the_first_statement_of_the_handler(self):
        """A statement before the assignment can throw and end the handler
        (#397), so nothing may precede it."""
        block = _block_after(self.page, 'objectName: "accountPassword"')
        handler = re.search(r"onTextChanged:\s*(\{?)\s*(.*)", block)
        self.assertIsNotNone(handler, "the password field has no onTextChanged")
        self.assertTrue(handler.group(2).startswith("InstallerController.userPassword"),
                        f"the handler starts with {handler.group(2)[:60]!r}")

    def test_the_controller_property_is_writable(self):
        header = _read(KDE, "src", "installercontroller.h")
        self.assertRegex(header, r"Q_PROPERTY\(QString userPassword READ userPassword WRITE setUserPassword")

    def test_the_recipe_carries_it(self):
        # The recipe is written from the controller's recipe: setUserPassword
        # has to store into it.
        source = _read(KDE, "src", "installercontroller.cpp")
        body = re.search(r"void InstallerController::setUserPassword\([^)]*\)\s*\{(.*?)\n\}", source, re.S)
        self.assertIsNotNone(body)
        self.assertIn("m_recipe.user.password", body.group(1))


class NiriPasswordReachesTheRecipe(unittest.TestCase):
    def setUp(self):
        self.page = _read(NIRI, "ui", "installer.qml")

    def test_the_account_page_assigns_the_password(self):
        block = _block_after(self.page, 'objectName: "accountPassword"', window=600)
        self.assertRegex(block, r"root\.userPassword\s*=\s*(text|userPassField\.text)")

    def test_the_recipe_builder_is_given_the_password(self):
        self.assertRegex(self.page, r"password:\s*root\.userPassword")
        self.assertRegex(_read(NIRI, "ui", "recipe.js"), r'password:\s*c\.password')


class KdeAddonsPinHasEveryNamedProperty(unittest.TestCase):
    def test_no_page_names_a_property_the_pin_lacks(self):
        manifest = json.loads(_read(KDE, "flatpak", "org.tunaos.InstallerKde.json"))
        module = next(m for m in manifest["modules"]
                      if isinstance(m, dict) and m.get("name") == "kirigami-addons")
        tag = module["sources"][0]["tag"]
        major, minor = (int(n) for n in re.match(r"v(\d+)\.(\d+)", tag).groups())
        problems = []
        for path in _qml_files(os.path.join(KDE, "modules")) + _qml_files(os.path.join(KDE, "src", "qml")):
            text = _read(path)
            for prop, since in KIRIGAMI_ADDONS_SINCE.items():
                if (major, minor) < since and re.search(rf"\b{prop}\b", text):
                    problems.append(f"{os.path.relpath(path, REPO)} names {prop} (kirigami-addons "
                                    f"{since[0]}.{since[1]}); the manifest pins {tag}")
        self.assertEqual(problems, [])

    def test_the_check_finds_what_it_is_for(self):
        self.assertIn("showPasswordQuality", KIRIGAMI_ADDONS_SINCE)


class KdeCMakeListsEveryQmlFile(unittest.TestCase):
    def test_every_page_and_shell_file_is_in_the_qml_module(self):
        cmake = _read(KDE, "CMakeLists.txt")
        steps = re.search(r"set\(STEP_MODULES\s+([^)]*)\)", cmake).group(1).split()
        listed = {f"modules/{step}/contents/ui/main.qml" for step in steps}
        listed |= set(re.findall(r"^\s+(src/qml/\w+\.qml)\s*$", cmake, re.M))
        on_disk = {os.path.relpath(p, KDE) for p in _qml_files(os.path.join(KDE, "modules"))}
        on_disk |= {os.path.relpath(p, KDE) for p in _qml_files(os.path.join(KDE, "src", "qml"))}
        self.assertEqual(sorted(on_disk - listed), [],
                         "QML files that CMakeLists.txt does not put in the module")
        self.assertEqual(sorted(listed - on_disk), [], "CMakeLists.txt lists QML files that do not exist")


class NiriQmldirListsEveryComponent(unittest.TestCase):
    """The same rule as frontends/niri/installer/qmldir_test.go, here so that
    the repo's required Python check holds it, and extended: each listed file
    exists."""

    def test_every_component_is_listed_and_every_entry_exists(self):
        listed = {}
        for line in _read(NIRI, "ui", "qmldir").splitlines():
            fields = line.split()
            if not fields or fields[0].startswith("#"):
                continue
            if fields[0] in ("singleton", "internal"):
                fields = fields[1:]
            listed[fields[-1]] = fields[0]
        self.assertTrue(listed, "ui/qmldir lists nothing")
        for name in sorted(os.listdir(os.path.join(NIRI, "ui"))):
            if name.endswith(".qml") and name[0].isupper() and name != "installer.qml":
                self.assertEqual(listed.get(name), name[:-4], f"ui/qmldir does not list {name}")
        for name in listed:
            self.assertTrue(os.path.exists(os.path.join(NIRI, "ui", name)), f"qmldir lists missing {name}")


if __name__ == "__main__":
    unittest.main()
