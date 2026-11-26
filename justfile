# Reproduce the fast validation pieces locally.
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

check: go-test python-test flatpak-validate

go-test:
    cd fisherman/fisherman && go vet ./... && go test -count=1 ./...

python-test:
    python3 -m pytest tests/unit/ -v --tb=short

flatpak-validate:
    for manifest in flatpak/*installer*.json; do \
      python3 -m json.tool "$manifest" > /dev/null; \
      jq -e '."app-id" and .runtime and .command' "$manifest" > /dev/null; \
    done

# GNOME screenshot walkthrough, the way screenshots-gnome.yml runs it.
# GTK4 has no offscreen backend (unlike Qt's, which is how the KDE capture
# runs with no display server), so a display is still required: the existing
# one when set, else Xvfb on a stock runner. tests/gui/capture-screens.py
# errors out clearly when neither exists.
capture:
    test -f build/bootc_installer/bootc-installer.gresource || (meson setup build -Dbuild-fisherman=false && ninja -C build)
    if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then BOOTC_RESOURCE=build/bootc_installer/bootc-installer.gresource python3 tests/gui/capture-screens.py docs/screenshots; elif command -v xvfb-run >/dev/null 2>&1; then BOOTC_RESOURCE=build/bootc_installer/bootc-installer.gresource xvfb-run -a -s "-screen 0 1400x1000x24" python3 tests/gui/capture-screens.py docs/screenshots; else echo "just capture: no display server and no xvfb-run; run under Xvfb or with DISPLAY set" >&2; exit 1; fi

# `just walkthrough kde` (or gnome, cosmic, niri, xfce): picture each page of
# that installer against the mock daemon, into docs/walkthrough/mock/kde
# (tools/walkthrough/README.md; needs podman or docker). With no frontend:
# fold the committed captures into docs/walkthrough/ (as walkthrough.yml does).
walkthrough frontend="":
    if [ -n "{{frontend}}" ]; then exec tools/walkthrough/run.sh "{{frontend}}"; fi
    just walkthrough-aggregate

walkthrough-aggregate:
    rm -rf _captures && mkdir -p _captures
    cp -r docs/screenshots _captures/gnome
    for n in kde cosmic niri xfce; do cp -r frontends/$n/docs/screenshots _captures/$n; done
    test -f _captures/cosmic/walkthrough-cosmic.json || python3 shared/walkthrough/report_from_pngs.py cosmic _captures/cosmic
    python3 shared/walkthrough/aggregate.py _captures docs/walkthrough
