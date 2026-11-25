# Installer roadmap

**Last updated**: 2026-11-25 | **Maintainer**: tuna-os (hanthor)

## Mission

One native installer for each TunaOS desktop, with one backend and one set of
contracts. [Architecture](docs/architecture.md) tells you how it works today.

## Architecture principle

- **Logic goes in fisherman.** A rule that all frontends need is in the
  backend, and a frontend shows the answer.
- **Contracts and data go in `shared/`.** A frontend reads them through one
  thin reader.
- **A frontend owns only its native UI.** If two frontends have the same rule,
  that rule moves to fisherman or `shared/`, and a test fails when a frontend
  makes a copy.
- **GNOME stays upstream.** tunaOS builds gnome-setup from a pinned commit and
  a patch series. This repository gets no GNOME port to the daemon.

## Status on 2026-11-25

| Area | State | Evidence |
|---|---|---|
| Native frontends | KDE, COSMIC, niri and XFCE have a page for each of the 18 screens, and use `fishermand` | [shared/flow](shared/flow/README.md), [PARITY](docs/PARITY.md) |
| Image-based medium | Not available to users. KDE and COSMIC have the most passes. No cell passes all seven stages | [Test state](docs/image-medium.md) |
| Live ISOs | Use the recipe path. GNOME uses the legacy `bootc_installer/` | [Live ISO](docs/live-iso.md) |
| Validation | All checks on `dev` are green | Actions on `dev` |
| Publication | Five Flatpaks, through `prod` only | [Release flow](docs/RELEASE.md) |
| Name | `tuna-os/bootc-installer` became `tuna-os/installer`. The GHCR package and the app IDs keep their names | [Migration](docs/MIGRATION.md) |

## Now

| Priority | Item | Tracking |
|---|---|---|
| P0 | All seven stages pass on one cell for each desktop | tunaOS#4910, #443, #444, #445, #446 |
| P0 | The recovery key is on the disk after the KDE install | tuna-os/fisherman |
| P0 | SELinux enforces in the live session | tunaOS#4973 |
| P0 | A CD boot of a GRUB cell works | tunaOS#4970 |
| P1 | CI drives each native frontend against the mock daemon, page by page | #443, #444, #445, #446 |
| P1 | One contract for the install log | #457 |
| P1 | Pins move with Renovate, and container images have a digest | #458, #427 |
| P2 | Evidence receipts in the walkthrough workflow | #270 |

## Later

- Publish the signed medium (tunaOS#4905).
- btrfs migration and soft reboot in `fishermand` (tunaOS#4908, tunaOS#4909).
- Retire the live ISO path after the exit criteria of ADR 0018 in tunaOS pass.
- Retire the recipe path after wootc leaves it. There is no date.

## Done

The plan of 2026-10-08 moved progress, probe, recipe, validation and log rules
into fisherman (steps F1 to F8). `docs/PARITY.md`, `shared/CHANGELOG.md` and
the git history of this file have the record.

## Roadmap governance

Update this file after a milestone, or each quarter. Send the change as a pull
request. Each status must name a workflow, a document or an issue that a reader
can check.
