"""Build an exact-batch cleanup plan for legacy PA004 paper positions."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any, Iterable, Mapping

from scripts.m15_longbridge_realtime_execution_lib import append_jsonl
from scripts.m15_sdk_validation_flatten_lib import in_regular_session, market_date

ZERO = Decimal("0")
TARGET_BUCKETS = {"pa004_mbf", "pa004_mbf_qc"}
TARGET_RUNTIMES = {
    "M10-PA-004-MBF-1d",
    "M10-PA-004-MBF-QC-1d",
}


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return ZERO


def normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    return symbol if "." in symbol else f"{symbol}.US"


def stable_cleanup_id(*, batch_id: str, cleanup_epoch_id: str) -> str:
    digest = hashlib.sha256(f"{cleanup_epoch_id}|{batch_id}".encode()).hexdigest()
    return f"pa004-cleanup-{digest[:24]}"


def plan_digest(rows: Iterable[Mapping[str, Any]]) -> str:
    normalized = [
        {
            "batch_id": str(row.get("batch_id") or ""),
            "capital_bucket": str(row.get("capital_bucket") or ""),
            "runtime_id": str(row.get("runtime_id") or ""),
            "symbol": normalize_symbol(row.get("symbol")),
            "quantity": str(row.get("quantity") or ""),
            "source_open_order_id": str(row.get("source_open_order_id") or ""),
            "source_open_trade_id": str(row.get("source_open_trade_id") or ""),
        }
        for row in rows
    ]
    encoded = json.dumps(
        sorted(normalized, key=lambda row: row["batch_id"]),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _open_sell_symbols(account_state: Mapping[str, Any]) -> set[str]:
    symbols: set[str] = set()
    for row in account_state.get("open_orders", []) or []:
        if not isinstance(row, Mapping):
            continue
        side = str(row.get("side") or row.get("order_side") or "").lower()
        status = str(row.get("status") or "").lower()
        if side in {"sell", "sell_short"} and status not in {
            "filled",
            "cancelled",
            "canceled",
            "expired",
            "rejected",
        }:
            symbols.add(normalize_symbol(row.get("symbol")))
    return symbols


def _broker_available_by_symbol(account_state: Mapping[str, Any]) -> dict[str, Decimal]:
    available: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in account_state.get("positions", []) or []:
        if not isinstance(row, Mapping):
            continue
        symbol = normalize_symbol(row.get("symbol"))
        quantity = decimal(
            row.get(
                "available_quantity",
                row.get("available", row.get("sellable_quantity", row.get("quantity"))),
            )
        )
        if quantity > ZERO:
            available[symbol] += quantity.to_integral_value(rounding=ROUND_FLOOR)
    return dict(available)


def build_cleanup_plan(
    attribution: Mapping[str, Any],
    account_state: Mapping[str, Any],
    *,
    cleanup_epoch_id: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    planned_by_symbol: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for batch in attribution.get("batches", []) or []:
        if not isinstance(batch, Mapping):
            continue
        bucket = str(batch.get("capital_bucket") or "")
        runtime_id = str(batch.get("runtime_id") or "")
        direction = str(batch.get("direction") or "").lower()
        quantity = decimal(batch.get("remaining_quantity"))
        if (
            bucket not in TARGET_BUCKETS
            or runtime_id not in TARGET_RUNTIMES
            or direction != "long"
            or quantity <= ZERO
        ):
            continue
        whole_quantity = quantity.to_integral_value(rounding=ROUND_FLOOR)
        if whole_quantity != quantity or whole_quantity < 1:
            raise ValueError(
                f"cleanup_batch_requires_whole_positive_quantity:{batch.get('batch_id')}"
            )
        symbol = normalize_symbol(batch.get("symbol"))
        row = {
            "cleanup_id": stable_cleanup_id(
                batch_id=str(batch.get("batch_id") or ""),
                cleanup_epoch_id=cleanup_epoch_id,
            ),
            "cleanup_epoch_id": cleanup_epoch_id,
            "batch_id": str(batch.get("batch_id") or ""),
            "test_epoch_id": str(batch.get("test_epoch_id") or ""),
            "capital_bucket": bucket,
            "runtime_id": runtime_id,
            "strategy_id": str((batch.get("metadata") or {}).get("strategy_id") or ""),
            "symbol": symbol,
            "direction": "long",
            "position_action": "close_long",
            "side": "sell",
            "order_type": "market",
            "quantity": str(whole_quantity),
            "source_open_order_id": str(batch.get("open_order_id") or ""),
            "source_open_trade_id": str(batch.get("trade_id") or ""),
            "source_open_signal_id": str(
                (batch.get("metadata") or {}).get("signal_id") or ""
            ),
            "open_price": str(batch.get("open_price") or ""),
            "client_request_id": stable_cleanup_id(
                batch_id=str(batch.get("batch_id") or ""),
                cleanup_epoch_id=cleanup_epoch_id,
            ),
        }
        if not row["batch_id"] or not row["source_open_order_id"] or not row["source_open_trade_id"]:
            raise ValueError("cleanup_batch_missing_exact_attribution_key")
        rows.append(row)
        planned_by_symbol[symbol] += whole_quantity

    rows.sort(key=lambda row: (row["symbol"], row["capital_bucket"], row["batch_id"]))
    broker_available = _broker_available_by_symbol(account_state)
    open_sell_symbols = _open_sell_symbols(account_state)
    blockers: list[dict[str, Any]] = []
    if not account_state.get("paper_account_verified"):
        blockers.append({"code": "paper_account_not_verified"})
    critical_errors = list(account_state.get("critical_errors") or [])
    if critical_errors:
        blockers.append(
            {"code": "account_state_has_critical_errors", "details": critical_errors}
        )
    for symbol, quantity in sorted(planned_by_symbol.items()):
        available = broker_available.get(symbol, ZERO)
        if quantity > available:
            blockers.append(
                {
                    "code": "planned_quantity_exceeds_broker_available",
                    "symbol": symbol,
                    "planned_quantity": str(quantity),
                    "broker_available_quantity": str(available),
                }
            )
        if symbol in open_sell_symbols:
            blockers.append({"code": "existing_open_sell_order", "symbol": symbol})
    if not rows:
        blockers.append({"code": "no_target_open_batches"})

    digest = plan_digest(rows)
    return {
        "schema_version": "m15.pa004-overcap-cleanup.v1",
        "stage": "M15.pa004_overcap_cleanup",
        "status": "blocked" if blockers else "ready",
        "cleanup_scope": "all_open_lots_in_target_buckets_for_fresh_baseline",
        "cleanup_epoch_id": cleanup_epoch_id,
        "generated_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "market_date": market_date(now),
        "regular_session": in_regular_session(now),
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "target_buckets": sorted(TARGET_BUCKETS),
        "target_runtimes": sorted(TARGET_RUNTIMES),
        "capital_bucket_states": {
            bucket: {"status": "pending_cleanup"} for bucket in sorted(TARGET_BUCKETS)
        },
        "plan_digest": digest,
        "planned_batch_count": len(rows),
        "planned_symbol_count": len(planned_by_symbol),
        "planned_quantity_by_symbol": {
            symbol: str(quantity) for symbol, quantity in sorted(planned_by_symbol.items())
        },
        "broker_available_quantity_by_symbol": {
            symbol: str(broker_available.get(symbol, ZERO))
            for symbol in sorted(planned_by_symbol)
        },
        "blockers": blockers,
        "orders": rows,
        "bucket_baselines": {},
    }


def execution_allowed(
    plan: Mapping[str, Any],
    *,
    now: datetime,
    expected_market_date: str,
    expected_plan_digest: str,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if plan.get("status") != "ready":
        reasons.append("cleanup_plan_not_ready")
    if not in_regular_session(now):
        reasons.append("outside_regular_session")
    if market_date(now) != expected_market_date:
        reasons.append("unexpected_market_date")
    if str(plan.get("plan_digest") or "") != expected_plan_digest:
        reasons.append("plan_digest_mismatch")
    if plan.get("paper_simulated_only") is not True:
        reasons.append("paper_only_guard_missing")
    return not reasons, reasons


def _broker_order_statuses(account_state: Mapping[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for row in account_state.get("orders", []) or []:
        if not isinstance(row, Mapping):
            continue
        order_id = str(row.get("order_id") or row.get("id") or "")
        if order_id:
            statuses[order_id] = str(row.get("status") or "").split(".")[-1].lower()
    return statuses


def _cleanup_ledger_row(
    order: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    order_id = str(response.get("order_id") or "")
    return {
        "stage": "M15.longbridge_realtime_execution",
        "execution_run_id": str(order.get("cleanup_epoch_id") or ""),
        "signal_id": str(order.get("cleanup_id") or ""),
        "client_request_id": str(order.get("client_request_id") or ""),
        "runtime_id": str(order.get("runtime_id") or ""),
        "strategy_id": str(order.get("strategy_id") or ""),
        "capital_bucket": str(order.get("capital_bucket") or ""),
        "test_epoch_id": str(order.get("test_epoch_id") or ""),
        "symbol": str(order.get("symbol") or "").replace(".US", ""),
        "timeframe": "1d",
        "direction": "long",
        "position_action": "close_long",
        "side": "sell",
        "order_type": "market",
        "submitted_quantity": str(order.get("quantity") or ""),
        "quantity": str(order.get("quantity") or ""),
        "source_open_signal_id": str(order.get("source_open_signal_id") or ""),
        "source_open_order_id": str(order.get("source_open_order_id") or ""),
        "source_open_trade_id": str(order.get("source_open_trade_id") or ""),
        "source_open_remaining_quantity": str(order.get("quantity") or ""),
        "exit_reason": "pa004_legacy_overcap_cleanup",
        "market_exit_no_reprice": True,
        "paper_trading_approval": True,
        "execute_orders": True,
        "submission_status": "submitted",
        "submission_confirmation_state": "broker_order_id_received",
        "order_id": order_id,
        "broker_order_id": order_id,
        "longbridge_order_id": order_id,
        "submission_response": dict(response),
        "created_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "submitted_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "processed_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "local_simulation_ignored": True,
        "m13_m14_gate_used_for_order": False,
        "fast_queue_used_for_order": False,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "blockers": [],
        "order_payload": dict(order),
    }


def advance_cleanup_state(
    state: dict[str, Any],
    account_state: Mapping[str, Any],
    client: Any,
    *,
    now: datetime,
    execution_ledger_path: Path,
) -> dict[str, Any]:
    """Advance at most one exact-batch PA004 cleanup request per cycle."""
    status = str(state.get("status") or "")
    if not state or status in {"inactive", "complete", "blocked"}:
        return state or {"status": "inactive"}
    state["updated_at"] = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if state.get("paper_simulated_only") is not True:
        state.update({"status": "blocked", "reason": "paper_only_boundary_missing"})
        return state
    if account_state.get("paper_account_verified") is not True:
        state.update({"status": "waiting_for_fresh_paper_account", "reason": "paper_account_not_verified"})
        return state
    if account_state.get("critical_errors"):
        state.update({"status": "waiting_for_fresh_paper_account", "reason": "account_state_has_critical_errors"})
        return state

    submissions = state.setdefault("submissions", {})
    broker_statuses = _broker_order_statuses(account_state)
    terminal_failures = {"rejected", "cancelled", "canceled", "expired"}
    pending = False
    for request_id, submission in submissions.items():
        if not isinstance(submission, dict):
            continue
        order_id = str(submission.get("order_id") or "")
        broker_status = broker_statuses.get(order_id, "")
        if broker_status in {"filled", "filledstatus"}:
            submission["status"] = "filled"
            submission["filled_at"] = state["updated_at"]
        elif broker_status in terminal_failures:
            submission["status"] = "failed"
            submission["broker_status"] = broker_status
            state.update({
                "status": "blocked",
                "reason": f"cleanup_order_{broker_status}:{order_id}",
            })
            return state
        else:
            pending = True
            submission["status"] = "submitted_waiting_broker_fill"
            submission["broker_status"] = broker_status or "not_yet_visible"
    if pending:
        state["status"] = "submitted_waiting_broker_fill"
        return state

    orders = [row for row in state.get("orders", []) if isinstance(row, dict)]
    remaining = [
        row for row in orders
        if str(row.get("client_request_id") or "") not in submissions
    ]
    if not remaining:
        state.update({
            "status": "complete",
            "completed_at": state["updated_at"],
            "blocks_new_entries": False,
            "capital_bucket_states": {
                bucket: {"status": "active"} for bucket in sorted(TARGET_BUCKETS)
            },
            "bucket_baselines": {
                bucket: {
                    "started_at": state["updated_at"],
                    "test_started_at": state["updated_at"],
                    "exclude_prior_batches": True,
                    "cleanup_epoch_id": str(state.get("cleanup_epoch_id") or ""),
                }
                for bucket in sorted(TARGET_BUCKETS)
            },
        })
        return state
    if not in_regular_session(now):
        state.update({
            "status": "pending_cleanup",
            "reason": "paper_cleanup_waiting_regular_session",
            "blocks_new_entries": True,
        })
        return state

    order = remaining[0]
    symbol = normalize_symbol(order.get("symbol"))
    required = decimal(order.get("quantity"))
    available = _broker_available_by_symbol(account_state).get(symbol, ZERO)
    if required <= ZERO or required > available:
        state.update({
            "status": "blocked",
            "reason": "cleanup_quantity_not_available",
            "blocked_symbol": symbol,
            "required_quantity": str(required),
            "available_quantity": str(available),
        })
        return state
    if symbol in _open_sell_symbols(account_state):
        state.update({
            "status": "submitted_waiting_broker_fill",
            "reason": "existing_sell_order_waiting_reconciliation",
            "blocked_symbol": symbol,
        })
        return state

    request_id = str(order["client_request_id"])
    response = client.submit_order(
        {
            **order,
            "symbol": symbol.replace(".US", ""),
            "signal_id": str(order["cleanup_id"]),
            "market_exit_no_reprice": True,
        }
    )
    order_id = str(response.get("order_id") or "")
    if not order_id:
        state.update({
            "status": "blocked",
            "reason": str(response.get("error") or response.get("status") or "cleanup_order_id_missing"),
            "failed_request_id": request_id,
            "response": dict(response),
        })
        return state
    submissions[request_id] = {
        "status": "submitted_waiting_broker_fill",
        "order_id": order_id,
        "submitted_at": state["updated_at"],
        "symbol": symbol,
        "quantity": str(required),
        "batch_id": str(order.get("batch_id") or ""),
    }
    append_jsonl(
        execution_ledger_path,
        [_cleanup_ledger_row(order, response, now=now)],
    )
    state.update({
        "status": "submitted_waiting_broker_fill",
        "reason": "",
        "submitted_this_cycle": 1,
        "last_submitted_order_id": order_id,
        "blocks_new_entries": True,
    })
    return state
