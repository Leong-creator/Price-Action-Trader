#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_source_visual_confirmation_response_gate.json"
ALLOWED_MANUAL_RESPONSES = {"pending", "confirmed", "rejected", "unclear"}
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
)


@dataclass(frozen=True, slots=True)
class StrategySourceVisualConfirmationResponseGateConfig:
    stage: str
    strategy_source_visual_confirmation_packet_path: Path
    manual_visual_confirmation_response_path: Path
    source_visual_confirmation_response_gate_json_path: Path
    source_visual_confirmation_response_gate_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
) -> StrategySourceVisualConfirmationResponseGateConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategySourceVisualConfirmationResponseGateConfig(
        stage=str(payload["stage"]),
        strategy_source_visual_confirmation_packet_path=resolve_repo_path(
            inputs["m14_strategy_source_visual_confirmation_packet"]
        ),
        manual_visual_confirmation_response_path=resolve_repo_path(
            inputs["manual_visual_confirmation_response"]
        ),
        source_visual_confirmation_response_gate_json_path=resolve_repo_path(
            outputs["source_visual_confirmation_response_gate_json"]
        ),
        source_visual_confirmation_response_gate_md_path=resolve_repo_path(
            outputs["source_visual_confirmation_response_gate_md"]
        ),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategySourceVisualConfirmationResponseGateConfig) -> None:
    if config.stage != "M14.strategy_source_visual_confirmation_response_gate":
        raise ValueError("M14 strategy source visual confirmation response gate stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy source visual confirmation response gate must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy source visual confirmation response gate must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy source visual confirmation response gate cannot enable {key}")


def run_m14_strategy_source_visual_confirmation_response_gate(
    config: StrategySourceVisualConfirmationResponseGateConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    packet = read_json(config.strategy_source_visual_confirmation_packet_path)
    response_created = False
    if config.manual_visual_confirmation_response_path.exists():
        response = read_json(config.manual_visual_confirmation_response_path)
    else:
        response = build_response_scaffold(packet, generated_at, config)
        write_json(config.manual_visual_confirmation_response_path, response)
        response_created = True
    validate_response_against_packet(response, packet)
    response_rows_by_strategy = {
        str(row.get("strategy_id", "")): dict(row)
        for row in response.get("response_rows", [])
    }
    gate_rows = [
        build_gate_row(dict(packet_row), response_rows_by_strategy.get(str(packet_row.get("strategy_id", "")), {}))
        for packet_row in packet.get("packet_rows", [])
    ]
    gate_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    summary = build_summary(packet, gate_rows, response_created, config)
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-source-visual-confirmation-response-gate.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_source_visual_confirmation_packet": project_path(
                config.strategy_source_visual_confirmation_packet_path
            ),
            "manual_visual_confirmation_response": project_path(
                config.manual_visual_confirmation_response_path
            ),
        },
        "summary": summary,
        "response_gate_rows": gate_rows,
        "response_gate_policy": {
            "purpose": "Validate manual visual confirmation responses before any future source-reextract spec can be drafted.",
            "allowed_now": "Create a pending response scaffold when absent and verify confirmed/rejected/unclear responses when present.",
            "not_allowed_now": "No strategy creation, gap closure, promotion, discard, parameter mutation, registry/account mutation, broker/live path, paper approval, or manual M12.37 once-mode.",
            "completion_rule": "A future source-reextract spec is only unblocked when every question and case response is confirmed with evidence_checked=true.",
        },
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.source_visual_confirmation_response_gate_json_path, payload)
    config.source_visual_confirmation_response_gate_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.source_visual_confirmation_response_gate_md_path.write_text(build_gate_md(payload), encoding="utf-8")
    return payload


