#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time as wall_time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_realtime_execution_lib import DEFAULT_DAILY_DIR, parse_utc_datetime, to_iso


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_paper_session_report.json"
SUMMARY_JSON = "m15_longbridge_paper_session_report.json"
REPORT_MD = "m15_longbridge_paper_session_report.md"
RECONCILIATION_CSV = "m15_longbridge_paper_order_reconciliation.csv"
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class SessionReportConfig:
    stage: str
    title: str
    output_dir: Path
    execution_ledger_path: Path
    execution_summary_path: Path
    account_state_path: Path
    position_manager_path: Path
    session_supervisor_path: Path
    market_timezone: str
    regular_session_start_time: str
    first_window_minutes: int
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


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> SessionReportConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    report = payload.get("report", {})
    return SessionReportConfig(
        stage=str(payload.get("stage", "M15.longbridge_paper_session_report")),
        title=str(payload.get("title", "长桥模拟账户交易报告")),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        execution_ledger_path=resolve_repo_path(inputs.get("execution_ledger", DEFAULT_OUTPUT_DIR / "m15_longbridge_realtime_execution_ledger.jsonl")),
        execution_summary_path=resolve_repo_path(inputs.get("execution_summary", DEFAULT_OUTPUT_DIR / "m15_longbridge_realtime_execution.json")),
        account_state_path=resolve_repo_path(inputs.get("account_state", DEFAULT_OUTPUT_DIR / "m15_longbridge_realtime_account_state.json")),
        position_manager_path=resolve_repo_path(inputs.get("position_manager", DEFAULT_OUTPUT_DIR / "m15_longbridge_realtime_position_manager.json")),
        session_supervisor_path=resolve_repo_path(inputs.get("session_supervisor", DEFAULT_OUTPUT_DIR / "m15_longbridge_realtime_session_supervisor.json")),
        market_timezone=str(report.get("market_timezone", "America/New_York")),
        regular_session_start_time=str(report.get("regular_session_start_time", "09:30")),
        first_window_minutes=int(report.get("first_window_minutes", 60)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: SessionReportConfig) -> None:
    if config.stage != "M15.longbridge_paper_session_report":
        raise ValueError("M15 paper session report stage drift")
    if config.first_window_minutes <= 0:
        raise ValueError("first_window_minutes must be positive")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("session report must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("session report cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("session report cannot enable real money actions")
    if config.hard_boundaries.get("local_simulation_as_order_source", False):
        raise ValueError("session report cannot use local simulation as order source")
    if config.hard_boundaries.get("manual_m12_37_once", False):
        raise ValueError("session report cannot enable manual M12.37 once-mode")


def run_session_report(config: SessionReportConfig | None = None, *, generated_at: str | None = None) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    execution_rows = read_jsonl(config.execution_ledger_path)
    execution_summary = read_json(config.execution_summary_path)
    account_state = read_json(config.account_state_path)
    position_manager = read_json(config.position_manager_path)
    session_supervisor = read_json(config.session_supervisor_path)
    market_date = infer_market_date(config, now, session_supervisor, account_state, execution_summary, execution_rows)
    window_start, window_end = first_window_bounds(config, market_date)
    submitted_rows = unique_submitted_orders(config, execution_rows, market_date)
    first_window_submitted = [row for row in submitted_rows if row_in_window(row, window_start, window_end)]
    after_window_submitted = [row for row in submitted_rows if not row_in_window(row, window_start, window_end)]
    reconciliation_rows = reconcile_orders(submitted_rows, account_state)
    current_positions = account_state.get("positions") if isinstance(account_state.get("positions"), list) else []
    current_open_orders = account_state.get("open_orders") if isinstance(account_state.get("open_orders"), list) else []
    blocked_by_reason = execution_summary.get("blocked_by_reason") if isinstance(execution_summary.get("blocked_by_reason"), dict) else {}
    latest_blocked_total = int_like(execution_summary.get("blocked_signal_count", 0))
    summary = {
        "schema_version": "m15.longbridge-paper-session-report.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at_iso,
        "market_date": market_date,
        "first_window": {
            "start": to_iso(window_start),
            "end": to_iso(window_end),
            "minutes": config.first_window_minutes,
        },
        "submitted_order_count": len(submitted_rows),
        "first_window_submitted_order_count": len(first_window_submitted),
        "after_first_window_submitted_order_count": len(after_window_submitted),
        "submitted_buy_count": count_if(submitted_rows, "side", "buy"),
        "submitted_sell_count": count_if(submitted_rows, "side", "sell"),
        "current_position_count": len(current_positions),
        "current_open_order_count": len(current_open_orders),
        "current_position_symbols": [base_symbol(str(row.get("symbol", ""))) for row in current_positions if isinstance(row, dict)],
        "current_open_order_symbols": [base_symbol(str(row.get("symbol", ""))) for row in current_open_orders if isinstance(row, dict)],
        "account": {
            "generated_at": account_state.get("generated_at", ""),
            "account_channel": account_state.get("account_channel", ""),
            "paper_account_verified": bool(account_state.get("paper_account_verified", False)),
            "cash": str(account_state.get("cash", "")),
            "buying_power": str(account_state.get("buying_power", "")),
            "total_position_notional": str(account_state.get("total_position_notional", "0")),
            "total_open_order_notional": str(account_state.get("total_open_order_notional", "0")),
        },
        "latest_execution": {
            "generated_at": execution_summary.get("generated_at", ""),
            "ready_order_count": int_like(execution_summary.get("ready_order_count", 0)),
            "submitted_count_this_cycle": int_like(execution_summary.get("submitted_count", 0)),
            "blocked_signal_count": latest_blocked_total,
            "blocked_by_reason": blocked_by_reason,
        },
        "position_manager": {
            "generated_at": position_manager.get("generated_at", ""),
            "managed_position_count": int_like(position_manager.get("managed_position_count", 0)),
            "new_exit_signal_event_count": int_like(position_manager.get("new_exit_signal_event_count", 0)),
            "blocked_by_reason": position_manager.get("blocked_by_reason", {}),
        },
        "reconciliation": reconciliation_summary(reconciliation_rows),
        "reconciliation_rows": reconciliation_rows,
        "plain_language_result": plain_language_result(
            len(submitted_rows),
            len(first_window_submitted),
            len(current_positions),
            len(current_open_orders),
            latest_blocked_total,
            blocked_by_reason,
        ),
        "inputs": {
            "execution_ledger": project_path(config.execution_ledger_path),
            "execution_summary": project_path(config.execution_summary_path),
            "account_state": project_path(config.account_state_path),
            "position_manager": project_path(config.position_manager_path),
            "session_supervisor": project_path(config.session_supervisor_path),
        },
        "outputs": {
            "summary": project_path(config.output_dir / SUMMARY_JSON),
            "report": project_path(config.output_dir / REPORT_MD),
            "reconciliation_csv": project_path(config.output_dir / RECONCILIATION_CSV),
        },
        "local_simulation_isolated": True,
        "paper_simulated_only": True,
        "real_money_actions": False,
        "live_execution": False,
    }
    write_json(config.output_dir / SUMMARY_JSON, summary)
    write_reconciliation_csv(config.output_dir / RECONCILIATION_CSV, reconciliation_rows)
    (config.output_dir / REPORT_MD).write_text(render_report(summary), encoding="utf-8")
    return summary


def infer_market_date(
    config: SessionReportConfig,
    now: datetime,
    session_supervisor: dict[str, Any],
    account_state: dict[str, Any],
    execution_summary: dict[str, Any],
    execution_rows: list[dict[str, Any]],
) -> str:
    window = session_supervisor.get("window") if isinstance(session_supervisor.get("window"), dict) else {}
    for value in (window.get("market_date"), account_state.get("market_date"), execution_summary.get("market_date")):
        if value:
            return str(value)
    for row in reversed(execution_rows):
        market_date = row_market_date(config, row)
        if market_date:
            return market_date
    return now.astimezone(ZoneInfo(config.market_timezone)).date().isoformat()


def first_window_bounds(config: SessionReportConfig, market_date: str) -> tuple[datetime, datetime]:
    hour, minute = config.regular_session_start_time.split(":")
    start = datetime.combine(
        datetime.fromisoformat(market_date).date(),
        wall_time(int(hour), int(minute)),
        tzinfo=ZoneInfo(config.market_timezone),
    ).astimezone(UTC)
    return start, start + timedelta(minutes=config.first_window_minutes)


def unique_submitted_orders(config: SessionReportConfig, rows: list[dict[str, Any]], market_date: str) -> list[dict[str, Any]]:
    submitted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("submission_status") != "submitted":
            continue
        if row_market_date(config, row) != market_date:
            continue
        key = str(row.get("signal_id") or row.get("submitted_at") or row.get("symbol") or len(seen))
        if key in seen:
            continue
        seen.add(key)
        submitted.append(row)
    submitted.sort(key=lambda row: str(row.get("submitted_at") or row.get("processed_at") or row.get("created_at") or ""))
    return submitted


def row_market_date(config: SessionReportConfig, row: dict[str, Any]) -> str:
    for key in ("submitted_at", "processed_at", "created_at", "generated_at"):
        value = str(row.get(key) or "")
        if not value:
            continue
        try:
            return parse_utc_datetime(value).astimezone(ZoneInfo(config.market_timezone)).date().isoformat()
        except ValueError:
            continue
    return ""


def row_in_window(row: dict[str, Any], start: datetime, end: datetime) -> bool:
    timestamp = parse_row_timestamp(row)
    return bool(timestamp and start <= timestamp <= end)


def parse_row_timestamp(row: dict[str, Any]) -> datetime | None:
    for key in ("submitted_at", "processed_at", "created_at", "generated_at"):
        value = str(row.get(key) or "")
        if not value:
            continue
        try:
            return parse_utc_datetime(value)
        except ValueError:
            continue
    return None


def reconcile_orders(submitted_rows: list[dict[str, Any]], account_state: dict[str, Any]) -> list[dict[str, Any]]:
    positions = account_state.get("positions") if isinstance(account_state.get("positions"), list) else []
    account_orders = account_state.get("orders") if isinstance(account_state.get("orders"), list) else []
    open_orders = account_state.get("open_orders") if isinstance(account_state.get("open_orders"), list) else []
    matchable_orders = account_orders if account_orders else open_orders
    position_qty_by_symbol: dict[str, Decimal] = {}
    for row in positions:
        if not isinstance(row, dict):
            continue
        symbol = base_symbol(str(row.get("symbol", "")))
        position_qty_by_symbol[symbol] = position_qty_by_symbol.get(symbol, Decimal("0")) + decimal(row.get("quantity", "0"))
    sell_rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in submitted_rows:
        if normalize_side(row.get("side")) == "sell":
            symbol = base_symbol(str(row.get("symbol", "")))
            sell_rows_by_symbol.setdefault(symbol, []).append(row)
    output: list[dict[str, Any]] = []
    for row in submitted_rows:
        symbol = base_symbol(str(row.get("symbol", "")))
        side = normalize_side(row.get("side"))
        quantity = decimal(row.get("quantity", "0"))
        limit_price = decimal(row.get("limit_price", "0"))
        matched_order = match_account_order(matchable_orders, symbol, side, quantity, limit_price)
        direct_order_id = extract_submission_order_id(row)
        inferred_order_id = str(matched_order.get("order_id") or "") if matched_order else ""
        status = "unmatched"
        note = "未在长桥今日订单、当前持仓或挂单里找到对应记录"
        if matched_order and is_open_account_order(matched_order):
            status = "open_order"
            note = "当前仍是长桥未成交挂单"
        elif side == "buy" and position_qty_by_symbol.get(symbol, Decimal("0")) >= quantity:
            status = "materialized_position"
            note = "已体现在长桥当前持仓里"
        elif side == "buy" and later_sell_quantity(sell_rows_by_symbol.get(symbol, []), row) >= quantity:
            status = "closed_or_flattened_by_later_sell"
            note = "买入后已有实时卖出信号，当前账户不再显示该持仓"
        elif side == "sell" and position_qty_by_symbol.get(symbol, Decimal("0")) <= Decimal("0"):
            status = "sell_materialized_flat_position"
            note = "卖出后当前账户没有该标的多头"
        elif matched_order:
            status = "matched_account_order"
            note = "已在长桥今日订单列表里找到对应订单"
        output.append(
            {
                "submitted_at": str(row.get("submitted_at") or ""),
                "signal_id": str(row.get("signal_id") or ""),
                "runtime_id": str(row.get("runtime_id") or ""),
                "strategy_id": str(row.get("strategy_id") or ""),
                "symbol": symbol,
                "side": side,
                "order_type": str(row.get("order_type") or ""),
                "quantity": str(row.get("quantity") or ""),
                "limit_price": str(row.get("limit_price") or ""),
                "trigger_price": str(row.get("trigger_price") or ""),
                "notional": str(row.get("notional") or ""),
                "direct_order_id": direct_order_id,
                "inferred_order_id": inferred_order_id,
                "reconciliation_status": status,
                "account_order_status": str(matched_order.get("status") or "") if matched_order else "",
                "account_executed_quantity": str(matched_order.get("executed_quantity") or "") if matched_order else "",
                "note": note,
            }
        )
    return output


def extract_submission_order_id(row: dict[str, Any]) -> str:
    for key in ("order_id", "longbridge_order_id"):
        value = str(row.get(key) or "")
        if value:
            return value
    submission_response = row.get("submission_response")
    if isinstance(submission_response, dict):
        for key in ("order_id", "id", "longbridge_order_id"):
            value = str(submission_response.get(key) or "")
            if value:
                return value
        response = submission_response.get("response")
        if isinstance(response, dict):
            for key in ("order_id", "id", "longbridge_order_id"):
                value = str(response.get(key) or "")
                if value:
                    return value
    return ""


def later_sell_quantity(sell_rows: list[dict[str, Any]], buy_row: dict[str, Any]) -> Decimal:
    buy_timestamp = parse_row_timestamp(buy_row)
    quantity = Decimal("0")
    for sell_row in sell_rows:
        sell_timestamp = parse_row_timestamp(sell_row)
        if buy_timestamp and sell_timestamp and sell_timestamp <= buy_timestamp:
            continue
        quantity += decimal(sell_row.get("quantity", "0"))
    return quantity


def match_account_order(account_orders: list[Any], symbol: str, side: str, quantity: Decimal, limit_price: Decimal) -> dict[str, Any]:
    account_side = "buy" if side == "buy" else "sell"
    for row in account_orders:
        if not isinstance(row, dict):
            continue
        if base_symbol(str(row.get("symbol", ""))) != symbol:
            continue
        if normalize_side(row.get("side")) != account_side:
            continue
        if decimal(row.get("quantity", "0")) != quantity:
            continue
        if abs(decimal(row.get("price", "0")) - limit_price) > Decimal("0.01"):
            continue
        return row
    return {}


def is_open_account_order(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").strip().lower().replace(" ", "_")
    executed_quantity = decimal(row.get("executed_quantity", row.get("filled_quantity", "0")))
    total_quantity = decimal(row.get("quantity", row.get("qty", "0")))
    if status in {"new", "submitted", "pending", "pending_submit", "open", "partially_filled", "partial_filled"}:
        return total_quantity <= ZERO or executed_quantity < total_quantity
    return False


def reconciliation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    direct_order_id_count = 0
    inferred_order_id_count = 0
    reconciled_order_id_count = 0
    for row in rows:
        status = str(row.get("reconciliation_status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        if row.get("direct_order_id"):
            direct_order_id_count += 1
        if row.get("inferred_order_id"):
            inferred_order_id_count += 1
        if row.get("direct_order_id") or row.get("inferred_order_id"):
            reconciled_order_id_count += 1
    return {
        "status_counts": dict(sorted(counts.items())),
        "direct_order_id_count": direct_order_id_count,
        "inferred_order_id_count": inferred_order_id_count,
        "reconciled_order_id_count": reconciled_order_id_count,
        "missing_direct_order_id_count": max(0, len(rows) - direct_order_id_count),
        "unresolved_order_id_count": max(0, len(rows) - reconciled_order_id_count),
        "unmatched_count": counts.get("unmatched", 0),
    }


def plain_language_result(
    submitted_count: int,
    first_window_count: int,
    position_count: int,
    open_order_count: int,
    latest_blocked_total: int,
    blocked_by_reason: dict[str, Any],
) -> str:
    exposure_blocks = int_like(blocked_by_reason.get("blocked_total_exposure_over_cap", 0))
    return (
        f"长桥模拟账户今日累计提交 {submitted_count} 笔模拟订单，其中开盘后首小时提交 {first_window_count} 笔；"
        f"当前账户有 {position_count} 个持仓、{open_order_count} 个挂单。"
        f"最新一轮没有新提交，主要原因是总敞口风控阻断 {exposure_blocks}/{latest_blocked_total} 条信号。"
    )


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# 长桥模拟账户交易报告",
        "",
        f"- 生成时间: `{summary['generated_at']}`",
        f"- 交易日: `{summary['market_date']}`",
        f"- 首小时窗口: `{summary['first_window']['start']}` 到 `{summary['first_window']['end']}`",
        f"- 结论: {summary['plain_language_result']}",
        "",
        "## 总览",
        "",
        f"- 今日累计提交: `{summary['submitted_order_count']}`",
        f"- 首小时提交: `{summary['first_window_submitted_order_count']}`",
        f"- 首小时后提交: `{summary['after_first_window_submitted_order_count']}`",
        f"- 买入 / 卖出: `{summary['submitted_buy_count']} / {summary['submitted_sell_count']}`",
        f"- 当前持仓 / 挂单: `{summary['current_position_count']} / {summary['current_open_order_count']}`",
        f"- 当前持仓标的: `{', '.join(summary['current_position_symbols']) or '暂无'}`",
        f"- 当前挂单标的: `{', '.join(summary['current_open_order_symbols']) or '暂无'}`",
        "",
        "## 最新阻断",
        "",
    ]
    for reason, count in summary["latest_execution"]["blocked_by_reason"].items():
        lines.append(f"- `{reason}`: `{count}`")
    lines.extend(
        [
            "",
            "## 订单对账",
            "",
            f"- 已对上订单号: `{summary['reconciliation']['reconciled_order_id_count']}`",
            f"- 提交瞬间直接返回订单号: `{summary['reconciliation']['direct_order_id_count']}`",
            f"- 通过长桥今日订单列表补齐订单号: `{summary['reconciliation']['inferred_order_id_count']}`",
            f"- 仍缺订单号: `{summary['reconciliation']['unresolved_order_id_count']}`",
            f"- 未匹配订单: `{summary['reconciliation']['unmatched_count']}`",
            "",
            "| 时间 | 运行单元 | 标的 | 方向 | 数量 | 限价 | 对账状态 | 订单号 | 说明 |",
            "|---|---|---:|---|---:|---:|---|---|---|",
        ]
    )
    for row in summary["reconciliation_rows"]:
        order_id = row.get("direct_order_id") or row.get("inferred_order_id") or ""
        lines.append(
            f"| `{row['submitted_at']}` | `{row['runtime_id']}` | `{row['symbol']}` | `{row['side']}` | "
            f"`{row['quantity']}` | `{row['limit_price']}` | `{row['reconciliation_status']}` | `{order_id}` | {row['note']} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 本报告只读 M15 实时执行流水和长桥模拟账户状态。",
            "- 不读取本地模拟账本作为下单依据，不触发 M12.37 once-mode。",
            "- 不提交、撤销或修改订单，不触碰实盘或真实资金。",
            "",
        ]
    )
    return "\n".join(lines)


def write_reconciliation_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "submitted_at",
        "signal_id",
        "runtime_id",
        "strategy_id",
        "symbol",
        "side",
        "order_type",
        "quantity",
        "limit_price",
        "trigger_price",
        "notional",
        "direct_order_id",
        "inferred_order_id",
        "reconciliation_status",
        "account_order_status",
        "account_executed_quantity",
        "note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def count_if(rows: list[dict[str, Any]], key: str, value: str) -> int:
    return sum(1 for row in rows if normalize_side(row.get(key)) == value)


def normalize_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "long", "open_long", "bullish", "看涨", "买入", "做多"}:
        return "buy"
    if text in {"sell", "close_long", "sell_long", "平仓", "卖出平多", "sell"}:
        return "sell"
    return text


def base_symbol(symbol: str) -> str:
    return symbol.upper().split(".")[0]


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def int_like(value: Any) -> int:
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return 0


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
