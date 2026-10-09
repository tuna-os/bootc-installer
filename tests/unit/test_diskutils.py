"""Unit tests for the pure-Python parts of core/disks.py.

Covers Diskutils.pretty_size() (static, no I/O), the probe-backed Disk, and
the Partition comparison operators (__lt__, __eq__) via lightweight stubs.
"""

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bootc_installer.core.disks import Disk as _Disk
from bootc_installer.core.disks import Diskutils
from bootc_installer.core.disks import Partition as _Partition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakePartition:
    """Minimal stand-in that satisfies __lt__ / __eq__ duck-typing."""

    def __init__(self, partition: str, uuid: str = "", fs_type: str = ""):
        self.partition = partition
        self.uuid = uuid
        self.fs_type = fs_type

    def __lt__(self, other):
        return self.partition < other.partition

    def __eq__(self, other):
        if not other:
            return False
        return self.uuid == other.uuid and self.fs_type == other.fs_type


# ---------------------------------------------------------------------------
# Diskutils.pretty_size
# ---------------------------------------------------------------------------

class TestPrettySize(unittest.TestCase):
    """fisherman's size rule (shared/probe/README.md), for partition sizes the
    probe does not report. It used to be binary maths labelled "GB"."""

    def test_bytes(self):
        self.assertEqual(Diskutils.pretty_size(512), "512 B")
        self.assertEqual(Diskutils.pretty_size(0), "0 B")

    def test_binary_units_labelled_honestly(self):
        self.assertEqual(Diskutils.pretty_size(1024), "1 KiB")
        self.assertEqual(Diskutils.pretty_size(10 * 1024 ** 2), "10 MiB")
        self.assertEqual(Diskutils.pretty_size(500 * 1024 ** 3), "500 GiB")
        self.assertEqual(Diskutils.pretty_size(int(1.5 * 1024 ** 3)), "1.5 GiB")

    def test_matches_fishermans_labels(self):
        # Sizes from shared/probe/fixtures/laptop.json, labelled by fisherman.
        self.assertEqual(Diskutils.pretty_size(500107862016), "465.8 GiB")
        self.assertEqual(Diskutils.pretty_size(2000398934016), "1.8 TiB")


# ---------------------------------------------------------------------------
# Partition ordering and equality (via _FakePartition)
# ---------------------------------------------------------------------------

class TestPartitionComparisons(unittest.TestCase):
    def test_lt_by_device_path(self):
        sda1 = _FakePartition("/dev/sda1")
        sda2 = _FakePartition("/dev/sda2")
        self.assertLess(sda1, sda2)
        self.assertFalse(sda2 < sda1)

    def test_lt_equal_paths_not_less(self):
        a = _FakePartition("/dev/sda1")
        b = _FakePartition("/dev/sda1")
        self.assertFalse(a < b)

    def test_eq_same_uuid_and_fstype(self):
        a = _FakePartition("/dev/sda1", uuid="abc-123", fs_type="ext4")
        b = _FakePartition("/dev/sdb1", uuid="abc-123", fs_type="ext4")
        self.assertEqual(a, b)

    def test_neq_different_uuid(self):
        a = _FakePartition("/dev/sda1", uuid="abc", fs_type="ext4")
        b = _FakePartition("/dev/sda1", uuid="xyz", fs_type="ext4")
        self.assertNotEqual(a, b)

    def test_neq_different_fstype(self):
        a = _FakePartition("/dev/sda1", uuid="abc", fs_type="ext4")
        b = _FakePartition("/dev/sda1", uuid="abc", fs_type="xfs")
        self.assertNotEqual(a, b)

    def test_eq_none_is_false(self):
        a = _FakePartition("/dev/sda1", uuid="abc", fs_type="ext4")
        self.assertFalse(a == None)  # noqa: E711 — intentional None comparison

    def test_sort_order(self):
        parts = [
            _FakePartition("/dev/sda3"),
            _FakePartition("/dev/sda1"),
            _FakePartition("/dev/sda2"),
        ]
        sorted_parts = sorted(parts)
        self.assertEqual(
            [p.partition for p in sorted_parts],
            ["/dev/sda1", "/dev/sda2", "/dev/sda3"],
        )


