"""How a Python frontend reaches fisherman on the host.

One place decides it, for the probe, the validate checks and the install:

  native    /usr/local/bin/fisherman. The install escalates with pkexec,
            and with `sudo -n` only on live media (fisherman's
            live.is_live), where the live user has passwordless sudo and
            may have no polkit agent. `-n`: sudo must not ask on a
            terminal that the installer does not have.
  Flatpak   the fisherman that the Flatpak built (/app/bin/fisherman),
            copied to $XDG_CACHE_HOME/bootc-installer/fisherman and
            compared on the host by SHA256 before anything runs it. The
            host needs no fisherman of its own.

The install escalates inside a bash that the frontend owns, never straight
from flatpak-spawn: fisherman runs as root, so the frontend cannot signal
it, and fisherman cancels itself when its parent dies
(tuna-os/fisherman#267). The parent is that bash, and the frontend signals
its process group.

`-`: fisherman reads the recipe from stdin (tuna-os/fisherman#276). The
frontend writes the JSON to the wrapper's stdin and closes it, so no file
holds the passphrase or the user password. bash, pkexec, sudo and
flatpak-spawn all pass stdin through.
"""

import hashlib
import os
import shlex
import shutil
import stat
import subprocess

from . import validate

FISHERMAN_PATH = "/usr/local/bin/fisherman"
BUNDLED_FISHERMAN = "/app/bin/fisherman"
# A test names a different binary to stage with this variable.
SOURCE_ENV = "BOOTC_FISHERMAN_PATH"

PURPOSES = ("probe", "validate", "validate-full", "plan", "install")


class StageError(Exception):
    """The bundled fisherman could not be put where the host can run it."""


def stage_dir(environ=None) -> str:
    """$XDG_CACHE_HOME/bootc-installer: Flatpak's persistent app cache.

    Never HOME/.cache. --filesystem=host does not expose /var/home on every
    host, and a HOME that the sandbox made up can be only in its own tmpfs;
    Flatpak always shares the app's XDG_CACHE_HOME with the host.
    """
    environ = os.environ if environ is None else environ
    cache_home = environ.get("XDG_CACHE_HOME", "")
    if not cache_home or not os.path.isabs(cache_home):
        raise StageError("Flatpak XDG_CACHE_HOME must be an absolute path")
    return os.path.join(cache_home, "bootc-installer")


def home_base(environ=None) -> str:
    """The user's own base directory: HOME, else the runtime directory."""
    environ = os.environ if environ is None else environ
    return (environ.get("HOME") or environ.get("XDG_RUNTIME_DIR")
            or f"/run/user/{os.getuid()}")


def private_path_problem(path, check_mode=True) -> str:
    """Why `path` is not safe to stage a root-executed helper at, or "".
    A path that does not exist is safe: the stage makes it."""
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return ""
    except OSError as error:
        return f"cannot stat {path}: {error}"
    if stat.S_ISLNK(path_stat.st_mode):
        return f"{path} is a symlink"
    if path_stat.st_uid != os.getuid():
        return f"{path} is owned by uid {path_stat.st_uid}, not {os.getuid()}"
    if check_mode and path_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return f"{path} is group- or world-writable"
    return ""


def sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def host_sha256(path) -> str:
    """The SHA256 of `path` as the HOST sees it, or "" when it cannot say."""
    try:
        seen = subprocess.run(["flatpak-spawn", "--host", "sha256sum", "--", path],
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    if seen.returncode:
        return ""
    return (seen.stdout.split(maxsplit=1) or [""])[0]


def stage(source=None, cache_dir=None, *, home=None, environ=None, host_hash=None) -> str:
    """Copy the bundled fisherman to the app cache and return its path.

    Before the copy, each directory on the way must be the user's own: the
    home base (a symlink or a foreign owner there means the cache below it
    is not the user's either; its mode is not judged), the parent of the
    cache directory, the cache directory and the file.

    After the copy, the file is hashed THROUGH THE HOST PORTAL: success
    inside the sandbox does not prove that pkexec and the probe see the
    same bytes. StageError when a step fails; nothing may run the staged
    file then.
    """
    environ = os.environ if environ is None else environ
    source = source or environ.get(SOURCE_ENV) or BUNDLED_FISHERMAN
    cache_dir = cache_dir or stage_dir(environ)
    host_path = os.path.join(cache_dir, "fisherman")
    problem = private_path_problem(home or home_base(environ), check_mode=False)
    for path in (os.path.dirname(cache_dir), cache_dir, host_path):
        problem = problem or private_path_problem(path)
    if problem:
        raise StageError(f"cannot stage fisherman: {problem}")
    try:
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
        shutil.copy2(source, host_path)
        os.chmod(host_path, stat.S_IRWXU)
        expected = sha256(source)
    except OSError as error:
        raise StageError(f"cannot stage fisherman: {error}") from error
    if (host_hash or host_sha256)(host_path) != expected:
        raise StageError(
            f"the staged fisherman is not byte-identical on the host: {host_path}")
    return host_path


def install_script(binary=FISHERMAN_PATH, escalate="pkexec", log_path=None) -> str:
    """The bash script of the install wrapper.

    Without `log_path` the wrapper does no redirection: stdout and stderr
    come back through the pipes. With it, the two go to that file, which
    the frontend then reads; the exit status is fisherman's in both cases.
    """
    redirect = f" >{shlex.quote(log_path)} 2>&1" if log_path else ""
    return f"{escalate} {shlex.quote(binary)} -{redirect}; exit $?"


def unprivileged(*, in_flatpak, host_path=None) -> list:
    """The way to reach fisherman as the desktop user, with no subcommand:
    the binary, behind `flatpak-spawn --host` in a Flatpak."""
    if in_flatpak:
        if not host_path:
            raise StageError("no staged fisherman: stage it before you build a command")
        return ["flatpak-spawn", "--host", host_path]
    return [FISHERMAN_PATH]


def command(purpose, *, in_flatpak, live=False, host_path=None, log_path=None,
            escalate=None) -> list:
    """The argv that runs fisherman for `purpose`. The only resolver.

    "probe" (`probe --json`), "validate" (`validate --json --partial -`) and
    "validate-full" (`validate --json -`) and "plan" (`plan --json -`,
    fisherman/docs/PLAN.md) run unprivileged, never through
    pkexec or sudo. "install" runs with privileges and reads the recipe on
    stdin.

    In a Flatpak `host_path` is the staged binary and must be given: the
    caller stages first (stage()). `live` is fisherman's live.is_live and
    matters only for a native install. `log_path` is for "install" only
    (install_script). `escalate` replaces the escalation command; it is
    for a test that has sudo and no polkit agent.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"unknown fisherman purpose {purpose!r}")
    plain = unprivileged(in_flatpak=in_flatpak, host_path=host_path)
    if purpose == "install":
        if in_flatpak:
            return ["flatpak-spawn", "--host", "bash", "-c",
                    install_script(host_path, escalate or "pkexec", log_path)]
        return ["bash", "-c", install_script(
            FISHERMAN_PATH, escalate or ("sudo -n" if live else "pkexec"), log_path)]
    if purpose == "probe":
        return plain + ["probe", "--json"]
    if purpose == "plan":
        return plain + ["plan", "--json", "-"]
    return validate.argv(plain, partial=purpose == "validate")
