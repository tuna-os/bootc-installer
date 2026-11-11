"""GNOME's language, keyboard and time zone reach the recipe (#292).

The three steps hand the Processor a locale, an XKB layout and variant, and
an IANA zone. The Processor writes `locale`, `keyboard` and `timezone` only
for a step that has a selected value; without one the image keeps its own.
Every value the lists can offer must pass fisherman's rule, which the
shared recipe schema carries as a pattern.

The lists do not need GnomeDesktop or GWeather: without them the zones
come from tzdata and the layouts from xkeyboard-config.
"""

import importlib
import json
import os
import re
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "shared", "python"))

from bootc_installer.defaults.disk_plan import (  # noqa: E402
    build_auto_partition_recipe, build_disk_finals)
from bootc_installer.utils import field_check  # noqa: E402
from bootc_installer.utils.processor import Processor, region_fields  # noqa: E402

SCHEMA = json.load(open(os.path.join(REPO, "shared", "recipe", "fisherman-recipe.schema.json"),
                        encoding="utf-8"))["properties"]


def _ok(prop, value):
    return re.fullmatch(prop["pattern"].strip("^$"), value) is not None and len(value) <= 64


class _Disk:
    disk = "/dev/vda"
    pretty_size = "64 GB"
    size = 64 * 1024 ** 3


def _recipe(*finals):
    disk = build_disk_finals(build_auto_partition_recipe(_Disk()), "xfs", "host")
    with patch("bootc_installer.core.system.Systeminfo.has_nvidia_gpu", return_value=False):
        return Processor.gen_install_recipe("", [disk, *finals], {"imgref": "r.example/os:1"})


class TestTheRecipe(unittest.TestCase):
    def test_the_three_keys_follow_the_steps(self):
        recipe = _recipe({"language": "de_DE.UTF-8"},
                         {"keyboard": {"layout": "de", "variant": "nodeadkeys"}},
                         {"timezone": "Europe/Berlin"})
        self.assertEqual(recipe["locale"], "de_DE.UTF-8")
        self.assertEqual(recipe["keyboard"], {"layout": "de", "variant": "nodeadkeys"})
        self.assertEqual(recipe["timezone"], "Europe/Berlin")

    def test_no_selection_writes_no_key(self):
        """A step with nothing selected sends no key, and the image keeps
        its own value."""
        recipe = _recipe({}, {}, {})
        for key in ("locale", "keyboard", "timezone"):
            self.assertNotIn(key, recipe)

    def test_one_key_alone(self):
        recipe = _recipe({"timezone": "America/New_York"})
        self.assertEqual(recipe["timezone"], "America/New_York")
        self.assertNotIn("locale", recipe)
        self.assertNotIn("keyboard", recipe)

    def test_an_empty_variant_and_wrong_types_are_left_out(self):
        self.assertEqual(region_fields({"keyboard": {"layout": "us", "variant": ""}}),
                         {"keyboard": {"layout": "us"}})
        self.assertEqual(region_fields({
            "language": None, "timezone": {"region": "Europe", "zone": "Berlin"},
            "keyboard": [{"layout": "us"}]}), {})
        self.assertEqual(region_fields({"keyboard": {"variant": "intl"}}), {})


