#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M11_DIR = M10_DIR / "paper_gate" / "m11"
M10_12_SUMMARY = M10_DIR / "all_strategy_scorecard" / "m10_12" / "m10_12_all_strategy_scorecard_summary.json"
M10_13_QUEUE = M10_DIR / "read_only_observation" / "m10_13" / "m10_13_observation_candidate_queue.json"
M10_13_SUMMARY = M10_DIR / "read_only_observation" / "m10_13" / "m10_13_read_only_observation_runbook_summary.json"
FORBIDDEN_OUTPUT_STRINGS = ("PA-SC-", "SF-", "live-ready", "paper_trading_approval=true", "broker_connection=true", "real_orders=true")
TIER_A_CORE_POOL = ("M10-PA-001", "M10-PA-002", "M10-PA-012")
TIER_B_CONDITIONAL_VISUAL_POOL = ("M10-PA-008", "M10-PA-009")


def run_m11_paper_gate(output_dir: Path = M11_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    m10_12_summary = load_json(M10_12_SUMMARY)
    m10_13_queue = load_json(M10_13_QUEUE)
    m10_13_summary = load_json(M10_13_SUMMARY)
    candidate_list = build_candidate_list(m10_12_summary, m10_13_queue, m10_13_summary)
    policy = build_risk_policy(m10_13_queue)
    write_json(output_dir / "m11_candidate_strategy_list.json", candidate_list)
    write_report(output_dir / "m11_paper_gate_report.md", candidate_list, policy)
    write_policy(output_dir / "m11_risk_and_pause_policy.md", policy)
    summary = {
        "schema_version": "m11.paper-gate-summary.v1",
        "generated_at": "2026-04-27T00:00:00Z",
        "stage": "M11.paper_gate",
        "gate_decision": "not_approved",
        "paper_trading_approval": False,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "candidate_strategy_count": len(candidate_list["candidate_strategies"]),
        "candidate_strategy_ids": [item["strategy_id"] for item in candidate_list["candidate_strategies"]],
        "tier_a_core_candidate_count": len(candidate_list["candidate_groups"]["tier_a_core_after_read_only_observation"]),
        "tier_b_conditional_visual_candidate_count": len(candidate_list["candidate_groups"]["tier_b_conditional_visual_after_review"]),
        "blocking_condition_count": len(candidate_list["blocking_conditions"]),
        "output_dir": format_output_dir(output_dir),
    }
    write_json(output_dir / "m11_paper_gate_summary.json", summary)
    validate_outputs(output_dir)
    return summary


def build_candidate_list(m10_12_summary: dict[str, Any], m10_13_queue: dict[str, Any], m10_13_summary: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for item in m10_13_queue["primary_observation_queue"]:
        visual_required = bool(item["requires_visual_review_context"])
        strategy_id = item["strategy_id"]
        candidates.append(
            {
                "strategy_id": strategy_id,
                "title": item["title"],
                "candidate_tier": "paper_gate_candidate_after_visual_review" if visual_required else "paper_gate_candidate_after_read_only_observation",
                "client_gate_tier": client_gate_tier_for(strategy_id),
                "gate_evidence_status": gate_evidence_status_for(strategy_id),
                "counts_as_gate_evidence_now": False,
                "timeframes": item["timeframes"],
                "symbols": item["symbols"],
                "historical_metric_snapshot": item["historical_metric_snapshot"],
                "selected_timeframe_metrics": item["selected_timeframe_metrics"],
                "reserve_timeframes": item["reserve_timeframes"],
                "requires_visual_review_context": visual_required,
                "gate_status": "not_approved_pending_read_only_observation",
                "approval_blockers": approval_blockers_for(item),
                "risk_notes": risk_notes_for(item),
            }
        )
    return {
        "schema_version": "m11.candidate-strategy-list.v1",
        "generated_at": "2026-04-27T00:00:00Z",
        "stage": "M11.paper_gate",
        "input_refs": {
            "m10_12_summary": "reports/strategy_lab/m10_price_action_strategy_refresh/all_strategy_scorecard/m10_12/m10_12_all_strategy_scorecard_summary.json",
            "m10_13_queue": "reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_13/m10_13_observation_candidate_queue.json",
            "m10_13_summary": "reports/strategy_lab/m10_price_action_strategy_refresh/read_only_observation/m10_13/m10_13_read_only_observation_runbook_summary.json",
        },
        "boundaries": {
            "paper_simulated_only": True,
            "paper_trading_approval": False,
            "broker_connection": False,
            "real_orders": False,
            "live_execution": False,
        },
        "m10_12_portfolio_proxy": m10_12_summary["portfolio_proxy"],
        "m10_13_primary_strategy_ids": m10_13_summary["primary_strategy_ids"],
        "candidate_groups": {
            "tier_a_core_after_read_only_observation": list(TIER_A_CORE_POOL),
            "tier_b_conditional_visual_after_review": list(TIER_B_CONDITIONAL_VISUAL_POOL),
            "watchlist_deferred": ["M10-PA-003", "M10-PA-011", "M10-PA-013"],
            "blocked_definition_fix": ["M10-PA-004", "M10-PA-005", "M10-PA-007"],
            "not_independent_trigger_or_not_backtestable": ["M10-PA-006", "M10-PA-010", "M10-PA-014", "M10-PA-015", "M10-PA-016"],
        },
        "gate_evidence_policy": {
            "current_gate_evidence_accepted": False,
            "tier_a_can_be_reconsidered_after": [
                "completed_real_read_only_observation_window",
                "weekly_pause_redlines_checked",
                "human_business_approval",
            ],
            "tier_b_extra_requirements": [
                "manual_visual_context_review_closed",
                "visual_context_unresolved_not_triggered",
            ],
        },
        "candidate_strategies": candidates,
        "excluded_from_gate": {
            "definition_not_closed": ["M10-PA-005"],
            "non_positive_or_watchlist_only": ["M10-PA-003", "M10-PA-011", "M10-PA-013"],
            "visual_only_not_backtestable": ["M10-PA-010"],
            "supporting_only": ["M10-PA-014", "M10-PA-015"],
            "research_only": ["M10-PA-006", "M10-PA-016"],
            "needs_definition_fix": ["M10-PA-004", "M10-PA-007"],
        },
        "blocking_conditions": [
            "no_completed_real_read_only_observation_window",
            "no_human_business_approval_for_paper_trading",
            "visual_context_review_still_required_for_visual_candidates",
            "broker_connection_and_order_path_must_remain_disabled",
        ],
    }


def approval_blockers_for(item: dict[str, Any]) -> list[str]:
    blockers = ["no_completed_real_read_only_observation_window", "no_human_business_approval_for_paper_trading"]
    if item["requires_visual_review_context"]:
        blockers.append("manual_visual_context_review_required")
    return blockers


def client_gate_tier_for(strategy_id: str) -> str:
    if strategy_id in TIER_A_CORE_POOL:
        return "tier_a_core_after_read_only_observation"
    if strategy_id in TIER_B_CONDITIONAL_VISUAL_POOL:
        return "tier_b_conditional_visual_after_review"
    return "not_in_m11_candidate_pool"


def gate_evidence_status_for(strategy_id: str) -> str:
    if strategy_id in TIER_A_CORE_POOL:
        return "not_evidence_until_real_read_only_observation_is_reviewed"
    if strategy_id in TIER_B_CONDITIONAL_VISUAL_POOL:
        return "not_evidence_until_read_only_observation_and_manual_visual_review_are_closed"
    return "not_gate_evidence"


def risk_notes_for(item: dict[str, Any]) -> list[str]:
    strategy_id = item["strategy_id"]
    reserve_negative = [
        reserve["timeframe"]
        for reserve in item.get("reserve_timeframes", [])
        if str(reserve.get("return_percent", "")).startswith("-")
    ]
    if strategy_id == "M10-PA-001":
        return [
            "历史模拟收益为正，但回撤金额较高，且 1h reserve 为负；进入任何后续 gate 前必须先观察回撤和连续亏损。",
        ]
    if strategy_id == "M10-PA-002":
        return [
            "历史模拟优势较薄，且 5m reserve 为负；只适合作为观察候选，不可直接批准 paper trading。",
        ]
    if strategy_id == "M10-PA-012":
        return [
            "只覆盖 15m / 5m 开盘区间场景；15m 仍保留 derived_from_5m lineage，需要按 bar-close 节奏复核。",
        ]
    if strategy_id == "M10-PA-008":
        return [
            "视觉语境策略，必须完成人工图形复核；1d reserve 为负，不能把 OHLCV proxy 结果直接当作 gate evidence。",
        ]
    if strategy_id == "M10-PA-009":
        return [
            f"正收益幅度最弱，reserve 负周期为 {' / '.join(reserve_negative) or 'none'}；必须先完成视觉复核和只读观察。",
        ]
    return ["未纳入 M11 默认候选分级。"]


def build_risk_policy(m10_13_queue: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "m11.risk-and-pause-policy.v1",
        "stage": "M11.paper_gate",
        "policy_status": "draft_for_future_paper_only_not_active",
        "paper_trading_approval": False,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "capital_policy_if_later_approved": {
            "currency": "USD",
            "initial_capital": "100000.00",
            "risk_per_trade_percent_of_equity": "0.50",
            "max_simultaneous_risk_percent": "4.00",
            "max_simultaneous_positions": 8,
            "leverage_allowed": False,
            "real_orders_allowed": False,
        },
        "eligible_strategy_ids": [item["strategy_id"] for item in m10_13_queue["primary_observation_queue"]],
        "pause_conditions": m10_13_queue["pause_conditions"]
        + [
            {
                "code": "paper_gate_without_observation_results",
                "trigger": "paper trading is requested before a completed read-only observation review window exists",
                "action": "deny paper gate and continue read-only observation planning",
            },
            {
                "code": "manual_approval_missing",
                "trigger": "human business approval is missing",
                "action": "deny paper gate",
            },
            {
                "code": "candidate_status_downgrade",
                "trigger": "candidate strategy is downgraded to needs_definition_fix, needs_visual_review, or reject_for_now",
                "action": "remove from candidate list until fixed and re-reviewed",
            },
        ],
        "weekly_review_required_fields": m10_13_queue["weekly_report_requirements"],
    }


def write_report(path: Path, candidate_list: dict[str, Any], policy: dict[str, Any]) -> None:
    lines = [
        "# M11 Paper Gate Report",
        "",
        "## Gate Decision",
        "",
        "- decision: `not_approved`",
        "- paper trading 继续关闭。",
        "- broker connection、real account、live execution 和 real orders 继续禁用。",
        "- 当前没有任何候选策略可作为 paper trading approval evidence。",
        "",
        "## 候选分级",
        "",
        f"- Tier A 核心观察候选：`{' / '.join(candidate_list['candidate_groups']['tier_a_core_after_read_only_observation'])}`。",
        f"- Tier B 视觉条件候选：`{' / '.join(candidate_list['candidate_groups']['tier_b_conditional_visual_after_review'])}`，必须先完成人工图形语境复核。",
        "- Tier C/D/E 策略只保留在 watchlist、definition-fix、supporting 或 research-only 路径。",
        "",
        "## 候选策略",
        "",
        "| Strategy | Timeframes | Client Tier | Evidence Status | Blockers |",
        "|---|---|---|---|---|",
    ]
    for item in candidate_list["candidate_strategies"]:
        lines.append(
            f"| {item['strategy_id']} | `{' / '.join(item['timeframes'])}` | {item['client_gate_tier']} | {item['gate_evidence_status']} | `{' / '.join(item['approval_blockers'])}` |"
        )
    lines.extend(["", "## 候选风险点", ""])
    for item in candidate_list["candidate_strategies"]:
        for note in item["risk_notes"]:
            lines.append(f"- `{item['strategy_id']}`: {note}")
    lines.extend(
        [
            "",
            "## 为什么不批准",
            "",
        ]
    )
    for blocker in candidate_list["blocking_conditions"]:
        lines.append(f"- `{blocker}`")
    lines.extend(
        [
            "",
            "## 后续 Gate 条件",
            "",
            "- 先按 M10.13 runbook 完成至少一个真实只读观察复核窗口。",
            "- 对视觉候选策略完成人工图形语境复核。",
            "- 逐条检查暂停红线，任何 pause condition 命中都继续关闭 gate。",
            "- 确认候选策略没有因暂停条件被降级。",
            "- 在任何 paper trading 设置前取得明确人工业务审批。",
            "",
            "## 边界",
            "",
            "本报告只准备 gate review，不批准 paper trading，也不授权任何订单路径。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_policy(path: Path, policy: dict[str, Any]) -> None:
    lines = [
        "# M11 Risk And Pause Policy",
        "",
        "## Status",
        "",
        "- policy status: `draft_for_future_paper_only_not_active`",
        "- paper trading approval: `false`",
        "- broker connection: `false`",
        "- real orders: `false`",
        "- live execution: `false`",
        "",
        "## 后续如获批准才可使用的资金口径",
        "",
    ]
    for key, value in policy["capital_policy_if_later_approved"].items():
        lines.append(f"- {key}: `{str(value).lower() if isinstance(value, bool) else value}`")
    lines.extend(
        [
            "",
            "## 暂停条件",
            "",
            "| Code | Trigger | Action |",
            "|---|---|---|",
        ]
    )
    for item in policy["pause_conditions"]:
        lines.append(f"| {item['code']} | {item['trigger']} | {item['action']} |")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "本策略不是交易许可。任何 paper trading 或 broker setup 都需要单独明确审批。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in output_dir.glob("*"))
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_STRINGS:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


if __name__ == "__main__":
    run_m11_paper_gate()
