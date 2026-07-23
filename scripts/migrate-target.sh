#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "migrate-target.sh is retained for compatibility; use deploy-target.sh." >&2
exec "$ROOT/scripts/deploy-target.sh" "${1:-zai}"
