#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M10_12_DIR = M10_DIR / "all_strategy_scorecard" / "m10_12"
CATALOG_PATH = M10_DIR / "strategy_catalog_m10_frozen.json"
WAVE_A_METRICS = M10_DIR / "capital_backtest" / "m10_8_wave_a" / "m10_8_wave_a_metrics.csv"
M10_9_METRICS = M10_DIR / "definition_tightening" / "m10_9_pa_005" / "m10_9_before_after_metrics.csv"
WAVE_B_METRICS = M10_DIR / "capital_backtest" / "m10_11_wave_b" / "m10_11_wave_b_metrics.csv"
FORBIDDEN_OUTPUT_STRINGS = ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true")


STATUS_OVERRIDES = {
    "M10-PA-004": ("需要定义修正", "needs_definition_fix", "Broad channel boundary requires encoded channel anchors."),
    "M10-PA-006": ("research-only", "research_only", "BLSHS limit-order framework is not an independent trigger."),
    "M10-PA-007": ("需要定义修正", "needs_definition_fix", "Second-leg trap needs explicit leg/range-edge fields."),
    "M10-PA-010": ("图形复核保留", "visual_only_not_backtestable", "Final flag/climax/TBTL remains too composite for one trigger."),
    "M10-PA-014": ("只能辅助", "supporting_rule", "Measured move is a target module, not an entry trigger."),
    "M10-PA-015": ("只能辅助", "supporting_rule", "Stop and position sizing is a risk module, not an entry trigger."),
    "M10-PA-016": ("research-only", "research_only", "Trading range scaling remains research-only."),
}
PORTFOLIO_PRIORITY = ("M10-PA-001", "M10-PA-002", "M10-PA-012", "M10-PA-005", "M10-PA-013", "M10-PA-003", "M10-PA-008", "M10-PA-009", "M10-PA-011")
M10_7_REQUIRED_METRICS = (
    "initial_capital",
    "final_equity",
    "net_profit",
    "return_percent",
    "trade_count",
    "win_rate",
    "profit_factor",
    "max_drawdown",
    "max_drawdown_percent",
    "max_consecutive_losses",
    "average_win",
    "average_loss",
    "average_holding_bars",
    "best_symbol",
    "worst_symbol",
    "best_timeframe",
    "worst_timeframe",
)


