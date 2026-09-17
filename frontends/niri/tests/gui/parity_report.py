"""Emit `walkthrough-<flavor>.json` — the file tunaOS's installer parity
matrix consumes.

WHY THIS EXISTS. tunaOS defines the screen contract once, in
`tests/installer-screens.yaml`, and `scripts/installer-walkthrough.py` fills
the parity matrix in `docs/INSTALLER-FRONTENDS.md` from a
`walkthrough-<flavor>.json` per frontend. That harness boots a VM and OCRs
QEMU screendumps, so it needs a virgl-capable host — which is why the matrix
has read `_GPU_` / `_pending_` for niri and xfce since it was written, and why
two crash-on-launch bugs and a 93%-white screen survived in frontends nobody
had ever measured.

This module emits the SAME file from the GPU-less capture that already runs on
a stock CI runner. No new contract, no new mechanism: the screenshots we
already take are re-reported in the shape the matrix already reads.

HOW IT DIFFERS FROM THE VM HARNESS, stated so nobody reads more into the
numbers than is there:

  * Text comes from the WIDGET TREE, not OCR. `"ocr": false` and
    `"text_source": "widget-tree"` say so. This is strictly stronger evidence
    for keyword matching (no recognition error) and strictly weaker evidence
    of "a user could read it" (a string set on an invisible or clipped widget
    still counts). The pixel audit that gates this capture is what covers the
    latter, and its per-page verdict is reported as `rendered`.
  * `activation_key` is null. Pages are driven programmatically, so this says
    NOTHING about whether keyboard navigation works — the defect the VM
    harness found on KDE (enter does nothing) is invisible here and must stay
    the VM run's job.
  * `frames` are wizard pages, one per page, not timed samples of a live VM.

Everything else — the metrics, the thresholds, and the rule about which
screens may be credited — is deliberately identical to
`scripts/installer-walkthrough.py` so the two sources are comparable.
"""

import json
import os
import subprocess
import sys

# Same values as scripts/installer-walkthrough.py in tuna-os/tunaOS.
BLANK_STDDEV = 0.02   # grayscale stddev floor for "screen looks blank"
DIFF_PIXELS = 500     # pixels that must change to count as a transition

# ── The screen contract ──────────────────────────────────────────────────
#
# Copied VERBATIM from tuna-os/tunaOS `tests/installer-screens.yaml`. It is
# duplicated rather than fetched so this capture stays hermetic on a runner
# with no network, but that makes DRIFT possible in the one place drift would
# be most embarrassing. `verify_spec_matches_upstream()` below re-checks it
# against the real file whenever the network happens to be there; CI treats a
# mismatch as a warning, not a failure, so an unreachable network can never
# turn a working capture red.
#
# The comments in the upstream file are load-bearing and are kept: each
# explains a keyword that PREVIOUSLY produced a false row in the matrix.
SPEC_URL = ("https://raw.githubusercontent.com/tuna-os/tunaOS/main/"
            "tests/installer-screens.yaml")

