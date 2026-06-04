#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.m15_all_strategy_order_preview_lib import (
    MONEY,
    ZERO,
    apply_shared_account_caps,
    assert_no_legacy_profit_fields,
    broker_order_side,
    decimal,
    estimated_open_risk,
    fmt_decimal,
    fmt_money,
    infer_order_type,
    normalize_direction,
    order_blockers,
    order_preview_status,
    order_price,
    paper_order_quantity,
    preview_id,
    quote_source_blockers_for,
    risk_tier_policy,
    runtime_risk_tier,
    text_has_fallback_or_no_fetch,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_fast_signal_queue.json"
DEFAULT_DAILY_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
)
DEFAULT_M12_DIR = DEFAULT_DAILY_DIR / "m12_29_current_day_scan_dashboard"
DEFAULT_M14_DIR = DEFAULT_DAILY_DIR / "m14_strategy_challenge"
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_fast_signal_queue"
SUMMARY_JSON = "m15_longbridge_fast_signal_queue.json"
LEDGER_JSONL = "m15_longbridge_fast_signal_queue_ledger.jsonl"
REPORT_MD = "m15_longbridge_fast_signal_queue.md"
READY_STATUS = "local_order_preview_created_ready_after_user_approval"


@dataclass(frozen=True, slots=True)
class FastSignalQueueConfig:
    stage: str
    title: str
    dashboard_path: Path
    account_trade_ledger_path: Path
    paper_gate_path: Path
    strategy_decision_ledger_path: Path
    extended_session_monitor_path: Path
    output_dir: Path
    token_mode: str
    live_token_allowed: bool
    default_order_type: str
    allowed_order_types: tuple[str, ...]
    breakout_order_type: str
    max_signal_age_seconds: int
    max_signal_age_seconds_by_timeframe: dict[str, int]
    regular_hours_only: bool
    max_orders_per_day: int
    max_risk_per_order: Decimal
    quantity_policy: str
    paper_account_equity: Decimal
    max_total_exposure: Decimal
    min_cash_reserve: Decimal
    max_symbol_exposure: Decimal
    allow_fractional_shares: bool
    allow_short_selling: bool
    allow_options: bool
    risk_tiers: dict[str, dict[str, Decimal]]
    primary_runtime_ids: tuple[str, ...]
    market_timezone: str
    market_holidays: frozenset[date]
    independent_family_bonus: Decimal
    same_family_variant_bonus: Decimal
    max_same_family_variants: int
    max_confluence_multiplier: Decimal
    commission_per_share: Decimal
    commission_min: Decimal
    platform_fee_per_share: Decimal
    platform_fee_min: Decimal
    settlement_fee_per_share: Decimal
    sec_fee_rate: Decimal
    sec_fee_min: Decimal
    taf_per_share: Decimal
    taf_min: Decimal
    taf_max: Decimal
    premarket_against_signal_block_percent: Decimal
    premarket_overheat_wait_percent: Decimal
    hard_boundaries: dict[str, bool]

    def __post_init__(self) -> None:
        validate_config(self)


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> FastSignalQueueConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    queue = payload.get("longbridge_paper_fast_queue", {})
    account_model = queue.get("paper_account_model", {})
    fee_model = queue.get("fee_model", {})
    risk_tiers = {
        str(name): {
            str(key): decimal(value)
            for key, value in dict(settings).items()
            if key in {"max_strategy_exposure", "max_risk_per_order"}
        }
        for name, settings in dict(queue.get("risk_tiers", {})).items()
    }
    return FastSignalQueueConfig(
        stage=str(payload.get("stage", "M15.longbridge_fast_signal_queue")),
        title=str(payload.get("title", "长桥模拟账户快速新信号队列")),
        dashboard_path=resolve_repo_path(inputs.get("m12_32_dashboard", DEFAULT_M12_DIR / "m12_32_minute_readonly_dashboard_data.json")),
        account_trade_ledger_path=resolve_repo_path(
            inputs.get("m12_46_account_trade_ledger", DEFAULT_M12_DIR / "m12_46_account_trade_ledger.jsonl")
        ),
        paper_gate_path=resolve_repo_path(inputs.get("m14_paper_trial_gate", DEFAULT_M14_DIR / "m14_paper_trial_gate.json")),
        strategy_decision_ledger_path=resolve_repo_path(
            inputs.get("m14_strategy_decision_ledger", DEFAULT_M14_DIR / "m14_strategy_decision_ledger.jsonl")
        ),
        extended_session_monitor_path=resolve_repo_path(
            inputs.get("m12_48_extended_session_monitor", DEFAULT_M12_DIR / "m12_48_extended_session_monitor.json")
        ),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        token_mode=str(queue.get("token_mode", "paper")),
        live_token_allowed=bool(queue.get("live_token_allowed", False)),
        default_order_type=str(queue.get("default_order_type", "limit")),
        allowed_order_types=tuple(str(item) for item in queue.get("allowed_order_types", ["limit", "trigger_limit"])),
        breakout_order_type=str(queue.get("breakout_order_type", "trigger_limit")),
        max_signal_age_seconds=int(queue.get("max_signal_age_seconds", 900)),
        max_signal_age_seconds_by_timeframe={
            str(name): int(value)
            for name, value in dict(queue.get("max_signal_age_seconds_by_timeframe", {})).items()
        },
        regular_hours_only=bool(queue.get("regular_hours_only", True)),
        max_orders_per_day=int(queue.get("max_orders_per_day", 6)),
        max_risk_per_order=decimal(queue.get("max_risk_per_order", "20")),
        quantity_policy=str(queue.get("quantity_policy", "integer_floor_no_fractional")),
        paper_account_equity=decimal(account_model.get("equity", "10000")),
        max_total_exposure=decimal(account_model.get("max_total_exposure", "6000")),
        min_cash_reserve=decimal(account_model.get("min_cash_reserve", "4000")),
        max_symbol_exposure=decimal(account_model.get("max_symbol_exposure", "1500")),
        allow_fractional_shares=bool(account_model.get("allow_fractional_shares", False)),
        allow_short_selling=bool(account_model.get("allow_short_selling", False)),
        allow_options=bool(account_model.get("allow_options", False)),
        risk_tiers=risk_tiers,
        primary_runtime_ids=tuple(str(item) for item in queue.get("primary_runtime_ids", ["M10-PA-004-long-1d"])),
        market_timezone=str(queue.get("market_timezone", "America/New_York")),
        market_holidays=parse_holidays(queue.get("market_holidays", [])),
        independent_family_bonus=decimal(queue.get("independent_family_bonus", "0.50")),
        same_family_variant_bonus=decimal(queue.get("same_family_variant_bonus", "0.25")),
        max_same_family_variants=int(queue.get("max_same_family_variants", 2)),
        max_confluence_multiplier=decimal(queue.get("max_confluence_multiplier", "1.75")),
        commission_per_share=decimal(fee_model.get("commission_per_share", "0.0049")),
        commission_min=decimal(fee_model.get("commission_min", "0.99")),
        platform_fee_per_share=decimal(fee_model.get("platform_fee_per_share", "0.005")),
        platform_fee_min=decimal(fee_model.get("platform_fee_min", "1.00")),
        settlement_fee_per_share=decimal(fee_model.get("settlement_fee_per_share", "0.003")),
        sec_fee_rate=decimal(fee_model.get("sec_fee_rate", "0.0000229")),
        sec_fee_min=decimal(fee_model.get("sec_fee_min", "0.01")),
        taf_per_share=decimal(fee_model.get("taf_per_share", "0.00013")),
        taf_min=decimal(fee_model.get("taf_min", "0.01")),
        taf_max=decimal(fee_model.get("taf_max", "6.49")),
        premarket_against_signal_block_percent=decimal(queue.get("premarket_against_signal_block_percent", "-3")),
        premarket_overheat_wait_percent=decimal(queue.get("premarket_overheat_wait_percent", "8")),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: FastSignalQueueConfig) -> None:
    if config.stage != "M15.longbridge_fast_signal_queue":
        raise ValueError("M15 fast signal queue stage drift")
    if config.token_mode != "paper":
        raise ValueError("M15 fast signal queue must stay paper-token-only")
    if config.live_token_allowed:
        raise ValueError("M15 fast signal queue cannot allow live token")
    supported_order_types = {"limit", "trigger_limit"}
    if set(config.allowed_order_types) - supported_order_types:
        raise ValueError("M15 fast signal queue supports only limit and trigger_limit")
    if config.breakout_order_type not in set(config.allowed_order_types):
        raise ValueError("M15 fast signal queue breakout order type must be allowed")
    if config.max_signal_age_seconds <= 0:
        raise ValueError("M15 fast signal queue max signal age must be positive")
    if any(value <= 0 for value in config.max_signal_age_seconds_by_timeframe.values()):
        raise ValueError("M15 fast signal queue timeframe max signal ages must be positive")
    if config.allow_fractional_shares:
        raise ValueError("M15 fast signal queue forbids fractional shares")
    if config.allow_short_selling:
        raise ValueError("M15 fast signal queue forbids short selling")
    if config.allow_options:
        raise ValueError("M15 fast signal queue forbids options")
    if not config.regular_hours_only:
        raise ValueError("M15 fast signal queue must stay US regular-hours only")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 fast signal queue must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "manual_m12_37_once"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M15 fast signal queue cannot enable {key}")
    if config.independent_family_bonus < ZERO:
        raise ValueError("M15 fast signal queue independent family bonus must be non-negative")
    if config.same_family_variant_bonus < ZERO:
        raise ValueError("M15 fast signal queue same family variant bonus must be non-negative")
    if config.max_same_family_variants < 0:
        raise ValueError("M15 fast signal queue same family variant cap must be non-negative")
    if config.max_confluence_multiplier < Decimal("1.0"):
        raise ValueError("M15 fast signal queue confluence multiplier must be >= 1")
    fee_values = (
        config.commission_per_share,
        config.commission_min,
        config.platform_fee_per_share,
        config.platform_fee_min,
        config.settlement_fee_per_share,
        config.sec_fee_rate,
        config.sec_fee_min,
        config.taf_per_share,
        config.taf_min,
        config.taf_max,
    )
    if any(value < ZERO for value in fee_values):
        raise ValueError("M15 fast signal queue fee model values must be non-negative")
    if config.premarket_against_signal_block_percent >= ZERO:
        raise ValueError("M15 fast signal queue premarket against threshold must be negative")
    if config.premarket_overheat_wait_percent <= ZERO:
        raise ValueError("M15 fast signal queue premarket overheat threshold must be positive")


