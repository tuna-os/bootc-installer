# fisherman progress protocol

fisherman writes **newline-delimited JSON to stdout** and nothing else. One
event per line. This is the only progress interface a frontend gets; there is
no human-readable step prefix, and there never has been.

The Python parser is
[`bootc_shared.progress`](../python/bootc_shared/progress.py). The two
Python frontends import that one module, and
`tests/unit/test_shared_progress.py` runs it against the case files below.
Non-Python frontends implement the same semantics against this document.

fisherman now computes the bar and names each step itself: `overall_pct`
and `step_id` (below) are authoritative. The derivation in this parser, and
in the four other frontends, is only the fallback for a fisherman that does
not send them yet. ROADMAP.md (consolidation step F1) removes it once that
support goes.

[`fraction-cases.json`](fraction-cases.json) pins the bar position after
each event in a set of event sequences. `generate-fraction-cases.py`
writes it from the canonical parser. Every frontend's tests read it: the
Python tests, COSMIC's `cargo test`, KDE's backend tests and Niri's
`tests/progress-fraction-test.mjs`. A change to the bar in one parser
therefore fails the other four until they follow. Regenerate the file after
you change the parser.

[`overall-pct-cases.json`](overall-pct-cases.json) does the same for events
that carry `overall_pct`, and for a stream without it that must fall back.
The same script writes it, and the same five test suites read it. It is a
separate file because fisherman's tests replay `fraction-cases.json`
through its own computation of `overall_pct`.

[`error-cases.json`](error-cases.json) pins what a parser keeps of the
`error` event: the last one, as `message`, `code` and `field`. A part that
is missing or is not a string is `""`. The event does not move the bar.
The same script writes the file, and the same five test suites read it.

[`receipt-cases.json`](receipt-cases.json) pins what a parser keeps of the
`receipt` event, and the lines of the done page. See "The receipt event"
below. The same script writes the file, and the same five test suites read
it.

[`source-reuse-cases.json`](source-reuse-cases.json) pins what a parser
keeps of the `source_reuse` events, the lines of the progress page and the
cancel question. See "The copy of this computer's system" below. The same
script writes the file, and the same five test suites read it.

## Events

Every event carries `type`, plus `timestamp` (RFC 3339) and `elapsed_ms`.
Consumers must ignore fields they do not know: the emitter is free to add
them.

