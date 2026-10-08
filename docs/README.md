# bootc-installer Documentation

This folder holds 27+ documents covering the installer, backend architecture, testing, and release process. Use this index to find what you need.

**Quick navigation by role:**
- **New contributors**: Start with [../CONTRIBUTING.md](../CONTRIBUTING.md), then read [DESIGN-AUDIT.md](DESIGN-AUDIT.md)
- **Testers and QA**: See [test-plans/](test-plans/), [PARITY.md](PARITY.md), [live-iso.md](live-iso.md)
- **Release maintainers**: Read [RELEASE.md](RELEASE.md) and check [MIGRATION.md](MIGRATION.md)
- **Frontend developers**: Check [walkthrough/README.md](walkthrough/README.md) and your frontend's docs

---

## Getting Started & Walkthroughs

| Document | Purpose |
|---|---|
| [gui-walkthrough.md](gui-walkthrough.md) | Visual tour of the GNOME installer |
| [walkthrough/README.md](walkthrough/README.md) | Multi-frontend walkthrough index (GNOME, KDE, COSMIC, Niri, XFCE) |
| [live-iso.md](live-iso.md) | Building and testing with live ISO |

## Architecture & Design

| Document | Purpose |
|---|---|
| [DESIGN-AUDIT.md](DESIGN-AUDIT.md) | Full installer architecture and design decisions |
| [PARITY.md](PARITY.md) | Desktop frontend parity tracking (GNOME, KDE, COSMIC, Niri, XFCE) |

## Testing & Validation

| Document | Purpose |
|---|---|
| [test-plans/release-qualification.md](test-plans/release-qualification.md) | Release qualification checklist |
| [test-plans/e2e-feature-verification.md](test-plans/e2e-feature-verification.md) | End-to-end feature validation |
| [test-plans/encryption-matrix.md](test-plans/encryption-matrix.md) | LUKS and TPM2 encryption scenarios |
| [test-plans/dakota-tpm2-validation.md](test-plans/dakota-tpm2-validation.md) | Dakota / systemd-boot + TPM2 tests |
| [test-plans/failure-paths.md](test-plans/failure-paths.md) | Error handling and recovery paths |
| [test-plans/demo-mode-e2e.md](test-plans/demo-mode-e2e.md) | Demo mode end-to-end flow |

## Features & Implementation

| Document | Purpose |
|---|---|
| [features/gstreamer-codec-validation.md](features/gstreamer-codec-validation.md) | Codec support validation |
| [features/libpastry-integration.md](features/libpastry-integration.md) | libpastry integration |
| [features/qr-phone-companion.md](features/qr-phone-companion.md) | QR phone companion app |

## Release & Maintenance

| Document | Purpose |
|---|---|
| [RELEASE.md](RELEASE.md) | Release process and automation |
| [MIGRATION.md](MIGRATION.md) | History: how repos were merged; open items from old repos |

## Developer Skills & Knowledge

| Document | Purpose |
|---|---|
| [skills/PITFALLS.md](skills/PITFALLS.md) | Common traps and gotchas when working on the installer |
| [skills/SKILL.md](skills/SKILL.md) | Developer skill guide and onboarding |
| [skills/INDEX.md](skills/INDEX.md) | Skills index |

## Planning & Experiments

See `superpowers/` for planning documents and design specs:
- `plans/` — quarterly planning and roadmap items
- `specs/` — detailed design specs for features under development

---

## Contributing to docs

1. Keep docs in sync with code changes
2. Link to related docs so readers don't get lost
3. Add a new doc to this index when you create one
4. For major features, consider a design doc in `superpowers/specs/`

See [../CONTRIBUTING.md](../CONTRIBUTING.md) for how to contribute code.
