#!/usr/bin/env bash
# VoiceOS Custom MCP launch command. stdout is the MCP wire — never echo there.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACTIVATE="$ROOT/.venv/bin/activate"
PY="$ROOT/.venv/bin/python"
if [[ ! -f "$ACTIVATE" || ! -x "$PY" ]]; then
  echo "Draft venv missing: $ROOT/.venv" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$ACTIVATE"
export PYTHONUNBUFFERED=1
exec "$PY" -u "$ROOT/scripts/voiceos_mcp.py"
