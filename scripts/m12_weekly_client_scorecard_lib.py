#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_weekly_client_scorecard.json"
M12_6_DIR = M10_DIR / "weekly_scorecard" / "m12_6"
FORBIDDEN_OUTPUT_STRINGS = ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true", "paper approval")
TIER_A_STRATEGIES = ("M10-PA-001", "M10-PA-002", "M10-PA-012")
VISUAL_PRIORITY = ("M10-PA-008", "M10-PA-009")
DEFINITION_QUEUE = ("M10-PA-004", "M10-PA-005", "M10-PA-007")
SUPPORTING_OR_RESEARCH = ("M10-PA-006", "M10-PA-014", "M10-PA-015", "M10-PA-016")


@dataclass(frozen=True, slots=True)
class ScorecardConfig:
    title: str
    run_id: str
    output_dir: Path
    m10_12_summary_path: Path
    m10_12_decision_matrix_path: Path
    m12_2_status_matrix_path: Path
    m12_3_visual_precheck_path: Path
    m12_4_definition_fix_summary_path: Path
    m12_5_scanner_summary_path: Path
    m12_5_scanner_candidates_path: Path


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def load_scorecard_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ScorecardConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    return ScorecardConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_6_weekly_client_scorecard"),
        output_dir=resolve_repo_path(payload["output_dir"]),
        m10_12_summary_path=resolve_repo_path(payload["m10_12_summary_path"]),
        m10_12_decision_matrix_path=resolve_repo_path(payload["m10_12_decision_matrix_path"]),
        m12_2_status_matrix_path=resolve_repo_path(payload["m12_2_status_matrix_path"]),
        m12_3_visual_precheck_path=resolve_repo_path(payload["m12_3_visual_precheck_path"]),
        m12_4_definition_fix_summary_path=resolve_repo_path(payload["m12_4_definition_fix_summary_path"]),
        m12_5_scanner_summary_path=resolve_repo_path(payload["m12_5_scanner_summary_path"]),
        m12_5_scanner_candidates_path=resolve_repo_path(payload["m12_5_scanner_candidates_path"]),
    )


def run_m12_weekly_client_scorecard(
    config: ScorecardConfig | None = None,
    *,
    generated_at: str = "2026-04-27T00:00:00Z",
) -> dict[str, Any]:
    config = config or load_scorecard_config()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    m10_12_summary = load_json(config.m10_12_summary_path)
    decision_matrix = load_json(config.m10_12_decision_matrix_path)
    observation_status = load_json(config.m12_2_status_matrix_path)
    visual_precheck = load_json(config.m12_3_visual_precheck_path)
    definition_summary = load_json(config.m12_4_definition_fix_summary_path)
    scanner_summary = load_json(config.m12_5_scanner_summary_path)
    scanner_candidates = read_csv(config.m12_5_scanner_candidates_path)

    dashboard_rows = build_dashboard_rows(
        decision_matrix=decision_matrix,
        observation_status=observation_status,
        visual_precheck=visual_precheck,
        definition_summary=definition_summary,
        scanner_candidates=scanner_candidates,
    )
    summary = build_summary(
        config=config,
        generated_at=generated_at,
        m10_12_summary=m10_12_summary,
        observation_status=observation_status,
        visual_precheck=visual_precheck,
        definition_summary=definition_summary,
        scanner_summary=scanner_summary,
        dashboard_rows=dashboard_rows,
    )

    write_dashboard(config.output_dir / "m12_6_strategy_dashboard.csv", dashboard_rows)
    (config.output_dir / "m12_6_weekly_client_scorecard.md").write_text(
        build_weekly_report(summary, dashboard_rows, scanner_candidates),
        encoding="utf-8",
    )
    (config.output_dir / "m12_6_next_week_action_plan.md").write_text(
        build_next_week_plan(summary, dashboard_rows),
        encoding="utf-8",
    )
    write_json(config.output_dir / "m12_6_weekly_client_scorecard_summary.json", summary)
    write_handoff(config.output_dir / "m12_6_handoff.md")
    assert_no_forbidden_output(config.output_dir)
    return summary


