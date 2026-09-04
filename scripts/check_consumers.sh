#!/usr/bin/env bash
# Reverse-dependency check: run each consuming bridge's suite against THIS tree's wheel.
#
# The bridges pin an exact pontonier version, so their normal `uv sync` would silently
# test the PREVIOUS release. This script builds the wheel, force-installs it into each
# consumer's own environment, asserts the consumer really imports it, runs the
# consumer's suite, and then restores the consumer's locked environment.
#
# Usage:
#   scripts/check_consumers.sh                      # the three sibling checkouts
#   scripts/check_consumers.sh /path/to/bridge ...  # explicit consumers
#
# Run it directly, not via `uv run`. Documented in docs/releasing.md.
set -euo pipefail

cd "$(dirname "$0")/.."
root="$(pwd)"

wheel_dir="$(mktemp -d)"
trap 'rm -rf "$wheel_dir"' EXIT
uv build --wheel --out-dir "$wheel_dir" >/dev/null
wheel="$(find "$wheel_dir" -name '*.whl')"
expected="$(uv run --no-sync python -c \
  'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"

consumers=("$@")
if [[ ${#consumers[@]} -eq 0 ]]; then
  consumers=("$root/../codex-in-claude" "$root/../moonbridge" "$root/../claude-in-codex")
fi

status=0
for consumer in "${consumers[@]}"; do
  printf '\n\033[1m==> %s\033[0m\n' "$consumer"
  if [[ ! -f "$consumer/pyproject.toml" ]]; then
    echo "no pyproject.toml in $consumer" >&2
    status=1
    continue
  fi
  (
    cd "$consumer"
    uv sync --locked
    uv pip install --python .venv/bin/python --reinstall "$wheel"
    got="$(uv run --no-sync python -c 'import importlib.metadata as m; print(m.version("pontonier"))')"
    if [[ "$got" != "$expected" ]]; then
      echo "consumer imports pontonier $got, expected $expected" >&2
      exit 1
    fi
    uv run --no-sync pytest -q -p no:cacheprovider
  ) || status=1
  # Restore the consumer's pinned pontonier whatever happened above.
  (cd "$consumer" && uv sync --locked) || status=1
done

if [[ $status -ne 0 ]]; then
  printf '\n\033[1;31m==> consumer check FAILED\033[0m\n'
  exit 1
fi
printf '\n\033[1;32m==> all consumers passed against pontonier %s\033[0m\n' "$expected"
