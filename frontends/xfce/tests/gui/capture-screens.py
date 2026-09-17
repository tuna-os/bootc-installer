#!/usr/bin/env python3
"""Render every wizard page to PNG, plus an animated walkthrough, for
docs/gui-walkthrough.md and the README.

Runs headless under Xvfb with no desktop, no GPU and no real disks: the app's
pages are built against fixtures, driven through the real InstallerWindow, and
grabbed from the X server.

Nothing here touches a disk. core.host_run — the single seam every hardware
query goes through — is replaced with canned lsblk output, so `candidate_disks`
sees a plausible machine that does not exist.

    xvfb-run -a python3 tests/gui/capture-screens.py [outdir]
"""

import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

# SAFETY INTERLOCK — set before ANY tuna_installer_xfce import, and first
# because this is the one line whose absence costs a disk rather than a
# screenshot. ProgressPage.on_enter() calls win.start_install() with no
# confirmation in between, so navigating this wizard to the progress page runs
# fisherman as root. core.dry_run() makes that a no-op that plays a transcript
# instead; the full reasoning is in tuna_installer_xfce/core.py, and the check
# that this actually took effect is further down.
os.environ.setdefault("TUNA_INSTALLER_DRY_RUN", "1")

# ── fixtures, installed BEFORE the app imports anything ──────────────────────

CATALOG = {
    "default_image": "ghcr.io/tuna-os/bonito:latest",
    "fallback_flatpaks": [],
    "images": [
        {
            "name": "TunaOS", "registry": "ghcr.io/tuna-os/bonito",
            "desc": "The default TunaOS image.",
            "bootloader": "systemd", "filesystem": "btrfs", "composefs": True,
            "children": [
                {"name": "GNOME", "tag": "latest",
                 "subtitle": "The standard desktop",
                 "desc": "A clean GNOME desktop. The best-tested option."},
                {"name": "KDE Plasma", "tag": "kde",
                 "subtitle": "More to configure",
                 "desc": "KDE Plasma, for a more customisable desktop."},
            ],
        },
        {
            "name": "Bluefin", "registry": "ghcr.io/ublue-os/bluefin",
            "desc": "Universal Blue's developer image.",
            "bootloader": "grub2", "filesystem": "xfs",
            "children": [
                {"name": "Bluefin", "tag": "latest",
                 "subtitle": "Developer-focused",
                 "desc": "Tracks upstream Universal Blue closely."},
            ],
        },
    ],
}

LSBLK = {
    "blockdevices": [
        {"name": "nvme0n1", "path": "/dev/nvme0n1", "size": 512110190592,
         "model": "SAMSUNG MZVL2512", "type": "disk", "rm": False,
         "mountpoints": [None], "tran": "nvme"},
        {"name": "sda", "path": "/dev/sda", "size": 2000398934016,
         "model": "WDC WD20SPZX", "type": "disk", "rm": False,
         "mountpoints": [None], "tran": "sata"},
    ]
}

_tmp = tempfile.mkdtemp(prefix="tuna-shots-")
_catalog_path = os.path.join(_tmp, "images.json")
with open(_catalog_path, "w") as fh:
    json.dump(CATALOG, fh)
os.environ["FISHERMAN_IMAGES_PATH"] = _catalog_path
os.environ.setdefault("XDG_RUNTIME_DIR", _tmp)
os.environ.setdefault("GTK_A11Y", "none")

# SAFETY, and not a small one. ProgressPage.on_enter() calls
# win.start_install(), so simply navigating the wizard to the progress page
# LAUNCHES A REAL INSTALL — there is no confirmation between the two. A capture
# script that drove pages the obvious way would try to partition the runner's
# disk.
#
# This used to be `InstallerWindow.start_install = lambda self, page: None`,
# applied before any page was shown. That protected THIS script and nothing
# else: a monkeypatch in one test file is invisible to anything driving the
# real binary, which is exactly what the live-ISO walkthrough harness in
# tuna-os/tunaOS does over a QEMU keyboard with no ability to patch anything.
#
# The interlock now lives in the app (core.dry_run(), honoured as the first
# statement of start_install), so it protects every caller. It is read at CALL
# time, so import order cannot defeat it — but the assignment stays up here
# above every import anyway, because the cost of being wrong about this is a
# disk rather than a screenshot.

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from tuna_installer_xfce import core  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parity_report  # noqa: E402


class _Result:
    def __init__(self, stdout): self.returncode, self.stdout, self.stderr = 0, stdout, ""


def _fake_host_run(argv, **kwargs):
    """Every hardware query in core goes through host_run, so one seam covers
    the lot. Anything unexpected returns empty rather than reaching the host."""
    if argv and argv[0] == "lsblk":
        return _Result(json.dumps(LSBLK))
    return _Result("")


core.host_run = _fake_host_run
core.live_iso_image = lambda: None
core.offline_stores = lambda: []

