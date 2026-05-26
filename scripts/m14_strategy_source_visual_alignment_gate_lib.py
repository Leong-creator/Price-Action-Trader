#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_source_visual_alignment_gate.json"
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
class StrategySourceVisualAlignmentGateConfig:
    stage: str
    strategy_source_reextract_review_path: Path
    visual_golden_case_dir: Path
    old_m10_worktree_root: Path
    source_visual_alignment_gate_json_path: Path
    source_visual_alignment_gate_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategySourceVisualAlignmentGateConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategySourceVisualAlignmentGateConfig(
        stage=str(payload["stage"]),
        strategy_source_reextract_review_path=resolve_repo_path(
            inputs["m14_strategy_source_reextract_review"]
        ),
        visual_golden_case_dir=resolve_repo_path(inputs["visual_golden_case_dir"]),
        old_m10_worktree_root=Path(inputs["old_m10_worktree_root"]),
        source_visual_alignment_gate_json_path=resolve_repo_path(
            outputs["source_visual_alignment_gate_json"]
        ),
        source_visual_alignment_gate_md_path=resolve_repo_path(
            outputs["source_visual_alignment_gate_md"]
        ),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategySourceVisualAlignmentGateConfig) -> None:
    if config.stage != "M14.strategy_source_visual_alignment_gate":
        raise ValueError("M14 strategy source visual alignment gate stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy source visual alignment gate must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy source visual alignment gate must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy source visual alignment gate cannot enable {key}")


def run_m14_strategy_source_visual_alignment_gate(
    config: StrategySourceVisualAlignmentGateConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    review = read_json(config.strategy_source_reextract_review_path)
    rows = [
        build_alignment_row(config, dict(row))
        for row in review.get("review_rows", [])
        if bool(row.get("visual_review_required", False))
    ]
    rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    summary = build_summary(review, rows)
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-source-visual-alignment-gate.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_source_reextract_review": project_path(
                config.strategy_source_reextract_review_path
            ),
            "visual_golden_case_dir": project_path(config.visual_golden_case_dir),
            "old_m10_worktree_root": str(config.old_m10_worktree_root),
        },
        "summary": summary,
        "alignment_rows": rows,
        "gate_policy": {
            "purpose": "Check whether source-reextract candidates have enough local visual evidence for manual visual alignment.",
            "allowed_now": "Verify visual case pack coverage, evidence asset availability, checksum match, and source-backed visual questions.",
            "not_allowed_now": "No strategy creation, gap closure, promotion, discard, parameter mutation, registry/account mutation, broker/live path, paper approval, or manual M12.37 once-mode.",
            "completion_rule": "Rows can become ready for human visual alignment, but future specs remain blocked until manual visual confirmation is recorded.",
        },
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.source_visual_alignment_gate_json_path, payload)
    config.source_visual_alignment_gate_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.source_visual_alignment_gate_md_path.write_text(build_gate_md(payload), encoding="utf-8")
    return payload


