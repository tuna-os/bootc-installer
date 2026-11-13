"""The browser-only COSMIC build stays advisory and stays out of the product.

#105: upstream does not take the wasm fixes, so `.github/workflows/wasm-cosmic.yml`
builds `frontends/cosmic` for wasm32 against the tuna-os forks. The fork
pins live in `frontends/cosmic/web/` and reach Cargo only through
`cargo --config`. This test holds these facts:

- The workflow is advisory: job-level `continue-on-error`, a check step that
  may fail on dev, and no job of it in the promote gate's REQUIRED_CHECKS.
- It is path-filtered to frontends/cosmic/** and itself.
- Each fork pin is a tuna-os repository at a full 40-hex commit SHA, never a
  branch, a tag or a local path, and the iced crates are patched as one set.
- CARRIED.md names each pin, and Renovate tracks each pin.
- Nothing outside the job names a fork: Cargo.toml has no [patch], and
  Cargo.lock and the Flatpak cargo sources name no tuna-os source.
- The `web` feature is off by default.
"""

import json
import pathlib
import re
import tomllib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "wasm-cosmic.yml"
PROMOTE = REPO / ".github" / "workflows" / "promote.yml"
COSMIC = REPO / "frontends" / "cosmic"
PATCH = COSMIC / "web" / "cargo-patch.toml"
CARRIED = REPO / "shared" / "browser" / "wasm-patches" / "CARRIED.md"
RENOVATE = REPO / "renovate.json"

SHA = re.compile(r"^[0-9a-f]{40}$")
FORKS = {
    "https://github.com/tuna-os/libcosmic",
    "https://github.com/tuna-os/iced",
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
        iced = {n for n, s in patch[source].items() if s["git"] == "https://github.com/tuna-os/iced"}
        assert iced == ICED_CRATES, source


def pins():
    patch = tomllib.loads(PATCH.read_text())["patch"]
    return {(s["git"], s["rev"]) for crates in patch.values() for s in crates.values()}


def test_carried_md_names_each_pin():
    text = CARRIED.read_text()
    for git, rev in pins():
        assert git.removeprefix("https://github.com/") in text, git
        assert rev in text, (git, rev)


def test_renovate_tracks_each_pin():
    managers = [
        m for m in json.loads(RENOVATE.read_text())["customManagers"]
        if any("cargo-patch" in p for p in m["managerFilePatterns"])
    ]
    found = set()
    for manager in managers:
        assert manager["datasourceTemplate"] == "git-refs"
        assert manager["currentValueTemplate"]
        for pattern in manager["matchStrings"]:
            # Renovate regexes are JavaScript; these use only syntax that
            # Python reads the same way, apart from the group names.
            regex = re.compile(pattern.replace("(?<", "(?P<"))
            for m in regex.finditer(PATCH.read_text()):
                found.add((m["depName"], m["currentDigest"]))
    assert found == pins()


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
