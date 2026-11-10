import os
import sys

# Make the repo root importable so `from tuna_installer_xfce import ...`
# works regardless of how pytest is invoked.
_XFCE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _XFCE)
# bootc_shared, the contract code shared with GNOME, for a test that imports
# it before it imports tuna_installer_xfce (whose __init__ does the same).
sys.path.insert(0, os.path.normpath(os.path.join(_XFCE, "..", "..", "shared", "python")))
