"""
Unit tests for bootc_installer/readiness.py — pure Python, no GTK required.

This module is the smoke-test safety net for the COSMIC-leg incident
described in its own docstring: a frontend process can be alive with no
window ever mapped, and `flatpak ps` alone cannot tell. write_stamp()/arm()
were entirely untested (0% of write_stamp, arm not exercised at all).
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bootc_installer import readiness  # noqa: E402


class TestStampPath(unittest.TestCase):
    def test_returns_none_without_xdg_runtime_dir(self):
        env = dict(os.environ)
        env.pop("XDG_RUNTIME_DIR", None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(readiness.stamp_path())

    def test_joins_runtime_dir_and_stamp_name(self):
        with unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}):
            self.assertEqual(
                readiness.stamp_path(),
                os.path.join("/run/user/1000", readiness.STAMP_NAME),
            )


class TestWriteStamp(unittest.TestCase):
    def test_no_runtime_dir_logs_warning_and_does_not_raise(self):
        env = dict(os.environ)
        env.pop("XDG_RUNTIME_DIR", None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs(readiness.logger, level="WARNING") as cm:
                readiness.write_stamp("app.id", "BootcMainWindow")
        self.assertTrue(any("XDG_RUNTIME_DIR" in msg for msg in cm.output))

    def test_writes_expected_fields_via_atomic_rename(self):
        tmp_dir = self.enterContext(_temp_runtime_dir())
        readiness.write_stamp("com.tuna.Installer", "BootcMainWindow", page="disk")

        path = os.path.join(tmp_dir, readiness.STAMP_NAME)
        self.assertTrue(os.path.exists(path))
        # No leftover .tmp<pid> file — os.replace() must have run.
        leftovers = [f for f in os.listdir(tmp_dir) if f != readiness.STAMP_NAME]
        self.assertEqual(leftovers, [])

        content = open(path).read()
        self.assertIn("app_id=com.tuna.Installer", content)
        self.assertIn("window=BootcMainWindow", content)
        self.assertIn(f"signal={readiness.SIGNAL}", content)
        self.assertIn("page=disk", content)
        self.assertRegex(content, r"mapped_at=\d+\.\d{3}")

    def test_page_omitted_when_not_given(self):
        tmp_dir = self.enterContext(_temp_runtime_dir())
        readiness.write_stamp("com.tuna.Installer", "BootcMainWindow")

        content = open(os.path.join(tmp_dir, readiness.STAMP_NAME)).read()
        self.assertNotIn("page=", content)

    def test_overwrites_stale_stamp_from_prior_session(self):
        tmp_dir = self.enterContext(_temp_runtime_dir())
        readiness.write_stamp("com.tuna.Installer", "BootcCpuWindow")
        readiness.write_stamp("com.tuna.Installer", "BootcMainWindow")

        content = open(os.path.join(tmp_dir, readiness.STAMP_NAME)).read()
        self.assertIn("window=BootcMainWindow", content)
        self.assertNotIn("BootcCpuWindow", content)

    def test_oserror_on_write_is_caught_and_logged(self):
        tmp_dir = self.enterContext(_temp_runtime_dir())
        with unittest.mock.patch("builtins.open", side_effect=OSError("disk full")):
            with self.assertLogs(readiness.logger, level="ERROR"):
                readiness.write_stamp("com.tuna.Installer", "BootcMainWindow")
        # Best-effort: must not raise, and must not leave a partial stamp.
        self.assertFalse(os.path.exists(os.path.join(tmp_dir, readiness.STAMP_NAME)))


class TestArm(unittest.TestCase):
    def test_connects_to_map_signal(self):
        window = MagicMock()
        readiness.arm(window, "com.tuna.Installer")
        window.connect.assert_called_once()
        self.assertEqual(window.connect.call_args[0][0], "map")

    def test_map_callback_writes_stamp_with_widget_class_name(self):
        tmp_dir = self.enterContext(_temp_runtime_dir())

        class BootcRamWindow:
            pass

        window = MagicMock()
        readiness.arm(window, "com.tuna.Installer", page="ram-check")
        on_map = window.connect.call_args[0][1]

        on_map(BootcRamWindow())

        content = open(os.path.join(tmp_dir, readiness.STAMP_NAME)).read()
        self.assertIn("window=BootcRamWindow", content)
        self.assertIn("page=ram-check", content)


class _temp_runtime_dir:
    """Context manager: a throwaway XDG_RUNTIME_DIR for one test."""

    def __enter__(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self._patcher = unittest.mock.patch.dict(
            os.environ, {"XDG_RUNTIME_DIR": self._tmpdir.name}
        )
        self._patcher.start()
        return self._tmpdir.name

    def __exit__(self, *exc_info):
        self._patcher.stop()
        self._tmpdir.cleanup()
        return False


if __name__ == "__main__":
    unittest.main()
