# Runbook: Readiness Stamp & Frontend Startup Troubleshooting

## Scope

This runbook covers diagnosing and remediating failures where the TunaOS installer frontend (`tuna-installer-xfce` / `org.tunaos.InstallerXfce`) fails to map its GUI window or write its readiness stamp during automated verification, live-ISO boot, or smoke testing.

## Background & Contract

`tuna_installer_xfce/readiness.py` emits an atomic readiness stamp file named `tuna-installer-ready` in `$XDG_RUNTIME_DIR` (or `/run/user/<uid>/app/org.tunaos.InstallerXfce/` inside Flatpak sandbox) when the installer window maps via GTK's `map` signal.

The stamp payload contains:
```
app_id=org.tunaos.InstallerXfce
window=InstallerWindow
signal=gtk-map
mapped_at=<timestamp>
page=<page_id>
```

### Why flatpak ps / process checks are insufficient

A process running inside a sandbox or background session may be active without mapping a window (e.g., waiting on unfulfilled D-Bus services, missing display servers, display manager initialization failures, or XDG runtime directory issues). The readiness stamp verifies genuine GUI presentation.

## Triage Checklist

### 1. Check if the process launched vs mapped
Inside the test VM / guest:
```bash
# Check if flatpak / binary is running
ps aux | grep -E "tuna_installer_xfce|org.tunaos.InstallerXfce"

# Inspect the readiness stamp
cat "${XDG_RUNTIME_DIR}/tuna-installer-ready" 2>/dev/null || \
cat "/run/user/$(id -u)/app/org.tunaos.InstallerXfce/tuna-installer-ready" 2>/dev/null
```

### 2. Verify XDG Runtime Directory & Permissions
If `XDG_RUNTIME_DIR` is unset or points to an unwritable path, `write_stamp()` logs a warning and skips writing to avoid blocking installation:
```bash
echo "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}"
ls -ld "${XDG_RUNTIME_DIR}"
```
Ensure `$XDG_RUNTIME_DIR` is set, owned by the active session user, and mounted read-write (`tmpfs`).

### 3. Diagnose Display Server & Session Startup
If the process fails to map:
- Check if `DISPLAY` (X11) or `WAYLAND_DISPLAY` is exported.
- Check journal logs for GTK / GDK initialization errors:
  ```bash
  journalctl --user -u org.tunaos.InstallerXfce -b --no-pager
  ```
- Inspect whether `lightdm` or the window manager (`xfwm4` / `xwayland`) crashed or restarted.

## Incident Escalation & Recovery

1. If the stamp exists but contains an unexpected `page` or window:
   - Check if an error/warning dialog intercepted the main wizard window before reaching the first page.
2. If `signal` differs from `gtk-map`:
   - Note that toolkit fallback signals (`first-frame`) indicate weaker guarantees; investigate whether GTK `map` was delivered.
3. If running in headless CI without DRM nodes:
   - Ensure the virtual frame buffer / test runner correctly initialized the X11/Wayland backend.
