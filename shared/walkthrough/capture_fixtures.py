"""Fixtures and the GIF step that the Python capture harnesses share.

The install screen is captured in flight: fisherman's dry-run transcript
(`shared/progress/dry-run-transcript.ndjson`) cut part-way through the image
pull, so the bar sits mid-way and not at either end. Every frontend cuts at
the same line and renders the same fraction; KDE (`tests/capture.cpp`) and
the Niri wasm harness carry the same cut in C++.
"""

import json
import os
import shutil
import subprocess

TRANSCRIPT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "progress", "dry-run-transcript.ndjson"))

# The last line of the in-flight transcript is the one that holds this.
CUT_MARKER = "47/71"

# fisherman emits this once, after TPM enrolment, and it is the only way back
# into the disk if the TPM state changes (#129). No CI runner does a TPM
# install, so the event is synthesised. A harness must feed it through the
# parser a real install goes through, not write the key into a widget: a
# capture that seeded the label directly would keep passing if the parse broke.
RECOVERY_KEY = "mkta-rdcw-nnhu-fnbx-kwnv-oixz-ahhh-uahf"
RECOVERY_EVENT = json.dumps({
    "type": "recovery_key",
    "key": RECOVERY_KEY,
    "timestamp": "2026-01-01T00:00:00Z",
    "elapsed_ms": 1000,
})


def cut_transcript(lines):
    """`lines` up to and including the middle of the image pull."""
    cut = next(i for i, ln in enumerate(lines) if CUT_MARKER in ln) + 1
    return lines[:cut]


def fixture_log():
    """The shared transcript's lines, without newlines, cut mid-pull."""
    with open(TRANSCRIPT, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    return cut_transcript(lines)


def write_gif(frames, gif):
    """Assemble the frames into the animated walkthrough.

    ImageMagick 7 names the tool `magick`; ImageMagick 6 has only `convert`.
    The two capture workflows that build the GIF in shell (KDE, COSMIC) run
    the same command: `convert -delay 240 -loop 0 <frames> walkthrough.gif`.
    """
    tool = "magick" if shutil.which("magick") else "convert"
    subprocess.run([tool, "-delay", "240", "-loop", "0", *frames, gif],
                   check=True)
