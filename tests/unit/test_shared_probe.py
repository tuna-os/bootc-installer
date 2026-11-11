"""`fisherman probe --json`: the shared fixtures and the reader.

shared/probe/ is canonical (README.md says what a frontend renders). These
tests keep it honest in three directions:

1. The fixtures cannot go stale against fisherman. `laptop.json` must be
   byte-identical to fisherman's own golden output, and every fixture must
   carry exactly the JSON fields the Go structs in
   fisherman/fisherman/internal/probe declare, with the Go types, so a
   renamed or added field in fisherman fails here at the next submodule bump.
2. Each `<name>.expected.json` is what every frontend must render from
   `<name>.json`: the same disks, in the same order, with the same size
   strings and models. The per-frontend tests read the same files.
3. The Python frontends import the one reader, bootc_shared.probe
   (tests/unit/test_shared_python_package.py).
"""

import glob
import importlib.util
import json
import os
import re
import sys
import unittest

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
SHARED = os.path.join(REPO, "shared", "probe")
FIXTURES = os.path.join(SHARED, "fixtures")
CANONICAL = os.path.join(REPO, "shared", "python", "bootc_shared", "probe.py")
PROBE_PKG = os.path.join(REPO, "fisherman", "fisherman", "internal", "probe")
GOLDEN = os.path.join(PROBE_PKG, "testdata", "golden", "probe.json")

FIXTURE_NAMES = sorted(
    f[:-len(".json")] for f in os.listdir(FIXTURES)
    if f.endswith(".json") and not f.endswith(".expected.json"))


