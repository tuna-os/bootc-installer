#!/usr/bin/env python3
"""Fold every frontend's capture into one walkthrough + parity document.

Input:  a directory holding one sub-directory per frontend flavor (gnome, kde,
        cosmic, niri, xfce), each with the `NN-<page>.png` frames,
        `walkthrough.gif`, `walkthrough-<flavor>.json` and optionally
        `captions.json` that the frontend's capture harness produced.
Output: <outdir>/README.md, <outdir>/summary.json and a copy of every
        frame under <outdir>/<flavor>/.

    python3 shared/walkthrough/aggregate.py <captures-dir> docs/walkthrough

The parity matrix is computed from the reports' `screens` maps, which every
frontend's harness fills against the SAME contract
(shared/walkthrough/parity_report.py: SCREENS). A frontend with no report
reads as "pending"; a report whose `screens` values are null (PNG-only
capture) reads as "not measured". Neither is a pass.

The consumer does not take a report's word for it (#186). For a strict
report it checks again, against the frames in the capture directory and
its own copy of the contract: the report's contract digest must match; each
required screen must show on a page whose frame is present, is a readable
PNG, passed the pixel audit, is the file that the emitter audited (the
page's `sha256`), is not a byte copy of another frame, and changed from the
frame before it (`transition_pixels`); else
the frontend's manifest must exempt the screen with a reason
(`screen_exemptions`). A report that says `strict: true` and `failures: 0`
fails here when that evidence is missing.

A PNG-only report (`strict: false`, `advisory: true`) and a report from an
emitter older than the contract digest are ADVISORY: the page labels them
so, and they neither pass nor fail. A frontend with no capture is pending.
Neither is a failure, so one frontend's capture never gates another.

`--strict` exits 1 when there is a failure. walkthrough.yml runs with it,
commits the page first, and then fails the job, so the page shows the gap.
"""

import argparse
import html
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parity_report

FLAVORS = [
    ("gnome", "GNOME", "GTK4 / libadwaita (Python)", "bootc_installer/"),
    ("kde", "KDE Plasma", "Qt 6 / Kirigami (C++ + QML)", "frontends/kde/"),
    ("cosmic", "COSMIC", "libcosmic / iced (Rust)", "frontends/cosmic/"),
    ("niri", "Niri", "Quickshell QML + Go backend", "frontends/niri/"),
    ("xfce", "XFCE", "GTK3 / PyGObject", "frontends/xfce/"),
]

PENDING, UNMEASURED, YES, NO, EXEMPT = "pending", "not measured", "yes", "no", "exempt"
STRICT, ADVISORY = "strict", "advisory"


def frame_path(d, png):
    """The copy of a report page's frame in the capture directory."""
    return os.path.join(d["dir"], os.path.basename(png or ""))


def verify(flavor, d, repo=None):
    """Check a report again. Sets d["kind"], d["outcomes"]; returns failures.

    Each failure is a string that names the frontend, the screen or the
    artifact, and the reason.
    """
    r = d["report"]
    name = dict((f, n) for f, n, *_ in FLAVORS).get(flavor, flavor)
    d["outcomes"] = None
    if r.get("strict") is not True or r.get("text_source") == "none":
        d["kind"] = ADVISORY
        return []
    if not r.get("contract_digest"):
        # Written by an emitter older than #186: label it, do not trust it.
        d["kind"] = ADVISORY
        d["legacy"] = True
        return []
    d["kind"] = STRICT
    failures = []
    if r["contract_digest"] != parity_report.contract_digest():
        failures.append(f"{name}: report was made against another screen contract "
                        f"(digest {r['contract_digest'][:12]}, this one "
                        f"{parity_report.contract_digest()[:12]})")
    try:
        exemptions = parity_report.load_exemptions(
            flavor, **({"repo": repo} if repo else {}))
    except ValueError as exc:
        failures.append(f"{name}: {exc}")
        exemptions = {}
    detail = r.get("screens_detail") or {}
    missing_detail = [s["id"] for s in parity_report.SCREENS if s["id"] not in detail]
    if missing_detail:
        failures.append(f"{name}: report has no detail for screen(s) "
                        f"{', '.join(missing_detail)}")
        detail = {s["id"]: detail.get(s["id"], {"on_pages": []})
                  for s in parity_report.SCREENS}
    evidence = parity_report.page_evidence(
        r.get("pages") or [], resolve=lambda png: frame_path(d, png),
        transitions=r.get("transition_pixels"))
    outcomes, _reached, found = parity_report.evaluate(detail, evidence, exemptions)
    d["outcomes"] = outcomes
    for f in found:
        failures.append(f"{name}: required screen '{f['screen']}': {f['reason']}")
    claimed = r.get("failures")
    if found and claimed == 0:
        failures.append(f"{name}: report says strict with 0 failures, but the "
                        "evidence above is missing")
    if isinstance(claimed, int) and claimed > 0:
        found_ids = {f["screen"] for f in found}
        for f in r.get("failure_reasons") or []:
            if f.get("screen") not in found_ids:
                failures.append(f"{name}: required screen '{f.get('screen')}': "
                                f"{f.get('reason')} (from the report)")
    return failures


