"""Host execution boundary for the privileged fisherman helper.

The rules are in bootc_shared.fisherman_host, which XFCE also uses: where
the bundled fisherman is staged, how the stage is checked on the host, and
the one argv for the probe, the validate checks and the install. This
module is the GNOME half: the paths of this process, and the log file that
the install's output goes to (the progress page tails that file).
"""

import logging
import os
import subprocess  # noqa: F401 - tests patch fisherman_runner.subprocess.run

from bootc_shared import fisherman_host

logger = logging.getLogger("Installer::FishermanRunner")

IN_FLATPAK = os.path.exists("/.flatpak-info")


def default_stage_base() -> str:
    """Return the private user-owned base used for host-visible staging."""
    return fisherman_host.home_base()


def default_cache_dir() -> str:
    """Use Flatpak's persistent app cache, not its possibly private HOME.

    --filesystem=host does not expose /var/home on every host. Flatpak always
    shares the app-specific XDG_CACHE_HOME with the host; a synthetic
    HOME/.cache can instead live only in the current sandbox's tmpfs.
    Outside a Flatpak nothing is staged, and the directory only holds the
    install log.
    """
    if IN_FLATPAK:
        try:
            return fisherman_host.stage_dir()
        except fisherman_host.StageError as error:
            raise ValueError(str(error)) from error
    return os.path.join(default_stage_base(), ".cache", "bootc-installer")


STAGE_BASE = default_stage_base()
CACHE_DIR = default_cache_dir()
HOST_PATH = os.path.join(CACHE_DIR, "fisherman")
LOG_PATH = os.path.join(CACHE_DIR, "fisherman-output.log")


def build_argv(
    *,
    in_flatpak: bool = IN_FLATPAK,
    use_sudo: bool = False,
    host_path: str = HOST_PATH,
    log_path: str = LOG_PATH,
) -> list[str]:
    """Build the host-side command that runs fisherman and captures its output.

    fisherman reads the recipe from stdin (`fisherman -`, tuna-os/fisherman#276):
    the caller writes the JSON to the wrapper's stdin and closes it, so no
    recipe file ever holds the passphrase or the user password. stdout and
    stderr go to the log file, which the progress page tails.

    `use_sudo` is for live media outside a Flatpak, where the live user has
    passwordless sudo and may have no polkit agent; the command is then
    `sudo -n`, as in the other frontends. The caller decides it from
    fisherman's probe (`live.is_live`), never from /run/ostree-booted, which
    every installed ostree host has.
    """
    escalate = None
    if in_flatpak and os.environ.get("BOOTC_TEST"):
        # A test in a Flatpak with sudo and no polkit agent.
        host_path = os.environ.get(fisherman_host.SOURCE_ENV, host_path)
        escalate = "sudo"
    return fisherman_host.command(
        "install", in_flatpak=in_flatpak, live=use_sudo, host_path=host_path,
        log_path=log_path, escalate=escalate)


def fisherman_argv(
    *,
    in_flatpak: bool = IN_FLATPAK,
    host_path: str = HOST_PATH,
) -> list[str]:
    """The unprivileged way to reach fisherman, for `probe --json` and
    `validate --json`: the same binary the install runs, on the host, as the
    desktop user. In a Flatpak that is the staged copy, so the caller stages
    it first (stage_on_host)."""
    return fisherman_host.unprivileged(in_flatpak=in_flatpak, host_path=host_path)


def probe_argv(
    *,
    in_flatpak: bool = IN_FLATPAK,
    host_path: str = HOST_PATH,
) -> list[str]:
    """The unprivileged `fisherman probe --json` command (shared/probe/README.md).

    Never through pkexec or sudo: the probe needs no root.
    """
    return fisherman_host.command("probe", in_flatpak=in_flatpak, host_path=host_path)


def path_is_private(path: str, check_mode: bool = True) -> bool:
    """Return whether a path is safe for staging a root-executed helper."""
    problem = fisherman_host.private_path_problem(path, check_mode)
    if problem:
        logger.error("staging path refused: %s", problem)
    return not problem


def stage_on_host(
    *,
    in_flatpak: bool = IN_FLATPAK,
    stage_base: str = STAGE_BASE,
    cache_dir: str = CACHE_DIR,
    host_path: str = HOST_PATH,
) -> bool:
    """Copy fisherman to a private host-visible location for pkexec.

    True when the staged file is there and the host sees the same bytes.
    `host_path` is always `<cache_dir>/fisherman`.
    """
    if not in_flatpak:
        return True
    try:
        staged = fisherman_host.stage(cache_dir=cache_dir, home=stage_base)
    except fisherman_host.StageError as error:
        logger.error("%s", error)
        return False
    if staged != host_path:
        logger.error("Staged fisherman is at %s, not at %s", staged, host_path)
        return False
    logger.info("Staged and host-verified fisherman binary to %s", staged)
    return True
