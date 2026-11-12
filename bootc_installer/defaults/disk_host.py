"""The host probes of the disk step, without GTK (#85).

The disk step asks the host three things: whether the mkfs tool of a
filesystem is installed, which loop device a virtual disk image gets, and
whether a disk for /var already has a filesystem. Each helper takes a
`HostExecutor` (`bootc_installer.utils.host`) so a test can give one that
records the argv, and returns a plain value that the GTK page shows.
"""

from __future__ import annotations

import logging
import os

from bootc_installer.utils.host import HostExecutor, Scope, default_executor

logger = logging.getLogger("Installer::DiskHost")

# filesystem -> (tool that creates it, package that has the tool)
FS_TOOLS = {
    "xfs": ("mkfs.xfs", "xfsprogs"),
    "btrfs": ("mkfs.btrfs", "btrfs-progs"),
    "zfs": ("zpool", "zfsutils-linux"),
}

# pkexec waits for the user at the polkit prompt.
_ELEVATED_TIMEOUT = 300


def fs_tool_available(tool: str, executor: HostExecutor | None = None) -> bool:
    """Whether `tool` is on the host's PATH.

    Fails closed: a probe that cannot run, times out or exits non-zero
    counts as "not installed", so the page does not offer a filesystem that
    fisherman cannot create.
    """
    executor = executor or default_executor()
    result = executor.command_exists(tool, scope=Scope.HOST, timeout=3)
    if not result.ok:
        logger.info("Filesystem tool %s not found on the host (%s)", tool, result.describe())
    return result.ok


def has_existing_filesystem(device: str, executor: HostExecutor | None = None) -> bool | None:
    """Whether `device` or one of its partitions has a filesystem.

    True or False when lsblk answered; None when it could not tell (lsblk
    missing, failed or timed out). The caller treats None as "maybe": it
    offers to keep the data instead of formatting the disk without asking.
    """
    if not device.startswith("/dev/"):
        logger.warning("Not a device path: %r", device)
        return None
    executor = executor or default_executor()
    result = executor.run(["lsblk", "-no", "FSTYPE", "--", device], scope=Scope.HOST, timeout=10)
    if not result.ok:
        logger.warning("Cannot read the filesystems of %s: %s", device, result.describe())
        return None
    return bool(result.stdout.strip())


def offer_keep(existing: bool | None) -> bool:
    """Whether the /var disk page shows the keep/format choice, with "keep"
    on: when the disk has a filesystem, and when lsblk could not tell."""
    return existing is not False


def setup_loop_device(
    img: str,
    size: str,
    executor: HostExecutor | None = None,
    *,
    environ=None,
) -> str | None:
    """Create the virtual disk image `img` and attach it as a loop device.

    Returns the loop device path, or None when a step failed (logged).
    BOOTC_VIRTUAL_DISK names a loop device that was made outside the
    sandbox; then nothing is run.
    """
    environ = os.environ if environ is None else environ
    pre_created = environ.get("BOOTC_VIRTUAL_DISK", "")
    if pre_created.startswith("/dev/"):
        logger.info("Using pre-created virtual disk: %s", pre_created)
        return pre_created

    executor = executor or default_executor()
    try:
        os.makedirs(os.path.dirname(img), exist_ok=True)
    except OSError as error:
        logger.error("Cannot create the directory of %s: %s", img, error)
        return None

    logger.info("Creating virtual disk image: %s (%s)", img, size)
    steps = (
        (["truncate", "-s", size, "--", img], Scope.LOCAL, 60),
        (["losetup", "-fP", "--", img], Scope.ELEVATED, _ELEVATED_TIMEOUT),
    )
    for cmd, scope, timeout in steps:
        result = executor.run(cmd, scope=scope, timeout=timeout)
        if not result.ok:
            logger.error("Failed to set up loop device: %s", result.describe())
            return None

    listing = executor.run(
        ["losetup", "--list", "--output", "NAME,BACK-FILE", "--noheadings"],
        scope=Scope.HOST, timeout=10,
    )
    if not listing.ok:
        logger.error("Failed to list loop devices: %s", listing.describe())
        return None
    device = loop_device_for(listing.stdout, img)
    if device is None:
        logger.error("Could not find loop device after setup")
    else:
        logger.info("Loop device: %s", device)
    return device


def loop_device_for(listing: str, img: str) -> str | None:
    """The device in `losetup --list --output NAME,BACK-FILE` backed by `img`."""
    for line in listing.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip() == img:
            return parts[0]
    return None
