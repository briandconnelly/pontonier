#!/usr/bin/env bash
# Reverse-dependency check: run each consuming bridge's suite against THIS tree's wheel.
#
# The bridges pin an exact pontonier version, so their normal `uv sync` would silently
# test the PREVIOUS release. This script builds the wheel, installs it over the pinned
# one in each consumer's own environment (only pontonier moves; every other locked
# dependency stays as the consumer ships it), asserts the consumer really imports it
# (the installed distribution's `direct_url.json` must name the wheel just built, by
# full path — the version check alone cannot fail before the version is bumped, because
# consumers pin the current release), runs the consumer's suite, and then restores the
# consumer's locked environment, also on Ctrl-C.
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
# The consumer whose environment currently holds the development wheel; the trap
# restores it so an interrupted run does not leave a sibling testing an unreleased
# pontonier on its next `uv run pytest`.
current=""
cleanup() {
  if [[ -n "$current" ]]; then
    (cd "$current" && uv sync --locked) || echo "could not restore $current; run 'uv sync --locked' there" >&2
  fi
  rm -rf "$wheel_dir"
}
trap cleanup EXIT
uv build --wheel --out-dir "$wheel_dir" >/dev/null
wheel="$(find "$wheel_dir" -name '*.whl')"
[[ -n "$wheel" ]] || { echo "no wheel was built" >&2; exit 1; }
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
  current="$consumer"
  # The subshell is deliberately NOT the left operand of `||`: bash ignores errexit
  # inside any command in an OR-list, so `( ... ) || status=1` would let a failed
  # sync or install fall through to the suite. Capture its status the long way.
  set +e
  (
    set -e
    cd "$consumer"
    uv sync --locked
    uv pip install --python .venv/bin/python --no-deps --reinstall-package pontonier "$wheel"
    uv run --no-sync python - "$wheel" <<'PY' || { echo "consumer is not importing the freshly built wheel" >&2; exit 1; }
import importlib.metadata as m
import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

wheel = Path(sys.argv[1]).resolve()
raw = m.distribution("pontonier").read_text("direct_url.json")
if not raw:
    sys.exit("pontonier has no direct_url.json: it was not installed from a local file")
record = json.loads(raw)
url = urlparse(record.get("url", ""))
# Full path, not basename: the wheel lives in a directory created for this run, so a
# stale same-named wheel from an earlier build cannot match. (uv records no hash in
# archive_info for a local wheel, so the path is the provenance.)
if url.scheme != "file" or Path(unquote(url.path)).resolve() != wheel:
    sys.exit(f"installed from {record.get('url')!r}, expected the built wheel {wheel}")
PY
    got="$(uv run --no-sync python -c 'import importlib.metadata as m; print(m.version("pontonier"))')"
    if [[ "$got" != "$expected" ]]; then
      echo "consumer imports pontonier $got, expected $expected" >&2
      exit 1
    fi
    uv run --no-sync pytest -q -p no:cacheprovider
  )
  rc=$?
  set -e
  [[ $rc -eq 0 ]] || status=1
  # Restore the consumer's pinned pontonier after a completed or failed suite; the
  # trap covers an interrupted one.
  (cd "$consumer" && uv sync --locked) || status=1
  current=""
done

if [[ $status -ne 0 ]]; then
  printf '\n\033[1;31m==> consumer check FAILED\033[0m\n'
  exit 1
fi
printf '\n\033[1;32m==> all consumers passed against pontonier %s\033[0m\n' "$expected"
