#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_ab_evidence_tracker.json"
BLOCKING_LEDGER_STATES = frozenset({"not_connected", "detector_missing", "missing_data"})
ACTIVE_OPERATION_TYPES = frozenset({"open", "close", "risk_blocked"})


@dataclass(frozen=True, slots=True)
class RescueAbEvidenceTrackerConfig:
    stage: str
    rescue_coverage_path: Path
    paper_gate_path: Path
    scorecard_path: Path
    signal_ledger_path: Path
    account_ledger_path: Path
    tracker_json_path: Path
    tracker_md_path: Path
    min_ab_trading_days: int
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueAbEvidenceTrackerConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueAbEvidenceTrackerConfig(
        stage=str(payload["stage"]),
        rescue_coverage_path=resolve_repo_path(inputs["m14_rescue_runtime_coverage"]),
        paper_gate_path=resolve_repo_path(inputs["m14_paper_trial_gate"]),
        scorecard_path=resolve_repo_path(inputs["m13_daily_strategy_scorecard"]),
        signal_ledger_path=resolve_repo_path(inputs["m13_strategy_signal_ledger"]),
        account_ledger_path=resolve_repo_path(inputs["m13_account_operation_ledger"]),
        tracker_json_path=resolve_repo_path(outputs["tracker_json"]),
        tracker_md_path=resolve_repo_path(outputs["tracker_md"]),
        min_ab_trading_days=int(payload["min_ab_trading_days"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueAbEvidenceTrackerConfig) -> None:
    if config.stage != "M14.rescue_ab_evidence_tracker":
        raise ValueError("M14 rescue A/B evidence tracker stage drift")
    if config.min_ab_trading_days != 10:
        raise ValueError("M14 rescue A/B evidence must require 10 trading days")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue A/B evidence tracker must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue A/B evidence tracker cannot enable {key}")


def run_m14_rescue_ab_evidence_tracker(
    config: RescueAbEvidenceTrackerConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rescue_coverage = read_json(config.rescue_coverage_path)
    paper_gate = read_json(config.paper_gate_path)
    scorecard = read_json(config.scorecard_path)
    signal_ledger_rows = read_jsonl(config.signal_ledger_path)
    account_ledger_rows = read_jsonl(config.account_ledger_path)

    gate_by_strategy_id = {str(row.get("strategy_id", "")): row for row in paper_gate.get("rows", [])}
    scorecard_by_strategy_id = {str(row.get("strategy_id", "")): row for row in scorecard.get("rows", [])}
    evidence_rows = [
        build_evidence_row(
            coverage_row=dict(row),
            gate_by_strategy_id=gate_by_strategy_id,
            scorecard_by_strategy_id=scorecard_by_strategy_id,
            signal_ledger_rows=signal_ledger_rows,
            account_ledger_rows=account_ledger_rows,
            min_ab_trading_days=config.min_ab_trading_days,
        )
        for row in rescue_coverage.get("rows", [])
    ]
    evidence_rows.sort(key=lambda row: row["strategy_id"])

    ready_rows = [row for row in evidence_rows if row["evidence_status"] == "evidence_ready_for_manual_review"]
    collecting_rows = [row for row in evidence_rows if row["evidence_status"] == "collecting_ab_evidence"]
    no_ledger_rows = [row for row in evidence_rows if row["evidence_status"] == "no_m13_rescue_ledger_evidence_yet"]
    blocked_rows = [row for row in evidence_rows if row["has_blocking_ledger_state"]]
    pending_rows = [row for row in evidence_rows if not row["meets_min_ab_trading_days"]]

    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-ab-evidence-tracker.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_rescue_runtime_coverage": project_path(config.rescue_coverage_path),
            "m14_paper_trial_gate": project_path(config.paper_gate_path),
            "m13_daily_strategy_scorecard": project_path(config.scorecard_path),
            "m13_strategy_signal_ledger": project_path(config.signal_ledger_path),
            "m13_account_operation_ledger": project_path(config.account_ledger_path),
        },
        "min_ab_trading_days": config.min_ab_trading_days,
        "rescue_runtime_coverage_complete": bool(
            rescue_coverage.get("all_registered_rescue_inputs_connected")
            and rescue_coverage.get("all_planned_rescue_actions_have_runtime_coverage")
        ),
        "summary": {
            "rescue_runtime_strategy_count": len(evidence_rows),
            "m13_ledger_observed_strategy_count": sum(1 for row in evidence_rows if row["observed_trading_days_count"] > 0),
            "no_m13_ledger_evidence_count": len(no_ledger_rows),
            "collecting_evidence_count": len(collecting_rows),
            "evidence_ready_for_manual_review_count": len(ready_rows),
            "blocking_ledger_state_count": len(blocked_rows),
            "promotion_allowed_count": 0,
            "pending_evidence_strategy_ids": [row["strategy_id"] for row in pending_rows],
            "no_m13_ledger_evidence_strategy_ids": [row["strategy_id"] for row in no_ledger_rows],
            "evidence_ready_for_manual_review_strategy_ids": [row["strategy_id"] for row in ready_rows],
            "blocking_ledger_state_strategy_ids": [row["strategy_id"] for row in blocked_rows],
        },
        "promotion_policy": {
            "connected_runtime_is_not_passed": True,
            "parent_strategy_evidence_does_not_count_for_rescue_variant": True,
            "required_ab_trading_days": config.min_ab_trading_days,
            "auto_promotion_allowed": False,
            "manual_m14_review_required_after_min_days": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
        },
        "paper_or_live_approval": False,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
        },
        "rows": evidence_rows,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.tracker_json_path, payload)
    config.tracker_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.tracker_md_path.write_text(build_tracker_md(payload), encoding="utf-8")
    return payload


