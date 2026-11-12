"""`strict` in a walkthrough report means something (#186).

parity_report.write_report used to write `strict: true, failures: 0`
whatever it saw, and a missing required screen was a NOTE on stderr. Now
the emitter computes the failures, and the consumer (aggregate.py, which
walkthrough.yml runs with --strict) checks a strict report again against
the frames it has. Each test below goes through the real emitter and the
real consumer, with real PNG files.
"""

import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import zlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WALK = REPO / "shared" / "walkthrough"
sys.path.insert(0, str(WALK))
import aggregate  # noqa: E402
import parity_report as pr  # noqa: E402

# One page per contract screen, in wizard order, with text that matches it.
PAGES = [
    ("welcome", "Welcome. Get started."),
    ("disk", "Select a disk"),
    ("encryption", "Disk encryption: enter passphrase"),
    ("confirm", "Review your choices. Ready to install"),
    ("progress", "Installation progress. Please wait"),
    ("done", "Installation complete. Remove the installation media"),
]
REQUIRED = [s["id"] for s in pr.SCREENS if s["required"]]
OPTIONAL = [s["id"] for s in pr.SCREENS if not s["required"]]
SCREEN_PAGE = {"welcome": "welcome", "disk": "disk", "encryption": "encryption",
               "summary": "confirm", "install": "progress", "done": "done"}


def png(path, seed, size=32, poke=0):
    """A small RGB PNG whose pixels depend on `seed`.

    32 x 32 pixels, so that two seeds differ by more than DIFF_PIXELS.
    `poke` inverts that many pixels of the first row: the frame is a new
    file, but shows the same picture (a stale grab).
    """
    def value(seed, x, y):
        v = (seed * 37 + x * 11 + y * 5) % 256
        return 255 - v if y == 0 and x < poke else v
    rows = b"".join(b"\0" + bytes(value(seed, x, y)
                                  for x in range(size) for _ in range(3))
                    for y in range(size))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def capture(root, flavor="gnome", texts=None, exemptions=None, before=None):
    """Write frames and run the emitter, as a harness does. Returns the report."""
    out = root / flavor
    out.mkdir(parents=True)
    pages = []
    for i, (name, text) in enumerate(PAGES):
        frame = out / f"{i + 1:02d}-{name}.png"
        png(frame, i + 1)
        pages.append({"name": name, "png": str(frame), "rendered": True,
                      "colours": 100, "flat": 0.5, "ink": 0.1, "stddev": 0.3,
                      "text": (texts or {}).get(name, text)})
    if before:
        before(out, pages)
    _path, summary = pr.write_report(str(out), flavor, pages, harness="test",
                                     exemptions=exemptions or {})
    return summary


def consume(root, tmp_path):
    """Run the consumer as walkthrough.yml does. Returns (rc, summary.json)."""
    outdir = tmp_path / "out"
    rc = aggregate.build(str(root), str(outdir), "tuna-os/bootc-installer", True)
    return rc, json.loads((outdir / "summary.json").read_text())


def rewrite(root, flavor, change):
    path = root / flavor / f"walkthrough-{flavor}.json"
    report = json.loads(path.read_text())
    change(report)
    path.write_text(json.dumps(report))


@pytest.fixture
def root(tmp_path):
    return tmp_path / "captures"


def test_complete_capture_passes_emitter_and_consumer(root, tmp_path):
    summary = capture(root)
    assert summary["strict"] is True
    assert summary["failures"] == 0 and summary["failure_reasons"] == []
    assert all(o["outcome"] == pr.PASSED for o in summary["screen_outcomes"].values())
    assert summary["contract_digest"] == pr.contract_digest()
    rc, agg = consume(root, tmp_path)
    assert rc == 0, agg["failures"]
    assert agg["frontends"]["gnome"]["kind"] == aggregate.STRICT
    assert all(agg["screens"][s]["gnome"] == aggregate.YES for s in agg["screens"])


