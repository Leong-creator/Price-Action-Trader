#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_source_reextract_review.json"
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
class StrategySourceReextractReviewConfig:
    stage: str
    strategy_source_reextract_plan_path: Path
    source_reextract_review_json_path: Path
    source_reextract_review_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategySourceReextractReviewConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategySourceReextractReviewConfig(
        stage=str(payload["stage"]),
        strategy_source_reextract_plan_path=resolve_repo_path(
            inputs["m14_strategy_source_reextract_plan"]
        ),
        source_reextract_review_json_path=resolve_repo_path(outputs["source_reextract_review_json"]),
        source_reextract_review_md_path=resolve_repo_path(outputs["source_reextract_review_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategySourceReextractReviewConfig) -> None:
    if config.stage != "M14.strategy_source_reextract_review":
        raise ValueError("M14 strategy source reextract review stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy source reextract review must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy source reextract review must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy source reextract review cannot enable {key}")


def run_m14_strategy_source_reextract_review(
    config: StrategySourceReextractReviewConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    plan = read_json(config.strategy_source_reextract_plan_path)
    review_rows = [
        build_review_row(dict(row))
        for row in plan.get("plan_rows", [])
        if row.get("plan_state") == "future_source_reextract_candidate"
    ]
    review_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    summary = build_summary(plan, review_rows)
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-source-reextract-review.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_source_reextract_plan": project_path(
                config.strategy_source_reextract_plan_path
            ),
        },
        "summary": summary,
        "review_rows": review_rows,
        "review_policy": {
            "purpose": "Convert future source-reextract candidates into source-backed review/spec packets.",
            "allowed_now": "Review existing local source refs, answer source-review questions, and prepare future spec hypotheses.",
            "not_allowed_now": "No strategy creation, gap closure, promotion, discard, parameter mutation, registry/account mutation, broker/live path, paper approval, or manual M12.37 once-mode.",
            "completion_rule": "A row can be spec-ready for future drafting, but still cannot mutate strategy state or enter broker/live from this review.",
        },
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.source_reextract_review_json_path, payload)
    config.source_reextract_review_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.source_reextract_review_md_path.write_text(build_review_md(payload), encoding="utf-8")
    return payload


def build_review_row(plan_row: dict[str, Any]) -> dict[str, Any]:
    strategy_id = str(plan_row.get("strategy_id", ""))
    source_refs = list(plan_row.get("source_refs_to_review", []))
    markdown_refs = [ref for ref in source_refs if is_markdown_source_ref(ref)]
    non_markdown_refs = [ref for ref in source_refs if not is_markdown_source_ref(ref)]
    atoms = source_atoms_for(strategy_id, source_refs)
    review_answers = source_review_answers_for(strategy_id)
    visual_required = True
    return {
        "review_id": f"source_reextract_review::{strategy_id}",
        "plan_id": str(plan_row.get("plan_id", "")),
        "strategy_id": strategy_id,
        "catalog_title": str(plan_row.get("catalog_title", "")),
        "priority": str(plan_row.get("priority", "")),
        "source_review_state": "source_review_packet_ready",
        "future_spec_readiness": future_spec_readiness_for(strategy_id),
        "setup_hypothesis": setup_hypothesis_for(strategy_id),
        "source_backed_atoms": atoms,
        "source_review_answers": review_answers,
        "ohlcv_proxy_assessment": ohlcv_proxy_assessment_for(strategy_id),
        "visual_review_required": visual_required,
        "visual_review_reason": visual_review_reason_for(strategy_id, non_markdown_refs),
        "markdown_source_ref_count": len(markdown_refs),
        "markdown_source_ref_exists_count": sum(source_ref_exists(ref) for ref in markdown_refs),
        "non_markdown_source_ref_count": len(non_markdown_refs),
        "source_refs_reviewed": source_refs,
        "can_draft_future_source_reextract_spec": True,
        "can_create_strategy_now": False,
        "can_close_gap_now": False,
        "can_promote_now": False,
        "can_discard_now": False,
        "parameter_mutation_allowed_now": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        **hard_boundaries(),
    }


def source_atoms_for(strategy_id: str, source_refs: list[dict[str, Any]]) -> list[dict[str, str]]:
    if strategy_id == "M10-PA-003":
        return [
            atom(
                "context",
                ref_for(source_refs, "video_014E_trends_tight_channel_small_pullback.md"),
                "part1 p987-p992",
                "Tight channels are treated like higher-timeframe breakouts; when unclear, trade only with the trend.",
                "Use higher-timeframe breakout context and block counter-trend entries in tight-channel state.",
            ),
            atom(
                "setup_definition",
                ref_for(source_refs, "video_017A_tight_channels_micro_channels_definitions.md"),
                "part1 p1398-p1406",
                "A tight/small-pullback trend has shallow pullbacks, often 1-3 bars, and pullbacks smaller than about two average bars or two to three minimum scalps.",
                "Approximate with pullback depth, pullback bar count, average bar size, and trend-direction persistence.",
            ),
            atom(
                "entry_trigger",
                ref_for(source_refs, "video_014E_trends_tight_channel_small_pullback.md"),
                "part1 p1006-p1007",
                "After 20 or more bars above the moving average, the first pullback to the average or first close below it can become a trend-continuation reversal entry.",
                "Model as first MA test or first opposite-side close after a sustained trend gap-bar run.",
            ),
            atom(
                "risk_management",
                ref_for(source_refs, "video_014E_trends_tight_channel_small_pullback.md"),
                "part1 p1004-p1005",
                "Correct stops can be far in strong trends; strong traders use wider stops below the last trend leg and trail after new extremes.",
                "Keep position sizing tied to stop distance instead of tightening stops to fit a fixed quantity.",
            ),
            atom(
                "invalidation",
                ref_for(source_refs, "video_014E_trends_tight_channel_small_pullback.md"),
                "part1 p1000-p1001",
                "A strong trend can reverse, but it needs stronger contrary evidence such as wedge/MAG failure, all trend-continuation setups failing, and opposite breakout with follow-through.",
                "Require explicit opposite breakout/follow-through before treating tight-channel continuation as failed.",
            ),
        ]
    if strategy_id == "M10-PA-010":
        return [
            atom(
                "context",
                ref_for(source_refs, "video_029A_climaxes_definition_breakout_exhaustion_vacuum_support_resistance.md"),
                "part2 p802-p810",
                "A climax is a late move-ending breakout; most climaxes lead first to a 3-10 bar trading range, not automatically to a new opposite trend.",
                "Mark late-trend acceleration as decision-zone context, not immediate reversal permission.",
            ),
            atom(
                "setup_definition",
                ref_for(source_refs, "video_029C_climaxes_climactic_reversals_gaps_exhaustion_measuring.md"),
                "part2 p842-p847",
                "After about 10-20 or 20+ bars, a large trend bar near support/resistance can be either measuring gap or exhaustion gap; follow-through and gap closure decide the label.",
                "Track late trend age, large-body rank, gap/overlap state, and next-bar follow-through before assigning reversal state.",
            ),
            atom(
                "entry_trigger",
                ref_for(source_refs, "video_029C_climaxes_climactic_reversals_gaps_exhaustion_measuring.md"),
                "part2 p848-p853",
                "After exhaustion, early counter-trend entries have better reward/risk but lower probability; waiting for strong opposite breakout raises probability with worse reward/risk.",
                "Split future spec into early visual-review entry and confirmed opposite-breakout entry; do not merge them into one trigger.",
            ),
            atom(
                "target_management",
                ref_for(source_refs, "video_029E_climaxes_options_firms_failed_consecutive_climaxes.md"),
                "part2 p879-p883",
                "Consecutive sell climaxes often imply TBTL or trading range, but a final 5-10 bar sell vacuum can still appear before the larger correction.",
                "Require TBTL tracking and allow a final-climax exception before promoting reversal evidence.",
            ),
            atom(
                "invalidation",
                ref_for(source_refs, "video_029E_climaxes_options_firms_failed_consecutive_climaxes.md"),
                "part2 p884-p886",
                "Strong micro-channel pressure means the first reversal can fail; final buy climax can still resolve roughly 50/50 between reversal and trend resumption.",
                "Block promotion unless visual review confirms failed breakout/exhaustion rather than measuring-gap trend continuation.",
            ),
        ]
    return []


def source_review_answers_for(strategy_id: str) -> list[dict[str, str]]:
    if strategy_id == "M10-PA-003":
        return [
            {
                "question_id": "tight_channel_vs_ordinary_channel",
                "answer": "Tightness is defined by tradeability and pullback size: higher-timeframe breakout behavior, pullbacks around 1-3/1-4 bars, smaller than about two average bars or two to three minimum scalps, and poor counter-trend profitability.",
                "evidence_state": "source_supported",
            },
            {
                "question_id": "minimum_pullback_or_failure_condition",
                "answer": "Continuation weakens when gaps close, pullbacks overlap breakout points, the market shifts toward broad-channel/TR behavior, or opposite breakout/follow-through appears after failed continuation setups.",
                "evidence_state": "source_supported",
            },
            {
                "question_id": "ohlcv_approximation_boundary",
                "answer": "Pullback depth/count, average bar size, MA tests, gap bars, and opposite breakout/follow-through are OHLCV-approximable; channel-quality and example matching still require visual review.",
                "evidence_state": "source_supported_visual_review_required",
            },
        ]
    if strategy_id == "M10-PA-010":
        return [
            {
                "question_id": "climax_final_flag_failed_breakout_boundary",
                "answer": "The reviewed sources support late-trend acceleration, exhaustion gap, failed breakout, TBTL, support/resistance, and final-flag language, but final-flag classification remains visual-first.",
                "evidence_state": "source_supported_visual_review_required",
            },
            {
                "question_id": "required_reversal_confirmation",
                "answer": "A climax alone is not enough. Confirmation needs follow-through failure, gap closure or negative gap, support/resistance reaction, or a strong opposite breakout depending on early-versus-confirmed entry route.",
                "evidence_state": "source_supported",
            },
            {
                "question_id": "visual_vs_ohlcv_boundary",
                "answer": "Late trend age, bar count, large-body rank, gaps, follow-through, and TBTL tracking are OHLCV-approximable; wedge/final flag, exhaustion versus measuring-gap interpretation, and failed-breakout quality require visual review.",
                "evidence_state": "source_supported_visual_review_required",
            },
        ]
    return []


def setup_hypothesis_for(strategy_id: str) -> str:
    return {
        "M10-PA-003": "tight_channel_small_pullback_trend_continuation",
        "M10-PA-010": "climax_exhaustion_gap_tbtl_reversal",
    }.get(strategy_id, "unknown_source_reextract_hypothesis")


def future_spec_readiness_for(strategy_id: str) -> str:
    return {
        "M10-PA-003": "draftable_after_visual_case_alignment",
        "M10-PA-010": "draftable_as_visual_first_dual_route_spec",
    }.get(strategy_id, "hold")


def ohlcv_proxy_assessment_for(strategy_id: str) -> dict[str, Any]:
    if strategy_id == "M10-PA-003":
        return {
            "proxy_state": "partially_ohlcv_approximable",
            "approximable_fields": [
                "trend_direction",
                "pullback_bar_count",
                "pullback_depth_vs_average_bar",
                "moving_average_gap_bar",
                "gap_close_or_overlap",
                "opposite_breakout_follow_through",
            ],
            "visual_first_fields": ["channel_tightness_quality", "higher_timeframe_breakout_alignment"],
        }
    if strategy_id == "M10-PA-010":
        return {
            "proxy_state": "visual_first_with_ohlcv_support",
            "approximable_fields": [
                "late_trend_bar_count",
                "large_body_rank",
                "gap_or_negative_gap",
                "follow_through_bar_count",
                "tbtl_bar_count",
                "support_resistance_proxy",
            ],
            "visual_first_fields": ["final_flag_shape", "wedge_or_vacuum_context", "failed_breakout_quality"],
        }
    return {"proxy_state": "unknown", "approximable_fields": [], "visual_first_fields": []}


def visual_review_reason_for(strategy_id: str, non_markdown_refs: list[dict[str, Any]]) -> str:
    if strategy_id == "M10-PA-010":
        return "Climax/final-flag/TBTL reversal needs chart-shape confirmation, and PDF/notes refs remain visual-review inputs."
    if non_markdown_refs:
        return "PDF/notes refs are present and must be visually checked before future source-reextract spec promotion."
    return "Visual alignment still required before any strategy-state change."


def build_summary(plan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    plan_summary = plan.get("summary", {})
    readiness_counts = Counter(row["future_spec_readiness"] for row in rows)
    return {
        "current_project_stage": str(plan_summary.get("current_project_stage", "")),
        "m14_trading_date": str(plan_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(plan_summary.get("challenge_progress_label", "")),
        "source_reextract_review_row_count": len(rows),
        "candidate_strategy_count": len({row["strategy_id"] for row in rows}),
        "source_backed_atom_count": sum(len(row["source_backed_atoms"]) for row in rows),
        "source_review_answer_count": sum(len(row["source_review_answers"]) for row in rows),
        "markdown_source_ref_count": sum(row["markdown_source_ref_count"] for row in rows),
        "markdown_source_ref_exists_count": sum(row["markdown_source_ref_exists_count"] for row in rows),
        "non_markdown_source_ref_count": sum(row["non_markdown_source_ref_count"] for row in rows),
        "future_spec_draftable_count": sum(row["can_draft_future_source_reextract_spec"] for row in rows),
        "visual_review_required_count": sum(row["visual_review_required"] for row in rows),
        "can_create_strategy_now_count": 0,
        "can_close_gap_now_count": 0,
        "can_promote_now_count": 0,
        "can_discard_now_count": 0,
        "parameter_mutation_allowed_now_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "strategy_state_mutation_allowed": False,
        "future_spec_readiness_counts": dict(sorted(readiness_counts.items())),
    }


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Source reextract review produced {summary['source_reextract_review_row_count']} candidate review packets "
        f"with {summary['source_backed_atom_count']} source-backed atoms and "
        f"{summary['source_review_answer_count']} review answers. "
        f"{summary['future_spec_draftable_count']} future specs are draftable after visual alignment, while "
        f"{summary['visual_review_required_count']} still require visual review before any strategy-state decision. "
        "The review cannot create strategies, close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live."
    )


def build_review_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Source Reextract Review",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Review rows: `{summary['source_reextract_review_row_count']}`",
        f"- Source-backed atoms / answers: `{summary['source_backed_atom_count']}/{summary['source_review_answer_count']}`",
        f"- Markdown refs existing / total: `{summary['markdown_source_ref_exists_count']}/{summary['markdown_source_ref_count']}`",
        f"- Non-markdown refs pending visual review: `{summary['non_markdown_source_ref_count']}`",
        f"- Future spec draftable / visual-review required: `{summary['future_spec_draftable_count']}/{summary['visual_review_required_count']}`",
        f"- Create/close/promote/discard/mutate allowed now: `{summary['can_create_strategy_now_count']}/{summary['can_close_gap_now_count']}/{summary['can_promote_now_count']}/{summary['can_discard_now_count']}/{summary['parameter_mutation_allowed_now_count']}`",
        "- Boundary: source review/spec packet only; no strategy creation, gap closure, broker/live, real orders, paper approval, parameter mutation, or manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Review Rows",
        "",
    ]
    for row in payload["review_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} {row['catalog_title']}",
                "",
                f"- Review state: `{row['source_review_state']}`",
                f"- Setup hypothesis: `{row['setup_hypothesis']}`",
                f"- Future spec readiness: `{row['future_spec_readiness']}`",
                f"- OHLCV proxy state: `{row['ohlcv_proxy_assessment']['proxy_state']}`",
                f"- Visual review required: `{row['visual_review_required']}`",
                f"- Visual review reason: {row['visual_review_reason']}",
                "",
                "#### Source-Backed Atoms",
                "",
            ]
        )
        for atom_row in row["source_backed_atoms"]:
            lines.extend(
                [
                    f"- `{atom_row['field']}` from `{atom_row['locator_summary']}`",
                    f"  - Rule: {atom_row['extracted_rule']}",
                    f"  - Implementation hint: {atom_row['implementation_hint']}",
                ]
            )
        lines.extend(["", "#### Review Answers", ""])
        for answer in row["source_review_answers"]:
            lines.append(f"- `{answer['question_id']}`: {answer['answer']}")
        lines.append("")
    return "\n".join(lines)


