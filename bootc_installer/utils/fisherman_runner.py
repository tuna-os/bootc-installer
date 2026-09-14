"""Host execution boundary for the privileged fisherman helper."""

import logging
import os
import shutil
import stat

logger = logging.getLogger("Installer::FishermanRunner")

IN_FLATPAK = os.path.exists("/.flatpak-info")
LIVE_ISO = not IN_FLATPAK and os.path.exists("/run/ostree-booted")


def default_stage_base() -> str:
    """Return the private user-owned base used for host-visible staging."""
    return (
        os.environ.get("HOME")
        or os.environ.get("XDG_RUNTIME_DIR")
        or f"/run/user/{os.getuid()}"
    )


STAGE_BASE = default_stage_base()
CACHE_DIR = os.path.join(STAGE_BASE, ".cache", "bootc-installer")
HOST_PATH = os.path.join(CACHE_DIR, "fisherman")
LOG_PATH = os.path.join(CACHE_DIR, "fisherman-output.log")


def build_argv(
    recipe: str,
    *,
    in_flatpak: bool = IN_FLATPAK,
    live_iso: bool = LIVE_ISO,
    host_path: str = HOST_PATH,
    log_path: str = LOG_PATH,
) -> list[str]:
    """Build the host-side command used to run fisherman and capture output."""
    if in_flatpak:
        if os.environ.get("BOOTC_TEST"):
            binary = os.environ.get("BOOTC_FISHERMAN_PATH", host_path)
            command = f'sudo "{binary}" "$1" >"{log_path}" 2>&1; exit $?'
        else:
            command = f'pkexec "{host_path}" "$1" >"{log_path}" 2>&1; exit $?'
        return ["flatpak-spawn", "--host", "bash", "-c", command, "--", recipe]
    if live_iso:
        command = f'sudo /usr/local/bin/fisherman "$1" >"{log_path}" 2>&1; exit $?'
    else:
        command = f'pkexec /usr/local/bin/fisherman "$1" >"{log_path}" 2>&1; exit $?'
    return ["bash", "-c", command, "--", recipe]


def path_is_private(path: str, check_mode: bool = True) -> bool:
    """Return whether a path is safe for staging a root-executed helper."""
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError as error:
        logger.error("cannot stat staging path %s: %s", path, error)
        return False

    if stat.S_ISLNK(path_stat.st_mode):
        logger.error("staging path %s is a symlink; refusing", path)
        return False
    if path_stat.st_uid != os.getuid():
        logger.error("staging path %s is owned by uid %d, not %d; refusing",
                     path, path_stat.st_uid, os.getuid())
        return False
    if check_mode and path_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        logger.error("staging path %s is group- or world-writable; refusing", path)
        return False
    return True


def stage_on_host(
    *,
    in_flatpak: bool = IN_FLATPAK,
    stage_base: str = STAGE_BASE,
    cache_dir: str = CACHE_DIR,
    host_path: str = HOST_PATH,
) -> bool:
    """Copy fisherman to a private host-visible location for pkexec."""
    if not in_flatpak:
        return True
    if not path_is_private(stage_base, check_mode=False):
        return False
    for path in (os.path.dirname(cache_dir), cache_dir, host_path):
        if not path_is_private(path):
            return False

    os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    source = os.environ.get("BOOTC_FISHERMAN_PATH", "/app/bin/fisherman")
    try:
        shutil.copy2(source, host_path)
        os.chmod(host_path, stat.S_IRWXU)
        logger.info("Staged fisherman binary to %s", host_path)
        return True
    except OSError as error:
        logger.error("Failed to stage fisherman binary: %s", error)
        return False