@pytest.mark.parametrize("screen", REQUIRED)
def test_deleted_required_frame_fails_at_the_consumer(root, tmp_path, screen):
    """The report was strict and clean; the artifact lost the frame."""
    summary = capture(root)
    assert summary["failures"] == 0
    page = SCREEN_PAGE[screen]
    for f in (root / "gnome").glob(f"*-{page}.png"):
        f.unlink()
    rc, agg = consume(root, tmp_path)
    assert rc == 1
    text = "\n".join(agg["failures"])
    assert f"required screen '{screen}'" in text and f"{page}: frame is missing" in text
    assert "report says strict with 0 failures" in text


@pytest.mark.parametrize("screen", REQUIRED)
def test_deleted_required_frame_fails_at_the_emitter(root, tmp_path, screen):
    page = SCREEN_PAGE[screen]

    def drop(out, _pages):
        for f in out.glob(f"*-{page}.png"):
            f.unlink()
    summary = capture(root, before=drop)
    assert summary["failures"] == 1
    assert summary["failure_reasons"][0]["screen"] == screen
    assert "frame is missing" in summary["failure_reasons"][0]["reason"]
    assert summary["screens"][screen] is False
    assert consume(root, tmp_path)[0] == 1


@pytest.mark.parametrize("screen", REQUIRED)
def test_unreadable_frame_fails(root, tmp_path, screen):
    page = SCREEN_PAGE[screen]

    def corrupt(out, _pages):
        next(out.glob(f"*-{page}.png")).write_bytes(b"not a png at all, sorry")
    summary = capture(root, before=corrupt)
    assert [f["screen"] for f in summary["failure_reasons"]] == [screen]
    assert "not a readable PNG" in summary["failure_reasons"][0]["reason"]
    assert consume(root, tmp_path)[0] == 1


@pytest.mark.parametrize("screen", REQUIRED)
def test_blank_frame_fails(root, tmp_path, screen):
    """The pixel audit said the page did not render."""
    page = SCREEN_PAGE[screen]

    def blank(_out, pages):
        next(p for p in pages if p["name"] == page)["rendered"] = False
    summary = capture(root, before=blank)
    assert [f["screen"] for f in summary["failure_reasons"]] == [screen]
    assert "did not pass the pixel audit" in summary["failure_reasons"][0]["reason"]
    rc, agg = consume(root, tmp_path)
    assert rc == 1 and any(f"'{screen}'" in f for f in agg["failures"])


@pytest.mark.parametrize("screen", REQUIRED)
def test_omitted_required_screen_fails(root, tmp_path, screen):
    page = SCREEN_PAGE[screen]
    summary = capture(root, texts={page: "nothing that matches"})
    assert summary["failure_reasons"] == [
        {"screen": screen, "reason": "no captured page shows it"}]
    assert summary["screen_outcomes"][screen]["outcome"] == pr.FAILED
    rc, agg = consume(root, tmp_path)
    assert rc == 1
    assert any(f"required screen '{screen}': no captured page shows it" in f
               for f in agg["failures"])


def test_duplicate_frame_cannot_credit_another_screen(root, tmp_path):
    """The confirm page's frame is a stale copy of the disk page's frame."""
    def stale(out, _pages):
        shutil.copy(next(out.glob("*-disk.png")), next(out.glob("*-confirm.png")))
    summary = capture(root, before=stale)
    assert [f["screen"] for f in summary["failure_reasons"]] == ["summary"]
    assert "byte copy of page 'disk'" in summary["failure_reasons"][0]["reason"]
    # The same holds when the stale copy appears only in the artifact.
    shutil.rmtree(root)
    capture(root)
    frames = root / "gnome"
    shutil.copy(next(frames.glob("*-disk.png")), next(frames.glob("*-confirm.png")))
    rc, agg = consume(root, tmp_path)
    assert rc == 1 and any("byte copy of page 'disk'" in f for f in agg["failures"])


def _pixels(path):
    """The RGB bytes of a frame that png() wrote (filter 0 on each row)."""
    data = path.read_bytes()
    size = struct.unpack(">I", data[16:20])[0]
    raw = zlib.decompress(data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8])
    return b"".join(raw[r * (size * 3 + 1) + 1:(r + 1) * (size * 3 + 1)] for r in range(size))


