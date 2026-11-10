# TunaOS COSMIC Installer — Roadmap

**Last updated**: 2026-08-30 | **Maintainer**: tuna-os (hanthor)

---

## Mission

Ship the COSMIC desktop's install experience: a real `cosmic::Application`
frontend that gathers the user's choices, writes the fisherman recipe, and
presents the backend's progress and result — so a first-time COSMIC user gets
a native, polished install from first boot to desktop.

---

## Current Status

- **App**: libcosmic (Iced/Rust) frontend for the fisherman bootc backend.
  It has fourteen screens (see DESIGN.md). CI renders the walkthrough in
  docs/screenshots.
- **Distribution**: image-baked flatpak (`org.tunaos.InstallerCosmic`) — no
  standalone GitHub Releases (by design, not yet documented as policy).
- **Parity**: covered by `installer-smoke.yml` + `docs/INSTALLER-FRONTENDS.md`
  checks (readiness stamp, non-blank, advances, per-screen OCR).
- **Health**: active (pushed 08-24); open issues concentrate on install-recipe
  hardening (#39/#40/#41) and backend privilege boundary (#38).

### Priorities

| Priority | Item | Tracking | Status |
|----------|------|----------|--------|
| P0 | Install-recipe hardening — unpredictable recipe path, 0600 mode honored | #39/#41 | ✅ Complete |
| P0 | Unpin `cargo-sources` generation (flatpak-cargo-generator.py) | #40 | 🟡 Open |
| P1 | Privileged install backend — only unpinned binary in the image | #38 | 🟡 Open |
| P1 | Parity reporting — only frontend that emits no parity signal | #36 | 🟡 Open |
| P2 | ROADMAP-coverage entry in org ROADMAP tally | #1295 | ⬜ Not started |

The rows below are issues of `tuna-os/bootc-installer` (the 2026-11 review).

| Priority | Item | Tracking | Status |
|----------|------|----------|--------|
| P0 | Every catalog field reaches the recipe; the filesystem list is the image's | #286 | ✅ Complete |
| P0 | Shared catalog contract: default account, default selection, Flatpak lists, NVIDIA image | #288, #289, #296, #297 | ✅ COSMIC part complete |
| P0 | Remove the phone companion | #293 | ✅ COSMIC part complete |
| P1 | Staged and verified fisherman in the Flatpak; `pkexec` natively | #290 | ✅ COSMIC part complete |
| P1 | Shared account groups and the operator override | #302 | ✅ COSMIC part complete |
| P1 | Cancel asks first; a cancelled page | #299 | ✅ COSMIC part complete |
| P2 | Network settings for an offline user; probe the registry of the image | #301 | ✅ COSMIC part complete |
| P2 | One choke point for translatable strings, with a lint | #300 | 🟡 Shim and lint; no catalog ships |
| P2 | Language, keyboard and time zone in the recipe | #292 | 🟡 The pages say "this session only"; the fields wait for fisherman |

---

## Quarterly Goals

### Current Quarter (2026 Q3)

**Theme**: harden the install path

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| Install-recipe path and permission hardening | hanthor | #39/#41 | ✅ Complete |
| Pin cargo-sources generator and Python dependencies | hanthor | #40 | 🟡 In progress |
| Decide backend privilege boundary | hanthor | #38 | ⬜ Not started |

### Next Quarter (2026 Q4)

**Theme**: parity and cadence

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| Emit parity signal like the other frontends | hanthor | #36 | ⬜ Not started |
| Document release/versioning model (image-baked vs tagged) | tuna-os | (org #2020) | ⬜ Not started |

---

*ROADMAP added by strategist agent (ACMM L6 — full mode). Signed-off-by: hanthor-hive-agent[bot] <290068839+hanthor-hive-agent[bot]@users.noreply.github.com>*
