# fisherman progress protocol

fisherman writes **newline-delimited JSON to stdout** and nothing else. One
event per line. This is the only progress interface a frontend gets; there is
no human-readable step prefix, and there never has been.

Canonical parser: [`progress_parser.py`](progress_parser.py). Every Python
frontend keeps a **byte-identical** copy, enforced by
`tests/unit/test_shared_progress.py` — the same arrangement
`shared/branding/` and `shared/recipe/` use. Non-Python frontends implement
the same semantics against this document.

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
you change `progress_parser.py`.

[`overall-pct-cases.json`](overall-pct-cases.json) does the same for events
that carry `overall_pct`, and for a stream without it that must fall back.
The same script writes it, and the same five test suites read it. It is a
separate file because fisherman's tests replay `fraction-cases.json`
through its own computation of `overall_pct`.

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
| `complete` | `message`, `boot_id` (optional), `overall_pct` | Install finished |
| `error` | `message` | Terminal failure |

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
