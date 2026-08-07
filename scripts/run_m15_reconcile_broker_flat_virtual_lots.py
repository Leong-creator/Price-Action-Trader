#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT
    / "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation"
    / "m15_longbridge_realtime_execution"
)
ACCOUNT_STATE_PATH = OUTPUT_DIR / "m15_longbridge_realtime_account_state.json"
ATTRIBUTION_PATH = OUTPUT_DIR / "m15_longbridge_fill_attribution_v2.json"
RECONCILIATION_PATH = OUTPUT_DIR / "m15_longbridge_order_reconciliation.json"
ADJUSTMENTS_PATH = OUTPUT_DIR / "m15_account_reconciliation_adjustments.json"
REPORT_PATH = OUTPUT_DIR / "m15_broker_flat_virtual_lot_reconciliation.json"
FORMAL_EPOCH_PATH = OUTPUT_DIR / "m15_sdk_formal_test_epoch.json"
ZERO = Decimal("0")


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return ZERO


def base_symbol(value: Any) -> str:
    return str(value or "").upper().removesuffix(".US")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


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


def order_id(row: Mapping[str, Any]) -> str:
    return str(row.get("order_id") or row.get("id") or "").strip()


def canonical_side(row: Mapping[str, Any]) -> str:
    side = str(row.get("side") or row.get("order_side") or "").strip().lower()
    if side.endswith("sell") or side == "sell":
        return "sell"
    if side.endswith("buy") or side == "buy":
        return "buy"
    return side


def canonical_status(row: Mapping[str, Any]) -> str:
    return str(row.get("canonical_status") or row.get("status") or "").strip().lower()


