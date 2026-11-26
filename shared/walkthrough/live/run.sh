#!/usr/bin/env bash
# Picture one installer against the mock daemon, in a container.
#
#   run.sh FRONTEND [OUT]        gnome, kde, cosmic, niri or xfce
#
# OUT defaults to docs/walkthrough/mock/FRONTEND. Needs podman (or docker)
# and about 3 GB for the image and the build cache. WALK_CACHE (default
# ~/.cache/tuna-installer-walk) keeps the builds between runs; WALK_ONLY
# limits the runs (comma separated, see runs.py); WALK_VARIANT=dark or small
# makes the variant set under OUT/dark or OUT/small.
set -euo pipefail
fe="${1:?usage: run.sh gnome|kde|cosmic|niri|xfce [OUT]}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "${here}/../../.." && pwd)"
out="${2:-${repo}/docs/walkthrough/mock/${fe}}"
[[ -n "${WALK_VARIANT:-}" ]] && out="${out}/${WALK_VARIANT}"
cache="${WALK_CACHE:-${XDG_CACHE_HOME:-${HOME}/.cache}/tuna-installer-walk}"
engine="$(command -v podman || command -v docker)"
# shellcheck disable=SC1091
source "${here}/PINS"

mkdir -p "${cache}/out" "${cache}/pins" "${cache}/captures"
fetch() { # fetch DIR REPO REF
	if [[ "$(git -C "$1" rev-parse HEAD 2>/dev/null)" != "$3" ]]; then
		rm -rf "$1"
		git init -q "$1"
		git -C "$1" fetch -q --depth 1 "$2" "$3"
		git -C "$1" checkout -q FETCH_HEAD
	fi
}
fetch "${cache}/pins/fisherman" "${FISHERMAN_REPO}" "${FISHERMAN_REF}"
fetch "${cache}/pins/tunaos" "${TUNAOS_REPO}" "${TUNAOS_REF}"

image="localhost/tuna-installer-walk:${fe}"
"${engine}" build -q --build-arg "FRONTEND=${fe}" -t "${image}" "${here}" >/dev/null

common=(--rm --hostname tunaos --shm-size 512m
	-v "${repo}:/src:ro" -v "${cache}/out:/out"
	-v "${cache}/pins/fisherman:/pins/fisherman:ro" -v "${cache}/pins/tunaos:/pins/tunaos")
# The build may download sources; the walk has no network at all.
"${engine}" run "${common[@]}" --network host "${image}" bash /src/shared/walkthrough/live/build.sh "${fe}"

cap="${cache}/captures/${fe}${WALK_VARIANT:+-${WALK_VARIANT}}"
rm -rf "${cap}"
mkdir -p "${cap}"
rc=0
"${engine}" run "${common[@]}" --network none -v "${cap}:/captures" "${image}" \
	python3 /src/shared/walkthrough/live/walk.py "${fe}" /captures --work /captures/work \
	${WALK_ONLY:+--only "${WALK_ONLY}"} ${WALK_VARIANT:+--variant "${WALK_VARIANT}"} || rc=$?
mkdir -p "${out}"
"${engine}" run "${common[@]}" --network none -v "${cap}:/captures:ro" -v "${out}:/render" \
	"${image}" python3 /src/shared/walkthrough/live/render.py "${fe}" /captures /render \
	${WALK_RUN_URL:+--run "${WALK_RUN_URL}"}
echo "walkthrough: ${out} (walk exit ${rc})"
exit "${rc}"
