"""Where the contract data files are.

The files stay in `shared/<contract>/`: the compiled frontends and their
tests read them there. An installed package cannot reach `shared/`, so each
build copies the files in FILES to `bootc_shared/data/<contract>/`, with the
same relative path. path() looks in the installed place first, then in the
checkout. tests/unit/test_shared_python_package.py fails when a build does
not install a file of FILES.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
# Installed: beside the modules. Checkout: shared/python/bootc_shared -> shared/.
ROOTS = (os.path.join(_HERE, "data"), os.path.dirname(os.path.dirname(_HERE)))

# Each file a module of this package reads at run time, relative to shared/.
FILES = (
    "account/groups.json",
    "branding/copy-defaults.json",
    "progress/dry-run-transcript.ndjson",
    "recipe/encryption-choices.json",
)


def path(relative):
    """The absolute path of `relative` (one of FILES).

    When neither root has the file, the installed path is the answer, so
    the error of the open() that follows names the place a build must fill.
    """
    for root in ROOTS:
        candidate = os.path.join(root, *relative.split("/"))
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(ROOTS[0], *relative.split("/"))


def load_json(relative):
    with open(path(relative), encoding="utf-8") as stream:
        return json.load(stream)
