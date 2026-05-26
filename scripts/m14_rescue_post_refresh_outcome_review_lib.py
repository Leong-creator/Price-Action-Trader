#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_post_refresh_outcome_review.json"
PASS_STATUSES = frozenset({"passed", "evidence_observed"})
FAIL_STATUSES = frozenset(
    {
        "failed_missing_first_ledger_after_fresh_refresh",
        "failed_zero_signal_after_fresh_refresh",
        "failed_missing_shadow_ledger_after_fresh_refresh",
        "failed_missing_comparable_broker_row_after_fresh_refresh",
        "still_waiting_parent_detector_after_fresh_refresh",
        "unsupported_watch_family",
    }
)


@dataclass(frozen=True, slots=True)
class RescuePostRefreshOutcomeReviewConfig:
    stage: str
    next_refresh_readiness_path: Path
    rescue_ab_evidence_path: Path
    scorecard_path: Path
    signal_ledger_path: Path
    account_ledger_path: Path
    dashboard_path: Path
    broker_readiness_path: Path
    outcome_json_path: Path
    outcome_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescuePostRefreshOutcomeReviewConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescuePostRefreshOutcomeReviewConfig(
        stage=str(payload["stage"]),
        next_refresh_readiness_path=resolve_repo_path(inputs["m14_rescue_next_refresh_readiness"]),
        rescue_ab_evidence_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        scorecard_path=resolve_repo_path(inputs["m13_daily_strategy_scorecard"]),
        signal_ledger_path=resolve_repo_path(inputs["m13_strategy_signal_ledger"]),
        account_ledger_path=resolve_repo_path(inputs["m13_account_operation_ledger"]),
        dashboard_path=resolve_repo_path(inputs["m12_minute_dashboard_data"]),
        broker_readiness_path=resolve_repo_path(inputs["m14_2_broker_readiness_plan"]),
        outcome_json_path=resolve_repo_path(outputs["outcome_json"]),
        outcome_md_path=resolve_repo_path(outputs["outcome_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescuePostRefreshOutcomeReviewConfig) -> None:
    if config.stage != "M14.rescue_post_refresh_outcome_review":
        raise ValueError("M14 rescue post-refresh outcome review stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue post-refresh outcome review must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval", "manual_m12_37_once"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue post-refresh outcome review cannot enable {key}")


def run_m14_rescue_post_refresh_outcome_review(
    config: RescuePostRefreshOutcomeReviewConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    next_refresh = read_json(config.next_refresh_readiness_path)
    rescue_ab = read_json(config.rescue_ab_evidence_path)
    scorecard = read_json(config.scorecard_path)
    signal_rows = read_jsonl(config.signal_ledger_path)
    account_rows = read_jsonl(config.account_ledger_path)
    dashboard = read_json(config.dashboard_path)
    broker_readiness = read_json(config.broker_readiness_path)

    source_state = build_source_state(dashboard, signal_rows, account_rows)
    scorecard_by_strategy = {str(row.get("strategy_id", "")): row for row in scorecard.get("rows", [])}
    outcome_rows = [
        build_outcome_row(
            watch_row=dict(row),
            source_state=source_state,
            signal_rows=signal_rows,
            account_rows=account_rows,
            broker_rows=list(broker_readiness.get("rows", [])),
            scorecard_by_strategy=scorecard_by_strategy,
        )
        for row in next_refresh.get("rows", [])
    ]
    outcome_rows.sort(key=lambda row: (row["priority"], row["readiness_family"], row["strategy_id"], row["runtime_id"]))
    status_counts = Counter(row["outcome_status"] for row in outcome_rows)
    family_counts = Counter(row["readiness_family"] for row in outcome_rows)
    summary = {
        "fresh_refresh_observed": source_state["fresh_refresh_observed"],
        "source_quote": source_state["quote_source"],
        "source_scan_date": source_state["scan_date"],
        "latest_ledger_trading_date": source_state["latest_ledger_trading_date"],
        "watch_rows": len(outcome_rows),
        "passed_count": sum(1 for row in outcome_rows if row["outcome_status"] in PASS_STATUSES),
        "waiting_count": status_counts.get("waiting_for_m12_47_fresh_refresh", 0),
        "failed_count": sum(1 for row in outcome_rows if row["outcome_status"] in FAIL_STATUSES),
        "first_ledger_passed_count": sum(
            1
            for row in outcome_rows
            if row["readiness_family"] == "first_rescue_ledger_watch" and row["outcome_status"] == "passed"
        ),
        "fresh_quote_recheck_passed_count": sum(
            1
            for row in outcome_rows
            if row["readiness_family"] == "fresh_quote_recheck" and row["outcome_status"] == "passed"
        ),
        "broker_rule_evidence_observed_count": sum(
            1
            for row in outcome_rows
            if row["readiness_family"] == "broker_rule_shadow_recheck"
            and row["outcome_status"] == "evidence_observed"
        ),
        "target_stop_shadow_passed_count": sum(
            1
            for row in outcome_rows
            if row["readiness_family"] == "target_stop_shadow_compare" and row["outcome_status"] == "passed"
        ),
        "parent_detector_passed_count": sum(
            1
            for row in outcome_rows
            if row["readiness_family"] == "parent_detector_evidence_wait" and row["outcome_status"] == "passed"
        ),
        "outcome_status_counts": dict(sorted(status_counts.items())),
        "readiness_family_counts": dict(sorted(family_counts.items())),
        "promotion_allowed_count": 0,
        "parameter_change_allowed_now_count": 0,
        "manual_m12_37_once_allowed": False,
        "broker_or_live_enabled": False,
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-post-refresh-outcome-review.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_rescue_next_refresh_readiness": project_path(config.next_refresh_readiness_path),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_path),
            "m13_daily_strategy_scorecard": project_path(config.scorecard_path),
            "m13_strategy_signal_ledger": project_path(config.signal_ledger_path),
            "m13_account_operation_ledger": project_path(config.account_ledger_path),
            "m12_minute_dashboard_data": project_path(config.dashboard_path),
            "m14_2_broker_readiness_plan": project_path(config.broker_readiness_path),
        },
        "source_state": source_state,
        "summary": summary,
        "rows": outcome_rows,
        "rescue_ab_evidence_summary": dict(rescue_ab.get("summary", {})),
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
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "readiness_status_mutation": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.outcome_json_path, payload)
    config.outcome_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.outcome_md_path.write_text(build_outcome_md(payload), encoding="utf-8")
    return payload


def build_source_state(
    dashboard: dict[str, Any],
    signal_rows: list[dict[str, Any]],
    account_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = dashboard.get("summary", {})
    market_session = summary.get("market_session", {})
    quote_source = str(summary.get("quote_source", ""))
    scan_date = str(summary.get("scan_date", ""))
    ledger_dates = sorted(
        {
            str(row.get("trading_date", ""))
            for row in signal_rows + account_rows
            if str(row.get("trading_date", ""))
        }
    )
    latest_ledger_date = ledger_dates[-1] if ledger_dates else ""
    fresh_refresh_observed = bool(
        quote_source == "longbridge_quote_readonly"
        and summary.get("current_day_runtime_ready") is True
        and summary.get("current_day_scan_complete") is True
        and scan_date
        and latest_ledger_date
        and scan_date == latest_ledger_date
    )
    return {
        "fresh_refresh_observed": fresh_refresh_observed,
        "quote_source": quote_source,
        "scan_date": scan_date,
        "latest_ledger_trading_date": latest_ledger_date,
        "dashboard_generated_at": str(summary.get("generated_at") or dashboard.get("generated_at", "")),
        "current_day_runtime_ready": bool(summary.get("current_day_runtime_ready", False)),
        "current_day_scan_complete": bool(summary.get("current_day_scan_complete", False)),
        "market_status": str(market_session.get("status", "")),
        "new_york_date": str(market_session.get("new_york_date", "")),
        "data_freshness_warning": str(summary.get("data_freshness_warning", "")),
        "signal_ledger_row_count": len(signal_rows),
        "account_ledger_row_count": len(account_rows),
    }


def build_outcome_row(
    *,
    watch_row: dict[str, Any],
    source_state: dict[str, Any],
    signal_rows: list[dict[str, Any]],
    account_rows: list[dict[str, Any]],
    broker_rows: list[dict[str, Any]],
    scorecard_by_strategy: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    strategy_id = str(watch_row.get("strategy_id", ""))
    parent_strategy_id = str(watch_row.get("parent_strategy_id", ""))
    runtime_id = str(watch_row.get("runtime_id", ""))
    family = str(watch_row.get("readiness_family", ""))
    matching_signal_rows = matching_ledger_rows(signal_rows, strategy_id, runtime_id)
    matching_account_rows = matching_ledger_rows(account_rows, strategy_id, runtime_id)
    matching_parent_signal_rows = [
        row
        for row in signal_rows
        if str(row.get("strategy_id", "")) == parent_strategy_id
        and str(row.get("timeframe", "")) == str(watch_row.get("timeframe", ""))
    ]
    matching_broker_rows = matching_broker_readiness_rows(broker_rows, watch_row)
    metrics = {
        "current_signal_ledger_row_count": len(matching_signal_rows),
        "current_account_ledger_row_count": len(matching_account_rows),
        "current_signal_count": sum(int_or_zero(row.get("signal_count")) for row in matching_signal_rows),
        "current_source_row_count": sum(int_or_zero(row.get("source_row_count")) for row in matching_signal_rows),
        "current_account_operation_count": len(matching_account_rows),
        "current_parent_signal_count": sum(int_or_zero(row.get("signal_count")) for row in matching_parent_signal_rows),
        "current_parent_source_row_count": sum(int_or_zero(row.get("source_row_count")) for row in matching_parent_signal_rows),
        "current_broker_comparable_row_count": len(matching_broker_rows),
        "scorecard_test_states": str(scorecard_by_strategy.get(strategy_id, {}).get("test_states", "")),
        "scorecard_signal_count": int_or_zero(scorecard_by_strategy.get(strategy_id, {}).get("signal_count")),
        "scorecard_open_count": int_or_zero(scorecard_by_strategy.get(strategy_id, {}).get("open_count")),
        "scorecard_close_count": int_or_zero(scorecard_by_strategy.get(strategy_id, {}).get("close_count")),
    }
    outcome_status, next_action = outcome_for_family(
        family=family,
        source_state=source_state,
        watch_row=watch_row,
        metrics=metrics,
    )
    return {
        "row_id": str(watch_row.get("row_id", "")),
        "source_kind": str(watch_row.get("source_kind", "")),
        "strategy_id": strategy_id,
        "parent_strategy_id": parent_strategy_id,
        "runtime_id": runtime_id,
        "timeframe": str(watch_row.get("timeframe", "")),
        "priority": str(watch_row.get("priority", "")),
        "readiness_family": family,
        "readiness_state": str(watch_row.get("readiness_state", "")),
        "fresh_refresh_observed": bool(source_state.get("fresh_refresh_observed", False)),
        "outcome_status": outcome_status,
        "outcome_passed": outcome_status in PASS_STATUSES,
        "outcome_failed": outcome_status in FAIL_STATUSES,
        "next_action": next_action,
        "expected_evidence_after_refresh": str(watch_row.get("expected_evidence_after_refresh", "")),
        "pass_action": str(watch_row.get("pass_action", "")),
        "fail_action": str(watch_row.get("fail_action", "")),
        "source_metrics": dict(watch_row.get("source_metrics", {})),
        "current_metrics": metrics,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
        "parameter_change_allowed_now": False,
        "m13_registry_mutation": False,
        "m12_account_specs_mutation": False,
        "broker_readiness_status_mutation": False,
        "readiness_status_mutation": False,
    }


def outcome_for_family(
    *,
    family: str,
    source_state: dict[str, Any],
    watch_row: dict[str, Any],
    metrics: dict[str, Any],
) -> tuple[str, str]:
    if not bool(source_state.get("fresh_refresh_observed", False)):
        return (
            "waiting_for_m12_47_fresh_refresh",
            "Wait for an M12.47-owned fresh refresh; do not run M12.37 once-mode manually.",
        )
    if family == "first_rescue_ledger_watch":
        source_metrics = watch_row.get("source_metrics", {})
        old_signal_rows = int_or_zero(source_metrics.get("m13_signal_ledger_row_count"))
        old_account_rows = int_or_zero(source_metrics.get("m13_account_ledger_row_count"))
        if (
            metrics["current_signal_ledger_row_count"] > old_signal_rows
            or metrics["current_account_ledger_row_count"] > old_account_rows
        ):
            return "passed", "Start this rescue runtime's own 10-day A/B evidence count."
        return "failed_missing_first_ledger_after_fresh_refresh", "Audit M13 registry, M12 input mapping, and ledger write path."
    if family == "fresh_quote_recheck":
        if metrics["current_signal_count"] > 0 or metrics["current_source_row_count"] > 0:
            return "passed", "Continue collecting rescue A/B evidence without changing parameters."
        return "failed_zero_signal_after_fresh_refresh", "Inspect detector/filter gates before parameter changes."
    if family == "broker_rule_shadow_recheck":
        if metrics["current_broker_comparable_row_count"] > 0:
            return "evidence_observed", "Record rule-only comparison evidence; keep original broker readiness rows unchanged."
        return "failed_missing_comparable_broker_row_after_fresh_refresh", "Keep broker blockers watch-only and refine comparison contract."
    if family == "target_stop_shadow_compare":
        if metrics["current_signal_ledger_row_count"] > 0 or metrics["current_account_ledger_row_count"] > 0:
            return "passed", "Compare normalized target/stop shadow ledger against frozen rescue runtime."
        return "failed_missing_shadow_ledger_after_fresh_refresh", "Inspect target/stop shadow runtime input mapping."
    if family == "parent_detector_evidence_wait":
        if metrics["current_parent_signal_count"] > 0 or metrics["current_parent_source_row_count"] > 0:
            return "passed", "Review same-timeframe rescue mapping with parent detector evidence present."
        return "still_waiting_parent_detector_after_fresh_refresh", "Keep same-timeframe wait; do not hard-map across timeframes."
    return "unsupported_watch_family", "Add an explicit evaluator for this watch family before using it as evidence."


def matching_ledger_rows(rows: list[dict[str, Any]], strategy_id: str, runtime_id: str) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("strategy_id", "")) == strategy_id
        or (runtime_id and str(row.get("runtime_id", "")) == runtime_id)
    ]


def matching_broker_readiness_rows(rows: list[dict[str, Any]], watch_row: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = watch_row.get("source_metrics", {})
    symbol = str(metrics.get("symbol", ""))
    strategy_id = str(watch_row.get("strategy_id", ""))
    runtime_id = str(watch_row.get("runtime_id", ""))
    return [
        row
        for row in rows
        if str(row.get("strategy_id", "")) == strategy_id
        and (not runtime_id or str(row.get("runtime_id", "")) == runtime_id)
        and (not symbol or str(row.get("symbol", "")) == symbol)
    ]


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    if summary["fresh_refresh_observed"]:
        refresh_clause = "a fresh M12.47 refresh is visible"
    else:
        refresh_clause = f"still waiting for fresh M12.47 data because quote_source={summary['source_quote']}"
    return (
        f"Post-refresh outcome review checked {summary['watch_rows']} rescue watch rows; {refresh_clause}. "
        f"Passed/evidence observed: {summary['passed_count']}; waiting: {summary['waiting_count']}; failed: {summary['failed_count']}. "
        f"First-ledger passed {summary['first_ledger_passed_count']}, fresh-quote rechecks passed {summary['fresh_quote_recheck_passed_count']}, "
        f"broker-rule evidence observed {summary['broker_rule_evidence_observed_count']}, target/stop shadow passed {summary['target_stop_shadow_passed_count']}. "
        "No parameter change, registry mutation, account-spec mutation, broker readiness mutation, broker connection, real order, live execution, or paper approval is enabled."
    )


def build_outcome_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue Post-Refresh Outcome Review",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Fresh refresh observed: `{summary['fresh_refresh_observed']}`",
        f"- Quote source: `{summary['source_quote']}`",
        f"- Scan date / latest ledger date: `{summary['source_scan_date']} / {summary['latest_ledger_trading_date']}`",
        f"- Watch rows: `{summary['watch_rows']}`",
        f"- Passed or evidence observed: `{summary['passed_count']}`",
        f"- Waiting: `{summary['waiting_count']}`",
        f"- Failed: `{summary['failed_count']}`",
        f"- Manual M12.37 once-mode allowed: `{summary['manual_m12_37_once_allowed']}`",
        "- Boundary: read-only review; no registry/account-spec/broker readiness mutation, no broker connection, no real order, no live execution.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Outcome Rows",
        "",
    ]
    for row in payload["rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} / {row['runtime_id'] or row['readiness_family']}",
                "",
                f"- Family: `{row['readiness_family']}`",
                f"- Status: `{row['outcome_status']}`",
                f"- Current signal/source rows: `{row['current_metrics']['current_signal_count']} / {row['current_metrics']['current_source_row_count']}`",
                f"- Current ledger rows: `{row['current_metrics']['current_signal_ledger_row_count']} signal / {row['current_metrics']['current_account_ledger_row_count']} account`",
                f"- Comparable broker rows: `{row['current_metrics']['current_broker_comparable_row_count']}`",
                f"- Next action: {row['next_action']}",
                "",
            ]
        )
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
