"""shared/ci/frontends.json — the one table the publish path reads.

publish-flatpak.yml used to exist five times, once per frontend, and the
copies differed in six values. Those values are now rows of
shared/ci/frontends.json, and one publish-flatpak.yml takes the frontend's
name. Nothing can run that workflow here, so these tests hold the parts a
wrong edit would break without a red check: the table against the manifests
it names, the script that turns a row into job outputs, and the callers
against the table.
"""

import json
import os
import re
import sys
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "shared", "ci"))

import frontend_table as ft  # noqa: E402
import published_freshness as pf  # noqa: E402

WORKFLOWS = os.path.join(REPO, ".github", "workflows")
# flathub-infra/flatpak-github-actions names its images <family>-<version>.
IMAGE_FAMILY = {
    "org.gnome.Platform": "gnome",
    "org.kde.Platform": "kde",
    "org.freedesktop.Platform": "freedesktop",
}


def workflow(name):
    with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as stream:
        return stream.read()


class TableTest(unittest.TestCase):
    def setUp(self):
        self.table = ft.load()

    def test_the_five_frontends_in_the_order_the_other_scripts_use(self):
        self.assertEqual(list(self.table), ["gnome", "kde", "cosmic", "niri", "xfce"])
        self.assertEqual(pf.FRONTENDS, tuple(self.table))
        self.assertEqual(pf.APP_IDS, {n: row["app-id"] for n, row in self.table.items()})

    def test_each_row_matches_the_manifest_it_names(self):
        for name, row in self.table.items():
            with self.subTest(frontend=name):
                path = os.path.join(REPO, row["manifest-path"])
                self.assertTrue(os.path.isfile(path), row["manifest-path"])
                with open(path, encoding="utf-8") as stream:
                    manifest = json.load(stream)
                self.assertEqual(manifest.get("app-id") or manifest.get("id"), row["app-id"])
                # The builder image must carry the SDK of the manifest's
                # runtime, or the build fails after the promotion.
                family = IMAGE_FAMILY[manifest["runtime"]]
                self.assertEqual(row["flatpak-builder-image"],
                                 f"{family}-{manifest['runtime-version']}")

    def test_a_manifest_that_builds_from_the_submodule_gets_it_checked_out(self):
        # Every manifest builds fisherman from the submodule (GNOME from
        # ../fisherman, the others through shared/flatpak/fisherman.json),
        # so a row that does not check it out builds from an empty directory.
        import flatpak_manifest
        submodule = os.path.join(REPO, "fisherman")
        for name, row in self.table.items():
            with self.subTest(frontend=name):
                paths = flatpak_manifest.local_paths(os.path.join(REPO, row["manifest-path"]))
                uses = any(kind == "dir" and target == submodule for _m, kind, target in paths)
                self.assertTrue(uses, f"{name} does not build fisherman from the submodule")
                self.assertEqual(row["checkout-submodules"], uses)

    def test_only_gnome_moves_the_unqualified_latest_tags(self):
        # `latest` is GNOME's historical alias. A second frontend with it
        # would overwrite the image that existing live ISOs pull.
        self.assertEqual([n for n, row in self.table.items() if row["also-latest"]], ["gnome"])


class OutputsTest(unittest.TestCase):
    def test_a_row_becomes_one_output_per_column(self):
        self.assertEqual(
            ft.render_outputs(ft.row_for("gnome", ft.load())),
            "app-id=org.bootcinstaller.Installer\n"
            "manifest-path=flatpak/org.bootcinstaller.Installer.json\n"
            "flatpak-builder-image=gnome-50\n"
            "checkout-submodules=true\n"
            "also-latest=true\n")
        self.assertEqual(
            ft.render_outputs(ft.row_for("cosmic", ft.load())),
            "app-id=org.tunaos.InstallerCosmic\n"
            "manifest-path=frontends/cosmic/flatpak/org.tunaos.InstallerCosmic.json\n"
            "flatpak-builder-image=freedesktop-25.08\n"
            "checkout-submodules=true\n"
            "also-latest=false\n")

    def test_main_appends_to_github_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            with open(out, "w", encoding="utf-8") as stream:
                stream.write("earlier=1\n")
            self.assertEqual(ft.main(["--frontend", "kde", "--github-output", out]), 0)
            with open(out, encoding="utf-8") as stream:
                text = stream.read()
        self.assertTrue(text.startswith("earlier=1\napp-id=org.tunaos.InstallerKde\n"))
        self.assertIn("flatpak-builder-image=kde-6.11\n", text)

    def test_an_unknown_frontend_fails_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self.assertEqual(ft.main(["--frontend", "plasma", "--github-output", out]), 1)
            self.assertFalse(os.path.exists(out))
        self.assertEqual(ft.main(["--frontend", ""]), 1)

    def test_a_broken_row_fails(self):
        good = ft.load()["kde"]
        broken = [
            {k: v for k, v in good.items() if k != "also-latest"},   # a column is missing
            {**good, "extra": 1},                                    # a column nobody reads
            {**good, "also-latest": "false"},                        # a string is truthy in bash
            {**good, "checkout-submodules": 0},
            {**good, "app-id": ""},
            {**good, "manifest-path": "a\nalso-latest=true"},        # would inject an output
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "frontends.json")
            for row in broken:
                with open(path, "w", encoding="utf-8") as stream:
                    json.dump({"kde": row}, stream)
                with self.subTest(row=row):
                    self.assertRaises(ft.TableError, ft.load, path)
                    self.assertEqual(ft.main(["--frontend", "kde", "--table", path]), 1)


