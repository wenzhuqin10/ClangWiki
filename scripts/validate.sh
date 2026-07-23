#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${1:-dev-gpu}"
set -a
# shellcheck disable=SC1090
source "$ROOT/config/profiles/$PROFILE.env"
set +a

cmake -S "$ROOT/tests/fixtures/cpp-sample" \
  -B "$ROOT/tests/fixtures/cpp-sample/build" \
  -G Ninja -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build "$ROOT/tests/fixtures/cpp-sample/build"
"$ROOT/.venv/bin/python" -m pytest "$ROOT/tests" -q
"$ROOT/.venv/bin/python" -m cppwiki.validation \
  --repo "$ROOT/tests/fixtures/cpp-sample" --live
