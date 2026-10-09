# TunaOS COSMIC Installer — Roadmap

**Status**: Consolidated inside monorepo (`frontends/cosmic`) | **Parent Roadmap**: [Root ROADMAP.md](../../ROADMAP.md)

---

## Mission

Ship the COSMIC desktop's install experience: a native `cosmic::Application`
(Iced/Rust) frontend that gathers user choices, writes the fisherman recipe, and
presents installation progress and outcomes for a polished first boot to desktop.

---

## Monorepo Context & Consolidation

Following the 2026-09-17 monorepo migration ([docs/MIGRATION.md](../../docs/MIGRATION.md)),
COSMIC installer planning is unified under the root [ROADMAP.md](../../ROADMAP.md).

- **Shared Contracts**: Uses the canonical recipe schema (`shared/recipe/`) and fulfills the six core screens verified in [docs/walkthrough/README.md](../../docs/walkthrough/README.md).
- **Release & Distribution**: Published as `ghcr.io/tuna-os/bootc-installer:cosmic` via `.github/workflows/publish-oci.yml` upon promotion to `prod` ([docs/RELEASE.md](../../docs/RELEASE.md)).
- **Consolidation Plan (F1–F8)**: Migrating duplicate non-UI logic (progress calculation, system probing, recipe generation, validation) directly into fisherman or `shared/`.

### Active COSMIC Priorities in Monorepo

| Priority | Item | Tracking | Status |
|----------|------|----------|--------|
| P0 | Frontend consolidation: adopt shared fisherman probe & progress events | #186, #208 | 🟡 In progress |
| P1 | Browser rendering via Broadway/WASM evaluation | #105 | 🟡 In progress |
| P1 | Parity alignment with walkthrough contract table | #150, [docs/PARITY.md](../../docs/PARITY.md) | 🟡 In progress |
| P2 | Fold redundant vendored copies into `shared/` core | #207 | 🟡 In review |

---
*Consolidated roadmap for COSMIC frontend. See root [ROADMAP.md](../../ROADMAP.md) for overarching milestone commitments.*
