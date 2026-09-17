"""Readiness stamp: a compositor-independent record that a window really mapped.

WHY THIS EXISTS

tunaOS's `installer-smoke.yml` proves the frontend is up with `flatpak ps`,
which answers "is the process alive". That is not the same question as "did the
user get a window", and the two have already diverged in production: the COSMIC
leg had the installer process running with no window ever appearing on screen,
and the check stayed green. The only thing that noticed was a human looking at
a screenshot.

Inferring it from pixels is the other half of the same problem — it needs a
compositor that renders, and four of the five desktops need a DRM render node
that GitHub-hosted runners do not have. So the frontend says so itself, in a
file, which any runner can read over SSH with no GPU and no OCR.

WHAT IT RECORDS

The window class and the wizard page that was showing when it mapped. XFCE only
ever maps InstallerWindow, so the class matters less here than it does in
bootc-installer (whose do_activate can present a not-enough-RAM window that
`flatpak ps` reports as a healthy install) — but the field is part of the
contract and stays uniform across the frontends that implement it.

The page is the useful half here: it distinguishes "a window mapped" from "the
wizard reached its first page", which is the thing a smoke test actually wants
to know.

DUPLICATION, DELIBERATELY FLAGGED

This file is a near-copy of bootc_installer/readiness.py, because the five
frontends share no code at all — they are five independent implementations in
five languages, and this is the fifth thing to be reimplemented five times
(after the offline-store probe, the privilege escalation, the product-name
resolution and the encryption table). The contract is small enough that copying
it is the right call today; docs/INSTALLER-FRONTENDS.md in tunaOS is where the
canonical field list lives, and it is what a sixth frontend should be written
against.
"""

import logging
import os
import time

logger = logging.getLogger(__name__)

# $XDG_RUNTIME_DIR is per-user, tmpfs, and cleared between sessions, so a stale
# stamp cannot survive a reboot and be read as a fresh success. Inside the
# Flatpak sandbox this is the app's own runtime dir, which the host sees at
# /run/user/<uid>/app/<app-id>/ — the smoke test looks in both.
STAMP_NAME = "tuna-installer-ready"

# The `signal` field records HOW the stamp was earned, because the five
# frontends cannot all make the same claim and a reader must not treat them as
# equivalent.
#
#   gtk-map      the GTK `map` signal — the widget was actually mapped.
#   first-frame  the toolkit asked us to build a frame. Strictly weaker: it
#                proves the event loop runs and produces frames, not that a
#                surface was mapped and presented.
#
# libcosmic is iced-on-wgpu and has no `map` equivalent, so
# tuna-installer-cosmic can only offer first-frame. Flattening that difference
# would let a smoke test believe a frame callback proves a mapped window — on
# the very frontend whose window never appeared.
SIGNAL = "gtk-map"

APP_ID = "org.tunaos.InstallerXfce"


def stamp_path():
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        return None
    return os.path.join(runtime_dir, STAMP_NAME)


def write_stamp(app_id, window_class, page=None):
    """Record that `window_class` mapped. Best-effort by design.

    A frontend that cannot write its stamp must still install: this is
    observability, and taking the installer down because a tmpfs was read-only
    would be a far worse bug than the one it detects. Failures are logged and
    swallowed.
    """
    path = stamp_path()
    if not path:
        logger.warning("no XDG_RUNTIME_DIR; skipping readiness stamp")
        return

    fields = [
        f"app_id={app_id}",
        f"window={window_class}",
        f"signal={SIGNAL}",
        f"mapped_at={time.time():.3f}",
    ]
    if page is not None:
        fields.append(f"page={page}")

    try:
        # Written via a temp file and renamed, so a reader over SSH never sees
        # a half-written stamp and concludes the wrong window mapped.
        tmp = f"{path}.tmp{os.getpid()}"
        with open(tmp, "w") as fh:
            fh.write("\n".join(fields) + "\n")
        os.replace(tmp, path)
        logger.info("readiness stamp written: %s (%s)", path, window_class)
    except OSError:
        logger.exception("could not write readiness stamp to %s", path)


def arm(window, app_id=APP_ID, page_getter=None):
    """Write the stamp the first time `window` is mapped.

    `page_getter` is called at map time rather than read up front, so the stamp
    reports the page the user is actually looking at instead of whatever was
    current when the signal was connected.
    """

    def _on_map(widget):
        page = None
        if page_getter is not None:
            try:
                page = page_getter()
            except Exception:
                logger.exception("page_getter failed; stamping without a page")
        write_stamp(app_id, type(widget).__name__, page=page)

    window.connect("map", _on_map)
