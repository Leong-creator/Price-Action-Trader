#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_fill_attribution_lib import (
    apply_account_reconciliation_adjustments,
    broker_fill_rows_from_orders_and_executions,
    rebuild_fill_attribution,
)

from scripts.m15_longbridge_realtime_execution_lib import (
    DEFAULT_DAILY_DIR,
    DEFAULT_OUTPUT_DIR,
    LEDGER_JSONL as EXECUTION_LEDGER_JSONL,
    ORDER_RECONCILIATION_JSON,
    PAPER_SHORT_RUNTIME_IDS,
    account_short_position_quantities,
    broker_order_for_ledger_row,
    broker_order_is_terminal,
    confirmed_order_quantity,
    decimal,
    is_short_position_row,
    ledger_row_order_id,
    latest_account_orders_by_id,
    normalize_position_action,
    normalize_side,
    order_has_confirmed_fill,
    fmt_decimal,
    fmt_money,
    hydrate_unconfirmed_execution_rows,
    parse_signal_time,
    parse_utc_datetime,
    project_path,
    to_iso,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_position_manager.json"
DEFAULT_ACCOUNT_STATE = DEFAULT_OUTPUT_DIR / "m15_longbridge_realtime_account_state.json"
DEFAULT_MARKET_EVENTS = DEFAULT_OUTPUT_DIR / "m15_realtime_market_events.jsonl"
DEFAULT_SIGNAL_EVENTS = DEFAULT_OUTPUT_DIR / "m15_realtime_signal_events.jsonl"
DEFAULT_EXECUTION_LEDGER = DEFAULT_OUTPUT_DIR / EXECUTION_LEDGER_JSONL
DEFAULT_FILL_ATTRIBUTION = DEFAULT_OUTPUT_DIR / "m15_longbridge_fill_attribution_runtime.json"
DEFAULT_CANONICAL_FILL_ATTRIBUTION = DEFAULT_OUTPUT_DIR / "m15_longbridge_fill_attribution_v2.json"
ACCOUNT_RECONCILIATION_ADJUSTMENTS = "m15_account_reconciliation_adjustments.json"
SUMMARY_JSON = "m15_longbridge_realtime_position_manager.json"
LEDGER_JSONL = "m15_longbridge_realtime_position_manager_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_position_manager.md"
ZERO = Decimal("0")
NEW_YORK = ZoneInfo("America/New_York")
PA002_REPAIRED_RUNTIME_ID = "M10-PA-002-5m-repaired-v1"


@dataclass(frozen=True, slots=True)
class RealtimePositionManagerConfig:
    stage: str
    title: str
    account_state_path: Path
    market_events_path: Path
    realtime_signal_events_path: Path
    realtime_execution_ledger_path: Path
    fill_attribution_path: Path
    canonical_fill_attribution_path: Path
    output_dir: Path
    max_exit_events_per_run: int
    stop_loss_events_bypass_run_cap: bool
    exit_attempt_cooldown_seconds: int
    manage_untracked_positions_for_exit: bool
    untracked_stop_loss_percent: Decimal
    untracked_take_profit_percent: Decimal
    long_exit_limit_discount_percent: Decimal
    short_cover_limit_premium_percent: Decimal
    test_epoch_id: str
    test_started_at: str
    paper_short_testing_enabled: bool
    short_test_epoch_id: str
    paper_short_runtime_ids: tuple[str, ...]
    hard_boundaries: dict[str, bool]

    def __post_init__(self) -> None:
        validate_config(self)


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RealtimePositionManagerConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    manager = payload.get("longbridge_position_manager", {})
    short_testing = manager.get("paper_short_testing", {}) if isinstance(manager.get("paper_short_testing"), dict) else {}
    output_dir = resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR))
    return RealtimePositionManagerConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_position_manager")),
        title=str(payload.get("title", "长桥模拟账户实时持仓退出管理")),
        account_state_path=resolve_repo_path(inputs.get("account_state", DEFAULT_ACCOUNT_STATE)),
        market_events_path=resolve_repo_path(inputs.get("market_events", DEFAULT_MARKET_EVENTS)),
        realtime_signal_events_path=resolve_repo_path(inputs.get("realtime_signal_events", DEFAULT_SIGNAL_EVENTS)),
        realtime_execution_ledger_path=resolve_repo_path(inputs.get("realtime_execution_ledger", DEFAULT_EXECUTION_LEDGER)),
        fill_attribution_path=resolve_repo_path(
            inputs.get("fill_attribution")
            or (output_dir / "m15_longbridge_fill_attribution_runtime.json")
        ),
        canonical_fill_attribution_path=resolve_repo_path(
            inputs.get("canonical_fill_attribution")
            or (output_dir / "m15_longbridge_fill_attribution_v2.json")
        ),
        output_dir=output_dir,
        max_exit_events_per_run=int(manager.get("max_exit_events_per_run", 10)),
        stop_loss_events_bypass_run_cap=bool(manager.get("stop_loss_events_bypass_run_cap", True)),
        exit_attempt_cooldown_seconds=int(manager.get("exit_attempt_cooldown_seconds", 900)),
        manage_untracked_positions_for_exit=bool(manager.get("manage_untracked_positions_for_exit", True)),
        untracked_stop_loss_percent=decimal(manager.get("untracked_stop_loss_percent", "3")),
        untracked_take_profit_percent=decimal(manager.get("untracked_take_profit_percent", "3")),
        long_exit_limit_discount_percent=decimal(manager.get("long_exit_limit_discount_percent", "0.5")),
        short_cover_limit_premium_percent=decimal(manager.get("short_cover_limit_premium_percent", "0.5")),
        test_epoch_id=str(manager.get("test_epoch_id") or ""),
        test_started_at=str(manager.get("test_started_at") or ""),
        paper_short_testing_enabled=bool(short_testing.get("enabled", False)),
        short_test_epoch_id=str(short_testing.get("test_epoch_id") or ""),
        paper_short_runtime_ids=tuple(str(item) for item in short_testing.get("runtime_ids", []) if str(item)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: RealtimePositionManagerConfig) -> None:
    if config.stage != "M15.longbridge_realtime_position_manager":
        raise ValueError("M15 realtime position manager stage drift")
    if config.max_exit_events_per_run <= 0:
        raise ValueError("M15 realtime position manager max_exit_events_per_run must be positive")
    if config.exit_attempt_cooldown_seconds <= 0:
        raise ValueError("M15 realtime position manager exit_attempt_cooldown_seconds must be positive")
    if config.manage_untracked_positions_for_exit and (
        config.untracked_stop_loss_percent <= ZERO or config.untracked_take_profit_percent <= ZERO
    ):
        raise ValueError("M15 realtime position manager untracked exit percents must be positive")
    if not (ZERO < config.long_exit_limit_discount_percent <= Decimal("5")):
        raise ValueError("M15 realtime position manager long exit limit discount is invalid")
    if not (ZERO < config.short_cover_limit_premium_percent <= Decimal("5")):
        raise ValueError("M15 realtime position manager short cover limit premium is invalid")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 realtime position manager must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("M15 realtime position manager cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("M15 realtime position manager cannot enable real money actions")
    if config.hard_boundaries.get("local_simulation_as_exit_source", False):
        raise ValueError("M15 realtime position manager cannot use local simulation as exit source")
    if config.hard_boundaries.get("short_selling", False):
        if not config.paper_short_testing_enabled:
            raise ValueError("M15 realtime position manager short exit needs explicit paper short testing")
        if not config.short_test_epoch_id or not config.paper_short_runtime_ids:
            raise ValueError("M15 realtime position manager short exit needs a short test epoch and whitelist")
        invalid = set(config.paper_short_runtime_ids) - set(PAPER_SHORT_RUNTIME_IDS)
        if invalid:
            raise ValueError(f"M15 realtime position manager has unapproved short runtime: {sorted(invalid)}")
    elif config.paper_short_testing_enabled or config.paper_short_runtime_ids:
        raise ValueError("M15 realtime position manager short config requires the paper short boundary")


def run_realtime_position_manager(
    config: RealtimePositionManagerConfig | None = None,
    *,
    generated_at: str | None = None,
    account_state_override: dict[str, Any] | None = None,
    market_events_override: list[dict[str, Any]] | None = None,
    execution_rows_override: list[dict[str, Any]] | None = None,
    signal_events_override: list[dict[str, Any]] | None = None,
    fill_attribution_state_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    account_state = dict(account_state_override) if account_state_override is not None else read_json(config.account_state_path)
    market_events = list(market_events_override) if market_events_override is not None else read_jsonl(config.market_events_path)
    raw_execution_rows = (
        list(execution_rows_override)
        if execution_rows_override is not None
        else read_jsonl(config.realtime_execution_ledger_path)
    )
    hydrated_execution_rows = hydrate_unconfirmed_execution_rows(
        raw_execution_rows,
        account_state,
        read_json(config.output_dir / ORDER_RECONCILIATION_JSON),
    )
    long_execution_rows = rows_for_current_test_epoch(
        hydrated_execution_rows,
        config.test_epoch_id,
        config.test_started_at,
    )
    short_execution_rows = (
        rows_for_current_test_epoch(hydrated_execution_rows, config.short_test_epoch_id, "")
        if config.paper_short_testing_enabled
        else []
    )
    execution_rows = merge_active_epoch_rows(long_execution_rows, short_execution_rows)
    all_signal_events = (
        list(signal_events_override)
        if signal_events_override is not None
        else read_jsonl(config.realtime_signal_events_path)
    )
    long_signal_events = rows_for_current_test_epoch(
        all_signal_events,
        config.test_epoch_id,
        config.test_started_at,
    )
    short_signal_events = (
        rows_for_current_test_epoch(all_signal_events, config.short_test_epoch_id, "")
        if config.paper_short_testing_enabled
        else []
    )
    existing_signal_events = merge_active_epoch_rows(long_signal_events, short_signal_events)
    existing_signal_ids = {str(row.get("signal_id")) for row in existing_signal_events if row.get("signal_id")}

    latest_prices = latest_price_by_symbol(market_events)
    exact_attribution_required = config.test_epoch_id.startswith("m15-sdk-formal-")
    fill_attribution = (
        cached_or_refreshed_fill_attribution(
            config,
            account_state,
            execution_rows,
            fill_attribution_state_cache,
        )
        if exact_attribution_required
        else {}
    )
    if exact_attribution_required:
        position_slices = fill_attributed_long_position_slices(
            account_state,
            fill_attribution,
            config.test_epoch_id,
            config.manage_untracked_positions_for_exit,
        )
    else:
        position_slices = account_position_slices(
            account_state,
            long_execution_rows,
            config.manage_untracked_positions_for_exit,
        )
    bucket_open_exposure = fill_attributed_open_exposure_by_bucket_symbol(
        fill_attribution
    )
    position_slices.extend(confirmed_short_position_slices(account_state, short_execution_rows, config))
    retriable_short_exit_signal_ids = terminal_retriable_short_exit_signal_ids(short_execution_rows, account_state)
    retriable_exit_signal_ids = (
        retriable_short_exit_signal_ids
        | broker_failed_long_exit_signal_ids(
            long_execution_rows, account_state
        )
        | unprocessed_exit_signal_ids(existing_signal_events, execution_rows)
    )
    recent_exit_attempts = recent_exit_attempt_keys(
        execution_rows + existing_signal_events,
        now,
        config.exit_attempt_cooldown_seconds,
    )
    ledger_rows: list[dict[str, Any]] = []
    exit_candidates: list[dict[str, Any]] = []
    for position, metadata in position_slices:
        symbol = str(position["symbol"])
        latest = latest_prices.get(symbol, ZERO)
        row, event = evaluate_position(
            config,
            position,
            metadata,
            latest,
            generated_at_iso,
            existing_signal_ids,
            recent_exit_attempts,
            retriable_exit_signal_ids,
        )
        ledger_rows.append(row)
        if event:
            exit_candidates.append(event)
            existing_signal_ids.add(event["signal_id"])
    exit_events, deferred_exit_events = select_exit_events(
        exit_candidates,
        max_non_stop_events=config.max_exit_events_per_run,
        stop_loss_events_bypass_run_cap=config.stop_loss_events_bypass_run_cap,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.realtime_signal_events_path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(config.realtime_signal_events_path, exit_events)
    write_jsonl(config.output_dir / LEDGER_JSONL, ledger_rows)
    summary = {
        "schema_version": "m15.longbridge-realtime-position-manager.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at_iso,
        "source_mode": "longbridge_account_positions_plus_realtime_market_events",
        "execution_input_mode": (
            "runtime_memory"
            if execution_rows_override is not None
            else "jsonl_audit_stream"
        ),
        "signal_input_mode": (
            "runtime_memory"
            if signal_events_override is not None
            else "jsonl_audit_stream"
        ),
        "local_simulation_isolated": True,
        "local_close_signal_used": False,
        "position_count": len(position_slices),
        "managed_short_position_count": sum(
            1 for _position, metadata in position_slices if str(metadata.get("position_direction") or "") == "short"
        ),
        "exact_fill_attribution_required": exact_attribution_required,
        "fill_attribution_summary": fill_attribution.get("summary", {}),
        "fill_attribution_mismatch_count": sum(
            1 for row in fill_attribution.get("symbol_checks", [])
            if isinstance(row, dict) and not bool(row.get("matches_broker_net"))
        ),
        "fill_attribution_mismatch_symbols": sorted(
            str(row.get("symbol") or "")
            for row in fill_attribution.get("symbol_checks", [])
            if isinstance(row, dict) and not bool(row.get("matches_broker_net")) and row.get("symbol")
        ),
        "fill_attributed_open_exposure_by_bucket_symbol": bucket_open_exposure,
        "account_position_count": len(account_positions(account_state)),
        "managed_position_count": sum(1 for row in ledger_rows if row.get("position_management_scope") == "m15_realtime_managed"),
        "unmanaged_position_count": sum(1 for row in ledger_rows if row.get("position_management_scope") == "longbridge_account_unmanaged"),
        "exit_only_position_count": sum(
            1 for row in ledger_rows if row.get("position_management_scope") == "longbridge_account_exit_only"
        ),
        "unmanaged_position_symbols": [
            str(row.get("symbol", ""))
            for row in ledger_rows
            if row.get("position_management_scope") == "longbridge_account_unmanaged"
        ],
        "exit_only_position_symbols": [
            str(row.get("symbol", ""))
            for row in ledger_rows
            if row.get("position_management_scope") == "longbridge_account_exit_only"
        ],
        "new_exit_signal_event_count": len(exit_events),
        "deferred_non_stop_exit_event_count": len(deferred_exit_events),
        "stop_loss_events_bypass_run_cap": config.stop_loss_events_bypass_run_cap,
        # The SDK runtime consumes these in memory so an exit does not wait
        # for another file-scan cycle before reaching the paper executor.
        "emitted_exit_signal_events": exit_events,
        "blocked_by_reason": count_statuses(ledger_rows),
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "inputs": {
            "account_state": project_path(config.account_state_path),
            "market_events": project_path(config.market_events_path),
            "realtime_execution_ledger": project_path(config.realtime_execution_ledger_path),
            "fill_attribution": project_path(config.fill_attribution_path),
            "local_simulation_ledger": "",
        },
        "outputs": {
            "signal_events": project_path(config.realtime_signal_events_path),
            "summary": project_path(config.output_dir / SUMMARY_JSON),
            "ledger": project_path(config.output_dir / LEDGER_JSONL),
            "report": project_path(config.output_dir / REPORT_MD),
        },
        "plain_language_result": plain_language_result(len(exit_events), ledger_rows),
    }
    write_json(config.output_dir / SUMMARY_JSON, summary)
    (config.output_dir / REPORT_MD).write_text(render_report(summary, ledger_rows), encoding="utf-8")
    return summary


def fill_attributed_open_exposure_by_bucket_symbol(
    fill_attribution: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Return actual unclosed fill cost by virtual bucket and symbol."""
    exposure: dict[str, dict[str, Decimal]] = {}
    for row in fill_attribution.get("batches", []):
        if not isinstance(row, dict):
            continue
        remaining_quantity = decimal(row.get("remaining_quantity", "0"))
        open_price = decimal(row.get("open_price", "0"))
        bucket = str(row.get("capital_bucket") or "")
        symbol = str(row.get("symbol") or "").upper().replace(".US", "")
        if not bucket or not symbol or remaining_quantity <= ZERO or open_price <= ZERO:
            continue
        bucket_rows = exposure.setdefault(bucket, {})
        bucket_rows[symbol] = (
            bucket_rows.get(symbol, ZERO) + (remaining_quantity * open_price)
        )
    return {
        bucket: {
            symbol: fmt_money(value)
            for symbol, value in sorted(symbols.items())
        }
        for bucket, symbols in sorted(exposure.items())
    }


def exit_event_priority(event: dict[str, Any]) -> tuple[int, str, str]:
    reason = str(event.get("exit_reason") or event.get("position_action") or "")
    return (
        0 if reason == "stop_loss" else 1,
        str(event.get("created_at") or ""),
        str(event.get("signal_id") or ""),
    )


def select_exit_events(
    candidates: list[dict[str, Any]],
    *,
    max_non_stop_events: int,
    stop_loss_events_bypass_run_cap: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Never make a verified stop loss wait behind an arbitrary batch cap."""
    ordered = sorted(candidates, key=exit_event_priority)
    if not stop_loss_events_bypass_run_cap:
        return ordered[:max_non_stop_events], ordered[max_non_stop_events:]
    stop_losses = [row for row in ordered if str(row.get("exit_reason") or "") == "stop_loss"]
    non_stops = [row for row in ordered if str(row.get("exit_reason") or "") != "stop_loss"]
    return stop_losses + non_stops[:max_non_stop_events], non_stops[max_non_stop_events:]


def evaluate_position(
    config: RealtimePositionManagerConfig,
    position: dict[str, Any],
    metadata: dict[str, Any],
    latest_price: Decimal,
    generated_at: str,
    existing_signal_ids: set[str],
    recent_exit_attempts: set[tuple[str, str, str, str]],
    retriable_exit_signal_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    symbol = str(position["symbol"])
    quantity = decimal(position.get("quantity", "0"))
    available_quantity = decimal(position.get("available", quantity))
    stop_price = decimal(metadata.get("stop_price", "0"))
    target_price = decimal(metadata.get("target_price", "0"))
    runtime_id = str(metadata.get("runtime_id", ""))
    strategy_id = str(metadata.get("strategy_id", ""))
    position_direction = str(metadata.get("position_direction") or "long").lower()
    source_open_order_id = str(
        metadata.get("short_open_order_id")
        or metadata.get("open_order_id")
        or metadata.get("order_id")
        or ""
    )
    source_open_trade_id = str(metadata.get("source_open_trade_id") or metadata.get("trade_id") or "")
    cost_price = position_cost_price(position)
    latest_for_pnl = latest_price if latest_price > ZERO else decimal(position.get("current_price", position.get("last_price", "0")))
    unrealized_pnl = (
        ((cost_price - latest_for_pnl) if position_direction == "short" else (latest_for_pnl - cost_price)) * quantity
        if latest_for_pnl > ZERO and cost_price > ZERO
        else ZERO
    )
    status = "hold_no_exit_trigger"
    management_scope = "m15_realtime_managed"
    management_note = "本轮 M15 实时链路管理的长桥模拟账户持仓。"
    exit_reason = ""
    current_market_date = parse_signal_time(generated_at)
    current_market_date_text = (
        current_market_date.astimezone(NEW_YORK).date().isoformat()
        if current_market_date is not None
        else ""
    )
    open_market_date = str(metadata.get("open_market_date") or "")
    if metadata.get("attribution_mismatch"):
        status = "fill_attribution_mismatch_frozen"
        management_scope = "longbridge_account_attribution_frozen"
        management_note = "长桥净持仓与精确成交批次数量不一致；已冻结自动策略退出和新开仓，等待成交对账修复。"
    elif not metadata:
        if config.manage_untracked_positions_for_exit:
            runtime_id = "M15-LONGBRIDGE-EXIT-ONLY"
            strategy_id = "M15-LONGBRIDGE-EXIT-ONLY"
            management_scope = "longbridge_account_exit_only"
            management_note = "长桥账户已有持仓，未迁移成本地策略；只接管退出，不参与新开仓或加仓。"
            basis_price = cost_price if cost_price > ZERO else latest_for_pnl
            if basis_price > ZERO:
                stop_price = basis_price * (Decimal("1") - config.untracked_stop_loss_percent / Decimal("100"))
                target_price = basis_price * (Decimal("1") + config.untracked_take_profit_percent / Decimal("100"))
                status = "exit_only_hold_no_exit_trigger"
                if latest_price <= ZERO:
                    status = "missing_latest_price"
                elif latest_price <= stop_price:
                    status = "exit_signal_created"
                    exit_reason = "stop_loss"
                elif latest_price >= target_price:
                    status = "exit_signal_created"
                    exit_reason = "take_profit"
            else:
                status = "missing_cost_basis_for_exit_only"
        else:
            status = "legacy_unmanaged_longbridge_position"
            management_scope = "longbridge_account_unmanaged"
            management_note = "长桥模拟账户已有持仓，但只接管退出配置关闭；不参与新开仓或加仓，需人工复核退出计划。"
    elif (
        position_direction == "long"
        and config.test_epoch_id.startswith("m15-sdk-formal-")
        and (not source_open_order_id or not source_open_trade_id)
    ):
        status = "missing_exact_open_fill_identity"
    elif position_direction == "short" and not source_open_order_id:
        status = "missing_short_open_order_identity"
    elif latest_price <= ZERO:
        status = "missing_latest_price"
    elif stop_price <= ZERO or target_price <= ZERO:
        status = "missing_stop_or_target_metadata"
    elif (
        runtime_id == PA002_REPAIRED_RUNTIME_ID
        and position_direction == "long"
        and open_market_date
        and current_market_date_text > open_market_date
    ):
        status = "exit_signal_created"
        exit_reason = "next_market_day_timeout"
    elif position_direction == "short":
        if latest_price >= stop_price:
            status = "exit_signal_created"
            exit_reason = "stop_loss"
        elif latest_price <= target_price:
            status = "exit_signal_created"
            exit_reason = "take_profit"
    elif latest_price <= stop_price:
        status = "exit_signal_created"
        exit_reason = "stop_loss"
    elif latest_price >= target_price:
        status = "exit_signal_created"
        exit_reason = "take_profit"
    signal_id = ""
    exit_retry_attempt = 1
    exit_retry_of_signal_id = ""
    event: dict[str, Any] | None = None
    if status == "exit_signal_created":
        base_signal_id = deterministic_exit_signal_id(
            symbol=symbol,
            runtime_id=runtime_id,
            exit_reason=exit_reason,
            source_open_signal_id=str(metadata.get("signal_id", "")),
            source_open_order_id=source_open_order_id,
            source_open_trade_id=source_open_trade_id,
        )
        signal_id = base_signal_id
        exit_attempt_key = (
            symbol,
            position_direction,
            exit_reason,
            f"{source_open_order_id}:{source_open_trade_id}",
        )
        if available_quantity <= ZERO:
            status = "position_not_available_for_exit"
        elif exit_attempt_key in recent_exit_attempts:
            status = "recent_exit_attempt_cooldown"
        else:
            retry_signal_id, retry_attempt = next_exit_retry_signal_id(
                base_signal_id,
                existing_signal_ids,
                retriable_exit_signal_ids,
            )
            if retry_signal_id:
                signal_id = retry_signal_id
                exit_retry_attempt = retry_attempt
                exit_retry_of_signal_id = base_signal_id
            elif signal_id in existing_signal_ids:
                status = "duplicate_exit_signal_event"
            if status == "exit_signal_created":
                exit_quantity = min(quantity, available_quantity)
                if position_direction == "short":
                    exit_limit_price = latest_price * (
                        Decimal("1") + config.short_cover_limit_premium_percent / Decimal("100")
                    )
                    exit_limit_price_source = "current_price_plus_short_cover_buffer"
                else:
                    exit_limit_price = latest_price * (
                        Decimal("1") - config.long_exit_limit_discount_percent / Decimal("100")
                    )
                    exit_limit_price_source = "current_price_minus_long_exit_buffer"
                event = {
                    "signal_id": signal_id,
                    "created_at": generated_at,
                    "runtime_id": runtime_id,
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "timeframe": str(metadata.get("timeframe", "")),
                    "direction": position_direction,
                    "side": "buy" if position_direction == "short" else "sell",
                    "position_action": (
                        "close_short"
                        if position_direction == "short"
                        else ("close_long" if exit_reason == "next_market_day_timeout" else exit_reason)
                    ),
                    "exit_reason": exit_reason,
                    "order_type": "limit",
                    "limit_price": fmt_money(exit_limit_price),
                    "current_price": fmt_money(latest_price),
                    "quantity": fmt_decimal(exit_quantity),
                    "notional": fmt_money(exit_quantity * latest_price),
                    "risk_amount": "0.00",
                    "net_profit_after_fees_at_target": "0.01",
                    "source_market_event_id": str(metadata.get("source_market_event_id", "")),
                    "source_open_signal_id": str(metadata.get("signal_id", "")),
                    "source_open_order_id": source_open_order_id,
                    "source_open_trade_id": source_open_trade_id,
                    "source_open_remaining_quantity": fmt_decimal(quantity),
                    "exit_retry_attempt": exit_retry_attempt,
                    "exit_retry_of_signal_id": exit_retry_of_signal_id,
                    "short_structure_low": str(metadata.get("short_structure_low") or ""),
                    "local_simulation_source": False,
                    "longbridge_position_exit_source": True,
                    "longbridge_untracked_exit_only": management_scope == "longbridge_account_exit_only",
                    "test_epoch_id": config.test_epoch_id,
                    "open_market_date": open_market_date,
                    "exit_limit_price_source": exit_limit_price_source,
                }
    row = {
        "stage": config.stage,
        "symbol": symbol,
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "position_direction": position_direction,
        "quantity": fmt_decimal(quantity),
        "available_quantity": fmt_decimal(available_quantity),
        "account_symbol_quantity": str(position.get("account_symbol_quantity") or ""),
        "account_symbol_available_quantity": str(position.get("account_symbol_available_quantity") or ""),
        "virtual_position_quantity": str(metadata.get("virtual_position_quantity") or position.get("virtual_position_quantity") or ""),
        "virtual_position_slice_quantity": str(metadata.get("virtual_position_slice_quantity") or ""),
        "virtual_position_slice_available": str(metadata.get("virtual_position_slice_available") or ""),
        "virtual_position_capped_by_account": bool(position.get("virtual_position_capped_by_account", False)),
        "cost_price": fmt_money(cost_price) if cost_price > ZERO else "",
        "unrealized_pnl": fmt_money(unrealized_pnl) if latest_for_pnl > ZERO and cost_price > ZERO else "",
        "latest_price": fmt_money(latest_price) if latest_price > ZERO else "",
        "stop_price": fmt_money(stop_price) if stop_price > ZERO else "",
        "target_price": fmt_money(target_price) if target_price > ZERO else "",
        "manager_status": status,
        "position_management_scope": management_scope,
        "management_note": management_note,
        "exit_reason": exit_reason,
        "exit_signal_id": signal_id,
        "exit_retry_attempt": exit_retry_attempt,
        "exit_retry_of_signal_id": exit_retry_of_signal_id,
        "exit_allowed": management_scope in {"m15_realtime_managed", "longbridge_account_exit_only"},
        "exit_only_takeover": management_scope == "longbridge_account_exit_only",
        "source_open_order_id": source_open_order_id,
        "source_open_trade_id": source_open_trade_id,
        "local_simulation_ignored": True,
    }
    return row, event


def rows_for_current_test_epoch(
    rows: list[dict[str, Any]],
    test_epoch_id: str,
    test_started_at: str,
) -> list[dict[str, Any]]:
    """Exclude prior-test attribution while preserving legacy standalone use."""
    if not test_epoch_id:
        return rows
    started_at = parse_signal_time(test_started_at)
    current: list[dict[str, Any]] = []
    for row in rows:
        row_epoch = str(row.get("test_epoch_id") or "")
        if row_epoch:
            if row_epoch == test_epoch_id:
                current.append(row)
            continue
        row_at = parse_signal_time(
            row.get("submitted_at") or row.get("processed_at") or row.get("created_at")
        )
        if started_at is not None and row_at is not None and row_at >= started_at:
            current.append(row)
    return current


def merge_active_epoch_rows(*row_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine active long/short epoch rows without duplicating shared rows."""
    merged: list[dict[str, Any]] = []
    seen: set[int] = set()
    for rows in row_groups:
        for row in rows:
            identity = id(row)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(row)
    return merged


def account_positions(account_state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_positions = account_state.get("positions")
    if not isinstance(raw_positions, list):
        return []
    positions: list[dict[str, Any]] = []
    for row in raw_positions:
        if not isinstance(row, dict):
            continue
        if is_short_position_row(row):
            continue
        symbol = base_symbol(str(row.get("symbol", "")))
        quantity = decimal(row.get("quantity", row.get("qty", "0")))
        if symbol and quantity > ZERO:
            positions.append({**row, "symbol": symbol, "quantity": fmt_decimal(quantity)})
    return positions


def position_cost_price(position: dict[str, Any]) -> Decimal:
    for key in (
        "cost_price",
        "average_cost",
        "avg_cost",
        "average_price",
        "avg_price",
        "cost",
    ):
        price = decimal(position.get(key, "0"))
        if price > ZERO:
            return price
    quantity = decimal(position.get("quantity", position.get("qty", "0")))
    cost_amount = decimal(position.get("cost_amount", position.get("invest_cost", "0")))
    if quantity > ZERO and cost_amount > ZERO:
        return cost_amount / quantity
    return ZERO


def latest_price_by_symbol(market_events: list[dict[str, Any]]) -> dict[str, Decimal]:
    latest: dict[str, tuple[str, Decimal]] = {}
    for event in market_events:
        symbol = base_symbol(str(event.get("symbol", "")))
        price = decimal(event.get("close", event.get("last_price", "")))
        event_time = str(event.get("event_time") or event.get("received_at") or "")
        if not symbol or price <= ZERO:
            continue
        if symbol not in latest or event_time >= latest[symbol][0]:
            latest[symbol] = (event_time, price)
    return {symbol: value[1] for symbol, value in latest.items()}


def refresh_fill_attribution_state(
    config: RealtimePositionManagerConfig,
    account_state: dict[str, Any],
    execution_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Increment the exact-fill lot ledger from current broker facts.

    The local execution ledger supplies identity metadata only. Quantity and
    price facts always come from Longbridge executions.
    """
    runtime_existing = read_json(config.fill_attribution_path)
    canonical_existing = read_json(config.canonical_fill_attribution_path)
    existing, baseline_source = preferred_fill_attribution_baseline(
        runtime_existing,
        canonical_existing,
    )
    orders: list[dict[str, Any]] = []
    seen_orders: set[str] = set()
    for key in ("historical_orders", "orders"):
        for row in account_state.get(key, []) if isinstance(account_state.get(key), list) else []:
            if not isinstance(row, dict):
                continue
            order_id = str(row.get("order_id") or row.get("id") or "")
            if order_id and order_id not in seen_orders:
                orders.append(dict(row))
                seen_orders.add(order_id)
    executions: list[dict[str, Any]] = []
    seen_trades: set[tuple[str, str]] = set()
    for key in ("historical_executions", "executions"):
        for row in account_state.get(key, []) if isinstance(account_state.get(key), list) else []:
            if not isinstance(row, dict):
                continue
            identity = (str(row.get("order_id") or ""), str(row.get("trade_id") or ""))
            if all(identity) and identity not in seen_trades:
                executions.append(dict(row))
                seen_trades.add(identity)
    broker_positions: dict[str, Decimal] = {}
    for row in account_state.get("positions", []) if isinstance(account_state.get("positions"), list) else []:
        if not isinstance(row, dict):
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        quantity = decimal(row.get("quantity", row.get("qty", "0")))
        if is_short_position_row(row):
            quantity = -quantity
        if symbol:
            broker_positions[symbol] = broker_positions.get(symbol, ZERO) + quantity
    exact_local_rows = [
        dict(row)
        for row in execution_rows
        if ledger_row_order_id(row)
        and str(row.get("test_epoch_id") or "").startswith(
            ("m15-sdk-formal-", "m15-short-single-strategy-")
        )
    ]
    eligible_order_ids = {
        ledger_row_order_id(row)
        for row in exact_local_rows
        if ledger_row_order_id(row)
    }
    broker_fills = broker_fill_rows_from_orders_and_executions(orders, executions)
    broker_fills = [
        row
        for row in broker_fills
        if str(row.get("order_id") or "") in eligible_order_ids
    ]
    payload = rebuild_fill_attribution(
        exact_local_rows,
        broker_fills,
        broker_net_positions=broker_positions,
        existing_state=existing,
    )
    payload = apply_account_reconciliation_adjustments(
        payload,
        read_json(config.output_dir / ACCOUNT_RECONCILIATION_ADJUSTMENTS),
        broker_net_positions=broker_positions,
    )
    enrich_fill_attribution_batch_metadata(payload, exact_local_rows)
    payload.update(
        {
            "generated_at": str(account_state.get("generated_at") or ""),
            "paper_simulated_only": True,
            "live_execution": False,
            "real_money_actions": False,
            "baseline_source": baseline_source,
        }
    )
    write_json(config.fill_attribution_path, payload)
    return payload


def cached_or_refreshed_fill_attribution(
    config: RealtimePositionManagerConfig,
    account_state: dict[str, Any],
    execution_rows: list[dict[str, Any]],
    state_cache: dict[str, Any] | None,
) -> dict[str, Any]:
    signature = fill_attribution_account_signature(account_state, execution_rows)
    if (
        state_cache is not None
        and state_cache.get("signature") == signature
        and isinstance(state_cache.get("payload"), dict)
    ):
        return dict(state_cache["payload"])
    payload = refresh_fill_attribution_state(config, account_state, execution_rows)
    if state_cache is not None:
        state_cache.clear()
        state_cache.update({"signature": signature, "payload": payload})
    return payload


def fill_attribution_account_signature(
    account_state: dict[str, Any],
    execution_rows: list[dict[str, Any]],
) -> str:
    broker_facts: list[tuple[str, ...]] = []
    for key in ("historical_orders", "orders"):
        for row in account_state.get(key, []) if isinstance(account_state.get(key), list) else []:
            if not isinstance(row, dict):
                continue
            broker_facts.append(
                (
                    "order",
                    str(row.get("order_id") or row.get("id") or ""),
                    str(row.get("status") or row.get("order_status") or ""),
                    str(row.get("executed_quantity") or row.get("filled_quantity") or ""),
                    str(row.get("executed_price") or row.get("average_price") or ""),
                )
            )
    for key in ("historical_executions", "executions"):
        for row in account_state.get(key, []) if isinstance(account_state.get(key), list) else []:
            if not isinstance(row, dict):
                continue
            broker_facts.append(
                (
                    "execution",
                    str(row.get("order_id") or ""),
                    str(row.get("trade_id") or ""),
                    str(row.get("quantity") or row.get("filled_quantity") or ""),
                    str(row.get("price") or row.get("filled_price") or ""),
                )
            )
    for row in account_state.get("positions", []) if isinstance(account_state.get("positions"), list) else []:
        if not isinstance(row, dict):
            continue
        broker_facts.append(
            (
                "position",
                base_symbol(str(row.get("symbol") or "")),
                str(row.get("quantity") or row.get("qty") or ""),
                str(
                    row.get("available_quantity")
                    or row.get("available_qty")
                    or row.get("available")
                    or ""
                ),
            )
        )
    local_order_facts = sorted(
        (
            ledger_row_order_id(row),
            str(row.get("test_epoch_id") or ""),
            str(row.get("capital_bucket") or ""),
            str(row.get("runtime_id") or ""),
            str(row.get("strategy_id") or ""),
            str(row.get("signal_id") or ""),
            str(row.get("stop_price") or ""),
            str(row.get("target_price") or ""),
        )
        for row in execution_rows
        if ledger_row_order_id(row)
    )
    encoded = json.dumps(
        {
            "broker_facts": sorted(broker_facts),
            "local_order_facts": local_order_facts,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def preferred_fill_attribution_baseline(
    runtime_state: dict[str, Any],
    canonical_state: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Use the most complete exact-fill state before applying live increments."""

    def score(state: dict[str, Any]) -> tuple[int, int, int]:
        summary = state.get("summary") if isinstance(state.get("summary"), dict) else {}
        return (
            int(summary.get("matched_event_count") or 0),
            -int(summary.get("anomaly_count") or 0),
            int(summary.get("open_batch_count") or 0),
        )

    if canonical_state and score(canonical_state) > score(runtime_state):
        return canonical_state, "canonical_full_history"
    return runtime_state, "runtime_incremental"


def enrich_fill_attribution_batch_metadata(
    attribution: dict[str, Any],
    local_rows: list[dict[str, Any]],
) -> None:
    """Restore stop/target facts omitted by the slow reconciliation view."""
    local_by_order_id = {
        ledger_row_order_id(row): row
        for row in local_rows
        if ledger_row_order_id(row)
    }
    metadata_keys = (
        "strategy_id",
        "signal_id",
        "timeframe",
        "stop_price",
        "target_price",
        "source_market_event_id",
        "created_at",
        "submitted_at",
        "position_action",
        "repair_rule_id",
        "source_breakout_entry_price",
        "latest_confirms_entry",
        "next_market_day_timeout",
        "close_position",
        "volume_ratio",
        "market_confirmation_status",
        "quality_score",
    )
    for batch in attribution.get("batches", []):
        if not isinstance(batch, dict):
            continue
        local = local_by_order_id.get(str(batch.get("open_order_id") or ""))
        if not local:
            continue
        metadata = dict(batch.get("metadata") or {})
        for key in metadata_keys:
            value = local.get(key)
            if value not in (None, ""):
                metadata[key] = value
        batch["metadata"] = metadata


def fill_attributed_long_position_slices(
    account_state: dict[str, Any],
    fill_attribution: dict[str, Any],
    test_epoch_id: str,
    include_untracked_exit_only: bool,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Create strategy slices only from exact Longbridge fill batches."""
    checks = {
        base_symbol(str(row.get("symbol") or "")): bool(row.get("matches_broker_net"))
        for row in fill_attribution.get("symbol_checks", [])
        if isinstance(row, dict)
    }
    batches_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in fill_attribution.get("batches", []):
        if not isinstance(row, dict):
            continue
        if str(row.get("test_epoch_id") or "") != test_epoch_id or str(row.get("direction") or "") != "long":
            continue
        if decimal(row.get("remaining_quantity", "0")) <= ZERO:
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        if symbol:
            batches_by_symbol.setdefault(symbol, []).append(dict(row))
    slices: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for account_position in account_positions(account_state):
        symbol = str(account_position["symbol"])
        account_quantity = decimal(account_position.get("quantity", "0"))
        account_available = decimal(account_position.get("available", account_quantity))
        symbol_batches = sorted(
            batches_by_symbol.get(symbol, []),
            key=lambda row: (str(row.get("open_order_id") or ""), str(row.get("trade_id") or "")),
        )
        if checks.get(symbol) is False:
            slices.append(
                (
                    {
                        **account_position,
                        "account_symbol_quantity": fmt_decimal(account_quantity),
                        "account_symbol_available_quantity": fmt_decimal(account_available),
                    },
                    {"attribution_mismatch": True, "position_direction": "long"},
                )
            )
            continue
        remaining_available = account_available
        attributed_quantity = ZERO
        for batch in symbol_batches:
            quantity = decimal(batch.get("remaining_quantity", "0"))
            if quantity <= ZERO:
                continue
            available = min(quantity, remaining_available)
            metadata = dict(batch.get("metadata") or {})
            metadata.update(
                {
                    "capital_bucket": str(batch.get("capital_bucket") or ""),
                    "runtime_id": str(batch.get("runtime_id") or ""),
                    "position_direction": "long",
                    "open_order_id": str(batch.get("open_order_id") or ""),
                    "source_open_trade_id": str(batch.get("trade_id") or ""),
                    "open_market_date": str(batch.get("open_market_date") or ""),
                    "virtual_position_quantity": fmt_decimal(quantity),
                    "virtual_position_slice_quantity": fmt_decimal(quantity),
                    "virtual_position_slice_available": fmt_decimal(available),
                }
            )
            slices.append(
                (
                    {
                        **account_position,
                        "quantity": fmt_decimal(quantity),
                        "available": fmt_decimal(available),
                        "cost_price": str(batch.get("open_price") or account_position.get("cost_price") or ""),
                        "account_symbol_quantity": fmt_decimal(account_quantity),
                        "account_symbol_available_quantity": fmt_decimal(account_available),
                        "virtual_position_quantity": fmt_decimal(quantity),
                        "virtual_position_capped_by_account": False,
                    },
                    metadata,
                )
            )
            attributed_quantity += quantity
            remaining_available = max(remaining_available - available, ZERO)
        if include_untracked_exit_only and account_quantity > attributed_quantity:
            untracked = account_quantity - attributed_quantity
            slices.append(
                (
                    {
                        **account_position,
                        "quantity": fmt_decimal(untracked),
                        "available": fmt_decimal(min(untracked, remaining_available)),
                        "account_symbol_quantity": fmt_decimal(account_quantity),
                        "account_symbol_available_quantity": fmt_decimal(account_available),
                    },
                    {},
                )
            )
    return slices


def confirmed_short_position_slices(
    account_state: dict[str, Any],
    execution_rows: list[dict[str, Any]],
    config: RealtimePositionManagerConfig,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Build cover-only slices from Longbridge-confirmed short fills.

    A local submitted sell is deliberately not enough. Both a confirmed M15
    opening sell and an explicit short position in the Longbridge account are
    required before the manager can emit a buy-to-cover signal.
    """
    if not config.paper_short_testing_enabled:
        return []
    order_by_id = latest_account_orders_by_id(account_state)
    broker_short_quantities = account_short_position_quantities(account_state)
    lots: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in sorted(execution_rows, key=lambda item: str(item.get("submitted_at") or item.get("processed_at") or "")):
        if row.get("submission_status") != "submitted":
            continue
        if str(row.get("test_epoch_id") or "") != config.short_test_epoch_id:
            continue
        runtime_id = str(row.get("runtime_id") or "")
        if runtime_id not in set(config.paper_short_runtime_ids):
            continue
        position_action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        side = normalize_side(row.get("side"), position_action=position_action)
        symbol = base_symbol(str(row.get("symbol") or ""))
        bucket = str(row.get("capital_bucket") or "")
        order_id = ledger_row_order_id(row)
        account_order = broker_order_for_ledger_row(row, order_by_id)
        if not symbol or not bucket or not order_has_confirmed_fill(account_order):
            continue
        quantity = confirmed_order_quantity(
            account_order,
            decimal(row.get("submitted_quantity", row.get("quantity", "0"))),
        )
        if quantity <= ZERO:
            continue
        key = (bucket, runtime_id, symbol)
        if side == "sell_short" or position_action == "open_short":
            lots.setdefault(key, []).append(
                {
                    "quantity": quantity,
                    "cost_price": decimal(
                        account_order.get("executed_price", account_order.get("avg_price", row.get("limit_price", "0")))
                    ),
                    "metadata": {**row, "position_direction": "short", "short_open_order_id": order_id},
                }
            )
        elif position_action == "close_short":
            source_open_order_id = str(row.get("source_open_order_id") or "")
            if not source_open_order_id:
                continue
            remaining = quantity
            for lot in lots.get(key, []):
                if remaining <= ZERO:
                    break
                lot_open_order_id = str(lot.get("metadata", {}).get("short_open_order_id") or "")
                if lot_open_order_id != source_open_order_id:
                    continue
                matched = min(remaining, lot["quantity"])
                lot["quantity"] -= matched
                remaining -= matched

    remaining_broker_quantity = dict(broker_short_quantities)
    slices: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for (_bucket, _runtime_id, symbol), symbol_lots in lots.items():
        broker_available = remaining_broker_quantity.get(symbol, ZERO)
        if broker_available <= ZERO:
            continue
        for lot in symbol_lots:
            quantity = min(lot["quantity"], broker_available)
            if quantity <= ZERO:
                continue
            cost_price = decimal(lot.get("cost_price", "0"))
            metadata = dict(lot.get("metadata", {}))
            metadata["virtual_position_quantity"] = fmt_decimal(lot["quantity"])
            metadata["virtual_position_slice_quantity"] = fmt_decimal(quantity)
            metadata["virtual_position_slice_available"] = fmt_decimal(quantity)
            slices.append(
                (
                    {
                        "symbol": symbol,
                        "quantity": fmt_decimal(quantity),
                        "available": fmt_decimal(quantity),
                        "cost_price": fmt_money(cost_price) if cost_price > ZERO else "",
                        "account_symbol_quantity": fmt_decimal(broker_short_quantities.get(symbol, ZERO)),
                        "account_symbol_available_quantity": fmt_decimal(broker_available),
                        "virtual_position_quantity": fmt_decimal(lot["quantity"]),
                        "virtual_position_capped_by_account": lot["quantity"] > quantity,
                    },
                    metadata,
                )
            )
            broker_available -= quantity
            remaining_broker_quantity[symbol] = broker_available
    return slices


def account_position_slices(
    account_state: dict[str, Any],
    execution_rows: list[dict[str, Any]],
    include_untracked_exit_only: bool,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    grouped = submitted_open_position_groups(execution_rows)
    slices: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for account_position in account_positions(account_state):
        symbol = str(account_position["symbol"])
        remaining_quantity = decimal(account_position.get("quantity", "0"))
        remaining_available = decimal(account_position.get("available", remaining_quantity))
        symbol_groups = [
            group
            for group in grouped.values()
            if group.get("symbol") == symbol and decimal(group.get("open_quantity", "0")) > ZERO
        ]
        symbol_groups.sort(key=lambda row: str(row.get("last_buy_at") or row.get("first_buy_at") or ""))
        for group in symbol_groups:
            if remaining_quantity <= ZERO:
                break
            group_quantity = decimal(group.get("open_quantity", "0"))
            slice_quantity = min(group_quantity, remaining_quantity)
            if slice_quantity <= ZERO:
                continue
            slice_available = min(slice_quantity, remaining_available)
            position = {
                **account_position,
                "quantity": fmt_decimal(slice_quantity),
                "available": fmt_decimal(slice_available),
                "account_symbol_quantity": fmt_decimal(decimal(account_position.get("quantity", "0"))),
                "account_symbol_available_quantity": fmt_decimal(decimal(account_position.get("available", remaining_quantity))),
                "virtual_position_quantity": fmt_decimal(group_quantity),
                "virtual_position_capped_by_account": group_quantity > slice_quantity,
            }
            metadata = dict(group.get("metadata", {}))
            metadata["virtual_position_quantity"] = fmt_decimal(group_quantity)
            metadata["virtual_position_slice_quantity"] = fmt_decimal(slice_quantity)
            metadata["virtual_position_slice_available"] = fmt_decimal(slice_available)
            slices.append((position, metadata))
            remaining_quantity -= slice_quantity
            remaining_available = max(remaining_available - slice_available, ZERO)
        if include_untracked_exit_only and remaining_quantity > ZERO:
            position = {
                **account_position,
                "quantity": fmt_decimal(remaining_quantity),
                "available": fmt_decimal(min(remaining_quantity, remaining_available)),
                "account_symbol_quantity": fmt_decimal(decimal(account_position.get("quantity", "0"))),
                "account_symbol_available_quantity": fmt_decimal(decimal(account_position.get("available", remaining_quantity))),
                "virtual_position_quantity": "",
                "virtual_position_capped_by_account": False,
            }
            slices.append((position, {}))
    return slices


def submitted_open_position_groups(execution_rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in execution_rows:
        if row.get("submission_status") != "submitted":
            continue
        symbol = base_symbol(str(row.get("symbol", "")))
        if not symbol:
            continue
        side = str(row.get("side", "")).lower()
        quantity = decimal(row.get("submitted_quantity", row.get("quantity", "0")))
        if quantity <= ZERO or side not in {"buy", "sell"}:
            continue
        capital_bucket = str(row.get("capital_bucket") or "")
        runtime_id = str(row.get("runtime_id") or "")
        strategy_id = str(row.get("strategy_id") or "")
        key = (symbol, capital_bucket, runtime_id, strategy_id)
        group = groups.setdefault(
            key,
            {
                "symbol": symbol,
                "capital_bucket": capital_bucket,
                "runtime_id": runtime_id,
                "strategy_id": strategy_id,
                "open_quantity": "0",
                "first_buy_at": "",
                "last_buy_at": "",
                "metadata": {},
            },
        )
        open_quantity = decimal(group.get("open_quantity", "0"))
        if side == "buy":
            open_quantity += quantity
            if not group.get("first_buy_at"):
                group["first_buy_at"] = str(row.get("generated_at") or row.get("created_at") or "")
            group["last_buy_at"] = str(row.get("generated_at") or row.get("created_at") or "")
            group["metadata"] = row
        else:
            open_quantity -= quantity
        group["open_quantity"] = fmt_decimal(max(open_quantity, ZERO))
    return groups


def terminal_retriable_short_exit_signal_ids(
    execution_rows: list[dict[str, Any]],
    account_state: dict[str, Any],
) -> set[str]:
    """Return canceled/rejected/expired short-cover attempts eligible for one fresh retry.

    A fully filled cover remains non-retriable until the broker position snapshot
    has caught up.  This is intentionally limited to explicitly attributable
    paper-short lots; generic long exits keep their existing conservative flow.
    """
    order_by_id = latest_account_orders_by_id(account_state)
    latest_by_signal_id: dict[str, dict[str, Any]] = {}
    for row in execution_rows:
        signal_id = str(row.get("signal_id") or "")
        action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        if not signal_id or action != "close_short":
            continue
        latest_by_signal_id[signal_id] = row
    retriable: set[str] = set()
    for signal_id, row in latest_by_signal_id.items():
        if str(row.get("submission_status") or "") != "submitted":
            continue
        broker_order = broker_order_for_ledger_row(row, order_by_id)
        if not broker_order or not broker_order_is_terminal(broker_order):
            continue
        status = str(broker_order.get("status") or "").strip().lower().replace(" ", "_")
        if status not in {"filled", "executed", "done", "completed"}:
            retriable.add(signal_id)
    return retriable


def broker_failed_long_exit_signal_ids(
    execution_rows: list[dict[str, Any]],
    account_state: dict[str, Any],
) -> set[str]:
    """Retry only after a trustworthy broker snapshot proves no active order."""
    if account_state.get("orders_ok") is not True:
        return set()
    broker_orders = broker_order_rows(account_state)
    retriable: set[str] = set()
    for row in execution_rows:
        signal_id = str(row.get("signal_id") or "")
        action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        status = str(row.get("submission_status") or "")
        if not (
            signal_id
            and action in {"close_long", "exit_long", "stop_loss", "take_profit"}
            and status.startswith("broker_submit_failed:")
        ):
            continue
        client_request_id = str(row.get("client_request_id") or "")
        matching_orders = [
            order
            for order in broker_orders
            if broker_order_matches_request(
                order,
                signal_id=signal_id,
                client_request_id=client_request_id,
            )
        ]
        if matching_orders and any(
            not broker_order_is_terminal_without_fill(order)
            for order in matching_orders
        ):
            continue
        retriable.add(signal_id)
    return retriable


def broker_order_rows(account_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("open_orders", "orders", "historical_orders"):
        values = account_state.get(key)
        if not isinstance(values, list):
            continue
        for row in values:
            if not isinstance(row, dict):
                continue
            order_id = str(row.get("order_id") or "")
            identity = order_id or json.dumps(row, sort_keys=True, default=str)
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(row)
    return rows


def broker_order_matches_request(
    order: dict[str, Any],
    *,
    signal_id: str,
    client_request_id: str,
) -> bool:
    text = " ".join(
        str(order.get(key) or "")
        for key in ("remark", "note", "message", "client_request_id")
    )
    tokens = set(text.replace("|", " ").split())
    return bool(
        signal_id in tokens
        or (client_request_id and client_request_id in tokens)
    )


def broker_order_is_terminal_without_fill(order: dict[str, Any]) -> bool:
    status = (
        str(order.get("status") or "")
        .strip()
        .lower()
        .replace("orderstatus.", "")
        .replace(" ", "_")
    )
    executed_quantity = decimal(
        order.get("executed_quantity", order.get("filled_quantity", "0"))
    )
    return (
        status
        in {
            "canceled",
            "cancelled",
            "rejected",
            "expired",
            "withdrawn",
            "failed",
        }
        and executed_quantity <= ZERO
    )


def unprocessed_exit_signal_ids(
    signal_events: list[dict[str, Any]],
    execution_rows: list[dict[str, Any]],
) -> set[str]:
    """Allow a fresh intent when an exit event never reached the executor."""
    processed_ids = {
        str(row.get("signal_id") or "")
        for row in execution_rows
        if str(row.get("signal_id") or "")
    }
    retriable: set[str] = set()
    for row in signal_events:
        signal_id = str(row.get("signal_id") or "")
        action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        if (
            signal_id
            and signal_id not in processed_ids
            and action in {"close_long", "exit_long", "close_short", "stop_loss", "take_profit"}
        ):
            retriable.add(signal_id)
    return retriable


def next_exit_retry_signal_id(
    base_signal_id: str,
    existing_signal_ids: set[str],
    retriable_exit_signal_ids: set[str],
) -> tuple[str, int]:
    previous_ids: list[tuple[int, str]] = []
    for signal_id in existing_signal_ids:
        if signal_id == base_signal_id:
            previous_ids.append((1, signal_id))
            continue
        prefix = f"{base_signal_id}-retry-"
        if signal_id.startswith(prefix):
            suffix = signal_id.removeprefix(prefix)
            if suffix.isdigit() and int(suffix) >= 2:
                previous_ids.append((int(suffix), signal_id))
    if not previous_ids:
        return "", 1
    previous_ids.sort()
    last_attempt, last_signal_id = previous_ids[-1]
    if last_signal_id not in retriable_exit_signal_ids:
        return "", last_attempt
    next_attempt = last_attempt + 1
    return f"{base_signal_id}-retry-{next_attempt}", next_attempt


def recent_exit_attempt_keys(
    execution_rows: list[dict[str, Any]],
    now: datetime,
    cooldown_seconds: int,
    retriable_exit_signal_ids: set[str] | None = None,
) -> set[tuple[str, str, str, str]]:
    del retriable_exit_signal_ids
    attempts: set[tuple[str, str, str, str]] = set()
    for row in execution_rows:
        position_action = normalize_position_action(row.get("position_action") or row.get("exit_reason"))
        side = normalize_side(row.get("side"), position_action=position_action)
        if side not in {"sell", "buy"} or position_action not in {
            "close_long",
            "exit_long",
            "stop_loss",
            "take_profit",
            "close_short",
        }:
            continue
        status = str(row.get("submission_status") or "")
        if status == "blocked_not_submitted":
            continue
        if not status and not str(row.get("created_at") or ""):
            continue
        attempted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if attempted_at and (now - attempted_at).total_seconds() > cooldown_seconds:
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        exit_reason = str(row.get("exit_reason") or row.get("position_action") or "")
        direction = "short" if position_action == "close_short" else "long"
        if symbol and exit_reason:
            source_open_order_id = str(row.get("source_open_order_id") or "")
            source_open_trade_id = str(row.get("source_open_trade_id") or "")
            attempts.add(
                (
                    symbol,
                    direction,
                    exit_reason,
                    f"{source_open_order_id}:{source_open_trade_id}",
                )
            )
    return attempts


def deterministic_exit_signal_id(
    *,
    symbol: str,
    runtime_id: str,
    exit_reason: str,
    source_open_signal_id: str = "",
    source_open_order_id: str = "",
    source_open_trade_id: str = "",
    generated_at: str = "",
) -> str:
    del generated_at
    digest = sha256(
        f"{symbol}|{runtime_id}|{exit_reason}|{source_open_signal_id}|{source_open_order_id}|{source_open_trade_id}".encode("utf-8")
    ).hexdigest()[:16]
    return f"m15exit-{digest}"


def count_statuses(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("manager_status", ""))
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def plain_language_result(exit_count: int, rows: list[dict[str, Any]]) -> str:
    if exit_count:
        return f"长桥持仓退出管理生成 {exit_count} 条平仓信号；这些信号来自长桥账户持仓和实时行情，不来自本地模拟。"
    exit_only_symbols = [
        str(row.get("symbol", ""))
        for row in rows
        if row.get("position_management_scope") == "longbridge_account_exit_only"
    ]
    if exit_only_symbols:
        return (
            "长桥持仓退出管理已检查账户持仓；"
            f"{', '.join(exit_only_symbols)} 是非系统元数据持仓，已按只接管退出模式管理，不参与新开仓或加仓。"
        )
    unmanaged_symbols = [
        str(row.get("symbol", ""))
        for row in rows
        if row.get("position_management_scope") == "longbridge_account_unmanaged"
    ]
    if unmanaged_symbols:
        return (
            "长桥持仓退出管理已检查账户持仓；"
            f"{', '.join(unmanaged_symbols)} 是账户已有但非本轮 M15 开仓的持仓，当前未接管退出配置关闭，需人工复核退出计划。"
        )
    if rows:
        return "长桥持仓退出管理已检查账户持仓；当前没有触发止损或止盈。"
    return "长桥持仓退出管理已就绪；当前长桥账户没有可管理持仓。"


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 长桥模拟账户实时持仓退出管理",
        "",
        f"- 生成时间: `{summary['generated_at']}`",
        f"- 持仓数: `{summary['position_count']}`",
        f"- 系统管理持仓 / 只接管退出持仓 / 未接管退出持仓: `{summary['managed_position_count']} / {summary.get('exit_only_position_count', 0)} / {summary['unmanaged_position_count']}`",
        f"- 新平仓信号: `{summary['new_exit_signal_event_count']}`",
        f"- 结论: {summary['plain_language_result']}",
        "",
        "| 标的 | 运行单元 | 管理范围 | 状态 | 成本 | 当前价 | 浮盈亏 | 止损 | 目标 |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows[:30]:
        lines.append(
            f"| `{row.get('symbol', '')}` | `{row.get('runtime_id', '')}` | `{row.get('position_management_scope', '')}` | `{row.get('manager_status', '')}` | "
            f"`{row.get('cost_price', '')}` | `{row.get('latest_price', '')}` | `{row.get('unrealized_pnl', '')}` | `{row.get('stop_price', '')}` | `{row.get('target_price', '')}` |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 只看长桥模拟账户持仓、长桥实时行情和长桥实时执行记录。",
            "- 本地模拟平仓不触发长桥平仓。",
            "- 多头平仓只卖出已有多头；三条受限纸面短仓的平仓只能买入回补已确认的短仓，二者不会混用。",
            "",
        ]
    )
    return "\n".join(lines)


def base_symbol(symbol: str) -> str:
    return symbol.upper().split(".")[0]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(json_ready(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        "".join(json.dumps(json_ready(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.touch(exist_ok=True)
        return
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(json_ready(row), ensure_ascii=False, sort_keys=True)
                + "\n"
            )


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return fmt_decimal(value)
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value
