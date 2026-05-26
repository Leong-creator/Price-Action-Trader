#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_source_visual_confirmation_packet.json"
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
class StrategySourceVisualConfirmationPacketConfig:
    stage: str
    strategy_source_visual_alignment_gate_path: Path
    source_visual_confirmation_packet_json_path: Path
    source_visual_confirmation_packet_md_path: Path
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
) -> StrategySourceVisualConfirmationPacketConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategySourceVisualConfirmationPacketConfig(
        stage=str(payload["stage"]),
        strategy_source_visual_alignment_gate_path=resolve_repo_path(
            inputs["m14_strategy_source_visual_alignment_gate"]
        ),
        source_visual_confirmation_packet_json_path=resolve_repo_path(
            outputs["source_visual_confirmation_packet_json"]
        ),
        source_visual_confirmation_packet_md_path=resolve_repo_path(
            outputs["source_visual_confirmation_packet_md"]
        ),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategySourceVisualConfirmationPacketConfig) -> None:
    if config.stage != "M14.strategy_source_visual_confirmation_packet":
        raise ValueError("M14 strategy source visual confirmation packet stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy source visual confirmation packet must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy source visual confirmation packet must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy source visual confirmation packet cannot enable {key}")


def run_m14_strategy_source_visual_confirmation_packet(
    config: StrategySourceVisualConfirmationPacketConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    alignment_gate = read_json(config.strategy_source_visual_alignment_gate_path)
    packet_rows = [
        build_packet_row(dict(row))
        for row in alignment_gate.get("alignment_rows", [])
        if row.get("visual_alignment_state") == "ready_for_manual_visual_alignment"
    ]
    packet_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    summary = build_summary(alignment_gate, packet_rows)
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-source-visual-confirmation-packet.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_source_visual_alignment_gate": project_path(
                config.strategy_source_visual_alignment_gate_path
            ),
        },
        "summary": summary,
        "packet_rows": packet_rows,
        "packet_policy": {
            "purpose": "Prepare a human-readable visual confirmation packet for source-reextract candidates whose image assets and checksums are ready.",
            "allowed_now": "Group visual questions, source-backed hypotheses, case roles, and pending confirmation fields for manual review.",
            "not_allowed_now": "No visual confirmation is recorded by this packet; no future spec drafting, strategy creation, gap closure, promotion, discard, parameter mutation, registry/account mutation, broker/live path, paper approval, or manual M12.37 once-mode.",
            "completion_rule": "Future source-reextract specs remain blocked until manual visual confirmation is recorded in a separate reviewed artifact.",
        },
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.source_visual_confirmation_packet_json_path, payload)
    config.source_visual_confirmation_packet_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.source_visual_confirmation_packet_md_path.write_text(build_packet_md(payload), encoding="utf-8")
    return payload


def build_packet_row(alignment_row: dict[str, Any]) -> dict[str, Any]:
    case_rows = [build_case_confirmation_row(dict(case), alignment_row) for case in alignment_row["case_rows"]]
    confirmation_items = [
        build_confirmation_item(dict(question), case_rows)
        for question in alignment_row.get("visual_alignment_questions", [])
    ]
    return {
        "packet_id": f"source_visual_confirmation::{alignment_row['strategy_id']}",
        "alignment_id": str(alignment_row.get("alignment_id", "")),
        "strategy_id": str(alignment_row.get("strategy_id", "")),
        "catalog_title": str(alignment_row.get("catalog_title", "")),
        "priority": str(alignment_row.get("priority", "")),
        "packet_state": "manual_visual_confirmation_packet_ready",
        "future_spec_gate_state": "blocked_until_manual_visual_confirmation_recorded",
        "manual_visual_confirmation_required": True,
        "manual_visual_confirmation_recorded": False,
        "setup_hypothesis": str(alignment_row.get("setup_hypothesis", "")),
        "source_backed_atom_count": int_or_zero(alignment_row.get("source_backed_atom_count")),
        "source_review_answer_count": int_or_zero(alignment_row.get("source_review_answer_count")),
        "case_count": len(case_rows),
        "case_counts": dict(sorted(Counter(case["case_type"] for case in case_rows).items())),
        "confirmation_item_count": len(confirmation_items),
        "confirmation_items": confirmation_items,
        "case_confirmation_rows": case_rows,
        "can_draft_future_source_reextract_spec_now": False,
        "can_create_strategy_now": False,
        "can_close_gap_now": False,
        "can_promote_now": False,
        "can_discard_now": False,
        "parameter_mutation_allowed_now": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        **hard_boundaries(),
    }