| `type` | Fields | Meaning |
|---|---|---|
| `step` | `step`, `total_steps`, `step_name`, `step_id`, `cumulative_pct`, `weight_pct`, `overall_pct` | A pipeline step began |
| `substep` | `message`, `overall_pct` | Progress within the current step |
| `info` | `message` | Informational line |
| `recovery_key` | `key` | LUKS recovery passphrase, for `tpm2-luks` |
| `receipt` | `version`, `written`, `install_id`, `path`, `first_boot_check`, `reason` | What the install did with the installation receipt (tuna-os/fisherman#441) |
| `source_reuse` | `version`, `phase`, `digest`, `platform`, `source`, `destination`, `destination_digest`, `estimate`, `measured`, `code`, `reason` | The copy of this computer's system before the first step (tuna-os/fisherman#384) |
| `complete` | `message`, `boot_id` (optional), `overall_pct` | Install finished |
| `error` | `message`, `code` (optional), `field` (optional) | Terminal failure. `code` and `field` are those of `fisherman validate` (`fisherman/docs/VALIDATE.md`), when the failure has one |

## Driving a progress bar

**Use `overall_pct` when the event has it.** fisherman puts it on every
`step`, `substep` and `complete` event (tuna-os/fisherman#270): the bar
position, 0–100, with two decimals. It never decreases, and it stays at or
below 99 until `complete`, which is 100. fisherman computes it in
`internal/progress/bar.go`, a port of this parser. It also moves the bar
through the Flatpak copy (`Copying Flatpak data: N%`), which the derivation
below does not. A frontend shows it as it stands: clamped to 0–100, and
never lower than the bar already is.

The rest of this section is the fallback for an event without
`overall_pct`, from a fisherman older than that change.

**Use `cumulative_pct`. Do not derive the bar from `step / total_steps`.**

Two independent reasons:

1. **`total_steps` is not a constant.** `cmd/fisherman/main.go` computes it
   from the recipe: a base of 8, minus 3 for a manual layout, plus one each
   for LUKS setup, TPM2 enrolment, and formatting a separate `/var` disk.
2. **The steps are wildly unequal.** `Installing OS` carries 87% of a cold
   install's weight (68% when the image is already pulled); five of the other
   steps carry 0%. A bar advanced one-nth per step sits near zero for the
   entire visible install and then jumps.

`cumulative_pct` is the bar position (0–100) at the *start* of the step, and
`weight_pct` is that step's share. Within a step, interpolate from `substep`
messages — `Pulling image: layer 23/71` is the one that matters, because it
covers the long pull:

```
fraction = (cumulative_pct + (done / total) * weight_pct) / 100
```

The canonical parser does this, but gives the pull only the first 60% of
the step (`_PULL_SHARE`). The rest of the step is for the phases after the
pull: OCI export, deploy and bootloader. They have no counter, so the parser
gives each phase message a fixed position in what is left of the step
(`_PHASE_MILESTONES`). An offline install pulls nothing, so these phases get
the whole step. Before this change, the bar stayed at 1% for about ten
minutes on an offline install (#115). The bar never moves backwards inside a
step. `complete` is what takes the bar to 100%: `cumulative_pct` only
reaches 99 on the last step.

## Step names

`step_name` is fisherman's own English name (`Partitioning disk`,
`Installing OS`, …). `step_id` is a stable id for it (`partition`,
`install_os`, …). fisherman never renames or reuses an id, and leaves
`step_id` out for a step name it has no id for.

**Label a step by its `step_id`.** The label is the branding copy key
`step_<step_id>` (`shared/branding/README.md`, "Install steps"), so a
product can rebrand it. A Python frontend gives the parser a resolver with
`set_step_label_resolver()`. When the event has no `step_id`, or the copy
has no line for it, the frontend falls back to the step name. Thus a new
step in fisherman shows its real name, not nothing.

The parser's own step-name table is that fallback for a fisherman without
`step_id`. Its labels are the same as the copy defaults. One of them names
the product (`Installing {product}…`): frontends call `set_product_name()`
with the resolved branding name. The default is a neutral `"the OS"`, never
a distro.

## The receipt event

fisherman sends one `receipt` event inside the `Configuring installed
system` step ([`fisherman/docs/RECEIPT.md`](../../fisherman/docs/RECEIPT.md)).
The event does not move the bar, and it does not decide the outcome: the
exit code does. A parser keeps the last one as `{state, install_id,
reason}`:

| `state` | When |
|---|---|
| `check_set_up` | `written` and `first_boot_check` are true |
| `written_no_check` | `written` is true and `first_boot_check` is not |
| `not_written` | `written` is false |
| `unreadable` | a `version` other than the number 1, a `written` that is not a boolean, or a written receipt without an install ID of 32 lowercase hex digits |

`install_id` is set only for a written receipt. `reason` is fisherman's
code, or `""` when the event has none or the value is not a code.

After an install that exits 0, the done page shows `done_verification`,
then the line for the receipt: `done_receipt_<state>`, with the install ID
as `{value}`. Without a `receipt` event, the line is `done_receipt_none`.
When fisherman did not write the receipt or did not set up the first-boot
check, a reason line follows: `done_receipt_reason_<reason>`. A code that
the copy does not know gets `done_receipt_reason_unknown`. No
line says that the new system started: only `fisherman verify --json` on
that system can say so. A failed or cancelled install shows no receipt
line.

The first six cases of `receipt-cases.json` are fisherman's own events
(`internal/progress/testdata/receipt-events.ndjson`), and a test holds the
file to them. `bootc_shared.completion.receipt_lines()` is the canonical
choice of lines. GNOME and XFCE call it. KDE (`sourcecheck::receiptLines`),
COSMIC (`source_check::receipt_lines`) and Niri (`receiptLines` in
`ui/progress.js`) port it.

## The copy of this computer's system

With `sourceReuse` in the recipe, fisherman copies this computer's system
into containers-storage before the first step
([`fisherman/docs/SOURCE-REUSE.md`](../../fisherman/docs/SOURCE-REUSE.md)).
It reports the copy in `source_reuse` events. A parser keeps one view of
them:

| Field | From |
|---|---|
| `phase` | the last `planned`, `copying`, `verified` or `failed`; `unreadable` for a `version` other than the number 1 |
| `required_bytes` | `estimate.required_bytes`: the free space that the copy needs |
| `destination_digest` | `verified`: the digest of the copy, `sha256:` and 64 lowercase hex digits, else `""` |
| `copy_ms`, `used_bytes` | `verified`: `measured.copy_ms`, and the larger of the two peaks of `measured` (the sum on two filesystems) |
| `code` | `failed`: the `source_reuse_*` code |
| `released` | `released`: `removed`, `remove_failed`, or `unknown` for another reason |
| `destination` | the copy in containers-storage |

A count that is not a whole number of 0 or more is null. A phase that the
parser does not know changes nothing. `released` can come before `failed`:
a cancel removes the copy while bootc still runs.

The progress page shows the lines of
`bootc_shared.progress.source_reuse_lines()`. The space line uses GiB with
one decimal, and the time line whole seconds. A failed copy shows
`progress_reuse_failed_<code without source_reuse_>`, or
`progress_reuse_failed_unknown` for a code that the copy does not know.

The events do not move the bar. fisherman sends no `overall_pct` for the
copy, so the bar keeps its start state until the first step: it pulses,
or it stays at 0.

The copy runs before the first disk step. While no step has started and
the copy did not fail, `copy_cancel()` is true, and the cancel question
says `progress_reuse_cancel`: the installer stops the copy and removes it,
and the disk does not change. fisherman then removes the copy, writes
`released` and maybe `failed`, and exits 130.

## How an install ended

The exit code of the wrapper decides the outcome, never a `complete`
event. fisherman can write `complete` and exit non-zero, for example when
the teardown fails. The rule:

| Exit | Outcome |
|---|---|
| 0 | succeeded, also after a cancel that came too late |
| 130 | cancelled: fisherman's own code for a cancel |
| a signal (or a shell's 128 + n) after the user confirmed a cancel | cancelled: the frontend signalled the wrapper |
| another code after the user confirmed a cancel | failed: fisherman failed before the cancel reached it |
| another code, or a signal, without a cancel | failed |

[`outcome-cases.json`](outcome-cases.json) pins the rule. GNOME and XFCE
call `bootc_shared.progress.install_outcome()`. KDE
(`InstallerController::outcomeOf`), COSMIC (`install_outcome`) and Niri
(`installOutcome` in `ui/progress.js`) test their rule against the file.
Only a succeeded install shows the receipt lines.


## Recovery key in a log

The `recovery_key` event holds the key that unlocks the disk. A frontend
shows the key on its done page and keeps it in memory until the user
confirms that it is saved. A frontend must not write the key to a log file,
and must not put it in a copy of the log that leaves the installer (the
clipboard, a log dialog). A user attaches a log to a bug report.

A log line keeps the event and loses the value:
`{"type":"recovery_key","key":"[redacted]",...}`. The rules, in order, for
each line:

1. In a line that contains `"recovery_key"`, replace the value of each
   `"key"` string with `[redacted]`. Keep the spaces around the colon.
2. Replace the text after `Recovery key:` with `[redacted]`.
3. When the frontend knows the key, replace each occurrence of the key.

[`recovery-key-cases.json`](recovery-key-cases.json) has the key, the
placeholder, the redacted event and a list of single lines with the
expected result. [`recovery-key-transcript.ndjson`](recovery-key-transcript.ndjson)
is a short install with one `recovery_key` event. A frontend that keeps a
log sends the transcript through its log writer and compares the file:
the key is not there, the redacted event is, and each other line is
unchanged. GNOME (`tests/unit/test_recovery_key_log_fixture.py`), KDE
(`frontends/kde/tests/test_backend.cpp`), COSMIC (`src/redact.rs`), Niri
(`installer/redact_test.go`) and XFCE
(`frontends/xfce/tests/test_recovery_key_log.py`) do this. GNOME and XFCE
use one function, `bootc_shared.redact`.

## Fixture

[`dry-run-transcript.ndjson`](dry-run-transcript.ndjson) is a representative
uncached auto-layout install (8 steps, no encryption). It is **generated from
fisherman's own emitter and weight profile**, not written by hand, so it
cannot drift from the wire format; `timestamp` and `elapsed_ms` are frozen so
the fixture is stable. The XFCE frontend plays it for
`TUNA_INSTALLER_DRY_RUN`, which is also what the screenshot harness captures.

Hand-written fixtures are how this went wrong the first time: the XFCE bar
parsed a `[n/9]` prefix fisherman does not emit, and its fixture was written
in that same shape — so the screenshot harness rendered a bar advancing
through a format no install produces, while the bar on a real install never
moved at all.