SCREENS = [
    # No keyword may contain a product name: the frontends are branded per
    # variant from os-release (Skipjack, Bonito, ...), so "install tunaos"
    # matched nothing on a Skipjack ISO. Upstream removed those in
    # tuna-os/tunaOS#1060; this copy follows.
    {"id": "welcome", "title": "Welcome", "required": True,
     "keywords": ["welcome", "get started", "let's get", "begin"]},
    # Heading/prompt text, not the "Target Disk: vda" row on the summary.
    {"id": "disk", "title": "Disk / target selection", "required": True,
     "keywords": ["select target disk", "select a disk", "choose the disk",
                  "available disks", "be installed", "destination"]},
    # NOT bare "encrypt": that matches the summary page's "Encryption: None"
    # field label, which is the opposite of having reached an encryption
    # screen. Require the screen's own heading or its passphrase prompt.
    {"id": "encryption", "title": "Disk encryption (LUKS)", "required": False,
     "keywords": ["disk encryption", "encrypt this disk", "enter passphrase",
                  "luks passphrase", "encryption passphrase"]},
    {"id": "summary", "title": "Summary / confirm", "required": True,
     "keywords": ["confirm installation", "review your choices", "summary",
                  "ready to install", "about to install"]},
    # NOT "%" and NOT bare "install": a single character matches OCR noise,
    # and bare "install" matches the disk page's "will be installed". Progress
    # screens say what they are DOING, so match that instead. Note the ellipsis
    # in "installing…" — bare "installing" is a substring of the encryption
    # page's "without reinstalling", which has produced a phantom install row.
    {"id": "install", "title": "Install progress", "required": False,
     "keywords": ["installation progress", "copying files", "deploying",
                  "please wait", "writing image", "installing…",
                  "partitioning", "installing image"]},
    # NOT "reboot"/"restart", NOT bare "complete"/"finished"/"success": a
    # LOGIN GREETER satisfies those. cosmic-greeter's power menu offers
    # Restart, Power Off and Suspend, so tunaOS run 31183217981 — stuck on the
    # greeter with the installer never launched — was still credited with
    # reaching the FINISHED screen. Synced from tuna-os/tunaOS#1075.
    {"id": "done", "title": "Finished / reboot", "required": False,
     "keywords": ["installation complete", "installation finished",
                  "is installed", "has been installed",
                  "remove the installation media",
                  "restart to boot", "reboot into"]},
]


def verify_spec_matches_upstream(timeout=5):
    """Best-effort drift check against tunaOS's real spec.

    Returns None when the file could not be fetched (offline runner, and the
    normal case), otherwise a list of human-readable differences. A copy that
    has silently fallen behind upstream would report parity against a contract
    nobody else is using, which is worse than reporting nothing.
    """
    try:
        import urllib.request
        with urllib.request.urlopen(SPEC_URL, timeout=timeout) as fh:
            text = fh.read().decode("utf-8")
    except Exception:
        return None

    # Deliberately not a YAML dependency: parse only the two fields we mirror.
    upstream, current = [], None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if stripped.startswith("- id:"):
            current = {"id": stripped.split(":", 1)[1].strip(), "keywords": []}
            upstream.append(current)
        elif current is not None and stripped.startswith("keywords:"):
            current["_kw_raw"] = stripped.split(":", 1)[1].strip()
        elif current is not None and current.get("_kw_raw", "").count("[") > \
                current.get("_kw_raw", "").count("]"):
            current["_kw_raw"] += " " + stripped

    def parse_kw(blob):
        blob = blob.strip().lstrip("[").rstrip("]")
        return [k.strip().strip('"\'').lower() for k in blob.split(",")
                if k.strip()]

    diffs = []
    ours = {s["id"]: [k.lower() for k in s["keywords"]] for s in SCREENS}
    theirs = {s["id"]: parse_kw(s.get("_kw_raw", "")) for s in upstream}
    if not theirs:
        return None  # could not parse; say nothing rather than cry wolf
    for sid in sorted(set(ours) | set(theirs)):
        if sid not in ours:
            diffs.append(f"upstream has screen '{sid}', this copy does not")
        elif sid not in theirs:
            diffs.append(f"this copy has screen '{sid}', upstream does not")
        elif sorted(ours[sid]) != sorted(theirs[sid]):
            diffs.append(f"'{sid}' keywords differ from upstream")
    return diffs


def changed_pixels(a, b):
    """Pixels differing between two PNGs — same ImageMagick metric, same fuzz
    as the VM harness, so the counts mean the same thing in both reports."""
    try:
        r = subprocess.run(
            ["compare", "-metric", "AE", "-fuzz", "5%", a, b, "null:"],
            capture_output=True, text=True)
    except FileNotFoundError:
        return None
    import re
    m = re.search(r"(\d+)", (r.stderr or "").strip())
    return int(m.group(1)) if m else 0


