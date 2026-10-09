# TunaOS Niri Installer — Roadmap

**Status**: Consolidated inside monorepo (`frontends/niri`) | **Parent Roadmap**: [Root ROADMAP.md](../../ROADMAP.md)

---

## Mission

Ship the Niri desktop's install experience: a Quickshell/QML + Go frontend
that drives the fisherman bootc backend, providing a native install workflow on the
scrollable-tiling Wayland compositor.

---

## Monorepo Context & Consolidation

Following the 2026-09-17 monorepo migration ([docs/MIGRATION.md](../../docs/MIGRATION.md)),
Niri installer planning is unified under the root [ROADMAP.md](../../ROADMAP.md).

- **Shared Contracts**: Uses the canonical recipe schema (`shared/recipe/`) and fulfills the six core screens verified in [docs/walkthrough/README.md](../../docs/walkthrough/README.md).
- **Release & Distribution**: Published as `ghcr.io/tuna-os/bootc-installer:niri` via `.github/workflows/publish-oci.yml` upon promotion to `prod` ([docs/RELEASE.md](../../docs/RELEASE.md)).
- **Consolidation Plan (F1–F8)**: Migrating duplicate non-UI logic (progress calculation, system probing, recipe generation, validation) directly into fisherman or `shared/`.

### Active Niri Priorities in Monorepo

| Priority | Item | Tracking | Status |
|----------|------|----------|--------|
| P0 | Frontend consolidation: adopt shared fisherman probe & progress events | #186, #208 | 🟡 In progress |
| P1 | Browser rendering with Qt for WebAssembly wizard | #103, PR #170 | 🟡 In review |
| P1 | Parity alignment with walkthrough contract table | #150, [docs/PARITY.md](../../docs/PARITY.md) | 🟡 In progress |
| P2 | Fold redundant vendored copies into `shared/` core | #207 | 🟡 In review |

---
*Consolidated roadmap for Niri frontend. See root [ROADMAP.md](../../ROADMAP.md) for overarching milestone commitments.*
