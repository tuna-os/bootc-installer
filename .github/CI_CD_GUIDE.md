# CI/CD Guide — bootc-installer monorepo

Reference for every workflow in this repository, the promotion/release flow,
and the release qualification runbook. The narrative version of the release
flow is [`docs/RELEASE.md`](../docs/RELEASE.md); this page is the index.

---

## Branches

```
feature/xyz ──PR──▶ dev ──promote.yml (all checks green + soak)──▶ prod ──▶ release.yml
```

- All PRs target `dev`. Merge queue is enabled on `dev`.
- `prod` is a fast-forward of `dev`, moved only by `promote.yml`. Never push
  to it by hand and never open a PR against it.
- Bots push `[skip ci]` commits to `dev` (refreshed screenshots, refreshed
  walkthrough). Promotion skips those when picking a candidate.

---

## Workflows

### Validation (run on PRs and pushes to `dev`)

| Workflow | Job names (as the promotion gate sees them) | Scope |
|---|---|---|
| `python-test.yml` | `Unit Tests (no display)`, `UI Integration Tests (offscreen GTK)` | GNOME frontend. Coverage gate `--cov-fail-under` is a ratchet; never lower it. |
| `go-test.yml` | `Unit Tests` | fisherman submodule: vet, tests, 20% coverage floor, race detector. |
| `flatpak.yml` | `Build (production)`, `Build (production, aarch64)`, `Build (devel)` | GNOME Flatpak bundles, kept as artifacts. On a `dev` push also refreshes the `latest-dev` **pre-release**. Also `workflow_call`, used by `release.yml`. |
| `flatpak-frontends.yml` | `kde / publish`, `cosmic / publish`, … | Build-only (`publish: false`) Flatpak of each imported frontend whose tree changed, x86_64. |
| `screenshots-gnome.yml` | `Screenshots (gnome)` | Renders every GNOME page under Xvfb, pixel audit, parity report. Commits to `docs/screenshots/` on `dev`. |
| `screenshots-kde.yml` | `Screenshots (kde)` | Same for `frontends/kde` (Fedora container, KF6). |
| `screenshots-cosmic.yml` | `Screenshots (cosmic)` | Same for `frontends/cosmic` (lavapipe). Only job that compiles the crate. |
| `screenshots-niri.yml` | `Screenshots (niri)` | Same for `frontends/niri` (PyQt6 offscreen, Quickshell stubs). |
| `screenshots-xfce.yml` | `Screenshots (xfce)` | Same for `frontends/xfce` (GTK3 under Xvfb), plus its pytest suite. |
| `ci-niri.yml` | `Go backend (niri)` | gofmt / vet / build / test for `frontends/niri/installer`. |
| `cargo-sources-cosmic.yml` | `cargo-sources matches Cargo.lock (cosmic)` | Offline cargo vendoring stays in sync with `Cargo.lock`. |
| `cargo-test-cosmic.yml` | `Cargo Tests (cosmic)` | `cargo test` for `frontends/cosmic`. The tests open no window; the e2e test is `#[ignore]`d and runs from `e2e.yml`. |
| `e2e.yml` | `E2E (gnome)`, `E2E (kde)`, `E2E (cosmic)`, `E2E (niri)`, `E2E (xfce)`, `E2E (install <frontend>)` | The gate that proves the installers work: each frontend drives its real backend launch path to Done against the real fisherman's validation, then the recipe it produced is installed onto a loop disk and booted in QEMU. See `shared/e2e/README.md`. |
| `recipe-compliance.yml` | `Recipe compliance (gnome)`, `(kde)`, `(cosmic)`, `(niri)`, `(xfce)`, `Recipe compliance` | Drives each case in `shared/recipe/fixtures/compliance.json` through the recipe builder of each frontend and compares the recipes byte for byte. The GNOME job also sends each expected recipe to `fisherman validate --json --partial`. No path filter. `Recipe compliance` is in `REQUIRED_CHECKS`. See `shared/recipe/README.md`. |
| `browser-walkthrough.yml` | `Browser walkthrough (gnome)`, `(xfce)`, `(niri)` | Playwright walks every wizard page in a browser: GNOME and XFCE through GTK Broadway, Niri as a WebAssembly build. The `niri` leg is advisory (`continue-on-error`). See `shared/browser/README.md`. |
| `wasm-kde.yml` | `Build KDE frontend for wasm` | Build check: compiles `frontends/kde` with Qt for WebAssembly and Emscripten. Nothing is served yet. |
| `wasm-cosmic.yml` | `COSMIC wasm check (advisory)` | Compiles `frontends/cosmic` for `wasm32-unknown-unknown` against the forks pinned in `frontends/cosmic/web/cargo-patch.toml`. Advisory: not in `REQUIRED_CHECKS`, and on `dev` the job stays green with a warning. |
| `sbom.yml` | `SBOM (<frontend>)` | SPDX SBOM of the Flatpak of each frontend. A dry run on PRs and `dev` pushes that change an SBOM input. `release.yml` calls it and attaches the files to the release. |
| `validate-flatpak.yml` | `Validate Flatpak manifests` | GNOME manifests are well-formed with required fields. |
| `actionlint.yml` | `actionlint` | Workflow syntax. |
| `actions-security.yml` | `lockfile`, `zizmor` | `gh actions-lock --verify` against `.github/workflows/actions.lock`, and the zizmor security lint of the workflows. Runs on every PR. See `docs/RELEASE.md`, "Action pinning". |
| `ste.yml` | `ste` | Simplified Technical English over every `.md`, budget in `.ste-budget` (a ratchet; the monorepo budget is the sum of the five repos'). |
| `nightly.yml` | — | Weekly test sweep of `dev` and `prod`. |
| `drop-bot-review-requests.yml` | — | Stops CODEOWNERS review requests on bot PRs. |

### Documentation

| Workflow | What |
|---|---|
| `walkthrough.yml` | After any screenshot job on `dev` (and daily): downloads the latest green `gui-screenshots-<frontend>` artifact of every frontend, runs `shared/walkthrough/aggregate.py`, checks that the page has no STE finding (the commit is `[skip ci]`, and `.ste-budget` is exact), commits `docs/walkthrough/`. |

### Monitoring

| Workflow | Trigger | What |
|---|---|---|
| `published-freshness.yml` | daily 07:23 UTC; manual | Checks that the tuna-os Flatpak remote serves each frontend from the build that `prod` last released (`shared/ci/published_freshness.py`). When a frontend is stale, the job fails and opens or updates one issue labelled `published-freshness`. It closes that issue when all frontends match again. |

### Promotion and release

| Workflow | Trigger | What |
|---|---|---|
| `promote.yml` | completion of any validation workflow on `dev`; hourly catch-up; manual | Gate: candidate is newest non-`[skip ci]` `dev` commit, descends from `prod`, older than `SOAK_MINUTES` (the job sleeps out the remainder), every check run complete and green, every `REQUIRED_CHECKS` name present. Then fast-forwards `prod` and dispatches `release.yml`. |
| `release.yml` | dispatch on `prod` (from promote); `v*` tag push; manual on `prod` | Builds GNOME bundles via `flatpak.yml`, cuts the `vYYYY.MM.DD-<sha>` release marked `--latest`, verifies the `/releases/latest/download/` URLs, then publishes each changed frontend's Flatpak. |
| `publish-flatpak.yml` | `workflow_call` from release / frontends validation; manual | One frontend (the `frontend` input) → `ghcr.io/tuna-os/bootc-installer:<frontend>` and the tuna-os Flatpak remote, through `publish-oci.yml`. The per-frontend values are in `shared/ci/frontends.json`. |

Names matter: `promote.yml` lists workflow *names* in its `workflow_run`
trigger and job *names* in `REQUIRED_CHECKS`. Renaming a job or workflow
means updating both.
`tests/unit/test_promote_gate.py` fails when a name in one of
the two lists matches nothing, and when a workflow that runs on `dev` is
absent from the trigger list (`docs/RELEASE.md`, "Knobs").

---

## Release process

There is no manual release step. A `dev` commit that passes every check and
sits for the soak window is promoted and released automatically. See
[`docs/RELEASE.md`](../docs/RELEASE.md) for the escape hatches (`force`,
promoting a specific sha, hotfix tags, rollback, pausing).

Release assets:

| Asset | Contents |
|---|---|
| `org.bootcinstaller.Installer.flatpak` | GNOME, production app id, x86_64 |
| `org.bootcinstaller.Installer-aarch64.flatpak` | GNOME, production app id, aarch64 (absent if that build failed) |
| `org.bootcinstaller.Installer.Devel.flatpak` | GNOME, devel app id, x86_64 |

The other four frontends are distributed through the tuna-os Flatpak remote
(`https://tunaos.org/flatpak/index/static`), not as release assets.

---

## Release qualification runbook

### Software-only (automated in CI; reproducible locally)

```bash
./QUALIFY_SOFTWARE.sh     # GNOME: manifests, unit + UI tests, fisherman tests, both Flatpaks
just capture              # GNOME screenshot walkthrough, as screenshots-gnome.yml runs it
just walkthrough          # cross-frontend parity page from the committed captures
```

All of it must be green before `promote.yml` will move `prod`; running it
locally is for diagnosing a red `dev`, not a step in releasing.

### Hardware-only checks (manual, not gated in CI)

| Check | How to test |
|-------|-------------|
| TPM2 LUKS enrolment | Install with `tpm2-luks` on real hardware; verify no password prompt on reboot |
| Recovery key display | Install with `tpm2-luks-passphrase`; confirm key shown and copyable in GUI |
| Passphrase fallback | Install with `luks-passphrase`; verify passphrase prompt on reboot |
| GRUB boot (XFS root) | Install with `filesystem=xfs`; verify GRUB loads from ext4 `/boot` |
| systemd-boot (btrfs/composefs) | Install with `composeFsBackend=true`; verify `bootctl status` clean |
| Offline ISO | Boot from live ISO with embedded OCI; verify install completes without internet |
| Post-reboot WiFi | Install on machine with saved WiFi; verify auto-reconnect after reboot |

The VM install matrix for the backend lives in `tuna-os/fisherman`
(`bootcrew-vm.yml`); the live-ISO smoke test for every frontend lives in
`tuna-os/tunaOS` (`installer-smoke.yml`).
