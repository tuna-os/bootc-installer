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
    for manifest in flatpak/*installer*.json; do
      python3 -m json.tool "$manifest" > /dev/null
      jq -e '."app-id" and .runtime and .command' "$manifest" > /dev/null
    done

# GNOME screenshot walkthrough, the way screenshots-gnome.yml runs it.
capture:
    test -f build/bootc_installer/bootc-installer.gresource || (meson setup build -Dbuild-fisherman=false && ninja -C build)
    BOOTC_RESOURCE=build/bootc_installer/bootc-installer.gresource \
      xvfb-run -a -s "-screen 0 1400x1000x24" python3 tests/gui/capture-screens.py docs/screenshots

# Fold every frontend's committed capture into docs/walkthrough/ (what walkthrough.yml does from CI artifacts).
walkthrough:
    rm -rf _captures && mkdir -p _captures
    cp -r docs/screenshots _captures/gnome
    for n in kde cosmic niri xfce; do cp -r frontends/$n/docs/screenshots _captures/$n; done
    test -f _captures/cosmic/walkthrough-cosmic.json || python3 shared/walkthrough/report_from_pngs.py cosmic _captures/cosmic
    python3 shared/walkthrough/aggregate.py _captures docs/walkthrough
