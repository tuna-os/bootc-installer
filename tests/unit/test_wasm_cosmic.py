"""The browser-only COSMIC build stays advisory and stays out of the product.

#105: upstream does not take the wasm fixes, so `.github/workflows/wasm-cosmic.yml`
builds `frontends/cosmic` for wasm32 against the tuna-os forks. The fork
pins live in `frontends/cosmic/web/` and reach Cargo only through
`cargo --config`. This test holds these facts:

- The workflow is advisory: job-level `continue-on-error`, a check step that
  may fail on dev, and no job of it in the promote gate's REQUIRED_CHECKS.
- It is path-filtered to frontends/cosmic/** and itself.
- Each fork pin is a tuna-os repository at a full 40-hex commit SHA, never a
  branch or a tag, and the iced crates are patched as one set.
- Nothing outside the job names a fork: Cargo.toml has no [patch], and
  Cargo.lock and the Flatpak cargo sources name no tuna-os source.
- The `web` feature is off by default.
"""

import pathlib
import re
import tomllib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "wasm-cosmic.yml"
PROMOTE = REPO / ".github" / "workflows" / "promote.yml"
COSMIC = REPO / "frontends" / "cosmic"
PATCH = COSMIC / "web" / "cargo-patch.toml"
ASSEMBLE = COSMIC / "web" / "assemble-iced.sh"

SHA = re.compile(r"^[0-9a-f]{40}$")
FORKS = {
    "https://github.com/tuna-os/libcosmic",
    "https://github.com/tuna-os/rust-atomicwrites",
}
ICED_CRATES = {
    "build_helpers", "iced", "iced_accessibility", "iced_core", "iced_debug",
    "iced_futures", "iced_graphics", "iced_program", "iced_renderer",
    "iced_runtime", "iced_tiny_skia", "iced_wgpu", "iced_widget", "iced_winit",
}


def workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def triggers(wf):
    # PyYAML reads the bare key `on` as True.
    return wf.get("on", wf.get(True))


def test_the_job_is_advisory():
    jobs = workflow()["jobs"]
    assert list(jobs) == ["check"]
    job = jobs["check"]
    assert job["continue-on-error"] is True
    step = next(s for s in job["steps"] if s.get("id") == "wasm")
    # Red on a pull request, a warning on dev: never a failed check run
    # on a dev commit, which the promote gate would count.
    assert step["continue-on-error"] == "${{ github.event_name != 'pull_request' }}"
    assert "--config web/cargo-patch.toml" in step["run"]
    assert "--target wasm32-unknown-unknown" in step["run"]
    assert "--no-default-features --features web" in step["run"]
    assert "--locked" not in step["run"]
    report = next(s for s in job["steps"] if s.get("name") == "report")
    assert report["if"] == "always()"


def test_the_job_is_not_in_the_promote_gate():
    wf = workflow()
    job_name = wf["jobs"]["check"]["name"]
    assert "advisory" in job_name
    promote = yaml.safe_load(PROMOTE.read_text())
    required = promote["env"]["REQUIRED_CHECKS"].split("\n")
    assert job_name not in [r.strip() for r in required]
    # It is a trigger of the gate, like every workflow that runs on dev.
    assert wf["name"] in triggers(promote)["workflow_run"]["workflows"]


def test_the_workflow_is_path_filtered_to_cosmic():
    on = triggers(workflow())
    expected = ["frontends/cosmic/**", ".github/workflows/wasm-cosmic.yml"]
    assert on["push"]["paths"] == expected
    assert on["pull_request"]["paths"] == expected
    assert "schedule" not in on


def test_each_git_pin_is_a_tuna_os_fork_at_a_full_sha():
    patch = tomllib.loads(PATCH.read_text())["patch"]
    assert set(patch) == {
        "https://github.com/pop-os/libcosmic",
        "https://github.com/tuna-os/libcosmic",
        "https://github.com/jackpot51/rust-atomicwrites",
    }
    revs = {}
    for source, crates in patch.items():
        for name, spec in crates.items():
            if "path" in spec:
                assert name in ICED_CRATES, name
                assert spec["path"].startswith("web/iced"), spec
                continue
            assert set(spec) == {"git", "rev"}, (source, name, spec)
            assert spec["git"] in FORKS, spec
            assert SHA.match(spec["rev"]), spec
            revs.setdefault(spec["git"], set()).add(spec["rev"])
    # One commit per fork.
    assert all(len(r) == 1 for r in revs.values()), revs
    assert set(revs) == FORKS


def test_the_iced_crates_are_patched_as_one_set():
    patch = tomllib.loads(PATCH.read_text())["patch"]
    for source in ("https://github.com/pop-os/libcosmic", "https://github.com/tuna-os/libcosmic"):
        iced = {n for n, s in patch[source].items() if "path" in s}
        assert iced == ICED_CRATES, source


def test_the_iced_tree_is_pinned_by_full_shas():
    text = ASSEMBLE.read_text()
    assert 'ICED_REPO=https://github.com/tuna-os/iced\n' in text
    base = re.search(r"^ICED_BASE=(\S+)$", text, re.M).group(1)
    picks = re.search(r'^ICED_PICKS="([^"]+)"$', text, re.M).group(1).split()
    assert SHA.match(base)
    assert len(picks) == 2 and all(SHA.match(p) for p in picks)


def test_nothing_outside_the_job_names_a_fork():
    cargo = tomllib.loads((COSMIC / "Cargo.toml").read_text())
    assert "patch" not in cargo
    assert "tuna-os/" not in (COSMIC / "Cargo.lock").read_text()
    sources = COSMIC / "flatpak" / "cargo-sources.json"
    assert "tuna-os/" not in sources.read_text()
    assert not (COSMIC / ".cargo").exists()


def test_the_web_feature_is_off_by_default():
    features = tomllib.loads((COSMIC / "Cargo.toml").read_text())["features"]
    assert features["default"] == ["desktop"]
    assert "web" in features
    assert "web" not in features["default"]
