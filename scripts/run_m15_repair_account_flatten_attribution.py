#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_realtime_account_state_lib import build_fill_attribution_v2


OUTPUT_DIR = ROOT / "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m15_longbridge_realtime_execution"
ACCOUNT_STATE_PATH = OUTPUT_DIR / "m15_longbridge_realtime_account_state.json"
RECONCILIATION_PATH = OUTPUT_DIR / "m15_longbridge_order_reconciliation.json"
EXECUTION_LEDGER_PATH = OUTPUT_DIR / "m15_longbridge_realtime_execution_ledger.jsonl"
REPORT_PATH = OUTPUT_DIR / "m15_historical_account_flatten_attribution_repair.json"


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def base_symbol(value: Any) -> str:
    return str(value or "").upper().removesuffix(".US")


def order_id(row: Mapping[str, Any]) -> str:
    return str(
        row.get("order_id")
        or row.get("broker_order_id")
        or row.get("longbridge_order_id")
        or ""
    )


def enrich_reconciliation_from_ledger(
    reconciliation: dict[str, Any],
    ledger: list[dict[str, Any]],
) -> None:
    local_by_order_id = {order_id(row): row for row in ledger if order_id(row)}
    preserved_fields = (
        "source_open_remaining_quantity",
        "strategy_contract_hash",
        "account_flatten_allocation",
        "historical_audit_repair",
    )
    for row in reconciliation.get("rows", []):
        if not isinstance(row, dict):
            continue
        local = local_by_order_id.get(order_id(row))
        if not local:
            continue
        for field in preserved_fields:
            row[field] = local.get(field, row.get(field))


