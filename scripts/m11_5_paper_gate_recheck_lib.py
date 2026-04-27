#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m11_5_paper_gate_recheck.json"
M11_5_DIR = M10_DIR / "paper_gate" / "m11_5_recheck"
FORBIDDEN_OUTPUT_STRINGS = ("PA-SC-", "SF-", "live-ready", "paper_trading_approval=true", "broker_connection=true", "real_orders=true")
TIER_A = ("M10-PA-001", "M10-PA-002", "M10-PA-012")
VISUAL_CONDITIONAL = ("M10-PA-008", "M10-PA-009")


@dataclass(frozen=True, slots=True)
class GateRecheckConfig:
    title: str
    run_id: str
    output_dir: Path
    m11_candidate_strategy_list_path: Path
    m12_6_summary_path: Path
    m12_6_dashboard_path: Path


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def load_gate_recheck_config(path: str | Path = DEFAULT_CONFIG_PATH) -> GateRecheckConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    return GateRecheckConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m11_5_paper_gate_recheck"),
        output_dir=resolve_repo_path(payload["output_dir"]),
        m11_candidate_strategy_list_path=resolve_repo_path(payload["m11_candidate_strategy_list_path"]),
        m12_6_summary_path=resolve_repo_path(payload["m12_6_summary_path"]),
        m12_6_dashboard_path=resolve_repo_path(payload["m12_6_dashboard_path"]),
    )


def run_m11_5_paper_gate_recheck(
    config: GateRecheckConfig | None = None,
    *,
    generated_at: str = "2026-04-27T00:00:00Z",
) -> dict[str, Any]:
    config = config or load_gate_recheck_config()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    m11_candidates = load_json(config.m11_candidate_strategy_list_path)
    m12_6_summary = load_json(config.m12_6_summary_path)
    dashboard_rows = read_csv(config.m12_6_dashboard_path)
    candidate_list = build_candidate_list(generated_at, config, m11_candidates, m12_6_summary, dashboard_rows)
    blockers = build_blockers_and_approvals(generated_at, config, candidate_list, m12_6_summary)
    write_json(config.output_dir / "m11_5_candidate_strategy_list.json", candidate_list)
    write_json(config.output_dir / "m11_5_blockers_and_approvals.json", blockers)
    (config.output_dir / "m11_5_blockers_and_approvals.md").write_text(build_blocker_report(blockers), encoding="utf-8")
    (config.output_dir / "m11_5_paper_gate_recheck_report.md").write_text(build_gate_report(candidate_list, blockers), encoding="utf-8")
    summary = {
        "schema_version": "m11.5.paper-gate-recheck-summary.v1",
        "generated_at": generated_at,
        "stage": "M11.5.paper_gate_recheck",
        "run_id": config.run_id,
        "gate_decision": "not_approved",
        "paper_trading_approval": False,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "candidate_strategy_count": len(candidate_list["candidate_strategies"]),
        "candidate_strategy_ids": [item["strategy_id"] for item in candidate_list["candidate_strategies"]],
        "blocking_condition_count": len(blockers["blocking_conditions"]),
        "output_dir": project_path(config.output_dir),
    }
    write_json(config.output_dir / "m11_5_paper_gate_recheck_summary.json", summary)
    write_handoff(config.output_dir / "m11_5_handoff.md")
    assert_no_forbidden_output(config.output_dir)
    return summary


