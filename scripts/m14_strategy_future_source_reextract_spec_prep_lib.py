#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_future_source_reextract_spec_prep.json"
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
    "strategy_state_mutation",
    "legacy_historical_profit_planning_input",
)


@dataclass(frozen=True, slots=True)
class StrategyFutureSourceReextractSpecPrepConfig:
    stage: str
    strategy_source_reextract_review_path: Path
    strategy_source_visual_confirmation_response_gate_path: Path
    future_source_reextract_spec_prep_json_path: Path
    future_source_reextract_spec_prep_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategyFutureSourceReextractSpecPrepConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategyFutureSourceReextractSpecPrepConfig(
        stage=str(payload["stage"]),
        strategy_source_reextract_review_path=resolve_repo_path(
            inputs["m14_strategy_source_reextract_review"]
        ),
        strategy_source_visual_confirmation_response_gate_path=resolve_repo_path(
            inputs["m14_strategy_source_visual_confirmation_response_gate"]
        ),
        future_source_reextract_spec_prep_json_path=resolve_repo_path(
            outputs["future_source_reextract_spec_prep_json"]
        ),
        future_source_reextract_spec_prep_md_path=resolve_repo_path(
            outputs["future_source_reextract_spec_prep_md"]
        ),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategyFutureSourceReextractSpecPrepConfig) -> None:
    if config.stage != "M14.strategy_future_source_reextract_spec_prep":
        raise ValueError("M14 strategy future source reextract spec prep stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy future source reextract spec prep must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError(
            "M14 strategy future source reextract spec prep must keep internal simulated accounts enabled"
        )
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy future source reextract spec prep cannot enable {key}")


def run_m14_strategy_future_source_reextract_spec_prep(
    config: StrategyFutureSourceReextractSpecPrepConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    review = read_json(config.strategy_source_reextract_review_path)
    response_gate = read_json(config.strategy_source_visual_confirmation_response_gate_path)
    response_rows_by_strategy = {
        str(row.get("strategy_id", "")): dict(row)
        for row in response_gate.get("response_gate_rows", [])
    }
    prep_rows = [
        build_prep_row(dict(row), response_rows_by_strategy.get(str(row.get("strategy_id", "")), {}))
        for row in review.get("review_rows", [])
        if row.get("can_draft_future_source_reextract_spec")
    ]
    prep_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    summary = build_summary(review, response_gate, prep_rows)
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-future-source-reextract-spec-prep.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_source_reextract_review": project_path(
                config.strategy_source_reextract_review_path
            ),
            "m14_strategy_source_visual_confirmation_response_gate": project_path(
                config.strategy_source_visual_confirmation_response_gate_path
            ),
        },
        "summary": summary,
        "future_source_reextract_spec_prep_rows": prep_rows,
        "spec_prep_policy": {
            "purpose": "Prepare conditional future source-reextract spec drafts from source review and visual confirmation gates.",
            "allowed_now": "Carry source-backed atoms into conditional draft scaffolds and list the visual/manual gates required before activation.",
            "not_allowed_now": "No strategy creation, gap closure, promotion, discard, parameter mutation, registry/account mutation, broker/live path, paper approval, manual M12.37 once-mode, or legacy historical profit planning input.",
            "completion_rule": "A row can move to manual M14 draft review only after all visual questions and cases are confirmed with evidence.",
        },
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.future_source_reextract_spec_prep_json_path, payload)
    config.future_source_reextract_spec_prep_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.future_source_reextract_spec_prep_md_path.write_text(build_prep_md(payload), encoding="utf-8")
    return payload