def build_response_scaffold(
    packet: dict[str, Any],
    generated_at: str,
    config: StrategySourceVisualConfirmationResponseGateConfig,
) -> dict[str, Any]:
    return {
        "schema_version": "m14.strategy-source-visual-confirmation-response.v1",
        "stage": "M14.strategy_source_visual_confirmation_response",
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_source_visual_confirmation_packet": project_path(
                config.strategy_source_visual_confirmation_packet_path
            ),
        },
        "response_policy": {
            "allowed_manual_response_values": sorted(ALLOWED_MANUAL_RESPONSES),
            "confirmation_rule": "Use confirmed only after the referenced visual evidence has been checked; keep pending, rejected, or unclear when not fully confirmed.",
            "boundary": "This response file records manual visual review only; it does not create strategies, mutate parameters, approve paper trading, or enable broker/live.",
        },
        "response_rows": [
            build_response_scaffold_row(dict(row))
            for row in packet.get("packet_rows", [])
        ],
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }


def build_response_scaffold_row(packet_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": str(packet_row.get("strategy_id", "")),
        "packet_id": str(packet_row.get("packet_id", "")),
        "catalog_title": str(packet_row.get("catalog_title", "")),
        "manual_reviewer": "",
        "manual_reviewed_at": "",
        "response_state": "pending_manual_review",
        "question_responses": [
            {
                "question_id": str(item.get("question_id", "")),
                "manual_response": "pending",
                "evidence_checked": False,
                "review_note": "",
            }
            for item in packet_row.get("confirmation_items", [])
        ],
        "case_responses": [
            {
                "case_id": str(case.get("case_id", "")),
                "case_type": str(case.get("case_type", "")),
                "manual_response": "pending",
                "evidence_checked": False,
                "review_note": "",
            }
            for case in packet_row.get("case_confirmation_rows", [])
        ],
    }


def build_gate_row(packet_row: dict[str, Any], response_row: dict[str, Any]) -> dict[str, Any]:
    question_responses = {
        str(item.get("question_id", "")): dict(item)
        for item in response_row.get("question_responses", [])
    }
    case_responses = {
        str(item.get("case_id", "")): dict(item)
        for item in response_row.get("case_responses", [])
    }
    question_rows = [
        build_question_gate_row(dict(item), question_responses.get(str(item.get("question_id", "")), {}))
        for item in packet_row.get("confirmation_items", [])
    ]
    case_rows = [
        build_case_gate_row(dict(item), case_responses.get(str(item.get("case_id", "")), {}))
        for item in packet_row.get("case_confirmation_rows", [])
    ]
    invalid_response_count = sum(row["invalid_response"] for row in question_rows + case_rows)
    rejected_or_unclear_count = sum(
        row["manual_response"] in {"rejected", "unclear"} for row in question_rows + case_rows
    )
    all_questions_confirmed = bool(question_rows) and all(row["confirmed_with_evidence"] for row in question_rows)
    all_cases_confirmed = bool(case_rows) and all(row["confirmed_with_evidence"] for row in case_rows)
    future_spec_unblocked = all_questions_confirmed and all_cases_confirmed and invalid_response_count == 0
    if future_spec_unblocked:
        response_gate_state = "manual_visual_confirmation_complete"
        future_spec_gate_state = "ready_for_future_source_reextract_spec_draft_review"
    elif rejected_or_unclear_count:
        response_gate_state = "manual_visual_confirmation_rejected_or_unclear"
        future_spec_gate_state = "blocked_until_manual_visual_confirmation_recorded"
    else:
        response_gate_state = "pending_manual_visual_confirmation"
        future_spec_gate_state = "blocked_until_manual_visual_confirmation_recorded"
    strategy_id = str(packet_row.get("strategy_id", ""))
    question_confirmed_count = sum(row["confirmed_with_evidence"] for row in question_rows)
    question_pending_count = sum(row["manual_response"] == "pending" for row in question_rows)
    question_rejected_count = sum(row["manual_response"] == "rejected" for row in question_rows)
    question_unclear_count = sum(row["manual_response"] == "unclear" for row in question_rows)
    case_confirmed_count = sum(row["confirmed_with_evidence"] for row in case_rows)
    case_pending_count = sum(row["manual_response"] == "pending" for row in case_rows)
    case_rejected_count = sum(row["manual_response"] == "rejected" for row in case_rows)
    case_unclear_count = sum(row["manual_response"] == "unclear" for row in case_rows)
    return {
        "response_gate_id": f"source_visual_confirmation_response_gate::{strategy_id}",
        "packet_id": str(packet_row.get("packet_id", "")),
        "strategy_id": strategy_id,
        "catalog_title": str(packet_row.get("catalog_title", "")),
        "priority": str(packet_row.get("priority", "")),
        "response_gate_state": response_gate_state,
        "manual_visual_confirmation_state": response_gate_state,
        "future_spec_gate_state": future_spec_gate_state,
        "manual_reviewer": str(response_row.get("manual_reviewer", "")),
        "manual_reviewed_at": str(response_row.get("manual_reviewed_at", "")),
        "required_question_response_count": len(question_rows),
        "confirmed_question_response_count": question_confirmed_count,
        "pending_question_response_count": question_pending_count,
        "rejected_question_response_count": question_rejected_count,
        "unclear_question_response_count": question_unclear_count,
        "question_response_required_count": len(question_rows),
        "question_response_confirmed_count": question_confirmed_count,
        "question_response_pending_count": question_pending_count,
        "question_response_rejected_count": question_rejected_count,
        "question_response_unclear_count": question_unclear_count,
        "required_case_response_count": len(case_rows),
        "confirmed_case_response_count": case_confirmed_count,
        "pending_case_response_count": case_pending_count,
        "rejected_case_response_count": case_rejected_count,
        "unclear_case_response_count": case_unclear_count,
        "case_response_required_count": len(case_rows),
        "case_response_confirmed_count": case_confirmed_count,
        "case_response_pending_count": case_pending_count,
        "case_response_rejected_count": case_rejected_count,
        "case_response_unclear_count": case_unclear_count,
        "rejected_or_unclear_response_count": rejected_or_unclear_count,
        "invalid_response_count": invalid_response_count,
        "future_spec_unblocked_after_manual_confirmation": future_spec_unblocked,
        "ready_for_future_source_reextract_spec_draft": future_spec_unblocked,
        "question_gate_rows": question_rows,
        "case_gate_rows": case_rows,
        "can_create_strategy_now": False,
        "can_close_gap_now": False,
        "can_promote_now": False,
        "can_discard_now": False,
        "parameter_mutation_allowed_now": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        **hard_boundaries(),
    }