def _changed_pixels(a, b):
    """changed_pixels() for png() frames, where ImageMagick is absent."""
    pa, pb = _pixels(pathlib.Path(a)), _pixels(pathlib.Path(b))
    return sum(1 for i in range(0, len(pa), 3) if pa[i:i + 3] != pb[i:i + 3])


@pytest.fixture
def measured(monkeypatch):
    """Transitions are measured: with ImageMagick when it is there."""
    if not (shutil.which("compare") or shutil.which("magick")):
        monkeypatch.setattr(pr, "changed_pixels", _changed_pixels)


def test_stale_grab_cannot_credit_the_next_screen(root, tmp_path, measured):
    """The confirm frame still shows the encryption page, with a few pixels
    changed (a cursor), and the confirm page's widget text. The file is not
    a byte copy, so only the transition shows that it is stale."""
    def stale(out, _pages):
        png(next(out.glob("*-confirm.png")), 3, poke=4)  # 3: the encryption seed
    summary = capture(root, before=stale)
    assert summary["transition_pixels"][2] <= pr.DIFF_PIXELS
    assert [f["screen"] for f in summary["failure_reasons"]] == ["summary"]
    assert "no change from page 'encryption'" in summary["failure_reasons"][0]["reason"]
    rc, agg = consume(root, tmp_path)
    assert rc == 1
    assert any("'summary'" in f and "stale grab" in f for f in agg["failures"])


def test_real_transitions_still_credit_each_screen(root, tmp_path, measured):
    summary = capture(root)
    assert all(d > pr.DIFF_PIXELS for d in summary["transition_pixels"])
    assert summary["failures"] == 0
    assert consume(root, tmp_path)[0] == 0


def test_unmeasured_transition_is_not_a_stale_grab(root, tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "changed_pixels", lambda a, b: None)
    summary = capture(root)
    assert summary["transition_pixels"] == [None] * (len(PAGES) - 1)
    assert summary["failures"] == 0
    assert consume(root, tmp_path)[0] == 0


@pytest.mark.skipif(not shutil.which("compare"), reason="ImageMagick compare is absent")
def test_a_compare_error_measures_nothing(tmp_path):
    png(tmp_path / "a.png", 1)
    assert pr.changed_pixels(str(tmp_path / "a.png"), str(tmp_path / "missing.png")) is None


def test_report_binds_each_page_to_its_frame(root, tmp_path):
    """A frame from another run, under the same name, is not the evidence."""
    summary = capture(root)
    frame = next((root / "gnome").glob("*-confirm.png"))
    page = next(p for p in summary["pages"] if p["name"] == "confirm")
    assert page["sha256"] == hashlib.sha256(frame.read_bytes()).hexdigest()
    png(frame, 99)  # a good frame, but not the one that the emitter audited
    rc, agg = consume(root, tmp_path)
    assert rc == 1
    assert any("'summary'" in f and "not the frame that the report audited" in f
               for f in agg["failures"])


@pytest.mark.parametrize("screen", OPTIONAL)
def test_missing_optional_screen_is_not_a_pass_and_not_a_failure(root, tmp_path, screen):
    summary = capture(root, texts={SCREEN_PAGE[screen]: "nothing that matches"})
    assert summary["failures"] == 0
    assert summary["screen_outcomes"][screen]["outcome"] == pr.OPTIONAL_MISSING
    rc, agg = consume(root, tmp_path)
    assert rc == 0
    assert agg["screens"][screen]["gnome"] == aggregate.NO


def test_declared_exemption_is_distinct_from_pass(root, tmp_path, monkeypatch):
    reason = "this frontend has no summary page (#999)"
    summary = capture(root, texts={"confirm": "nothing that matches"},
                      exemptions={"summary": reason})
    assert summary["failures"] == 0
    assert summary["screen_outcomes"]["summary"] == {
        "required": True, "evidence": [], "outcome": pr.EXEMPT, "reason": reason}
    monkeypatch.setattr(pr, "load_exemptions", lambda flavor, **_: {"summary": reason})
    rc, agg = consume(root, tmp_path)
    assert rc == 0
    assert agg["screens"]["summary"]["gnome"] == aggregate.EXEMPT


