#!/usr/bin/env python3
"""Turn the pictures of one walk into a walkthrough: numbered and optimised
PNGs, an animation, a page with captions, and manifest.json.

    render.py FRONTEND CAPTURES OUT [--source mock|e2e] [--run URL]

CAPTURES holds `<page>.png` and the `captures.json` of walk.py. The tunaOS
image-installer E2E writes the same two things from a real install, so one
renderer makes both sets. The captions come from shared/flow/screens.yaml.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "../.."))
sys.path.insert(0, HERE)
import flows  # noqa: E402

NAMES = {"gnome": "GNOME (gnome-setup)", "kde": "KDE Plasma", "cosmic": "COSMIC",
         "niri": "niri", "xfce": "XFCE"}

# Captions of pages that the flow spec has no id for.
OWN = {
    "session": "Keyboard, language, time zone and network, on one page.",
    "source": "The image to install.",
    "image": "The image to install.",
    "options": "Computer name and file system.",
    "computer": "Computer name.",
    "tour": "A tour of the image.",
}
STATES = {
    "dialog": "The confirmation, in a dialog.",
    "cancel": "Cancel asks first.",
    "soft-reboot": "The daemon starts the installed system with a soft reboot.",
    "migrate": "The daemon moves this session to the installed system.",
}

COMPOSITOR = {
    "niri": ("The niri installer runs here in sway with software rendering. "
             "niri itself needs hardware GL, but this installer is a Quickshell "
             "app that any wlroots compositor shows the same way."),
}


def spec():
    with open(os.path.join(REPO, "shared/flow/screens.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def caption(name, s):
    page, _, state = name.partition("--")
    screens = {x["id"]: x for x in s["screens"]}
    if page in screens:
        title = screens[page]["title"]
        when = screens[page].get("applies_when", "")
    else:
        title, when = page.replace("-", " ").capitalize(), OWN.get(page, "")
    if state:
        fs = s.get("failure_states", {}).get(state)
        detail = fs["shows"] if fs else STATES.get(state, state.replace("-", " ") + ".")
        return f"{title}: {state.replace('-', ' ')}", detail
    return title, when


def order_key(name, s, happy_order):
    ids = s["order"]
    page, _, state = name.partition("--")
    if page in ids:
        base = ids.index(page)
    else:
        # A page of this frontend alone: after the spec page before it.
        before = [p for p in happy_order[:happy_order.index(page)] if p in ids] \
            if page in happy_order else []
        base = ids.index(before[-1]) + 0.5 if before else len(ids)
    return (base, bool(state), state)


def optimise(src, dst):
    shutil.copyfile(src, dst)
    subprocess.run(["optipng", "-quiet", "-o2", "-strip", "all", dst], check=True)


def single_colour(path):
    from PIL import Image
    with Image.open(path) as img:
        lo, hi = img.convert("L").getextrema()
    return hi - lo < 4


def animate(frames, out):
    """An animated WebP of the main path, 800 pixels wide."""
    tmp = out + ".d"
    os.makedirs(tmp, exist_ok=True)
    small = []
    for i, f in enumerate(frames):
        p = os.path.join(tmp, f"{i:02d}.png")
        subprocess.run(["magick", f, "-resize", "800x", p], check=True)
        small.append(p)
    argv = ["img2webp", "-loop", "0", "-lossy", "-q", "70", "-m", "4"]
    for p in small:
        argv += ["-d", "2200", p]
    subprocess.run(argv + ["-o", out], check=True, stdout=subprocess.DEVNULL)
    shutil.rmtree(tmp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frontend")
    ap.add_argument("captures")
    ap.add_argument("out")
    ap.add_argument("--source", choices=("mock", "e2e"), default="mock")
    ap.add_argument("--run", default="")
    a = ap.parse_args()
    s = spec()
    with open(os.path.join(a.captures, "captures.json"), encoding="utf-8") as fh:
        cap = json.load(fh)
    pages = cap["pages"]
    happy = [v["page"] for v in pages.values() if v.get("run") == "happy"]
    names = sorted(pages, key=lambda n: order_key(n, s, happy))
    if os.path.isdir(a.out):
        for f in os.listdir(a.out):
            if re.match(r"^\d\d-.*\.png$", f) or f in ("walkthrough.webp", "manifest.json"):
                os.unlink(os.path.join(a.out, f))
    os.makedirs(a.out, exist_ok=True)
    entries, main_frames = [], []
    for i, name in enumerate(names, 1):
        file = f"{i:02d}-{name}.png"
        dst = os.path.join(a.out, file)
        optimise(os.path.join(a.captures, pages[name]["file"]), dst)
        title, detail = caption(name, s)
        with open(dst, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        entries.append({"name": name, "page": name.partition("--")[0], "file": file,
                        "title": title, "caption": detail, "run": pages[name].get("run"),
                        "scenario": pages[name].get("scenario"), "sha256": digest,
                        "blank": single_colour(dst)})
        if "--" not in name and pages[name].get("run") in ("happy", "install"):
            main_frames.append(dst)
    if main_frames:
        animate(main_frames, os.path.join(a.out, "walkthrough.webp"))
    manifest = {"frontend": a.frontend, "source": a.source, "run": a.run,
                "variant": cap.get("variant", ""), "pages": entries,
                "errors": cap.get("errors", [])}
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
        fh.write("\n")
    write_page(a, manifest)
    return 0


def write_page(a, manifest):
    name = NAMES.get(a.frontend, a.frontend)
    if a.source == "mock":
        source = ("These pictures come from the real installer against the mock daemon "
                  "(`fishermand --mock`). The mock writes to no disk. The machine, the "
                  "disks and the recovery key are fixtures.")
    else:
        source = ("These pictures come from a real install in a virtual machine, by the "
                  "image-installer E2E test of tuna-os/tunaOS.")
    lines = [f"# {name}: installer walkthrough", "",
             "Do not edit this page. `tools/walkthrough/render.py` makes it.", "",
             source]
    if a.source == "mock" and a.frontend in COMPOSITOR:
        lines += ["", COMPOSITOR[a.frontend]]
    if a.run:
        lines += ["", f"Run: {a.run}"]
    if os.path.exists(os.path.join(a.out, "walkthrough.webp")):
        lines += ["", "![The main path, animated](walkthrough.webp)"]
    lines += ["", "| # | Page | When it shows | Picture |", "|---|---|---|---|"]
    for i, e in enumerate(manifest["pages"], 1):
        cell = e["caption"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {i} | {e['title']} | {cell} | [![{e['name']}]({e['file']})]({e['file']}) |")
    if manifest["errors"]:
        lines += ["", "## Runs that did not finish", ""]
        lines += [f"- `{e.splitlines()[0][:200]}`" for e in manifest["errors"]]
    with open(os.path.join(a.out, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