def load_flavor(root, flavor):
    d = os.path.join(root, flavor)
    if not os.path.isdir(d):
        return None
    frames = sorted(f for f in os.listdir(d) if re.match(r"^\d\d-.*\.png$", f))
    report = None
    rp = os.path.join(d, f"walkthrough-{flavor}.json")
    if os.path.exists(rp):
        with open(rp) as fh:
            report = json.load(fh)
    captions = {}
    cp = os.path.join(d, "captions.json")
    if os.path.exists(cp):
        with open(cp) as fh:
            captions = json.load(fh)
    return {"dir": d, "frames": frames, "report": report, "captions": captions,
            "gif": ("walkthrough.gif"
                    if os.path.exists(os.path.join(d, "walkthrough.gif")) else None)}


def cell(data, screen_id):
    if data is None or data["report"] is None:
        return PENDING
    outcomes = data.get("outcomes")
    if outcomes is not None and screen_id in outcomes:
        outcome = outcomes[screen_id]["outcome"]
        if outcome == parity_report.EXEMPT:
            return EXEMPT
        return YES if outcome == parity_report.PASSED else NO
    val = (data["report"].get("screens") or {}).get(screen_id)
    if val is None:
        return UNMEASURED
    return YES if val else NO


def render_cell(state, required):
    if state == YES:
        return "✅"
    if state == NO:
        return "❌" if required else "⚠️"
    if state == UNMEASURED:
        return "➖"
    if state == EXEMPT:
        return "⚪"
    return "⏳"


def page_label(frame):
    return re.sub(r"^\d\d-", "", frame[:-4]).replace("_", " ").replace("-", " ")


def cell_text(text, limit=None):
    """Captured or free text as the text of one Markdown table cell.

    A line break in a cell ends the table row: the page then shows the rest
    of the widget text as body paragraphs, and the STE prose check
    (.github/workflows/ste.yml) counts UI strings as this repository's prose.
    So all white space becomes one space, `|` cannot start a new cell, and
    `<` and `&` cannot start markup.
    """
    text = " ".join((text or "").split())
    if limit is not None:
        text = text[:limit].rstrip()
    return html.escape(text, quote=False).replace("|", "&#124;")


# The legend is a table, not a sentence: table cells are not prose to the STE
# check, and a row for each mark is easier to read than a line of separators.
LEGEND = [
    ("✅", "The frontend reaches the screen."),
    ("❌", "The frontend does not reach a required screen."),
    ("⚠️", "The frontend does not reach an optional screen."),
    ("➖", "No measurement: the harness of this frontend does not read its widget text."),
    ("⚪", "The `screen_exemptions` of the frontend exempt the screen."),
    ("⏳", "No capture is on record."),
]


