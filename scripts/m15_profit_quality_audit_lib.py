#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_profit_quality_audit.json"
DEFAULT_DAILY_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
)
DEFAULT_M12_DIR = DEFAULT_DAILY_DIR / "m12_29_current_day_scan_dashboard"
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_profit_quality_audit"
AUDIT_JSON = "m15_profit_quality_audit.json"
AUDIT_MD = "m15_profit_quality_audit.md"
NY_TZ = ZoneInfo("America/New_York")
MONEY = Decimal("0.01")
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ProfitQualityAuditConfig:
    stage: str
    dashboard_path: Path
    runtime_state_path: Path
    output_dir: Path
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


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ProfitQualityAuditConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    config = ProfitQualityAuditConfig(
        stage=str(payload.get("stage", "M15.profit_quality_audit")),
        dashboard_path=resolve_repo_path(inputs.get("m12_32_dashboard", DEFAULT_M12_DIR / "m12_32_minute_readonly_dashboard_data.json")),
        runtime_state_path=resolve_repo_path(inputs.get("m12_46_account_runtime_state", DEFAULT_M12_DIR / "m12_46_account_runtime_state.json")),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    return config


def validate_config(config: ProfitQualityAuditConfig) -> None:
    if config.stage != "M15.profit_quality_audit":
        raise ValueError("M15 profit quality audit stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M15 profit quality audit must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval", "manual_m12_37_once"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M15 profit quality audit cannot enable {key}")


def run_profit_quality_audit(
    config: ProfitQualityAuditConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = build_profit_quality_audit(config, generated_at)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / AUDIT_JSON, payload)
    (config.output_dir / AUDIT_MD).write_text(render_markdown(payload), encoding="utf-8")
    return payload


def build_profit_quality_audit(config: ProfitQualityAuditConfig, generated_at: str) -> dict[str, Any]:
    dashboard = read_json(config.dashboard_path)
    runtime_state = read_json(config.runtime_state_path)
    summary = dict(dashboard.get("summary", dashboard))
    scan_date = parse_date(str(summary.get("scan_date", ""))) or date.today()
    quote_source = str(summary.get("quote_source", ""))
    boundary_flags = {
        "paper_simulated_only": bool(dashboard.get("paper_simulated_only", summary.get("paper_simulated_only", False))),
        "broker_connection": bool(dashboard.get("trading_connection", summary.get("trading_connection", False))),
        "real_order": bool(dashboard.get("real_money_actions", summary.get("real_money_actions", False))),
        "live_execution": bool(dashboard.get("live_execution", summary.get("live_execution", False))),
        "paper_trading_approval": bool(dashboard.get("paper_trading_approval", summary.get("paper_trading_approval", False))),
        "manual_m12_37_once": False,
    }
    boundary_violation = any(
        boundary_flags[key]
        for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval", "manual_m12_37_once")
    ) or not boundary_flags["paper_simulated_only"]
    fallback_or_no_fetch = text_has_fallback_or_no_fetch(
        quote_source,
        summary.get("data_freshness_warning", ""),
        summary.get("plain_language_result", ""),
    )

    closed_rows: list[dict[str, Any]] = []
    open_rows: list[dict[str, Any]] = []
    account_rows: list[dict[str, Any]] = []
    accounts = runtime_state.get("accounts", {})
    if not isinstance(accounts, dict):
        accounts = {}

    for runtime_id, account in sorted(accounts.items()):
        account_row = build_account_row(str(runtime_id), account, scan_date)
        account_rows.append(account_row)
        for trade in account.get("closed_trades", []) or []:
            if trading_date_of(trade.get("event_time")) == scan_date:
                closed_rows.append(build_closed_trade_row(str(runtime_id), account, trade, scan_date))
        for position in account.get("open_positions", []) or []:
            open_rows.append(build_open_position_row(str(runtime_id), account, position, scan_date))

    closed_rows.sort(key=lambda row: abs_money(row["pnl"]), reverse=True)
    open_rows.sort(key=lambda row: abs_money(row["pnl"]), reverse=True)
    account_rows.sort(key=lambda row: abs_money(row["today_total_pnl"]), reverse=True)

    category_summary = build_category_summary(closed_rows, open_rows)
    symbol_summary = build_symbol_summary(closed_rows, open_rows)
    runtime_summary = build_runtime_summary(closed_rows, open_rows)
    top_contributors = sorted(
        closed_rows + open_rows,
        key=lambda row: abs_money(row["pnl"]),
        reverse=True,
    )[:20]
    concentration = build_concentration(top_contributors, category_summary["total_today_pnl"])
    audit_status = classify_audit_status(boundary_violation, fallback_or_no_fetch, quote_source)
    quality_notes = build_quality_notes(audit_status, category_summary, symbol_summary, concentration)

    payload = {
        "schema_version": "m15.profit-quality-audit.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m12_32_dashboard": project_path(config.dashboard_path),
            "m12_46_account_runtime_state": project_path(config.runtime_state_path),
        },
        "scan_date": scan_date.isoformat(),
        "dashboard_generated_at": str(dashboard.get("generated_at", summary.get("generated_at", ""))),
        "quote_source": quote_source,
        "audit_status": audit_status,
        "fallback_or_no_fetch_data": fallback_or_no_fetch,
        "boundary_flags": boundary_flags,
        "category_summary": category_summary,
        "concentration": concentration,
        "quality_notes": quality_notes,
        "account_rows": account_rows[:30],
        "top_contributors": top_contributors,
        "top_closed_trades": closed_rows[:30],
        "top_open_positions": open_rows[:30],
        "symbol_summary": symbol_summary[:30],
        "runtime_summary": runtime_summary[:30],
        "plain_language_result": build_plain_language_result(audit_status, category_summary, symbol_summary, top_contributors),
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
            "manual_m12_37_once": False,
        },
    }
    assert_no_legacy_profit_fields(payload)
    return payload


