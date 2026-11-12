"""The reference normaliser of shared/recipe/fixtures/compliance.json.

Two recipes that fisherman reads the same way can differ in their bytes: one
frontend writes `"composeFsBackend": false`, another leaves the key out. The
fixture's `normalise` table says which forms are the same, and this module is
the reference for the two rules. The C++, Rust and Go tests implement the
same two rules; shared/recipe/README.md ("The compliance fixture") describes
them.

1. `absent_equals`: a key at the path `key` whose value equals `value` is
   removed. The rows apply in the order of the table.
2. `absent_without`: an object at the path `key` that has no key `needs`
   after rule 1 is removed.

`canonical()` is the byte form that the tests compare: keys sorted, no
spaces, UTF-8.

    python3 shared/recipe/compliance.py < recipe.json
"""

import copy
import json
import os
import sys

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "compliance.json")


def load(path=FIXTURE):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def _parent(recipe, path):
    node = recipe
    for key in path[:-1]:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else None


def normalise(recipe, table=None):
    """A copy of `recipe` with the forms that fisherman reads as absent
    removed (the fixture's `normalise` table)."""
    table = load()["normalise"] if table is None else table
    out = copy.deepcopy(recipe)
    for row in table["absent_equals"]:
        parent = _parent(out, row["key"])
        last = row["key"][-1]
        # `False == 0` in Python; the rule compares JSON values, so a type
        # that differs is never equal.
        if (parent is not None and last in parent
                and type(parent[last]) is type(row["value"])
                and parent[last] == row["value"]):
            del parent[last]
    for row in table["absent_without"]:
        parent = _parent(out, row["key"])
        last = row["key"][-1]
        if parent is not None and isinstance(parent.get(last), dict) and row["needs"] not in parent[last]:
            del parent[last]
    return out


def canonical(recipe, table=None):
    """The normalised recipe as the bytes that the tests compare."""
    return json.dumps(normalise(recipe, table), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


if __name__ == "__main__":
    sys.stdout.write(canonical(json.load(sys.stdin)).decode("utf-8") + "\n")