def build_evidence_row(
    *,
    coverage_row: dict[str, Any],
    gate_by_strategy_id: dict[str, dict[str, Any]],
    scorecard_by_strategy_id: dict[str, dict[str, Any]],
    signal_ledger_rows: list[dict[str, Any]],
    account_ledger_rows: list[dict[str, Any]],
    min_ab_trading_days: int,
) -> dict[str, Any]:
    strategy_id = str(coverage_row.get("strategy_id", ""))
    parent_strategy_id = str(coverage_row.get("parent_strategy_id", ""))
    runtime_ids = {str(item) for item in coverage_row.get("runtime_ids", []) if str(item)}
    signal_rows = matching_rescue_rows(signal_ledger_rows, strategy_id, runtime_ids)
    account_rows = matching_rescue_rows(account_ledger_rows, strategy_id, runtime_ids)
    observed_days = sorted(
        {
            str(row.get("trading_date", ""))
            for row in signal_rows + account_rows
            if str(row.get("trading_date", ""))
        }
    )
    signal_days = sorted(
        {
            str(row.get("trading_date", ""))
            for row in signal_rows
            if int_or_zero(row.get("signal_count")) > 0 and str(row.get("trading_date", ""))
        }
    )
    operation_days = sorted(
        {
            str(row.get("trading_date", ""))
            for row in account_rows
            if str(row.get("event_type", "")) in ACTIVE_OPERATION_TYPES and str(row.get("trading_date", ""))
        }
    )
    test_states = sorted({str(row.get("test_state", "")) for row in signal_rows + account_rows if row.get("test_state")})
    blocking_states = sorted(state for state in test_states if state in BLOCKING_LEDGER_STATES)
    observed_count = len(observed_days)
    meets_min_days = observed_count >= min_ab_trading_days
    evidence_status = evidence_status_for_row(coverage_row, signal_rows, account_rows, observed_count, min_ab_trading_days)
    scorecard_row = dict(scorecard_by_strategy_id.get(strategy_id, {}))
    parent_gate_row = dict(gate_by_strategy_id.get(parent_strategy_id, {}))

    return {
        "strategy_id": strategy_id,
        "parent_strategy_id": parent_strategy_id,
        "coverage_status": str(coverage_row.get("coverage_status", "")),
        "runtime_ids": sorted(runtime_ids),
        "timeframes": list(coverage_row.get("timeframes", [])),
        "variant_ids": list(coverage_row.get("variant_ids", [])),
        "required_ab_trading_days": min_ab_trading_days,
        "observed_trading_days": observed_days,
        "observed_trading_days_count": observed_count,
        "remaining_ab_trading_days": max(0, min_ab_trading_days - observed_count),
        "meets_min_ab_trading_days": meets_min_days,
        "signal_trading_days": signal_days,
        "operation_trading_days": operation_days,
        "latest_trading_date": observed_days[-1] if observed_days else "",
        "m13_signal_ledger_row_count": len(signal_rows),
        "m13_account_ledger_row_count": len(account_rows),
        "scorecard_row_present": bool(scorecard_row),
        "scorecard_test_states": str(scorecard_row.get("test_states", "")),
        "scorecard_ledger_state_count": int_or_zero(scorecard_row.get("ledger_state_count")),
        "signal_count": sum(int_or_zero(row.get("signal_count")) for row in signal_rows),
        "source_row_count": sum(int_or_zero(row.get("source_row_count")) for row in signal_rows),
        "open_count": sum(1 for row in account_rows if str(row.get("event_type", "")) == "open"),
        "close_count": sum(1 for row in account_rows if str(row.get("event_type", "")) == "close"),
        "risk_blocked_count": sum(
            1
            for row in account_rows
            if str(row.get("event_type", "")) == "risk_blocked" or str(row.get("test_state", "")) == "risk_blocked"
        ),
        "no_account_operation_count": sum(1 for row in account_rows if str(row.get("event_type", "")) == "no_account_operation"),
        "test_states": test_states,
        "has_blocking_ledger_state": bool(blocking_states),
        "blocking_ledger_states": blocking_states,
        "parent_gate_decision": str(parent_gate_row.get("decision", "")),
        "parent_paper_trial_gate": str(parent_gate_row.get("paper_trial_gate", "")),
        "evidence_status": evidence_status,
        "ready_for_manual_review": evidence_status == "evidence_ready_for_manual_review",
        "can_promote": False,
        "promotion_blocked_reason": promotion_blocked_reason(evidence_status, blocking_states),
        "parent_strategy_evidence_counted": False,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def matching_rescue_rows(
    rows: list[dict[str, Any]],
    strategy_id: str,
    runtime_ids: set[str],
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("strategy_id", "")) == strategy_id or str(row.get("runtime_id", "")) in runtime_ids
    ]


