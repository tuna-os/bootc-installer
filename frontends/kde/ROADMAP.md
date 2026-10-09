# TunaOS KDE Installer — Roadmap

**Status**: Consolidated inside monorepo (`frontends/kde`) | **Parent Roadmap**: [Root ROADMAP.md](../../ROADMAP.md)

---

## Mission

Ship the KDE desktop's install experience: a thin Qt 6 / Kirigami wizard
(built the way KDE's own KISS initial-setup is built — self-contained
`SetupModule` steps) that drives the fisherman bootc backend, so a first-time
Plasma user gets a native install from first boot to desktop.

---

## Monorepo Context & Consolidation

Following the 2026-09-17 monorepo migration ([docs/MIGRATION.md](../../docs/MIGRATION.md)),
KDE installer planning is unified under the root [ROADMAP.md](../../ROADMAP.md).

- **Shared Contracts**: Uses the canonical recipe schema (`shared/recipe/`) and adheres to the multi-frontend screen contract ([docs/walkthrough/README.md](../../docs/walkthrough/README.md)).
- **Release & Distribution**: Published as `ghcr.io/tuna-os/bootc-installer:kde` via `.github/workflows/publish-oci.yml` upon promotion to `prod` ([docs/RELEASE.md](../../docs/RELEASE.md)).
- **Consolidation Plan (F1–F8)**: Migrating duplicate non-UI logic (progress calculation, system probing, recipe generation, validation) directly into fisherman or `shared/`.

### Active KDE Priorities in Monorepo

| Priority | Item | Tracking | Status |
|----------|------|----------|--------|
| P0 | Frontend consolidation: adopt shared fisherman probe & progress events | #186, #208 | 🟡 In progress |
| P1 | Stream buffer handling & cancel wrapper reliability | #208 | 🟡 In review |
| P1 | Parity alignment with walkthrough contract table | #150, [docs/PARITY.md](../../docs/PARITY.md) | 🟡 In progress |
| P2 | Fold redundant vendored copies into `shared/` core | #207 | 🟡 In review |

---
*Consolidated roadmap for KDE frontend. See root [ROADMAP.md](../../ROADMAP.md) for overarching milestone commitments.*
