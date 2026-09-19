#!/usr/bin/env bash
# Render a frontend in a real browser and walk its wizard with Playwright.
#
#   shared/browser/run.sh gnome [outdir]
#   shared/browser/run.sh xfce  [outdir]
#
# Starts the right Broadway daemon, starts the frontend against it, runs the
# Playwright driver, and tears both down. Nothing here touches a disk: the
# window is built from the frontend's own capture fixtures.
set -euo pipefail

FRONTEND="${1:?usage: run.sh gnome|xfce [outdir]}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${2:-$REPO/docs/browser/$FRONTEND}"

case "$FRONTEND" in
  gnome) DAEMON=gtk4-broadwayd; TOOLKIT=gtk4 ;;
  xfce)  DAEMON=broadwayd;      TOOLKIT=gtk3 ;;
  *) echo "run.sh: unknown frontend '$FRONTEND'" >&2; exit 2 ;;
esac

command -v "$DAEMON" >/dev/null || {
  echo "run.sh: $DAEMON not found." >&2
  echo "  gtk4-broadwayd ships in libgtk-4-bin, broadwayd in libgtk-3-bin." >&2
  exit 127
}

# Broadway serves display :N on port 8080+N. Pick a free pair rather than a
# fixed one so two frontends can be walked at once, and so a leftover daemon
# from an earlier run cannot be mistaken for this one's.
DISPLAY_NUM=""
for n in $(seq 5 40); do
  if ! (exec 3<>"/dev/tcp/127.0.0.1/$((8080 + n))") 2>/dev/null; then
    DISPLAY_NUM="$n"; break
  fi
done
[ -n "$DISPLAY_NUM" ] || { echo "run.sh: no free Broadway port in 8085-8120" >&2; exit 1; }
PORT=$((8080 + DISPLAY_NUM))

# Both daemon and client must agree on XDG_RUNTIME_DIR: it is where the
# display socket lands, and the GTK3 capture harness sets its own if one is
# not already in the environment -- which is how the client ends up looking
# for the socket in a directory the daemon never wrote to.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-$(mktemp -d)}"
mkdir -p "$XDG_RUNTIME_DIR"; chmod 700 "$XDG_RUNTIME_DIR"

WORK="$(mktemp -d)"
CMD="$WORK/cmd"; STATE="$WORK/state"
: > "$CMD"

DAEMON_PID=""; APP_PID=""
cleanup() {
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null || true
  [ -n "$DAEMON_PID" ] && kill "$DAEMON_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "→ $DAEMON on :$DISPLAY_NUM (http://127.0.0.1:$PORT)"
"$DAEMON" ":$DISPLAY_NUM" > "$WORK/daemon.log" 2>&1 &
DAEMON_PID=$!

for _ in $(seq 1 50); do
  (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break
  sleep 0.2
done

echo "→ $FRONTEND under GDK_BACKEND=broadway"
PY="${PYTHON:-python3}"
BROWSER_CMD_FILE="$CMD" BROWSER_STATE_FILE="$STATE" \
GDK_BACKEND=broadway BROADWAY_DISPLAY=":$DISPLAY_NUM" \
  "$PY" "$REPO/shared/browser/present.py" "$FRONTEND" > "$WORK/app.log" 2>&1 &
APP_PID=$!

for _ in $(seq 1 100); do
  grep -q '^PAGES ' "$WORK/app.log" 2>/dev/null && break
  kill -0 "$APP_PID" 2>/dev/null || { echo "run.sh: $FRONTEND exited during startup" >&2
                                      tail -30 "$WORK/app.log" >&2; exit 1; }
  sleep 0.3
done
grep -q '^PAGES ' "$WORK/app.log" 2>/dev/null || {
  echo "run.sh: $FRONTEND never reported its pages" >&2; tail -30 "$WORK/app.log" >&2; exit 1; }

echo "→ Playwright"
mkdir -p "$OUT"
status=0
node "$REPO/shared/browser/walk.mjs" \
  --port "$PORT" --cmd "$CMD" --state "$STATE" \
  --out "$OUT" --toolkit "$TOOLKIT" --name "$FRONTEND" || status=$?

if [ "$status" -ne 0 ]; then
  echo "── $FRONTEND app log ──" >&2
  tail -30 "$WORK/app.log" >&2
fi
exit "$status"
