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
