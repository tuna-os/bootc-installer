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

## `account/`

The first account: the supplementary groups that each frontend writes into
`user.groups` of the recipe, and the file where an ISO builder sets a
different list. `tests/unit/test_shared_account.py` holds `groups.json` to
the list that the GNOME frontend sends. A new frontend sends the list from
`groups.json`, reads the operator's list from
`<etc>/bootc-installer/recipe.json`, and adds a test that fails when its copy
of the list changes. See [account/README.md](account/README.md).

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

## `catalog/`

The image catalog (`images.json`): where a frontend looks for it, which
fields of a leaf go into the recipe, which image is selected at the start,
and when the installer makes an account. `resolve.py` is the reference
resolver, and `tests/unit/test_shared_catalog.py` runs it against
`fixtures/`. The reader that GNOME and XFCE ship is `bootc_shared.catalog`
(see `python/`). A new frontend reads `fixtures/catalog.json` with its own
parser in a test and compares the result with `fixtures/expected.json`. See
[catalog/README.md](catalog/README.md).

## `ci/`

Scripts and data for the workflows. `frontends.json` is the table of the
frontends: the app id, the Flatpak manifest, the builder image, and two
switches. `publish-flatpak.yml` publishes each frontend from its row, and
`frontend_table.py` reads the row. `fisherman_pins.py` moves the fisherman
submodule pin, the one pin. `flatpak_manifest.py` reads a Flatpak manifest
with its module includes, as flatpak-builder does, and checks its local
sources. `published_freshness.py` compares the served Flatpaks with `prod`.
`contract_version.py` computes the digest of the contract files and checks
the version (see "How a contract changes"). `tests/unit/test_ci_frontend_table.py`,
`tests/unit/test_ci_fisherman_pins.py` and
`tests/unit/test_ci_published_freshness.py` cover them. A new frontend adds
one row to `frontends.json`, and one `Publish (<name>)` job to `release.yml`.

## `completion/`

