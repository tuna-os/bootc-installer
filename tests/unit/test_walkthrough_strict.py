"""`strict` in a walkthrough report means something (#186).

parity_report.write_report used to write `strict: true, failures: 0`
whatever it saw, and a missing required screen was a NOTE on stderr. Now
the emitter computes the failures, and the consumer (aggregate.py, which
walkthrough.yml runs with --strict) checks a strict report again against
the frames it has. Each test below goes through the real emitter and the
real consumer, with real PNG files.
"""

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


def png(path, seed, size=8):
    """A small RGB PNG whose pixels depend on `seed`."""
    rows = b"".join(b"\0" + bytes((seed * 37 + x * 11 + y * 5) % 256
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
