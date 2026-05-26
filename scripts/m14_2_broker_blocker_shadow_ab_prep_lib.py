#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_2_broker_blocker_shadow_ab_prep.json"


@dataclass(frozen=True, slots=True)
class BrokerBlockerShadowAbPrepConfig:
    stage: str
    shadow_repair_path: Path
    shadow_ab_prep_json_path: Path
    shadow_ab_prep_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> BrokerBlockerShadowAbPrepConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = BrokerBlockerShadowAbPrepConfig(
        stage=str(payload["stage"]),
        shadow_repair_path=resolve_repo_path(inputs["broker_blocker_shadow_repair"]),
        shadow_ab_prep_json_path=resolve_repo_path(outputs["shadow_ab_prep_json"]),
        shadow_ab_prep_md_path=resolve_repo_path(outputs["shadow_ab_prep_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: BrokerBlockerShadowAbPrepConfig) -> None:
    if config.stage != "M14.2.broker_blocker_shadow_ab_prep":
        raise ValueError("M14.2 broker blocker shadow A/B prep stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14.2 broker blocker shadow A/B prep must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14.2 broker blocker shadow A/B prep cannot enable {key}")


def run_broker_blocker_shadow_ab_prep(
    config: BrokerBlockerShadowAbPrepConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    shadow_repair = read_json(config.shadow_repair_path)
    rows = [build_ab_prep_row(dict(row)) for row in shadow_repair.get("rows", [])]
    rows.sort(key=lambda row: (row["strategy_id"], row["symbol"], row["timeframe"], row["prep_action"]))
    strategy_summaries = build_strategy_summaries(rows)
    prep_counts = Counter(row["prep_action"] for row in rows)
    status_counts = Counter(row["prep_status"] for row in rows)
    summary = {
        "source_shadow_repair_rows": len(rows),
        "ab_prep_rows": len(rows),
        "strategy_count": len(strategy_summaries),
        "risk_cap_runtime_candidate_count": prep_counts.get("prepare_quantity_cap_shadow_runtime", 0),
        "exposure_ranker_rule_candidate_count": prep_counts.get("prepare_exposure_ranker_shadow_rule", 0),
        "cooldown_quality_rule_candidate_count": prep_counts.get("prepare_cooldown_quality_veto_shadow_rule", 0),
        "runtime_registration_candidate_count": sum(1 for row in rows if row["ready_for_shadow_runtime_registration"]),
        "rule_only_candidate_count": sum(1 for row in rows if row["shadow_scope"] == "rule_only_shadow"),
        "original_blocked_rows_preserved_count": sum(1 for row in rows if row["original_readiness_status_remains_blocked"]),
        "m13_registry_mutation_count": 0,
        "m12_account_specs_mutation_count": 0,
        "broker_readiness_status_mutation_count": 0,
        "prep_action_counts": dict(sorted(prep_counts.items())),
        "prep_status_counts": dict(sorted(status_counts.items())),
        "broker_or_live_enabled": False,
    }
    payload = {
        "schema_version": "m14.2.broker-blocker-shadow-ab-prep.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "broker_blocker_shadow_repair": project_path(config.shadow_repair_path),
            "source_broker_blocker_diagnostics": shadow_repair.get("input_refs", {}).get("broker_blocker_diagnostics", ""),
            "source_broker_readiness_plan": shadow_repair.get("input_refs", {}).get("source_broker_readiness_plan", ""),
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
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.shadow_ab_prep_json_path, payload)
    config.shadow_ab_prep_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.shadow_ab_prep_md_path.write_text(build_shadow_ab_prep_md(payload), encoding="utf-8")
    return payload


def build_ab_prep_row(row: dict[str, Any]) -> dict[str, Any]:
    action = str(row.get("shadow_action", ""))
    strategy_id = str(row.get("strategy_id", ""))
    timeframe = str(row.get("timeframe", ""))
    if action == "apply_quantity_cap":
        return base_ab_prep_row(
            row,
            prep_action="prepare_quantity_cap_shadow_runtime",
            prep_status="ready_for_shadow_runtime_design",
            shadow_scope="runtime_candidate_shadow",
            proposed_shadow_strategy_id=f"{strategy_id}-broker-risk-cap-shadow",
            proposed_shadow_runtime_id=f"{strategy_id}-broker-risk-cap-shadow-{timeframe}",
            proposed_variant_id="broker_risk_cap_shadow",
            ready_for_shadow_runtime_registration=True,
            ab_test_hypothesis=(
                "Capping quantity to the existing risk limit can preserve the signal while reducing "
                "max_risk_per_order blocks; original broker readiness remains blocked until fresh A/B evidence exists."
            ),
            next_action="Register only after code review as a separate simulated A/B runtime; do not mutate the approved baseline.",
        )
    if action == "defer_until_exposure_frees":
        return base_ab_prep_row(
            row,
            prep_action="prepare_exposure_ranker_shadow_rule",
            prep_status="rule_only_prep_not_runtime",
            shadow_scope="rule_only_shadow",
            proposed_shadow_strategy_id=f"{strategy_id}-broker-exposure-ranker-shadow",
            proposed_shadow_runtime_id="",
            proposed_variant_id="broker_exposure_ranker_shadow",
            ready_for_shadow_runtime_registration=False,
            ab_test_hypothesis=(
                "A portfolio exposure ranker should defer this signal until headroom exists instead of forcing "
                "an entry that would exceed total exposure."
            ),
            next_action="Keep this as rule-only shadow prep and compare later fresh internal-sim ranking decisions.",
        )
    if action == "keep_loss_streak_halt":
        return base_ab_prep_row(
            row,
            prep_action="prepare_cooldown_quality_veto_shadow_rule",
            prep_status="rule_only_prep_not_runtime",
            shadow_scope="rule_only_shadow",
            proposed_shadow_strategy_id=f"{strategy_id}-broker-cooldown-quality-shadow",
            proposed_shadow_runtime_id="",
            proposed_variant_id="broker_cooldown_quality_shadow",
            ready_for_shadow_runtime_registration=False,
            ab_test_hypothesis=(
                "Cooldown and quality-veto rules should preserve the loss-streak halt while testing whether "
                "later same-session entries can be filtered more cleanly."
            ),
            next_action="Do not create a runtime that bypasses the halt; keep the halt and test veto evidence after fresh ledger rows.",
        )
    return base_ab_prep_row(
        row,
        prep_action="manual_shadow_ab_review",
        prep_status="manual_review_needed",
        shadow_scope="manual_review_shadow",
        proposed_shadow_strategy_id="",
        proposed_shadow_runtime_id="",
        proposed_variant_id="",
        ready_for_shadow_runtime_registration=False,
        ab_test_hypothesis="Risk reason attribution must be reviewed before any shadow A/B prep can be defined.",
        next_action="Keep blocked and manually review the risk reason before changing any runtime.",
    )


def base_ab_prep_row(
    row: dict[str, Any],
    *,
    prep_action: str,
    prep_status: str,
    shadow_scope: str,
    proposed_shadow_strategy_id: str,
    proposed_shadow_runtime_id: str,
    proposed_variant_id: str,
    ready_for_shadow_runtime_registration: bool,
    ab_test_hypothesis: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "row_id": str(row.get("row_id", "")),
        "strategy_id": str(row.get("strategy_id", "")),
        "runtime_id": str(row.get("runtime_id", "")),
        "signal_id": str(row.get("signal_id", "")),
        "trading_date": str(row.get("trading_date", "")),
        "symbol": str(row.get("symbol", "")),
        "timeframe": str(row.get("timeframe", "")),
        "direction": str(row.get("direction", "")),
        "source_shadow_action": str(row.get("shadow_action", "")),
        "source_shadow_repair_status": str(row.get("shadow_repair_status", "")),
        "source_reason_codes": list(row.get("original_reason_codes", [])),
        "expected_blocker_reduction": list(row.get("expected_blocker_reduction", [])),
        "prep_action": prep_action,
        "prep_status": prep_status,
        "shadow_scope": shadow_scope,
        "proposed_shadow_strategy_id": proposed_shadow_strategy_id,
        "proposed_shadow_runtime_id": proposed_shadow_runtime_id,
        "proposed_variant_id": proposed_variant_id,
        "ready_for_shadow_runtime_registration": ready_for_shadow_runtime_registration,
        "ab_test_hypothesis": ab_test_hypothesis,
        "source_quantity": str(row.get("source_quantity", "")),
        "proposed_quantity": str(row.get("proposed_quantity", "")),
        "source_risk_amount": str(row.get("source_risk_amount", "")),
        "proposed_risk_amount": str(row.get("proposed_risk_amount", "")),
        "source_notional_exposure": str(row.get("source_notional_exposure", "")),
        "proposed_notional_exposure": str(row.get("proposed_notional_exposure", "")),
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
        prep_counts = Counter(row["prep_action"] for row in strategy_rows)
        summaries.append(
            {
                "strategy_id": strategy_id,
                "symbols": sorted({row["symbol"] for row in strategy_rows if row["symbol"]}),
                "prep_rows": len(strategy_rows),
                "prep_action_counts": dict(sorted(prep_counts.items())),
                "runtime_registration_candidate_count": sum(
                    1 for row in strategy_rows if row["ready_for_shadow_runtime_registration"]
                ),
                "rule_only_candidate_count": sum(1 for row in strategy_rows if row["shadow_scope"] == "rule_only_shadow"),
                "recommended_next_action": strategy_next_action(strategy_id, set(prep_counts)),
                "paper_simulated_only": True,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return summaries


def strategy_next_action(strategy_id: str, actions: set[str]) -> str:
    if "prepare_quantity_cap_shadow_runtime" in actions:
        return f"{strategy_id}: prepare a separate quantity-cap shadow runtime only after review; do not mutate baseline readiness."
    if "prepare_cooldown_quality_veto_shadow_rule" in actions:
        return f"{strategy_id}: keep loss-streak halt active and shadow-test cooldown/quality veto rules."
    if "prepare_exposure_ranker_shadow_rule" in actions:
        return f"{strategy_id}: shadow-test exposure ranking so lower-ranked entries wait for headroom."
    return f"{strategy_id}: keep blocked until risk attribution is reviewed."


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Broker-blocker shadow A/B prep converted {summary['ab_prep_rows']} repair rows into "
        f"{summary['runtime_registration_candidate_count']} runtime-registration candidate and "
        f"{summary['rule_only_candidate_count']} rule-only shadow candidates. "
        f"Risk-cap candidates: {summary['risk_cap_runtime_candidate_count']}; "
        f"exposure-ranker rules: {summary['exposure_ranker_rule_candidate_count']}; "
        f"cooldown/quality rules: {summary['cooldown_quality_rule_candidate_count']}. "
        "No M13 registry, M12 account specs, broker readiness, broker connection, real order, live execution, or paper approval is changed."
    )


def build_shadow_ab_prep_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14.2 Broker Blocker Shadow A/B Prep",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Source shadow repair rows: `{summary['source_shadow_repair_rows']}`",
        f"- Runtime-registration candidates: `{summary['runtime_registration_candidate_count']}`",
        f"- Rule-only shadow candidates: `{summary['rule_only_candidate_count']}`",
        f"- Prep action counts: `{summary['prep_action_counts']}`",
        "- Boundary: prep only; no registry mutation, no account spec mutation, no broker readiness mutation.",
        "",
        "## Strategy Prep",
        "",
    ]
    for row in payload["strategy_summaries"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Symbols: `{', '.join(row['symbols'])}`",
                f"- Prep rows: `{row['prep_rows']}`",
                f"- Runtime-registration candidates: `{row['runtime_registration_candidate_count']}`",
                f"- Rule-only candidates: `{row['rule_only_candidate_count']}`",
                f"- Prep actions: `{row['prep_action_counts']}`",
                f"- Next action: {row['recommended_next_action']}",
                "",
            ]
        )
    lines.extend(["## Prep Rows", ""])
    for row in payload["rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} / {row['symbol']} / {row['timeframe']}",
                "",
                f"- Prep action: `{row['prep_action']}`",
                f"- Prep status: `{row['prep_status']}`",
                f"- Proposed shadow strategy: `{row['proposed_shadow_strategy_id'] or 'none'}`",
                f"- Proposed shadow runtime: `{row['proposed_shadow_runtime_id'] or 'none'}`",
                f"- Quantity source/proposed: `{row['source_quantity']} / {row['proposed_quantity']}`",
                f"- Risk source/proposed: `{row['source_risk_amount']} / {row['proposed_risk_amount']}`",
                f"- Original readiness remains blocked: `{row['original_readiness_status_remains_blocked']}`",
                f"- Hypothesis: {row['ab_test_hypothesis']}",
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
