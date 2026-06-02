#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_all_strategy_order_preview.json"
DEFAULT_DAILY_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
)
DEFAULT_M12_DIR = DEFAULT_DAILY_DIR / "m12_29_current_day_scan_dashboard"
DEFAULT_M13_DIR = DEFAULT_DAILY_DIR / "m13_real_daily_strategy_testing"
DEFAULT_M14_DIR = DEFAULT_DAILY_DIR / "m14_strategy_challenge"
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_all_strategy_order_preview"
SUMMARY_JSON = "m15_all_strategy_order_preview.json"
LEDGER_JSONL = "m15_all_strategy_order_preview_ledger.jsonl"
REPORT_MD = "m15_all_strategy_order_preview.md"
MONEY = Decimal("0.01")
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class AllStrategyOrderPreviewConfig:
    stage: str
    title: str
    dashboard_path: Path
    runtime_state_path: Path
    account_trade_ledger_path: Path
    account_operation_ledger_path: Path
    paper_gate_path: Path
    output_dir: Path
    token_mode: str
    live_token_allowed: bool
    broker_connection_enabled: bool
    submit_orders: bool
    paper_trading_approval: bool
    default_order_type: str
    allowed_order_types: tuple[str, ...]
    breakout_order_type: str
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


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AllStrategyOrderPreviewConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    preview = payload.get("longbridge_paper_preview", {})
    account_model = preview.get("paper_account_model", {})
    risk_tiers = {
        str(name): {
            str(key): decimal(value)
            for key, value in dict(settings).items()
            if key in {"max_strategy_exposure", "max_risk_per_order"}
        }
        for name, settings in dict(preview.get("risk_tiers", {})).items()
    }
    return AllStrategyOrderPreviewConfig(
        stage=str(payload.get("stage", "M15.all_strategy_order_preview")),
        title=str(payload.get("title", "全策略长桥模拟账户订单预演")),
        dashboard_path=resolve_repo_path(inputs.get("m12_32_dashboard", DEFAULT_M12_DIR / "m12_32_minute_readonly_dashboard_data.json")),
        runtime_state_path=resolve_repo_path(
            inputs.get("m12_46_account_runtime_state", DEFAULT_M12_DIR / "m12_46_account_runtime_state.json")
        ),
        account_trade_ledger_path=resolve_repo_path(
            inputs.get("m12_46_account_trade_ledger", DEFAULT_M12_DIR / "m12_46_account_trade_ledger.jsonl")
        ),
        account_operation_ledger_path=resolve_repo_path(
            inputs.get("m13_account_operation_ledger", DEFAULT_M13_DIR / "m13_account_operation_ledger.jsonl")
        ),
        paper_gate_path=resolve_repo_path(inputs.get("m14_paper_trial_gate", DEFAULT_M14_DIR / "m14_paper_trial_gate.json")),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        token_mode=str(preview.get("token_mode", "paper")),
        live_token_allowed=bool(preview.get("live_token_allowed", False)),
        broker_connection_enabled=bool(preview.get("broker_connection_enabled", False)),
        submit_orders=bool(preview.get("submit_orders", False)),
        paper_trading_approval=bool(preview.get("paper_trading_approval", False)),
        default_order_type=str(preview.get("default_order_type", "limit")),
        allowed_order_types=tuple(str(item) for item in preview.get("allowed_order_types", ["limit"])),
        breakout_order_type=str(preview.get("breakout_order_type", "trigger_limit")),
        regular_hours_only=bool(preview.get("regular_hours_only", True)),
        max_orders_per_day=int(preview.get("max_orders_per_day", 5)),
        max_risk_per_order=decimal(preview.get("max_risk_per_order", "12")),
        quantity_policy=str(preview.get("quantity_policy", "preserve_local_sim_quantity")),
        paper_account_equity=decimal(account_model.get("equity", "6000")),
        max_total_exposure=decimal(account_model.get("max_total_exposure", "3600")),
        min_cash_reserve=decimal(account_model.get("min_cash_reserve", "2400")),
        max_symbol_exposure=decimal(account_model.get("max_symbol_exposure", "600")),
        allow_fractional_shares=bool(account_model.get("allow_fractional_shares", False)),
        allow_short_selling=bool(account_model.get("allow_short_selling", False)),
        allow_options=bool(account_model.get("allow_options", False)),
        risk_tiers=risk_tiers,
        primary_runtime_ids=tuple(str(item) for item in preview.get("primary_runtime_ids", ["M10-PA-004-long-1d"])),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: AllStrategyOrderPreviewConfig) -> None:
    if config.stage != "M15.all_strategy_order_preview":
        raise ValueError("M15 all-strategy order preview stage drift")
    if config.token_mode != "paper":
        raise ValueError("M15 order preview must stay paper-token-only")
    if config.live_token_allowed:
        raise ValueError("M15 order preview cannot allow live token")
    if config.broker_connection_enabled:
        raise ValueError("M15 order preview cannot enable broker_connection")
    if config.submit_orders:
        raise ValueError("M15 order preview cannot submit orders")
    if config.paper_trading_approval:
        raise ValueError("M15 order preview cannot approve paper trading")
    supported_order_types = {"limit", "trigger_limit"}
    if config.default_order_type not in supported_order_types:
        raise ValueError("M15 order preview default order type must be limit or trigger_limit")
    if not config.allowed_order_types:
        raise ValueError("M15 order preview must define allowed_order_types")
    unsupported = sorted(set(config.allowed_order_types) - supported_order_types)
    if unsupported:
        raise ValueError(f"M15 order preview has unsupported order types: {unsupported}")
    if config.breakout_order_type not in set(config.allowed_order_types):
        raise ValueError("M15 order preview breakout order type must be allowed")
    if config.allow_fractional_shares:
        raise ValueError("M15 order preview currently forbids fractional shares")
    if config.allow_short_selling:
        raise ValueError("M15 order preview currently forbids short selling")
    if config.allow_options:
        raise ValueError("M15 order preview currently forbids options")
    if not config.regular_hours_only:
        raise ValueError("M15 order preview must stay US regular-hours only")
    if config.paper_account_equity <= ZERO:
        raise ValueError("M15 order preview must define positive paper account equity")
    if config.max_total_exposure <= ZERO:
        raise ValueError("M15 order preview must define positive max total exposure")
    if config.max_orders_per_day <= 0:
        raise ValueError("M15 order preview must define positive max_orders_per_day")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 order preview must stay paper/simulated only")
    for key in (
        "broker_connection",
        "real_order",
        "live_execution",
        "paper_trading_approval",
        "credential_read",
        "manual_m12_37_once",
    ):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M15 order preview cannot enable {key}")