def build_confirmation_item(question: dict[str, Any], case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "question_id": str(question.get("question_id", "")),
        "question": str(question.get("question", "")),
        "acceptance_signal": str(question.get("acceptance_signal", "")),
        "required_manual_response": "confirmed | rejected | unclear",
        "manual_response_recorded": False,
        "blocks_future_spec_until_confirmed": True,
        "positive_case_ids": [case["case_id"] for case in case_rows if case["case_type"] == "positive"],
        "counterexample_case_ids": [
            case["case_id"] for case in case_rows if case["case_type"] == "counterexample"
        ],
        "boundary_case_ids": [case["case_id"] for case in case_rows if case["case_type"] == "boundary"],
    }


def build_case_confirmation_row(case: dict[str, Any], alignment_row: dict[str, Any]) -> dict[str, Any]:
    case_type = str(case.get("case_type", ""))
    return {
        "case_id": str(case.get("case_id", "")),
        "strategy_id": str(alignment_row.get("strategy_id", "")),
        "case_type": case_type,
        "expected_visual_role": expected_visual_role(case_type),
        "human_confirmation_state": "pending_manual_visual_confirmation",
        "manual_response_recorded": False,
        "resolved_evidence_path": str(case.get("resolved_evidence_path", "")),
        "evidence_asset_location": str(case.get("evidence_asset_location", "")),
        "checksum_match": bool(case.get("checksum_match", False)),
        "brooks_unit_ref": str(case.get("brooks_unit_ref", "")),
        "evidence_video_id": str(case.get("evidence_video_id", "")),
        "evidence_page": int_or_zero(case.get("evidence_page")),
        "matched_terms": list(case.get("matched_terms", [])),
        "pattern_decision_points": list(case.get("pattern_decision_points", [])),
        "disqualifiers": list(case.get("disqualifiers", [])),
        "ohlcv_approximation_risk": str(case.get("ohlcv_approximation_risk", "")),
        "future_spec_input_allowed_after_confirmation": case_type in {"positive", "boundary"},
        "future_spec_disqualifier_input_after_confirmation": case_type == "counterexample",
        "paper_gate_evidence_now": False,
        "can_draft_future_source_reextract_spec_now": False,
        "can_create_strategy_now": False,
        "parameter_mutation_allowed_now": False,
    }


def expected_visual_role(case_type: str) -> str:
    if case_type == "positive":
        return "confirm_setup_geometry_and_context"
    if case_type == "counterexample":
        return "confirm_invalidation_or_disqualifier_boundary"
    if case_type == "boundary":
        return "confirm_borderline_rule_before_ohlcv_approximation"
    return "confirm_case_role_before_use"


