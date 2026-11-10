"""bootc_shared.network (GNOME and XFCE) follows shared/network/targets.json,
the fixture that the KDE, COSMIC and Niri tests read too."""

import json
import os
import sys

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "shared", "python"))

from bootc_shared import network  # noqa: E402

with open(os.path.join(REPO, "shared", "network", "targets.json"), encoding="utf-8") as _stream:
    FIXTURE = json.load(_stream)


def _addresses(targets):
    return [f"{host}:{port}" for host, port in targets]


def test_every_case_of_the_fixture():
    assert len(FIXTURE["cases"]) >= 20
    for case in FIXTURE["cases"]:
        assert _addresses(network.connectivity_targets(case["imgref"])) == case["targets"], case


def test_the_constants_are_the_fixtures():
    assert _addresses(network.SHARED_TARGETS) == FIXTURE["shared_targets"]
    assert f"{network.DEFAULT_REGISTRY}:{FIXTURE['default_port']}" == FIXTURE["docker_hub"]
    assert network.TIMEOUT_SECONDS == FIXTURE["timeout_seconds"]
    assert list(network.SKIP_ENV_VARS) == FIXTURE["skip_env"]


def test_the_skip_variables():
    for case in FIXTURE["skip_cases"]:
        assert network.skip_requested(case["env"]) is case["skip"], case
        if case["skip"]:
            # The check passes with no connection at all.
            def refuse(address, timeout):
                raise AssertionError(f"dialled {address}")
            assert network.has_connectivity("quay.io/a/b:1", connect=refuse,
                                            environ=case["env"]) is True
