#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ $# -gt 0 ]]; then
  echo "Usage: $0" >&2
  exit 2
fi

OUTPUT_DIR="reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m15_startup"
LOG_FILE="$OUTPUT_DIR/m15_startup_bootstrap.log"
LOCK_FILE="$OUTPUT_DIR/startup.flock"

mkdir -p "$OUTPUT_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another startup bootstrap holds the lock; exit."
  exit 0
fi

if [[ -f "$LOG_FILE" ]] && [[ "$(wc -c < "$LOG_FILE")" -gt 5242880 ]]; then
  mv "$LOG_FILE" "$LOG_FILE.$(date -u +%Y%m%dT%H%M%SZ).old"
fi

exec >>"$LOG_FILE" 2>&1

echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) M15 startup bootstrap ===="

PYTHON_BIN="$ROOT_DIR/.venv-m15/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Project virtualenv Python is unavailable: $PYTHON_BIN"
  exit 1
fi

# This gate is offline and runs before OAuth, market data or account contexts.
"$PYTHON_BIN" scripts/run_m15_sdk_provenance.py --verify

run_step() {
  local label="$1"
  shift
  echo "-- $label"
  # Daemon descendants must not inherit the bootstrap lock after it exits.
  "$@" 9>&-
}

start_stack() {
  local failed=0
  run_step "start M15 Longbridge SDK realtime runtime" \
    "$PYTHON_BIN" scripts/run_m15_longbridge_sdk_runtime.py \
    --daemon \
    --config config/m15_longbridge_marketdata.production.json || failed=1

  run_step "start M15 background watchdog" \
    "$PYTHON_BIN" scripts/run_m15_background_watchdog.py \
    --daemon \
    --config config/m15_background_watchdog.production.json || failed=1

  return "$failed"
}

if ! start_stack; then
  echo "Initial stack start failed; automatic retries are disabled."
  exit 1
fi

run_step "check M15 Longbridge SDK realtime status" \
  "$PYTHON_BIN" scripts/run_m15_longbridge_sdk_runtime.py \
  --status \
  --config config/m15_longbridge_marketdata.production.json

run_step "check M15 background watchdog status" \
  "$PYTHON_BIN" scripts/run_m15_background_watchdog.py \
  --status \
  --config config/m15_background_watchdog.production.json

echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) M15 startup bootstrap done ===="
