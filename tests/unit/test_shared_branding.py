"""The branding contract: shared/branding/README.md.

shared/branding/branding.py is the canonical resolver. The GNOME frontend
(bootc_installer/utils/branding.py) and the XFCE frontend
(frontends/xfce/tuna_installer_xfce/branding.py) ship byte-identical copies
because each Flatpak builds from its own tree; if a copy drifts, "shared"
is a lie, so this test fails.

The fixture cases in shared/branding/fixtures/expected.json are the same
ones the Go, C++ and Rust resolvers test against.
"""

import importlib.util
import json
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SHARED = REPO / "shared" / "branding" / "branding.py"
COPIES = [
    REPO / "bootc_installer" / "utils" / "branding.py",
    REPO / "frontends" / "xfce" / "tuna_installer_xfce" / "branding.py",
]
FIXTURES = REPO / "shared" / "branding" / "fixtures"


def _load(path):
    spec = importlib.util.spec_from_file_location("branding_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


branding = _load(SHARED)


class CopiesAreIdentical(unittest.TestCase):
    def test_every_copy_matches_the_shared_module(self):
        canonical = SHARED.read_bytes()
        for copy in COPIES:
            self.assertEqual(
                copy.read_bytes(), canonical,
                f"{copy.relative_to(REPO)} has diverged from shared/branding/branding.py; "
                "edit the shared copy and cp it over",
            )


class FixtureCases(unittest.TestCase):
    """Every language's resolver must reproduce expected.json."""

    @classmethod
    def setUpClass(cls):
        cls.expected = json.loads((FIXTURES / "expected.json").read_text())

    def _inputs(self, case):
        file_data = None
        if case["branding"]:
            file_data = json.loads((FIXTURES / case["branding"]).read_text())
        os_release = None
        if case["os_release"]:
            os_release = (FIXTURES / case["os_release"]).read_text()
        return file_data, os_release

    def test_pure_resolution_matches_expected(self):
        for name, case in self.expected.items():
            if name.startswith("_") or "expect" not in case:
                continue
            with self.subTest(case=name):
                file_data, os_release = self._inputs(case)
                got = branding.from_sources(file_data, os_release).as_dict()
                self.assertEqual(got, case["expect"])

    def test_name_override_wins(self):
        case = self.expected["name_override"]
        file_data, os_release = self._inputs(case)
        got = branding.from_sources(file_data, os_release, case["name_override"])
        self.assertEqual(got.name, case["expect_name"])
        self.assertEqual(got.source, "env")
        # The override touches nothing else.
        self.assertEqual(got.default_image, "ghcr.io/example/marlin:latest")

    def test_resolve_reads_files_in_order(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            missing = tmp / "missing.json"
            broken = tmp / "broken.json"
            broken.write_text("{ not json")
            good = tmp / "good.json"
            good.write_text('{"name": "FromFile"}')
            osr = tmp / "os-release"
            osr.write_text('ID=filetest\nPRETTY_NAME="From OS"\n')
            got = branding.resolve(
                branding_paths=[str(missing), str(broken), str(good)],
                os_release_paths=[str(tmp / "no-such"), str(osr)],
                env={},
            )
            self.assertEqual(got.name, "FromFile")
            self.assertEqual(got.source, "file")
            self.assertEqual(got.id, "filetest")
            self.assertEqual(got.default_hostname, "filetest")

            # The env file path replaces the search list entirely.
            got = branding.resolve(
                branding_paths=None,
                os_release_paths=[str(osr)],
                env={branding.ENV_FILE: str(good)},
            )
            self.assertEqual(got.name, "FromFile")

            # Nothing readable: neutral, and never a product name.
            got = branding.resolve(
                branding_paths=[str(missing)], os_release_paths=[str(missing)], env={},
            )
            self.assertEqual(got.name, "Linux")
            self.assertEqual(got.id, "linux")
            self.assertEqual(got.source, "default")


class OsReleaseParsing(unittest.TestCase):
    def test_quotes_escapes_and_comments(self):
        text = (
            "# comment\n"
            'NAME="Quoted Name"\n'
            "PRETTY_NAME='Single \"inner\"'\n"
            "ID=plain\n"
            "BROKEN=\"unterminated\n"
            "EMPTY=\n"
            "NOEQUALS\n"
        )
        got = branding.parse_os_release(text)
        self.assertEqual(got["NAME"], "Quoted Name")
        self.assertEqual(got["PRETTY_NAME"], 'Single "inner"')
        self.assertEqual(got["ID"], "plain")
        self.assertEqual(got["BROKEN"], "unterminated")
        self.assertEqual(got["EMPTY"], "")
        self.assertNotIn("NOEQUALS", got)

    def test_no_product_name_is_hardcoded(self):
        source = SHARED.read_text().lower()
        for banned in ("bluefin", "tunaos", "tuna-os", "dakota"):
            self.assertNotIn(banned, source, f"branding.py must not mention {banned!r}")


if __name__ == "__main__":
    unittest.main()
