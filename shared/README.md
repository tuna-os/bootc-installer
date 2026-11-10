# shared/: the contracts between the frontends

Five frontends live in this repository. They do not share a toolkit or a
language. They share the contracts in this directory, and the fisherman
backend.

The rule is in the root [ROADMAP.md](../ROADMAP.md): logic goes into
fisherman, contracts and data go into `shared/`, and a frontend owns only
its native UI.

Each directory below is one contract. Each paragraph says what the contract
is, which test makes it true, and how a new frontend adopts it.
`tests/unit/test_shared_contract_docs.py` fails when a directory has no
section here.

[CHANGELOG.md](CHANGELOG.md) records each change to a contract. Read it
when you update a frontend.

## `branding/`

The product identity: name, id, hostname stem, URLs, artwork, and each line
of text that a product can change (`copy-defaults.json`). The order is
`branding.json` first, `os-release` second, neutral defaults last.
`tests/unit/test_shared_branding.py` runs the Python resolver against
`fixtures/`. `tests/unit/test_branding_parity.py` and
`tests/unit/test_copy_coverage.py` compare what each frontend renders. A new
frontend writes one resolver in its own language, runs it against
`fixtures/expected.json`, and reads each product string through it. See
[branding/README.md](branding/README.md).

## `browser/`

The harness that renders a frontend in a real browser, so that Playwright
can click through the wizard. This directory is test tooling, not a
contract that a frontend reads at run time. `browser-walkthrough.yml` runs
it; no unit test covers it. A new frontend adds an entry to `run.sh` when
its toolkit has a browser backend. See
[browser/README.md](browser/README.md).

## `ci/`

Scripts for the workflows: `fisherman_pins.py` moves every fisherman pin
together, and `published_freshness.py` compares the served Flatpaks with
`prod`. `tests/unit/test_ci_fisherman_pins.py` and
`tests/unit/test_ci_published_freshness.py` cover them. A new frontend adds
its Flatpak manifest to the lists in the two scripts.

## `e2e/`

The end-to-end gate. Each frontend drives its real backend path to the Done
page. `check-recipe.py` then examines the recipe that the frontend wrote, and
`vm-install.sh` installs it and boots the result in a VM.
`tests/unit/test_e2e_shim.py` covers the fisherman shim, and `e2e.yml` runs
the gate on each push. `promote.yml` requires its jobs. A new frontend adds
an `E2E (<name>)` job and an entry in the install matrix of `e2e.yml`, and
the two job names in `REQUIRED_CHECKS`. See [e2e/README.md](e2e/README.md).

## `probe/`

How a frontend reads hardware facts: the disk list, the TPM, live media and
the minimum requirements all come from `fisherman probe --json`.
`fisherman_probe.py` is the Python reader; GNOME and XFCE keep
byte-identical copies. `tests/unit/test_shared_probe.py` runs the reader
against `fixtures/`, compares the copies, and refuses a frontend that reads
`lsblk` itself. `tests/unit/test_probe_frontend.py` covers the GNOME side.
A new frontend runs the command, reads the JSON, and points its capture at
a fixture with `BOOTC_INSTALLER_FAKE_PROBE`. See
[probe/README.md](probe/README.md).

## `progress/`

The progress protocol: fisherman writes one JSON event on each line of
stdout. `progress_parser.py` is the Python parser, and the JSON case files
give the expected bar position for each event.
`tests/unit/test_shared_progress.py` runs the cases and compares the
copies of the parser. A new frontend implements the parser in its own
language and runs it against `fraction-cases.json`,
`overall-pct-cases.json` and `dry-run-transcript.ndjson`. See
[progress/README.md](progress/README.md).

## `readiness/`

The readiness stamp: a file that a frontend writes when its window is on
the screen, so that a test can tell a live process from a visible window.
`readiness.py` is the canonical copy; GNOME and XFCE keep byte-identical
copies. `tests/unit/test_shared_readiness.py` compares them. A new frontend
writes the same file with the same fields; the docstring of `readiness.py`
is the specification.

## `recipe/`

The recipe that each frontend writes for fisherman:
`fisherman-recipe.schema.json`, the encryption choices, and the reader for
`fisherman validate --json`. fisherman owns the rules; the schema must have
each field of fisherman's `Recipe` struct.
`tests/unit/test_shared_recipe_schema.py` examines that, and that the KDE copy
is byte-identical. `tests/unit/test_shared_validate.py` and
`tests/unit/test_encryption_choices.py` cover the reader and the choices.
`tests/unit/test_shared_contract_docs.py` fails when the schema changes
with no new entry in [CHANGELOG.md](CHANGELOG.md). A new frontend builds
the recipe in memory, sends it to `fisherman -` on stdin, and adds its
recipe to the checks in `e2e/`. See [recipe/README.md](recipe/README.md).

## `tpm/`

How to decide whether to offer the TPM encryption types. fisherman makes
the decision; this directory keeps the specification and the sysfs
fixtures. `tests/unit/test_shared_tpm.py` runs the fixtures. A new frontend
reads `tpm.usable` from the probe and does not read sysfs itself. See
[tpm/README.md](tpm/README.md).

## `walkthrough/`

The screen contract: the screens that every installer must show
(`parity_report.py`), and `aggregate.py`, which builds
[docs/walkthrough/](../docs/walkthrough/README.md) from the reports of all
five. `tests/unit/test_walkthrough_contract.py` covers the contract. A new
frontend adds a capture harness and a `screenshots-<name>.yml` workflow
that writes `walkthrough-<name>.json`, and `walkthrough.yml` adds it to the
page.

## How a new frontend starts

1. Put the tree in `frontends/<name>/` with its own `AGENTS.md`. Do not add
   a `.github/` there.
2. Adopt the contracts in this order: `branding/`, `probe/`, `recipe/`,
   `progress/`, `tpm/`, `readiness/`.
3. Add the capture harness (`walkthrough/`), then the end-to-end job
   (`e2e/`).
4. Add a column to [docs/PARITY.md](../docs/PARITY.md).

Where a contract has a Python file, a Python frontend keeps a
byte-identical copy and adds its path to the test that compares the copies.
A frontend in a different language implements the same behaviour and runs
it against the same fixtures.

## How a contract changes

A change to a contract changes all five frontends at once. These rules
keep that visible.

- **Add.** A new optional field, key or event is safe. Add it, add a
  fixture or a test case, and add an entry to `CHANGELOG.md`. The entry
  says which frontends use the addition and which do not yet.
- **Change the recipe schema.** fisherman owns the recipe. Change
  fisherman first, then the schema, then the KDE copy. Put the new sha256
  of the schema in the `CHANGELOG.md` entry.
- **Deprecate.** Do not remove a field, a key or a file in the commit that
  replaces it. First add a `CHANGELOG.md` entry with the word "Deprecated",
  the replacement, and the issue that tracks the removal. Readers keep
  support for the old form in that period.
- **Remove.** Remove the old form only after all five frontends use the
  replacement, and after one promotion to `prod` shipped the deprecation
  entry. The removal is a `CHANGELOG.md` entry with the word "Removed". For
  a recipe field, fisherman must stop support first: the schema cannot lose
  a field that fisherman's `Recipe` struct still has.

The contracts have no version number at this time. The date of the newest
`CHANGELOG.md` entry, and the sha256 of the recipe schema, identify the
state of the contracts.