def run_all_strategy_order_preview(
    config: AllStrategyOrderPreviewConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary, ledger_rows = build_all_strategy_order_preview(config, generated_at)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / SUMMARY_JSON, summary)
    write_jsonl(config.output_dir / LEDGER_JSONL, ledger_rows)
    (config.output_dir / REPORT_MD).write_text(render_markdown(summary, ledger_rows), encoding="utf-8")
    return summary


def build_all_strategy_order_preview(
    config: AllStrategyOrderPreviewConfig,
    generated_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dashboard = read_json(config.dashboard_path)
    runtime_state = read_json(config.runtime_state_path)
    paper_gate = read_json(config.paper_gate_path)
    m14_summary = read_json(config.paper_gate_path.with_name("m14_strategy_challenge_summary.json"))
    dashboard_summary = dashboard.get("summary", dashboard) if isinstance(dashboard.get("summary", dashboard), dict) else {}
    scan_date = str(dashboard_summary.get("scan_date", ""))
    quote_source = str(dashboard_summary.get("quote_source", ""))
    m14_trading_date = str(m14_summary.get("trading_date", ""))
    fallback_or_no_fetch = text_has_fallback_or_no_fetch(
        quote_source,
        dashboard_summary.get("data_freshness_warning", ""),
        dashboard_summary.get("data_quality_state", ""),
        m14_summary.get("data_freshness_warning", ""),
        m14_summary.get("data_quality_state", ""),
    )
    current_day_blockers = build_current_day_blockers(scan_date, m14_trading_date)
    quote_source_blockers = quote_source_blockers_for(quote_source, fallback_or_no_fetch)

    m12_rows = current_day_trade_rows(read_jsonl(config.account_trade_ledger_path), scan_date)
    m13_rows = current_day_trade_rows(read_jsonl(config.account_operation_ledger_path), scan_date)
    m13_index = build_m13_match_index(m13_rows)
    gate_rows = list(paper_gate.get("rows", []))
    gate_by_runtime = {str(row.get("runtime_id", "")): row for row in gate_rows if row.get("runtime_id")}
    accounts = runtime_state.get("accounts", {}) if isinstance(runtime_state.get("accounts", {}), dict) else {}
    ledger_rows = [
        build_preview_row(config, generated_at, row, gate_by_runtime.get(str(row.get("runtime_id", "")), {}), m13_index)
        for row in m12_rows
    ]
    apply_shared_account_caps(ledger_rows, config)
    runtime_rows = build_runtime_rows(accounts, gate_rows, m12_rows, ledger_rows)
    auxiliary_rows = build_auxiliary_rows(gate_rows)
    summary_counts = build_summary_counts(runtime_rows, auxiliary_rows, ledger_rows)
    preview_status = preview_status_for(summary_counts, quote_source_blockers, current_day_blockers)
    payload = {
        "schema_version": "m15.all-strategy-order-preview.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at,
        "input_refs": {
            "m12_32_dashboard": project_path(config.dashboard_path),
            "m12_46_account_runtime_state": project_path(config.runtime_state_path),
            "m12_46_account_trade_ledger": project_path(config.account_trade_ledger_path),
            "m13_account_operation_ledger": project_path(config.account_operation_ledger_path),
            "m14_paper_trial_gate": project_path(config.paper_gate_path),
        },
        "output_refs": {
            "summary": project_path(config.output_dir / SUMMARY_JSON),
            "order_preview_ledger": project_path(config.output_dir / LEDGER_JSONL),
            "markdown_report": project_path(config.output_dir / REPORT_MD),
        },
        "scan_date": scan_date,
        "quote_source": quote_source,
        "fallback_or_no_fetch_data": fallback_or_no_fetch,
        "quote_source_blockers": quote_source_blockers,
        "m14_trading_date": m14_trading_date,
        "current_day_blockers": current_day_blockers,
        "preview_status": preview_status,
        "summary": summary_counts,
        "runtime_rows": runtime_rows,
        "auxiliary_modules": auxiliary_rows,
        "sample_order_previews": ledger_rows[:30],
        "comparison_summary": build_comparison_summary(ledger_rows),
        "longbridge_paper_preview_policy": {
            "paper_token_only": True,
            "token_mode": config.token_mode,
            "live_token_allowed": False,
            "broker_connection_enabled": False,
            "submit_orders": False,
            "paper_trading_approval": False,
            "default_order_type": config.default_order_type,
            "allowed_order_types": list(config.allowed_order_types),
            "breakout_order_type": config.breakout_order_type,
            "regular_hours_only": config.regular_hours_only,
            "max_orders_per_day": config.max_orders_per_day,
            "quantity_policy": config.quantity_policy,
            "paper_account_equity": fmt_money(config.paper_account_equity),
            "max_total_exposure": fmt_money(config.max_total_exposure),
            "min_cash_reserve": fmt_money(config.min_cash_reserve),
            "max_symbol_exposure": fmt_money(config.max_symbol_exposure),
            "allow_fractional_shares": config.allow_fractional_shares,
            "allow_short_selling": config.allow_short_selling,
            "allow_options": config.allow_options,
            "max_risk_per_order": fmt_money(config.max_risk_per_order),
        },
        "hard_boundaries": {
            "paper_simulated_only": True,
            "local_record_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
            "credential_read": False,
            "manual_m12_37_once": False,
        },
        "plain_language_result": plain_language_result(preview_status, summary_counts, quote_source_blockers, current_day_blockers),
    }
    assert_no_legacy_profit_fields(payload, ledger_rows)
    return payload, ledger_rows


def current_day_trade_rows(rows: list[dict[str, Any]], scan_date: str) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("trading_date", "")) == scan_date and str(row.get("event_type", "")) in {"open", "close"}
    ]


