# bootc-installer Roadmap

**Last updated**: 2026-08-25 | **Maintainer**: tuna-os (hanthor) / architect agent

---

## Mission

bootc-installer is the org's install UX front door: a GTK 4 / Libadwaita
Flatpak installer that guides a user from ISO to a booted, personalized
[bootc](https://containers.github.io/bootc/) image. The `fisherman` Go backend
executes a 9-step pipeline (partition → format → LUKS → mount → `bootc
install` → post-install → Windows migration → finalize) from a single JSON
recipe, supporting both the systemd-boot/UKI stack (Dakota) and the GRUB2
stack (Bluefin, Bluefin-LTS, Bazzite).

---

## Current Status (August 2026)

- Young, active repo: production Flatpak auto-released on every push to `dev`
  (#5); TunaOS project-baseline CI adopted (#11, merged).
- 9-step fisherman pipeline covers both boot stacks; Windows data migration
  (documents/photos/music/bookmarks/fonts/wallpapers) is a differentiator.
- ⚠️ The supply-chain issue this doc previously marked fixed regressed on the
  default `dev` branch: #36 tracks `FLATPAK_INDEX_TOKEN` returning to a git
  clone URL. Keep the token-safe publishing gate open until the fix is on
  `dev` and a publish run verifies it.
- Tuna publishes x86_64 and aarch64 release bundles from this fork, but the
  README's production and development install commands still download
  Project Bluefin artifacts. The supported distribution owner and release
  promotion contract are therefore not yet defined.
- Org context: per-desktop installers (`tuna-installer-cosmic|kde|niri|xfce`)
  and Apple Silicon (`bootc-installer-asahi`) share this backend's concepts;
  parity between them is not yet tracked in this repo.
- No milestones yet; work tracked ad-hoc via issues.
- ⚠️ This file previously lived only on the non-default `main` branch
  (tunaos#1361) — landed here on `dev`, the repo's actual default branch, so
  it's visible from the repo root.

### Priorities

| Priority | Item | Tracking | Status |
|----------|------|----------|--------|
| P0 | Keep publishing credentials out of clone URLs and verify on `dev` | #36 | 🟡 Regression open |
| P0 | Define one supported distribution owner, install URL, and promotion/rollback contract | strategist finding | ⬜ Not started |
| P0 | Live-ISO flow documented + tested end-to-end | docs/live-iso.md | 🟡 Docs exist |
| P1 | tuna-installer-* family parity — single backend, per-desktop skins | tunaos#1294 (context) | ⬜ Not started |
| P1 | E2E test plans for both boot stacks (systemd-boot + GRUB2) | docs/test-plans/ | 🟡 In progress |
| P2 | Windows migration QA matrix (Win10/11, FAT32/NTFS/exFAT) | docs/features/ | ⬜ Not started |

---

## Quarterly Goals

### Current Quarter (2026 Q3 — July–September)

**Theme**: Stable, token-safe install UX

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| Resolve #36 on `dev` and verify a token-safe publish run | sec-check | #36 | 🟡 Regression open |
| Choose Tuna-owned or delegated distribution; align install, clone, and security links | maintainer | strategist finding | ⬜ Decision needed |
| Baseline CI green on both boot-stack test plans | ci-maintainer | #11 (baseline) | ✅ Baseline adopted; coverage gate rising |
| Publish install-UX guide for tunaos.org (download → installed) | guide | docs site | ⬜ Not started |
| Define tuna-installer-* parity contract (backend reuse) | architect | — | ⬜ Not started |

### Next Quarter (2026 Q4 — October–December)

**Theme**: Enterprise-ready installs

- LUKS-first + dual-boot scenarios validated on Redfin/RHEL track (#1123)
- Signed Flatpak releases + SBOM aligned with org Q4 supply chain (#1187)
- Windows-migration QA matrix shipped; recovery/rollback path documented
- Installer telemetry hook (opt-in) feeding ADOPTION-METRICS.md install tier

---

## Technical Debt Backlog

| Item | Issue | Priority | Effort |
|------|-------|----------|--------|
| Scratch-space constraints (`/var/fisherman-tmp` vs tmpfs `/run`) | README | P2 | S |
| `VERSION` / recipe drift across tuna-installer-* forks | — | P2 | M |
| Single JSON recipe error-handling transparency | — | P3 | S |

## Distribution Graduation Gate

The installer is not generally available under the Tuna name until one
distribution model is documented and verified:

1. **Ownership:** state whether Tuna owns production artifacts or delegates
   production distribution to Project Bluefin.
2. **Supported channel:** publish one canonical install URL, artifact naming
   scheme, architecture matrix, and support boundary.
3. **Promotion evidence:** require green x86_64 and aarch64 builds, a successful
   Flatpak-index publish, checksum/signature verification, and an install smoke
   test before promotion.
4. **Recovery:** document rollback to the prior qualified artifact and name the
   decision owner.
5. **Routing:** make README, CONTRIBUTING, and vulnerability-reporting links
   agree with the ownership decision.

---

## How to Contribute

See [CONTRIBUTING.md](./CONTRIBUTING.md) and [AGENTS.md](./AGENTS.md). The
repo is small and well-scoped — good entry points: test-plan coverage for a
boot stack, live-ISO docs, Windows-migration QA fixtures.

## Roadmap Governance

Maintained by the strategist agent; updates after major milestones or
quarterly. Propose changes via PR to this file with an issue reference.

---
*Generated by strategist agent at ACMM L6 — full mode (ISSUES_AND_PRS).*
