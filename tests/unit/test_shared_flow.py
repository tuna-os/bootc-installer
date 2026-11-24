"""shared/flow/ holds together: the spec, its README and the proposal.

`screens.yaml` is the machine-readable spec of the 18 shared screens.
These tests keep it consistent with itself, with `flow/README.md`, and with
`installer-screens.proposed.yaml`, the proposed content of tunaOS
`tests/installer-screens.yaml`.
"""

import pathlib
import re

import yaml

FLOW = pathlib.Path(__file__).resolve().parents[2] / "shared" / "flow"
SPEC = yaml.safe_load((FLOW / "screens.yaml").read_text(encoding="utf-8"))
PROPOSED = yaml.safe_load((FLOW / "installer-screens.proposed.yaml").read_text(encoding="utf-8"))
README = (FLOW / "README.md").read_text(encoding="utf-8")

REQUIRED = {"try-or-install", "disk", "confirm", "install", "recovery-key", "done"}
FRONTENDS = {"kde", "cosmic", "niri", "xfce"}
STATUS = {"have", "partial", "missing"}
# The six ids of the live tunaOS file.
LEGACY = {"welcome", "disk", "encryption", "summary", "install", "done"}


def screens():
    return {s["id"]: s for s in SPEC["screens"]}


def test_eighteen_screens_in_the_declared_order():
    assert len(SPEC["order"]) == 18
    assert [s["id"] for s in SPEC["screens"]] == SPEC["order"]
    assert len(set(SPEC["order"])) == 18


def test_required_screens_are_the_six_of_the_issue():
    assert {i for i, s in screens().items() if s["required_for_harness"]} == REQUIRED
    assert {s["id"] for s in PROPOSED["screens"] if s["required"]} == REQUIRED


def test_each_screen_has_the_fields_and_every_frontend():
    for sid, s in screens().items():
        for key in ("title", "applies_when", "skip_when", "varlink", "failure_states",
                    "accessibility", "gnome_setup", "frontends"):
            assert key in s, f"{sid} has no {key}"
        assert set(s["frontends"]) == FRONTENDS, sid
        for name, row in s["frontends"].items():
            assert row["status"] in STATUS, (sid, name)
        assert s["gnome_setup"]["status"] in {"present", "partial", "absent"}, sid


def test_failure_states_and_scenarios_name_things_that_exist():
    for sid, s in screens().items():
        for f in s["failure_states"]:
            assert f in SPEC["failure_states"], (sid, f)
    for name, scenario in SPEC["mock_scenarios"].items():
        for sid in scenario["reaches"]:
            assert sid in SPEC["order"], (name, sid)


def test_each_scenario_is_reached_by_a_failure_or_a_screen():
    """The issue asks for these failures: device lost, repart error, no TPM,
    RST present, existing data."""
    for name in ("device-lost", "repart-error", "happy-no-tpm", "rst-present", "existing-data"):
        assert name in SPEC["mock_scenarios"]


def test_readme_table_lists_each_screen_in_order():
    ids = re.findall(r"^\| \d+ \| `([\w-]+)` \|", README, re.M)
    assert ids == SPEC["order"]


def test_readme_gap_table_matches_the_spec():
    rows = re.findall(r"^\| `([\w-]+)` \| (\w+) \| (\w+) \| (\w+) \| (\w+) \|$", README, re.M)
    assert [r[0] for r in rows] == SPEC["order"]
    for sid, kde, cosmic, niri, xfce in rows:
        got = {"kde": kde, "cosmic": cosmic, "niri": niri, "xfce": xfce}
        want = {k: v["status"] for k, v in screens()[sid]["frontends"].items()}
        assert got == want, sid


def test_proposal_follows_the_spec_and_keeps_the_legacy_ids():
    assert [s["id"] for s in PROPOSED["screens"]] == SPEC["order"]
    kept = set()
    for s in PROPOSED["screens"]:
        kept.add(s["id"])
        kept.update(s.get("aliases", []))
    assert LEGACY <= kept


def test_proposal_has_no_bare_noun_keywords_from_the_old_blacklist():
    """The live file bans bare nouns that also appear as field labels."""
    banned = {"encrypt", "target", "install", "installing", "reboot", "restart",
              "complete", "finished", "success", "recovery key"}
    for s in PROPOSED["screens"]:
        assert not banned & {k.lower() for k in s["keywords"]}, s["id"]


def test_recovery_key_shape_matches_a_systemd_key():
    shape = re.compile(SPEC["test_contract"]["recovery_key_shape"])
    assert shape.match("cvrfkfrk-ngkncjgr-ijlgdbhe-hvtlcvhn-ikvvlgur-ddkhlirk-ukgccrrd-bvfvkvdd")
    assert not shape.match("Recovery Key")


def test_the_test_contract_of_the_utah_session_is_in_the_readme():
    for phrase in ("input-send-event", "role=button", "by shape", "failure before", "no-break space"):
        assert phrase.lower() in README.lower().replace("\n", " ") or phrase in README, phrase
