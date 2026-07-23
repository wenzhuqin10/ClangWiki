#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  build-essential bear clang clang-tools clangd cmake curl git \
  jq libclang-dev llvm-dev ninja-build nodejs npm python3 python3-pip \
  python3-venv rsync sqlite3

python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/pip" install -e "$ROOT[test,faiss]"

if ! command -v opencode >/dev/null 2>&1; then
  NPM_REGISTRY="${CPPWIKI_NPM_REGISTRY:-https://registry.npmmirror.com}"
  sudo npm install -g opencode-ai --registry="$NPM_REGISTRY" --no-audit --no-fund
fi
echo "WSL dependencies are ready in $ROOT/.venv"