def build_repair_plan(
    account_state: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    attribution: Mapping[str, Any],
    marker: Mapping[str, Any],
    existing_order_ids: set[str],
    *,
    window_seconds: int = 300,
) -> dict[str, Any]:
    epoch_id = str(
        marker.get("last_validation_test_epoch_id")
        or marker.get("validation_test_epoch_id")
        or marker.get("test_epoch_id")
        or ""
    )
    completed_at = parse_time(
        marker.get("validation_completed_at")
        or marker.get("validation_end_at")
        or marker.get("last_validation_end_at")
    )
    blockers: list[str] = []
    if not epoch_id:
        blockers.append("missing_validation_epoch_id")
    if completed_at is None:
        blockers.append("missing_validation_completion_time")
    positions = [
        row
        for row in account_state.get("positions", [])
        if isinstance(row, Mapping) and decimal(row.get("quantity")) != 0
    ]
    if positions:
        blockers.append("current_broker_positions_not_zero")

    remaining_by_symbol: dict[str, dict[str, Any]] = {}
    for batch in attribution.get("batches", []):
        if not isinstance(batch, Mapping):
            continue
        if str(batch.get("test_epoch_id") or "") != epoch_id:
            continue
        quantity = decimal(batch.get("remaining_quantity"))
        if quantity <= 0:
            continue
        symbol = base_symbol(batch.get("symbol"))
        direction = str(batch.get("direction") or "long")
        item = remaining_by_symbol.setdefault(
            symbol,
            {"quantity": Decimal("0"), "directions": set()},
        )
        item["quantity"] += quantity
        item["directions"].add(direction)
    for symbol, item in remaining_by_symbol.items():
        if len(item["directions"]) != 1:
            blockers.append(f"mixed_direction_remaining_position:{symbol}")

    candidate_by_symbol: dict[str, list[dict[str, Any]]] = {}
    if completed_at is not None:
        window_end = completed_at + timedelta(seconds=window_seconds)
        for row in reconciliation.get("rows", []):
            if not isinstance(row, Mapping):
                continue
            created_at = parse_time(
                row.get("created_at") or row.get("submitted_at") or row.get("updated_at")
            )
            status = str(row.get("status") or "").lower()
            candidate_order_id = order_id(row)
            if (
                created_at is None
                or created_at < completed_at
                or created_at > window_end
                or status not in {"filled", "orderstatus.filled"}
                or not candidate_order_id
            ):
                continue
            candidate_by_symbol.setdefault(base_symbol(row.get("symbol")), []).append(dict(row))

    rows_to_append: list[dict[str, Any]] = []
    for symbol, remaining in sorted(remaining_by_symbol.items()):
        candidates = candidate_by_symbol.get(symbol, [])
        if len(candidates) != 1:
            blockers.append(f"flatten_order_count_not_one:{symbol}:{len(candidates)}")
            continue
        broker_row = candidates[0]
        broker_quantity = decimal(
            broker_row.get("executed_quantity") or broker_row.get("quantity")
        )
        if broker_quantity != remaining["quantity"]:
            blockers.append(
                f"flatten_quantity_mismatch:{symbol}:{broker_quantity}:{remaining['quantity']}"
            )
            continue
        direction = next(iter(remaining["directions"]))
        expected_side = "buy" if direction == "short" else "sell"
        actual_side = str(broker_row.get("side") or "").lower()
        if actual_side != expected_side:
            blockers.append(f"flatten_side_mismatch:{symbol}:{actual_side}:{expected_side}")
            continue
        broker_order_id = order_id(broker_row)
        if broker_order_id in existing_order_ids:
            continue
        rows_to_append.append(
            {
                "stage": "M15.historical_account_flatten_attribution_repair",
                "created_at": str(broker_row.get("created_at") or ""),
                "processed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "submitted_at": str(broker_row.get("created_at") or ""),
                "submission_status": "submitted",
                "execute_orders": True,
                "paper_trading_approval": True,
                "account_flatten_allocation": True,
                "historical_audit_repair": True,
                "market_exit_no_reprice": True,
                "exit_only_position_signal": True,
                "order_id": broker_order_id,
                "broker_order_id": broker_order_id,
                "longbridge_order_id": broker_order_id,
                "runtime_id": "M15-LONGBRIDGE-SDK-AUTO-FLATTEN",
                "strategy_id": "M15-LONGBRIDGE-SDK-AUTO-FLATTEN",
                "capital_bucket": "account_validation_flatten",
                "test_epoch_id": epoch_id,
                "symbol": symbol,
                "side": expected_side,
                "direction": direction,
                "position_action": "close_short" if direction == "short" else "close_long",
                "order_type": "market",
                "quantity": str(broker_quantity),
                "submitted_quantity": str(broker_quantity),
                "local_simulation_ignored": True,
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
            }
        )
    unmatched_candidates = sorted(set(candidate_by_symbol) - set(remaining_by_symbol))
    if unmatched_candidates:
        blockers.append(
            "unexpected_filled_orders_in_flatten_window:" + ",".join(unmatched_candidates)
        )
    return {
        "schema_version": "m15.historical-account-flatten-attribution-repair.v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "blocked" if blockers else ("already_applied" if not rows_to_append else "ready"),
        "test_epoch_id": epoch_id,
        "validation_completed_at": (
            completed_at.isoformat().replace("+00:00", "Z") if completed_at else ""
        ),
        "remaining_symbol_count": len(remaining_by_symbol),
        "repair_order_count": len(rows_to_append),
        "blockers": blockers,
        "rows_to_append": rows_to_append,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair historical account-flatten attribution without broker writes."
    )
    parser.add_argument("--marker-archive", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    account_state = read_json(ACCOUNT_STATE_PATH)
    reconciliation = read_json(RECONCILIATION_PATH)
    marker = read_json(args.marker_archive)
    ledger = read_jsonl(EXECUTION_LEDGER_PATH)
    enrich_reconciliation_from_ledger(reconciliation, ledger)
    attribution = build_fill_attribution_v2(account_state, reconciliation)
    plan = build_repair_plan(
        account_state,
        reconciliation,
        attribution,
        marker,
        {order_id(row) for row in ledger if order_id(row)},
    )
    if args.execute and plan["status"] == "ready":
        with EXECUTION_LEDGER_PATH.open("a", encoding="utf-8") as handle:
            for row in plan["rows_to_append"]:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        plan["status"] = "applied"
    elif args.execute and plan["status"] == "blocked":
        plan["execution_note"] = "Blocked plan was not written to the execution ledger."
    REPORT_PATH.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0 if plan["status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
