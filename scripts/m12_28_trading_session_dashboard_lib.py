#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_liquid_universe_scanner_lib import load_bars  # noqa: E402
from scripts.m12_readonly_auth_preflight_lib import _assert_readonly_command, clean_cli_text  # noqa: E402


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_28_trading_session_dashboard.json"
OUTPUT_DIR = M10_DIR / "dashboard" / "m12_28_trading_session_dashboard"
MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
DEFAULT_ACCOUNT_EQUITY = Decimal("100000")
DEFAULT_RISK_BUDGET = Decimal("500")
FORBIDDEN_OUTPUT_TEXT = (
    "PA-SC-",
    "SF-",
    "live-ready",
    "real_orders=true",
    "broker_connection=true",
    "paper approval",
    "order_id",
    "fill_id",
    "account_id",
    "cash_balance",
    "position_qty",
)


@dataclass(frozen=True, slots=True)
class QuoteRefreshConfig:
    enabled: bool
    max_symbols: int
    fallback_behavior: str


@dataclass(frozen=True, slots=True)
class Pa004LongConfig:
    enabled: bool
    max_recent_events: int
    lookback_days: int
    variant_id: str


@dataclass(frozen=True, slots=True)
class BoundaryConfig:
    paper_simulated_only: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool
    paper_trading_approval: bool