def evidence_status_for_row(
    coverage_row: dict[str, Any],
    signal_rows: list[dict[str, Any]],
    account_rows: list[dict[str, Any]],
    observed_count: int,
    min_ab_trading_days: int,
) -> str:
    if str(coverage_row.get("coverage_status", "")) != "connected_not_promoted":
        return "runtime_coverage_not_ready"
    if not signal_rows and not account_rows:
        return "no_m13_rescue_ledger_evidence_yet"
    if observed_count < min_ab_trading_days:
        return "collecting_ab_evidence"
    return "evidence_ready_for_manual_review"


def promotion_blocked_reason(evidence_status: str, blocking_states: list[str]) -> str:
    if evidence_status == "runtime_coverage_not_ready":
        return "runtime_input_coverage_not_ready"
    if evidence_status == "no_m13_rescue_ledger_evidence_yet":
        return "no_m13_rescue_ledger_rows_yet"
    if evidence_status == "collecting_ab_evidence":
        return "needs_10_trading_days_ab_evidence"
    if blocking_states:
        return "blocking_ledger_states_require_fix_before_review"
    return "manual_m14_review_and_metrics_gate_required"


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Rescue A/B evidence is observed for {summary['m13_ledger_observed_strategy_count']}/"
        f"{summary['rescue_runtime_strategy_count']} rescue strategies. "
        f"{summary['evidence_ready_for_manual_review_count']} have at least "
        f"{payload['min_ab_trading_days']} trading days of rescue-ledger evidence; "
        f"{summary['no_m13_ledger_evidence_count']} have no M13 rescue ledger rows yet. "
        "No rescue strategy is auto-promoted; broker connection, real orders, live execution, and paper-trading approval remain disabled."
    )


def build_tracker_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue A/B Evidence Tracker",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Rescue strategies with M13 ledger evidence: `{summary['m13_ledger_observed_strategy_count']}/{summary['rescue_runtime_strategy_count']}`",
        f"- Ready for manual review after min days: `{summary['evidence_ready_for_manual_review_count']}`",
        f"- No M13 rescue ledger evidence yet: `{summary['no_m13_ledger_evidence_count']}`",
        f"- Promotion allowed count: `{summary['promotion_allowed_count']}`",
        "- Boundary: internal simulated only; no broker connection, no real orders, no live execution.",
        "- Policy: parent strategy evidence does not count for the rescue variant; every rescue variant needs its own 10 trading-day ledger.",
        "",
        "## Rows",
    ]
    for row in payload["rows"]:
        lines.extend(
            [
                "",
                f"### {row['strategy_id']}",
                "",
                f"- Parent: `{row['parent_strategy_id']}`",
                f"- Runtime ids: `{', '.join(row['runtime_ids'])}`",
                f"- Evidence status: `{row['evidence_status']}`",
                f"- Observed trading days: `{row['observed_trading_days_count']}/{row['required_ab_trading_days']}`",
                f"- Signal / open / close / risk-blocked: `{row['signal_count']} / {row['open_count']} / {row['close_count']} / {row['risk_blocked_count']}`",
                f"- Promotion blocked reason: `{row['promotion_blocked_reason']}`",
            ]
        )
    lines.extend(["", "## Summary", "", payload["plain_language_result"], ""])
    return "\n".join(lines)


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
