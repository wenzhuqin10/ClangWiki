#!/usr/bin/env sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build="${1:-$root/build/clang-tool}"
install="${2:-$root/bin}"
cmake -S "$root/clang-tool" -B "$build"
cmake --build "$build" --config Release
mkdir -p "$install"
candidate=$(find "$build" -type f -name clangwiki-analyzer -print -quit)
test -n "$candidate"
cp "$candidate" "$install/clangwiki-analyzer"
echo "Installed: $install/clangwiki-analyzer"

