#!/usr/bin/env bash
set -euo pipefail

if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

TEMP_OLLAMA_PID=""
cleanup_temp_ollama() {
  if [[ -n "$TEMP_OLLAMA_PID" ]] && kill -0 "$TEMP_OLLAMA_PID" 2>/dev/null; then
    kill "$TEMP_OLLAMA_PID"
  fi
}
trap cleanup_temp_ollama EXIT
if ! curl -fsS --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  nohup ollama serve >/tmp/cppwiki-ollama-install.log 2>&1 &
  TEMP_OLLAMA_PID=$!
  for _ in $(seq 1 30); do
    curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    sleep 1
  done
fi

ollama pull bge-m3
if [[ "${CPPWIKI_SKIP_GENERATOR_MODEL:-0}" != "1" ]]; then
  ollama pull "${CPPWIKI_LOCAL_GENERATOR_MODEL:-qwen3.5:4b}"
fi
