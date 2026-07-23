#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cmake -S "$ROOT/clang-tool" -B "$ROOT/build/clang-tool" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$ROOT/build/clang-tool"
mkdir -p "$ROOT/bin"
cp "$ROOT/build/clang-tool/cpp-analyzer" "$ROOT/bin/cpp-analyzer"
echo "Analyzer built at $ROOT/bin/cpp-analyzer"

