"""Unit tests for GTK-free disk plan construction."""

from types import SimpleNamespace
import unittest

from bootc_installer.defaults.disk_plan import (
    build_auto_partition_recipe,
    build_disk_finals,
)


class TestDiskPlan(unittest.TestCase):
    def test_build_auto_partition_recipe_copies_disk_contract(self):
        disk = SimpleNamespace(disk="/dev/nvme0n1", pretty_size="500 GB", size=500,
                               model="Samsung SSD 980 PRO", is_removable=False)

        self.assertEqual(build_auto_partition_recipe(disk), {
            "auto": {
                "disk": "/dev/nvme0n1",
                "pretty_size": "500 GB",
                "size": 500,
                "model": "Samsung SSD 980 PRO",
                "removable": False,
                "vgs_to_remove": [],
                "pvs_to_remove": [],
            }
        })

    def test_build_auto_partition_recipe_flags_removable_disk(self):
        # #251: a USB stick or other external drive must carry "removable"
        # into the finals so the confirm page can warn about it.
        disk = SimpleNamespace(disk="/dev/sdb", pretty_size="14.8 GiB", size=15931539456,
                               model="Ultra Fit", is_removable=True)

        recipe = build_auto_partition_recipe(disk)
        self.assertTrue(recipe["auto"]["removable"])

    def test_build_auto_partition_recipe_defaults_removable_when_absent(self):
        # A disk object with no is_removable attribute (e.g. an older test
        # double) must not raise, and must be treated as not removable.
        disk = SimpleNamespace(disk="/dev/sda", pretty_size="500 GB", size=500, model="")

        recipe = build_auto_partition_recipe(disk)
        self.assertFalse(recipe["auto"]["removable"])

    def test_build_disk_finals_adds_auto_filesystem_contract(self):
        result = build_disk_finals(
            {"auto": {"disk": "/dev/sda"}},
            "btrfs",
            "  workstation  ",
        )

        self.assertEqual(result, {
            "disk": {
                "auto": {"disk": "/dev/sda"},
                "filesystem": "btrfs",
                "btrfsSubvolumes": True,
            },
            "hostname": "workstation",
        })

    def test_build_disk_finals_adds_optional_disk_roles(self):
        result = build_disk_finals(
            None,
            "xfs",
            "host",
            virtual_disk=("/tmp/disk.img", "/dev/loop0"),
            var_disk=("/dev/sdb", True),
        )

        self.assertEqual(result["virtual_disk_img"], "/tmp/disk.img")
        self.assertEqual(result["virtual_disk_loop"], "/dev/loop0")
        self.assertEqual(
            result["var_disk"], {"disk": "/dev/sdb", "keep_existing": True}
        )
