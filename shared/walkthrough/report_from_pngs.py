#!/usr/bin/env python3
"""Build a `walkthrough-<flavor>.json` from a directory of captured PNGs.

For frontends whose capture harness does not (yet) read its own widget text
and emit the parity report itself -- today that is the COSMIC crate -- this
produces the same file shape from the pictures alone:

  * every `NN-<page>.png` becomes a page, with the same pixel audit
    (colours / flat / ink / stddev / rendered) the Python harnesses compute;
  * `text_source` is "none" and each page's `text` is empty, so
    `screens` reports every contract screen as unreached. The aggregator
    renders those cells as "not measured" rather than as a gap. That is the
    honest answer: nothing here can tell which screen a picture shows.

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


def _pixels(path):
    """Yield (r, g, b) for every third pixel on every third row."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            px = im.load()
            for y in range(0, h, 3):
                for x in range(0, w, 3):
                    yield px[x, y]
            return
    except ImportError:
        pass
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    data, stride, chans = pb.get_pixels(), pb.get_rowstride(), pb.get_n_channels()
    for y in range(0, pb.get_height(), 3):
        row = y * stride
        for x in range(0, pb.get_width(), 3):
            i = row + x * chans
            yield (data[i], data[i + 1], data[i + 2])


def audit(path, name):
    counts, samples, dark = {}, 0, 0
    luma_sum = luma_sq = 0
    try:
        for px in _pixels(path):
            counts[px] = counts.get(px, 0) + 1
            samples += 1
            luma = (30 * px[0] + 59 * px[1] + 11 * px[2]) // 100
            luma_sum += luma
            luma_sq += luma * luma
            if luma < 160:
                dark += 1
    except Exception as exc:  # no image library at all
        print(f"  {name}: pixel audit unavailable ({exc})", file=sys.stderr)
        return {"name": name, "png": path, "rendered": None, "text": ""}
    if not samples:
        return {"name": name, "png": path, "rendered": False, "text": ""}
    mean = luma_sum / samples
    var = max(luma_sq / samples - mean * mean, 0.0)
    f = {"name": name, "png": path, "colours": len(counts),
         "flat": max(counts.values()) / samples, "ink": dark / samples,
         "stddev": (var ** 0.5) / 255.0, "text": ""}
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
    pages = []
    for f in pngs:
        name = re.sub(r"^\d\d-", "", f[:-4])
        page = audit(os.path.join(args.directory, f), name)
        page["png"] = os.path.join(args.directory, f)
        pages.append(page)
        print(f"  {name:14s} rendered={page['rendered']}")

    _path, summary = parity_report.write_report(
        args.directory, args.flavor, pages, harness=args.harness)
    # Overwrite the fields that only hold when text was actually read.
    import json
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