def build_account_row(runtime_id: str, account: dict[str, Any], scan_date: date) -> dict[str, Any]:
    return {
        "runtime_id": runtime_id,
        "display_name": str(account.get("display_name", "")),
        "strategy_id": str(account.get("strategy_id", "")),
        "timeframe": str(account.get("timeframe", "")),
        "lane": str(account.get("lane", "")),
        "today_total_pnl": fmt_money(decimal(account.get("today_total_pnl", "0"))),
        "today_realized_pnl": fmt_money(decimal(account.get("today_realized_pnl", "0"))),
        "today_unrealized_pnl": fmt_money(decimal(account.get("today_unrealized_pnl", "0"))),
        "today_closed_count": int_or_zero(account.get("today_closed_count")),
        "today_opened_count": int_or_zero(account.get("today_opened_count")),
        "open_position_count": len(account.get("open_positions", []) or []),
        "equity": fmt_money(decimal(account.get("equity", "0"))),
        "scan_date": scan_date.isoformat(),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
    }


def build_closed_trade_row(runtime_id: str, account: dict[str, Any], trade: dict[str, Any], scan_date: date) -> dict[str, Any]:
    opened_date = trading_date_of(trade.get("opened_at"))
    signal_date = trading_date_of(trade.get("signal_time")) or parse_date(str(trade.get("signal_date", "")))
    category = "today_opened_and_closed" if opened_date == scan_date else "prior_position_closed_today"
    pnl = decimal(trade.get("realized_pnl", "0"))
    row = {
        "row_type": "closed_trade",
        "quality_bucket": category,
        "runtime_id": runtime_id,
        "display_name": str(account.get("display_name", "")),
        "strategy_id": str(account.get("strategy_id", "")),
        "lane": str(account.get("lane", "")),
        "symbol": str(trade.get("symbol", "")),
        "timeframe": str(trade.get("timeframe", account.get("timeframe", ""))),
        "direction": normalize_direction(str(trade.get("direction", ""))),
        "pnl": fmt_money(pnl),
        "entry_price": fmt_decimal(decimal(trade.get("entry_price", "0"))),
        "exit_price": fmt_decimal(decimal(trade.get("exit_price", "0"))),
        "quantity": fmt_decimal(decimal(trade.get("quantity", "0"))),
        "exit_reason": str(trade.get("exit_reason", "")),
        "price_source": str(trade.get("exit_price_source", "")),
        "opened_at": str(trade.get("opened_at", "")),
        "signal_time": str(trade.get("signal_time", "")),
        "event_time": str(trade.get("event_time", "")),
        "opened_trading_date": opened_date.isoformat() if opened_date else "",
        "signal_trading_date": signal_date.isoformat() if signal_date else "",
        "event_trading_date": scan_date.isoformat(),
        "simulation_only": True,
        "broker_fill": False,
        "real_cash_profit": False,
    }
    row["quality_flags"] = quality_flags_for_row(row)
    return row


