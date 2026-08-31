#!/usr/bin/env bash
# Enforce a ceiling on duplicated source/test code blocks (pylint duplicate-code).
# The allowed count is read from pyproject.toml [tool.ipmininet] duplication_max,
# so the project config file stays the single source of truth.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BASELINE="$(uv run python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["tool"]["ipmininet"].get("duplication_max", 0))')"

OUT="$(uv run pylint ipmininet/ 2>&1 || true)"
COUNT="$(printf '%s\n' "$OUT" | grep -c "R0801" || true)"

if [ "$COUNT" -gt "$BASELINE" ]; then
    printf 'FAIL: %s duplicated code block(s) exceed the baseline of %s\n' "$COUNT" "$BASELINE" >&2
    printf '%s\n' "$OUT" | grep -B1 "duplicate-code" || true
    exit 1
fi
printf 'OK: %s duplicated code block(s) <= baseline %s\n' "$COUNT" "$BASELINE"