def build_alignment_row(
    config: StrategySourceVisualAlignmentGateConfig,
    review_row: dict[str, Any],
) -> dict[str, Any]:
    strategy_id = str(review_row.get("strategy_id", ""))
    pack_path = config.visual_golden_case_dir / f"{strategy_id}.json"
    pack = read_json(pack_path) if pack_path.exists() else {}
    cases = [build_case_row(config, dict(case)) for case in pack.get("cases", [])]
    case_counts = dict(sorted(Counter(case["case_type"] for case in cases).items()))
    required_mix_ready = (
        case_counts.get("positive", 0) >= 3
        and case_counts.get("counterexample", 0) >= 1
        and case_counts.get("boundary", 0) >= 1
    )
    all_assets_available = bool(cases) and all(case["evidence_asset_location"] != "missing" for case in cases)
    all_checksums_match = bool(cases) and all(case["checksum_match"] for case in cases)
    human_required = True
    ready_for_manual_alignment = required_mix_ready and all_assets_available and all_checksums_match
    return {
        "alignment_id": f"source_visual_alignment::{strategy_id}",
        "review_id": str(review_row.get("review_id", "")),
        "strategy_id": strategy_id,
        "catalog_title": str(review_row.get("catalog_title", "")),
        "priority": str(review_row.get("priority", "")),
        "setup_hypothesis": str(review_row.get("setup_hypothesis", "")),
        "visual_alignment_state": (
            "ready_for_manual_visual_alignment"
            if ready_for_manual_alignment
            else "blocked_missing_or_unmatched_visual_evidence"
        ),
        "future_spec_gate_state": "blocked_until_manual_visual_confirmation",
        "manual_visual_confirmation_required": human_required,
        "visual_pack_path": project_path(pack_path),
        "visual_pack_present": bool(pack),
        "visual_pack_status": str(pack.get("pack_status", "")),
        "visual_pack_review_status": str(pack.get("review_status", "")),
        "required_case_mix_ready": required_mix_ready,
        "all_assets_available": all_assets_available,
        "all_checksums_match": all_checksums_match,
        "case_count": len(cases),
        "case_counts": case_counts,
        "source_backed_atom_count": len(review_row.get("source_backed_atoms", [])),
        "source_review_answer_count": len(review_row.get("source_review_answers", [])),
        "visual_alignment_questions": visual_alignment_questions_for(strategy_id),
        "case_rows": cases,
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


def build_case_row(config: StrategySourceVisualAlignmentGateConfig, case: dict[str, Any]) -> dict[str, Any]:
    logical_path = Path(str(case.get("evidence_image_logical_path", "")))
    current_path = ROOT / logical_path
    old_path = config.old_m10_worktree_root / logical_path
    expected_checksum = str(case.get("evidence_image_checksum", ""))
    evidence_asset_location = "missing"
    resolved_path = ""
    checksum_match = False
    if current_path.exists():
        evidence_asset_location = "current_worktree"
        resolved_path = project_path(current_path)
        checksum_match = sha256_file(current_path) == expected_checksum
    elif old_path.exists():
        evidence_asset_location = "old_m10_worktree"
        resolved_path = str(old_path)
        checksum_match = sha256_file(old_path) == expected_checksum
    return {
        "case_id": str(case.get("case_id", "")),
        "case_type": str(case.get("case_type", "")),
        "brooks_unit_ref": str(case.get("brooks_unit_ref", "")),
        "evidence_video_id": str(case.get("evidence_video_id", "")),
        "evidence_page": int_or_zero(case.get("evidence_page")),
        "evidence_image_logical_path": str(case.get("evidence_image_logical_path", "")),
        "evidence_asset_location": evidence_asset_location,
        "resolved_evidence_path": resolved_path,
        "pack_evidence_exists": bool(case.get("evidence_exists", False)),
        "pack_checksum_resolved": bool(case.get("checksum_resolved", False)),
        "checksum_match": checksum_match,
        "review_status": str(case.get("review_status", "")),
        "matched_terms": list(case.get("matched_terms", [])),
        "pattern_decision_points": list(case.get("pattern_decision_points", [])),
        "disqualifiers": list(case.get("disqualifiers", [])),
        "ohlcv_approximation_risk": str(case.get("ohlcv_approximation_risk", "")),
    }


def visual_alignment_questions_for(strategy_id: str) -> list[dict[str, str]]:
    if strategy_id == "M10-PA-003":
        return [
            {
                "question_id": "tight_channel_geometry_visible",
                "question": "Does the case visibly show a tight channel or small-pullback trend rather than an ordinary broad channel?",
                "acceptance_signal": "Small pullbacks stay shallow and mostly fail to create attractive counter-trend swings.",
            },
            {
                "question_id": "higher_timeframe_breakout_context",
                "question": "Does the chart context support treating the tight channel like a higher-timeframe breakout?",
                "acceptance_signal": "Trend direction and follow-through remain dominant enough to block counter-trend entries.",
            },
            {
                "question_id": "failure_boundary_visible",
                "question": "Do counterexample and boundary cases show channel break or opposite follow-through conditions clearly enough to define invalidation?",
                "acceptance_signal": "Opposite breakout/follow-through is visually distinguishable from normal small pullback noise.",
            },
        ]
    if strategy_id == "M10-PA-010":
        return [
            {
                "question_id": "climax_vs_measuring_gap_visible",
                "question": "Does the visual case separate exhaustion climax behavior from measuring-gap continuation?",
                "acceptance_signal": "Follow-through, gap closure, support/resistance reaction, or failed-breakout behavior is visible.",
            },
            {
                "question_id": "tbtl_or_trading_range_context",
                "question": "Does the case support TBTL or trading-range expectation after the climax instead of immediate opposite-trend assumptions?",
                "acceptance_signal": "The post-climax reaction can be labeled as TBTL/TR evidence without forcing a reversal entry.",
            },
            {
                "question_id": "early_vs_confirmed_reversal_split",
                "question": "Can early low-probability reversal entries be separated from confirmed opposite-breakout entries?",
                "acceptance_signal": "The chart makes entry route, risk, and follow-through confirmation visually distinct.",
            },
        ]
    return []


def build_summary(review: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    review_summary = review.get("summary", {})
    all_cases = [case for row in rows for case in row["case_rows"]]
    case_counts = Counter(case["case_type"] for case in all_cases)
    location_counts = Counter(case["evidence_asset_location"] for case in all_cases)
    return {
        "current_project_stage": str(review_summary.get("current_project_stage", "")),
        "m14_trading_date": str(review_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(review_summary.get("challenge_progress_label", "")),
        "source_visual_alignment_gate_row_count": len(rows),
        "candidate_strategy_count": len({row["strategy_id"] for row in rows}),
        "visual_case_count": len(all_cases),
        "positive_case_count": case_counts.get("positive", 0),
        "counterexample_case_count": case_counts.get("counterexample", 0),
        "boundary_case_count": case_counts.get("boundary", 0),
        "pack_evidence_exists_count": sum(case["pack_evidence_exists"] for case in all_cases),
        "pack_checksum_resolved_count": sum(case["pack_checksum_resolved"] for case in all_cases),
        "checksum_match_count": sum(case["checksum_match"] for case in all_cases),
        "current_worktree_asset_exists_count": location_counts.get("current_worktree", 0),
        "old_worktree_asset_exists_count": location_counts.get("old_m10_worktree", 0),
        "missing_asset_count": location_counts.get("missing", 0),
        "ready_for_manual_visual_alignment_count": sum(
            row["visual_alignment_state"] == "ready_for_manual_visual_alignment" for row in rows
        ),
        "manual_visual_confirmation_required_count": sum(
            row["manual_visual_confirmation_required"] for row in rows
        ),
        "future_spec_blocked_until_visual_confirmation_count": len(rows),
        "can_draft_future_source_reextract_spec_now_count": 0,
        "can_create_strategy_now_count": 0,
        "can_close_gap_now_count": 0,
        "can_promote_now_count": 0,
        "can_discard_now_count": 0,
        "parameter_mutation_allowed_now_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "strategy_state_mutation_allowed": False,
        "case_type_counts": dict(sorted(case_counts.items())),
        "evidence_asset_location_counts": dict(sorted(location_counts.items())),
    }


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Source visual alignment gate checked {summary['source_visual_alignment_gate_row_count']} candidate rows "
        f"with {summary['visual_case_count']} visual cases. "
        f"{summary['ready_for_manual_visual_alignment_count']} rows have complete visual packs and checksum-matched local assets, "
        f"but {summary['manual_visual_confirmation_required_count']} rows still require manual visual confirmation before future specs. "
        "The gate cannot draft specs now, create strategies, close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live."
    )


def build_gate_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Source Visual Alignment Gate",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Gate rows / strategies: `{summary['source_visual_alignment_gate_row_count']}/{summary['candidate_strategy_count']}`",
        f"- Visual cases positive/counterexample/boundary: `{summary['positive_case_count']}/{summary['counterexample_case_count']}/{summary['boundary_case_count']}`",
        f"- Checksum match / cases: `{summary['checksum_match_count']}/{summary['visual_case_count']}`",
        f"- Asset locations: `{summary['evidence_asset_location_counts']}`",
        f"- Ready for manual visual alignment / manual confirmation required: `{summary['ready_for_manual_visual_alignment_count']}/{summary['manual_visual_confirmation_required_count']}`",
        f"- Draft/create/close/promote/discard/mutate allowed now: `{summary['can_draft_future_source_reextract_spec_now_count']}/{summary['can_create_strategy_now_count']}/{summary['can_close_gap_now_count']}/{summary['can_promote_now_count']}/{summary['can_discard_now_count']}/{summary['parameter_mutation_allowed_now_count']}`",
        "- Boundary: visual alignment gate only; no strategy creation, gap closure, broker/live, real orders, paper approval, parameter mutation, or manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Alignment Rows",
        "",
    ]
    for row in payload["alignment_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} {row['catalog_title']}",
                "",
                f"- Alignment state: `{row['visual_alignment_state']}`",
                f"- Future spec gate: `{row['future_spec_gate_state']}`",
                f"- Setup hypothesis: `{row['setup_hypothesis']}`",
                f"- Case count: `{row['case_count']}`",
                f"- Case counts: `{row['case_counts']}`",
                f"- All assets available / checksums match: `{row['all_assets_available']}/{row['all_checksums_match']}`",
                "",
                "#### Visual Questions",
                "",
            ]
        )
        for question in row["visual_alignment_questions"]:
            lines.append(f"- `{question['question_id']}`: {question['question']}")
        lines.extend(["", "#### Cases", ""])
        for case in row["case_rows"]:
            lines.append(
                f"- `{case['case_id']}` `{case['case_type']}` page `{case['evidence_page']}` "
                f"asset `{case['evidence_asset_location']}` checksum `{case['checksum_match']}`"
            )
        lines.append("")
    return "\n".join(lines)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
