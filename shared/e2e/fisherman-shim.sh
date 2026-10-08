#!/bin/bash
# The fisherman every frontend launches in the end-to-end job.
#
# Installed at /usr/local/bin/fisherman, which is the path all five frontends
# run (sudo outside Flatpak, pkexec inside). It is NOT a fake backend: the
# recipe the frontend hands over is validated by the REAL fisherman built
# from the submodule (`fisherman validate`, the same Validate() the install
# path runs first), and the recipe is kept so a later job can run the real
# install against a loop disk in a VM. What this shim does not do is
# partition the runner it is on: after validating, it streams the progress
# events a real install emits, so the frontend's progress parsing, log
# persistence and done-page transition run against the real protocol.
#
# "The real protocol" was not true when this was written. The shim streamed
# nine "[n/9] Partitioning ..." lines, described in the comment below as
# "the step lines a real run prints". fisherman prints no such lines: it
# writes newline-delimited JSON to stdout and nothing else
# (shared/progress/README.md). Two frontends parsed the invented prefix, so
# their progress bars never moved on a real install — and this gate, the one
# check whose whole purpose is to drive each frontend's real backend path,
# fed them the invented format and passed.
#
# Layout (created by setup.sh):
#   /usr/local/lib/tuna-e2e/fisherman.real   the binary built from fisherman/
#   /tmp/tuna-e2e/                           1777; recipe.json lands here
set -u
REAL=/usr/local/lib/tuna-e2e/fisherman.real
DIR=/tmp/tuna-e2e

case "${1:-}" in
  validate|images|scan|--help|-h|"")
    exec "$REAL" "$@"
    ;;
esac

RECIPE="$1"
mkdir -p "$DIR"
# Keep the recipe exactly as the frontend wrote it. The frontends delete
# their private copy the moment this process exits.
cp "$RECIPE" "$DIR/recipe.json"
chmod 0644 "$DIR/recipe.json"
echo "[e2e] recipe received: $RECIPE ($(wc -c < "$RECIPE") bytes)"

if ! "$REAL" validate "$RECIPE"; then
  echo "[e2e] the real fisherman rejected this recipe" >&2
  exit 3
fi
echo "[e2e] fisherman validate: ok"

DISK=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["disk"])' "$RECIPE")
IMAGE=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("image") or "(running system)")' "$RECIPE")
FS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("filesystem") or "xfs")' "$RECIPE")

# The events a real run emits: fisherman's stdout protocol, verbatim in shape
# (internal/progress/progress.go). Step names, weights and cumulative
# percentages are those of an uncached auto-layout install, the same profile
# shared/progress/dry-run-transcript.ndjson was generated from. total_steps
# is 8 here and is NOT a constant — fisherman computes it from the recipe.
#
# A frontend that shows a moving bar against this is parsing the protocol. A
# frontend that shows an empty one is not, which is the point of the gate.
TOTAL=8
step() { # step_name cumulative_pct weight_pct
  printf '{"type":"step","step":%d,"total_steps":%d,"step_name":"%s","cumulative_pct":%d,"weight_pct":%d,"elapsed_ms":%d,"timestamp":"%s"}\n' \
    "$N" "$TOTAL" "$1" "$2" "$3" "$((N * 200))" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  N=$((N + 1))
  sleep 0.2
}
substep() {
  printf '{"type":"substep","message":"%s","elapsed_ms":0,"timestamp":"%s"}\n' \
    "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  sleep 0.2
}
N=1
step "Partitioning disk"            0  0
substep "target disk: $DISK"
step "Formatting EFI partition"     0  1
step "Formatting root filesystem"   1  0
substep "filesystem: $FS"
step "Mounting filesystem"          1  0
step "Installing OS"                1 87
substep "image: $IMAGE"
for layer in 18 47 71; do substep "Pulling image: layer $layer/71"; done
step "Copying system Flatpaks"     88 11
step "Configuring installed system" 99  0
step "Finalizing installation"      99  1
printf '{"type":"complete","message":"Installation complete","boot_id":"0001","elapsed_ms":0,"timestamp":"%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[e2e] install simulated; recipe kept at $DIR/recipe.json"
exit 0