def build_question_gate_row(packet_item: dict[str, Any], response_item: dict[str, Any]) -> dict[str, Any]:
    manual_response = str(response_item.get("manual_response", "pending"))
    validate_manual_response(manual_response)
    evidence_checked = bool(response_item.get("evidence_checked", False))
    return {
        "question_id": str(packet_item.get("question_id", "")),
        "question": str(packet_item.get("question", "")),
        "acceptance_signal": str(packet_item.get("acceptance_signal", "")),
        "manual_response": manual_response,
        "evidence_checked": evidence_checked,
        "review_note": str(response_item.get("review_note", "")),
        "confirmed_with_evidence": manual_response == "confirmed" and evidence_checked,
        "invalid_response": False,
        "blocks_future_spec": manual_response != "confirmed" or not evidence_checked,
    }


def build_case_gate_row(packet_case: dict[str, Any], response_item: dict[str, Any]) -> dict[str, Any]:
    manual_response = str(response_item.get("manual_response", "pending"))
    validate_manual_response(manual_response)
    evidence_checked = bool(response_item.get("evidence_checked", False))
    return {
        "case_id": str(packet_case.get("case_id", "")),
        "case_type": str(packet_case.get("case_type", "")),
        "expected_visual_role": str(packet_case.get("expected_visual_role", "")),
        "resolved_evidence_path": str(packet_case.get("resolved_evidence_path", "")),
        "manual_response": manual_response,
        "evidence_checked": evidence_checked,
        "review_note": str(response_item.get("review_note", "")),
        "confirmed_with_evidence": manual_response == "confirmed" and evidence_checked,
        "invalid_response": False,
        "blocks_future_spec": manual_response != "confirmed" or not evidence_checked,
    }


def validate_manual_response(value: str) -> None:
    if value not in ALLOWED_MANUAL_RESPONSES:
        raise ValueError(f"Invalid manual visual confirmation response: {value}")


