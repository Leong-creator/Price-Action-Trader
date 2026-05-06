#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_12_daily_observation_loop_lib import (  # noqa: E402
    load_config as load_m12_12_config,
    run_m12_12_daily_observation_loop,
)
from scripts.m12_20_visual_detector_implementation_lib import (  # noqa: E402
    best_cache_file,
    detect_broad_channel_boundary_reversal,
    file_sha256,
    load_config as load_m12_20_config,
)
from scripts.m12_28_trading_session_dashboard_lib import (  # noqa: E402
    build_pa004_long_rows,
    build_quotes,
    load_config as load_m12_28_config,
    pa004_candidate_from_event,
)
from scripts.m12_liquid_universe_scanner_lib import load_bars  # noqa: E402


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_29_current_day_scan_dashboard.json"
OUTPUT_DIR = M10_DIR / "daily_observation" / "m12_29_current_day_scan_dashboard"
MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
DEFAULT_ACCOUNT_EQUITY = Decimal("20000")
DEFAULT_ACCOUNT_RISK_RATE = Decimal("0.005")
DEFAULT_ACCOUNT_RISK_BUDGET = (DEFAULT_ACCOUNT_EQUITY * DEFAULT_ACCOUNT_RISK_RATE).quantize(MONEY)
DEFAULT_EQUITY = DEFAULT_ACCOUNT_EQUITY
DEFAULT_RISK_BUDGET = DEFAULT_ACCOUNT_RISK_BUDGET
MAX_GENERATED_AT_FUTURE_SKEW_SECONDS = 90
MAINLINE_STRATEGIES = ("M10-PA-001", "M10-PA-002", "M10-PA-004", "M10-PA-012", "M12-FTD-001")
EXPERIMENTAL_STRATEGIES = ("M10-PA-005", "M10-PA-007", "M10-PA-008", "M10-PA-009", "M10-PA-011", "M10-PA-013")
PRIMARY_TIMEFRAME_ORDER = ("1d", "5m")
TIMEFRAME_ORDER = PRIMARY_TIMEFRAME_ORDER
TIMEFRAME_LABELS = {
    "1d": "1d 日线测试",
    "5m": "5m 五分钟测试",
}
EXTENDED_SESSION_MOVE_THRESHOLD = Decimal("3")
EXTENDED_SESSION_FOCUS_LABELS = {
    "AMD": "AMD / AI 芯片",
    "NVDA": "英伟达 / AI 芯片",
    "QCOM": "高通 / 芯片",
    "TSM": "台积电 / 晶圆代工",
    "MU": "存储芯片",
    "WDC": "存储芯片",
    "SOXX": "半导体 ETF",
    "SMH": "半导体 ETF",
    "GOOG": "谷歌 / 财报观察",
    "GOOGL": "谷歌 / 财报观察",
}
ACCOUNT_SPECS = (
    {"account_id": "M10-PA-001-1d", "strategy_id": "M10-PA-001", "timeframe": "1d", "lane": "mainline", "display_name": "M10-PA-001 日线账户", "variant_id": "base"},
    {"account_id": "M10-PA-001-5m", "strategy_id": "M10-PA-001", "timeframe": "5m", "lane": "mainline", "display_name": "M10-PA-001 五分钟账户", "variant_id": "base"},
    {"account_id": "M10-PA-002-1d", "strategy_id": "M10-PA-002", "timeframe": "1d", "lane": "mainline", "display_name": "M10-PA-002 日线账户", "variant_id": "base"},
    {"account_id": "M10-PA-002-5m", "strategy_id": "M10-PA-002", "timeframe": "5m", "lane": "mainline", "display_name": "M10-PA-002 五分钟账户", "variant_id": "base"},
    {"account_id": "M10-PA-004-long-1d", "strategy_id": "M10-PA-004", "timeframe": "1d", "lane": "mainline", "display_name": "M10-PA-004 只做多日线账户", "variant_id": "long_only"},
    {"account_id": "M10-PA-012-5m", "strategy_id": "M10-PA-012", "timeframe": "5m", "lane": "mainline", "display_name": "M10-PA-012 五分钟账户", "variant_id": "base"},
    {"account_id": "M12-FTD-001-baseline-1d", "strategy_id": "M12-FTD-001", "timeframe": "1d", "lane": "mainline", "display_name": "M12-FTD-001 原版日线账户", "variant_id": "baseline"},
    {"account_id": "M12-FTD-001-loss-streak-guard-1d", "strategy_id": "M12-FTD-001", "timeframe": "1d", "lane": "mainline", "display_name": "M12-FTD-001 连亏保护日线账户", "variant_id": "loss_streak_guard"},
    {"account_id": "M10-PA-005-1d", "strategy_id": "M10-PA-005", "timeframe": "1d", "lane": "experimental", "display_name": "M10-PA-005 日线实验账户", "variant_id": "base"},
    {"account_id": "M10-PA-005-5m", "strategy_id": "M10-PA-005", "timeframe": "5m", "lane": "experimental", "display_name": "M10-PA-005 五分钟实验账户", "variant_id": "base"},
    {"account_id": "M10-PA-007-1d", "strategy_id": "M10-PA-007", "timeframe": "1d", "lane": "experimental", "display_name": "M10-PA-007 日线实验账户", "variant_id": "base"},
    {"account_id": "M10-PA-008-1d", "strategy_id": "M10-PA-008", "timeframe": "1d", "lane": "experimental", "display_name": "M10-PA-008 日线实验账户", "variant_id": "base"},
    {"account_id": "M10-PA-009-1d", "strategy_id": "M10-PA-009", "timeframe": "1d", "lane": "experimental", "display_name": "M10-PA-009 日线实验账户", "variant_id": "base"},
    {"account_id": "M10-PA-011-1d", "strategy_id": "M10-PA-011", "timeframe": "1d", "lane": "experimental", "display_name": "M10-PA-011 日线实验账户", "variant_id": "base"},
    {"account_id": "M10-PA-011-5m", "strategy_id": "M10-PA-011", "timeframe": "5m", "lane": "experimental", "display_name": "M10-PA-011 五分钟实验账户", "variant_id": "base"},
    {"account_id": "M10-PA-013-1d", "strategy_id": "M10-PA-013", "timeframe": "1d", "lane": "experimental", "display_name": "M10-PA-013 日线实验账户", "variant_id": "base"},
    {"account_id": "M10-PA-013-5m", "strategy_id": "M10-PA-013", "timeframe": "5m", "lane": "experimental", "display_name": "M10-PA-013 五分钟实验账户", "variant_id": "base"},
)
SUPPORTING_RULE_SPECS = (
    {"supporting_rule_id": "M10-PA-006", "display_name": "BLSHS 限价过滤", "mode": "base_trigger + M10-PA-006"},
    {"supporting_rule_id": "M10-PA-014", "display_name": "目标/止盈模块", "mode": "base_trigger + M10-PA-014"},
    {"supporting_rule_id": "M10-PA-015", "display_name": "止损/仓位模块", "mode": "base_trigger + M10-PA-015"},
    {"supporting_rule_id": "M10-PA-016", "display_name": "区间加仓研究模块", "mode": "base_trigger + M10-PA-016"},
)
FORBIDDEN_OUTPUT_TEXT = (
    "PA-SC-",
    "SF-",
    "live-ready",
    "real_orders=true",
    "broker_connection=true",
    "paper_trading_approval=true",
    "order_id",
    "fill_id",
    "account_id",
    "cash_balance",
    "position_qty",
)


@dataclass(frozen=True, slots=True)
class BoundaryConfig:
    paper_simulated_only: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool
    paper_trading_approval: bool


@dataclass(frozen=True, slots=True)
class M1229Config:
    title: str
    run_id: str
    stage: str
    market: str
    output_dir: Path
    source_m12_12_config_path: Path
    m12_16_source_candidate_plan_path: Path
    m10_12_all_strategy_metrics_path: Path
    m12_24_small_pilot_metrics_path: Path
    m12_27_pa004_long_metrics_path: Path
    m12_15_best_variant_path: Path
    dashboard_refresh_seconds: int
    first_batch_size: int
    min_observation_days_for_trial: int
    boundary: BoundaryConfig


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M1229Config:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    boundary = payload["boundary"]
    config = M1229Config(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_29_current_day_scan_dashboard"),
        stage=payload["stage"],
        market=payload.get("market", "US"),
        output_dir=resolve_repo_path(payload["output_dir"]),
        source_m12_12_config_path=resolve_repo_path(payload["source_m12_12_config_path"]),
        m12_16_source_candidate_plan_path=resolve_repo_path(payload["m12_16_source_candidate_plan_path"]),
        m10_12_all_strategy_metrics_path=resolve_repo_path(payload["m10_12_all_strategy_metrics_path"]),
        m12_24_small_pilot_metrics_path=resolve_repo_path(payload["m12_24_small_pilot_metrics_path"]),
        m12_27_pa004_long_metrics_path=resolve_repo_path(payload["m12_27_pa004_long_metrics_path"]),
        m12_15_best_variant_path=resolve_repo_path(payload["m12_15_best_variant_path"]),
        dashboard_refresh_seconds=int(payload["dashboard_refresh_seconds"]),
        first_batch_size=int(payload["first_batch_size"]),
        min_observation_days_for_trial=int(payload["min_observation_days_for_trial"]),
        boundary=BoundaryConfig(
            paper_simulated_only=bool(boundary["paper_simulated_only"]),
            trading_connection=bool(boundary["trading_connection"]),
            real_money_actions=bool(boundary["real_money_actions"]),
            live_execution=bool(boundary["live_execution"]),
            paper_trading_approval=bool(boundary["paper_trading_approval"]),
        ),
    )
    validate_config(config)
    return config


def validate_config(config: M1229Config) -> None:
    if config.stage != "M12.29.current_day_scan_dashboard":
        raise ValueError("M12.29 stage drift")
    if config.first_batch_size != 50:
        raise ValueError("M12.29 first batch must stay 50 symbols")
    if not config.boundary.paper_simulated_only:
        raise ValueError("M12.29 must stay paper/simulated only")
    if (
        config.boundary.trading_connection
        or config.boundary.real_money_actions
        or config.boundary.live_execution
        or config.boundary.paper_trading_approval
    ):
        raise ValueError("M12.29 cannot enable trading connection, real money actions, live execution, or paper approval")


def run_m12_29_current_day_scan_dashboard(
    config: M1229Config | None = None,
    *,
    generated_at: str | None = None,
    execute_fetch: bool = True,
    max_native_fetches: int | None = None,
    refresh_quotes: bool = True,
) -> dict[str, Any]:
    config = config or load_config()
    validate_config(config)
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    validate_generated_at_for_artifacts(generated_at)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    market = market_session_status(generated_at)
    scan_date = current_us_scan_date(generated_at)
    source_dir = config.output_dir / "m12_12_current_day_source"

    base = load_m12_12_config(config.source_m12_12_config_path)
    source_config = replace(
        base,
        output_dir=source_dir,
        daily_end=scan_date,
        intraday_current_start=scan_date,
        intraday_end=scan_date,
    )
    source_summary = run_m12_12_daily_observation_loop(
        source_config,
        generated_at=generated_at,
        execute_fetch=execute_fetch,
        max_native_fetches=max_native_fetches,
    )

    first50 = load_json(source_dir / "m12_12_first50_universe.json")["symbols"]
    candidates = read_csv(source_dir / "m12_12_daily_candidates.csv")
    cache_summary = load_json(source_dir / "m12_12_first50_cache_summary.json")
    quote_config = load_m12_28_config()
    quotes, quote_manifest = build_quotes(quote_config, first50, generated_at, enabled=refresh_quotes)
    extended_session_monitor = build_extended_session_monitor(quotes)
    trade_rows = build_trade_rows(candidates, quotes, scan_date)
    pa004_formal_rows = build_pa004_formal_rows(first50, quotes, generated_at, scan_date)
    pa004_reference_rows = build_pa004_reference_rows(quotes, generated_at)
    closure_rows = build_strategy_closure_rows(config)
    visual_rows = build_visual_definition_rows(closure_rows)
    current_day_complete = cache_summary["daily_ready_symbols"] == config.first_batch_size and cache_summary["current_5m_ready_symbols"] == config.first_batch_size
    runtime = advance_account_runtime(
        config,
        generated_at,
        scan_date,
        trade_rows,
        pa004_formal_rows,
        closure_rows,
        current_day_complete,
    )
    summary = build_accountized_summary(
        config,
        generated_at,
        market,
        scan_date,
        source_summary,
        cache_summary,
        quote_manifest,
        extended_session_monitor,
        trade_rows,
        pa004_formal_rows,
        pa004_reference_rows,
        runtime,
    )
    dashboard = build_accountized_dashboard_payload(
        config,
        generated_at,
        summary,
        runtime,
        extended_session_monitor,
        closure_rows,
        visual_rows,
        pa004_reference_rows,
    )
    run_status = build_accountized_run_status(config, runtime)
    gate = build_accountized_gate_recheck(config, summary, run_status)

    write_json(config.output_dir / "m12_29_current_day_scan_summary.json", summary)
    write_json(config.output_dir / "m12_48_extended_session_monitor.json", extended_session_monitor)
    write_csv(config.output_dir / "m12_29_today_candidates.csv", candidates)
    write_jsonl(config.output_dir / "m12_29_today_candidates.jsonl", candidates)
    write_csv(config.output_dir / "m12_29_trade_view.csv", dashboard["trade_rows"])
    write_json(config.output_dir / "m12_30_strategy_closure_matrix.json", {"schema_version": "m12.30.strategy-closure.v1", "stage": "M12.30.strategy_closure", "rows": closure_rows})
    write_csv(config.output_dir / "m12_30_strategy_closure_matrix.csv", closure_rows)
    (config.output_dir / "m12_30_strategy_closure_report.md").write_text(build_strategy_closure_md(closure_rows), encoding="utf-8")
    write_json(config.output_dir / "m12_31_visual_definition_final_review.json", {"schema_version": "m12.31.visual-definition-final.v1", "stage": "M12.31.visual_definition_final", "rows": visual_rows})
    (config.output_dir / "m12_31_visual_definition_final_review.md").write_text(build_visual_definition_md(visual_rows), encoding="utf-8")
    write_json(config.output_dir / "m12_32_minute_readonly_dashboard_data.json", dashboard)
    write_json(config.output_dir / "m12_35_timeframe_readonly_dashboard_data.json", dashboard)
    write_csv(config.output_dir / "m12_32_strategy_scorecard.csv", dashboard["strategy_scorecard_rows"])
    write_csv(config.output_dir / "m12_46_account_scorecards.csv", dashboard["strategy_scorecard_rows"])
    write_json(config.output_dir / "m12_46_account_input_audit.json", dashboard["account_input_audit"])
    (config.output_dir / "m12_32_minute_readonly_dashboard.html").write_text(build_dashboard_html(config, dashboard), encoding="utf-8")
    write_json(config.output_dir / "m12_34_observation_test_lane.json", dashboard["observation_test_lane"])
    write_csv(config.output_dir / "m12_34_observation_strategy_rows.csv", dashboard["observation_test_lane"]["rows"])
    (config.output_dir / "m12_34_observation_test_lane.md").write_text(build_observation_test_lane_md(dashboard["observation_test_lane"]), encoding="utf-8")
    write_json(config.output_dir / "m12_35_timeframe_views.json", dashboard["timeframe_views"])
    (config.output_dir / "m12_35_timeframe_dashboard.md").write_text(build_timeframe_views_md(dashboard["timeframe_views"]), encoding="utf-8")
    write_json(config.output_dir / "m12_36_ftd001_monitor.json", dashboard["ftd001_monitor"])
    (config.output_dir / "m12_36_ftd001_monitor.md").write_text(build_ftd001_monitor_md(dashboard["ftd001_monitor"]), encoding="utf-8")
    write_json(config.output_dir / "m12_46_supporting_rule_ab_results.json", dashboard["supporting_rule_ab_results"])
    write_json(config.output_dir / "m12_38_codex_observer_latest.json", dashboard["codex_observer"])
    append_jsonl(config.output_dir / "m12_38_codex_observer_inbox.jsonl", dashboard["codex_observer"])
    write_json(config.output_dir / "m12_33_observation_run_status.json", run_status)
    (config.output_dir / "m12_33_observation_run_status.md").write_text(build_run_status_md(run_status), encoding="utf-8")
    write_json(config.output_dir / "m11_6_paper_trial_gate_recheck.json", gate)
    (config.output_dir / "m11_6_paper_trial_gate_recheck.md").write_text(build_gate_md(gate), encoding="utf-8")
    write_json(config.output_dir / "m11_8_paper_trial_gate_recheck.json", gate)
    (config.output_dir / "m11_8_paper_trial_gate_recheck.md").write_text(build_gate_md(gate), encoding="utf-8")
    (config.output_dir / "m12_29_current_day_scan_report.md").write_text(build_report_md(summary), encoding="utf-8")
    (config.output_dir / "m12_29_handoff.md").write_text(build_handoff_md(config, summary), encoding="utf-8")
    assert_no_forbidden_output(config.output_dir)
    return {
        "summary": summary,
        "dashboard": dashboard,
        "strategy_closure_rows": closure_rows,
        "visual_definition_rows": visual_rows,
        "run_status": run_status,
        "gate_recheck": gate,
        "runtime": runtime,
    }


def validate_generated_at_for_artifacts(generated_at: str) -> None:
    if os.environ.get("M12_ALLOW_FUTURE_GENERATED_AT") == "1":
        return
    generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    now = datetime.now(UTC)
    if generated > now + timedelta(seconds=MAX_GENERATED_AT_FUTURE_SKEW_SECONDS):
        raise ValueError(
            f"generated_at_is_in_the_future: {generated_at}; refusing to write production dashboard artifacts"
        )


