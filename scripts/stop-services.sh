#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for name in opencode ollama; do
  pid_file="$ROOT/.cppwiki/run/$name.pid"
  [[ -f "$pid_file" ]] || continue
  pid=$(cat "$pid_file")
  if [[ -r "/proc/$pid/cmdline" ]] && tr '\0' ' ' <"/proc/$pid/cmdline" | grep -q "$name"; then
    kill "$pid"
    echo "Stopped $name (PID $pid)"
  else
    echo "Ignored stale $name PID file"
  fi
  rm -f "$pid_file"
done

