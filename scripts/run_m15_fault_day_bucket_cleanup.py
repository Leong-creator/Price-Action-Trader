#!/usr/bin/env python3
"""Authorize exact paper cleanup of PA001 and FTD fault-day bucket positions."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_realtime_execution_lib import write_json
from scripts.m15_pa004_overcap_cleanup_lib import build_cleanup_plan


OUTPUT_DIR = ROOT / "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m15_longbridge_realtime_execution"
TARGET_BUCKETS = {"pa001_daily_contract_v1", "ftd_pullback_guard_confirm_v1"}
TARGET_RUNTIMES = {"M10-PA-001-1d", "M12-FTD-001-pullback-guard-confirm-1d"}


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_json_object:{path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attribution", default=str(OUTPUT_DIR / "m15_longbridge_fill_attribution_v2.json"))
    parser.add_argument("--account-state", default=str(OUTPUT_DIR / "m15_longbridge_realtime_account_state.json"))
    parser.add_argument("--output", default=str(OUTPUT_DIR / "m15_capital_bucket_migration_state.json"))
    parser.add_argument("--cleanup-epoch-id", default=f"fault-day-bucket-cleanup-{datetime.now(UTC).date().isoformat()}")
    args = parser.parse_args()
    output_path = Path(args.output).expanduser().resolve()
    previous_state: dict[str, Any] = {}
    if output_path.exists():
        previous_state = read_object(output_path)
    plan = build_cleanup_plan(
        read_object(Path(args.attribution).expanduser().resolve()),
        read_object(Path(args.account_state).expanduser().resolve()),
        cleanup_epoch_id=args.cleanup_epoch_id,
        target_buckets=TARGET_BUCKETS,
        target_runtimes=TARGET_RUNTIMES,
        aggregate_by_strategy_symbol=True,
        cleanup_scope="all_fault_day_residual_lots_in_pa001_and_ftd_buckets",
        exit_reason="authorized_fault_day_bucket_cleanup",
    )
    plan["authorized"] = True
    plan["authorized_by"] = "user"
    plan["authorized_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    plan["preserved_bucket_baselines"] = {
        str(bucket): dict(value)
        for bucket, value in (previous_state.get("bucket_baselines") or {}).items()
        if isinstance(value, dict) and bucket not in TARGET_BUCKETS
    }
    if plan["status"] == "ready":
        plan.update({
            "status": "pending_cleanup",
            "blocks_new_entries": True,
            "reason": "paper_cleanup_waiting_regular_session",
        })
    plan["inputs"] = {
        "fill_attribution": str(Path(args.attribution).expanduser().resolve()),
        "paper_account_state": str(Path(args.account_state).expanduser().resolve()),
    }
    write_json(output_path, plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0 if plan["status"] == "pending_cleanup" else 2


if __name__ == "__main__":
    raise SystemExit(main())