def current_us_scan_date(generated_at: str) -> date:
    ny_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
    candidate = ny_dt.date()
    if ny_dt.weekday() < 5 and ny_dt.time() < time(9, 30):
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def market_session_status(generated_at: str) -> dict[str, str]:
    utc_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    ny_dt = utc_dt.astimezone(ZoneInfo("America/New_York"))
    if ny_dt.weekday() >= 5:
        status = "非交易日"
    elif time(9, 30) <= ny_dt.time() <= time(16, 0):
        status = "美股常规交易时段"
    elif time(4, 0) <= ny_dt.time() < time(9, 30):
        status = "盘前"
    elif time(16, 0) < ny_dt.time() <= time(20, 0):
        status = "盘后"
    else:
        status = "休市"
    return {
        "status": status,
        "new_york_date": ny_dt.date().isoformat(),
        "new_york_time": ny_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "beijing_time": utc_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z"),
    }


def iso_to_ny_trading_date(value: str) -> date | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return parse_iso_date(value)
    return dt.astimezone(ZoneInfo("America/New_York")).date()


def build_trade_rows(candidates: list[dict[str, str]], quotes: dict[str, dict[str, str]], scan_date: date) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in candidates:
        latest = decimal_or_none(quotes.get(row["symbol"], {}).get("latest_price")) or decimal_or_none(row.get("hypothetical_entry_price")) or ZERO
        entry = decimal_or_none(row.get("hypothetical_entry_price")) or ZERO
        stop = decimal_or_none(row.get("hypothetical_stop_price")) or ZERO
        target = decimal_or_none(row.get("hypothetical_target_price")) or ZERO
        qty = quantity_from_prices(entry, stop)
        direction = row.get("signal_direction", "")
        pnl = simulated_pnl(direction, latest, entry, qty)
        signal_date = row.get("bar_timestamp", "")[:10]
        rows.append(
            {
                "strategy_id": row["strategy_id"],
                "strategy_title": row["strategy_title"],
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "direction": direction_zh(direction),
                "signal_time": row.get("bar_timestamp", ""),
                "signal_date": signal_date,
                "is_current_scan_date": str(signal_date == scan_date.isoformat()).lower(),
                "latest_price": money(latest),
                "latest_price_source": quotes.get(row["symbol"], {}).get("quote_source", "candidate_reference_fallback"),
                "hypothetical_entry_price": row.get("hypothetical_entry_price", ""),
                "hypothetical_stop_price": row.get("hypothetical_stop_price", ""),
                "hypothetical_target_price": row.get("hypothetical_target_price", ""),
                "hypothetical_quantity": str(qty.quantize(Decimal("0.0001"))),
                "simulated_intraday_pnl": money(pnl),
                "simulated_intraday_return_percent": pct(pnl / DEFAULT_EQUITY * HUNDRED),
                "simulated_state": simulated_state(direction, latest, stop, target),
                "bucket": "今日新扫描机会" if signal_date == scan_date.isoformat() else "旧观察机会",
                "candidate_status": row.get("candidate_status", ""),
                "queue_action": row.get("queue_action", ""),
                "review_status": row.get("review_status", ""),
                "risk_level": row.get("risk_level", ""),
                "notes": row.get("notes", ""),
                "data_path": row.get("data_path", ""),
                "data_lineage": row.get("data_lineage", ""),
                "data_checksum": row.get("data_checksum", ""),
                "spec_ref": row.get("spec_ref", ""),
                "simulated_context": row.get("simulated_context", ""),
                "candidate_schema_version": row.get("schema_version", ""),
                "source_refs": row.get("source_refs", ""),
                "signal_source_type": "formal_scan",
            }
        )
    return rows


def next_us_trading_date(value: date) -> date:
    candidate = value + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def build_pa004_formal_rows(
    first50: list[str],
    quotes: dict[str, dict[str, str]],
    generated_at: str,
    scan_date: date,
) -> list[dict[str, str]]:
    detector_config = load_m12_20_config()
    daily_start = parse_iso_date(str(detector_config.daily_start)) or date(2010, 6, 29)
    rows: list[dict[str, str]] = []
    for symbol in first50:
        cache_path = best_cache_file(
            detector_config.local_data_roots,
            symbol,
            "1d",
            daily_start,
            scan_date,
        )
        if cache_path is None or not cache_path.exists():
            continue
        bars = load_bars(cache_path)
        if not bars:
            continue
        checksum = file_sha256(cache_path)
        events = detect_broad_channel_boundary_reversal(
            generated_at=generated_at,
            symbol=symbol,
            bars=bars,
            data_path=cache_path,
            source_checksum=checksum,
        )
        for event in events:
            if event.get("direction") != "long":
                continue
            event_date = iso_to_ny_trading_date(event.get("bar_timestamp", ""))
            if event_date is None:
                continue
            trade_date = next_us_trading_date(event_date)
            if trade_date != scan_date:
                continue
            candidate = pa004_candidate_from_event(event)
            if not candidate:
                continue
            quote = quotes.get(symbol, {})
            latest = decimal_or_none(quote.get("latest_price")) or decimal_or_none(candidate.get("hypothetical_entry_price")) or ZERO
            entry = decimal_or_none(candidate.get("hypothetical_entry_price")) or ZERO
            stop = decimal_or_none(candidate.get("hypothetical_stop_price")) or ZERO
            target = decimal_or_none(candidate.get("hypothetical_target_price")) or ZERO
            qty = quantity_from_prices(entry, stop)
            pnl = simulated_pnl("看涨", latest, entry, qty)
            rows.append(
                {
                    "strategy_id": "M10-PA-004",
                    "variant_id": "pa004_long_only_formal",
                    "strategy_title": "宽通道边界反转（只做多正式版）",
                    "symbol": symbol,
                    "timeframe": "1d",
                    "direction": "看涨",
                    "signal_time": candidate["signal_time"],
                    "signal_date": trade_date.isoformat(),
                    "is_current_scan_date": str(trade_date.isoformat() == scan_date.isoformat()).lower(),
                    "latest_price": money(latest),
                    "latest_price_source": quote.get("quote_source", "candidate_reference_fallback"),
                    "hypothetical_entry_price": candidate["hypothetical_entry_price"],
                    "hypothetical_stop_price": candidate["hypothetical_stop_price"],
                    "hypothetical_target_price": candidate["hypothetical_target_price"],
                    "hypothetical_quantity": str(qty.quantize(Decimal("0.0001"))),
                    "simulated_intraday_pnl": money(pnl),
                    "simulated_intraday_return_percent": pct(pnl / DEFAULT_EQUITY * HUNDRED),
                    "simulated_state": simulated_state("看涨", latest, stop, target),
                    "bucket": "PA004 正式账户信号",
                    "candidate_status": "formal_detector_entry",
                    "queue_action": "open_runtime_account_if_scan_date_matches",
                    "review_status": "PA004 只做多正式账户信号：前一交易日日线确认，当前交易日按账户口径入场。",
                    "risk_level": "中",
                    "notes": "该信号已从历史观察样例拆出，正式进入主线账户输入。",
                    "data_path": project_path(cache_path),
                    "data_lineage": event.get("source_lineage", ""),
                    "data_checksum": checksum,
                    "spec_ref": event.get("spec_ref", ""),
                    "simulated_context": "broad_channel_boundary_reversal_long_only",
                    "candidate_schema_version": event.get("schema_version", ""),
                    "source_refs": ";".join(event.get("source_refs", [])),
                    "signal_source_type": "formal_detector_entry",
                }
            )
    rows.sort(key=lambda row: (row["signal_time"], row["symbol"]), reverse=True)
    return rows


def build_pa004_reference_rows(quotes: dict[str, dict[str, str]], generated_at: str) -> list[dict[str, str]]:
    rows = build_pa004_long_rows(load_m12_28_config(), quotes, generated_at)
    for row in rows:
        row["bucket"] = "PA004 历史参考样例"
        row["signal_source_type"] = "reference_observation"
    return rows


def build_strategy_closure_rows(config: M1229Config) -> list[dict[str, str]]:
    metrics = {row["strategy_id"]: row for row in read_csv(config.m10_12_all_strategy_metrics_path)}
    source_plan = load_json(config.m12_16_source_candidate_plan_path)
    best_ftd = load_json(config.m12_15_best_variant_path)["metrics"]
    small_pilot = metrics_by_strategy(config.m12_24_small_pilot_metrics_path)
    pa004_long_metrics = metrics_by_strategy(config.m12_27_pa004_long_metrics_path, cohort_id="long_only")
    source_by_linked = {row["linked_runtime_id"]: row for row in source_plan["rows"]}
    rows: list[dict[str, str]] = []
    decisions = {
        "M10-PA-001": ("主线正式账户", "核心顺势策略，进入 1d + 5m 正式模拟账户。"),
        "M10-PA-002": ("主线正式账户", "突破后跟进策略，进入 1d + 5m 正式模拟账户。"),
        "M10-PA-003": ("过滤器/排名因子", "紧密通道更适合作为强趋势股票加分项，不独立造触发。"),
        "M10-PA-004": ("主线正式账户：只做多版", "只做多版已升主线，独立 1d 账户测试；做空版继续冻结。"),
        "M10-PA-005": ("实验账户测试", "定义仍弱，但不能空挂；进入 1d + 5m 实验账户继续测。"),
        "M10-PA-006": ("挂件 A/B", "BLSHS 限价框架只作为挂件，不独立开账户。"),
        "M10-PA-007": ("实验账户测试", "第二腿陷阱反转进入 1d 实验账户，而不是只观察不入账。"),
        "M10-PA-008": ("实验账户测试", "主要趋势反转进入 1d 实验账户，继续用账户结果决定升降级。"),
        "M10-PA-009": ("实验账户测试", "楔形反转进入 1d 实验账户。"),
        "M10-PA-010": ("研究项", "Final Flag/Climax/TBTL 过于复合，不作为单独触发。"),
        "M10-PA-011": ("实验账户测试", "开盘反转不并入主线，但进入 1d + 5m 实验账户继续测。"),
        "M10-PA-012": ("主线正式账户", "开盘区间突破继续作为 5m 主线正式账户。"),
        "M10-PA-013": ("实验账户测试", "支撑阻力失败测试进入 1d + 5m 实验账户继续测。"),
        "M10-PA-014": ("挂件 A/B", "Measured Move 只作为目标/止盈模块。"),
        "M10-PA-015": ("挂件 A/B", "止损与仓位模块，不是入场触发。"),
        "M10-PA-016": ("挂件 A/B", "交易区间加仓只作为挂件研究模块。"),
    }
    for strategy_id in [f"M10-PA-{idx:03d}" for idx in range(1, 17)]:
        metric = metrics.get(strategy_id, {})
        status, reason = decisions[strategy_id]
        pilot = pa004_long_metrics.get(strategy_id, {}) if strategy_id == "M10-PA-004" else small_pilot.get(strategy_id, {})
        rows.append(
            {
                "strategy_id": strategy_id,
                "strategy_title": metric.get("title", strategy_id),
                "final_status": status,
                "daily_realtime_test": str(status.startswith("主线正式账户")).lower(),
                "experimental_account": str(status == "实验账户测试").lower(),
                "observation_queue": "false",
                "supporting_or_research": str(status in {"过滤器/排名因子", "研究项", "挂件 A/B"}).lower(),
                "return_percent": pilot.get("return_percent") or metric.get("return_percent", ""),
                "win_rate_percent": pilot.get("win_rate_percent") or normalize_rate(pilot.get("win_rate", "")) or normalize_rate(metric.get("win_rate", "")),
                "max_drawdown_percent": pilot.get("max_drawdown_percent") or metric.get("max_drawdown_percent", ""),
                "trade_count": pilot.get("trade_count") or metric.get("trade_count", ""),
                "historical_initial_capital": pilot.get("initial_capital") or metric.get("initial_capital", ""),
                "historical_final_equity": pilot.get("final_equity") or metric.get("final_equity", ""),
                "historical_net_profit": pilot.get("net_profit") or metric.get("net_profit", ""),
                "historical_profit_factor": pilot.get("profit_factor") or metric.get("profit_factor", ""),
                "historical_average_holding_bars": pilot.get("average_holding_bars") or metric.get("average_holding_bars", ""),
                "historical_best_symbol": pilot.get("best_symbol") or metric.get("best_symbol", ""),
                "historical_worst_symbol": pilot.get("worst_symbol") or metric.get("worst_symbol", ""),
                "historical_best_timeframe": pilot.get("best_timeframe") or metric.get("best_timeframe", ""),
                "historical_worst_timeframe": pilot.get("worst_timeframe") or metric.get("worst_timeframe", ""),
                "linked_source_candidate": source_by_linked.get(strategy_id, {}).get("candidate_id", ""),
                "plain_reason": reason,
                "paper_trial_candidate_now": "false",
            }
        )
    rows.append(
        {
            "strategy_id": "M12-FTD-001",
            "strategy_title": "方方土日线趋势顺势信号K",
            "final_status": "主线正式账户",
            "daily_realtime_test": "true",
            "experimental_account": "false",
            "observation_queue": "false",
            "supporting_or_research": "false",
            "return_percent": best_ftd.get("return_percent", ""),
            "win_rate_percent": best_ftd.get("win_rate", ""),
            "max_drawdown_percent": best_ftd.get("max_drawdown_percent", ""),
            "trade_count": str(best_ftd.get("trade_count", "")),
            "historical_initial_capital": best_ftd.get("initial_capital", ""),
            "historical_final_equity": best_ftd.get("final_equity", ""),
            "historical_net_profit": best_ftd.get("net_profit", ""),
            "historical_profit_factor": best_ftd.get("profit_factor", ""),
            "historical_average_holding_bars": best_ftd.get("average_holding_bars", ""),
            "historical_best_symbol": "",
            "historical_worst_symbol": "",
            "historical_best_timeframe": "1d",
            "historical_worst_timeframe": "1d",
            "linked_source_candidate": "M12-SRC-001",
            "plain_reason": "早期强策略已改为 pullback_guard 版本，进入每日只读测试观察回撤。",
            "paper_trial_candidate_now": "false",
        }
    )
    for source in source_plan["rows"]:
        rows.append(
            {
                "strategy_id": source["candidate_id"],
                "strategy_title": source["name"],
                "final_status": "已合并到 " + source["linked_runtime_id"],
                "daily_realtime_test": str(source["queue"] == "daily_readonly_test").lower(),
                "experimental_account": str(source["queue"] == "strict_observation").lower(),
                "observation_queue": "false",
                "supporting_or_research": str(source["queue"] == "filter_or_ranking_factor").lower(),
                "return_percent": "",
                "win_rate_percent": "",
                "max_drawdown_percent": "",
                "trade_count": "",
                "historical_initial_capital": "",
                "historical_final_equity": "",
                "historical_net_profit": "",
                "historical_profit_factor": "",
                "historical_average_holding_bars": "",
                "historical_best_symbol": "",
                "historical_worst_symbol": "",
                "historical_best_timeframe": "",
                "historical_worst_timeframe": "",
                "linked_source_candidate": source["linked_runtime_id"],
                "plain_reason": source["client_note"],
                "paper_trial_candidate_now": "false",
            }
        )
    return rows


