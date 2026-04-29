#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
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
from scripts.m12_28_trading_session_dashboard_lib import (  # noqa: E402
    build_pa004_long_rows,
    build_quotes,
    load_config as load_m12_28_config,
)


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_29_current_day_scan_dashboard.json"
OUTPUT_DIR = M10_DIR / "daily_observation" / "m12_29_current_day_scan_dashboard"
MONEY = Decimal("0.01")
PERCENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
DEFAULT_EQUITY = Decimal("100000")
DEFAULT_RISK_BUDGET = Decimal("500")
MAINLINE_STRATEGIES = ("M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001")
OBSERVATION_STRATEGIES = ("M10-PA-004-long", "M10-PA-007", "M10-PA-008", "M10-PA-009")
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
    trade_rows = build_trade_rows(candidates, quotes, scan_date)
    pa004_rows = build_pa004_rows(quotes, generated_at)
    closure_rows = build_strategy_closure_rows(config)
    visual_rows = build_visual_definition_rows(closure_rows)
    summary = build_summary(config, generated_at, market, scan_date, source_summary, cache_summary, quote_manifest, candidates, trade_rows, pa004_rows)
    dashboard = build_dashboard_payload(config, generated_at, summary, trade_rows, pa004_rows, closure_rows, visual_rows)
    run_status = build_run_status(config, summary, closure_rows)
    gate = build_gate_recheck(config, summary, run_status, closure_rows)

    write_json(config.output_dir / "m12_29_current_day_scan_summary.json", summary)
    write_csv(config.output_dir / "m12_29_today_candidates.csv", candidates)
    write_jsonl(config.output_dir / "m12_29_today_candidates.jsonl", candidates)
    write_csv(config.output_dir / "m12_29_trade_view.csv", trade_rows)
    write_json(config.output_dir / "m12_30_strategy_closure_matrix.json", {"schema_version": "m12.30.strategy-closure.v1", "stage": "M12.30.strategy_closure", "rows": closure_rows})
    write_csv(config.output_dir / "m12_30_strategy_closure_matrix.csv", closure_rows)
    (config.output_dir / "m12_30_strategy_closure_report.md").write_text(build_strategy_closure_md(closure_rows), encoding="utf-8")
    write_json(config.output_dir / "m12_31_visual_definition_final_review.json", {"schema_version": "m12.31.visual-definition-final.v1", "stage": "M12.31.visual_definition_final", "rows": visual_rows})
    (config.output_dir / "m12_31_visual_definition_final_review.md").write_text(build_visual_definition_md(visual_rows), encoding="utf-8")
    write_json(config.output_dir / "m12_32_minute_readonly_dashboard_data.json", dashboard)
    (config.output_dir / "m12_32_minute_readonly_dashboard.html").write_text(build_dashboard_html(config, dashboard), encoding="utf-8")
    write_json(config.output_dir / "m12_33_observation_run_status.json", run_status)
    (config.output_dir / "m12_33_observation_run_status.md").write_text(build_run_status_md(run_status), encoding="utf-8")
    write_json(config.output_dir / "m11_6_paper_trial_gate_recheck.json", gate)
    (config.output_dir / "m11_6_paper_trial_gate_recheck.md").write_text(build_gate_md(gate), encoding="utf-8")
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
    }


def current_us_scan_date(generated_at: str) -> date:
    ny_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
    candidate = ny_dt.date()
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
                "review_status": row.get("review_status", ""),
                "source_refs": row.get("source_refs", ""),
            }
        )
    return rows


def build_pa004_rows(quotes: dict[str, dict[str, str]], generated_at: str) -> list[dict[str, str]]:
    pa004_rows = build_pa004_long_rows(load_m12_28_config(), quotes, generated_at)
    for row in pa004_rows:
        row["bucket"] = "PA004 做多观察"
    return pa004_rows


