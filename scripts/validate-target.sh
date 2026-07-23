#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Missing .env; run deploy-target.sh first" >&2; exit 2; }
set -a
# shellcheck disable=SC1091
source .env
set +a

"$ROOT/scripts/preflight-target.sh"
cmake -S "$ROOT/tests/fixtures/cpp-sample" \
  -B "$ROOT/tests/fixtures/cpp-sample/build" \
  -G Ninja -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build "$ROOT/tests/fixtures/cpp-sample/build"
"$ROOT/.venv/bin/python" -m pytest "$ROOT/tests" -q
"$ROOT/.venv/bin/python" -m cppwiki.validation \
  --repo "$ROOT/tests/fixtures/cpp-sample" --live --generate
