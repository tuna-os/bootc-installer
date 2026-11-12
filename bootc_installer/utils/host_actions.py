"""The small host actions of the GTK windows, without GTK (#82).

Power off, reboot, firmware setup, the Bluetooth settings and the restart
that skips a hardware check. Each one goes through `HostExecutor`
(`bootc_installer.utils.host`) and takes an `executor`, so a test can
record the argv and the scope.
"""

from __future__ import annotations

import logging

from bootc_installer.utils.host import HostExecutor, Scope, default_executor

logger = logging.getLogger("Installer::HostActions")

# The desktop's Bluetooth settings, the first one the host has.
BLUETOOTH_COMMANDS = (
    ("gnome-control-center", "bluetooth"),
    ("gnome-bluetooth-panel",),
    ("blueman-manager",),
)


def host_systemctl(*args: str, executor: HostExecutor | None = None) -> bool:
    """Run `systemctl <args>` on the host and wait for it. True on exit 0.

    The sandbox has no systemctl, so this is `Scope.HOST`. No timeout:
    power off and reboot end the session, and in a Flatpak a timeout would
    kill flatpak-spawn but not the host command (utils/host.py).
    """
    result = (executor or default_executor()).run(
        ["systemctl", *args], scope=Scope.HOST, timeout=None)
    if not result.ok:
        logger.error("%s", result.describe())
    return result.ok


def open_bluetooth_settings(executor: HostExecutor | None = None) -> bool:
    """Start the first Bluetooth settings tool that starts, on the host.

    A missing tool tries the next one; any other error stops. In a Flatpak
    only a missing flatpak-spawn counts as missing, as before.
    """
    executor = executor or default_executor()
    for command in BLUETOOTH_COMMANDS:
        result = executor.spawn(command, scope=Scope.HOST)
        if result.started:
            return True
        if not result.missing_command:
            logger.warning("Could not open the Bluetooth settings: %s", result.describe())
            return False
    return False


def restart_ignoring(*checks: str, program: str = "vanilla-installer",
                     executor: HostExecutor | None = None) -> bool:
    """Start the installer again with IGNORE_<check>=1 for each check.

    This was `IGNORE_RAM=1 vanilla-installer` through a shell; it is now
    an argv for `env`, in this process's environment (`Scope.LOCAL`).
    """
    argv = ["env", *(f"IGNORE_{check}=1" for check in checks), program]
    result = (executor or default_executor()).spawn(argv, scope=Scope.LOCAL)
    if not result.started:
        logger.error("%s", result.describe())
    return result.started
