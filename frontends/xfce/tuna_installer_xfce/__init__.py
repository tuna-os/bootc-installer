import os as _os
import sys as _sys

# bootc_shared is the contract code that this frontend shares with GNOME
# (shared/python/). The Flatpak copies it beside this package, so it is
# importable there. In a checkout it is three directories up; put it on the
# path here, so that the launcher, `python -m`, the tests and the harnesses
# all find it the same way.
_SHARED = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                        "..", "..", "..", "shared", "python")
if _os.path.isdir(_os.path.join(_SHARED, "bootc_shared")):
    _SHARED = _os.path.normpath(_SHARED)
    if _SHARED not in _sys.path:
        _sys.path.insert(0, _SHARED)

__version__ = "0.1.0"
