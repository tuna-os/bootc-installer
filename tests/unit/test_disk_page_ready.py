"""The disk page moves on only with every choice it shows made (#407, #408)."""

import pathlib
import unittest

from bootc_installer.defaults.disk_plan import disk_page_ready

BLP = pathlib.Path(__file__).resolve().parents[2] / "bootc_installer" / "gtk" / "default-disk.blp"


class TestDiskPageReady(unittest.TestCase):
    def test_needs_a_system_disk_and_a_valid_hostname(self):
        self.assertFalse(disk_page_ready(False, True, False, False))
        self.assertFalse(disk_page_ready(True, False, False, False))
        self.assertTrue(disk_page_ready(True, True, False, False))

    def test_data_disk_switch_on_needs_a_data_disk(self):
        # projectbluefin/dakota#1886: the switch on and no data disk chosen
        # used to advance and install with no /var disk.
        self.assertFalse(disk_page_ready(True, True, True, False))
        self.assertTrue(disk_page_ready(True, True, True, True))

    def test_turning_the_switch_off_releases_the_page(self):
        self.assertTrue(disk_page_ready(True, True, False, False))


class TestDiskPageOrder(unittest.TestCase):
    def test_use_entire_disk_comes_after_every_setting(self):
        # projectbluefin/dakota#1885: the button moves on at once, so a
        # setting below it could be missed.
        text = BLP.read_text()
        button = text.index("Button btn_auto")
        for widget in ("filesystem_row", "hostname_entry", "var_disk_switch",
                       "group_var_disks", "group_var_disk_existing"):
            self.assertLess(text.index(widget), button, widget)


if __name__ == "__main__":
    unittest.main()