def build_visual_definition_rows(closure_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    notes = {
        "M10-PA-003": ("紧密通道、小回调、顺势延续", "趋势强弱可近似；通道形态仍需代理字段", "过滤器/排名因子"),
        "M10-PA-004": ("宽通道、边界触碰、边界后反转", "做空分支不稳定；当前只跑做多版", "主线正式账户：只做多版"),
        "M10-PA-007": ("第一腿、第二腿、陷阱点、反向确认", "复杂图形仍可能漏判，只能先实验账户验证", "实验账户测试"),
        "M10-PA-008": ("趋势破坏、二次测试、反转确认", "主要趋势反转仍强依赖上下文", "实验账户测试"),
        "M10-PA-009": ("三推、楔形/楔形旗形、反转确认", "不强制完美收敛，误判需继续实验验证", "实验账户测试"),
        "M10-PA-010": ("最终旗形、高潮、TBTL 片段", "组合概念过多，机器触发不稳定", "研究项"),
        "M10-PA-011": ("开盘反转、开盘失败突破", "历史结果偏弱，但已进实验账户继续测", "实验账户测试"),
        "M10-PA-013": ("支撑阻力失败测试", "历史结果偏弱，但已进实验账户继续测", "实验账户测试"),
    }
    by_id = {row["strategy_id"]: row for row in closure_rows}
    rows = []
    for strategy_id, (machine, limitation, final_status) in notes.items():
        rows.append(
            {
                "strategy_id": strategy_id,
                "strategy_title": by_id.get(strategy_id, {}).get("strategy_title", strategy_id),
                "machine_can_identify": machine,
                "machine_cannot_claim": limitation,
                "final_status": final_status,
                "blocks_mainline": "false",
                "needs_user_manual_review": "false",
                "paper_trial_candidate_now": "false",
            }
        )
    return rows


def build_account_history_lookup(config: M1229Config, closure_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    closure_by_strategy = {row["strategy_id"]: row for row in closure_rows}
    lookup: dict[str, dict[str, str]] = {}
    ftd_variant_path = (
        M10_DIR
        / "news_earnings"
        / "m12_42_ftd001_news_risk_ab"
        / "m12_42_ftd001_news_risk_ab_metrics.csv"
    )
    ftd_variants: dict[str, dict[str, str]] = {}
    if ftd_variant_path.exists():
        with ftd_variant_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("variant_id"):
                    ftd_variants[row["variant_id"]] = row
    for spec in ACCOUNT_SPECS:
        history = dict(closure_by_strategy.get(spec["strategy_id"], {}))
        if spec["strategy_id"] == "M12-FTD-001":
            variant_history = ftd_variants.get(spec["variant_id"])
            if variant_history:
                history.update(
                    {
                        "return_percent": variant_history.get("return_percent", ""),
                        "win_rate_percent": normalize_rate(variant_history.get("win_rate", "")),
                        "max_drawdown_percent": variant_history.get("max_drawdown_percent", ""),
                        "historical_initial_capital": variant_history.get("initial_capital", ""),
                        "historical_final_equity": variant_history.get("final_equity", ""),
                        "historical_net_profit": variant_history.get("net_profit", ""),
                        "historical_profit_factor": variant_history.get("profit_factor", ""),
                        "historical_average_holding_bars": variant_history.get("average_holding_bars", ""),
                        "variant_label": variant_history.get("variant_title", spec["variant_id"]),
                    }
                )
        lookup[spec["account_id"]] = history
    return lookup


def runtime_signal_rows(
    spec: dict[str, str],
    trade_rows: list[dict[str, str]],
    pa004_formal_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    if spec["strategy_id"] == "M10-PA-004":
        return [row for row in pa004_formal_rows if row.get("timeframe") == spec["timeframe"]]
    return [
        row for row in trade_rows
        if row.get("strategy_id") == spec["strategy_id"]
        and row.get("timeframe") == spec["timeframe"]
    ]


def bootstrap_account_state(spec: dict[str, str]) -> dict[str, Any]:
    return {
        "runtime_id": spec["account_id"],
        "strategy_id": spec["strategy_id"],
        "display_name": spec["display_name"],
        "lane": spec["lane"],
        "timeframe": spec["timeframe"],
        "variant_id": spec["variant_id"],
        "starting_capital": money(DEFAULT_ACCOUNT_EQUITY),
        "cash": money(DEFAULT_ACCOUNT_EQUITY),
        "equity": money(DEFAULT_ACCOUNT_EQUITY),
        "peak_equity": money(DEFAULT_ACCOUNT_EQUITY),
        "realized_pnl": money(ZERO),
        "unrealized_pnl": money(ZERO),
        "max_drawdown_percent": pct(ZERO),
        "open_positions": [],
        "closed_trades": [],
        "processed_signal_ids": [],
        "consecutive_losses": 0,
        "pause_remaining_signals": 0,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def load_account_runtime_state(config: M1229Config) -> dict[str, Any]:
    state_path = config.output_dir / "m12_46_account_runtime_state.json"
    if not state_path.exists():
        return {
            "schema_version": "m12.46.account-runtime-state.v1",
            "stage": "M12.46.accountized_realtime_testing",
            "starting_capital": money(DEFAULT_ACCOUNT_EQUITY),
            "risk_rate": str(DEFAULT_ACCOUNT_RISK_RATE),
            "accounts": {},
            "trading_day_registry": {},
        }
    state = load_json(state_path)
    state.setdefault("accounts", {})
    state.setdefault("trading_day_registry", {})
    return state


def account_signal_id(spec: dict[str, str], row: dict[str, str]) -> str:
    base = row.get("variant_id") or spec["variant_id"]
    return "|".join(
        [
            spec["account_id"],
            row.get("symbol", ""),
            row.get("timeframe", ""),
            row.get("signal_time", ""),
            base,
        ]
    )


def build_quote_lookup(trade_rows: list[dict[str, str]], pa004_formal_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for row in trade_rows + pa004_formal_rows:
        symbol = row.get("symbol", "")
        if not symbol:
            continue
        lookup[symbol] = {
            "latest_price": row.get("latest_price", ""),
            "latest_price_source": row.get("latest_price_source", ""),
        }
    return lookup


def holding_days_limit(spec: dict[str, str], history: dict[str, str]) -> int:
    if spec["timeframe"] == "5m":
        return 1
    avg = decimal_or_none(history.get("historical_average_holding_bars") or history.get("average_holding_bars"))
    if avg is None:
        return 5
    return max(1, min(20, int(avg)))


def open_new_positions(
    account: dict[str, Any],
    spec: dict[str, str],
    rows: list[dict[str, str]],
    scan_date: date,
    generated_at: str,
) -> tuple[list[dict[str, Any]], int]:
    new_ledger: list[dict[str, Any]] = []
    opened = 0
    for row in rows:
        if row.get("signal_date") != scan_date.isoformat():
            continue
        signal_id = account_signal_id(spec, row)
        if signal_id in account["processed_signal_ids"]:
            continue
        if spec["variant_id"] == "loss_streak_guard" and account.get("pause_remaining_signals", 0) > 0:
            account["pause_remaining_signals"] -= 1
            account["processed_signal_ids"].append(signal_id)
            continue
        entry = money_to_decimal(row.get("hypothetical_entry_price", ""))
        stop = money_to_decimal(row.get("hypothetical_stop_price", ""))
        target = money_to_decimal(row.get("hypothetical_target_price", ""))
        latest = money_to_decimal(row.get("latest_price", ""))
        if entry <= ZERO or stop <= ZERO:
            continue
        risk_per_share = abs(entry - stop)
        if risk_per_share <= ZERO:
            continue
        current_equity = money_to_decimal(account["equity"])
        available_cash = money_to_decimal(account["cash"])
        risk_budget = (current_equity * DEFAULT_ACCOUNT_RISK_RATE).quantize(MONEY)
        max_risk_qty = risk_budget / risk_per_share
        max_cash_qty = available_cash / entry if entry > ZERO else ZERO
        qty = min(max_risk_qty, max_cash_qty).quantize(Decimal("0.0001"))
        if qty <= ZERO:
            continue
        reserved_notional = (entry * qty).quantize(MONEY)
        account["cash"] = money(available_cash - reserved_notional)
        position = {
            "position_id": signal_id,
            "signal_id": signal_id,
            "strategy_id": spec["strategy_id"],
            "runtime_id": spec["account_id"],
            "display_name": spec["display_name"],
            "lane": spec["lane"],
            "timeframe": spec["timeframe"],
            "symbol": row.get("symbol", ""),
            "direction": row.get("direction", ""),
            "signal_time": row.get("signal_time", ""),
            "signal_date": row.get("signal_date", scan_date.isoformat()),
            "opened_at": generated_at,
            "entry_price": money(entry),
            "stop_price": money(stop),
            "target_price": money(target),
            "latest_price": money(latest or entry),
            "quantity": str(qty),
            "reserved_notional": money(reserved_notional),
            "current_pnl": money(ZERO),
            "current_state": "持仓中",
            "review_status": row.get("review_status", ""),
            "risk_level": row.get("risk_level", ""),
            "source_refs": row.get("source_refs", ""),
            "spec_ref": row.get("spec_ref", ""),
        }
        account["open_positions"].append(position)
        account["processed_signal_ids"].append(signal_id)
        opened += 1
        new_ledger.append(
            {
                "event_type": "open",
                "runtime_id": spec["account_id"],
                "strategy_id": spec["strategy_id"],
                "timeframe": spec["timeframe"],
                "symbol": row.get("symbol", ""),
                "signal_time": row.get("signal_time", ""),
                "event_time": generated_at,
                "direction": row.get("direction", ""),
                "entry_price": money(entry),
                "stop_price": money(stop),
                "target_price": money(target),
                "quantity": str(qty),
                "reserved_notional": money(reserved_notional),
            }
        )
    return new_ledger, opened


def mark_position_to_market(
    account: dict[str, Any],
    position: dict[str, Any],
    quote_lookup: dict[str, dict[str, str]],
    spec: dict[str, str],
    generated_at: str,
    scan_date: date,
    max_holding_days: int,
) -> dict[str, Any] | None:
    latest = money_to_decimal(quote_lookup.get(position["symbol"], {}).get("latest_price") or position.get("latest_price", ""))
    if latest > ZERO:
        position["latest_price"] = money(latest)
    entry = money_to_decimal(position["entry_price"])
    stop = money_to_decimal(position["stop_price"])
    target = money_to_decimal(position["target_price"])
    qty = decimal_or_none(position["quantity"]) or ZERO
    direction = position.get("direction", "")
    pnl = simulated_pnl(direction, latest, entry, qty)
    position["current_pnl"] = money(pnl)
    position["current_state"] = simulated_state(direction, latest, stop, target)
    signal_date = parse_iso_date(position.get("signal_date", ""))
    if spec["timeframe"] == "5m" and signal_date and scan_date > signal_date:
        exit_reason = "次日超时退出"
    elif signal_date and (scan_date - signal_date).days >= max_holding_days:
        exit_reason = "持仓到期退出"
    elif position["current_state"] == "触及止损参考":
        exit_reason = "止损"
    elif position["current_state"] == "触及目标参考":
        exit_reason = "止盈"
    else:
        return None
    reserved = money_to_decimal(position["reserved_notional"])
    cash = money_to_decimal(account["cash"])
    account["cash"] = money(cash + reserved + pnl)
    trade = {
        "event_type": "close",
        "runtime_id": account["runtime_id"],
        "strategy_id": account["strategy_id"],
        "timeframe": account["timeframe"],
        "symbol": position["symbol"],
        "event_time": generated_at,
        "direction": direction,
        "entry_price": position["entry_price"],
        "exit_price": money(latest),
        "stop_price": position["stop_price"],
        "target_price": position["target_price"],
        "quantity": position["quantity"],
        "signal_time": position["signal_time"],
        "opened_at": position["opened_at"],
        "exit_reason": exit_reason,
        "realized_pnl": money(pnl),
    }
    account["closed_trades"].append(trade)
    if pnl < ZERO:
        account["consecutive_losses"] = int(account.get("consecutive_losses", 0)) + 1
        if spec["variant_id"] == "loss_streak_guard" and account["consecutive_losses"] >= 3:
            account["pause_remaining_signals"] = 1
            account["consecutive_losses"] = 0
    else:
        account["consecutive_losses"] = 0
    return trade


def recalc_account_metrics(account: dict[str, Any], scan_date: date) -> None:
    open_positions = account["open_positions"]
    reserved = sum((money_to_decimal(position["reserved_notional"]) for position in open_positions), ZERO)
    unrealized = sum((money_to_decimal(position["current_pnl"]) for position in open_positions), ZERO)
    realized = sum((money_to_decimal(trade.get("realized_pnl", "0")) for trade in account["closed_trades"]), ZERO)
    cash = money_to_decimal(account["cash"])
    equity = cash + reserved + unrealized
    peak = max(money_to_decimal(account["peak_equity"]), equity)
    drawdown = ((peak - equity) / peak * HUNDRED) if peak > ZERO else ZERO
    wins = [trade for trade in account["closed_trades"] if money_to_decimal(trade.get("realized_pnl", "0")) > ZERO]
    today_key = scan_date.isoformat()
    today_opened = [position for position in open_positions if position.get("signal_date") == today_key]
    today_closed = [
        trade for trade in account["closed_trades"]
        if iso_to_ny_trading_date(trade.get("event_time", "")) == scan_date
    ]
    today_realized = sum((money_to_decimal(trade.get("realized_pnl", "0")) for trade in today_closed), ZERO)
    account["realized_pnl"] = money(realized)
    account["unrealized_pnl"] = money(unrealized)
    account["equity"] = money(equity)
    account["peak_equity"] = money(peak)
    account["max_drawdown_percent"] = pct(drawdown)
    account["closed_trade_count"] = len(account["closed_trades"])
    account["winning_trade_count"] = len(wins)
    account["losing_trade_count"] = len(account["closed_trades"]) - len(wins)
    account["win_rate_percent"] = pct(Decimal(len(wins)) / Decimal(len(account["closed_trades"])) * HUNDRED) if account["closed_trades"] else "0.00"
    account["cumulative_return_percent"] = pct((equity - DEFAULT_ACCOUNT_EQUITY) / DEFAULT_ACCOUNT_EQUITY * HUNDRED)
    account["today_opened_count"] = len(today_opened)
    account["today_closed_count"] = len(today_closed)
    account["today_realized_pnl"] = money(today_realized)
    account["today_unrealized_pnl"] = money(unrealized)
    account["today_total_pnl"] = money(today_realized + unrealized)
    account["today_signal_count"] = len(today_opened)


def advance_account_runtime(
    config: M1229Config,
    generated_at: str,
    scan_date: date,
    trade_rows: list[dict[str, str]],
    pa004_formal_rows: list[dict[str, str]],
    closure_rows: list[dict[str, str]],
    current_day_complete: bool,
) -> dict[str, Any]:
    state = load_account_runtime_state(config)
    history_lookup = build_account_history_lookup(config, closure_rows)
    quote_lookup = build_quote_lookup(trade_rows, pa004_formal_rows)
    new_ledger_rows: list[dict[str, Any]] = []
    account_rows: list[dict[str, Any]] = []
    mainline_accounts: list[dict[str, Any]] = []
    experimental_accounts: list[dict[str, Any]] = []
    for spec in ACCOUNT_SPECS:
        account = state["accounts"].get(spec["account_id"]) or bootstrap_account_state(spec)
        state["accounts"][spec["account_id"]] = account
        rows = runtime_signal_rows(spec, trade_rows, pa004_formal_rows)
        max_holding = holding_days_limit(spec, history_lookup.get(spec["account_id"], {}))
        remaining: list[dict[str, Any]] = []
        for position in account["open_positions"]:
            closed = mark_position_to_market(account, position, quote_lookup, spec, generated_at, scan_date, max_holding)
            if closed is None:
                remaining.append(position)
            else:
                new_ledger_rows.append(closed)
        account["open_positions"] = remaining
        opened_rows, _ = open_new_positions(account, spec, rows, scan_date, generated_at)
        new_ledger_rows.extend(opened_rows)
        refreshed_positions: list[dict[str, Any]] = []
        for position in account["open_positions"]:
            closed = mark_position_to_market(account, position, quote_lookup, spec, generated_at, scan_date, max_holding)
            if closed is None:
                refreshed_positions.append(position)
            else:
                new_ledger_rows.append(closed)
        account["open_positions"] = refreshed_positions
        recalc_account_metrics(account, scan_date)
        account_view = build_account_view(account, history_lookup.get(spec["account_id"], {}))
        account_rows.append(account_view)
        if spec["lane"] == "mainline":
            mainline_accounts.append(account_view)
        else:
            experimental_accounts.append(account_view)
    registry = state["trading_day_registry"]
    registry_key = scan_date.isoformat()
    previous = registry.get(registry_key, {})
    counted_now = current_day_complete and bool(mainline_accounts) and bool(experimental_accounts)
    registry[registry_key] = {
        "counted": bool(previous.get("counted")) or counted_now,
        "generated_at": generated_at,
        "first_counted_at": previous.get("first_counted_at") or (generated_at if counted_now else ""),
        "mainline_progressed": bool(previous.get("mainline_progressed")) or bool(mainline_accounts),
        "experimental_progressed": bool(previous.get("experimental_progressed")) or bool(experimental_accounts),
        "last_run_complete": counted_now,
    }
    write_json(config.output_dir / "m12_46_account_runtime_state.json", state)
    if new_ledger_rows:
        append_rows_to_jsonl(config.output_dir / "m12_46_account_trade_ledger.jsonl", new_ledger_rows)
    return {
        "state": state,
        "account_rows": account_rows,
        "mainline_accounts": mainline_accounts,
        "experimental_accounts": experimental_accounts,
        "supporting_rule_rows": build_supporting_rule_rows(mainline_accounts, experimental_accounts),
        "signal_watchlist": trade_rows + pa004_formal_rows,
        "account_input_audit_rows": build_account_input_audit_rows(scan_date, trade_rows, pa004_formal_rows),
        "new_trade_ledger_rows": new_ledger_rows,
    }


def build_supporting_rule_rows(mainline_accounts: list[dict[str, Any]], experimental_accounts: list[dict[str, Any]]) -> list[dict[str, str]]:
    active_accounts = mainline_accounts + experimental_accounts
    active_ids = [row["runtime_id"] for row in active_accounts if int(row["today_signal_count"]) > 0]
    rows: list[dict[str, str]] = []
    for spec in SUPPORTING_RULE_SPECS:
        rows.append(
            {
                "supporting_rule_id": spec["supporting_rule_id"],
                "display_name": spec["display_name"],
                "mode": spec["mode"],
                "today_base_signal_accounts": ", ".join(active_ids[:8]) or "暂无",
                "status": "待接入 A/B",
                "plain_reason": "当前先把独立触发策略账户化；挂件规则保持 A/B 位，不伪造独立买卖触发。",
            }
        )
    return rows


def build_account_input_audit_rows(
    scan_date: date,
    trade_rows: list[dict[str, str]],
    pa004_formal_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for spec in ACCOUNT_SPECS:
        if spec["strategy_id"] == "M10-PA-004":
            source_rows = [row for row in pa004_formal_rows if row.get("timeframe") == spec["timeframe"]]
            source_type = "formal_detector_entry"
        else:
            source_rows = [
                row
                for row in trade_rows
                if row.get("strategy_id") == spec["strategy_id"] and row.get("timeframe") == spec["timeframe"]
            ]
            source_type = "formal_scan"
        today_formal_count = sum(1 for row in source_rows if row.get("signal_date") == scan_date.isoformat())
        rows.append(
            {
                "runtime_id": spec["account_id"],
                "strategy_id": spec["strategy_id"],
                "lane": spec["lane"],
                "timeframe": spec["timeframe"],
                "input_source_type": source_type,
                "formal_input_stream": "true",
                "today_formal_signal_count": str(today_formal_count),
                "source_row_count": str(len(source_rows)),
                "watchlist_only": "false",
                "plain_language_result": (
                    "今日有正式账户输入。"
                    if today_formal_count > 0 else
                    "当前账户源已对齐为正式输入流；若今日无信号，会如实显示 0 开仓。"
                ),
            }
        )
    return rows


def build_account_view(account: dict[str, Any], history: dict[str, str]) -> dict[str, str]:
    open_positions = account["open_positions"]
    symbols = sorted({position["symbol"] for position in open_positions + account["closed_trades"]})
    return {
        "runtime_id": account["runtime_id"],
        "strategy_id": account["strategy_id"],
        "display_name": account["display_name"],
        "lane": account["lane"],
        "timeframe": account["timeframe"],
        "variant_id": account["variant_id"],
        "starting_capital": account["starting_capital"],
        "cash": account["cash"],
        "equity": account["equity"],
        "realized_pnl": account["realized_pnl"],
        "unrealized_pnl": account["unrealized_pnl"],
        "today_total_pnl": account["today_total_pnl"],
        "today_realized_pnl": account["today_realized_pnl"],
        "today_unrealized_pnl": account["today_unrealized_pnl"],
        "today_opened_count": str(account["today_opened_count"]),
        "today_closed_count": str(account["today_closed_count"]),
        "today_signal_count": str(account["today_signal_count"]),
        "open_position_count": str(len(open_positions)),
        "closed_trade_count": str(account["closed_trade_count"]),
        "winning_trade_count": str(account["winning_trade_count"]),
        "losing_trade_count": str(account["losing_trade_count"]),
        "win_rate_percent": account["win_rate_percent"],
        "max_drawdown_percent": account["max_drawdown_percent"],
        "cumulative_return_percent": account["cumulative_return_percent"],
        "symbols": ", ".join(symbols[:10]),
        "historical_return_percent": history.get("return_percent", ""),
        "historical_win_rate_percent": history.get("win_rate_percent", ""),
        "historical_max_drawdown_percent": history.get("max_drawdown_percent", ""),
        "historical_profit_factor": history.get("historical_profit_factor", ""),
        "historical_initial_capital": history.get("historical_initial_capital", history.get("initial_capital", "")),
        "historical_final_equity": history.get("historical_final_equity", history.get("final_equity", "")),
        "historical_net_profit": history.get("historical_net_profit", history.get("net_profit", "")),
        "historical_average_holding_bars": history.get("historical_average_holding_bars", history.get("average_holding_bars", "")),
        "variant_label": history.get("variant_label", ""),
        "paper_trial_candidate_now": "false",
    }


def build_account_overview(name: str, accounts: list[dict[str, str]]) -> dict[str, Any]:
    starting = DEFAULT_ACCOUNT_EQUITY * Decimal(len(accounts))
    current = sum((money_to_decimal(row["equity"]) for row in accounts), ZERO)
    day_pnl = sum((money_to_decimal(row["today_total_pnl"]) for row in accounts), ZERO)
    max_drawdown = max((decimal_or_none(row["max_drawdown_percent"]) or ZERO for row in accounts), default=ZERO)
    closed_trades = sum((int(row["closed_trade_count"]) for row in accounts), 0)
    wins = sum((int(row["winning_trade_count"]) for row in accounts), 0)
    return {
        "account_group_name": name,
        "starting_capital": money(starting),
        "current_equity": money(current),
        "day_pnl": money(day_pnl),
        "cumulative_return_percent": pct((current - starting) / starting * HUNDRED) if starting > ZERO else "0.00",
        "win_rate_percent": pct(Decimal(wins) / Decimal(closed_trades) * HUNDRED) if closed_trades else "0.00",
        "max_drawdown_percent": pct(max_drawdown),
        "today_opened_count": str(sum(int(row["today_opened_count"]) for row in accounts)),
        "today_closed_count": str(sum(int(row["today_closed_count"]) for row in accounts)),
        "today_signal_count": str(sum(int(row["today_signal_count"]) for row in accounts)),
        "strategy_account_count": str(len(accounts)),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_accountized_timeframe_views(account_rows: list[dict[str, str]]) -> dict[str, Any]:
    views: dict[str, Any] = {}
    for timeframe in PRIMARY_TIMEFRAME_ORDER:
        rows = [row for row in account_rows if row["timeframe"] == timeframe]
        mainline = [row for row in rows if row["lane"] == "mainline"]
        experimental = [row for row in rows if row["lane"] == "experimental"]
        pnl = sum((money_to_decimal(row["today_total_pnl"]) for row in rows), ZERO)
        views[timeframe] = {
            "timeframe": timeframe,
            "display_name": TIMEFRAME_LABELS[timeframe],
            "account_count": len(rows),
            "mainline_account_count": len(mainline),
            "experimental_account_count": len(experimental),
            "today_total_pnl": money(pnl),
            "win_rate_percent": pct(
                Decimal(sum(int(row["winning_trade_count"]) for row in rows))
                / Decimal(sum(int(row["closed_trade_count"]) for row in rows))
                * HUNDRED
            ) if sum(int(row["closed_trade_count"]) for row in rows) else "0.00",
            "strategy_rows": rows,
            "plain_language_note": timeframe_note(timeframe, []),
        }
    return {
        "schema_version": "m12.46.timeframe-account-views.v1",
        "stage": "M12.46.timeframe_account_views",
        "timeframe_order": list(PRIMARY_TIMEFRAME_ORDER),
        "views": views,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_ftd_account_monitor(mainline_accounts: list[dict[str, str]]) -> dict[str, Any]:
    rows = [row for row in mainline_accounts if row["strategy_id"] == "M12-FTD-001"]
    baseline = next((row for row in rows if row["variant_id"] == "baseline"), None)
    guard = next((row for row in rows if row["variant_id"] == "loss_streak_guard"), None)
    active = guard or baseline
    risk_flags: list[str] = []
    if active and decimal_or_none(active.get("historical_max_drawdown_percent", "")) and decimal_or_none(active["historical_max_drawdown_percent"]) >= Decimal("40"):
        risk_flags.append("历史最大回撤高")
    if active and decimal_or_none(active.get("historical_profit_factor", "")) and decimal_or_none(active["historical_profit_factor"]) <= Decimal("1.10"):
        risk_flags.append("盈利因子偏薄")
    if active and money_to_decimal(active.get("today_total_pnl", "0")) < ZERO:
        risk_flags.append("今日暂时亏损")
    if baseline and int(baseline["today_signal_count"]) > 10:
        risk_flags.append("触发过密")
    if not risk_flags:
        risk_flags.append("继续观察")
    return {
        "schema_version": "m12.46.ftd-account-monitor.v1",
        "stage": "M12.46.ftd_account_monitor",
        "accounts": rows,
        "current_plain_status": f"FTD001 对照：原版 {baseline['today_total_pnl'] if baseline else '暂无'} / 连亏保护 {guard['today_total_pnl'] if guard else '暂无'}",
        "risk_flags": risk_flags,
        "plain_language_summary": (
            f"FTD001 原版今日 {baseline['today_total_pnl'] if baseline else '暂无'}，"
            f"连亏保护版今日 {guard['today_total_pnl'] if guard else '暂无'}；"
            f"重点看回撤、连亏和是否过度触发。"
        ),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_extended_session_monitor(quotes: dict[str, dict[str, str]]) -> dict[str, Any]:
    premarket_rows = build_extended_session_rows(quotes, "pre_market", "盘前")
    postmarket_rows = build_extended_session_rows(quotes, "post_market", "盘后")
    focus_hits = [
        row for row in (premarket_rows + postmarket_rows)
        if row["symbol"] in EXTENDED_SESSION_FOCUS_LABELS and row["threshold_hit"] == "true"
    ]
    summary_parts: list[str] = []
    if premarket_rows:
        summary_parts.append(f"盘前异动 {len(premarket_rows)} 条，最强 {extended_mover_label(premarket_rows[0])}")
    if postmarket_rows:
        summary_parts.append(f"盘后异动 {len(postmarket_rows)} 条，最强 {extended_mover_label(postmarket_rows[0])}")
    if focus_hits:
        summary_parts.append("重点关注股命中：" + "，".join(extended_mover_label(row) for row in focus_hits[:6]))
    if not summary_parts:
        summary_parts.append("当前没有超过 3% 的盘前/盘后异动。")
    return {
        "schema_version": "m12.48.extended-session-monitor.v1",
        "stage": "M12.48.extended_session_monitor",
        "threshold_percent": pct(EXTENDED_SESSION_MOVE_THRESHOLD),
        "premarket_rows": premarket_rows[:12],
        "postmarket_rows": postmarket_rows[:12],
        "focus_hits": focus_hits[:12],
        "premarket_count": len(premarket_rows),
        "postmarket_count": len(postmarket_rows),
        "focus_hit_count": len(focus_hits),
        "plain_language_summary": "；".join(summary_parts),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_extended_session_rows(
    quotes: dict[str, dict[str, str]],
    prefix: str,
    session_display: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for symbol, quote in quotes.items():
        extended_price = decimal_or_none(quote.get(f"{prefix}_last"))
        reference_close = decimal_or_none(quote.get(f"{prefix}_reference_close"))
        move_percent = decimal_or_none(quote.get(f"{prefix}_move_percent"))
        if extended_price in (None, ZERO) or reference_close in (None, ZERO) or move_percent is None:
            continue
        move_amount = decimal_or_none(quote.get(f"{prefix}_move_amount")) or ZERO
        rows.append(
            {
                "symbol": symbol,
                "session": session_display,
                "theme": EXTENDED_SESSION_FOCUS_LABELS.get(symbol, ""),
                "quote_timestamp": quote.get(f"{prefix}_timestamp", ""),
                "reference_close": money(reference_close),
                "extended_price": money(extended_price),
                "move_amount": money(move_amount),
                "move_percent": pct(move_percent),
                "move_direction": "上涨" if move_percent > ZERO else "下跌" if move_percent < ZERO else "持平",
                "threshold_hit": "true" if abs(move_percent) >= EXTENDED_SESSION_MOVE_THRESHOLD else "false",
                "quote_source": quote.get("quote_source", ""),
                "quote_status": quote.get("quote_status", ""),
            }
        )
    rows = [row for row in rows if row["threshold_hit"] == "true"]
    rows.sort(key=lambda row: abs(money_to_decimal(row["move_percent"])), reverse=True)
    return rows


def extended_mover_label(row: dict[str, str]) -> str:
    theme = f"（{row['theme']}）" if row.get("theme") else ""
    return f"{row['symbol']}{theme} {row['move_percent']}%"


def build_trade_ledger_rows(account_rows: list[dict[str, str]], state: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for account_row in account_rows:
        account = state["accounts"][account_row["runtime_id"]]
        for position in account["open_positions"]:
            rows.append(
                {
                    "record_type": "open_position",
                    "runtime_id": account_row["runtime_id"],
                    "strategy_id": account_row["strategy_id"],
                    "display_name": account_row["display_name"],
                    "lane": account_row["lane"],
                    "timeframe": account_row["timeframe"],
                    "symbol": position["symbol"],
                    "direction": direction_zh(position["direction"]),
                    "opened_at": position["opened_at"],
                    "signal_time": position["signal_time"],
                    "entry_price": position["entry_price"],
                    "stop_price": position["stop_price"],
                    "target_price": position["target_price"],
                    "latest_price": position["latest_price"],
                    "quantity": position["quantity"],
                    "pnl": position["current_pnl"],
                    "state": position["current_state"],
                }
            )
        for trade in account["closed_trades"][-10:]:
            rows.append(
                {
                    "record_type": "closed_trade",
                    "runtime_id": account_row["runtime_id"],
                    "strategy_id": account_row["strategy_id"],
                    "display_name": account_row["display_name"],
                    "lane": account_row["lane"],
                    "timeframe": account_row["timeframe"],
                    "symbol": trade["symbol"],
                    "direction": direction_zh(trade["direction"]),
                    "opened_at": trade["opened_at"],
                    "signal_time": trade["signal_time"],
                    "entry_price": trade["entry_price"],
                    "stop_price": trade["stop_price"],
                    "target_price": trade["target_price"],
                    "latest_price": trade["exit_price"],
                    "quantity": trade["quantity"],
                    "pnl": trade["realized_pnl"],
                    "state": trade["exit_reason"],
                }
            )
    rows.sort(key=lambda row: (row["signal_time"], row["record_type"], row["runtime_id"]), reverse=True)
    return rows[:260]


def build_accountized_summary(
    config: M1229Config,
    generated_at: str,
    market: dict[str, str],
    scan_date: date,
    source_summary: dict[str, Any],
    cache_summary: dict[str, Any],
    quote_manifest: dict[str, Any],
    extended_session_monitor: dict[str, Any],
    trade_rows: list[dict[str, str]],
    pa004_formal_rows: list[dict[str, str]],
    pa004_reference_rows: list[dict[str, str]],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    current_rows = [row for row in trade_rows if row["is_current_scan_date"] == "true"]
    old_rows = [row for row in trade_rows if row["is_current_scan_date"] != "true"]
    mainline = build_account_overview("主线正式账户", runtime["mainline_accounts"])
    experimental = build_account_overview("实验账户", runtime["experimental_accounts"])
    current_day_complete = cache_summary["daily_ready_symbols"] == config.first_batch_size and cache_summary["current_5m_ready_symbols"] == config.first_batch_size
    return {
        "schema_version": "m12.46.accountized-summary.v1",
        "stage": "M12.46.accountized_realtime_testing",
        "generated_at": generated_at,
        "market_session": market,
        "scan_date": scan_date.isoformat(),
        "source_m12_12_summary_ref": project_path(source_config_output_path(config, "m12_12_daily_observation_summary.json")),
        "source_m12_12_candidate_count": len(trade_rows),
        "quote_count": quote_manifest.get("quote_count", 0),
        "quote_source": quote_manifest.get("quote_source", ""),
        "today_candidate_count": len(current_rows),
        "old_candidate_count": len(old_rows),
        "visible_opportunity_count": len(trade_rows) + len(pa004_formal_rows),
        "signal_watchlist_count": len(runtime["signal_watchlist"]),
        "reference_watchlist_count": len(pa004_reference_rows),
        "pa004_formal_signal_count": len(pa004_formal_rows),
        "premarket_mover_count": extended_session_monitor["premarket_count"],
        "postmarket_mover_count": extended_session_monitor["postmarket_count"],
        "focus_mover_count": extended_session_monitor["focus_hit_count"],
        "mainline_today_pnl": mainline["day_pnl"],
        "experimental_today_pnl": experimental["day_pnl"],
        "mainline_current_equity": mainline["current_equity"],
        "experimental_current_equity": experimental["current_equity"],
        "mainline_return_percent": mainline["cumulative_return_percent"],
        "experimental_return_percent": experimental["cumulative_return_percent"],
        "current_day_scan_complete": current_day_complete,
        "candidate_date_warning": "" if not old_rows else f"仍有 {len(old_rows)} 条旧日期候选留在观察信号里，不能当作今日新开仓。",
        "first50_daily_ready_symbols": cache_summary["daily_ready_symbols"],
        "first50_current_5m_ready_symbols": cache_summary["current_5m_ready_symbols"],
        "plain_language_result": (
            f"主线正式账户当前权益 {mainline['current_equity']}，今日盈亏 {mainline['day_pnl']}；"
            f"实验账户当前权益 {experimental['current_equity']}，今日盈亏 {experimental['day_pnl']}。"
            f"PA004 正式信号 {len(pa004_formal_rows)} 条，历史参考样例 {len(pa004_reference_rows)} 条（不入账）。"
            f"{extended_session_monitor['plain_language_summary']}"
        ),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def source_config_output_path(config: M1229Config, filename: str) -> Path:
    return config.output_dir / "m12_12_current_day_source" / filename


def build_accountized_dashboard_payload(
    config: M1229Config,
    generated_at: str,
    summary: dict[str, Any],
    runtime: dict[str, Any],
    extended_session_monitor: dict[str, Any],
    closure_rows: list[dict[str, str]],
    visual_rows: list[dict[str, str]],
    pa004_reference_rows: list[dict[str, str]],
) -> dict[str, Any]:
    mainline_overview = build_account_overview("主线正式账户", runtime["mainline_accounts"])
    experimental_overview = build_account_overview("实验账户", runtime["experimental_accounts"])
    timeframe_views = build_accountized_timeframe_views(runtime["account_rows"])
    ftd001_monitor = build_ftd_account_monitor(runtime["mainline_accounts"])
    codex_observer = build_accountized_codex_observer(
        config,
        summary,
        mainline_overview,
        experimental_overview,
        timeframe_views,
        ftd001_monitor,
        extended_session_monitor,
    )
    trade_ledger_rows = build_trade_ledger_rows(runtime["account_rows"], runtime["state"])
    update_status = build_dashboard_update_status(config, summary, config.dashboard_refresh_seconds)
    return {
        "schema_version": "m12.46.accountized-readonly-dashboard.v1",
        "stage": "M12.46.accountized_realtime_dashboard",
        "generated_at": generated_at,
        "title": "分钟级只读模拟账户看板",
        "refresh_seconds": config.dashboard_refresh_seconds,
        "update_status": update_status,
        "top_metrics": {
            "主线模拟权益": mainline_overview["current_equity"],
            "主线今日盈亏": mainline_overview["day_pnl"],
            "主线累计收益": mainline_overview["cumulative_return_percent"] + "%",
            "主线胜率": mainline_overview["win_rate_percent"] + "%",
            "主线最大回撤": mainline_overview["max_drawdown_percent"] + "%",
            "今日新开仓": mainline_overview["today_opened_count"],
            "今日已平仓": mainline_overview["today_closed_count"],
            "FTD001 对照": ftd001_monitor["current_plain_status"],
            "盘前/盘后异动": extended_session_monitor["plain_language_summary"],
            "北京时间更新": update_status["beijing_time"],
            "运行状态": update_status["runtime_status"],
        },
        "dashboard_layout": {
            "home": "主线正式账户总览",
            "experimental": "实验账户总览",
            "timeframe_views": "按 1d / 5m 分组测试",
            "ftd001_focus": "FTD001 双版本对照",
            "extended_session_monitor": "盘前 / 盘后异动",
            "trade_ledger": "模拟交易明细",
            "signal_watchlist": "信号观察清单",
        },
        "shared_account_view": mainline_overview,
        "mainline_account_view": mainline_overview,
        "experimental_account_view": experimental_overview,
        "mainline_accounts": runtime["mainline_accounts"],
        "experimental_accounts": runtime["experimental_accounts"],
        "supporting_rule_ab_results": {
            "schema_version": "m12.46.supporting-rule-ab.v1",
            "rows": runtime["supporting_rule_rows"],
        },
        "account_input_audit": {
            "schema_version": "m12.46.account-input-audit.v1",
            "rows": runtime["account_input_audit_rows"],
        },
        "strategy_scorecard_rows": runtime["account_rows"],
        "strategy_detail_views": build_account_detail_views(runtime["state"], runtime["account_rows"]),
        "observation_test_lane": {
            "schema_version": "m12.46.experimental-account-lane.v1",
            "stage": "M12.46.experimental_account_lane",
            "plain_language_result": "实验策略也已经进入独立账户测试；即使没有触发，也会保留零触发记录，不再空挂。",
            "rows": runtime["experimental_accounts"],
            "paper_simulated_only": True,
            "trading_connection": False,
            "real_money_actions": False,
            "live_execution": False,
            "paper_trading_approval": False,
        },
        "timeframe_views": timeframe_views,
        "ftd001_monitor": ftd001_monitor,
        "extended_session_monitor": extended_session_monitor,
        "codex_observer": codex_observer,
        "summary": summary,
        "trade_rows": trade_ledger_rows,
        "signal_watchlist": runtime["signal_watchlist"],
        "reference_watchlist": pa004_reference_rows,
        "strategy_status_rows": closure_rows,
        "visual_definition_rows": visual_rows,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_account_detail_views(state: dict[str, Any], account_rows: list[dict[str, str]]) -> dict[str, Any]:
    views: dict[str, Any] = {}
    for row in account_rows:
        account = state["accounts"][row["runtime_id"]]
        views[row["runtime_id"]] = {
            "summary": row,
            "open_positions": account["open_positions"],
            "closed_trades": account["closed_trades"][-20:],
        }
    return views


def build_accountized_codex_observer(
    config: M1229Config,
    summary: dict[str, Any],
    mainline: dict[str, Any],
    experimental: dict[str, Any],
    timeframe_views: dict[str, Any],
    ftd001_monitor: dict[str, Any],
    extended_session_monitor: dict[str, Any],
) -> dict[str, Any]:
    active_timeframes = [
        timeframe_views["views"][timeframe]["display_name"]
        for timeframe in timeframe_views["timeframe_order"]
        if timeframe_views["views"][timeframe]["account_count"] > 0
    ]
    alerts: list[dict[str, str]] = []
    if money_to_decimal(mainline["day_pnl"]) < ZERO:
        alerts.append({"level": "注意", "message": "主线账户今日暂时为负，先看是否集中在 M10-PA-012 或 FTD001。"})
    if summary["candidate_date_warning"]:
        alerts.append({"level": "数据", "message": summary["candidate_date_warning"]})
    if not summary["current_day_scan_complete"]:
        alerts.append({"level": "数据", "message": "第一批 50 只股票当日数据未全部齐。"})
    if extended_session_monitor["premarket_count"] > 0:
        alerts.append({"level": "盘前", "message": extended_session_monitor["plain_language_summary"]})
    elif extended_session_monitor["postmarket_count"] > 0:
        alerts.append({"level": "盘后", "message": extended_session_monitor["plain_language_summary"]})
    if not alerts:
        alerts.append({"level": "正常", "message": "当前主线和实验账户都已刷新，没有明显数据阻塞。"})
    return {
        "schema_version": "m12.46.codex-observer.v1",
        "stage": "M12.46.codex_observer",
        "generated_at": summary["generated_at"],
        "observer_mode": "codex_heartbeat_or_file_inbox",
        "observer_interval_minutes": 15,
        "dashboard_refresh_seconds": config.dashboard_refresh_seconds,
        "market_session": summary["market_session"],
        "plain_language_summary": (
            f"主线模拟权益 {mainline['current_equity']}，主线今日盈亏 {mainline['day_pnl']}；"
            f"实验账户权益 {experimental['current_equity']}，实验今日盈亏 {experimental['day_pnl']}。"
            f"活跃周期：{', '.join(active_timeframes) or '暂无'}。"
            f"{extended_session_monitor['plain_language_summary']} "
            f"{ftd001_monitor['plain_language_summary']}"
        ),
        "active_timeframes": active_timeframes,
        "alerts": alerts,
        "recommended_codex_message": (
            f"盘中只读模拟：主线权益 {mainline['current_equity']}，今日 {mainline['day_pnl']}；"
            f"实验账户今日 {experimental['day_pnl']}。"
            f"{extended_session_monitor['plain_language_summary']} "
            f"{ftd001_monitor['plain_language_summary']} 当前提醒："
            + "；".join(f"{row['level']}：{row['message']}" for row in alerts)
        ),
        "latest_dashboard_json": project_path(config.output_dir / "m12_32_minute_readonly_dashboard_data.json"),
        "latest_dashboard_html": project_path(config.output_dir / "m12_32_minute_readonly_dashboard.html"),
        "observer_inbox": project_path(config.output_dir / "m12_38_codex_observer_inbox.jsonl"),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_dashboard_update_status(config: M1229Config, summary: dict[str, Any], refresh_seconds: int) -> dict[str, str]:
    market = summary["market_session"]
    status = market["status"]
    now_dt = datetime.now(UTC).replace(microsecond=0)
    generated_dt = datetime.fromisoformat(summary["generated_at"].replace("Z", "+00:00"))
    dashboard_age = int((now_dt - generated_dt).total_seconds())
    if dashboard_age < -90:
        freshness_state = "future_timestamp_error"
    elif dashboard_age <= refresh_seconds * 3:
        freshness_state = "fresh"
    else:
        freshness_state = "stale"
    if status == "美股常规交易时段":
        runtime_status = f"交易时段自动运行中，每 {refresh_seconds} 秒刷新报价，5m 收盘更新信号。"
    elif status == "盘前":
        runtime_status = f"盘前异动监控中，每 {refresh_seconds} 秒刷新只读报价；正式信号仍等常规交易时段确认。"
    elif status == "盘后":
        runtime_status = f"盘后异动监控中，每 {refresh_seconds} 秒刷新只读报价；正式信号不在夜盘确认。"
    else:
        runtime_status = "非交易时段快照，当前不会生成新正式交易。"
    supervisor_path = config.output_dir / "m12_47_session_supervisor_status.json"
    session_liveness = "unknown"
    supervisor_process_alive = "unknown"
    last_heartbeat_at_utc = ""
    last_heartbeat_beijing_time = ""
    heartbeat_age_seconds = ""
    stale_after_seconds = str(refresh_seconds * 3)
    if supervisor_path.exists():
        supervisor = load_json(supervisor_path)
        last_heartbeat_at_utc = supervisor.get("supervisor_generated_at", "")
        last_heartbeat_beijing_time = supervisor.get("beijing_time", "")
        supervisor_alive = supervisor_pid_alive(supervisor)
        supervisor_process_alive = str(supervisor_alive).lower()
        child_running = bool(supervisor.get("child_running"))
        supervisor_market_status = supervisor.get("market_status", "")
        if last_heartbeat_at_utc:
            try:
                heartbeat_dt = datetime.fromisoformat(last_heartbeat_at_utc.replace("Z", "+00:00"))
                heartbeat_age = int((now_dt - heartbeat_dt).total_seconds())
                heartbeat_age_seconds = str(max(heartbeat_age, 0))
                if not supervisor_alive:
                    session_liveness = "stopped"
                elif child_running and heartbeat_age <= refresh_seconds * 3:
                    session_liveness = "alive"
                elif child_running:
                    session_liveness = "stale"
                elif supervisor_market_status in {"等待开盘前预热", "等待下一交易日", "非交易日等待"}:
                    session_liveness = "idle"
                else:
                    session_liveness = "stopped"
            except ValueError:
                session_liveness = "unknown"
        elif child_running:
            session_liveness = "alive"
    return {
        "generated_at_utc": summary["generated_at"],
        "wall_clock_beijing_time": now_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "dashboard_age_seconds": str(dashboard_age),
        "freshness_state": freshness_state,
        "beijing_time": market["beijing_time"],
        "new_york_time": market["new_york_time"],
        "market_status": status,
        "runtime_status": runtime_status,
        "session_liveness": session_liveness,
        "supervisor_process_alive": supervisor_process_alive,
        "last_heartbeat_at_utc": last_heartbeat_at_utc,
        "last_heartbeat_beijing_time": last_heartbeat_beijing_time,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "stale_after_seconds": stale_after_seconds,
    }


def supervisor_pid_alive(supervisor: dict[str, Any]) -> bool:
    try:
        pid = int(supervisor.get("supervisor_pid") or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def build_accountized_run_status(config: M1229Config, runtime: dict[str, Any]) -> dict[str, Any]:
    registry = runtime["state"]["trading_day_registry"]
    observed_days = sum(1 for value in registry.values() if value.get("counted"))
    return {
        "schema_version": "m12.46.trading-day-registry.v1",
        "stage": "M12.46.trading_day_registry",
        "observed_trading_days": observed_days,
        "required_trading_days": config.min_observation_days_for_trial,
        "ready_for_m11_8_review": observed_days >= config.min_observation_days_for_trial,
        "daily_realtime_strategy_ids": runtime_strategy_ids_from_specs("mainline"),
        "experimental_strategy_ids": runtime_strategy_ids_from_specs("experimental"),
        "plain_language_result": (
            "主线和实验账户已按纽约交易日累计。"
            if observed_days >= config.min_observation_days_for_trial else
            "主线和实验账户已经开始按交易日累计，但还没满 10 个纽约真实交易日。"
        ),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_accountized_gate_recheck(config: M1229Config, summary: dict[str, Any], run_status: dict[str, Any]) -> dict[str, Any]:
    ready = run_status["ready_for_m11_8_review"] and summary["current_day_scan_complete"]
    return {
        "schema_version": "m11.8.paper-trial-gate.v1",
        "stage": "M11.8.paper_trial_gate_recheck",
        "paper_trial_approval": ready,
        "plain_language_result": (
            "主线账户和实验账户都已累计足够交易日，可以进入模拟交易试运行复查。"
            if ready else
            "当前已经是账户化实时测试，但还没满 10 个纽约真实交易日，先继续累计。"
        ),
        "candidate_strategy_ids": runtime_strategy_ids_from_specs("mainline"),
        "blocking_items": [] if ready else ["连续纽约真实交易日不足 10 天", "仍需继续验证主线/实验账户的每日稳定入账"],
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": ready,
    }


def runtime_strategy_ids_from_specs(lane: str) -> list[str]:
    seen: list[str] = []
    for spec in ACCOUNT_SPECS:
        if spec["lane"] != lane:
            continue
        if spec["strategy_id"] not in seen:
            seen.append(spec["strategy_id"])
    return seen


def append_rows_to_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_iso_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def build_summary(
    config: M1229Config,
    generated_at: str,
    market: dict[str, str],
    scan_date: date,
    source_summary: dict[str, Any],
    cache_summary: dict[str, Any],
    quote_manifest: dict[str, Any],
    candidates: list[dict[str, str]],
    trade_rows: list[dict[str, str]],
    pa004_rows: list[dict[str, str]],
) -> dict[str, Any]:
    current_rows = [row for row in trade_rows if row["is_current_scan_date"] == "true"]
    old_rows = [row for row in trade_rows if row["is_current_scan_date"] != "true"]
    pnl = sum((money_to_decimal(row["simulated_intraday_pnl"]) for row in trade_rows), ZERO)
    pa004_pnl = sum((money_to_decimal(row["simulated_intraday_pnl"]) for row in pa004_rows if row["simulated_intraday_pnl"] != "暂无"), ZERO)
    current_day_complete = cache_summary["daily_ready_symbols"] == config.first_batch_size and cache_summary["current_5m_ready_symbols"] == config.first_batch_size
    warning = "" if not old_rows else "仍存在旧日期候选，不能把旧候选当作今日新扫描机会。"
    return {
        "schema_version": "m12.29.current-day-scan-summary.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "market_session": market,
        "scan_date": scan_date.isoformat(),
        "plain_language_result": "已把 50 只股票滚动到当前美股交易日扫描，并生成分钟级只读模拟看板输入。",
        "source_m12_12_summary_ref": project_path(config.output_dir / "m12_12_current_day_source" / "m12_12_loop_summary.json"),
        "source_m12_12_candidate_count": source_summary["daily_loop"]["candidate_count"],
        "quote_source": quote_manifest["quote_source"],
        "quote_count": quote_manifest["quote_count"],
        "first50_daily_ready_symbols": cache_summary["daily_ready_symbols"],
        "first50_current_5m_ready_symbols": cache_summary["current_5m_ready_symbols"],
        "current_day_scan_complete": current_day_complete,
        "today_candidate_count": len(current_rows),
        "old_candidate_count": len(old_rows),
        "pa004_long_observation_count": len(pa004_rows),
        "visible_opportunity_count": len(trade_rows) + len(pa004_rows),
        "mainline_simulated_pnl": money(pnl),
        "pa004_long_simulated_pnl": money(pa004_pnl),
        "total_simulated_pnl": money(pnl + pa004_pnl),
        "total_simulated_return_percent": pct((pnl + pa004_pnl) / DEFAULT_EQUITY * HUNDRED),
        "positive_opportunity_percent": positive_percent(trade_rows + pa004_rows),
        "strategy_hit_distribution": dict(Counter(row["strategy_id"] for row in current_rows)),
        "candidate_date_warning": warning,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_dashboard_payload(config: M1229Config, generated_at: str, summary: dict[str, Any], trade_rows: list[dict[str, str]], pa004_rows: list[dict[str, str]], closure_rows: list[dict[str, str]], visual_rows: list[dict[str, str]]) -> dict[str, Any]:
    all_rows = trade_rows + pa004_rows
    strategy_scorecards = build_strategy_scorecards(all_rows, closure_rows)
    shared_account = build_shared_account_view(summary, all_rows, strategy_scorecards)
    strategy_detail_views = build_strategy_detail_views(all_rows, strategy_scorecards)
    observation_test_lane = build_observation_test_lane(strategy_scorecards, strategy_detail_views)
    timeframe_views = build_timeframe_views(all_rows, strategy_scorecards)
    ftd001_monitor = build_ftd001_monitor(strategy_scorecards, strategy_detail_views)
    codex_observer = build_codex_observer(config, summary, shared_account, timeframe_views, ftd001_monitor, observation_test_lane)
    return {
        "schema_version": "m12.35.timeframe-readonly-dashboard.v1",
        "stage": "M12.35.timeframe_readonly_dashboard",
        "generated_at": generated_at,
        "title": "分钟级只读模拟看板",
        "refresh_seconds": config.dashboard_refresh_seconds,
        "top_metrics": {
            "模拟账户权益": shared_account["current_equity"],
            "今日新机会": summary["today_candidate_count"],
            "盘中模拟盈亏": summary["total_simulated_pnl"],
            "模拟收益率": summary["total_simulated_return_percent"],
            "浮盈机会占比": summary["positive_opportunity_percent"],
            "最大回撤参考": dashboard_drawdown_reference(closure_rows),
            "策略可用数": shared_account["strategy_count_daily_test"],
            "FTD001 状态": ftd001_monitor["current_plain_status"],
        },
        "dashboard_layout": {
            "home": "共享模拟账户总览",
            "timeframe_views": "按周期分组测试",
            "ftd001_focus": "FTD001 重点观察",
            "strategy_scorecard": "单策略独立成绩",
            "today_trade_view": "今日机会明细",
            "single_strategy_detail": "单策略复盘入口",
        },
        "shared_account_view": shared_account,
        "strategy_scorecard_rows": strategy_scorecards,
        "strategy_detail_views": strategy_detail_views,
        "observation_test_lane": observation_test_lane,
        "timeframe_views": timeframe_views,
        "ftd001_monitor": ftd001_monitor,
        "codex_observer": codex_observer,
        "summary": summary,
        "trade_rows": trade_rows,
        "pa004_long_rows": pa004_rows,
        "strategy_status_rows": closure_rows,
        "visual_definition_rows": visual_rows,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_shared_account_view(summary: dict[str, Any], rows: list[dict[str, str]], scorecards: list[dict[str, str]]) -> dict[str, Any]:
    day_pnl = money_to_decimal(summary["total_simulated_pnl"])
    equity = DEFAULT_EQUITY + day_pnl
    active_rows = [row for row in rows if row.get("simulated_intraday_pnl") not in ("", "暂无", None)]
    positive_rows = [row for row in active_rows if money_to_decimal(row["simulated_intraday_pnl"]) > ZERO]
    negative_rows = [row for row in active_rows if money_to_decimal(row["simulated_intraday_pnl"]) < ZERO]
    paused_or_non_trigger = [
        row for row in scorecards
        if row["current_status"] not in {"每日测试", "观察"}
    ]
    return {
        "account_name": "共享模拟账户",
        "account_purpose": "像一个真实模拟账户一样，把所有可用策略合并看总盈亏；不代表真实资金。",
        "starting_capital": money(DEFAULT_EQUITY),
        "current_equity": money(equity),
        "day_simulated_pnl": money(day_pnl),
        "day_simulated_return_percent": pct(day_pnl / DEFAULT_EQUITY * HUNDRED),
        "visible_opportunity_count": len(rows),
        "today_candidate_count": summary["today_candidate_count"],
        "floating_profit_count": len(positive_rows),
        "floating_loss_count": len(negative_rows),
        "floating_positive_percent": positive_percent(rows),
        "strategy_count_daily_test": sum(1 for row in scorecards if row["current_status"] == "每日测试"),
        "strategy_count_observation": sum(1 for row in scorecards if row["current_status"] == "观察"),
        "strategy_count_paused_or_non_trigger": len(paused_or_non_trigger),
        "risk_budget_per_opportunity": money(DEFAULT_RISK_BUDGET),
        "theoretical_risk_budget_if_all_opportunities_active": money(DEFAULT_RISK_BUDGET * Decimal(len(rows))),
        "plain_language_note": "首页按共享模拟账户展示，方便你盘中先看总盈亏；策略成绩表仍按单策略独立统计，方便判断哪条策略好坏。",
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_strategy_scorecards(rows: list[dict[str, str]], closure_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["strategy_id"], []).append(row)
    closure_by_id = {row["strategy_id"]: row for row in closure_rows}
    strategy_ids = [
        row["strategy_id"] for row in closure_rows
        if (row["daily_realtime_test"] == "true" or row["observation_queue"] == "true")
        and not row["strategy_id"].startswith("M12-SRC-")
    ]
    cards: list[dict[str, str]] = []
    for strategy_id in strategy_ids:
        closure = closure_by_id[strategy_id]
        strategy_rows = grouped.get(strategy_id, [])
        pnl = sum((money_to_decimal(row.get("simulated_intraday_pnl", "")) for row in strategy_rows), ZERO)
        active = [row for row in strategy_rows if row.get("simulated_intraday_pnl") not in ("", "暂无", None)]
        symbols = sorted({row["symbol"] for row in strategy_rows})
        status = "每日测试" if closure["daily_realtime_test"] == "true" else "观察"
        cards.append(
            {
                "strategy_id": strategy_id,
                "strategy_title": closure["strategy_title"],
                "current_status": status,
                "today_opportunity_count": str(len(strategy_rows)),
                "unique_symbol_count": str(len(symbols)),
                "simulated_pnl_today": money(pnl),
                "simulated_return_today_percent": pct(pnl / DEFAULT_EQUITY * HUNDRED),
                "floating_positive_percent": positive_percent(strategy_rows),
                "historical_return_percent": closure.get("return_percent", ""),
                "historical_win_rate_percent": closure.get("win_rate_percent", ""),
                "historical_max_drawdown_percent": closure.get("max_drawdown_percent", ""),
                "historical_trade_count": closure.get("trade_count", ""),
                "historical_initial_capital": closure.get("historical_initial_capital", ""),
                "historical_final_equity": closure.get("historical_final_equity", ""),
                "historical_net_profit": closure.get("historical_net_profit", ""),
                "historical_profit_factor": closure.get("historical_profit_factor", ""),
                "historical_average_holding_bars": closure.get("historical_average_holding_bars", ""),
                "historical_best_symbol": closure.get("historical_best_symbol", ""),
                "historical_worst_symbol": closure.get("historical_worst_symbol", ""),
                "historical_best_timeframe": closure.get("historical_best_timeframe", ""),
                "historical_worst_timeframe": closure.get("historical_worst_timeframe", ""),
                "average_simulated_pnl_per_opportunity": money(pnl / Decimal(len(active))) if active else "0.00",
                "top_symbols": ", ".join(symbols[:8]),
                "plain_next_action": closure["plain_reason"],
                "paper_trial_candidate_now": "false",
            }
        )
    cards.sort(key=lambda row: (0 if row["current_status"] == "每日测试" else 1, -money_to_decimal(row["simulated_pnl_today"])))
    return cards


def build_strategy_detail_views(rows: list[dict[str, str]], scorecards: list[dict[str, str]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["strategy_id"], []).append(row)
    details: dict[str, Any] = {}
    for card in scorecards:
        strategy_id = card["strategy_id"]
        opportunity_rows = grouped.get(strategy_id, [])
        symbol_pnl = aggregate_pnl(opportunity_rows, "symbol")
        timeframe_pnl = aggregate_pnl(opportunity_rows, "timeframe")
        bucket_counts = Counter(row.get("bucket", "") for row in opportunity_rows)
        timeframe_counts = Counter(row.get("timeframe", "") for row in opportunity_rows)
        details[strategy_id] = {
            "summary": {
                "strategy_id": strategy_id,
                "strategy_title": card["strategy_title"],
                "current_status": card["current_status"],
                "today_opportunity_count": card["today_opportunity_count"],
                "unique_symbol_count": card["unique_symbol_count"],
                "today_simulated_pnl": card["simulated_pnl_today"],
                "positive_opportunity_percent": card["floating_positive_percent"],
                "top_symbol_today": best_key_by_pnl(symbol_pnl, reverse=True),
                "worst_symbol_today": best_key_by_pnl(symbol_pnl, reverse=False),
                "timeframe_breakdown": dict(sorted(timeframe_counts.items())),
                "bucket_breakdown": dict(sorted(bucket_counts.items())),
                "historical_return_percent": card["historical_return_percent"],
                "historical_win_rate_percent": card["historical_win_rate_percent"],
                "historical_max_drawdown_percent": card["historical_max_drawdown_percent"],
                "historical_trade_count": card["historical_trade_count"],
                "historical_profit_factor": card["historical_profit_factor"],
                "historical_net_profit": card["historical_net_profit"],
                "historical_final_equity": card["historical_final_equity"],
                "historical_best_symbol": card["historical_best_symbol"],
                "historical_worst_symbol": card["historical_worst_symbol"],
                "historical_best_timeframe": card["historical_best_timeframe"],
                "historical_worst_timeframe": card["historical_worst_timeframe"],
                "today_pnl_by_timeframe": {key: money(value) for key, value in sorted(timeframe_pnl.items())},
                "plain_next_action": card["plain_next_action"],
                "paper_trial_candidate_now": "false",
            },
            "opportunity_rows": opportunity_rows,
        }
    return details


def build_observation_test_lane(scorecards: list[dict[str, str]], detail_views: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for card in scorecards:
        if card["current_status"] != "观察":
            continue
        detail = detail_views.get(card["strategy_id"], {})
        events = detail.get("opportunity_rows", [])
        has_event = len(events) > 0
        rows.append(
            {
                "strategy_id": card["strategy_id"],
                "strategy_title": card["strategy_title"],
                "test_lane": "低准入每日观察测试",
                "today_opportunity_count": card["today_opportunity_count"],
                "unique_symbol_count": card["unique_symbol_count"],
                "today_simulated_pnl": card["simulated_pnl_today"],
                "positive_opportunity_percent": card["floating_positive_percent"],
                "historical_return_percent": card["historical_return_percent"],
                "historical_win_rate_percent": card["historical_win_rate_percent"],
                "historical_max_drawdown_percent": card["historical_max_drawdown_percent"],
                "timeframes_today": ", ".join(sorted({row.get("timeframe", "") for row in events if row.get("timeframe")})),
                "symbols_today": card["top_symbols"],
                "daily_result_plain": (
                    "今日有触发，已进入只读模拟盈亏统计。"
                    if has_event else
                    "今日没有触发，这也是观察结果；继续等待符合定义的机会。"
                ),
                "upgrade_or_downgrade_hint": observation_hint(card, has_event),
                "paper_trial_candidate_now": "false",
            }
        )
    return {
        "schema_version": "m12.34.observation-test-lane.v1",
        "stage": "M12.34.observation_strategy_test_lane",
        "plain_language_result": "观察策略已进入每日只读测试链路；没有触发时也记录为当日观察结果，不再只是挂状态。",
        "rows": rows,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def observation_hint(card: dict[str, str], has_event: bool) -> str:
    if card["strategy_id"] == "M10-PA-004":
        return "只做多版继续观察；做空版暂停，不单独展示成一条割裂策略。"
    if not has_event:
        return "继续自动观察，等真实触发样本积累后再决定升级或降级。"
    pnl = money_to_decimal(card["simulated_pnl_today"])
    if pnl > ZERO:
        return "今日样本暂时为正，继续观察，不直接升级。"
    if pnl < ZERO:
        return "今日样本暂时为负，继续看是否连续偏弱。"
    return "今日触发但盈亏接近持平，继续观察。"


def build_timeframe_views(rows: list[dict[str, str]], scorecards: list[dict[str, str]]) -> dict[str, Any]:
    status_by_strategy = {card["strategy_id"]: card["current_status"] for card in scorecards}
    title_by_strategy = {card["strategy_id"]: card["strategy_title"] for card in scorecards}
    views: dict[str, Any] = {}
    for timeframe in TIMEFRAME_ORDER:
        tf_rows = [row for row in rows if row.get("timeframe") == timeframe]
        strategy_ids = sorted({row["strategy_id"] for row in tf_rows})
        mainline_rows = [row for row in tf_rows if status_by_strategy.get(row["strategy_id"]) == "每日测试"]
        observation_rows = [row for row in tf_rows if status_by_strategy.get(row["strategy_id"]) == "观察"]
        pnl = sum((money_to_decimal(row.get("simulated_intraday_pnl", "")) for row in tf_rows), ZERO)
        symbol_counts = Counter(row["symbol"] for row in tf_rows)
        strategy_rows: list[dict[str, str]] = []
        for strategy_id in strategy_ids:
            strategy_tf_rows = [row for row in tf_rows if row["strategy_id"] == strategy_id]
            strategy_pnl = sum((money_to_decimal(row.get("simulated_intraday_pnl", "")) for row in strategy_tf_rows), ZERO)
            strategy_rows.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_title": title_by_strategy.get(strategy_id, strategy_id),
                    "status": status_by_strategy.get(strategy_id, ""),
                    "opportunity_count": str(len(strategy_tf_rows)),
                    "simulated_pnl": money(strategy_pnl),
                    "positive_opportunity_percent": positive_percent(strategy_tf_rows),
                    "symbols": ", ".join(sorted({row["symbol"] for row in strategy_tf_rows})[:12]),
                }
            )
        views[timeframe] = {
            "timeframe": timeframe,
            "display_name": TIMEFRAME_LABELS[timeframe],
            "opportunity_count": len(tf_rows),
            "mainline_opportunity_count": len(mainline_rows),
            "observation_opportunity_count": len(observation_rows),
            "simulated_pnl": money(pnl),
            "simulated_return_percent": pct(pnl / DEFAULT_EQUITY * HUNDRED),
            "positive_opportunity_percent": positive_percent(tf_rows),
            "strategy_count": len(strategy_ids),
            "top_symbols": [symbol for symbol, _ in symbol_counts.most_common(12)],
            "active_strategy_ids": strategy_ids,
            "strategy_rows": strategy_rows,
            "opportunity_rows": tf_rows,
            "plain_language_note": timeframe_note(timeframe, tf_rows),
        }
    return {
        "schema_version": "m12.35.timeframe-views.v1",
        "stage": "M12.35.timeframe_grouped_dashboard",
        "timeframe_order": list(TIMEFRAME_ORDER),
        "views": views,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def timeframe_note(timeframe: str, rows: list[dict[str, str]]) -> str:
    if timeframe == "1d":
        return "日线只在收盘后确认新信号；盘中只更新当前价和模拟盈亏。"
    if timeframe in {"1h", "15m", "5m"}:
        return f"{TIMEFRAME_LABELS[timeframe]}只在对应 K 线收盘后更新正式信号，盘中波动不当作新信号。"
    return "按对应周期收盘确认。"


def build_ftd001_monitor(scorecards: list[dict[str, str]], detail_views: dict[str, Any]) -> dict[str, Any]:
    card = next((row for row in scorecards if row["strategy_id"] == "M12-FTD-001"), None)
    detail = detail_views.get("M12-FTD-001", {})
    rows = detail.get("opportunity_rows", [])
    today_pnl = money_to_decimal(card["simulated_pnl_today"]) if card else ZERO
    historical_drawdown = decimal_or_none(card.get("historical_max_drawdown_percent", "")) if card else None
    historical_profit_factor = decimal_or_none(card.get("historical_profit_factor", "")) if card else None
    risk_flags: list[str] = []
    if historical_drawdown is not None and historical_drawdown >= Decimal("40"):
        risk_flags.append("历史最大回撤高")
    if historical_profit_factor is not None and historical_profit_factor <= Decimal("1.10"):
        risk_flags.append("盈利因子偏薄")
    if today_pnl < ZERO:
        risk_flags.append("今日暂时亏损")
    if len(rows) > 10:
        risk_flags.append("触发过密")
    if len({row["symbol"] for row in rows}) <= 2 and rows:
        risk_flags.append("信号集中度偏高")
    if not risk_flags:
        risk_flags.append("继续观察")
    return {
        "schema_version": "m12.36.ftd001-monitor.v1",
        "stage": "M12.36.ftd001_focus_monitor",
        "strategy_id": "M12-FTD-001",
        "strategy_title": card["strategy_title"] if card else "方方土日线趋势顺势信号K",
        "current_status": card["current_status"] if card else "每日测试",
        "historical_return_percent": card["historical_return_percent"] if card else "",
        "historical_win_rate_percent": card["historical_win_rate_percent"] if card else "",
        "historical_max_drawdown_percent": card["historical_max_drawdown_percent"] if card else "",
        "historical_profit_factor": card["historical_profit_factor"] if card else "",
        "today_opportunity_count": len(rows),
        "today_symbols": sorted({row["symbol"] for row in rows}),
        "today_timeframes": sorted({row["timeframe"] for row in rows}),
        "today_simulated_pnl": money(today_pnl),
        "today_positive_opportunity_percent": positive_percent(rows),
        "current_consecutive_loss_proxy": consecutive_loss_proxy(rows),
        "risk_flags": risk_flags,
        "drawdown_watch": "true" if "历史最大回撤高" in risk_flags else "false",
        "current_plain_status": f"FTD001：{risk_flags[0]}",
        "plain_language_summary": build_ftd_plain_summary(card, rows, today_pnl, risk_flags),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def consecutive_loss_proxy(rows: list[dict[str, str]]) -> int:
    streak = 0
    for row in sorted(rows, key=lambda item: item.get("signal_time", ""), reverse=True):
        if money_to_decimal(row.get("simulated_intraday_pnl", "")) < ZERO:
            streak += 1
            continue
        break
    return streak


def build_ftd_plain_summary(card: dict[str, str] | None, rows: list[dict[str, str]], today_pnl: Decimal, risk_flags: list[str]) -> str:
    if card is None:
        return "FTD001 暂无成绩卡，不能解读。"
    direction = "盈利" if today_pnl > ZERO else "亏损" if today_pnl < ZERO else "持平"
    symbols = ", ".join(sorted({row["symbol"] for row in rows})[:8]) or "暂无"
    return (
        f"FTD001 历史收益 {card['historical_return_percent']}%，胜率 {card['historical_win_rate_percent']}%，"
        f"最大回撤 {card['historical_max_drawdown_percent']}%。今天触发 {len(rows)} 条，股票：{symbols}，"
        f"当前模拟{direction} {money(today_pnl)}。重点风险：{'，'.join(risk_flags)}。"
    )


def build_codex_observer(
    config: M1229Config,
    summary: dict[str, Any],
    shared_account: dict[str, Any],
    timeframe_views: dict[str, Any],
    ftd001_monitor: dict[str, Any],
    observation_test_lane: dict[str, Any],
) -> dict[str, Any]:
    active_timeframes = [
        view["display_name"] for view in timeframe_views["views"].values()
        if view["opportunity_count"] > 0
    ]
    alerts = observer_alerts(summary, shared_account, ftd001_monitor, observation_test_lane)
    plain_summary = (
        f"当前模拟权益 {shared_account['current_equity']}，今日模拟盈亏 {shared_account['day_simulated_pnl']}，"
        f"今日机会 {shared_account['visible_opportunity_count']} 条。活跃周期：{', '.join(active_timeframes) or '暂无'}。"
        f"{ftd001_monitor['plain_language_summary']}"
    )
    return {
        "schema_version": "m12.38.codex-observer.v1",
        "stage": "M12.38.codex_observer",
        "generated_at": summary["generated_at"],
        "observer_mode": "codex_heartbeat_or_file_inbox",
        "observer_interval_minutes": 15,
        "dashboard_refresh_seconds": config.dashboard_refresh_seconds,
        "market_session": summary["market_session"],
        "plain_language_summary": plain_summary,
        "active_timeframes": active_timeframes,
        "alerts": alerts,
        "recommended_codex_message": build_recommended_codex_message(summary, shared_account, ftd001_monitor, alerts),
        "latest_dashboard_json": project_path(config.output_dir / "m12_32_minute_readonly_dashboard_data.json"),
        "latest_dashboard_html": project_path(config.output_dir / "m12_32_minute_readonly_dashboard.html"),
        "observer_inbox": project_path(config.output_dir / "m12_38_codex_observer_inbox.jsonl"),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def observer_alerts(summary: dict[str, Any], shared_account: dict[str, Any], ftd001_monitor: dict[str, Any], observation_test_lane: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    if money_to_decimal(shared_account["day_simulated_pnl"]) < ZERO:
        alerts.append({"level": "注意", "message": "今日总模拟盈亏暂时为负，需要看是否集中在单一策略或周期。"})
    if ftd001_monitor["risk_flags"] and ftd001_monitor["risk_flags"] != ["继续观察"]:
        alerts.append({"level": "重点", "message": "FTD001 触发风险观察：" + "，".join(ftd001_monitor["risk_flags"])})
    if summary["candidate_date_warning"]:
        alerts.append({"level": "数据", "message": summary["candidate_date_warning"]})
    if not summary["current_day_scan_complete"]:
        alerts.append({"level": "数据", "message": "第一批 50 只股票当日数据未全部可用。"})
    observed_with_events = [row["strategy_id"] for row in observation_test_lane["rows"] if row["today_opportunity_count"] != "0"]
    if observed_with_events:
        alerts.append({"level": "观察策略", "message": "观察策略今日已有触发：" + "，".join(observed_with_events)})
    if not alerts:
        alerts.append({"level": "正常", "message": "当前没有明显数据异常或重点风险。"})
    return alerts


def build_recommended_codex_message(summary: dict[str, Any], shared_account: dict[str, Any], ftd001_monitor: dict[str, Any], alerts: list[dict[str, str]]) -> str:
    alert_text = "；".join(f"{row['level']}：{row['message']}" for row in alerts)
    return (
        f"盘中观察：市场状态 {summary['market_session']['status']}，今日机会 {shared_account['visible_opportunity_count']} 条，"
        f"今日模拟盈亏 {shared_account['day_simulated_pnl']}，当前模拟权益 {shared_account['current_equity']}。"
        f"{ftd001_monitor['plain_language_summary']} 当前提醒：{alert_text}"
    )


def aggregate_pnl(rows: list[dict[str, str]], key: str) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        value = row.get(key, "")
        if not value:
            continue
        totals[value] = totals.get(value, ZERO) + money_to_decimal(row.get("simulated_intraday_pnl", ""))
    return totals


def best_key_by_pnl(values: dict[str, Decimal], *, reverse: bool) -> str:
    if not values:
        return ""
    key, value = sorted(values.items(), key=lambda item: item[1], reverse=reverse)[0]
    return f"{key} ({money(value)})"


def build_run_status(config: M1229Config, summary: dict[str, Any], closure_rows: list[dict[str, str]]) -> dict[str, Any]:
    observed_days = 1 if summary["current_day_scan_complete"] else 0
    return {
        "schema_version": "m12.33.observation-run-status.v1",
        "stage": "M12.33.observation_run_status",
        "observed_trading_days": observed_days,
        "required_trading_days": config.min_observation_days_for_trial,
        "ready_for_m11_6_review": observed_days >= config.min_observation_days_for_trial,
        "daily_realtime_strategy_ids": runtime_strategy_ids(closure_rows, "daily_realtime_test"),
        "observation_strategy_ids": runtime_strategy_ids(closure_rows, "observation_queue"),
        "plain_language_result": "今日扫描已入账，但还没有连续 10 个交易日记录，不能进入模拟交易试运行。",
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_gate_recheck(config: M1229Config, summary: dict[str, Any], run_status: dict[str, Any], closure_rows: list[dict[str, str]]) -> dict[str, Any]:
    ready = run_status["ready_for_m11_6_review"] and summary["current_day_scan_complete"]
    return {
        "schema_version": "m11.6.paper-trial-gate-recheck.v1",
        "stage": "M11.6.paper_trial_gate_recheck",
        "paper_trial_approval": ready,
        "plain_language_result": (
            "满足连续记录和数据稳定后，可以批准第一批策略进入模拟交易试运行。"
            if ready else
            "当前已能盘中扫描和看板刷新，但还没满 10 个交易日，暂不能批准模拟交易试运行。"
        ),
        "candidate_strategy_ids": runtime_strategy_ids(closure_rows, "daily_realtime_test"),
        "blocking_items": [] if ready else ["连续交易日记录不足 10 天", "仍需继续验证每日扫描稳定性"],
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": ready,
    }


def runtime_strategy_ids(closure_rows: list[dict[str, str]], flag: str) -> list[str]:
    return [
        row["strategy_id"] for row in closure_rows
        if row.get(flag) == "true" and not row["strategy_id"].startswith("M12-SRC-")
    ]


def build_report_md(summary: dict[str, Any]) -> str:
    warning = f"\n- 注意：{summary['candidate_date_warning']}" if summary["candidate_date_warning"] else ""
    return (
        "# M12.29 当日扫描报告\n\n"
        "## 用人话结论\n\n"
        f"- 扫描交易日：`{summary['scan_date']}`；市场状态：{summary['market_session']['status']}。\n"
        f"- 主线正式账户今日盈亏：`{summary['mainline_today_pnl']}`，当前权益：`{summary['mainline_current_equity']}`。\n"
        f"- 实验账户今日盈亏：`{summary['experimental_today_pnl']}`，当前权益：`{summary['experimental_current_equity']}`。\n"
        f"- 今日新信号 `{summary['today_candidate_count']}` 条，信号观察清单总数 `{summary['signal_watchlist_count']}` 条。\n"
        f"- 盘前异动 `{summary['premarket_mover_count']}` 条，盘后异动 `{summary['postmarket_mover_count']}` 条，重点关注股命中 `{summary['focus_mover_count']}` 条。\n"
        f"- 50 只股票日线可用 `{summary['first50_daily_ready_symbols']}` 只，当日 5m 可用 `{summary['first50_current_5m_ready_symbols']}` 只。{warning}\n"
        "- 这不是实盘，也不是自动买卖；只是只读行情和模拟盈亏。\n"
    )


def build_strategy_closure_md(rows: list[dict[str, str]]) -> str:
    lines = ["# M12.30 策略全量收口表", "", "| 策略 | 最终状态 | 收益% | 胜率% | 最大回撤% | 说明 |", "|---|---:|---:|---:|---:|---|"]
    for row in rows:
        lines.append(
            f"| {row['strategy_id']} {row['strategy_title']} | {row['final_status']} | {row['return_percent']} | {row['win_rate_percent']} | {row['max_drawdown_percent']} | {row['plain_reason']} |"
        )
    return "\n".join(lines) + "\n"


def build_visual_definition_md(rows: list[dict[str, str]]) -> str:
    lines = ["# M12.31 图形确认与定义修正终局", "", "| 策略 | 机器能识别 | 不能宣称 | 最终状态 |", "|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['strategy_id']} | {row['machine_can_identify']} | {row['machine_cannot_claim']} | {row['final_status']} |")
    return "\n".join(lines) + "\n"


def build_observation_test_lane_md(lane: dict[str, Any]) -> str:
    lines = [
        "# M12.46 实验账户测试",
        "",
        "## 用人话结论",
        "",
        f"- {lane['plain_language_result']}",
        "- 实验策略也已经入账；当天没触发，会显示为零触发和零开仓，而不是空挂状态。",
        "",
        "| 账户 | 周期 | 今日开仓 | 今日平仓 | 今日盈亏 | 当前权益 | 历史收益 | 最大回撤 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in lane["rows"]:
        lines.append(
            f"| {row['display_name']} | {row['timeframe']} | {row['today_opened_count']} | {row['today_closed_count']} | {row['today_total_pnl']} | {row['equity']} | {row['historical_return_percent']}% | {row['max_drawdown_percent']}% |"
        )
    return "\n".join(lines) + "\n"


def build_timeframe_views_md(timeframe_views: dict[str, Any]) -> str:
    lines = [
        "# M12.35 按周期分组看板",
        "",
        "| 周期 | 账户数 | 主线账户 | 实验账户 | 今日盈亏 | 胜率 | 账户列表 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for timeframe in timeframe_views["timeframe_order"]:
        view = timeframe_views["views"][timeframe]
        lines.append(
            f"| {view['display_name']} | {view['account_count']} | {view['mainline_account_count']} | {view['experimental_account_count']} | {view['today_total_pnl']} | {view['win_rate_percent']}% | {', '.join(row['runtime_id'] for row in view['strategy_rows']) or '暂无'} |"
        )
    return "\n".join(lines) + "\n"


def build_ftd001_monitor_md(monitor: dict[str, Any]) -> str:
    baseline = next((row for row in monitor["accounts"] if row["variant_id"] == "baseline"), {})
    guard = next((row for row in monitor["accounts"] if row["variant_id"] == "loss_streak_guard"), {})
    lines = [
        "# M12.46 FTD001 双版本重点监控",
        "",
        "## 用人话结论",
        "",
        f"- {monitor['plain_language_summary']}",
        "",
        "| 版本 | 今日盈亏 | 当前权益 | 历史收益 | 胜率 | 最大回撤 |",
        "|---|---:|---:|---:|---:|---:|",
        f"| 原版 baseline | {baseline.get('today_total_pnl', '暂无')} | {baseline.get('equity', '暂无')} | {baseline.get('historical_return_percent', '')}% | {baseline.get('historical_win_rate_percent', '')}% | {baseline.get('historical_max_drawdown_percent', '')}% |",
        f"| 连亏保护 loss_streak_guard | {guard.get('today_total_pnl', '暂无')} | {guard.get('equity', '暂无')} | {guard.get('historical_return_percent', '')}% | {guard.get('historical_win_rate_percent', '')}% | {guard.get('historical_max_drawdown_percent', '')}% |",
        "",
        f"- 风险标记：{'，'.join(monitor['risk_flags'])}",
    ]
    return "\n".join(lines) + "\n"


def build_dashboard_html(config: M1229Config, dashboard: dict[str, Any]) -> str:
    metrics = dashboard["top_metrics"]
    mainline = dashboard["mainline_account_view"]
    experimental = dashboard["experimental_account_view"]
    timeframe_views = dashboard["timeframe_views"]["views"]
    ftd = dashboard["ftd001_monitor"]
    update_status = dashboard["update_status"]
    cards = "\n".join(
        f"<section class=\"metric\"><span>{html.escape(k)}</span><strong>{html.escape(str(v))}</strong></section>"
        for k, v in metrics.items()
    )
    mainline_rows = "\n".join(
        f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(value))}</td></tr>"
        for label, value in [
            ("总起始本金", mainline["starting_capital"]),
            ("当前主线权益", mainline["current_equity"]),
            ("主线今日盈亏", mainline["day_pnl"]),
            ("主线累计收益", mainline["cumulative_return_percent"] + "%"),
            ("今日新开仓", mainline["today_opened_count"]),
            ("今日已平仓", mainline["today_closed_count"]),
            ("当前胜率", mainline["win_rate_percent"] + "%"),
            ("当前最大回撤", mainline["max_drawdown_percent"] + "%"),
        ]
    )
    experimental_rows = "\n".join(
        f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(value))}</td></tr>"
        for label, value in [
            ("总起始本金", experimental["starting_capital"]),
            ("当前实验权益", experimental["current_equity"]),
            ("实验今日盈亏", experimental["day_pnl"]),
            ("实验累计收益", experimental["cumulative_return_percent"] + "%"),
            ("今日新开仓", experimental["today_opened_count"]),
            ("今日已平仓", experimental["today_closed_count"]),
            ("当前胜率", experimental["win_rate_percent"] + "%"),
            ("当前最大回撤", experimental["max_drawdown_percent"] + "%"),
        ]
    )
    strategy_scorecard_rows = "\n".join(strategy_scorecard_html(row) for row in dashboard["strategy_scorecard_rows"])
    pnl_bars = "\n".join(strategy_pnl_bar_html(row) for row in dashboard["strategy_scorecard_rows"])
    strategy_detail_rows = "\n".join(strategy_detail_summary_html(view["summary"]) for view in dashboard["strategy_detail_views"].values())
    today_rows = "\n".join(trade_row_html(row) for row in dashboard["trade_rows"][:220])
    watch_rows = "\n".join(signal_watchlist_html(row) for row in dashboard["signal_watchlist"][:220])
    reference_rows = "\n".join(signal_watchlist_html(row) for row in dashboard["reference_watchlist"][:80])
    timeframe_sections = "\n".join(timeframe_view_html(timeframe_views[timeframe]) for timeframe in PRIMARY_TIMEFRAME_ORDER)
    ftd_rows = "".join(ftd_account_row_html(row) for row in ftd["accounts"])
    extended_monitor = dashboard["extended_session_monitor"]
    premarket_rows = "\n".join(extended_session_row_html(row) for row in extended_monitor["premarket_rows"])
    postmarket_rows = "\n".join(extended_session_row_html(row) for row in extended_monitor["postmarket_rows"])
    focus_rows = "\n".join(extended_session_row_html(row) for row in extended_monitor["focus_hits"])
    status_rows = "\n".join(
        f"<tr><td>{html.escape(row['strategy_id'])}</td><td>{html.escape(row['strategy_title'])}</td><td>{html.escape(row['final_status'])}</td><td>{html.escape(row['plain_reason'])}</td></tr>"
        for row in dashboard["strategy_status_rows"]
    )
    supporting_rows = "\n".join(
        f"<tr><td>{html.escape(row['supporting_rule_id'])}</td><td>{html.escape(row['display_name'])}</td><td>{html.escape(row['mode'])}</td><td>{html.escape(row['status'])}</td><td>{html.escape(row['plain_reason'])}</td></tr>"
        for row in dashboard["supporting_rule_ab_results"]["rows"]
    )
    audit_rows = "\n".join(
        f"<tr><td>{html.escape(row['runtime_id'])}</td><td>{html.escape(row['input_source_type'])}</td><td>{html.escape(row['today_formal_signal_count'])}</td><td>{html.escape(row['source_row_count'])}</td><td>{html.escape(row['plain_language_result'])}</td></tr>"
        for row in dashboard["account_input_audit"]["rows"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{config.dashboard_refresh_seconds}">
  <title>M12.46 分钟级只读模拟账户看板</title>
  <style>
    body {{ margin:0; font-family:Arial,"Noto Sans SC",sans-serif; background:#f6f7f9; color:#1f2933; letter-spacing:0; }}
    header {{ padding:18px 22px; background:#fff; border-bottom:1px solid #d8dee9; display:flex; justify-content:space-between; gap:18px; }}
    h1 {{ margin:0; font-size:24px; }} main {{ padding:18px 22px; display:grid; gap:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(6,minmax(120px,1fr)); gap:10px; }}
    .metric,.panel {{ background:#fff; border:1px solid #d8dee9; border-radius:8px; }}
    .metric {{ padding:12px; }} .metric span {{ display:block; color:#667085; font-size:12px; }} .metric strong {{ display:block; margin-top:8px; font-size:22px; }}
    h2 {{ margin:0; padding:14px 16px; font-size:18px; border-bottom:1px solid #d8dee9; }}
    .note {{ padding:12px 16px; color:#667085; line-height:1.6; }}
    .two-col {{ display:grid; grid-template-columns:minmax(280px,0.9fr) minmax(320px,1.1fr); gap:14px; padding:14px 16px; }}
    .mini-card {{ border:1px solid #e5e7eb; border-radius:8px; overflow:hidden; background:#fff; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }} th,td {{ padding:9px 10px; border-bottom:1px solid #e5e7eb; text-align:left; vertical-align:top; }}
    th {{ background:#eef2f7; }} .wrap {{ max-height:520px; overflow:auto; }}
    .good {{ color:#18794e; font-weight:700; }} .bad {{ color:#b42318; font-weight:700; }}
    .timeframes {{ display:grid; grid-template-columns:repeat(2,minmax(260px,1fr)); gap:14px; padding:14px 16px; }}
    .timeframe-card {{ border:1px solid #d8dee9; border-radius:8px; background:#fff; overflow:hidden; }}
    .timeframe-card h3 {{ margin:0; padding:12px 14px; background:#f2f4f7; font-size:16px; }}
    .timeframe-card .stats {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; padding:10px 14px; }}
    .timeframe-card .stats div {{ border:1px solid #eef2f7; border-radius:6px; padding:8px; }}
    .bar-row {{ display:grid; grid-template-columns:150px 1fr 86px; align-items:center; gap:8px; padding:8px 10px; border-bottom:1px solid #eef2f7; font-size:13px; }}
    .bar-track {{ height:12px; background:#eef2f7; border-radius:999px; overflow:hidden; }}
    .bar-fill {{ height:12px; min-width:2px; }}
    .bar-good {{ background:#2f9e6b; }} .bar-bad {{ background:#d92d20; }}
    @media (max-width:980px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} header,.two-col,.timeframes {{ display:block; }} }}
  </style>
</head>
<body>
  <header><div><h1>分钟级只读模拟账户看板</h1><div>北京时间最后更新：{html.escape(update_status['beijing_time'])}</div><div>当前电脑时间：{html.escape(update_status['wall_clock_beijing_time'])} ｜ 看板新鲜度：{html.escape(update_status['freshness_state'])} ｜ 看板延迟秒数：{html.escape(update_status['dashboard_age_seconds'])}</div><div>纽约时间：{html.escape(update_status['new_york_time'])} ｜ 市场状态：{html.escape(update_status['market_status'])}</div><div>运行状态：{html.escape(update_status['runtime_status'])}</div><div>自动会话：{html.escape(update_status['session_liveness'])} ｜ 守护器进程：{html.escape(update_status['supervisor_process_alive'])} ｜ 上次心跳（北京时间）：{html.escape(update_status['last_heartbeat_beijing_time'] or '暂无')} ｜ 心跳延迟秒数：{html.escape(update_status['heartbeat_age_seconds'] or '暂无')}</div></div><div>只读行情 + 模拟账户，不接真实账户，不做真实买卖</div></header>
  <main>
    <div class="grid">{cards}</div>
    <section class="panel"><h2>主线正式账户</h2><div class="note">这里只看已经进入正式账户测试的策略，不混入实验策略收益。</div><div class="two-col"><div class="mini-card"><table><tbody>{mainline_rows}</tbody></table></div><div class="mini-card"><h2>各账户今日盈亏</h2>{pnl_bars}</div></div></section>
    <section class="panel"><h2>实验账户</h2><div class="note">实验策略也已经真实入账；没触发就显示零开仓零盈亏，不再空挂。</div><div class="two-col"><div class="mini-card"><table><tbody>{experimental_rows}</tbody></table></div><div class="mini-card"><h2>挂件 A/B 位</h2><table><thead><tr><th>挂件</th><th>名称</th><th>模式</th><th>状态</th><th>说明</th></tr></thead><tbody>{supporting_rows}</tbody></table></div></div></section>
    <section class="panel"><h2>FTD001 双版本对照</h2><div class="note">{html.escape(ftd['plain_language_summary'])}</div><div class="wrap"><table><thead><tr><th>版本</th><th>今日盈亏</th><th>当前权益</th><th>历史收益</th><th>胜率</th><th>最大回撤</th></tr></thead><tbody>{ftd_rows}</tbody></table></div><div class="note">当前判断：{html.escape(ftd['current_plain_status'])}；风险标记：{html.escape('，'.join(ftd['risk_flags']))}</div></section>
    <section class="panel"><h2>盘前 / 盘后异动</h2><div class="note">{html.escape(extended_monitor['plain_language_summary'])}</div><div class="two-col"><div class="mini-card"><h2>盘前超过 {html.escape(extended_monitor['threshold_percent'])}%</h2><div class="wrap"><table><thead>{extended_session_head()}</thead><tbody>{premarket_rows}</tbody></table></div></div><div class="mini-card"><h2>盘后超过 {html.escape(extended_monitor['threshold_percent'])}%</h2><div class="wrap"><table><thead>{extended_session_head()}</thead><tbody>{postmarket_rows}</tbody></table></div></div></div><div class="wrap"><table><thead>{extended_session_head()}</thead><tbody>{focus_rows}</tbody></table></div></section>
    <section class="panel"><h2>按 1d / 5m 分组测试</h2><div class="note">当前主计划只保留 1d 与 5m。信号按各自周期收盘确认，盘中每 60 秒只刷新报价和持仓盈亏。</div><div class="timeframes">{timeframe_sections}</div></section>
    <section class="panel"><h2>账户成绩单</h2><div class="note">每条独立账户都看得到本金、权益、今日盈亏、胜率和最大回撤；主线和实验分层展示，但都真实入账。</div><div class="wrap"><table><thead>{strategy_scorecard_head()}</thead><tbody>{strategy_scorecard_rows}</tbody></table></div></section>
    <section class="panel"><h2>账户下钻</h2><div class="note">这里看每个账户的当前状态、开平仓数量、可用现金和历史参考指标。</div><div class="wrap"><table><thead>{strategy_detail_head()}</thead><tbody>{strategy_detail_rows}</tbody></table></div></section>
    <section class="panel"><h2>模拟交易明细</h2><div class="note">这里展示当前持仓和最近已平仓记录，按账户状态机推进，不再是旧的机会当前价覆盖。</div><div class="wrap"><table><thead>{table_head()}</thead><tbody>{today_rows}</tbody></table></div></section>
    <section class="panel"><h2>正式信号清单</h2><div class="note">这里只展示真正会进入账户测试的正式信号，不再把历史观察样例混进主线收益和机会统计。</div><div class="wrap"><table><thead>{watchlist_head()}</thead><tbody>{watch_rows}</tbody></table></div></section>
    <section class="panel"><h2>账户输入审计</h2><div class="note">这张表专门防止“名义上进测试、实际上还吃旧观察流”的老问题。所有进账户的策略都必须明确写清楚输入源。</div><div class="wrap"><table><thead><tr><th>账户</th><th>输入源</th><th>今日正式信号</th><th>可用正式行数</th><th>说明</th></tr></thead><tbody>{audit_rows}</tbody></table></div></section>
    <section class="panel"><h2>历史参考样例（不入账）</h2><div class="note">这里只放回看和复盘用的旧样例，不参与今日主线收益，也不会触发新开仓。</div><div class="wrap"><table><thead>{watchlist_head()}</thead><tbody>{reference_rows}</tbody></table></div></section>
    <section class="panel"><h2>策略状态</h2><div class="wrap"><table><thead><tr><th>策略</th><th>名称</th><th>状态</th><th>说明</th></tr></thead><tbody>{status_rows}</tbody></table></div></section>
  </main>
</body>
</html>
"""


def table_head() -> str:
    return "<tr><th>记录</th><th>账户</th><th>股票</th><th>周期</th><th>方向</th><th>开仓时间</th><th>入场</th><th>止损</th><th>目标</th><th>最新价/平仓价</th><th>盈亏</th><th>状态</th></tr>"


def watchlist_head() -> str:
    return "<tr><th>类别</th><th>策略</th><th>股票</th><th>周期</th><th>方向</th><th>当前价</th><th>入场</th><th>止损</th><th>目标</th><th>信号时间</th><th>说明</th></tr>"


def strategy_scorecard_head() -> str:
    return "<tr><th>账户</th><th>分层</th><th>周期</th><th>今日开仓</th><th>今日平仓</th><th>今日盈亏</th><th>当前权益</th><th>胜率</th><th>最大回撤</th><th>历史收益</th></tr>"


def timeframe_view_html(view: dict[str, Any]) -> str:
    strategy_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['runtime_id'])}</td>"
        f"<td>{html.escape('主线' if row['lane'] == 'mainline' else '实验')}</td>"
        f"<td>{html.escape(row['today_total_pnl'])}</td>"
        f"<td>{html.escape(row['equity'])}</td>"
        f"<td>{html.escape(row['win_rate_percent'])}%</td>"
        "</tr>"
        for row in view["strategy_rows"]
    )
    strategy_rows = strategy_rows or "<tr><td colspan=\"5\">暂无账户</td></tr>"
    return (
        "<section class=\"timeframe-card\">"
        f"<h3>{html.escape(view['display_name'])}</h3>"
        "<div class=\"stats\">"
        f"<div><small>账户数</small><strong>{html.escape(str(view['account_count']))}</strong></div>"
        f"<div><small>今日盈亏</small><strong>{html.escape(view['today_total_pnl'])}</strong></div>"
        f"<div><small>胜率</small><strong>{html.escape(view['win_rate_percent'])}%</strong></div>"
        "</div>"
        f"<div class=\"note\">{html.escape(view['plain_language_note'])}</div>"
        "<table><thead><tr><th>账户</th><th>分层</th><th>今日盈亏</th><th>当前权益</th><th>胜率</th></tr></thead>"
        f"<tbody>{strategy_rows}</tbody></table>"
        "</section>"
    )


def strategy_scorecard_html(row: dict[str, str]) -> str:
    pnl = row["today_total_pnl"]
    cls = "good" if money_to_decimal(pnl) > ZERO else "bad" if money_to_decimal(pnl) < ZERO else ""
    return (
        "<tr>"
        f"<td>{html.escape(row['runtime_id'])}<br><small>{html.escape(row['display_name'])}</small></td>"
        f"<td>{html.escape('主线正式账户' if row['lane'] == 'mainline' else '实验账户')}</td>"
        f"<td>{html.escape(row['timeframe'])}</td>"
        f"<td>{html.escape(row['today_opened_count'])}</td>"
        f"<td>{html.escape(row['today_closed_count'])}</td>"
        f"<td class=\"{cls}\">{html.escape(pnl)}</td>"
        f"<td>{html.escape(row['equity'])}</td>"
        f"<td>{html.escape(row['win_rate_percent'])}%</td>"
        f"<td>{html.escape(row['max_drawdown_percent'])}%</td>"
        f"<td>{html.escape(row['historical_return_percent'])}%</td>"
        "</tr>"
    )


def strategy_detail_head() -> str:
    return "<tr><th>账户</th><th>当前权益</th><th>可用现金</th><th>当前持仓</th><th>累计已平仓</th><th>今日开仓/平仓</th><th>历史净利润</th><th>历史收益/回撤</th></tr>"


def strategy_detail_summary_html(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(row['runtime_id'])}<br><small>{html.escape(row['display_name'])}</small></td>"
        f"<td>{html.escape(row['equity'])}</td>"
        f"<td>{html.escape(row['cash'])}</td>"
        f"<td>{html.escape(row['open_position_count'])}</td>"
        f"<td>{html.escape(row['closed_trade_count'])}</td>"
        f"<td>{html.escape(row['today_opened_count'])}/{html.escape(row['today_closed_count'])}</td>"
        f"<td>{html.escape(row['historical_net_profit'])}</td>"
        f"<td>{html.escape(row['historical_return_percent'])}% / {html.escape(row['historical_max_drawdown_percent'])}%</td>"
        "</tr>"
    )


def strategy_pnl_bar_html(row: dict[str, str]) -> str:
    pnl = money_to_decimal(row["today_total_pnl"])
    width = min(100, max(4, int(abs(pnl) / Decimal("250")))) if pnl != ZERO else 4
    cls = "bar-good" if pnl > ZERO else "bar-bad" if pnl < ZERO else ""
    return (
        "<div class=\"bar-row\">"
        f"<div>{html.escape(row['runtime_id'])}</div>"
        f"<div class=\"bar-track\"><div class=\"bar-fill {cls}\" style=\"width:{width}%\"></div></div>"
        f"<div>{html.escape(row['today_total_pnl'])}</div>"
        "</div>"
    )


def trade_row_html(row: dict[str, str]) -> str:
    pnl = row["pnl"]
    cls = "good" if pnl != "暂无" and money_to_decimal(pnl) > ZERO else "bad" if pnl != "暂无" and money_to_decimal(pnl) < ZERO else ""
    return (
        "<tr>"
        f"<td>{html.escape(row.get('record_type', ''))}</td><td>{html.escape(row['runtime_id'])}<br><small>{html.escape(row['display_name'])}</small></td>"
        f"<td>{html.escape(row['symbol'])}</td><td>{html.escape(row['timeframe'])}</td><td>{html.escape(row.get('direction', ''))}</td>"
        f"<td>{html.escape(row['opened_at'])}</td><td>{html.escape(row['entry_price'])}</td><td>{html.escape(row['stop_price'])}</td><td>{html.escape(row['target_price'])}</td>"
        f"<td>{html.escape(row['latest_price'])}</td><td class=\"{cls}\">{html.escape(pnl)}</td><td>{html.escape(row['state'])}</td></tr>"
    )


def signal_watchlist_html(row: dict[str, str]) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(row.get('bucket', ''))}</td><td>{html.escape(row['strategy_id'])}<br><small>{html.escape(row['strategy_title'])}</small></td>"
        f"<td>{html.escape(row['symbol'])}</td><td>{html.escape(row['timeframe'])}</td><td>{html.escape(row.get('direction', ''))}</td>"
        f"<td>{html.escape(row['latest_price'])}</td><td>{html.escape(row['hypothetical_entry_price'])}</td><td>{html.escape(row['hypothetical_stop_price'])}</td><td>{html.escape(row['hypothetical_target_price'])}</td>"
        f"<td>{html.escape(row.get('signal_time', ''))}</td><td>{html.escape(row.get('review_status', ''))}</td></tr>"
    )


def extended_session_head() -> str:
    return "<tr><th>时段</th><th>股票</th><th>主题</th><th>现价</th><th>参考收盘</th><th>涨跌额</th><th>涨跌幅</th><th>时间</th></tr>"


def extended_session_row_html(row: dict[str, str]) -> str:
    cls = "good" if money_to_decimal(row["move_percent"]) > ZERO else "bad" if money_to_decimal(row["move_percent"]) < ZERO else ""
    return (
        "<tr>"
        f"<td>{html.escape(row['session'])}</td>"
        f"<td>{html.escape(row['symbol'])}</td>"
        f"<td>{html.escape(row.get('theme', '') or '普通监控')}</td>"
        f"<td>{html.escape(row['extended_price'])}</td>"
        f"<td>{html.escape(row['reference_close'])}</td>"
        f"<td class=\"{cls}\">{html.escape(row['move_amount'])}</td>"
        f"<td class=\"{cls}\">{html.escape(row['move_percent'])}%</td>"
        f"<td>{html.escape(row['quote_timestamp'])}</td>"
        "</tr>"
    )


def ftd_account_row_html(row: dict[str, str]) -> str:
    label = "原版 baseline" if row["variant_id"] == "baseline" else "连亏保护 loss_streak_guard"
    return (
        "<tr>"
        f"<td>{html.escape(label)}</td>"
        f"<td>{html.escape(row['today_total_pnl'])}</td>"
        f"<td>{html.escape(row['equity'])}</td>"
        f"<td>{html.escape(row['historical_return_percent'])}%</td>"
        f"<td>{html.escape(row['historical_win_rate_percent'])}%</td>"
        f"<td>{html.escape(row['historical_max_drawdown_percent'])}%</td>"
        "</tr>"
    )


def build_run_status_md(status: dict[str, Any]) -> str:
    return (
        "# M12.33 连续观察状态\n\n"
        f"- 已记录交易日：`{status['observed_trading_days']}/{status['required_trading_days']}`。\n"
        f"- 结论：{status['plain_language_result']}\n"
    )


def build_gate_md(gate: dict[str, Any]) -> str:
    lines = ["# M11.8 模拟交易试运行准入复查", "", f"- 结论：{gate['plain_language_result']}", f"- 是否批准：`{str(gate['paper_trial_approval']).lower()}`", ""]
    if gate["blocking_items"]:
        lines.append("## 还差什么")
        for item in gate["blocking_items"]:
            lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def build_handoff_md(config: M1229Config, summary: dict[str, Any]) -> str:
    return (
        "```yaml\n"
        "task_id: M12.46-M11.8-accountized-testing\n"
        "role: main-agent\n"
        "branch_or_worktree: codex/m12-46-accountized-testing\n"
        "objective: 把只读实时测试升级为 20,000 USD 独立模拟账户，按 1d/5m 分栏运行主线和实验策略，并修复纽约交易日累计口径\n"
        "status: success\n"
        "files_changed:\n"
        "  - config/examples/m12_29_current_day_scan_dashboard.json\n"
        "  - config/examples/m12_37_intraday_auto_loop.json\n"
        "  - scripts/m12_29_current_day_scan_dashboard_lib.py\n"
        "  - scripts/run_m12_29_current_day_scan_dashboard.py\n"
        "  - scripts/run_m12_37_intraday_auto_loop.py\n"
        "  - tests/unit/test_m12_29_current_day_scan_dashboard.py\n"
        "  - tests/unit/test_m12_37_intraday_auto_loop.py\n"
        "  - reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/*\n"
        "interfaces_changed: []\n"
        "commands_run:\n"
        "  - python scripts/run_m12_37_intraday_auto_loop.py --once --no-fetch\n"
        "tests_run:\n"
        "  - python -m unittest tests/unit/test_m12_29_current_day_scan_dashboard.py -v\n"
        "  - python -m unittest tests/unit/test_m12_37_intraday_auto_loop.py -v\n"
        "  - python -m unittest tests/unit/test_m12_46_runtime_accounts.py -v\n"
        "  - python -m unittest tests/unit/test_m12_29_current_day_scan_dashboard.py tests/unit/test_m12_37_intraday_auto_loop.py tests/unit/test_m12_46_runtime_accounts.py tests/unit/test_m12_17_daily_observation_continuity.py tests/unit/test_m12_25_daily_observation_continuity.py -v\n"
        "  - git diff --check\n"
        "verification_results:\n"
        f"  - scan_date: {summary['scan_date']}\n"
        f"  - today_candidate_count: {summary['today_candidate_count']}\n"
        f"  - current_day_scan_complete: {str(summary['current_day_scan_complete']).lower()}\n"
        "assumptions:\n"
        "  - 当前仍是只读行情和模拟盈亏，不接真实账户，不下真实订单\n"
        "risks:\n"
        "  - 实验账户仍需累计更多真实交易日，当前还不能直接当作稳定结论\n"
        "  - 自动运行需要显式启用 systemd/cron 或 Codex automation，当前 handoff 只记录实现状态\n"
        "qa_focus:\n"
        "  - 检查纽约交易日累计、主线/实验账户隔离、FTD001 双版本并行和只读边界\n"
        "rollback_notes:\n"
        "  - 回滚本阶段提交即可撤回 M12.46 账户化实时测试产物\n"
        "next_recommended_action: 启用交易日会话自动运行，累计 10 个纽约真实交易日的主线/实验账户结果，再做 M11.8 模拟交易试运行复查\n"
        "needs_user_decision: false\n"
        "user_decision_needed: ''\n"
        "```\n"
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def metrics_by_strategy(path: Path, *, cohort_id: str | None = None) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        if not row.get("strategy_id"):
            continue
        if row.get("grain") != "strategy" or row.get("cost_tier") != "baseline":
            continue
        if cohort_id is not None and row.get("cohort_id") != cohort_id:
            continue
        rows[row["strategy_id"]] = row
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def decimal_or_none(value: Any) -> Decimal | None:
    try:
        if value in (None, "", "暂无"):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def money_to_decimal(value: str) -> Decimal:
    return decimal_or_none(value) or ZERO


def quantity_from_prices(entry: Decimal, stop: Decimal) -> Decimal:
    risk = abs(entry - stop)
    return DEFAULT_RISK_BUDGET / risk if risk > ZERO else ZERO


def simulated_pnl(direction: str, latest: Decimal, entry: Decimal, qty: Decimal) -> Decimal:
    if direction in {"long", "看涨"}:
        return (latest - entry) * qty
    if direction in {"short", "看跌"}:
        return (entry - latest) * qty
    return ZERO


def simulated_state(direction: str, latest: Decimal, stop: Decimal, target: Decimal) -> str:
    if latest <= ZERO:
        return "等待行情"
    if direction in {"long", "看涨"}:
        if latest <= stop:
            return "触及止损参考"
        if latest >= target:
            return "触及目标参考"
    if direction in {"short", "看跌"}:
        if latest >= stop:
            return "触及止损参考"
        if latest <= target:
            return "触及目标参考"
    return "观察中"


def direction_zh(direction: str) -> str:
    return "看涨" if direction == "long" else "看跌" if direction == "short" else direction


def normalize_rate(value: str) -> str:
    dec = decimal_or_none(value)
    if dec is None:
        return ""
    return pct(dec * HUNDRED)


def dashboard_drawdown_reference(rows: list[dict[str, str]]) -> str:
    values = [decimal_or_none(row["max_drawdown_percent"]) for row in rows if row["daily_realtime_test"] == "true"]
    values = [value for value in values if value is not None]
    return pct(max(values)) if values else "暂无"


def positive_percent(rows: list[dict[str, str]]) -> str:
    numeric = [row for row in rows if row.get("simulated_intraday_pnl") not in ("", "暂无", None)]
    if not numeric:
        return "0.00"
    positive = [row for row in numeric if money_to_decimal(row["simulated_intraday_pnl"]) > ZERO]
    return pct(Decimal(len(positive)) / Decimal(len(numeric)) * HUNDRED)


def money(value: Decimal) -> str:
    return str(value.quantize(MONEY))


def pct(value: Decimal) -> str:
    return str(value.quantize(PERCENT))


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden.lower() in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")
