#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_source_reextract_plan.json"
FORBIDDEN_OPERATIONS = (
    "broker_connection",
    "real_order",
    "live_execution",
    "paper_trading_approval",
    "manual_m12_37_once",
    "m13_registry_mutation",
    "m12_account_specs_mutation",
    "broker_readiness_status_mutation",
    "parameter_mutation",
)


@dataclass(frozen=True, slots=True)
class StrategySourceReextractPlanConfig:
    stage: str
    strategy_source_recheck_triage_path: Path
    source_reextract_plan_json_path: Path
    source_reextract_plan_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategySourceReextractPlanConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategySourceReextractPlanConfig(
        stage=str(payload["stage"]),
        strategy_source_recheck_triage_path=resolve_repo_path(
            inputs["m14_strategy_source_recheck_triage"]
        ),
        source_reextract_plan_json_path=resolve_repo_path(outputs["source_reextract_plan_json"]),
        source_reextract_plan_md_path=resolve_repo_path(outputs["source_reextract_plan_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategySourceReextractPlanConfig) -> None:
    if config.stage != "M14.strategy_source_reextract_plan":
        raise ValueError("M14 strategy source reextract plan stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy source reextract plan must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy source reextract plan must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy source reextract plan cannot enable {key}")


def run_m14_strategy_source_reextract_plan(
    config: StrategySourceReextractPlanConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    source_recheck = read_json(config.strategy_source_recheck_triage_path)
    plan_rows = [build_plan_row(dict(row)) for row in source_recheck.get("triage_rows", [])]
    plan_rows.sort(key=lambda row: (plan_state_rank(row["plan_state"]), row["priority"], row["strategy_id"]))
    summary = build_summary(source_recheck, plan_rows)
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-source-reextract-plan.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_source_recheck_triage": project_path(config.strategy_source_recheck_triage_path),
        },
        "summary": summary,
        "plan_rows": plan_rows,
        "plan_policy": {
            "purpose": "Turn source recheck triage rows into a bounded original-source review plan.",
            "allowed_now": "Prepare source-review tasks and future reextract questions from existing source refs.",
            "not_allowed_now": "No strategy creation, gap closure, promotion, discard, parameter mutation, registry/account mutation, broker/live path, paper approval, or manual M12.37 once-mode.",
            "completion_rule": "Candidate rows can receive future source-reextract specs only after source and visual review; this plan alone changes no strategy state.",
        },
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.source_reextract_plan_json_path, payload)
    config.source_reextract_plan_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.source_reextract_plan_md_path.write_text(build_plan_md(payload), encoding="utf-8")
    return payload


def build_plan_row(triage_row: dict[str, Any]) -> dict[str, Any]:
    strategy_id = str(triage_row.get("strategy_id", ""))
    triage_state = str(triage_row.get("triage_state", ""))
    plan_state = plan_state_for(triage_state)
    source_refs = list(triage_row.get("source_refs", []))
    can_draft_future_spec = plan_state == "future_source_reextract_candidate"
    return {
        "plan_id": f"source_reextract::{strategy_id}",
        "triage_id": str(triage_row.get("triage_id", "")),
        "review_id": str(triage_row.get("review_id", "")),
        "strategy_id": strategy_id,
        "display_name": str(triage_row.get("display_name", "")),
        "catalog_title": str(triage_row.get("catalog_title", "")),
        "priority": str(triage_row.get("priority", "")),
        "triage_state": triage_state,
        "plan_state": plan_state,
        "source_reextract_route": source_reextract_route_for(plan_state),
        "can_draft_future_source_reextract_spec": can_draft_future_spec,
        "source_review_tasks": source_review_tasks_for(strategy_id, str(triage_row.get("catalog_title", "")), plan_state),
        "source_review_questions": source_review_questions_for(strategy_id, str(triage_row.get("catalog_title", "")), plan_state),
        "source_refs_to_review": source_refs[:8],
        "source_ref_count": int_or_zero(triage_row.get("source_ref_count", len(source_refs))),
        "source_families": list(triage_row.get("source_families", [])),
        "prerequisites": list(triage_row.get("prerequisites", [])),
        "can_create_strategy_now": False,
        "can_close_gap_now": False,
        "can_promote_now": False,
        "can_discard_now": False,
        "parameter_mutation_allowed_now": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        **hard_boundaries(),
    }


def plan_state_for(triage_state: str) -> str:
    states = {
        "source_visual_recheck_candidate": "future_source_reextract_candidate",
        "research_only_risk_definition_hold": "research_only_hold_no_reextract",
        "supporting_rule_attach_to_parent": "supporting_rule_no_standalone_reextract",
        "external_reference_hold_no_local_strategy": "external_reference_hold",
        "source_recheck_hold_no_independent_evidence": "source_recheck_hold",
    }
    return states.get(triage_state, "source_recheck_hold")


def source_reextract_route_for(plan_state: str) -> str:
    routes = {
        "future_source_reextract_candidate": "original_source_and_visual_packet_review",
        "research_only_hold_no_reextract": "research_definition_hold",
        "supporting_rule_no_standalone_reextract": "attach_to_parent_setup_only",
        "external_reference_hold": "local_source_required_before_reextract",
        "source_recheck_hold": "hold_until_independent_source_evidence",
    }
    return routes.get(plan_state, routes["source_recheck_hold"])


def source_review_tasks_for(strategy_id: str, title: str, plan_state: str) -> list[str]:
    normalized = f"{strategy_id} {title}".lower()
    if plan_state == "future_source_reextract_candidate" and (
        strategy_id == "M10-PA-003" or "tight channel" in normalized
    ):
        return [
            "Re-read Brooks tight-channel and small-pullback trend units for independent setup context, signal bar, entry, stop, and target candidates.",
            "Recheck Fangfangtu channel refs and notes for visual examples; keep missing charts explicit when unavailable.",
            "Decide whether a future source-reextract spec can separate this setup from generic trend filter or ranking logic.",
        ]
    if plan_state == "future_source_reextract_candidate" and (
        strategy_id == "M10-PA-010" or "climax" in normalized or "final flag" in normalized
    ):
        return [
            "Re-read Brooks climax, final-flag, and TBTL refs for reversal trigger versus failed-breakout boundaries.",
            "Recheck Fangfangtu climax/exhaustion refs and notes for visual examples; separate final flag from generic exhaustion language.",
            "Decide whether a future source-reextract spec can be OHLCV-proxied or must remain visual-review first.",
        ]
    if plan_state == "research_only_hold_no_reextract":
        return [
            "Keep as research-only until bounded-risk, range maturity, and cost/slippage definitions are frozen.",
            "Do not draft a standalone source-reextract spec from risk framework language alone.",
        ]
    if plan_state == "supporting_rule_no_standalone_reextract":
        return [
            "Attach as target, stop, or sizing support to parent setups during future source review.",
            "Do not draft a standalone strategy spec unless a separate source-backed setup emerges later.",
        ]
    if plan_state == "external_reference_hold":
        return [
            "Keep as external architecture/reference input only.",
            "Require local source refs before any local source-reextract task can be opened.",
        ]
    return [
        "Hold until independent local source evidence is available.",
        "Do not create, promote, discard, or mutate strategy state from this row.",
    ]


def source_review_questions_for(strategy_id: str, title: str, plan_state: str) -> list[str]:
    normalized = f"{strategy_id} {title}".lower()
    if plan_state == "future_source_reextract_candidate" and (
        strategy_id == "M10-PA-003" or "tight channel" in normalized
    ):
        return [
            "Which bars define a tight channel versus an ordinary channel in the source material?",
            "What minimum pullback size or failure condition invalidates the trend-continuation read?",
            "Which visual examples can be approximated from OHLCV without chart-image confirmation?",
        ]
    if plan_state == "future_source_reextract_candidate" and (
        strategy_id == "M10-PA-010" or "climax" in normalized or "final flag" in normalized
    ):
        return [
            "Where do the sources separate climax, final flag, failed breakout, and TBTL reversal language?",
            "What confirmation must appear before any reversal entry is considered?",
            "Which examples require visual confirmation rather than OHLCV-only approximation?",
        ]
    if plan_state == "research_only_hold_no_reextract":
        return [
            "What concrete setup trigger is missing beyond risk or position-management language?",
            "What fresh evidence would make this more than a research-only framework?",
        ]
    if plan_state == "supporting_rule_no_standalone_reextract":
        return [
            "Which parent setup should consume this target, stop, or sizing rule?",
            "Can the supporting rule be tested only as an attachment rather than a standalone strategy?",
        ]
    if plan_state == "external_reference_hold":
        return [
            "Which local Brooks or Fangfangtu source refs would be required before this becomes a local task?",
            "Which parts are architecture inspiration only and must not override local evidence gates?",
        ]
    return [
        "What independent source evidence is missing?",
        "What future artifact should be produced before any strategy-state decision?",
    ]


def build_summary(source_recheck: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    triage_summary = source_recheck.get("summary", {})
    state_counts = Counter(row["plan_state"] for row in rows)
    return {
        "current_project_stage": str(triage_summary.get("current_project_stage", "")),
        "m14_trading_date": str(triage_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(triage_summary.get("challenge_progress_label", "")),
        "source_reextract_plan_row_count": len(rows),
        "future_source_reextract_candidate_count": state_counts.get(
            "future_source_reextract_candidate", 0
        ),
        "research_only_hold_no_reextract_count": state_counts.get(
            "research_only_hold_no_reextract", 0
        ),
        "supporting_rule_no_standalone_reextract_count": state_counts.get(
            "supporting_rule_no_standalone_reextract", 0
        ),
        "external_reference_hold_count": state_counts.get("external_reference_hold", 0),
        "source_recheck_hold_count": state_counts.get("source_recheck_hold", 0),
        "source_ref_review_task_count": sum(len(row["source_review_tasks"]) for row in rows),
        "source_review_question_count": sum(len(row["source_review_questions"]) for row in rows),
        "can_draft_future_source_reextract_spec_count": sum(
            row["can_draft_future_source_reextract_spec"] for row in rows
        ),
        "can_create_strategy_now_count": 0,
        "can_close_gap_now_count": 0,
        "can_promote_now_count": 0,
        "can_discard_now_count": 0,
        "parameter_mutation_allowed_now_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "plan_state_counts": dict(sorted(state_counts.items())),
    }


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Source reextract plan tracks {summary['source_reextract_plan_row_count']} source-triage rows. "
        f"{summary['future_source_reextract_candidate_count']} rows are future source-reextract candidates, "
        f"{summary['research_only_hold_no_reextract_count']} remain research-only holds, "
        f"{summary['supporting_rule_no_standalone_reextract_count']} are supporting-only attachments, and "
        f"{summary['external_reference_hold_count']} are external-reference holds. "
        f"The plan has {summary['source_ref_review_task_count']} source-review tasks and "
        f"{summary['source_review_question_count']} review questions. "
        "It cannot create strategies, close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live."
    )


def build_plan_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Source Reextract Plan",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Source reextract plan rows: `{summary['source_reextract_plan_row_count']}`",
        f"- Future source-reextract candidates: `{summary['future_source_reextract_candidate_count']}`",
        f"- Research/support/external holds: `{summary['research_only_hold_no_reextract_count']}/{summary['supporting_rule_no_standalone_reextract_count']}/{summary['external_reference_hold_count']}`",
        f"- Source-review tasks/questions: `{summary['source_ref_review_task_count']}/{summary['source_review_question_count']}`",
        f"- Create/close/promote/discard/mutate allowed now: `{summary['can_create_strategy_now_count']}/{summary['can_close_gap_now_count']}/{summary['can_promote_now_count']}/{summary['can_discard_now_count']}/{summary['parameter_mutation_allowed_now_count']}`",
        "- Boundary: source reextract planning only; no strategy creation, gap closure, broker/live, real orders, paper approval, parameter mutation, or manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Plan Rows",
        "",
    ]
    for row in payload["plan_rows"]:
        lines.extend(
            [
                f"### {row['priority']} {row['strategy_id']}",
                "",
                f"- State: `{row['plan_state']}`",
                f"- Route: `{row['source_reextract_route']}`",
                f"- Catalog title: `{row['catalog_title']}`",
                f"- Source families: `{', '.join(row['source_families'])}`",
                f"- Future source-reextract spec allowed to draft: `{row['can_draft_future_source_reextract_spec']}`",
                f"- Can create/close/promote/discard/mutate now: `{row['can_create_strategy_now']}/{row['can_close_gap_now']}/{row['can_promote_now']}/{row['can_discard_now']}/{row['parameter_mutation_allowed_now']}`",
                "- Tasks:",
            ]
        )
        lines.extend(f"  - {task}" for task in row["source_review_tasks"])
        lines.append("- Questions:")
        lines.extend(f"  - {question}" for question in row["source_review_questions"])
        lines.append("")
    return "\n".join(lines)


def plan_state_rank(plan_state: str) -> int:
    return {
        "future_source_reextract_candidate": 0,
        "research_only_hold_no_reextract": 1,
        "supporting_rule_no_standalone_reextract": 2,
        "external_reference_hold": 3,
        "source_recheck_hold": 4,
    }.get(plan_state, 9)


def hard_boundaries() -> dict[str, bool]:
    return {
        "paper_simulated_only": True,
        "internal_simulated_account": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "parameter_mutation": False,
    }


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