def build_dashboard_rows(
    *,
    decision_matrix: dict[str, Any],
    observation_status: dict[str, Any],
    visual_precheck: dict[str, Any],
    definition_summary: dict[str, Any],
    scanner_candidates: list[dict[str, str]],
) -> list[dict[str, str]]:
    observation_by_strategy = {item["strategy_id"]: item for item in observation_status.get("strategy_statuses", [])}
    visual_cases_by_strategy = Counter(row["strategy_id"] for row in visual_precheck.get("case_rows", []))
    visual_pending_by_strategy = Counter(
        row["strategy_id"]
        for row in visual_precheck.get("case_rows", [])
        if row.get("manual_review_status") == "agent_selected_pending_manual_review"
    )
    definition_by_strategy = {item["strategy_id"]: item for item in definition_summary.get("strategy_status", [])}
    scanner_counts = Counter(row["strategy_id"] for row in scanner_candidates)
    scanner_trigger_counts = Counter(row["strategy_id"] for row in scanner_candidates if row["candidate_status"] == "trigger_candidate")
    scanner_watch_counts = Counter(row["strategy_id"] for row in scanner_candidates if row["candidate_status"] == "watch_candidate")

    rows: list[dict[str, str]] = []
    for strategy in decision_matrix["strategies"]:
        strategy_id = strategy["strategy_id"]
        observation = observation_by_strategy.get(strategy_id, {})
        definition = definition_by_strategy.get(strategy_id, {})
        current_status, next_action, client_note = weekly_status_for(
            strategy,
            observation,
            visual_cases_by_strategy[strategy_id],
            scanner_counts[strategy_id],
            definition,
        )
        rows.append(
            {
                "strategy_id": strategy_id,
                "title": strategy["title"],
                "capital_test_status": strategy["machine_status"],
                "client_status": strategy["client_status"],
                "initial_capital": strategy.get("initial_capital", ""),
                "final_equity": strategy.get("final_equity", ""),
                "net_profit": strategy.get("net_profit", ""),
                "return_percent": strategy.get("return_percent", ""),
                "win_rate": strategy.get("win_rate", ""),
                "profit_factor": strategy.get("profit_factor", ""),
                "max_drawdown_percent": strategy.get("max_drawdown_percent", ""),
                "trade_count": strategy.get("trade_count", ""),
                "daily_observation_events": str(observation.get("event_count", 0)),
                "daily_candidate_events": str(observation.get("candidate_event_count", 0)),
                "daily_skip_no_trade": str(observation.get("skip_no_trade_count", 0)),
                "scanner_candidates": str(scanner_counts[strategy_id]),
                "scanner_trigger_candidates": str(scanner_trigger_counts[strategy_id]),
                "scanner_watch_candidates": str(scanner_watch_counts[strategy_id]),
                "visual_case_count": str(visual_cases_by_strategy[strategy_id]),
                "visual_pending_review_count": str(visual_pending_by_strategy[strategy_id]),
                "definition_status": definition.get("status", ""),
                "definition_retest_status": definition.get("retest_status", ""),
                "current_week_status": current_status,
                "next_week_action": next_action,
                "client_note": client_note,
            }
        )
    return rows


