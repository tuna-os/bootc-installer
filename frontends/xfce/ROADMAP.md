# TunaOS XFCE Installer — Roadmap

**Status**: Consolidated inside monorepo (`frontends/xfce`) | **Parent Roadmap**: [Root ROADMAP.md](../../ROADMAP.md)

---

## Mission

Ship the XFCE desktop's install experience: a lightweight GTK3 frontend that drives the
fisherman bootc backend, providing a native, responsive install from first boot to desktop.

---

## Monorepo Context & Consolidation

Following the 2026-09-17 monorepo migration ([docs/MIGRATION.md](../../docs/MIGRATION.md)),
XFCE installer planning is unified under the root [ROADMAP.md](../../ROADMAP.md).

- **Shared Contracts**: Uses the canonical recipe schema (`shared/recipe/`) and fulfills the six core screens verified in [docs/walkthrough/README.md](../../docs/walkthrough/README.md).
- **Release & Distribution**: Published as `ghcr.io/tuna-os/bootc-installer:xfce` via `.github/workflows/publish-oci.yml` upon promotion to `prod` ([docs/RELEASE.md](../../docs/RELEASE.md)).
- **Consolidation Plan (F1–F8)**: Migrating duplicate non-UI logic (progress calculation, system probing, recipe generation, validation) directly into fisherman or `shared/`.

### Active XFCE Priorities in Monorepo

| Priority | Item | Tracking | Status |
|----------|------|----------|--------|
| P0 | Frontend consolidation: adopt shared fisherman probe & progress events | #186, #208 | 🟡 In progress |
| P1 | Unit test suite execution in monorepo CI (`ci-xfce.yml`) | #186 | 🟡 Active |
| P1 | Parity alignment with walkthrough contract table | #150, [docs/PARITY.md](../../docs/PARITY.md) | 🟡 In progress |
| P2 | Fold redundant vendored copies into `shared/` core | #207 | 🟡 In review |

---
*Consolidated roadmap for XFCE frontend. See root [ROADMAP.md](../../ROADMAP.md) for overarching milestone commitments.*