def build_broker_flat_adjustments(
    account_state: Mapping[str, Any],
    attribution: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    existing: Mapping[str, Any],
    *,
    active_test_epoch_ids: set[str] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    if str(account_state.get("account_channel") or "") != "lb_papertrading":
        blockers.append("account_not_confirmed_paper")
    if account_state.get("paper_account_verified") is not True:
        blockers.append("paper_account_not_verified")
    if account_state.get("live_execution") is True or account_state.get("real_money_actions") is True:
        blockers.append("live_or_real_money_state_detected")
    open_orders = [
        row
        for row in account_state.get("open_orders", [])
        if isinstance(row, Mapping)
    ]
    if open_orders:
        blockers.append("open_orders_present")

    broker_quantity_by_symbol: dict[str, Decimal] = {}
    for row in account_state.get("positions", []):
        if not isinstance(row, Mapping):
            continue
        symbol = base_symbol(row.get("symbol"))
        if symbol:
            broker_quantity_by_symbol[symbol] = (
                broker_quantity_by_symbol.get(symbol, ZERO)
                + decimal(row.get("quantity", row.get("qty", "0")))
            )

    batches_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in attribution.get("batches", []):
        if not isinstance(row, Mapping) or decimal(row.get("remaining_quantity")) <= ZERO:
            continue
        symbol = base_symbol(row.get("symbol"))
        if symbol:
            batches_by_symbol.setdefault(symbol, []).append(dict(row))

    evidence_by_symbol: dict[str, list[str]] = {}
    for row in reconciliation.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        status = canonical_status(row)
        if "filled" not in status:
            continue
        symbol = base_symbol(row.get("symbol"))
        side = canonical_side(row)
        candidate_order_id = order_id(row)
        if symbol and side in {"buy", "sell"} and candidate_order_id:
            evidence_by_symbol.setdefault(f"{symbol}:{side}", []).append(candidate_order_id)

    preserved = [
        dict(row)
        for row in existing.get("adjustments", [])
        if isinstance(row, Mapping)
    ]
    existing_by_symbol = {base_symbol(row.get("symbol")): row for row in preserved}
    generated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    active_test_epoch_ids = set(active_test_epoch_ids or set())
    for symbol, all_batches in sorted(batches_by_symbol.items()):
        broker_quantity = broker_quantity_by_symbol.get(symbol, ZERO)
        virtual_quantity = sum(
            (
                -decimal(row.get("remaining_quantity"))
                if str(row.get("direction") or "long") == "short"
                else decimal(row.get("remaining_quantity"))
            )
            for row in all_batches
        )
        batches = list(all_batches)
        if broker_quantity != ZERO:
            old_batches = [
                row
                for row in all_batches
                if str(row.get("test_epoch_id") or "") not in active_test_epoch_ids
            ]
            old_quantity = sum(
                (
                    -decimal(row.get("remaining_quantity"))
                    if str(row.get("direction") or "long") == "short"
                    else decimal(row.get("remaining_quantity"))
                )
                for row in old_batches
            )
            if not old_batches or virtual_quantity - old_quantity != broker_quantity:
                skipped.append({"symbol": symbol, "reason": "broker_position_not_zero"})
                continue
            batches = old_batches
        directions = {str(row.get("direction") or "long") for row in batches}
        if len(directions) != 1:
            skipped.append({"symbol": symbol, "reason": "mixed_virtual_directions"})
            continue
        direction = next(iter(directions))
        closing_side = "buy" if direction == "short" else "sell"
        evidence_order_ids = sorted(set(evidence_by_symbol.get(f"{symbol}:{closing_side}", [])))
        if not evidence_order_ids:
            skipped.append({"symbol": symbol, "reason": "missing_filled_broker_exit_evidence"})
            continue
        open_order_ids = sorted(
            {
                str(row.get("open_order_id") or "")
                for row in batches
                if str(row.get("open_order_id") or "")
            }
        )
        if not open_order_ids:
            skipped.append({"symbol": symbol, "reason": "missing_source_open_order_ids"})
            continue
        previous = existing_by_symbol.get(symbol, {})
        generated.append(
            {
                "approved": True,
                "adjustment_id": str(previous.get("adjustment_id") or f"broker-flat-{symbol.lower()}-20260807"),
                "symbol": symbol,
                "open_order_ids": open_order_ids,
                "evidence_order_id": evidence_order_ids[-1],
                "evidence_order_ids": evidence_order_ids,
                "reason": "Longbridge paper account is flat and filled broker exits prove these historical virtual lots are terminal.",
                "resolve_symbol_anomalies": True,
                "include_in_strategy_performance": False,
            }
        )

    generated_symbols = {row["symbol"] for row in generated}
    untouched = [row for row in preserved if base_symbol(row.get("symbol")) not in generated_symbols]
    payload = {
        "schema_version": "m15.account-reconciliation-adjustments.v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "approved": not blockers,
        "status": "blocked" if blockers else "ready",
        "blockers": blockers,
        "adjustments": untouched + generated,
        "generated_adjustment_count": len(generated),
        "skipped": skipped,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
    }
    return payload


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile broker-flat historical virtual lots without broker writes."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-account-age-seconds", type=int, default=120)
    args = parser.parse_args()
    account_state = read_json(ACCOUNT_STATE_PATH)
    formal_epoch = read_json(FORMAL_EPOCH_PATH)
    active_test_epoch_ids = {
        str(formal_epoch.get("test_epoch_id") or ""),
        str(formal_epoch.get("short_test_epoch_id") or ""),
    } - {""}
    payload = build_broker_flat_adjustments(
        account_state,
        read_json(ATTRIBUTION_PATH),
        read_json(RECONCILIATION_PATH),
        read_json(ADJUSTMENTS_PATH),
        active_test_epoch_ids=active_test_epoch_ids,
    )
    generated_at = parse_time(account_state.get("generated_at"))
    account_age_seconds = (
        max(0, int((datetime.now(UTC) - generated_at).total_seconds()))
        if generated_at is not None
        else -1
    )
    payload["account_snapshot_age_seconds"] = account_age_seconds
    if args.execute and (
        account_age_seconds < 0
        or account_age_seconds > args.max_account_age_seconds
    ):
        payload["status"] = "blocked"
        payload.setdefault("blockers", []).append("account_snapshot_stale")
    if args.execute and payload["status"] == "ready":
        write_json_atomic(ADJUSTMENTS_PATH, payload)
        payload["status"] = "applied"
    elif args.execute:
        payload["execution_note"] = "Blocked plan was not written."
    write_json_atomic(REPORT_PATH, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
