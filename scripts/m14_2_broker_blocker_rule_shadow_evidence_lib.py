#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_2_broker_blocker_rule_shadow_evidence.json"


@dataclass(frozen=True, slots=True)
class BrokerBlockerRuleShadowEvidenceConfig:
    stage: str
    shadow_ab_prep_path: Path
    rule_shadow_evidence_json_path: Path
    rule_shadow_evidence_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> BrokerBlockerRuleShadowEvidenceConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = BrokerBlockerRuleShadowEvidenceConfig(
        stage=str(payload["stage"]),
        shadow_ab_prep_path=resolve_repo_path(inputs["broker_blocker_shadow_ab_prep"]),
        rule_shadow_evidence_json_path=resolve_repo_path(outputs["rule_shadow_evidence_json"]),
        rule_shadow_evidence_md_path=resolve_repo_path(outputs["rule_shadow_evidence_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: BrokerBlockerRuleShadowEvidenceConfig) -> None:
    if config.stage != "M14.2.broker_blocker_rule_shadow_evidence":
        raise ValueError("M14.2 broker blocker rule shadow evidence stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14.2 broker blocker rule shadow evidence must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14.2 broker blocker rule shadow evidence cannot enable {key}")


def run_broker_blocker_rule_shadow_evidence(
    config: BrokerBlockerRuleShadowEvidenceConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    shadow_ab_prep = read_json(config.shadow_ab_prep_path)
    source_rows = list(shadow_ab_prep.get("rows", []))
    rows = [
        build_rule_shadow_evidence_row(dict(row))
        for row in source_rows
        if str(row.get("shadow_scope", "")) == "rule_only_shadow"
    ]
    rows.sort(key=lambda row: (row["strategy_id"], row["symbol"], row["timeframe"], row["rule_family"]))
    strategy_summaries = build_strategy_summaries(rows)
    rule_family_counts = Counter(row["rule_family"] for row in rows)
    status_counts = Counter(row["shadow_evidence_status"] for row in rows)
    summary = {
        "source_ab_prep_rows": len(source_rows),
        "source_runtime_candidate_rows": sum(
            1 for row in source_rows if str(row.get("shadow_scope", "")) == "runtime_candidate_shadow"
        ),
        "rule_shadow_evidence_rows": len(rows),
        "strategy_count": len(strategy_summaries),
        "rule_only_candidate_count": len(rows),
        "exposure_ranker_rule_count": rule_family_counts.get("portfolio_exposure_ranker", 0),
        "cooldown_quality_rule_count": rule_family_counts.get("cooldown_quality_veto", 0),
        "ready_for_next_internal_sim_refresh_count": sum(
            1 for row in rows if row["shadow_evidence_status"] == "ready_for_next_internal_sim_refresh"
        ),
        "runtime_registration_count": 0,
        "original_blocked_rows_preserved_count": sum(
            1 for row in rows if row["original_readiness_status_remains_blocked"]
        ),
        "m13_registry_mutation_count": 0,
        "m12_account_specs_mutation_count": 0,
        "broker_readiness_status_mutation_count": 0,
        "rule_family_counts": dict(sorted(rule_family_counts.items())),
        "shadow_evidence_status_counts": dict(sorted(status_counts.items())),
        "broker_or_live_enabled": False,
    }
    payload = {
        "schema_version": "m14.2.broker-blocker-rule-shadow-evidence.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "broker_blocker_shadow_ab_prep": project_path(config.shadow_ab_prep_path),
            "source_broker_blocker_shadow_repair": shadow_ab_prep.get("input_refs", {}).get(
                "broker_blocker_shadow_repair", ""
            ),
            "source_broker_blocker_diagnostics": shadow_ab_prep.get("input_refs", {}).get(
                "source_broker_blocker_diagnostics", ""
            ),
            "source_broker_readiness_plan": shadow_ab_prep.get("input_refs", {}).get(
                "source_broker_readiness_plan", ""
            ),
        },
        "summary": summary,
        "rows": rows,
        "strategy_summaries": strategy_summaries,
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
        },
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "readiness_status_mutation": False,
        "runtime_registration_mutation": False,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.rule_shadow_evidence_json_path, payload)
    config.rule_shadow_evidence_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.rule_shadow_evidence_md_path.write_text(build_rule_shadow_evidence_md(payload), encoding="utf-8")
    return payload


def build_rule_shadow_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    prep_action = str(row.get("prep_action", ""))
    if prep_action == "prepare_exposure_ranker_shadow_rule":
        rule_family = "portfolio_exposure_ranker"
        shadow_rule_decision = "defer_until_exposure_headroom_returns"
        comparison_contract = (
            "Compare future same-strategy internal-sim signals by total exposure headroom and rank; "
            "lower-ranked entries remain deferred until headroom exists."
        )
        next_action = "Observe the next fresh internal-sim refresh and compare ranking/defer decisions without creating a runtime."
    elif prep_action == "prepare_cooldown_quality_veto_shadow_rule":
        rule_family = "cooldown_quality_veto"
        shadow_rule_decision = "preserve_loss_streak_halt_and_veto_lower_quality_later_entries"
        comparison_contract = (
            "Preserve the loss-streak halt and compare later same-session entries against cooldown/quality-veto checks; "
            "the blocked source row remains blocked."
        )
        next_action = "Keep the halt active and collect later same-session veto evidence after fresh ledger rows exist."
    else:
        rule_family = "manual_rule_shadow_review"
        shadow_rule_decision = "manual_review_required"
        comparison_contract = "Review the prep row before defining any rule-only shadow evidence contract."
        next_action = "Keep blocked and manually review the rule-only shadow row."
    return {
        "row_id": str(row.get("row_id", "")),
        "strategy_id": str(row.get("strategy_id", "")),
        "runtime_id": str(row.get("runtime_id", "")),
        "signal_id": str(row.get("signal_id", "")),
        "trading_date": str(row.get("trading_date", "")),
        "symbol": str(row.get("symbol", "")),
        "timeframe": str(row.get("timeframe", "")),
        "direction": str(row.get("direction", "")),
        "source_prep_action": prep_action,
        "source_prep_status": str(row.get("prep_status", "")),
        "source_shadow_action": str(row.get("source_shadow_action", "")),
        "source_shadow_repair_status": str(row.get("source_shadow_repair_status", "")),
        "source_reason_codes": list(row.get("source_reason_codes", [])),
        "expected_blocker_reduction": list(row.get("expected_blocker_reduction", [])),
        "proposed_shadow_strategy_id": str(row.get("proposed_shadow_strategy_id", "")),
        "proposed_variant_id": str(row.get("proposed_variant_id", "")),
        "rule_family": rule_family,
        "shadow_rule_decision": shadow_rule_decision,
        "shadow_evidence_status": "ready_for_next_internal_sim_refresh",
        "comparison_contract": comparison_contract,
        "source_quantity": str(row.get("source_quantity", "")),
        "source_risk_amount": str(row.get("source_risk_amount", "")),
        "source_notional_exposure": str(row.get("source_notional_exposure", "")),
        "proposed_quantity": str(row.get("proposed_quantity", "")),
        "proposed_risk_amount": str(row.get("proposed_risk_amount", "")),
        "proposed_notional_exposure": str(row.get("proposed_notional_exposure", "")),
        "would_create_runtime": False,
        "ready_for_shadow_runtime_registration": False,
        "runtime_registration_mutation": False,
        "original_readiness_status_remains_blocked": True,
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "readiness_status_mutation": False,
        "next_action": next_action,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_strategy_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_strategy[row["strategy_id"]].append(row)
    summaries: list[dict[str, Any]] = []
    for strategy_id, strategy_rows in sorted(by_strategy.items()):
        rule_counts = Counter(row["rule_family"] for row in strategy_rows)
        summaries.append(
            {
                "strategy_id": strategy_id,
                "symbols": sorted({row["symbol"] for row in strategy_rows if row["symbol"]}),
                "rule_shadow_rows": len(strategy_rows),
                "rule_family_counts": dict(sorted(rule_counts.items())),
                "runtime_registration_count": 0,
                "original_blocked_rows_preserved_count": sum(
                    1 for row in strategy_rows if row["original_readiness_status_remains_blocked"]
                ),
                "recommended_next_action": strategy_next_action(strategy_id, set(rule_counts)),
                "paper_simulated_only": True,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return summaries


def strategy_next_action(strategy_id: str, rule_families: set[str]) -> str:
    if {"portfolio_exposure_ranker", "cooldown_quality_veto"}.issubset(rule_families):
        return (
            f"{strategy_id}: observe exposure ranking and cooldown/quality veto evidence together; "
            "do not create a runtime or unblock broker readiness."
        )
    if "portfolio_exposure_ranker" in rule_families:
        return f"{strategy_id}: observe whether lower-ranked entries wait for exposure headroom."
    if "cooldown_quality_veto" in rule_families:
        return f"{strategy_id}: keep loss-streak halt active and observe later quality-veto behavior."
    return f"{strategy_id}: keep blocked until rule-only shadow evidence is reviewed."


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Broker-blocker rule-only shadow evidence opened {summary['rule_shadow_evidence_rows']} rows from "
        f"{summary['source_ab_prep_rows']} A/B prep rows: "
        f"{summary['exposure_ranker_rule_count']} exposure-ranker rule and "
        f"{summary['cooldown_quality_rule_count']} cooldown/quality rule. "
        f"Runtime registrations: {summary['runtime_registration_count']}; "
        f"original blocked rows preserved: {summary['original_blocked_rows_preserved_count']}. "
        "No M13 registry, M12 account specs, broker readiness, broker connection, real order, live execution, or paper approval is changed."
    )


def build_rule_shadow_evidence_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14.2 Broker Blocker Rule Shadow Evidence",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Source A/B prep rows: `{summary['source_ab_prep_rows']}`",
        f"- Rule shadow evidence rows: `{summary['rule_shadow_evidence_rows']}`",
        f"- Exposure-ranker rules: `{summary['exposure_ranker_rule_count']}`",
        f"- Cooldown/quality rules: `{summary['cooldown_quality_rule_count']}`",
        f"- Runtime registrations: `{summary['runtime_registration_count']}`",
        "- Boundary: rule-only evidence; no runtime registration, registry mutation, account spec mutation, or broker readiness mutation.",
        "",
        "## Strategy Evidence",
        "",
    ]
    for row in payload["strategy_summaries"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Symbols: `{', '.join(row['symbols'])}`",
                f"- Rule shadow rows: `{row['rule_shadow_rows']}`",
                f"- Rule families: `{row['rule_family_counts']}`",
                f"- Original blocked rows preserved: `{row['original_blocked_rows_preserved_count']}`",
                f"- Next action: {row['recommended_next_action']}",
                "",
            ]
        )
    lines.extend(["## Evidence Rows", ""])
    for row in payload["rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} / {row['symbol']} / {row['timeframe']}",
                "",
                f"- Rule family: `{row['rule_family']}`",
                f"- Shadow decision: `{row['shadow_rule_decision']}`",
                f"- Evidence status: `{row['shadow_evidence_status']}`",
                f"- Source reason codes: `{row['source_reason_codes']}`",
                f"- Quantity / risk / notional: `{row['source_quantity']} / {row['source_risk_amount']} / {row['source_notional_exposure']}`",
                f"- Would create runtime: `{row['would_create_runtime']}`",
                f"- Original readiness remains blocked: `{row['original_readiness_status_remains_blocked']}`",
                f"- Comparison contract: {row['comparison_contract']}",
                f"- Next action: {row['next_action']}",
                "",
            ]
        )
    lines.extend(["## Summary", "", payload["plain_language_result"], ""])
    return "\n".join(lines)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