def run_fast_signal_queue(
    config: FastSignalQueueConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or now_utc_iso()
    summary, ledger_rows = build_fast_signal_queue(config, generated_at)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / SUMMARY_JSON, summary)
    write_jsonl(config.output_dir / LEDGER_JSONL, ledger_rows)
    (config.output_dir / REPORT_MD).write_text(render_markdown(summary, ledger_rows), encoding="utf-8")
    return summary


def build_fast_signal_queue(config: FastSignalQueueConfig, generated_at: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started = time.perf_counter()
    dashboard = read_json(config.dashboard_path)
    extended_session_monitor = read_json(config.extended_session_monitor_path)
    paper_gate = read_json(config.paper_gate_path)
    m14_summary = read_json(config.paper_gate_path.with_name("m14_strategy_challenge_summary.json"))
    dashboard_summary = dashboard.get("summary", dashboard) if isinstance(dashboard.get("summary", dashboard), dict) else {}
    scan_date = str(dashboard_summary.get("scan_date", ""))
    current_market_date = market_date_for(config, generated_at)
    quote_source = str(dashboard_summary.get("quote_source", ""))
    m14_trading_date = str(m14_summary.get("trading_date", ""))
    fallback_or_no_fetch = text_has_fallback_or_no_fetch(
        quote_source,
        dashboard_summary.get("data_freshness_warning", ""),
        dashboard_summary.get("data_quality_state", ""),
        m14_summary.get("data_freshness_warning", ""),
        m14_summary.get("data_quality_state", ""),
    )
    quote_source_blockers = quote_source_blockers_for(quote_source, fallback_or_no_fetch)
    current_day_blockers = current_day_strategy_blockers(scan_date, m14_trading_date)
    stale_snapshot_blockers = stale_snapshot_blockers_for(scan_date, current_market_date)
    gate_rows = list(paper_gate.get("rows", []))
    gate_by_runtime = {str(row.get("runtime_id", "")): row for row in gate_rows if row.get("runtime_id")}
    decision_by_runtime = latest_strategy_decisions_by_runtime(read_jsonl(config.strategy_decision_ledger_path), m14_trading_date)
    source_ledger_rows = read_jsonl(config.account_trade_ledger_path)
    source_rows = current_day_open_rows(source_ledger_rows, scan_date)
    mark_open_rows_superseded_by_close(source_rows, source_ledger_rows, scan_date)
    ledger_rows = [
        build_fast_signal_row(
            config,
            generated_at,
            row,
            gate_by_runtime.get(str(row.get("runtime_id", "")), {}),
            decision_by_runtime.get(str(row.get("runtime_id", "")), {}),
        )
        for row in source_rows
    ]
    apply_premarket_adjustments(ledger_rows, extended_session_monitor)
    confluence_summary = apply_confluence_merge(config, ledger_rows)
    sort_rows_for_profit_priority(ledger_rows)
    apply_shared_account_caps(ledger_rows, config)
    apply_stale_snapshot_blockers(ledger_rows, stale_snapshot_blockers)
    apply_submission_priority_ranks(ledger_rows)
    counts = build_summary_counts(ledger_rows, gate_rows)
    status = fast_queue_status_for(counts, quote_source_blockers, current_day_blockers, stale_snapshot_blockers)
    payload = {
        "schema_version": "m15.longbridge-fast-signal-queue.v1",
        "stage": config.stage,
        "title": config.title,
        "source_mode": "fast_signal_queue",
        "generated_at": generated_at,
        "build_elapsed_ms": int((time.perf_counter() - started) * 1000),
        "input_refs": {
            "m12_32_dashboard": project_path(config.dashboard_path),
            "m12_46_account_trade_ledger": project_path(config.account_trade_ledger_path),
            "m14_paper_trial_gate": project_path(config.paper_gate_path),
            "m14_strategy_decision_ledger": project_path(config.strategy_decision_ledger_path),
            "m12_48_extended_session_monitor": project_path(config.extended_session_monitor_path),
        },
        "output_refs": {
            "summary": project_path(config.output_dir / SUMMARY_JSON),
            "fast_signal_queue_ledger": project_path(config.output_dir / LEDGER_JSONL),
            "markdown_report": project_path(config.output_dir / REPORT_MD),
        },
        "scan_date": scan_date,
        "current_market_date": current_market_date,
        "m14_trading_date": m14_trading_date,
        "quote_source": quote_source,
        "fallback_or_no_fetch_data": fallback_or_no_fetch,
        "quote_source_blockers": quote_source_blockers,
        "current_day_blockers": current_day_blockers,
        "stale_snapshot_blockers": stale_snapshot_blockers,
        "current_day_strategy_confirmation_status": "confirmed" if not current_day_blockers else "blocked",
        "snapshot_freshness_status": "current_market_date" if not stale_snapshot_blockers else "stale_snapshot",
        "fast_path_no_m13_wait": True,
        "fast_queue_status": status,
        "preview_status": status,
        "confluence_summary": confluence_summary,
        "summary": counts,
        "paper_account_model": {
            "equity": fmt_money(config.paper_account_equity),
            "max_total_exposure": fmt_money(config.max_total_exposure),
            "min_cash_reserve": fmt_money(config.min_cash_reserve),
            "max_symbol_exposure": fmt_money(config.max_symbol_exposure),
            "max_risk_per_order": fmt_money(config.max_risk_per_order),
            "max_orders_per_day": config.max_orders_per_day,
        },
        "signal_freshness_policy": {
            "max_signal_age_seconds": config.max_signal_age_seconds,
            "max_signal_age_seconds_by_timeframe": dict(sorted(config.max_signal_age_seconds_by_timeframe.items())),
            "close_after_open_blocks_submit": True,
        },
        "profit_priority_policy": {
            "fee_profit_gate": "target_gross_profit_minus_buy_fees_minus_sell_fees_must_be_positive",
            "sort_order": [
                "net_profit_after_fees_at_target_desc",
                "strategy_quality_score_desc",
                "reward_r_desc",
                "confluence_multiplier_desc",
            ],
            "symbol_price_priority": "not_used_for_priority_only_affordability_and_risk",
        },
        "fee_model": {
            "commission_per_share": fmt_decimal(config.commission_per_share),
            "commission_min": fmt_money(config.commission_min),
            "platform_fee_per_share": fmt_decimal(config.platform_fee_per_share),
            "platform_fee_min": fmt_money(config.platform_fee_min),
            "settlement_fee_per_share": fmt_decimal(config.settlement_fee_per_share),
            "sec_fee_rate": fmt_decimal(config.sec_fee_rate),
            "sec_fee_min": fmt_money(config.sec_fee_min),
            "taf_per_share": fmt_decimal(config.taf_per_share),
            "taf_min": fmt_money(config.taf_min),
            "taf_max": fmt_money(config.taf_max),
        },
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "manual_m12_37_once": False,
            "local_sim_position_migration": False,
            "m13_wait_before_submit": False,
        },
        "plain_language_result": plain_language_result(status, counts, quote_source_blockers, current_day_blockers, stale_snapshot_blockers),
    }
    assert_no_legacy_profit_fields(payload, ledger_rows)
    return payload, ledger_rows