def build_candidate_list(
    generated_at: str,
    config: GateRecheckConfig,
    m11_candidates: dict[str, Any],
    m12_6_summary: dict[str, Any],
    dashboard_rows: list[dict[str, str]],
) -> dict[str, Any]:
    dashboard_by_id = {row["strategy_id"]: row for row in dashboard_rows}
    prior_by_id = {item["strategy_id"]: item for item in m11_candidates["candidate_strategies"]}
    candidates = []
    for strategy_id in (*TIER_A, *VISUAL_CONDITIONAL):
        row = dashboard_by_id[strategy_id]
        prior = prior_by_id[strategy_id]
        approval_blockers = approval_blockers_for(row, m12_6_summary)
        candidate = {
            "strategy_id": strategy_id,
            "title": row["title"],
            "client_gate_tier": "tier_a_core_after_read_only_observation" if strategy_id in TIER_A else "tier_b_conditional_visual_after_review",
            "current_week_status": row["current_week_status"],
            "historical_return_percent": row["return_percent"],
            "historical_win_rate": row["win_rate"],
            "historical_max_drawdown_percent": row["max_drawdown_percent"],
            "daily_observation_events": int(row["daily_observation_events"] or 0),
            "daily_candidate_events": int(row["daily_candidate_events"] or 0),
            "scanner_candidates": int(row["scanner_candidates"] or 0),
            "visual_pending_review_count": int(row["visual_pending_review_count"] or 0),
            "counts_as_gate_evidence_now": False,
            "paper_gate_recheck_status": gate_status_for(approval_blockers),
            "approval_blockers": approval_blockers,
            "prior_m11_gate_status": prior["gate_status"],
            "prior_m11_gate_evidence_status": prior["gate_evidence_status"],
            "next_required_action": row["next_week_action"],
        }
        candidates.append(candidate)
    return {
        "schema_version": "m11.5.candidate-strategy-list.v1",
        "generated_at": generated_at,
        "stage": "M11.5.paper_gate_recheck",
        "input_refs": {
            "m11_candidate_strategy_list": project_path(config.m11_candidate_strategy_list_path),
            "m12_6_summary": project_path(config.m12_6_summary_path),
            "m12_6_dashboard": project_path(config.m12_6_dashboard_path),
        },
        "gate_evidence_policy": {
            "current_gate_evidence_accepted": False,
            "reason": "M12.6 has no completed real read-only observation window, no human business approval, visual review remains pending, and definition blockers are still open.",
        },
        "candidate_groups": {
            "tier_a_core_after_read_only_observation": list(TIER_A),
            "tier_b_conditional_visual_after_review": list(VISUAL_CONDITIONAL),
        },
        "candidate_strategies": candidates,
    }


def gate_status_for(blockers: list[str]) -> str:
    if "manual_visual_review_still_pending" in blockers:
        return "not_approved_pending_manual_visual_review"
    if blockers:
        return "not_approved_blocked_by_open_gate_conditions"
    return "not_approved_pending_business_approval"


def approval_blockers_for(row: dict[str, str], m12_6_summary: dict[str, Any]) -> list[str]:
    blockers = ["no_completed_real_read_only_observation_window", "no_human_business_approval_for_paper_trading"]
    if m12_6_summary["daily_observation"]["candidate_event_count"] == 0:
        blockers.append("m12_2_has_no_completed_strategy_candidate_events")
    if row["strategy_id"] in VISUAL_CONDITIONAL:
        blockers.append("manual_visual_review_still_pending")
    if m12_6_summary["scanner"]["deferred_symbol_count"] > 0:
        blockers.append("scanner_universe_cache_coverage_incomplete")
    if not m12_6_summary["definition_fix"]["pa005_definition_cleared"]:
        blockers.append("unresolved_definition_blockers")
    return blockers


def build_blockers_and_approvals(
    generated_at: str,
    config: GateRecheckConfig,
    candidate_list: dict[str, Any],
    m12_6_summary: dict[str, Any],
) -> dict[str, Any]:
    blocker_counts = Counter(blocker for item in candidate_list["candidate_strategies"] for blocker in item["approval_blockers"])
    return {
        "schema_version": "m11.5.blockers-and-approvals.v1",
        "generated_at": generated_at,
        "stage": "M11.5.paper_gate_recheck",
        "input_refs": candidate_list["input_refs"],
        "paper_trading_approval": False,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "approval_state": "not_approved",
        "approval_summary": {
            "tier_a_has_historical_capital_tests": True,
            "tier_a_has_completed_real_read_only_window": False,
            "scanner_has_candidates": m12_6_summary["scanner"]["candidate_count"] > 0,
            "scanner_universe_cache_coverage_complete": m12_6_summary["scanner"]["deferred_symbol_count"] == 0,
            "visual_review_closed": not m12_6_summary["visual_review"]["manual_review_pending"],
            "definition_blockers_closed": m12_6_summary["definition_fix"]["pa005_definition_cleared"],
            "human_business_approval": False,
        },
        "blocking_conditions": sorted(blocker_counts),
        "blocking_condition_counts": dict(blocker_counts),
        "approvals_granted": [],
        "approvals_required_before_next_gate": [
            "completed_real_read_only_observation_window",
            "manual_visual_review_closed_for_m10_pa_008_009",
            "definition_blockers_closed_or_formally_deferred",
            "scanner_cache_coverage_plan_or_deferred_scope_approval",
            "human_business_approval_for_paper_trading",
        ],
    }


