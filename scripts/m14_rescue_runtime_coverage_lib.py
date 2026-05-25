#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.m12_29_current_day_scan_dashboard_lib import (
    ACCOUNT_SPECS,
    RESCUE_CONNECTED_STRATEGIES,
    rescue_input_source_type_for_spec,
    scanner_connected_for_spec,
)
from scripts.m13_daily_strategy_test_runner_lib import load_registry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_runtime_coverage.json"
ACTION_PLAN_LANES = frozenset({"rescue_candidate", "detector_rebuild"})


@dataclass(frozen=True, slots=True)
class RescueRuntimeCoverageConfig:
    stage: str
    registry_path: Path
    rescue_plan_path: Path
    coverage_json_path: Path
    coverage_md_path: Path
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


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueRuntimeCoverageConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueRuntimeCoverageConfig(
        stage=str(payload["stage"]),
        registry_path=resolve_repo_path(inputs["m13_strategy_runtime_registry"]),
        rescue_plan_path=resolve_repo_path(inputs["m14_strategy_rescue_plan"]),
        coverage_json_path=resolve_repo_path(outputs["coverage_json"]),
        coverage_md_path=resolve_repo_path(outputs["coverage_md"]),
        min_ab_trading_days=int(payload["min_ab_trading_days"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueRuntimeCoverageConfig) -> None:
    if config.stage != "M14.rescue_runtime_coverage":
        raise ValueError("M14 rescue runtime coverage stage drift")
    if config.min_ab_trading_days != 10:
        raise ValueError("M14 rescue runtime coverage must require 10 A/B trading days")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue runtime coverage must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue runtime coverage cannot enable {key}")


def run_m14_rescue_runtime_coverage(
    config: RescueRuntimeCoverageConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    registry = load_registry(config.registry_path)
    rescue_plan = read_json(config.rescue_plan_path)
    registry_by_id = {str(row.get("strategy_id", "")): row for row in registry.get("strategies", [])}
    account_specs = tuple(dict(item) for item in ACCOUNT_SPECS)
    account_specs_by_id = {str(item["account_id"]): item for item in account_specs}

    rows = build_registered_rescue_rows(registry_by_id, account_specs_by_id)
    plan_rows = build_plan_action_coverage(rescue_plan, registry_by_id, rows)
    pending_registered_ids = [row["strategy_id"] for row in rows if row["coverage_status"] != "connected_not_promoted"]
    pending_plan_ids = [row["strategy_id"] for row in plan_rows if row["coverage_status"] == "pending_runtime"]
    connected_count = len(rows) - len(pending_registered_ids)
    plan_covered_count = len(plan_rows) - len(pending_plan_ids)
    all_registered_connected = not pending_registered_ids
    all_plan_actions_covered = not pending_plan_ids

    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-runtime-coverage.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "registry_ref": project_path(config.registry_path),
        "rescue_plan_ref": project_path(config.rescue_plan_path),
        "m12_account_specs_source": "scripts/m12_29_current_day_scan_dashboard_lib.py#ACCOUNT_SPECS",
        "min_ab_trading_days": config.min_ab_trading_days,
        "registered_rescue_strategy_count": len(rows),
        "registered_rescue_account_count": sum(len(row["runtime_ids"]) for row in rows),
        "connected_rescue_strategy_count": connected_count,
        "pending_rescue_strategy_ids": pending_registered_ids,
        "planned_action_row_count": len(plan_rows),
        "planned_action_covered_count": plan_covered_count,
        "pending_planned_action_strategy_ids": pending_plan_ids,
        "all_registered_rescue_inputs_connected": all_registered_connected,
        "all_planned_rescue_actions_have_runtime_coverage": all_plan_actions_covered,
        "coverage_complete_but_not_promoted": all_registered_connected and all_plan_actions_covered,
        "connected_not_passed_policy": (
            "Runtime connection proves input coverage only; promotion, modification, or rejection still requires "
            "10 trading-day A/B ledger evidence."
        ),
        "next_required_evidence": "10 trading-day A/B ledger evidence before promote, modify, or reject.",
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
        "rows": rows,
        "planned_action_rows": plan_rows,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.coverage_json_path, payload)
    config.coverage_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.coverage_md_path.write_text(build_coverage_md(payload), encoding="utf-8")
    return payload


def build_registered_rescue_rows(
    registry_by_id: dict[str, dict[str, Any]],
    account_specs_by_id: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy_id in sorted(registry_by_id):
        registry_row = registry_by_id[strategy_id]
        rescue_accounts = [
            dict(account)
            for account in registry_row.get("runtime_accounts", [])
            if str(account.get("lane", "")) == "rescue"
        ]
        if not rescue_accounts:
            continue

        missing_runtime_ids: list[str] = []
        mismatched_runtime_ids: list[str] = []
        disconnected_runtime_ids: list[str] = []
        input_source_types: list[str] = []
        for account in rescue_accounts:
            runtime_id = str(account.get("runtime_id", ""))
            spec = account_specs_by_id.get(runtime_id)
            if spec is None:
                missing_runtime_ids.append(runtime_id)
                continue
            if spec.get("strategy_id") != strategy_id or spec.get("lane") != "rescue":
                mismatched_runtime_ids.append(runtime_id)
            if not scanner_connected_for_spec(spec):
                disconnected_runtime_ids.append(runtime_id)
            source_type = rescue_input_source_type_for_spec(spec)
            if source_type not in input_source_types:
                input_source_types.append(source_type)

        detector_connected = registry_row.get("detector_status") == "connected"
        required_for_goal = bool(registry_row.get("required_for_goal", False))
        known_connected_strategy = strategy_id in RESCUE_CONNECTED_STRATEGIES
        has_parent = bool(registry_row.get("parent_strategy_id"))
        connected = (
            detector_connected
            and known_connected_strategy
            and has_parent
            and not required_for_goal
            and not missing_runtime_ids
            and not mismatched_runtime_ids
            and not disconnected_runtime_ids
        )
        rows.append(
            {
                "strategy_id": strategy_id,
                "parent_strategy_id": str(registry_row.get("parent_strategy_id", "")),
                "detector_id": str(registry_row.get("detector_id", "")),
                "detector_status": str(registry_row.get("detector_status", "")),
                "required_for_goal": required_for_goal,
                "runtime_ids": [str(account.get("runtime_id", "")) for account in rescue_accounts],
                "timeframes": sorted({str(account.get("timeframe", "")) for account in rescue_accounts}),
                "variant_ids": sorted({str(account.get("variant_id", "")) for account in rescue_accounts}),
                "account_spec_runtime_ids": [
                    str(account.get("runtime_id", ""))
                    for account in rescue_accounts
                    if str(account.get("runtime_id", "")) in account_specs_by_id
                ],
                "missing_account_spec_runtime_ids": missing_runtime_ids,
                "mismatched_account_spec_runtime_ids": mismatched_runtime_ids,
                "disconnected_account_spec_runtime_ids": disconnected_runtime_ids,
                "input_source_types": input_source_types,
                "coverage_status": "connected_not_promoted" if connected else "pending_or_misconfigured",
                "promotion_status": "not_promoted_requires_10_day_ab_evidence",
                "needs_ab_trading_days": 10,
                "paper_simulated_only": True,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return rows


def build_plan_action_coverage(
    rescue_plan: dict[str, Any],
    registry_by_id: dict[str, dict[str, Any]],
    rescue_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rescue_by_parent: dict[str, list[str]] = {}
    for row in rescue_rows:
        rescue_by_parent.setdefault(row["parent_strategy_id"], []).append(row["strategy_id"])

    rows: list[dict[str, Any]] = []
    for plan_row in rescue_plan.get("rows", []):
        lane = str(plan_row.get("lane", ""))
        if lane not in ACTION_PLAN_LANES:
            continue
        strategy_id = str(plan_row.get("strategy_id", ""))
        next_variant_id = str(plan_row.get("next_variant_id", ""))
        direct_variant_row = registry_by_id.get(next_variant_id)
        direct_runtime_ids = [
            str(account.get("runtime_id", ""))
            for account in (direct_variant_row or {}).get("runtime_accounts", [])
        ]
        rescue_strategy_ids = sorted(rescue_by_parent.get(strategy_id, []))
        coverage_strategy_ids = list(dict.fromkeys(rescue_strategy_ids + ([next_variant_id] if direct_runtime_ids else [])))
        if rescue_strategy_ids:
            coverage_status = "covered_by_rescue_runtime"
        elif direct_runtime_ids:
            coverage_status = "covered_by_existing_runtime"
        else:
            coverage_status = "pending_runtime"
        rows.append(
            {
                "strategy_id": strategy_id,
                "plan_lane": lane,
                "decision": str(plan_row.get("decision", "")),
                "decision_reason": str(plan_row.get("decision_reason", "")),
                "next_variant_id": next_variant_id,
                "coverage_status": coverage_status,
                "coverage_strategy_ids": coverage_strategy_ids,
                "direct_variant_runtime_ids": direct_runtime_ids,
                "rescue_runtime_strategy_ids": rescue_strategy_ids,
                "needs_ab_trading_days": 10,
                "connected_does_not_mean_passed": True,
                "paper_simulated_only": True,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return rows


def build_plain_language_result(payload: dict[str, Any]) -> str:
    return (
        f"Registered rescue runtime coverage is {payload['connected_rescue_strategy_count']}/"
        f"{payload['registered_rescue_strategy_count']} strategies and "
        f"{payload['registered_rescue_account_count']} accounts. "
        f"Planned rescue/rebuild action coverage is {payload['planned_action_covered_count']}/"
        f"{payload['planned_action_row_count']}. "
        "Connected does not mean passed or approved; every rescue runtime still needs 10 trading-day A/B ledger evidence. "
        "No broker connection, real order, live execution, or paper-trading approval was enabled."
    )


def build_coverage_md(payload: dict[str, Any]) -> str:
    lines = [
        "# M14 Rescue Runtime Coverage",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Registered rescue strategies connected: `{payload['connected_rescue_strategy_count']}/{payload['registered_rescue_strategy_count']}`",
        f"- Registered rescue accounts: `{payload['registered_rescue_account_count']}`",
        f"- Planned rescue/rebuild actions covered: `{payload['planned_action_covered_count']}/{payload['planned_action_row_count']}`",
        "- Boundary: internal simulated only; no broker connection, no real orders, no live execution.",
        "- Policy: Connected does not mean passed or approved; 10 trading-day A/B ledger evidence is still required.",
        "",
        "## Registered Rescue Runtimes",
    ]
    for row in payload["rows"]:
        lines.extend(
            [
                "",
                f"### {row['strategy_id']}",
                "",
                f"- Parent: `{row['parent_strategy_id']}`",
                f"- Detector: `{row['detector_id']}` / `{row['detector_status']}`",
                f"- Runtime ids: `{', '.join(row['runtime_ids'])}`",
                f"- Input source types: `{', '.join(row['input_source_types'])}`",
                f"- Coverage: `{row['coverage_status']}`",
                f"- Promotion status: `{row['promotion_status']}`",
            ]
        )
    lines.extend(["", "## Planned Action Coverage"])
    for row in payload["planned_action_rows"]:
        coverage_ids = ", ".join(row["coverage_strategy_ids"]) or "none"
        lines.extend(
            [
                "",
                f"### {row['strategy_id']}",
                "",
                f"- Plan lane: `{row['plan_lane']}`",
                f"- Next variant: `{row['next_variant_id'] or 'n/a'}`",
                f"- Coverage: `{row['coverage_status']}`",
                f"- Covered by: `{coverage_ids}`",
            ]
        )
    lines.extend(["", "## Summary", "", payload["plain_language_result"], ""])
    return "\n".join(lines)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
