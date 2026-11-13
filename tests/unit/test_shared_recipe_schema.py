"""The recipe schema is the contract every frontend writes against.

shared/recipe/fisherman-recipe.schema.json is the one copy. No frontend
keeps or installs a second one.
"""

import json
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SHARED = REPO / "shared" / "recipe" / "fisherman-recipe.schema.json"


def _recipe_package_source():
    """The Go source of fisherman's recipe package: its structs and
    constants are spread over recipe.go and its siblings (SourceReuse and
    bootc_store_reuse are in reuse.go)."""
    pkg = REPO / "fisherman" / "fisherman" / "internal" / "recipe"
    return "\n".join(p.read_text() for p in sorted(pkg.glob("*.go"))
                     if not p.name.endswith("_test.go"))


class SharedRecipeSchemaTests(unittest.TestCase):
    def test_shared_schema_is_valid_json_schema(self):
        doc = json.loads(SHARED.read_text())
        self.assertIn("$schema", doc)
        self.assertIn("properties", doc)
        for field in ("disk", "encryption", "image"):
            self.assertIn(field, doc["properties"], f"schema lost the '{field}' field")

    def test_schema_covers_every_fisherman_recipe_field(self):
        """Every top-level `json:"..."` tag on fisherman's Recipe struct is a
        schema property. The schema used to list 13 of the backend's 26
        fields, so a frontend validating against it could not express what
        GNOME already writes (user, varDisk, customMounts...)."""
        recipe_go = REPO / "fisherman" / "fisherman" / "internal" / "recipe" / "recipe.go"
        if not recipe_go.exists():
            self.skipTest("fisherman submodule not checked out")
        src = recipe_go.read_text()
        start = src.index("type Recipe struct {")
        end = src.index("\n}", start)
        tags = re.findall(r'`json:"([A-Za-z0-9]+)', src[start:end])
        self.assertTrue(tags, "could not read fisherman's Recipe struct")
        props = json.loads(SHARED.read_text())["properties"]
        missing = sorted(set(tags) - set(props))
        self.assertEqual(missing, [], f"fisherman recipe fields absent from the shared schema: {missing}")

    def _switch_cases(self, src, expr):
        """The string literals of the first `case` clause of `switch <expr> {`
        in fisherman's rules: the values its rule accepts."""
        start = src.index(f"switch {expr} {{")
        clause = src[start:src.index(":", src.index("case", start))]
        return set(re.findall(r'"([^"]*)"', clause))

    def test_enums_match_what_fisherman_accepts(self):
        """A schema enum narrower than fisherman's rules rejects recipes
        fisherman installs: GNOME writes bootloader "" when the image
        metadata names none, and fisherman then picks the image's default.
        The rules live in internal/recipe/rules.go since fisherman#277, the
        one rule set the install and `validate --json` share."""
        rules_go = REPO / "fisherman" / "fisherman" / "internal" / "recipe" / "rules.go"
        choices = REPO / "fisherman" / "data" / "encryption-choices.json"
        if not rules_go.exists() or not choices.exists():
            self.skipTest("fisherman submodule not checked out")
        src = rules_go.read_text()
        props = json.loads(SHARED.read_text())["properties"]
        filesystems = src[src.index("var Filesystems = []string{"):]
        filesystems = filesystems[:filesystems.index("}")]
        # "" is accepted as "none" (LookupEncryption).
        enc_types = {c["type"] for c in json.loads(choices.read_text())["choices"]} | {""}
        cases = {
            "bootloader": (self._switch_cases(src, "b"), props["bootloader"]["enum"]),
            "encryption.type": (enc_types, props["encryption"]["properties"]["type"]["enum"]),
            "filesystem": (set(re.findall(r'"([^"]*)"', filesystems)),
                           props["filesystem"]["enum"]),
        }
        for field, (accepted, enum) in cases.items():
            with self.subTest(field=field):
                self.assertTrue(accepted, f"could not read fisherman's {field} rule")
                self.assertEqual(sorted(enum), sorted(accepted),
                                 f"schema enum for {field} differs from fisherman's rules")

    def test_hostname_and_username_patterns_follow_fishermans_rules(self):
        """The schema's patterns accept what fisherman's CheckHostname and
        CheckUsername accept, on the cases fisherman/docs/VALIDATE.md names.
        (Reserved usernames are a list, not a pattern: the schema cannot
        express them, `fisherman validate --json` reports them.)"""
        props = json.loads(SHARED.read_text())["properties"]
        host = props["hostname"]
        user = props["user"]["properties"]["username"]["pattern"]
        accepted = ["my-pc", "MyPC", "pc.example.com", "a", "a" * 63, "a." * 31 + "ab"]
        rejected = ["", "my_pc", "-router", "router-", "a..b", ".a", "a.", "a" * 64,
                    "a" * 63 + "." + "b"]
        for h in accepted:
            with self.subTest(hostname=h):
                self.assertRegex(h, host["pattern"])
                self.assertLessEqual(len(h), host["maxLength"])
        for h in rejected:
            with self.subTest(hostname=h):
                ok = re.fullmatch(host["pattern"], h) and len(h) <= host["maxLength"]
                self.assertFalse(ok, f"{h!r} should be rejected")
        for u in ["", "alice", "_svc", "a-b_c9", "a" * 32]:
            self.assertRegex(u, user)
        for u in ["Alice", "1abc", "a b", "a" * 33, "al.ice"]:
            self.assertIsNone(re.fullmatch(user, u), u)

    def test_distro_id_and_brew_tap_patterns_are_fishermans(self):
        """distroID and brewTap take fisherman's own patterns
        (distroIDPattern and brewTapPattern in rules.go, fisherman#299), with
        the empty string allowed as fisherman allows it. distroID names paths
        and units on the target and brewTap goes into a shell script, so a
        looser schema would pass recipes `fisherman validate` rejects."""
        rules_go = REPO / "fisherman" / "fisherman" / "internal" / "recipe" / "rules.go"
        if not rules_go.exists():
            self.skipTest("fisherman submodule not checked out")
        src = rules_go.read_text()
        props = json.loads(SHARED.read_text())["properties"]
        for field, var in (("distroID", "distroIDPattern"), ("brewTap", "brewTapPattern")):
            with self.subTest(field=field):
                m = re.search(var + r"\s*=\s*regexp\.MustCompile\(`\^(.*)\$`\)", src)
                self.assertIsNotNone(m, f"could not read fisherman's {var}")
                self.assertEqual(props[field]["pattern"], f"^({m.group(1)})?$")
        distro = props["distroID"]["pattern"]
        for ok in ["", "bootc", "fedora", "bluefin-lts", "a" * 63]:
            self.assertRegex(ok, distro)
        for bad in ["Fedora", "1os", "a/b", "..", "a_b", "a" * 64, "-os"]:
            self.assertIsNone(re.fullmatch(distro, bad), bad)
        tap = props["brewTap"]["pattern"]
        for ok in ["", "owner/tap", "Org_1/homebrew-tap.v2"]:
            self.assertRegex(ok, tap)
        for bad in ["owner", "a/b/c", "-x/y", "x/y;rm", "x y/z", "/y"]:
            self.assertIsNone(re.fullmatch(tap, bad), bad)

    def _struct_tags(self, src, name):
        start = src.index(f"type {name} struct {{")
        return re.findall(r'`json:"([A-Za-z0-9]+)', src[start:src.index("\n}", start)])

    def test_nested_objects_have_exactly_fishermans_fields(self):
        """fisherman refuses an unknown key at any depth, so a nested object
        of the schema names the fields of the Go struct and no other."""
        recipe_go = REPO / "fisherman" / "fisherman" / "internal" / "recipe" / "recipe.go"
        if not recipe_go.exists():
            self.skipTest("fisherman submodule not checked out")
        src = _recipe_package_source()
        props = json.loads(SHARED.read_text())["properties"]
        cases = {
            "Recipe": props,
            "KeyboardSpec": props["keyboard"]["properties"],
            "Extras": props["extras"]["properties"],
            "UserSpec": props["user"]["properties"],
            "VarDiskSpec": props["varDisk"]["properties"],
            "CustomMount": props["customMounts"]["items"]["properties"],
            "Encryption": props["encryption"]["properties"],
            "SourceReuse": props["sourceReuse"]["properties"],
        }
        for struct, schema_props in cases.items():
            with self.subTest(struct=struct):
                self.assertEqual(sorted(schema_props), sorted(self._struct_tags(src, struct)))

    def test_every_object_is_closed(self):
        """fisherman's recipe_unknown_field rule, in the schema: a recipe
        with a key that the schema does not have fails check-recipe.py too."""
        def walk(node, where):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False,
                                  f"{where} accepts unknown keys; fisherman refuses them")
                for key, value in node.items():
                    walk(value, f"{where}/{key}")
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, f"{where}/{i}")
        walk(json.loads(SHARED.read_text()), "")

    def test_locale_keyboard_and_timezone_patterns_are_fishermans(self):
        rules_go = REPO / "fisherman" / "fisherman" / "internal" / "recipe" / "rules.go"
        if not rules_go.exists():
            self.skipTest("fisherman submodule not checked out")
        src = rules_go.read_text()
        props = json.loads(SHARED.read_text())["properties"]
        keyboard = props["keyboard"]["properties"]

        def go(var):
            m = re.search(var + r"\s*=\s*regexp\.MustCompile\(`\^(.*)\$`\)", src)
            self.assertIsNotNone(m, f"could not read fisherman's {var}")
            return m.group(1)
        # Empty is valid for these three in fisherman; layout and variant
        # take fisherman's pattern as it is.
        self.assertEqual(props["locale"]["pattern"], f"^({go('localePattern')})?$")
        self.assertEqual(props["timezone"]["pattern"], f"^({go('timezonePattern')})?$")
        self.assertEqual(keyboard["model"]["pattern"], f"^({go('xkbModelPattern')})?$")
        self.assertEqual(keyboard["layout"]["pattern"], f"^{go('xkbLayoutPattern')}$")
        self.assertEqual(keyboard["variant"]["pattern"], f"^{go('xkbVariantPattern')}$")
        for field in (props["locale"], props["timezone"], *keyboard.values()):
            self.assertEqual(field["maxLength"], 64)
        self.assertEqual(props["keyboard"]["required"], ["layout"])
        for ok in ["", "de_DE.UTF-8", "sr_RS@latin", "C", "POSIX.UTF-8"]:
            self.assertRegex(ok, props["locale"]["pattern"])
        for bad in ["de DE", "de_DE\nLC_ALL=C", "../x", "DE"]:
            self.assertIsNone(re.fullmatch(props["locale"]["pattern"], bad), bad)
        for ok in ["", "Europe/Berlin", "Etc/GMT+1", "UTC"]:
            self.assertRegex(ok, props["timezone"]["pattern"])
        for bad in ["/etc/passwd", "../UTC", "Europe/", "1/x", "a b"]:
            self.assertIsNone(re.fullmatch(props["timezone"]["pattern"], bad), bad)

    def test_list_enums_are_fishermans(self):
        recipe_go = REPO / "fisherman" / "fisherman" / "internal" / "recipe" / "recipe.go"
        if not recipe_go.exists():
            self.skipTest("fisherman submodule not checked out")
        src = _recipe_package_source()
        props = json.loads(SHARED.read_text())["properties"]
        consts = dict(re.findall(r'^\s*(?:const\s+)?(\w+)\s*=\s*"([^"]+)"', src, re.M))
        for field, var in (("override", "Overrides"), ("experimental", "Experimentals")):
            with self.subTest(field=field):
                names = re.search(rf"var {var} = \[\]string\{{([^}}]*)\}}", src).group(1)
                values = [consts[n.strip()] for n in names.split(",") if n.strip()]
                self.assertEqual(sorted(props[field]["items"]["enum"]), sorted(values))

    def test_zfs_needs_the_experimental_opt_in(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("python3-jsonschema is not installed")
        validator = jsonschema.Draft7Validator(json.loads(SHARED.read_text()))
        base = {"disk": "/dev/sda", "hostname": "a", "filesystem": "zfs"}
        self.assertTrue(list(validator.iter_errors(base)))
        self.assertFalse(list(validator.iter_errors({**base, "experimental": ["zfs"]})))
        self.assertFalse(list(validator.iter_errors({**base, "filesystem": "xfs"})))

    def test_source_reuse_needs_the_opt_in_an_empty_image_and_a_target(self):
        """fisherman's static sourceReuse rules (docs/SOURCE-REUSE.md):
        source_reuse_experimental, source_reuse_image_conflict and
        source_reuse_target_imgref_required, in the schema."""
        try:
            import jsonschema
        except ImportError:
            self.skipTest("python3-jsonschema is not installed")
        validator = jsonschema.Draft7Validator(json.loads(SHARED.read_text()))
        reuse = {"store": "bootc", "digest": "sha256:" + "1" * 64, "platform": "x86_64"}
        good = {"disk": "/dev/sda", "hostname": "a", "image": "",
                "targetImgref": "ghcr.io/example/os:stable",
                "experimental": ["bootc_store_reuse"], "sourceReuse": reuse}
        self.assertFalse(list(validator.iter_errors(good)))
        for bad in ({**good, "experimental": []},
                    {k: v for k, v in good.items() if k != "experimental"},
                    {**good, "image": "ghcr.io/example/os:stable"},
                    {k: v for k, v in good.items() if k != "targetImgref"},
                    {**good, "sourceReuse": {**reuse, "store": "podman"}},
                    {**good, "sourceReuse": {**reuse, "digest": "stable"}},
                    {**good, "sourceReuse": {**reuse, "extra": 1}}):
            with self.subTest(recipe=bad):
                self.assertTrue(list(validator.iter_errors(bad)))

    def test_no_frontend_keeps_a_second_copy(self):
        copies = [p.relative_to(REPO).as_posix()
                  for root in ("frontends", "bootc_installer", "data")
                  for p in (REPO / root).rglob("fisherman-recipe.schema.json")
                  if "node_modules" not in p.parts and "target" not in p.parts]
        self.assertEqual(copies, [], "the recipe schema has one home: shared/recipe/")


if __name__ == "__main__":
    unittest.main()
