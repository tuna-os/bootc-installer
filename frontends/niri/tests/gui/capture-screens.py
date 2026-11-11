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

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Qt Quick's scene graph wants a GL context; the software backend renders the
# same tree on the CPU, which is what a container with no DRM device needs.
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ["QML2_IMPORT_PATH"] = os.path.join(REPO, "tests", "qml-stubs")
os.environ["QML_IMPORT_PATH"] = os.environ["QML2_IMPORT_PATH"]

from PyQt6.QtCore import (QUrl, QTimer, QEventLoop, QMetaObject, Q_ARG,  # noqa: E402
                          QObject, QVariant, QPointF, QRect, QRectF, QSizeF)
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtQml import QQmlApplicationEngine  # noqa: E402
from PyQt6.QtQuick import QQuickWindow  # noqa: E402
from PyQt6 import sip  # noqa: E402

# The screen contract, the pixel audit and the capture fixtures live once, in
# shared/walkthrough/, for every frontend.
SHARED_WALKTHROUGH = os.path.normpath(os.path.join(REPO, "..", "..", "shared", "walkthrough"))
sys.path.insert(0, SHARED_WALKTHROUGH)
import capture_fixtures  # noqa: E402
import parity_report  # noqa: E402
import pixel_audit  # noqa: E402

PAGES = [
    ("01-welcome", 0, "What the installer is about to do."),
    ("02-session", 1, "Live-session keyboard, language, timezone and network."),
    ("03-source", 2, "What to install: live system or a catalog image."),
    ("04-disk", 3, "Choose the target disk."),
    ("05-encryption", 4, "Encryption and filesystem choice."),
    ("06-account", 5, "The account the install creates."),
    ("07-confirm", 6, "The last screen before anything is written."),
    ("08-progress", 7, "The install, with live log."),
    ("09-done", 8, "Finished."),
    ("10-recovery", 8, "A TPM install: the recovery key, and restart held "
                       "until it is acknowledged."),
    ("11-tour", 8, "The selected image's tour slides."),
    ("12-cancel-confirm", 7, "Cancel asks first: the install continues "
                             "until the user confirms."),
    ("13-cancelled", 8, "The end of an install that the user cancelled."),
    ("14-offline", 2, "An image that needs a download, and no network: "
                      "Continue is held."),
]

# The button that leaves each step, by frame.
NEXT_BUTTONS = {"02-session": "sessionNextButton", "03-source": "sourceNextButton",
                "04-disk": "diskNextButton", "05-encryption": "encryptionNextButton",
                "06-account": "accountNextButton", "07-confirm": "confirmInstallButton",
                "14-offline": "sourceNextButton"}

# The account page's fields, filled the way a user would leave them: the
# account frame shows them, and the confirm frame names the user. Neutral
# values; the passwords are dots on screen.
ACCOUNT = {"username": "alex", "fullname": "Alex Example",
           "userPassword": "capture", "userPasswordConfirm": "capture"}

# Pages by role, so the checks below do not hard-code positions twice.
PROGRESS_PAGE = 7
DONE_PAGE = 8

# The recovery event is synthesised (no CI runner does a TPM install), but it
# goes in through appendLog(), the function a real install calls, so this
# frame exercises the parse rather than a property assignment that would keep
# passing if the parse broke.
RECOVERY_EVENT = capture_fixtures.RECOVERY_EVENT

# The install screen, caught in flight: fisherman's real newline-delimited
# JSON transcript (shared/progress/), truncated part-way through the image
# pull so the bar sits mid-way rather than at either end.
#
# This was seven hand-written "[n/9] " lines naming a specific image ref, and
# it was assigned straight to the `installLog` property — so the capture
# painted text into the log pane and never called appendLog() at all. The bar
# and the step caption were therefore never exercised by this harness in
# either direction, while docs/PARITY.md credited this frontend with a
# working progress bar. (fisherman does not emit that prefix, so the parser
# it was feeding could not have matched it anyway.)
#
# Naming a product in a fixture was the second problem: it put that product's
# image ref into the rendered docs for everyone who rebrands this installer.
fixture_lines = capture_fixtures.fixture_log

_PROBE_EXPECTED = os.path.join(REPO, "..", "..", "shared", "probe", "fixtures",
                               "laptop.expected.json")



