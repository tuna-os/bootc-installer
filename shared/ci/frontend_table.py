#!/usr/bin/env python3
"""The per-frontend values that the publish workflows need, from one table.

frontends.json, next to this file, has one row per frontend:

    app-id                 the Flatpak app id
    manifest-path          the Flatpak manifest, from the repository root
    flatpak-builder-image  the flathub-infra/flatpak-github-actions image tag;
                           it must track the manifest's runtime and
                           runtime-version
    checkout-submodules    true when the manifest builds from the fisherman
                           submodule; every manifest does today (GNOME from
                           ../fisherman, the others through
                           shared/flatpak/fisherman.json)
    also-latest            true when the publish also moves the unqualified
                           `latest` tags (GNOME, for consumers that predate
                           the per-frontend tags)

The order of the rows is the order of the frontends everywhere else
(published_freshness.FRONTENDS, the outputs of release_changes.py).

publish-flatpak.yml runs this to turn its `frontend` input into the inputs
of publish-oci.yml:

    python3 shared/ci/frontend_table.py --frontend kde --github-output "$GITHUB_OUTPUT"

It prints one `<key>=<value>` line per column, booleans as true/false. A
frontend that is not in the table, or a row with a missing or mistyped
column, is an error and exits non-zero: the publish must not start from a
guess.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontends.json")
COLUMNS = {
    "app-id": str,
    "manifest-path": str,
    "flatpak-builder-image": str,
    "checkout-submodules": bool,
    "also-latest": bool,
}


class TableError(Exception):
    """The table, or the frontend asked for, is not usable."""


def load(path=TABLE):
    """{frontend: row}, in file order, with every column present and typed."""
    with open(path, encoding="utf-8") as stream:
        table = json.load(stream)
    if not isinstance(table, dict) or not table:
        raise TableError(f"{path}: expected a non-empty object of frontends")
    for name, row in table.items():
        if not isinstance(row, dict) or set(row) != set(COLUMNS):
            raise TableError(f"{path}: {name}: expected exactly the columns {sorted(COLUMNS)}")
        for column, kind in COLUMNS.items():
            value = row[column]
            if type(value) is not kind or (kind is str and (not value or "\n" in value)):
                raise TableError(f"{path}: {name}.{column}: expected a {kind.__name__}, got {value!r}")
    return table


def row_for(frontend, table):
    if frontend not in table:
        raise TableError(f"unknown frontend {frontend!r}; the table has {', '.join(table)}")
    return table[frontend]


def render_outputs(row):
    def text(value):
        return ("true" if value else "false") if isinstance(value, bool) else value
    return "".join(f"{column}={text(row[column])}\n" for column in COLUMNS)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--table", default=TABLE)
    parser.add_argument("--github-output", help="append the outputs to this file")
    args = parser.parse_args(argv)
    try:
        outputs = render_outputs(row_for(args.frontend, load(args.table)))
    except (TableError, OSError, ValueError) as error:
        print(f"::error::{error}")
        return 1
    sys.stdout.write(outputs)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as stream:
            stream.write(outputs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
