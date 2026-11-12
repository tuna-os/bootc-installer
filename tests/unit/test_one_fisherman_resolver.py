"""Every frontend reaches fisherman through one resolver (#290).

GNOME stages the fisherman that its Flatpak builds to
`$XDG_CACHE_HOME/bootc-installer/fisherman`, checks its SHA256 on the host,
and runs that copy. KDE, COSMIC, Niri and XFCE used to name
`/usr/local/bin/fisherman` in their probe, validate and install code. Their
Flatpaks built `/app/bin/fisherman` and never ran it, so they worked only
where an ISO had put fisherman on the host.

Each frontend now has one resolver (RESOLVER). This test holds four rules:

- No other source file of the frontend names a fisherman path.
- The resolver stages the bundled binary in the application cache, never in
  `HOME/.cache`, and checks it with SHA256.
- A native install escalates with pkexec. `sudo` appears only as `sudo -n`
  (live media, no terminal for a prompt).
- Each Flatpak manifest builds the `/app/bin/fisherman` that the resolver
  stages.

The per-frontend tests run each resolver: `test_fisherman_runner.py` and
`frontends/xfce/tests/test_core.py` (TestStaging), KDE `test_backend.cpp`,
COSMIC `offline.rs`, Niri `offline_test.go`.
"""

import json
import re
import unittest

from tests.unit.test_no_frontend_detection import FRONTENDS, REPO, frontend_files

SHARED_PYTHON = "shared/python/bootc_shared/fisherman_host.py"

# frontend -> the files that are its resolver.
RESOLVER = {
    "gnome": (SHARED_PYTHON,),
    "kde": ("frontends/kde/src/fisherman.h", "frontends/kde/src/fisherman.cpp"),
    "cosmic": ("frontends/cosmic/src/offline.rs",),
    "niri": ("frontends/niri/installer/offline.go",),
    "xfce": (SHARED_PYTHON,),
}

MANIFEST = {
    "gnome": "flatpak/org.bootcinstaller.Installer.json",
    "kde": "frontends/kde/flatpak/org.tunaos.InstallerKde.json",
    "cosmic": "frontends/cosmic/flatpak/org.tunaos.InstallerCosmic.json",
    "niri": "frontends/niri/flatpak/org.tunaos.InstallerNiri.json",
    "xfce": "frontends/xfce/flatpak/org.tunaos.InstallerXfce.json",
}

NATIVE = "/usr/local/bin/fisherman"
BUNDLED = "/app/bin/fisherman"
FISHERMAN_PATH = re.compile(re.escape(NATIVE) + "|" + re.escape(BUNDLED))
# A string that starts with sudo, and does not go on with -n.
SUDO_WITHOUT_N = re.compile(r"""["'`]sudo\b(?!\s+-n\b)""")


def code_of(frontend):
    """{repo-relative path: code with comments removed}."""
    return {str(path.relative_to(REPO)): code for path, code in frontend_files(frontend)}


def resolver_code(frontend, code):
    return "\n".join(code[path] for path in RESOLVER[frontend])


def modules(manifest_path):
    """The manifest's modules, with each file reference read in."""
    path = REPO / manifest_path
    for module in json.loads(path.read_text())["modules"]:
        if isinstance(module, str):
            module = json.loads((path.parent / module).resolve().read_text())
        yield module


class OneFishermanResolver(unittest.TestCase):
    def test_the_resolver_is_part_of_the_scanned_code(self):
        for frontend in FRONTENDS:
            code = code_of(frontend)
            for path in RESOLVER[frontend]:
                with self.subTest(frontend=frontend, path=path):
                    self.assertIn(path, code)

    def test_only_the_resolver_names_a_fisherman_path(self):
        for frontend in FRONTENDS:
            for path, text in code_of(frontend).items():
                if path in RESOLVER[frontend]:
                    continue
                with self.subTest(frontend=frontend, path=path):
                    found = FISHERMAN_PATH.search(text)
                    self.assertIsNone(
                        found,
                        f"{path} names {found.group(0) if found else ''}: take fisherman "
                        f"from the resolver ({', '.join(RESOLVER[frontend])})")

    def test_the_resolver_knows_both_binaries(self):
        for frontend in FRONTENDS:
            text = resolver_code(frontend, code_of(frontend))
            for binary in (NATIVE, BUNDLED):
                with self.subTest(frontend=frontend, binary=binary):
                    self.assertIn(binary, text)

    def test_the_resolver_stages_in_the_application_cache_and_checks_the_hash(self):
        for frontend in FRONTENDS:
            text = resolver_code(frontend, code_of(frontend))
            with self.subTest(frontend=frontend):
                self.assertIn("XDG_CACHE_HOME", text)
                self.assertIn("bootc-installer", text)
                self.assertRegex(text, re.compile("sha256", re.IGNORECASE))
                self.assertNotRegex(text, r"""["']\.cache["']""",
                                    "never derive the staging path from HOME/.cache")

    def test_native_installs_escalate_with_pkexec_and_sudo_only_with_n(self):
        for frontend in FRONTENDS:
            text = resolver_code(frontend, code_of(frontend))
            with self.subTest(frontend=frontend):
                self.assertIn("pkexec", text)
                self.assertIn("sudo -n", text)
                found = SUDO_WITHOUT_N.search(text)
                self.assertIsNone(
                    found, "sudo without -n waits for a password that a GUI cannot type")

    def test_every_flatpak_builds_the_binary_its_resolver_stages(self):
        for frontend, manifest in MANIFEST.items():
            with self.subTest(frontend=frontend):
                commands = [
                    command
                    for module in modules(manifest) if module.get("name") == "fisherman"
                    for command in module.get("build-commands", [])
                ]
                self.assertTrue(any(f"-o {BUNDLED} " in c for c in commands), commands)

    def test_the_patterns_see_what_used_to_be_there(self):
        """Guards the guard: the code #290 removed matches the rules."""
        self.assertIsNotNone(FISHERMAN_PATH.search(
            'QStringLiteral("/usr/local/bin/fisherman"), {"probe", "--json"}'))
        self.assertIsNotNone(SUDO_WITHOUT_N.search('["sudo", "/usr/local/bin/fisherman", "-"]'))
        self.assertIsNotNone(SUDO_WITHOUT_N.search('"sudo /usr/local/bin/fisherman -"'))
        self.assertIsNone(SUDO_WITHOUT_N.search('"sudo -n /usr/local/bin/fisherman -; exit $?"'))
        self.assertIsNone(SUDO_WITHOUT_N.search('{ "sudo -n" } else'))


if __name__ == "__main__":
    unittest.main()
