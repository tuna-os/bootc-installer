# Completion: installed is not verified

This contract is #269. An install that exits 0 wrote a disk. That does not
show that the disk starts, or that the system that starts is the image
that the user selected. fisherman keeps the two claims apart
([`fisherman/docs/RECEIPT.md`](../../fisherman/docs/RECEIPT.md),
tuna-os/fisherman#385):

| Claim | Who makes it | Evidence |
|---|---|---|
| installed, restart required | the install: fisherman exits 0 | the pipeline ran to the end |
| start verified | `fisherman verify --json` on the installed system | the `bootc status` of the installed system, compared with the installation receipt |

## The done page

After an install that exits 0, each frontend shows `done_title`,
`done_subtitle` and `done_verification`. The last line says that nothing
checked the new system yet, where the new system records its first start
(`/var/lib/fisherman/boot-receipt/`), and that `fisherman verify --json`
on that system compares the record with the receipt. The check covers the
identity of the image only.

- A done page never says "verified". The live installer cannot see the
  start of the new system: its own `bootc status` describes the live
  system, not the target.
- A failed or cancelled install does not show the line.
- The installer runs no `bootc` command and reads no file of the new
  system. Nothing is uploaded.

The installed system does not have this installer. A first-boot viewer of
the result does not exist yet. On the installed system, run
`fisherman verify --json` as root, or read
`/var/lib/fisherman/boot-receipt/verification.json` when
`fisherman verify --write` made it.

## The reader of a result

A viewer on the installed system reads a `fisherman verify --json`
result. Each language has a reader, and each reader gives the same view
for the same result:

| State | When |
|---|---|
| `verified` | outcome `verified`, evidence `live_status` or `collected_status`, and no check is `mismatch` |
| `mismatch` | outcome `mismatch`: a different image, deployment, platform or update reference started, or the expected image is staged, cached or the rollback entry |
| `unsupported` | outcome `unsupported`, or a result `version` other than 1 |
| `unavailable` | outcome `unavailable`; also a malformed result, an unknown outcome, a result of a different install (`other_install`), and a `verified` result that has a `mismatch` check |
| `pending` | outcome `not-yet-run`: the new system did not start yet |

`reason` is fisherman's code. An unknown code becomes `unknown`. When the
caller knows the install id, a result with a different `install_id` is
`unavailable`. That is how a reader refuses the result of an earlier
install.

[`verification-cases.json`](verification-cases.json) holds the cases. The
fixtures in `fixtures/` are fisherman's golden results
(`internal/receipt/testdata/results/`), and six `frontend-*` files that
this repository made: a result that is not JSON, version 2, a different
schema, an unknown outcome, an unknown reason, and a `verified` outcome
with a `mismatch` check. No fixture makes a verified start from nothing:
each `verified` case is a fisherman golden result.
`../probe/generate-source-check-cases.py` writes the case file.

| Frontend | Reader | Test |
|---|---|---|
| GNOME, XFCE | `bootc_shared.completion` | `tests/unit/test_shared_source_check.py` |
| KDE | `sourcecheck::verification` (`src/sourcecheck.{h,cpp}`) | `tests/test_backend.cpp` (`verificationCases`) |
| COSMIC | `source_check::verification` | `cargo test source_check` |
| Niri | `readVerification` (`installer/sourcecheck.go`) | `go test -run Verification` |

No page reads a result today, because no page runs on the installed
system.

## What is not here yet

- fisherman reports the receipt in its install log as a line of text, not
  as an event. So the done page cannot say that this install wrote a
  receipt, or show its install id. A `receipt` progress event would let it
  do that.
- No frontend runs on the installed system, so no frontend shows a
  verification result.
