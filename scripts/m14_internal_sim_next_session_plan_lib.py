#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_internal_sim_next_session_plan.json"


@dataclass(frozen=True, slots=True)
class InternalSimNextSessionPlanConfig:
    stage: str
    project_stage_label: str
    internal_sim_launch_readiness_path: Path
    goal_readiness_report_path: Path
    rescue_next_refresh_readiness_path: Path
    rescue_ab_evidence_path: Path
    plan_json_path: Path
    plan_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> InternalSimNextSessionPlanConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = InternalSimNextSessionPlanConfig(
        stage=str(payload["stage"]),
        project_stage_label=str(payload["project_stage_label"]),
        internal_sim_launch_readiness_path=resolve_repo_path(inputs["m14_internal_sim_launch_readiness"]),
        goal_readiness_report_path=resolve_repo_path(inputs["m14_goal_readiness_report"]),
        rescue_next_refresh_readiness_path=resolve_repo_path(inputs["m14_rescue_next_refresh_readiness"]),
        rescue_ab_evidence_path=resolve_repo_path(inputs["m14_rescue_ab_evidence_tracker"]),
        plan_json_path=resolve_repo_path(outputs["plan_json"]),
        plan_md_path=resolve_repo_path(outputs["plan_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: InternalSimNextSessionPlanConfig) -> None:
    if config.stage != "M14.internal_sim_next_session_plan":
        raise ValueError("M14 internal simulated next-session plan stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 internal simulated next-session plan must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M14 internal simulated next-session plan must keep internal simulated account enabled")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval", "manual_m12_37_once"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 internal simulated next-session plan cannot enable {key}")


def run_m14_internal_sim_next_session_plan(
    config: InternalSimNextSessionPlanConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    launch = read_json(config.internal_sim_launch_readiness_path)
    goal = read_json(config.goal_readiness_report_path)
    next_refresh = read_json(config.rescue_next_refresh_readiness_path)
    rescue_ab = read_json(config.rescue_ab_evidence_path)

    launch_summary = dict(launch.get("summary", {}))
    strategy_rows = build_strategy_session_rows(
        launch_rows=list(launch.get("strategy_rows", [])),
        next_refresh_rows=list(next_refresh.get("rows", [])),
    )
    global_watch_rows = build_global_watch_rows(next_refresh, rescue_ab)
    summary = build_summary(launch_summary, strategy_rows, global_watch_rows, next_refresh, rescue_ab)
    payload: dict[str, Any] = {
        "schema_version": "m14.internal-sim-next-session-plan.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "project_stage_label": config.project_stage_label,
        "m14_trading_date": str(launch.get("m14_trading_date") or goal.get("m14_trading_date", "")),
        "input_refs": {
            "m14_internal_sim_launch_readiness": project_path(config.internal_sim_launch_readiness_path),
            "m14_goal_readiness_report": project_path(config.goal_readiness_report_path),
            "m14_rescue_next_refresh_readiness": project_path(config.rescue_next_refresh_readiness_path),
            "m14_rescue_ab_evidence_tracker": project_path(config.rescue_ab_evidence_path),
        },
        "summary": summary,
        "strategy_session_rows": strategy_rows,
        "global_watch_rows": global_watch_rows,
        "execution_protocol": build_execution_protocol(),
        "hard_boundaries": {
            "paper_simulated_only": True,
            "internal_simulated_account": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
            "manual_m12_37_once": False,
        },
        "paper_simulated_only": True,
        "internal_simulated_account": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.plan_json_path, payload)
    config.plan_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.plan_md_path.write_text(build_plan_md(payload), encoding="utf-8")
    return payload


def build_strategy_session_rows(
    *,
    launch_rows: list[dict[str, Any]],
    next_refresh_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in launch_rows:
        strategy_id = str(row.get("strategy_id", ""))
        linked_watch_rows = [
            watch
            for watch in next_refresh_rows
            if strategy_id in {str(watch.get("strategy_id", "")), str(watch.get("parent_strategy_id", ""))}
        ]
        watch_family_counts = Counter(str(watch.get("readiness_family", "")) for watch in linked_watch_rows)
        broker_blocked_count = int_or_zero(row.get("broker_dry_run_blocked_count"))
        status = str(row.get("internal_sim_launch_status", ""))
        session_action = "continue_internal_simulated_account_testing"
        if broker_blocked_count:
            session_action = "continue_internal_sim_and_watch_broker_dry_run_blockers"
        if not row.get("can_continue_internal_simulated_account", False):
            session_action = "hold_until_launch_readiness_repaired"
        rows.append(
            {
                "strategy_id": strategy_id,
                "display_name": str(row.get("display_name", "")),
                "runtime_ids": list(row.get("gate_runtime_ids", [])),
                "internal_sim_launch_status": status,
                "session_action": session_action,
                "m12_account_input_connected_runtime_count": int_or_zero(
                    row.get("m12_account_input_connected_runtime_count")
                ),
                "m12_account_input_runtime_count": int_or_zero(row.get("m12_account_input_runtime_count")),
                "m12_account_input_status_counts": dict(row.get("m12_account_input_status_counts", {})),
                "m13_signal_count": int_or_zero(row.get("m13_signal_count")),
                "m13_open_count": int_or_zero(row.get("m13_open_count")),
                "m13_close_count": int_or_zero(row.get("m13_close_count")),
                "m13_test_states": str(row.get("m13_test_states", "")),
                "broker_dry_run_ready_count": int_or_zero(row.get("broker_dry_run_ready_count")),
                "broker_dry_run_blocked_count": broker_blocked_count,
                "broker_blocker_reason_counts": dict(row.get("broker_blocker_reason_counts", {})),
                "linked_next_refresh_watch_count": len(linked_watch_rows),
                "linked_next_refresh_family_counts": dict(sorted(watch_family_counts.items())),
                "acceptance_checks": acceptance_checks(row, linked_watch_rows),
                "can_continue_internal_simulated_account": bool(row.get("can_continue_internal_simulated_account", False)),
                "can_start_broker_paper": False,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return rows


def acceptance_checks(launch_row: dict[str, Any], linked_watch_rows: list[dict[str, Any]]) -> list[str]:
    checks = [
        "m12_47_supervised_fresh_refresh_only",
        "m13_signal_and_account_ledgers_refresh_after_session",
        "m14_gate_stays_approved_internal_sim_only",
        "no_broker_connection_no_real_order_no_live_execution",
    ]
    if int_or_zero(launch_row.get("broker_dry_run_blocked_count")):
        checks.append("broker_dry_run_blockers_remain_watch_only")
    if any(str(row.get("readiness_family", "")) == "broker_rule_shadow_recheck" for row in linked_watch_rows):
        checks.append("pa005_rule_shadow_recheck_after_fresh_refresh")
    if any(str(row.get("readiness_family", "")) == "first_rescue_ledger_watch" for row in linked_watch_rows):
        checks.append("first_rescue_ledger_watch_after_fresh_refresh")
    return checks


def build_global_watch_rows(next_refresh: dict[str, Any], rescue_ab: dict[str, Any]) -> list[dict[str, Any]]:
    next_refresh_summary = next_refresh.get("summary", {})
    rescue_summary = rescue_ab.get("summary", {})
    rows = [
        {
            "watch_id": "approved_internal_sim_launch_recheck",
            "priority": "P0",
            "watch_type": "launch_readiness_recheck",
            "expected_after_refresh": "Approved strategies remain launch-ready and all approved runtime inputs stay connected.",
            "pass_action": "Continue internal simulated-account testing.",
            "fail_action": "Hold affected internal sim row and repair gate/runtime/input mapping before continuing.",
        },
        {
            "watch_id": "rescue_next_refresh_matrix",
            "priority": "P0",
            "watch_type": "rescue_next_refresh_matrix",
            "expected_after_refresh": (
                f"{int_or_zero(next_refresh_summary.get('watch_rows'))} rescue watch rows can be evaluated after the next fresh run."
            ),
            "pass_action": "Update rescue evidence status without promoting or rejecting from a single refresh.",
            "fail_action": "Keep waiting or repair the specific input path; no direct parameter mutation.",
        },
        {
            "watch_id": "first_rescue_ledger_watch",
            "priority": "P0",
            "watch_type": "first_rescue_ledger_watch",
            "expected_after_refresh": (
                f"{int_or_zero(rescue_summary.get('no_m13_ledger_evidence_count'))} rescue runtimes currently need first M13 ledger evidence."
            ),
            "pass_action": "Start counting each runtime's own 10-day A/B evidence window.",
            "fail_action": "Audit M13 registry and M12 account input mapping for the no-ledger runtimes.",
        },
        {
            "watch_id": "broker_live_boundary_check",
            "priority": "P0",
            "watch_type": "boundary_check",
            "expected_after_refresh": "broker_connection=false, real_order=false, live_execution=false, paper_trading_approval=false.",
            "pass_action": "Keep broker readiness in dry-run preview only.",
            "fail_action": "Stop and inspect boundary regression before any further readiness work.",
        },
    ]
    return rows


def build_summary(
    launch_summary: dict[str, Any],
    strategy_rows: list[dict[str, Any]],
    global_watch_rows: list[dict[str, Any]],
    next_refresh: dict[str, Any],
    rescue_ab: dict[str, Any],
) -> dict[str, Any]:
    next_refresh_summary = next_refresh.get("summary", {})
    rescue_summary = rescue_ab.get("summary", {})
    launch_ready = int_or_zero(launch_summary.get("launch_ready_strategy_count"))
    approved = int_or_zero(launch_summary.get("approved_internal_sim_strategy_count"))
    broker_watch = int_or_zero(launch_summary.get("broker_watch_strategy_count"))
    return {
        "next_session_mode": "m12_47_supervised_fresh_refresh_only",
        "can_run_next_internal_sim_session": bool(
            approved > 0
            and launch_ready == approved
            and int_or_zero(launch_summary.get("hard_boundary_violation_count")) == 0
        ),
        "approved_internal_sim_strategy_count": approved,
        "launch_ready_strategy_count": launch_ready,
        "approved_runtime_input_connected_count": int_or_zero(
            launch_summary.get("m12_account_input_connected_runtime_count")
        ),
        "approved_runtime_input_count": int_or_zero(launch_summary.get("m12_account_input_runtime_count")),
        "broker_watch_strategy_count": broker_watch,
        "broker_watch_strategy_ids": list(launch_summary.get("broker_watch_strategy_ids", [])),
        "strategy_session_row_count": len(strategy_rows),
        "global_watch_row_count": len(global_watch_rows),
        "rescue_next_refresh_watch_rows": int_or_zero(next_refresh_summary.get("watch_rows")),
        "first_ledger_watch_count": int_or_zero(next_refresh_summary.get("first_ledger_watch_count")),
        "broker_rule_shadow_watch_count": int_or_zero(next_refresh_summary.get("broker_rule_shadow_watch_count")),
        "target_stop_shadow_compare_count": int_or_zero(next_refresh_summary.get("target_stop_shadow_compare_count")),
        "parameter_change_allowed_now_count": int_or_zero(next_refresh_summary.get("parameter_change_allowed_now_count")),
        "no_m13_ledger_evidence_count": int_or_zero(rescue_summary.get("no_m13_ledger_evidence_count")),
        "promotion_allowed_count": int_or_zero(rescue_summary.get("promotion_allowed_count")),
        "manual_m12_37_once_allowed": False,
        "can_start_broker_paper": False,
        "broker_or_live_enabled": False,
        "hard_boundary_violation_count": int_or_zero(launch_summary.get("hard_boundary_violation_count")),
    }


def build_execution_protocol() -> list[dict[str, str]]:
    return [
        {
            "step": "wait_for_m12_47_supervisor_window",
            "owner": "M12.47 supervisor",
            "rule": "Do not manually run scripts/run_m12_37_intraday_auto_loop.py --once.",
        },
        {
            "step": "refresh_m12_dashboard_and_m13_ledgers",
            "owner": "M12.47 post_run_strategy_ledgers",
            "rule": "Use fresh readonly market data only when the supervisor owns the trading-window refresh.",
        },
        {
            "step": "rebuild_m14_readiness_artifacts",
            "owner": "M14 scripts",
            "rule": "Recompute launch readiness, next-refresh readiness, and goal readiness from current artifacts.",
        },
        {
            "step": "review_internal_sim_and_rescue_evidence",
            "owner": "Codex/read-only review",
            "rule": "Continue internal simulation and rescue evidence collection; do not enable broker/live.",
        },
    ]


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Next internal simulated-account session is ready in {summary['next_session_mode']} mode: "
        f"{summary['launch_ready_strategy_count']}/{summary['approved_internal_sim_strategy_count']} approved strategies "
        f"and {summary['approved_runtime_input_connected_count']}/{summary['approved_runtime_input_count']} approved runtimes are connected. "
        f"{summary['broker_watch_strategy_count']} approved strategies need broker dry-run blocker watch; "
        f"{summary['rescue_next_refresh_watch_rows']} rescue watch rows and {summary['first_ledger_watch_count']} first-ledger watches remain for the next fresh refresh. "
        "Manual M12.37 once-mode, broker paper, live execution, real orders, and paper-trading approval remain disabled."
    )


def build_plan_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Internal Sim Next Session Plan",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Mode: `{summary['next_session_mode']}`",
        f"- Can run next internal sim session: `{summary['can_run_next_internal_sim_session']}`",
        f"- Approved launch-ready strategies: `{summary['launch_ready_strategy_count']}/{summary['approved_internal_sim_strategy_count']}`",
        f"- Approved runtime input coverage: `{summary['approved_runtime_input_connected_count']}/{summary['approved_runtime_input_count']}`",
        f"- Broker watch strategies: `{summary['broker_watch_strategy_count']}`",
        f"- Rescue watch rows: `{summary['rescue_next_refresh_watch_rows']}`",
        f"- Manual M12.37 once-mode allowed: `{summary['manual_m12_37_once_allowed']}`",
        f"- Broker paper start allowed: `{summary['can_start_broker_paper']}`",
        "- Boundary: internal simulated accounts only; no broker connection, no real orders, no live execution.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Strategy Session Rows",
        "",
    ]
    for row in payload["strategy_session_rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Action: `{row['session_action']}`",
                f"- Runtimes: `{', '.join(row['runtime_ids']) or 'none'}`",
                f"- Runtime input coverage: `{row['m12_account_input_connected_runtime_count']}/{row['m12_account_input_runtime_count']}`",
                f"- M13 signal/open/close: `{row['m13_signal_count']}/{row['m13_open_count']}/{row['m13_close_count']}`",
                f"- Broker dry-run ready/blocked: `{row['broker_dry_run_ready_count']}/{row['broker_dry_run_blocked_count']}`",
                f"- Linked next-refresh watches: `{row['linked_next_refresh_watch_count']}`",
                f"- Acceptance checks: `{', '.join(row['acceptance_checks'])}`",
                "",
            ]
        )
    lines.extend(["## Global Watch Rows", ""])
    for row in payload["global_watch_rows"]:
        lines.append(f"- `{row['priority']}` `{row['watch_id']}`: {row['expected_after_refresh']}")
    lines.extend(["", "## Execution Protocol", ""])
    for item in payload["execution_protocol"]:
        lines.append(f"- `{item['step']}` owner `{item['owner']}`: {item['rule']}")
    lines.append("")
    return "\n".join(lines)


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
