import os as _os
import sys as _sys

# bootc_shared is the contract code that this frontend shares with XFCE
# (shared/python/). The build installs it beside this package
# (shared/python/meson.build), so it is importable there. In a checkout it
# is in shared/python; put that on the path here, so that the tests, the
# capture harness and the E2E driver all find it the same way.
_SHARED = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "shared", "python")
if _os.path.isdir(_os.path.join(_SHARED, "bootc_shared")):
    _SHARED = _os.path.normpath(_SHARED)
    if _SHARED not in _sys.path:
        _sys.path.insert(0, _SHARED)