def weekly_status_for(
    strategy: dict[str, str],
    observation: dict[str, Any],
    visual_case_count: int,
    scanner_candidate_count: int,
    definition: dict[str, str],
) -> tuple[str, str, str]:
    strategy_id = strategy["strategy_id"]
    if strategy_id in TIER_A_STRATEGIES:
        if scanner_candidate_count:
            return (
                "continue_read_only_observation",
                "carry_scanner_candidates_into_weekly_review",
                "本周 scanner 有候选，但 M12.2 实际只读观察仍未产生完整策略触发。",
            )
        return (
            "continue_read_only_observation",
            "keep_bar_close_observation_running",
            "本周 M12.2 为 skip/no-trade；继续记录 bar-close 输入。",
        )
    if strategy_id in VISUAL_PRIORITY:
        return (
            "manual_visual_review_required",
            "user_review_priority_visual_cases",
            "图形预审包已准备，进入任何 gate 前仍需人工确认关键图例。",
        )
    if strategy_id in DEFINITION_QUEUE:
        reason = definition.get("reason", "definition fields are not closed")
        return ("definition_fix_required", "finish_definition_fields_before_retest", reason)
    if strategy_id in SUPPORTING_OR_RESEARCH:
        return (
            "not_independent_trigger",
            "keep_as_supporting_or_research",
            "当前不作为独立扫描或观察触发器。",
        )
    if strategy["machine_status"] == "completed_capital_test" and visual_case_count:
        return (
            "watchlist_after_priority_cases",
            "review_after_tier_a_and_priority_visual_cases",
            "已有资金测试，但不是本周自动观察主线。",
        )
    return (
        "not_current_week_focus",
        "keep_in_backlog",
        "当前阶段不进入自动观察或 scanner。",
    )


def build_summary(
    *,
    config: ScorecardConfig,
    generated_at: str,
    m10_12_summary: dict[str, Any],
    observation_status: dict[str, Any],
    visual_precheck: dict[str, Any],
    definition_summary: dict[str, Any],
    scanner_summary: dict[str, Any],
    dashboard_rows: list[dict[str, str]],
) -> dict[str, Any]:
    status_counts = Counter(row["current_week_status"] for row in dashboard_rows)
    return {
        "schema_version": "m12.weekly-client-scorecard-summary.v1",
        "generated_at": generated_at,
        "stage": "M12.6.weekly_client_scorecard",
        "run_id": config.run_id,
        "strategy_count": len(dashboard_rows),
        "input_refs": {
            "m10_12_summary": project_path(config.m10_12_summary_path),
            "m10_12_decision_matrix": project_path(config.m10_12_decision_matrix_path),
            "m12_2_status_matrix": project_path(config.m12_2_status_matrix_path),
            "m12_3_visual_precheck": project_path(config.m12_3_visual_precheck_path),
            "m12_4_definition_fix_summary": project_path(config.m12_4_definition_fix_summary_path),
            "m12_5_scanner_summary": project_path(config.m12_5_scanner_summary_path),
            "m12_5_scanner_candidates": project_path(config.m12_5_scanner_candidates_path),
        },
        "historical_capital_status_counts": m10_12_summary["status_counts"],
        "portfolio_proxy": m10_12_summary["portfolio_proxy"],
        "daily_observation": {
            "event_count": observation_status["event_count"],
            "candidate_event_count": observation_status["candidate_event_count"],
            "skip_no_trade_count": observation_status["skip_no_trade_count"],
            "tier_a_strategy_ids": observation_status["tier_a_strategy_ids"],
        },
        "scanner": {
            "universe_symbol_count": scanner_summary["universe_symbol_count"],
            "scanned_symbol_count": scanner_summary["scanned_symbol_count"],
            "candidate_count": scanner_summary["candidate_count"],
            "deferred_symbol_count": scanner_summary["deferred_symbol_count"],
            "strategy_candidate_counts": scanner_summary["strategy_candidate_counts"],
        },
        "visual_review": {
            "case_count": visual_precheck["case_count"],
            "priority_strategy_ids": list(VISUAL_PRIORITY),
            "manual_review_pending": True,
        },
        "definition_fix": {
            "pa005_definition_cleared": definition_summary["pa005_definition_cleared"],
            "strategy_ids": definition_summary["strategy_ids"],
        },
        "current_week_status_counts": dict(status_counts),
        "trading_status": "closed_not_authorized",
        "output_dir": project_path(config.output_dir),
    }


