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

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Project virtualenv Python is unavailable: $PYTHON_BIN"
  exit 1
fi

run_step() {
  local label="$1"
  shift
  echo "-- $label"
  "$@"
}

run_step "start M15 Longbridge SDK realtime runtime" \
  "$PYTHON_BIN" scripts/run_m15_longbridge_sdk_runtime.py \
  --daemon \
  --dispatch \
  --config config/examples/m15_longbridge_sdk_runtime.json

run_step "start M15 background watchdog" \
  "$PYTHON_BIN" scripts/run_m15_background_watchdog.py \
  --daemon \
  --config config/examples/m15_background_watchdog.json

run_step "start local postclose scheduler" \
  "$PYTHON_BIN" scripts/run_m12_m14_local_postclose_scheduler.py \
  --daemon \
  --config config/examples/m12_m14_local_postclose_scheduler.json

run_step "check M15 Longbridge SDK realtime status" \
  "$PYTHON_BIN" scripts/run_m15_longbridge_sdk_runtime.py \
  --status \
  --config config/examples/m15_longbridge_sdk_runtime.json

run_step "check M15 background watchdog status" \
  "$PYTHON_BIN" scripts/run_m15_background_watchdog.py \
  --status \
  --config config/examples/m15_background_watchdog.json

run_step "check local postclose scheduler status" \
  "$PYTHON_BIN" scripts/run_m12_m14_local_postclose_scheduler.py \
  --status \
  --config config/examples/m12_m14_local_postclose_scheduler.json

echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) M15 startup bootstrap done ===="
