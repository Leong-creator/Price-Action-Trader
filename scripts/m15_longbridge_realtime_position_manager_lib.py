#!/usr/bin/env python3
from __future__ import annotations

import json
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
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: RealtimePositionManagerConfig) -> None:
    if config.stage != "M15.longbridge_realtime_position_manager":
        raise ValueError("M15 realtime position manager stage drift")
    if config.max_exit_events_per_run <= 0:
        raise ValueError("M15 realtime position manager max_exit_events_per_run must be positive")
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
    open_metadata = submitted_open_metadata(execution_rows)
    ledger_rows: list[dict[str, Any]] = []
    exit_events: list[dict[str, Any]] = []
    for position in account_positions(account_state):
        symbol = str(position["symbol"])
        metadata = open_metadata.get(symbol, {})
        latest = latest_prices.get(symbol, ZERO)
        row, event = evaluate_position(config, position, metadata, latest, generated_at_iso, existing_signal_ids)
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
        "position_count": len(account_positions(account_state)),
        "managed_position_count": sum(1 for row in ledger_rows if row.get("manager_status") != "no_submitted_open_metadata"),
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
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    symbol = str(position["symbol"])
    quantity = decimal(position.get("quantity", "0"))
    stop_price = decimal(metadata.get("stop_price", "0"))
    target_price = decimal(metadata.get("target_price", "0"))
    runtime_id = str(metadata.get("runtime_id", ""))
    status = "hold_no_exit_trigger"
    exit_reason = ""
    if not metadata:
        status = "no_submitted_open_metadata"
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
        signal_id = deterministic_exit_signal_id(symbol=symbol, runtime_id=runtime_id, exit_reason=exit_reason, generated_at=generated_at)
        if signal_id in existing_signal_ids:
            status = "duplicate_exit_signal_event"
        else:
            event = {
                "signal_id": signal_id,
                "created_at": generated_at,
                "runtime_id": runtime_id,
                "strategy_id": str(metadata.get("strategy_id", "")),
                "symbol": symbol,
                "timeframe": str(metadata.get("timeframe", "")),
                "direction": "long",
                "side": "sell",
                "position_action": exit_reason,
                "order_type": "limit",
                "limit_price": fmt_money(latest_price),
                "current_price": fmt_money(latest_price),
                "quantity": fmt_decimal(quantity),
                "notional": fmt_money(quantity * latest_price),
                "risk_amount": "0.00",
                "net_profit_after_fees_at_target": "0.01",
                "source_market_event_id": str(metadata.get("source_market_event_id", "")),
                "source_open_signal_id": str(metadata.get("signal_id", "")),
                "local_simulation_source": False,
                "longbridge_position_exit_source": True,
            }
    row = {
        "stage": config.stage,
        "symbol": symbol,
        "runtime_id": runtime_id,
        "quantity": fmt_decimal(quantity),
        "latest_price": fmt_money(latest_price) if latest_price > ZERO else "",
        "stop_price": fmt_money(stop_price) if stop_price > ZERO else "",
        "target_price": fmt_money(target_price) if target_price > ZERO else "",
        "manager_status": status,
        "exit_reason": exit_reason,
        "exit_signal_id": signal_id,
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


def submitted_open_metadata(execution_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for row in execution_rows:
        if row.get("submission_status") != "submitted":
            continue
        if row.get("side") != "buy":
            continue
        symbol = base_symbol(str(row.get("symbol", "")))
        if not symbol:
            continue
        metadata[symbol] = row
    return metadata


def deterministic_exit_signal_id(*, symbol: str, runtime_id: str, exit_reason: str, generated_at: str) -> str:
    digest = sha256(f"{symbol}|{runtime_id}|{exit_reason}|{generated_at}".encode("utf-8")).hexdigest()[:16]
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
    if rows:
        return "长桥持仓退出管理已检查账户持仓；当前没有触发止损或止盈。"
    return "长桥持仓退出管理已就绪；当前长桥账户没有可管理持仓。"


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 长桥模拟账户实时持仓退出管理",
        "",
        f"- 生成时间: `{summary['generated_at']}`",
        f"- 持仓数: `{summary['position_count']}`",
        f"- 新平仓信号: `{summary['new_exit_signal_event_count']}`",
        f"- 结论: {summary['plain_language_result']}",
        "",
        "| 标的 | 运行单元 | 状态 | 当前价 | 止损 | 目标 |",
        "|---|---|---|---:|---:|---:|",
    ]
    for row in rows[:30]:
        lines.append(
            f"| `{row.get('symbol', '')}` | `{row.get('runtime_id', '')}` | `{row.get('manager_status', '')}` | "
            f"`{row.get('latest_price', '')}` | `{row.get('stop_price', '')}` | `{row.get('target_price', '')}` |"
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
    path.write_text(json.dumps(json_ready(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(json_ready(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return fmt_decimal(value)
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value
