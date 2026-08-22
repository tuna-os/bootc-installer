"""The libbge probes must diagnose without ever failing the build.

bootc-installer#25: libbge installs bge.h, which #includes
bge-markdown-render.h, without installing that header, so libpastry fails:

    /app/include/bge/bge.h:32:10: fatal error: bge-markdown-render.h:
    No such file or directory

It is arch-specific rather than a plain packaging gap. In run 32537597515 the
x86_64 job compiled libbge AND libpastry from source -- that log contains no
cache-restore lines at all -- and passed. Same sources, only aarch64 failed.
bazaar-org is outside this session's repo scope, so the cause is being read
out of the build rather than guessed at.

These probes are temporary. They must not change what the module builds or
installs, and a probe that fails the build would convert a diagnostic into a
new outage on the one arch that currently still works.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "flatpak" / "org.bootcinstaller.Installer.json"


def libbge() -> dict:
    modules = json.loads(MANIFEST.read_text(encoding="utf-8"))["modules"]
    return next(m for m in modules if m.get("name") == "libbge")


def probes() -> list[str]:
    return [c for c in libbge()["build-commands"] if "bge probe" in c]


def test_the_probes_exist():
    assert probes(), "no libbge probes found"


def test_every_probe_that_can_fail_is_tolerated():
    """`uname -m` cannot fail; everything that inspects the filesystem or a
    log can, and must not take the build down with it."""
    for cmd in probes():
        if cmd.rstrip().endswith("uname -m"):
            continue
        assert cmd.rstrip().endswith("|| true"), cmd


def test_the_probes_run_after_install_not_before():
    """Reading /app/include/bge before `meson install` would report an empty
    directory on every arch and prove nothing."""
    cmds = libbge()["build-commands"]
    install = next(i for i, c in enumerate(cmds) if c.startswith("meson install"))
    assert all(cmds.index(p) > install for p in probes())


def test_the_probes_do_not_alter_the_build():
    """A probe that writes into /app would make the diagnostic itself the fix
    and hide what libbge actually does."""
    # Reading a path under _flatpak_build/meson-logs/ is fine; INVOKING meson
    # is not. Match invocations, not any occurrence of the word.
    for cmd in probes():
        for mutating in ("install -D", "cp ", "mv ", "rm ", "ln -s",
                         "&& meson ", "; meson "):
            assert mutating not in cmd, (mutating, cmd)
        assert not cmd.lstrip().startswith("meson "), cmd


def test_the_real_build_commands_are_unchanged():
    cmds = [c for c in libbge()["build-commands"] if "bge probe" not in c]
    assert cmds == [
        "meson setup _flatpak_build --prefix=/app -Dbge_only=true",
        "meson compile -C _flatpak_build",
        "meson install -C _flatpak_build",
        "ln -sf bge-0.7.15.pc /app/lib/pkgconfig/libbge.pc",
    ], cmds


def test_the_probes_name_the_issue_they_serve():
    """Undated, unattributed debug output is what never gets removed."""
    assert "#25" in json.dumps(libbge())