def build_prep_row(review_row: dict[str, Any], response_row: dict[str, Any]) -> dict[str, Any]:
    strategy_id = str(review_row.get("strategy_id", ""))
    question_gate_rows = list(response_row.get("question_gate_rows", []))
    case_gate_rows = list(response_row.get("case_gate_rows", []))
    pending_question_ids = [
        str(row.get("question_id", ""))
        for row in question_gate_rows
        if row.get("blocks_future_spec", True)
    ]
    pending_case_ids = [
        str(row.get("case_id", ""))
        for row in case_gate_rows
        if row.get("blocks_future_spec", True)
    ]
    unblocked = bool(response_row.get("future_spec_unblocked_after_manual_confirmation", False))
    if unblocked:
        draft_state = "ready_for_manual_m14_draft_review"
    elif int_or_zero(response_row.get("rejected_or_unclear_response_count")):
        draft_state = "blocked_until_manual_visual_confirmation_repaired"
    else:
        draft_state = "blocked_until_manual_visual_confirmation"
    source_atoms = list(review_row.get("source_backed_atoms", []))
    source_review_answers = list(review_row.get("source_review_answers", []))
    return {
        "prep_id": f"future_source_reextract_spec_prep::{strategy_id}",
        "future_spec_id": f"{strategy_id}-future-source-reextract-v0",
        "strategy_id": strategy_id,
        "catalog_title": str(review_row.get("catalog_title", "")),
        "priority": str(review_row.get("priority", "")),
        "draft_state": draft_state,
        "future_spec_gate_state": str(
            response_row.get("future_spec_gate_state", "blocked_until_manual_visual_confirmation_recorded")
        ),
        "setup_hypothesis": str(review_row.get("setup_hypothesis", "")),
        "future_spec_readiness": str(review_row.get("future_spec_readiness", "")),
        "source_backed_atom_count": len(source_atoms),
        "source_review_answer_count": len(source_review_answers),
        "source_backed_atoms": source_atoms,
        "source_review_answers": source_review_answers,
        "source_refs_reviewed": list(review_row.get("source_refs_reviewed", [])),
        "candidate_entry_logic": logic_from_atoms(source_atoms, "entry_trigger"),
        "candidate_exit_logic": logic_from_atoms(source_atoms, "target_management")
        or logic_from_atoms(source_atoms, "risk_management"),
        "candidate_invalidation_logic": logic_from_atoms(source_atoms, "invalidation"),
        "ohlcv_proxy_assessment": dict(review_row.get("ohlcv_proxy_assessment", {})),
        "visual_confirmation_required": True,
        "manual_visual_confirmation_complete": unblocked,
        "manual_confirmation_pending_question_ids": pending_question_ids,
        "manual_confirmation_pending_case_ids": pending_case_ids,
        "manual_confirmation_pending_count": len(pending_question_ids) + len(pending_case_ids),
        "required_before_activation": required_before_activation(
            pending_question_ids=pending_question_ids,
            pending_case_ids=pending_case_ids,
            unblocked=unblocked,
        ),
        "planning_input_policy": {
            "legacy_historical_profit_planning_input": False,
            "legacy_bug_profit_metric_display_only": True,
            "decision_basis": "source_atoms_visual_confirmation_internal_sim_evidence_only",
        },
        "conditional_spec_draft": {
            "state": draft_state,
            "setup": str(review_row.get("setup_hypothesis", "")),
            "entry": logic_from_atoms(source_atoms, "entry_trigger"),
            "exit_or_risk": logic_from_atoms(source_atoms, "target_management")
            or logic_from_atoms(source_atoms, "risk_management"),
            "invalidation": logic_from_atoms(source_atoms, "invalidation"),
            "proxy_fields": proxy_fields(review_row),
            "activation_boundary": "manual_visual_confirmation_and_manual_m14_review_required_before_strategy_state_change",
        },
        "can_create_strategy_now": False,
        "can_close_gap_now": False,
        "can_promote_now": False,
        "can_discard_now": False,
        "parameter_mutation_allowed_now": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "legacy_historical_profit_planning_input": False,
        **hard_boundaries(),
    }


def required_before_activation(
    *,
    pending_question_ids: list[str],
    pending_case_ids: list[str],
    unblocked: bool,
) -> list[str]:
    requirements = []
    if not unblocked:
        requirements.extend(f"manual_visual_question::{item}" for item in pending_question_ids)
        requirements.extend(f"manual_visual_case::{item}" for item in pending_case_ids)
    requirements.extend(
        [
            "manual_m14_draft_review",
            "strategy_state_change_review",
            "simulated_backtest_or_shadow_spec_before_runtime_use",
            "m12_47_supervised_readonly_refresh_before_any_gate_closure",
        ]
    )
    return requirements


def logic_from_atoms(source_atoms: list[dict[str, Any]], field: str) -> str:
    for atom in source_atoms:
        if atom.get("field") == field:
            return str(atom.get("implementation_hint") or atom.get("extracted_rule") or "")
    return ""


def proxy_fields(review_row: dict[str, Any]) -> list[str]:
    assessment = dict(review_row.get("ohlcv_proxy_assessment", {}))
    return [str(item) for item in assessment.get("approximable_fields", [])]


