#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from scripts.longbridge_cli_env import build_longbridge_cli_env
from scripts.m12_readonly_auth_preflight_lib import clean_cli_text
from scripts.m15_longbridge_realtime_execution_lib import DEFAULT_DAILY_DIR, project_path, to_iso
from scripts.m15_longbridge_fill_attribution_lib import (
    DEFAULT_COMMISSION_PER_ORDER_SIDE,
    DEFAULT_REGULATORY_FEE_PER_SELL_ORDER,
    add_completed_trade_performance,
    apply_aggregate_strategy_exit_fill_allocations,
    apply_account_flatten_fill_allocations,
    apply_account_reconciliation_adjustments,
    broker_fill_rows_from_orders_and_executions,
    rebuild_fill_attribution_from_history,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_account_state.json"
ACCOUNT_STATE_JSON = "m15_longbridge_realtime_account_state.json"
SUMMARY_JSON = "m15_longbridge_realtime_account_state_summary.json"
PNL_RECONCILIATION_JSON = "m15_longbridge_account_pnl_reconciliation.json"
TRUSTED_PNL_RECONCILIATION_JSON = "m15_longbridge_last_trustworthy_pnl_reconciliation.json"
TRUSTED_ORDER_HISTORY_JSON = "m15_longbridge_last_trustworthy_order_history.json"
PNL_RECONCILIATION_MD = "m15_longbridge_account_pnl_reconciliation.md"
ORDER_RECONCILIATION_JSON = "m15_longbridge_order_reconciliation.json"
UNFILLED_ORDER_DIAGNOSTICS_JSON = "m15_longbridge_unfilled_order_diagnostics.json"
FILL_ATTRIBUTION_JSON = "m15_longbridge_fill_attribution_v2.json"
ORDER_DETAIL_CACHE_JSON = "m15_longbridge_order_detail_cache.json"
LEDGER_JSONL = "m15_longbridge_realtime_account_state_ledger.jsonl"
EQUITY_CURVE_JSONL = "m15_longbridge_realtime_equity_curve.jsonl"
REPORT_MD = "m15_longbridge_realtime_account_state.md"
REALTIME_EXECUTION_LEDGER_JSONL = "m15_longbridge_realtime_execution_ledger.jsonl"
STALE_ORDER_CLEANUP_LEDGER_JSONL = "m15_longbridge_realtime_stale_order_cleanup_ledger.jsonl"
MONEY = Decimal("0.01")
ZERO = Decimal("0")
NEW_YORK_TZ = ZoneInfo("America/New_York")
SYSTEM_FAULT_BLOCKERS = {
    "blocked_account_state_stale",
    "blocked_non_paper_account",
    "blocked_delayed_signal_age_over_limit",
    "blocked_delayed_signal_missing_revalidation_price",
}
STRATEGY_TEST_EPOCH_PREFIXES = (
    "m15-sdk-formal-",
    "m15-short-single-strategy-",
    "m15-sdk-contract-v1-",
    "m15-sdk-validation-",
)

CommandRunner = Callable[[list[str]], Any]


def strategy_test_epoch_id(value: str) -> bool:
    return value.startswith(STRATEGY_TEST_EPOCH_PREFIXES)


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class RealtimeAccountStateConfig:
    stage: str
    title: str
    output_dir: Path
    account_state_path: Path
    cli_name: str
    required_account_channel: str
    cli_timeout_seconds: int
    historical_order_start_date: str
    unfilled_order_detail_lookup_limit: int
    hard_boundaries: dict[str, bool]
    historical_cli_timeout_seconds: int = 30
    historical_refresh_interval_seconds: int = 300
    commission_per_order_side: Decimal = DEFAULT_COMMISSION_PER_ORDER_SIDE
    regulatory_fee_per_sell_order: Decimal = DEFAULT_REGULATORY_FEE_PER_SELL_ORDER

    def __post_init__(self) -> None:
        validate_config(self)


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RealtimeAccountStateConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    outputs = payload.get("outputs", {})
    account = payload.get("longbridge_account_state", {})
    fee_model = payload.get("fee_model", {})
    output_dir = resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR))
    return RealtimeAccountStateConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_account_state")),
        title=str(payload.get("title", "长桥模拟账户实时账户状态")),
        output_dir=output_dir,
        account_state_path=resolve_repo_path(outputs.get("account_state", output_dir / ACCOUNT_STATE_JSON)),
        cli_name=str(account.get("cli_name", "longbridge")),
        required_account_channel=str(account.get("required_account_channel", "lb_papertrading")),
        cli_timeout_seconds=int(account.get("cli_timeout_seconds", 6)),
        historical_order_start_date=str(account.get("historical_order_start_date", "2026-06-01")),
        unfilled_order_detail_lookup_limit=int(account.get("unfilled_order_detail_lookup_limit", 120)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
        historical_cli_timeout_seconds=int(account.get("historical_cli_timeout_seconds", 30)),
        historical_refresh_interval_seconds=int(account.get("historical_refresh_interval_seconds", 300)),
        commission_per_order_side=Decimal(
            str(
                fee_model.get(
                    "commission_per_order_side",
                    DEFAULT_COMMISSION_PER_ORDER_SIDE,
                )
            )
        ),
        regulatory_fee_per_sell_order=Decimal(
            str(
                fee_model.get(
                    "regulatory_fee_per_sell_order",
                    DEFAULT_REGULATORY_FEE_PER_SELL_ORDER,
                )
            )
        ),
    )


