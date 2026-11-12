"""The disk step's host probes (bootc_installer.defaults.disk_host, #85).

A fake executor records each command and its scope and answers from a
script, so the tests show which argv runs where and what each failure means.
"""

import os
import tempfile
import unittest

from bootc_installer.defaults import disk_host
from bootc_installer.utils.host import HostExecutor, HostResult, Scope


class _FakeExecutor(HostExecutor):
    def __init__(self, answers, *, in_flatpak=True):
        super().__init__(in_flatpak=in_flatpak, popen=None)
        self.answers = list(answers)
        self.calls = []

    def run(self, cmd, *, scope=Scope.HOST, timeout=10, cancel=None, input_text=None):
        self.calls.append((list(cmd), scope, self.argv(cmd, scope)))
        answer = self.answers.pop(0)
        return HostResult(tuple(self.argv(cmd, scope)), **answer)


OK = {"returncode": 0}
FAIL = {"returncode": 1, "stderr": "boom"}
TIMEOUT = {"returncode": None, "timed_out": True}
MISSING = {"returncode": None, "missing_command": True}


class TestFsToolAvailable(unittest.TestCase):
    def test_found(self):
        ex = _FakeExecutor([OK])
        self.assertTrue(disk_host.fs_tool_available("mkfs.xfs", ex))
        cmd, scope, argv = ex.calls[0]
        self.assertIs(scope, Scope.HOST)
        self.assertEqual(argv[:4], ["flatpak-spawn", "--host", "sh", "-c"])
        self.assertEqual(argv[-1], "mkfs.xfs")

    def test_fails_closed(self):
        # The old probe treated any exception as "installed" (#85).
        for answer in (FAIL, TIMEOUT, MISSING):
            with self.subTest(answer=answer):
                self.assertFalse(disk_host.fs_tool_available("mkfs.xfs", _FakeExecutor([answer])))

    def test_native_probe_does_not_use_flatpak_spawn(self):
        ex = _FakeExecutor([OK], in_flatpak=False)
        disk_host.fs_tool_available("mkfs.btrfs", ex)
        self.assertEqual(ex.calls[0][2][:2], ["sh", "-c"])

    def test_real_native_probe(self):
        ex = HostExecutor(in_flatpak=False)
        self.assertTrue(disk_host.fs_tool_available("sh", ex))
        self.assertFalse(disk_host.fs_tool_available("bootc-installer-no-such-mkfs", ex))

    def test_tools_table(self):
        self.assertEqual(disk_host.FS_TOOLS["xfs"], ("mkfs.xfs", "xfsprogs"))
        self.assertEqual(set(disk_host.FS_TOOLS), {"xfs", "btrfs", "zfs"})


class TestHasExistingFilesystem(unittest.TestCase):
    def test_filesystem_found(self):
        ex = _FakeExecutor([{"returncode": 0, "stdout": "\next4\n"}])
        self.assertIs(disk_host.has_existing_filesystem("/dev/vdb", ex), True)
        self.assertEqual(ex.calls[0][2],
                         ["flatpak-spawn", "--host", "lsblk", "-no", "FSTYPE", "--", "/dev/vdb"])

    def test_blank_disk(self):
        ex = _FakeExecutor([{"returncode": 0, "stdout": "\n\n"}])
        self.assertIs(disk_host.has_existing_filesystem("/dev/vdb", ex), False)

    def test_unknown_when_lsblk_cannot_tell(self):
        # The old probe treated any exception as "no filesystem", so the
        # disk would be formatted without the keep/format choice (#82).
        for answer in (FAIL, TIMEOUT, MISSING):
            with self.subTest(answer=answer):
                self.assertIsNone(
                    disk_host.has_existing_filesystem("/dev/vdb", _FakeExecutor([answer])))

    def test_keep_is_offered_unless_the_disk_is_known_blank(self):
        self.assertTrue(disk_host.offer_keep(True))
        self.assertTrue(disk_host.offer_keep(None))
        self.assertFalse(disk_host.offer_keep(False))

    def test_not_a_device_runs_nothing(self):
        ex = _FakeExecutor([])
        self.assertIsNone(disk_host.has_existing_filesystem("-o NAME", ex))
        self.assertEqual(ex.calls, [])