# ---------------------------------------------------------------------------
# Diskutils — subprocess-dependent methods
# ---------------------------------------------------------------------------

class TestSeparateDeviceAndPartn(unittest.TestCase):
    """Tests for Diskutils.separate_device_and_partn()."""

    def _mock_output(self, name, pkname, partn):
        payload = json.dumps({
            "blockdevices": [{"name": name, "pkname": pkname, "partn": partn}]
        })
        return payload.encode()

    def test_partition_returns_disk_and_number(self):
        with patch("subprocess.check_output",
                   return_value=self._mock_output("nvme0n1p2", "nvme0n1", 2)):
            disk, num = Diskutils.separate_device_and_partn("/dev/nvme0n1p2")
        self.assertEqual(disk, "/dev/nvme0n1")
        self.assertEqual(num, "2")

    def test_bare_device_returns_none_for_partn(self):
        with patch("subprocess.check_output",
                   return_value=self._mock_output("sda", None, None)):
            disk, num = Diskutils.separate_device_and_partn("/dev/sda")
        self.assertEqual(disk, "/dev/sda")
        self.assertIsNone(num)

    def test_multiple_devices_raises_value_error(self):
        payload = json.dumps({
            "blockdevices": [
                {"name": "sda1", "pkname": "sda", "partn": 1},
                {"name": "sdb1", "pkname": "sdb", "partn": 1},
            ]
        }).encode()
        with patch("subprocess.check_output", return_value=payload):
            with self.assertRaises(ValueError):
                Diskutils.separate_device_and_partn("/dev/sda1")


class TestFetchLvmPvs(unittest.TestCase):
    """Tests for Diskutils.fetch_lvm_pvs()."""

    def test_returns_pv_vg_pairs(self):
        payload = json.dumps({
            "report": [{"pv": [
                {"pv_name": "/dev/sda2", "vg_name": "vg_data"},
                {"pv_name": "/dev/sdb1", "vg_name": ""},
            ]}]
        }).encode()
        with patch("subprocess.check_output", return_value=payload):
            result = Diskutils.fetch_lvm_pvs()
        self.assertEqual(result, [["/dev/sda2", "vg_data"], ["/dev/sdb1", None]])

    def test_empty_vg_name_becomes_none(self):
        payload = json.dumps({
            "report": [{"pv": [{"pv_name": "/dev/sdc1", "vg_name": ""}]}]
        }).encode()
        with patch("subprocess.check_output", return_value=payload):
            result = Diskutils.fetch_lvm_pvs()
        self.assertEqual(result, [["/dev/sdc1", None]])

    def test_returns_empty_list_on_exception(self):
        with patch("subprocess.check_output", side_effect=Exception("pvs not found")):
            result = Diskutils.fetch_lvm_pvs()
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Disk — one eligible disk from `fisherman probe --json`
# ---------------------------------------------------------------------------

_PROBED = {
    "path": "/dev/nvme0n1", "size_bytes": 1024209543168, "size_label": "953.9 GiB",
    "model": "WD_BLACK SN850X 1000GB", "vendor": "", "transport": "nvme",
    "transport_label": "NVMe", "removable": False, "read_only": False, "eligible": True,
}


