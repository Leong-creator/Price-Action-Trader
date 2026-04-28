#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M1212_DIR = M10_DIR / "daily_observation" / "m12_12_loop"
M1215_DIR = M10_DIR / "ftd_v02_ab_retest" / "m12_15"
M1216_DIR = M10_DIR / "source_candidate_test_plan" / "m12_16"
OUTPUT_DIR = M10_DIR / "daily_observation" / "m12_17_continuity"
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


def run_m12_17_daily_observation_continuity(
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
    trade_rows = read_csv(M1212_DIR / "m12_12_dashboard_trade_view.csv")
    strategy_scope = ["M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001"]
    filtered_trade_rows = [row for row in trade_rows if row["strategy_id"] in set(strategy_scope)]

    continuity_day = build_continuity_day(generated_at, dashboard, m12_12_summary, best_variant, filtered_trade_rows)
    summary = {
        "schema_version": "m12.17.daily-observation-continuity.v1",
        "stage": "M12.17.daily_observation_continuity",
        "generated_at": generated_at,
        "plain_language_result": "每日只读测试已形成第1个连续记录；还需要累计到10个交易日，才讨论模拟买卖试运行准入。",
        "day_count_recorded": 1,
        "required_day_count_for_paper_trial_review": 10,
        "days_remaining_for_paper_trial_review": 9,
        "daily_strategy_scope": strategy_scope,
        "selected_ftd_variant": best_variant["selected_variant_id"],
        "selected_ftd_variant_metrics": best_variant["metrics"],
        "source_candidate_queue_ref": project_path(M1216_DIR / "m12_16_daily_test_queue.json"),
        "current_day": continuity_day,
        "source_daily_loop_ref": project_path(M1212_DIR / "m12_12_loop_summary.json"),
        "source_dashboard_ref": project_path(M1212_DIR / "m12_12_dashboard_data.json"),
        "source_queue_rows": source_queue,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }

    write_json(output_dir / "m12_17_daily_observation_continuity_summary.json", summary)
    write_json(output_dir / "m12_17_dashboard_snapshot.json", build_dashboard_snapshot(summary, filtered_trade_rows))
    write_json(output_dir / "m12_17_observation_day_counter.json", {
        "schema_version": "m12.17.day-counter.v1",
        "recorded_trading_days": [continuity_day],
        "recorded_day_count": 1,
        "target_day_count": 10,
        "paper_trial_review_ready": False,
    })
    write_jsonl(output_dir / "m12_17_daily_observation_ledger.jsonl", build_ledger_rows(generated_at, filtered_trade_rows))
    write_csv(output_dir / "m12_17_today_trade_details.csv", build_trade_detail_rows(filtered_trade_rows))
    (output_dir / "m12_17_dashboard_snapshot.html").write_text(build_dashboard_html(summary, filtered_trade_rows), encoding="utf-8")
    (output_dir / "m12_17_daily_client_report.md").write_text(build_client_report(summary), encoding="utf-8")
    (output_dir / "m12_17_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def build_continuity_day(
    generated_at: str,
    dashboard: dict[str, Any],
    m12_12_summary: dict[str, Any],
    best_variant: dict[str, Any],
    trade_rows: list[dict[str, str]],
) -> dict[str, Any]:
    top = dashboard["top_metrics"]
    trade_summary = dashboard["trade_view_summary"]
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
        "ftd_baseline_return_percent": top["早期日线历史收益率"],
        "ftd_baseline_win_rate": top["早期日线历史胜率"],
        "ftd_baseline_max_drawdown_percent": top["早期日线最大回撤"],
        "ftd_selected_variant": best_variant["selected_variant_id"],
        "ftd_selected_variant_return_percent": best_variant["metrics"]["return_percent"],
        "ftd_selected_variant_win_rate": best_variant["metrics"]["win_rate"],
        "ftd_selected_variant_max_drawdown_percent": best_variant["metrics"]["max_drawdown_percent"],
        "strategy_rows": trade_summary["strategy_rows"],
        "trade_detail_count": len(trade_rows),
        "m12_12_observation_event_count": m12_12_summary["daily_loop"]["observation_event_count"],
        "status": "continue_observation",
        "pause_reason": "",
        "paper_trial_review_ready": False,
    }