How the done page tells an installed system from a verified start (#269),
and the reader of a `fisherman verify --json` result. The done page says
"installed, restart required" and never "verified": only the new system
can check its own start. Each frontend renders `done_verification`, then
the line for fisherman's `receipt` event (`progress/receipt-cases.json`).
`bootc_shared.completion` is the Python reader, and
`tests/unit/test_shared_source_check.py` holds the case file to it. The
KDE, COSMIC and Niri readers read the same `verification-cases.json`. A
new frontend shows the line on its done page and ports the reader. See
[completion/README.md](completion/README.md).

## `e2e/`

The end-to-end gate. Each frontend drives its real backend path to the Done
page. `check-recipe.py` then examines the recipe that the frontend wrote, and
`vm-install.sh` installs it and boots the result in a VM.
`tests/unit/test_e2e_shim.py` covers the fisherman shim, and `e2e.yml` runs
the gate on each push. `promote.yml` requires its jobs. A new frontend adds
an `E2E (<name>)` job and an entry in the install matrix of `e2e.yml`, and
the two job names in `REQUIRED_CHECKS`. See [e2e/README.md](e2e/README.md).

Each driver gives its frontend `e2e/catalog.json`, the one E2E catalog. A
new driver reads that file and picks a leaf from it.

## `flatpak/`

The Flatpak modules that more than one manifest builds. `go.json` is the Go
toolchain, and all six manifests list it by path. `fisherman.json` builds
fisherman from the submodule and installs its catalog and polkit policy. The
four frontend manifests list it by path, so the submodule gitlink is the only
fisherman pin. GNOME keeps its own fisherman module, because it installs the
catalog and the policy in other modules. flatpak-builder reads a source path
in these files from `shared/flatpak/`, not from the manifest directory.
`TestFishermanPin` in `tests/unit/test_shared_probe.py` and
`tests/unit/test_manifest_sources_are_arch_aware.py` cover them, and
`validate-flatpak.yml` resolves every include. A new frontend adds
`"../../../shared/flatpak/go.json"` and
`"../../../shared/flatpak/fisherman.json"` to its `modules`, and sets
`checkout-submodules` in its `ci/frontends.json` row.

## `i18n/`

The translation templates of KDE, Niri, XFCE and COSMIC. Each frontend
marks its text in the way of its own toolkit, and has a template in the
format of that toolkit: a Qt `.ts` file, a gettext `.pot` file, or the JSON
catalog of COSMIC. `templates.py` writes the templates from the sources, and
`tests/unit/test_frontend_translation_templates.py` fails when one is out of
date. A new frontend adds a target to `templates.py` and a lint that fails
on a bare string. `catalogs.py` writes the catalog of a language for each
frontend from its template and from `po/` of GNOME, and
`tests/unit/test_frontend_translation_catalogs.py` fails when a catalog is
out of date. Each frontend ships French. See [i18n/README.md](i18n/README.md).

## `network/`

The network check before an install that downloads its image:
`targets.json` holds the targets for each image reference, in order, the
timeout and the variables that turn the check off. The Python reader is
`bootc_shared.network`. A test in each frontend reads the file. A new
frontend reads the same file in its test. See
[network/README.md](network/README.md).

## `probe/`

How a frontend reads hardware facts: the disk list, the TPM, live media and
the minimum requirements all come from `fisherman probe --json`.
The Python reader is `bootc_shared.probe` (see `python/`).
`tests/unit/test_shared_probe.py` runs the reader against `fixtures/`, and
refuses a frontend that reads `lsblk` itself. `tests/unit/test_probe_frontend.py` covers the GNOME side.
A new frontend runs the command, reads the JSON, and points its capture at
a fixture with `BOOTC_INSTALLER_FAKE_PROBE`. The same command with
`--source` gives the check of the selected image (`capabilities`, #266) and
the images in this computer's bootc storage (`bootc_store`, #267);
`bootc_shared.source_check` reads them, and each frontend runs its reader
against `capabilities-cases.json` and `bootc-store-cases.json`. The
system that this computer runs can be the install source (`sourceReuse`):
each frontend runs its reader against `source-reuse-cases.json`. See
[probe/README.md](probe/README.md).

## `progress/`

The progress protocol: fisherman writes one JSON event on each line of
stdout. The Python parser is `bootc_shared.progress` (see `python/`), and
the JSON case files give the expected bar position for each event.
`tests/unit/test_shared_progress.py` runs the cases. A new frontend implements the parser in its own
language and runs it against `fraction-cases.json`,
`overall-pct-cases.json` and `dry-run-transcript.ndjson`. See
[progress/README.md](progress/README.md).

## `python/`

The package `bootc_shared`: the contract code that the two Python frontends
(GNOME and XFCE) import. It has the readers for `probe/` and `recipe/`, the
parser for `progress/`, the resolver for `branding/`, the groups of
`account/`, and the readiness stamp. It also has the logic that the two
frontends had each written and that had drifted: the catalog reader
(`catalog`), NVIDIA detection (`hardware`), the targets of the network
check (`network`), the stage and the command for fisherman
(`fisherman_host`), and the removal of the recovery key from a log
(`redact`). `tests/unit/test_shared_python_catalog.py` and
`tests/unit/test_shared_python_host.py` cover those. There is one copy. The data files stay
in their contract directories, because the other three frontends read them
there; `_data.py` lists the files that the package reads and finds them in
a checkout and in an installed tree. The GNOME build installs the package
and those files with `python/meson.build`. The XFCE Flatpak manifest copies
them. `tests/unit/test_shared_python_package.py` fails when a build does not
install a file, when a copy comes back in a frontend, and when a release
does not count a change to the package as a change to XFCE. A new Python
frontend installs the package beside its own, and adds its build to that
test. Do not copy a module.

The readiness stamp is a file that a frontend writes when its window is on
the screen, so that a test can tell a live process from a visible window.
`tests/unit/test_shared_readiness.py` covers the Python module. A frontend
in a different language writes the same file with the same fields; the
docstring of `python/bootc_shared/readiness.py` is the specification.

## `recipe/`

The recipe that each frontend writes for fisherman:
`fisherman-recipe.schema.json`, the encryption choices, and the reader for
`fisherman validate --json`. fisherman owns the rules; the schema must have
each field of fisherman's `Recipe` struct.
`tests/unit/test_shared_recipe_schema.py` examines that, and that no
frontend keeps a second copy. `tests/unit/test_shared_validate.py` and
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
five. `tests/unit/test_walkthrough_contract.py` covers the contract. The
Python harnesses (GNOME, XFCE, Niri) import this directory directly. They
share the pixel audit (`pixel_audit.py`) and the capture fixtures
(`capture_fixtures.py`: the cut transcript, the recovery event and the GIF
step). `tests/unit/test_walkthrough_pixel_audit.py` covers both. The
compiled harnesses (KDE, COSMIC) write their PNGs and a `texts.json`, and
their workflows run `report_from_pngs.py`. A report is strict: each
required screen shows on a page whose frame is present, readable, rendered
and not a copy of another frame, or the `screen_exemptions` of the
frontend's feature manifest exempt it with a reason. Else the screen is a
failure. `aggregate.py --strict` checks each strict report again against
its frames, and `walkthrough.yml` fails on a failure. A PNG-only report is
advisory. `tests/unit/test_walkthrough_strict.py` covers each case. A new
frontend adds a capture harness and a `screenshots-<name>.yml` workflow
that writes `walkthrough-<name>.json`, and `walkthrough.yml` adds it to the
page.

Each harness that shows an image list reads `capture-catalog.json`, which
names no real product. `tests/unit/test_capture_catalog.py` covers it.

## How a new frontend starts

1. Put the tree in `frontends/<name>/` with its own `AGENTS.md`. Do not add
   a `.github/` there.
2. Adopt the contracts in this order: `branding/`, `probe/`, `recipe/`,
   `progress/`, `tpm/`, then the readiness stamp (`python/`).
3. Add the capture harness (`walkthrough/`), then the end-to-end job
   (`e2e/`).
4. Add a column to [docs/PARITY.md](../docs/PARITY.md).

Where a contract has Python code, the code is in the `bootc_shared`
package (`python/`), and a Python frontend imports it. A Python frontend
does not keep a copy. A frontend in a different language implements the same
behaviour and runs it against the same fixtures.

## How a contract changes

A change to a contract changes all five frontends at once. These rules
keep that visible. A change to a file in `shared/` starts the test workflow
of each frontend (`tests/unit/test_ci_shared_path_filters.py`), so each
frontend reads the new fixture in the same pull request.

- **Add.** A new optional field, key or event is safe. Add it, add a
  fixture or a test case, and add an entry to `CHANGELOG.md`. The entry
  says which frontends use the addition and which do not yet.
- **Change the recipe schema.** fisherman owns the recipe. Change
  fisherman first, then the schema. Put the new sha256
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

`VERSION` holds the version of the contracts, in the form
MAJOR.MINOR.PATCH. One version covers all the contract files. A contract
file is each file in `shared/` that git tracks, except Markdown, `VERSION`,
and the CI tools in `ci/`, `browser/` and `e2e/`.
`ci/contract_version.py` keeps this list.

Each change to a contract file increases the version, in the same pull
request:

- **MAJOR** for a removal, or for a change that an old reader cannot read.
- **MINOR** for an addition, a deprecation, or a new recipe schema that adds
  a field.
- **PATCH** for a change that no reader sees in its fields: a corrected
  fixture value, a new test case, a fix in shared code.

The `CHANGELOG.md` entry of the change has two more lines, which
`python3 shared/ci/contract_version.py` prints:
`Contracts version:` with the new version, and `Contracts sha256:` with the
digest of the contract files. `tests/unit/test_shared_contract_docs.py`
fails when a contract file changes with no new entry, when the version in
the entry is not `VERSION`, and when the version is not greater than the
version on `dev`.
