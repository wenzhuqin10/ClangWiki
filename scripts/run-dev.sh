#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${1:-dev-gpu}"
set -a
# shellcheck disable=SC1090
source "$ROOT/config/profiles/$PROFILE.env"
set +a

mkdir -p "$ROOT/logs"
if ! curl -fsS "$CPPWIKI_EMBED_URL/api/version" >/dev/null 2>&1; then
  nohup ollama serve >"$ROOT/logs/ollama.log" 2>&1 &
fi
if ! curl -fsS "$CPPWIKI_OPENCODE_URL/global/health" >/dev/null 2>&1; then
  OPENCODE_BIN="${CPPWIKI_OPENCODE_BIN:-opencode}"
  nohup "$OPENCODE_BIN" serve --hostname 127.0.0.1 --port 4096 \
    >"$ROOT/logs/opencode.log" 2>&1 &
fi
exec "$ROOT/.venv/bin/uvicorn" cppwiki.api:app \
  --app-dir "$ROOT/backend" --host 127.0.0.1 --port 8000 --reload

