> **Part of the [bootc-installer monorepo](../../README.md).** This tree was
> `tuna-os/tuna-installer-niri` until 2026-09-17 and was imported with its history. CI for it
> lives in the root `.github/workflows/` (`screenshots-niri.yml`,
> `publish-flatpak.yml`); releases follow [`docs/RELEASE.md`](../../docs/RELEASE.md).

# TunaOS Niri Installer — Quickshell + Go installer

<p align="center">
  <img src="docs/screenshots/walkthrough.gif" alt="The TunaOS niri installer, screen by screen" width="640">
</p>

<p align="center">
  <em>Rendered in CI from the real QML — see the <a href="docs/gui-walkthrough.md">walkthrough</a>.</em>
</p>


**Quickshell/QML + Go** installer for TunaOS, modeled on [DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell)'s architecture. Runs on the Niri scrollable-tiling Wayland compositor.

## Architecture

```
tuna-installer-niri/
├── ui/                    # Quickshell QML wizard and theme
├── installer/             # Go backend, offline detection, readiness, and tests
├── flatpak/               # Flatpak manifest for the packaged installer
├── tests/                 # Headless GUI capture and parity-report tooling
├── docs/gui-walkthrough.md # CI-generated screen-by-screen walkthrough
└── DESIGN.md              # Interaction and visual design specification
```

## Build

### Go backend

```bash
cd installer
go build -o tuna-installer-niri .
./tuna-installer-niri discover-disks     # the disks `fisherman probe --json` offers
./tuna-installer-niri install '{...}'     # run fisherman with a JSON recipe
```

### QML frontend

Requires [Quickshell](https://quickshell.org/):

```bash
quickshell ui/installer.qml
```

## Workflow

1. **Welcome** — intro screen. Unmet RAM/CPU/UEFI requirements block here
   (Continue anyway for RAM/CPU; power off or firmware setup for UEFI),
   mirroring GNOME's `window_cpu`/`window_ram`/`window_unsupported`.
2. **Session** — live-session keyboard, locale, timezone and connectivity
   (`session-get`/`session-set`); nothing here enters the recipe.
3. **Source** — live system or one `catalog` leaf per row, offline images
   first; the leaf carries the image ref, filesystem default, bootloader,
   composefs, flatpaks, `needs_user_creation` and tour slides.
4. **Disk Selection** — calls `tuna-installer-niri discover-disks`, which renders `fisherman probe --json` (`../../shared/probe/README.md`)
5. **Encryption** — offers supported LUKS and TPM-backed choices, plus the
   filesystem (`xfs`/`ext4`/`btrfs`/`zfs`, default from the leaf) and btrfs
   subvolumes under Advanced. The account step drops out when the leaf
   sets `needs_user_creation: false`.
6. **Account** — the user fisherman creates, in `wheel` (skipped per above).
7. **Confirm** — summary with hostname input.
8. **Install Progress** — streams the Go backend's output, with Cancel
   (`cancel` kills the wrapper's process group), a Copy-log button and the
   persistent log path (`detect`'s `logPath`, `log-path`).
9. **Done** — success/failure, recovery key, restart, power dialog, and the
   leaf's tour slides when it ships any.

## Parity notes

- The phone companion (`bootc_installer/utils/phone_companion.py`) stays
  GNOME-only: it needs an HTTP server, a QR encoder and credential
  injection into the recipe, and `docs/PARITY.md` keeps locale/companion
  steps GNOME-only by design with no fisherman rule behind them.
- Keyboard/locale/timezone apply to the live session only (localectl,
  timedatectl on the host). The fisherman recipe schema has no keys for
  them, so an installed system inherits the image's own defaults.

## DBus Integration

For tighter QML ↔ Go integration (future), expose the backend as a DBus service:

- Service: `org.tunaos.Installer`
- Object: `/org/tunaos/Installer`
- Methods: `DiscoverDisks()`, `StartInstall(disk, hostname)`, `PollOutput()`, `PollStatus()`

## License

GPL-3.0-only

## Offline installs

`tuna-installer-niri detect` reports the live-ISO image and the probe's
offline images as JSON; the QML layer offers "install this system, no
download" on live media and marks offline catalog rows. The recipe leaves
`additionalImageStores` out: fisherman exposes the host's stores itself.

## Testing

### Go Backend Unit Tests

```bash
cd installer
go test ./...
```

### Headless UI Screenshot Capture & Verification

The installer UI can be rendered and tested headlessly without running a full Wayland/Quickshell compositor:

```bash
pip install PyQt6
python3 tests/gui/capture-screens.py docs/screenshots
```

## Contributing

Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development workflows, testing requirements, and guidelines.

## Development

```bash
cd installer && go build -o tuna-installer-backend .
TUNA_BACKEND=$PWD/tuna-installer-backend quickshell -p ../ui/installer.qml
```

## Flatpak

```bash
flatpak-builder --user --install --force-clean build flatpak/org.tunaos.InstallerNiri.json
flatpak run org.tunaos.InstallerNiri
```

