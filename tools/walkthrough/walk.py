#!/usr/bin/env python3
"""Walk one installer against the mock daemon and picture each page.

    walk.py FRONTEND OUTDIR [--only RUN[,RUN]] [--variant dark|small]

Each run of runs.py starts a new session, a new mock daemon with the run's
scenario, and the real installer. The walk reads which page is on the screen,
pictures it once, and presses what a person would press. It stops at the
run's last page. See README.md.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import apps  # noqa: E402
import flows  # noqa: E402
import runs  # noqa: E402
from session import Session, SessionError  # noqa: E402

OCR_FRONTENDS = ("cosmic", "niri")  # niri gives names to buttons, not to text
BUTTONS = ("button", "push button", "toggle button", "link")
# Roles whose names are not a heading of a page.
NOT_HEADINGS = ("button", "check", "radio", "list item", "menu", "text", "entry",
                "combo", "toggle", "tool tip", "table cell", "link")
FIELD_ROLES = ("text", "entry", "password text", "editable", "input")


# Pages that may end a run: a restart that the mock takes and ends.
TERMINAL = ("handoff", "done")


from walk_errors import Stuck  # noqa: E402


def clean(line):
    line = re.sub(r"^\s*Step \d+ of \d+\s*\W+\s*", "", line or "", flags=re.I)
    line = re.sub(r"^[^\w(]+|[^\w)?!.…]+$", "", line)
    return re.sub(r"\s+", " ", line.replace("&", "")).strip()


class Walker:
    def __init__(self, frontend, session, work):
        self.fe, self.s, self.work = frontend, session, work
        self.ocr_on = frontend in OCR_FRONTENDS
        self.nodes, self.words = [], []
        self.table = dict(flows.PAGES)
        for pid, pats in flows.OWN_PAGES.get(frontend, {}).items():
            self.table[pid] = self.table.get(pid, []) + pats

    # -- read --------------------------------------------------------------

    def read(self):
        try:
            r = subprocess.run(["python3", f"{HERE}/atspi.py", "dump"], env=self.s.env,
                               capture_output=True, text=True, timeout=60)
            self.nodes = [n for n in map(json.loads, filter(None, r.stdout.split("\n")))
                          if "showing" in n["states"]]
        except subprocess.TimeoutExpired:
            self.nodes = []
        self.words = self.ocr() if self.ocr_on else []

    def ocr(self):
        shot, big = f"{self.work}/ocr.png", f"{self.work}/ocr-big.png"
        self.s.shot(shot)
        subprocess.run(["magick", shot, "-resize", "250%", "-colorspace", "Gray", big], check=True)
        words = []
        for psm in ("6", "11"):
            r = subprocess.run(["tesseract", big, "-", "--psm", psm, "tsv"],
                               capture_output=True, text=True)
            for row in r.stdout.splitlines()[1:]:
                c = row.split("\t")
                if len(c) > 11 and c[11].strip() and float(c[10]) > 25:
                    x, y, w, h = (int(int(v) / 2.5) for v in c[6:10])
                    words.append({"line": (psm, c[2], c[3], c[4]), "text": c[11],
                                  "box": [x, y, w, h]})
        words += self.button_words(shot)
        return words

    def button_words(self, shot):
        """Text on cards and buttons. Page OCR takes a block whose colour is
        not the page colour for a picture and skips it, so each such block
        is read alone."""
        from PIL import Image
        img = Image.open(shot).convert("L")
        step = 4
        small = img.resize((img.width // step, img.height // step), Image.Resampling.BOX)
        w, h = small.size
        px = small.load()
        seen, words, n = set(), [], 0
        for y0 in range(h):
            for x0 in range(w):
                if (x0, y0) in seen:
                    continue
                seed = px[x0, y0]

                def differs(v, seed=seed):
                    return abs(v - seed) <= 6

                stack, cells = [(x0, y0)], 0
                seen.add((x0, y0))
                x1 = x2 = x0
                y1 = y2 = y0
                while stack:
                    x, y = stack.pop()
                    cells += 1
                    x1, x2, y1, y2 = min(x1, x), max(x2, x), min(y1, y), max(y2, y)
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen \
                                and differs(px[nx, ny]):
                            seen.add((nx, ny))
                            stack.append((nx, ny))
                bw, bh = x2 - x1 + 1, y2 - y1 + 1
                # A block: wide enough for a word, filled, and not the page.
                if bw * step < 40 or bh * step < 16 or cells < 0.5 * bw * bh \
                        or bw * bh > 0.5 * w * h:
                    continue
                box = [x1 * step, y1 * step, bw * step, bh * step]
                crop = img.crop((box[0], box[1], box[0] + box[2], box[1] + box[3]))
                crop = crop.resize((int(crop.width * 2.5), int(crop.height * 2.5)))
                n += 1
                path = f"{self.work}/ocr-block.png"
                crop.save(path)
                psm = "7" if box[3] <= 60 else "11"
                r = subprocess.run(["tesseract", path, "-", "--psm", psm, "tsv"],
                                   capture_output=True, text=True)
                for row in r.stdout.splitlines()[1:]:
                    c = row.split("\t")
                    if len(c) > 11 and c[11].strip() and float(c[10]) > 25:
                        x, y, ww, hh = (int(int(v) / 2.5) for v in c[6:10])
                        words.append({"line": ("block", n, c[2], c[3], c[4]), "text": c[11],
                                      "box": [box[0] + x, box[1] + y, ww, hh]})
        return words

    def ocr_lines(self):
        lines = {}
        for w in self.words:
            lines.setdefault(w["line"], []).append(w)
        # psm 6 first: it keeps the reading order.
        return [lines[k] for k in sorted(lines, key=lambda k: (k[0], lines[k][0]["box"][1]))]

    def lines(self, headings=False):
        out = []
        for n in self.nodes:
            if n["role"] == "frame":
                continue
            if headings and any(r in n["role"] for r in NOT_HEADINGS):
                continue
            for t in (n.get("name"), n.get("text")):
                if t:
                    out += t.split("\n")
        for line in self.ocr_lines():
            out.append(" ".join(w["text"] for w in line))
        return [c for c in map(clean, out) if c]

    def page(self):
        lines = self.lines(headings=True)
        for pid, pats in flows.MODAL.items():
            for p in pats:
                if any(re.fullmatch(p, ln, re.I) for ln in lines):
                    return pid
        for ln in lines:
            for pid, pats in self.table.items():
                if any(re.fullmatch(p, ln, re.I) for p in pats):
                    return pid
        return "unknown"

    # -- find and act ------------------------------------------------------

    def find(self, pattern, roles=None, enabled=True, exact=True):
        match = re.fullmatch if exact else re.search
        hits = [n for n in self.nodes
                if match(pattern, clean(n["name"]), re.I)
                and (not roles or any(r in n["role"] for r in roles))
                and (not enabled or "sensitive" in n["states"])]
        return hits

    def find_text(self, pattern):
        """The box of OCR words that the pattern matches in full. A line is
        cut where the gap between two words is wider than a letter is high,
        so two buttons on one line are two pieces."""
        for line in self.ocr_lines():
            pieces, cur = [], [line[0]]
            for prev, w in zip(line, line[1:]):
                gap = w["box"][0] - (prev["box"][0] + prev["box"][2])
                if gap > 1.2 * max(prev["box"][3], w["box"][3]):
                    pieces.append(cur)
                    cur = []
                cur.append(w)
            pieces.append(cur)
            for piece in pieces + [line]:
                text = clean(" ".join(w["text"] for w in piece))
                if re.fullmatch(pattern, text, re.I):
                    x1 = min(w["box"][0] for w in piece)
                    y1 = min(w["box"][1] for w in piece)
                    x2 = max(w["box"][0] + w["box"][2] for w in piece)
                    y2 = max(w["box"][1] + w["box"][3] for w in piece)
                    return [x1, y1, x2 - x1, y2 - y1]
        return None

    def do(self, verb, node, *words):
        r = subprocess.run(["python3", f"{HERE}/atspi.py", verb, json.dumps(node["path"]), *words],
                           env=self.s.env, capture_output=True, text=True, timeout=30)
        return r.returncode == 0

    def click_box(self, box):
        if not box or box[2] <= 0 or box[0] < 0:
            return False
        self.s.click(box[0] + box[2] / 2, box[1] + box[3] / 2)
        return True

    def press(self, pattern, roles=BUTTONS, must=True, ocr=True):
        hits = self.find(pattern, roles)
        if hits:
            node = hits[-1]
            # The action of the node; a click where the toolkit has none.
            if not (node.get("actions") and self.do("press", node)):
                self.click_box(node.get("box"))
            return True
        if self.ocr_on and ocr:
            box = self.find_text(pattern)
            if box and not self.find(pattern, roles, enabled=False):
                return self.click_box(box)
        if must:
            raise Stuck(f"nothing to press: {pattern}")
        return False

    def choose(self, pattern):
        """A row of a list, or a radio button."""
        hits = (self.find(pattern, ("radio", "check", "list item"))
                or self.find(pattern))
        if hits and self.click_box(hits[0].get("box")):
            return True
        if hits and hits[0].get("actions"):
            return self.do("press", hits[0])
        box = self.find_text(pattern) if self.ocr_on else None
        if box:
            return self.click_box(box)
        return False

    def fields(self):
        return [n for n in self.nodes
                if "editable" in n["states"] and "sensitive" in n["states"]
                and (n.get("box") or [0, 0, 0, 0])[2] > 0]

    def type_into(self, x, y, text):
        """Click an entry, empty it, and type, as a person does."""
        self.s.click(x, y)
        time.sleep(0.2)
        self.s.click(x, y)
        self.s.keys("End", *(["BackSpace"] * 40))
        self.s.type(text)

    def primary(self):
        """The button that goes on."""
        for p in flows.PRIMARY:
            if self.press(p, must=False, ocr=False):
                return
        for p in flows.PRIMARY:
            if self.ocr_on and self.press(p, must=False):
                return
        raise Stuck("no primary button is enabled")

    def signature(self):
        return "\n".join(self.lines())


def picture(walker, out, name):
    path = os.path.join(out, f"{name}.png")
    still = walker.s.still(path)
    return path, still


def walk(frontend, run, out, work, variant, log):
    size = {"small": (1024, 600)}.get(variant, (1000, 700))
    argv, env = apps.command(frontend)
    env = {**apps.COMMON, **env, **run.env}
    apps.set_terms(frontend, run.env.get("WALK_EULA"))
    found = {}
    with Session(run.scenario, step_delay=run.step_delay, width=size[0], height=size[1],
                 dark=variant == "dark", log_dir=work) as s:
        s.launch(argv, env)
        w = Walker(frontend, s, work)
        time.sleep(2)
        last, same, seen, prepared = None, 0, [], set()
        for _step in range(run.max_steps):
            w.read()
            page = w.page()
            sig = (page, w.signature())
            same = same + 1 if sig == last else 0
            last = sig
            if page not in seen:
                seen.append(page)
                log(f"  {page}")
            name = run.name_of(frontend, page)
            act = runs.action(run, frontend, page)
            if name and name not in found:
                if act.prepare and page not in prepared:
                    prepared.add(page)
                    act.prepare(w)
                    time.sleep(0.4)
                path = os.path.join(out, f"{name}.png")
                still = s.still(path)
                # The page must still be the same one: a page that changed
                # while the picture settled is not this page.
                w.read()
                if w.page() == page:
                    found[name] = {"page": page, "run": run.name, "scenario": run.scenario,
                                   "still": still, "file": os.path.basename(path),
                                   "headings": w.lines()[:4]}
                    log(f"    picture {name}")
                    if run.done(found, frontend):
                        break
                else:
                    os.unlink(path)
                    continue
            if page in run.until:
                break
            if page in TERMINAL and same > 2 and (name in found or not name):
                break
            waiting = page in runs.WAIT_PAGES and not run.actions.get(page)
            if same > (90 if waiting else 12):
                s.shot(os.path.join(work, f"stuck-{run.name}.png"))
                raise Stuck(f"{run.name}: no progress on page {page}: {w.lines()[:40]}")
            if waiting or page == "unknown":
                time.sleep(1)
                continue
            try:
                if act.prepare and page not in prepared:
                    prepared.add(page)
                    act.prepare(w)
                    time.sleep(0.3)
                    w.read()
                (act.leave or Walker.primary)(w)
            except Stuck as exc:
                if same >= 6:
                    s.shot(os.path.join(work, f"stuck-{run.name}.png"))
                    raise Stuck(f"{run.name}: {page}: {exc}: {w.lines()[:40]}") from exc
                time.sleep(0.7)
            time.sleep(0.8)
        else:
            raise Stuck(f"{run.name}: more than {run.max_steps} steps: {seen}")
    missing = [p for p in run.only if run.name_of(frontend, p) not in found]
    if missing:
        raise Stuck(f"{run.name}: never reached {missing}; saw {seen}")
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frontend", choices=sorted(("gnome", "kde", "cosmic", "niri", "xfce")))
    ap.add_argument("out")
    ap.add_argument("--only", default="")
    ap.add_argument("--variant", choices=("", "dark", "small"), default="")
    ap.add_argument("--work", default="/tmp/walk")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)
    only = set(filter(None, a.only.split(",")))
    pages, errors = {}, []
    for run in runs.for_frontend(a.frontend, a.variant):
        if only and run.name not in only:
            continue
        for attempt in (1, 2):
            print(f"run {run.name} ({run.scenario})", flush=True)
            try:
                got = walk(a.frontend, run, a.out, a.work, a.variant, print)
                for k, v in got.items():
                    pages.setdefault(k, v)
                break
            except (Stuck, SessionError, subprocess.SubprocessError) as exc:
                print(f"  FAIL {exc}", flush=True)
                if attempt == 2:
                    errors.append(f"{run.name}: {exc}"[:600])
    with open(os.path.join(a.out, "captures.json"), "w", encoding="utf-8") as fh:
        json.dump({"frontend": a.frontend, "variant": a.variant, "pages": pages,
                   "errors": errors}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
