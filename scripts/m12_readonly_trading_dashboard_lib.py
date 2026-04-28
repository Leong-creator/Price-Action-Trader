#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_readonly_trading_dashboard.json"
OUTPUT_DIR = M10_DIR / "dashboard" / "m12_11_readonly_trading_dashboard"
WAVE_A_EQUITY_DIR = M10_DIR / "capital_backtest" / "m10_8_wave_a" / "m10_8_wave_a_equity_curves"
TIER_A = ("M10-PA-001", "M10-PA-002", "M10-PA-012")
PRIORITY_VISUAL = ("M10-PA-008", "M10-PA-009")
DEFINITION_OVERLAY = ("M10-PA-004", "M10-PA-005", "M10-PA-007")
FORBIDDEN_OUTPUT_TEXT = (
    "PA-SC-",
    "SF-",
    "live-ready",
    "order_id",
    "fill_price",
    "account_id",
    "broker_connection=true",
    "paper approval",
)
FORBIDDEN_OUTPUT_WORDS = ("order", "fill", "account", "broker", "position", "cash")
FORBIDDEN_JSON_KEYS = {
    "order",
    "order_id",
    "fill",
    "fill_price",
    "position",
    "cash",
    "account",
    "account_id",
    "broker",
}

DISPLAY_LABELS = {
    "not_approved": "未批准",
    "continue_read_only_observation": "继续只读观察",
    "manual_visual_review_required": "等待图形复核",
    "reject_for_now_after_geometry_review": "暂不继续",
    "visual_only_not_backtestable_without_manual_labels": "只做图形研究",
    "watchlist_after_priority_cases": "观察名单",
    "not_current_week_focus": "暂非本周重点",
    "not_independent_trigger": "非独立策略",
    "skip_no_trade": "跳过，未交易",
    "continue_observation": "继续观察",
    "long": "看涨",
    "short": "看跌",
    "none": "无方向",
    "1d": "日线",
    "1h": "1小时",
    "15m": "15分钟",
    "5m": "5分钟",
    "closed": "已收盘",
    "complete": "已完成",
    "unavailable": "暂无",
}


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    title: str
    run_id: str
    output_dir: Path
    m12_1_feed_manifest_path: Path
    m12_1_feed_ledger_path: Path
    m12_2_observation_events_path: Path
    m12_2_status_matrix_path: Path
    m12_5_scanner_candidates_path: Path
    m12_5_scanner_summary_path: Path
    m12_6_strategy_dashboard_path: Path
    m12_8_cache_summary_path: Path
    m12_8_available_universe_path: Path
    m12_10_retest_summary_path: Path
    m12_10_field_ledger_path: Path
    m11_5_gate_summary_path: Path
    m10_12_scorecard_summary_path: Path
    m10_12_decision_matrix_path: Path
    paper_simulated_only: bool
    paper_trading_approval: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def project_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def load_dashboard_config(path: str | Path = DEFAULT_CONFIG_PATH) -> DashboardConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    config = DashboardConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_11_readonly_trading_dashboard"),
        output_dir=resolve_repo_path(payload["output_dir"]),
        m12_1_feed_manifest_path=resolve_repo_path(payload["m12_1_feed_manifest_path"]),
        m12_1_feed_ledger_path=resolve_repo_path(payload["m12_1_feed_ledger_path"]),
        m12_2_observation_events_path=resolve_repo_path(payload["m12_2_observation_events_path"]),
        m12_2_status_matrix_path=resolve_repo_path(payload["m12_2_status_matrix_path"]),
        m12_5_scanner_candidates_path=resolve_repo_path(payload["m12_5_scanner_candidates_path"]),
        m12_5_scanner_summary_path=resolve_repo_path(payload["m12_5_scanner_summary_path"]),
        m12_6_strategy_dashboard_path=resolve_repo_path(payload["m12_6_strategy_dashboard_path"]),
        m12_8_cache_summary_path=resolve_repo_path(payload["m12_8_cache_summary_path"]),
        m12_8_available_universe_path=resolve_repo_path(payload["m12_8_available_universe_path"]),
        m12_10_retest_summary_path=resolve_repo_path(payload["m12_10_retest_summary_path"]),
        m12_10_field_ledger_path=resolve_repo_path(payload["m12_10_field_ledger_path"]),
        m11_5_gate_summary_path=resolve_repo_path(payload["m11_5_gate_summary_path"]),
        m10_12_scorecard_summary_path=resolve_repo_path(payload["m10_12_scorecard_summary_path"]),
        m10_12_decision_matrix_path=resolve_repo_path(payload["m10_12_decision_matrix_path"]),
        paper_simulated_only=bool(payload["paper_simulated_only"]),
        paper_trading_approval=bool(payload["paper_trading_approval"]),
        trading_connection=bool(payload["trading_connection"]),
        real_money_actions=bool(payload["real_money_actions"]),
        live_execution=bool(payload["live_execution"]),
    )
    validate_dashboard_config(config)
    return config