def build_m13_match_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str, str], deque[dict[str, Any]]]:
    index: dict[tuple[str, str, str, str, str], deque[dict[str, Any]]] = defaultdict(deque)
    for row in rows:
        index[match_key(row)].append(row)
    return index


def build_preview_row(
    config: AllStrategyOrderPreviewConfig,
    generated_at: str,
    source_row: dict[str, Any],
    gate_row: dict[str, Any],
    m13_index: dict[tuple[str, str, str, str, str], deque[dict[str, Any]]],
) -> dict[str, Any]:
    event_type = str(source_row.get("event_type", ""))
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
        event_type=event_type,
        price=price,
        stop_price=stop_price,
        tier=tier,
        tier_policy=tier_policy,
    )
    risk_amount = estimated_open_risk(event_type, price, stop_price, quantity)
    order_type = infer_order_type(source_row, config)
    matched = pop_m13_match(source_row, m13_index)
    comparison = compare_m13(source_row, matched)
    blockers = order_blockers(config, source_row, gate_row, price, source_quantity, quantity, risk_amount, tier_policy)
    preview_status = order_preview_status(gate_row, blockers)
    runtime_id = str(source_row.get("runtime_id", ""))
    strategy_id = str(source_row.get("strategy_id", ""))
    symbol = str(source_row.get("symbol", ""))
    signal_time = str(source_row.get("signal_time", ""))
    row = {
        "schema_version": "m15.all-strategy-order-preview-row.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "preview_id": preview_id(runtime_id, symbol, event_type, signal_time, price, quantity),
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
        "local_event_type": event_type,
        "order_intent": "开仓" if event_type == "open" else "平仓",
        "direction": direction,
        "broker_order_side": broker_order_side(event_type, direction),
        "order_type": order_type,
        "allowed_order_types": list(config.allowed_order_types),
        "breakout_order_type": config.breakout_order_type,
        "limit_price": fmt_decimal(price),
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
        "paper_account_equity": fmt_money(config.paper_account_equity),
        "max_total_exposure": fmt_money(config.max_total_exposure),
        "max_symbol_exposure": fmt_money(config.max_symbol_exposure),
        "risk_tier": tier,
        "max_strategy_exposure": fmt_money(tier_policy["max_strategy_exposure"]),
        "max_risk_per_order": fmt_money(tier_policy["max_risk_per_order"]),
        "m13_comparison_status": comparison["status"],
        "m13_comparison_notes": comparison["notes"],
        "longbridge_paper_order_preview_status": preview_status,
        "blockers": blockers,
        "local_record_only": True,
        "paper_token_required_before_connection": True,
        "broker_connection_attempted": False,
        "order_submitted": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    return row


def order_blockers(
    config: AllStrategyOrderPreviewConfig,
    source_row: dict[str, Any],
    gate_row: dict[str, Any],
    price: Decimal,
    source_quantity: Decimal,
    quantity: Decimal,
    risk_amount: Decimal,
    tier_policy: dict[str, Decimal],
) -> list[str]:
    blockers = ["broker_connection_disabled", "order_submission_disabled", "paper_trading_approval_false"]
    if not gate_row:
        blockers.append("runtime_not_in_current_m14_gate")
    action_state = str(gate_row.get("action_state", ""))
    if action_state == "repair_now":
        blockers.append("repair_runtime_submit_blocked")
    elif action_state == "auxiliary_module":
        blockers.append("auxiliary_module_no_order")
    elif action_state == "pause_runtime":
        blockers.append("paused_runtime_submit_blocked")
    if price <= ZERO:
        blockers.append("missing_limit_price")
    if source_quantity <= ZERO:
        blockers.append("missing_quantity")
    if quantity <= ZERO:
        blockers.append("integer_quantity_below_one")
    direction = normalize_direction(str(source_row.get("direction", "")))
    event_type = str(source_row.get("event_type", ""))
    if direction == "看跌":
        blockers.append("short_selling_disabled")
    notional = price * quantity
    if event_type == "close":
        blockers.append("close_requires_existing_paper_position")
    if event_type == "open":
        if notional > config.max_symbol_exposure:
            blockers.append("symbol_exposure_over_6000_account_cap")
        if notional > tier_policy["max_strategy_exposure"]:
            blockers.append("strategy_tier_exposure_over_cap")
    if str(source_row.get("event_type", "")) == "open":
        if decimal(source_row.get("stop_price", "0")) <= ZERO:
            blockers.append("missing_stop_price")
        if decimal(source_row.get("target_price", "0")) <= ZERO:
            blockers.append("missing_target_price")
        if risk_amount > tier_policy["max_risk_per_order"]:
            blockers.append("risk_over_preview_cap")
    return blockers


def order_preview_status(gate_row: dict[str, Any], blockers: list[str]) -> str:
    hard = {
        "missing_limit_price",
        "missing_quantity",
        "integer_quantity_below_one",
        "missing_stop_price",
        "missing_target_price",
    }
    if any(blocker in hard for blocker in blockers):
        return "blocked_missing_order_fields"
    action_state = str(gate_row.get("action_state", ""))
    if action_state == "repair_now":
        return "repair_runtime_order_preview_created_submit_blocked"
    if "close_requires_existing_paper_position" in blockers:
        return "local_order_preview_created_close_position_unmapped"
    if "short_selling_disabled" in blockers:
        return "local_order_preview_created_short_disabled"
    if (
        "strategy_tier_exposure_over_cap" in blockers
        or "symbol_exposure_over_6000_account_cap" in blockers
        or "shared_account_total_exposure_over_6000_cap" in blockers
        or "shared_symbol_exposure_over_6000_cap" in blockers
        or "shared_strategy_tier_exposure_over_cap" in blockers
    ):
        return "local_order_preview_created_6000_account_size_blocked"
    if "risk_over_preview_cap" in blockers:
        return "local_order_preview_created_risk_cap_blocked"
    if action_state in {"advance_internal_sim", "risk_limited_advance", "paper_candidate"}:
        return "local_order_preview_created_ready_after_user_approval"
    if not gate_row:
        return "local_order_preview_created_gate_unmapped"
    return "local_order_preview_created_submit_blocked"


def build_runtime_rows(
    accounts: dict[str, Any],
    gate_rows: list[dict[str, Any]],
    m12_rows: list[dict[str, Any]],
    preview_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gate_by_runtime = {str(row.get("runtime_id", "")): row for row in gate_rows if row.get("runtime_id")}
    source_by_runtime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    preview_by_runtime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in m12_rows:
        source_by_runtime[str(row.get("runtime_id", ""))].append(row)
    for row in preview_rows:
        preview_by_runtime[str(row.get("runtime_id", ""))].append(row)
    runtime_ids = sorted(set(accounts) | set(gate_by_runtime) | set(source_by_runtime))
    rows: list[dict[str, Any]] = []
    for runtime_id in runtime_ids:
        gate = gate_by_runtime.get(runtime_id, {})
        account = accounts.get(runtime_id, {}) if isinstance(accounts.get(runtime_id, {}), dict) else {}
        source_rows = source_by_runtime.get(runtime_id, [])
        previews = preview_by_runtime.get(runtime_id, [])
        if str(gate.get("runtime_role", "")) == "auxiliary_module":
            continue
        rows.append(
            {
                "runtime_id": runtime_id,
                "strategy_id": str(account.get("strategy_id") or gate.get("strategy_id", "")),
                "display_name": str(account.get("display_name") or gate.get("display_name", "")),
                "timeframe": str(account.get("timeframe") or gate.get("timeframe", "")),
                "lane": str(account.get("lane", "")),
                "runtime_role": "trading_runtime",
                "gate_action_state": str(gate.get("action_state", "not_in_current_m14_gate")),
                "gate_display_action": str(gate.get("display_action", "")),
                "position_size_multiplier": str(gate.get("position_size_multiplier", "")),
                "local_open_order_count": sum(1 for row in source_rows if row.get("event_type") == "open"),
                "local_close_order_count": sum(1 for row in source_rows if row.get("event_type") == "close"),
                "order_preview_count": len(previews),
                "submit_allowed": False,
                "broker_connection_attempted": False,
                "local_record_status": local_record_status(gate, previews),
            }
        )
    return rows


def build_auxiliary_rows(gate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in gate_rows:
        if str(row.get("runtime_role", "")) != "auxiliary_module":
            continue
        rows.append(
            {
                "runtime_id": str(row.get("runtime_id", "")),
                "strategy_id": str(row.get("strategy_id", "")),
                "display_name": str(row.get("display_name", "")),
                "runtime_role": "auxiliary_module",
                "display_action": str(row.get("display_action", "")),
                "auxiliary_module_purpose": str(row.get("auxiliary_module_purpose", "")),
                "standalone_trading_allowed": False,
                "order_preview_count": 0,
                "submit_allowed": False,
            }
        )
    return rows


def local_record_status(gate: dict[str, Any], previews: list[dict[str, Any]]) -> str:
    if previews:
        return "已生成本地订单草稿"
    if str(gate.get("action_state", "")) == "repair_now":
        return "修复运行单元本次没有本地新订单"
    if str(gate.get("action_state", "")) in {"advance_internal_sim", "risk_limited_advance", "paper_candidate"}:
        return "推进运行单元本次没有本地新订单"
    return "本次没有本地新订单"


def build_summary_counts(
    runtime_rows: list[dict[str, Any]],
    auxiliary_rows: list[dict[str, Any]],
    preview_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    action_counts = Counter(row["gate_action_state"] for row in runtime_rows)
    status_counts = Counter(row["longbridge_paper_order_preview_status"] for row in preview_rows)
    side_counts = Counter(row["broker_order_side"] for row in preview_rows)
    comparison_counts = Counter(row["m13_comparison_status"] for row in preview_rows)
    risk_tier_counts = Counter(row.get("risk_tier", "") for row in preview_rows)
    ready_after_approval = [
        row
        for row in preview_rows
        if row["longbridge_paper_order_preview_status"] == "local_order_preview_created_ready_after_user_approval"
    ]
    ready_notional = sum((decimal(row.get("notional", "0")) for row in ready_after_approval), ZERO)
    return {
        "trading_runtime_count": len(runtime_rows),
        "auxiliary_module_count": len(auxiliary_rows),
        "runtime_with_order_preview_count": sum(1 for row in runtime_rows if row["order_preview_count"] > 0),
        "runtime_without_order_preview_count": sum(1 for row in runtime_rows if row["order_preview_count"] == 0),
        "order_preview_count": len(preview_rows),
        "open_order_preview_count": sum(1 for row in preview_rows if row["local_event_type"] == "open"),
        "close_order_preview_count": sum(1 for row in preview_rows if row["local_event_type"] == "close"),
        "action_state_counts": dict(sorted(action_counts.items())),
        "order_preview_status_counts": dict(sorted(status_counts.items())),
        "broker_order_side_counts": dict(sorted(side_counts.items())),
        "risk_tier_counts": dict(sorted(risk_tier_counts.items())),
        "m13_comparison_status_counts": dict(sorted(comparison_counts.items())),
        "ready_after_user_approval_count": len(ready_after_approval),
        "long_only_ready_after_user_approval_count": sum(1 for row in ready_after_approval if row["broker_order_side"] in {"buy", "sell"}),
        "ready_after_user_approval_notional": fmt_money(ready_notional),
        "submit_allowed_count": 0,
        "broker_connection_attempted": False,
        "order_submitted": False,
    }


def apply_shared_account_caps(preview_rows: list[dict[str, Any]], config: AllStrategyOrderPreviewConfig) -> None:
    total_open_notional = ZERO
    runtime_open_notional: dict[str, Decimal] = defaultdict(lambda: ZERO)
    symbol_open_notional: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in preview_rows:
        if row["longbridge_paper_order_preview_status"] != "local_order_preview_created_ready_after_user_approval":
            continue
        if row["local_event_type"] != "open" or row["broker_order_side"] != "buy":
            continue
        notional = decimal(row.get("notional", "0"))
        runtime_id = row["runtime_id"]
        symbol = row["symbol"]
        blockers = list(row.get("blockers", []))
        if int(sum(1 for item in preview_rows if item["longbridge_paper_order_preview_status"] == "local_order_preview_created_ready_after_user_approval" and item.get("_accepted_daily_order"))) >= config.max_orders_per_day:
            blockers.append("daily_order_count_over_6000_account_cap")
        if total_open_notional + notional > config.max_total_exposure:
            blockers.append("shared_account_total_exposure_over_6000_cap")
        if symbol_open_notional[symbol] + notional > config.max_symbol_exposure:
            blockers.append("shared_symbol_exposure_over_6000_cap")
        if runtime_open_notional[runtime_id] + notional > decimal(row.get("max_strategy_exposure", "0")):
            blockers.append("shared_strategy_tier_exposure_over_cap")
        if blockers != row.get("blockers", []):
            row["blockers"] = blockers
            row["longbridge_paper_order_preview_status"] = "local_order_preview_created_6000_account_size_blocked"
            continue
        row["_accepted_daily_order"] = True
        total_open_notional += notional
        runtime_open_notional[runtime_id] += notional
        symbol_open_notional[symbol] += notional
    for row in preview_rows:
        row.pop("_accepted_daily_order", None)


def build_comparison_summary(preview_rows: list[dict[str, Any]]) -> dict[str, Any]:
    mismatches = [row for row in preview_rows if row["m13_comparison_status"] != "matched"]
    return {
        "matched_count": sum(1 for row in preview_rows if row["m13_comparison_status"] == "matched"),
        "mismatch_or_missing_count": len(mismatches),
        "mismatch_samples": [
            {
                "runtime_id": row["runtime_id"],
                "symbol": row["symbol"],
                "local_event_type": row["local_event_type"],
                "status": row["m13_comparison_status"],
                "notes": row["m13_comparison_notes"],
            }
            for row in mismatches[:20]
        ],
    }


def preview_status_for(
    summary_counts: dict[str, Any],
    quote_source_blockers: list[str],
    current_day_blockers: list[str],
) -> str:
    if quote_source_blockers:
        return "blocked_quote_source_order_preview_only"
    if current_day_blockers:
        return "local_preview_created_m14_stale_submit_blocked"
    if summary_counts["order_preview_count"] == 0:
        return "no_local_orders_to_preview"
    return "local_preview_created_for_all_strategy_orders"


def quote_source_blockers_for(quote_source: str, fallback_or_no_fetch: bool) -> list[str]:
    if fallback_or_no_fetch:
        return ["fallback_or_no_fetch_data"]
    if quote_source != "longbridge_quote_readonly":
        return ["quote_source_not_longbridge_readonly" if quote_source else "quote_source_missing"]
    return []


def build_current_day_blockers(scan_date: str, m14_trading_date: str) -> list[str]:
    if scan_date and m14_trading_date and scan_date != m14_trading_date:
        return ["m14_not_recomputed_for_current_scan_date"]
    return []


def plain_language_result(
    status: str,
    summary_counts: dict[str, Any],
    quote_source_blockers: list[str],
    current_day_blockers: list[str],
) -> str:
    base = (
        f"已为 {summary_counts['trading_runtime_count']} 个交易运行单元做长桥模拟账户格式的本地订单预演，"
        f"生成 {summary_counts['order_preview_count']} 条订单草稿，其中开仓 {summary_counts['open_order_preview_count']} 条、"
        f"平仓 {summary_counts['close_order_preview_count']} 条；{summary_counts['auxiliary_module_count']} 个辅助模块不单独生成订单。"
        f" 按 6000 美元共享资金、整股、只做多规则筛选后，{summary_counts.get('ready_after_user_approval_count', 0)} 条草稿可在用户批准后进入模拟账户提交链路。"
    )
    if status == "local_preview_created_for_all_strategy_orders":
        return base + " 当前只写本地账本，不连接账户、不下单。"
    if status == "local_preview_created_m14_stale_submit_blocked":
        return base + f" 但策略分层日期还没追上当前看板日期：{', '.join(current_day_blockers)}，所以只能预演，不能提交。"
    if status == "blocked_quote_source_order_preview_only":
        return base + f" 但行情来源不满足长桥只读要求：{', '.join(quote_source_blockers)}，所以只能留作本地对比。"
    return base + " 本次没有可提交动作，仍保持只读和本地记录。"


def match_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("runtime_id", "")),
        str(row.get("symbol", "")),
        str(row.get("timeframe", "")),
        str(row.get("event_type", "")),
        row_time_key(row),
    )


def row_time_key(row: dict[str, Any]) -> str:
    return str(row.get("source_event_time") or row.get("event_time") or row.get("signal_time") or "")


def pop_m13_match(
    source_row: dict[str, Any],
    m13_index: dict[tuple[str, str, str, str, str], deque[dict[str, Any]]],
) -> dict[str, Any] | None:
    bucket = m13_index.get(match_key(source_row))
    if not bucket:
        return None
    return bucket.popleft()


def compare_m13(source_row: dict[str, Any], matched: dict[str, Any] | None) -> dict[str, Any]:
    if matched is None:
        return {"status": "missing_m13_operation", "notes": ["M13 当天账本没有匹配这条 M12 本地模拟订单"]}
    notes: list[str] = []
    source_qty = decimal(source_row.get("quantity", "0"))
    matched_qty = decimal(matched.get("quantity", "0"))
    if abs(source_qty - matched_qty) > Decimal("0.0001"):
        notes.append("数量和 M13 账本不一致")
    source_price = order_price(source_row)
    matched_price = order_price(matched)
    if abs(source_price - matched_price) > Decimal("0.0001"):
        notes.append("价格和 M13 账本不一致")
    if notes:
        return {"status": "mismatch", "notes": notes}
    return {"status": "matched", "notes": ["M12 本地订单和 M13 当天账本一致"]}


def order_price(row: dict[str, Any]) -> Decimal:
    if str(row.get("event_type", "")) == "close":
        return decimal(row.get("exit_price", "0"))
    return decimal(row.get("entry_price", "0"))


def broker_order_side(event_type: str, direction: str) -> str:
    if event_type == "open":
        return "buy" if direction == "看涨" else "sell_short"
    return "sell" if direction == "看涨" else "buy_to_cover"


def estimated_open_risk(event_type: str, entry_price: Decimal, stop_price: Decimal, quantity: Decimal) -> Decimal:
    if event_type != "open" or entry_price <= ZERO or stop_price <= ZERO or quantity <= ZERO:
        return ZERO
    return abs(entry_price - stop_price) * quantity


def paper_order_quantity(
    source_quantity: Decimal,
    config: AllStrategyOrderPreviewConfig,
    *,
    event_type: str,
    price: Decimal,
    stop_price: Decimal,
    tier: str,
    tier_policy: dict[str, Decimal],
) -> Decimal:
    if source_quantity <= ZERO:
        return ZERO
    if config.allow_fractional_shares or config.quantity_policy == "preserve_local_sim_quantity":
        return source_quantity
    if config.quantity_policy == "integer_floor_no_fractional":
        local_integer = source_quantity.to_integral_value(rounding=ROUND_FLOOR)
        if event_type != "open" or tier == "repair":
            return local_integer
        candidates = [local_integer]
        if price > ZERO:
            candidates.append((tier_policy["max_strategy_exposure"] / price).to_integral_value(rounding=ROUND_FLOOR))
            candidates.append((config.max_symbol_exposure / price).to_integral_value(rounding=ROUND_FLOOR))
            candidates.append((config.max_total_exposure / price).to_integral_value(rounding=ROUND_FLOOR))
        risk_per_share = abs(price - stop_price)
        if risk_per_share > ZERO:
            candidates.append((tier_policy["max_risk_per_order"] / risk_per_share).to_integral_value(rounding=ROUND_FLOOR))
        return max(min(candidates), ZERO)
    raise ValueError(f"Unsupported quantity policy: {config.quantity_policy}")


def infer_order_type(source_row: dict[str, Any], config: AllStrategyOrderPreviewConfig) -> str:
    explicit = str(source_row.get("order_type") or source_row.get("entry_order_type") or "").strip()
    if explicit in set(config.allowed_order_types):
        return explicit
    text = " ".join(
        str(source_row.get(key, ""))
        for key in (
            "entry_style",
            "entry_trigger",
            "setup",
            "pattern",
            "signal_label",
            "runtime_repair_policy",
            "strategy_id",
            "runtime_id",
        )
    ).lower()
    if any(token in text for token in ("breakout", "突破", "follow-through", "follow_through")):
        return config.breakout_order_type
    return config.default_order_type


def runtime_risk_tier(
    source_row: dict[str, Any],
    gate_row: dict[str, Any],
    config: AllStrategyOrderPreviewConfig,
) -> str:
    action_state = str(gate_row.get("action_state", ""))
    runtime_id = str(source_row.get("runtime_id") or gate_row.get("runtime_id", ""))
    if action_state == "repair_now":
        return "repair"
    if runtime_id in set(config.primary_runtime_ids):
        return "primary"
    if action_state == "risk_limited_advance":
        return "risk_limited"
    if action_state in {"advance_internal_sim", "paper_candidate"}:
        return "standard"
    return "repair"


def risk_tier_policy(tier: str, config: AllStrategyOrderPreviewConfig) -> dict[str, Decimal]:
    defaults = {
        "primary": {"max_strategy_exposure": Decimal("900"), "max_risk_per_order": Decimal("12")},
        "standard": {"max_strategy_exposure": Decimal("600"), "max_risk_per_order": Decimal("8")},
        "risk_limited": {"max_strategy_exposure": Decimal("450"), "max_risk_per_order": Decimal("6")},
        "repair": {"max_strategy_exposure": ZERO, "max_risk_per_order": ZERO},
    }
    policy = dict(defaults.get(tier, defaults["repair"]))
    policy.update(config.risk_tiers.get(tier, {}))
    return policy


def normalize_direction(value: str) -> str:
    text = value.strip().lower()
    if text in {"long", "bullish", "buy", "看涨"}:
        return "看涨"
    if text in {"short", "bearish", "sell_short", "看跌"}:
        return "看跌"
    return value or "未知"


def preview_id(runtime_id: str, symbol: str, event_type: str, signal_time: str, price: Decimal, quantity: Decimal) -> str:
    digest = sha256(f"{runtime_id}|{symbol}|{event_type}|{signal_time}|{price}|{quantity}".encode("utf-8")).hexdigest()[:16]
    return f"m15-order-preview-{digest}"


def text_has_fallback_or_no_fetch(*values: Any) -> bool:
    text = " ".join(str(value).lower() for value in values)
    return any(token in text for token in ("fallback", "no-fetch", "no_fetch", "no-refresh", "no_refresh", "旧快照"))


def decimal(value: Any) -> Decimal:
    try:
        if value in (None, ""):
            return ZERO
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if text == "-0" else text


def fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY))