# Product branding is resolved from the host's os-release, so an unpinned
# capture is BRANDED BY THE RUNNER: on a GitHub ubuntu-24.04 box the wizard
# renders "Welcome to Ubuntu 24.04.4 LTS", and the main-branch job commits
# those PNGs into docs/. Pin it so the committed walkthrough is stable and
# says the family name, exactly as it did before branding became dynamic.
# On a real Skipjack ISO the same attributes read "Skipjack" instead.
core.PRODUCT_NAME = "TunaOS"

from tuna_installer_xfce.app import PAGE_ORDER, InstallerWindow  # noqa: E402,F401

# Guard on the guard, in the spirit of tuna-installer-cosmic's
# TUNA_BLANK_SELFTEST. The whole safety of this script rests on one check in
# another module, and the failure mode if it silently stops being read is not a
# broken screenshot — it is a partitioned runner disk. So refuse to show a
# single page unless the interlock is demonstrably live.
#
# It has already earned its keep: on the first attempt this fired in CI (run
# 31271258293) because the env var was set HERE, below the `from
# tuna_installer_xfce import core` above, while core evaluated it at import
# time. The guard turned an ordering mistake into a failed job instead of an
# install. core.dry_run() is now read at call time so that ordering cannot
# matter, and the assignment moved to the top of the file so it does not
# matter twice.
if not core.dry_run():
    sys.exit(
        "refusing to run: core.dry_run() is False, so navigating to the "
        "progress page would start a REAL install. TUNA_INSTALLER_DRY_RUN is "
        "set at the top of this file; if core no longer honours it, fix the "
        "interlock rather than this check."
    )

CAPTIONS = {
    "welcome": "What the assistant is about to do.",
    "source": "Choose an image to install.",
    "destination": "Choose the disk. Nothing is written yet.",
    "setup": "Filesystem and encryption.",
    "identity": "Your account and computer name.",
    "confirm": "The last screen before anything is written.",
    "progress": "The install, step by step.",
    "done": "Finished — restart into the new system.",
}


FIXTURE_LOG = """[1/9] Partitioning /dev/nvme0n1
  created EFI system partition (1.0 GiB, FAT32)
  created root partition (511.1 GiB)
[2/9] Formatting boot partitions
[3/9] Setting up encryption
  encryption: none
[4/9] Formatting root filesystem (btrfs)
[5/9] Mounting target at /mnt
[6/9] Installing image ghcr.io/tuna-os/bonito:latest
  pulling layers... 1.9 GiB
"""


def _seed_progress(page):
    """Fill the progress screen with a believable install in flight.

    append_log() also drives the step label and progress bar off the "[n/9]"
    prefixes, so feeding it real-shaped lines exercises the same code path a
    live install would.
    """
    for line in FIXTURE_LOG.splitlines(keepends=True):
        page.append_log(line)


def _settle():
    """Let GTK finish layout and drawing before the grab.

    Grabbing too early is the dangerous failure: it yields a valid PNG of a
    half-drawn or empty window, which looks like a screenshot and is not one.
    """
    for _ in range(200):
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if not Gtk.events_pending():
            break


def _grab(window):
    gdk_window = window.get_window()
    if gdk_window is None:
        return None
    width = gdk_window.get_width()
    height = gdk_window.get_height()
    return Gdk.pixbuf_get_from_window(gdk_window, 0, 0, width, height)


def _page_text(widget, acc=None):
    """Every string the page actually put in its widget tree.

    This is what the parity report matches tunaOS's screen keywords against.
    Reading the tree rather than OCRing the PNG is the whole reason this can
    run on a GPU-less runner: no tesseract, no recognition error, and it costs
    nothing on top of a capture we already do.

    It is read from the VISIBLE page only — walking the whole window would
    collect all eight pages' text at once and credit every screen on every
    frame, which is precisely the false-parity failure tunaOS's spec file
    warns about in its comments.
    """
    acc = [] if acc is None else acc
    if isinstance(widget, Gtk.Label):
        acc.append(widget.get_text() or "")
    elif isinstance(widget, Gtk.Button):
        acc.append(widget.get_label() or "")
    elif isinstance(widget, Gtk.TextView):
        buf = widget.get_buffer()
        acc.append(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False) or "")
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            _page_text(child, acc)
    return acc