def build_weekly_report(summary: dict[str, Any], dashboard_rows: list[dict[str, str]], scanner_candidates: list[dict[str, str]]) -> str:
    lines = [
        "# M12.6 Weekly Client Scorecard",
        "",
        "## 本周总览",
        "",
        f"- 策略总数：{summary['strategy_count']} 条。",
        f"- 历史资金测试状态：{json.dumps(summary['historical_capital_status_counts'], ensure_ascii=False, sort_keys=True)}。",
        f"- 每日只读观察：{summary['daily_observation']['event_count']} 条记录，{summary['daily_observation']['candidate_event_count']} 条完整候选，{summary['daily_observation']['skip_no_trade_count']} 条 skip/no-trade。",
        f"- 选股扫描：股票池 {summary['scanner']['universe_symbol_count']} 只，本地缓存实际扫描 {summary['scanner']['scanned_symbol_count']} 只，候选 {summary['scanner']['candidate_count']} 条，deferred {summary['scanner']['deferred_symbol_count']} 只。",
        f"- 图形预审：{summary['visual_review']['case_count']} 个 Brooks v2 图例 case，仍待人工复核。",
        f"- 当前交易状态：`{summary['trading_status']}`。",
        "",
        "## 策略 Dashboard",
        "",
        "| Strategy | 状态 | 历史收益 | 胜率 | 最大回撤 | 本周观察 | Scanner | 下周动作 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in dashboard_rows:
        lines.append(
            f"| {row['strategy_id']} | {row['current_week_status']} | {fmt_percent(row['return_percent'])} | "
            f"{fmt_rate(row['win_rate'])} | {fmt_percent(row['max_drawdown_percent'])} | "
            f"{row['daily_observation_events']} | {row['scanner_candidates']} | {row['next_week_action']} |"
        )
    lines.extend(["", "## Scanner 候选", ""])
    if scanner_candidates:
        lines.extend(
            [
                "| Symbol | Strategy | Timeframe | Status | Direction | Entry | Stop | Target | Risk |",
                "|---|---|---|---|---|---:|---:|---:|---|",
            ]
        )
        for row in scanner_candidates:
            lines.append(
                f"| {row['symbol']} | {row['strategy_id']} | {row['timeframe']} | {row['candidate_status']} | "
                f"{row['signal_direction']} | {row['entry_price']} | {row['stop_price']} | {row['target_price']} | {row['risk_level']} |"
            )
    else:
        lines.append("- 本周无 scanner 候选。")
    lines.extend(
        [
            "",
            "## 甲方结论",
            "",
            "- Tier A 可以继续做每日只读观察和 scanner 候选跟踪。",
            "- `M10-PA-008/009` 仍需人工图形复核，不进入自动 scanner。",
            "- `M10-PA-004/005/007` 仍在定义修正队列。",
            "- 当前周报只用于模拟观察和测试管理，不作为交易批准。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_next_week_plan(summary: dict[str, Any], dashboard_rows: list[dict[str, str]]) -> str:
    tier_a_rows = [row for row in dashboard_rows if row["strategy_id"] in TIER_A_STRATEGIES]
    visual_rows = [row for row in dashboard_rows if row["strategy_id"] in VISUAL_PRIORITY]
    definition_rows = [row for row in dashboard_rows if row["strategy_id"] in DEFINITION_QUEUE]
    lines = [
        "# M12.6 Next Week Action Plan",
        "",
        "## 1. 每日只读观察",
        "",
        "- 继续跟踪 Tier A：`M10-PA-001 / M10-PA-002 / M10-PA-012`。",
        f"- 当前 M12.2 观察记录为 {summary['daily_observation']['event_count']} 条，完整候选为 {summary['daily_observation']['candidate_event_count']} 条；下一周重点是积累真实 bar-close 观察窗口。",
        "",
        "## 2. Scanner 覆盖扩展",
        "",
        f"- 当前股票池 {summary['scanner']['universe_symbol_count']} 只，只有 {summary['scanner']['scanned_symbol_count']} 只有本地缓存。",
        "- 下一步优先补齐 universe seed 的只读 K 线缓存或受控读取计划，再扩大日扫覆盖。",
        "",
        "## 3. 图形复核",
        "",
        f"- 优先复核：{', '.join(row['strategy_id'] for row in visual_rows)}。",
        "- 复核目标是确认 Brooks v2 图例语境是否能转成可执行定义，不替代人工判断。",
        "",
        "## 4. 定义修正",
        "",
        f"- 继续处理：{', '.join(row['strategy_id'] for row in definition_rows)}。",
        "- `M10-PA-005` 需要 range geometry 字段；`M10-PA-004/007` 需要边界、腿部和陷阱确认字段。",
        "",
        "## 5. M11.5 承接",
        "",
        "- 只有在周报输入完整、图形复核和定义 blocker 有明确状态后，才进入 M11.5 gate recheck。",
        "- M11.5 仍只做 gate 复查，不批准交易。",
    ]
    if tier_a_rows:
        lines.extend(["", "## Tier A 本周状态", "", "| Strategy | Observation | Scanner | Next |", "|---|---:|---:|---|"])
        for row in tier_a_rows:
            lines.append(f"| {row['strategy_id']} | {row['daily_observation_events']} | {row['scanner_candidates']} | {row['next_week_action']} |")
    return "\n".join(lines) + "\n"


def write_dashboard(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "strategy_id",
        "title",
        "capital_test_status",
        "client_status",
        "initial_capital",
        "final_equity",
        "net_profit",
        "return_percent",
        "win_rate",
        "profit_factor",
        "max_drawdown_percent",
        "trade_count",
        "daily_observation_events",
        "daily_candidate_events",
        "daily_skip_no_trade",
        "scanner_candidates",
        "scanner_trigger_candidates",
        "scanner_watch_candidates",
        "visual_case_count",
        "visual_pending_review_count",
        "definition_status",
        "definition_retest_status",
        "current_week_status",
        "next_week_action",
        "client_note",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_handoff(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "task_id: m12_6_weekly_client_scorecard",
                "role: implementer",
                "branch_or_worktree: feature/m12-6-weekly-client-scorecard",
                "objective: Build weekly client scorecard from M10/M12 artifacts.",
                "status: success",
                "files_changed:",
                "  - config/examples/m12_weekly_client_scorecard.json",
                "  - scripts/m12_weekly_client_scorecard_lib.py",
                "  - scripts/run_m12_weekly_client_scorecard.py",
                "  - tests/unit/test_m12_weekly_client_scorecard.py",
                "  - reports/strategy_lab/m10_price_action_strategy_refresh/weekly_scorecard/m12_6/",
                "interfaces_changed:",
                "  - M12.6 dashboard consumes signal_direction from M12.5 scanner candidates.",
                "commands_run:",
                "  - python scripts/run_m12_weekly_client_scorecard.py",
                "  - python -m unittest tests/unit/test_m12_weekly_client_scorecard.py -v",
                "tests_run:",
                "  - M12.6 unit tests passed.",
                "assumptions:",
                "  - Weekly scorecard summarizes existing artifacts and does not create new market signals.",
                "risks:",
                "  - Scanner coverage is still limited by local cache availability.",
                "qa_focus:",
                "  - Dashboard has one row per M10 strategy.",
                "  - Weekly report carries observation, scanner, visual, and definition status without trading approval.",
                "rollback_notes:",
                "  - Revert this milestone commit to remove M12.6 scorecard code and artifacts.",
                "next_recommended_action: Start M11.5 gate recheck after M12.6 is merged.",
                "needs_user_decision: false",
                "user_decision_needed:",
                "",
            ]
        ),
        encoding="utf-8",
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fmt_percent(value: str) -> str:
    if not value:
        return "-"
    try:
        return f"{Decimal(value):.2f}%"
    except (InvalidOperation, ValueError):
        return value


def fmt_rate(value: str) -> str:
    if not value:
        return "-"
    try:
        return f"{Decimal(value) * Decimal('100'):.2f}%"
    except (InvalidOperation, ValueError):
        return value


def project_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output_dir.glob("m12_6_*")
        if path.is_file()
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_STRINGS:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


if __name__ == "__main__":
    run_m12_weekly_client_scorecard()
