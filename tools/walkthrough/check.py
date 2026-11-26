#!/usr/bin/env python3
"""Check a new walkthrough against the flow spec and the committed one.

    check.py FRONTEND NEW [--committed DIR] [--summary FILE]

Fails (exit 1) when a page of the flow spec has no picture and the frontend
does not exempt it (flows.EXEMPT), when a committed page has no new
picture, when a picture is one colour, or when a run did not finish.
Pixel changes are reported, never failed: fonts and antialiasing move.
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import flows  # noqa: E402
import render  # noqa: E402
import runs  # noqa: E402

FUZZ = "8%"          # colour distance that counts as the same pixel
CHANGED = 0.005      # share of pixels that makes a page "changed"


def expected(frontend):
    """Each page the walk must picture: the spec pages, and the states that
    the runs reach, less the exemptions of the frontend."""
    names = list(render.spec()["order"])
    for run in runs.for_frontend(frontend):
        names += [run.name_of(frontend, p) for p in run.only]
    exempt = flows.EXEMPT.get(frontend, {})
    covered = {p for pages in flows.COVERS.get(frontend, {}).values() for p in pages}
    out = []
    for n in names:
        if n and n not in out and n not in exempt and n not in covered:
            out.append(n)
    return out


def diff(a, b):
    r = subprocess.run(["magick", "compare", "-metric", "AE", "-fuzz", FUZZ, a, b, "null:"],
                       capture_output=True, text=True)
    try:
        changed = float(r.stderr.split()[0])
    except (IndexError, ValueError):
        return None
    from PIL import Image
    with Image.open(a) as img:
        return changed / (img.width * img.height)


def load(d):
    with open(os.path.join(d, "manifest.json"), encoding="utf-8") as fh:
        return {e["name"]: e for e in json.load(fh)["pages"]}, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frontend")
    ap.add_argument("new")
    ap.add_argument("--committed", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--verdict", default="",
                    help="write 'changed' or 'same' here: whether a pull request is worth it")
    a = ap.parse_args()
    new, _ = load(a.new)
    with open(os.path.join(a.new, "manifest.json"), encoding="utf-8") as fh:
        errors = json.load(fh).get("errors", [])
    old = {}
    if a.committed and os.path.exists(os.path.join(a.committed, "manifest.json")):
        old, _ = load(a.committed)
    fail, rows = [], []
    for name in expected(a.frontend):
        if name not in new:
            fail.append(f"page `{name}` of the flow spec has no picture")
    for name, e in new.items():
        if e["blank"]:
            fail.append(f"page `{name}` is one colour")
    for name in old:
        if name not in new:
            fail.append(f"page `{name}` has a committed picture and no new one")
    for err in errors:
        fail.append(f"a run did not finish: {err.splitlines()[0][:300]}")
    for name, e in new.items():
        if name not in old:
            rows.append((name, "new", ""))
            continue
        if old[name]["sha256"] == e["sha256"]:
            rows.append((name, "same", "0"))
            continue
        share = diff(os.path.join(a.committed, old[name]["file"]),
                     os.path.join(a.new, e["file"]))
        if share is None:
            rows.append((name, "changed (size)", ""))
        else:
            rows.append((name, "changed" if share > CHANGED else "same (antialiasing)",
                         f"{share * 100:.2f}"))
    exempt = flows.EXEMPT.get(a.frontend, {})
    out = [f"### Walkthrough check: {a.frontend}", "",
           f"{len(new)} pictures; {len(expected(a.frontend))} pages expected.", ""]
    if fail:
        out += ["Failures:", ""] + [f"- {f}" for f in fail] + [""]
    out += ["| Page | Against the committed picture | Changed pixels (%) |", "|---|---|---|"]
    out += [f"| `{n}` | {st} | {p} |" for n, st, p in rows]
    blocked = flows.BLOCKED_BY.get(a.frontend, {})
    if exempt:
        out += ["", "Exempt pages:", ""] + [
            f"- `{k}` ({'defect, ' + blocked[k] if k in blocked else 'design'}): {v}"
            for k, v in exempt.items()]
    changed = any(st in ("new", "changed", "changed (size)") for _n, st, _p in rows) \
        or any(n not in new for n in old)
    if a.verdict:
        with open(a.verdict, "w", encoding="utf-8") as fh:
            fh.write("changed\n" if changed else "same\n")
    out.insert(2, "Verdict: the pictures changed." if changed else
               "Verdict: no page changed beyond antialiasing.")
    out.insert(3, "")
    text = "\n".join(out) + "\n"
    print(text)
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