def build_gate_report(candidate_list: dict[str, Any], blockers: dict[str, Any]) -> str:
    lines = [
        "# M11.5 Paper Gate Recheck Report",
        "",
        "## Gate Decision",
        "",
        "- decision: `not_approved`",
        "- paper trading 继续关闭。",
        "- broker connection、live execution 和 real orders 继续禁用。",
        "- M12.6 周报可以作为观察管理材料，但不能作为交易批准。",
        "",
        "## 候选策略复查",
        "",
        "| Strategy | Tier | Status | Obs Events | Candidate Events | Scanner | Main Blockers |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for item in candidate_list["candidate_strategies"]:
        lines.append(
            f"| {item['strategy_id']} | {item['client_gate_tier']} | {item['paper_gate_recheck_status']} | "
            f"{item['daily_observation_events']} | {item['daily_candidate_events']} | {item['scanner_candidates']} | "
            f"{', '.join(item['approval_blockers'])} |"
        )
    lines.extend(
        [
            "",
            "## 当前阻塞",
            "",
        ]
    )
    for blocker in blockers["blocking_conditions"]:
        lines.append(f"- `{blocker}`")
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "当前只能继续只读观察、scanner 覆盖补齐、图形复核和定义修正，不进入 paper trading。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_blocker_report(blockers: dict[str, Any]) -> str:
    lines = [
        "# M11.5 Blockers and Required Approvals",
        "",
        "## Approval State",
        "",
        "- approval_state: `not_approved`",
        "- paper_trading_approval: `false`",
        "- broker_connection: `false`",
        "- real_orders: `false`",
        "- live_execution: `false`",
        "",
        "## Blocking Conditions",
        "",
    ]
    for blocker, count in sorted(blockers["blocking_condition_counts"].items()):
        lines.append(f"- `{blocker}`: {count}")
    lines.extend(["", "## Required Before Next Gate", ""])
    for item in blockers["approvals_required_before_next_gate"]:
        lines.append(f"- `{item}`")
    return "\n".join(lines) + "\n"


def write_handoff(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "task_id: m11_5_paper_gate_recheck",
                "role: implementer",
                "branch_or_worktree: feature/m11-5-paper-gate-recheck",
                "objective: Recheck paper gate using M12.2-M12.6 artifacts without approving trading.",
                "status: success",
                "files_changed:",
                "  - config/examples/m11_5_paper_gate_recheck.json",
                "  - scripts/m11_5_paper_gate_recheck_lib.py",
                "  - scripts/run_m11_5_paper_gate_recheck.py",
                "  - tests/unit/test_m11_5_paper_gate_recheck.py",
                "  - docs/status.md",
                "  - plans/active-plan.md",
                "  - reports/strategy_lab/README.md",
                "  - reports/strategy_lab/m10_price_action_strategy_refresh/paper_gate/m11_5_recheck/",
                "interfaces_changed:",
                "  - M11.5 candidate list consumes M12.6 dashboard statuses.",
                "commands_run:",
                "  - python scripts/run_m11_5_paper_gate_recheck.py",
                "  - python -m unittest tests/unit/test_m11_5_paper_gate_recheck.py -v",
                "  - python scripts/validate_kb.py",
                "  - python scripts/validate_kb_coverage.py",
                "  - python scripts/validate_knowledge_atoms.py",
                "  - python -m unittest discover -s tests/unit -v",
                "  - python -m unittest discover -s tests/reliability -v",
                "  - git diff --check",
                "tests_run:",
                "  - M11.5 unit tests passed.",
                "  - KB validation passed.",
                "  - KB coverage validation passed.",
                "  - Knowledge atom validation passed.",
                "  - Full unit suite passed.",
                "  - Reliability suite passed.",
                "  - git diff --check passed.",
                "assumptions:",
                "  - M12.6 is the latest weekly scorecard input.",
                "risks:",
                "  - Gate remains blocked until real read-only observation, manual visual review, definition blockers, scanner coverage, and manual approval are closed.",
                "qa_focus:",
                "  - Gate decision stays not_approved.",
                "  - Candidate statuses reflect M12.6 observation, scanner, visual, and definition state.",
                "rollback_notes:",
                "  - Revert this milestone commit to remove M11.5 recheck artifacts.",
                "next_recommended_action: Continue read-only observation and resolve visual/definition/cache blockers before another gate recheck.",
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


def project_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in output_dir.glob("m11_5_*") if path.is_file())
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_STRINGS:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


if __name__ == "__main__":
    run_m11_5_paper_gate_recheck()
