#!/usr/bin/env bash
# Builds the iced tree of the browser-only COSMIC build (#105) in web/iced.
#
# The tuna-os/libcosmic fork pins iced at ICED_BASE, the commit that
# pop-os/libcosmic pins. tuna-os/iced has patch 06 and patch 03, but only
# on a newer iced that libcosmic does not build against (a changed
# Scrollable API and a second winit). So this script checks out ICED_BASE
# from tuna-os/iced and applies the two fork commits on top. Every input is
# a full commit SHA. web/cargo-patch.toml points the iced crates here.
# tests/unit/test_wasm_cosmic.py checks the format of the pins.
set -euo pipefail

ICED_REPO=https://github.com/tuna-os/iced
# pop-os/iced 5fc4372, in the tuna-os/iced history; the iced gitlink of
# tuna-os/libcosmic at LIBCOSMIC_REV (web/cargo-patch.toml).
ICED_BASE=5fc4372d877ad2ca6eaab1c0ca5e424f238b9258
# tuna-os/iced#1 (patch 06) and tuna-os/iced#2 (patch 03), in this order.
ICED_PICKS="5e69e982a0bf6fc0658653a9df9f2701ac22d5f0 febc8444ec5e00b8405b6ce8b64fa5f668dc32a5"

here=$(cd "$(dirname "$0")" && pwd)
dest="$here/iced"
rm -rf "$dest"
git init -q "$dest"
git -C "$dest" remote add origin "$ICED_REPO"
# shellcheck disable=SC2086 # one fetch argument per SHA
git -C "$dest" fetch -q --depth 2 origin "$ICED_BASE" $ICED_PICKS
git -C "$dest" -c advice.detachedHead=false checkout -q "$ICED_BASE"
for sha in $ICED_PICKS; do
  git -C "$dest" -c user.name=wasm-cosmic -c user.email=wasm-cosmic@invalid \
    cherry-pick --allow-empty -x "$sha" >/dev/null
done
git -C "$dest" log --oneline -n 3
