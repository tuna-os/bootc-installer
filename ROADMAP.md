# bootc-installer Roadmap

**Last updated**: 2026-10-06 | **Maintainer**: tuna-os (hanthor)

---

## Mission

bootc-installer is the org's install front door: the monorepo for every TunaOS/Bluefin installer frontend. Five frontends (GNOME at the root; KDE, COSMIC, Niri and XFCE under `frontends/`) render one shared screen contract and write one shared recipe for the `fisherman` Go backend, which executes the 9-step pipeline (partition → format → LUKS → mount → `bootc install` → post-install → Windows migration → finalize) on both the systemd-boot/UKI stack (Dakota) and the GRUB2 stack (Bluefin, Bluefin-LTS, Bazzite).

---

## Current Status (October 2026)

**Monorepo consolidation (2026-09-17)**: Four separate desktop-specific repositories (`tuna-installer-kde|cosmic|niri|xfce`) were imported via `git subtree add` and frozen (epic #83, closed). Parity moved from a cross-repo goal to an in-repo invariant.

| Subsystem | State | Evidence |
|---|---|---|
| Frontend parity | All five frontends reach all six contract screens (`welcome`, `disk`, `encryption`, `summary`, `install`, `done`). | [docs/walkthrough/README.md](docs/walkthrough/README.md); [docs/PARITY.md](docs/PARITY.md) |
| Shared core | Recipe schema, parity report and walkthrough aggregator in `shared/`; KDE and COSMIC still vendor copies, drift-checked in CI. | [docs/MIGRATION.md](docs/MIGRATION.md) |
| CI validation | Flatpak, Python, Go, per-frontend Flatpak, screenshots ×5, E2E (every frontend drives fisherman to booted VM), walkthrough: all green. | Actions on `dev` |
| Promotion | `promote.yml` fast-forwards `prod` from `dev` when all checks pass; `prod` is at `dev` (0 commits behind). | [docs/RELEASE.md](docs/RELEASE.md) |
| **Publishing** | **RED since 09-18.** Every `release.yml` run fails at "Push OCI to shared registry"; Flatpak remote has no `org.bootcinstaller.Installer` apps since 09-18; docs smoke test red daily. | #100; fix pending review in PR #107 (open 09-22) |
| Browser rendering | GTK frontends render in browser via Broadway, driven by Playwright (#102); Niri (#103), KDE (#104), COSMIC (#105, working) follow. | `shared/browser/`; five upstream libcosmic patches pending |
| Activity | 172 commits on `dev` last 30 days (70 maintainer, 41 hive agents, 36 bot, 24 Claude sessions). | Recent momentum is high |

✅ Supply-chain fix: `FLATPAK_INDEX_TOKEN`/`GITHUB_TOKEN` not embedded in clone URLs (#12, merged).
⚠️ Per-frontend ROADMAP.md files cite deleted standalone repositories — needs update.

### Priorities

| Priority | Item | Tracking | Status |
|----------|------|----------|--------|
| P0 | Restore Flatpak publishing on `prod` — unblock Flatpak remote and smoke test | #100, PR #107 | 🔴 Blocked on #107 review (open 09-22) |
| P0 | Live-ISO flow tested end-to-end (not just documented) | docs/live-iso.md, `e2e.yml` | 🟢 E2E runs every push |
| P1 | Consolidate shared core: KDE and COSMIC consume `shared/` instead of vendored copies | [docs/MIGRATION.md](docs/MIGRATION.md) | 🟡 Drift-checked, not consolidated |
| P1 | Browser rendering for Niri and KDE frontends (COSMIC rendering works) | #103, #104 | 🟡 COSMIC done; Niri/KDE open |
| P1 | Update per-frontend ROADMAP.md files — retire standalone repo references | — | ⬜ Not started |
| P2 | Windows migration QA matrix (Win10/11, FAT32/NTFS/exFAT) | docs/features/ | ⬜ Not started |
| P2 | Unify version identity: `meson.build` (3.0.0) vs `VERSION` (1.0.0) vs tags (legacy v3.0.x + authoritative vYYYY.MM.DD) | [docs/RELEASE.md](docs/RELEASE.md) | ⬜ Not started |
| P3 | Record what has been sent upstream to Vanilla OS installer vs fork-only code | #23 | ⬜ No record |

---

## Quarterly Goals

### 2026 Q3 (July–September) — closed

**Theme was**: Stable, token-safe install UX. **What happened**: Monorepo consolidation (#83 epic) reshaped the project.

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| Land #12 token fix + verify no secrets in recipe/clone paths | sec-check | #12 | ✅ Done |
| Baseline CI green on both boot-stack test plans | ci-maintainer | #11 | ✅ Adopted; coverage gate rising |
| Consolidate per-desktop installers into one repo with shared backend | architect | #83 | ✅ Done (2026-09-17) |
| Ship Q3 with five frontends at feature parity | — | epic #83 | ✅ Done |

### 2026 Q4 (October–December) — current

**Theme**: Stabilize post-consolidation, unblock publishing, ship enterprise features

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| **Triage & merge PR #107** (fix OCI publishing). Restore Flatpak remote and docs smoke test. | tuna-os | #100, PR #107 | 🔴 **CRITICAL** — review needed |
| Finish shared core parity (KDE + COSMIC consume `shared/`, not vendored copies) | architect | [docs/MIGRATION.md](docs/MIGRATION.md) #67 | 🟡 Planned; not yet sequenced |
| Browser rendering for Niri + KDE; ship COSMIC's patches upstream to libcosmic | ci-maintainer | #103, #104, #105 | 🟡 COSMIC renders; others pending |
| LUKS-first + dual-boot scenarios validated on Redfin/RHEL; signed Flatpak + SBOM | — | tunaos#1123, #1187 | ⬜ Not started |
| Installer telemetry hook (opt-in) + adoption signal feed | — | — | ⬜ Not started |

---

## Technical Debt & Known Issues

| Item | Issue | Priority | Effort |
|------|-------|----------|--------|
| Per-frontend ROADMAP.md files cite deleted standalone repositories | — | P1 | S |
| Shared core vendoring in KDE + COSMIC creates drift surface | #67 | P1 | M |
| Version identity split: `meson.build` (3.0.0), `VERSION` (1.0.0), tags (legacy + YYYY.MM.DD) | — | P2 | M |
| Scratch-space constraints (`/var/fisherman-tmp` vs tmpfs `/run`) | README | P2 | S |
| Single JSON recipe error-handling transparency | — | P3 | S |
| Upstream sync record: what's sent to Vanilla OS vs fork-only | #23 | P3 | S |

---

## How to Contribute

See [CONTRIBUTING.md](./CONTRIBUTING.md) and [AGENTS.md](./AGENTS.md). The
repo is small and well-scoped — good entry points: test-plan coverage for a
boot stack, live-ISO docs, Windows-migration QA fixtures.

## Roadmap Governance

Maintained by the strategist agent; updates after major milestones or quarterly checkpoints. Propose changes via PR with an issue reference. Per-frontend ROADMAP.md files under `frontends/*/` should be updated simultaneously.

---
