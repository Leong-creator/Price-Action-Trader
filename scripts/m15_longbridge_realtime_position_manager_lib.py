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

from scripts.m15_longbridge_realtime_execution_lib import (
    DEFAULT_DAILY_DIR,
    DEFAULT_OUTPUT_DIR,
    LEDGER_JSONL as EXECUTION_LEDGER_JSONL,
    decimal,
    fmt_decimal,
    fmt_money,
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
SUMMARY_JSON = "m15_longbridge_realtime_position_manager.json"
LEDGER_JSONL = "m15_longbridge_realtime_position_manager_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_position_manager.md"
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class RealtimePositionManagerConfig:
    stage: str
    title: str
    account_state_path: Path
    market_events_path: Path
    realtime_signal_events_path: Path
    realtime_execution_ledger_path: Path
    output_dir: Path
    max_exit_events_per_run: int
    exit_attempt_cooldown_seconds: int
    manage_untracked_positions_for_exit: bool
    untracked_stop_loss_percent: Decimal
    untracked_take_profit_percent: Decimal
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
    return RealtimePositionManagerConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_position_manager")),
        title=str(payload.get("title", "长桥模拟账户实时持仓退出管理")),
        account_state_path=resolve_repo_path(inputs.get("account_state", DEFAULT_ACCOUNT_STATE)),
        market_events_path=resolve_repo_path(inputs.get("market_events", DEFAULT_MARKET_EVENTS)),
        realtime_signal_events_path=resolve_repo_path(inputs.get("realtime_signal_events", DEFAULT_SIGNAL_EVENTS)),
        realtime_execution_ledger_path=resolve_repo_path(inputs.get("realtime_execution_ledger", DEFAULT_EXECUTION_LEDGER)),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        max_exit_events_per_run=int(manager.get("max_exit_events_per_run", 10)),
        exit_attempt_cooldown_seconds=int(manager.get("exit_attempt_cooldown_seconds", 900)),
        manage_untracked_positions_for_exit=bool(manager.get("manage_untracked_positions_for_exit", True)),
        untracked_stop_loss_percent=decimal(manager.get("untracked_stop_loss_percent", "3")),
        untracked_take_profit_percent=decimal(manager.get("untracked_take_profit_percent", "3")),
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
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 realtime position manager must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("M15 realtime position manager cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("M15 realtime position manager cannot enable real money actions")
    if config.hard_boundaries.get("local_simulation_as_exit_source", False):
        raise ValueError("M15 realtime position manager cannot use local simulation as exit source")
    if config.hard_boundaries.get("short_selling", False):
        raise ValueError("M15 realtime position manager cannot enable short selling")


def run_realtime_position_manager(
    config: RealtimePositionManagerConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    account_state = read_json(config.account_state_path)
    market_events = read_jsonl(config.market_events_path)
    execution_rows = read_jsonl(config.realtime_execution_ledger_path)
    existing_signal_events = read_jsonl(config.realtime_signal_events_path)
    existing_signal_ids = {str(row.get("signal_id")) for row in existing_signal_events if row.get("signal_id")}

    latest_prices = latest_price_by_symbol(market_events)
    position_slices = account_position_slices(account_state, execution_rows, config.manage_untracked_positions_for_exit)
    recent_exit_attempts = recent_exit_attempt_keys(execution_rows, now, config.exit_attempt_cooldown_seconds)
    ledger_rows: list[dict[str, Any]] = []
    exit_events: list[dict[str, Any]] = []
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
        )
        ledger_rows.append(row)
        if event and len(exit_events) < config.max_exit_events_per_run:
            exit_events.append(event)
            existing_signal_ids.add(event["signal_id"])

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.realtime_signal_events_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(config.realtime_signal_events_path, existing_signal_events + exit_events)
    write_jsonl(config.output_dir / LEDGER_JSONL, ledger_rows)
    summary = {
        "schema_version": "m15.longbridge-realtime-position-manager.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at_iso,
        "source_mode": "longbridge_account_positions_plus_realtime_market_events",
        "local_simulation_isolated": True,
        "local_close_signal_used": False,
        "position_count": len(position_slices),
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
        "blocked_by_reason": count_statuses(ledger_rows),
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "inputs": {
            "account_state": project_path(config.account_state_path),
            "market_events": project_path(config.market_events_path),
            "realtime_execution_ledger": project_path(config.realtime_execution_ledger_path),
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


def evaluate_position(
    config: RealtimePositionManagerConfig,
    position: dict[str, Any],
    metadata: dict[str, Any],
    latest_price: Decimal,
    generated_at: str,
    existing_signal_ids: set[str],
    recent_exit_attempts: set[tuple[str, str]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    symbol = str(position["symbol"])
    quantity = decimal(position.get("quantity", "0"))
    available_quantity = decimal(position.get("available", quantity))
    stop_price = decimal(metadata.get("stop_price", "0"))
    target_price = decimal(metadata.get("target_price", "0"))
    runtime_id = str(metadata.get("runtime_id", ""))
    strategy_id = str(metadata.get("strategy_id", ""))
    cost_price = position_cost_price(position)
    latest_for_pnl = latest_price if latest_price > ZERO else decimal(position.get("current_price", position.get("last_price", "0")))
    unrealized_pnl = (latest_for_pnl - cost_price) * quantity if latest_for_pnl > ZERO and cost_price > ZERO else ZERO
    status = "hold_no_exit_trigger"
    management_scope = "m15_realtime_managed"
    management_note = "本轮 M15 实时链路管理的长桥模拟账户持仓。"
    exit_reason = ""
    if not metadata:
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
    elif latest_price <= ZERO:
        status = "missing_latest_price"
    elif stop_price <= ZERO or target_price <= ZERO:
        status = "missing_stop_or_target_metadata"
    elif latest_price <= stop_price:
        status = "exit_signal_created"
        exit_reason = "stop_loss"
    elif latest_price >= target_price:
        status = "exit_signal_created"
        exit_reason = "take_profit"
    signal_id = ""
    event: dict[str, Any] | None = None
    if status == "exit_signal_created":
        signal_id = deterministic_exit_signal_id(
            symbol=symbol,
            runtime_id=runtime_id,
            exit_reason=exit_reason,
            source_open_signal_id=str(metadata.get("signal_id", "")),
        )
        if available_quantity <= ZERO:
            status = "position_not_available_for_exit"
        elif (symbol, exit_reason) in recent_exit_attempts:
            status = "recent_exit_attempt_cooldown"
        elif signal_id in existing_signal_ids:
            status = "duplicate_exit_signal_event"
        else:
            exit_quantity = min(quantity, available_quantity)
            event = {
                "signal_id": signal_id,
                "created_at": generated_at,
                "runtime_id": runtime_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "timeframe": str(metadata.get("timeframe", "")),
                "direction": "long",
                "side": "sell",
                "position_action": exit_reason,
                "order_type": "limit",
                "limit_price": fmt_money(latest_price),
                "current_price": fmt_money(latest_price),
                "quantity": fmt_decimal(exit_quantity),
                "notional": fmt_money(exit_quantity * latest_price),
                "risk_amount": "0.00",
                "net_profit_after_fees_at_target": "0.01",
                "source_market_event_id": str(metadata.get("source_market_event_id", "")),
                "source_open_signal_id": str(metadata.get("signal_id", "")),
                "local_simulation_source": False,
                "longbridge_position_exit_source": True,
                "longbridge_untracked_exit_only": management_scope == "longbridge_account_exit_only",
            }
    row = {
        "stage": config.stage,
        "symbol": symbol,
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
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
        "exit_allowed": management_scope in {"m15_realtime_managed", "longbridge_account_exit_only"},
        "exit_only_takeover": management_scope == "longbridge_account_exit_only",
        "local_simulation_ignored": True,
    }
    return row, event


def account_positions(account_state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_positions = account_state.get("positions")
    if not isinstance(raw_positions, list):
        return []
    positions: list[dict[str, Any]] = []
    for row in raw_positions:
        if not isinstance(row, dict):
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


def recent_exit_attempt_keys(
    execution_rows: list[dict[str, Any]],
    now: datetime,
    cooldown_seconds: int,
) -> set[tuple[str, str]]:
    attempts: set[tuple[str, str]] = set()
    for row in execution_rows:
        if str(row.get("side") or "").lower() != "sell":
            continue
        status = str(row.get("submission_status") or "")
        if not status or status == "blocked_not_submitted":
            continue
        attempted_at = parse_signal_time(row.get("submitted_at") or row.get("processed_at") or row.get("created_at"))
        if attempted_at and (now - attempted_at).total_seconds() > cooldown_seconds:
            continue
        symbol = base_symbol(str(row.get("symbol") or ""))
        exit_reason = str(row.get("position_action") or row.get("exit_reason") or "")
        if symbol and exit_reason:
            attempts.add((symbol, exit_reason))
    return attempts


def deterministic_exit_signal_id(
    *,
    symbol: str,
    runtime_id: str,
    exit_reason: str,
    source_open_signal_id: str = "",
    generated_at: str = "",
) -> str:
    del generated_at
    digest = sha256(f"{symbol}|{runtime_id}|{exit_reason}|{source_open_signal_id}".encode("utf-8")).hexdigest()[:16]
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
            "- 平仓是卖出已有多头，不是融券做空。",
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


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return fmt_decimal(value)
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value