def test_consumer_ignores_an_exemption_the_manifest_does_not_declare(root, tmp_path):
    """The emitter was told of an exemption; the repository has none."""
    capture(root, texts={"confirm": "nothing that matches"},
            exemptions={"summary": "this frontend has no summary page (#999)"})
    rc, agg = consume(root, tmp_path)
    assert rc == 1 and any("'summary'" in f for f in agg["failures"])


def test_exemption_needs_a_known_screen_and_a_reason(tmp_path, monkeypatch):
    manifest = tmp_path / "m.json"
    monkeypatch.setitem(pr.MANIFESTS, "gnome", "m.json")
    manifest.write_text(json.dumps({"screen_exemptions": {"summary": "no"}}))
    with pytest.raises(ValueError, match="reason"):
        pr.load_exemptions("gnome", repo=str(tmp_path))
    manifest.write_text(json.dumps({"screen_exemptions": {"nope": "x" * 30}}))
    with pytest.raises(ValueError, match="not a screen"):
        pr.load_exemptions("gnome", repo=str(tmp_path))
    manifest.write_text(json.dumps({"screen_exemptions": {"disk": "x" * 30}}))
    assert pr.load_exemptions("gnome", repo=str(tmp_path)) == {"disk": "x" * 30}


def test_every_manifest_exemption_loads():
    for flavor in pr.MANIFESTS:
        pr.load_exemptions(flavor)


def test_schema_lists_the_screens_of_the_contract():
    schema = json.loads((WALK / "features.schema.json").read_text())
    names = schema["properties"]["screen_exemptions"]["propertyNames"]["enum"]
    assert names == [s["id"] for s in pr.SCREENS]
    assert (schema["properties"]["screen_exemptions"]["additionalProperties"]["minLength"]
            == pr.MIN_REASON)


def test_strict_zero_failures_with_missing_evidence_cannot_pass(root, tmp_path):
    """A report edited to claim a pass, with a screen it never reached."""
    capture(root, texts={"disk": "nothing that matches"})

    def lie(r):
        r["failures"], r["failure_reasons"] = 0, []
        r["screens"]["disk"] = True
    rewrite(root, "gnome", lie)
    rc, agg = consume(root, tmp_path)
    assert rc == 1
    assert any("'disk'" in f for f in agg["failures"])
    assert any("strict with 0 failures" in f for f in agg["failures"])


def test_report_failures_reach_the_consumer(root, tmp_path):
    capture(root, texts={"disk": "nothing that matches"})
    rc, agg = consume(root, tmp_path)
    assert rc == 1 and any("'disk'" in f for f in agg["failures"])
    assert "failed: disk" in (tmp_path / "out" / "README.md").read_text()


def test_contract_drift_is_a_failure(root, tmp_path):
    capture(root)
    rewrite(root, "gnome", lambda r: r.update(contract_digest="0" * 64))
    rc, agg = consume(root, tmp_path)
    assert rc == 1 and any("another screen contract" in f for f in agg["failures"])


def test_legacy_report_is_advisory_not_strict(root, tmp_path):
    """A report from before #186 has no digest: labelled, never a strict pass."""
    capture(root)
    rewrite(root, "gnome", lambda r: r.pop("contract_digest"))
    rc, agg = consume(root, tmp_path)
    assert rc == 0
    assert agg["frontends"]["gnome"]["kind"] == aggregate.ADVISORY
    assert "advisory (old emitter)" in (tmp_path / "out" / "README.md").read_text()


def test_png_only_report_is_advisory(root, tmp_path):
    out = root / "cosmic"
    out.mkdir(parents=True)
    for i, (name, _text) in enumerate(PAGES):
        png(out / f"{i + 1:02d}-{name}.png", i + 1)
    subprocess.run([sys.executable, str(WALK / "report_from_pngs.py"), "cosmic", str(out)],
                   check=True, capture_output=True)
    report = json.loads((out / "walkthrough-cosmic.json").read_text())
    assert report["strict"] is False and report["advisory"] is True
    assert report["failures"] == 0
    assert {o["outcome"] for o in report["screen_outcomes"].values()} == {pr.NOT_MEASURED}
    rc, agg = consume(root, tmp_path)
    assert rc == 0
    assert agg["frontends"]["cosmic"]["kind"] == aggregate.ADVISORY
    assert agg["screens"]["welcome"]["cosmic"] == aggregate.UNMEASURED