def build_summary(alignment_gate: dict[str, Any], packet_rows: list[dict[str, Any]]) -> dict[str, Any]:
    alignment_summary = alignment_gate.get("summary", {})
    case_rows = [case for row in packet_rows for case in row["case_confirmation_rows"]]
    return {
        "current_project_stage": str(alignment_summary.get("current_project_stage", "")),
        "m14_trading_date": str(alignment_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(alignment_summary.get("challenge_progress_label", "")),
        "source_visual_confirmation_packet_row_count": len(packet_rows),
        "candidate_strategy_count": len({row["strategy_id"] for row in packet_rows}),
        "confirmation_item_count": sum(row["confirmation_item_count"] for row in packet_rows),
        "confirmation_case_row_count": len(case_rows),
        "positive_case_count": sum(case["case_type"] == "positive" for case in case_rows),
        "counterexample_case_count": sum(case["case_type"] == "counterexample" for case in case_rows),
        "boundary_case_count": sum(case["case_type"] == "boundary" for case in case_rows),
        "packet_ready_count": sum(row["packet_state"] == "manual_visual_confirmation_packet_ready" for row in packet_rows),
        "manual_visual_confirmation_required_count": sum(
            row["manual_visual_confirmation_required"] for row in packet_rows
        ),
        "manual_visual_confirmation_recorded_count": sum(
            row["manual_visual_confirmation_recorded"] for row in packet_rows
        ),
        "pending_manual_visual_confirmation_case_count": sum(
            case["human_confirmation_state"] == "pending_manual_visual_confirmation"
            for case in case_rows
        ),
        "future_spec_blocked_until_visual_confirmation_count": len(packet_rows),
        "future_spec_unblocked_count": 0,
        "can_draft_future_source_reextract_spec_now_count": 0,
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
        f"Source visual confirmation packet prepared {summary['source_visual_confirmation_packet_row_count']} strategy rows, "
        f"{summary['confirmation_item_count']} confirmation questions, and {summary['confirmation_case_row_count']} case rows. "
        f"{summary['packet_ready_count']} packets are ready for manual review, but "
        f"{summary['manual_visual_confirmation_recorded_count']} confirmations are recorded and "
        f"{summary['future_spec_unblocked_count']} future specs are unblocked. "
        "This packet cannot draft specs, create strategies, close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live."
    )


def build_packet_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Source Visual Confirmation Packet",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Packet rows / strategies: `{summary['source_visual_confirmation_packet_row_count']}/{summary['candidate_strategy_count']}`",
        f"- Confirmation questions / case rows: `{summary['confirmation_item_count']}/{summary['confirmation_case_row_count']}`",
        f"- Cases positive/counterexample/boundary: `{summary['positive_case_count']}/{summary['counterexample_case_count']}/{summary['boundary_case_count']}`",
        f"- Packet ready / manual required / recorded: `{summary['packet_ready_count']}/{summary['manual_visual_confirmation_required_count']}/{summary['manual_visual_confirmation_recorded_count']}`",
        f"- Future specs unblocked / draft allowed now: `{summary['future_spec_unblocked_count']}/{summary['can_draft_future_source_reextract_spec_now_count']}`",
        "- Boundary: packet preparation only; no confirmation recorded, no future spec drafting, no strategy creation, no broker/live, no parameter mutation, no manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Packet Rows",
        "",
    ]
    for row in payload["packet_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} {row['catalog_title']}",
                "",
                f"- Packet state: `{row['packet_state']}`",
                f"- Future spec gate: `{row['future_spec_gate_state']}`",
                f"- Manual confirmation recorded: `{row['manual_visual_confirmation_recorded']}`",
                f"- Case counts: `{row['case_counts']}`",
                "",
                "#### Confirmation Items",
                "",
            ]
        )
        for item in row["confirmation_items"]:
            lines.extend(
                [
                    f"- `{item['question_id']}`: {item['question']}",
                    f"  - Acceptance signal: {item['acceptance_signal']}",
                    f"  - Manual response recorded: `{item['manual_response_recorded']}`",
                ]
            )
        lines.extend(["", "#### Case Rows", ""])
        for case in row["case_confirmation_rows"]:
            lines.append(
                f"- `{case['case_id']}` `{case['case_type']}` role `{case['expected_visual_role']}` "
                f"state `{case['human_confirmation_state']}` evidence `{case['resolved_evidence_path']}`"
            )
        lines.append("")
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
