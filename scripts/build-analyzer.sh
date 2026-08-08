#!/usr/bin/env sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build="${1:-$root/build/clang-tool-libclang}"
install="${2:-$root/bin}"
llvm_root="${LLVM_ROOT:-$(llvm-config --prefix 2>/dev/null || true)}"
if [ -n "$llvm_root" ]; then
  cmake -S "$root/clang-tool" -B "$build" "-DLLVM_ROOT=$llvm_root"
else
  cmake -S "$root/clang-tool" -B "$build"
fi
cmake --build "$build" --config Release
mkdir -p "$install"
candidate=$(find "$build" -type f -name clangwiki-analyzer -print -quit)
test -n "$candidate"
cp "$candidate" "$install/clangwiki-analyzer"
echo "Installed: $install/clangwiki-analyzer"