class TestSetupLoopDevice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.img = os.path.join(self.tmp.name, "cache", "virtual-disk.img")

    def tearDown(self):
        self.tmp.cleanup()

    def _listing(self):
        return {"returncode": 0,
                "stdout": f"/dev/loop0 /var/lib/other.img\n/dev/loop3 {self.img}\n"}

    def test_creates_attaches_and_finds_the_device(self):
        ex = _FakeExecutor([OK, OK, self._listing()])
        self.assertEqual(disk_host.setup_loop_device(self.img, "50G", ex, environ={}),
                         "/dev/loop3")
        self.assertTrue(os.path.isdir(os.path.dirname(self.img)))
        (truncate, s1, a1), (attach, s2, a2), (listing, s3, a3) = ex.calls
        self.assertEqual((s1, a1), (Scope.LOCAL, ["truncate", "-s", "50G", "--", self.img]))
        self.assertEqual((s2, a2), (Scope.ELEVATED,
                                    ["flatpak-spawn", "--host", "pkexec",
                                     "losetup", "-fP", "--", self.img]))
        self.assertIs(s3, Scope.HOST)
        self.assertEqual(a3[:3], ["flatpak-spawn", "--host", "losetup"])

    def test_native_elevation_is_plain_pkexec(self):
        ex = _FakeExecutor([OK, OK, self._listing()], in_flatpak=False)
        disk_host.setup_loop_device(self.img, "50G", ex, environ={})
        self.assertEqual(ex.calls[1][2][:2], ["pkexec", "losetup"])

    def test_stops_at_the_first_failed_step(self):
        for answers, ran in (([FAIL], 1), ([OK, FAIL], 2), ([OK, TIMEOUT], 2),
                             ([OK, MISSING], 2), ([OK, OK, FAIL], 3)):
            with self.subTest(answers=answers):
                ex = _FakeExecutor(answers)
                self.assertIsNone(disk_host.setup_loop_device(self.img, "50G", ex, environ={}))
                self.assertEqual(len(ex.calls), ran)

    def test_no_device_backed_by_the_image(self):
        ex = _FakeExecutor([OK, OK, {"returncode": 0, "stdout": "/dev/loop0 /other.img\n"}])
        self.assertIsNone(disk_host.setup_loop_device(self.img, "50G", ex, environ={}))

    def test_pre_created_device_runs_nothing(self):
        ex = _FakeExecutor([])
        got = disk_host.setup_loop_device(self.img, "50G", ex,
                                          environ={"BOOTC_VIRTUAL_DISK": "/dev/loop9"})
        self.assertEqual(got, "/dev/loop9")
        self.assertEqual(ex.calls, [])

    def test_loop_device_for_keeps_spaces_in_the_path(self):
        listing = "/dev/loop1 /home/a b/disk.img\n"
        self.assertEqual(disk_host.loop_device_for(listing, "/home/a b/disk.img"), "/dev/loop1")
        self.assertIsNone(disk_host.loop_device_for(listing, "/home/a"))


class TestDiskPageUsesTheHelpers(unittest.TestCase):
    """The GTK page keeps no subprocess call of its own."""

    def test_disk_py_has_no_subprocess(self):
        import pathlib

        src = (pathlib.Path(disk_host.__file__).with_name("disk.py")).read_text(encoding="utf-8")
        self.assertNotIn("subprocess", src)
        self.assertNotIn("flatpak-spawn", src)
        for helper in ("fs_tool_available", "has_existing_filesystem", "setup_loop_device",
                       "offer_keep"):
            self.assertIn(f"disk_host.{helper}(", src)


if __name__ == "__main__":
    unittest.main()
