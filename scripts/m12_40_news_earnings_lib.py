#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_DASHBOARD_DIR = M10_DIR / "daily_observation" / "m12_29_current_day_scan_dashboard"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_40_news_earnings_pipeline.json"
MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")
ZERO = Decimal("0")
STARTING_CAPITAL = Decimal("100000")
FORBIDDEN_TEXT = (
    "real_orders=true",
    "broker_connection=true",
    "live_execution=true",
    "live-ready",
)


@dataclass(frozen=True, slots=True)
class M1240Config:
    output_root: Path
    dashboard_dir: Path
    trade_view_path: Path
    today_candidates_path: Path
    dashboard_json_path: Path
    first50_universe_path: Path
    ftd_trade_ledger_path: Path
    ftd_variant_metrics_path: Path
    strategy_closure_path: Path
    cache_coverage_path: Path
    universe147_coverage_path: Path
    event_seed: tuple[dict[str, Any], ...]
    macro_event_seed: tuple[dict[str, Any], ...]
    event_window_days: int
    gap_threshold_percent: Decimal
    paper_simulated_only: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool
    paper_trading_approval: bool


def resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M1240Config:
    payload = json.loads(resolve(path).read_text(encoding="utf-8"))
    boundary = payload["boundary"]
    config = M1240Config(
        output_root=resolve(payload["output_root"]),
        dashboard_dir=resolve(payload["dashboard_dir"]),
        trade_view_path=resolve(payload["trade_view_path"]),
        today_candidates_path=resolve(payload["today_candidates_path"]),
        dashboard_json_path=resolve(payload["dashboard_json_path"]),
        first50_universe_path=resolve(payload["first50_universe_path"]),
        ftd_trade_ledger_path=resolve(payload["ftd_trade_ledger_path"]),
        ftd_variant_metrics_path=resolve(payload["ftd_variant_metrics_path"]),
        strategy_closure_path=resolve(payload["strategy_closure_path"]),
        cache_coverage_path=resolve(payload["cache_coverage_path"]),
        universe147_coverage_path=resolve(payload["universe147_coverage_path"]),
        event_seed=tuple(payload.get("event_seed", [])),
        macro_event_seed=tuple(payload.get("macro_event_seed", [])),
        event_window_days=int(payload.get("event_window_days", 1)),
        gap_threshold_percent=decimal(payload.get("gap_threshold_percent", "3")),
        paper_simulated_only=bool(boundary["paper_simulated_only"]),
        trading_connection=bool(boundary["trading_connection"]),
        real_money_actions=bool(boundary["real_money_actions"]),
        live_execution=bool(boundary["live_execution"]),
        paper_trading_approval=bool(boundary["paper_trading_approval"]),
    )
    validate_boundary(config)
    return config


def validate_boundary(config: M1240Config) -> None:
    if not config.paper_simulated_only:
        raise ValueError("M12.40+ must stay paper/simulated only")
    if config.trading_connection or config.real_money_actions or config.live_execution or config.paper_trading_approval:
        raise ValueError("M12.40+ cannot enable account connection, real-money actions, live execution, or approval")


def decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return default


def money(value: Any) -> str:
    return str(decimal(value).quantize(MONEY))


def pct(value: Any) -> str:
    return str(decimal(value).quantize(PERCENT))


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def event_rows(config: M1240Config) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in config.event_seed:
        symbols = event.get("symbols", [])
        for symbol in symbols:
            move = event.get("symbol_moves", {}).get(symbol, event.get("move_percent", ""))
            rows.append(
                {
                    "event_id": event["event_id"],
                    "symbol": symbol,
                    "event_date": event["event_date"],
                    "event_type": event["event_type"],
                    "event_title": event["event_title"],
                    "event_direction": event.get("event_direction", "unknown"),
                    "session": event.get("session", "regular"),
                    "move_percent": str(move),
                    "severity": event.get("severity", "medium"),
                    "source_refs": " | ".join(event.get("source_refs", [])),
                    "notes": event.get("notes", ""),
                }
            )
    for event in config.macro_event_seed:
        rows.append(
            {
                "event_id": event["event_id"],
                "symbol": "MARKET",
                "event_date": event["event_date"],
                "event_type": event["event_type"],
                "event_title": event["event_title"],
                "event_direction": event.get("event_direction", "market_risk"),
                "session": event.get("session", "regular"),
                "move_percent": "",
                "severity": event.get("severity", "medium"),
                "source_refs": " | ".join(event.get("source_refs", [])),
                "notes": event.get("notes", ""),
            }
        )
    return rows


def match_events_for_signal(config: M1240Config, row: dict[str, str]) -> list[dict[str, Any]]:
    signal_date = parse_date(row.get("signal_date") or row.get("signal_time"))
    if not signal_date:
        return []
    symbol = row.get("symbol", "")
    matches: list[dict[str, Any]] = []
    for event in event_rows(config):
        event_date = parse_date(event["event_date"])
        if not event_date:
            continue
        symbol_match = event["symbol"] in {symbol, "MARKET"}
        if not symbol_match:
            continue
        days = (signal_date - event_date).days
        if -config.event_window_days <= days <= config.event_window_days:
            enriched = dict(event)
            enriched["days_from_event"] = days
            matches.append(enriched)
    return matches


