# AGENTS.md — agent guide for tuna-os/tuna-installer-niri

A **Quickshell/QML wizard with a Go backend** that drives the
[fisherman](https://github.com/tuna-os/fisherman) bootc install backend, for
the Niri scrollable-tiling Wayland compositor. Architecture is modelled on
[DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell).

Human docs: [`README.md`](README.md) (architecture, build, recipe),
[`DESIGN.md`](DESIGN.md) (interaction and visual spec),
[`docs/gui-walkthrough.md`](docs/gui-walkthrough.md) (CI-generated).

## Two halves, one contract

| Path | What |
|---|---|
| `installer/` | the Go backend — **its own module**, with all the unit tests |
| `ui/` | the Quickshell QML wizard (`installer.qml`, `Theme.qml`, `qmldir`) |
| `tests/gui/` | headless capture (`capture-screens.py`) and `parity_report.py` |
| `tests/qml-stubs/` | a stub `Quickshell` QML module so the UI can be loaded without the real one |

The QML talks to the backend through its CLI, not a library:

```bash
cd installer
go build -o tuna-installer-niri .
./tuna-installer-niri discover-disks        # renders lsblk -J output
./tuna-installer-niri install '{...}'       # runs fisherman with a JSON recipe
quickshell ui/installer.qml                 # the frontend, needs Quickshell
```

So a change to the backend's **stdout shape** is a breaking change to the UI
even though nothing in `ui/` references a Go symbol.

## Checks

CI (`ci.yml`) runs everything with `working-directory: installer`, which is
why a root-level `go` command finds nothing:

```bash
cd installer
gofmt -l .        # must print nothing — CI fails on any unformatted file
go vet ./...
go build ./...
go test ./...
```

`.golangci.yml` config lives at the repo root. The Go tests are real and cover
the interesting parts — `offline_test.go`, `readiness_test.go`,
`product_test.go` — so run them before pushing rather than relying on CI.

## The QML stub is load-bearing

`tests/qml-stubs/Quickshell/` exists so the wizard can be loaded in CI without
installing Quickshell itself. When you add a Quickshell API call to the UI, the
stub needs the matching shim or the screenshot job fails with a QML resolution
error that looks nothing like the real cause.

## Visual verification

`screenshots.yml` renders every screen headlessly from the real QML and emits
the parity report the shared installer matrix consumes. A UI change that breaks
capture breaks that cross-installer report, not just this repo's screenshots.
`DESIGN.md`'s "Quality floor" section is the standard those renders are held to
— the scrolling column strip is the signature element, so treat changes to it
as design changes, not layout tweaks.

## Sibling contract

The recipe JSON and the screen sequence are shared with the other frontends
(`tuna-installer-kde`, `-xfce`, `-cosmic`) via the
[installer frontend contract](https://github.com/tuna-os/tunaos/blob/main/docs/INSTALLER-FRONTENDS.md).
A field added here has to exist there too, or the installers diverge. All the
real disk work belongs in fisherman — keep it there.
