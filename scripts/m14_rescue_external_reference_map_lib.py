#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_external_reference_map.json"


@dataclass(frozen=True, slots=True)
class RescueExternalReferenceMapConfig:
    stage: str
    project_stage_assessment_path: Path
    rescue_optimization_backlog_path: Path
    rescue_zero_signal_diagnostics_path: Path
    rescue_next_refresh_readiness_path: Path
    rescue_target_stop_diagnostics_path: Path
    reference_map_json_path: Path
    reference_map_md_path: Path
    external_reference_patterns: tuple[dict[str, str], ...]
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueExternalReferenceMapConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueExternalReferenceMapConfig(
        stage=str(payload["stage"]),
        project_stage_assessment_path=resolve_repo_path(inputs["m14_project_stage_assessment"]),
        rescue_optimization_backlog_path=resolve_repo_path(inputs["m14_rescue_optimization_backlog"]),
        rescue_zero_signal_diagnostics_path=resolve_repo_path(inputs["m14_rescue_zero_signal_diagnostics"]),
        rescue_next_refresh_readiness_path=resolve_repo_path(inputs["m14_rescue_next_refresh_readiness"]),
        rescue_target_stop_diagnostics_path=resolve_repo_path(inputs["m14_rescue_target_stop_diagnostics"]),
        reference_map_json_path=resolve_repo_path(outputs["reference_map_json"]),
        reference_map_md_path=resolve_repo_path(outputs["reference_map_md"]),
        external_reference_patterns=tuple(
            {str(key): str(value) for key, value in item.items()}
            for item in payload.get("external_reference_patterns", [])
        ),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueExternalReferenceMapConfig) -> None:
    if config.stage != "M14.rescue_external_reference_map":
        raise ValueError("M14 rescue external reference map stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue external reference map must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval", "manual_m12_37_once"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue external reference map cannot enable {key}")
    pattern_ids = {str(item.get("pattern_id", "")) for item in config.external_reference_patterns}
    required = {
        "ai_trader_shadow_signal_scoreboard",
        "tradingagents_role_decomposed_review",
        "tradingagents_persistent_decision_log",
    }
    if not required.issubset(pattern_ids):
        raise ValueError("M14 rescue external reference map missing required external reference patterns")


def run_m14_rescue_external_reference_map(
    config: RescueExternalReferenceMapConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    stage = read_json(config.project_stage_assessment_path)
    backlog = read_json(config.rescue_optimization_backlog_path)
    zero_signal = read_json(config.rescue_zero_signal_diagnostics_path)
    next_refresh = read_json(config.rescue_next_refresh_readiness_path)
    target_stop = read_json(config.rescue_target_stop_diagnostics_path)

    zero_by_strategy = {str(row.get("strategy_id", "")): row for row in zero_signal.get("rows", [])}
    next_watch_by_strategy = group_rows_by_strategy(list(next_refresh.get("rows", [])))
    target_stop_strategy_ids = {
        str(row.get("strategy_id", ""))
        for row in target_stop.get("rows", [])
        if str(row.get("strategy_id", ""))
    }

    rescue_rows = [
        build_rescue_reference_row(
            row=dict(row),
            zero_diag=dict(zero_by_strategy.get(str(row.get("strategy_id", "")), {})),
            next_watch_rows=next_watch_by_strategy.get(str(row.get("strategy_id", "")), []),
            target_stop_strategy_ids=target_stop_strategy_ids,
        )
        for row in backlog.get("rescue_rows", [])
    ]
    rescue_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))

    blocker_rows = [
        build_broker_blocker_reference_row(dict(row))
        for row in backlog.get("broker_dry_run_blockers", [])
    ]
    blocker_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))

    pattern_counts = Counter()
    issue_counts = Counter(row["issue_type"] for row in rescue_rows)
    for row in rescue_rows + blocker_rows:
        pattern_counts.update(row["external_reference_pattern_ids"])

    next_summary = next_refresh.get("summary", {})
    stage_summary = stage.get("summary", {})
    summary = {
        "project_stage": str(stage_summary.get("current_project_stage", "")),
        "ten_day_challenge_complete": bool(stage_summary.get("ten_day_challenge_complete", False)),
        "mapped_rescue_row_count": len(rescue_rows),
        "broker_blocker_reference_row_count": len(blocker_rows),
        "p0_reference_row_count": sum(1 for row in rescue_rows + blocker_rows if row["priority"] == "P0"),
        "next_refresh_dependent_count": int_or_zero(next_summary.get("next_refresh_dependent_count")),
        "parameter_change_allowed_now_count": int_or_zero(next_summary.get("parameter_change_allowed_now_count")),
        "external_reference_project_count": len({item["project"] for item in config.external_reference_patterns}),
        "external_reference_pattern_counts": dict(sorted(pattern_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "copy_trading_allowed": False,
        "external_decision_can_override_local_gate": False,
        "broker_or_live_enabled": False,
        "manual_m12_37_once_allowed": False,
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-external-reference-map.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_project_stage_assessment": project_path(config.project_stage_assessment_path),
            "m14_rescue_optimization_backlog": project_path(config.rescue_optimization_backlog_path),
            "m14_rescue_zero_signal_diagnostics": project_path(config.rescue_zero_signal_diagnostics_path),
            "m14_rescue_next_refresh_readiness": project_path(config.rescue_next_refresh_readiness_path),
            "m14_rescue_target_stop_diagnostics": project_path(config.rescue_target_stop_diagnostics_path),
        },
        "external_reference_patterns": list(config.external_reference_patterns),
        "summary": summary,
        "rescue_reference_rows": rescue_rows,
        "broker_blocker_reference_rows": blocker_rows,
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
            "manual_m12_37_once": False,
        },
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.reference_map_json_path, payload)
    config.reference_map_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.reference_map_md_path.write_text(build_reference_map_md(payload), encoding="utf-8")
    return payload


