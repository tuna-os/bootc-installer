"""Shim: the parity report lives once in shared/walkthrough/parity_report.py.

This file used to carry its own copy of the screen contract and the report
writer. In the monorepo every frontend reports against the same spec from the
same module, so a keyword fix lands for all of them at once. The module name
and the `write_report(outdir, flavor, pages, harness)` signature are
unchanged, so capture-screens.py did not have to move.

Loaded by path rather than `import parity_report`, because this file IS the
`parity_report` that a sibling `import` resolves to first.
"""

import importlib.util
import os

_SHARED = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "..", "shared", "walkthrough", "parity_report.py"))

_spec = importlib.util.spec_from_file_location("_shared_parity_report", _SHARED)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