def validate_dashboard_config(config: DashboardConfig) -> None:
    if not config.paper_simulated_only:
        raise ValueError("M12.11 dashboard must remain paper/simulated only")
    if config.paper_trading_approval or config.trading_connection or config.real_money_actions or config.live_execution:
        raise ValueError("M12.11 dashboard must not enable trading connection, real money actions, or live execution")


def run_m12_readonly_trading_dashboard(
    config: DashboardConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_dashboard_config()
    validate_dashboard_config(config)
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    config.output_dir.mkdir(parents=True, exist_ok=True)

    feed_manifest = load_json(config.m12_1_feed_manifest_path)
    feed_events = load_jsonl(config.m12_1_feed_ledger_path)
    observation_events = read_csv(config.m12_2_observation_events_path)
    observation_status = load_json(config.m12_2_status_matrix_path)
    scanner_candidates = read_csv(config.m12_5_scanner_candidates_path)
    scanner_summary = load_json(config.m12_5_scanner_summary_path)
    weekly_rows = read_csv(config.m12_6_strategy_dashboard_path)
    cache_summary = load_json(config.m12_8_cache_summary_path)
    available_universe = load_json(config.m12_8_available_universe_path)
    definition_summary = load_json(config.m12_10_retest_summary_path)
    definition_ledger = load_json(config.m12_10_field_ledger_path)
    gate_summary = load_json(config.m11_5_gate_summary_path)
    scorecard_summary = load_json(config.m10_12_scorecard_summary_path)
    decision_matrix = load_json(config.m10_12_decision_matrix_path)

    readonly_quotes = build_readonly_quotes(feed_events)
    strategy_statuses = build_strategy_statuses(weekly_rows, definition_summary, definition_ledger)
    scanner_rows = build_scanner_rows(scanner_candidates, readonly_quotes)
    observation_rows = build_observation_rows(observation_events)
    equity_curves = build_equity_curve_refs(config.output_dir)
    dashboard = build_dashboard_data(
        config=config,
        generated_at=generated_at,
        feed_manifest=feed_manifest,
        observation_status=observation_status,
        scanner_summary=scanner_summary,
        cache_summary=cache_summary,
        available_universe=available_universe,
        definition_summary=definition_summary,
        gate_summary=gate_summary,
        scorecard_summary=scorecard_summary,
        decision_matrix=decision_matrix,
        readonly_quotes=readonly_quotes,
        strategy_statuses=strategy_statuses,
        scanner_rows=scanner_rows,
        observation_rows=observation_rows,
        equity_curves=equity_curves,
    )

    write_json(config.output_dir / "m12_11_dashboard_data.json", dashboard)
    (config.output_dir / "m12_11_readonly_trading_dashboard.html").write_text(
        build_dashboard_html(dashboard),
        encoding="utf-8",
    )
    (config.output_dir / "m12_11_dashboard_snapshot.md").write_text(
        build_snapshot_report(dashboard),
        encoding="utf-8",
    )
    (config.output_dir / "m12_11_handoff.md").write_text(
        build_handoff(config, dashboard),
        encoding="utf-8",
    )
    assert_no_forbidden_output(config.output_dir)
    return dashboard


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def decimal_or_none(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def text_or_unavailable(value: str | None) -> str:
    return value if value not in (None, "") else "unavailable"


def display_value(value: Any) -> str:
    text = str(value)
    return DISPLAY_LABELS.get(text, text)


def display_number_or_na(value: Any) -> str:
    return "暂无" if value in (None, "", "unavailable") else str(value)


def sanitize_dashboard_text(value: str) -> str:
    return (
        value.replace("portfolio order book", "portfolio ledger")
        .replace("order book", "ledger")
        .replace("orders", "records")
    )


def sanitize_dashboard_title(value: str) -> str:
    return (
        sanitize_dashboard_text(value)
        .replace("Limit-Order Framework", "Limit Framework")
        .replace("Limit Order Framework", "Limit Framework")
        .replace("Limit-Order", "Limit Framework")
        .replace("Limit Order", "Limit Framework")
        .replace("Position Sizing", "Risk Sizing")
        .replace("Position", "Risk")
    )


def sanitize_blocker_text(value: str) -> str:
    translations = {
        "Requires manual labels or a new detector before any automated retest.": "需要人工标注或新识别器，之后才可能自动复测。",
        "Priority visual case confirmation is still required before gate evidence.": "关键图形样例仍需要你确认，确认前不能作为准入证据。",
        "PA005 has geometry fields, but remains rejected for now after review.": "PA005 已补齐几何字段，但复核后仍暂不继续。",
    }
    return translations.get(value, sanitize_dashboard_text(value))


def build_readonly_quotes(feed_events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    timeframe_rank = {"5m": 0, "15m": 1, "1h": 2, "1d": 3}
    for row in sorted(feed_events, key=lambda item: timeframe_rank.get(item["timeframe"], 99)):
        symbol = row["symbol"]
        if symbol in by_symbol:
            continue
        ohlcv = row.get("ohlcv", {})
        by_symbol[symbol] = {
            "symbol": symbol,
            "readonly_last_price": text_or_unavailable(ohlcv.get("close")),
            "readonly_last_price_timeframe": row["timeframe"],
            "readonly_last_bar_timestamp": row["bar_timestamp"],
            "readonly_bar_status": row["bar_status"],
            "readonly_source": row["source"],
        }
    return by_symbol


def build_scanner_rows(candidates: list[dict[str, str]], quotes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in candidates:
        quote = quotes.get(row["symbol"], {})
        latest = decimal_or_none(str(quote.get("readonly_last_price", "")))
        entry = decimal_or_none(row.get("entry_price"))
        risk = decimal_or_none(row.get("risk_per_share"))
        direction = row.get("signal_direction", "")
        hypothetical_r = ""
        hypothetical_pnl_per_share = ""
        if latest is not None and entry is not None and risk is not None and risk > 0:
            pnl = latest - entry if direction == "long" else entry - latest
            hypothetical_pnl_per_share = f"{pnl:.4f}"
            hypothetical_r = f"{(pnl / risk):.4f}"
        rows.append(
            {
                "strategy_id": row["strategy_id"],
                "strategy_title": sanitize_dashboard_title(row["strategy_title"]),
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "candidate_status": row["candidate_status"],
                "signal_direction": direction,
                "bar_timestamp": row["bar_timestamp"],
                "hypothetical_entry_price": text_or_unavailable(row.get("entry_price")),
                "hypothetical_stop_price": text_or_unavailable(row.get("stop_price")),
                "hypothetical_target_price": text_or_unavailable(row.get("target_price")),
                "hypothetical_risk_per_share": text_or_unavailable(row.get("risk_per_share")),
                "readonly_last_price": text_or_unavailable(str(quote.get("readonly_last_price", ""))),
                "readonly_last_price_timeframe": text_or_unavailable(str(quote.get("readonly_last_price_timeframe", ""))),
                "hypothetical_pnl_per_share": hypothetical_pnl_per_share or "unavailable",
                "hypothetical_unrealized_r": hypothetical_r or "unavailable",
                "risk_level": row["risk_level"],
                "review_status": row["review_status"],
                "queue_action": row["queue_action"],
                "data_lineage": row["data_lineage"],
            }
        )
    return rows


def build_observation_rows(events: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "strategy_id": row["strategy_id"],
            "strategy_title": sanitize_dashboard_title(row["strategy_title"]),
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "bar_timestamp": row["bar_timestamp"],
            "event_kind": row["event_kind"],
            "event_code": row["event_code"],
            "review_status": row["review_status"],
            "direction": row["direction"],
            "hypothetical_entry_price": text_or_unavailable(row.get("entry_price")),
            "hypothetical_stop_price": text_or_unavailable(row.get("stop_price")),
            "hypothetical_target_price": text_or_unavailable(row.get("target_price")),
            "data_provider": row["data_provider"],
            "lineage": row["lineage"],
        }
        for row in events
    ]


def build_strategy_statuses(
    weekly_rows: list[dict[str, str]],
    definition_summary: dict[str, Any],
    definition_ledger: dict[str, Any],
) -> list[dict[str, Any]]:
    definition_decisions = {
        row["strategy_id"]: row["definition_decision"]
        for row in definition_ledger.get("strategy_rows", [])
    }
    visual_decisions = definition_summary.get("visual_definition_decisions", {})
    rows: list[dict[str, Any]] = []
    for row in weekly_rows:
        strategy_id = row["strategy_id"]
        dashboard_status = row["current_week_status"]
        blocker = row["client_note"]
        if strategy_id == "M10-PA-005":
            dashboard_status = definition_summary["pa005_decision"]
            blocker = "PA005 已补齐几何字段，但复核后仍暂不继续。"
        elif strategy_id in visual_decisions:
            dashboard_status = visual_decisions[strategy_id]
            blocker = "需要人工标注或新识别器，之后才可能自动复测。"
        elif strategy_id in PRIORITY_VISUAL:
            dashboard_status = "manual_visual_review_required"
            blocker = "关键图形样例仍需要你确认，确认前不能作为准入证据。"
        rows.append(
            {
                "strategy_id": strategy_id,
                "display_title": sanitize_dashboard_title(row["title"]),
                "dashboard_status": dashboard_status,
                "capital_test_status": row["capital_test_status"],
                "client_status": row["client_status"],
                "simulated_initial_capital": text_or_unavailable(row.get("initial_capital")),
                "simulated_final_equity": text_or_unavailable(row.get("final_equity")),
                "simulated_net_profit": text_or_unavailable(row.get("net_profit")),
                "simulated_return_percent": text_or_unavailable(row.get("return_percent")),
                "simulated_win_rate": text_or_unavailable(row.get("win_rate")),
                "simulated_profit_factor": text_or_unavailable(row.get("profit_factor")),
                "simulated_max_drawdown_percent": text_or_unavailable(row.get("max_drawdown_percent")),
                "simulated_trade_count": text_or_unavailable(row.get("trade_count")),
                "readonly_observation_events": row["daily_observation_events"],
                "readonly_skip_no_trade": row["daily_skip_no_trade"],
                "scanner_candidates": row["scanner_candidates"],
                "scanner_trigger_candidates": row["scanner_trigger_candidates"],
                "scanner_watch_candidates": row["scanner_watch_candidates"],
                "visual_pending_review_count": row["visual_pending_review_count"],
                "definition_decision": definition_decisions.get(strategy_id, row.get("definition_status", "")),
                "blocker_or_next_action": sanitize_blocker_text(blocker),
            }
        )
    return rows


def build_equity_curve_refs(output_dir: Path) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for strategy_id in TIER_A:
        for path in sorted(WAVE_A_EQUITY_DIR.glob(f"{strategy_id}_*_baseline_equity.svg")):
            timeframe = path.name.removeprefix(f"{strategy_id}_").removesuffix("_baseline_equity.svg")
            refs.append(
                {
                    "strategy_id": strategy_id,
                    "timeframe": timeframe,
                    "simulated_equity_curve_ref": project_path(path),
                    "html_relative_src": os.path.relpath(path, output_dir),
                    "curve_semantics": "simulated_historical_equity_curve",
                }
            )
    return refs


def build_dashboard_data(
    *,
    config: DashboardConfig,
    generated_at: str,
    feed_manifest: dict[str, Any],
    observation_status: dict[str, Any],
    scanner_summary: dict[str, Any],
    cache_summary: dict[str, Any],
    available_universe: dict[str, Any],
    definition_summary: dict[str, Any],
    gate_summary: dict[str, Any],
    scorecard_summary: dict[str, Any],
    decision_matrix: dict[str, Any],
    readonly_quotes: dict[str, dict[str, Any]],
    strategy_statuses: list[dict[str, Any]],
    scanner_rows: list[dict[str, Any]],
    observation_rows: list[dict[str, Any]],
    equity_curves: list[dict[str, str]],
) -> dict[str, Any]:
    status_counts = Counter(row["dashboard_status"] for row in strategy_statuses)
    scanner_counts = Counter(row["candidate_status"] for row in scanner_rows)
    return {
        "schema_version": "m12.11.readonly-trading-dashboard.v1",
        "stage": "M12.11.readonly_trading_dashboard",
        "run_id": config.run_id,
        "generated_at": generated_at,
        "paper_simulated_only": True,
        "paper_trading_approval": False,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "dashboard_mode": "local_readonly_snapshot",
        "input_refs": {
            "feed_manifest": project_path(config.m12_1_feed_manifest_path),
            "feed_ledger": project_path(config.m12_1_feed_ledger_path),
            "observation_events": project_path(config.m12_2_observation_events_path),
            "scanner_candidates": project_path(config.m12_5_scanner_candidates_path),
            "strategy_dashboard": project_path(config.m12_6_strategy_dashboard_path),
            "cache_summary": project_path(config.m12_8_cache_summary_path),
            "definition_summary": project_path(config.m12_10_retest_summary_path),
            "gate_summary": project_path(config.m11_5_gate_summary_path),
            "scorecard_summary": project_path(config.m10_12_scorecard_summary_path),
            "decision_matrix": project_path(config.m10_12_decision_matrix_path),
        },
        "summary": {
            "readonly_symbol_count": len(readonly_quotes),
            "readonly_feed_rows": feed_manifest["ledger_row_count"],
            "readonly_observation_events": observation_status["event_count"],
            "readonly_skip_no_trade": observation_status["skip_no_trade_count"],
            "scanner_candidates": scanner_summary["candidate_count"],
            "scanner_trigger_candidates": scanner_counts.get("trigger_candidate", 0),
            "scanner_watch_candidates": scanner_counts.get("watch_candidate", 0),
            "scanner_universe_symbols": scanner_summary["universe_symbol_count"],
            "scanner_deferred_symbols": scanner_summary["deferred_symbol_count"],
            "cache_target_complete_symbols": cache_summary["target_complete_symbol_count"],
            "cache_present_symbols": available_universe["cache_present_symbol_count"],
            "strategy_count": len(strategy_statuses),
            "paper_gate_decision": gate_summary["gate_decision"],
            "blocking_condition_count": gate_summary["blocking_condition_count"],
            "pa005_decision": definition_summary["pa005_decision"],
            "pa005_geometry_event_count": definition_summary["pa005_geometry_event_count"],
            "pa005_geometry_event_id_unique": definition_summary["pa005_geometry_event_id_unique"],
            "simulated_portfolio_proxy_final_equity": scorecard_summary.get("portfolio_proxy", {}).get("proxy_final_equity", "unavailable"),
            "simulated_portfolio_proxy_net_profit": scorecard_summary.get("portfolio_proxy", {}).get("proxy_net_profit", "unavailable"),
            "simulated_portfolio_proxy_not_executable_reason": sanitize_dashboard_text(
                scorecard_summary.get("portfolio_proxy", {}).get("not_executable_reason", "unavailable")
            ),
            "simulated_equity_curve_count": len(equity_curves),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "readonly_quotes": list(readonly_quotes.values()),
        "scanner_candidates": scanner_rows,
        "observation_events": observation_rows,
        "strategy_statuses": strategy_statuses,
        "simulated_equity_curves": equity_curves,
    }


def build_dashboard_html(dashboard: dict[str, Any]) -> str:
    data = html.escape(json.dumps(dashboard, ensure_ascii=False, sort_keys=True))
    summary = dashboard["summary"]
    cards = [
        ("今日候选", summary["scanner_candidates"], "扫描出的机会"),
        ("观察记录", summary["readonly_observation_events"], "只读记录"),
        ("跳过次数", summary["readonly_skip_no_trade"], "条件不满足"),
        ("股票池缓存", f"{summary['cache_present_symbols']}/{summary['scanner_universe_symbols']}", "已有本地数据"),
        ("准入状态", display_value(summary["paper_gate_decision"]), "不能纸面交易"),
    ]
    card_html = "\n".join(
        f'<section class="metric-card"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong><small>{html.escape(note)}</small></section>'
        for label, value, note in cards
    )
    candidate_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row['symbol'])}</td>"
        f"<td>{html.escape(row['strategy_id'])}</td>"
        f"<td>{html.escape(display_value(row['timeframe']))}</td>"
        f"<td>{html.escape(display_value(row['signal_direction']))}</td>"
        f"<td>{html.escape(display_number_or_na(row['hypothetical_entry_price']))}</td>"
        f"<td>{html.escape(display_number_or_na(row['hypothetical_stop_price']))}</td>"
        f"<td>{html.escape(display_number_or_na(row['hypothetical_target_price']))}</td>"
        f"<td>{html.escape(display_number_or_na(row['readonly_last_price']))}</td>"
        f"<td>{html.escape(display_number_or_na(row['hypothetical_unrealized_r']))}</td>"
        f"<td>{html.escape(display_value(row['review_status']))}</td>"
        "</tr>"
        for row in dashboard["scanner_candidates"]
    )
    status_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row['strategy_id'])}</td>"
        f"<td>{html.escape(row['display_title'])}</td>"
        f"<td>{html.escape(display_value(row['dashboard_status']))}</td>"
        f"<td>{html.escape(display_number_or_na(row['simulated_net_profit']))}</td>"
        f"<td>{html.escape(display_number_or_na(row['simulated_win_rate']))}</td>"
        f"<td>{html.escape(display_number_or_na(row['simulated_max_drawdown_percent']))}</td>"
        f"<td>{html.escape(row['scanner_candidates'])}</td>"
        f"<td>{html.escape(row['blocker_or_next_action'])}</td>"
        "</tr>"
        for row in dashboard["strategy_statuses"]
    )
    quote_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row['symbol'])}</td>"
        f"<td>{html.escape(display_number_or_na(row['readonly_last_price']))}</td>"
        f"<td>{html.escape(display_value(row['readonly_last_price_timeframe']))}</td>"
        f"<td>{html.escape(row['readonly_last_bar_timestamp'])}</td>"
        f"<td>{html.escape(display_value(row['readonly_bar_status']))}</td>"
        "</tr>"
        for row in dashboard["readonly_quotes"]
    )
    curve_cards = "\n".join(
        "<figure class=\"curve-card\">"
        f"<img src=\"{html.escape(row['html_relative_src'])}\" alt=\"{html.escape(row['strategy_id'])} {html.escape(display_value(row['timeframe']))} 模拟资金曲线\">"
        f"<figcaption>{html.escape(row['strategy_id'])} {html.escape(display_value(row['timeframe']))} 模拟资金曲线</figcaption>"
        "</figure>"
        for row in dashboard["simulated_equity_curves"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>M12.11 只读交易看板</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --ink: #1d2430;
      --muted: #5c6675;
      --line: #d8dde5;
      --accent: #0b6b8a;
      --accent-2: #8a5a0b;
      --danger: #a33a2a;
      --ok: #21734d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, "Noto Sans SC", sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
    }}
    header {{
      padding: 20px 24px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: end;
    }}
    h1 {{ font-size: 24px; margin: 0 0 6px; line-height: 1.2; }}
    .sub {{ color: var(--muted); font-size: 13px; }}
    main {{ padding: 18px 24px 28px; display: grid; gap: 18px; }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(140px, 1fr));
      gap: 10px;
    }}
    .metric-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 88px;
      padding: 12px;
      display: grid;
      gap: 6px;
    }}
    .metric-card span, th {{ color: var(--muted); font-size: 12px; font-weight: 600; text-transform: uppercase; }}
    .metric-card strong {{ font-size: 22px; line-height: 1.1; color: var(--accent); overflow-wrap: anywhere; }}
    .metric-card small {{ color: var(--muted); }}
    section.table-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    section.table-panel h2 {{
      margin: 0;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      font-size: 16px;
      line-height: 1.25;
    }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: auto; min-width: 960px; }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 9px 10px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
      line-height: 1.35;
    }}
    td {{ overflow-wrap: anywhere; }}
    tbody tr:hover {{ background: #f1f5f8; }}
    .status-line {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      font-size: 13px;
      color: var(--muted);
    }}
    .badge {{
      display: inline-block;
      padding: 4px 7px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      color: var(--muted);
      font-size: 12px;
    }}
    .curve-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(190px, 1fr));
      gap: 10px;
      padding: 12px;
    }}
    .curve-card {{
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: #fbfcfd;
    }}
    .curve-card img {{
      display: block;
      width: 100%;
      height: 150px;
      object-fit: contain;
      background: #ffffff;
    }}
    .curve-card figcaption {{
      padding: 7px 9px;
      color: var(--muted);
      font-size: 12px;
      border-top: 1px solid var(--line);
    }}
    @media (max-width: 900px) {{
      header {{ align-items: start; flex-direction: column; }}
      main {{ padding: 14px; }}
      .metric-grid {{ grid-template-columns: repeat(2, minmax(130px, 1fr)); }}
      .curve-grid {{ grid-template-columns: repeat(2, minmax(150px, 1fr)); }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>M12.11 只读交易看板</h1>
      <div class="sub">快照时间 {html.escape(dashboard['generated_at'])}</div>
    </div>
    <div class="status-line">
      <span class="badge">仅模拟</span>
      <span class="badge">不接交易账户</span>
      <span class="badge">不碰真实资金</span>
      <span class="badge">不实盘执行</span>
    </div>
  </header>
  <main>
    <div class="metric-grid">
      {card_html}
    </div>
    <section class="table-panel">
      <h2>今日候选机会</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>标的</th><th>策略</th><th>周期</th><th>方向</th><th>假设入场价</th><th>假设止损价</th><th>假设目标价</th><th>当前参考价</th><th>假设盈亏 R</th><th>复核状态</th></tr></thead>
          <tbody>{candidate_rows}</tbody>
        </table>
      </div>
    </section>
    <section class="table-panel">
      <h2>策略状态</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>策略</th><th>当前状态</th><th>模拟收益</th><th>模拟胜率</th><th>最大回撤 %</th><th>候选数</th><th>阻塞 / 下一步</th></tr></thead>
          <tbody>{status_rows}</tbody>
        </table>
      </div>
    </section>
    <section class="table-panel">
      <h2>模拟资金曲线</h2>
      <div class="curve-grid">{curve_cards}</div>
    </section>
    <section class="table-panel">
      <h2>只读行情参考</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>标的</th><th>最新参考价</th><th>周期</th><th>K 线时间</th><th>状态</th></tr></thead>
          <tbody>{quote_rows}</tbody>
        </table>
      </div>
    </section>
  </main>
  <script type="application/json" id="dashboard-data">{data}</script>
</body>
</html>
"""


def build_snapshot_report(dashboard: dict[str, Any]) -> str:
    summary = dashboard["summary"]
    lines = [
        "# M12.11 只读交易看板快照",
        "",
        "## 摘要",
        "",
        f"- 今日候选机会：`{summary['scanner_candidates']}`",
        f"- 只读观察记录：`{summary['readonly_observation_events']}`",
        f"- 跳过次数：`{summary['readonly_skip_no_trade']}`",
        f"- 已有本地数据的标的：`{summary['cache_present_symbols']}` / `{summary['scanner_universe_symbols']}`",
        f"- 完整覆盖目标窗口的标的：`{summary['cache_target_complete_symbols']}`",
        f"- 纸面交易准入：`{display_value(summary['paper_gate_decision'])}`",
        f"- PA005 当前结论：`{display_value(summary['pa005_decision'])}`",
        f"- 模拟资金曲线数量：`{summary['simulated_equity_curve_count']}`",
        "",
        "## 边界",
        "",
        "- 看板只消费既有只读 / 模拟 artifacts。",
        "- 看板只显示 readonly、hypothetical、simulated 字段。",
        "- 当前不批准 paper trading，也不产生真实资金行为。",
    ]
    return "\n".join(lines) + "\n"


def build_handoff(config: DashboardConfig, dashboard: dict[str, Any]) -> str:
    return f"""task_id: M12.11 Read-only Trading Dashboard
role: main_agent
branch_or_worktree: feature/m12-11-readonly-trading-dashboard
objective: Build a local read-only dashboard snapshot from M12 artifacts for client-facing monitoring.
status: success
files_changed:
  - config/examples/m12_readonly_trading_dashboard.json
  - scripts/m12_readonly_trading_dashboard_lib.py
  - scripts/run_m12_readonly_trading_dashboard.py
  - tests/unit/test_m12_readonly_trading_dashboard.py
  - reports/strategy_lab/m10_price_action_strategy_refresh/dashboard/m12_11_readonly_trading_dashboard/
interfaces_changed:
  - Added M12.11 dashboard data JSON and static HTML report.
commands_run:
  - python scripts/run_m12_readonly_trading_dashboard.py
tests_run:
  - python -m unittest tests/unit/test_m12_readonly_trading_dashboard.py -v
assumptions:
  - Dashboard uses M12.1 kline close as readonly_last_price, not a real-time quote stream.
  - Hypothetical PnL is per-share and derived from scanner candidate fields only.
risks:
  - M12.8 universe cache coverage is incomplete; dashboard must show deferred coverage rather than full-universe readiness.
qa_focus:
  - Confirm only readonly/hypothetical/simulated fields appear.
  - Confirm scanner candidates and strategy statuses match source artifacts.
  - Confirm no trading connection or real money actions are enabled.
rollback_notes:
  - Revert M12.11 commit or remove {project_path(config.output_dir)} artifacts.
next_recommended_action: Continue M12.12 daily observation loop after dashboard review.
needs_user_decision: false
user_decision_needed:
summary:
  scanner_candidates: {dashboard['summary']['scanner_candidates']}
  readonly_observation_events: {dashboard['summary']['readonly_observation_events']}
  paper_gate_decision: {dashboard['summary']['paper_gate_decision']}
"""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in output_dir.glob("m12_11_*") if path.is_file())
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_TEXT:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden M12.11 output text found: {forbidden}")
    for forbidden in FORBIDDEN_OUTPUT_WORDS:
        if re.search(rf"\b{re.escape(forbidden)}\b", lowered):
            raise ValueError(f"Forbidden M12.11 output word found: {forbidden}")
    data_path = output_dir / "m12_11_dashboard_data.json"
    if data_path.exists():
        assert_no_forbidden_json_keys(json.loads(data_path.read_text(encoding="utf-8")))


def assert_no_forbidden_json_keys(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_JSON_KEYS:
                raise ValueError(f"Forbidden M12.11 JSON key found: {key}")
            assert_no_forbidden_json_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            assert_no_forbidden_json_keys(item)


def main() -> int:
    dashboard = run_m12_readonly_trading_dashboard()
    print(
        "M12.11 read-only trading dashboard complete: "
        f"scanner_candidates={dashboard['summary']['scanner_candidates']} / "
        f"paper_gate_decision={dashboard['summary']['paper_gate_decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