def atom(
    field: str,
    source_ref: str,
    locator_summary: str,
    extracted_rule: str,
    implementation_hint: str,
) -> dict[str, str]:
    return {
        "field": field,
        "source_ref": source_ref,
        "locator_summary": locator_summary,
        "extracted_rule": extracted_rule,
        "implementation_hint": implementation_hint,
        "evidence_state": "source_supported",
    }


def ref_for(source_refs: list[dict[str, Any]], filename: str) -> str:
    for ref in source_refs:
        source_ref = str(ref.get("source_ref", ""))
        if filename in source_ref:
            return source_ref
    for ref in source_refs:
        source_ref = str(ref.get("source_ref", ""))
        if source_ref.endswith(".md"):
            return source_ref
    return ""


def is_markdown_source_ref(ref: dict[str, Any]) -> bool:
    return str(ref.get("source_ref", "")).endswith(".md")


def source_ref_exists(ref: dict[str, Any]) -> bool:
    path = path_from_source_ref(str(ref.get("source_ref", "")))
    return bool(path and path.exists())


def path_from_source_ref(source_ref: str) -> Path | None:
    if not source_ref.startswith("raw:"):
        return None
    raw_path = Path(source_ref.removeprefix("raw:"))
    return raw_path if raw_path.is_absolute() else ROOT / raw_path


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