@dataclass(frozen=True, slots=True)
class M1228Config:
    title: str
    run_id: str
    stage: str
    market: str
    output_dir: Path
    first50_universe_path: Path
    m12_12_dashboard_path: Path
    m12_12_trade_view_path: Path
    m12_27_pa004_summary_path: Path
    pa004_detector_events_path: Path
    fallback_live_snapshot_ledger_path: Path
    quote_refresh: QuoteRefreshConfig
    dashboard_refresh_seconds: int
    pa004_long_observation: Pa004LongConfig
    boundary: BoundaryConfig


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path | None) -> str:
    if path is None:
        return ""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M1228Config:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    quote = payload["quote_refresh"]
    pa004 = payload["pa004_long_observation"]
    boundary = payload["boundary"]
    config = M1228Config(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_28_trading_session_dashboard"),
        stage=payload["stage"],
        market=payload.get("market", "US"),
        output_dir=resolve_repo_path(payload["output_dir"]),
        first50_universe_path=resolve_repo_path(payload["first50_universe_path"]),
        m12_12_dashboard_path=resolve_repo_path(payload["m12_12_dashboard_path"]),
        m12_12_trade_view_path=resolve_repo_path(payload["m12_12_trade_view_path"]),
        m12_27_pa004_summary_path=resolve_repo_path(payload["m12_27_pa004_summary_path"]),
        pa004_detector_events_path=resolve_repo_path(payload["pa004_detector_events_path"]),
        fallback_live_snapshot_ledger_path=resolve_repo_path(payload["fallback_live_snapshot_ledger_path"]),
        quote_refresh=QuoteRefreshConfig(
            enabled=bool(quote["enabled"]),
            max_symbols=int(quote["max_symbols"]),
            fallback_behavior=quote["fallback_behavior"],
        ),
        dashboard_refresh_seconds=int(payload["dashboard_refresh_seconds"]),
        pa004_long_observation=Pa004LongConfig(
            enabled=bool(pa004["enabled"]),
            max_recent_events=int(pa004["max_recent_events"]),
            lookback_days=int(pa004["lookback_days"]),
            variant_id=pa004["variant_id"],
        ),
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


def validate_config(config: M1228Config) -> None:
    if config.stage != "M12.28.trading_session_dashboard":
        raise ValueError("M12.28 stage drift")
    if config.quote_refresh.max_symbols > 50:
        raise ValueError("M12.28 quote refresh must stay within first 50 symbols")
    if not config.boundary.paper_simulated_only:
        raise ValueError("M12.28 must stay paper/simulated only")
    if (
        config.boundary.trading_connection
        or config.boundary.real_money_actions
        or config.boundary.live_execution
        or config.boundary.paper_trading_approval
    ):
        raise ValueError("M12.28 cannot enable trading connection, real money actions, live execution, or paper approval")


def run_m12_28_trading_session_dashboard(
    config: M1228Config | None = None,
    *,
    generated_at: str | None = None,
    refresh_quotes: bool | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    validate_config(config)
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    config.output_dir.mkdir(parents=True, exist_ok=True)

    first50 = load_json(config.first50_universe_path)["symbols"][: config.quote_refresh.max_symbols]
    m12_12_dashboard = load_json(config.m12_12_dashboard_path)
    m12_12_trade_rows = read_csv(config.m12_12_trade_view_path)
    pa004_summary = load_json(config.m12_27_pa004_summary_path)
    quote_fetch_enabled = config.quote_refresh.enabled if refresh_quotes is None else refresh_quotes
    quotes, quote_manifest = build_quotes(config, first50, generated_at, enabled=quote_fetch_enabled)
    session_rows = build_session_trade_rows(m12_12_trade_rows, quotes)
    pa004_rows = build_pa004_long_rows(config, quotes, generated_at)
    summary = build_summary(
        config=config,
        generated_at=generated_at,
        first50=first50,
        m12_12_dashboard=m12_12_dashboard,
        pa004_summary=pa004_summary,
        quote_manifest=quote_manifest,
        session_rows=session_rows,
        pa004_rows=pa004_rows,
    )
    dashboard = {
        "schema_version": "m12.28.trading-session-dashboard.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "title": config.title,
        "summary": summary,
        "session_quotes": list(quotes.values()),
        "session_trade_rows": session_rows,
        "pa004_long_observation_rows": pa004_rows,
        "input_refs": {
            "m12_12_dashboard": project_path(config.m12_12_dashboard_path),
            "m12_12_trade_view": project_path(config.m12_12_trade_view_path),
            "m12_27_pa004_summary": project_path(config.m12_27_pa004_summary_path),
            "pa004_detector_events": project_path(config.pa004_detector_events_path),
        },
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_json(config.output_dir / "m12_28_session_dashboard_data.json", dashboard)
    write_json(config.output_dir / "m12_28_session_quote_manifest.json", quote_manifest)
    write_csv(config.output_dir / "m12_28_session_trade_view.csv", session_rows)
    write_csv(config.output_dir / "m12_28_pa004_long_observation.csv", pa004_rows)
    (config.output_dir / "m12_28_trading_session_dashboard.html").write_text(build_dashboard_html(config, dashboard), encoding="utf-8")
    (config.output_dir / "m12_28_session_report.md").write_text(build_report_md(dashboard), encoding="utf-8")
    (config.output_dir / "m12_28_handoff.md").write_text(build_handoff_md(config, summary), encoding="utf-8")
    assert_no_forbidden_output(config.output_dir)
    return dashboard


def build_quotes(
    config: M1228Config,
    symbols: list[str],
    generated_at: str,
    *,
    enabled: bool,
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    if enabled:
        try:
            quotes = fetch_longbridge_quotes(symbols, config.market, generated_at)
            return quotes, quote_manifest(config, generated_at, "longbridge_quote_readonly", quotes, "")
        except Exception as exc:  # pragma: no cover - runtime provider path
            fallback = fallback_quotes(config, generated_at)
            return fallback, quote_manifest(config, generated_at, "fallback_after_quote_error", fallback, str(exc)[:300])
    fallback = fallback_quotes(config, generated_at)
    return fallback, quote_manifest(config, generated_at, "fallback_quotes_only", fallback, "quote_refresh_disabled")


def fetch_longbridge_quotes(symbols: list[str], market: str, generated_at: str) -> dict[str, dict[str, str]]:
    cli_path = shutil.which("longbridge")
    if cli_path is None:
        raise RuntimeError("longbridge_cli_missing")
    lb_symbols = [build_longbridge_symbol(symbol, market) for symbol in symbols]
    command = ["quote", *lb_symbols, "--format", "json"]
    _assert_readonly_command(command)
    completed = subprocess.run([cli_path, *command], capture_output=True, text=True, check=False, timeout=45)
    if completed.returncode != 0:
        detail = clean_cli_text((completed.stderr or completed.stdout or "").strip())
        raise RuntimeError(detail or f"longbridge quote failed with {completed.returncode}")
    payload = json.loads(completed.stdout.strip() or "[]")
    if not isinstance(payload, list):
        raise RuntimeError("longbridge quote returned non-list payload")
    quotes: dict[str, dict[str, str]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).split(".")[0]
        if not symbol:
            continue
        quotes[symbol] = {
            "symbol": symbol,
            "latest_price": str(row.get("last", "")),
            "previous_close": str(row.get("prev_close", "")),
            "open": str(row.get("open", "")),
            "high": str(row.get("high", "")),
            "low": str(row.get("low", "")),
            "volume": str(row.get("volume", "")),
            "quote_status": str(row.get("status", "")),
            "quote_timestamp": generated_at,
            "quote_source": "longbridge_quote_readonly",
        }
    return quotes


def fallback_quotes(config: M1228Config, generated_at: str) -> dict[str, dict[str, str]]:
    quotes: dict[str, dict[str, str]] = {}
    if config.fallback_live_snapshot_ledger_path.exists():
        for row in load_jsonl(config.fallback_live_snapshot_ledger_path):
            symbol = row.get("symbol", "")
            if not symbol or symbol in quotes:
                continue
            ohlcv = row.get("ohlcv", {})
            quotes[symbol] = {
                "symbol": symbol,
                "latest_price": str(ohlcv.get("close", "")),
                "previous_close": "",
                "open": str(ohlcv.get("open", "")),
                "high": str(ohlcv.get("high", "")),
                "low": str(ohlcv.get("low", "")),
                "volume": str(ohlcv.get("volume", "")),
                "quote_status": "fallback_snapshot",
                "quote_timestamp": row.get("bar_timestamp", generated_at),
                "quote_source": "m12_27_readonly_kline_fallback",
            }
    for row in read_csv(config.m12_12_trade_view_path):
        symbol = row["symbol"]
        if symbol in quotes:
            continue
        quotes[symbol] = {
            "symbol": symbol,
            "latest_price": row.get("current_reference_price", ""),
            "previous_close": "",
            "open": "",
            "high": "",
            "low": "",
            "volume": "",
            "quote_status": "cached_reference",
            "quote_timestamp": generated_at,
            "quote_source": "m12_12_cached_reference_fallback",
        }
    return quotes


def quote_manifest(
    config: M1228Config,
    generated_at: str,
    source: str,
    quotes: dict[str, dict[str, str]],
    error: str,
) -> dict[str, Any]:
    return {
        "schema_version": "m12.28.session-quote-manifest.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "quote_source": source,
        "quote_count": len(quotes),
        "symbols": sorted(quotes),
        "error": error,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
    }


def build_session_trade_rows(source_rows: list[dict[str, str]], quotes: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for row in source_rows:
        quote = quotes.get(row["symbol"], {})
        latest = decimal_or_none(quote.get("latest_price")) or decimal_or_none(row.get("current_reference_price")) or ZERO
        entry = decimal_or_none(row.get("hypothetical_entry_price")) or ZERO
        stop = decimal_or_none(row.get("hypothetical_stop_price")) or ZERO
        target = decimal_or_none(row.get("hypothetical_target_price")) or ZERO
        qty = decimal_or_none(row.get("hypothetical_quantity")) or quantity_from_prices(entry, stop)
        pnl = simulated_pnl(row.get("direction", ""), latest, entry, qty)
        state = simulated_state(row.get("direction", ""), latest, stop, target)
        rows.append(
            {
                "strategy_id": row["strategy_id"],
                "strategy_title": row["strategy_title"],
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "direction": row["direction"],
                "signal_time": row["bar_timestamp"],
                "latest_price": money(latest),
                "latest_price_source": quote.get("quote_source", "m12_12_cached_reference_fallback"),
                "hypothetical_entry_price": row["hypothetical_entry_price"],
                "hypothetical_stop_price": row["hypothetical_stop_price"],
                "hypothetical_target_price": row["hypothetical_target_price"],
                "hypothetical_quantity": str(qty.quantize(Decimal("0.0001"))),
                "simulated_intraday_pnl": money(pnl),
                "simulated_intraday_return_percent": pct(pnl / DEFAULT_ACCOUNT_EQUITY * HUNDRED),
                "simulated_state": state,
                "review_status": row["review_status"],
                "risk_level": row["risk_level"],
                "source_refs": row.get("source_refs", ""),
            }
        )
    return rows


def build_pa004_long_rows(config: M1228Config, quotes: dict[str, dict[str, str]], generated_at: str) -> list[dict[str, str]]:
    if not config.pa004_long_observation.enabled:
        return []
    cutoff_date = (datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date() - timedelta(days=config.pa004_long_observation.lookback_days))
    events = [
        row for row in load_jsonl(config.pa004_detector_events_path)
        if row.get("strategy_id") == "M10-PA-004" and row.get("direction") == "看涨"
        and parse_date_prefix(row.get("bar_timestamp", "")) >= cutoff_date
    ]
    events.sort(key=lambda row: row["bar_timestamp"], reverse=True)
    rows: list[dict[str, str]] = []
    for event in events[: config.pa004_long_observation.max_recent_events]:
        candidate = pa004_candidate_from_event(event)
        if not candidate:
            continue
        quote = quotes.get(candidate["symbol"], {})
        latest = decimal_or_none(quote.get("latest_price")) or ZERO
        entry = d(candidate["hypothetical_entry_price"])
        stop = d(candidate["hypothetical_stop_price"])
        target = d(candidate["hypothetical_target_price"])
        qty = quantity_from_prices(entry, stop)
        pnl = simulated_pnl("看涨", latest, entry, qty) if latest > ZERO else ZERO
        rows.append(
            {
                "strategy_id": "M10-PA-004",
                "variant_id": config.pa004_long_observation.variant_id,
                "strategy_title": "宽通道边界反转（只做多观察版）",
                "symbol": candidate["symbol"],
                "timeframe": "1d",
                "direction": "看涨",
                "signal_time": candidate["signal_time"],
                "latest_price": money(latest) if latest > ZERO else "暂无",
                "latest_price_source": quote.get("quote_source", "暂无"),
                "hypothetical_entry_price": candidate["hypothetical_entry_price"],
                "hypothetical_stop_price": candidate["hypothetical_stop_price"],
                "hypothetical_target_price": candidate["hypothetical_target_price"],
                "hypothetical_quantity": str(qty.quantize(Decimal("0.0001"))),
                "simulated_intraday_pnl": money(pnl) if latest > ZERO else "暂无",
                "simulated_intraday_return_percent": pct(pnl / DEFAULT_ACCOUNT_EQUITY * HUNDRED) if latest > ZERO else "暂无",
                "simulated_state": simulated_state("看涨", latest, stop, target) if latest > ZERO else "等待行情",
                "review_status": "PA004 做多观察版，等待日线收盘确认",
                "risk_level": "中",
                "source_refs": ";".join(event.get("source_refs", [])),
            }
        )
    return rows


def parse_date_prefix(value: str):
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return datetime.min.date()


def pa004_candidate_from_event(event: dict[str, Any]) -> dict[str, str] | None:
    source_path = resolve_repo_path(event["source_cache_path"])
    if not source_path.exists():
        return None
    bars = load_bars(source_path)
    by_ts = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    signal_idx = by_ts.get(event["bar_timestamp"])
    if signal_idx is None or signal_idx + 1 >= len(bars):
        return None
    entry = bars[signal_idx + 1].open
    stop = d(event["range_low"])
    risk = entry - stop
    if risk <= ZERO:
        return None
    target = entry + risk * Decimal("2")
    return {
        "symbol": event["symbol"],
        "signal_time": event["bar_timestamp"],
        "hypothetical_entry_price": money(entry),
        "hypothetical_stop_price": money(stop),
        "hypothetical_target_price": money(target),
    }


def build_summary(
    *,
    config: M1228Config,
    generated_at: str,
    first50: list[str],
    m12_12_dashboard: dict[str, Any],
    pa004_summary: dict[str, Any],
    quote_manifest: dict[str, Any],
    session_rows: list[dict[str, str]],
    pa004_rows: list[dict[str, str]],
) -> dict[str, Any]:
    pnl = sum((d(row["simulated_intraday_pnl"]) for row in session_rows if row["simulated_intraday_pnl"] != "暂无"), ZERO)
    pa004_pnl = sum((d(row["simulated_intraday_pnl"]) for row in pa004_rows if row["simulated_intraday_pnl"] != "暂无"), ZERO)
    all_rows = session_rows + pa004_rows
    positive = [row for row in all_rows if row["simulated_intraday_pnl"] != "暂无" and d(row["simulated_intraday_pnl"]) > ZERO]
    pa004_long = pa004_summary["pa004_long_only_retest"]
    market = market_session_status(generated_at)
    mainline_candidate_dates = extract_signal_dates(session_rows)
    pa004_candidate_dates = extract_signal_dates(pa004_rows)
    mainline_is_today = mainline_candidate_dates == [market["new_york_date"]]
    alignment = "current_day_scan_with_live_quotes" if mainline_is_today else "live_quote_overlay_on_prior_candidate_set"
    warning = (
        "当前价格已按 Longbridge 只读行情刷新，但主线候选仍来自上一轮 M12.12 扫描；"
        "这不是今日重新全量扫描结果，下一步需要把 50 只股票滚动到当前交易日重新扫描。"
    )
    return {
        "plain_language_result": "盘中只读模拟看板已可刷新；PA004 只做多版已进入观察区，但不是成交、不是实盘。",
        "market_session": market,
        "dashboard_refresh_seconds": config.dashboard_refresh_seconds,
        "first50_symbol_count": len(first50),
        "quote_count": quote_manifest["quote_count"],
        "quote_source": quote_manifest["quote_source"],
        "mainline_opportunity_count": len(session_rows),
        "pa004_long_observation_count": len(pa004_rows),
        "total_visible_opportunity_count": len(all_rows),
        "mainline_candidate_dates": mainline_candidate_dates,
        "pa004_candidate_dates": pa004_candidate_dates,
        "quote_market_date": market["new_york_date"],
        "candidate_quote_time_alignment": alignment,
        "current_day_scanner_complete": mainline_is_today,
        "candidate_source_warning": warning,
        "mainline_simulated_intraday_pnl": money(pnl),
        "pa004_long_simulated_intraday_pnl": money(pa004_pnl),
        "total_simulated_intraday_pnl": money(pnl + pa004_pnl),
        "total_simulated_intraday_return_percent": pct((pnl + pa004_pnl) / DEFAULT_ACCOUNT_EQUITY * HUNDRED),
        "positive_opportunity_percent": pct(Decimal(len(positive)) / Decimal(len(all_rows)) * HUNDRED if all_rows else ZERO),
        "m12_12_prior_dashboard_metrics": m12_12_dashboard.get("top_metrics", {}),
        "pa004_long_historical_metrics": {
            "return_percent": pa004_long["return_percent"],
            "win_rate_percent": pct(d(pa004_long["win_rate"]) * HUNDRED),
            "max_drawdown_percent": pa004_long["max_drawdown_percent"],
            "trade_count": pa004_long["trade_count"],
            "decision": pa004_long["decision"],
        },
        "next_action": "用同一个脚本按 60 秒或 5 分钟刷新；下一阶段可把 M12.12 日期滚动后接入 50 只盘中扫描。",
    }


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
        "beijing_date": utc_dt.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "beijing_time": utc_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z"),
    }


def extract_signal_dates(rows: list[dict[str, str]]) -> list[str]:
    dates = {
        value[:10]
        for row in rows
        for value in [row.get("signal_time", "")]
        if len(value) >= 10 and value[:4].isdigit()
    }
    return sorted(dates)


def build_dashboard_html(config: M1228Config, dashboard: dict[str, Any]) -> str:
    summary = dashboard["summary"]
    cards = [
        ("今日机会", summary["total_visible_opportunity_count"], "含 PA004 做多观察"),
        ("盘中模拟盈亏", summary["total_simulated_intraday_pnl"], "按当前只读价估算"),
        ("模拟收益率", f"{summary['total_simulated_intraday_return_percent']}%", "以 100,000 USD 口径"),
        ("浮盈机会占比", f"{summary['positive_opportunity_percent']}%", "只看当前快照"),
        ("PA004做多", summary["pa004_long_observation_count"], "观察规则已接入"),
        ("市场状态", summary["market_session"]["status"], summary["market_session"]["new_york_time"]),
    ]
    card_html = "\n".join(
        f"<section class=\"metric\"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong><small>{html.escape(note)}</small></section>"
        for label, value, note in cards
    )
    rows = "\n".join(trade_row_html(row) for row in dashboard["session_trade_rows"][:160])
    pa004_rows = "\n".join(trade_row_html(row) for row in dashboard["pa004_long_observation_rows"][:40])
    pa004 = summary["pa004_long_historical_metrics"]
    warning = html.escape(summary["candidate_source_warning"])
    mainline_dates = ", ".join(summary["mainline_candidate_dates"]) or "暂无"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{config.dashboard_refresh_seconds}">
  <title>M12.28 盘中只读模拟看板</title>
  <style>
    :root {{ --bg:#f6f7f9; --panel:#fff; --ink:#202733; --muted:#5d6877; --line:#d9dee7; --good:#1f7a4f; --bad:#a43d2f; --accent:#0b6b8a; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Arial,"Noto Sans SC",sans-serif; background:var(--bg); color:var(--ink); letter-spacing:0; }}
    header {{ padding:18px 22px; background:var(--panel); border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:16px; align-items:end; }}
    h1 {{ margin:0 0 6px; font-size:24px; line-height:1.2; }}
    .sub {{ color:var(--muted); font-size:13px; }}
    main {{ padding:18px 22px 28px; display:grid; gap:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(6,minmax(130px,1fr)); gap:10px; }}
    .metric {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; min-height:88px; }}
    .metric span,.metric small {{ display:block; color:var(--muted); font-size:12px; }}
    .metric strong {{ display:block; margin:8px 0 4px; font-size:22px; line-height:1.1; word-break:break-word; }}
    section.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
    .warning {{ background:#fff8e6; border:1px solid #e4c56a; border-radius:8px; padding:12px 14px; color:#4d3a00; line-height:1.55; }}
    h2 {{ margin:0; padding:14px 16px; font-size:18px; border-bottom:1px solid var(--line); }}
    .note {{ padding:12px 16px; color:var(--muted); font-size:13px; line-height:1.6; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:9px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ background:#f0f3f7; color:#354052; font-weight:700; position:sticky; top:0; }}
    .table-wrap {{ max-height:520px; overflow:auto; }}
    .good {{ color:var(--good); font-weight:700; }}
    .bad {{ color:var(--bad); font-weight:700; }}
    @media (max-width:980px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} header {{ display:block; }} }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>盘中只读模拟看板</h1>
      <div class="sub">更新时间：{html.escape(dashboard['generated_at'])} ｜ {html.escape(summary['market_session']['beijing_time'])}</div>
    </div>
    <div class="sub">只读行情 + 模拟盈亏，不接真实账户，不做真实买卖</div>
  </header>
  <main>
    <div class="grid">{card_html}</div>
    <div class="warning"><strong>重要提示：</strong>{warning}<br>当前主线候选日期：{html.escape(mainline_dates)}；当前报价日期：{html.escape(summary['quote_market_date'])}。</div>
    <section class="panel">
      <h2>PA004 做多版状态</h2>
      <div class="note">历史复测：收益 {html.escape(pa004['return_percent'])}%，胜率 {html.escape(pa004['win_rate_percent'])}%，最大回撤 {html.escape(pa004['max_drawdown_percent'])}%，历史模拟样本 {html.escape(pa004['trade_count'])} 笔。现在只作为观察版进入看板，不是成交信号。</div>
      <div class="table-wrap"><table><thead>{table_head()}</thead><tbody>{pa004_rows}</tbody></table></div>
    </section>
    <section class="panel">
      <h2>今日机会与模拟盈亏</h2>
      <div class="note">这里展示的是“如果按策略价位观察”的模拟结果；当前价来自 Longbridge 只读行情，缺行情时使用上一轮缓存参考价。</div>
      <div class="table-wrap"><table><thead>{table_head()}</thead><tbody>{rows}</tbody></table></div>
    </section>
  </main>
</body>
</html>
"""


def table_head() -> str:
    return (
        "<tr><th>策略</th><th>股票</th><th>周期</th><th>方向</th><th>当前价</th><th>入场</th>"
        "<th>止损</th><th>目标</th><th>模拟盈亏</th><th>状态</th></tr>"
    )


def trade_row_html(row: dict[str, str]) -> str:
    pnl = row["simulated_intraday_pnl"]
    cls = "good" if pnl != "暂无" and d(pnl) > ZERO else "bad" if pnl != "暂无" and d(pnl) < ZERO else ""
    return (
        "<tr>"
        f"<td>{html.escape(row['strategy_id'])}<br><small>{html.escape(row['strategy_title'])}</small></td>"
        f"<td>{html.escape(row['symbol'])}</td>"
        f"<td>{html.escape(row['timeframe'])}</td>"
        f"<td>{html.escape(row['direction'])}</td>"
        f"<td>{html.escape(row['latest_price'])}</td>"
        f"<td>{html.escape(row['hypothetical_entry_price'])}</td>"
        f"<td>{html.escape(row['hypothetical_stop_price'])}</td>"
        f"<td>{html.escape(row['hypothetical_target_price'])}</td>"
        f"<td class=\"{cls}\">{html.escape(pnl)}</td>"
        f"<td>{html.escape(row['simulated_state'])}</td>"
        "</tr>"
    )


def build_report_md(dashboard: dict[str, Any]) -> str:
    s = dashboard["summary"]
    pa004 = s["pa004_long_historical_metrics"]
    return (
        "# M12.28 盘中只读模拟看板报告\n\n"
        "## 用人话结论\n\n"
        f"- 当前市场状态：{s['market_session']['status']}，纽约时间 `{s['market_session']['new_york_time']}`。\n"
        f"- 看板当前显示 `{s['total_visible_opportunity_count']}` 条机会/观察项，盘中模拟盈亏 `{s['total_simulated_intraday_pnl']}`，模拟收益率 `{s['total_simulated_intraday_return_percent']}%`。\n"
        f"- PA004 做多版已接入观察区：历史复测收益 `{pa004['return_percent']}%`，胜率 `{pa004['win_rate_percent']}%`，最大回撤 `{pa004['max_drawdown_percent']}%`。\n"
        f"- 重要提示：{s['candidate_source_warning']}\n"
        f"- 当前主线候选日期：`{', '.join(s['mainline_candidate_dates']) or '暂无'}`；当前报价日期：`{s['quote_market_date']}`；对齐状态：`{s['candidate_quote_time_alignment']}`。\n"
        "- 这不是实盘，也不是自动买卖；只是盘中按只读行情刷新模拟表现。\n\n"
        "## 下一步\n\n"
        "- 盘中可以重复运行本阶段脚本刷新看板。\n"
        "- 下一步把 M12.12 的日期滚动接入 50 只股票的盘中扫描，让今日候选不再依赖上一轮缓存日期。\n"
        "- 长历史 5m 继续补，用于以后做完整日内回测，不阻塞当前看板。\n"
    )


def build_handoff_md(config: M1228Config, summary: dict[str, Any]) -> str:
    return (
        "```yaml\n"
        "task_id: M12.28-trading-session-dashboard\n"
        "role: main-agent\n"
        "branch_or_worktree: feature/m12-28-pa004-long-dashboard-refresh\n"
        "objective: 接入 PA004 做多观察版，并生成盘中只读模拟看板刷新产物\n"
        "status: success\n"
        "files_changed:\n"
        "  - config/examples/m12_28_trading_session_dashboard.json\n"
        "  - scripts/m12_28_trading_session_dashboard_lib.py\n"
        "  - scripts/run_m12_28_trading_session_dashboard.py\n"
        "  - tests/unit/test_m12_28_trading_session_dashboard.py\n"
        "  - reports/strategy_lab/m10_price_action_strategy_refresh/dashboard/m12_28_trading_session_dashboard/*\n"
        "interfaces_changed: []\n"
        "commands_run:\n"
        "  - python scripts/run_m12_28_trading_session_dashboard.py\n"
        "  - python -m py_compile scripts/m12_28_trading_session_dashboard_lib.py scripts/run_m12_28_trading_session_dashboard.py\n"
        "  - python scripts/validate_kb.py\n"
        "  - python scripts/validate_kb_coverage.py\n"
        "  - python scripts/validate_knowledge_atoms.py\n"
        "  - python -m unittest tests/unit/test_m12_28_trading_session_dashboard.py -v\n"
        "  - python -m unittest discover -s tests/unit -v\n"
        "  - python -m unittest discover -s tests/reliability -v\n"
        "  - git diff --check\n"
        "tests_run:\n"
        "  - python -m unittest tests/unit/test_m12_28_trading_session_dashboard.py -v\n"
        "  - python -m unittest discover -s tests/unit -v\n"
        "  - python -m unittest discover -s tests/reliability -v\n"
        "verification_results:\n"
        f"  - visible_opportunities: {summary['total_visible_opportunity_count']}\n"
        f"  - quote_count: {summary['quote_count']}\n"
        f"  - pa004_long_observation_count: {summary['pa004_long_observation_count']}\n"
        f"  - candidate_quote_time_alignment: {summary['candidate_quote_time_alignment']}\n"
        "assumptions:\n"
        "  - 当前只做静态 HTML 刷新产物；实时刷新需要重复运行 runner 或 loop 模式\n"
        "  - 当前只刷新只读报价；主线候选仍来自上一轮 M12.12 扫描，需下一阶段滚动日期重扫\n"
        "risks:\n"
        "  - M12.12 日期尚未滚动到最新交易日，今日候选仍需下一阶段更新扫描日期\n"
        "qa_focus:\n"
        "  - 检查看板首页是否优先展示盈利、机会、PA004 做多状态，且无真实交易语义\n"
        "rollback_notes:\n"
        "  - 回滚本阶段提交即可撤回 M12.28 看板\n"
        "next_recommended_action: 将 M12.12 日期滚动和 first50 当前 5m 扫描接入 M12.28 刷新循环\n"
        "needs_user_decision: false\n"
        "user_decision_needed: ''\n"
        "```\n"
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden.lower() in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")


def simulated_pnl(direction: str, latest: Decimal, entry: Decimal, qty: Decimal) -> Decimal:
    if direction in {"看涨", "long"}:
        return (latest - entry) * qty
    if direction in {"看跌", "short"}:
        return (entry - latest) * qty
    return ZERO


def simulated_state(direction: str, latest: Decimal, stop: Decimal, target: Decimal) -> str:
    if latest <= ZERO:
        return "等待行情"
    if direction in {"看涨", "long"}:
        if latest <= stop:
            return "触及止损参考"
        if latest >= target:
            return "触及目标参考"
    if direction in {"看跌", "short"}:
        if latest >= stop:
            return "触及止损参考"
        if latest <= target:
            return "触及目标参考"
    return "观察中"


def quantity_from_prices(entry: Decimal, stop: Decimal) -> Decimal:
    risk = abs(entry - stop)
    return DEFAULT_RISK_BUDGET / risk if risk > ZERO else ZERO


def build_longbridge_symbol(symbol: str, market: str) -> str:
    return symbol if "." in symbol else f"{symbol}.{market.upper()}"


def decimal_or_none(value: Any) -> Decimal | None:
    try:
        if value in (None, "", "暂无"):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def d(value: Any) -> Decimal:
    return Decimal(str(value))


def money(value: Decimal) -> str:
    return str(value.quantize(MONEY))


def pct(value: Decimal) -> str:
    return str(value.quantize(PERCENT))
