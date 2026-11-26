# Contributing to the installer

This repository holds the installer frontends for [bootc](https://containers.github.io/bootc/) images: KDE, COSMIC, niri and XFCE in `frontends/`, and the legacy GNOME wizard in `bootc_installer/`. The install backend is [fisherman](https://github.com/tuna-os/fisherman), written in Go.

<!-- hive-contribute-plea: donated-compute appeal, keep in sync across repos -->
## Contribute compute — no code needed

**[Donate time with your AI CLI](https://hub.tunaos.org/#contribute).**

Your machine runs one task at a time using your signed-in AI coding CLI.
The relay alternates between eligible **School** (OS) and **Reef** (apps)
hives after each task. If one hive has no work, the other can continue.

The guide covers prerequisites, verified `just` setup, credentials, provider
costs, and how to stop with Ctrl+C. Your subscription quota or API charges apply.
Never post account credentials or API keys in issues or pull requests.

## Getting started

```bash
git clone --recurse-submodules https://github.com/tuna-os/installer
cd installer
```

> **Important:** `fisherman` is a git submodule. Always clone with `--recurse-submodules`, or run `git submodule update --init --recursive` after a plain clone. Without this, `fisherman/` is empty and all build paths fail immediately.

## Prerequisites

- `flatpak` + `org.flatpak.Builder` — for the recommended Flatpak build
- `meson`, `ninja` — for native (non-Flatpak) builds
- Go ≥ 1.22 — for `fisherman` (the install backend, in the submodule)
- Python ≥ 3.10 — for the GUI codebase
- `libadwaita-1-dev`, `gettext`, `desktop-file-utils`, `libgnome-desktop-4-dev`

## Building

### Flatpak (recommended)

```bash
git submodule update --init --recursive   # Required — fisherman is a submodule
flatpak run org.flatpak.Builder --force-clean --user --install _build flatpak/org.bootcinstaller.Installer.json
flatpak run org.bootcinstaller.Installer
```

### Meson (development)

```bash
git submodule update --init --recursive   # Required — fisherman is a submodule
meson setup build
ninja -C build
sudo ninja -C build install
bootc-installer
```

### Dev loop

```bash
./run-dev.sh                               # Rebuild and launch with BOOTC_DEMO=1 (no disk writes)
BOOTC_PREVIEW_SCREEN=confirm ./run-dev.sh  # Jump to a specific screen
```

## Running tests

```bash
pytest tests/unit/ -q                           # Unit tests (no display required)
xvfb-run -a pytest tests/ui/ -q                 # UI tests
python3 -m ruff check bootc_installer/ tests/   # Lint
./QUALIFY_SOFTWARE.sh                           # Full qualification suite
```

CI gate: `--cov-fail-under=51` (the minimum coverage for unit tests).

### PR checks versus the weekly branch sweep

`Go Tests` and `Python Tests` check the PR head SHA and its pinned fisherman
submodule. Push and merge-group runs check the event SHA.

`CI Tests` checks `prod` and `dev`, not the PR head. It runs on PRs only when
`.github/workflows/nightly.yml` changes. The Sunday 06:00 UTC schedule and
manual runs still check both branches. Do not require this path-filtered
workflow: GitHub leaves skipped PR workflows pending.

## Branch workflow

- Default branch: **`dev`**
- **Open all PRs against `dev`** — do not target `main`
- Follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages
- PR title format: `feat:`, `fix:`, `docs:`, `chore:`, `ci:`

## Adding images to the catalog

The image catalog lives in [`fisherman/data/images.json`](https://github.com/tuna-os/fisherman/blob/dev/data/images.json). Refer to [the guidebook](docs/guide/customising.md#add-an-image-to-the-default-catalog) for the JSON schema.

> `fisherman/` is a git submodule that points to [`tuna-os/fisherman`](https://github.com/tuna-os/fisherman). Commit and push changes to the catalog **separately** to the fisherman repo, then update the submodule pointer here.

## Architecture overview

| Component | Language | Role |
|---|---|---|
| `frontends/kde/`, `cosmic/`, `niri/`, `xfce/` | C++, Rust, QML and Go, Python | Native frontends. Each has a `CONTRIBUTING.md` with its build and test commands |
| `bootc_installer/` | Python | Legacy GNOME frontend (recipe path only) |
| `shared/` | Data and Python | Contracts, fixtures and test tools |
| `fisherman/fisherman/` | Go | Backend command of the recipe path (submodule) |

[Architecture](docs/architecture.md) has the full picture. GNOME changes for the image-based medium go to tunaOS, not here.

The build and test commands above are for the legacy GNOME frontend.

## Code style

- Python: [Ruff](https://docs.astral.sh/ruff/) (`python3 -m ruff check bootc_installer/ tests/`). CI runs it. `ruff.toml` names the rules; see [the developer guide](docs/guide/developing.md#lint-with-ruff).
- Go: `gofmt` + `go vet`
- Commit messages: Conventional Commits

## Security

Report vulnerabilities through a [private vulnerability report on GitHub](https://github.com/tuna-os/installer/security/advisories/new). Do not open public issues for security bugs.