def build_open_position_row(runtime_id: str, account: dict[str, Any], position: dict[str, Any], scan_date: date) -> dict[str, Any]:
    opened_date = trading_date_of(position.get("opened_at"))
    signal_date = trading_date_of(position.get("signal_time")) or parse_date(str(position.get("signal_date", "")))
    category = "today_open_position_unrealized" if opened_date == scan_date else "prior_open_position_unrealized"
    row = {
        "row_type": "open_position",
        "quality_bucket": category,
        "runtime_id": runtime_id,
        "display_name": str(account.get("display_name", "")),
        "strategy_id": str(account.get("strategy_id", "")),
        "lane": str(account.get("lane", "")),
        "symbol": str(position.get("symbol", "")),
        "timeframe": str(position.get("timeframe", account.get("timeframe", ""))),
        "direction": normalize_direction(str(position.get("direction", ""))),
        "pnl": fmt_money(decimal(position.get("current_pnl", "0"))),
        "entry_price": fmt_decimal(decimal(position.get("entry_price", "0"))),
        "latest_price": fmt_decimal(decimal(position.get("latest_price", "0"))),
        "quantity": fmt_decimal(decimal(position.get("quantity", "0"))),
        "exit_reason": "未平仓浮动盈亏",
        "price_source": str(position.get("latest_price_source", "")),
        "opened_at": str(position.get("opened_at", "")),
        "signal_time": str(position.get("signal_time", position.get("signal_date", ""))),
        "opened_trading_date": opened_date.isoformat() if opened_date else "",
        "signal_trading_date": signal_date.isoformat() if signal_date else "",
        "event_trading_date": scan_date.isoformat(),
        "simulation_only": True,
        "broker_fill": False,
        "real_cash_profit": False,
    }
    row["quality_flags"] = quality_flags_for_row(row)
    return row


def quality_flags_for_row(row: dict[str, Any]) -> list[str]:
    flags = ["内部模拟", "没有真实成交"]
    if row["price_source"] == "longbridge_quote_readonly":
        flags.append("长桥只读行情估值")
    elif text_has_fallback_or_no_fetch(row["price_source"]):
        flags.append("备用行情或未抓取数据")
    elif row["price_source"]:
        flags.append("非长桥主行情估值")
    if row["quality_bucket"] == "prior_position_closed_today":
        flags.append("旧持仓今天平仓")
    elif row["quality_bucket"] == "today_opened_and_closed":
        flags.append("今天新开新平")
    elif row["quality_bucket"] == "prior_open_position_unrealized":
        flags.append("旧持仓当前浮盈浮亏")
    else:
        flags.append("今天新开仓当前浮盈浮亏")
    if row["exit_reason"] in ("持仓到期退出", "次日超时退出"):
        flags.append("按模拟规则超时退出")
    if abs_money(row["pnl"]) >= Decimal("500"):
        flags.append("大额单笔贡献")
    return flags


