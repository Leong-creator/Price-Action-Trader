#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_next_refresh_readiness.json"


@dataclass(frozen=True, slots=True)
class RescueNextRefreshReadinessConfig:
    stage: str
    rescue_optimization_backlog_path: Path
    rescue_zero_signal_diagnostics_path: Path
    rescue_ab_evidence_path: Path
    rescue_target_stop_shadow_normalization_path: Path
    broker_blocker_rule_shadow_evidence_path: Path
    readiness_json_path: Path
    readiness_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueNextRefreshReadinessConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueNextRefreshReadinessConfig(
        stage=str(payload["stage"]),
        rescue_optimization_backlog_path=resolve_repo_path(inputs["m14_rescue_optimization_backlog"]),
        rescue_zero_signal_diagnostics_path=resolve_repo_path(inputs["m14_rescue_zero_signal_diagnostics"]),
        rescue_ab_evidence_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        rescue_target_stop_shadow_normalization_path=resolve_repo_path(
            inputs["m14_rescue_target_stop_shadow_normalization"]
        ),
        broker_blocker_rule_shadow_evidence_path=resolve_repo_path(inputs["m14_2_broker_blocker_rule_shadow_evidence"]),
        readiness_json_path=resolve_repo_path(outputs["next_refresh_readiness_json"]),
        readiness_md_path=resolve_repo_path(outputs["next_refresh_readiness_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueNextRefreshReadinessConfig) -> None:
    if config.stage != "M14.rescue_next_refresh_readiness":
        raise ValueError("M14 rescue next refresh readiness stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue next refresh readiness must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue next refresh readiness cannot enable {key}")


def run_m14_rescue_next_refresh_readiness(
    config: RescueNextRefreshReadinessConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rescue_optimization_backlog = read_json(config.rescue_optimization_backlog_path)
    zero_signal_diagnostics = read_json(config.rescue_zero_signal_diagnostics_path)
    rescue_ab_evidence = read_json(config.rescue_ab_evidence_path)
    target_stop_shadow_normalization = read_json(config.rescue_target_stop_shadow_normalization_path)
    broker_rule_shadow_evidence = read_json(config.broker_blocker_rule_shadow_evidence_path)

    rows: list[dict[str, Any]] = []
    rows.extend(build_zero_signal_rows(zero_signal_diagnostics))
    rows.extend(build_first_ledger_rows(rescue_ab_evidence))
    rows.extend(build_broker_rule_shadow_rows(broker_rule_shadow_evidence))
    rows.sort(key=lambda row: (row["priority"], row["readiness_family"], row["strategy_id"], row["runtime_id"]))

    family_counts = Counter(row["readiness_family"] for row in rows)
    state_counts = Counter(row["readiness_state"] for row in rows)
    summary = {
        "source_rescue_backlog_rows": len(rescue_optimization_backlog.get("rescue_rows", [])),
        "watch_rows": len(rows),
        "fresh_quote_recheck_count": family_counts.get("fresh_quote_recheck", 0),
        "first_ledger_watch_count": family_counts.get("first_rescue_ledger_watch", 0),
        "broker_rule_shadow_watch_count": family_counts.get("broker_rule_shadow_recheck", 0),
        "target_stop_shadow_compare_count": family_counts.get("target_stop_shadow_compare", 0),
        "parent_detector_wait_count": family_counts.get("parent_detector_evidence_wait", 0),
        "next_refresh_dependent_count": sum(1 for row in rows if row["next_refresh_dependent"]),
        "parameter_change_allowed_now_count": 0,
        "ready_for_next_m12_47_refresh_count": sum(
            1 for row in rows if row["readiness_state"] == "ready_for_next_m12_47_refresh"
        ),
        "m13_registry_mutation_count": 0,
        "m12_account_specs_mutation_count": 0,
        "broker_readiness_status_mutation_count": 0,
        "readiness_family_counts": dict(sorted(family_counts.items())),
        "readiness_state_counts": dict(sorted(state_counts.items())),
        "broker_or_live_enabled": False,
    }
    payload = {
        "schema_version": "m14.rescue-next-refresh-readiness.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_rescue_optimization_backlog": project_path(config.rescue_optimization_backlog_path),
            "m14_rescue_zero_signal_diagnostics": project_path(config.rescue_zero_signal_diagnostics_path),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_path),
            "m14_rescue_target_stop_shadow_normalization": project_path(
                config.rescue_target_stop_shadow_normalization_path
            ),
            "m14_2_broker_blocker_rule_shadow_evidence": project_path(
                config.broker_blocker_rule_shadow_evidence_path
            ),
        },
        "summary": summary,
        "rows": rows,
        "target_stop_shadow_normalization_summary": dict(target_stop_shadow_normalization.get("summary", {})),
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
    write_json(config.readiness_json_path, payload)
    config.readiness_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.readiness_md_path.write_text(build_next_refresh_readiness_md(payload), encoding="utf-8")
    return payload


def build_zero_signal_rows(zero_signal_diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in zero_signal_diagnostics.get("rows", []):
        dominant_issue = str(row.get("dominant_issue", ""))
        if dominant_issue == "stale_quote_source_blocks_candidate":
            rows.append(
                base_readiness_row(
                    source_kind="zero_signal_diagnostics",
                    strategy_id=str(row.get("strategy_id", "")),
                    parent_strategy_id=str(row.get("parent_strategy_id", "")),
                    runtime_id=str(row.get("runtime_id", "")),
                    timeframe=str(row.get("timeframe", "")),
                    readiness_family="fresh_quote_recheck",
                    readiness_state="ready_for_next_m12_47_refresh",
                    priority="P0",
                    trigger_condition="Next M12.47-owned fresh Longbridge quote refresh produces current source rows.",
                    expected_evidence=(
                        f"{int_or_zero(row.get('eligible_if_fresh_quote_count'))} eligible candidates if the stale "
                        "quote gate clears."
                    ),
                    pass_action="Continue 10-day rescue A/B evidence collection without changing parameters.",
                    fail_action="Audit quote-refresh path before changing detector thresholds or risk settings.",
                    source_metrics={
                        "eligible_if_fresh_quote_count": int_or_zero(row.get("eligible_if_fresh_quote_count")),
                        "parent_source_row_count": int_or_zero(row.get("parent_source_row_count")),
                        "rejection_reason_counts": dict(row.get("rejection_reason_counts", {})),
                        "sample_symbols": list(row.get("sample_symbols", [])),
                    },
                    next_refresh_dependent=True,
                    row_key=dominant_issue,
                )
            )
        elif dominant_issue == "reward_filter_blocks_all":
            rows.append(
                base_readiness_row(
                    source_kind="zero_signal_diagnostics",
                    strategy_id=str(row.get("strategy_id", "")),
                    parent_strategy_id=str(row.get("parent_strategy_id", "")),
                    runtime_id=str(row.get("runtime_id", "")),
                    timeframe=str(row.get("timeframe", "")),
                    readiness_family="target_stop_shadow_compare",
                    readiness_state="covered_by_shadow_runtime_wait_refresh",
                    priority="P0",
                    trigger_condition="Next fresh run can compare the frozen rescue runtime with the normalized target/stop shadow runtime.",
                    expected_evidence="Frozen runtime remains unchanged; normalized shadow runtime should produce its own M13 ledger evidence.",
                    pass_action="Compare the normalized 1.0R shadow ledger against the frozen PA012 rescue runtime.",
                    fail_action="Inspect target/stop generation again; do not lower the frozen reward threshold directly.",
                    source_metrics={
                        "eligible_if_fresh_quote_count": int_or_zero(row.get("eligible_if_fresh_quote_count")),
                        "shadow_reward_min_r_pass_counts": dict(row.get("shadow_reward_min_r_pass_counts", {})),
                        "rejection_reason_counts": dict(row.get("rejection_reason_counts", {})),
                    },
                    next_refresh_dependent=True,
                    row_key=dominant_issue,
                )
            )
        elif dominant_issue == "parent_detector_zero_signal_for_timeframe":
            rows.append(
                base_readiness_row(
                    source_kind="zero_signal_diagnostics",
                    strategy_id=str(row.get("strategy_id", "")),
                    parent_strategy_id=str(row.get("parent_strategy_id", "")),
                    runtime_id=str(row.get("runtime_id", "")),
                    timeframe=str(row.get("timeframe", "")),
                    readiness_family="parent_detector_evidence_wait",
                    readiness_state="wait_same_timeframe_parent_evidence",
                    priority="P1",
                    trigger_condition="Parent detector produces same-timeframe source rows in a fresh run.",
                    expected_evidence="Parent detector must show valid same-timeframe source rows before rescue remapping.",
                    pass_action="Only then evaluate a same-timeframe rescue variant; do not remap across timeframes.",
                    fail_action="Keep waiting for parent evidence or start a separate detector redesign review.",
                    source_metrics={
                        "parent_audit_input_status": str(row.get("parent_audit_input_status", "")),
                        "parent_audit_source_row_count": int_or_zero(row.get("parent_audit_source_row_count")),
                    },
                    next_refresh_dependent=True,
                    row_key=dominant_issue,
                )
            )
    return rows


def build_first_ledger_rows(rescue_ab_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in rescue_ab_evidence.get("rows", []):
        if str(row.get("evidence_status", "")) != "no_m13_rescue_ledger_evidence_yet":
            continue
        runtime_ids = list(row.get("runtime_ids", []))
        rows.append(
            base_readiness_row(
                source_kind="rescue_ab_evidence_tracker",
                strategy_id=str(row.get("strategy_id", "")),
                parent_strategy_id=str(row.get("parent_strategy_id", "")),
                runtime_id=str(runtime_ids[0] if runtime_ids else ""),
                timeframe=str(runtime_ids[0]).rsplit("-", 1)[-1] if runtime_ids else "",
                readiness_family="first_rescue_ledger_watch",
                readiness_state="ready_for_next_m12_47_refresh",
                priority="P0",
                trigger_condition="Next M12.47/M13 refresh writes the first rescue signal/account ledger row.",
                expected_evidence="M13 signal/account ledger row count becomes greater than zero for this rescue runtime.",
                pass_action="Start counting its own 10 rescue A/B trading days from the fresh ledger evidence.",
                fail_action="Audit M13 registry, M12 account specs input mapping, and ledger write path.",
                source_metrics={
                    "m13_signal_ledger_row_count": int_or_zero(row.get("m13_signal_ledger_row_count")),
                    "m13_account_ledger_row_count": int_or_zero(row.get("m13_account_ledger_row_count")),
                    "observed_trading_days_count": int_or_zero(row.get("observed_trading_days_count")),
                },
                next_refresh_dependent=True,
                row_key=str(row.get("evidence_status", "")),
            )
        )
    return rows


def build_broker_rule_shadow_rows(broker_rule_shadow_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in broker_rule_shadow_evidence.get("rows", []):
        rows.append(
            base_readiness_row(
                source_kind="broker_rule_shadow_evidence",
                strategy_id=str(row.get("strategy_id", "")),
                parent_strategy_id=str(row.get("strategy_id", "")),
                runtime_id=str(row.get("runtime_id", "")),
                timeframe=str(row.get("timeframe", "")),
                readiness_family="broker_rule_shadow_recheck",
                readiness_state="ready_for_next_m12_47_refresh",
                priority="P0",
                trigger_condition="Next internal-sim risk check produces comparable PA005 broker-blocker rows.",
                expected_evidence=str(row.get("comparison_contract", "")),
                pass_action="Record whether exposure ranking or cooldown/quality veto would reduce blockers without unblocking readiness.",
                fail_action="Keep original broker readiness blocked and refine only the rule contract.",
                source_metrics={
                    "rule_family": str(row.get("rule_family", "")),
                    "source_reason_codes": list(row.get("source_reason_codes", [])),
                    "source_quantity": str(row.get("source_quantity", "")),
                    "source_risk_amount": str(row.get("source_risk_amount", "")),
                    "source_notional_exposure": str(row.get("source_notional_exposure", "")),
                    "symbol": str(row.get("symbol", "")),
                },
                next_refresh_dependent=True,
                row_key=str(row.get("signal_id", "")) or str(row.get("rule_family", "")),
            )
        )
    return rows


def base_readiness_row(
    *,
    source_kind: str,
    strategy_id: str,
    parent_strategy_id: str,
    runtime_id: str,
    timeframe: str,
    readiness_family: str,
    readiness_state: str,
    priority: str,
    trigger_condition: str,
    expected_evidence: str,
    pass_action: str,
    fail_action: str,
    source_metrics: dict[str, Any],
    next_refresh_dependent: bool,
    row_key: str = "",
) -> dict[str, Any]:
    return {
        "row_id": (
            f"m14-next-refresh-{slug(source_kind)}-{slug(strategy_id)}-"
            f"{slug(runtime_id or readiness_family)}-{slug(row_key or readiness_family)}"
        ),
        "source_kind": source_kind,
        "strategy_id": strategy_id,
        "parent_strategy_id": parent_strategy_id,
        "runtime_id": runtime_id,
        "timeframe": timeframe,
        "readiness_family": readiness_family,
        "readiness_state": readiness_state,
        "priority": priority,
        "trigger_condition": trigger_condition,
        "expected_evidence_after_refresh": expected_evidence,
        "pass_action": pass_action,
        "fail_action": fail_action,
        "source_metrics": source_metrics,
        "next_refresh_dependent": next_refresh_dependent,
        "parameter_change_allowed_now": False,
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


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Next-refresh rescue readiness tracks {summary['watch_rows']} rows: "
        f"{summary['fresh_quote_recheck_count']} fresh-quote rechecks, "
        f"{summary['first_ledger_watch_count']} first-ledger watches, "
        f"{summary['broker_rule_shadow_watch_count']} PA005 broker-rule shadow rechecks, "
        f"{summary['target_stop_shadow_compare_count']} target/stop shadow comparisons, and "
        f"{summary['parent_detector_wait_count']} parent-detector waits. "
        f"Parameter changes allowed now: {summary['parameter_change_allowed_now_count']}. "
        "No registry, account-spec, broker readiness, broker connection, real order, live execution, or paper approval is changed."
    )


def build_next_refresh_readiness_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue Next Refresh Readiness",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Watch rows: `{summary['watch_rows']}`",
        f"- Fresh-quote rechecks: `{summary['fresh_quote_recheck_count']}`",
        f"- First-ledger watches: `{summary['first_ledger_watch_count']}`",
        f"- Broker-rule shadow rechecks: `{summary['broker_rule_shadow_watch_count']}`",
        f"- Target/stop shadow comparisons: `{summary['target_stop_shadow_compare_count']}`",
        f"- Parent-detector waits: `{summary['parent_detector_wait_count']}`",
        f"- Parameter changes allowed now: `{summary['parameter_change_allowed_now_count']}`",
        "- Boundary: next-refresh readiness only; no runtime registration, registry mutation, account spec mutation, or broker readiness mutation.",
        "",
        "## Watch Rows",
        "",
    ]
    for row in payload["rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} / {row['runtime_id'] or row['readiness_family']}",
                "",
                f"- Priority: `{row['priority']}`",
                f"- Family: `{row['readiness_family']}`",
                f"- State: `{row['readiness_state']}`",
                f"- Trigger: {row['trigger_condition']}",
                f"- Expected evidence: {row['expected_evidence_after_refresh']}",
                f"- Pass action: {row['pass_action']}",
                f"- Fail action: {row['fail_action']}",
                f"- Parameter change allowed now: `{row['parameter_change_allowed_now']}`",
                "",
            ]
        )
    lines.extend(["## Summary", "", payload["plain_language_result"], ""])
    return "\n".join(lines)


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