def build(root, outdir, repo, strict):
    os.makedirs(outdir, exist_ok=True)
    data = {flavor: load_flavor(root, flavor) for flavor, *_ in FLAVORS}
    failures = []
    for flavor, d in data.items():
        if d is not None and d["report"] is not None:
            failures += verify(flavor, d)

    # Copy frames so the document is self-contained and diffable in git.
    for flavor, d in data.items():
        dest = os.path.join(outdir, flavor)
        if d is None:
            continue
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(dest)
        for f in d["frames"] + ([d["gif"]] if d["gif"] else []):
            shutil.copy2(os.path.join(d["dir"], f), os.path.join(dest, f))
        if d["report"] is not None:
            with open(os.path.join(dest, f"walkthrough-{flavor}.json"), "w") as fh:
                json.dump(d["report"], fh, indent=2)
                fh.write("\n")

    lines = []
    w = lines.append
    w("# Installer frontends: walkthrough and parity")
    w("")
    # The sentences below are the only prose on this page, and the STE check
    # counts each finding against .ste-budget. Keep them at zero findings:
    # short, active, no "-ing" forms (tests/unit/test_walkthrough_strict.py).
    w("`shared/walkthrough/aggregate.py` makes this page from the screenshot job")
    w("of each frontend. CI renders each frame from the real UI, so this page")
    w("cannot drift from the apps. Do not edit this page by hand.")
    w("")
    w("## Parity matrix")
    w("")
    w("The matrix shows the screens of the shared contract that each frontend")
    w("reaches. Each harness reads the visible widget text of each page that it")
    w("captures. `shared/walkthrough/parity_report.py` compares that text with")
    w("the contract. For a strict report, the aggregator does a second check")
    w("against the frames. An advisory report is not a pass.")
    w("")
    w("| Mark | Meaning |")
    w("|---|---|")
    for mark, meaning in LEGEND:
        w(f"| {mark} | {meaning} |")
    w("")
    header = "| Screen | " + " | ".join(name for _, name, *_ in FLAVORS) + " |"
    w(header)
    w("|---|" + "---|" * len(FLAVORS))
    problems = list(failures)
    for sc in parity_report.SCREENS:
        row = [f"`{sc['id']}` {'(required)' if sc['required'] else ''}".strip()]
        for flavor, name, *_ in FLAVORS:
            st = cell(data[flavor], sc["id"])
            row.append(render_cell(st, sc["required"]))
            d = data[flavor]
            if (st == NO and sc["required"] and d and d.get("kind") == ADVISORY
                    and not d.get("legacy")):
                problems.append(f"{name}: required screen '{sc['id']}' not reached "
                                "(advisory report)")
        w("| " + " | ".join(row) + " |")
    w("")
    w("| Frontend | Pages | Rendered | Transitions | Report | Harness |")
    w("|---|---|---|---|---|---|")
    for flavor, name, _toolkit, _path in FLAVORS:
        d = data[flavor]
        if d is None or d["report"] is None:
            w(f"| {name} | {len(d['frames']) if d else 0} | – | – | pending | – |")
            continue
        r = d["report"]
        # No run id or link here on purpose: this file is committed, and a
        # value that changes on every CI run turns each re-run into a new
        # commit even when nothing rendered differently (dev grew two
        # identical-looking walkthrough commits in five minutes on the
        # first day). The run ids stay in the job log.
        w(f"| {name} | {r.get('frames')} | {r.get('rendered_frames')} | "
          f"{r.get('advanced_transitions')} | {report_kind(d)} | {r.get('harness', '')} |")
    w("")
    if problems:
        w("**Gaps:**")
        w("")
        # Messages, not prose: each names a frontend, a screen and a reason,
        # and the set changes from run to run. Outside the STE count, so a
        # red capture cannot also move the prose budget.
        w("<!-- ste-disable: failure messages that the aggregator generates -->")
        w("")
        for p in problems:
            w(f"- {cell_text(p)}")
        w("")
        w("<!-- ste-enable -->")
        w("")

    for flavor, name, toolkit, path in FLAVORS:
        d = data[flavor]
        w(f"## {name}")
        w("")
        w(f"{toolkit}. Source: `{path}`.")
        w("")
        if d is None or not d["frames"]:
            w("_No capture on record yet._")
            w("")
            continue
        if d["gif"]:
            w(f'<p align="center"><img src="{flavor}/walkthrough.gif" '
              f'alt="{name} installer walkthrough" width="640"></p>')
            w("")
        w("| | |")
        w("|---|---|")
        pages = {p["name"]: p for p in (d["report"] or {}).get("pages", [])}
        for f in d["frames"]:
            label = page_label(f)
            caption = cell_text(d["captions"].get(f))
            key = re.sub(r"^\d\d-", "", f[:-4])
            p = pages.get(key) or pages.get(f[:-4]) or {}
            rendered = p.get("rendered")
            flag = "" if rendered in (True, None) else " **(did not render)**"
            excerpt = cell_text(p.get("text_excerpt"), limit=140)
            excerpt = f" <br><sub>{excerpt}</sub>" if excerpt else ""
            w(f'| <img src="{flavor}/{f}" width="360"> | **{label}**{flag} {caption}{excerpt} |')
        w("")

    with open(os.path.join(outdir, "README.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")

    summary = {
        "screens": {sc["id"]: {flavor: cell(data[flavor], sc["id"]) for flavor, *_ in FLAVORS}
                    for sc in parity_report.SCREENS},
        # Each frontend's own entry: this read the last loop's `d` for all
        # five before, so every frontend showed the frame count of XFCE.
        "frontends": {flavor: {
            "frames": len(fd["frames"]) if fd else 0,
            "report": bool(fd and fd["report"]),
            "kind": (fd.get("kind") if fd and fd["report"] else PENDING),
        } for flavor, fd in data.items()},
        "problems": problems,
        "failures": failures,
    }
    with open(os.path.join(outdir, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")

    for p in problems:
        level = "error" if p in failures else "warning"
        print(f"::{level}::{p}")
    print(f"wrote {os.path.join(outdir, 'README.md')} ({len(problems)} gap(s), "
          f"{len(failures)} failure(s))")
    return 1 if (strict and failures) else 0


def report_kind(d):
    if d.get("legacy"):
        return "advisory (old emitter)"
    if d.get("kind") == STRICT:
        failed = [s for s, o in (d.get("outcomes") or {}).items()
                  if o["outcome"] == parity_report.FAILED]
        return "strict, " + (f"failed: {', '.join(failed)}" if failed else "passed")
    return d.get("kind") or ADVISORY


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("captures")
    ap.add_argument("outdir")
    ap.add_argument("--repo", default="")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    return build(args.captures, args.outdir, args.repo, args.strict)


if __name__ == "__main__":
    sys.exit(main())