CAPTURE_CATALOG = os.path.join(SHARED_WALKTHROUGH, "capture-catalog.json")


def capture_leaves(offline_images):
    """{imgref: leaf} in the shape `catalog` prints (installer/catalog.go)
    for shared/walkthrough/capture-catalog.json. The leaves come from the
    reference reader (shared/catalog/resolve.py), which the backend's own
    test holds to the same fixture; the node's words and tour come from the
    node, as the backend reads them."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("shared_catalog_resolve", os.path.join(
        SHARED_WALKTHROUGH, "..", "catalog", "resolve.py"))
    resolve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resolve)
    catalog = resolve.load(CAPTURE_CATALOG)
    nodes = {}

    def walk(items, registry, carousel):
        for node in items:
            registry_here = node.get("registry", registry)
            carousel_here = node.get("carousel", carousel)
            if node.get("imgref"):
                nodes[node["imgref"]] = (node, carousel_here)
            elif node.get("tag"):
                nodes[f"{registry_here}:{node['tag']}"] = (node, carousel_here)
            walk(node.get("children") or [], registry_here, carousel_here)

    walk(catalog["images"], "", [])
    out = {}
    for leaf in resolve.leaves(catalog):
        node, carousel = nodes[leaf["imgref"]]
        shown = dict(leaf, desc=node.get("desc", ""),
                     carousel=[dict({"image": ""}, **slide) for slide in carousel])
        shown["recipe"] = resolve.recipe_fragment(leaf, offline_images=offline_images)["recipe"]
        out[leaf["imgref"]] = shown
    return out

def find_item(root, name):
    """The QQuickItem with this objectName, searched down the VISUAL tree.

    findChild() walks the QObject tree, which does not reach items a QML
    component parents visually rather than by ownership — the sibling KDE
    harness reported its progress bar missing on a screen that was rendering
    beside it for exactly that reason. childItems() is what "on the screen"
    means.
    """
    if root is None:
        return None
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = find_item(child, name)
        if found is not None:
            return found
    return None


def assert_progress_bar_drawn(window, image, out=sys.stderr):
    """Is the progress bar's filled part actually on the screen?

    The pixel audit cannot answer this and was never meant to: it measures ink
    over the whole frame, and the install screen supplies plenty from the log
    text alone. The KDE frontend shipped a bar that laid out at full width,
    reported itself visible and opaque, and painted nothing — and passed every
    check in this repository, its capture job included, because a page with a
    populated log looks populated either way.

    This frontend is the one whose harness used to set `installLog` directly
    instead of calling appendLog(), so its bar was never exercised here at
    all. That is fixed; this stops it coming back.
    """
    fill = find_item(window.contentItem(), "installProgressFill")
    if fill is None:
        print("FAIL: no item named installProgressFill in the visual tree",
              file=out)
        return False

    track = fill.parentItem()
    share = fill.width() / track.width() if track and track.width() > 0 else 0.0
    print(f"    bar fill: {fill.width():.0f}x{fill.height():.0f} "
          f"({share:.1%} of track) visible={fill.isVisible()} "
          f"opacity={fill.opacity():.2f}", file=out)

    if fill.width() <= 0 or fill.height() <= 0 or not fill.isVisible():
        print("FAIL: the progress bar's fill has no drawable geometry", file=out)
        return False

    scale = image.width() / window.width()
    top_left = fill.mapToScene(QPointF(0, 0)) * scale
    rect = QRectF(top_left,
                  QSizeF(fill.width() * scale, fill.height() * scale)).toRect()
    rect = rect.intersected(QRect(0, 0, image.width(), image.height()))
    if rect.isEmpty():
        print("FAIL: the progress bar's fill maps to no pixels", file=out)
        return False

    background = image.pixel(2, 2)
    ink = sum(
        1
        for y in range(rect.top(), rect.bottom() + 1)
        for x in range(rect.left(), rect.right() + 1)
        if image.pixel(x, y) != background
    )
    if ink == 0:
        print(f"FAIL: the progress bar's fill covers {rect.width()}x"
              f"{rect.height()} pixels and every one is the page background "
              "— it is laid out but not painted", file=out)
        return False
    return True


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
    # Every fourth pixel, and the theme is near-black, so "ink" is the LIGHT
    # pixels. `stddev` is the same "is the screen blank" measure tunaOS's VM
    # walkthrough takes with ImageMagick: reported only; the thresholds in
    # main() are this repo's and are unchanged.
    return {"name": name, "w": image.width(), "h": image.height(),
            **pixel_audit.qimage_stats(image, step=4,
                                       ink=lambda luma: luma > 60)}


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

    # The disks every frontend's capture shows: shared/probe/fixtures/laptop,
    # as fisherman's probe renders it (shared/probe/README.md) -- the exact
    # shape the backend's discover-disks prints, which installer/probe_test.go
    # pins against the same file. The pages are set directly, so the QML's
    # own discover-disks call never runs here.
    with open(_PROBE_EXPECTED, encoding="utf-8") as fh:
        probed = json.load(fh)
    root.setProperty("disks", probed["disks"])
    root.setProperty("disksProbed", True)
    root.setProperty("selectedDisk", probed["disks"][0])
    root.setProperty("hasTpm", probed["tpm_usable"])
    # The gate photographed on purpose: the fixture meets every requirement,
    # so the welcome frame would never show the blocking dialog the wizard
    # now puts up. RAM/CPU keep a "Continue anyway" path; UEFI would not.
    root.setProperty("unmet", ["ram", "cpu"])
    # The encryption choices the backend's `detect` reports: its embedded
    # copy of fisherman's encryption-choices.json.
    with open(os.path.join(REPO, "installer", "encryption-choices.json"), encoding="utf-8") as fh:
        root.setProperty("encryptionChoices", json.load(fh)["choices"])
    # The catalog the backend's `catalog` reports for the capture catalog
    # of every harness (shared/walkthrough/capture-catalog.json), joined
    # here against the probe's offline images the way the Source step does.
    # Stable and Beta are in the fixture's offline_images, so both rows read
    # "available offline"; Edge needs a download.
    leaves = capture_leaves(probed["offline_images"])
    STABLE, BETA, EDGE = (leaves[f"ghcr.io/example/os:{tag}"] for tag in ("stable", "beta", "edge"))
    # The leaf that ships tour slides.
    TOUR = next(leaf for leaf in leaves.values() if leaf["carousel"])
    CATALOG = {"path": "/etc/bootc-installer/images.json", "skipped": [],
               "default_image": "", "selected": "", "leaves": list(leaves.values()),
               "machine": {"has_nvidia": False, "is_live": False,
                           "offline_images": probed["offline_images"]},
               "live_leaf": None, "live_needs_user_creation": True}
    root.setProperty("offlineImages", probed["offline_images"])
    root.setProperty("netConnected", True)
    root.setProperty("netChecked", True)

    def call(method, *args):
        QMetaObject.invokeMethod(root, method, *[Q_ARG(QVariant, a) for a in args])

    def answer_netcheck(connected):
        """Replace the answer of the wizard's `netcheck` Process (the stub
        in tests/qml-stubs): what the backend would print on this machine."""
        for obj in root.findChildren(QObject):
            command = obj.property("command")
            command = command.toVariant() if hasattr(command, "toVariant") else command
            if command and "netcheck" in list(command):
                obj.setProperty("fixtures", {"netcheck": json.dumps(
                    {"connected": connected, "target": "", "tried": []})})
                return
        print("FAIL: the wizard has no netcheck Process", file=sys.stderr)
        sys.exit(1)

    def item(name):
        found = find_item(window.contentItem(), name)
        if found is None:
            print(f"FAIL: no item named {name} in the visual tree", file=sys.stderr)
            sys.exit(1)
        return found

    def process(subcommand):
        """The wizard's Process (the stub) that runs this backend subcommand."""
        for obj in root.findChildren(QObject):
            command = obj.property("command")
            command = command.toVariant() if hasattr(command, "toVariant") else command
            if command and subcommand in list(command):
                return obj
        print(f"FAIL: the wizard has no {subcommand} Process", file=sys.stderr)
        sys.exit(1)

    # #291, the Session step. On live media, with a current keyboard layout
    # that the host's list does not have ("us,de": localectl reports the X11
    # layout, list-keymaps does not), the field must show THAT value, and
    # Continue must send nothing and move on.
    root.setProperty("isLive", True)
    root.setProperty("keyboardLayouts", ["de", "us"])
    root.setProperty("keyboardLayout", "us,de")
    root.setProperty("localeList", ["de_DE.UTF-8", "en_US.UTF-8"])
    root.setProperty("localeName", "en_US.UTF-8")
    root.setProperty("timezoneList", ["UTC", "Europe/Berlin"])
    root.setProperty("timezoneName", "")
    root.setProperty("currentPage", 1)
    settle(200)
    shown = item("sessionKeyboard").property("editText")
    if shown != "us,de":
        print(f"FAIL: the keyboard field shows {shown!r}, not the session's "
              "own 'us,de' (#291: entry 0 was shown, then applied)", file=sys.stderr)
        return 1
    if item("sessionTimezone").property("editText") != "":
        print("FAIL: an unknown time zone shows an entry of the list", file=sys.stderr)
        return 1
    setter = process("session-set")
    call("advance")
    settle(200)
    if root.property("currentPage") != 2 or setter.property("written"):
        print(f"FAIL: Continue with nothing changed went to page "
              f"{root.property('currentPage')} and sent {setter.property('written')!r}",
              file=sys.stderr)
        return 1
    # One field changed: only that field is sent. The backend fails (no
    # systemd-localed, a polkit denial): a warning, and the wizard moves on.
    root.setProperty("currentPage", 1)
    item("sessionTimezone").setProperty("editText", "Europe/Berlin")
    setter.setProperty("exitCode", 1)
    call("advance")
    settle(200)
    sent = json.loads(setter.property("written") or "{}")
    if sent != {"timezone": "Europe/Berlin"}:
        print(f"FAIL: session-set was sent {sent!r}, not the one changed field",
              file=sys.stderr)
        return 1
    if root.property("currentPage") != 2 or not root.property("sessionWarning"):
        print("FAIL: a failed session-set did not move on with a warning "
              "(#291: the wizard stopped on step 2)", file=sys.stderr)
        return 1
    # Off live media nothing is sent, whatever the fields say.
    setter.setProperty("exitCode", 0)
    setter.setProperty("written", "")
    root.setProperty("isLive", False)
    root.setProperty("sessionFailed", False)
    root.setProperty("currentPage", 1)
    call("advance")
    settle(200)
    if root.property("currentPage") != 2 or setter.property("written"):
        print("FAIL: off live media the Session step sent settings to the host",
              file=sys.stderr)
        return 1
    root.setProperty("currentPage", 0)

    # #289: a catalog whose default the branding and the catalog do not name
    # selects NOTHING, and Continue on the Source step is held until the
    # user picks a row. The first row is never chosen for them.
    call("loadCatalog", CATALOG)
    root.setProperty("catalogLoaded", True)
    root.setProperty("currentPage", 2)
    settle(200)
    if root.property("sourceReady") or item("sourceNextButton").property("enabled"):
        print("FAIL: an image is selected, or Continue is live, with no "
              "default_image in the branding or the catalog (#289)", file=sys.stderr)
        return 1
    # The catalog names one: that leaf is the selection at the start, with
    # its filesystem and its choices.
    call("loadCatalog", dict(CATALOG, default_image=STABLE["imgref"],
                             selected=STABLE["imgref"]))
    settle(200)
    chosen = root.property("selectedLeaf")
    chosen = chosen.toVariant() if hasattr(chosen, "toVariant") else chosen
    if not chosen or chosen.get("imgref") != STABLE["imgref"]:
        print("FAIL: the catalog's default_image is not the selection", file=sys.stderr)
        return 1
    if root.property("filesystem") != "btrfs" or not item("sourceNextButton").property("enabled"):
        print("FAIL: the selected leaf's filesystem was not applied, or "
              "Continue is held with a selection", file=sys.stderr)
        return 1
    # A different leaf brings its own filesystem; the one before is not kept.
    call("selectLeaf", BETA)
    if root.property("filesystem") != "ext4" or root.property("needsUserCreation"):
        print("FAIL: selecting another leaf kept the old filesystem or the "
              "old account flag", file=sys.stderr)
        return 1
    call("selectLeaf", STABLE)
    root.setProperty("currentPage", 0)
    # The preflight's answer: lists from the host tools, connectivity up.
    root.setProperty("keyboardLayouts", ["us", "de"])
    root.setProperty("keyboardLayout", "us")
    root.setProperty("localeList", ["en_US.UTF-8", "de_DE.UTF-8"])
    root.setProperty("localeName", "en_US.UTF-8")
    root.setProperty("timezoneList", ["UTC", "Europe/Berlin"])
    root.setProperty("timezoneName", "Europe/Berlin")
    root.setProperty("netConnected", True)
    root.setProperty("sessionLoaded", True)
    # The persistent log `detect` names next to the progress page's copy.
    root.setProperty("logPath", "/home/user/.local/state/tuna-installer/install.log")
    for prop, value in ACCOUNT.items():
        root.setProperty(prop, value)
    if not root.property("accountReady"):
        print("FAIL: the filled account page still holds Continue", file=sys.stderr)
        return 1
    # #295: the passwords are hidden until the reveal toggle is used, and a
    # mismatch holds Continue.
    # displayText is what the field draws: dots, or the text itself.
    secret = ACCOUNT["userPassword"]
    hidden = item("accountPassword").property("displayText")
    root.setProperty("showPassword", True)
    shown = (item("accountPassword").property("displayText"),
             item("accountPasswordConfirm").property("displayText"))
    root.setProperty("showPassword", False)
    if hidden == secret or shown != (secret, secret):
        print("FAIL: the reveal toggle does not show the two password "
              "fields, or they are readable without it (#295)", file=sys.stderr)
        return 1
    root.setProperty("userPasswordConfirm", "different")
    if root.property("accountReady"):
        print("FAIL: Continue is live with two different passwords", file=sys.stderr)
        return 1
    root.setProperty("userPasswordConfirm", ACCOUNT["userPasswordConfirm"])

    frames, findings = [], []
    for name, page, _caption in PAGES:
        root.setProperty("currentPage", page)
        # The tour overlay is independent of the page: open it over the
        # done screen with the leaf that ships slides selected.
        if name == "11-tour":
            root.setProperty("selectedLeaf", TOUR)
            root.setProperty("tourIndex", 0)
            root.setProperty("tourOpen", True)
        else:
            root.setProperty("tourOpen", False)
        if name == "08-progress":
            # Through appendLog(), the function a real install calls — so the
            # bar, the step caption and the log rendering are all the live
            # code path. Assigning installLog directly, as this used to, is
            # how a screen can be "captured" without running any of it.
            for line in fixture_lines():
                QMetaObject.invokeMethod(root, "appendLog",
                                         Q_ARG(QVariant, line))
            # The fill has `Behavior on width { NumberAnimation }`, so it
            # arrives at its final width over a few hundred milliseconds.
            # Grabbing on the usual 300ms settle can catch it part-way and
            # photograph a bar narrower than the install really is.
            settle(700)
        if page == DONE_PAGE:
            root.setProperty("installSuccess", name != "13-cancelled")
        # #299: Cancel asks first. The overlay is over the install page, and
        # the install is not stopped by opening it.
        root.setProperty("cancelOpen", name == "12-cancel-confirm")
        if name == "13-cancelled":
            # fisherman's exit code for a cancelled install, through the
            # function the install Process's exit calls.
            root.setProperty("recoveryKey", "")
            QMetaObject.invokeMethod(root, "installExited", Q_ARG(QVariant, 130))
        if name == "14-offline":
            # #301: the selected image is not on the media and the check
            # says there is no network.
            # The answer comes from the wizard's own `netcheck` Process
            # (the stub's, replaced here by an offline one), so the frame
            # exercises the check and not a property assignment.
            answer_netcheck(False)
            call("selectLeaf", EDGE)
            settle(600)  # the check's pause, then the stub's answer
        if name == "10-recovery":
            QMetaObject.invokeMethod(root, "appendLog",
                                     Q_ARG(QVariant, RECOVERY_EVENT))
            if not root.property("recoveryKey"):
                print("  !! the recovery_key event did not parse",
                      file=sys.stderr)
                sys.exit(1)
        settle(300)
        image = window.grabWindow()
        path = os.path.join(out, f"{name}.png")
        image.save(path)
        frames.append(path)

        # The install screen is the one with a progress bar, and a bar that
        # lays out but paints nothing is invisible to the pixel audit. Fail
        # rather than publish a documentation image of a bar that is not
        # there.
        if page == PROGRESS_PAGE and not assert_progress_bar_drawn(window, image):
            sys.exit(1)
        finding = audit(image, name)
        finding["png"] = path
        finding["text"] = " ".join(page_text(window.contentItem()))

        # The account step's purpose is the user block; the confirm screen
        # is where the user checks it before anything is written.
        if name in ("06-account", "07-confirm") and ACCOUNT["username"] not in finding["text"]:
            print(f"  !! the username is not on {name}", file=sys.stderr)
            sys.exit(1)

        # The button that moves the wizard on must be ON the screen. The
        # encryption page used to be taller than the window, and because all
        # pages share one stack, that pushed Back, Continue and the hint bar
        # below the bottom edge on EVERY step: each frame looked fine and
        # none of them could be left with the mouse.
        if name in NEXT_BUTTONS:
            button = item(NEXT_BUTTONS[name])
            bottom = button.mapToScene(QPointF(0, button.height())).y()
            if not button.isVisible() or bottom > window.height():
                print(f"  !! {NEXT_BUTTONS[name]} is not on the screen on {name} "
                      f"(bottom edge at {bottom:.0f} of {window.height()})",
                      file=sys.stderr)
                sys.exit(1)

        if name == "03-source":
            # A flat list of a full catalog: each row is the breadcrumb
            # (product and channel), never a bare channel name, and the
            # filter box is there.
            if STABLE["breadcrumb"] not in finding["text"] or not item("sourceSearch").isVisible():
                print("  !! the Source step shows no product in its rows, "
                      "or has no filter box (#289)", file=sys.stderr)
                sys.exit(1)
        if name == "12-cancel-confirm":
            if (not item("cancelConfirmButton").isVisible()
                    or root.property("cancelRequested")):
                print("  !! Cancel did not ask first (#299)", file=sys.stderr)
                sys.exit(1)
        if name == "13-cancelled":
            with open(os.path.join(REPO, "installer", "copy-defaults.json"),
                      encoding="utf-8") as fh:
                copy = json.load(fh)
            title = item("doneTitle").property("text")
            if title != copy["done_cancelled_title"] or copy["done_failed_title"] in finding["text"]:
                print(f"  !! exit code 130 shows {title!r}, not the copy line "
                      "done_cancelled_title (#299)", file=sys.stderr)
                sys.exit(1)
            # After a confirmed cancel a killed wrapper (128 + SIGTERM) is a
            # cancelled install too; with no cancel, a failure stays a failure.
            root.setProperty("cancelRequested", True)
            QMetaObject.invokeMethod(root, "installExited", Q_ARG(QVariant, 143))
            cancelled = item("doneTitle").property("text")
            root.setProperty("cancelRequested", False)
            QMetaObject.invokeMethod(root, "installExited", Q_ARG(QVariant, 1))
            failed = item("doneTitle").property("text")
            if cancelled != copy["done_cancelled_title"] or failed != copy["done_failed_title"]:
                print(f"  !! after a confirmed cancel the page reads {cancelled!r}; "
                      f"a plain failure reads {failed!r} (#299)", file=sys.stderr)
                sys.exit(1)
        if name == "14-offline":
            if item("sourceNextButton").property("enabled") or not item("offlineRecheck").isVisible():
                print("  !! offline with an image that needs a download, and "
                      "Continue is live or there is no Recheck (#301)",
                      file=sys.stderr)
                sys.exit(1)
            # An image that is on the media needs no network.
            call("selectLeaf", STABLE)
            settle(600)
            if root.property("netConnected") or not item("sourceNextButton").property("enabled"):
                print("  !! an offline image is held by the network gate",
                      file=sys.stderr)
                sys.exit(1)
            # The network comes back: Recheck lets the download through.
            call("selectLeaf", EDGE)
            answer_netcheck(True)
            call("recheckNetwork")
            settle(600)
            if not item("sourceNextButton").property("enabled"):
                print("  !! Continue stays held after the network came back",
                      file=sys.stderr)
                sys.exit(1)

        # The recovery frame is the one screen where a correct-looking render
        # can still be wrong: the panel can draw without the key in it, and
        # Restart can be live before the acknowledgement. Neither shows up in
        # a pixel histogram.
        if name == "10-recovery":
            key = root.property("recoveryKey")
            if key not in finding["text"]:
                print("  !! the recovery key is not in the rendered text — "
                      "the panel did not draw (#129)", file=sys.stderr)
                sys.exit(1)
            # The key alone is not enough. On the first run of this frame
            # every LABEL was empty -- installer.qml keeps its own copy of
            # the contract defaults and had not been given the recovery
            # keys -- and the check still passed, because the key is set
            # from the event rather than from the copy table. Assert on a
            # contract-sourced string too, or this frame photographs a
            # panel of blank buttons and calls it covered.
            # Read from the canonical contract, not from the QML: that is
            # what makes this catch drift between installer.qml's own copy
            # table and shared/branding/copy-defaults.json.
            # REPO is frontends/niri; the contract lives two levels up.
            contract_path = os.path.join(
                os.path.dirname(os.path.dirname(REPO)),
                "shared", "branding", "copy-defaults.json")
            if not os.path.exists(contract_path):
                print("  .. shared/branding is absent; this tree is checked "
                      "out without the monorepo, so the copy-table check is "
                      "skipped", file=sys.stderr)
                findings.append(finding)
                continue
            with open(contract_path) as fh:
                contract = json.load(fh)
            for key in ("recovery_key_title", "recovery_key_ack",
                        "recovery_key_copy"):
                want = contract[key]
                if want not in finding["text"]:
                    print(f"  !! {key} is not in the rendered text. The copy "
                          "table in installer.qml is a hand-written duplicate "
                          "of copy-defaults.json and nothing enforces it; a "
                          "key added to the contract and not to that table "
                          "renders as an empty string (#129).",
                          file=sys.stderr)
                    sys.exit(1)
            restart = find_item(window.contentItem(), "doneRestartButton")
            if restart is None:
                print("  !! no doneRestartButton in the visual tree",
                      file=sys.stderr)
                sys.exit(1)
            if restart.property("enabled"):
                print("  !! Restart is live before the recovery key was "
                      "acknowledged (#129)", file=sys.stderr)
                sys.exit(1)

        findings.append(finding)

    # Runtime regression for the same portable file-logo contract as every
    # frontend. PNG avoids depending on a platform's optional SVG plugin.
    from PyQt6.QtGui import QColor, QImage
    logo_path = os.path.join(out, "fixture logo #1.png")
    logo = QImage(32, 32, QImage.Format.Format_ARGB32)
    logo.fill(QColor("#13b97d"))
    assert logo.save(logo_path)
    root.setProperty("branding", {
        "name": "Example Fork", "logoKind": "file",
        "logoValue": QUrl.fromLocalFile(os.path.abspath(logo_path)).toString(),
    })
    root.setProperty("recoveryKey", "")
    # The capture fixture leaves ram+cpu unmet so the screenshots show the
    # blocking gate dialog on welcome. Dismiss it here: the grabs below
    # photograph the logo, and the dialog would cover it.
    root.setProperty("gatesAccepted", True)
    # The tour overlay is page-independent: the main loop above leaves it open
    # on the last leaf, and it would cover the logo the same way.
    root.setProperty("tourOpen", False)
    for page, name in [(0, "welcomeBrandingLogo"), (DONE_PAGE, "doneBrandingLogo")]:
        root.setProperty("currentPage", page)
        root.setProperty("installSuccess", True)
        settle(300)
        item = find_item(window.contentItem(), name)
        assert item is not None and item.property("visible"), name + " failed to decode"
        image = window.grabWindow()
        image.save(os.path.join(out, "branding-" + str(page) + ".png"))
        assert any(image.pixelColor(x, y).name() == "#13b97d"
                   for y in range(image.height()) for x in range(image.width())), "logo pixels missing"
    root.setProperty("installSuccess", False)
    settle(100)
    assert not find_item(window.contentItem(), "doneBrandingLogo").property("visible")
    root.setProperty("branding", {"name": "Example Fork", "logoKind": "file",
                                  "logoValue": "file:///nonexistent/branding-logo.png"})
    root.setProperty("currentPage", 0)
    settle(100)
    assert not find_item(window.contentItem(), "welcomeBrandingLogo").property("visible")

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
    capture_fixtures.write_gif(frames, gif)
    print(f"  wrote {len(frames)} screens + {os.path.basename(gif)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