def direction_alignment(signal_direction: str, event_direction: str) -> str:
    bullish = signal_direction in {"看涨", "long", "Long", "LONG"}
    bearish = signal_direction in {"看跌", "short", "Short", "SHORT"}
    positive = event_direction in {"positive", "bullish", "up"}
    negative = event_direction in {"negative", "bearish", "down"}
    if (bullish and positive) or (bearish and negative):
        return "一致"
    if (bullish and negative) or (bearish and positive):
        return "相反"
    return "不确定"


def classify_event_effect(matches: list[dict[str, Any]], direction: str, threshold: Decimal) -> tuple[str, str, str]:
    if not matches:
        return "none", "无事件标签", "no_useful_signal"
    has_earnings = any(match["event_type"] == "earnings" for match in matches)
    has_macro = any(match["symbol"] == "MARKET" for match in matches)
    max_move = max((abs(decimal(match.get("move_percent"))) for match in matches), default=ZERO)
    alignments = {direction_alignment(direction, match.get("event_direction", "")) for match in matches}
    if has_macro:
        return "macro_risk", "宏观事件日，优先做风险提示", "risk_filter_only"
    if has_earnings and max_move >= threshold and "一致" in alignments:
        return "earnings_gap_aligned", "财报/盘前盘后异动与策略方向一致，可作为优先级加分候选", "priority_boost_candidate"
    if has_earnings and max_move >= threshold and "相反" in alignments:
        return "earnings_gap_opposite", "财报/盘前盘后异动与策略方向相反，优先做风险拦截候选", "risk_filter_only"
    if has_earnings:
        return "earnings_nearby", "临近财报，先标记事件风险", "risk_filter_only"
    return "event_context", "有事件背景，样本继续观察", "no_useful_signal"


