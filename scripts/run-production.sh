#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Missing .env; run scripts/deploy-target.sh first" >&2; exit 2; }
set -a
# shellcheck disable=SC1091
source .env
set +a

mkdir -p logs .cppwiki/run

wait_for() {
  local name="$1" url="$2"
  for _ in $(seq 1 60); do
    curl -fsS --max-time 2 "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "$name did not become healthy: $url" >&2
  return 1
}

if ! curl -fsS --max-time 2 "$CPPWIKI_EMBED_URL/api/version" >/dev/null 2>&1; then
  nohup ollama serve >logs/ollama.log 2>&1 &
  echo $! >.cppwiki/run/ollama.pid
fi
wait_for "Ollama" "$CPPWIKI_EMBED_URL/api/version"

if ! curl -fsS --max-time 2 "$CPPWIKI_OPENCODE_URL/global/health" >/dev/null 2>&1; then
  OPENCODE_BIN="${CPPWIKI_OPENCODE_BIN:-opencode}"
  nohup "$OPENCODE_BIN" serve --hostname 127.0.0.1 --port 4096 \
    >logs/opencode.log 2>&1 &
  echo $! >.cppwiki/run/opencode.pid
fi
wait_for "OpenCode" "$CPPWIKI_OPENCODE_URL/global/health"

echo "Starting C++ DeepWiki at http://127.0.0.1:8000"
exec "$ROOT/.venv/bin/uvicorn" cppwiki.api:app \
  --app-dir "$ROOT/backend" --host 127.0.0.1 --port 8000