def current_day_open_rows(rows: list[dict[str, Any]], scan_date: str) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("trading_date", "")) == scan_date and str(row.get("event_type", "")) == "open"
    ]


def mark_open_rows_superseded_by_close(open_rows: list[dict[str, Any]], all_rows: list[dict[str, Any]], scan_date: str) -> None:
    closes_by_runtime_symbol: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for row in all_rows:
        if str(row.get("trading_date", "")) != scan_date or str(row.get("event_type", "")) != "close":
            continue
        close_dt = parse_optional_utc_datetime(str(row.get("event_time", "")))
        if close_dt is None:
            continue
        key = (str(row.get("runtime_id", "")), str(row.get("symbol", "")))
        closes_by_runtime_symbol[key].append(close_dt)
    for row in open_rows:
        open_dt = parse_optional_utc_datetime(str(row.get("event_time", "")))
        if open_dt is None:
            continue
        key = (str(row.get("runtime_id", "")), str(row.get("symbol", "")))
        later_closes = [close_dt for close_dt in closes_by_runtime_symbol.get(key, []) if close_dt > open_dt]
        if later_closes:
            row["_latest_close_event_time_after_open"] = max(later_closes).isoformat().replace("+00:00", "Z")


def signal_freshness_blockers(config: FastSignalQueueConfig, generated_at: str, source_row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if str(source_row.get("_latest_close_event_time_after_open", "")):
        blockers.append("signal_superseded_by_close")
    generated_dt = parse_optional_utc_datetime(generated_at)
    event_dt = parse_optional_utc_datetime(str(source_row.get("event_time", "")))
    if generated_dt is not None and event_dt is not None:
        age_seconds = int((generated_dt - event_dt).total_seconds())
        max_age_seconds = signal_max_age_seconds(config, source_row)
        source_row["_signal_age_seconds"] = str(age_seconds)
        source_row["_signal_max_age_seconds"] = str(max_age_seconds)
        if age_seconds > max_age_seconds:
            blockers.append("signal_age_expired")
    return blockers


def signal_max_age_seconds(config: FastSignalQueueConfig, source_row: dict[str, Any]) -> int:
    timeframe = str(source_row.get("timeframe", "")).strip().lower()
    return config.max_signal_age_seconds_by_timeframe.get(timeframe, config.max_signal_age_seconds)


def parse_optional_utc_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def latest_strategy_decisions_by_runtime(rows: list[dict[str, Any]], trading_date: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        runtime_id = str(row.get("runtime_id", ""))
        if not runtime_id:
            continue
        row_date = str(row.get("trading_date", ""))
        if trading_date and row_date and row_date != trading_date:
            continue
        current = result.get(runtime_id)
        if current is None or str(row.get("generated_at", "")) >= str(current.get("generated_at", "")):
            result[runtime_id] = row
    return result


def estimate_fee_profit_fields(
    config: FastSignalQueueConfig,
    entry_price: Decimal,
    target_price: Decimal,
    quantity: Decimal,
) -> dict[str, Any]:
    gross_profit = (target_price - entry_price) * quantity
    entry_fees = estimate_us_stock_fee(config, "buy", entry_price, quantity)
    exit_fee_breakdown = estimate_us_stock_fee_breakdown(config, "sell", target_price, quantity)
    exit_fees = sum(exit_fee_breakdown.values(), ZERO)
    regulatory = exit_fee_breakdown.get("sec_fee", ZERO) + exit_fee_breakdown.get("taf_fee", ZERO)
    net_profit = gross_profit - entry_fees - exit_fees
    blockers: list[str] = []
    if quantity > ZERO and entry_price > ZERO and target_price > ZERO and net_profit <= ZERO:
        blockers.append("net_profit_after_fees_not_positive")
    return {
        "gross_profit_at_target": fmt_money(gross_profit),
        "estimated_entry_fees": fmt_money(entry_fees),
        "estimated_exit_fees_at_target": fmt_money(exit_fees),
        "estimated_regulatory_fees_at_target": fmt_money(regulatory),
        "net_profit_after_fees_at_target": fmt_money(net_profit),
        "fee_profit_gate_status": "passed" if not blockers else "blocked",
        "fee_profit_gate_blockers": blockers,
    }


def estimate_us_stock_fee(config: FastSignalQueueConfig, side: str, price: Decimal, quantity: Decimal) -> Decimal:
    return sum(estimate_us_stock_fee_breakdown(config, side, price, quantity).values(), ZERO)


def estimate_us_stock_fee_breakdown(
    config: FastSignalQueueConfig,
    side: str,
    price: Decimal,
    quantity: Decimal,
) -> dict[str, Decimal]:
    if price <= ZERO or quantity <= ZERO:
        return {"commission": ZERO, "platform_fee": ZERO, "settlement_fee": ZERO, "sec_fee": ZERO, "taf_fee": ZERO}
    commission = max(config.commission_per_share * quantity, config.commission_min)
    platform_fee = max(config.platform_fee_per_share * quantity, config.platform_fee_min)
    settlement_fee = config.settlement_fee_per_share * quantity
    sec_fee = ZERO
    taf_fee = ZERO
    if side == "sell":
        sec_fee = max(config.sec_fee_rate * price * quantity, config.sec_fee_min)
        taf_fee = min(max(config.taf_per_share * quantity, config.taf_min), config.taf_max)
    return {
        "commission": commission,
        "platform_fee": platform_fee,
        "settlement_fee": settlement_fee,
        "sec_fee": sec_fee,
        "taf_fee": taf_fee,
    }


def strategy_win_rate(decision_row: dict[str, Any]) -> str:
    for key in ("win_rate", "win_rate_percent", "current_win_rate", "current_win_rate_percent"):
        if str(decision_row.get(key, "")) != "":
            return str(decision_row.get(key, ""))
    return ""


def strategy_quality_score(decision_row: dict[str, Any], gate_row: dict[str, Any]) -> Decimal:
    score = action_quality_score(str(gate_row.get("action_state", "")))
    net_pnl_r = decimal(decision_row.get("net_pnl_r", "0"))
    realized_pnl = decimal(decision_row.get("realized_pnl", "0"))
    drawdown = decimal(decision_row.get("max_drawdown_percent", "0"))
    risk_block_ratio = decimal(decision_row.get("risk_block_ratio", "0"))
    signal_count = decimal(decision_row.get("total_signal_count") or decision_row.get("signal_count") or "0")
    if net_pnl_r > ZERO:
        score += min(net_pnl_r * Decimal("10"), Decimal("30"))
    if realized_pnl > ZERO:
        score += min(realized_pnl / Decimal("10"), Decimal("20"))
    if drawdown > ZERO:
        score += max(Decimal("0"), Decimal("20") - drawdown)
    if risk_block_ratio > ZERO:
        score -= min(risk_block_ratio * Decimal("20"), Decimal("20"))
    score += min(signal_count, Decimal("10"))
    return max(score, ZERO)


def action_quality_score(action_state: str) -> Decimal:
    scores = {
        "paper_candidate": Decimal("30"),
        "advance_internal_sim": Decimal("25"),
        "risk_limited_advance": Decimal("15"),
        "repair_now": Decimal("0"),
        "pause_runtime": Decimal("0"),
        "auxiliary_module": Decimal("0"),
    }
    return scores.get(action_state, ZERO)


def sort_rows_for_profit_priority(rows: list[dict[str, Any]]) -> None:
    rows.sort(key=profit_priority_key)


def profit_priority_key(row: dict[str, Any]) -> tuple[int, Decimal, Decimal, Decimal, Decimal, str, str]:
    ready_penalty = 0 if row.get("longbridge_paper_order_preview_status") == READY_STATUS else 1
    return (
        ready_penalty,
        -decimal(row.get("net_profit_after_fees_at_target", "0")),
        -decimal(row.get("strategy_quality_score", "0")),
        -decimal(row.get("reward_r", "0")),
        -decimal(row.get("confluence_multiplier", "1")),
        str(row.get("symbol", "")),
        str(row.get("runtime_id", "")),
    )


def apply_submission_priority_ranks(rows: list[dict[str, Any]]) -> None:
    rank = 0
    for row in rows:
        if row.get("longbridge_paper_order_preview_status") != READY_STATUS:
            row["submission_priority_rank"] = ""
            continue
        rank += 1
        row["submission_priority_rank"] = str(rank)


def market_date_for(config: FastSignalQueueConfig, generated_at: str) -> str:
    utc_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    return utc_dt.astimezone(ZoneInfo(config.market_timezone)).date().isoformat()


def stale_snapshot_blockers_for(scan_date: str, current_market_date: str) -> list[str]:
    if scan_date and current_market_date and scan_date != current_market_date:
        return ["stale_snapshot_submit_blocked"]
    return []


def apply_stale_snapshot_blockers(rows: list[dict[str, Any]], blockers: list[str]) -> None:
    if not blockers:
        return
    for row in rows:
        row["pre_stale_snapshot_status"] = row.get("longbridge_paper_order_preview_status", "")
        row["longbridge_paper_order_preview_status"] = "stale_snapshot_submit_blocked"
        row["snapshot_freshness_status"] = "stale_snapshot"
        row["blockers"] = append_unique(row.get("blockers", []), blockers)


def apply_premarket_adjustments(rows: list[dict[str, Any]], extended_session_monitor: dict[str, Any]) -> None:
    premarket_by_symbol = strongest_premarket_rows(extended_session_monitor)
    for row in rows:
        symbol = str(row.get("symbol", ""))
        premarket = premarket_by_symbol.get(symbol)
        if not premarket:
            row["premarket_adjustment"] = "none"
            continue
        move_percent = decimal(premarket.get("move_percent", "0"))
        row["premarket_adjustment"] = "context_only"
        row["premarket_move_percent"] = fmt_decimal(move_percent)
        row["premarket_extended_price"] = str(premarket.get("extended_price", ""))
        row["premarket_quote_timestamp"] = str(premarket.get("quote_timestamp", ""))
        if row.get("direction") != "看涨" or row.get("longbridge_paper_order_preview_status") != READY_STATUS:
            continue
        if move_percent <= row_premarket_against_threshold(row):
            row["premarket_adjustment"] = "block_against_signal"
            row["longbridge_paper_order_preview_status"] = "premarket_against_signal_blocked"
            row["blockers"] = append_unique(row.get("blockers", []), ["premarket_against_signal_blocked"])
        elif move_percent > row_premarket_overheat_threshold(row):
            row["premarket_adjustment"] = "wait_first_5m_confirmation"
            row["longbridge_paper_order_preview_status"] = "wait_first_5m_confirmation"
            row["blockers"] = append_unique(row.get("blockers", []), ["wait_first_5m_confirmation"])
        elif move_percent >= Decimal("3"):
            row["premarket_adjustment"] = "same_direction_confirmed_no_extra_size"


def strongest_premarket_rows(extended_session_monitor: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = extended_session_monitor.get("premarket_rows", [])
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict) or str(row.get("symbol", "")) == "":
            continue
        symbol = str(row.get("symbol", ""))
        current = result.get(symbol)
        if current is None or abs(decimal(row.get("move_percent", "0"))) > abs(decimal(current.get("move_percent", "0"))):
            result[symbol] = row
    return result


def row_premarket_against_threshold(row: dict[str, Any]) -> Decimal:
    return decimal(row.get("premarket_against_signal_block_percent", "-3"))


def row_premarket_overheat_threshold(row: dict[str, Any]) -> Decimal:
    return decimal(row.get("premarket_overheat_wait_percent", "8"))


def apply_confluence_merge(config: FastSignalQueueConfig, rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("longbridge_paper_order_preview_status") != READY_STATUS:
            continue
        key = (
            str(row.get("trading_date", "")),
            str(row.get("symbol", "")),
            str(row.get("broker_order_side", "")),
            str(row.get("direction", "")),
        )
        groups[key].append(row)

    primary_count = 0
    support_count = 0
    max_multiplier = Decimal("1")
    for key, group in groups.items():
        if len(group) < 2:
            group[0]["confluence_role"] = "single"
            group[0]["confluence_multiplier"] = "1"
            continue
        primary = sorted(group, key=primary_rank_key)[0]
        support_rows = [row for row in group if row is not primary]
        multiplier = confluence_multiplier(config, group)
        max_multiplier = max(max_multiplier, multiplier)
        update_primary_for_confluence(config, primary, support_rows, key, multiplier)
        for support in support_rows:
            mark_confluence_support(support, primary, key, group, multiplier)
        primary_count += 1
        support_count += len(support_rows)

    return {
        "confluence_group_count": primary_count,
        "confluence_support_row_count": support_count,
        "max_confluence_multiplier": fmt_decimal(max_multiplier),
    }


def primary_rank_key(row: dict[str, Any]) -> tuple[int, int, int, Decimal, Decimal, str]:
    return (
        rescue_or_shadow_penalty(row),
        mainline_penalty(row),
        action_state_rank(str(row.get("runtime_action_state", ""))),
        -reward_r(row),
        decimal(row.get("estimated_open_risk", "0")),
        str(row.get("runtime_id", "")),
    )


def rescue_or_shadow_penalty(row: dict[str, Any]) -> int:
    text = " ".join(str(row.get(key, "")) for key in ("runtime_id", "strategy_id", "lane")).lower()
    return 1 if any(token in text for token in ("rescue", "shadow", "m14-modify")) else 0


def mainline_penalty(row: dict[str, Any]) -> int:
    lane = str(row.get("lane", "")).lower()
    if lane in {"mainline", "primary"}:
        return 0
    return rescue_or_shadow_penalty(row)


def action_state_rank(value: str) -> int:
    ranks = {
        "paper_candidate": 0,
        "advance_internal_sim": 1,
        "risk_limited_advance": 2,
    }
    return ranks.get(value, 9)


def reward_r(row: dict[str, Any]) -> Decimal:
    price = decimal(row.get("limit_price", "0"))
    stop = decimal(row.get("stop_price", "0"))
    target = decimal(row.get("target_price", "0"))
    risk = abs(price - stop)
    if price <= ZERO or stop <= ZERO or target <= ZERO or risk <= ZERO:
        return ZERO
    return abs(target - price) / risk


def strategy_family_id(row: dict[str, Any]) -> str:
    text = str(row.get("strategy_id") or row.get("runtime_id") or "")
    match = re.search(r"(M10-PA-\d{3}|M12-FTD-\d{3})", text)
    return match.group(1) if match else text


def confluence_multiplier(config: FastSignalQueueConfig, group: list[dict[str, Any]]) -> Decimal:
    family_counts = Counter(strategy_family_id(row) for row in group)
    independent_bonus = max(len(family_counts) - 1, 0) * config.independent_family_bonus
    same_family_variant_count = sum(min(max(count - 1, 0), config.max_same_family_variants) for count in family_counts.values())
    same_family_bonus = Decimal(same_family_variant_count) * config.same_family_variant_bonus
    return min(Decimal("1") + independent_bonus + same_family_bonus, config.max_confluence_multiplier)


def update_primary_for_confluence(
    config: FastSignalQueueConfig,
    primary: dict[str, Any],
    support_rows: list[dict[str, Any]],
    key: tuple[str, str, str, str],
    multiplier: Decimal,
) -> None:
    old_quantity = decimal(primary.get("quantity", "0"))
    old_fingerprint = str(primary.get("signal_fingerprint") or primary.get("preview_id", ""))
    base_strategy_exposure = decimal(primary.get("max_strategy_exposure", "0"))
    base_risk_cap = decimal(primary.get("max_risk_per_order", "0"))
    effective_strategy_exposure = min(config.max_symbol_exposure, base_strategy_exposure * multiplier)
    effective_risk_cap = min(config.max_risk_per_order, base_risk_cap * multiplier)
    quantity = confluence_quantity(config, primary, effective_strategy_exposure, effective_risk_cap)
    price = decimal(primary.get("limit_price", "0"))
    stop = decimal(primary.get("stop_price", "0"))
    risk_amount = estimated_open_risk("open", price, stop, quantity)
    fee_profit = estimate_fee_profit_fields(config, price, decimal(primary.get("target_price", "0")), quantity)
    new_fingerprint = preview_id(
        str(primary.get("runtime_id", "")),
        str(primary.get("symbol", "")),
        "open",
        str(primary.get("source_signal_time", "")),
        price,
        quantity,
    )
    primary.update(
        {
            "source_signal_fingerprint": old_fingerprint,
            "preview_id": new_fingerprint,
            "signal_fingerprint": new_fingerprint,
            "confluence_role": "primary",
            "confluence_group_key": "|".join(key),
            "confluence_multiplier": fmt_decimal(multiplier),
            "confluence_signal_count": len(support_rows) + 1,
            "confluence_family_count": len({strategy_family_id(row) for row in [primary, *support_rows]}),
            "confluence_family_ids": sorted({strategy_family_id(row) for row in [primary, *support_rows]}),
            "confluence_supporting_signal_fingerprints": [
                str(row.get("signal_fingerprint") or row.get("preview_id", "")) for row in support_rows
            ],
            "confluence_supporting_runtime_ids": sorted({str(row.get("runtime_id", "")) for row in support_rows}),
            "confluence_quantity_before": fmt_decimal(old_quantity),
            "confluence_quantity_after": fmt_decimal(quantity),
            "base_max_strategy_exposure": fmt_money(base_strategy_exposure),
            "base_max_risk_per_order": fmt_money(base_risk_cap),
            "effective_max_strategy_exposure": fmt_money(effective_strategy_exposure),
            "effective_max_risk_per_order": fmt_money(effective_risk_cap),
            "max_strategy_exposure": fmt_money(effective_strategy_exposure),
            "max_risk_per_order": fmt_money(effective_risk_cap),
            "quantity": fmt_decimal(quantity),
            "notional": fmt_money(price * quantity),
            "estimated_open_risk": fmt_money(risk_amount),
            "gross_profit_at_target": fee_profit["gross_profit_at_target"],
            "estimated_entry_fees": fee_profit["estimated_entry_fees"],
            "estimated_exit_fees_at_target": fee_profit["estimated_exit_fees_at_target"],
            "estimated_regulatory_fees_at_target": fee_profit["estimated_regulatory_fees_at_target"],
            "net_profit_after_fees_at_target": fee_profit["net_profit_after_fees_at_target"],
            "fee_profit_gate_status": fee_profit["fee_profit_gate_status"],
            "fee_profit_gate_blockers": fee_profit["fee_profit_gate_blockers"],
            "reward_r": fmt_decimal(reward_r({"limit_price": price, "stop_price": stop, "target_price": primary.get("target_price", "0")})),
        }
    )


def confluence_quantity(
    config: FastSignalQueueConfig,
    row: dict[str, Any],
    effective_strategy_exposure: Decimal,
    effective_risk_cap: Decimal,
) -> Decimal:
    source_quantity = decimal(row.get("source_quantity", "0"))
    price = decimal(row.get("limit_price", "0"))
    stop = decimal(row.get("stop_price", "0"))
    candidates = [source_quantity.to_integral_value(rounding=ROUND_FLOOR)]
    if price > ZERO:
        candidates.append((effective_strategy_exposure / price).to_integral_value(rounding=ROUND_FLOOR))
        candidates.append((config.max_symbol_exposure / price).to_integral_value(rounding=ROUND_FLOOR))
        candidates.append((config.max_total_exposure / price).to_integral_value(rounding=ROUND_FLOOR))
    risk_per_share = abs(price - stop)
    if risk_per_share > ZERO:
        candidates.append((effective_risk_cap / risk_per_share).to_integral_value(rounding=ROUND_FLOOR))
    return max(min(candidates), ZERO)


def mark_confluence_support(
    support: dict[str, Any],
    primary: dict[str, Any],
    key: tuple[str, str, str, str],
    group: list[dict[str, Any]],
    multiplier: Decimal,
) -> None:
    support["confluence_role"] = "support"
    support["confluence_group_key"] = "|".join(key)
    support["confluence_multiplier"] = fmt_decimal(multiplier)
    support["confluence_signal_count"] = len(group)
    support["confluence_family_count"] = len({strategy_family_id(row) for row in group})
    support["confluence_family_ids"] = sorted({strategy_family_id(row) for row in group})
    support["merged_primary_signal_fingerprint"] = primary.get("signal_fingerprint", "")
    support["merged_primary_runtime_id"] = primary.get("runtime_id", "")
    support["longbridge_paper_order_preview_status"] = "merged_into_confluence_primary"
    support["blockers"] = append_unique(support.get("blockers", []), ["merged_into_confluence_primary"])


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    result = list(values)
    for item in additions:
        if item not in result:
            result.append(item)
    return result


def build_fast_signal_row(
    config: FastSignalQueueConfig,
    generated_at: str,
    source_row: dict[str, Any],
    gate_row: dict[str, Any],
    decision_row: dict[str, Any],
) -> dict[str, Any]:
    direction = normalize_direction(str(source_row.get("direction", "")))
    price = order_price(source_row)
    source_quantity = decimal(source_row.get("quantity", "0"))
    stop_price = decimal(source_row.get("stop_price", "0"))
    target_price = decimal(source_row.get("target_price", "0"))
    tier = runtime_risk_tier(source_row, gate_row, config)
    tier_policy = risk_tier_policy(tier, config)
    quantity = paper_order_quantity(
        source_quantity,
        config,
        event_type="open",
        price=price,
        stop_price=stop_price,
        tier=tier,
        tier_policy=tier_policy,
    )
    risk_amount = estimated_open_risk("open", price, stop_price, quantity)
    order_type = infer_order_type(source_row, config)
    blockers = order_blockers(config, source_row, gate_row, price, source_quantity, quantity, risk_amount, tier_policy)
    blockers = append_unique(blockers, signal_freshness_blockers(config, generated_at, source_row))
    fee_profit = estimate_fee_profit_fields(config, price, target_price, quantity)
    if fee_profit["fee_profit_gate_status"] == "blocked":
        blockers = append_unique(blockers, ["net_profit_after_fees_not_positive"])
    preview_status = order_preview_status(gate_row, blockers)
    if "signal_superseded_by_close" in blockers and preview_status == READY_STATUS:
        preview_status = "signal_superseded_by_close_submit_blocked"
    if "signal_age_expired" in blockers and preview_status == READY_STATUS:
        preview_status = "signal_age_expired_submit_blocked"
    if "net_profit_after_fees_not_positive" in blockers and preview_status == READY_STATUS:
        preview_status = "local_order_preview_created_fee_profit_blocked"
    runtime_id = str(source_row.get("runtime_id", ""))
    strategy_id = str(source_row.get("strategy_id", ""))
    symbol = str(source_row.get("symbol", ""))
    signal_time = str(source_row.get("signal_time", ""))
    fingerprint = preview_id(runtime_id, symbol, "open", signal_time, price, quantity)
    explicit_trigger_price = decimal(source_row.get("trigger_price", ""))
    row = {
        "schema_version": "m15.longbridge-fast-signal-queue-row.v1",
        "stage": "M15.longbridge_fast_signal_queue",
        "source_mode": "fast_signal_queue",
        "generated_at": generated_at,
        "preview_id": fingerprint,
        "signal_fingerprint": fingerprint,
        "trading_date": str(source_row.get("trading_date", "")),
        "source_ledger": project_path(config.account_trade_ledger_path),
        "source_event_time": str(source_row.get("event_time", "")),
        "source_signal_time": signal_time,
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "timeframe": str(source_row.get("timeframe", "")),
        "lane": str(source_row.get("lane", "")),
        "runtime_action_state": str(gate_row.get("action_state", "not_in_current_m14_gate")),
        "runtime_gate": str(gate_row.get("paper_trial_gate", "")),
        "runtime_position_size_multiplier": str(
            source_row.get("position_size_multiplier") or gate_row.get("position_size_multiplier", "")
        ),
        "runtime_repair_policy": str(source_row.get("runtime_repair_policy", "")),
        "symbol": symbol,
        "market": "US",
        "local_event_type": "open",
        "order_intent": "开仓",
        "direction": direction,
        "broker_order_side": broker_order_side("open", direction),
        "order_type": order_type,
        "allowed_order_types": list(config.allowed_order_types),
        "breakout_order_type": config.breakout_order_type,
        "max_signal_age_seconds": str(source_row.get("_signal_max_age_seconds") or config.max_signal_age_seconds),
        "limit_price": fmt_decimal(price),
        "trigger_price": fmt_decimal(explicit_trigger_price if explicit_trigger_price > ZERO else price),
        "source_quantity": fmt_decimal(source_quantity),
        "quantity": fmt_decimal(quantity),
        "quantity_policy": config.quantity_policy,
        "fractional_shares_allowed": config.allow_fractional_shares,
        "short_selling_allowed": config.allow_short_selling,
        "options_allowed": config.allow_options,
        "notional": fmt_money(price * quantity),
        "stop_price": fmt_decimal(stop_price),
        "target_price": fmt_decimal(target_price),
        "estimated_open_risk": fmt_money(risk_amount),
        "gross_profit_at_target": fee_profit["gross_profit_at_target"],
        "estimated_entry_fees": fee_profit["estimated_entry_fees"],
        "estimated_exit_fees_at_target": fee_profit["estimated_exit_fees_at_target"],
        "estimated_regulatory_fees_at_target": fee_profit["estimated_regulatory_fees_at_target"],
        "net_profit_after_fees_at_target": fee_profit["net_profit_after_fees_at_target"],
        "fee_profit_gate_status": fee_profit["fee_profit_gate_status"],
        "fee_profit_gate_blockers": fee_profit["fee_profit_gate_blockers"],
        "signal_age_seconds": str(source_row.get("_signal_age_seconds", "")),
        "latest_close_event_time_after_open": str(source_row.get("_latest_close_event_time_after_open", "")),
        "strategy_win_rate": strategy_win_rate(decision_row),
        "strategy_quality_score": fmt_decimal(strategy_quality_score(decision_row, gate_row)),
        "strategy_quality_source": "m14_strategy_decision_ledger",
        "reward_r": fmt_decimal(reward_r({"limit_price": price, "stop_price": stop_price, "target_price": target_price})),
        "submission_priority_rank": "",
        "paper_account_equity": fmt_money(config.paper_account_equity),
        "max_total_exposure": fmt_money(config.max_total_exposure),
        "max_symbol_exposure": fmt_money(config.max_symbol_exposure),
        "risk_tier": tier,
        "max_strategy_exposure": fmt_money(tier_policy["max_strategy_exposure"]),
        "max_risk_per_order": fmt_money(tier_policy["max_risk_per_order"]),
        "premarket_against_signal_block_percent": fmt_decimal(config.premarket_against_signal_block_percent),
        "premarket_overheat_wait_percent": fmt_decimal(config.premarket_overheat_wait_percent),
        "m13_comparison_status": "fast_queue_no_m13_wait",
        "m13_comparison_notes": ["快速通道不等待 M13 当天账本；完整本地模拟留给后台对账。"],
        "longbridge_paper_order_preview_status": preview_status,
        "blockers": blockers,
        "local_record_only": False,
        "paper_token_required_before_connection": True,
        "broker_connection_attempted": False,
        "order_submitted": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    return row


def build_summary_counts(rows: list[dict[str, Any]], gate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ready = [row for row in rows if row["longbridge_paper_order_preview_status"] == READY_STATUS]
    status_counts = Counter(row["longbridge_paper_order_preview_status"] for row in rows)
    action_counts = Counter(row.get("runtime_action_state", "") for row in rows)
    return {
        "new_open_signal_count": len(rows),
        "ready_after_user_approval_count": len(ready),
        "blocked_signal_count": len(rows) - len(ready),
        "ready_after_user_approval_notional": fmt_money(sum((decimal(row.get("notional", "0")) for row in ready), ZERO)),
        "status_counts": dict(sorted(status_counts.items())),
        "action_state_counts": dict(sorted(action_counts.items())),
        "confluence_primary_count": sum(1 for row in rows if row.get("confluence_role") == "primary"),
        "confluence_support_count": sum(1 for row in rows if row.get("confluence_role") == "support"),
        "stale_snapshot_blocked_count": sum(1 for row in rows if row.get("longbridge_paper_order_preview_status") == "stale_snapshot_submit_blocked"),
        "premarket_blocked_count": sum(1 for row in rows if row.get("longbridge_paper_order_preview_status") == "premarket_against_signal_blocked"),
        "premarket_wait_confirmation_count": sum(1 for row in rows if row.get("longbridge_paper_order_preview_status") == "wait_first_5m_confirmation"),
        "fee_profit_blocked_count": sum(1 for row in rows if row.get("longbridge_paper_order_preview_status") == "local_order_preview_created_fee_profit_blocked"),
        "signal_age_expired_count": sum(1 for row in rows if row.get("longbridge_paper_order_preview_status") == "signal_age_expired_submit_blocked"),
        "signal_superseded_by_close_count": sum(1 for row in rows if row.get("longbridge_paper_order_preview_status") == "signal_superseded_by_close_submit_blocked"),
        "net_profitable_ready_count": sum(1 for row in ready if decimal(row.get("net_profit_after_fees_at_target", "0")) > ZERO),
        "repair_signal_count": sum(1 for row in rows if row.get("runtime_action_state") == "repair_now"),
        "auxiliary_module_count": sum(1 for row in gate_rows if str(row.get("runtime_role", "")) == "auxiliary_module"),
    }


def fast_queue_status_for(
    counts: dict[str, Any],
    quote_source_blockers: list[str],
    current_day_blockers: list[str],
    stale_snapshot_blockers: list[str],
) -> str:
    if stale_snapshot_blockers:
        return "stale_snapshot_waiting_for_current_refresh"
    if quote_source_blockers:
        return "blocked_quote_source_fast_queue_only"
    if current_day_blockers:
        return "fast_queue_created_m14_stale_submit_blocked"
    if counts["new_open_signal_count"] == 0:
        return "no_new_open_signals"
    if counts["ready_after_user_approval_count"] == 0:
        return "no_submit_ready_fast_signals"
    return "fast_signal_queue_ready"


def current_day_strategy_blockers(scan_date: str, m14_trading_date: str) -> list[str]:
    blockers: list[str] = []
    if not scan_date:
        blockers.append("scan_date_missing")
    if not m14_trading_date:
        blockers.append("m14_trading_date_missing")
    if scan_date and m14_trading_date and scan_date != m14_trading_date:
        blockers.append("m14_not_recomputed_for_current_scan_date")
    return blockers


def plain_language_result(
    status: str,
    counts: dict[str, Any],
    quote_source_blockers: list[str],
    current_day_blockers: list[str],
    stale_snapshot_blockers: list[str],
) -> str:
    base = (
        f"快速通道发现 {counts['new_open_signal_count']} 条当天新开仓信号，"
        f"其中 {counts['ready_after_user_approval_count']} 条通过快速队列风控。"
    )
    if status == "stale_snapshot_waiting_for_current_refresh":
        return base + f" 但这是旧快照，等待今日刷新：{', '.join(stale_snapshot_blockers)}。"
    if status == "fast_signal_queue_ready":
        return (
            base
            + f" 共振合并主订单 {counts.get('confluence_primary_count', 0)} 条，"
            + f"支持行 {counts.get('confluence_support_count', 0)} 条；提交器可直接消费本队列，不等待完整 M13/M14 对账。"
        )
    if status == "blocked_quote_source_fast_queue_only":
        return base + f" 行情来源阻断：{', '.join(quote_source_blockers)}。"
    if status == "fast_queue_created_m14_stale_submit_blocked":
        return base + f" 当天策略名单未确认：{', '.join(current_day_blockers)}。"
    if status == "no_new_open_signals":
        return "快速通道当前没有当天新开仓信号。"
    return base + " 但没有信号满足提交条件。"


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_holidays(values: list[str]) -> frozenset[date]:
    return frozenset(date.fromisoformat(str(item)) for item in values)


def render_markdown(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    counts = summary["summary"]
    lines = [
        "# 长桥模拟账户快速新信号队列",
        "",
        f"- 状态：`{summary['fast_queue_status']}`",
        f"- 看板日期：`{summary['scan_date']}`",
        f"- 当前纽约交易日：`{summary.get('current_market_date', '')}`",
        f"- M14 策略名单日期：`{summary['m14_trading_date']}`",
        f"- 行情来源：`{summary['quote_source']}`",
        f"- 人话结论：{summary['plain_language_result']}",
        f"- 队列生成耗时毫秒：`{summary['build_elapsed_ms']}`",
        "- 完整 M13/M14 对账等待：否",
        "- 旧本地模拟仓位迁移：否",
        f"- 账户口径：`{summary['paper_account_model']['equity']}` 美元模型；总敞口 `{summary['paper_account_model']['max_total_exposure']}`，单标的 `{summary['paper_account_model']['max_symbol_exposure']}`，现金保留 `{summary['paper_account_model']['min_cash_reserve']}`",
        "- 排序口径：扣费后预计净利润优先，价格不参与优先级",
        f"- 旧快照阻断：`{', '.join(summary.get('stale_snapshot_blockers', [])) or 'none'}`",
        "",
        "## 汇总",
        "",
        f"- 当天新开仓信号：`{counts['new_open_signal_count']}`",
        f"- 快速风控通过：`{counts['ready_after_user_approval_count']}`",
        f"- 被阻断信号：`{counts['blocked_signal_count']}`",
        f"- 共振主订单：`{counts.get('confluence_primary_count', 0)}`",
        f"- 共振支持行：`{counts.get('confluence_support_count', 0)}`",
        f"- 扣费后不赚钱阻断：`{counts.get('fee_profit_blocked_count', 0)}`",
        f"- 盘前阻断/等待确认：`{counts.get('premarket_blocked_count', 0)}` / `{counts.get('premarket_wait_confirmation_count', 0)}`",
        "",
        "## 队列样本",
        "",
        "| 优先级 | 状态 | 共振角色 | 运行单元 | 标的 | 类型 | 数量 | 限价 | 触发价 | 扣费后净利 | 收益风险比 | 阻断 |",
        "| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows[:50]:
        lines.append(
            f"| {row.get('submission_priority_rank', '')} | {row.get('longbridge_paper_order_preview_status', '')} | {row.get('confluence_role', '')} | "
            f"{row.get('runtime_id', '')} | "
            f"{row.get('symbol', '')} | {row.get('order_type', '')} | {row.get('quantity', '')} | "
            f"{row.get('limit_price', '')} | {row.get('trigger_price', '')} | "
            f"{row.get('net_profit_after_fees_at_target', '')} | {row.get('reward_r', '')} | "
            f"{', '.join(row.get('blockers', [])) or 'none'} |"
        )
    return "\n".join(lines) + "\n"


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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
