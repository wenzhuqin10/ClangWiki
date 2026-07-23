#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAILURES=0
WARNINGS=0

ok() { printf '[OK] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; WARNINGS=$((WARNINGS + 1)); }
fail() { printf '[FAIL] %s\n' "$1"; FAILURES=$((FAILURES + 1)); }

if [[ "$(uname -s)" == "Linux" ]]; then ok "Linux environment"; else fail "Linux/WSL2 is required"; fi
if grep -qi microsoft /proc/version 2>/dev/null; then ok "WSL detected"; else warn "Not running under WSL; verify deployment intent"; fi
if [[ "$ROOT" == /mnt/* ]]; then fail "Repository is under /mnt; copy it into the WSL ext4 filesystem"; else ok "Repository is on the Linux filesystem"; fi

MEMORY_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || printf '0')
DISK_GB=$(df -Pk "$ROOT" | awk 'NR==2 {printf "%d", $4/1024/1024}')
(( MEMORY_GB >= 12 )) && ok "Memory: ${MEMORY_GB} GiB" || warn "Memory below 12 GiB: ${MEMORY_GB} GiB"
(( DISK_GB >= 15 )) && ok "Free disk: ${DISK_GB} GiB" || fail "At least 15 GiB free disk is required"

for command_name in python3 cmake ninja clang clangd sqlite3 node npm opencode ollama curl; do
  if command -v "$command_name" >/dev/null 2>&1; then
    ok "$command_name: $(command -v "$command_name")"
  else
    fail "Missing command: $command_name"
  fi
done

[[ -x "$ROOT/bin/cpp-analyzer" ]] && ok "cpp-analyzer is built" || fail "Run scripts/build-analyzer.sh"
[[ -x "$ROOT/.venv/bin/python" ]] && ok "Python virtual environment exists" || fail "Run scripts/bootstrap-wsl.sh"
[[ -f "$ROOT/.env" ]] && ok ".env exists" || fail "Deploy a target profile to .env"

if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ROOT/.env"; set +a
  [[ "${CPPWIKI_EMBED_MODEL:-}" == "bge-m3" ]] && ok "Embedding model is bge-m3" || fail "CPPWIKI_EMBED_MODEL must be bge-m3"
  [[ "${CPPWIKI_EMBED_NUM_GPU:-}" == "0" ]] && ok "CPU embedding is forced" || fail "CPPWIKI_EMBED_NUM_GPU must be 0"
  [[ "${CPPWIKI_OPENCODE_MODEL:-}" == "glm-5.1" ]] && ok "Generator model is glm-5.1" || fail "Generator model must be glm-5.1"
  if grep -Eq 'company|REPLACE|YOUR_|CHANGE_ME' "$ROOT/.env"; then
    warn "The environment profile still contains a provider placeholder"
  fi
fi

if ollama list 2>/dev/null | grep -q '^bge-m3'; then ok "bge-m3 is installed"; else fail "Run scripts/install-models.sh with CPPWIKI_SKIP_GENERATOR_MODEL=1"; fi

if curl -fsS --max-time 5 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  ok "Ollama API is healthy"
else
  warn "Ollama API is not running yet"
fi
if curl -fsS --max-time 5 http://127.0.0.1:4096/global/health >/dev/null 2>&1; then
  ok "OpenCode Server is healthy"
else
  warn "OpenCode Server is not running yet"
fi

printf '\nPreflight result: %d failure(s), %d warning(s)\n' "$FAILURES" "$WARNINGS"
exit "$FAILURES"

