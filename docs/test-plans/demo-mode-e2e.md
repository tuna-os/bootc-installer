# Demo Mode E2E Validation

Automated E2E test for demo mode and screen-isolated preview support for rapid UI iteration.

Refs: #38|Closes

## 1. Automated Demo Mode Test (`tests/ui/test_demo_e2e.py`)

A single integration test that:
- Launches the app with `BOOTC_DEMO=1` + `TUNA_TEST=1`
- Auto-advances through all wizard steps
- Verifies that the confirm screen renders with the "( Become Legend )" button
- Clicks confirm
- Waits for demo install to complete (~5 seconds)
- Verifies done screen shows success state

## 2. Screen-Isolated Preview Mode

Add `BOOTC_PREVIEW_SCREEN=<name>` env var support:
- Skips wizard, jumps directly to the named screen
- `progress`: immediately starts demo mode
- `done`: shows success state with dummy data
- `confirm`: shows with sample finals data
- `credits`: opens credits window directly

This lets you quickly change the UI of one screen at a time.

## 3. Dev Setup Documentation

Document in `README.md` or `docs/DEV_SETUP.md`:
- How to create the `dakota-lab` toolbox
- Required packages (meson, blueprint-compiler, libadwaita-devel, etc.)
- How to run demo mode
- How to run tests

## Files to Change

- [x] `tests/ui/test_demo_e2e.py` (new)
- [x] `bootc_installer/windows/main_window.py` (`BOOTC_PREVIEW_SCREEN` support)
- [x] `run-dev.sh` (document better, add `--screen` flag)
- [x] `README.md` or `docs/DEV_SETUP.md` (dev setup guide)

## Acceptance

- [x] `xvfb-run -a pytest tests/ui/test_demo_e2e.py -v` passes
- [x] `BOOTC_PREVIEW_SCREEN=progress` opens directly to progress in demo
- [x] The dev setup docs let a new contributor run the app in < 10 min
