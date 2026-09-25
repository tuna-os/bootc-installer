# fisherman progress protocol

fisherman writes **newline-delimited JSON to stdout** and nothing else. One
event per line. This is the only progress interface a frontend gets; there is
no human-readable step prefix, and there never has been.

Canonical parser: [`progress_parser.py`](progress_parser.py). Every Python
frontend keeps a **byte-identical** copy, enforced by
`tests/unit/test_shared_progress.py` — the same arrangement
`shared/branding/` and `shared/recipe/` use. Non-Python frontends implement
the same semantics against this document.

## Events

Every event carries `type`, plus `timestamp` (RFC 3339) and `elapsed_ms`.
Consumers must ignore fields they do not know: the emitter is free to add
them.

| `type` | Fields | Meaning |
|---|---|---|
| `step` | `step`, `total_steps`, `step_name`, `cumulative_pct`, `weight_pct` | A pipeline step began |
| `substep` | `message` | Progress within the current step |
| `info` | `message` | Informational line |
| `recovery_key` | `key` | LUKS recovery passphrase, for `tpm2-luks` |
| `complete` | `message`, `boot_id` (optional) | Install finished |
| `error` | `message` | Terminal failure |

## Driving a progress bar

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

The canonical parser does exactly this. `complete` is what takes the bar to
100%: `cumulative_pct` only reaches 99 on the last step.

## Step names

`step_name` is fisherman's own English name (`Partitioning disk`,
`Installing OS`, …). The parser maps them to friendlier labels and falls
back to the raw name for ones it does not know, so a new step in fisherman
degrades to showing its real name rather than showing nothing.

One label names the product (`Installing {product}…`). Frontends **must**
call `set_product_name()` with the resolved branding name; the default is a
neutral `"the OS"`, never a distro. See `shared/branding/README.md`.

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