class WorkflowsTest(unittest.TestCase):
    def setUp(self):
        self.names = list(ft.load())

    def test_there_is_one_publish_workflow(self):
        found = sorted(f for f in os.listdir(WORKFLOWS) if f.startswith("publish-flatpak"))
        self.assertEqual(found, ["publish-flatpak.yml"])

    def test_the_manual_dispatch_offers_the_frontends_of_the_table(self):
        options = re.findall(r"^        options: \[(.*)\]$", workflow("publish-flatpak.yml"), re.MULTILINE)
        self.assertEqual([o.split(", ") for o in options], [self.names])

    def test_the_workflow_passes_each_column_to_publish_oci(self):
        text = workflow("publish-flatpak.yml")
        self.assertIn("shared/ci/frontend_table.py --frontend \"$FRONTEND\"", text)
        self.assertIn("      frontend: ${{ inputs.frontend }}\n", text)
        for column, kind in ft.COLUMNS.items():
            with self.subTest(column=column):
                self.assertIn(f"      {column}: ${{{{ steps.row.outputs.{column} }}}}\n", text)
                value = f"needs.resolve.outputs.{column}"
                # A job output is a string. `'false'` as a string is truthy,
                # so a boolean input needs the comparison.
                passed = f"${{{{ {value} == 'true' }}}}" if kind is bool else f"${{{{ {value} }}}}"
                self.assertIn(f"      {column}: {passed}\n", text)
        # The inputs of publish-oci.yml that have no default are all passed.
        oci = workflow("publish-oci.yml")
        required = re.findall(r"^      ([\w-]+):\n(?:        description: .*\n)?        required: true$",
                              oci, re.MULTILINE)
        self.assertEqual(sorted(required),
                         ["app-id", "flatpak-builder-image", "frontend", "manifest-path"])

    def test_release_publishes_each_frontend_of_the_table_in_full(self):
        text = workflow("release.yml")
        for name in self.names:
            with self.subTest(frontend=name):
                # No `publish:` or `archs:` here: the release takes the
                # defaults of publish-flatpak.yml, publish=true on both
                # architectures.
                self.assertIn(
                    f"  publish-{name}:\n"
                    f"    name: Publish ({name})\n"
                    f"    needs: [guard, release]\n"
                    f"    if: needs.guard.outputs.{name} == 'true'\n"
                    f"    permissions:\n"
                    f"      contents: write\n"
                    f"      packages: write\n"
                    f"    uses: $/.github/workflows/publish-flatpak.yml\n"
                    f"    with:\n"
                    f"      frontend: {name}\n"
                    f"    secrets:\n"
                    f"      FLATPAK_INDEX_DEPLOY_KEY: ${{{{ secrets.FLATPAK_INDEX_DEPLOY_KEY }}}}\n", text)
        self.assertEqual(text.count("uses: $/.github/workflows/publish-flatpak.yml"), len(self.names))
        defaults = workflow("publish-flatpak.yml").split("  workflow_dispatch:")[0]
        self.assertRegex(defaults, r"      publish:\n(?:.*\n){3}        default: true\n")
        self.assertIn("        default: '[\"x86_64\", \"aarch64\"]'\n", defaults)

    def test_the_pull_request_build_never_publishes(self):
        text = workflow("flatpak-frontends.yml")
        calls = re.findall(r"    uses: \$/\.github/workflows/publish-flatpak\.yml\n"
                           r"    with:\n      frontend: (\w+)\n      publish: (\w+)\n", text)
        self.assertEqual(calls, [(n, "false") for n in self.names if n != "gnome"])
        self.assertEqual(text.count("publish-flatpak.yml\n"), len(calls))


if __name__ == "__main__":
    unittest.main()
