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

WHAT IT RECORDS, AND WHY IT IS NOT JUST A BOOLEAN

`do_activate` does not always present the installer. Depending on the machine
it may present BootcRamWindow, BootcCpuWindow or BootcUnsupportedWindow
instead — real windows, correctly mapped, that are not the wizard. `flatpak ps`
cannot tell those apart, and neither can "a window exists". A CI VM sized just
under the RAM threshold would show the not-enough-RAM screen and pass every
check we currently run.

So the stamp carries the window class that actually mapped, and the smoke test
can require the wizard rather than merely a window.

WHEN IT IS WRITTEN

On GTK's `map` signal, not on `present()`. `present()` is a request; `map` is
the widget actually being mapped. Writing on the request would reintroduce
exactly the gap this closes.
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


def arm(window, app_id, page=None):
    """Write the stamp the first time `window` is mapped."""

    def _on_map(widget):
        write_stamp(app_id, type(widget).__name__, page=page)

    window.connect("map", _on_map)
