"""The daemon backend encrypts the root: no `none`, and the TPM first.

The first install from this frontend stopped with "an unencrypted install
(none) is not supported yet" (tuna-os/tunaOS run 45639909696): the first
choice of the page was `none`.
"""

import os
import sys

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import app, core, pages  # noqa: E402,F401


class _Win:
    def refresh_nav(self):
        pass

    def selected_leaf(self):
        return None

    def layout_source(self):
        return None


@pytest.mark.parametrize(
    "backend, tpm, offered_none, chosen",
    [
        ("daemon", True, False, "tpm2-luks"),
        ("daemon", False, False, "luks-passphrase"),
        ("recipe", True, True, "none"),
    ],
)
def test_the_encryption_choices_follow_the_backend(monkeypatch, backend, tpm, offered_none, chosen):
    monkeypatch.setattr(core, "backend", lambda: backend)
    monkeypatch.setattr(core, "has_tpm", lambda: tpm)
    page = pages.SetupPage(_Win())
    assert ("none" in [r.value for r in page.enc_radios]) is offered_none
    assert page.enc_type() == chosen