def _load(path, name):
    """A new instance of a bootc_shared module, so that a test which sets
    module state (the product label, a patched function) does not leak
    into another. The name keeps it inside the package for `from . import`."""
    import bootc_shared  # noqa: F401  (pytest.ini puts shared/python on the path)
    spec = importlib.util.spec_from_file_location("bootc_shared." + name.lstrip("_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture(name):
    with open(os.path.join(FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _expected(name):
    with open(os.path.join(FIXTURES, name + ".expected.json"), encoding="utf-8") as fh:
        return json.load(fh)


_STRUCT = re.compile(r"^type (\w+) struct \{\n(.*?)^\}", re.M | re.S)
_FIELD = re.compile(r"^\s*\w+\s+([\w\[\]*.]+)\s+`json:\"([^\"]+)\"`", re.M)


def _go_structs():
    """{struct name: {json name: (go type, omitempty)}} for the probe package."""
    structs = {}
    for fname in sorted(os.listdir(PROBE_PKG)):
        if not fname.endswith(".go") or fname.endswith("_test.go"):
            continue
        with open(os.path.join(PROBE_PKG, fname), encoding="utf-8") as fh:
            src = fh.read()
        for m in _STRUCT.finditer(src):
            structs[m.group(1)] = _struct_fields(m.group(1), m.group(2), structs)
    return structs


# A field whose type is an anonymous struct: `Sources struct { ... } `json:"sources"``
# (BootcStore.sources). Its fields are registered as the struct "<Parent>.<json>".
_INLINE = re.compile(r"^\s*\w+\s+struct \{\n(.*?)^\s*\} `json:\"([^\"]+)\"`", re.M | re.S)


def _struct_fields(name, body, structs):
    fields = {}
    for m in _INLINE.finditer(body):
        json_name, *opts = m.group(2).split(",")
        inner = f"{name}.{json_name}"
        structs[inner] = _struct_fields(inner, m.group(1), structs)
        fields[json_name] = (inner, "omitempty" in opts)
    for f in _FIELD.finditer(_INLINE.sub("", body)):
        json_name, *opts = f.group(2).split(",")
        fields[json_name] = (f.group(1), "omitempty" in opts)
    return fields


def _go_constants(prefix):
    values = set()
    for fname in os.listdir(PROBE_PKG):
        if fname.endswith(".go") and not fname.endswith("_test.go"):
            with open(os.path.join(PROBE_PKG, fname), encoding="utf-8") as fh:
                values.update(re.findall(rf"^\s*{prefix}\w*\s*=\s*\"([^\"]+)\"", fh.read(), re.M))
    return values


@unittest.skipUnless(os.path.isdir(PROBE_PKG), "fisherman submodule not checked out")
class TestFixturesMatchFisherman(unittest.TestCase):
    def setUp(self):
        self.structs = _go_structs()

    def test_the_go_structs_were_found(self):
        for name in ("Result", "Disk", "TPM", "System", "Live", "Offline"):
            self.assertIn(name, self.structs, f"probe.go no longer declares {name}")
            self.assertTrue(self.structs[name], name)
        # The anonymous struct of BootcStore.sources, which a parser that
        # only reads top-level structs would miss.
        self.assertEqual(set(self.structs.get("BootcStore.sources", {})),
                         {"bootc_status", "store_index", "image_list"})

    def test_laptop_fixture_is_fishermans_golden_output(self):
        with open(GOLDEN, "rb") as a, open(os.path.join(FIXTURES, "laptop.json"), "rb") as b:
            self.assertEqual(a.read(), b.read(),
                             "shared/probe/fixtures/laptop.json drifted from fisherman's "
                             "golden; copy internal/probe/testdata/golden/probe.json over it")

    def _check(self, value, gotype, where):
        if gotype.startswith("[]"):
            self.assertIsInstance(value, list, f"{where}: arrays are never null")
            for i, item in enumerate(value):
                self._check(item, gotype[2:], f"{where}[{i}]")
        elif gotype.startswith("map[string]"):
            self.assertIsInstance(value, dict, f"{where}: maps are never null")
            for key, item in value.items():
                self.assertIsInstance(key, str, where)
                self._check(item, gotype[len("map[string]"):], f"{where}[{key!r}]")
        elif gotype in self.structs:
            self.assertIsInstance(value, dict, where)
            fields = self.structs[gotype]
            for key in value:
                self.assertIn(key, fields, f"{where}.{key} is not a field of {gotype}")
            for key, (subtype, omitempty) in fields.items():
                if key not in value:
                    self.assertTrue(omitempty, f"{where}.{key} is missing")
                    continue
                self._check(value[key], subtype, f"{where}.{key}")
        elif gotype in ("int", "int64"):
            self.assertIsInstance(value, int, where)
            self.assertNotIsInstance(value, bool, where)
        elif gotype == "string":
            self.assertIsInstance(value, str, where)
        elif gotype == "bool":
            self.assertIsInstance(value, bool, where)
        else:
            self.fail(f"{where}: unhandled Go type {gotype}")

    def test_every_fixture_has_exactly_the_go_fields(self):
        for name in FIXTURE_NAMES:
            with self.subTest(fixture=name):
                self._check(_fixture(name), "Result", name)

    def test_the_e2e_shims_answer_has_exactly_the_go_fields(self):
        """shared/e2e/setup.sh writes what the e2e shim prints for
        `fisherman probe --json`; it must be a probe answer every frontend
        can read, offering exactly the loop disk."""
        import contextlib
        import io

        with open(os.path.join(REPO, "shared", "e2e", "setup.sh"), encoding="utf-8") as fh:
            src = fh.read()
        snippet = src.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        out = io.StringIO()
        argv = sys.argv
        try:
            sys.argv = ["setup.sh", "/dev/loop9"]
            with contextlib.redirect_stdout(out):
                exec(compile(snippet, "setup.sh", "exec"), {})
        finally:
            sys.argv = argv
        answer = json.loads(out.getvalue())
        self._check(answer, "Result", "e2e")
        fp = _load(CANONICAL, "fisherman_probe_e2e")
        self.assertEqual([d["path"] for d in fp.render_disks(answer)], ["/dev/loop9"])
        self.assertEqual(fp.unmet_requirements(answer), [])

    def test_every_fixture_uses_known_reasons_and_requirements(self):
        reasons = _go_constants("Excluded")
        unmet = _go_constants("Unmet")
        self.assertIn("zram", reasons)
        self.assertEqual(unmet, {"ram", "cpu", "uefi"})
        for name in FIXTURE_NAMES:
            data = _fixture(name)
            self.assertEqual(data["protocol_version"], 1)
            for disk in data["disks"]:
                with self.subTest(fixture=name, disk=disk["path"]):
                    if disk["eligible"]:
                        self.assertNotIn("excluded_reason", disk)
                    else:
                        self.assertIn(disk["excluded_reason"], reasons)
            self.assertLessEqual(set(data["system"]["unmet"]), unmet)
            self.assertEqual(data["system"]["meets_requirements"],
                             not data["system"]["unmet"])


class TestReader(unittest.TestCase):
    def setUp(self):
        self.fp = _load(CANONICAL, "fisherman_probe_canonical")

    def test_every_fixture_has_an_expected_rendering(self):
        self.assertGreaterEqual(len(FIXTURE_NAMES), 3)
        for name in FIXTURE_NAMES:
            with self.subTest(fixture=name):
                result = self.fp.parse(json.dumps(_fixture(name)))
                self.assertEqual(
                    {
                        "disks": self.fp.render_disks(result),
                        "tpm_usable": self.fp.tpm_usable(result),
                        "unmet": self.fp.unmet_requirements(result),
                        "live_image": self.fp.live_image(result),
                        "offline_images": self.fp.offline_images(result),
                    },
                    _expected(name))

    def test_live_and_offline_facts(self):
        laptop = self.fp.parse(json.dumps(_fixture("laptop")))
        self.assertTrue(self.fp.is_live(laptop))
        self.assertEqual(self.fp.live_image(laptop), "ghcr.io/example/os:stable")
        self.assertIn("localhost/os:beta", self.fp.offline_images(laptop))
        container = self.fp.parse(json.dumps(_fixture("container")))
        self.assertFalse(self.fp.is_live(container))
        self.assertEqual(self.fp.live_image(container), "")
        # A live_image is only ever reported for live media.
        odd = {"live": {"is_live": False, "live_image": "x"}}
        self.assertEqual(self.fp.live_image(odd), "")
        self.assertEqual(self.fp.offline_images({}), [])

    def test_pure_live_fixture_is_a_live_install_of_the_running_image(self):
        """Tacklebox live media (cmdline:root=tbox:) with an embedded OCI
        store: the probe reports live, names the booted image, and offers
        only the non-boot disk, so the recipe may leave `image` empty."""
        result = self.fp.parse(json.dumps(_fixture("pure-live-oci")))
        self.assertTrue(self.fp.is_live(result))
        self.assertEqual(self.fp.live_image(result), "ghcr.io/example/os:stable")
        self.assertIn("ghcr.io/example/os:stable", self.fp.offline_images(result))
        self.assertEqual([d["path"] for d in self.fp.eligible_disks(result)],
                         ["/dev/nvme0n1"])
        self.assertEqual(self.fp.unmet_requirements(result), [])

    def test_the_expected_renderings_cover_what_drifted(self):
        laptop = _expected("laptop")
        paths = [d["path"] for d in laptop["disks"]]
        # zram, the live USB (boot_disk), the DVD and too-small disks are gone.
        self.assertEqual(paths, ["/dev/sda", "/dev/sdc", "/dev/sdd", "/dev/nvme0n1"])
        # Removable disks are offered, flagged, in fisherman's order.
        self.assertEqual([d["removable"] for d in laptop["disks"]], [False, True, True, False])
        # A disk with no model is titled by its path.
        self.assertEqual(_expected("vm")["disks"][0]["title"], "/dev/vda")
        self.assertEqual(_expected("vm")["unmet"], ["ram", "cpu", "uefi"])
        self.assertEqual(_expected("container")["disks"], [])

    def test_format_size_is_fishermans_rule(self):
        labels = {}
        for name in FIXTURE_NAMES:
            for disk in _fixture(name)["disks"]:
                labels[disk["size_bytes"]] = disk["size_label"]
        self.assertGreater(len(labels), 10)
        for nbytes, label in labels.items():
            with self.subTest(nbytes=nbytes):
                self.assertEqual(self.fp.format_size(nbytes), label)
        self.assertEqual(self.fp.format_size(512), "512 B")
        self.assertEqual(self.fp.format_size(1024), "1 KiB")
        self.assertEqual(self.fp.format_size(53687091200), "50 GiB")

    def test_unknown_excluded_reason_or_missing_eligible_is_not_offered(self):
        result = {"protocol_version": 1, "disks": [
            {"path": "/dev/a", "eligible": False, "excluded_reason": "something_new"},
            {"path": "/dev/b"},
            {"path": "/dev/c", "eligible": True, "model": "M", "size_label": "1 TiB"},
        ]}
        self.assertEqual([d["path"] for d in self.fp.eligible_disks(result)], ["/dev/c"])

    def test_parse_rejects_what_it_cannot_read(self):
        for text in ("", "not json", "[]", '{"protocol_version": 2}', "{}"):
            with self.subTest(text=text):
                with self.assertRaises(self.fp.ProbeError):
                    self.fp.parse(text)

    def test_run_reads_the_fake_probe_file_without_running_anything(self):
        path = os.path.join(FIXTURES, "vm.json")
        result = self.fp.run(["/nonexistent/fisherman", "probe", "--json"],
                             environ={self.fp.FAKE_ENV: path})
        self.assertEqual(self.fp.render_disks(result), _expected("vm")["disks"])

    def test_run_reports_a_missing_binary_and_a_failing_probe(self):
        with self.assertRaises(self.fp.ProbeError) as cm:
            self.fp.run(["/nonexistent/fisherman", "probe", "--json"], environ={})
        self.assertIn("not found", str(cm.exception))
        # An older fisherman has no probe subcommand: it exits non-zero.
        with self.assertRaises(self.fp.ProbeError) as cm:
            self.fp.run(["sh", "-c", "echo 'unknown command \"probe\"' >&2; exit 2"],
                        environ={})
        self.assertIn("exit 2", str(cm.exception))
        self.assertIn("unknown command", str(cm.exception))

    def test_run_parses_stdout(self):
        path = os.path.join(FIXTURES, "laptop.json")
        result = self.fp.run(["cat", path], environ={})
        self.assertTrue(self.fp.tpm_usable(result))


# Where each frontend's own code lives (test trees excluded).
FRONTEND_SOURCES = [
    ("bootc_installer", (".py",)),
    ("frontends/xfce/tuna_installer_xfce", (".py",)),
    ("frontends/kde/src", (".cpp", ".h")),
    ("frontends/kde/modules", (".qml",)),
    ("frontends/cosmic/src", (".rs",)),
    ("frontends/niri/installer", (".go",)),
    ("frontends/niri/ui", (".qml",)),
]
# GNOME's partition picker and Windows-data scan still ask lsblk about
# PARTITIONS (filesystem, UUID, parent disk), which the probe does not
# report. Nothing may list or filter disks with it again.
LSBLK_ALLOWED = {
    "bootc_installer/core/disks.py",
    "bootc_installer/defaults/disk.py",
}
_RUNS_LSBLK = re.compile(r"[\"']lsblk[\"']")


class TestNoFrontendScansDisks(unittest.TestCase):
    def test_only_the_partition_helpers_run_lsblk(self):
        offenders = []
        for rel, exts in FRONTEND_SOURCES:
            for root, _dirs, files in os.walk(os.path.join(REPO, rel)):
                if "/tests" in root or "/target" in root:
                    continue
                for name in files:
                    if not name.endswith(exts) or name.endswith("_test.go"):
                        continue
                    path = os.path.join(root, name)
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        text = fh.read().split("#[cfg(test)]", 1)[0]
                    relpath = os.path.relpath(path, REPO)
                    if _RUNS_LSBLK.search(text) and relpath not in LSBLK_ALLOWED:
                        offenders.append(relpath)
        self.assertEqual(offenders, [],
                         "these frontend files run lsblk; the disk list is "
                         "`fisherman probe --json` (shared/probe/README.md)")


class TestFishermanPin(unittest.TestCase):
    """Every graphical installer runs the same fisherman revision.

    The `fisherman` submodule pin is the revision, and every Flatpak builds
    fisherman from that submodule: the four frontend manifests (kde, cosmic,
    niri, xfce) through shared/flatpak/fisherman.json, GNOME through its own
    module with the source ../fisherman. A manifest that pinned a fisherman
    git commit again would let one frontend probe, validate and install with
    other rules after the next bump.
    """

    def _modules(self, manifest):
        sys.path.insert(0, os.path.join(REPO, "shared", "ci"))
        import flatpak_manifest
        return list(flatpak_manifest.walk(manifest))

    def _fisherman_sources(self, manifest):
        found = []
        for module, base in self._modules(manifest):
            if module.get("name") != "fisherman":
                continue
            for source in module.get("sources", []):
                if source.get("type") == "dir":
                    source = {**source, "path": os.path.normpath(os.path.join(base, source["path"]))}
                found.append(source)
        return found

    def test_every_manifest_builds_fisherman_from_the_submodule(self):
        submodule = os.path.join(REPO, "fisherman")
        manifests = sorted(glob.glob(os.path.join(
            REPO, "frontends", "*", "flatpak", "org.tunaos.Installer*.json")))
        self.assertEqual(len(manifests), 4,
                         f"expected four frontend manifests, found {manifests}")
        manifests += sorted(glob.glob(os.path.join(REPO, "flatpak", "org.bootcinstaller.*.json")))
        for manifest in manifests:
            with self.subTest(manifest=os.path.relpath(manifest, REPO)):
                sources = self._fisherman_sources(manifest)
                self.assertEqual(sources, [{"type": "dir", "path": submodule}],
                                 "build fisherman from the submodule, with no pin of its own")

    def test_the_frontends_share_one_fisherman_module(self):
        for manifest in sorted(glob.glob(os.path.join(
                REPO, "frontends", "*", "flatpak", "org.tunaos.Installer*.json"))):
            with self.subTest(manifest=os.path.relpath(manifest, REPO)):
                with open(manifest, encoding="utf-8") as fh:
                    modules = json.load(fh)["modules"]
                self.assertIn("../../../shared/flatpak/fisherman.json", modules)
                self.assertNotIn("fisherman", [m.get("name") for m in modules
                                               if isinstance(m, dict)])

    def test_the_submodule_has_what_the_module_installs(self):
        root = os.path.join(REPO, "fisherman")
        if not os.path.isfile(os.path.join(root, "fisherman", "go.mod")):
            self.skipTest("the fisherman submodule is not checked out")
        for rel in ("fisherman/cmd/fisherman", "data/images.json", "data/images",
                    "data/polkit/org.tunaos.Installer.policy"):
            with self.subTest(path=rel):
                self.assertTrue(os.path.exists(os.path.join(root, rel)), rel)


if __name__ == "__main__":
    unittest.main()
