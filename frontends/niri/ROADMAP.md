# Niri frontend roadmap

**Last updated**: 2026-11-10

This frontend (Quickshell QML and a Go backend) is one of five in the `tuna-os/bootc-installer`
monorepo. It has no plan of its own. The plan for all five is the root
[ROADMAP.md](../../ROADMAP.md).

The repository `tuna-os/tuna-installer-niri` does not exist any more. An issue
number in this file is an issue in `tuna-os/bootc-installer`.

## Where to look

| Topic | Document |
|---|---|
| The plan for the monorepo | [ROADMAP.md](../../ROADMAP.md) |
| The move from the old repository, and the issues that were open then | [docs/MIGRATION.md](../../docs/MIGRATION.md) |
| The path from `dev` to `prod`, and how the Flatpak ships | [docs/RELEASE.md](../../docs/RELEASE.md) |
| The contracts that all five frontends share | [shared/](../../shared/) |
| The screens of all five frontends, with the parity matrix | [docs/walkthrough/](../../docs/walkthrough/README.md) |
| What each frontend renders and does | [docs/PARITY.md](../../docs/PARITY.md) |
| The rules for this tree | [AGENTS.md](AGENTS.md) |

## Open items for this frontend

The tracker is the source of truth. This list is a snapshot from 2026-11-10.

| Issue | Gap |
|---|---|
| #291 | The Session step blocks the wizard when `localectl` or `timedatectl` fails, and can change the keymap |
| #289 | Off live media, the frontend ignores the branding `default_image` |
| #295 | The account password has no reveal toggle |
| #298 | The Flatpak cannot see a host catalog in `/etc/bootc-installer` |
| #290 | The Flatpak builds fisherman, but does not stage it or verify its SHA256 |
| #300 | The frontend has no translatable strings |
| #301 | The connectivity check does not block, and it probes a different host |
| #299 | Cancel does not ask first, and the result page reports a cancel as a failure |
| #288 | The default for `needs_user_creation` is not the same in every frontend |
| #292 | Language, keyboard and time zone do not reach the installed system |
| #296 | The catalog's Flatpak list for an image does not reach the recipe |
| #297 | `nvidia_imgref`, `flatpak_var_path` and `targetImgref` from the catalog do not all reach the recipe |
| #302 | The first account is only in `wheel` |

When you close one of these issues, remove its row.
`tests/unit/test_frontend_roadmaps.py` examines this file.