class TestDiskClass(unittest.TestCase):
    def test_properties_come_from_the_probe(self):
        d = _Disk(dict(_PROBED))
        self.assertEqual(d.disk, "/dev/nvme0n1")
        self.assertEqual(d.name, "nvme0n1")
        self.assertEqual(d.block, "/sys/block/nvme0n1")
        self.assertEqual(d.size, 1024209543168)
        self.assertEqual(d.pretty_size, "953.9 GiB")
        self.assertEqual(d.model, "WD_BLACK SN850X 1000GB")
        self.assertEqual(d.display_name, "WD_BLACK SN850X 1000GB")
        self.assertEqual(d.transport_label, "NVMe")
        self.assertFalse(d.is_removable)

    def test_display_name_falls_back_to_the_path(self):
        d = _Disk(dict(_PROBED, model=""))
        self.assertEqual(d.display_name, "/dev/nvme0n1")

    def test_removable_is_reported_not_filtered(self):
        self.assertTrue(_Disk(dict(_PROBED, removable=True)).is_removable)

    def test_partitions_are_read_lazily_from_sysfs(self):
        d = _Disk(dict(_PROBED))
        with patch("bootc_installer.core.disks.os.listdir",
                   return_value=["nvme0n1p1", "queue", "nvme0n1p2"]) as listdir, \
             patch("bootc_installer.core.disks.Partition",
                   side_effect=lambda disk, part: (disk, part)):
            self.assertEqual(d.partitions, [("nvme0n1", "nvme0n1p1"), ("nvme0n1", "nvme0n1p2")])
            d.partitions
        listdir.assert_called_once_with("/sys/block/nvme0n1")

    def test_no_sysfs_means_no_partitions(self):
        d = _Disk(dict(_PROBED))
        with patch("bootc_installer.core.disks.os.listdir", side_effect=OSError):
            self.assertEqual(d.partitions, [])

    def test_get_partition_by_mountpoint(self):
        d = _Disk(dict(_PROBED))

        class _FakePart:
            def __init__(self, mp):
                self.mountpoint = mp

        root, boot = _FakePart("/"), _FakePart("/boot")
        d._Disk__partitions = [root, boot]
        self.assertIs(d.get_partition("/boot"), boot)
        self.assertIsNone(d.get_partition("/home"))


class TestPartitionInit(unittest.TestCase):
    """Tests for Partition.__init__ via mocked I/O."""

    def _make_partition(self, mountpoint=b"", fs_type=b"xfs", uuid=b"abc-123", label=b""):
        import io

        outputs = [mountpoint, fs_type, uuid, label]
        call_idx = [0]

        def fake_check_output(cmd, **kw):
            idx = call_idx[0]
            call_idx[0] += 1
            if idx < len(outputs):
                return outputs[idx]
            return b""

        with patch("subprocess.check_output", side_effect=fake_check_output), \
             patch("builtins.open", return_value=io.StringIO("2097152\n")):
            from bootc_installer.core.disks import Partition
            return Partition("nvme0n1", "nvme0n1p2")

    def test_partition_init_sets_properties(self):
        p = self._make_partition(mountpoint=b"/", fs_type=b"xfs", uuid=b"abc-123", label=b"root")
        self.assertEqual(p.mountpoint, "/")
        self.assertEqual(p.fs_type, "xfs")
        self.assertEqual(p.uuid, "abc-123")
        self.assertEqual(p.label, "root")
        self.assertEqual(p.size, 2097152 * 512)

    def test_partition_init_handles_subprocess_errors(self):
        """CalledProcessError from any subprocess returns None gracefully."""
        import subprocess as _sp

        def raise_cpe(cmd, **kw):
            raise _sp.CalledProcessError(1, cmd)

        import io
        with patch("subprocess.check_output", side_effect=raise_cpe), \
             patch("builtins.open", return_value=io.StringIO("0\n")):
            from bootc_installer.core.disks import Partition
            p = Partition("sda", "sda1")

        self.assertIsNone(p.mountpoint)
        self.assertIsNone(p.fs_type)
        self.assertIsNone(p.uuid)
        self.assertIsNone(p.label)



# ---------------------------------------------------------------------------
# Partition class — using __new__ + attribute injection
# ---------------------------------------------------------------------------


def _make_stub_partition(disk="nvme0n1", partition="nvme0n1p2",
                          mountpoint="/", size=512 * 1024 ** 3,
                          fs_type="xfs", uuid="abc-123", label="root"):
    """Create a Partition without calling __init__ (no subprocess/sysfs I/O)."""
    p = _Partition.__new__(_Partition)
    p._Partition__disk = disk
    p._Partition__partition = partition
    p._Partition__mountpoint = mountpoint
    p._Partition__size = size
    p._Partition__fs_type = fs_type
    p._Partition__uuid = uuid
    p._Partition__label = label
    return p


