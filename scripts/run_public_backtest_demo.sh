#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Missing $VENV_PY. Create the local demo environment first with: python -m venv .venv" >&2
  exit 1
fi

exec "$VENV_PY" "$ROOT/scripts/run_public_backtest_demo.py" "$@"