class TestEveryOfferPassesFishermansRule(unittest.TestCase):
    def test_locales(self):
        mods = {"gi": types.SimpleNamespace(require_version=MagicMock(side_effect=ValueError))}
        with patch.dict(sys.modules, mods):
            sys.modules.pop("bootc_installer.core.languages", None)
            languages = importlib.import_module("bootc_installer.core.languages")
        sys.modules.pop("bootc_installer.core.languages", None)
        self.assertIsNone(languages.GnomeDesktop)
        self.assertGreater(len(languages.all_locale), 100)
        for code in languages.all_locale:
            self.assertTrue(_ok(SCHEMA["locale"], code), code)
            # Without GnomeDesktop the row shows the locale itself.
            self.assertEqual(languages.all_languages[code], code)

    @unittest.skipUnless(os.path.exists("/usr/share/zoneinfo/zone1970.tab"), "no tzdata")
    def test_zones_from_tzdata(self):
        timezones = _import_timezones_without_gweather()
        zones = timezones.tzdata_zones()
        self.assertGreater(len(zones), 200)
        for zone, country, lat, lon in zones:
            self.assertTrue(_ok(SCHEMA["timezone"], zone), zone)
            self.assertTrue(country)
            self.assertTrue(-90 <= lat <= 90 and -180 <= lon <= 180, zone)
        regions = timezones.all_timezones
        self.assertEqual(regions["Europe"]["Germany"]["Berlin"], "Europe/Berlin")
        guess = timezones.nearest_zone(zones, 52.5, 13.4)
        self.assertEqual(guess.get_timezone_str(), "Europe/Berlin")
        self.assertEqual(guess.get_country_name(), "Germany")
        self.assertEqual(timezones.nearest_zone([], 0, 0), None)

    def test_zone1970_coordinates(self):
        timezones = _import_timezones_without_gweather()
        lat, lon = timezones.parse_coordinates("+5230+01322")
        self.assertAlmostEqual(lat, 52.5)
        self.assertAlmostEqual(lon, 13.3667, places=3)
        lat, lon = timezones.parse_coordinates("-0745+11030")
        self.assertAlmostEqual(lat, -7.75)
        lat, lon = timezones.parse_coordinates("+404251-0740023")
        self.assertAlmostEqual(lat, 40.7142, places=3)
        self.assertAlmostEqual(lon, -74.0064, places=3)

    def test_layouts_from_xkeyboard_config(self):
        keymaps = _import_keymaps_without_gnome_desktop()
        path = os.path.join(os.path.dirname(__file__), "fixtures", "evdev-mini.xml")
        layouts = keymaps.evdev_layouts(path)
        self.assertEqual(layouts["us"], ("English (US)", "en", "us", ""))
        self.assertEqual(layouts["de+nodeadkeys"],
                         ("German (no dead keys)", "de", "de", "nodeadkeys"))
        self.assertEqual(keymaps.evdev_layouts("/nonexistent.xml"), {})
        real = keymaps.evdev_layouts()
        for _name, (_display, _short, layout, variant) in (real or layouts).items():
            self.assertTrue(_ok(SCHEMA["keyboard"]["properties"]["layout"], layout), layout)
            self.assertTrue(_ok(SCHEMA["keyboard"]["properties"]["variant"], variant), variant)
        with patch.object(keymaps, "evdev_layouts", return_value=layouts):
            listed = keymaps.KeyMaps().list_all
        self.assertEqual(listed["German"]["de+nodeadkeys"]["xkb_variant"], "nodeadkeys")


def _import_timezones_without_gweather():
    gi = types.SimpleNamespace(require_version=MagicMock(side_effect=ValueError),
                               repository=types.SimpleNamespace(GLib=MagicMock()))
    with patch.dict(sys.modules, {"gi": gi, "gi.repository": gi.repository}):
        sys.modules.pop("bootc_installer.core.timezones", None)
        mod = importlib.import_module("bootc_installer.core.timezones")
    sys.modules.pop("bootc_installer.core.timezones", None)
    assert mod.GWeather is None
    return mod


def _import_keymaps_without_gnome_desktop():
    repo = types.ModuleType("gi.repository")
    with patch.dict(sys.modules, {"gi.repository": repo,
                                  "gi.repository.GnomeDesktop": None}):
        sys.modules.pop("bootc_installer.core.keymaps", None)
        mod = importlib.import_module("bootc_installer.core.keymaps")
    sys.modules.pop("bootc_installer.core.keymaps", None)
    assert mod.XkbInfo is None
    return mod


class TestChoiceCheck(unittest.TestCase):
    def _check(self, field):
        live = MagicMock()
        message = MagicMock()
        changed = MagicMock()
        check = field_check.ChoiceCheck(
            MagicMock(), field, message, on_change=changed,
            live_check_factory=lambda on_result: live)
        return check, live, message, changed

    def test_a_problem_for_the_field_or_below_it_holds_the_page(self):
        check, live, message, changed = self._check("keyboard")
        check.submit({"keyboard": {"layout": "de rd.break"}})
        live.submit.assert_called_once_with({"keyboard": {"layout": "de rd.break"}})
        problem = {"field": "keyboard.layout", "code": "keyboard_layout_invalid",
                   "message": "bad layout"}
        with patch.object(field_check.copy_text, "text", return_value=""):
            check._on_result([{"field": "hostname", "code": "x"}, problem], None)
        self.assertFalse(check.ok)
        message.set_label.assert_called_with("bad layout")
        message.set_visible.assert_called_with(True)
        changed.assert_called()

    def test_another_field_or_no_answer_does_not_hold_it(self):
        check, _live, message, _changed = self._check("locale")
        check._on_result([{"field": "localex", "code": "x"}], None)
        self.assertTrue(check.ok)
        check._on_result(None, "fisherman is not there")
        self.assertTrue(check.ok)
        message.set_visible.assert_called_with(False)


class TestTheBundledRecipeHasTheSteps(unittest.TestCase):
    def test_the_three_steps_come_before_the_image(self):
        recipe = json.load(open(os.path.join(REPO, "recipe.json"), encoding="utf-8"))
        steps = list(recipe["steps"])
        for key in ("language", "keyboard", "timezone"):
            self.assertEqual(recipe["steps"][key]["template"], key)
            self.assertLess(steps.index(key), steps.index("image"))


if __name__ == "__main__":
    unittest.main()