def build_category_summary(closed_rows: list[dict[str, Any]], open_rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = {
        "today_opened_and_closed": {"label": "今天新开新平", "row_count": 0, "pnl": ZERO},
        "prior_position_closed_today": {"label": "旧持仓今天平仓", "row_count": 0, "pnl": ZERO},
        "today_open_position_unrealized": {"label": "今天新开仓当前浮盈浮亏", "row_count": 0, "pnl": ZERO},
        "prior_open_position_unrealized": {"label": "旧持仓当前浮盈浮亏", "row_count": 0, "pnl": ZERO},
    }
    for row in closed_rows + open_rows:
        bucket = buckets[row["quality_bucket"]]
        bucket["row_count"] += 1
        bucket["pnl"] += decimal(row["pnl"])
    closed_pnl = sum((decimal(row["pnl"]) for row in closed_rows), ZERO)
    open_pnl = sum((decimal(row["pnl"]) for row in open_rows), ZERO)
    total = closed_pnl + open_pnl
    return {
        "total_today_pnl": fmt_money(total),
        "closed_today_pnl": fmt_money(closed_pnl),
        "unrealized_current_pnl": fmt_money(open_pnl),
        "closed_trade_count": len(closed_rows),
        "open_position_count": len(open_rows),
        "buckets": [
            {
                "bucket": key,
                "label": value["label"],
                "row_count": value["row_count"],
                "pnl": fmt_money(value["pnl"]),
                "share_of_total_abs": fmt_decimal(safe_abs_share(value["pnl"], total)),
            }
            for key, value in buckets.items()
        ],
    }


def build_symbol_summary(closed_rows: list[dict[str, Any]], open_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = defaultdict(lambda: {"pnl": ZERO, "closed_count": 0, "open_count": 0, "runtime_ids": set()})
    for row in closed_rows:
        bucket = by_symbol[row["symbol"]]
        bucket["pnl"] += decimal(row["pnl"])
        bucket["closed_count"] += 1
        bucket["runtime_ids"].add(row["runtime_id"])
    for row in open_rows:
        bucket = by_symbol[row["symbol"]]
        bucket["pnl"] += decimal(row["pnl"])
        bucket["open_count"] += 1
        bucket["runtime_ids"].add(row["runtime_id"])
    rows = [
        {
            "symbol": symbol,
            "pnl": fmt_money(value["pnl"]),
            "closed_count": value["closed_count"],
            "open_position_count": value["open_count"],
            "runtime_count": len(value["runtime_ids"]),
            "runtime_ids": sorted(value["runtime_ids"]),
        }
        for symbol, value in by_symbol.items()
        if symbol
    ]
    rows.sort(key=lambda row: abs_money(row["pnl"]), reverse=True)
    return rows


def build_runtime_summary(closed_rows: list[dict[str, Any]], open_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_runtime: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"pnl": ZERO, "closed_count": 0, "open_count": 0, "symbols": set(), "display_name": "", "lane": ""}
    )
    for row in closed_rows + open_rows:
        bucket = by_runtime[row["runtime_id"]]
        bucket["pnl"] += decimal(row["pnl"])
        bucket["symbols"].add(row["symbol"])
        bucket["display_name"] = row["display_name"]
        bucket["lane"] = row["lane"]
        if row["row_type"] == "closed_trade":
            bucket["closed_count"] += 1
        else:
            bucket["open_count"] += 1
    rows = [
        {
            "runtime_id": runtime_id,
            "display_name": value["display_name"],
            "lane": value["lane"],
            "pnl": fmt_money(value["pnl"]),
            "closed_count": value["closed_count"],
            "open_position_count": value["open_count"],
            "symbol_count": len(value["symbols"]),
            "symbols": sorted(value["symbols"]),
        }
        for runtime_id, value in by_runtime.items()
    ]
    rows.sort(key=lambda row: abs_money(row["pnl"]), reverse=True)
    return rows


def build_concentration(top_contributors: list[dict[str, Any]], total_pnl: str) -> dict[str, Any]:
    total = decimal(total_pnl)
    top_abs_sum = sum((abs_money(row["pnl"]) for row in top_contributors[:5]), ZERO)
    top_symbol = top_contributors[0]["symbol"] if top_contributors else ""
    return {
        "top_contributor_symbol": top_symbol,
        "top_contributor_pnl": top_contributors[0]["pnl"] if top_contributors else "0.00",
        "top5_abs_pnl": fmt_money(top_abs_sum),
        "top5_abs_share_of_total_abs": fmt_decimal(safe_abs_share(top_abs_sum, total)),
    }


def classify_audit_status(boundary_violation: bool, fallback_or_no_fetch: bool, quote_source: str) -> str:
    if boundary_violation:
        return "boundary_violation"
    if fallback_or_no_fetch:
        return "not_verifiable_from_fresh_quotes"
    if quote_source == "longbridge_quote_readonly":
        return "simulated_mark_to_market_only"
    return "not_verified_by_primary_longbridge_quote"


def build_quality_notes(
    audit_status: str,
    category_summary: dict[str, Any],
    symbol_summary: list[dict[str, Any]],
    concentration: dict[str, Any],
) -> list[str]:
    notes: list[str] = []
    if audit_status == "simulated_mark_to_market_only":
        notes.append("当前利润来自内部模拟账户按长桥只读行情估值，不是账户现金利润。")
    elif audit_status == "not_verifiable_from_fresh_quotes":
        notes.append("当前行情不是 fresh 长桥只读行情，今日利润不能用于推进判断。")
    elif audit_status == "not_verified_by_primary_longbridge_quote":
        notes.append("当前看板顶层行情来源不是 longbridge_quote_readonly，今日利润只能当作辅助估值，不能作为进入长桥模拟账户的依据。")
    elif audit_status == "boundary_violation":
        notes.append("检测到交易边界异常，必须先停用账户/下单相关路径。")
    buckets = {row["bucket"]: row for row in category_summary["buckets"]}
    prior_closed = decimal(buckets["prior_position_closed_today"]["pnl"])
    if abs(prior_closed) > ZERO:
        notes.append(f"今日平仓利润里包含旧持仓今天退出：{fmt_money(prior_closed)}，不能理解为今天新信号直接赚到。")
    open_pnl = decimal(category_summary["unrealized_current_pnl"])
    if open_pnl != ZERO:
        notes.append(f"当前未平仓浮盈浮亏为 {fmt_money(open_pnl)}，这部分还没有平仓。")
    if symbol_summary:
        notes.append(
            f"最大标的贡献是 {symbol_summary[0]['symbol']}：{symbol_summary[0]['pnl']}，需要单独核对入场价、退出价和退出原因。"
        )
    if decimal(concentration["top5_abs_share_of_total_abs"]) >= Decimal("0.50"):
        notes.append("前 5 笔大额贡献占比很高，今天的利润质量存在集中度风险。")
    return notes


def build_plain_language_result(
    audit_status: str,
    category_summary: dict[str, Any],
    symbol_summary: list[dict[str, Any]],
    top_contributors: list[dict[str, Any]],
) -> str:
    status_text = {
        "simulated_mark_to_market_only": "今日高利润是内部模拟按长桥只读行情重估出来的，不是真实账户利润。",
        "not_verifiable_from_fresh_quotes": "今日利润不能确认，因为行情不是 fresh 长桥只读行情。",
        "not_verified_by_primary_longbridge_quote": "今日利润未通过长桥主行情确认，只能当作内部模拟辅助估值。",
        "boundary_violation": "检测到交易边界异常，不能信任该利润口径。",
        "needs_quote_source_review": "行情来源需要复核，利润只能当作模拟参考。",
    }.get(audit_status, "利润只能当作模拟参考。")
    top = top_contributors[0] if top_contributors else {}
    top_text = ""
    if top:
        top_text = f" 最大单笔是 {top.get('runtime_id')} 的 {top.get('symbol')}，{top.get('direction')}，{top.get('pnl')}，原因：{top.get('exit_reason')}。"
    return (
        f"{status_text} 合计模拟今日盈亏 {category_summary['total_today_pnl']}，"
        f"其中今日平仓 {category_summary['closed_today_pnl']}，当前浮盈浮亏 {category_summary['unrealized_current_pnl']}。"
        f"{top_text}"
    )


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# M15 今日利润质量审计",
        "",
        f"- 生成时间：`{payload['generated_at']}`",
        f"- 看板日期：`{payload['scan_date']}`",
        f"- 看板时间：`{payload['dashboard_generated_at']}`",
        f"- 行情来源：`{payload['quote_source']}`",
        f"- 审计状态：`{payload['audit_status']}`",
        f"- 人话结论：{payload['plain_language_result']}",
        "",
        "## 边界",
        "",
        "- 只读行情和内部模拟：是",
        "- 账户连接：否",
        "- 真实订单：否",
        "- 实盘执行：否",
        "- 长桥模拟账户下单批准：否",
        "- 手动运行 M12.37 一次性刷新：否",
        "",
        "## 利润拆分",
        "",
        "| 口径 | 笔数 | 盈亏 | 占总盈亏绝对值比例 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in payload["category_summary"]["buckets"]:
        lines.append(f"| {row['label']} | {row['row_count']} | {row['pnl']} | {row['share_of_total_abs']} |")
    lines.extend(
        [
            "",
            "## 质量提醒",
            "",
        ]
    )
    for note in payload["quality_notes"]:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## 大额贡献明细",
            "",
            "| 类型 | 运行单元 | 标的 | 方向 | 盈亏 | 入场 | 退出/最新 | 原因 | 价格来源 | 质量标签 |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in payload["top_contributors"][:20]:
        exit_or_latest = row.get("exit_price") or row.get("latest_price", "")
        lines.append(
            "| "
            + " | ".join(
                [
                    "已平仓" if row["row_type"] == "closed_trade" else "未平仓",
                    row["runtime_id"],
                    row["symbol"],
                    row["direction"],
                    row["pnl"],
                    row["entry_price"],
                    exit_or_latest,
                    row["exit_reason"],
                    row["price_source"],
                    "、".join(row["quality_flags"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 标的贡献",
            "",
            "| 标的 | 盈亏 | 平仓数 | 未平仓数 | 涉及运行单元数 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in payload["symbol_summary"][:20]:
        lines.append(f"| {row['symbol']} | {row['pnl']} | {row['closed_count']} | {row['open_position_count']} | {row['runtime_count']} |")
    lines.extend(
        [
            "",
            "## 运行单元贡献",
            "",
            "| 运行单元 | 分组 | 盈亏 | 平仓数 | 未平仓数 | 标的数 |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in payload["runtime_summary"][:20]:
        lines.append(
            f"| {row['runtime_id']} | {row['lane']} | {row['pnl']} | {row['closed_count']} | {row['open_position_count']} | {row['symbol_count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def assert_no_legacy_profit_fields(value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False)
    forbidden = ("historical_net_profit", "历史净利润", "历史收益", "历史盈利因子")
    found = [token for token in forbidden if token in text]
    if found:
        raise ValueError(f"legacy historical profit fields leaked into profit quality audit: {found}")


def trading_date_of(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value)
    parsed = parse_datetime(text)
    if parsed:
        return parsed.astimezone(NY_TZ).date()
    return parse_date(text[:10])


def parse_datetime(text: str) -> datetime | None:
    try:
        value = text.strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=NY_TZ)
        return parsed
    except ValueError:
        return None


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def normalize_direction(value: str) -> str:
    value = value.strip().lower()
    if value in ("long", "bullish", "看涨"):
        return "看涨"
    if value in ("short", "bearish", "看跌"):
        return "看跌"
    return value or "未知"


def text_has_fallback_or_no_fetch(*values: Any) -> bool:
    text = " ".join(str(value).lower() for value in values)
    return any(token in text for token in ("fallback", "no-fetch", "no_fetch", "no-refresh", "no_refresh", "旧快照"))


def int_or_zero(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def decimal(value: Any) -> Decimal:
    try:
        if value in (None, ""):
            return ZERO
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def abs_money(value: Any) -> Decimal:
    return abs(decimal(value))


def safe_abs_share(value: Decimal, total: Decimal) -> Decimal:
    denominator = abs(total)
    if denominator == ZERO:
        return ZERO
    return abs(value) / denominator


def fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY))


def fmt_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
