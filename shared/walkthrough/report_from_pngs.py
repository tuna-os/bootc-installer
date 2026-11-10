#!/usr/bin/env python3
"""Build a `walkthrough-<flavor>.json` from a directory of captured PNGs.

For frontends whose capture harness does not emit the parity report itself
-- today that is the COSMIC crate -- this produces the same file shape:

  * every `NN-<page>.png` becomes a page, with the same pixel audit
    (colours / flat / ink / stddev / rendered) the Python harnesses compute;
  * when the harness left a `texts.json` next to the PNGs ({"<page>": "the
    page's text"}), that text is matched against the contract keywords like
    any widget-tree capture, and `text_source` says where it came from;
  * without `texts.json`, `text_source` is "none" and `screens` is null for
    every contract screen. The aggregator renders those cells as "not
    measured" rather than as a gap. That is the honest answer: nothing here
    can tell which screen a picture shows.

    python3 report_from_pngs.py <flavor> <dir> [--harness "..."]

Requires Pillow or GdkPixbuf for the pixel audit; falls back to
`rendered: null` when neither is importable.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parity_report
import pixel_audit


def audit(path, name):
    try:
        stats = pixel_audit.png_stats(path)
    except Exception as exc:  # no image library at all
        print(f"  {name}: pixel audit unavailable ({exc})", file=sys.stderr)
        return {"name": name, "png": path, "rendered": None, "text": ""}
    if stats is None:
        return {"name": name, "png": path, "rendered": False, "text": ""}
    f = {"name": name, "png": path, **stats, "text": ""}
    f["rendered"] = f["colours"] >= 60 and f["flat"] <= 0.985 and f["ink"] >= 0.003
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("flavor")
    ap.add_argument("directory")
    ap.add_argument("--harness", default="PNG-only report (no widget text)")
    args = ap.parse_args()

    pngs = sorted(f for f in os.listdir(args.directory)
                  if re.match(r"^\d\d-.*\.png$", f))
    if not pngs:
        sys.exit(f"no NN-<page>.png files in {args.directory}")
    import json
    texts = None
    texts_path = os.path.join(args.directory, "texts.json")
    if os.path.exists(texts_path):
        with open(texts_path) as fh:
            texts = json.load(fh)

    pages = []
    for f in pngs:
        name = re.sub(r"^\d\d-", "", f[:-4])
        page = audit(os.path.join(args.directory, f), name)
        page["png"] = os.path.join(args.directory, f)
        if texts is not None:
            page["text"] = texts.get(name, "")
        pages.append(page)
        print(f"  {name:14s} rendered={page['rendered']}")

    _path, summary = parity_report.write_report(
        args.directory, args.flavor, pages, harness=args.harness)
    if texts is not None:
        summary["text_source"] = "rendered-strings"
        summary["notes"] = (
            "Text comes from the strings the harness rendered each page from "
            "(the same constants the view reads), not from a widget tree or "
            "OCR, so this reports SCREEN PARITY only. It does not measure "
            "keyboard navigation, compositor rendering, or that the frontend "
            "launches under its real desktop \u2014 those stay the VM "
            "walkthrough's job.")
    else:
        # Overwrite the fields that only hold when text was actually read.
        summary["text_source"] = "none"
        summary["screens"] = {k: None for k in summary["screens"]}
        summary["notes"] = ("PNG-only report: this harness does not read widget text, "
                            "so contract screens are NOT MEASURED (null), not unreached. "
                            "Rendered/blank per page is still audited from the pixels.")
    with open(_path, "w") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