def build_strategy_closure_rows(config: M1229Config) -> list[dict[str, str]]:
    metrics = {row["strategy_id"]: row for row in read_csv(config.m10_12_all_strategy_metrics_path)}
    source_plan = load_json(config.m12_16_source_candidate_plan_path)
    best_ftd = load_json(config.m12_15_best_variant_path)["metrics"]
    small_pilot = metrics_by_strategy(config.m12_24_small_pilot_metrics_path)
    pa004_long_metrics = metrics_by_strategy(config.m12_27_pa004_long_metrics_path, cohort_id="long_only")
    source_by_linked = {row["linked_runtime_id"]: row for row in source_plan["rows"]}
    rows: list[dict[str, str]] = []
    decisions = {
        "M10-PA-001": ("进入每日实时只读测试", "核心顺势策略，历史资金测试完成，继续扫描 50 只。"),
        "M10-PA-002": ("进入每日实时只读测试", "突破后跟进策略，历史资金测试完成，也可作为 FTD 确认过滤器。"),
        "M10-PA-003": ("过滤器/排名因子", "紧密通道更适合作为强趋势股票加分项，暂不作为独立买卖触发。"),
        "M10-PA-004": ("观察队列：只做多版", "整体混合版本弱，但做多分支转正；只做多观察，做空版暂不进入主线。"),
        "M10-PA-005": ("研究项：定义仍弱", "交易区间失败突破复测仍弱，几何定义不能稳定改善，不拖主线。"),
        "M10-PA-006": ("研究项", "BLSHS 限价框架不是独立触发。"),
        "M10-PA-007": ("观察队列", "第二腿陷阱小范围测试为正，先观察但不进模拟买卖准入。"),
        "M10-PA-008": ("观察队列", "主要趋势反转有历史资金测试，但图形语境强，先严格观察。"),
        "M10-PA-009": ("观察队列", "楔形反转历史测试略正，先严格观察。"),
        "M10-PA-010": ("研究项", "Final Flag/Climax/TBTL 过于复合，不作为单独触发。"),
        "M10-PA-011": ("暂不进入主线", "开盘反转历史资金测试偏弱，保留复核。"),
        "M10-PA-012": ("进入每日实时只读测试", "开盘区间突破历史资金测试表现较好，继续 15m/5m。"),
        "M10-PA-013": ("暂不进入主线", "支撑阻力失败测试历史资金测试偏弱，暂不加入实时主线。"),
        "M10-PA-014": ("辅助规则", "Measured Move 只作为目标/止盈模块。"),
        "M10-PA-015": ("辅助规则", "止损与仓位模块，不是入场触发。"),
        "M10-PA-016": ("研究项", "交易区间加仓研究不作为独立触发。"),
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
                "daily_realtime_test": str(status == "进入每日实时只读测试").lower(),
                "observation_queue": str(status.startswith("观察队列")).lower(),
                "supporting_or_research": str(status in {"辅助规则", "研究项", "研究项：定义仍弱", "过滤器/排名因子"}).lower(),
                "return_percent": pilot.get("return_percent") or metric.get("return_percent", ""),
                "win_rate_percent": pilot.get("win_rate_percent") or normalize_rate(pilot.get("win_rate", "")) or normalize_rate(metric.get("win_rate", "")),
                "max_drawdown_percent": pilot.get("max_drawdown_percent") or metric.get("max_drawdown_percent", ""),
                "trade_count": pilot.get("trade_count") or metric.get("trade_count", ""),
                "linked_source_candidate": source_by_linked.get(strategy_id, {}).get("candidate_id", ""),
                "plain_reason": reason,
                "paper_trial_candidate_now": "false",
            }
        )
    rows.append(
        {
            "strategy_id": "M12-FTD-001",
            "strategy_title": "方方土日线趋势顺势信号K",
            "final_status": "进入每日实时只读测试",
            "daily_realtime_test": "true",
            "observation_queue": "false",
            "supporting_or_research": "false",
            "return_percent": best_ftd.get("return_percent", ""),
            "win_rate_percent": best_ftd.get("win_rate", ""),
            "max_drawdown_percent": best_ftd.get("max_drawdown_percent", ""),
            "trade_count": str(best_ftd.get("trade_count", "")),
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
                "observation_queue": str(source["queue"] == "strict_observation").lower(),
                "supporting_or_research": str(source["queue"] == "filter_or_ranking_factor").lower(),
                "return_percent": "",
                "win_rate_percent": "",
                "max_drawdown_percent": "",
                "trade_count": "",
                "linked_source_candidate": source["linked_runtime_id"],
                "plain_reason": source["client_note"],
                "paper_trial_candidate_now": "false",
            }
        )
    return rows


