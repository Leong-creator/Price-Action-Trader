#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_source_recheck_triage.json"
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
class StrategySourceRecheckTriageConfig:
    stage: str
    strategy_pre_refresh_review_audit_path: Path
    strategy_decision_ladder_path: Path
    m10_strategy_catalog_path: Path
    m10_source_support_matrix_path: Path
    m10_backtest_eligibility_matrix_path: Path
    source_recheck_triage_json_path: Path
    source_recheck_triage_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategySourceRecheckTriageConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = StrategySourceRecheckTriageConfig(
        stage=str(payload["stage"]),
        strategy_pre_refresh_review_audit_path=resolve_repo_path(
            inputs["m14_strategy_pre_refresh_review_audit"]
        ),
        strategy_decision_ladder_path=resolve_repo_path(inputs["m14_strategy_decision_ladder"]),
        m10_strategy_catalog_path=resolve_repo_path(inputs["m10_strategy_catalog"]),
        m10_source_support_matrix_path=resolve_repo_path(inputs["m10_source_support_matrix"]),
        m10_backtest_eligibility_matrix_path=resolve_repo_path(
            inputs["m10_backtest_eligibility_matrix"]
        ),
        source_recheck_triage_json_path=resolve_repo_path(outputs["source_recheck_triage_json"]),
        source_recheck_triage_md_path=resolve_repo_path(outputs["source_recheck_triage_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategySourceRecheckTriageConfig) -> None:
    if config.stage != "M14.strategy_source_recheck_triage":
        raise ValueError("M14 strategy source recheck triage stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 strategy source recheck triage must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 strategy source recheck triage must keep internal simulated accounts enabled")
    for key in FORBIDDEN_OPERATIONS:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 strategy source recheck triage cannot enable {key}")


def run_m14_strategy_source_recheck_triage(
    config: StrategySourceRecheckTriageConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    audit = read_json(config.strategy_pre_refresh_review_audit_path)
    decision_ladder = read_json(config.strategy_decision_ladder_path)
    catalog = read_json(config.m10_strategy_catalog_path)
    support_matrix = read_json(config.m10_source_support_matrix_path)
    eligibility_matrix = read_json(config.m10_backtest_eligibility_matrix_path)

    catalog_by_id = {str(row.get("strategy_id", "")): dict(row) for row in catalog.get("strategies", [])}
    support_by_id = {str(row.get("strategy_id", "")): dict(row) for row in support_matrix.get("matrix", [])}
    eligibility_by_id = {
        str(row.get("strategy_id", "")): dict(row) for row in eligibility_matrix.get("matrix", [])
    }
    ladder_by_id = {
        str(row.get("strategy_id", "")): dict(row) for row in decision_ladder.get("ladder_rows", [])
    }

    recheck_rows = [
        build_triage_row(
            dict(row),
            catalog_by_id.get(str(row.get("strategy_id", "")), {}),
            support_by_id.get(str(row.get("strategy_id", "")), {}),
            eligibility_by_id.get(str(row.get("strategy_id", "")), {}),
            ladder_by_id.get(str(row.get("strategy_id", "")), {}),
        )
        for row in audit.get("audit_rows", [])
        if row.get("audit_state") == "ready_for_artifact_review_now"
    ]
    recheck_rows.sort(key=lambda row: (priority_rank(row["priority"]), row["triage_rank"], row["strategy_id"]))
    summary = build_summary(audit, recheck_rows)
    payload: dict[str, Any] = {
        "schema_version": "m14.strategy-source-recheck-triage.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_strategy_pre_refresh_review_audit": project_path(
                config.strategy_pre_refresh_review_audit_path
            ),
            "m14_strategy_decision_ladder": project_path(config.strategy_decision_ladder_path),
            "m10_strategy_catalog": project_path(config.m10_strategy_catalog_path),
            "m10_source_support_matrix": project_path(config.m10_source_support_matrix_path),
            "m10_backtest_eligibility_matrix": project_path(
                config.m10_backtest_eligibility_matrix_path
            ),
        },
        "summary": summary,
        "triage_rows": recheck_rows,
        "triage_policy": {
            "purpose": "Convert artifact-only pre-refresh review rows into source recheck and research triage tasks.",
            "allowed_now": "Review M10 source ledgers, strategy catalog status, visual-review prerequisites, and support/eligibility matrices.",
            "not_allowed_now": "No evidence-changing refresh, promotion, final discard, parameter mutation, registry/account-spec mutation, broker readiness mutation, broker/live path, paper approval, or manual M12.37 once-mode.",
            "completion_rule": "This triage can prioritize source rechecks, but cannot upgrade strategy status or discard a strategy without later evidence.",
        },
        "hard_boundaries": hard_boundaries(),
        **hard_boundaries(),
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.source_recheck_triage_json_path, payload)
    config.source_recheck_triage_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.source_recheck_triage_md_path.write_text(build_triage_md(payload), encoding="utf-8")
    return payload


def build_triage_row(
    audit_row: dict[str, Any],
    catalog_row: dict[str, Any],
    support_row: dict[str, Any],
    eligibility_row: dict[str, Any],
    ladder_row: dict[str, Any],
) -> dict[str, Any]:
    strategy_id = str(audit_row.get("strategy_id", ""))
    catalog_status = str(catalog_row.get("status", "external_or_missing_catalog"))
    test_route = str(eligibility_row.get("test_route") or catalog_row.get("backtest_eligibility", {}).get("route", ""))
    eligible = bool(
        eligibility_row.get("eligible_for_historical_backtest")
        or catalog_row.get("backtest_eligibility", {}).get("eligible_for_historical_backtest", False)
    )
    ohlcv_approximable = bool(
        eligibility_row.get("ohlcv_approximable")
        or catalog_row.get("backtest_eligibility", {}).get("ohlcv_approximable", False)
    )
    source_refs = list(catalog_row.get("source_refs", []))
    support_counts = dict(support_row.get("support_counts", {}))
    triage_state, triage_rank = triage_state_for(
        strategy_id=strategy_id,
        catalog_status=catalog_status,
        test_route=test_route,
        eligible=eligible,
        ohlcv_approximable=ohlcv_approximable,
    )
    return {
        "triage_id": f"source_recheck::{strategy_id}",
        "review_id": str(audit_row.get("review_id", "")),
        "strategy_id": strategy_id,
        "display_name": str(audit_row.get("display_name") or catalog_row.get("title", "")),
        "catalog_title": str(catalog_row.get("title", "")),
        "priority": str(audit_row.get("priority", "")),
        "triage_rank": triage_rank,
        "burn_down_lane": str(audit_row.get("burn_down_lane", "")),
        "triage_state": triage_state,
        "next_source_recheck_action": source_recheck_action_for(triage_state),
        "catalog_status": catalog_status,
        "decision_ladder_state": str(ladder_row.get("ladder_state", "")),
        "decision_ladder_next_decision": str(ladder_row.get("next_decision", "")),
        "test_route": test_route,
        "ohlcv_approximable": ohlcv_approximable,
        "eligible_for_historical_backtest": eligible,
        "visual_dependency": str(catalog_row.get("visual_dependency", "")),
        "source_ref_count": len(source_refs),
        "source_families": list(catalog_row.get("source_families", support_row.get("supported_families", []))),
        "support_counts": support_counts,
        "source_refs": source_refs[:8],
        "prerequisites": list(eligibility_row.get("prerequisites", [])),
        "recheck_can_create_new_strategy_now": False,
        "recheck_can_close_gap_now": False,
        "recheck_can_promote_now": False,
        "recheck_can_discard_now": False,
        "parameter_mutation_allowed_now": False,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        **hard_boundaries(),
    }


def triage_state_for(
    *,
    strategy_id: str,
    catalog_status: str,
    test_route: str,
    eligible: bool,
    ohlcv_approximable: bool,
) -> tuple[str, int]:
    if not strategy_id.startswith("M10-PA-"):
        return "external_reference_hold_no_local_strategy", 40
    if catalog_status == "supporting_rule" or test_route == "supporting_rule_attached_to_parent_setups":
        return "supporting_rule_attach_to_parent", 30
    if catalog_status == "research_only" or not ohlcv_approximable:
        return "research_only_risk_definition_hold", 20
    if eligible:
        return "source_visual_recheck_candidate", 10
    return "source_recheck_hold_no_independent_evidence", 50


def source_recheck_action_for(triage_state: str) -> str:
    actions = {
        "source_visual_recheck_candidate": (
            "Recheck original source refs and visual packs; if independent setup evidence is stronger, draft a future source-reextract spec without promoting now."
        ),
        "research_only_risk_definition_hold": (
            "Keep as research-only until range maturity, cost, and bounded-risk rules are frozen; do not convert to a daily trigger now."
        ),
        "supporting_rule_attach_to_parent": (
            "Attach as target, stop, or sizing support to parent setups; do not treat it as a standalone strategy."
        ),
        "external_reference_hold_no_local_strategy": (
            "Keep external project ideas as architecture/reference checklists only; require local source refs before any local strategy account."
        ),
        "source_recheck_hold_no_independent_evidence": (
            "Hold for manual source review; no independent strategy evidence is sufficient yet."
        ),
    }
    return actions.get(triage_state, actions["source_recheck_hold_no_independent_evidence"])


def build_summary(audit: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    audit_summary = audit.get("summary", {})
    state_counts = Counter(row["triage_state"] for row in rows)
    return {
        "current_project_stage": str(audit_summary.get("current_project_stage", "")),
        "m14_trading_date": str(audit_summary.get("m14_trading_date", "")),
        "challenge_progress_label": str(audit_summary.get("challenge_progress_label", "")),
        "artifact_only_review_row_count": int_or_zero(audit_summary.get("ready_for_artifact_review_now_count")),
        "source_recheck_row_count": len(rows),
        "source_visual_recheck_candidate_count": state_counts.get("source_visual_recheck_candidate", 0),
        "research_only_risk_definition_hold_count": state_counts.get(
            "research_only_risk_definition_hold", 0
        ),
        "supporting_rule_attach_to_parent_count": state_counts.get(
            "supporting_rule_attach_to_parent", 0
        ),
        "external_reference_hold_count": state_counts.get(
            "external_reference_hold_no_local_strategy", 0
        ),
        "source_recheck_hold_count": state_counts.get("source_recheck_hold_no_independent_evidence", 0),
        "local_m10_row_count": sum(1 for row in rows if row["strategy_id"].startswith("M10-PA-")),
        "eligible_for_future_source_reextract_count": sum(
            row["triage_state"] == "source_visual_recheck_candidate" for row in rows
        ),
        "standalone_strategy_creation_allowed_count": 0,
        "recheck_can_close_gap_now_count": 0,
        "recheck_can_promote_now_count": 0,
        "recheck_can_discard_now_count": 0,
        "parameter_mutation_allowed_now_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
        "triage_state_counts": dict(sorted(state_counts.items())),
    }


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Source recheck triage reviewed {summary['source_recheck_row_count']} artifact-only rows. "
        f"{summary['source_visual_recheck_candidate_count']} rows can be prioritized for source/visual recheck, "
        f"{summary['supporting_rule_attach_to_parent_count']} rows should attach to parent setups only, "
        f"{summary['research_only_risk_definition_hold_count']} rows remain research-only until risk/cost rules are frozen, and "
        f"{summary['external_reference_hold_count']} rows are external-reference only. "
        "No row can create a new strategy, close gaps, promote, discard, mutate parameters, run M12.37 manually, or enable broker/live."
    )


def build_triage_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Strategy Source Recheck Triage",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Current stage: `{summary['current_project_stage']}`",
        f"- Challenge: `{summary['challenge_progress_label']}`",
        f"- Source recheck rows: `{summary['source_recheck_row_count']}`",
        f"- Source/visual candidates: `{summary['source_visual_recheck_candidate_count']}`",
        f"- Supporting-only / research-only / external-only: `{summary['supporting_rule_attach_to_parent_count']}/{summary['research_only_risk_definition_hold_count']}/{summary['external_reference_hold_count']}`",
        f"- Close/promote/discard/mutate allowed now: `{summary['recheck_can_close_gap_now_count']}/{summary['recheck_can_promote_now_count']}/{summary['recheck_can_discard_now_count']}/{summary['parameter_mutation_allowed_now_count']}`",
        "- Boundary: source triage only; no strategy creation, broker/live, real orders, paper approval, parameter mutation, or manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Triage Rows",
        "",
    ]
    for row in payload["triage_rows"]:
        lines.extend(
            [
                f"### {row['priority']} {row['strategy_id']}",
                "",
                f"- State: `{row['triage_state']}`",
                f"- Catalog status / route: `{row['catalog_status']}` / `{row['test_route']}`",
                f"- Eligible / OHLCV approximable: `{row['eligible_for_historical_backtest']}/{row['ohlcv_approximable']}`",
                f"- Source families: `{', '.join(row['source_families'])}`",
                f"- Next action: {row['next_source_recheck_action']}",
                f"- Can create/close/promote/discard/mutate now: `{row['recheck_can_create_new_strategy_now']}/{row['recheck_can_close_gap_now']}/{row['recheck_can_promote_now']}/{row['recheck_can_discard_now']}/{row['parameter_mutation_allowed_now']}`",
                "",
            ]
        )
    return "\n".join(lines)


def priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(priority, 9)


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