def run_m10_12_all_strategy_scorecard(output_dir: Path = M10_12_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog = load_json(CATALOG_PATH)
    metrics_by_strategy = collect_strategy_metrics()
    rows = []
    for item in catalog["strategies"]:
        strategy_id = item["strategy_id"]
        rows.append(build_strategy_row(strategy_id, item["title"], metrics_by_strategy.get(strategy_id)))
    write_metrics(output_dir / "m10_12_all_strategy_metrics.csv", rows)
    decision_matrix = build_decision_matrix(rows)
    write_json(output_dir / "m10_12_strategy_decision_matrix.json", decision_matrix)
    portfolio = build_portfolio_proxy(rows)
    write_json(output_dir / "m10_12_portfolio_proxy_summary.json", portfolio)
    write_scorecard(output_dir / "m10_12_all_strategy_scorecard.md", rows)
    write_portfolio_report(output_dir / "m10_12_portfolio_simulation_report.md", portfolio)
    write_client_report(output_dir / "m10_12_client_final_report.md", rows, portfolio)
    summary = {
        "schema_version": "m10.12.all-strategy-scorecard-summary.v1",
        "generated_at": "2026-04-27T00:00:00Z",
        "stage": "M10.12.all_strategy_scorecard",
        "strategy_count": len(rows),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "paper_trading_approval": False,
        "status_counts": count_statuses(rows),
        "portfolio_proxy": portfolio,
        "output_dir": format_output_dir(output_dir),
    }
    write_json(output_dir / "m10_12_all_strategy_scorecard_summary.json", summary)
    validate_outputs(output_dir)
    return summary


def collect_strategy_metrics() -> dict[str, dict[str, str]]:
    metrics: dict[str, dict[str, str]] = {}
    for row in read_csv(WAVE_A_METRICS):
        if row["grain"] == "strategy" and row["cost_tier"] == "baseline" and row["strategy_id"] != "M10-PA-005":
            metrics[row["strategy_id"]] = row
    metrics["M10-PA-005"] = aggregate_m10_9_pa005()
    for row in read_csv(WAVE_B_METRICS):
        if row["grain"] == "strategy" and row["cost_tier"] == "baseline":
            metrics[row["strategy_id"]] = row
    return metrics


def aggregate_m10_9_pa005() -> dict[str, str]:
    rows = [row for row in read_csv(M10_9_METRICS) if row["strategy_id"] == "M10-PA-005" and row["cost_tier"] == "baseline"]
    initial = Decimal("400000") * Decimal(len(rows))
    net_profit = sum((Decimal(row["after_net_profit"]) for row in rows), Decimal("0"))
    trade_count = sum(int(row["after_trade_count"]) for row in rows)
    weighted_wins = sum(Decimal(row["after_win_rate"]) * Decimal(row["after_trade_count"]) for row in rows)
    max_drawdown = sum((Decimal(row["after_max_drawdown"]) for row in rows), Decimal("0"))
    return {
        "strategy_id": "M10-PA-005",
        "initial_capital": f"{initial:.2f}",
        "final_equity": f"{(initial + net_profit):.2f}",
        "net_profit": f"{net_profit:.2f}",
        "return_percent": f"{(net_profit / initial * Decimal('100')):.4f}",
        "trade_count": str(trade_count),
        "win_rate": f"{(weighted_wins / Decimal(trade_count)):.4f}" if trade_count else "0.0000",
        "profit_factor": "",
        "max_drawdown": "",
        "max_drawdown_percent": "",
        "max_consecutive_losses": "",
        "average_win": "",
        "average_loss": "",
        "average_holding_bars": "",
        "best_symbol": "",
        "worst_symbol": "",
        "best_timeframe": "",
        "worst_timeframe": "",
        "status": "needs_definition_fix",
        "metric_completeness": "partial_retest_metrics",
        "metric_gap_note": "M10.9 retest does not persist full M10.7 metric set or synchronized equity curves; strategy remains needs_definition_fix.",
    }


def build_strategy_row(strategy_id: str, title: str, metrics: dict[str, str] | None) -> dict[str, str]:
    if strategy_id in STATUS_OVERRIDES:
        client_status, machine_status, reason = STATUS_OVERRIDES[strategy_id]
    elif strategy_id == "M10-PA-005":
        client_status, machine_status, reason = ("需要定义修正", "needs_definition_fix", "Retested with tighter density; range geometry still missing.")
    elif metrics:
        client_status, machine_status, reason = ("已完成资金测试", "completed_capital_test", "Historical simulated capital metrics available.")
    else:
        client_status, machine_status, reason = ("暂不继续", "not_queued", "No current test queue assignment.")
    metric_completeness = "full_m10_7_required_metrics" if metrics and machine_status == "completed_capital_test" else (
        metrics.get("metric_completeness", "partial_retest_metrics") if metrics else "not_tested_or_not_entry_trigger"
    )
    metric_gap_note = "" if metric_completeness == "full_m10_7_required_metrics" else (
        metrics.get("metric_gap_note", "No completed independent capital test for this strategy status.") if metrics else "No completed independent capital test for this strategy status."
    )
    portfolio_eligible = machine_status == "completed_capital_test" and metric_completeness == "full_m10_7_required_metrics"
    portfolio_exclusion_reason = "" if portfolio_eligible else f"Excluded from M10.12 portfolio proxy because status is {machine_status}."
    row = {
        "strategy_id": strategy_id,
        "title": title,
        "client_status": client_status,
        "machine_status": machine_status,
        **{metric: metrics.get(metric, "") if metrics else "" for metric in M10_7_REQUIRED_METRICS},
        "metric_completeness": metric_completeness,
        "metric_gap_note": metric_gap_note,
        "portfolio_eligible": str(portfolio_eligible).lower(),
        "portfolio_exclusion_reason": portfolio_exclusion_reason,
        "decision_reason": reason,
    }
    return row


def build_decision_matrix(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": "m10.12.strategy-decision-matrix.v1",
        "stage": "M10.12.all_strategy_scorecard",
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "paper_trading_approval": False,
        "strategies": rows,
    }


def build_portfolio_proxy(rows: list[dict[str, str]]) -> dict[str, Any]:
    row_by_id = {row["strategy_id"]: row for row in rows}
    ordered = [row_by_id[strategy_id] for strategy_id in PORTFOLIO_PRIORITY if row_by_id.get(strategy_id)]
    selected = [row for row in ordered if row["portfolio_eligible"] == "true"][:8]
    excluded = [
        {
            "strategy_id": row["strategy_id"],
            "machine_status": row["machine_status"],
            "reason": row["portfolio_exclusion_reason"],
        }
        for row in ordered
        if row["portfolio_eligible"] != "true"
    ]
    returns = [Decimal(row["return_percent"]) for row in selected if row["return_percent"]]
    average_return = sum(returns, Decimal("0")) / Decimal(len(returns)) if returns else Decimal("0")
    initial = Decimal("100000")
    final = initial * (Decimal("1") + average_return / Decimal("100"))
    return {
        "schema_version": "m10.12.portfolio-proxy.v1",
        "portfolio_initial_capital": "100000.00",
        "max_simultaneous_risk_percent": "4.00",
        "max_simultaneous_positions": 8,
        "selection_rule": "completed_capital_test_only_in_priority_order",
        "requested_priority_order": list(PORTFOLIO_PRIORITY),
        "selected_strategy_ids": [row["strategy_id"] for row in selected],
        "excluded_priority_candidates": excluded,
        "proxy_method": "equal_weight_strategy_return_average_not_executable_concurrent_backtest",
        "average_strategy_return_percent": f"{average_return:.4f}",
        "proxy_final_equity": f"{final:.2f}",
        "proxy_net_profit": f"{(final - initial):.2f}",
        "not_executable_reason": "Existing artifacts are strategy-sleeve simulations, not one timestamp-synchronized portfolio order book.",
    }


def write_metrics(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "strategy_id",
        "title",
        "client_status",
        "machine_status",
        "initial_capital",
        "final_equity",
        "net_profit",
        "return_percent",
        "trade_count",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "max_drawdown_percent",
        "max_consecutive_losses",
        "average_win",
        "average_loss",
        "average_holding_bars",
        "best_symbol",
        "worst_symbol",
        "best_timeframe",
        "worst_timeframe",
        "metric_completeness",
        "metric_gap_note",
        "portfolio_eligible",
        "portfolio_exclusion_reason",
        "decision_reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_scorecard(path: Path, rows: list[dict[str, str]]) -> None:
    lines = [
        "# M10.12 All Strategy Scorecard",
        "",
        "## 16 条策略状态矩阵",
        "",
        "| ID | Strategy | Status | Net Profit | Return % | Trades | Win Rate | Max Drawdown |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['strategy_id']} | {row['title']} | {row['client_status']} | {row['net_profit'] or '-'} | "
            f"{row['return_percent'] or '-'} | {row['trade_count'] or '-'} | {row['win_rate'] or '-'} | {row['max_drawdown'] or '-'} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_portfolio_report(path: Path, portfolio: dict[str, Any]) -> None:
    lines = [
        "# M10.12 Portfolio Proxy Report",
        "",
        "## 摘要",
        "",
        f"- proxy initial capital: `{portfolio['portfolio_initial_capital']} USD`",
        f"- selected strategy sleeves: `{', '.join(portfolio['selected_strategy_ids'])}`",
        f"- excluded priority candidates: `{', '.join(item['strategy_id'] for item in portfolio['excluded_priority_candidates']) or 'none'}`",
        f"- proxy final equity: `{portfolio['proxy_final_equity']} USD`",
        f"- proxy net profit: `{portfolio['proxy_net_profit']} USD`",
        f"- average strategy return: `{portfolio['average_strategy_return_percent']}%`",
        "",
        "## 边界",
        "",
        "这是基于已完成资金测试策略层结果的 equal-weight proxy，不是按真实时间戳合并订单的可执行组合回测；`needs_definition_fix`、supporting 和 research-only 策略不进入 proxy。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_client_report(path: Path, rows: list[dict[str, str]], portfolio: dict[str, Any]) -> None:
    tested = [row for row in rows if row["machine_status"] == "completed_capital_test"]
    needs_fix = [row for row in rows if row["machine_status"] == "needs_definition_fix"]
    visual_only = [row for row in rows if row["machine_status"] == "visual_only_not_backtestable"]
    support = [row for row in rows if row["machine_status"] == "supporting_rule"]
    research = [row for row in rows if row["machine_status"] == "research_only"]
    lines = [
        "# M10.12 Client Final Report",
        "",
        "## 总结",
        "",
        f"- 总策略数：`{len(rows)}` 条。",
        f"- 已完成资金测试：`{len(tested)}` 条。",
        f"- 需要定义修正：`{len(needs_fix)}` 条。",
        f"- 图形复核保留：`{len(visual_only)}` 条。",
        f"- 只能辅助：`{len(support)}` 条。",
        f"- research-only：`{len(research)}` 条。",
        f"- portfolio proxy final equity: `{portfolio['proxy_final_equity']} USD`。",
        f"- portfolio proxy excludes: `{', '.join(item['strategy_id'] for item in portfolio['excluded_priority_candidates']) or 'none'}`。",
        "",
        "## 甲方下一步应看",
        "",
        "- `m10_12_all_strategy_metrics.csv`：每条策略一行的总矩阵。",
        "- `m10_12_portfolio_simulation_report.md`：组合 proxy 口径与结果。",
        "- M10.13 后续只读观察 runbook：只观察已完成资金测试且仍需继续验证的候选。",
        "",
        "## 边界",
        "",
        "本报告不批准 paper trading，不连接 broker，不生成真实订单；portfolio proxy 只纳入已完成资金测试策略，不纳入仍需定义修正的策略，也不是按真实时间戳合并订单的可执行组合回测。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def count_statuses(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["machine_status"]] = counts.get(row["machine_status"], 0) + 1
    return counts


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def format_output_dir(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def validate_outputs(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in [
            output_dir / "m10_12_all_strategy_scorecard_summary.json",
            output_dir / "m10_12_strategy_decision_matrix.json",
            output_dir / "m10_12_client_final_report.md",
        ]
        if path.exists()
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_STRINGS:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


if __name__ == "__main__":
    run_m10_12_all_strategy_scorecard()
