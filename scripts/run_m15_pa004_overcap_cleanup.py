#!/usr/bin/env python3
"""Prepare the PA004 exact-batch paper cleanup consumed by the SDK runtime."""
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

DEFAULT_OUTPUT_DIR = (
    ROOT
    / "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation"
    / "m15_longbridge_realtime_execution"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare an exact-batch PA004 cleanup for the Longbridge paper runtime."
    )
    parser.add_argument(
        "--attribution",
        default=str(DEFAULT_OUTPUT_DIR / "m15_longbridge_fill_attribution_v2.json"),
    )
    parser.add_argument(
        "--account-state",
        default=str(DEFAULT_OUTPUT_DIR / "m15_longbridge_realtime_account_state.json"),
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR / "m15_capital_bucket_migration_state.json"),
    )
    parser.add_argument(
        "--cleanup-epoch-id",
        default=f"pa004-fresh-baseline-{datetime.now(UTC).date().isoformat()}",
    )
    return parser.parse_args()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_json_object:{path}")
    return value


def main() -> int:
    args = parse_args()
    attribution_path = Path(args.attribution).expanduser().resolve()
    account_path = Path(args.account_state).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    plan = build_cleanup_plan(
        read_object(attribution_path),
        read_object(account_path),
        cleanup_epoch_id=str(args.cleanup_epoch_id),
    )
    if plan["status"] == "ready":
        plan["status"] = "pending_cleanup"
        plan["blocks_new_entries"] = True
        plan["reason"] = "paper_cleanup_waiting_regular_session"
    plan["inputs"] = {
        "fill_attribution": str(attribution_path),
        "paper_account_state": str(account_path),
    }
    write_json(output_path, plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0 if plan["status"] == "pending_cleanup" else 2


if __name__ == "__main__":
    raise SystemExit(main())
