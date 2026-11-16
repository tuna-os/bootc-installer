"""The layout the passphrase is typed in reaches the recipe (#411).

projectbluefin/dakota#1299: the Dakota ISO has no keyboard step, so the
passphrase was typed in the live layout and asked for at boot in the
image's default one.
"""

import unittest

from bootc_installer.utils import live_keyboard
from bootc_installer.utils.host import Scope
from bootc_installer.utils.processor import region_fields
from tests.unit.fake_host import FAIL, FakeExecutor


class TestParseActiveLayout(unittest.TestCase):
    def test_the_first_source_without_a_history(self):
        self.assertEqual(live_keyboard.parse_active_layout("[('xkb', 'de')]", "@a(ss) []"),
                         {"layout": "de"})

    def test_the_most_recent_source_is_the_one_in_use(self):
        self.assertEqual(live_keyboard.parse_active_layout(
            "[('xkb', 'us'), ('xkb', 'fr+azerty')]", "[('xkb', 'fr+azerty'), ('xkb', 'us')]"),
            {"layout": "fr", "variant": "azerty"})

    def test_a_history_entry_that_is_no_longer_a_source_is_skipped(self):
        self.assertEqual(live_keyboard.parse_active_layout(
            "[('xkb', 'us')]", "[('xkb', 'de'), ('xkb', 'us')]"), {"layout": "us"})

    def test_no_layout_from_nothing_or_an_input_method(self):
        for sources in ("@a(ss) []", "", "garbage", "[('ibus', 'anthy')]"):
            with self.subTest(sources=sources):
                self.assertIsNone(live_keyboard.parse_active_layout(sources))


class TestActiveLayout(unittest.TestCase):
    def test_reads_both_keys_on_the_host(self):
        ex = FakeExecutor([{"returncode": 0, "stdout": "[('xkb', 'de+neo')]\n"},
                           {"returncode": 0, "stdout": "@a(ss) []\n"}])
        self.assertEqual(live_keyboard.active_layout(ex), {"layout": "de", "variant": "neo"})
        self.assertEqual([c[4] for c in ex.calls], [
            ["flatpak-spawn", "--host", "gsettings", "get", live_keyboard.SCHEMA, "sources"],
            ["flatpak-spawn", "--host", "gsettings", "get", live_keyboard.SCHEMA, "mru-sources"],
        ])
        self.assertTrue(all(c[2] is Scope.HOST and c[3] == 3 for c in ex.calls))

    def test_no_answer_is_no_layout(self):
        self.assertIsNone(live_keyboard.active_layout(FakeExecutor([FAIL])))


class TestRegionFields(unittest.TestCase):
    def test_the_typed_layout_fills_in_for_a_missing_keyboard_step(self):
        self.assertEqual(region_fields({"passphrase_keyboard": {"layout": "de"}}),
                         {"keyboard": {"layout": "de"}})

    def test_a_keyboard_step_wins(self):
        self.assertEqual(region_fields({"keyboard": {"layout": "fr"},
                                        "passphrase_keyboard": {"layout": "de"}}),
                         {"keyboard": {"layout": "fr"}})

    def test_a_bad_value_is_left_out(self):
        for value in ("de", {"layout": ""}, {"layout": 3}):
            with self.subTest(value=value):
                self.assertEqual(region_fields({"passphrase_keyboard": value}), {})


if __name__ == "__main__":
    unittest.main()
