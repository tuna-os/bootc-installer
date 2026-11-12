"""Emit `walkthrough-<flavor>.json` — the file tunaOS's installer parity
matrix consumes. Shared by every frontend in this monorepo.

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

import hashlib
import json
import os
import struct
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
    # No product name in any keyword: tunaOS brands each variant separately
    # (Skipjack, Bonito, Yellowfin...) from PRETTY_NAME, so a keyword naming
    # one variant silently fails to match every other ISO.
    {"id": "welcome", "title": "Welcome", "required": True,
     "keywords": ["welcome", "get started", "let's get", "begin",
                  "will guide you through"]},
    # Heading/prompt text, not the "Target Disk: vda" row on the summary.
    # "be installed" is the product-name-free remainder of headings like
    # "Where should <product> be installed?" — the name sits mid-phrase.
    {"id": "disk", "title": "Disk / target selection", "required": True,
     "keywords": ["select target disk", "select a disk", "choose the disk",
                  "available disks", "be installed", "destination",
                  "install location"]},
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
    # and the disk page's heading ends "... be installed?". Progress screens
    # say what they are DOING, so match that instead.
    {"id": "install", "title": "Install progress", "required": False,
     "keywords": ["installation progress", "copying files", "deploying",
                  "please wait", "writing image", "installing\u2026",
                  "partitioning", "installing image", "do not power off"]},
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
        out = []
        for k in blob.split(","):
            k = k.strip()
            if not k:
                continue
            quoted = k[:1] == '"'
            k = k.strip('"\'')
            if quoted:
                # YAML double-quoted scalars carry escapes; upstream writes
                # the Niri heading as "installing\u2026". Without decoding,
                # every capture job warned that 'install' had drifted when
                # the two lists were identical.
                k = k.encode("utf-8").decode("unicode_escape")
            out.append(k.lower())
        return out

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
    # ImageMagick 6 ships `compare`; an ImageMagick 7 build may ship only
    # `magick` (the KDE job runs in a Fedora container).
    for tool in (["compare"], ["magick", "compare"]):
        try:
            r = subprocess.run(
                [*tool, "-metric", "AE", "-fuzz", "5%", a, b, "null:"],
                capture_output=True, text=True)
            break
        except FileNotFoundError:
            continue
    else:
        return None
    # 0: the same, 1: different, 2: an error (a missing or unreadable frame,
    # two sizes). An error measures nothing; it is not "0 pixels changed".
    if r.returncode not in (0, 1):
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


# ── Strict evidence (#186) ───────────────────────────────────────────────
#
# `strict: true` means each required screen of the contract is either
# reached on a page with good evidence, or exempt by a declared, reasoned
# entry in the frontend's feature manifest. Good evidence: the page's PNG
# exists, is a readable PNG, passed the pixel audit (`rendered` is true),
# is the same file that the emitter audited (its `sha256`), is not a
# byte-identical copy of another page's frame, and changed from the frame
# before it (a stale grab that still shows the previous page has the new
# page's widget text, but not its pixels). A screen that
# fails is in `failure_reasons`, and `failures` is their count. Nothing
# here is unconditional.

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))

# The feature manifest of each frontend (the same table as features.py).
MANIFESTS = {
    "gnome": "shared/walkthrough/features-gnome.json",
    "kde": "frontends/kde/features.json",
    "cosmic": "frontends/cosmic/features.json",
    "niri": "frontends/niri/features.json",
    "xfce": "frontends/xfce/features.json",
}

# An exemption must say why in at least this many characters.
MIN_REASON = 20

PASSED, FAILED, EXEMPT, OPTIONAL_MISSING, NOT_MEASURED = (
    "passed", "failed", "exempt", "optional-missing", "not-measured")


def contract_digest():
    """sha256 of the screen contract as this copy has it.

    The report carries it, and the consumer compares it with its own copy:
    a report made against another contract cannot bless a strict result.
    """
    blob = json.dumps([{"id": s["id"], "required": s["required"],
                        "keywords": sorted(k.lower() for k in s["keywords"])}
                       for s in SCREENS], sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_exemptions(flavor, repo=REPO):
    """{screen id: reason} from the frontend's manifest `screen_exemptions`.

    Raises ValueError for an unknown screen or a reason that says nothing.
    A frontend with no manifest (a test, a new frontend) has none.
    """
    rel = MANIFESTS.get(flavor)
    path = os.path.join(repo, rel) if rel else None
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh).get("screen_exemptions") or {}
    ids = {s["id"] for s in SCREENS}
    out = {}
    for sid, reason in raw.items():
        if sid not in ids:
            raise ValueError(f"{rel}: screen_exemptions names '{sid}', which is "
                             "not a screen of the contract")
        if not isinstance(reason, str) or len(reason.strip()) < MIN_REASON:
            raise ValueError(f"{rel}: the exemption of '{sid}' needs a reason "
                             f"of at least {MIN_REASON} characters")
        out[sid] = reason.strip()
    return out


def png_problem(path):
    """None when `path` is a readable PNG with a size, else the reason."""
    if not path or not os.path.exists(path):
        return "frame is missing"
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
    except OSError as exc:
        return f"frame cannot be read ({exc.strerror})"
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return "frame is not a readable PNG"
    width, height = struct.unpack(">II", head[16:24])
    if not width or not height:
        return "frame has no pixels"
    return None


def _file_digest(path):
    if not path:
        return None
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def page_evidence(pages, resolve=lambda png: png, transitions=None):
    """{page name: None when the page is good evidence, else the reason}.

    `resolve` maps a page's recorded `png` to the file to check (the
    consumer reads a copy of the frames in another directory).

    `transitions` is the report's `transition_pixels`: the pixels that
    changed from the frame before each page. A page whose frame changed by
    DIFF_PIXELS or fewer is a stale grab of the page before it, and it
    cannot be the evidence for a screen. An unmeasured transition (None, no
    ImageMagick) is not checked.

    A page that records the `sha256` of its frame must still have that
    frame: a different file in its place (a frame from another run, a
    replaced frame) is not the frame that the emitter audited.
    """
    if not isinstance(transitions, list) or len(transitions) != max(len(pages) - 1, 0):
        transitions = None
    out, seen = {}, {}
    for i, p in enumerate(pages):
        path = resolve(p.get("png"))
        reason = png_problem(path)
        if reason is None and p.get("rendered") is not True:
            reason = ("frame did not pass the pixel audit" if p.get("rendered") is False
                      else "frame has no pixel audit")
        digest = _file_digest(path) if reason is None else None
        if reason is None:
            if digest in seen:
                reason = f"frame is a byte copy of page '{seen[digest]}'"
            else:
                seen[digest] = p["name"]
        if reason is None and p.get("sha256") and p["sha256"] != digest:
            reason = "frame is not the frame that the report audited (sha256 differs)"
        if reason is None and i > 0 and transitions is not None:
            changed = transitions[i - 1]
            if isinstance(changed, int) and not isinstance(changed, bool) \
                    and changed <= DIFF_PIXELS:
                reason = (f"frame shows no change from page '{pages[i - 1]['name']}' "
                          f"({changed} pixels changed, the floor is {DIFF_PIXELS}): "
                          "a stale grab")
        out[p["name"]] = reason
    return out


def evaluate(detail, evidence, exemptions):
    """Outcome of each screen, and the failures.

    `detail` is match_screens()'s detail; `evidence` is page_evidence().
    Returns (outcomes, reached, failures). A failure names the screen and
    says why, with the reason of each page that matched but could not count.
    """
    outcomes, reached, failures = {}, {}, []
    for sc in SCREENS:
        sid = sc["id"]
        pages = detail[sid]["on_pages"]
        good = [n for n in pages if evidence.get(n) is None]
        bad = [f"{n}: {evidence[n]}" for n in pages if evidence.get(n) is not None]
        reached[sid] = bool(good)
        entry = {"required": sc["required"], "evidence": good}
        if bad:
            entry["rejected"] = bad
        if good:
            entry["outcome"] = PASSED
        elif sid in exemptions:
            entry["outcome"] = EXEMPT
            entry["reason"] = exemptions[sid]
        elif sc["required"]:
            entry["outcome"] = FAILED
            why = ("matched only on pages that cannot count (" + "; ".join(bad) + ")"
                   if bad else "no captured page shows it")
            entry["reason"] = why
            failures.append({"screen": sid, "reason": why})
        else:
            entry["outcome"] = OPTIONAL_MISSING
        outcomes[sid] = entry
    return outcomes, reached, failures


def write_report(outdir, flavor, pages, harness, exemptions=None):
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
    _matched, detail = match_screens(pages)
    if exemptions is None:
        exemptions = load_exemptions(flavor)
    evidence = page_evidence(pages, transitions=diffs)
    outcomes, reached, failures = evaluate(detail, evidence, exemptions)

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
        # Strict: every required screen has good evidence or a declared
        # exemption, else it is in failure_reasons. Computed, not asserted.
        "strict": True,
        "failures": len(failures),
        "failure_reasons": failures,
        "screen_outcomes": outcomes,
        "contract_digest": contract_digest(),

        # ── extra context; a consumer reading only the above is unaffected ─
        "source": "offscreen-capture",
        "harness": harness,
        "text_source": "widget-tree",
        "screens_detail": detail,
        # `sha256` binds each page to the frame that this run audited: the
        # consumer rejects a different file under the same name.
        "pages": [dict({k: p[k] for k in
                        ("name", "png", "rendered", "colours", "flat", "ink",
                         "stddev") if k in p},
                       sha256=_file_digest(p.get("png")),
                       text_excerpt=(p.get("text") or "")[:240])
                  for p in pages],
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
        outcome = outcomes[sc["id"]]["outcome"]
        req = "required" if sc["required"] else "optional"
        where = ", ".join(outcomes[sc["id"]]["evidence"]) or "-"
        print(f"    {sc['id']:11s} {outcome:16s} ({req:8s}) {where}")
    for f in failures:
        # The report says so, and the consumer (aggregate.py --strict, run by
        # walkthrough.yml) fails on it. The capture job itself stays green on
        # this alone, so the page still shows the gap.
        print(f"    FAIL: required screen '{f['screen']}': {f['reason']}",
              file=sys.stderr)
    if drift:
        print(f"    WARNING: screen spec has drifted from {SPEC_URL}:",
              file=sys.stderr)
        for d in drift:
            print(f"      - {d}", file=sys.stderr)
    return path, summary
