#!/usr/bin/env python3
"""End to end: the Niri wizard's recipe, through the real Go backend, into
fisherman.

The chain on a real machine is QML -> `tuna-installer-niri install` (recipe
on stdin) -> `pkexec /usr/local/bin/fisherman -` (recipe on stdin again;
`sudo -n` on live media). Quickshell cannot run headless, so the QML is
loaded under PyQt6 with the stub modules from tests/qml-stubs and walked the
way a user walks it: Source, Disk, Encryption, Account, Confirm, Install.
The stub Process records what the QML wrote to the backend's stdin instead
of spawning it. That exact byte string is then piped to the REAL backend
binary, which pipes it on to fisherman (shared/e2e/setup.sh's validating
shim) and streams its output.

The catalog is shared/e2e/catalog.json, read by the REAL backend (`catalog`):
the image the wizard starts on is the branding's default_image, and its
recipe keys are the backend's. The driver copies that catalog to
<e2e dir>/catalog.json, so shared/e2e/check-recipe.py can hold the recipe's
account to the catalog (shared/catalog/README.md).

    python3 tests/e2e/run.py            # after: cd installer && go build -o tuna-installer-niri .
"""
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
E2E_DIR = os.environ.get("TUNA_E2E_DIR", "/tmp/tuna-e2e")
BACKEND = os.environ.get("TUNA_BACKEND", os.path.join(REPO, "installer", "tuna-installer-niri"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The branding the backend and the QML resolve from (shared/branding): its
# default_image names the leaf of the catalog below that the wizard starts
# on; on a runner that is the canary shared/e2e later rewrites.
os.environ.setdefault("BOOTC_INSTALLER_BRANDING", os.path.join(REPO, "tests", "e2e", "branding.json"))
# The catalog the backend reads (installer/catalog.go, FISHERMAN_IMAGES_PATH):
# shared/e2e/catalog.json, the one every E2E driver reads.
CATALOG = os.environ.setdefault("FISHERMAN_IMAGES_PATH", os.path.normpath(
    os.path.join(REPO, "..", "..", "shared", "e2e", "catalog.json")))
os.environ["QML2_IMPORT_PATH"] = os.path.join(REPO, "tests", "qml-stubs")
os.environ["QML_IMPORT_PATH"] = os.environ["QML2_IMPORT_PATH"]

from PyQt6.QtCore import (QEventLoop, QMetaObject, QObject, QTimer, QUrl,  # noqa: E402
                          Q_ARG, QVariant)
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine


# The account the e2e user types. The VM job installs it for real, so it is
# a valid name for fisherman (not reserved) and names no product.
ACCOUNT = {"username": "e2euser", "fullname": "E2E User",
           "userPassword": "e2e-password", "userPasswordConfirm": "e2e-password"}


def settle(ms=200):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    if not os.path.exists(BACKEND):
        sys.exit(f"FAIL: backend binary not built at {BACKEND}")
    with open(os.path.join(E2E_DIR, "loopdev")) as fh:
        disk = fh.read().strip()
    name = os.path.basename(disk)

    _app = QGuiApplication(sys.argv)  # must outlive the engine
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(os.path.join(REPO, "ui", "installer.qml")))
    if not engine.rootObjects():
        sys.exit("FAIL: installer.qml did not load")
    root = engine.rootObjects()[0]
    settle(400)

    # What the QML's own Process wrappers would have learned from the backend
    # on a real machine, from the real backend.
    facts = json.loads(subprocess.run([BACKEND, "detect"], capture_output=True, text=True, check=True).stdout)
    disks = json.loads(subprocess.run([BACKEND, "discover-disks"], capture_output=True, text=True, check=True).stdout)
    print(f"[e2e] backend detect: {facts}")
    print(f"[e2e] backend discover-disks: {disks}")
    chosen = next((d for d in disks if d.get("path") == disk), None)
    if chosen is None:
        sys.exit(f"FAIL: the backend did not list the e2e disk {name}: {disks}")

    # The catalog the REAL backend resolved: the leaves, the selection at
    # the start and each leaf's recipe keys for this machine.
    catalog = json.loads(subprocess.run([BACKEND, "catalog"], capture_output=True, text=True, check=True).stdout)
    print(f"[e2e] backend catalog: {catalog['path']}, selected {catalog['selected']!r}, "
          f"{len(catalog['leaves'])} leaves")
    with open(os.environ["BOOTC_INSTALLER_BRANDING"], encoding="utf-8") as fh:
        want_image = json.load(fh)["default_image"]
    if catalog["path"] != CATALOG or catalog["selected"] != want_image:
        sys.exit(f"FAIL: the backend read {catalog['path']!r} and selected "
                 f"{catalog['selected']!r}; expected {CATALOG!r} and the "
                 f"branding's default_image {want_image!r}")
    # What check-recipe.py judges the account against: the catalog this
    # driver gave the frontend.
    shutil.copyfile(CATALOG, os.path.join(E2E_DIR, "catalog.json"))

    def call(method, *args):
        QMetaObject.invokeMethod(root, method, *[Q_ARG(QVariant, a) for a in args])

    def page():
        return root.property("currentPage")

    # Drive the wizard the way a user reaches Install. advance() is the call
    # each page's Continue and Enter make, so a page that will not let a user
    # through fails here and not in the VM.
    root.setProperty("branding", facts.get("branding") or {})
    root.setProperty("isLive", facts.get("isLive") is True)
    root.setProperty("liveImage", facts.get("liveImage") or "")
    root.setProperty("offlineImages", facts.get("offlineImages") or [])
    root.setProperty("encryptionChoices", facts.get("encryptionChoices") or [])
    root.setProperty("disks", disks)
    root.setProperty("disksProbed", True)
    # The connectivity check is the backend's `netcheck`; a runner's network
    # is not this job's subject, so the answer is given: the registry answers.
    root.setProperty("netConnected", True)
    root.setProperty("netChecked", True)

    # Source: the backend's answer selects the branding's image; nothing
    # else is touched.
    call("loadCatalog", catalog)
    root.setProperty("catalogLoaded", True)
    root.setProperty("currentPage", 2)
    settle(500)  # the netcheck pause, then the stub's answer
    if root.property("selectedImage") != want_image:
        sys.exit(f"FAIL: the Source step starts on {root.property('selectedImage')!r}, "
                 f"not the branding's default_image {want_image!r}")
    # A leaf whose image makes its own first user has no account step.
    no_account = next(l for l in catalog["leaves"] if not l["needs_user_creation"])
    call("selectLeaf", no_account)
    if root.property("needsUserCreation") or 5 in list(root.property("flowPages").toVariant()):
        sys.exit("FAIL: the account step stays for an image with needs_user_creation false")
    call("selectLeaf", next(l for l in catalog["leaves"] if l["imgref"] == want_image))
    settle(500)
    call("advance")
    if page() != 3:
        sys.exit(f"FAIL: Continue on the Source step went to page {page()}, not Disk")

    # Disk: the e2e loop disk, by the row the backend listed.
    root.setProperty("selectedDisk", chosen)
    call("advance")
    if page() != 4:
        sys.exit(f"FAIL: Continue on the Disk step went to page {page()}, not Encryption")
    # Encryption: none, the default.
    call("advance")
    if page() != 5:
        sys.exit(f"FAIL: Continue on the Encryption step went to page {page()}, not Account")
    # Account: Continue is held until the fields are set.
    call("advance")
    if page() != 5:
        sys.exit("FAIL: the empty account page let Continue through")
    for prop, value in ACCOUNT.items():
        root.setProperty(prop, value)
    settle(500)  # the validate debounce, then the stub's answer
    if not root.property("accountReady"):
        sys.exit("FAIL: the filled account page holds Continue")
    call("advance")
    settle(200)
    if page() != 6:
        sys.exit(f"FAIL: Continue on the account page went to page {page()}, not Confirm")
    # Confirm: Install, the way Enter presses it.
    call("advance")
    settle(300)
    # The stub's install ends at once, so the wizard is on the install page
    # or already past it; what it wrote is read below.
    if page() not in (7, 8):
        sys.exit(f"FAIL: Install on the Confirm step went to page {page()}, not the install")

    # The install Process's write(); the stub keeps it. The validate Process
    # writes too (the page's fields, for `fisherman validate --partial`), so
    # pick the one whose command is `install`.
    def _command(obj):
        cmd = obj.property("command")
        cmd = cmd.toVariant() if hasattr(cmd, "toVariant") else cmd
        return list(cmd or [])

    written = next((obj.property("written") for obj in root.findChildren(QObject)
                    if obj.property("written") and "install" in _command(obj)), None)
    if not written:
        sys.exit("FAIL: startInstall wrote nothing to the backend's stdin")
    recipe = json.loads(written)
    print("[e2e] recipe the QML wrote:\n" + json.dumps(recipe, indent=2))
    if recipe.get("disk") != disk:
        sys.exit(f"FAIL: QML chose {recipe.get('disk')!r}, expected {disk!r}")
    # The account: the fields the user typed, and NO groups. The backend
    # writes the shared list (installer/user.go), checked below on the
    # recipe fisherman received.
    want_user = {"username": ACCOUNT["username"], "fullname": ACCOUNT["fullname"],
                 "password": ACCOUNT["userPassword"]}
    if recipe.get("user") != want_user:
        sys.exit(f"FAIL: the recipe's user block is {recipe.get('user')!r}, "
                 f"expected {want_user!r}")
    # The image keys are the backend's for the selected leaf, as they came.
    leaf = next(l for l in catalog["leaves"] if l["imgref"] == want_image)
    for key, value in leaf["recipe"].items():
        if recipe.get(key) != value:
            sys.exit(f"FAIL: the recipe's {key} is {recipe.get(key)!r}; the "
                     f"backend's catalog answer says {value!r}")
    if recipe.get("targetImgref") != want_image:
        sys.exit(f"FAIL: the recipe's targetImgref is {recipe.get('targetImgref')!r}")

    print(f"[e2e] piping it to {BACKEND} install")
    r = subprocess.run([BACKEND, "install"], input=written, capture_output=True, text=True,
                       timeout=180, check=False)
    print(r.stdout)
    print(r.stderr, file=sys.stderr)
    if r.returncode != 0:
        sys.exit(f"FAIL: backend install exited {r.returncode}")
    # Feed the backend's real output through the QML's own appendLog(), the
    # function a live install calls, and check where the bar lands.
    #
    # This was `if "[9/9]" not in r.stdout`, matching a prefix fisherman has
    # never written — the shim invented it to satisfy this line, so the
    # assertion compared the harness with itself and passed while the QML
    # bar sat at zero for every real install.
    for line in r.stdout.splitlines():
        if line.strip():
            QMetaObject.invokeMethod(root, "appendLog", Q_ARG(QVariant, line))
    fraction = root.property("installFraction")
    steps = root.property("installSteps")
    print(f"[e2e] progress bar ended at {fraction:.0%} over {steps} steps")
    if '"type":"complete"' not in r.stdout:
        sys.exit("FAIL: the backend's output carried no completion event")
    if fraction != 1.0:
        sys.exit(f"FAIL: the progress bar ended at {fraction:.0%}, not 100% — "
                 "the QML is not parsing fisherman's progress protocol "
                 "(shared/progress/README.md)")
    # The last step carries step_id "finalize", so its caption is the copy
    # line step_finalize, not fisherman's raw step_name.
    with open(os.path.join(REPO, "installer", "copy-defaults.json"), encoding="utf-8") as fh:
        want = json.load(fh)["step_finalize"]
    label = root.property("installStepName")
    print(f"[e2e] last step label: {label!r}")
    if label != want:
        sys.exit(f"FAIL: the last step reads {label!r}, not the copy line {want!r} -- "
                 "the QML is not labelling steps by step_id")
    received_path = os.path.join(E2E_DIR, "recipe.json")
    if not os.path.exists(received_path):
        sys.exit("FAIL: the shim recorded no recipe")
    # What fisherman received: the QML's recipe, with the account's groups
    # the backend wrote from shared/account/groups.json.
    with open(received_path, encoding="utf-8") as fh:
        received = json.load(fh)
    with open(os.path.join(REPO, "..", "..", "shared", "account", "groups.json"), encoding="utf-8") as fh:
        want_groups = json.load(fh)["default_groups"]
    if (received.get("user") or {}).get("groups") != want_groups:
        sys.exit(f"FAIL: fisherman received the groups {(received.get('user') or {}).get('groups')!r}, "
                 f"expected the shared list {want_groups!r}")
    for key in ("image", "targetImgref", "disk", "hostname", "filesystem"):
        if received.get(key) != recipe.get(key):
            sys.exit(f"FAIL: fisherman received {key}={received.get(key)!r}; the QML wrote {recipe.get(key)!r}")
    print("OK: Niri's recipe went QML -> backend -> fisherman")
    return 0


if __name__ == "__main__":
    sys.exit(main())