class TestPartitionClass(unittest.TestCase):
    """Tests for the Partition class properties via lightweight stubs."""

    def test_partition_property(self):
        p = _make_stub_partition(partition="nvme0n1p2")
        self.assertEqual(p.partition, "/dev/nvme0n1p2")

    def test_block_property(self):
        p = _make_stub_partition(disk="nvme0n1", partition="nvme0n1p2")
        self.assertEqual(p.block, "/sys/block/nvme0n1/nvme0n1p2")

    def test_mountpoint_property(self):
        p = _make_stub_partition(mountpoint="/boot")
        self.assertEqual(p.mountpoint, "/boot")

    def test_size_property(self):
        p = _make_stub_partition(size=1000)
        self.assertEqual(p.size, 1000)

    def test_pretty_size_uses_fishermans_rule(self):
        self.assertEqual(_make_stub_partition(size=500 * 1024 ** 3).pretty_size, "500 GiB")
        self.assertEqual(_make_stub_partition(size=10 * 1024 ** 2).pretty_size, "10 MiB")
        self.assertEqual(_make_stub_partition(size=512).pretty_size, "512 B")

    def test_fs_type_property(self):
        p = _make_stub_partition(fs_type="ext4")
        self.assertEqual(p.fs_type, "ext4")

    def test_uuid_property(self):
        p = _make_stub_partition(uuid="deadbeef")
        self.assertEqual(p.uuid, "deadbeef")

    def test_label_property(self):
        p = _make_stub_partition(label="EFI")
        self.assertEqual(p.label, "EFI")

    def test_lt_by_device_path(self):
        p1 = _make_stub_partition(partition="nvme0n1p1")
        p2 = _make_stub_partition(partition="nvme0n1p2")
        self.assertLess(p1, p2)

    def test_eq_same_uuid_and_fstype(self):
        p1 = _make_stub_partition(partition="nvme0n1p2", uuid="abc", fs_type="xfs")
        p2 = _make_stub_partition(partition="sda1", uuid="abc", fs_type="xfs")
        self.assertEqual(p1, p2)

    def test_neq_different_uuid(self):
        p1 = _make_stub_partition(uuid="abc", fs_type="xfs")
        p2 = _make_stub_partition(uuid="xyz", fs_type="xfs")
        self.assertNotEqual(p1, p2)

    def test_eq_none_is_false(self):
        p = _make_stub_partition()
        self.assertFalse(p == None)  # noqa: E711


if __name__ == "__main__":
    unittest.main()


class TestNoShellInjection(unittest.TestCase):
    """#163: device paths reach subprocess as one argv element, never a shell
    string, so shell metacharacters in them are inert."""

    HOSTILE = "/dev/sda1; touch {marker}; #"

    def test_hostile_device_path_runs_no_command(self):
        import tempfile

        marker = os.path.join(tempfile.mkdtemp(), "pwned")
        path = self.HOSTILE.format(marker=marker)
        # The real subprocess runs: lsblk rejects the odd device name, which
        # is fine. What must not happen is the shell running `touch`.
        try:
            Diskutils.separate_device_and_partn(path)
        except Exception:
            pass
        self.assertFalse(os.path.exists(marker), "the device path was run as a shell command")

    def test_every_disks_call_passes_an_argv_list(self):
        calls = []

        def fake(cmd, *args, **kwargs):
            calls.append((cmd, kwargs))
            return b'{"blockdevices": [{"name": "sda1", "pkname": "sda", "partn": 1}]}'

        with patch("subprocess.check_output", side_effect=fake):
            Diskutils.separate_device_and_partn("/dev/sda1; id")
        cmd, kwargs = calls[0]
        self.assertIsInstance(cmd, list)
        self.assertEqual(cmd[-1], "/dev/sda1; id")
        self.assertNotIn("shell", kwargs)

    def test_no_shell_true_left_in_disks_module(self):
        import bootc_installer.core.disks as disks_mod

        with open(disks_mod.__file__, encoding="utf-8") as fh:
            self.assertNotIn("shell=True", fh.read())
