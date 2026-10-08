"""Unit tests for windows/dialog_poweroff.py's host systemctl helper.

The dialog's rows used to call a bare `systemctl`, which does not exist in
the flatpak sandbox; every row raised FileNotFoundError out of its signal
handler. gi.repository is stubbed at import time, as in
test_dialog_recovery.py.
"""

import importlib
import sys
import unittest
from unittest.mock import patch

from tests.unit.test_dialog_recovery import _build_gi_stubs


def _import_fresh():
    _build_gi_stubs()
    sys.modules.pop("bootc_installer.windows.dialog_poweroff", None)
    return importlib.import_module("bootc_installer.windows.dialog_poweroff")


_mod = _import_fresh()


class HostSystemctlTests(unittest.TestCase):
    def test_wraps_in_flatpak_spawn_inside_the_sandbox(self):
        with patch.object(_mod, "_IN_FLATPAK", True), \
                patch.object(_mod.subprocess, "call") as call:
            _mod._host_systemctl("reboot", "--firmware-setup")
        call.assert_called_once_with(
            ["flatpak-spawn", "--host", "systemctl", "reboot", "--firmware-setup"])

    def test_runs_directly_outside_the_sandbox(self):
        with patch.object(_mod, "_IN_FLATPAK", False), \
                patch.object(_mod.subprocess, "call") as call:
            _mod._host_systemctl("poweroff")
        call.assert_called_once_with(["systemctl", "poweroff"])

    def test_missing_binary_is_logged_not_raised(self):
        with patch.object(_mod.subprocess, "call", side_effect=FileNotFoundError("systemctl")):
            _mod._host_systemctl("reboot")  # must not raise


if __name__ == "__main__":
    unittest.main()
