#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-zai}"

if [[ "$ROOT" == /mnt/* ]]; then
  echo "Refusing deployment under /mnt. Copy the repository to ~/projects first." >&2
  exit 2
fi

"$ROOT/scripts/bootstrap-wsl.sh"
"$ROOT/scripts/build-analyzer.sh"
CPPWIKI_SKIP_GENERATOR_MODEL=1 "$ROOT/scripts/install-models.sh"

case "$MODE" in
  zai)
    cp "$ROOT/config/profiles/production-zai-cpu.env" "$ROOT/.env"
    cp "$ROOT/config/opencode/zai-general.json" "$ROOT/opencode.json"
    ;;
  coding-plan)
    cp "$ROOT/config/profiles/production-zai-cpu.env" "$ROOT/.env"
    cp "$ROOT/config/opencode/zai-coding-plan.json" "$ROOT/opencode.json"
    ;;
  enterprise)
    cp "$ROOT/config/profiles/target-cpu-glm.env" "$ROOT/.env"
    cp "$ROOT/config/opencode/enterprise-managed.json" "$ROOT/opencode.json"
    ;;
  *)
    echo "Usage: scripts/deploy-target.sh [zai|coding-plan|enterprise]" >&2
    exit 2
    ;;
esac
chmod 600 "$ROOT/.env"

echo
echo "Base deployment completed for mode: $MODE"
echo "Human authentication checkpoint:"
echo "  1. Run: opencode auth login"
echo "  2. For a custom provider choose Other and use provider id: zai"
echo "  3. Paste the API key only into the OpenCode prompt"
echo "  4. Verify: opencode auth list && opencode models zai"
echo "  5. Run: scripts/preflight-target.sh"
