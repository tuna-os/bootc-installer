# Release flow: dev → validate → prod

This repository ships five installer frontends from two branches:

| Branch | Role | Who pushes to it |
|---|---|---|
| `dev` | Integration. Every PR targets it. | People, via PRs. Bots push `[skip ci]` screenshot refreshes. |
| `prod` | What ships. Always a fast-forward of `dev`. | Only `promote.yml`. Nobody pushes to `prod` by hand. |

Everything between the two is automated. The only manual actions that exist
are escape hatches, listed at the end.

## The pipeline

```
PR ──merge──▶ dev ──validate──▶ promote.yml ──fast-forward──▶ prod ──▶ release.yml
                                    ▲                                     │
                    Flatpak, Python Tests, Go Tests,                      ├─ GitHub release (GNOME bundles, --latest)
                    Screenshots (×5), Flatpak (frontends),                └─ Publish Flatpak (×5) to the tuna-os remote
                    CI (niri backend), cargo-sources (cosmic)
```

### 1. Validate on `dev`

Every push to `dev` runs the validation workflows. A PR runs the same set
before merge, so `dev` is rarely red, but the promotion gate reads the checks
on the actual `dev` commit, never the PR's.

| Workflow | Gates | Runs on |
|---|---|---|
| `flatpak.yml` | GNOME production (x86_64 + aarch64) and devel bundles build | every push |
| `python-test.yml` | GTK frontend unit + UI tests, coverage ratchet | every push |
| `go-test.yml` | fisherman submodule vet + tests + race | every push |
| `flatpak-frontends.yml` | kde / cosmic / niri / xfce Flatpaks build (publish=false) | when that frontend changed |
| `screenshots-*.yml` | each frontend launches, renders every page, pixel audit passes | when that frontend changed |
| `ci-niri.yml`, `cargo-sources-cosmic.yml` | frontend-specific checks | when relevant |
| `walkthrough.yml` | cross-frontend parity page regenerates | after any screenshot job |

A push to `dev` also refreshes the `latest-dev` **pre-release** with the GNOME
devel bundle. That is the only release-like thing `dev` does. Nothing on
`dev` reaches `/releases/latest/` or the Flatpak remote any more.

### 2. Promote (`promote.yml`)

Fires when any validation workflow completes on `dev`, every hour as a
catch-up (the completion usually lands before the soak has elapsed, so the
hourly tick is what actually ships most commits), and on demand. Each firing:

1. Picks the candidate: the newest `dev` commit that is not a bot
   `[skip ci]` commit (those carry no checks and must not stall promotion).
2. Refuses to move `prod` anywhere but forward: the candidate must descend
   from the current `prod`. There is no rewind path in CI.
3. Waits out the **soak window** (`SOAK_MINUTES`, 30 by default) so an
   immediate fix-up push supersedes the commit before it ships.
4. Reads every check run on the candidate through the Checks API and
   requires: none still running, none failed/cancelled/timed out, and each
   name in `REQUIRED_CHECKS` present and successful. Path-filtered jobs are
   not required by name: when they did not run there is nothing to validate,
   and when they did run, a red one blocks like any other.
5. If all of that holds, fast-forwards `prod` to the candidate and
   dispatches `release.yml` on `prod`.

Early firings (checks still running, soak not elapsed) exit green with the
reason in the job summary. Only the last workflow to finish on a commit sees
"everything complete", and that firing promotes.

`prod` is created by the first successful promotion. Nothing needs to exist
beforehand.

### 3. Release (`release.yml`)

Runs only on `prod` (dispatched by promote.yml) or on a hand-pushed `v*` tag.
It refuses any other ref, and refuses a dispatch whose `expected_sha` no
longer matches `prod` HEAD, which is how two promotions racing each other
lose safely.

1. Builds the GNOME bundles by calling `flatpak.yml` (same job, same
   artifacts).
2. Cuts the GitHub release, tagged `vYYYY.MM.DD-<short sha>`, marked
   `--latest`, carrying `org.bootcinstaller.Installer.flatpak`,
   `org.bootcinstaller.Installer.Devel.flatpak` and, when the aarch64 build
   produced one, `org.bootcinstaller.Installer-aarch64.flatpak`. It then
   verifies both `/releases/latest/download/` URLs resolve before continuing.
3. Publishes each frontend's Flatpak to the tuna-os remote through the shared
   `tuna-os/.github` reusable workflow, but only the frontends whose tree
   changed since the previous release. An unchanged frontend is not
   republished.

The date + sha tag is deliberate: it is monotonic, unique per promotion, and
never a rolling name an immutable-release ruleset can permanently ban (see
`runbooks/auto-release-rollback.md` for the history).

## Downstream contract

| Consumer wants | URL | Comes from |
|---|---|---|
| The GNOME installer a live ISO installs | `/releases/latest/download/org.bootcinstaller.Installer.flatpak` | the last promoted `prod` commit |
| The GNOME devel app id, same commit | `/releases/latest/download/org.bootcinstaller.Installer.Devel.flatpak` | the last promoted `prod` commit |
| Bleeding edge, unvalidated | `/releases/download/latest-dev/org.bootcinstaller.Installer.Devel.flatpak` | every push to `dev` (pre-release) |
| Any frontend from the tuna-os Flatpak remote | `https://tunaos.org/flatpak/index/static` | the last promoted `prod` commit |

**What changed for downstreams:** before this flow, `/releases/latest/` and
the Flatpak remote were rewritten on every push to `dev`, gated on nothing but
"the bundle built". Now they move only when a `dev` commit has passed every
check and the soak window. A consumer that wants `dev` bits takes the
`latest-dev` pre-release, which is the same asset it was before.

## Escape hatches

| Situation | Do this |
|---|---|
| Gate is wrong and a commit must ship now | Actions → *Promote dev → prod* → Run workflow with `force: true`. The soak and check gate are skipped; the fast-forward rule is not. |
| Promote a specific older commit on `dev` | Same dispatch with `sha:`. It must be on `dev` and ahead of `prod`. |
| Hotfix that cannot wait for `dev` | Push a `v*` tag on a commit; `release.yml` runs for the tag. Prefer a normal PR to `dev` and a forced promotion. |
| A bad release is `latest` | `runbooks/auto-release-rollback.md`: demote it with `gh release edit --latest=false` and promote the last good one. Never delete releases or tags. |
| Republish a frontend's Flatpak by hand | Actions → *Publish Flatpak (<frontend>)* → Run workflow on `prod`. |
| Pause promotion | Disable the *Promote dev → prod* workflow in the Actions UI. Merges keep landing on `dev`; nothing ships until it is re-enabled. |

## Knobs

All in `.github/workflows/promote.yml`:

- `SOAK_MINUTES`: minimum age of a commit before it may ship.
- `REQUIRED_CHECKS`: check-run names that must be present and green. Add a
  workflow's job name here when it should block promotion even on commits
  that did not trigger it by path.
- The `workflow_run` list: workflows whose completion re-evaluates the gate.
  A new validation workflow belongs in both lists.

## Things the flow does not do

- It does not run the VM install matrix. That lives in `tuna-os/fisherman`
  (`bootcrew-vm.yml`) against the backend, and in `tuna-os/tunaOS`
  (`installer-smoke.yml`) against the live ISOs. Widening the soak window is
  the lever if those need time to run against a `dev` commit first.
- It does not version the fisherman submodule. Bumping the pointer is a
  normal PR to `dev` and ships like any other change.
- It does not need a personal access token. `GITHUB_TOKEN` pushes do not
  trigger push workflows, which is why `release.yml` is dispatched explicitly
  rather than triggered by the push to `prod`.
