"""GNOME finds an NVIDIA GPU the way shared/probe/fixtures/pci/cases.json
says: a PCI display device (class 0x03xxxx) with vendor 0x10de. KDE,
COSMIC, Niri and XFCE run the same cases."""

import json
import os
import sys
from unittest.mock import patch

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from bootc_installer.core import system  # noqa: E402
from bootc_shared import hardware  # noqa: E402

PCI = os.path.join(REPO, "shared", "probe", "fixtures", "pci")
with open(os.path.join(PCI, "cases.json"), encoding="utf-8") as _stream:
    CASES = json.load(_stream)["cases"]


def test_the_cases_cover_each_kind_of_machine():
    names = {case["name"] for case in CASES}
    assert {"nvidia-display", "nvidia-non-display", "other-vendor-display", "none"} <= names
    assert {case["has_nvidia"] for case in CASES} == {True, False}


def test_the_shared_reader_follows_every_case():
    for case in CASES:
        assert hardware.has_nvidia_gpu(os.path.join(PCI, case["devices"])) is case["has_nvidia"], case


def test_gnome_follows_every_case():
    for case in CASES:
        with patch.object(system, "PCI_DEVICES", os.path.join(PCI, case["devices"])), \
                patch.object(system.Systeminfo, "_nvidia", None), \
                patch.object(system.Systeminfo, "_gpus", None):
            assert system.Systeminfo.has_nvidia_gpu() is case["has_nvidia"], case