def test_one_frontend_failure_does_not_change_another(root, tmp_path):
    capture(root, "gnome")
    capture(root, "xfce", texts={"disk": "nothing that matches"})
    rc, agg = consume(root, tmp_path)
    assert rc == 1
    assert all(f.startswith("XFCE:") for f in agg["failures"]), agg["failures"]
    assert agg["screens"]["disk"]["gnome"] == aggregate.YES
    assert agg["frontends"]["kde"]["kind"] == aggregate.PENDING


def test_receipt_still_states_what_it_does_not_prove(root):
    summary = capture(root)
    assert summary["activation_key"] is None
    assert summary["ocr"] is False
    assert summary["text_source"] == "widget-tree"
    assert "keyboard navigation" in summary["notes"]


def test_committed_walkthrough_still_passes_the_consumer(tmp_path):
    """docs/walkthrough holds the last real captures of all five."""
    rc, agg = consume(REPO / "docs" / "walkthrough", tmp_path)
    assert rc == 0, agg["failures"]
    assert os.path.exists(tmp_path / "out" / "README.md")


# ── The real captures (#186: "demonstrate the frontend capture integration")
#
# docs/walkthrough/ holds the last frames and reports that each frontend's
# own harness wrote on dev (GNOME, XFCE and Niri through write_report, KDE
# and COSMIC through report_from_pngs.py with their texts.json). The tests
# below run the consumer on a copy of them: each of the five is a strict
# report that passes, and a deliberate fault in each one fails with the
# frontend, the screen and the reason.

COMMITTED = REPO / "docs" / "walkthrough"
FLAVORS = [f for f, *_ in aggregate.FLAVORS]


def _committed_copy(tmp_path):
    root = tmp_path / "captures"
    for flavor in FLAVORS:
        shutil.copytree(COMMITTED / flavor, root / flavor)
    return root


def _evidence(root, flavor, screen):
    report = json.loads((root / flavor / f"walkthrough-{flavor}.json").read_text())
    names = report["screen_outcomes"][screen]["evidence"]
    return report, [root / flavor / os.path.basename(p["png"])
                    for p in report["pages"] if p["name"] in names]


def test_each_real_capture_is_strict_and_passes(tmp_path):
    rc, agg = consume(_committed_copy(tmp_path), tmp_path)
    assert rc == 0, agg["failures"]
    for flavor in FLAVORS:
        assert agg["frontends"][flavor]["kind"] == aggregate.STRICT, flavor
        for sc in pr.SCREENS:
            if sc["required"]:
                assert agg["screens"][sc["id"]][flavor] in (aggregate.YES, aggregate.EXEMPT), \
                    (flavor, sc["id"])


@pytest.mark.parametrize("flavor", FLAVORS)
def test_a_duplicate_real_frame_fails_that_frontend(tmp_path, flavor):
    root = _committed_copy(tmp_path)
    report, frames = _evidence(root, flavor, "summary")
    assert frames, f"{flavor}: no evidence for the summary screen"
    first = root / flavor / os.path.basename(report["pages"][0]["png"])
    for frame in frames:
        shutil.copy(first, frame)
    rc, agg = consume(root, tmp_path)
    assert rc == 1
    name = dict((f, n) for f, n, *_ in aggregate.FLAVORS)[flavor]
    assert agg["failures"] and all(f.startswith(f"{name}:") for f in agg["failures"]), \
        agg["failures"]
    assert any("'summary'" in f and "byte copy of page" in f for f in agg["failures"])


@pytest.mark.parametrize("flavor", FLAVORS)
def test_a_deleted_real_frame_fails_that_frontend(tmp_path, flavor):
    root = _committed_copy(tmp_path)
    _report, frames = _evidence(root, flavor, "disk")
    for frame in frames:
        frame.unlink()
    rc, agg = consume(root, tmp_path)
    assert rc == 1
    assert any("'disk'" in f and "frame is missing" in f for f in agg["failures"])
