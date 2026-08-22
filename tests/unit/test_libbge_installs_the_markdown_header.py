"""libbge must install the header its own public header includes.

bootc-installer#25. `bge.h` unconditionally does:

    #include "bge-markdown-render.h"

and libbge's meson.build omits that header from the installed set, so
libpastry fails to compile against an installed libbge:

    /app/include/bge/bge.h:32:10: fatal error: bge-markdown-render.h:
    No such file or directory

## It is NOT arch-specific, despite only failing on aarch64

Probes on run 32547509965 settled this. The header IS in the source tree, the
object IS compiled ([12/18] bge-markdown-render.c.o), md4c IS found (0.5.2),
and meson's own install-log lists eight headers without it -- identically on
both architectures.

x86_64 passes by ACCIDENT. libbge's .pc installs to the arch libdir, which is
/app/lib64 there and /app/lib on aarch64, while the manifest symlinks
libbge.pc into /app/lib/pkgconfig unconditionally. On x86_64 that symlink
dangles, so meson never finds the installed libbge at all:

    x86_64:  Run-time dependency libbge found: NO (tried pkgconfig and cmake)
             Looking for a fallback subproject for the dependency libbge
             Executing subproject bazaar                    -> builds, passes
    aarch64: Run-time dependency libbge found: YES 0.7.15   -> hits the gap

So x86_64 has never exercised the installed libbge, and the "arch-specific"
reading of this bug was wrong. Installing the header fixes aarch64 and is
harmless on x86_64, which continues to use its vendored subproject.

The dangling symlink is deliberately NOT fixed here: repairing it would flip
x86_64 onto the installed-libbge path for the first time, which is a
behaviour change on the arch that currently works, and belongs in its own
change.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "flatpak" / "org.bootcinstaller.Installer.json"


def libbge() -> dict:
    modules = json.loads(MANIFEST.read_text(encoding="utf-8"))["modules"]
    return next(m for m in modules if m.get("name") == "libbge")


def commands() -> list[str]:
    return libbge()["build-commands"]


def test_the_missing_header_is_installed():
    assert any(
        "bge-markdown-render.h" in c and "/app/include/bge/" in c
        for c in commands()
    ), commands()


def test_it_is_installed_from_the_source_tree_path_the_probe_found():
    """`bge/bge-markdown-render.h` is where the probe actually saw it. A
    guessed path would fail the build rather than fix it."""
    assert any(
        c.startswith("install -Dm644 bge/bge-markdown-render.h") for c in commands()
    ), commands()


def test_it_runs_after_meson_install():
    """meson install would not remove it, but ordering after install keeps the
    workaround visibly a patch on top of upstream rather than part of it."""
    cmds = commands()
    install = next(i for i, c in enumerate(cmds) if c.startswith("meson install"))
    header = next(i for i, c in enumerate(cmds) if "bge-markdown-render.h" in c)
    assert header > install


def test_the_upstream_build_is_otherwise_untouched():
    cmds = [c for c in commands() if "bge-markdown-render.h" not in c]
    assert cmds == [
        "meson setup _flatpak_build --prefix=/app -Dbge_only=true",
        "meson compile -C _flatpak_build",
        "meson install -C _flatpak_build",
        "ln -sf bge-0.7.15.pc /app/lib/pkgconfig/libbge.pc",
    ], cmds


def test_the_reason_is_recorded_in_the_manifest():
    """Without it, the next reader sees an unexplained `install` line next to
    a meson build and deletes it as redundant."""
    assert "#25" in json.dumps(libbge())