def group_rows_by_strategy(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strategy_id = str(row.get("strategy_id", ""))
        if strategy_id:
            grouped[strategy_id].append(row)
    return grouped


def build_rescue_reference_row(
    *,
    row: dict[str, Any],
    zero_diag: dict[str, Any],
    next_watch_rows: list[dict[str, Any]],
    target_stop_strategy_ids: set[str],
) -> dict[str, Any]:
    issue_type = str(row.get("issue_type", ""))
    strategy_id = str(row.get("strategy_id", ""))
    dominant_issue = str(zero_diag.get("dominant_issue", ""))
    readiness_families = sorted({str(item.get("readiness_family", "")) for item in next_watch_rows if item.get("readiness_family")})
    pattern_ids = external_patterns_for_rescue_row(
        issue_type=issue_type,
        dominant_issue=dominant_issue,
        readiness_families=readiness_families,
        has_target_stop_diagnostic=strategy_id in target_stop_strategy_ids,
    )
    return {
        "reference_row_id": f"m14-ext-ref-{slug(strategy_id)}",
        "strategy_id": strategy_id,
        "parent_strategy_id": str(row.get("parent_strategy_id", "")),
        "runtime_ids": list(row.get("runtime_ids", [])),
        "priority": str(row.get("priority", "")),
        "issue_type": issue_type,
        "dominant_zero_signal_issue": dominant_issue,
        "readiness_families": readiness_families,
        "external_reference_pattern_ids": pattern_ids,
        "local_review_lanes": local_review_lanes_for_patterns(pattern_ids),
        "local_application": local_application_for_row(
            issue_type=issue_type,
            dominant_issue=dominant_issue,
            readiness_families=readiness_families,
        ),
        "pre_refresh_action": pre_refresh_action_for_row(issue_type, dominant_issue),
        "post_refresh_acceptance_check": post_refresh_acceptance_for_row(issue_type, readiness_families),
        "parameter_change_allowed_now": False,
        "promotion_gate": "10 rescue A/B trading days plus manual M14 review",
        "copy_trading_allowed": False,
        "external_decision_can_override_local_gate": False,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
    }


def build_broker_blocker_reference_row(row: dict[str, Any]) -> dict[str, Any]:
    reason_counts = dict(row.get("reason_counts", {}))
    pattern_ids = [
        "tradingagents_role_decomposed_review",
        "tradingagents_persistent_decision_log",
    ]
    if "max_risk_per_order_exceeded" in reason_counts:
        pattern_ids.append("ai_trader_shadow_signal_scoreboard")
    return {
        "reference_row_id": f"m14-ext-ref-broker-{slug(str(row.get('strategy_id', '')))}",
        "strategy_id": str(row.get("strategy_id", "")),
        "priority": str(row.get("priority", "")),
        "blocked_count": int_or_zero(row.get("blocked_count")),
        "reason_counts": reason_counts,
        "external_reference_pattern_ids": sorted(set(pattern_ids)),
        "local_review_lanes": local_review_lanes_for_patterns(sorted(set(pattern_ids))),
        "local_application": (
            "Use a TradingAgents-style risk/portfolio split to decide whether the blocker is a sizing, exposure, "
            "or cooldown issue; keep broker readiness rows blocked until internal-sim evidence improves."
        ),
        "pre_refresh_action": "Prepare blocker comparison fields only; do not mutate broker readiness or run live/paper broker paths.",
        "post_refresh_acceptance_check": "After the next M12.47-owned refresh, compare dry-run blocker counts and reason codes without unblocking broker readiness.",
        "parameter_change_allowed_now": False,
        "copy_trading_allowed": False,
        "external_decision_can_override_local_gate": False,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
    }


def external_patterns_for_rescue_row(
    *,
    issue_type: str,
    dominant_issue: str,
    readiness_families: list[str],
    has_target_stop_diagnostic: bool,
) -> list[str]:
    patterns = {
        "tradingagents_role_decomposed_review",
        "tradingagents_persistent_decision_log",
    }
    if issue_type in {"missing_rescue_ledger", "collect_more_ab_evidence", "signal_generated_no_account_operation"}:
        patterns.add("ai_trader_shadow_signal_scoreboard")
    if "first_rescue_ledger_watch" in readiness_families:
        patterns.add("ai_trader_shadow_signal_scoreboard")
    if dominant_issue == "stale_quote_source_blocks_candidate":
        patterns.add("ai_trader_shadow_signal_scoreboard")
    if has_target_stop_diagnostic:
        patterns.add("tradingagents_role_decomposed_review")
    return sorted(patterns)


def local_review_lanes_for_patterns(pattern_ids: list[str]) -> list[str]:
    lanes: list[str] = []
    if "ai_trader_shadow_signal_scoreboard" in pattern_ids:
        lanes.append("shadow_signal_scoreboard")
    if "tradingagents_role_decomposed_review" in pattern_ids:
        lanes.extend(["technical_evidence_review", "bull_bear_objection_review", "risk_portfolio_review"])
    if "tradingagents_persistent_decision_log" in pattern_ids:
        lanes.append("decision_log_audit")
    return lanes


def local_application_for_row(issue_type: str, dominant_issue: str, readiness_families: list[str]) -> str:
    if issue_type == "missing_rescue_ledger":
        return "Treat external signal-sync ideas as a local ledger-chain checklist: registry, input spec, signal ledger, account ledger."
    if issue_type == "zero_signal_after_connection" and dominant_issue == "stale_quote_source_blocks_candidate":
        return "Use a shadow signal scoreboard only after fresh M12.47 data; stale/fallback source rows cannot justify parameter changes."
    if issue_type == "zero_signal_after_connection" and dominant_issue == "reward_filter_blocks_all":
        return "Use role-decomposed review to separate entry geometry, stop/target geometry, and reward/R policy before changing thresholds."
    if issue_type == "zero_signal_after_connection" and dominant_issue == "parent_detector_zero_signal_for_timeframe":
        return "Use bull/bear detector review to challenge the same-timeframe mapping; do not remap across timeframes without parent evidence."
    if issue_type == "collect_more_ab_evidence":
        return "Use a local scoreboard and decision log to keep baseline-vs-rescue evidence comparable until the 10-day rescue window is complete."
    if "broker_rule_shadow_recheck" in readiness_families:
        return "Use risk/portfolio split review for exposure, cooldown, and quality-veto evidence; broker readiness stays dry-run blocked."
    return "Use external projects only as review patterns; local M13/M14 evidence remains the only promotion input."


def pre_refresh_action_for_row(issue_type: str, dominant_issue: str) -> str:
    if issue_type == "missing_rescue_ledger":
        return "Prepare mapping audit fields now; actual pass/fail waits for the next M12.47-owned fresh refresh."
    if issue_type == "zero_signal_after_connection" and dominant_issue == "stale_quote_source_blocks_candidate":
        return "Do not tune thresholds now; wait for fresh quote evidence and compare source/signal counts."
    if issue_type == "zero_signal_after_connection" and dominant_issue == "reward_filter_blocks_all":
        return "Keep frozen runtime unchanged; use the existing target/stop shadow runtime as the only local comparison hook."
    if issue_type == "collect_more_ab_evidence":
        return "Keep collecting A/B evidence; no promotion or rejection before the 10-day rescue window is proven."
    return "Prepare review notes only; no parameter, registry, account-spec, or broker readiness mutation before fresh evidence."


def post_refresh_acceptance_for_row(issue_type: str, readiness_families: list[str]) -> str:
    if issue_type == "missing_rescue_ledger" or "first_rescue_ledger_watch" in readiness_families:
        return "A first M13 signal or account ledger row appears for the rescue runtime; then start its own 10-day evidence count."
    if "fresh_quote_recheck" in readiness_families:
        return "Fresh quote run produces nonzero source or signal evidence without using fallback quotes."
    if "target_stop_shadow_compare" in readiness_families:
        return "Normalized target/stop shadow runtime emits comparable M13 ledger evidence against the frozen rescue runtime."
    if "parent_detector_evidence_wait" in readiness_families:
        return "Parent detector produces same-timeframe evidence before the rescue mapping is reconsidered."
    return "Continue local A/B evidence collection and record the decision-log reason for hold/modify/reject."


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"External-reference map covered {summary['mapped_rescue_row_count']} rescue rows and "
        f"{summary['broker_blocker_reference_row_count']} broker-blocker rows using "
        f"{summary['external_reference_project_count']} external projects as architecture references only. "
        f"{summary['next_refresh_dependent_count']} checks still depend on the next M12.47-owned fresh refresh, "
        f"parameter changes allowed now remain {summary['parameter_change_allowed_now_count']}, "
        "and copy trading, external override, broker connection, real orders, live execution, paper approval, "
        "and manual M12.37 once-mode stay disabled."
    )


