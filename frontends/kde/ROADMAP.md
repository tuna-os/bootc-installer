# KDE Plasma frontend roadmap

**Last updated**: 2026-11-10

This frontend (Qt 6 / Kirigami, C++ and QML) is one of five in the `tuna-os/bootc-installer`
monorepo. It has no plan of its own. The plan for all five is the root
[ROADMAP.md](../../ROADMAP.md).

The repository `tuna-os/tuna-installer-kde` does not exist any more. An issue
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
| #287 | The catalog filesystem does not reach the recipe, so a composefs image gives a recipe that fisherman rejects |
| #290 | The Flatpak builds fisherman, but does not stage it or verify its SHA256 |
| #299 | Cancel does not ask first, and the result page reports a cancel as a failure |
| #300 | The frontend has no translatable strings |
| #301 | An offline user gets no help to connect |
| #288 | The default for `needs_user_creation` is not the same in every frontend |
| #296 | The catalog's Flatpak list for an image does not reach the recipe |
| #297 | `nvidia_imgref`, `flatpak_var_path` and `targetImgref` from the catalog do not all reach the recipe |
| #302 | The first account is only in `wheel` |

When you close one of these issues, remove its row.
`tests/unit/test_frontend_roadmaps.py` examines this file.
