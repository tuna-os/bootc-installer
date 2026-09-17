#!/usr/bin/env python3
"""Render every wizard page of ui/installer.qml to PNG, plus an animated
walkthrough, for docs/gui-walkthrough.md and the README.

The installer normally runs under Quickshell on a Wayland compositor, which is
why it has been effectively impossible to look at. This loads the SAME,
UNMODIFIED installer.qml under a plain Qt Quick runtime by supplying local stub
implementations of the two Quickshell modules it imports (tests/qml-stubs).

Nothing is spawned: the stubbed Process serves canned backend output. That is a
safety property, not a convenience — the real backend runs fisherman, which
partitions a disk.

    QT_QPA_PLATFORM=offscreen python3 tests/gui/capture-screens.py [outdir]
"""

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Qt Quick's scene graph wants a GL context; the software backend renders the
# same tree on the CPU, which is what a container with no DRM device needs.
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ["QML2_IMPORT_PATH"] = os.path.join(REPO, "tests", "qml-stubs")
os.environ["QML_IMPORT_PATH"] = os.environ["QML2_IMPORT_PATH"]

from PyQt6.QtCore import QUrl, QTimer, QEventLoop  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtQml import QQmlApplicationEngine  # noqa: E402
from PyQt6.QtQuick import QQuickWindow  # noqa: E402
from PyQt6 import sip  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parity_report  # noqa: E402

PAGES = [
    ("01-welcome", 0, "What the installer is about to do."),
    ("02-disk", 1, "Choose the target disk."),
    ("03-encryption", 2, "Encryption choice."),
    ("04-confirm", 3, "The last screen before anything is written."),
    ("05-progress", 4, "The install, with live log."),
    ("06-done", 5, "Finished."),
]

FIXTURE_LOG = "\n".join([
    "[1/9] Partitioning /dev/nvme0n1",
    "[2/9] Formatting boot partitions",
    "[3/9] Setting up encryption",
    "[4/9] Formatting root filesystem (xfs)",
    "[5/9] Mounting target at /mnt",
    "[6/9] Installing image ghcr.io/tuna-os/albacore:gnome",
    "  pulling layers... 1.9 GiB",
])


def settle(ms=250):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def audit(image, name):
    """Read the pixels back.

    A capture that only checks its PNGs exist will publish blank pages: the
    files are present, non-empty, and empty. Qt Quick makes that especially
    easy — grab before the first frame and you get a valid image of nothing.
    """
    w, h = image.width(), image.height()
    counts, samples, ink = {}, 0, 0
    luma_sum = luma_sq = 0
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            c = image.pixel(x, y) & 0xFFFFFF
            counts[c] = counts.get(c, 0) + 1
            samples += 1
            r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
            luma = (30 * r + 59 * g + 11 * b) // 100
            luma_sum += luma
            luma_sq += luma * luma
            if luma > 60:
                ink += 1  # the theme is near-black, so "ink" is the LIGHT pixels
    # Grayscale stddev, normalised 0..1 — the same "is the screen blank"
    # measure tunaOS's VM walkthrough takes with ImageMagick, computed from
    # the pixels we already visit. Reported only; the thresholds below are
    # this repo's and are unchanged.
    mean = luma_sum / samples
    var = max(luma_sq / samples - mean * mean, 0.0)
    return {"name": name, "w": w, "h": h, "colours": len(counts),
            "flat": max(counts.values()) / samples, "ink": ink / samples,
            "stddev": (var ** 0.5) / 255.0}


def page_text(item, acc=None):
    """Every string the CURRENTLY VISIBLE page put in the QML scene.

    This is what the parity report matches tunaOS's screen keywords against.
    Reading the scene graph instead of OCRing the PNG is what lets this run
    with no tesseract and no GPU, and it cannot misread a glyph.

    Visibility is the whole trick. `installer.qml` builds all six pages up
    front inside a StackLayout, so a naive walk of the tree collects every
    page's text on every frame and credits every screen everywhere — the
    exact false-parity failure tunaOS's spec file warns about. QQuickItem's
    `visible` is EFFECTIVE visibility (a child of a hidden page reports
    False), so pruning on it isolates one page.
    """
    acc = [] if acc is None else acc
    for child in item.childItems():
        if not child.isVisible():
            continue
        text = child.property("text")
        if isinstance(text, str) and text.strip():
            acc.append(text)
        page_text(child, acc)
    return acc


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "docs", "screenshots")
    os.makedirs(out, exist_ok=True)

    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(os.path.join(REPO, "ui", "installer.qml")))
    if not engine.rootObjects():
        print("FAIL: installer.qml did not load — see QML errors above", file=sys.stderr)
        return 1

    root = engine.rootObjects()[0]
    # PyQt wraps the root as a bare QWindow because it has no binding for
    # QQuickApplicationWindow. The cast is what exposes grabWindow().
    window = sip.cast(root, QQuickWindow)
    settle(500)

    frames, findings = [], []
    for name, page, _caption in PAGES:
        root.setProperty("currentPage", page)
        if page == 4:
            root.setProperty("installLog", FIXTURE_LOG)
        if page == 5:
            root.setProperty("installSuccess", True)
        settle(300)
        image = window.grabWindow()
        path = os.path.join(out, f"{name}.png")
        image.save(path)
        frames.append(path)
        finding = audit(image, name)
        finding["png"] = path
        finding["text"] = " ".join(page_text(window.contentItem()))
        findings.append(finding)

    failures = []
    for f in findings:
        print(f"  {f['name']:14s} {f['w']}x{f['h']}  colours {f['colours']:5d}  "
              f"largest-flat {f['flat']*100:5.1f}%  ink {f['ink']*100:5.1f}%")
        page_failures = []
        if f["colours"] < 20:
            page_failures.append(f"{f['name']}: {f['colours']} colours — did not render")
        if f["flat"] > 0.995:
            page_failures.append(f"{f['name']}: {f['flat']*100:.1f}% one flat colour — blank")
        if f["ink"] < 0.002:
            page_failures.append(f"{f['name']}: {f['ink']*100:.2f}% lit pixels — nothing drawn")
        # Same verdict, same thresholds — recorded per page as well, so the
        # parity report can name WHICH screen was blank rather than only how
        # many were.
        f["rendered"] = not page_failures
        failures.extend(page_failures)

    # Emitted before the failure gate on purpose: a frontend that renders a
    # blank page is exactly the case tunaOS's parity matrix most needs a row
    # for. Bailing out first would leave niri reading "_GPU_" forever, which
    # is how the last crop of defects survived unseen.
    parity_report.write_report(
        out, "niri", findings,
        harness="tests/gui/capture-screens.py (QML via PyQt6, offscreen)")

    if failures:
        for m in failures:
            print(f"FAIL: {m}", file=sys.stderr)
        return 1

    gif = os.path.join(out, "walkthrough.gif")
    subprocess.run(["convert", "-delay", "240", "-loop", "0", *frames, gif], check=True)
    print(f"  wrote {len(frames)} screens + {os.path.basename(gif)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
