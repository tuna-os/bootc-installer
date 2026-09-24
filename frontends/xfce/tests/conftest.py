import os
import sys

# Make the repo root importable so `from tuna_installer_xfce import ...`
# works regardless of how pytest is invoked.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