def build_dashboard_snapshot(summary: dict[str, Any], trade_rows: list[dict[str, str]]) -> dict[str, Any]:
    day = summary["current_day"]
    return {
        "schema_version": "m12.17.dashboard-snapshot.v1",
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
        },
        "today_trade_rows": trade_rows,
        "paper_trial_review_ready": False,
        "paper_simulated_only": True,
    }


def build_ledger_rows(generated_at: str, trade_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for row in trade_rows:
        rows.append(
            {
                "schema_version": "m12.17.observation-ledger.v1",
                "stage": "M12.17.daily_observation_continuity",
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
                "real_orders": False,
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
    ]
    card_html = "\n".join(f"<section class='card'><div>{label}</div><strong>{value}</strong></section>" for label, value in top_cards)
    rows_html = "\n".join(
        "<tr>"
        f"<td>{row['symbol']}</td><td>{row['strategy_id']}</td><td>{row['timeframe']}</td><td>{row['direction']}</td>"
        f"<td>{row['hypothetical_entry_price']}</td><td>{row['hypothetical_stop_price']}</td>"
        f"<td>{row['hypothetical_target_price']}</td><td>{row['current_reference_price']}</td>"
        f"<td>{row['simulated_unrealized_pnl']}</td><td>{row['review_status']}</td>"
        "</tr>"
        for row in trade_rows[:80]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>M12.17 每日只读测试看板</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #17202a; background: #f7f8fa; }}
    header {{ padding: 24px 32px 12px; background: #ffffff; border-bottom: 1px solid #dfe3e8; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    main {{ padding: 20px 32px 32px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }}
    .card {{ background: #ffffff; border: 1px solid #dfe3e8; border-radius: 8px; padding: 14px; }}
    .card div {{ color: #5f6b7a; font-size: 13px; }}
    .card strong {{ display: block; margin-top: 6px; font-size: 22px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #dfe3e8; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #e6e9ee; text-align: left; font-size: 13px; }}
    th {{ background: #eef2f6; }}
    .note {{ margin: 12px 0 20px; color: #5f6b7a; }}
  </style>
</head>
<body>
  <header>
    <h1>每日只读测试看板</h1>
    <p class="note">只显示模拟/假设数据，不是实际成交，不连接真实账户。</p>
  </header>
  <main>
    <div class="cards">{card_html}</div>
    <h2>今日机会明细</h2>
    <table>
      <thead><tr><th>股票</th><th>策略</th><th>周期</th><th>方向</th><th>假设入场</th><th>假设止损</th><th>假设目标</th><th>当前价</th><th>模拟盈亏</th><th>状态</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </main>
</body>
</html>
"""


def build_client_report(summary: dict[str, Any]) -> str:
    day = summary["current_day"]
    return "\n".join(
        [
            "# M12.17 每日只读测试报告",
            "",
            "## 用人话结论",
            "",
            f"- 今天记录到 `{day['today_opportunity_count']}` 条可观察机会，当前估算盈亏 `{day['today_simulated_unrealized_pnl']}`，估算收益率 `{day['today_simulated_unrealized_return_percent']}%`。",
            f"- 早期强策略下一轮不用 baseline，改用 `{summary['selected_ftd_variant']}`：历史收益 `{day['ftd_selected_variant_return_percent']}%`，胜率 `{day['ftd_selected_variant_win_rate']}%`，最大回撤 `{day['ftd_selected_variant_max_drawdown_percent']}%`。",
            f"- 当前连续记录 `{summary['day_count_recorded']}/10` 天，还差 `{summary['days_remaining_for_paper_trial_review']}` 个交易日才够做模拟买卖试运行复查。",
            "- 当前没有真实成交、真实账户、真实下单。",
            "",
            "## 明天继续看什么",
            "",
            "- 继续跑 `M10-PA-001 / M10-PA-002 / M10-PA-012 / M12-FTD-001 pullback_guard`。",
            "- 重点看今日机会是否持续出现、估算盈亏是否稳定、是否出现数据缺口或重复信号。",
        ]
    ) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "# M12.17 Handoff\n\n"
        "## 用人话结论\n\n"
        "每日只读测试已有第1个连续记录；还需要累计10个交易日才能做模拟买卖试运行复查。\n\n"
        "## 下一步\n\n"
        "- M12.18：把 `M10-PA-008/009` 转成严格观察事件。\n"
        "- 继续每日生成本目录的看板快照和 ledger。\n"
    )


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