def build_reference_map_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue External Reference Map",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Project stage: `{summary['project_stage']}`",
        f"- 10-day challenge complete: `{summary['ten_day_challenge_complete']}`",
        f"- Rescue rows mapped: `{summary['mapped_rescue_row_count']}`",
        f"- Broker blocker rows mapped: `{summary['broker_blocker_reference_row_count']}`",
        f"- P0 reference rows: `{summary['p0_reference_row_count']}`",
        f"- Next-refresh dependent checks: `{summary['next_refresh_dependent_count']}`",
        f"- Parameter changes allowed now: `{summary['parameter_change_allowed_now_count']}`",
        "- Boundary: external projects are architecture references only; No copy trading, broker sync, external override, real orders, live execution, or manual M12.37 once-mode.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## External Reference Patterns",
        "",
    ]
    for pattern in payload["external_reference_patterns"]:
        lines.extend(
            [
                f"### {pattern['pattern_id']}",
                "",
                f"- Project: `{pattern['project']}`",
                f"- URL: {pattern['url']}",
                f"- Allowed use: {pattern['allowed_use']}",
                f"- Forbidden use: {pattern['forbidden_use']}",
                "",
            ]
        )
    lines.extend(["## Rescue Rows", ""])
    for row in payload["rescue_reference_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Priority: `{row['priority']}`",
                f"- Issue: `{row['issue_type']}`",
                f"- Dominant zero-signal issue: `{row['dominant_zero_signal_issue']}`",
                f"- Patterns: `{', '.join(row['external_reference_pattern_ids'])}`",
                f"- Local application: {row['local_application']}",
                f"- Pre-refresh action: {row['pre_refresh_action']}",
                f"- Post-refresh check: {row['post_refresh_acceptance_check']}",
                "",
            ]
        )
    lines.extend(["## Broker Blocker Rows", ""])
    for row in payload["broker_blocker_reference_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Priority: `{row['priority']}`",
                f"- Blocked count: `{row['blocked_count']}`",
                f"- Reasons: `{row['reason_counts']}`",
                f"- Patterns: `{', '.join(row['external_reference_pattern_ids'])}`",
                f"- Local application: {row['local_application']}",
                "",
            ]
        )
    return "\n".join(lines)


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def slug(value: str) -> str:
    chars: list[str] = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    return "-".join(part for part in "".join(chars).split("-") if part)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