def validate_response_against_packet(response: dict[str, Any], packet: dict[str, Any]) -> None:
    packet_rows_by_strategy = {
        str(row.get("strategy_id", "")): dict(row)
        for row in packet.get("packet_rows", [])
    }
    for response_row in response.get("response_rows", []):
        strategy_id = str(response_row.get("strategy_id", ""))
        if strategy_id not in packet_rows_by_strategy:
            raise ValueError(f"Unknown manual visual confirmation strategy_id: {strategy_id}")
        packet_row = packet_rows_by_strategy[strategy_id]
        question_ids = {str(item.get("question_id", "")) for item in packet_row.get("confirmation_items", [])}
        case_ids = {str(item.get("case_id", "")) for item in packet_row.get("case_confirmation_rows", [])}
        validate_response_items(
            response_row.get("question_responses", []),
            expected_ids=question_ids,
            id_key="question_id",
            strategy_id=strategy_id,
        )
        validate_response_items(
            response_row.get("case_responses", []),
            expected_ids=case_ids,
            id_key="case_id",
            strategy_id=strategy_id,
        )


def validate_response_items(
    response_items: Any,
    *,
    expected_ids: set[str],
    id_key: str,
    strategy_id: str,
) -> None:
    observed_ids: set[str] = set()
    for item in response_items or []:
        item_id = str(item.get(id_key, ""))
        if item_id in observed_ids:
            raise ValueError(f"Duplicate manual visual confirmation {id_key}: {strategy_id} {item_id}")
        observed_ids.add(item_id)
        if item_id not in expected_ids:
            raise ValueError(f"Unknown manual visual confirmation {id_key}: {strategy_id} {item_id}")
        validate_manual_response(str(item.get("manual_response", "pending")))


def build_summary(
    packet: dict[str, Any],
    gate_rows: list[dict[str, Any]],
    response_created: bool,
    config: StrategySourceVisualConfirmationResponseGateConfig,
) -> dict[str, Any]:
    packet_summary = packet.get("summary", {})
    return {
        "current_project_stage": str(packet_summary.get("current_project_stage", "")),
        "m14_trading_date": str(packet_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(packet_summary.get("challenge_progress_label", "")),
        "manual_visual_confirmation_response_path": project_path(
            config.manual_visual_confirmation_response_path
        ),
        "manual_visual_confirmation_response_created": response_created,
        "response_scaffold_created": response_created,
        "source_visual_confirmation_response_gate_row_count": len(gate_rows),
        "candidate_strategy_count": len({row["strategy_id"] for row in gate_rows}),
        "required_question_response_count": sum(row["required_question_response_count"] for row in gate_rows),
        "confirmed_question_response_count": sum(row["confirmed_question_response_count"] for row in gate_rows),
        "pending_question_response_count": sum(row["pending_question_response_count"] for row in gate_rows),
        "rejected_question_response_count": sum(row["rejected_question_response_count"] for row in gate_rows),
        "unclear_question_response_count": sum(row["unclear_question_response_count"] for row in gate_rows),
        "question_response_required_count": sum(row["question_response_required_count"] for row in gate_rows),
        "question_response_confirmed_count": sum(row["question_response_confirmed_count"] for row in gate_rows),
        "question_response_pending_count": sum(row["question_response_pending_count"] for row in gate_rows),
        "question_response_rejected_count": sum(row["question_response_rejected_count"] for row in gate_rows),
        "question_response_unclear_count": sum(row["question_response_unclear_count"] for row in gate_rows),
        "required_case_response_count": sum(row["required_case_response_count"] for row in gate_rows),
        "confirmed_case_response_count": sum(row["confirmed_case_response_count"] for row in gate_rows),
        "pending_case_response_count": sum(row["pending_case_response_count"] for row in gate_rows),
        "rejected_case_response_count": sum(row["rejected_case_response_count"] for row in gate_rows),
        "unclear_case_response_count": sum(row["unclear_case_response_count"] for row in gate_rows),
        "case_response_required_count": sum(row["case_response_required_count"] for row in gate_rows),
        "case_response_confirmed_count": sum(row["case_response_confirmed_count"] for row in gate_rows),
        "case_response_pending_count": sum(row["case_response_pending_count"] for row in gate_rows),
        "case_response_rejected_count": sum(row["case_response_rejected_count"] for row in gate_rows),
        "case_response_unclear_count": sum(row["case_response_unclear_count"] for row in gate_rows),
        "rejected_or_unclear_response_count": sum(row["rejected_or_unclear_response_count"] for row in gate_rows),
        "invalid_response_count": sum(row["invalid_response_count"] for row in gate_rows),
        "fully_confirmed_strategy_count": sum(
            row["response_gate_state"] == "manual_visual_confirmation_complete" for row in gate_rows
        ),
        "manual_visual_confirmation_complete_count": sum(
            row["manual_visual_confirmation_state"] == "manual_visual_confirmation_complete"
            for row in gate_rows
        ),
        "future_spec_unblocked_count": sum(
            row["future_spec_unblocked_after_manual_confirmation"] for row in gate_rows
        ),
        "ready_for_future_source_reextract_spec_draft_count": sum(
            row["ready_for_future_source_reextract_spec_draft"] for row in gate_rows
        ),
        "can_create_strategy_now_count": 0,
        "can_close_gap_now_count": 0,
        "can_promote_now_count": 0,
        "can_discard_now_count": 0,
        "parameter_mutation_allowed_now_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "strategy_state_mutation_allowed": False,
    }


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Source visual confirmation response gate checked {summary['source_visual_confirmation_response_gate_row_count']} strategy rows. "
        f"Confirmed questions/cases are {summary['confirmed_question_response_count']}/{summary['required_question_response_count']} and "
        f"{summary['confirmed_case_response_count']}/{summary['required_case_response_count']}; "
        f"{summary['future_spec_unblocked_count']} future specs are unblocked and "
        f"{summary['pending_question_response_count'] + summary['pending_case_response_count']} responses remain pending. "
        "The gate cannot create strategies, close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live."
    )


