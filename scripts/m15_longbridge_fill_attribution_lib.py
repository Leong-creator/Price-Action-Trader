#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
from datetime import datetime
from zoneinfo import ZoneInfo


ZERO = Decimal("0")
MONEY = Decimal("0.01")
QUANTITY = Decimal("0.0001")
FILL_FACT_STATUSES = {"filled", "partially_filled"}
RELEASE_STATUSES = {"canceled", "cancelled", "expired", "rejected", "filled"}
OPEN_ACTIONS = {"open_long", "open_short", "open"}
EXIT_ACTIONS = {"close_long", "close_short", "take_profit", "stop_loss", "exit"}
DEFAULT_COMMISSION_PER_ORDER_SIDE = Decimal("1.99")
DEFAULT_REGULATORY_FEE_PER_SELL_ORDER = Decimal("0.02")
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(slots=True)
class _OpenBatchState:
    batch_id: str
    test_epoch_id: str
    capital_bucket: str
    runtime_id: str
    direction: str
    symbol: str
    open_order_id: str
    trade_id: str
    filled_quantity: Decimal
    remaining_quantity: Decimal
    open_price: Decimal
    metadata: dict[str, Any]
    reserved_released: bool = False


def broker_fill_rows_from_orders_and_executions(
    order_rows: Iterable[Mapping[str, Any]],
    execution_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Join Longbridge executions to their orders without guessing identity."""
    orders = {
        str(row.get("order_id") or row.get("id") or ""): dict(row)
        for row in order_rows
        if isinstance(row, Mapping) and str(row.get("order_id") or row.get("id") or "")
    }
    fills: list[dict[str, Any]] = []
    for execution in execution_rows:
        if not isinstance(execution, Mapping):
            continue
        order_id = str(execution.get("order_id") or execution.get("id") or "")
        trade_id = str(execution.get("trade_id") or "")
        quantity = _decimal(execution.get("quantity") or execution.get("executed_quantity"))
        if not order_id or not trade_id or quantity <= ZERO:
            continue
        order = orders.get(order_id, {})
        fills.append(
            {
                **order,
                **dict(execution),
                "order_id": order_id,
                "trade_id": trade_id,
                "status": "filled",
                "executed_quantity": _fmt_quantity(quantity),
                "executed_price": str(execution.get("price") or execution.get("executed_price") or ""),
            }
        )
    return sorted(fills, key=_row_sort_key)


def rebuild_fill_attribution_from_history(
    local_order_rows: Iterable[Mapping[str, Any]],
    broker_order_rows: Iterable[Mapping[str, Any]],
    *,
    broker_net_positions: Mapping[str, Any] | None = None,
    existing_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return rebuild_fill_attribution(
        local_order_rows,
        broker_order_rows,
        broker_net_positions=broker_net_positions,
        existing_state=existing_state,
    )


def apply_account_reconciliation_adjustments(
    payload: dict[str, Any],
    adjustments: Mapping[str, Any],
    *,
    broker_net_positions: Mapping[str, Any],
) -> dict[str, Any]:
    """Close only explicitly listed virtual lots after broker-account cleanup.

    Adjustments are intentionally order-id scoped. A future position in the
    same symbol is therefore unaffected by an old account reconciliation.
    """
    if adjustments.get("approved") is not True:
        return payload
    batches = payload.get("batches", []) if isinstance(payload.get("batches"), list) else []
    events = payload.get("events", []) if isinstance(payload.get("events"), list) else []
    anomalies = payload.get("anomalies", []) if isinstance(payload.get("anomalies"), list) else []
    applied: list[dict[str, Any]] = []
    existing_adjustment_ids = {
        str(row.get("adjustment_id") or "")
        for row in events
        if isinstance(row, Mapping) and row.get("event_type") == "account_reconciliation_adjustment"
    }
    for row in adjustments.get("adjustments", []):
        if not isinstance(row, Mapping) or row.get("approved") is not True:
            continue
        adjustment_id = str(row.get("adjustment_id") or "")
        symbol = str(row.get("symbol") or "").upper().replace(".US", "")
        open_order_ids = {str(value) for value in row.get("open_order_ids", []) if str(value)}
        broker_quantity = _decimal(broker_net_positions.get(symbol, "0"))
        if not adjustment_id or not symbol or not open_order_ids:
            applied.append({
                "adjustment_id": adjustment_id,
                "symbol": symbol,
                "status": "not_applied_invalid_scope",
                "broker_net_quantity": _fmt_quantity(broker_quantity),
            })
            continue
        virtual_quantity_before = ZERO
        targeted_quantity = ZERO
        for batch in batches:
            if not isinstance(batch, Mapping):
                continue
            if str(batch.get("symbol") or "").upper().replace(".US", "") != symbol:
                continue
            remaining = _decimal(batch.get("remaining_quantity"))
            signed_remaining = -remaining if str(batch.get("direction") or "") == "short" else remaining
            virtual_quantity_before += signed_remaining
            if str(batch.get("open_order_id") or "") in open_order_ids:
                targeted_quantity += signed_remaining
        projected_quantity = virtual_quantity_before - targeted_quantity
        if projected_quantity != broker_quantity:
            applied.append({
                "adjustment_id": adjustment_id,
                "symbol": symbol,
                "status": "not_applied_projected_broker_position_mismatch",
                "virtual_net_quantity_before": _fmt_quantity(virtual_quantity_before),
                "targeted_virtual_quantity": _fmt_quantity(targeted_quantity),
                "projected_virtual_net_quantity": _fmt_quantity(projected_quantity),
                "broker_net_quantity": _fmt_quantity(broker_quantity),
            })
            continue
        closed_quantity = ZERO
        closed_batches = 0
        for batch in batches:
            if not isinstance(batch, dict):
                continue
            if str(batch.get("symbol") or "").upper().replace(".US", "") != symbol:
                continue
            if str(batch.get("open_order_id") or "") not in open_order_ids:
                continue
            remaining = _decimal(batch.get("remaining_quantity"))
            if remaining > ZERO:
                closed_quantity += remaining
                closed_batches += 1
            batch["remaining_quantity"] = "0.0000"
            batch["account_reconciliation_status"] = "closed_excluded_from_strategy_performance"
            batch["account_reconciliation_adjustment_id"] = adjustment_id
            batch["include_in_bucket_performance"] = False
            batch["include_in_strategy_performance"] = False
        if row.get("resolve_symbol_anomalies") is True:
            anomalies = [
                anomaly for anomaly in anomalies
                if str(anomaly.get("symbol") or "").upper().replace(".US", "") != symbol
            ]
        if adjustment_id not in existing_adjustment_ids:
            events.append({
                "event_type": "account_reconciliation_adjustment",
                "attribution_status": "account_reconciliation_closed_excluded",
                "adjustment_id": adjustment_id,
                "symbol": symbol,
                "filled_quantity": _fmt_quantity(closed_quantity),
                "counts_for_performance": False,
                "include_in_bucket_performance": False,
                "include_in_strategy_performance": False,
                "reason": str(row.get("reason") or "broker_position_zero_after_account_cleanup"),
                "evidence_order_id": str(row.get("evidence_order_id") or ""),
            })
            existing_adjustment_ids.add(adjustment_id)
        applied.append({
            "adjustment_id": adjustment_id,
            "symbol": symbol,
            "status": "applied",
            "closed_batch_count": closed_batches,
            "closed_virtual_quantity": _fmt_quantity(closed_quantity),
            "broker_net_quantity": _fmt_quantity(broker_quantity),
            "projected_virtual_net_quantity": _fmt_quantity(projected_quantity),
        })

    virtual_by_symbol: dict[str, Decimal] = {}
    for batch in batches:
        if not isinstance(batch, Mapping):
            continue
        symbol = str(batch.get("symbol") or "").upper().replace(".US", "")
        remaining = _decimal(batch.get("remaining_quantity"))
        if str(batch.get("direction") or "") == "short":
            remaining = -remaining
        if symbol:
            virtual_by_symbol[symbol] = virtual_by_symbol.get(symbol, ZERO) + remaining
    symbols = sorted(set(virtual_by_symbol) | {str(key).upper().replace(".US", "") for key in broker_net_positions})
    payload["symbol_checks"] = [
        {
            "symbol": symbol,
            "virtual_net_quantity": _fmt_quantity(virtual_by_symbol.get(symbol, ZERO)),
            "broker_net_quantity": _fmt_quantity(_decimal(broker_net_positions.get(symbol, "0"))),
            "matches_broker_net": virtual_by_symbol.get(symbol, ZERO) == _decimal(broker_net_positions.get(symbol, "0")),
        }
        for symbol in symbols
    ]
    payload["events"] = events
    payload["anomalies"] = anomalies
    payload["account_reconciliation_adjustments"] = applied
    payload["summary"] = {
        **(payload.get("summary") if isinstance(payload.get("summary"), dict) else {}),
        "anomaly_count": len(anomalies),
        "excluded_event_count": sum(
            1 for event in events if isinstance(event, Mapping) and not bool(event.get("include_in_strategy_performance"))
        ),
        "account_reconciliation_adjustment_count": sum(row.get("status") == "applied" for row in applied),
    }
    return payload


def rebuild_fill_attribution(
    local_order_rows: Iterable[Mapping[str, Any]],
    broker_order_rows: Iterable[Mapping[str, Any]],
    *,
    broker_net_positions: Mapping[str, Any] | None = None,
    existing_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    local_rows = [dict(row) for row in local_order_rows if isinstance(row, Mapping)]
    broker_source_rows = [dict(row) for row in broker_order_rows if isinstance(row, Mapping)]
    trade_ids_by_order: dict[str, set[str]] = {}
    for row in broker_source_rows:
        order_id = str(row.get("order_id") or row.get("id") or "")
        trade_id = str(row.get("trade_id") or "")
        if order_id and trade_id:
            trade_ids_by_order.setdefault(order_id, set()).add(trade_id)
    for row in local_rows:
        if row.get("source_open_trade_id"):
            continue
        source_order_id = str(row.get("source_open_order_id") or "")
        exact_trade_ids = trade_ids_by_order.get(source_order_id, set())
        if source_order_id and len(exact_trade_ids) == 1:
            row["source_open_trade_id"] = next(iter(exact_trade_ids))
            row["source_open_trade_id_inferred_from_unique_broker_fill"] = True
    local_by_order_id = {
        str(row.get("order_id") or ""): row
        for row in local_rows
        if str(row.get("order_id") or "")
    }
    broker_rows = sorted(
        broker_source_rows,
        key=lambda row: (
            _row_sort_key(row)[0],
            0
            if _merged_local_row(local_by_order_id.get(str(row.get("order_id") or row.get("id") or ""), {})).get("intent") == "open"
            else 1,
            _row_sort_key(row)[1],
            _row_sort_key(row)[2],
        ),
    )
    latest_broker_by_order_id = _latest_broker_rows_by_order_id(broker_rows)
    max_fill_by_trade = _existing_fill_quantities(existing_state or {})
    open_batches = _existing_open_batches(existing_state or {})
    events: list[dict[str, Any]] = [
        dict(row) for row in (existing_state or {}).get("events", []) if isinstance(row, Mapping)
    ]
    anomalies: list[dict[str, Any]] = [
        dict(row) for row in (existing_state or {}).get("anomalies", []) if isinstance(row, Mapping)
    ]

    for broker_row in broker_rows:
        order_id = str(broker_row.get("order_id") or broker_row.get("id") or "")
        local_row = local_by_order_id.get(order_id)
        status = _canonical_status(broker_row)
        trade_id = str(broker_row.get("trade_id") or "")
        cumulative_quantity = _decimal(
            broker_row.get("executed_quantity")
            or broker_row.get("filled_quantity")
            or broker_row.get("quantity")
        )
        if local_row is None and status in FILL_FACT_STATUSES and cumulative_quantity > ZERO:
            anomaly = _make_anomaly(
                code="unattributed_fill_missing_local_order",
                broker_row=broker_row,
                message="Longbridge fill cannot be attributed because the local order metadata is missing.",
            )
            anomalies.append(anomaly)
            events.append(_make_unmatched_event(broker_row, anomaly))
            continue
        if local_row is None:
            continue
        if status not in FILL_FACT_STATUSES or cumulative_quantity <= ZERO or not trade_id:
            continue
        fill_key = (order_id, trade_id)
        previous_quantity = max_fill_by_trade.get(fill_key, ZERO)
        delta_quantity = cumulative_quantity - previous_quantity
        if delta_quantity <= ZERO:
            continue
        max_fill_by_trade[fill_key] = cumulative_quantity
        normalized = _merged_local_row(local_row)
        if normalized["intent"] == "open":
            batch = _apply_open_fill(
                normalized,
                broker_row,
                trade_id=trade_id,
                delta_quantity=delta_quantity,
                cumulative_quantity=cumulative_quantity,
                open_batches=open_batches,
            )
            events.append(
                {
                    "event_type": "open_fill",
                    "attribution_status": "matched_fill_batch",
                    "include_in_bucket_performance": True,
                    "include_in_strategy_performance": True,
                    "counts_for_performance": True,
                    "symbol": batch.symbol,
                    "direction": batch.direction,
                    "capital_bucket": batch.capital_bucket,
                    "runtime_id": batch.runtime_id,
                    "test_epoch_id": batch.test_epoch_id,
                    "order_id": batch.open_order_id,
                    "trade_id": batch.trade_id,
                    "batch_id": batch.batch_id,
                    "filled_quantity": _fmt_quantity(delta_quantity),
                    "filled_price": _fmt_money(_decimal(broker_row.get("executed_price") or broker_row.get("price"))),
                }
            )
            continue
        event, anomaly = _apply_exit_fill(
            normalized,
            broker_row,
            trade_id=trade_id,
            delta_quantity=delta_quantity,
            open_batches=open_batches,
        )
        events.append(event)
        if anomaly is not None:
            anomalies.append(anomaly)

    matched_fill_identities = {
        (str(row.get("order_id") or ""), str(row.get("trade_id") or ""))
        for row in events
        if str(row.get("attribution_status") or "") == "matched_fill_batch"
    }
    events = [
        row for row in events
        if str(row.get("attribution_status") or "") == "matched_fill_batch"
        or (str(row.get("order_id") or ""), str(row.get("trade_id") or "")) not in matched_fill_identities
    ]
    anomalies = [
        row for row in anomalies
        if (str(row.get("order_id") or ""), str(row.get("trade_id") or "")) not in matched_fill_identities
    ]
    events = _dedupe_unmatched_events(events)
    anomalies = _dedupe_anomalies(anomalies)
    reservations = _build_reservations(local_rows, latest_broker_by_order_id, max_fill_by_trade)
    batch_rows = _serialize_batches(open_batches)
    symbol_checks = _build_symbol_checks(open_batches, broker_net_positions or {})
    summary = {
        "total_batch_count": len(batch_rows),
        "open_batch_count": sum(
            1 for row in batch_rows if _decimal(row.get("remaining_quantity")) > ZERO
        ),
        "anomaly_count": len(anomalies),
        "matched_event_count": sum(1 for row in events if row.get("attribution_status") == "matched_fill_batch"),
        "excluded_event_count": sum(1 for row in events if not bool(row.get("include_in_strategy_performance"))),
    }
    return {
        "schema_version": "m15.longbridge-fill-attribution.v2",
        "batches": batch_rows,
        "events": events,
        "reservations": reservations,
        "symbol_checks": symbol_checks,
        "anomalies": anomalies,
        "summary": summary,
    }


def add_completed_trade_performance(
    payload: dict[str, Any],
    *,
    commission_per_order_side: Decimal = DEFAULT_COMMISSION_PER_ORDER_SIDE,
    regulatory_fee_per_sell_order: Decimal = DEFAULT_REGULATORY_FEE_PER_SELL_ORDER,
    fault_days: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Add fee-aware performance using only fully closed, exactly attributed lots."""
    batches = [
        row for row in payload.get("batches", [])
        if isinstance(row, Mapping)
    ]
    exit_events = [
        row for row in payload.get("events", [])
        if isinstance(row, Mapping)
        and row.get("event_type") == "exit_fill"
        and row.get("include_in_strategy_performance") is True
        and row.get("counts_for_performance") is True
        and str(row.get("source_batch_id") or "")
    ]
    exits_by_batch: dict[str, list[Mapping[str, Any]]] = {}
    open_quantity_by_order: dict[str, Decimal] = {}
    exit_quantity_by_order: dict[str, Decimal] = {}
    for batch in batches:
        open_order_id = str(batch.get("open_order_id") or "")
        if open_order_id and batch.get("include_in_strategy_performance") is not False:
            open_quantity_by_order[open_order_id] = (
                open_quantity_by_order.get(open_order_id, ZERO)
                + _decimal(batch.get("filled_quantity"))
            )
    for event in exit_events:
        batch_id = str(event.get("source_batch_id") or "")
        exits_by_batch.setdefault(batch_id, []).append(event)
        order_id = str(event.get("order_id") or "")
        if order_id:
            exit_quantity_by_order[order_id] = (
                exit_quantity_by_order.get(order_id, ZERO)
                + _decimal(event.get("filled_quantity"))
            )

    completed_trades: list[dict[str, Any]] = []
    normalized_fault_days = {
        str(day): sorted({str(reason) for reason in reasons if str(reason)})
        for day, reasons in (fault_days or {}).items()
    }
    for batch in batches:
        batch_id = str(batch.get("batch_id") or "")
        batch_exits = exits_by_batch.get(batch_id, [])
        if (
            not batch_id
            or batch.get("include_in_strategy_performance") is False
            or _decimal(batch.get("remaining_quantity")) != ZERO
            or not batch_exits
        ):
            continue
        direction = str(batch.get("direction") or "long")
        open_quantity = _decimal(batch.get("filled_quantity"))
        open_order_id = str(batch.get("open_order_id") or "")
        open_order_quantity = open_quantity_by_order.get(open_order_id, ZERO)
        open_fee = ZERO
        if open_order_quantity > ZERO:
            open_order_fee = commission_per_order_side
            if direction == "short":
                open_order_fee += regulatory_fee_per_sell_order
            open_fee = open_order_fee * open_quantity / open_order_quantity

        exit_fee = ZERO
        gross_realized = ZERO
        exit_order_ids: set[str] = set()
        closed_at = ""
        for event in batch_exits:
            gross_realized += _decimal(event.get("realized_pnl"))
            order_id = str(event.get("order_id") or "")
            quantity = _decimal(event.get("filled_quantity"))
            order_quantity = exit_quantity_by_order.get(order_id, ZERO)
            if order_id and order_quantity > ZERO:
                order_fee = commission_per_order_side
                if direction == "long":
                    order_fee += regulatory_fee_per_sell_order
                exit_fee += order_fee * quantity / order_quantity
                exit_order_ids.add(order_id)
            event_time = str(event.get("filled_at") or "")
            if event_time > closed_at:
                closed_at = event_time
        estimated_fees = open_fee + exit_fee
        estimated_net = gross_realized - estimated_fees
        metadata = batch.get("metadata") if isinstance(batch.get("metadata"), Mapping) else {}
        opened_at = str(metadata.get("submitted_at") or metadata.get("created_at") or "")
        open_market_date = _new_york_date(opened_at)
        close_market_date = _new_york_date(closed_at)
        fault_dates = sorted(
            {
                day
                for day in (open_market_date, close_market_date)
                if day and day in normalized_fault_days
            }
        )
        fault_reasons = sorted(
            {
                reason
                for day in fault_dates
                for reason in normalized_fault_days.get(day, [])
            }
        )
        completed_trades.append(
            {
                "batch_id": batch_id,
                "test_epoch_id": str(batch.get("test_epoch_id") or ""),
                "capital_bucket": str(batch.get("capital_bucket") or ""),
                "runtime_id": str(batch.get("runtime_id") or ""),
                "direction": direction,
                "symbol": str(batch.get("symbol") or ""),
                "open_order_id": open_order_id,
                "open_trade_id": str(batch.get("trade_id") or ""),
                "filled_quantity": _fmt_quantity(open_quantity),
                "open_price": _fmt_money(_decimal(batch.get("open_price"))),
                "exit_order_count": len(exit_order_ids),
                "exit_fill_event_count": len(batch_exits),
                "gross_realized_pnl": _fmt_money(gross_realized),
                "estimated_fees": _fmt_money(estimated_fees),
                "estimated_net_pnl": _fmt_money(estimated_net),
                "fee_source": "configured_conservative_estimate",
                "opened_at": opened_at,
                "closed_at": closed_at,
                "open_market_date": open_market_date,
                "close_market_date": close_market_date,
                "fault_day": bool(fault_dates),
                "fault_dates": fault_dates,
                "fault_day_reasons": fault_reasons,
                "open_signal_diagnostics": {
                    key: metadata.get(key)
                    for key in (
                        "repair_rule_id",
                        "source_breakout_entry_price",
                        "latest_confirms_entry",
                        "next_market_day_timeout",
                        "close_position",
                        "volume_ratio",
                        "market_confirmation_status",
                        "quality_score",
                    )
                    if metadata.get(key) not in (None, "")
                },
            }
        )
    completed_trades.sort(
        key=lambda row: (
            str(row.get("closed_at") or ""),
            str(row.get("batch_id") or ""),
        )
    )
    payload["completed_trades"] = completed_trades
    normal_trades = [
        row for row in completed_trades if not bool(row.get("fault_day"))
    ]
    fault_day_trades = [
        row for row in completed_trades if bool(row.get("fault_day"))
    ]
    payload["strategy_performance"] = _group_completed_trade_performance(
        normal_trades, "runtime_id"
    )
    payload["bucket_performance"] = _group_completed_trade_performance(
        normal_trades, "capital_bucket"
    )
    payload["strategy_performance_including_fault_days"] = (
        _group_completed_trade_performance(completed_trades, "runtime_id")
    )
    payload["bucket_performance_including_fault_days"] = (
        _group_completed_trade_performance(completed_trades, "capital_bucket")
    )
    payload["fault_day_strategy_performance"] = _group_completed_trade_performance(
        fault_day_trades, "runtime_id"
    )
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    summary.update(
        {
            "total_batch_count": len(batches),
            "open_batch_count": sum(
                1
                for row in batches
                if row.get("include_in_strategy_performance") is not False
                and _decimal(row.get("remaining_quantity")) > ZERO
            ),
            "exit_fill_event_count": len(exit_events),
            "completed_trade_count": len(completed_trades),
            "normal_completed_trade_count": len(normal_trades),
            "fault_day_completed_trade_count": len(fault_day_trades),
            "gross_realized_pnl": _fmt_money(
                sum(
                    (_decimal(row.get("gross_realized_pnl")) for row in completed_trades),
                    ZERO,
                )
            ),
            "estimated_fees": _fmt_money(
                sum(
                    (_decimal(row.get("estimated_fees")) for row in completed_trades),
                    ZERO,
                )
            ),
            "estimated_net_realized_pnl": _fmt_money(
                sum(
                    (_decimal(row.get("estimated_net_pnl")) for row in completed_trades),
                    ZERO,
                )
            ),
            "normal_estimated_net_realized_pnl": _fmt_money(
                sum(
                    (_decimal(row.get("estimated_net_pnl")) for row in normal_trades),
                    ZERO,
                )
            ),
            "fault_day_estimated_net_realized_pnl": _fmt_money(
                sum(
                    (
                        _decimal(row.get("estimated_net_pnl"))
                        for row in fault_day_trades
                    ),
                    ZERO,
                )
            ),
            "fee_source": "configured_conservative_estimate",
            "actual_broker_fee_field_available": False,
        }
    )
    payload["summary"] = summary
    payload["fee_model"] = {
        "commission_per_order_side": _fmt_money(commission_per_order_side),
        "regulatory_fee_per_sell_order": _fmt_money(regulatory_fee_per_sell_order),
        "source": "configured_conservative_estimate",
        "actual_broker_fee_field_available": False,
    }
    payload["fault_day_registry"] = normalized_fault_days
    payload["strategy_performance_scope"] = "completed_trades_excluding_fault_days"
    return payload


def group_completed_trade_performance_rows(
    rows: list[dict[str, Any]],
    group_field: str,
) -> list[dict[str, Any]]:
    """Expose completed-trade grouping for read-only dashboard filtering."""
    return _group_completed_trade_performance(rows, group_field)


def summarize_completed_trade_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    completed_trades = [dict(row) for row in rows if isinstance(row, Mapping)]
    normal_trades = [row for row in completed_trades if not bool(row.get("fault_day"))]
    fault_day_trades = [row for row in completed_trades if bool(row.get("fault_day"))]
    return {
        "completed_trade_count": len(completed_trades),
        "normal_completed_trade_count": len(normal_trades),
        "fault_day_completed_trade_count": len(fault_day_trades),
        "gross_realized_pnl": _fmt_money(
            sum((_decimal(row.get("gross_realized_pnl")) for row in completed_trades), ZERO)
        ),
        "estimated_fees": _fmt_money(
            sum((_decimal(row.get("estimated_fees")) for row in completed_trades), ZERO)
        ),
        "estimated_net_realized_pnl": _fmt_money(
            sum((_decimal(row.get("estimated_net_pnl")) for row in completed_trades), ZERO)
        ),
        "normal_estimated_net_realized_pnl": _fmt_money(
            sum((_decimal(row.get("estimated_net_pnl")) for row in normal_trades), ZERO)
        ),
        "fault_day_estimated_net_realized_pnl": _fmt_money(
            sum((_decimal(row.get("estimated_net_pnl")) for row in fault_day_trades), ZERO)
        ),
    }


def build_virtual_position_layers(
    payload: Mapping[str, Any],
    holding_rows: Iterable[Mapping[str, Any]],
    *,
    market_date: str | None = None,
) -> dict[str, Any]:
    holdings = _normalize_holdings(holding_rows)
    batches = [
        dict(row)
        for row in payload.get("batches", [])
        if isinstance(row, Mapping)
        and row.get("include_in_strategy_performance") is not False
        and _decimal(row.get("remaining_quantity")) > ZERO
    ]
    completed_trades = [
        dict(row) for row in payload.get("completed_trades", []) if isinstance(row, Mapping)
    ]

    actual_gross_market_value = ZERO
    actual_signed_market_value = ZERO
    actual_unrealized = ZERO
    actual_net_quantity = ZERO
    actual_valuation_complete = bool(holdings) and all(
        bool(row.get("valuation_available")) for row in holdings.values()
    )
    for row in holdings.values():
        actual_gross_market_value += row["gross_market_value"]
        actual_signed_market_value += row["signed_market_value"]
        actual_unrealized += row["unrealized_pnl"]
        actual_net_quantity += row["signed_quantity"]

    symbol_rows: dict[str, dict[str, Any]] = {}
    runtime_rows: dict[str, dict[str, Any]] = {}
    bucket_rows: dict[str, dict[str, Any]] = {}
    concentration_rows: dict[str, dict[str, Any]] = {}
    attributed_gross_market_value = ZERO
    attributed_signed_market_value = ZERO
    attributed_unrealized = ZERO
    attributed_net_quantity = ZERO
    attributed_batch_count = 0
    total_virtual_gross_exposure = ZERO
    attributed_valuation_complete = bool(batches)

    today_open_batches: list[dict[str, Any]] = []
    active_market_date = market_date or ""
    for batch in batches:
        symbol = _normalize_symbol(str(batch.get("symbol") or ""))
        holding = holdings.get(symbol)
        remaining_quantity = _decimal(batch.get("remaining_quantity"))
        open_price = _decimal(batch.get("open_price"))
        direction = str(batch.get("direction") or "long")
        signed_quantity = -remaining_quantity if direction == "short" else remaining_quantity
        valuation_available = bool(
            holding is not None and holding.get("valuation_available")
        )
        attributed_valuation_complete = (
            attributed_valuation_complete and valuation_available
        )
        market_price = holding["market_price"] if valuation_available else ZERO
        price_source = (
            "longbridge_holding_market_price"
            if valuation_available
            else "waiting_for_longbridge_position_market_price"
        )
        gross_market_value = remaining_quantity * market_price
        signed_market_value = -gross_market_value if direction == "short" else gross_market_value
        unrealized = (market_price - open_price) * remaining_quantity
        if direction == "short":
            unrealized = -unrealized

        attributed_gross_market_value += gross_market_value
        attributed_signed_market_value += signed_market_value
        attributed_unrealized += unrealized
        attributed_net_quantity += signed_quantity
        attributed_batch_count += 1
        total_virtual_gross_exposure += gross_market_value

        symbol_entry = symbol_rows.setdefault(
            symbol,
            {
                "symbol": symbol,
                "actual_net_quantity": "0.0000",
                "actual_gross_market_value": "0.00",
                "actual_signed_market_value": "0.00",
                "actual_unrealized_pnl": "0.00",
                "attributed_net_quantity": "0.0000",
                "attributed_gross_market_value": "0.00",
                "attributed_signed_market_value": "0.00",
                "attributed_unrealized_pnl": "0.00",
                "unreconciled_net_quantity": "0.0000",
                "unreconciled_gross_market_value": "0.00",
                "unreconciled_unrealized_pnl": "0.00",
                "bucket_count": 0,
                "runtime_count": 0,
                "batch_count": 0,
                "attributed_valuation_available": True,
                "buckets": [],
                "runtimes": [],
            },
        )
        symbol_entry["attributed_valuation_available"] = bool(
            symbol_entry["attributed_valuation_available"] and valuation_available
        )
        symbol_entry["attributed_net_quantity"] = _fmt_quantity(
            _decimal(symbol_entry["attributed_net_quantity"]) + signed_quantity
        )
        symbol_entry["attributed_gross_market_value"] = _fmt_money(
            _decimal(symbol_entry["attributed_gross_market_value"]) + gross_market_value
        )
        symbol_entry["attributed_signed_market_value"] = _fmt_money(
            _decimal(symbol_entry["attributed_signed_market_value"]) + signed_market_value
        )
        symbol_entry["attributed_unrealized_pnl"] = _fmt_money(
            _decimal(symbol_entry["attributed_unrealized_pnl"]) + unrealized
        )
        symbol_entry["batch_count"] += 1
        bucket = str(batch.get("capital_bucket") or "")
        runtime_id = str(batch.get("runtime_id") or "")
        if bucket and bucket not in symbol_entry["buckets"]:
            symbol_entry["buckets"].append(bucket)
            symbol_entry["bucket_count"] += 1
        if runtime_id and runtime_id not in symbol_entry["runtimes"]:
            symbol_entry["runtimes"].append(runtime_id)
            symbol_entry["runtime_count"] += 1

        concentration_entry = concentration_rows.setdefault(
            symbol,
            {
                "symbol": symbol,
                "gross_market_value": ZERO,
                "net_quantity": ZERO,
                "bucket_values": {},
                "runtime_ids": set(),
                "valuation_available": True,
            },
        )
        concentration_entry["valuation_available"] = bool(
            concentration_entry["valuation_available"] and valuation_available
        )
        concentration_entry["gross_market_value"] += gross_market_value
        concentration_entry["net_quantity"] += signed_quantity
        concentration_entry["runtime_ids"].add(runtime_id)
        if bucket:
            concentration_entry["bucket_values"][bucket] = (
                concentration_entry["bucket_values"].get(bucket, ZERO) + gross_market_value
            )

        _accumulate_open_position_group(
            runtime_rows,
            runtime_id,
            signed_quantity=signed_quantity,
            gross_market_value=gross_market_value,
            unrealized=unrealized,
            valuation_available=valuation_available,
        )
        _accumulate_open_position_group(
            bucket_rows,
            bucket,
            signed_quantity=signed_quantity,
            gross_market_value=gross_market_value,
            unrealized=unrealized,
            valuation_available=valuation_available,
        )

        metadata = batch.get("metadata") if isinstance(batch.get("metadata"), Mapping) else {}
        opened_at = str(metadata.get("submitted_at") or metadata.get("created_at") or "")
        if active_market_date and _new_york_date(opened_at) == active_market_date:
            today_open_batches.append(
                {
                    "batch_id": str(batch.get("batch_id") or ""),
                    "symbol": symbol,
                    "runtime_id": runtime_id,
                    "capital_bucket": bucket,
                    "remaining_quantity": _fmt_quantity(remaining_quantity),
                    "market_value": (
                        _fmt_money(gross_market_value) if valuation_available else ""
                    ),
                    "unrealized_pnl": (
                        _fmt_money(unrealized) if valuation_available else ""
                    ),
                    "valuation_available": valuation_available,
                    "price_source": price_source,
                }
            )

    for symbol, holding in holdings.items():
        symbol_entry = symbol_rows.setdefault(
            symbol,
            {
                "symbol": symbol,
                "actual_net_quantity": "0.0000",
                "actual_gross_market_value": "0.00",
                "actual_signed_market_value": "0.00",
                "actual_unrealized_pnl": "0.00",
                "attributed_net_quantity": "0.0000",
                "attributed_gross_market_value": "0.00",
                "attributed_signed_market_value": "0.00",
                "attributed_unrealized_pnl": "0.00",
                "unreconciled_net_quantity": "0.0000",
                "unreconciled_gross_market_value": "0.00",
                "unreconciled_unrealized_pnl": "0.00",
                "bucket_count": 0,
                "runtime_count": 0,
                "batch_count": 0,
                "attributed_valuation_available": True,
                "buckets": [],
                "runtimes": [],
            },
        )
        symbol_entry["actual_net_quantity"] = _fmt_quantity(holding["signed_quantity"])
        valuation_available = bool(holding.get("valuation_available"))
        symbol_entry["actual_valuation_available"] = valuation_available
        symbol_entry["actual_gross_market_value"] = (
            _fmt_money(holding["gross_market_value"]) if valuation_available else ""
        )
        symbol_entry["actual_signed_market_value"] = (
            _fmt_money(holding["signed_market_value"]) if valuation_available else ""
        )
        symbol_entry["actual_unrealized_pnl"] = (
            _fmt_money(holding["unrealized_pnl"]) if valuation_available else ""
        )
        actual_qty = holding["signed_quantity"]
        attributed_qty = _decimal(symbol_entry["attributed_net_quantity"])
        actual_gross = holding["gross_market_value"]
        attributed_gross = _decimal(symbol_entry["attributed_gross_market_value"])
        actual_u = holding["unrealized_pnl"]
        attributed_u = _decimal(symbol_entry["attributed_unrealized_pnl"])
        symbol_entry["unreconciled_net_quantity"] = _fmt_quantity(actual_qty - attributed_qty)
        symbol_entry["unreconciled_gross_market_value"] = (
            _fmt_money(actual_gross - attributed_gross) if valuation_available else ""
        )
        symbol_entry["unreconciled_unrealized_pnl"] = (
            _fmt_money(actual_u - attributed_u) if valuation_available else ""
        )

    for symbol, symbol_entry in symbol_rows.items():
        attributed_symbol_valuation_available = bool(
            symbol_entry.get("attributed_valuation_available")
        )
        if not attributed_symbol_valuation_available:
            symbol_entry["attributed_gross_market_value"] = ""
            symbol_entry["attributed_signed_market_value"] = ""
            symbol_entry["attributed_unrealized_pnl"] = ""
        if symbol not in holdings:
            symbol_entry["unreconciled_net_quantity"] = _fmt_quantity(
                ZERO - _decimal(symbol_entry["attributed_net_quantity"])
            )
            symbol_entry["unreconciled_gross_market_value"] = ""
            symbol_entry["unreconciled_unrealized_pnl"] = ""
        symbol_entry["buckets"] = sorted(symbol_entry["buckets"])
        symbol_entry["runtimes"] = sorted(symbol_entry["runtimes"])

    concentration = []
    for symbol, row in sorted(concentration_rows.items()):
        bucket_values = row["bucket_values"]
        gross_market_value = row["gross_market_value"]
        concentration.append(
            {
                "symbol": symbol,
                "bucket_count": len(bucket_values),
                "runtime_count": len(row["runtime_ids"]),
                "valuation_available": bool(row["valuation_available"]),
                "gross_market_value": (
                    _fmt_money(gross_market_value)
                    if row["valuation_available"]
                    else ""
                ),
                "share_of_virtual_gross_exposure_pct": (
                    _fmt_ratio(
                        gross_market_value * Decimal("100") / total_virtual_gross_exposure
                        if total_virtual_gross_exposure > ZERO
                        else ZERO
                    )
                    if row["valuation_available"]
                    else ""
                ),
                "net_quantity": _fmt_quantity(row["net_quantity"]),
                "bucket_breakdown": [
                    {
                        "capital_bucket": bucket,
                        "gross_market_value": (
                            _fmt_money(value) if row["valuation_available"] else ""
                        ),
                    }
                    for bucket, value in sorted(
                        bucket_values.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ],
            }
        )

    completed_today_rows = [
        row for row in completed_trades
        if active_market_date
        and (
            str(row.get("open_market_date") or "") == active_market_date
            or _new_york_date(str(row.get("opened_at") or "")) == active_market_date
        )
    ]

    return {
        "market_date": active_market_date,
        "actual_account_total": {
            "symbol_count": len(holdings),
            "valuation_available": actual_valuation_complete,
            "valuation_status": (
                "longbridge_position_valuation_available"
                if actual_valuation_complete
                else "waiting_for_longbridge_position_market_price"
            ),
            "gross_market_value": (
                _fmt_money(actual_gross_market_value)
                if actual_valuation_complete
                else ""
            ),
            "signed_market_value": (
                _fmt_money(actual_signed_market_value)
                if actual_valuation_complete
                else ""
            ),
            "unrealized_pnl": (
                _fmt_money(actual_unrealized) if actual_valuation_complete else ""
            ),
            "net_quantity": _fmt_quantity(actual_net_quantity),
        },
        "attributed_virtual_total": {
            "symbol_count": sum(
                1 for row in symbol_rows.values()
                if _decimal(row.get("attributed_gross_market_value")) > ZERO
            ),
            "batch_count": attributed_batch_count,
            "valuation_available": attributed_valuation_complete,
            "valuation_status": (
                "longbridge_position_valuation_available"
                if attributed_valuation_complete
                else "waiting_for_longbridge_position_market_price"
            ),
            "gross_market_value": (
                _fmt_money(attributed_gross_market_value)
                if attributed_valuation_complete
                else ""
            ),
            "signed_market_value": (
                _fmt_money(attributed_signed_market_value)
                if attributed_valuation_complete
                else ""
            ),
            "unrealized_pnl": (
                _fmt_money(attributed_unrealized)
                if attributed_valuation_complete
                else ""
            ),
            "net_quantity": _fmt_quantity(attributed_net_quantity),
        },
        "unreconciled_delta": {
            "symbol_count": sum(
                1 for row in symbol_rows.values()
                if _decimal(row.get("unreconciled_net_quantity")) != ZERO
            ),
            "valuation_available": actual_valuation_complete,
            "gross_market_value": (
                _fmt_money(actual_gross_market_value - attributed_gross_market_value)
                if actual_valuation_complete
                else ""
            ),
            "signed_market_value": (
                _fmt_money(actual_signed_market_value - attributed_signed_market_value)
                if actual_valuation_complete
                else ""
            ),
            "unrealized_pnl": (
                _fmt_money(actual_unrealized - attributed_unrealized)
                if actual_valuation_complete
                else ""
            ),
            "net_quantity": _fmt_quantity(actual_net_quantity - attributed_net_quantity),
        },
        "symbol_rows": sorted(symbol_rows.values(), key=lambda row: row["symbol"]),
        "cross_bucket_concentration": sorted(
            concentration,
            key=lambda row: (
                -_decimal(row.get("gross_market_value")),
                row["symbol"],
            ),
        ),
        "runtime_rows": _finalize_open_position_groups(runtime_rows, "runtime_id"),
        "bucket_rows": _finalize_open_position_groups(bucket_rows, "capital_bucket"),
        "today_buy_flow": {
            "bought_then_sold_count": len(completed_today_rows),
            "bought_then_sold_estimated_net_pnl": _fmt_money(
                sum((_decimal(row.get("estimated_net_pnl")) for row in completed_today_rows), ZERO)
            ),
            "still_held_batch_count": len(today_open_batches),
            "still_held_valuation_available": all(
                bool(row.get("valuation_available")) for row in today_open_batches
            ),
            "still_held_unrealized_pnl": (
                _fmt_money(
                    sum(
                        (_decimal(row.get("unrealized_pnl")) for row in today_open_batches),
                        ZERO,
                    )
                )
                if all(bool(row.get("valuation_available")) for row in today_open_batches)
                else ""
            ),
            "still_held_market_value": (
                _fmt_money(
                    sum(
                        (_decimal(row.get("market_value")) for row in today_open_batches),
                        ZERO,
                    )
                )
                if all(bool(row.get("valuation_available")) for row in today_open_batches)
                else ""
            ),
            "bought_then_sold_rows": completed_today_rows[-20:],
            "still_held_rows": today_open_batches[-20:],
        },
    }


def _group_completed_trade_performance(
    rows: list[dict[str, Any]],
    group_field: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        group_id = str(row.get(group_field) or "")
        if group_id:
            grouped.setdefault(group_id, []).append(row)
    summaries: list[dict[str, Any]] = []
    for group_id, group_rows in sorted(grouped.items()):
        net_values = [_decimal(row.get("estimated_net_pnl")) for row in group_rows]
        gross_values = [_decimal(row.get("gross_realized_pnl")) for row in group_rows]
        positive_net = sum((value for value in net_values if value > ZERO), ZERO)
        negative_net = sum((-value for value in net_values if value < ZERO), ZERO)
        positive_gross = sum((value for value in gross_values if value > ZERO), ZERO)
        negative_gross = sum((-value for value in gross_values if value < ZERO), ZERO)
        equity = ZERO
        peak = ZERO
        maximum_drawdown = ZERO
        for value in net_values:
            equity += value
            peak = max(peak, equity)
            maximum_drawdown = max(maximum_drawdown, peak - equity)
        trade_count = len(group_rows)
        win_count = sum(value > ZERO for value in net_values)
        loss_count = sum(value < ZERO for value in net_values)
        breakeven_count = trade_count - win_count - loss_count
        summaries.append(
            {
                group_field: group_id,
                "completed_trade_count": trade_count,
                "win_count_after_estimated_fees": win_count,
                "loss_count_after_estimated_fees": loss_count,
                "breakeven_count_after_estimated_fees": breakeven_count,
                "win_rate_after_estimated_fees_pct": _fmt_ratio(
                    Decimal(win_count) * Decimal("100") / Decimal(trade_count)
                    if trade_count
                    else ZERO
                ),
                "gross_realized_pnl": _fmt_money(sum(gross_values, ZERO)),
                "estimated_fees": _fmt_money(
                    sum(
                        (_decimal(row.get("estimated_fees")) for row in group_rows),
                        ZERO,
                    )
                ),
                "estimated_net_realized_pnl": _fmt_money(sum(net_values, ZERO)),
                "gross_profit_factor": _fmt_factor(positive_gross, negative_gross),
                "profit_factor_after_estimated_fees": _fmt_factor(
                    positive_net, negative_net
                ),
                "maximum_drawdown_after_estimated_fees": _fmt_money(maximum_drawdown),
                "fee_source": "configured_conservative_estimate",
            }
        )
    return summaries


def _accumulate_open_position_group(
    groups: dict[str, dict[str, Any]],
    group_id: str,
    *,
    signed_quantity: Decimal,
    gross_market_value: Decimal,
    unrealized: Decimal,
    valuation_available: bool,
) -> None:
    if not group_id:
        return
    row = groups.setdefault(
        group_id,
        {
            "signed_quantity": ZERO,
            "gross_market_value": ZERO,
            "unrealized_pnl": ZERO,
            "batch_count": 0,
            "valuation_available": True,
        },
    )
    row["signed_quantity"] += signed_quantity
    row["gross_market_value"] += gross_market_value
    row["unrealized_pnl"] += unrealized
    row["batch_count"] += 1
    row["valuation_available"] = bool(
        row["valuation_available"] and valuation_available
    )


def _finalize_open_position_groups(
    groups: Mapping[str, dict[str, Any]],
    key_name: str,
) -> list[dict[str, Any]]:
    return [
        {
            key_name: group_id,
            "batch_count": row["batch_count"],
            "net_quantity": _fmt_quantity(row["signed_quantity"]),
            "valuation_available": bool(row["valuation_available"]),
            "gross_market_value": (
                _fmt_money(row["gross_market_value"])
                if row["valuation_available"]
                else ""
            ),
            "unrealized_pnl": (
                _fmt_money(row["unrealized_pnl"])
                if row["valuation_available"]
                else ""
            ),
        }
        for group_id, row in sorted(
            groups.items(),
            key=lambda item: (-item[1]["gross_market_value"], item[0]),
        )
    ]


def _normalize_holdings(
    holding_rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for row in holding_rows:
        if not isinstance(row, Mapping):
            continue
        symbol = _normalize_symbol(str(row.get("symbol") or row.get("ticker") or ""))
        quantity = _decimal(row.get("quantity") or row.get("qty"))
        side = str(row.get("side") or row.get("position_side") or "").strip().lower()
        signed_quantity = -quantity if "short" in side and quantity > ZERO else quantity
        market_price = _decimal(
            row.get("market_price")
            or row.get("current_price")
            or row.get("last_price")
            or row.get("price")
        )
        cost_price = _decimal(
            row.get("cost_price")
            or row.get("average_cost")
            or row.get("avg_cost")
            or row.get("cost")
        )
        gross_market_value = _decimal(row.get("market_value"))
        valuation_available = gross_market_value > ZERO or market_price > ZERO
        if gross_market_value <= ZERO and market_price > ZERO and quantity > ZERO:
            gross_market_value = market_price * quantity
        signed_market_value = -gross_market_value if signed_quantity < ZERO else gross_market_value
        unrealized_pnl = _decimal(row.get("unrealized_pnl") or row.get("position_pnl"))
        if unrealized_pnl == ZERO and market_price > ZERO and cost_price > ZERO and quantity > ZERO:
            unrealized_pnl = (market_price - cost_price) * quantity
            if signed_quantity < ZERO:
                unrealized_pnl = -unrealized_pnl
        if symbol:
            normalized[symbol] = {
                "signed_quantity": signed_quantity,
                "market_price": market_price,
                "cost_price": cost_price,
                "gross_market_value": gross_market_value,
                "signed_market_value": signed_market_value,
                "unrealized_pnl": unrealized_pnl,
                "valuation_available": valuation_available,
            }
    return normalized


def _fmt_factor(profit: Decimal, loss: Decimal) -> str:
    if loss <= ZERO:
        return "unbounded" if profit > ZERO else "0.0000"
    return _fmt_ratio(profit / loss)


def _fmt_ratio(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001")))


def _new_york_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(NEW_YORK).date().isoformat()


def _dedupe_unmatched_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        status = str(row.get("attribution_status") or "")
        if status == "matched_fill_batch":
            deduped.append(row)
            continue
        identity = (
            status,
            str(row.get("order_id") or ""),
            str(row.get("trade_id") or ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(row)
    return deduped


def _dedupe_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        identity = (
            str(row.get("code") or ""),
            str(row.get("order_id") or ""),
            str(row.get("trade_id") or ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(row)
    return deduped


def _apply_open_fill(
    local_row: Mapping[str, Any],
    broker_row: Mapping[str, Any],
    *,
    trade_id: str,
    delta_quantity: Decimal,
    cumulative_quantity: Decimal,
    open_batches: dict[str, _OpenBatchState],
) -> _OpenBatchState:
    direction = str(local_row.get("direction") or "")
    symbol = str(local_row.get("symbol") or "")
    order_id = str(local_row.get("order_id") or "")
    batch_id = _build_batch_id(
        test_epoch_id=str(local_row.get("test_epoch_id") or ""),
        capital_bucket=str(local_row.get("capital_bucket") or ""),
        runtime_id=str(local_row.get("runtime_id") or ""),
        direction=direction,
        symbol=symbol,
        open_order_id=order_id,
        trade_id=trade_id,
    )
    batch = open_batches.get(batch_id)
    fill_price = _decimal(broker_row.get("executed_price") or broker_row.get("price"))
    if batch is None:
        batch = _OpenBatchState(
            batch_id=batch_id,
            test_epoch_id=str(local_row.get("test_epoch_id") or ""),
            capital_bucket=str(local_row.get("capital_bucket") or ""),
            runtime_id=str(local_row.get("runtime_id") or ""),
            direction=direction,
            symbol=symbol,
            open_order_id=order_id,
            trade_id=trade_id,
            filled_quantity=cumulative_quantity,
            remaining_quantity=cumulative_quantity,
            open_price=fill_price,
            metadata={
                key: local_row.get(key)
                for key in (
                    "strategy_id", "signal_id", "timeframe", "stop_price", "target_price",
                    "source_market_event_id", "created_at", "submitted_at", "position_action",
                )
                if local_row.get(key) not in (None, "")
            },
        )
        open_batches[batch_id] = batch
    else:
        batch.filled_quantity = cumulative_quantity
        batch.remaining_quantity += delta_quantity
        if fill_price > ZERO:
            batch.open_price = fill_price
    return batch


def _apply_exit_fill(
    local_row: Mapping[str, Any],
    broker_row: Mapping[str, Any],
    *,
    trade_id: str,
    delta_quantity: Decimal,
    open_batches: dict[str, _OpenBatchState],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    source_open_order_id = str(local_row.get("source_open_order_id") or "")
    source_open_trade_id = str(local_row.get("source_open_trade_id") or "")
    direction = str(local_row.get("direction") or "")
    symbol = str(local_row.get("symbol") or "")
    base_event = {
        "event_type": "exit_fill",
        "symbol": symbol,
        "direction": direction,
        "capital_bucket": str(local_row.get("capital_bucket") or ""),
        "runtime_id": str(local_row.get("runtime_id") or ""),
        "test_epoch_id": str(local_row.get("test_epoch_id") or ""),
        "order_id": str(local_row.get("order_id") or ""),
        "trade_id": trade_id,
        "filled_quantity": _fmt_quantity(delta_quantity),
        "filled_price": _fmt_money(_decimal(broker_row.get("executed_price") or broker_row.get("price"))),
        "filled_at": str(
            broker_row.get("trade_done_at")
            or broker_row.get("updated_at")
            or broker_row.get("created_at")
            or local_row.get("submitted_at")
            or local_row.get("created_at")
            or ""
        ),
        "source_open_order_id": source_open_order_id,
        "source_open_trade_id": source_open_trade_id,
        "counts_for_performance": True,
    }
    if not source_open_order_id or not source_open_trade_id:
        anomaly = _make_anomaly(
            code="exit_missing_source_batch",
            broker_row=broker_row,
            local_row=local_row,
            message="Exit fill must point to an exact source open batch.",
        )
        return (
            {
                **base_event,
                "attribution_status": "exit_missing_source_batch",
                "include_in_bucket_performance": False,
                "include_in_strategy_performance": False,
            },
            anomaly,
        )
    batch_id = _build_batch_id(
        test_epoch_id=str(local_row.get("test_epoch_id") or ""),
        capital_bucket=str(local_row.get("capital_bucket") or ""),
        runtime_id=str(local_row.get("runtime_id") or ""),
        direction=direction,
        symbol=symbol,
        open_order_id=source_open_order_id,
        trade_id=source_open_trade_id,
    )
    matched_batch = open_batches.get(batch_id)
    if matched_batch is None:
        cross_epoch_batch = _find_open_batch_across_epochs(
            open_batches.values(),
            capital_bucket=str(local_row.get("capital_bucket") or ""),
            runtime_id=str(local_row.get("runtime_id") or ""),
            direction=direction,
            symbol=symbol,
            open_order_id=source_open_order_id,
            trade_id=source_open_trade_id,
        )
        if cross_epoch_batch is not None:
            anomaly = _make_anomaly(
                code="cross_epoch_exit_attribution_rejected",
                broker_row=broker_row,
                local_row=local_row,
                message="Exit fill points to a source batch from another test epoch.",
            )
            return (
                {
                    **base_event,
                    "attribution_status": "cross_epoch_exit_attribution_rejected",
                    "include_in_bucket_performance": False,
                    "include_in_strategy_performance": False,
                    "source_batch_id": cross_epoch_batch.batch_id,
                },
                anomaly,
            )
        anomaly = _make_anomaly(
            code="exit_source_batch_not_found",
            broker_row=broker_row,
            local_row=local_row,
            message="Exit fill points to a source batch that does not exist in history.",
        )
        return (
            {
                **base_event,
                "attribution_status": "exit_source_batch_not_found",
                "include_in_bucket_performance": False,
                "include_in_strategy_performance": False,
            },
            anomaly,
        )
    if delta_quantity > matched_batch.remaining_quantity:
        anomaly = _make_anomaly(
            code="exit_quantity_exceeds_open_batch",
            broker_row=broker_row,
            local_row=local_row,
            message="Exit fill quantity exceeds the remaining quantity of the source open batch.",
        )
        return (
            {
                **base_event,
                "attribution_status": "exit_quantity_exceeds_open_batch",
                "include_in_bucket_performance": False,
                "include_in_strategy_performance": False,
                "source_batch_id": matched_batch.batch_id,
                "source_batch_remaining_quantity": _fmt_quantity(matched_batch.remaining_quantity),
            },
            anomaly,
        )
    matched_batch.remaining_quantity -= delta_quantity
    exit_price = _decimal(broker_row.get("executed_price") or broker_row.get("price"))
    realized_pnl = (exit_price - matched_batch.open_price) * delta_quantity
    if direction == "short":
        realized_pnl = -realized_pnl
    return (
        {
            **base_event,
            "attribution_status": "matched_fill_batch",
            "include_in_bucket_performance": True,
            "include_in_strategy_performance": True,
            "source_batch_id": matched_batch.batch_id,
            "realized_pnl": _fmt_money(realized_pnl),
        },
        None,
    )


def _build_reservations(
    local_rows: list[dict[str, Any]],
    latest_broker_by_order_id: Mapping[str, Mapping[str, Any]],
    max_fill_by_trade: Mapping[tuple[str, str], Decimal],
) -> list[dict[str, Any]]:
    reservations: list[dict[str, Any]] = []
    for row in local_rows:
        normalized = _merged_local_row(row)
        if normalized["intent"] != "open":
            continue
        order_id = str(row.get("order_id") or "")
        latest_broker = latest_broker_by_order_id.get(order_id, {})
        latest_status = _canonical_status(latest_broker)
        submitted_quantity = _decimal(row.get("quantity"))
        filled_quantity = sum(
            (
                quantity
                for (matched_order_id, _trade_id), quantity in max_fill_by_trade.items()
                if matched_order_id == order_id
            ),
            ZERO,
        )
        reserved_quantity = submitted_quantity
        if latest_status in RELEASE_STATUSES:
            if latest_status in {"filled"} and filled_quantity < submitted_quantity:
                reserved_quantity = submitted_quantity - filled_quantity
            else:
                reserved_quantity = ZERO
        elif latest_status == "partially_filled":
            reserved_quantity = max(submitted_quantity - filled_quantity, ZERO)
        reservations.append(
            {
                "capital_bucket": str(row.get("capital_bucket") or ""),
                "runtime_id": str(row.get("runtime_id") or ""),
                "test_epoch_id": str(row.get("test_epoch_id") or ""),
                "direction": str(normalized["direction"]),
                "symbol": str(normalized["symbol"]),
                "order_id": order_id,
                "submitted_quantity": _fmt_quantity(submitted_quantity),
                "filled_quantity": _fmt_quantity(filled_quantity),
                "reserved_quantity": _fmt_quantity(reserved_quantity),
                "reservation_released": reserved_quantity <= ZERO,
                "latest_broker_status": latest_status,
            }
        )
    return sorted(reservations, key=lambda row: (row["capital_bucket"], row["runtime_id"], row["symbol"], row["order_id"]))


def _serialize_batches(open_batches: Mapping[str, _OpenBatchState]) -> list[dict[str, Any]]:
    rows = []
    for batch in sorted(open_batches.values(), key=lambda item: item.batch_id):
        rows.append(
            {
                "batch_id": batch.batch_id,
                "test_epoch_id": batch.test_epoch_id,
                "capital_bucket": batch.capital_bucket,
                "runtime_id": batch.runtime_id,
                "direction": batch.direction,
                "symbol": batch.symbol,
                "open_order_id": batch.open_order_id,
                "trade_id": batch.trade_id,
                "filled_quantity": _fmt_quantity(batch.filled_quantity),
                "remaining_quantity": _fmt_quantity(batch.remaining_quantity),
                "open_price": _fmt_money(batch.open_price),
                "metadata": dict(batch.metadata),
            }
        )
    return rows


def _build_symbol_checks(
    open_batches: Mapping[str, _OpenBatchState],
    broker_net_positions: Mapping[str, Any],
) -> list[dict[str, Any]]:
    net_by_symbol: dict[str, Decimal] = {}
    for batch in open_batches.values():
        sign = Decimal("-1") if batch.direction == "short" else Decimal("1")
        net_by_symbol.setdefault(batch.symbol, ZERO)
        net_by_symbol[batch.symbol] += sign * batch.remaining_quantity
    normalized_broker_positions = {
        _normalize_symbol(str(symbol)): _decimal(quantity)
        for symbol, quantity in broker_net_positions.items()
    }
    all_symbols = sorted(set(net_by_symbol) | set(normalized_broker_positions))
    rows = []
    for symbol in all_symbols:
        broker_quantity = normalized_broker_positions.get(symbol, ZERO)
        virtual_quantity = net_by_symbol.get(symbol, ZERO)
        rows.append(
            {
                "symbol": symbol,
                "virtual_net_quantity": _fmt_quantity(virtual_quantity),
                "broker_net_quantity": _fmt_quantity(broker_quantity),
                "matches_broker_net": virtual_quantity == broker_quantity,
            }
        )
    return rows


def _existing_fill_quantities(existing_state: Mapping[str, Any]) -> dict[tuple[str, str], Decimal]:
    quantities: dict[tuple[str, str], Decimal] = {}
    for row in existing_state.get("events", []):
        if not isinstance(row, Mapping):
            continue
        # Unmatched events are diagnostic facts, not consumed fills.  They
        # must remain repairable when exact local order metadata arrives later.
        if str(row.get("attribution_status") or "") != "matched_fill_batch":
            continue
        order_id = str(row.get("order_id") or "")
        trade_id = str(row.get("trade_id") or "")
        if order_id and trade_id:
            key = (order_id, trade_id)
            quantities[key] = quantities.get(key, ZERO) + _decimal(row.get("filled_quantity"))
    return quantities


def _existing_open_batches(existing_state: Mapping[str, Any]) -> dict[str, _OpenBatchState]:
    batches: dict[str, _OpenBatchState] = {}
    for row in existing_state.get("batches", []):
        if not isinstance(row, Mapping):
            continue
        batch_id = str(row.get("batch_id") or "")
        if not batch_id:
            continue
        batches[batch_id] = _OpenBatchState(
            batch_id=batch_id,
            test_epoch_id=str(row.get("test_epoch_id") or ""),
            capital_bucket=str(row.get("capital_bucket") or ""),
            runtime_id=str(row.get("runtime_id") or ""),
            direction=str(row.get("direction") or ""),
            symbol=_normalize_symbol(str(row.get("symbol") or "")),
            open_order_id=str(row.get("open_order_id") or ""),
            trade_id=str(row.get("trade_id") or ""),
            filled_quantity=_decimal(row.get("filled_quantity")),
            remaining_quantity=_decimal(row.get("remaining_quantity")),
            open_price=_decimal(row.get("open_price")),
            metadata=dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), Mapping) else {},
        )
    return batches


def _normalized_local_row(row: Mapping[str, Any]) -> dict[str, str]:
    symbol = _normalize_symbol(str(row.get("symbol") or row.get("ticker") or ""))
    position_action = str(row.get("position_action") or row.get("action") or "").strip().lower()
    side = str(row.get("side") or "").strip().lower()
    direction = str(row.get("direction") or "").strip().lower()
    if direction not in {"long", "short"}:
        if position_action == "open_short" or side in {"sell_short", "sell"} and bool(row.get("source_open_order_id")) is False:
            direction = "short"
        else:
            direction = "long"
    if position_action in OPEN_ACTIONS or side in {"buy", "sell_short"}:
        intent = "open"
    elif position_action in EXIT_ACTIONS or side in {"sell", "buy"}:
        intent = "exit"
    else:
        intent = "open"
    return {
        "symbol": symbol,
        "direction": direction,
        "intent": intent,
    }


def _merged_local_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalized_local_row(row)
    merged = dict(row)
    merged.update(normalized)
    merged["symbol"] = normalized["symbol"]
    merged["direction"] = normalized["direction"]
    merged["intent"] = normalized["intent"]
    return merged


def _latest_broker_rows_by_order_id(broker_rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for row in broker_rows:
        order_id = str(row.get("order_id") or row.get("id") or "")
        if order_id:
            latest[order_id] = row
    return latest


def _find_open_batch_across_epochs(
    open_batches: Iterable[_OpenBatchState],
    *,
    capital_bucket: str,
    runtime_id: str,
    direction: str,
    symbol: str,
    open_order_id: str,
    trade_id: str,
) -> _OpenBatchState | None:
    for batch in open_batches:
        if (
            batch.capital_bucket == capital_bucket
            and batch.runtime_id == runtime_id
            and batch.direction == direction
            and batch.symbol == symbol
            and batch.open_order_id == open_order_id
            and batch.trade_id == trade_id
        ):
            return batch
    return None


def _make_unmatched_event(broker_row: Mapping[str, Any], anomaly: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_type": "unmatched_fill",
        "attribution_status": str(anomaly.get("code") or ""),
        "include_in_bucket_performance": False,
        "include_in_strategy_performance": False,
        "counts_for_performance": True,
        "symbol": _normalize_symbol(str(broker_row.get("symbol") or "")),
        "order_id": str(broker_row.get("order_id") or ""),
        "trade_id": str(broker_row.get("trade_id") or ""),
        "filled_quantity": _fmt_quantity(
            _decimal(
                broker_row.get("executed_quantity")
                or broker_row.get("filled_quantity")
                or broker_row.get("quantity")
            )
        ),
    }


def _make_anomaly(
    *,
    code: str,
    broker_row: Mapping[str, Any],
    message: str,
    local_row: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "order_id": str(broker_row.get("order_id") or broker_row.get("id") or ""),
        "trade_id": str(broker_row.get("trade_id") or ""),
        "symbol": _normalize_symbol(str(broker_row.get("symbol") or "")),
        "local_order_id": str((local_row or {}).get("order_id") or ""),
        "test_epoch_id": str((local_row or {}).get("test_epoch_id") or ""),
    }


def _build_batch_id(
    *,
    test_epoch_id: str,
    capital_bucket: str,
    runtime_id: str,
    direction: str,
    symbol: str,
    open_order_id: str,
    trade_id: str,
) -> str:
    return "|".join(
        [
            test_epoch_id,
            capital_bucket,
            runtime_id,
            direction,
            symbol,
            open_order_id,
            trade_id,
        ]
    )


def _normalize_symbol(value: str) -> str:
    text = value.strip().upper()
    if text.endswith(".US"):
        return text[:-3]
    return text


def _canonical_status(row: Mapping[str, Any]) -> str:
    status = str(row.get("status") or row.get("order_status") or "").strip().lower()
    normalized = status.replace(" ", "_").replace("-", "_")
    alias_map = {
        "partiallyfilled": "partially_filled",
        "partialfilled": "partially_filled",
        "partially_filled": "partially_filled",
        "filled": "filled",
        "canceled": "canceled",
        "cancelled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
    }
    return alias_map.get(normalized, normalized)


def _row_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(
            row.get("executed_at")
            or row.get("trade_done_at")
            or row.get("updated_at")
            or row.get("created_at")
            or row.get("submitted_at")
            or ""
        ),
        str(row.get("order_id") or row.get("id") or ""),
        str(row.get("trade_id") or ""),
    )


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, "", False):
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def _fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY))


def _fmt_quantity(value: Decimal) -> str:
    return str(value.quantize(QUANTITY))