def build_event_tag_rows(config: M1240Config, trade_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for index, row in enumerate(trade_rows, start=1):
        matches = match_events_for_signal(config, row)
        event_effect, plain_effect, conclusion = classify_event_effect(matches, row.get("direction", ""), config.gap_threshold_percent)
        alignments = [direction_alignment(row.get("direction", ""), match.get("event_direction", "")) for match in matches]
        tagged.append(
            {
                "row_id": f"m12_40_{index:05d}",
                "symbol": row.get("symbol", ""),
                "strategy_id": row.get("strategy_id", ""),
                "strategy_title": row.get("strategy_title", ""),
                "timeframe": row.get("timeframe", ""),
                "signal_date": row.get("signal_date", ""),
                "signal_time": row.get("signal_time", ""),
                "direction": row.get("direction", ""),
                "simulated_intraday_pnl": row.get("simulated_intraday_pnl", "0"),
                "simulated_state": row.get("simulated_state", ""),
                "has_event": "true" if matches else "false",
                "event_ids": " | ".join(match["event_id"] for match in matches),
                "event_types": " | ".join(match["event_type"] for match in matches),
                "event_titles": " | ".join(match["event_title"] for match in matches),
                "event_move_percent": " | ".join(str(match.get("move_percent", "")) for match in matches),
                "news_direction_alignment": " | ".join(alignments),
                "event_effect": event_effect,
                "plain_effect": plain_effect,
                "m12_41_preliminary_conclusion": conclusion,
                "source_refs": " | ".join(match.get("source_refs", "") for match in matches),
                "paper_simulated_only": "true",
                "broker_connection": "false",
                "real_orders": "false",
                "live_execution": "false",
            }
        )
    return tagged


def aggregate_metrics(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    pnl_values = [decimal(row.get("simulated_intraday_pnl")) for row in rows]
    wins = [pnl for pnl in pnl_values if pnl > 0]
    losses = [pnl for pnl in pnl_values if pnl < 0]
    equity = STARTING_CAPITAL
    peak = equity
    max_dd = ZERO
    for pnl in pnl_values:
        equity += pnl
        if equity > peak:
            peak = equity
        if peak:
            dd = (peak - equity) / peak * Decimal("100")
            max_dd = max(max_dd, dd)
    profit_factor = Decimal("0")
    if losses:
        profit_factor = sum(wins, ZERO) / abs(sum(losses, ZERO)) if sum(losses, ZERO) != ZERO else ZERO
    elif wins:
        profit_factor = Decimal("999")
    return {
        "group": label,
        "trade_count": len(rows),
        "net_profit": money(sum(pnl_values, ZERO)),
        "return_percent": pct(sum(pnl_values, ZERO) / STARTING_CAPITAL * Decimal("100") if STARTING_CAPITAL else ZERO),
        "win_rate": pct(Decimal(len(wins)) / Decimal(len(rows)) * Decimal("100") if rows else ZERO),
        "profit_factor": pct(profit_factor),
        "max_drawdown_percent": pct(max_dd),
    }


def run_m12_40(config: M1240Config | None = None, *, generated_at: str | None = None) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or now_utc()
    out = config.output_root / "news_earnings" / "m12_40_event_tags"
    trade_rows = read_csv(config.trade_view_path)
    tagged_rows = build_event_tag_rows(config, trade_rows)
    events = event_rows(config)
    by_effect = CounterDict(row["event_effect"] for row in tagged_rows)
    by_symbol = CounterDict(row["symbol"] for row in tagged_rows if row["has_event"] == "true")
    summary = {
        "schema_version": "m12.40.news-earnings-event-tags.v1",
        "stage": "M12.40.news_earnings_event_tags",
        "generated_at": generated_at,
        "signal_count": len(tagged_rows),
        "event_seed_count": len(events),
        "event_tagged_signal_count": sum(1 for row in tagged_rows if row["has_event"] == "true"),
        "event_effect_counts": by_effect,
        "event_symbol_counts": by_symbol,
        "google_case_detected": any(row["symbol"] in {"GOOG", "GOOGL"} and row["has_event"] == "true" for row in tagged_rows),
        "plain_language_result": build_m12_40_plain(tagged_rows),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_json(out / "m12_40_news_event_seed.json", events)
    write_csv(out / "m12_40_news_event_tags.csv", tagged_rows)
    write_jsonl(out / "m12_40_news_event_tags.jsonl", tagged_rows)
    write_json(out / "m12_40_news_event_tag_summary.json", summary)
    (out / "m12_40_daily_premarket_news_brief.md").write_text(build_news_brief_md(summary, tagged_rows, mode="盘前"), encoding="utf-8")
    (out / "m12_40_daily_postmarket_news_review.md").write_text(build_news_brief_md(summary, tagged_rows, mode="收盘/盘后"), encoding="utf-8")
    (out / "m12_40_news_explained_or_missed_report.md").write_text(build_m12_40_report_md(summary, tagged_rows), encoding="utf-8")
    assert_no_forbidden(out)
    return summary


def run_m12_41(config: M1240Config | None = None, *, generated_at: str | None = None) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or now_utc()
    m12_40_dir = config.output_root / "news_earnings" / "m12_40_event_tags"
    tagged = read_csv(m12_40_dir / "m12_40_news_event_tags.csv")
    out = config.output_root / "news_earnings" / "m12_41_news_impact_simulation"
    groups = {
        "all_signals": tagged,
        "event_tagged": [row for row in tagged if row.get("has_event") == "true"],
        "no_event": [row for row in tagged if row.get("has_event") != "true"],
        "event_aligned": [row for row in tagged if "一致" in row.get("news_direction_alignment", "")],
        "event_opposite": [row for row in tagged if "相反" in row.get("news_direction_alignment", "")],
        "earnings_gap": [row for row in tagged if row.get("event_effect", "").startswith("earnings_gap")],
    }
    metric_rows = [aggregate_metrics(rows, label) for label, rows in groups.items()]
    conclusion = choose_news_conclusion(metric_rows)
    summary = {
        "schema_version": "m12.41.news-impact-simulation.v1",
        "stage": "M12.41.news_impact_simulation",
        "generated_at": generated_at,
        "overall_conclusion": conclusion,
        "metric_rows": metric_rows,
        "plain_language_result": build_m12_41_plain(metric_rows, conclusion),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_csv(out / "m12_41_news_impact_metrics.csv", metric_rows)
    write_json(out / "m12_41_news_impact_summary.json", summary)
    (out / "m12_41_news_impact_report.md").write_text(build_m12_41_report_md(summary), encoding="utf-8")
    assert_no_forbidden(out)
    return summary


def run_m12_42(config: M1240Config | None = None, *, generated_at: str | None = None) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or now_utc()
    out = config.output_root / "news_earnings" / "m12_42_ftd001_news_risk_ab"
    trades = [row for row in read_csv(config.ftd_trade_ledger_path) if row.get("variant_id") == "pullback_guard"]
    events = event_rows(config)
    event_symbols = {event["symbol"] for event in events if event["symbol"] != "MARKET"}
    event_dates = {event["symbol"]: parse_date(event["event_date"]) for event in events if event["symbol"] != "MARKET"}
    variants = {
        "baseline": trades,
        "earnings_pause": [
            row for row in trades
            if not is_event_window_trade(row, event_dates, window_days=1)
        ],
        "news_alignment_only": [
            row for row in trades
            if row.get("symbol") in event_symbols
            and row.get("direction") == "看涨"
            and is_event_window_trade(row, event_dates, window_days=1)
        ],
        "macro_risk_pause": trades,
        "loss_streak_guard": apply_loss_streak_guard(trades, max_losses=3, pause_trades=1),
        "combined_guard": apply_loss_streak_guard(
            [row for row in trades if not is_event_window_trade(row, event_dates, window_days=1)],
            max_losses=3,
            pause_trades=1,
        ),
    }
    metric_rows = [ftd_metrics(rows, variant_id) for variant_id, rows in variants.items()]
    best = choose_ftd_best(metric_rows)
    summary = {
        "schema_version": "m12.42.ftd001-news-risk-ab.v1",
        "stage": "M12.42.ftd001_news_risk_ab",
        "generated_at": generated_at,
        "best_variant": best,
        "variant_count": len(metric_rows),
        "metric_rows": metric_rows,
        "plain_language_result": build_m12_42_plain(metric_rows, best),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_csv(out / "m12_42_ftd001_news_risk_ab_metrics.csv", metric_rows)
    write_json(out / "m12_42_ftd001_news_risk_ab_summary.json", summary)
    (out / "m12_42_ftd001_news_risk_ab_report.md").write_text(build_m12_42_report_md(summary), encoding="utf-8")
    assert_no_forbidden(out)
    return summary


def run_m12_43(config: M1240Config | None = None, *, generated_at: str | None = None) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or now_utc()
    out = config.output_root / "news_earnings" / "m12_43_earnings_gap_continuation"
    trade_rows = read_csv(config.trade_view_path)
    gap_events = [
        event for event in event_rows(config)
        if event["event_type"] == "earnings" and abs(decimal(event.get("move_percent"))) >= config.gap_threshold_percent
    ]
    observation_rows: list[dict[str, Any]] = []
    for event in gap_events:
        event_date = parse_date(event["event_date"])
        if not event_date:
            continue
        next_day = event_date + timedelta(days=1)
        matches = [
            row for row in trade_rows
            if row.get("symbol") == event["symbol"]
            and parse_date(row.get("signal_date") or row.get("signal_time")) == next_day
            and row.get("timeframe") in {"5m", "15m"}
            and row.get("strategy_id") in {"M10-PA-002", "M10-PA-012"}
        ]
        if not matches:
            observation_rows.append(earnings_gap_row(event, next_day, None))
        else:
            for match in matches:
                observation_rows.append(earnings_gap_row(event, next_day, match))
    summary = {
        "schema_version": "m12.43.earnings-gap-continuation.v1",
        "stage": "M12.43.earnings_gap_continuation",
        "generated_at": generated_at,
        "gap_event_count": len(gap_events),
        "observation_row_count": len(observation_rows),
        "google_case_rows": [row for row in observation_rows if row["symbol"] in {"GOOG", "GOOGL"}],
        "decision": "enter_observation_queue" if any(row["price_confirmation_found"] == "true" for row in observation_rows) else "needs_more_samples",
        "plain_language_result": build_m12_43_plain(observation_rows),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_csv(out / "m12_43_earnings_gap_observation_rows.csv", observation_rows)
    write_json(out / "m12_43_earnings_gap_summary.json", summary)
    (out / "m12_43_google_case_review.md").write_text(build_m12_43_report_md(summary), encoding="utf-8")
    assert_no_forbidden(out)
    return summary


def run_m12_44(config: M1240Config | None = None, *, generated_at: str | None = None) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or now_utc()
    out = config.output_root / "news_earnings" / "m12_44_data_scanner_news_expansion"
    candidates = read_csv(config.trade_view_path)
    tags = {row["row_id"]: row for row in read_csv(config.output_root / "news_earnings" / "m12_40_event_tags" / "m12_40_news_event_tags.csv")}
    # Match tags back by stable tuple because the original trade view has no row id.
    tag_by_tuple = {
        (row["symbol"], row["strategy_id"], row["timeframe"], row["signal_time"], row["direction"]): row
        for row in tags.values()
    }
    enriched: list[dict[str, Any]] = []
    for row in candidates:
        tag = tag_by_tuple.get((row.get("symbol", ""), row.get("strategy_id", ""), row.get("timeframe", ""), row.get("signal_time", ""), row.get("direction", "")), {})
        enriched.append(
            {
                **row,
                "has_news_or_earnings_event": tag.get("has_event", "false"),
                "news_event_effect": tag.get("event_effect", "none"),
                "news_direction_alignment": tag.get("news_direction_alignment", ""),
                "news_priority": news_priority(tag),
                "high_risk_pause": "true" if tag.get("m12_41_preliminary_conclusion") == "risk_filter_only" else "false",
            }
        )
    first50 = load_json(config.first50_universe_path, {}).get("symbols", [])
    coverage_rows = read_csv(config.cache_coverage_path)
    summary = {
        "schema_version": "m12.44.data-scanner-news-expansion.v1",
        "stage": "M12.44.data_scanner_news_expansion",
        "generated_at": generated_at,
        "first50_symbol_count": len(first50),
        "candidate_count": len(enriched),
        "news_tagged_candidate_count": sum(1 for row in enriched if row["has_news_or_earnings_event"] == "true"),
        "first50_coverage_rows": len(coverage_rows),
        "plain_language_result": build_m12_44_plain(enriched, first50),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_csv(out / "m12_44_news_weighted_scanner_candidates.csv", enriched)
    write_json(out / "m12_44_data_scanner_news_expansion_summary.json", summary)
    (out / "m12_44_data_scanner_news_expansion_report.md").write_text(build_m12_44_report_md(summary), encoding="utf-8")
    assert_no_forbidden(out)
    return summary


def run_m12_45(config: M1240Config | None = None, *, generated_at: str | None = None) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or now_utc()
    out = config.output_root / "news_earnings" / "m12_45_unified_strategy_portfolio_scorecard"
    closure = read_csv(config.strategy_closure_path)
    dashboard = load_json(config.dashboard_json_path, {})
    trade_rows = read_csv(config.trade_view_path)
    event_tags = read_csv(config.output_root / "news_earnings" / "m12_40_event_tags" / "m12_40_news_event_tags.csv")
    tag_by_tuple = {
        (row["symbol"], row["strategy_id"], row["timeframe"], row["signal_time"], row["direction"]): row
        for row in event_tags
    }
    score_rows = build_unified_score_rows(closure, dashboard, event_tags)
    portfolio_rows = build_portfolio_rows(trade_rows, tag_by_tuple)
    portfolio_metrics = aggregate_metrics(portfolio_rows, "shared_capital_portfolio")
    summary = {
        "schema_version": "m12.45.unified-strategy-portfolio-scorecard.v1",
        "stage": "M12.45.unified_strategy_portfolio_scorecard",
        "generated_at": generated_at,
        "strategy_count": len(score_rows),
        "portfolio_metrics": portfolio_metrics,
        "plain_language_result": build_m12_45_plain(score_rows, portfolio_metrics),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_csv(out / "m12_45_unified_strategy_scorecard.csv", score_rows)
    write_csv(out / "m12_45_portfolio_trade_proxy.csv", portfolio_rows)
    write_json(out / "m12_45_unified_strategy_portfolio_summary.json", summary)
    (out / "m12_45_unified_strategy_portfolio_report.md").write_text(build_m12_45_report_md(summary, score_rows), encoding="utf-8")
    assert_no_forbidden(out)
    return summary


def run_m11_7(config: M1240Config | None = None, *, generated_at: str | None = None) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or now_utc()
    out = config.output_root / "paper_gate" / "m11_7_paper_trial_recheck"
    run_status = load_json(config.dashboard_dir / "m12_33_observation_run_status.json", {})
    m1241 = load_json(config.output_root / "news_earnings" / "m12_41_news_impact_simulation" / "m12_41_news_impact_summary.json", {})
    m1242 = load_json(config.output_root / "news_earnings" / "m12_42_ftd001_news_risk_ab" / "m12_42_ftd001_news_risk_ab_summary.json", {})
    m1243 = load_json(config.output_root / "news_earnings" / "m12_43_earnings_gap_continuation" / "m12_43_earnings_gap_summary.json", {})
    observed_days = int(decimal(run_status.get("completed_observation_days", run_status.get("observation_day_count", 1))))
    blockers = []
    if observed_days < 10:
        blockers.append(f"只读观察还没满 10 个真实交易日，当前约 {observed_days}/10")
    if not m1241:
        blockers.append("新闻/财报影响分析缺失")
    if not m1242:
        blockers.append("FTD001 风险优化缺失")
    if not m1243:
        blockers.append("财报跳空策略原型缺失")
    approval = not blockers
    summary = {
        "schema_version": "m11.7.paper-trial-recheck.v1",
        "stage": "M11.7.paper_trial_recheck",
        "generated_at": generated_at,
        "paper_trial_approval": approval,
        "approved_strategy_ids": ["M10-PA-002", "M10-PA-012"] if approval else [],
        "continue_observation_strategy_ids": ["M10-PA-001", "M12-FTD-001", "M10-PA-004", "M10-PA-007", "M10-PA-008", "M10-PA-009"],
        "blockers": blockers,
        "plain_language_result": "满足条件，可进入模拟交易试运行。" if approval else "暂不进入模拟交易试运行：" + "；".join(blockers),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": approval,
    }
    write_json(out / "m11_7_paper_trial_recheck.json", summary)
    (out / "m11_7_paper_trial_recheck_report.md").write_text(build_m11_7_report_md(summary), encoding="utf-8")
    assert_no_forbidden(out)
    return summary


def CounterDict(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_m12_40_plain(rows: list[dict[str, Any]]) -> str:
    tagged = [row for row in rows if row["has_event"] == "true"]
    google = [row for row in tagged if row["symbol"] in {"GOOG", "GOOGL"}]
    return f"已给 {len(rows)} 条只读候选打新闻/财报标签，其中 {len(tagged)} 条带事件背景；Google/Alphabet 相关 {len(google)} 条。"


def build_news_brief_md(summary: dict[str, Any], rows: list[dict[str, Any]], *, mode: str) -> str:
    tagged = [row for row in rows if row["has_event"] == "true"]
    google = [row for row in tagged if row["symbol"] in {"GOOG", "GOOGL"}]
    lines = [
        f"# M12.40 {mode}新闻/财报简报",
        "",
        summary["plain_language_result"],
        "",
        "## 重点",
        f"- 带新闻/财报标签的候选：{len(tagged)} 条。",
        f"- Google/Alphabet 相关候选：{len(google)} 条。",
        "- 这些标签只用于只读模拟解释、风险提示和后续分组测试，不触发真实交易。",
        "",
        "## Google/Alphabet",
    ]
    if google:
        for row in google[:10]:
            lines.append(f"- {row['symbol']} {row['strategy_id']} {row['timeframe']} {row['direction']}：{row['plain_effect']}，模拟盈亏 {row['simulated_intraday_pnl']}。")
    else:
        lines.append("- 当前候选未命中 Google/Alphabet 事件标签。")
    return "\n".join(lines) + "\n"


def build_m12_40_report_md(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    effect_counts = summary["event_effect_counts"]
    lines = [
        "# M12.40 新闻/财报解释与漏检报告",
        "",
        summary["plain_language_result"],
        "",
        "## 事件效果分布",
    ]
    for effect, count in effect_counts.items():
        lines.append(f"- {effect}: {count}")
    lines.extend([
        "",
        "## 当前边界",
        "- 新闻和财报只作为标签、风险提示、优先级加分和后续分组测试输入。",
        "- 当前不接真实账户、不下单、不输出实盘建议。",
    ])
    return "\n".join(lines) + "\n"


def choose_news_conclusion(rows: list[dict[str, Any]]) -> str:
    by_group = {row["group"]: row for row in rows}
    aligned = by_group.get("event_aligned", {})
    event = by_group.get("event_tagged", {})
    if int(event.get("trade_count", 0)) == 0:
        return "no_useful_signal"
    if int(aligned.get("trade_count", 0)) > 0 and decimal(aligned.get("net_profit")) > 0:
        return "priority_boost_candidate"
    if decimal(event.get("net_profit")) < 0:
        return "risk_filter_only"
    return "no_useful_signal"


def build_m12_41_plain(rows: list[dict[str, Any]], conclusion: str) -> str:
    event_row = next((row for row in rows if row["group"] == "event_tagged"), {"trade_count": 0, "net_profit": "0.00"})
    return f"新闻/财报分组样本 {event_row['trade_count']} 条，事件组模拟盈亏 {event_row['net_profit']}；当前结论为 {conclusion}。"


def build_m12_41_report_md(summary: dict[str, Any]) -> str:
    lines = ["# M12.41 新闻影响历史/当前样本模拟", "", summary["plain_language_result"], "", "## 分组指标"]
    for row in summary["metric_rows"]:
        lines.append(f"- {row['group']}: 交易 {row['trade_count']}，盈亏 {row['net_profit']}，胜率 {row['win_rate']}%，最大回撤 {row['max_drawdown_percent']}%。")
    lines.extend(["", "## 结论", f"- {summary['overall_conclusion']}"])
    return "\n".join(lines) + "\n"


def is_event_window_trade(row: dict[str, str], event_dates: dict[str, date | None], *, window_days: int) -> bool:
    symbol = row.get("symbol", "")
    event_date = event_dates.get(symbol)
    trade_date = parse_date(row.get("signal_timestamp") or row.get("entry_timestamp"))
    if not event_date or not trade_date:
        return False
    return abs((trade_date - event_date).days) <= window_days


def apply_loss_streak_guard(rows: list[dict[str, str]], *, max_losses: int, pause_trades: int) -> list[dict[str, str]]:
    kept: list[dict[str, str]] = []
    losses = 0
    pause = 0
    for row in sorted(rows, key=lambda item: (item.get("entry_timestamp", ""), item.get("symbol", ""))):
        pnl = decimal(row.get("simulated_profit"))
        if pause > 0:
            pause -= 1
            continue
        kept.append(row)
        if pnl < 0:
            losses += 1
            if losses >= max_losses:
                pause = pause_trades
                losses = 0
        else:
            losses = 0
    return kept


def ftd_metrics(rows: list[dict[str, str]], variant_id: str) -> dict[str, Any]:
    converted = [{"simulated_intraday_pnl": row.get("simulated_profit", "0")} for row in rows]
    metrics = aggregate_metrics(converted, variant_id)
    metrics["variant_id"] = variant_id
    metrics["final_equity"] = money(STARTING_CAPITAL + decimal(metrics["net_profit"]))
    metrics["max_consecutive_losses"] = max_consecutive_losses(rows)
    metrics["sample_note"] = "新闻覆盖样本有限" if variant_id in {"earnings_pause", "news_alignment_only", "macro_risk_pause"} else "可直接用历史交易序列评估"
    return metrics


def max_consecutive_losses(rows: list[dict[str, str]]) -> int:
    current = 0
    best = 0
    for row in sorted(rows, key=lambda item: (item.get("entry_timestamp", ""), item.get("symbol", ""))):
        if decimal(row.get("simulated_profit")) < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def choose_ftd_best(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = next(row for row in rows if row["variant_id"] == "baseline")
    candidates = [row for row in rows if row["variant_id"] != "news_alignment_only"]
    scored = sorted(
        candidates,
        key=lambda row: (
            decimal(row["max_drawdown_percent"]),
            -decimal(row["return_percent"]),
            int(row["trade_count"]),
        ),
    )
    best = scored[0]
    return {
        "variant_id": best["variant_id"],
        "reason": f"在当前可用样本下，最大回撤 {best['max_drawdown_percent']}%，收益 {best['return_percent']}%；baseline 回撤 {baseline['max_drawdown_percent']}%。",
    }


def build_m12_42_plain(rows: list[dict[str, Any]], best: dict[str, Any]) -> str:
    baseline = next(row for row in rows if row["variant_id"] == "baseline")
    return f"FTD001 baseline 收益 {baseline['return_percent']}%，最大回撤 {baseline['max_drawdown_percent']}%；当前最佳折中版本为 {best['variant_id']}。"


def build_m12_42_report_md(summary: dict[str, Any]) -> str:
    lines = ["# M12.42 FTD001 新闻过滤与回撤优化", "", summary["plain_language_result"], "", "## 版本对比"]
    for row in summary["metric_rows"]:
        lines.append(f"- {row['variant_id']}: 收益 {row['return_percent']}%，胜率 {row['win_rate']}%，最大回撤 {row['max_drawdown_percent']}%，交易 {row['trade_count']}。")
    lines.append(f"\n建议版本：`{summary['best_variant']['variant_id']}`。{summary['best_variant']['reason']}")
    return "\n".join(lines) + "\n"


def earnings_gap_row(event: dict[str, Any], next_day: date, match: dict[str, str] | None) -> dict[str, Any]:
    base = {
        "event_id": event["event_id"],
        "symbol": event["symbol"],
        "event_date": event["event_date"],
        "next_session_date": next_day.isoformat(),
        "event_move_percent": event.get("move_percent", ""),
        "event_direction": event.get("event_direction", ""),
        "price_confirmation_found": "true" if match else "false",
        "decision": "enter_observation_queue" if match else "needs_more_samples",
        "paper_simulated_only": "true",
        "broker_connection": "false",
        "real_orders": "false",
        "live_execution": "false",
    }
    if not match:
        return {**base, "strategy_id": "", "timeframe": "", "direction": "", "hypothetical_entry_price": "", "hypothetical_stop_price": "", "hypothetical_target_price": "", "simulated_intraday_pnl": "", "plain_result": "财报跳空已识别，但次日尚未找到价格确认候选。"}
    return {
        **base,
        "strategy_id": match.get("strategy_id", ""),
        "strategy_title": match.get("strategy_title", ""),
        "timeframe": match.get("timeframe", ""),
        "direction": match.get("direction", ""),
        "signal_time": match.get("signal_time", ""),
        "hypothetical_entry_price": match.get("hypothetical_entry_price", ""),
        "hypothetical_stop_price": match.get("hypothetical_stop_price", ""),
        "hypothetical_target_price": match.get("hypothetical_target_price", ""),
        "simulated_intraday_pnl": match.get("simulated_intraday_pnl", ""),
        "plain_result": "财报跳空后次日出现价格确认候选，只进入观察队列。",
    }


def build_m12_43_plain(rows: list[dict[str, Any]]) -> str:
    confirmed = [row for row in rows if row["price_confirmation_found"] == "true"]
    return f"财报跳空事件 {len(rows)} 条观察记录，其中 {len(confirmed)} 条找到次日价格确认候选。"


def build_m12_43_report_md(summary: dict[str, Any]) -> str:
    lines = ["# M12.43 财报跳空 / 盘后异动策略原型", "", summary["plain_language_result"], "", "## Google 案例"]
    for row in summary["google_case_rows"]:
        lines.append(f"- {row['symbol']}：{row['plain_result']} 策略 {row.get('strategy_id','')}，周期 {row.get('timeframe','')}，模拟盈亏 {row.get('simulated_intraday_pnl','')}。")
    lines.append(f"\n当前策略原型结论：`{summary['decision']}`。")
    return "\n".join(lines) + "\n"


def news_priority(tag: dict[str, str]) -> str:
    effect = tag.get("event_effect", "")
    if effect == "earnings_gap_aligned":
        return "提高观察优先级"
    if effect in {"earnings_gap_opposite", "macro_risk"}:
        return "高风险暂停/降级"
    if effect == "earnings_nearby":
        return "事件风险提示"
    return "普通"


def build_m12_44_plain(rows: list[dict[str, Any]], first50: list[str]) -> str:
    tagged = sum(1 for row in rows if row["has_news_or_earnings_event"] == "true")
    return f"第一批股票池 {len(first50)} 只，当前候选 {len(rows)} 条，其中 {tagged} 条带新闻/财报事件字段。"


def build_m12_44_report_md(summary: dict[str, Any]) -> str:
    return "\n".join([
        "# M12.44 数据与选股池新闻字段补强",
        "",
        summary["plain_language_result"],
        "",
        "- 缺数据标的不会进入可交易候选。",
        "- 新闻字段只改变观察优先级或风险提示，不直接触发真实交易。",
    ]) + "\n"


def build_unified_score_rows(closure: list[dict[str, str]], dashboard: dict[str, Any], event_tags: list[dict[str, str]]) -> list[dict[str, Any]]:
    score_by_id = {row.get("strategy_id"): row for row in dashboard.get("strategy_scorecard_rows", [])}
    event_by_strategy = CounterDict(row.get("strategy_id", "") for row in event_tags if row.get("has_event") == "true")
    rows: list[dict[str, Any]] = []
    for row in closure:
        sid = row.get("strategy_id", "")
        score = score_by_id.get(sid, {})
        rows.append(
            {
                "strategy_id": sid,
                "strategy_title": row.get("strategy_title", ""),
                "final_status": row.get("final_status", ""),
                "client_status": normalize_client_status(row.get("final_status", "")),
                "today_opportunity_count": score.get("today_opportunity_count", row.get("today_opportunity_count", "0")),
                "today_simulated_pnl": score.get("simulated_pnl_today", "0.00"),
                "historical_return_percent": score.get("historical_return_percent", row.get("return_percent", "")),
                "historical_win_rate_percent": score.get("historical_win_rate_percent", row.get("win_rate", "")),
                "historical_max_drawdown_percent": score.get("historical_max_drawdown_percent", row.get("max_drawdown_percent", "")),
                "news_event_signal_count": event_by_strategy.get(sid, 0),
                "upgrade_pause_suggestion": upgrade_pause_suggestion(sid, row.get("final_status", ""), event_by_strategy.get(sid, 0)),
            }
        )
    return rows


def normalize_client_status(status: str) -> str:
    if "每日" in status:
        return "每日测试中"
    if "观察" in status:
        return "观察测试中"
    if "辅助" in status:
        return "只做辅助规则"
    if "过滤" in status:
        return "只做过滤器"
    if "研究" in status:
        return "研究项"
    return "暂不继续"


def upgrade_pause_suggestion(strategy_id: str, status: str, event_count: int) -> str:
    if strategy_id == "M12-FTD-001":
        return "重点做回撤和新闻过滤优化"
    if event_count > 0:
        return "加入新闻影响复盘"
    if "观察" in status:
        return "继续低准入观察"
    if "每日" in status:
        return "继续每日测试"
    return "不进入每日触发"


def build_portfolio_rows(trade_rows: list[dict[str, str]], tag_by_tuple: dict[tuple[str, str, str, str, str], dict[str, str]]) -> list[dict[str, Any]]:
    priority = {"M10-PA-002": 1, "M10-PA-012": 2, "M12-FTD-001": 3, "M10-PA-001": 4, "M10-PA-004": 5}
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in trade_rows:
        grouped[(row.get("symbol", ""), row.get("signal_date") or row.get("signal_time", ""))].append(row)
    selected: list[dict[str, Any]] = []
    for _, rows in grouped.items():
        rows.sort(key=lambda row: priority.get(row.get("strategy_id", ""), 99))
        chosen = rows[0]
        tag = tag_by_tuple.get((chosen.get("symbol", ""), chosen.get("strategy_id", ""), chosen.get("timeframe", ""), chosen.get("signal_time", ""), chosen.get("direction", "")), {})
        if tag.get("m12_41_preliminary_conclusion") == "risk_filter_only":
            chosen = dict(chosen)
            chosen["simulated_intraday_pnl"] = "0.00"
            chosen["portfolio_action"] = "新闻高风险，组合视角暂停"
        else:
            chosen = dict(chosen)
            chosen["portfolio_action"] = "纳入组合代理"
        selected.append(chosen)
    return selected


def build_m12_45_plain(rows: list[dict[str, Any]], portfolio: dict[str, Any]) -> str:
    testing = sum(1 for row in rows if row["client_status"] == "每日测试中")
    observation = sum(1 for row in rows if row["client_status"] == "观察测试中")
    return f"统一策略表覆盖 {len(rows)} 条策略：每日测试 {testing} 条，观察测试 {observation} 条；组合代理模拟盈亏 {portfolio['net_profit']}。"


def build_m12_45_report_md(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = ["# M12.45 统一策略成绩单与组合视图", "", summary["plain_language_result"], "", "## 策略状态"]
    for row in rows:
        lines.append(f"- {row['strategy_id']}：{row['client_status']}，今日盈亏 {row['today_simulated_pnl']}，建议：{row['upgrade_pause_suggestion']}。")
    metrics = summary["portfolio_metrics"]
    lines.extend(["", "## 共用本金组合代理", f"- 模拟盈亏：{metrics['net_profit']}，胜率：{metrics['win_rate']}%，最大回撤：{metrics['max_drawdown_percent']}%。"])
    return "\n".join(lines) + "\n"


def build_m11_7_report_md(summary: dict[str, Any]) -> str:
    lines = ["# M11.7 模拟交易试运行复查", "", summary["plain_language_result"], ""]
    if summary["blockers"]:
        lines.append("## 暂未通过的原因")
        for blocker in summary["blockers"]:
            lines.append(f"- {blocker}")
    else:
        lines.append("## 批准策略")
        for strategy_id in summary["approved_strategy_ids"]:
            lines.append(f"- {strategy_id}")
    lines.append("\n仍然只做模拟交易试运行，不接真实账户、不下真实订单。")
    return "\n".join(lines) + "\n"


def assert_no_forbidden(path: Path) -> None:
    for candidate in path.rglob("*"):
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        for token in FORBIDDEN_TEXT:
            if token in text:
                raise AssertionError(f"forbidden text {token!r} found in {candidate}")
