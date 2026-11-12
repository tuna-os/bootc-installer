"""The GTK windows' host actions (bootc_installer.utils.host_actions, #82).

Each test gives a recording executor and checks the argv, the scope and the
timeout of what would run, natively and in a Flatpak.
"""

import unittest

from bootc_installer.utils import host_actions
from bootc_installer.utils.host import Scope
from tests.unit.fake_host import FAIL, MISSING, OK, STARTED, FakeExecutor


class TestHostSystemctl(unittest.TestCase):
    def test_power_actions_run_on_the_host_without_a_timeout(self):
        for args in (("poweroff",), ("reboot",), ("reboot", "--firmware-setup")):
            with self.subTest(args=args):
                ex = FakeExecutor([OK], in_flatpak=True)
                self.assertTrue(host_actions.host_systemctl(*args, executor=ex))
                kind, cmd, scope, timeout, argv = ex.calls[0]
                self.assertEqual(kind, "run")
                self.assertEqual(argv, ["flatpak-spawn", "--host", "systemctl", *args])
                self.assertIs(scope, Scope.HOST)
                self.assertIsNone(timeout)

    def test_failure_is_a_result(self):
        for answer in (FAIL, MISSING):
            with self.subTest(answer=answer):
                self.assertFalse(host_actions.host_systemctl(
                    "poweroff", executor=FakeExecutor([answer])))


class TestBluetoothSettings(unittest.TestCase):
    def test_first_tool_that_starts_wins(self):
        ex = FakeExecutor([STARTED], in_flatpak=True)
        self.assertTrue(host_actions.open_bluetooth_settings(ex))
        self.assertEqual(len(ex.calls), 1)
        kind, cmd, scope, timeout, argv = ex.calls[0]
        self.assertEqual(kind, "spawn")
        self.assertIs(scope, Scope.HOST)
        self.assertEqual(argv, ["flatpak-spawn", "--host", "gnome-control-center", "bluetooth"])

    def test_a_missing_tool_tries_the_next(self):
        ex = FakeExecutor([MISSING, MISSING, MISSING], in_flatpak=False)
        self.assertFalse(host_actions.open_bluetooth_settings(ex))
        self.assertEqual([c[4] for c in ex.calls], [
            ["gnome-control-center", "bluetooth"],
            ["gnome-bluetooth-panel"],
            ["blueman-manager"],
        ])

    def test_another_error_stops(self):
        ex = FakeExecutor([{"returncode": None, "stderr": "permission denied"}])
        self.assertFalse(host_actions.open_bluetooth_settings(ex))
        self.assertEqual(len(ex.calls), 1)


class TestRestartIgnoring(unittest.TestCase):
    def test_env_argv_not_a_shell_string(self):
        ex = FakeExecutor([STARTED], in_flatpak=True)
        self.assertTrue(host_actions.restart_ignoring("RAM", "CPU", executor=ex))
        kind, cmd, scope, timeout, argv = ex.calls[0]
        self.assertEqual(kind, "spawn")
        self.assertIs(scope, Scope.LOCAL)
        self.assertEqual(argv, ["env", "IGNORE_RAM=1", "IGNORE_CPU=1", "vanilla-installer"])

    def test_cannot_start(self):
        self.assertFalse(host_actions.restart_ignoring("RAM", executor=FakeExecutor([MISSING])))


class TestWindowsCallTheActions(unittest.TestCase):
    """The GTK windows only name the action; the argv lives above."""

    def _source(self, rel):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2] / "bootc_installer"
        return (root / rel).read_text(encoding="utf-8")

    def test_windows(self):
        self.assertIn('host_systemctl("poweroff")', self._source("windows/window_unsupported.py"))
        self.assertIn('restart_ignoring("RAM")', self._source("windows/window_ram.py"))
        self.assertIn('restart_ignoring("RAM", "CPU")', self._source("windows/window_cpu.py"))
        self.assertIn("open_bluetooth_settings()", self._source("defaults/welcome.py"))


if __name__ == "__main__":
    unittest.main()
