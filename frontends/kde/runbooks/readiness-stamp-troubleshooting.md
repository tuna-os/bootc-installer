# Runbook: Readiness Stamp & Frontend Startup Troubleshooting

## Scope

This runbook covers diagnosing and remediating failures where the TunaOS KDE installer frontend (`tuna-installer-kde` / `org.tunaos.InstallerKde`) fails to map its GUI window, swap frames, or write its readiness stamp during automated verification, live-ISO boot, or smoke testing.

## Background & Contract

`src/readiness.cpp` emits an atomic readiness stamp file named `tuna-installer-ready` in `$XDG_RUNTIME_DIR` when the installer window presents its first graphical frame via Qt Quick / QML's `frameSwapped` signal on `QQuickWindow`.

The stamp payload format is:
```
app_id=org.tunaos.InstallerKde
window=ApplicationWindow
signal=frame-swapped
mapped_at=<seconds_since_epoch_with_3_decimals>
page=<step_id>
```

### Why flatpak ps / process checks are insufficient

A process running inside a Flatpak sandbox or background session may be active without actually rendering frames (e.g., waiting on unfulfilled D-Bus services, missing Wayland/X11 compositors, display manager initialization failures, or missing OpenGL/DRM support). The readiness stamp verifies genuine GUI presentation and frame swapping.

## Triage Checklist

### 1. Check if the process launched vs rendered frames
Inside the test VM / guest:
```bash
# Check if flatpak / binary is running
ps aux | grep -E "tuna-installer-kde|org.tunaos.InstallerKde"

# Inspect the readiness stamp
cat "${XDG_RUNTIME_DIR}/tuna-installer-ready" 2>/dev/null || \
cat "/run/user/$(id -u)/app/org.tunaos.InstallerKde/tuna-installer-ready" 2>/dev/null
```

### 2. Verify XDG Runtime Directory & Permissions
If `$XDG_RUNTIME_DIR` is empty or invalid, `writeStamp()` returns `false` without writing:
```bash
echo "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}"
ls -ld "${XDG_RUNTIME_DIR}"
```
Ensure `$XDG_RUNTIME_DIR` is set, owned by the active session user (typically `liveuser` / UID 1000), and mounted read-write (`tmpfs`).

### 3. Diagnose Display Server, Wayland / KWin, & OpenGL
If the process is running but no stamp is written:
- Verify `WAYLAND_DISPLAY` or `DISPLAY` is exported in the environment.
- Verify KWin / Wayland compositor is active and accepting clients:
  ```bash
  systemctl --user status plasma-kwin_wayland.service
  ```
- Check journal logs for Qt/QML, OpenGL, or Kirigami errors:
  ```bash
  journalctl --user -u org.tunaos.InstallerKde -b --no-pager
  ```
- Inspect graphics drivers / Mesa software rasterizer (e.g. `llvmpipe` on virtualized CI testbeds).

## Incident Escalation & Recovery

1. If the stamp exists but contains an unexpected `page` or `unknown`:
   - Check if `Main.qml` or `Wizard.qml` failed to bind `currentStepId` upon initial presentation.
2. If `signal` differs from `frame-swapped`:
   - Note that toolkit signals provide the presentation guarantee; verify whether `QQuickWindow::frameSwapped` was properly connected by `armStamp()`.
3. If running in headless CI without DRM / hardware acceleration:
   - Ensure `LIBGL_ALWAYS_SOFTWARE=1` or `QT_QUICK_BACKEND=software` (or virgl / virtio-gpu) is properly configured if hardware acceleration is absent.