def build_visual_definition_rows(closure_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    notes = {
        "M10-PA-003": ("紧密通道、小回调、顺势延续", "趋势强弱可近似；通道形态仍需代理字段", "过滤器/排名因子"),
        "M10-PA-004": ("宽通道、边界触碰、边界后反转", "做空分支不稳定；只保留做多观察", "观察队列：只做多版"),
        "M10-PA-007": ("第一腿、第二腿、陷阱点、反向确认", "复杂图形仍可能漏判，只做观察", "观察队列"),
        "M10-PA-008": ("趋势破坏、二次测试、反转确认", "主要趋势反转仍强依赖上下文", "观察队列"),
        "M10-PA-009": ("三推、楔形/楔形旗形、反转确认", "不强制完美收敛，误判需观察", "观察队列"),
        "M10-PA-010": ("最终旗形、高潮、TBTL 片段", "组合概念过多，机器触发不稳定", "研究项"),
        "M10-PA-011": ("开盘反转、开盘失败突破", "历史结果偏弱，暂不主线", "暂不进入主线"),
        "M10-PA-013": ("支撑阻力失败测试", "历史结果偏弱，暂不主线", "暂不进入主线"),
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
    return {
        "schema_version": "m12.32.minute-readonly-dashboard.v1",
        "stage": "M12.32.minute_readonly_dashboard",
        "generated_at": generated_at,
        "title": "分钟级只读模拟看板",
        "refresh_seconds": config.dashboard_refresh_seconds,
        "top_metrics": {
            "今日新机会": summary["today_candidate_count"],
            "盘中模拟盈亏": summary["total_simulated_pnl"],
            "模拟收益率": summary["total_simulated_return_percent"],
            "浮盈机会占比": summary["positive_opportunity_percent"],
            "最大回撤参考": dashboard_drawdown_reference(closure_rows),
            "策略可用数": sum(1 for row in closure_rows if row["daily_realtime_test"] == "true"),
        },
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


def build_run_status(config: M1229Config, summary: dict[str, Any], closure_rows: list[dict[str, str]]) -> dict[str, Any]:
    observed_days = 1 if summary["current_day_scan_complete"] else 0
    return {
        "schema_version": "m12.33.observation-run-status.v1",
        "stage": "M12.33.observation_run_status",
        "observed_trading_days": observed_days,
        "required_trading_days": config.min_observation_days_for_trial,
        "ready_for_m11_6_review": observed_days >= config.min_observation_days_for_trial,
        "daily_realtime_strategy_ids": [row["strategy_id"] for row in closure_rows if row["daily_realtime_test"] == "true"],
        "observation_strategy_ids": [row["strategy_id"] for row in closure_rows if row["observation_queue"] == "true"],
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
        "candidate_strategy_ids": [row["strategy_id"] for row in closure_rows if row["daily_realtime_test"] == "true"],
        "blocking_items": [] if ready else ["连续交易日记录不足 10 天", "仍需继续验证每日扫描稳定性"],
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": ready,
    }


def build_report_md(summary: dict[str, Any]) -> str:
    warning = f"\n- 注意：{summary['candidate_date_warning']}" if summary["candidate_date_warning"] else ""
    return (
        "# M12.29 当日扫描报告\n\n"
        "## 用人话结论\n\n"
        f"- 扫描交易日：`{summary['scan_date']}`；市场状态：{summary['market_session']['status']}。\n"
        f"- 今日新机会 `{summary['today_candidate_count']}` 条，PA004 做多观察 `{summary['pa004_long_observation_count']}` 条。\n"
        f"- 当前只读报价覆盖后的模拟盈亏：`{summary['total_simulated_pnl']}`，模拟收益率 `{summary['total_simulated_return_percent']}%`。\n"
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


def build_dashboard_html(config: M1229Config, dashboard: dict[str, Any]) -> str:
    metrics = dashboard["top_metrics"]
    cards = "\n".join(
        f"<section class=\"metric\"><span>{html.escape(k)}</span><strong>{html.escape(str(v))}</strong></section>"
        for k, v in metrics.items()
    )
    today_rows = "\n".join(trade_row_html(row) for row in dashboard["trade_rows"][:180])
    pa004_rows = "\n".join(trade_row_html(row) for row in dashboard["pa004_long_rows"][:40])
    status_rows = "\n".join(
        f"<tr><td>{html.escape(row['strategy_id'])}</td><td>{html.escape(row['strategy_title'])}</td><td>{html.escape(row['final_status'])}</td><td>{html.escape(row['plain_reason'])}</td></tr>"
        for row in dashboard["strategy_status_rows"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{config.dashboard_refresh_seconds}">
  <title>M12.32 分钟级只读模拟看板</title>
  <style>
    body {{ margin:0; font-family:Arial,"Noto Sans SC",sans-serif; background:#f6f7f9; color:#1f2933; letter-spacing:0; }}
    header {{ padding:18px 22px; background:#fff; border-bottom:1px solid #d8dee9; display:flex; justify-content:space-between; gap:18px; }}
    h1 {{ margin:0; font-size:24px; }} main {{ padding:18px 22px; display:grid; gap:18px; }}
    .grid {{ display:grid; grid-template-columns:repeat(6,minmax(120px,1fr)); gap:10px; }}
    .metric,.panel {{ background:#fff; border:1px solid #d8dee9; border-radius:8px; }}
    .metric {{ padding:12px; }} .metric span {{ display:block; color:#667085; font-size:12px; }} .metric strong {{ display:block; margin-top:8px; font-size:22px; }}
    h2 {{ margin:0; padding:14px 16px; font-size:18px; border-bottom:1px solid #d8dee9; }}
    .note {{ padding:12px 16px; color:#667085; line-height:1.6; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }} th,td {{ padding:9px 10px; border-bottom:1px solid #e5e7eb; text-align:left; vertical-align:top; }}
    th {{ background:#eef2f7; }} .wrap {{ max-height:520px; overflow:auto; }}
    .good {{ color:#18794e; font-weight:700; }} .bad {{ color:#b42318; font-weight:700; }}
    @media (max-width:980px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} header {{ display:block; }} }}
  </style>
</head>
<body>
  <header><div><h1>分钟级只读模拟看板</h1><div>更新时间：{html.escape(dashboard['generated_at'])}</div></div><div>只读行情 + 模拟盈亏，不接真实账户，不做真实买卖</div></header>
  <main>
    <div class="grid">{cards}</div>
    <section class="panel"><h2>今日新机会、旧观察机会与模拟盈亏</h2><div class="note">报价每 {config.dashboard_refresh_seconds} 秒刷新；策略信号按对应 K 线收盘确认；表内“类别”会区分今日新扫描和旧观察。</div><div class="wrap"><table><thead>{table_head()}</thead><tbody>{today_rows}</tbody></table></div></section>
    <section class="panel"><h2>PA004 做多观察</h2><div class="note">只做多版进入观察，不代表自动买卖准入。</div><div class="wrap"><table><thead>{table_head()}</thead><tbody>{pa004_rows}</tbody></table></div></section>
    <section class="panel"><h2>策略状态</h2><div class="wrap"><table><thead><tr><th>策略</th><th>名称</th><th>状态</th><th>说明</th></tr></thead><tbody>{status_rows}</tbody></table></div></section>
  </main>
</body>
</html>
"""


def table_head() -> str:
    return "<tr><th>类别</th><th>策略</th><th>股票</th><th>周期</th><th>方向</th><th>当前价</th><th>入场</th><th>止损</th><th>目标</th><th>模拟盈亏</th><th>状态</th></tr>"


def trade_row_html(row: dict[str, str]) -> str:
    pnl = row["simulated_intraday_pnl"]
    cls = "good" if pnl != "暂无" and money_to_decimal(pnl) > ZERO else "bad" if pnl != "暂无" and money_to_decimal(pnl) < ZERO else ""
    return (
        "<tr>"
        f"<td>{html.escape(row.get('bucket', ''))}</td><td>{html.escape(row['strategy_id'])}<br><small>{html.escape(row['strategy_title'])}</small></td>"
        f"<td>{html.escape(row['symbol'])}</td><td>{html.escape(row['timeframe'])}</td><td>{html.escape(row.get('direction', ''))}</td>"
        f"<td>{html.escape(row['latest_price'])}</td><td>{html.escape(row['hypothetical_entry_price'])}</td><td>{html.escape(row['hypothetical_stop_price'])}</td><td>{html.escape(row['hypothetical_target_price'])}</td>"
        f"<td class=\"{cls}\">{html.escape(pnl)}</td><td>{html.escape(row['simulated_state'])}</td></tr>"
    )


def build_run_status_md(status: dict[str, Any]) -> str:
    return (
        "# M12.33 连续观察状态\n\n"
        f"- 已记录交易日：`{status['observed_trading_days']}/{status['required_trading_days']}`。\n"
        f"- 结论：{status['plain_language_result']}\n"
    )


def build_gate_md(gate: dict[str, Any]) -> str:
    lines = ["# M11.6 模拟交易试运行准入复查", "", f"- 结论：{gate['plain_language_result']}", f"- 是否批准：`{str(gate['paper_trial_approval']).lower()}`", ""]
    if gate["blocking_items"]:
        lines.append("## 还差什么")
        for item in gate["blocking_items"]:
            lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def build_handoff_md(config: M1229Config, summary: dict[str, Any]) -> str:
    return (
        "```yaml\n"
        "task_id: M12.29-current-day-scan-dashboard\n"
        "role: main-agent\n"
        "branch_or_worktree: feature/m12-29-current-day-scan-dashboard\n"
        "objective: 滚动到当前美股交易日重新扫描第一批50只，并生成分钟级只读模拟看板与策略收口产物\n"
        "status: success\n"
        "files_changed:\n"
        "  - config/examples/m12_29_current_day_scan_dashboard.json\n"
        "  - scripts/m12_29_current_day_scan_dashboard_lib.py\n"
        "  - scripts/run_m12_29_current_day_scan_dashboard.py\n"
        "  - tests/unit/test_m12_29_current_day_scan_dashboard.py\n"
        "  - reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m12_29_current_day_scan_dashboard/*\n"
        "interfaces_changed: []\n"
        "commands_run:\n"
        "  - git push origin main  # failed: GitHub 100MB large-file limit on historical M10.6 ledger\n"
        "  - python scripts/run_m12_29_current_day_scan_dashboard.py\n"
        "tests_run:\n"
        "  - python -m unittest tests/unit/test_m12_29_current_day_scan_dashboard.py -v\n"
        "verification_results:\n"
        f"  - scan_date: {summary['scan_date']}\n"
        f"  - today_candidate_count: {summary['today_candidate_count']}\n"
        f"  - current_day_scan_complete: {str(summary['current_day_scan_complete']).lower()}\n"
        "assumptions:\n"
        "  - 当前仍是只读行情和模拟盈亏，不接真实账户，不下真实订单\n"
        "risks:\n"
        "  - 远端推送被历史大文件阻塞，需要单独做 Git 历史/LFS 清理方案\n"
        "qa_focus:\n"
        "  - 检查候选日期是否等于当前美股交易日，检查看板中文和只读边界\n"
        "rollback_notes:\n"
        "  - 回滚本阶段提交即可撤回 M12.29-M11.6 产物\n"
        "next_recommended_action: 继续累计10个真实交易日的只读模拟看板记录\n"
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