def _audit(pixbuf, name):
    """Read the pixels back.

    A capture rig that asserts its PNGs merely EXIST will happily publish blank
    pages — that is not hypothetical, it happened in bootc-installer-asahi and
    shipped a settings screen that was a title over an empty page. So measure
    what only holds when the UI really drew: enough non-background pixels, and
    enough distinct colours that it is not one flat fill.
    """
    data = pixbuf.get_pixels()
    stride, chans = pixbuf.get_rowstride(), pixbuf.get_n_channels()
    w, h = pixbuf.get_width(), pixbuf.get_height()
    counts, samples, dark = {}, 0, 0
    luma_sum = luma_sq = 0
    for y in range(0, h, 3):
        row = y * stride
        for x in range(0, w, 3):
            i = row + x * chans
            px = (data[i], data[i + 1], data[i + 2])
            counts[px] = counts.get(px, 0) + 1
            samples += 1
            luma = (30 * px[0] + 59 * px[1] + 11 * px[2]) // 100
            luma_sum += luma
            luma_sq += luma * luma
            if luma < 160:
                dark += 1
    bg = max(counts.values()) / samples
    # Grayscale stddev, normalised 0..1 — the same "is the screen blank"
    # measure tunaOS's VM walkthrough takes with ImageMagick, computed here
    # from the pixels we are already visiting. Reported, never gating: the
    # thresholds below are this repo's and stay exactly as calibrated.
    mean = luma_sum / samples
    var = max(luma_sq / samples - mean * mean, 0.0)
    return {"name": name, "w": w, "h": h, "colours": len(counts),
            "background": bg, "ink": dark / samples,
            "stddev": (var ** 0.5) / 255.0}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "docs", "screenshots")
    os.makedirs(out, exist_ok=True)

    # Drop the generated files before capturing anything. The workflow uploads
    # this directory on always(), because a failed capture is exactly when the
    # pictures are worth looking at — but on a fresh checkout the directory
    # already holds the committed copies from the last green run. Without this,
    # a page that never grabs leaves its old PNG in place (the loop below
    # continues past it), and walkthrough.gif is only rebuilt past the failure
    # gate at the end, so a failed run's artifact ships the previous run's
    # animation. Both then read as evidence about this run, which is how a
    # capture bug gets diagnosed against the wrong image.
    for stale in os.listdir(out):
        if stale.endswith(".png") or stale == "walkthrough.gif":
            os.unlink(os.path.join(out, stale))

    app = Gtk.Application(application_id="org.tunaos.installer.xfce.shots")
    frames, findings = [], []

    def on_activate(_app):
        win = InstallerWindow(app)
        win.set_default_size(760, 560)
        win.show_all()
        _settle()
        for index, name in enumerate(PAGE_ORDER):
            # Drive the stack directly rather than through _enter(): _enter
            # fires on_enter() side effects, and on the progress page that is
            # the install itself. Nav state is refreshed explicitly instead.
            win.index = index
            win.stack.set_visible_child_name(name)
            win.trawl.set_step(index)
            if name == "progress":
                _seed_progress(win.pages["progress"])
            elif name == "done":
                win.pages["done"].set_result(True, "")
            elif name != "confirm":
                win.pages[name].on_enter()
            else:
                win.pages[name].on_enter()
            win.refresh_nav()
            _settle()
            pixbuf = _grab(win)
            if pixbuf is None:
                print(f"  !! no window for {name}", file=sys.stderr)
                continue
            path = os.path.join(out, f"{index + 1:02d}-{name}.png")
            pixbuf.savev(path, "png", [], [])
            frames.append(path)
            finding = _audit(pixbuf, name)
            finding["png"] = path
            visible = win.stack.get_visible_child()
            finding["text"] = " ".join(_page_text(visible)) if visible else ""
            findings.append(finding)
        win.destroy()
        app.quit()

    app.connect("activate", on_activate)
    app.run([])

    failures = []
    for f in findings:
        print(f"  {f['name']:12s} {f['w']}x{f['h']}  colours {f['colours']:5d}  "
              f"largest-flat {f['background']*100:5.1f}%  ink {f['ink']*100:5.1f}%")
        # A window that never drew is one flat colour: few distinct values and a
        # background occupying nearly everything.
        # Thresholds calibrated against MEASURED output, not guessed. The eight
        # real pages score:
        #     colours       196 - 303
        #     largest-flat  47.6% - 96.1%
        #     ink            0.6% -  3.5%
        # A window that never drew is one flat fill: a handful of colours and a
        # background at ~100%. The gaps below sit between those two worlds.
        #
        # The first version used 0.97 for largest-flat and failed a page that
        # had rendered perfectly — these are sparse wizard pages on a light
        # theme, so 96% background is normal, not broken. Guessing a threshold
        # and then reading the failure as a defect is how you end up "fixing"
        # working code.
        page_failures = []
        if f["colours"] < 60:
            page_failures.append(f"{f['name']}: only {f['colours']} distinct colours — did not render")
        if f["background"] > 0.985:
            page_failures.append(f"{f['name']}: {f['background']*100:.1f}% one flat colour — blank page")
        if f["ink"] < 0.003:
            page_failures.append(f"{f['name']}: {f['ink']*100:.2f}% ink — no text drawn")
        # Same verdict, same thresholds — just also recorded per page so the
        # parity report can say WHICH screen was blank instead of only how
        # many were.
        f["rendered"] = not page_failures
        failures.extend(page_failures)

    if len(findings) != len(PAGE_ORDER):
        failures.append(f"captured {len(findings)} of {len(PAGE_ORDER)} pages")

    # Emitted before the failure gate on purpose: a frontend that renders a
    # blank page is exactly the case the parity matrix most needs a row for.
    # Bailing out here would leave that frontend reading "_pending_" forever,
    # which is how the last three defects survived.
    parity_report.write_report(
        out, "xfce", findings,
        harness="tests/gui/capture-screens.py (GTK3 under Xvfb)")

    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1

    gif = os.path.join(out, "walkthrough.gif")
    subprocess.run(["convert", "-delay", "240", "-loop", "0", *frames, gif], check=True)
    print(f"  wrote {len(frames)} screens + {os.path.basename(gif)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