def build_gate_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Source Visual Confirmation Response Gate",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Response file: `{summary['manual_visual_confirmation_response_path']}`",
        f"- Response file created this run: `{summary['manual_visual_confirmation_response_created']}`",
        f"- Gate rows / strategies: `{summary['source_visual_confirmation_response_gate_row_count']}/{summary['candidate_strategy_count']}`",
        f"- Questions confirmed/required/pending: `{summary['confirmed_question_response_count']}/{summary['required_question_response_count']}/{summary['pending_question_response_count']}`",
        f"- Cases confirmed/required/pending: `{summary['confirmed_case_response_count']}/{summary['required_case_response_count']}/{summary['pending_case_response_count']}`",
        f"- Rejected-or-unclear / invalid responses: `{summary['rejected_or_unclear_response_count']}/{summary['invalid_response_count']}`",
        f"- Future specs unblocked / ready-for-draft: `{summary['future_spec_unblocked_count']}/{summary['ready_for_future_source_reextract_spec_draft_count']}`",
        f"- Create/close/promote/discard/mutate allowed now: `{summary['can_create_strategy_now_count']}/{summary['can_close_gap_now_count']}/{summary['can_promote_now_count']}/{summary['can_discard_now_count']}/{summary['parameter_mutation_allowed_now_count']}`",
        "- Boundary: response validation only; no strategy creation, gap closure, broker/live, real orders, paper approval, parameter mutation, or manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Response Gate Rows",
        "",
    ]
    for row in payload["response_gate_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} {row['catalog_title']}",
                "",
                f"- Gate state: `{row['response_gate_state']}`",
                f"- Questions confirmed/required/pending: `{row['confirmed_question_response_count']}/{row['required_question_response_count']}/{row['pending_question_response_count']}`",
                f"- Cases confirmed/required/pending: `{row['confirmed_case_response_count']}/{row['required_case_response_count']}/{row['pending_case_response_count']}`",
                f"- Future spec unblocked: `{row['future_spec_unblocked_after_manual_confirmation']}`",
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
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