def build_summary(
    review: dict[str, Any],
    response_gate: dict[str, Any],
    prep_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    review_summary = review.get("summary", {})
    response_summary = response_gate.get("summary", {})
    return {
        "current_project_stage": str(review_summary.get("current_project_stage", "")),
        "m14_trading_date": str(review_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(review_summary.get("challenge_progress_label", "")),
        "future_source_reextract_spec_prep_row_count": len(prep_rows),
        "candidate_strategy_count": len({row["strategy_id"] for row in prep_rows}),
        "source_backed_atom_count": sum(row["source_backed_atom_count"] for row in prep_rows),
        "source_review_answer_count": sum(row["source_review_answer_count"] for row in prep_rows),
        "manual_visual_confirmation_complete_count": int_or_zero(
            response_summary.get("manual_visual_confirmation_complete_count")
        ),
        "future_spec_unblocked_count": sum(row["manual_visual_confirmation_complete"] for row in prep_rows),
        "blocked_until_manual_visual_confirmation_count": sum(
            row["draft_state"] != "ready_for_manual_m14_draft_review" for row in prep_rows
        ),
        "conditional_spec_draft_count": len(prep_rows),
        "manual_confirmation_pending_count": sum(
            row["manual_confirmation_pending_count"] for row in prep_rows
        ),
        "strategy_creation_allowed_count": 0,
        "can_close_gap_now_count": 0,
        "can_promote_now_count": 0,
        "can_discard_now_count": 0,
        "parameter_mutation_allowed_now_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "strategy_state_mutation_allowed": False,
        "legacy_historical_profit_planning_input_count": sum(
            row["legacy_historical_profit_planning_input"] for row in prep_rows
        ),
        "source_review_row_count": int_or_zero(review_summary.get("source_reextract_review_row_count")),
        "response_gate_row_count": int_or_zero(
            response_summary.get("source_visual_confirmation_response_gate_row_count")
        ),
    }


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Future source-reextract spec prep produced {summary['future_source_reextract_spec_prep_row_count']} conditional draft rows "
        f"from {summary['source_backed_atom_count']} source-backed atoms and {summary['source_review_answer_count']} source-review answers. "
        f"{summary['future_spec_unblocked_count']} rows are unblocked for manual M14 draft review, while "
        f"{summary['blocked_until_manual_visual_confirmation_count']} remain blocked until manual visual confirmation. "
        f"Legacy historical profit planning inputs remain {summary['legacy_historical_profit_planning_input_count']}. "
        "The prep cannot create strategies, close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live."
    )


def build_prep_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Future Source Reextract Spec Prep",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Prep rows / candidates: `{summary['future_source_reextract_spec_prep_row_count']}/{summary['candidate_strategy_count']}`",
        f"- Source atoms / answers: `{summary['source_backed_atom_count']}/{summary['source_review_answer_count']}`",
        f"- Conditional drafts / unblocked / blocked: `{summary['conditional_spec_draft_count']}/{summary['future_spec_unblocked_count']}/{summary['blocked_until_manual_visual_confirmation_count']}`",
        f"- Manual confirmation pending count: `{summary['manual_confirmation_pending_count']}`",
        f"- Strategy create/close/promote/discard/mutate allowed now: `{summary['strategy_creation_allowed_count']}/{summary['can_close_gap_now_count']}/{summary['can_promote_now_count']}/{summary['can_discard_now_count']}/{summary['parameter_mutation_allowed_now_count']}`",
        f"- Legacy historical profit planning inputs: `{summary['legacy_historical_profit_planning_input_count']}`",
        "- Boundary: conditional future spec prep only; no strategy creation, gap closure, broker/live, real orders, paper approval, parameter mutation, legacy historical profit planning input, or manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Prep Rows",
        "",
    ]
    for row in payload["future_source_reextract_spec_prep_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} {row['catalog_title']}",
                "",
                f"- Future spec id: `{row['future_spec_id']}`",
                f"- Draft state: `{row['draft_state']}`",
                f"- Setup hypothesis: `{row['setup_hypothesis']}`",
                f"- Entry logic: {row['candidate_entry_logic']}",
                f"- Exit/risk logic: {row['candidate_exit_logic']}",
                f"- Invalidation logic: {row['candidate_invalidation_logic']}",
                f"- Pending visual confirmations: `{row['manual_confirmation_pending_count']}`",
                f"- Legacy historical profit planning input: `{row['legacy_historical_profit_planning_input']}`",
                "",
            ]
        )
    return "\n".join(lines)


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
        "strategy_state_mutation": False,
        "legacy_historical_profit_planning_input": False,
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