def match_screens(pages):
    """Which contract screens the frontend actually showed.

    `pages` is the captured sequence, in navigation order, each with a `text`
    key holding that page's own widget text.

    The crediting rule is lifted from the VM harness and matters as much here:
    a screen other than the first may only be credited on a page the wizard
    actually advanced to. A welcome page that describes the whole flow
    ("you'll select a target disk, configure encryption...") otherwise
    manufactures rows for screens nobody has seen — run 29675493401 recorded
    three that way.
    """
    detail = {}
    reached = {}
    for idx, sc in enumerate(SCREENS):
        kws = [k.lower() for k in sc["keywords"]]
        hits = {i for i, p in enumerate(pages)
                if any(k in (p.get("text") or "").lower() for k in kws)}
        if idx > 0:
            hits.discard(0)
        reached[sc["id"]] = bool(hits)
        detail[sc["id"]] = {
            "required": sc["required"],
            "reached": bool(hits),
            "on_pages": [pages[i]["name"] for i in sorted(hits)],
            "matched_keywords": sorted({
                k for i in sorted(hits) for k in kws
                if k in (pages[i].get("text") or "").lower()}),
        }
    return reached, detail


def write_report(outdir, flavor, pages, harness):
    """Write `<outdir>/walkthrough-<flavor>.json` and print a short summary.

    Returns (path, summary). Never raises on a missing ImageMagick: transition
    counts degrade to null rather than taking the capture down with them.
    """
    pngs = [p["png"] for p in pages]
    diffs = [changed_pixels(a, b) for a, b in zip(pngs, pngs[1:])]
    measurable = [d for d in diffs if d is not None]
    advanced = sum(1 for d in measurable if d > DIFF_PIXELS) if measurable else None

    if measurable and len(measurable) == len(diffs):
        states, state = [], 0
        for i in range(len(pages)):
            if i > 0 and diffs[i - 1] > DIFF_PIXELS:
                state += 1
            states.append(state)
        visual_states = states[-1] + 1 if states else 0
    else:
        visual_states = None

    rendered = sum(1 for p in pages if p["rendered"])
    reached, detail = match_screens(pages)

    drift = verify_spec_matches_upstream()

    summary = {
        # ── the fields tuna-os/tunaOS's parity matrix reads ──────────────
        "flavor": flavor,
        "frames": len(pages),
        "rendered_frames": rendered,
        "advanced_transitions": advanced,
        "visual_states": visual_states,
        # Pages are driven programmatically here, so this run proves nothing
        # about keyboard navigation. Null, not "ret" — claiming a key worked
        # when none was pressed is exactly the self-satisfying assertion the
        # frontends doc warns about.
        "activation_key": None,
        # False on purpose: the text came from the widget tree, not OCR.
        "ocr": False,
        "screens": reached,
        "strict": True,
        "failures": 0,

        # ── extra context; a consumer reading only the above is unaffected ─
        "source": "offscreen-capture",
        "harness": harness,
        "text_source": "widget-tree",
        "screens_detail": detail,
        "pages": [{k: p[k] for k in
                   ("name", "png", "rendered", "colours", "flat", "ink",
                    "stddev") if k in p} for p in pages],
        "transition_pixels": diffs,
        "spec_drift": drift,
        "notes": (
            "GPU-less capture: pages are driven programmatically and text is "
            "read from the widget tree, so this reports SCREEN PARITY only. "
            "It does not measure keyboard navigation, compositor rendering, "
            "or that the frontend launches under its real desktop — those "
            "stay the VM walkthrough's job."),
    }

    path = os.path.join(outdir, f"walkthrough-{flavor}.json")
    with open(path, "w") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")

    print(f"\n  parity report -> {os.path.basename(path)}")
    for sc in SCREENS:
        mark = "reached" if reached[sc["id"]] else "NOT reached"
        req = "required" if sc["required"] else "optional"
        where = ", ".join(detail[sc["id"]]["on_pages"]) or "-"
        print(f"    {sc['id']:11s} {mark:12s} ({req:8s}) {where}")
    missing = [s["id"] for s in SCREENS
               if s["required"] and not reached[s["id"]]]
    if missing:
        # Reported, not fatal. This capture's job is to FILL the parity
        # matrix; deciding what a gap costs is the matrix's job, and failing
        # the screenshot build here would just get the emitter disabled.
        print(f"    NOTE: required screen(s) not detected: {', '.join(missing)}",
              file=sys.stderr)
    if drift:
        print(f"    WARNING: screen spec has drifted from {SPEC_URL}:",
              file=sys.stderr)
        for d in drift:
            print(f"      - {d}", file=sys.stderr)
    return path, summary