def validate_config(config: RealtimeAccountStateConfig) -> None:
    if config.stage != "M15.longbridge_realtime_account_state":
        raise ValueError("M15 realtime account state stage drift")
    if config.required_account_channel != "lb_papertrading":
        raise ValueError("M15 realtime account state requires Longbridge paper-trading account channel")
    if config.cli_timeout_seconds <= 0:
        raise ValueError("M15 realtime account state CLI timeout must be positive")
    if not config.historical_order_start_date:
        raise ValueError("M15 realtime account state historical order start date is required")
    if config.unfilled_order_detail_lookup_limit < 0:
        raise ValueError("M15 realtime account state unfilled order detail lookup limit cannot be negative")
    if config.historical_cli_timeout_seconds <= 0:
        raise ValueError("M15 realtime account state historical CLI timeout must be positive")
    if config.historical_refresh_interval_seconds <= 0:
        raise ValueError("M15 realtime account state historical refresh interval must be positive")
    if config.commission_per_order_side < ZERO:
        raise ValueError("M15 realtime account state commission cannot be negative")
    if config.regulatory_fee_per_sell_order < ZERO:
        raise ValueError("M15 realtime account state regulatory fee cannot be negative")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 realtime account state must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("M15 realtime account state cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("M15 realtime account state cannot enable real money actions")
    if config.hard_boundaries.get("local_simulation_as_account_source", False):
        raise ValueError("M15 realtime account state cannot use local simulation as account source")
    if config.hard_boundaries.get("order_submit_or_cancel_commands", False):
        raise ValueError("M15 realtime account state cannot submit or cancel orders")


def longbridge_account_pnl_market_date(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(NEW_YORK_TZ).date().isoformat()


def run_realtime_account_state(
    config: RealtimeAccountStateConfig | None = None,
    *,
    generated_at: str | None = None,
    command_runner: CommandRunner | None = None,
    refresh_historical_order_history: bool = True,
    refresh_analytics: bool = True,
) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    account_pnl_market_date = longbridge_account_pnl_market_date(now)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.account_state_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path = shutil.which(config.cli_name) or config.cli_name
    runner = command_runner or (lambda command: run_command(command, timeout_seconds=config.cli_timeout_seconds))
    historical_runner = command_runner or (
        lambda command: run_command(command, timeout_seconds=config.historical_cli_timeout_seconds)
    )

    auth = probe_json(runner, [cli_path, "auth", "status", "--format", "json"], config.cli_timeout_seconds)
    assets = probe_json(runner, [cli_path, "assets", "--format", "json"], config.cli_timeout_seconds)
    positions = probe_json(runner, [cli_path, "positions", "--format", "json"], config.cli_timeout_seconds)
    orders = probe_json(runner, [cli_path, "order", "--format", "json"], config.cli_timeout_seconds)
    history_end_date = now.date().isoformat()
    trusted_order_history = read_json(config.output_dir / TRUSTED_ORDER_HISTORY_JSON)
    if refresh_historical_order_history and historical_order_history_refresh_due(
        trusted_order_history,
        now,
        config.historical_refresh_interval_seconds,
    ):
        historical_orders = probe_json(
            historical_runner,
            [
                cli_path,
                "order",
                "--history",
                "--start",
                config.historical_order_start_date,
                "--end",
                history_end_date,
                "--format",
                "json",
            ],
            config.historical_cli_timeout_seconds,
        )
        historical_executions = probe_json(
            historical_runner,
            [
                cli_path,
                "order",
                "executions",
                "--history",
                "--start",
                config.historical_order_start_date,
                "--end",
                history_end_date,
                "--format",
                "json",
            ],
            config.historical_cli_timeout_seconds,
        )
    else:
        historical_orders = cached_order_history_probe(trusted_order_history, "historical_orders")
        historical_executions = cached_order_history_probe(trusted_order_history, "historical_executions")
    refreshed_order_history = refresh_trusted_order_history(
        trusted_order_history,
        historical_orders,
        historical_executions,
        generated_at_iso,
    )
    if refresh_analytics and refreshed_order_history != trusted_order_history:
        write_json(config.output_dir / TRUSTED_ORDER_HISTORY_JSON, refreshed_order_history)
    historical_orders, historical_executions = restore_historical_order_history_if_unavailable(
        historical_orders,
        historical_executions,
        refreshed_order_history,
    )
    account_state = build_account_state(
        config,
        generated_at_iso,
        auth,
        assets,
        positions,
        orders,
        historical_orders,
        historical_executions,
        history_end_date,
    )
    if not refresh_analytics:
        return write_hot_account_snapshot(
            config,
            generated_at_iso,
            account_state,
            auth=auth,
            assets=assets,
            positions=positions,
            orders=orders,
        )

    portfolio = probe_json(runner, [cli_path, "portfolio", "--format", "json"], config.cli_timeout_seconds)
    profit_analysis = probe_json(
        runner,
        [
            cli_path,
            "profit-analysis",
            "--start",
            config.historical_order_start_date,
            "--end",
            history_end_date,
            "--format",
            "json",
        ],
        config.cli_timeout_seconds,
    )
    today_profit_analysis = probe_json(
        runner,
        [
            cli_path,
            "profit-analysis",
            "--start",
            account_pnl_market_date,
            "--end",
            account_pnl_market_date,
            "--format",
            "json",
        ],
        config.cli_timeout_seconds,
    )
    by_market_profit = probe_json(
        runner,
        [
            cli_path,
            "profit-analysis",
            "by-market",
            "US",
            "--start",
            config.historical_order_start_date,
            "--end",
            history_end_date,
            "--size",
            "100",
            "--format",
            "json",
        ],
        config.cli_timeout_seconds,
    )
    pnl_reconciliation = build_pnl_reconciliation(
        config,
        generated_at_iso,
        portfolio,
        profit_analysis,
        today_profit_analysis,
        by_market_profit,
        account_state,
        history_end_date,
        account_pnl_market_date,
    )
    previous_pnl_reconciliation = read_json(config.output_dir / PNL_RECONCILIATION_JSON)
    trusted_pnl_reconciliation = read_json(config.output_dir / TRUSTED_PNL_RECONCILIATION_JSON)
    pnl_reconciliation = preserve_previous_holding_prices_if_degraded(
        pnl_reconciliation,
        previous_pnl_reconciliation,
    )
    pnl_reconciliation = preserve_previous_holding_prices_if_degraded(
        pnl_reconciliation,
        trusted_pnl_reconciliation,
    )
    realtime_execution_ledger = read_jsonl(config.output_dir / REALTIME_EXECUTION_LEDGER_JSONL)
    order_reconciliation = build_order_reconciliation(
        config,
        generated_at_iso,
        account_state,
        realtime_execution_ledger,
    )
    order_reconciliation = enrich_unfilled_order_reconciliation_with_details(
        config,
        generated_at_iso,
        runner,
        cli_path,
        order_reconciliation,
    )
    stale_order_cleanup_ledger = read_jsonl(config.output_dir / STALE_ORDER_CLEANUP_LEDGER_JSONL)
    order_reconciliation = enrich_order_reconciliation_with_stale_cleanup(
        order_reconciliation,
        stale_order_cleanup_ledger,
    )
    unfilled_order_diagnostics = build_unfilled_order_diagnostics(generated_at_iso, order_reconciliation)
    fill_attribution = build_fill_attribution_v2(
        account_state,
        order_reconciliation,
        account_reconciliation_adjustments=read_json(
            config.output_dir / "m15_account_reconciliation_adjustments.json"
        ),
        commission_per_order_side=config.commission_per_order_side,
        regulatory_fee_per_sell_order=config.regulatory_fee_per_sell_order,
        execution_rows_for_fault_days=realtime_execution_ledger,
    )
    summary = build_summary(
        config,
        generated_at_iso,
        account_state,
        auth,
        assets,
        positions,
        orders,
        portfolio,
        profit_analysis,
        today_profit_analysis,
        by_market_profit,
        pnl_reconciliation,
    )
    summary["order_reconciliation_summary"] = order_reconciliation.get("summary", {})
    summary["unfilled_order_diagnostics_summary"] = unfilled_order_diagnostics.get("summary", {})
    summary["fill_attribution_summary"] = fill_attribution.get("summary", {})
    summary["outputs"]["order_reconciliation"] = project_path(config.output_dir / ORDER_RECONCILIATION_JSON)
    summary["outputs"]["unfilled_order_diagnostics"] = project_path(config.output_dir / UNFILLED_ORDER_DIAGNOSTICS_JSON)
    summary["outputs"]["fill_attribution"] = project_path(config.output_dir / FILL_ATTRIBUTION_JSON)
    ledger_row = {
        "stage": config.stage,
        "generated_at": generated_at_iso,
        "account_status": summary["account_status"],
        "paper_account_verified": account_state["paper_account_verified"],
        "position_row_count": account_state["position_row_count"],
        "open_order_count": account_state["open_order_count"],
        "historical_execution_count": account_state["historical_execution_count"],
        "account_total_equity_estimate": account_state["account_total_equity_estimate"],
        "account_total_equity_source": account_state["account_total_equity_source"],
        "buying_power": account_state["buying_power"],
        "blockers": summary["blockers"],
        "local_simulation_ignored": True,
        "order_submit_or_cancel_command_used": False,
    }
    equity_curve_row = build_equity_curve_row(generated_at_iso, account_state)
    write_json(config.account_state_path, account_state)
    write_json(config.output_dir / SUMMARY_JSON, summary)
    write_json(config.output_dir / PNL_RECONCILIATION_JSON, pnl_reconciliation)
    if not portfolio_price_snapshot_degraded(pnl_reconciliation):
        write_json(config.output_dir / TRUSTED_PNL_RECONCILIATION_JSON, pnl_reconciliation)
    write_json(config.output_dir / ORDER_RECONCILIATION_JSON, order_reconciliation)
    write_json(config.output_dir / UNFILLED_ORDER_DIAGNOSTICS_JSON, unfilled_order_diagnostics)
    write_json(config.output_dir / FILL_ATTRIBUTION_JSON, fill_attribution)
    append_jsonl(config.output_dir / LEDGER_JSONL, [ledger_row])
    append_jsonl(config.output_dir / EQUITY_CURVE_JSONL, [equity_curve_row])
    (config.output_dir / REPORT_MD).write_text(render_report(summary, account_state), encoding="utf-8")
    (config.output_dir / PNL_RECONCILIATION_MD).write_text(
        render_pnl_reconciliation_report(pnl_reconciliation),
        encoding="utf-8",
    )
    return summary


def write_hot_account_snapshot(
    config: RealtimeAccountStateConfig,
    generated_at: str,
    account_state: dict[str, Any],
    *,
    auth: dict[str, Any],
    assets: dict[str, Any],
    positions: dict[str, Any],
    orders: dict[str, Any],
) -> dict[str, Any]:
    """Persist only order-safety inputs; reporting stays on the slow analytics path."""
    previous_summary = read_json(config.output_dir / SUMMARY_JSON)
    blockers = account_blockers(config, account_state, auth, assets, positions, orders)
    status = "paper_account_ready" if not blockers else blockers[0]
    hot_summary = {
        **previous_summary,
        "schema_version": "m15.longbridge-realtime-account-state-summary.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at,
        "account_status": status,
        "blockers": blockers,
        "paper_account_verified": account_state["paper_account_verified"],
        "account_channel": account_state["account_channel"],
        "cash": account_state["cash"],
        "buying_power": account_state["buying_power"],
        "held_symbols": account_state["held_symbols"],
        "position_row_count": account_state["position_row_count"],
        "open_order_count": account_state["open_order_count"],
        "total_position_notional": account_state["total_position_notional"],
        "total_open_order_notional": account_state["total_open_order_notional"],
        "analytics_refresh_status": "deferred_to_background",
        "analytics_last_refreshed_at": str(previous_summary.get("generated_at") or ""),
        "local_simulation_isolated": True,
        "order_submit_or_cancel_command_used": False,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "outputs": {
            **(previous_summary.get("outputs", {}) if isinstance(previous_summary.get("outputs"), dict) else {}),
            "account_state": project_path(config.account_state_path),
            "summary": project_path(config.output_dir / SUMMARY_JSON),
        },
        "plain_language_result": "长桥账户快速快照已更新；历史订单、盈亏和对账由后台刷新，不阻塞实时下单。",
    }
    ledger_row = {
        "stage": config.stage,
        "generated_at": generated_at,
        "refresh_mode": "hot",
        "account_status": status,
        "paper_account_verified": account_state["paper_account_verified"],
        "position_row_count": account_state["position_row_count"],
        "open_order_count": account_state["open_order_count"],
        "blockers": blockers,
        "local_simulation_ignored": True,
        "order_submit_or_cancel_command_used": False,
    }
    write_json(config.account_state_path, account_state)
    write_json(config.output_dir / SUMMARY_JSON, hot_summary)
    append_jsonl(config.output_dir / LEDGER_JSONL, [ledger_row])
    return hot_summary


def build_summary(
    config: RealtimeAccountStateConfig,
    generated_at: str,
    account_state: dict[str, Any],
    auth: dict[str, Any],
    assets: dict[str, Any],
    positions: dict[str, Any],
    orders: dict[str, Any],
    portfolio: dict[str, Any],
    profit_analysis: dict[str, Any],
    today_profit_analysis: dict[str, Any],
    by_market_profit: dict[str, Any],
    pnl_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    blockers = account_blockers(config, account_state, auth, assets, positions, orders)
    status = "paper_account_ready" if not blockers else blockers[0]
    pnl_account_snapshot = (
        pnl_reconciliation.get("account_snapshot", {})
        if isinstance(pnl_reconciliation.get("account_snapshot"), dict)
        else {}
    )
    account_total_equity_estimate = (
        pnl_account_snapshot.get("app_like_total_asset")
        or account_state["account_total_equity_estimate"]
    )
    account_total_equity_source = (
        pnl_account_snapshot.get("app_like_total_asset_source")
        or account_state["account_total_equity_source"]
    )
    position_notional = (
        pnl_account_snapshot.get("app_like_market_value")
        or account_state["total_position_notional"]
    )
    pnl_source_status = (
        pnl_reconciliation.get("source_status", {})
        if isinstance(pnl_reconciliation.get("source_status"), dict)
        else {}
    )
    holding_snapshot_degraded = bool(pnl_source_status.get("portfolio_price_snapshot_degraded")) and not bool(
        pnl_source_status.get("holding_prices_restored_from_previous_reconciliation")
    )
    today_holding_pnl = (
        "等待长桥持仓行情"
        if holding_snapshot_degraded
        else pnl_account_snapshot.get("portfolio_total_today_pl", "无法计算")
    )
    today_account_pnl = (
        pnl_reconciliation.get("today_account_pnl", {})
        if isinstance(pnl_reconciliation.get("today_account_pnl"), dict)
        else {}
    )
    today_account_sum_profit = today_account_pnl.get("sum_profit") or "无法计算"
    app_display_today_pnl = "等待长桥字段对齐"
    historical_history_cached = bool(account_state.get("historical_orders_cache_used")) or bool(
        account_state.get("historical_executions_cache_used")
    )
    return {
        "schema_version": "m15.longbridge-realtime-account-state-summary.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at,
        "source_mode": "longbridge_realtime_account_state_only",
        "account_status": status,
        "blockers": blockers,
        "paper_account_verified": account_state["paper_account_verified"],
        "account_channel": account_state["account_channel"],
        "buying_power": account_state["buying_power"],
        "cash": account_state["cash"],
        "account_total_equity_estimate": account_total_equity_estimate,
        "account_total_equity_source": account_total_equity_source,
        "account_today_total_pnl": today_account_sum_profit,
        "account_today_total_pnl_source": "longbridge profit-analysis market-day interval",
        "net_asset_intraday_pnl": today_account_sum_profit,
        "net_asset_intraday_pnl_source": "longbridge_profit_analysis_market_day",
        "app_display_today_pnl": app_display_today_pnl,
        "app_display_today_pnl_source": "not_exposed_by_current_longbridge_cli",
        "app_display_today_pnl_note": (
            "长桥 App 顶部当日盈亏截图口径暂未在 portfolio/profit-analysis/cash-flow CLI 字段中找到；"
            "看板不得用接口净值变化或持仓今日浮动冒充该字段。"
        ),
        "today_holding_pnl": today_holding_pnl,
        "today_total_pnl_label": "长桥 portfolio.total_today_pl，表示当前持仓今日浮动。",
        "held_symbols": account_state["held_symbols"],
        "position_row_count": account_state["position_row_count"],
        "open_order_count": account_state["open_order_count"],
        "total_position_notional": position_notional,
        "total_open_order_notional": account_state["total_open_order_notional"],
        "latency_ms": {
            "auth": auth.get("elapsed_ms", 0),
            "assets": assets.get("elapsed_ms", 0),
            "positions": positions.get("elapsed_ms", 0),
            "orders": orders.get("elapsed_ms", 0),
            "historical_orders": account_state.get("historical_orders_elapsed_ms", 0),
            "historical_executions": account_state.get("historical_executions_elapsed_ms", 0),
            "portfolio": portfolio.get("elapsed_ms", 0),
            "profit_analysis": profit_analysis.get("elapsed_ms", 0),
            "today_profit_analysis": today_profit_analysis.get("elapsed_ms", 0),
            "profit_analysis_by_market": by_market_profit.get("elapsed_ms", 0),
        },
        "pnl_reconciliation_ok": bool(pnl_reconciliation.get("pnl_reconciliation_ok")),
        "account_total_pnl_estimate": pnl_reconciliation.get("account_pnl", {}).get("sum_profit", "无法计算"),
        "longbridge_stock_total_pnl": pnl_reconciliation.get("trading_pnl", {}).get("stock_total_pnl", "无法计算"),
        "today_total_pnl": today_holding_pnl,
        "holding_price_snapshot_status": "degraded_waiting_longbridge_quote" if holding_snapshot_degraded else "available",
        "historical_order_history_status": "cached_after_longbridge_read_failure" if historical_history_cached else "fresh",
        "historical_order_history_cache_generated_at": account_state.get("historical_order_history_cache_generated_at", ""),
        "local_simulation_isolated": True,
        "local_simulation_account_source": "",
        "order_submit_or_cancel_command_used": False,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "outputs": {
            "account_state": project_path(config.account_state_path),
            "summary": project_path(config.output_dir / SUMMARY_JSON),
            "pnl_reconciliation": project_path(config.output_dir / PNL_RECONCILIATION_JSON),
            "pnl_reconciliation_report": project_path(config.output_dir / PNL_RECONCILIATION_MD),
            "trusted_order_history": project_path(config.output_dir / TRUSTED_ORDER_HISTORY_JSON),
            "ledger": project_path(config.output_dir / LEDGER_JSONL),
            "equity_curve": project_path(config.output_dir / EQUITY_CURVE_JSONL),
            "report": project_path(config.output_dir / REPORT_MD),
        },
        "plain_language_result": plain_language_result(status, account_state),
    }


def build_pnl_reconciliation(
    config: RealtimeAccountStateConfig,
    generated_at: str,
    portfolio: dict[str, Any],
    profit_analysis: dict[str, Any],
    today_profit_analysis: dict[str, Any],
    by_market_profit: dict[str, Any],
    account_state: dict[str, Any],
    history_end_date: str,
    account_pnl_market_date: str,
) -> dict[str, Any]:
    portfolio_json = portfolio.get("json", {}) if isinstance(portfolio.get("json"), dict) else {}
    profit_json = profit_analysis.get("json", {}) if isinstance(profit_analysis.get("json"), dict) else {}
    today_profit_json = (
        today_profit_analysis.get("json", {})
        if isinstance(today_profit_analysis.get("json"), dict)
        else {}
    )
    by_market_json = by_market_profit.get("json", {}) if isinstance(by_market_profit.get("json"), dict) else {}
    overview = portfolio_json.get("overview", {}) if isinstance(portfolio_json.get("overview"), dict) else {}
    market_accounts = portfolio_json.get("market_accounts", {}) if isinstance(portfolio_json.get("market_accounts"), dict) else {}
    us_market_account = market_accounts.get("US", {}) if isinstance(market_accounts.get("US"), dict) else {}
    holdings = portfolio_json.get("holdings", []) if isinstance(portfolio_json.get("holdings"), list) else []
    profit_section = profit_json.get("profits", {}) if isinstance(profit_json.get("profits"), dict) else {}
    sublist = profit_json.get("sublist", {}) if isinstance(profit_json.get("sublist"), dict) else {}
    symbol_rows = sublist.get("items", []) if isinstance(sublist.get("items"), list) else []
    by_market_symbol_rows = (
        by_market_json.get("stock_items", []) if isinstance(by_market_json.get("stock_items"), list) else []
    )
    holding_unrealized = current_holding_unrealized_pnl(holdings)
    stock_total = first_string(
        by_market_json,
        ("profit",),
        fallback=first_string(profit_section, ("stock",)),
    )
    stock_total_decimal = decimal(stock_total)
    realized_estimate = stock_total_decimal - holding_unrealized if stock_total else ZERO
    portfolio_total_cash = first_string(overview, ("total_cash",), fallback=account_state.get("cash", ""))
    app_market_value = first_string(us_market_account, ("market_value",), fallback=first_string(overview, ("market_cap",), fallback=account_state.get("total_position_notional", "")))
    app_total_asset = ""
    if portfolio_total_cash and app_market_value:
        app_total_asset = fmt_money(decimal(portfolio_total_cash) + decimal(app_market_value))
    sum_profit_rate = first_string(profit_json, ("sum_profit_rate",))
    sum_profit_percent = ""
    if sum_profit_rate:
        sum_profit_percent = pct_from_rate(decimal(sum_profit_rate))
    reconciliation_ok = bool(portfolio.get("ok")) or bool(profit_analysis.get("ok")) or bool(by_market_profit.get("ok"))
    return {
        "schema_version": "m15.longbridge-account-pnl-reconciliation.v2",
        "stage": "M15.longbridge_account_pnl_reconciliation",
        "generated_at": generated_at,
        "source_mode": "longbridge_readonly_profit_analysis_and_portfolio",
        "pnl_reconciliation_ok": reconciliation_ok,
        "local_simulation_isolated": True,
        "local_simulation_account_source": "",
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "query_range": {
            "start": config.historical_order_start_date,
            "end": str(profit_json.get("updated_date") or by_market_json.get("end_date") or history_end_date),
            "trade_update_date": str(profit_json.get("trade_update_date") or by_market_json.get("end_date") or ""),
            "account_pnl_market_date": account_pnl_market_date,
        },
        "account_pnl": {
            "currency": first_string(profit_json, ("currency",), fallback=first_string(overview, ("currency",), fallback="USD")),
            "initial_asset_value": first_string(profit_json, ("initial_asset_value",)),
            "ending_asset_value": first_string(
                profit_json,
                ("ending_asset_value", "current_total_asset"),
                fallback=first_string(overview, ("total_asset",), fallback=account_state.get("account_total_equity_estimate", "")),
            ),
            "current_total_asset": first_string(
                profit_json,
                ("current_total_asset", "ending_asset_value"),
                fallback=first_string(overview, ("total_asset",), fallback=account_state.get("account_total_equity_estimate", "")),
            ),
            "sum_profit": first_string(profit_json, ("sum_profit",)),
            "sum_profit_rate": sum_profit_rate,
            "sum_profit_percent": sum_profit_percent,
        },
        "today_account_pnl": {
            "currency": first_string(
                today_profit_json,
                ("currency",),
                fallback=first_string(profit_json, ("currency",), fallback="USD"),
            ),
            "start_date": first_string(today_profit_json, ("start_date",), fallback=account_pnl_market_date),
            "end_date": first_string(today_profit_json, ("end_date",), fallback=account_pnl_market_date),
            "initial_asset_value": first_string(today_profit_json, ("initial_asset_value",)),
            "current_total_asset": first_string(today_profit_json, ("current_total_asset", "ending_asset_value")),
            "ending_asset_value": first_string(today_profit_json, ("ending_asset_value", "current_total_asset")),
            "sum_profit": first_string(today_profit_json, ("sum_profit",)),
            "sum_profit_rate": first_string(today_profit_json, ("sum_profit_rate",)),
            "updated_at": first_string(today_profit_json, ("updated_at",)),
            "updated_date": first_string(today_profit_json, ("updated_date",)),
            "source": "longbridge_profit_analysis_market_day",
        },
        "trading_pnl": {
            "cumulative_transaction_amount": first_string(profit_section, ("cumulative_transaction_amount",)),
            "stock_total_pnl": stock_total,
            "realized_pnl_estimate": fmt_money(realized_estimate) if stock_total else "",
            "current_position_unrealized_pnl": fmt_money(holding_unrealized),
            "source": "longbridge_profit_analysis_by_market_us_plus_current_portfolio",
        },
        "account_snapshot": {
            "portfolio_total_cash": portfolio_total_cash,
            "portfolio_market_cap": first_string(overview, ("market_cap",), fallback=account_state.get("total_position_notional", "")),
            "portfolio_total_asset": first_string(overview, ("total_asset",), fallback=account_state.get("account_total_equity_estimate", "")),
            "app_like_market_value": app_market_value,
            "app_like_total_asset": app_total_asset,
            "app_like_total_asset_source": "portfolio.total_cash + portfolio.market_accounts.US.market_value" if app_total_asset else "",
            "portfolio_total_pl": first_string(overview, ("total_pl",)),
            "portfolio_total_today_pl": first_string(overview, ("total_today_pl",)),
            "portfolio_total_today_pl_label": "长桥接口持仓今日浮动，不等同于 App 顶部当日盈亏字段",
            "us_market_pl": first_string(us_market_account, ("pl",)),
            "us_market_today_pl": first_string(us_market_account, ("today_pl",)),
            "holding_count": len(holdings),
            "open_order_count": account_state.get("open_order_count", 0),
        },
        "symbol_pnl_rows": symbol_rows or normalize_by_market_symbol_rows(by_market_symbol_rows),
        "by_market_symbol_pnl_rows": by_market_symbol_rows,
        "current_holdings": holdings,
        "source_status": {
            "portfolio_ok": bool(portfolio.get("ok")),
            "profit_analysis_ok": bool(profit_analysis.get("ok")),
            "today_profit_analysis_ok": bool(today_profit_analysis.get("ok")),
            "profit_analysis_by_market_ok": bool(by_market_profit.get("ok")),
            "portfolio_stderr": str(portfolio.get("stderr") or ""),
            "profit_analysis_stderr": str(profit_analysis.get("stderr") or ""),
            "today_profit_analysis_stderr": str(today_profit_analysis.get("stderr") or ""),
            "profit_analysis_by_market_stderr": str(by_market_profit.get("stderr") or ""),
        },
    }


def current_holding_unrealized_pnl(holdings: list[dict[str, Any]]) -> Decimal:
    total = ZERO
    for row in holdings:
        quantity = first_decimal(row, ("quantity", "qty"))
        if quantity <= ZERO:
            continue
        market_value = first_decimal(row, ("market_value_usd", "market_value"))
        if market_value <= ZERO:
            market_value = first_decimal(row, ("market_price", "last_done", "price")) * quantity
        cost_value = first_decimal(row, ("cost_value", "invest_cost"))
        if cost_value <= ZERO:
            cost_value = first_decimal(row, ("cost_price", "avg_cost")) * quantity
        total += market_value - cost_value
    return total


def preserve_previous_holding_prices_if_degraded(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    if not portfolio_price_snapshot_degraded(current):
        return current
    output = dict(current)
    source_status = dict(output.get("source_status", {}) if isinstance(output.get("source_status"), dict) else {})
    source_status["portfolio_price_snapshot_degraded"] = True
    source_status["holding_price_snapshot_available"] = False
    output["source_status"] = source_status
    if portfolio_price_snapshot_degraded(previous):
        return output
    previous_holdings = previous.get("current_holdings") if isinstance(previous.get("current_holdings"), list) else []
    if not previous_holdings:
        return output
    output["current_holdings"] = previous_holdings
    current_snapshot = dict(output.get("account_snapshot", {}) if isinstance(output.get("account_snapshot"), dict) else {})
    previous_snapshot = previous.get("account_snapshot", {}) if isinstance(previous.get("account_snapshot"), dict) else {}
    for key in (
        "portfolio_market_cap",
        "portfolio_total_asset",
        "app_like_market_value",
        "app_like_total_asset",
        "app_like_total_asset_source",
        "portfolio_total_pl",
        "portfolio_total_today_pl",
        "us_market_pl",
        "us_market_today_pl",
    ):
        if previous_snapshot.get(key) not in (None, ""):
            current_snapshot[key] = previous_snapshot.get(key)
    output["account_snapshot"] = current_snapshot
    trading = dict(output.get("trading_pnl", {}) if isinstance(output.get("trading_pnl"), dict) else {})
    previous_trading = previous.get("trading_pnl", {}) if isinstance(previous.get("trading_pnl"), dict) else {}
    for key in ("current_position_unrealized_pnl", "realized_pnl_estimate"):
        if previous_trading.get(key) not in (None, ""):
            trading[key] = previous_trading.get(key)
    output["trading_pnl"] = trading
    source_status["holding_prices_restored_from_previous_reconciliation"] = True
    source_status["holding_price_snapshot_available"] = True
    source_status["previous_reconciliation_generated_at"] = str(previous.get("generated_at") or "")
    output["source_status"] = source_status
    return output


def portfolio_price_snapshot_degraded(reconciliation: dict[str, Any]) -> bool:
    holdings = reconciliation.get("current_holdings") if isinstance(reconciliation.get("current_holdings"), list) else []
    comparable_rows = []
    for row in holdings:
        if not isinstance(row, dict):
            continue
        quantity = first_decimal(row, ("quantity", "qty"))
        market_price = first_decimal(row, ("market_price", "last_done", "price"))
        cost_price = first_decimal(row, ("cost_price", "avg_cost"))
        if quantity > ZERO and market_price > ZERO and cost_price > ZERO:
            comparable_rows.append(row)
    if len(comparable_rows) < 3:
        return False
    price_equals_cost = all(
        first_decimal(row, ("market_price", "last_done", "price"))
        == first_decimal(row, ("cost_price", "avg_cost"))
        for row in comparable_rows
    )
    prev_close_missing = all(row.get("prev_close") in (None, "", "-", "0", "0.0", "0.00") for row in comparable_rows)
    snapshot = reconciliation.get("account_snapshot", {}) if isinstance(reconciliation.get("account_snapshot"), dict) else {}
    portfolio_pl_zero = first_decimal(snapshot, ("portfolio_total_pl",)) == ZERO
    portfolio_today_zero = first_decimal(snapshot, ("portfolio_total_today_pl",)) == ZERO
    return price_equals_cost and prev_close_missing and portfolio_pl_zero and portfolio_today_zero


def normalize_by_market_symbol_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "security_code": row.get("code", ""),
                "name": row.get("name", ""),
                "profit": row.get("profit", row.get("underlying_profit", "")),
                "profit_rate": "",
                "holding_value": "",
                "invest_cost": "",
                "realized_cash": "",
                "is_holding": False,
            }
        )
    return normalized


def build_account_state(
    config: RealtimeAccountStateConfig,
    generated_at: str,
    auth: dict[str, Any],
    assets: dict[str, Any],
    positions: dict[str, Any],
    orders: dict[str, Any],
    historical_orders: dict[str, Any],
    historical_executions: dict[str, Any],
    historical_order_end_date: str,
) -> dict[str, Any]:
    auth_json = auth.get("json", {}) if isinstance(auth.get("json"), dict) else {}
    account = auth_json.get("account", {}) if isinstance(auth_json.get("account"), dict) else {}
    position_rows = positions.get("json") if isinstance(positions.get("json"), list) else []
    order_rows = orders.get("json") if isinstance(orders.get("json"), list) else []
    historical_order_rows = historical_orders.get("json") if isinstance(historical_orders.get("json"), list) else []
    historical_execution_rows = (
        historical_executions.get("json") if isinstance(historical_executions.get("json"), list) else []
    )
    open_order_rows = [row for row in order_rows if is_open_order_row(row)]
    position_notional = exposure_by_symbol(position_rows, quantity_keys=("quantity", "qty"), price_keys=("market_price", "last_done", "cost_price", "price"))
    open_order_notional = exposure_by_symbol(open_order_rows, quantity_keys=("quantity", "qty"), price_keys=("price", "limit_price", "submitted_price"))
    total_position_notional = sum(position_notional.values(), ZERO)
    total_open_order_notional = sum(open_order_notional.values(), ZERO)
    cash = available_cash(assets)
    buying_power = available_buying_power(assets)
    currency_cash = currency_cash_snapshot(assets)
    usd_cash = currency_cash.get("USD", {})
    account_total_equity, account_total_equity_source = account_total_equity_estimate(
        assets,
        cash=cash,
        position_market_value=total_position_notional,
    )
    channel = str(account.get("account_channel", ""))
    return {
        "schema_version": "m15.longbridge-realtime-account-state.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "source": "longbridge_realtime_account_state_only",
        "local_simulation_isolated": True,
        "local_sim_position_migration": False,
        "auth_ok": bool(auth.get("ok")),
        "assets_ok": bool(assets.get("ok")),
        "positions_ok": bool(positions.get("ok")),
        "orders_ok": bool(orders.get("ok")),
        "historical_orders_ok": bool(historical_orders.get("ok")),
        "historical_executions_ok": bool(historical_executions.get("ok")),
        "historical_orders_cache_used": bool(historical_orders.get("cache_used")),
        "historical_executions_cache_used": bool(historical_executions.get("cache_used")),
        "historical_order_history_cache_generated_at": str(
            historical_orders.get("cache_generated_at") or historical_executions.get("cache_generated_at") or ""
        ),
        "account_channel": channel,
        "account_type": account.get("account_type"),
        "paper_account_detected": channel == config.required_account_channel,
        "paper_account_verified": bool(auth.get("ok")) and channel == config.required_account_channel,
        "cash": fmt_money(cash),
        "buying_power": fmt_money(buying_power),
        "currency_cash": currency_cash,
        "usd_available_cash": usd_cash.get("available_cash", ""),
        "usd_total_cash": usd_cash.get("total_cash", ""),
        "usd_settling_cash": usd_cash.get("settling_cash", ""),
        "usd_frozen_cash": usd_cash.get("frozen_cash", ""),
        "account_total_equity_estimate": fmt_money(account_total_equity),
        "account_total_equity_source": account_total_equity_source,
        "held_symbols": sorted(held_symbol_set(position_rows)),
        "position_row_count": len(position_rows),
        "order_row_count": len(order_rows),
        "historical_order_start_date": config.historical_order_start_date,
        "historical_order_end_date": historical_order_end_date,
        "historical_order_row_count": len(historical_order_rows),
        "historical_execution_count": len(historical_execution_rows),
        "historical_orders_elapsed_ms": historical_orders.get("elapsed_ms", 0),
        "historical_executions_elapsed_ms": historical_executions.get("elapsed_ms", 0),
        "open_order_count": len(open_order_rows),
        "positions": position_rows,
        "orders": order_rows,
        "historical_orders": historical_order_rows,
        "historical_executions": historical_execution_rows,
        "open_orders": open_order_rows,
        "position_notional_by_symbol": {key: fmt_money(value) for key, value in sorted(position_notional.items())},
        "open_order_notional_by_symbol": {key: fmt_money(value) for key, value in sorted(open_order_notional.items())},
        "total_position_notional": fmt_money(total_position_notional),
        "total_open_order_notional": fmt_money(total_open_order_notional),
        "submitted_signal_ids": [],
        "real_money_actions": False,
        "live_execution": False,
    }


def build_order_reconciliation(
    config: RealtimeAccountStateConfig,
    generated_at: str,
    account_state: dict[str, Any],
    realtime_execution_ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    longbridge_orders = merged_longbridge_order_rows(account_state)
    local_submissions = [
        row
        for row in realtime_execution_ledger
        if isinstance(row, dict)
        and str(row.get("submission_status") or "") in {"submitted", "confirmed_submitted", "submit_unconfirmed_missing_order_id"}
    ]
    local_by_order_id: dict[str, list[dict[str, Any]]] = {}
    local_by_signal_id: dict[str, list[dict[str, Any]]] = {}
    for row in local_submissions:
        local_order_id = str(row.get("order_id") or row.get("longbridge_order_id") or "")
        if local_order_id:
            local_by_order_id.setdefault(local_order_id, []).append(row)
        signal_id = str(row.get("signal_id") or "")
        if signal_id:
            local_by_signal_id.setdefault(signal_id, []).append(row)
    local_queues: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in sorted(local_submissions, key=order_time_sort_key):
        if requires_exact_realtime_attribution(row):
            continue
        local_queues.setdefault(order_match_key(row), []).append(row)

    used_local_ids: set[int] = set()
    rows: list[dict[str, Any]] = []
    for order in sorted(longbridge_orders, key=order_time_sort_key):
        order_id = str(order.get("order_id") or order.get("id") or "")
        local_row = unique_unconsumed_local_row(local_by_order_id.get(order_id, []), used_local_ids) if order_id else None
        match_method = "order_id" if local_row is not None else ""
        if local_row is None:
            remark_signal_id = realtime_signal_id_from_order_remark(order)
            local_row = unique_unconsumed_local_row(local_by_signal_id.get(remark_signal_id, []), used_local_ids)
            if local_row is not None:
                match_method = "remark_signal_id"
        if local_row is None:
            key = order_match_key(order)
            queue = local_queues.get(key, [])
            while queue and id(queue[0]) in used_local_ids:
                queue.pop(0)
            if queue:
                local_row = queue.pop(0)
                match_method = "symbol_side_quantity_price"
        if local_row is not None:
            used_local_ids.add(id(local_row))
        reconciled = reconciled_longbridge_order_row(order, local_row, match_method)
        apply_cross_epoch_exit_attribution_guard(
            reconciled,
            local_row,
            local_by_signal_id=local_by_signal_id,
            local_by_order_id=local_by_order_id,
        )
        rows.append(reconciled)

    for local_row in sorted(local_submissions, key=order_time_sort_key):
        if id(local_row) in used_local_ids:
            continue
        rows.append(local_submission_without_longbridge_order_row(local_row))

    summary = order_reconciliation_summary(rows, len(longbridge_orders), len(local_submissions))
    return {
        "schema_version": "m15.longbridge-order-reconciliation.v2",
        "stage": "M15.longbridge_order_reconciliation",
        "generated_at": generated_at,
        "source_mode": "longbridge_current_and_historical_orders_plus_realtime_submission_attribution",
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "local_simulation_isolated": True,
        "local_simulation_account_source": "",
        "historical_order_start_date": config.historical_order_start_date,
        "historical_order_end_date": account_state.get("historical_order_end_date", ""),
        "summary": summary,
        "rows": rows,
        "source_refs": {
            "longbridge_account_state": project_path(config.account_state_path),
            "realtime_execution_ledger": project_path(config.output_dir / REALTIME_EXECUTION_LEDGER_JSONL),
            "stale_order_cleanup_ledger": project_path(config.output_dir / STALE_ORDER_CLEANUP_LEDGER_JSONL),
        },
        "notes": [
            "长桥当前订单列表和历史订单列表先按订单号合并；避免当天订单尚未进入历史查询时被误判为本地未确认。",
            "当前做空测试基线只接受长桥订单号或 PAT-RT 订单备注中的精确 signal_id 归因；不会使用标的、方向、数量和价格的近似匹配。",
            "只有长桥订单状态为 Filled 或存在可确认成交数量的行计入分仓、策略、胜率和盈亏。",
            "Rejected/Canceled/Expired/本地未确认提交只进入未成交诊断，不计入交易成绩。",
            "本地实时提交流水只用于把长桥真实成交归因到资金池和运行单元，不作为成绩事实源。",
            *( ["长桥历史订单接口本轮不可用，已使用上一份可信历史订单缓存；当前对账不应被解释为实时新增成交。"]
               if account_state.get("historical_orders_cache_used") or account_state.get("historical_executions_cache_used") else [] ),
        ],
    }


def build_fill_attribution_v2(
    account_state: dict[str, Any],
    order_reconciliation: dict[str, Any],
    *,
    account_reconciliation_adjustments: dict[str, Any] | None = None,
    commission_per_order_side: Decimal = DEFAULT_COMMISSION_PER_ORDER_SIDE,
    regulatory_fee_per_sell_order: Decimal = DEFAULT_REGULATORY_FEE_PER_SELL_ORDER,
    execution_rows_for_fault_days: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rebuild exact virtual lots from broker executions and exact order identity."""
    reconciled_rows = order_reconciliation.get("rows") if isinstance(order_reconciliation.get("rows"), list) else []
    formal_rows = [
        dict(row)
        for row in reconciled_rows
        if isinstance(row, dict)
        and strategy_test_epoch_id(str(row.get("test_epoch_id") or ""))
    ]
    local_rows = [
        row for row in formal_rows if row.get("attribution_status") == "matched_m15_realtime_ledger"
    ]
    eligible_order_ids = {str(row.get("order_id") or "") for row in local_rows if row.get("order_id")}
    order_rows = merged_longbridge_order_rows(account_state)
    execution_rows: list[dict[str, Any]] = []
    seen_trades: set[tuple[str, str]] = set()
    for key in ("historical_executions", "executions"):
        source_rows = account_state.get(key) if isinstance(account_state.get(key), list) else []
        for row in source_rows:
            if not isinstance(row, dict):
                continue
            identity = (str(row.get("order_id") or ""), str(row.get("trade_id") or ""))
            if not all(identity) or identity in seen_trades:
                continue
            seen_trades.add(identity)
            execution_rows.append(dict(row))
    broker_positions: dict[str, Decimal] = {}
    positions = account_state.get("positions") if isinstance(account_state.get("positions"), list) else []
    for row in positions:
        if not isinstance(row, dict):
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        quantity = first_decimal(row, ("quantity", "qty"))
        side = str(row.get("side") or "").lower()
        if "short" in side and quantity > ZERO:
            quantity = -quantity
        if symbol:
            broker_positions[symbol] = broker_positions.get(symbol, ZERO) + quantity
    broker_fill_rows = broker_fill_rows_from_orders_and_executions(order_rows, execution_rows)
    # Account history includes pre-epoch and manual broker activity. Those rows
    # remain in account reconciliation, but cannot be assigned to a strategy
    # batch without an explicit formal-epoch identity.
    broker_fill_rows = [
        row for row in broker_fill_rows if str(row.get("order_id") or "") in eligible_order_ids
    ]
    payload = rebuild_fill_attribution_from_history(
        local_rows,
        broker_fill_rows,
        broker_net_positions=broker_positions,
    )
    payload = apply_aggregate_strategy_exit_fill_allocations(
        payload,
        local_rows,
        broker_fill_rows,
        broker_net_positions=broker_positions,
    )
    payload = apply_account_flatten_fill_allocations(
        payload,
        [
            row
            for row in local_rows
            if row.get("account_flatten_allocation") is True
            or str(row.get("runtime_id") or "")
            == "M15-LONGBRIDGE-SDK-AUTO-FLATTEN"
        ],
        broker_fill_rows,
        broker_net_positions=broker_positions,
    )
    payload = apply_account_reconciliation_adjustments(
        payload,
        account_reconciliation_adjustments or {},
        broker_net_positions=broker_positions,
    )
    payload = add_completed_trade_performance(
        payload,
        commission_per_order_side=commission_per_order_side,
        regulatory_fee_per_sell_order=regulatory_fee_per_sell_order,
        fault_days=fault_days_from_execution_rows(
            execution_rows_for_fault_days
            if execution_rows_for_fault_days is not None
            else formal_rows
        ),
    )
    payload["generated_at"] = str(account_state.get("generated_at") or order_reconciliation.get("generated_at") or "")
    payload["paper_simulated_only"] = True
    payload["live_execution"] = False
    payload["real_money_actions"] = False
    return payload


def fault_days_from_execution_rows(
    rows: list[dict[str, Any]],
) -> dict[str, list[str]]:
    fault_days: dict[str, set[str]] = {}
    for row in rows:
        if not strategy_test_epoch_id(str(row.get("test_epoch_id") or "")):
            continue
        if str(row.get("position_action") or "") not in {
            "open_long",
            "open_short",
        }:
            continue
        blockers = {
            str(blocker)
            for blocker in (row.get("blockers") or [])
            if str(blocker) in SYSTEM_FAULT_BLOCKERS
        }
        if not blockers:
            continue
        raw_timestamp = str(row.get("processed_at") or row.get("created_at") or "")
        try:
            parsed = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        market_date = parsed.astimezone(NEW_YORK_TZ).date().isoformat()
        fault_days.setdefault(market_date, set()).update(blockers)
    return {
        market_date: sorted(reasons)
        for market_date, reasons in sorted(fault_days.items())
    }


def refresh_trusted_order_history(
    existing: dict[str, Any],
    historical_orders: dict[str, Any],
    historical_executions: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    output = dict(existing) if isinstance(existing, dict) else {}
    refreshed = False
    if historical_orders.get("ok") and not historical_orders.get("cache_used") and isinstance(historical_orders.get("json"), list):
        output["historical_orders"] = historical_orders["json"]
        refreshed = True
    if historical_executions.get("ok") and not historical_executions.get("cache_used") and isinstance(historical_executions.get("json"), list):
        output["historical_executions"] = historical_executions["json"]
        refreshed = True
    if refreshed:
        output["schema_version"] = "m15.longbridge-trusted-order-history.v1"
        output["generated_at"] = generated_at
    return output


def historical_order_history_refresh_due(
    trusted_history: dict[str, Any],
    now: datetime,
    refresh_interval_seconds: int,
) -> bool:
    if not isinstance(trusted_history.get("historical_orders"), list) or not isinstance(
        trusted_history.get("historical_executions"), list
    ):
        return True
    try:
        generated_at = parse_utc_datetime(str(trusted_history.get("generated_at") or ""))
    except (TypeError, ValueError):
        return True
    return (now - generated_at).total_seconds() >= refresh_interval_seconds


def cached_order_history_probe(trusted_history: dict[str, Any], cache_key: str) -> dict[str, Any]:
    rows = trusted_history.get(cache_key) if isinstance(trusted_history, dict) else None
    if not isinstance(rows, list):
        return {"ok": False, "json": {}, "elapsed_ms": 0, "stderr": "trusted order history cache unavailable"}
    return {
        "ok": True,
        "json": rows,
        "elapsed_ms": 0,
        "stderr": "",
        "cache_used": True,
        "cache_generated_at": str(trusted_history.get("generated_at") or ""),
    }


def restore_historical_order_history_if_unavailable(
    historical_orders: dict[str, Any],
    historical_executions: dict[str, Any],
    trusted_history: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cache_generated_at = str(trusted_history.get("generated_at") or "") if isinstance(trusted_history, dict) else ""

    def restore(probe: dict[str, Any], cache_key: str) -> dict[str, Any]:
        if probe.get("ok"):
            return probe
        cached_rows = trusted_history.get(cache_key) if isinstance(trusted_history, dict) else None
        if not isinstance(cached_rows, list):
            return probe
        output = dict(probe)
        output["json"] = cached_rows
        output["cache_used"] = True
        output["cache_generated_at"] = cache_generated_at
        return output

    return restore(historical_orders, "historical_orders"), restore(historical_executions, "historical_executions")


def merged_longbridge_order_rows(account_state: dict[str, Any]) -> list[dict[str, Any]]:
    merged_by_id: dict[str, dict[str, Any]] = {}
    anonymous_rows: list[dict[str, Any]] = []
    for source_name in ("historical_orders", "orders"):
        source_rows = account_state.get(source_name, [])
        if not isinstance(source_rows, list):
            continue
        for row in source_rows:
            if not isinstance(row, dict):
                continue
            clean = dict(row)
            clean.setdefault("order_source", source_name)
            order_id = str(clean.get("order_id") or clean.get("id") or "")
            if not order_id:
                anonymous_rows.append(clean)
                continue
            prior = merged_by_id.get(order_id)
            if prior is None:
                merged_by_id[order_id] = clean
            else:
                merged_by_id[order_id] = merge_order_snapshots(prior, clean)
    return list(merged_by_id.values()) + anonymous_rows


def merge_order_snapshots(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = dict(old)
    for key, value in new.items():
        if value in (None, ""):
            continue
        old_value = merged.get(key)
        if old_value in (None, ""):
            merged[key] = value
            continue
        if key in {"status", "executed_quantity", "filled_quantity", "filled_qty", "deal_quantity", "executed_price", "filled_price", "avg_price", "updated_at", "last_done_at"}:
            merged[key] = value
    merged["order_source"] = ",".join(sorted(set(str(merged.get("order_source") or "").split(",") + [str(new.get("order_source") or "")]) - {""}))
    return merged


def enrich_order_reconciliation_with_stale_cleanup(
    order_reconciliation: dict[str, Any],
    stale_cleanup_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    cleanup_by_order_id = {
        str(row.get("order_id") or ""): row
        for row in stale_cleanup_rows
        if isinstance(row, dict) and str(row.get("order_id") or "")
    }
    rows = order_reconciliation.get("rows", []) if isinstance(order_reconciliation.get("rows"), list) else []
    for row in rows:
        if bool(row.get("counts_for_performance")):
            continue
        status = canonical_order_status(row)
        if status not in {"canceled", "cancelled"}:
            continue
        cleanup = cleanup_by_order_id.get(str(row.get("order_id") or ""))
        if not cleanup:
            continue
        reason = str(cleanup.get("cleanup_reason") or "")
        cleanup_status = str(cleanup.get("cleanup_status") or "")
        if reason != "current_session_buy_order_ttl_expired" or cleanup_status != "canceled":
            continue
        age_seconds = str(cleanup.get("age_seconds") or "")
        cleanup_time = str(cleanup.get("generated_at") or "")
        row.update(
            {
                "diagnostic_category": "canceled_by_system_stale_buy_ttl",
                "diagnostic_evidence": (
                    f"系统在 {cleanup_time} 按买单超时规则撤单；"
                    f"订单挂单约 {age_seconds} 秒仍未成交。"
                ),
                "repair_action": "这是系统主动清理未成交买单；若要提高成交率，应调整买入限价/触发价或买单有效期，不计入交易成绩。",
                "requires_future_tracking": False,
            }
        )
    order_reconciliation["summary"] = order_reconciliation_summary(
        rows,
        int(order_reconciliation.get("summary", {}).get("longbridge_order_count", 0)),
        int(order_reconciliation.get("summary", {}).get("local_submission_count", 0)),
    )
    return order_reconciliation


def build_unfilled_order_diagnostics(
    generated_at: str,
    order_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    rows = order_reconciliation.get("rows", []) if isinstance(order_reconciliation.get("rows"), list) else []
    diagnostic_rows = [
        {
            "order_id": row.get("order_id", ""),
            "symbol": row.get("symbol", ""),
            "side": row.get("side", ""),
            "status": row.get("status", ""),
            "capital_bucket": row.get("capital_bucket", ""),
            "runtime_id": row.get("runtime_id", ""),
            "strategy_id": row.get("strategy_id", ""),
            "diagnostic_category": row.get("diagnostic_category", ""),
            "diagnostic_evidence": row.get("diagnostic_evidence", ""),
            "repair_action": row.get("repair_action", ""),
            "requires_future_tracking": row.get("requires_future_tracking", False),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
        }
        for row in rows
        if isinstance(row, dict) and not bool(row.get("counts_for_performance"))
    ]
    status_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for row in diagnostic_rows:
        status_counts[str(row.get("status") or "unknown")] = status_counts.get(str(row.get("status") or "unknown"), 0) + 1
        category = str(row.get("diagnostic_category") or "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "schema_version": "m15.longbridge-unfilled-order-diagnostics.v1",
        "stage": "M15.longbridge_unfilled_order_diagnostics",
        "generated_at": generated_at,
        "source_mode": "longbridge_order_reconciliation_unfilled_subset",
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "summary": {
            "diagnostic_row_count": len(diagnostic_rows),
            "status_counts": dict(sorted(status_counts.items())),
            "diagnostic_category_counts": dict(sorted(category_counts.items())),
            "requires_future_tracking_count": sum(1 for row in diagnostic_rows if row.get("requires_future_tracking")),
        },
        "rows": diagnostic_rows,
        "notes": [
            "历史订单没有拒绝/取消/过期原因时，不强行猜测；从修复后的下一笔订单开始补全生命周期和行情路径。",
            "未成交订单不进入分仓盈亏、胜率、盈亏比、回撤或策略表现。",
        ],
    }


def enrich_unfilled_order_reconciliation_with_details(
    config: RealtimeAccountStateConfig,
    generated_at: str,
    runner: CommandRunner,
    cli_path: str,
    order_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    rows = order_reconciliation.get("rows", []) if isinstance(order_reconciliation.get("rows"), list) else []
    detail_cache_path = config.output_dir / ORDER_DETAIL_CACHE_JSON
    detail_cache = read_json(detail_cache_path)
    cached_details = detail_cache.get("details", {}) if isinstance(detail_cache.get("details"), dict) else {}
    lookup_limit = config.unfilled_order_detail_lookup_limit
    lookup_count = 0
    for row in rows:
        if bool(row.get("counts_for_performance")):
            continue
        order_id = str(row.get("order_id") or "")
        if not order_id:
            continue
        detail_payload = cached_details.get(order_id)
        if not isinstance(detail_payload, dict) and lookup_count < lookup_limit:
            detail = probe_json(
                runner,
                [cli_path, "order", "detail", order_id, "--format", "json"],
                config.cli_timeout_seconds,
            )
            detail_payload = {
                "ok": bool(detail.get("ok")),
                "fetched_at": generated_at,
                "json": detail.get("json") if isinstance(detail.get("json"), dict) else {},
                "stderr": detail.get("stderr", ""),
            }
            cached_details[order_id] = detail_payload
            lookup_count += 1
        if isinstance(detail_payload, dict):
            apply_order_detail_to_reconciliation_row(row, detail_payload)
    detail_cache = {
        "schema_version": "m15.longbridge-order-detail-cache.v1",
        "stage": "M15.longbridge_order_detail_cache",
        "generated_at": generated_at,
        "detail_count": len(cached_details),
        "last_lookup_count": lookup_count,
        "details": cached_details,
    }
    write_json(detail_cache_path, detail_cache)
    order_reconciliation["summary"] = order_reconciliation_summary(
        rows,
        int(order_reconciliation.get("summary", {}).get("longbridge_order_count", 0)),
        int(order_reconciliation.get("summary", {}).get("local_submission_count", 0)),
    )
    order_reconciliation["order_detail_lookup"] = {
        "cache_path": project_path(detail_cache_path),
        "cache_detail_count": len(cached_details),
        "lookup_limit": lookup_limit,
        "lookup_count": lookup_count,
    }
    return order_reconciliation


def apply_order_detail_to_reconciliation_row(row: dict[str, Any], detail_payload: dict[str, Any]) -> None:
    detail = detail_payload.get("json") if isinstance(detail_payload.get("json"), dict) else {}
    if not detail:
        if not row.get("detail_lookup_status"):
            row["detail_lookup_status"] = "detail_unavailable"
        return
    detail_status = str(detail.get("status") or "")
    detail_remark = order_reason_text(detail)
    if not detail_remark:
        history = detail.get("history") if isinstance(detail.get("history"), list) else []
        history_msgs = [
            str(item.get("msg") or "")
            for item in history
            if isinstance(item, dict) and str(item.get("msg") or "")
        ]
        detail_remark = " | ".join(history_msgs)
    row["detail_lookup_status"] = "detail_available"
    row["detail_status"] = detail_status
    row["detail_remark"] = detail_remark
    row["detail_history"] = detail.get("history", []) if isinstance(detail.get("history"), list) else []
    status = canonical_order_status(detail) if detail_status else str(row.get("canonical_status") or "")
    executed_quantity = first_decimal(detail, ("executed_quantity", "filled_quantity", "filled_qty", "deal_quantity"))
    if status in {"filled", "partially_filled"} or executed_quantity > ZERO:
        row.update(longbridge_order_diagnostic(status, executed_quantity, detail))
        return
    lower_remark = detail_remark.lower()
    if "insufficient holdings" in lower_remark or "available positions" in lower_remark:
        row.update(
            {
                "diagnostic_category": "sell_available_quantity_insufficient_or_occupied",
                "diagnostic_evidence": detail_remark,
                "repair_action": "修卖出状态机：同标的已有卖单、可卖数量为 0 或可卖数量被挂单占用时，不再重复提交卖单。",
                "requires_future_tracking": False,
            }
        )
        return
    if detail_remark:
        row.update(
            {
                "diagnostic_category": f"{status}_detail_reason_available" if status else "detail_reason_available",
                "diagnostic_evidence": detail_remark,
                "repair_action": "按长桥订单详情返回的原因修复对应提交逻辑。",
                "requires_future_tracking": False,
            }
        )


def reconciled_longbridge_order_row(
    order: dict[str, Any],
    local_row: dict[str, Any] | None,
    match_method: str,
) -> dict[str, Any]:
    status = canonical_order_status(order)
    executed_quantity = first_decimal(order, ("executed_quantity", "filled_quantity", "filled_qty", "deal_quantity"))
    quantity = first_decimal(order, ("quantity", "qty", "submitted_quantity"))
    price = first_decimal(order, ("price", "limit_price", "submitted_price"))
    executed_price = first_decimal(order, ("executed_price", "filled_price", "avg_price", "price"))
    counts_for_performance = status in {"filled", "partially_filled"} or executed_quantity > ZERO
    attribution_status = "matched_m15_realtime_ledger" if local_row is not None else "legacy_or_unattributed_longbridge_order"
    diagnostic = longbridge_order_diagnostic(status, executed_quantity, order)
    runtime_id = str(local_row.get("runtime_id") or "") if local_row else ""
    strategy_id = str(local_row.get("strategy_id") or "") if local_row else ""
    capital_bucket = str(local_row.get("capital_bucket") or "未归因") if local_row else "未归因"
    direction = local_position_direction(local_row) if local_row else ""
    position_action = str(local_row.get("position_action") or "") if local_row else ""
    source_open_order_id = str(local_row.get("source_open_order_id") or "") if local_row else ""
    source_open_trade_id = str(local_row.get("source_open_trade_id") or "") if local_row else ""
    order_id = str(order.get("order_id") or order.get("id") or "")
    if runtime_id and not strategy_id:
        strategy_id = runtime_id_parent(runtime_id)
    return {
        "order_id": order_id,
        "symbol": base_symbol(str(order.get("symbol") or "")),
        "side": normalize_order_side(order.get("side")),
        "order_type": str(order.get("order_type") or order.get("type") or ""),
        "status": str(order.get("status") or ""),
        "canonical_status": status,
        "quantity": fmt_decimal(quantity),
        "price": fmt_money(price) if price > ZERO else "",
        "executed_quantity": fmt_decimal(executed_quantity),
        "executed_price": fmt_money(executed_price) if executed_price > ZERO else "",
        "filled_quantity": fmt_decimal(executed_quantity),
        "created_at": first_string(order, ("created_at", "submitted_at", "time", "updated_at")),
        "updated_at": first_string(order, ("updated_at", "last_done_at", "time", "created_at")),
        "capital_bucket": capital_bucket,
        "runtime_id": runtime_id or "未归因长桥成交",
        "strategy_id": strategy_id or "未归因长桥成交",
        "signal_id": str(local_row.get("signal_id") or "") if local_row else "",
        "test_epoch_id": str(local_row.get("test_epoch_id") or "") if local_row else "",
        "direction": direction,
        "position_action": position_action,
        "source_open_order_id": source_open_order_id,
        "source_open_trade_id": source_open_trade_id,
        "source_open_remaining_quantity": str(local_row.get("source_open_remaining_quantity") or "") if local_row else "",
        "source_open_signal_id": str(local_row.get("source_open_signal_id") or "") if local_row else "",
        "strategy_contract_hash": str(local_row.get("strategy_contract_hash") or "") if local_row else "",
        "account_flatten_allocation": bool(local_row.get("account_flatten_allocation")) if local_row else False,
        "historical_audit_repair": bool(local_row.get("historical_audit_repair")) if local_row else False,
        "attribution_key": attribution_key(
            capital_bucket=capital_bucket,
            runtime_id=runtime_id,
            direction=direction,
            symbol=base_symbol(str(order.get("symbol") or "")),
            order_id=order_id,
        )
        if local_row is not None
        else "",
        "attribution_status": attribution_status,
        "attribution_match_method": match_method or "no_local_match",
        "counts_for_performance": counts_for_performance,
        "include_in_bucket_performance": counts_for_performance and attribution_status == "matched_m15_realtime_ledger",
        "include_in_strategy_performance": counts_for_performance and attribution_status == "matched_m15_realtime_ledger",
        **diagnostic,
    }


def apply_cross_epoch_exit_attribution_guard(
    reconciled: dict[str, Any],
    local_row: dict[str, Any] | None,
    *,
    local_by_signal_id: dict[str, list[dict[str, Any]]],
    local_by_order_id: dict[str, list[dict[str, Any]]],
) -> None:
    if local_row is None or not bool(reconciled.get("counts_for_performance")):
        return
    current_epoch = str(local_row.get("test_epoch_id") or "")
    source_signal_id = str(local_row.get("source_open_signal_id") or "")
    source_order_id = str(local_row.get("source_open_order_id") or "")
    if not current_epoch or (not source_signal_id and not source_order_id):
        return
    source_rows = list(local_by_signal_id.get(source_signal_id, [])) if source_signal_id else []
    if not source_rows and source_order_id:
        source_rows = list(local_by_order_id.get(source_order_id, []))
    source_epochs = {
        str(row.get("test_epoch_id") or "")
        for row in source_rows
        if str(row.get("test_epoch_id") or "")
    }
    if not source_epochs or current_epoch in source_epochs:
        return
    reconciled.update(
        {
            "attribution_status": "cross_epoch_exit_attribution_rejected",
            "include_in_bucket_performance": False,
            "include_in_strategy_performance": False,
            "diagnostic_category": "cross_epoch_exit_attribution_rejected",
            "diagnostic_evidence": (
                f"平仓请求测试编号 {current_epoch} 与来源开仓测试编号 "
                f"{','.join(sorted(source_epochs))} 不一致；保留长桥真实成交，但不计入具体分仓或策略。"
            ),
            "repair_action": "只允许当前测试编号内的开仓批次生成对应策略平仓归因。",
            "requires_future_tracking": False,
        }
    )


def local_submission_without_longbridge_order_row(local_row: dict[str, Any]) -> dict[str, Any]:
    runtime_id = str(local_row.get("runtime_id") or "")
    strategy_id = str(local_row.get("strategy_id") or runtime_id_parent(runtime_id))
    direction = local_position_direction(local_row)
    position_action = str(local_row.get("position_action") or "")
    order_id = str(local_row.get("order_id") or local_row.get("longbridge_order_id") or "")
    symbol = base_symbol(str(local_row.get("symbol") or ""))
    capital_bucket = str(local_row.get("capital_bucket") or "未归因")
    return {
        "order_id": order_id,
        "symbol": symbol,
        "side": normalize_order_side(local_row.get("side")),
        "order_type": str(local_row.get("order_type") or local_row.get("longbridge_order_type") or ""),
        "status": "LocalSubmittedNoLongbridgeOrder",
        "canonical_status": "local_unconfirmed",
        "quantity": fmt_decimal(first_decimal(local_row, ("quantity", "submitted_quantity"))),
        "price": fmt_money(first_decimal(local_row, ("submitted_price", "limit_price", "price"))) if first_decimal(local_row, ("submitted_price", "limit_price", "price")) > ZERO else "",
        "executed_quantity": "0",
        "executed_price": "",
        "filled_quantity": "0",
        "created_at": first_string(local_row, ("submitted_at", "processed_at", "created_at")),
        "updated_at": first_string(local_row, ("processed_at", "submitted_at", "created_at")),
        "capital_bucket": capital_bucket,
        "runtime_id": runtime_id or "未归因长桥请求",
        "strategy_id": strategy_id or "未归因长桥请求",
        "signal_id": str(local_row.get("signal_id") or ""),
        "test_epoch_id": str(local_row.get("test_epoch_id") or ""),
        "direction": direction,
        "position_action": position_action,
        "source_open_order_id": str(local_row.get("source_open_order_id") or ""),
        "source_open_trade_id": str(local_row.get("source_open_trade_id") or ""),
        "source_open_remaining_quantity": str(local_row.get("source_open_remaining_quantity") or ""),
        "strategy_contract_hash": str(local_row.get("strategy_contract_hash") or ""),
        "account_flatten_allocation": bool(local_row.get("account_flatten_allocation")),
        "historical_audit_repair": bool(local_row.get("historical_audit_repair")),
        "attribution_key": attribution_key(
            capital_bucket=capital_bucket,
            runtime_id=runtime_id,
            direction=direction,
            symbol=symbol,
            order_id=order_id,
        ),
        "attribution_status": "local_submitted_no_longbridge_order",
        "attribution_match_method": "no_longbridge_order_match",
        "counts_for_performance": False,
        "include_in_bucket_performance": False,
        "include_in_strategy_performance": False,
        "diagnostic_category": "local_unconfirmed_submission",
        "diagnostic_evidence": "本地流水显示已请求，但长桥历史订单没有匹配订单；不计入成交或分仓表现。",
        "repair_action": "后续订单必须记录长桥订单号并回查状态；未拿到订单号不得算提交成功。",
        "requires_future_tracking": True,
    }


def longbridge_order_diagnostic(status: str, executed_quantity: Decimal, order: dict[str, Any]) -> dict[str, Any]:
    if status in {"filled", "partially_filled"} or executed_quantity > ZERO:
        return {
            "diagnostic_category": "filled",
            "diagnostic_evidence": "长桥返回已成交或存在可确认成交数量。",
            "repair_action": "计入长桥实际成交口径。",
            "requires_future_tracking": False,
        }
    reason = order_reason_text(order)
    if status == "rejected":
        return {
            "diagnostic_category": "rejected_reason_available" if reason else "rejected_reason_unavailable",
            "diagnostic_evidence": reason or "长桥历史订单状态为 Rejected，但未返回拒绝原因。",
            "repair_action": "按长桥拒绝原因修复；若无原因，后续订单继续采集 reject message。",
            "requires_future_tracking": not bool(reason),
        }
    if status in {"canceled", "cancelled"}:
        return {
            "diagnostic_category": "cancel_reason_available" if reason else "cancel_reason_unavailable",
            "diagnostic_evidence": reason or "长桥历史订单状态为 Canceled，但未返回取消来源。",
            "repair_action": "区分系统撤单、旧挂单清理、人工或券商取消；后续订单记录取消来源。",
            "requires_future_tracking": not bool(reason),
        }
    if status == "expired":
        return {
            "diagnostic_category": "expired_price_path_unavailable",
            "diagnostic_evidence": reason or "长桥历史订单状态为 Expired；当前历史产物没有完整订单生命周期行情路径，不能确认是否触价。",
            "repair_action": "后续订单记录创建后最高/最低价、限价是否触达和最终过期时间，再判断价格未到或撮合问题。",
            "requires_future_tracking": True,
        }
    return {
        "diagnostic_category": "status_unknown_or_open",
        "diagnostic_evidence": reason or f"长桥订单状态为 {status or 'unknown'}，未能归入已成交、拒绝、取消或过期。",
        "repair_action": "后续订单继续回查生命周期，直到 Filled/Canceled/Expired/Rejected。",
        "requires_future_tracking": True,
    }


def order_reconciliation_summary(
    rows: list[dict[str, Any]],
    longbridge_order_count: int,
    local_submission_count: int,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    attribution_counts: dict[str, int] = {}
    diagnostic_counts: dict[str, int] = {}
    for row in rows:
        status_counts[str(row.get("canonical_status") or row.get("status") or "unknown")] = (
            status_counts.get(str(row.get("canonical_status") or row.get("status") or "unknown"), 0) + 1
        )
        attribution = str(row.get("attribution_status") or "unknown")
        attribution_counts[attribution] = attribution_counts.get(attribution, 0) + 1
        diagnostic = str(row.get("diagnostic_category") or "unknown")
        diagnostic_counts[diagnostic] = diagnostic_counts.get(diagnostic, 0) + 1
    return {
        "longbridge_order_count": longbridge_order_count,
        "local_submission_count": local_submission_count,
        "reconciliation_row_count": len(rows),
        "filled_order_count": sum(1 for row in rows if row.get("counts_for_performance")),
        "unfilled_order_count": sum(1 for row in rows if not row.get("counts_for_performance")),
        "matched_local_submission_count": sum(1 for row in rows if row.get("attribution_status") == "matched_m15_realtime_ledger"),
        "local_submitted_no_longbridge_order_count": sum(1 for row in rows if row.get("attribution_status") == "local_submitted_no_longbridge_order"),
        "legacy_or_unattributed_order_count": sum(1 for row in rows if row.get("attribution_status") == "legacy_or_unattributed_longbridge_order"),
        "status_counts": dict(sorted(status_counts.items())),
        "attribution_status_counts": dict(sorted(attribution_counts.items())),
        "diagnostic_category_counts": dict(sorted(diagnostic_counts.items())),
    }


def order_match_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    quantity = first_decimal(row, ("quantity", "qty", "submitted_quantity"))
    price = first_decimal(row, ("price", "limit_price", "submitted_price"))
    return (
        base_symbol(str(row.get("symbol") or "")),
        normalize_order_side(row.get("side")),
        fmt_decimal(quantity),
        fmt_money(price) if price > ZERO else "",
    )


def requires_exact_realtime_attribution(row: dict[str, Any]) -> bool:
    """Formal SDK rows must never be paired by symbol/price/quantity guesses."""
    direction = local_position_direction(row)
    epoch_id = str(row.get("test_epoch_id") or "")
    return (
        direction == "short"
        or epoch_id.startswith("m15-short-single-strategy-")
        or strategy_test_epoch_id(epoch_id)
    )


def local_position_direction(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    direction = str(row.get("direction") or "").strip().lower()
    position_action = str(row.get("position_action") or "").strip().lower()
    side = str(row.get("side") or "").strip().lower()
    if direction == "short" or position_action in {"open_short", "close_short"} or side == "sell_short":
        return "short"
    return "long"


def unique_unconsumed_local_row(
    candidates: list[dict[str, Any]], used_local_ids: set[int]
) -> dict[str, Any] | None:
    unconsumed = [row for row in candidates if id(row) not in used_local_ids]
    return unconsumed[0] if len(unconsumed) == 1 else None


def realtime_signal_id_from_order_remark(order: dict[str, Any]) -> str:
    for key in ("remark", "note", "message"):
        text = str(order.get(key) or "")
        match = re.search(r"(?:^|\\s)PAT-RT\\s+(\\S+)", text)
        if match:
            return match.group(1)
    return ""


def attribution_key(*, capital_bucket: str, runtime_id: str, direction: str, symbol: str, order_id: str) -> str:
    return "|".join((capital_bucket, runtime_id, direction, symbol, order_id))


def order_time_sort_key(row: dict[str, Any]) -> str:
    return first_string(row, ("created_at", "submitted_at", "processed_at", "time", "updated_at"))


def canonical_order_status(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").strip().lower().replace(" ", "_")
    # SDK objects stringify enums as e.g. ``OrderStatus.Canceled``. Treat the
    # enum member exactly like the plain API status so canceled orders do not
    # remain in the unknown/open diagnostic bucket.
    if "." in status:
        status = status.rsplit(".", 1)[-1]
    aliases = {
        "executed": "filled",
        "filled": "filled",
        "partially_filled": "partially_filled",
        "partial_filled": "partially_filled",
        "partialfilled": "partially_filled",
        "cancelled": "cancelled",
        "canceled": "canceled",
        "rejected": "rejected",
        "expired": "expired",
        "submitted": "submitted",
        "new": "submitted",
        "pending": "submitted",
    }
    if status in aliases:
        return aliases[status]
    if first_decimal(row, ("executed_quantity", "filled_quantity", "filled_qty", "deal_quantity")) > ZERO:
        return "filled"
    return status or "unknown"


def normalize_order_side(value: Any) -> str:
    side = str(value or "").strip().lower()
    if side in {"buy", "b", "long"}:
        return "buy"
    if side in {"sell", "s"}:
        return "sell"
    return side


def order_reason_text(row: dict[str, Any]) -> str:
    for key in ("reject_reason", "rejected_reason", "cancel_reason", "canceled_reason", "expire_reason", "reason", "message", "msg", "remark", "error", "status_msg"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def runtime_id_parent(runtime_id: str) -> str:
    parts = runtime_id.split("-")
    if len(parts) >= 3 and parts[0] == "M10" and parts[1] == "PA":
        return "-".join(parts[:3])
    if runtime_id.startswith("M12-FTD-001"):
        return "M12-FTD-001"
    return runtime_id


def build_equity_curve_row(generated_at: str, account_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "m15.longbridge-realtime-equity-snapshot.v1",
        "stage": "M15.longbridge_realtime_equity_curve",
        "generated_at": generated_at,
        "account_channel": account_state.get("account_channel", ""),
        "paper_account_verified": bool(account_state.get("paper_account_verified")),
        "account_total_equity_estimate": account_state.get("account_total_equity_estimate", "0.00"),
        "account_total_equity_source": account_state.get("account_total_equity_source", ""),
        "cash": account_state.get("cash", "0.00"),
        "buying_power": account_state.get("buying_power", "0.00"),
        "position_market_value": account_state.get("total_position_notional", "0.00"),
        "open_order_notional": account_state.get("total_open_order_notional", "0.00"),
        "position_row_count": account_state.get("position_row_count", 0),
        "open_order_count": account_state.get("open_order_count", 0),
        "local_simulation_isolated": True,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
    }


def account_blockers(
    config: RealtimeAccountStateConfig,
    account_state: dict[str, Any],
    auth: dict[str, Any],
    assets: dict[str, Any],
    positions: dict[str, Any],
    orders: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if auth.get("ok") is not True:
        blockers.append("auth_status_read_failed")
    if account_state.get("account_channel") != config.required_account_channel:
        blockers.append("account_channel_not_paper")
    if assets.get("ok") is not True:
        blockers.append("assets_read_failed")
    if positions.get("ok") is not True:
        blockers.append("positions_read_failed")
    if orders.get("ok") is not True:
        blockers.append("orders_read_failed")
    return blockers


def probe_json(runner: CommandRunner, command: list[str], timeout_seconds: int) -> dict[str, Any]:
    assert_account_state_command(command)
    started = time.perf_counter()
    try:
        result = runner(command)
    except Exception as exc:  # pragma: no cover - runtime provider path
        return {"ok": False, "json": {}, "elapsed_ms": int((time.perf_counter() - started) * 1000), "stderr": str(exc)[:300]}
    stdout = str(getattr(result, "stdout", ""))
    stderr = str(getattr(result, "stderr", ""))
    returncode = int(getattr(result, "returncode", 1))
    if returncode != 0:
        return {
            "ok": False,
            "json": {},
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "stderr": clean_cli_text(stderr or stdout)[:300],
        }
    return {
        "ok": True,
        "json": parse_json(stdout),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "stderr": clean_cli_text(stderr)[:300],
    }


def assert_account_state_command(command: list[str]) -> None:
    if len(command) < 2:
        raise ValueError("Longbridge account state command cannot be empty")
    args = command[1:]
    if args[:2] == ["auth", "status"] and "--format" in args:
        return
    if args[:1] in (["assets"], ["positions"], ["order"]) and "--format" in args:
        forbidden = {"buy", "sell", "cancel", "replace", "--yes"}
        if any(token in forbidden for token in args):
            raise ValueError(f"Longbridge account state command cannot submit or cancel orders: {args}")
        return
    if args[:1] == ["portfolio"] and "--format" in args:
        return
    if args[:1] == ["profit-analysis"] and "--format" in args:
        forbidden = {"buy", "sell", "cancel", "replace", "--yes"}
        if any(token in forbidden for token in args):
            raise ValueError(f"Longbridge account state command cannot submit or cancel orders: {args}")
        return
    raise ValueError(f"Longbridge account state command is not allowed: {args}")


def run_command(command: list[str], *, timeout_seconds: int = 30) -> CommandResult:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
        env=build_longbridge_cli_env(),
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def parse_json(text: str) -> Any:
    stripped = (text or "").lstrip()
    if not stripped:
        return {}
    decoder = json.JSONDecoder()
    try:
        payload, _ = decoder.raw_decode(stripped)
        return payload
    except json.JSONDecodeError:
        return {}


def is_open_order_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    status = str(row.get("status") or "").strip().lower()
    if not status:
        return True
    return status not in {"filled", "canceled", "cancelled", "rejected", "expired", "withdrawn", "deleted", "failed"}


def held_symbol_set(rows: list[dict[str, Any]]) -> set[str]:
    symbols: set[str] = set()
    for row in rows:
        if decimal(row.get("quantity", row.get("qty", "0"))) > ZERO and row.get("symbol"):
            symbols.add(base_symbol(str(row.get("symbol", ""))))
    return symbols


def exposure_by_symbol(rows: list[dict[str, Any]], *, quantity_keys: tuple[str, ...], price_keys: tuple[str, ...]) -> dict[str, Decimal]:
    exposures: dict[str, Decimal] = {}
    for row in rows:
        symbol = base_symbol(str(row.get("symbol", "")))
        if not symbol:
            continue
        quantity = first_decimal(row, quantity_keys)
        price = first_decimal(row, price_keys)
        if quantity <= ZERO or price <= ZERO:
            continue
        exposures[symbol] = exposures.get(symbol, ZERO) + quantity * price
    return exposures


def available_buying_power(assets: dict[str, Any]) -> Decimal:
    payload = assets.get("json")
    rows = payload if isinstance(payload, list) else []
    if not rows:
        return ZERO
    return first_decimal(rows[0], ("buy_power", "buying_power", "available_cash", "cash", "total_cash"))


def available_cash(assets: dict[str, Any]) -> Decimal:
    payload = assets.get("json")
    rows = payload if isinstance(payload, list) else []
    if not rows:
        return ZERO
    return first_decimal(rows[0], ("cash", "available_cash", "total_cash", "buy_power", "buying_power"))


def currency_cash_snapshot(assets: dict[str, Any]) -> dict[str, dict[str, str]]:
    payload = assets.get("json")
    rows = payload if isinstance(payload, list) else []
    if not rows or not isinstance(rows[0], dict):
        return {}
    snapshot: dict[str, dict[str, str]] = {}
    for row in rows[0].get("cash_infos", []) or []:
        if not isinstance(row, dict):
            continue
        currency = str(row.get("currency") or "").upper()
        if not currency:
            continue
        snapshot[currency] = {
            "available_cash": fmt_money(first_decimal(row, ("available_cash", "cash", "withdraw_cash"))),
            "total_cash": fmt_money(first_decimal(row, ("total_cash", "cash", "available_cash", "withdraw_cash"))),
            "settling_cash": fmt_money(first_decimal(row, ("settling_cash",))),
            "frozen_cash": fmt_money(first_decimal(row, ("frozen_cash",))),
            "withdraw_cash": fmt_money(first_decimal(row, ("withdraw_cash", "available_cash"))),
        }
    return snapshot


def account_total_equity_estimate(
    assets: dict[str, Any],
    *,
    cash: Decimal,
    position_market_value: Decimal,
) -> tuple[Decimal, str]:
    payload = assets.get("json")
    rows = payload if isinstance(payload, list) else []
    if rows:
        asset_row = rows[0]
        for key in (
            "net_assets",
            "assets_net_assets",
            "total_assets",
            "total_asset",
            "portfolio_total_asset",
            "current_total_asset",
            "account_total_equity",
            "equity",
        ):
            if asset_row.get(key) not in (None, ""):
                value = decimal(asset_row.get(key))
                if value > ZERO:
                    return value, f"longbridge_assets.{key}"
    if cash > ZERO or position_market_value > ZERO:
        return cash + position_market_value, "cash_plus_position_market_value"
    buying_power = available_buying_power(assets)
    if buying_power > ZERO:
        return buying_power, "buying_power_fallback"
    return ZERO, "unavailable"


def first_decimal(row: dict[str, Any], keys: tuple[str, ...]) -> Decimal:
    for key in keys:
        if row.get(key) not in (None, ""):
            return decimal(row.get(key))
    return ZERO


def first_string(row: dict[str, Any], keys: tuple[str, ...], *, fallback: Any = "") -> str:
    for key in keys:
        if row.get(key) not in (None, ""):
            return str(row.get(key))
    return str(fallback or "")


def base_symbol(symbol: str) -> str:
    return symbol.upper().split(".")[0]


def plain_language_result(status: str, account_state: dict[str, Any]) -> str:
    if status == "paper_account_ready":
        return (
            f"长桥模拟账户状态已读取：现金/购买力 {account_state['buying_power']}，"
            f"持仓 {account_state['position_row_count']} 条，未完成挂单 {account_state['open_order_count']} 条。"
        )
    return f"长桥模拟账户状态读取未通过：{status}。"


def render_report(summary: dict[str, Any], account_state: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# 长桥模拟账户实时账户状态",
            "",
            f"- 生成时间: `{summary['generated_at']}`",
            f"- 状态: `{summary['account_status']}`",
            f"- 账户通道: `{summary['account_channel']}`",
            f"- 现金/购买力: `{summary['buying_power']}`",
            f"- 账户总净值估算: `{summary['account_total_equity_estimate']}`（{summary['account_total_equity_source']}）",
            f"- 持仓条数: `{summary['position_row_count']}`",
            f"- 未完成挂单: `{summary['open_order_count']}`",
            f"- 本地模拟隔离: `{summary['local_simulation_isolated']}`",
            f"- 结论: {summary['plain_language_result']}",
            "",
            "## 边界",
            "",
            "- 只读取长桥模拟账户自身现金、持仓、挂单和账户通道。",
            "- 不读取本地模拟账本，不迁移本地持仓。",
            "- 不提交、不撤单、不改订单。",
            "",
        ]
    )


def render_pnl_reconciliation_report(reconciliation: dict[str, Any]) -> str:
    account_pnl = reconciliation.get("account_pnl", {}) if isinstance(reconciliation.get("account_pnl"), dict) else {}
    trading_pnl = reconciliation.get("trading_pnl", {}) if isinstance(reconciliation.get("trading_pnl"), dict) else {}
    snapshot = (
        reconciliation.get("account_snapshot", {})
        if isinstance(reconciliation.get("account_snapshot"), dict)
        else {}
    )
    query_range = reconciliation.get("query_range", {}) if isinstance(reconciliation.get("query_range"), dict) else {}
    symbol_rows = reconciliation.get("symbol_pnl_rows", [])
    symbol_rows = symbol_rows if isinstance(symbol_rows, list) else []
    lines = [
        "# 长桥模拟账户总盈亏对账",
        "",
        f"- 生成时间: `{reconciliation.get('generated_at', '')}`",
        f"- 查询区间: `{query_range.get('start', '')} ~ {query_range.get('end', '')}`",
        f"- 账户区间净值盈亏: `{account_pnl.get('sum_profit', '无法计算')}` USD",
        f"- 股票交易合并盈亏: `{trading_pnl.get('stock_total_pnl', '无法计算')}` USD",
        f"- 已实现估算: `{trading_pnl.get('realized_pnl_estimate', '无法计算')}` USD",
        f"- 当前持仓浮动: `{trading_pnl.get('current_position_unrealized_pnl', '无法计算')}` USD",
        f"- 当前总资产: `{snapshot.get('portfolio_total_asset', '无法计算')}` USD",
        f"- 当前现金: `{snapshot.get('portfolio_total_cash', '无法计算')}` USD",
        f"- 当前持仓市值: `{snapshot.get('portfolio_market_cap', '无法计算')}` USD",
        f"- 本地模拟隔离: `{reconciliation.get('local_simulation_isolated', True)}`",
        "",
        "## 逐标的盈亏",
        "",
        "| 标的 | 名称 | 盈亏 | 持仓市值 | 投入成本 | 是否持仓 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in symbol_rows[:30]:
        if not isinstance(row, dict):
            continue
        lines.append(
            "| "
            f"`{row.get('security_code') or row.get('code') or ''}` | "
            f"{row.get('name', '')} | "
            f"{row.get('profit', row.get('underlying_profit', ''))} | "
            f"{row.get('holding_value', '')} | "
            f"{row.get('invest_cost', '')} | "
            f"{row.get('is_holding', '')} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 只读取长桥模拟账户、长桥组合和长桥盈亏分析接口。",
            "- 不使用本地模拟账本，不使用旧版利润字段。",
            "- 不提交、不撤单、不改订单。",
            "",
        ]
    )
    return "\n".join(lines)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(json_ready(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(json_ready(row), ensure_ascii=False, sort_keys=True) + "\n")


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return fmt_decimal(value)
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def parse_utc_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, ""):
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f") if value == value.to_integral_value() else format(value, "f")


def fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY))


def pct_from_rate(value: Decimal) -> str:
    return str((value * Decimal("100")).quantize(MONEY))
