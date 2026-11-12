import os
import sys

# Make the repo root importable so `from tuna_installer_xfce import ...`
# works regardless of how pytest is invoked.
_XFCE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _XFCE)
# bootc_shared, the contract code shared with GNOME, for a test that imports
# it before it imports tuna_installer_xfce (whose __init__ does the same).
sys.path.insert(0, os.path.normpath(os.path.join(_XFCE, "..", "..", "shared", "python")))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_plan(monkeypatch):
    """No test asks a real fisherman for an install plan: the confirm page
    gets "no plan" (an older fisherman) unless a test gives it one."""
    from tuna_installer_xfce import core
    monkeypatch.setattr(core, "request_plan", lambda recipe: (None, "no plan in tests"))
