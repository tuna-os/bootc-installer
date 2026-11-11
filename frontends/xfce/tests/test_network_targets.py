"""XFCE's network check follows shared/network/targets.json, the fixture
that every frontend's test reads (GNOME shares the Python reader)."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tuna_installer_xfce import locale as locale_checks  # noqa: E402

FIXTURE_FILE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "shared", "network",
                                             "targets.json"))
with open(FIXTURE_FILE, encoding="utf-8") as _stream:
    FIXTURE = json.load(_stream)


def test_every_case_of_the_fixture():
    for case in FIXTURE["cases"]:
        targets = locale_checks.connectivity_targets(case["imgref"])
        got = [f"{host}:{port}" for host, port in targets]
        assert got == case["targets"], case


def test_the_skip_variables_and_the_timeout(monkeypatch):
    assert list(locale_checks.SKIP_ENV_VARS) == FIXTURE["skip_env"]
    for case in FIXTURE["skip_cases"]:
        for name in FIXTURE["skip_env"]:
            monkeypatch.delenv(name, raising=False)
        for name, value in case["env"].items():
            monkeypatch.setenv(name, value)
        if case["skip"]:
            monkeypatch.setattr(locale_checks.socket, "create_connection",
                                lambda *a, **k: (_ for _ in ()).throw(AssertionError("dialled")))
            assert locale_checks.has_connectivity(imgref="quay.io/a/b:1") is True
    import inspect
    assert inspect.signature(locale_checks.has_connectivity).parameters["timeout"].default \
        == FIXTURE["timeout_seconds"]