def render_markdown(summary: dict[str, Any], ledger_rows: list[dict[str, Any]]) -> str:
    counts = summary["summary"]
    lines = [
        "# 全策略长桥模拟账户订单预演",
        "",
        f"- 状态：`{summary['preview_status']}`",
        f"- 看板日期：`{summary['scan_date']}`",
        f"- 行情来源：`{summary['quote_source']}`",
        f"- 人话结论：{summary['plain_language_result']}",
        "",
        "## 边界",
        "",
        "- 只写本地订单草稿：是",
        "- 连接长桥账户：否",
        "- 读取凭证：否",
        "- 提交订单：否",
        "- 实盘执行：否",
        "- 手动运行 M12.37：否",
        "- 账户口径：6000 美元共享模拟资金",
        "- 碎股：不做，数量向下取整，低于 1 股只保留草稿",
        "- 做空/期权：不做，看空开仓只记录不提交",
        "- 订单类型：允许普通限价单和突破触发限价单",
        "",
        "## 汇总",
        "",
        f"- 交易运行单元：`{counts['trading_runtime_count']}`",
        f"- 辅助模块：`{counts['auxiliary_module_count']}`",
        f"- 订单草稿：`{counts['order_preview_count']}`",
        f"- 开仓草稿：`{counts['open_order_preview_count']}`",
        f"- 平仓草稿：`{counts['close_order_preview_count']}`",
        f"- 用户批准后可进入提交链路的草稿：`{counts.get('ready_after_user_approval_count', 0)}`",
        f"- 这些草稿名义金额：`{counts.get('ready_after_user_approval_notional', '0.00')}`",
        f"- M13 对比一致：`{summary['comparison_summary']['matched_count']}`",
        f"- M13 对比缺失或不一致：`{summary['comparison_summary']['mismatch_or_missing_count']}`",
        "",
        "## 运行单元",
        "",
        "| 运行单元 | 策略 | 状态 | 草稿数 | 开仓 | 平仓 | 本地记录状态 |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in summary["runtime_rows"]:
        lines.append(
            f"| {row['runtime_id']} | {row['strategy_id']} | {row['gate_action_state']} | {row['order_preview_count']} | "
            f"{row['local_open_order_count']} | {row['local_close_order_count']} | {row['local_record_status']} |"
        )
    lines.extend(
        [
            "",
            "## 辅助模块",
            "",
            "| 模块 | 用途 | 独立交易 |",
            "| --- | --- | --- |",
        ]
    )
    for row in summary["auxiliary_modules"]:
        lines.append(f"| {row['runtime_id']} | {row['auxiliary_module_purpose']} | 否 |")
    lines.extend(
        [
            "",
            "## 订单草稿样例",
            "",
            "| 意图 | 运行单元 | 标的 | 方向 | 动作 | 档位 | 本地数量 | 整股数量 | 限价 | 风险 | 状态 |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in ledger_rows[:50]:
        lines.append(
            f"| {row['order_intent']} | {row['runtime_id']} | {row['symbol']} | {row['direction']} | {row['broker_order_side']} | "
            f"{row['risk_tier']} | {row['source_quantity']} | {row['quantity']} | {row['limit_price']} | "
            f"{row['estimated_open_risk']} | {row['longbridge_paper_order_preview_status']} |"
        )
    lines.append("")
    return "\n".join(lines)


def assert_no_legacy_profit_fields(payload: dict[str, Any], ledger_rows: list[dict[str, Any]]) -> None:
    text = json.dumps(payload, ensure_ascii=False) + json.dumps(ledger_rows, ensure_ascii=False)
    forbidden = ("historical_net_profit", "历史净利润", "历史收益", "历史盈利因子")
    found = [token for token in forbidden if token in text]
    if found:
        raise ValueError(f"legacy historical profit fields leaked into all-strategy order preview: {found}")


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
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
