#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUTPUT_DIR="reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m15_startup"
LOG_FILE="$OUTPUT_DIR/m15_startup_bootstrap.log"
LOCK_DIR="$OUTPUT_DIR/startup.lock"

mkdir -p "$OUTPUT_DIR"

if [[ -f "$LOG_FILE" ]] && [[ "$(wc -c < "$LOG_FILE")" -gt 5242880 ]]; then
  mv "$LOG_FILE" "$LOG_FILE.$(date -u +%Y%m%dT%H%M%SZ).old"
fi

exec >>"$LOG_FILE" 2>&1

echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) M15 startup bootstrap ===="

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another startup bootstrap is already running; exit."
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

PYTHON_BIN="${PYTHON_BIN:-python}"

run_step() {
  local label="$1"
  shift
  echo "-- $label"
  "$@"
}

run_step "start M12.47 session supervisor" \
  "$PYTHON_BIN" scripts/run_m12_47_session_supervisor.py \
  --daemon \
  --config config/examples/m12_47_session_supervisor.json

run_step "start M15 Longbridge SDK realtime runtime" \
  "$PYTHON_BIN" scripts/run_m15_longbridge_sdk_runtime.py \
  --daemon \
  --dispatch \
  --config config/examples/m15_longbridge_sdk_runtime.json

run_step "start M15 background watchdog" \
  "$PYTHON_BIN" scripts/run_m15_background_watchdog.py \
  --daemon \
  --config config/examples/m15_background_watchdog.json

run_step "check M12.47 status" \
  "$PYTHON_BIN" scripts/run_m12_47_session_supervisor.py \
  --status \
  --config config/examples/m12_47_session_supervisor.json

run_step "check M15 Longbridge SDK realtime status" \
  "$PYTHON_BIN" scripts/run_m15_longbridge_sdk_runtime.py \
  --status \
  --config config/examples/m15_longbridge_sdk_runtime.json

run_step "check M15 background watchdog status" \
  "$PYTHON_BIN" scripts/run_m15_background_watchdog.py \
  --status \
  --config config/examples/m15_background_watchdog.json

run_step "check opening trade readiness" \
  "$PYTHON_BIN" scripts/run_m15_opening_trade_readiness.py \
  --config config/examples/m15_opening_trade_readiness.paper_orders_enabled.json

echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) M15 startup bootstrap done ===="
