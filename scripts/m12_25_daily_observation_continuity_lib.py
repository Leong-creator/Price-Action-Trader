#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M1212_DIR = M10_DIR / "daily_observation" / "m12_12_loop"
M1215_DIR = M10_DIR / "ftd_v02_ab_retest" / "m12_15"
M1216_DIR = M10_DIR / "source_candidate_test_plan" / "m12_16"
M1217_DIR = M10_DIR / "daily_observation" / "m12_17_continuity"
M1224_DIR = M10_DIR / "visual_detectors" / "m12_24_small_pilot"
OUTPUT_DIR = M10_DIR / "daily_observation" / "m12_25_continuity"

MAINLINE_STRATEGIES = ("M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001")
OBSERVATION_ONLY_STRATEGIES = ("M10-PA-007",)
EXCLUDED_FROM_DAILY_OBSERVATION = ("M10-PA-004",)
FORBIDDEN_OUTPUT_TEXT = (
    "live-ready",
    "real_orders=true",
    "broker_connection=true",
    "order_id",
    "fill_id",
    "account_id",
    "cash_balance",
    "position_qty",
)
PERCENT = Decimal("0.01")
HUNDRED = Decimal("100")


def run_m12_25_daily_observation_continuity(
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)

    dashboard = load_json(M1212_DIR / "m12_12_dashboard_data.json")
    m12_12_summary = load_json(M1212_DIR / "m12_12_loop_summary.json")
    best_variant = load_json(M1215_DIR / "m12_15_best_variant.json")
    source_queue = load_json(M1216_DIR / "m12_16_daily_test_queue.json")["rows"]
    prior_counter = load_json(M1217_DIR / "m12_17_observation_day_counter.json")
    m12_24_summary = load_json(M1224_DIR / "m12_24_pa004_pa007_small_pilot_summary.json")
    trade_rows = read_csv(M1212_DIR / "m12_12_dashboard_trade_view.csv")
    mainline_trade_rows = [row for row in trade_rows if row["strategy_id"] in set(MAINLINE_STRATEGIES)]

    observation_queue = build_observation_queue(source_queue, m12_24_summary)
    current_day = build_continuity_day(
        generated_at=generated_at,
        dashboard=dashboard,
        m12_12_summary=m12_12_summary,
        best_variant=best_variant,
        trade_rows=mainline_trade_rows,
        observation_queue=observation_queue,
    )
    recorded_days = update_recorded_days(prior_counter, current_day)
    day_count = len(recorded_days)
    days_remaining = max(0, 10 - day_count)
    summary = {
        "schema_version": "m12.25.daily-observation-continuity.v1",
        "stage": "M12.25.daily_observation_continuity",
        "generated_at": generated_at,
        "plain_language_result": (
            "每日只读测试继续运行；PA007 已加入观察队列。当前没有新增交易日数据，"
            f"连续记录仍为 {day_count}/10。"
        ),
        "day_count_recorded": day_count,
        "required_day_count_for_paper_trial_review": 10,
        "days_remaining_for_paper_trial_review": days_remaining,
        "paper_trial_review_ready": day_count >= 10,
        "mainline_strategy_scope": list(MAINLINE_STRATEGIES),
        "observation_only_strategy_scope": list(OBSERVATION_ONLY_STRATEGIES),
        "excluded_from_daily_observation": list(EXCLUDED_FROM_DAILY_OBSERVATION),
        "selected_ftd_variant": best_variant["selected_variant_id"],
        "selected_ftd_variant_metrics": best_variant["metrics"],
        "current_day": current_day,
        "recorded_trading_days": recorded_days,
        "observation_queue": observation_queue,
        "source_daily_loop_ref": project_path(M1212_DIR / "m12_12_loop_summary.json"),
        "source_dashboard_ref": project_path(M1212_DIR / "m12_12_dashboard_data.json"),
        "source_m12_24_pilot_ref": project_path(M1224_DIR / "m12_24_pa004_pa007_small_pilot_summary.json"),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }

    write_json(output_dir / "m12_25_daily_observation_continuity_summary.json", summary)
    write_json(output_dir / "m12_25_dashboard_snapshot.json", build_dashboard_snapshot(summary, mainline_trade_rows))
    write_json(
        output_dir / "m12_25_observation_day_counter.json",
        {
            "schema_version": "m12.25.day-counter.v1",
            "recorded_trading_days": recorded_days,
            "recorded_day_count": day_count,
            "target_day_count": 10,
            "paper_trial_review_ready": day_count >= 10,
        },
    )
    write_json(output_dir / "m12_25_strategy_observation_queue.json", {"schema_version": "m12.25.queue.v1", "rows": observation_queue})
    write_jsonl(output_dir / "m12_25_daily_observation_ledger.jsonl", build_ledger_rows(generated_at, mainline_trade_rows))
    write_csv(output_dir / "m12_25_today_trade_details.csv", build_trade_detail_rows(mainline_trade_rows))
    write_csv(output_dir / "m12_25_strategy_observation_queue.csv", observation_queue)
    (output_dir / "m12_25_dashboard_snapshot.html").write_text(build_dashboard_html(summary, mainline_trade_rows), encoding="utf-8")
    (output_dir / "m12_25_daily_client_report.md").write_text(build_client_report(summary), encoding="utf-8")
    (output_dir / "m12_25_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def build_observation_queue(source_queue: list[dict[str, Any]], m12_24_summary: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    source_by_runtime = {row.get("linked_runtime_id") or row.get("linked_strategy"): row for row in source_queue}
    titles = {
        "M10-PA-001": "趋势回调二次入场",
        "M10-PA-002": "突破后续跟进",
        "M10-PA-012": "开盘区间突破",
        "M12-FTD-001": "方方土日线趋势顺势信号K",
        "M10-PA-007": "第二腿陷阱反转",
        "M10-PA-004": "宽通道边界反转",
    }
    for strategy_id in MAINLINE_STRATEGIES:
        source = source_by_runtime.get(strategy_id, {})
        rows.append(
            {
                "strategy_id": strategy_id,
                "strategy_title": titles[strategy_id],
                "queue": "每日只读测试主线",
                "status": "继续观察",
                "today_in_dashboard": "true",
                "paper_trial_candidate_now": "false",
                "plain_reason": source.get("client_note", "主线策略继续累计10个交易日记录。"),
                "latest_test_return_percent": "",
                "latest_test_win_rate_percent": "",
                "latest_test_max_drawdown_percent": "",
                "source_ref": source.get("candidate_id", ""),
            }
        )

    decisions = {row["strategy_id"]: row for row in m12_24_summary["decision_rows"]}
    pa007 = decisions["M10-PA-007"]
    rows.append(
        {
            "strategy_id": "M10-PA-007",
            "strategy_title": titles["M10-PA-007"],
            "queue": "新增观察队列",
            "status": "进入每日观察，不进入模拟买卖准入",
            "today_in_dashboard": "false",
            "paper_trial_candidate_now": "false",
            "plain_reason": "M12.24 小范围历史测试为正收益且回撤可控，先加入每日观察，看后续实时只读信号是否稳定。",
            "latest_test_return_percent": pa007["return_percent"],
            "latest_test_win_rate_percent": decimal_percent_to_display(pa007["win_rate"]),
            "latest_test_max_drawdown_percent": pa007["max_drawdown_percent"],
            "source_ref": "M12.24",
        }
    )
    pa004 = decisions["M10-PA-004"]
    rows.append(
        {
            "strategy_id": "M10-PA-004",
            "strategy_title": titles["M10-PA-004"],
            "queue": "不进入每日观察",
            "status": "保留图形研究",
            "today_in_dashboard": "false",
            "paper_trial_candidate_now": "false",
            "plain_reason": "M12.24 小范围历史测试收益为负，本轮不加入每日观察，避免拖累主线。",
            "latest_test_return_percent": pa004["return_percent"],
            "latest_test_win_rate_percent": decimal_percent_to_display(pa004["win_rate"]),
            "latest_test_max_drawdown_percent": pa004["max_drawdown_percent"],
            "source_ref": "M12.24",
        }
    )
    return rows


def build_continuity_day(
    *,
    generated_at: str,
    dashboard: dict[str, Any],
    m12_12_summary: dict[str, Any],
    best_variant: dict[str, Any],
    trade_rows: list[dict[str, str]],
    observation_queue: list[dict[str, str]],
) -> dict[str, Any]:
    top = dashboard["top_metrics"]
    trade_summary = dashboard["trade_view_summary"]
    active_queue = [row for row in observation_queue if row["queue"] in {"每日只读测试主线", "新增观察队列"}]
    return {
        "recorded_at": generated_at,
        "source_day_generated_at": dashboard["generated_at"],
        "today_opportunity_count": top["今日机会数"],
        "today_simulated_unrealized_pnl": top["今日机会估算盈亏（未成交）"],
        "today_simulated_unrealized_return_percent": top["今日机会估算收益率（未成交）"],
        "floating_positive_percent": top["今日浮盈机会占比"],
        "first50_ready_symbols": top["第一批可测股票"],
        "current_5m_ready_symbols": top["当前5分钟可观察股票"],
        "long_history_5m_completeness": top["长历史5分钟完整度"],
        "ftd_selected_variant": best_variant["selected_variant_id"],
        "ftd_selected_variant_return_percent": best_variant["metrics"]["return_percent"],
        "ftd_selected_variant_win_rate": best_variant["metrics"]["win_rate"],
        "ftd_selected_variant_max_drawdown_percent": best_variant["metrics"]["max_drawdown_percent"],
        "strategy_rows": trade_summary["strategy_rows"],
        "trade_detail_count": len(trade_rows),
        "m12_12_observation_event_count": m12_12_summary["daily_loop"]["observation_event_count"],
        "active_observation_strategy_count": len(active_queue),
        "new_observation_strategy_ids": list(OBSERVATION_ONLY_STRATEGIES),
        "status": "continue_observation",
        "pause_reason": "",
        "paper_trial_review_ready": False,
    }


def update_recorded_days(prior_counter: dict[str, Any], current_day: dict[str, Any]) -> list[dict[str, Any]]:
    days = list(prior_counter.get("recorded_trading_days", []))
    source_key = current_day["source_day_generated_at"]
    existing_keys = {day.get("source_day_generated_at") for day in days}
    if source_key not in existing_keys:
        days.append(current_day)
    return days


def build_dashboard_snapshot(summary: dict[str, Any], trade_rows: list[dict[str, str]]) -> dict[str, Any]:
    day = summary["current_day"]
    return {
        "schema_version": "m12.25.dashboard-snapshot.v1",
        "stage": summary["stage"],
        "generated_at": summary["generated_at"],
        "homepage_metrics": {
            "今日机会": day["today_opportunity_count"],
            "今日估算盈亏": day["today_simulated_unrealized_pnl"],
            "今日估算收益率": day["today_simulated_unrealized_return_percent"],
            "今日浮盈机会占比": day["floating_positive_percent"],
            "FTD增强版历史收益率": day["ftd_selected_variant_return_percent"],
            "FTD增强版历史胜率": day["ftd_selected_variant_win_rate"],
            "FTD增强版最大回撤": day["ftd_selected_variant_max_drawdown_percent"],
            "连续记录天数": summary["day_count_recorded"],
            "准入还差天数": summary["days_remaining_for_paper_trial_review"],
            "观察中策略数": day["active_observation_strategy_count"],
        },
        "today_trade_rows": trade_rows,
        "observation_queue": summary["observation_queue"],
        "paper_trial_review_ready": summary["paper_trial_review_ready"],
        "paper_simulated_only": True,
    }


def build_ledger_rows(generated_at: str, trade_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for row in trade_rows:
        rows.append(
            {
                "schema_version": "m12.25.observation-ledger.v1",
                "stage": "M12.25.daily_observation_continuity",
                "generated_at": generated_at,
                "strategy_id": row["strategy_id"],
                "strategy_title": row["strategy_title"],
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "direction": row["direction"],
                "bar_timestamp": row["bar_timestamp"],
                "hypothetical_entry_price": row["hypothetical_entry_price"],
                "hypothetical_stop_price": row["hypothetical_stop_price"],
                "hypothetical_target_price": row["hypothetical_target_price"],
                "current_reference_price": row["current_reference_price"],
                "simulated_unrealized_pnl": row["simulated_unrealized_pnl"],
                "simulated_unrealized_return_percent": row["simulated_unrealized_return_percent"],
                "review_status": row["review_status"],
                "paper_simulated_only": True,
                "broker_connection": False,
                "real_orders": False,
                "live_execution": False,
            }
        )
    return rows


def build_trade_detail_rows(trade_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    wanted = [
        "strategy_id",
        "strategy_title",
        "symbol",
        "timeframe",
        "direction",
        "bar_timestamp",
        "hypothetical_entry_price",
        "hypothetical_stop_price",
        "hypothetical_target_price",
        "current_reference_price",
        "simulated_unrealized_pnl",
        "simulated_unrealized_return_percent",
        "review_status",
        "risk_level",
    ]
    return [{key: row.get(key, "") for key in wanted} for row in trade_rows]


def build_dashboard_html(summary: dict[str, Any], trade_rows: list[dict[str, str]]) -> str:
    day = summary["current_day"]
    top_cards = [
        ("今日机会", day["today_opportunity_count"]),
        ("今日估算盈亏", day["today_simulated_unrealized_pnl"]),
        ("今日估算收益率", f"{day['today_simulated_unrealized_return_percent']}%"),
        ("今日浮盈机会占比", f"{day['floating_positive_percent']}%"),
        ("FTD增强版历史收益", f"{day['ftd_selected_variant_return_percent']}%"),
        ("FTD增强版胜率", f"{day['ftd_selected_variant_win_rate']}%"),
        ("FTD增强版最大回撤", f"{day['ftd_selected_variant_max_drawdown_percent']}%"),
        ("连续记录", f"{summary['day_count_recorded']}/10"),
        ("观察中策略", day["active_observation_strategy_count"]),
    ]
    card_html = "\n".join(f"<section class='card'><div>{escape(str(label))}</div><strong>{escape(str(value))}</strong></section>" for label, value in top_cards)
    rows_html = "\n".join(
        "<tr>"
        f"<td>{escape(row['symbol'])}</td><td>{escape(row['strategy_id'])}</td><td>{escape(row['timeframe'])}</td><td>{escape(row['direction'])}</td>"
        f"<td>{escape(row['hypothetical_entry_price'])}</td><td>{escape(row['hypothetical_stop_price'])}</td>"
        f"<td>{escape(row['hypothetical_target_price'])}</td><td>{escape(row['current_reference_price'])}</td>"
        f"<td>{escape(row['simulated_unrealized_pnl'])}</td><td>{escape(row['review_status'])}</td>"
        "</tr>"
        for row in trade_rows[:100]
    )
    queue_rows = "\n".join(
        "<tr>"
        f"<td>{escape(row['strategy_id'])}</td><td>{escape(row['strategy_title'])}</td><td>{escape(row['queue'])}</td>"
        f"<td>{escape(row['status'])}</td><td>{escape(row['latest_test_return_percent'])}</td>"
        f"<td>{escape(row['latest_test_win_rate_percent'])}</td><td>{escape(row['latest_test_max_drawdown_percent'])}</td>"
        f"<td>{escape(row['plain_reason'])}</td>"
        "</tr>"
        for row in summary["observation_queue"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>M12.25 每日只读测试看板</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #17202a; background: #f7f8fa; }}
    header {{ padding: 24px 32px 12px; background: #ffffff; border-bottom: 1px solid #dfe3e8; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    main {{ padding: 20px 32px 32px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 20px; }}
    .card {{ background: #ffffff; border: 1px solid #dfe3e8; border-radius: 8px; padding: 14px; }}
    .card div {{ color: #5f6b7a; font-size: 13px; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 22px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #dfe3e8; margin-bottom: 24px; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #e6e9ee; text-align: left; font-size: 13px; vertical-align: top; }}
    th {{ background: #eef2f6; }}
    .note {{ margin: 12px 0 20px; color: #5f6b7a; }}
  </style>
</head>
<body>
  <header>
    <h1>每日只读测试看板</h1>
    <p class="note">首页先看盈利、胜率、回撤和今日机会；全部数据都是模拟/假设，不是实际成交。</p>
  </header>
  <main>
    <div class="cards">{card_html}</div>
    <h2>今日机会明细</h2>
    <table>
      <thead><tr><th>股票</th><th>策略</th><th>周期</th><th>方向</th><th>假设入场</th><th>假设止损</th><th>假设目标</th><th>当前价</th><th>模拟盈亏</th><th>状态</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    <h2>策略队列</h2>
    <table>
      <thead><tr><th>策略</th><th>名称</th><th>队列</th><th>状态</th><th>最近收益率</th><th>最近胜率</th><th>最近最大回撤</th><th>说明</th></tr></thead>
      <tbody>{queue_rows}</tbody>
    </table>
  </main>
</body>
</html>
"""


def build_client_report(summary: dict[str, Any]) -> str:
    day = summary["current_day"]
    queue = {row["strategy_id"]: row for row in summary["observation_queue"]}
    pa007 = queue["M10-PA-007"]
    pa004 = queue["M10-PA-004"]
    return "\n".join(
        [
            "# M12.25 每日只读测试报告",
            "",
            "## 用人话结论",
            "",
            f"- 今天主线仍有 `{day['today_opportunity_count']}` 条可观察机会，当前估算盈亏 `{day['today_simulated_unrealized_pnl']}`，估算收益率 `{day['today_simulated_unrealized_return_percent']}%`。",
            f"- 连续记录现在是 `{summary['day_count_recorded']}/10` 天；因为没有新的交易日数据，本次不把记录天数硬加一。",
            f"- `M10-PA-007` 已加入观察队列：最近小范围测试收益 `{pa007['latest_test_return_percent']}%`，胜率 `{pa007['latest_test_win_rate_percent']}%`，最大回撤 `{pa007['latest_test_max_drawdown_percent']}%`。",
            f"- `M10-PA-004` 不进入每日观察：最近小范围测试收益 `{pa004['latest_test_return_percent']}%`，继续保留图形研究。",
            "- 当前没有真实成交、真实账户、真实下单，也没有批准模拟买卖试运行。",
            "",
            "## 接下来继续看什么",
            "",
            "- 主线继续累计 `M10-PA-001 / M10-PA-002 / M10-PA-012 / M12-FTD-001` 的每日记录。",
            "- `M10-PA-007` 先只看每日观察信号是否稳定，不直接计入模拟买卖准入。",
            "- 需要累计满 `10` 个交易日稳定看板记录后，才做 M11.6 模拟买卖试运行复查。",
        ]
    ) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "# M12.25 Handoff\n\n"
        "## 用人话结论\n\n"
        f"每日只读测试继续运行，连续记录为 `{summary['day_count_recorded']}/10`；"
        "`M10-PA-007` 已加入观察队列，`M10-PA-004` 不进入每日观察。\n\n"
        "## 下一步\n\n"
        "- M12.26：继续补数据缓存与 scanner 扩展，不能把缺数据股票放进可用候选。\n"
        "- 同步每日看板，直到累计满 10 个交易日后再做 M11.6 复查。\n"
    )


def decimal_percent_to_display(value: str) -> str:
    try:
        return str((Decimal(value) * HUNDRED).quantize(PERCENT, rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError):
        return value


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def project_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")
