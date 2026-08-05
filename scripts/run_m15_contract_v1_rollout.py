#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_sdk_runtime_lib import load_config
from scripts.m15_sdk_validation_flatten_lib import in_regular_session
from scripts.m15_strategy_contracts_lib import load_contracts, write_state_atomic


DEFAULT_CONFIG = ROOT / "config/examples/m15_longbridge_sdk_runtime.contract_v1.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def account_state_path(config: Any) -> Path:
    payload = read_json(config.account_state_config_path)
    value = str((payload.get("outputs") or {}).get("account_state") or "")
    if not value:
        raise ValueError("contract rollout account state path is missing")
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def snapshot_age_seconds(snapshot: dict[str, Any], now: datetime) -> int | None:
    try:
        generated_at = datetime.fromisoformat(
            str(snapshot.get("generated_at") or "").replace("Z", "+00:00")
        ).astimezone(UTC)
    except (TypeError, ValueError):
        return None
    return max(0, int((now.astimezone(UTC) - generated_at).total_seconds()))


def rollout_check(config_path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    config = load_config(config_path)
    execution = read_json(config.execution_config_path)
    contract_directory = Path(
        str((execution.get("strategy_contracts") or {}).get("directory") or "")
    )
    if not contract_directory.is_absolute():
        contract_directory = ROOT / contract_directory
    contracts = load_contracts(contract_directory)
    allowed = list((execution.get("longbridge_realtime") or {}).get("allowed_runtime_ids") or [])
    invalid_contracts = [
        runtime_id
        for runtime_id in allowed
        if runtime_id not in contracts
        or str(contracts[runtime_id].get("stage") or "") not in {"paper-v1", "full-v1"}
    ]
    buckets = execution.get("virtual_capital_buckets") or {}
    non_independent_buckets = [
        bucket_id
        for bucket_id, bucket in buckets.items()
        if len(list((bucket or {}).get("runtime_ids") or [])) != 1
    ]
    snapshot_path = account_state_path(config)
    snapshot = read_json(snapshot_path)
    age = snapshot_age_seconds(snapshot, current)
    account_safe = bool(
        snapshot.get("paper_account_verified") is True
        and str(snapshot.get("account_channel") or "") == "lb_papertrading"
        and snapshot.get("positions_ok") is True
        and snapshot.get("orders_ok") is True
        and age is not None
        and age <= config.maximum_account_snapshot_age_seconds
    )
    blockers = []
    if not config.paper_trading_only or config.live_execution or config.real_money_actions:
        blockers.append("not_paper_only")
    if not config.paper_order_dispatch_enabled:
        blockers.append("paper_dispatch_not_enabled")
    if invalid_contracts:
        blockers.append("invalid_or_non_executable_contract")
    if non_independent_buckets:
        blockers.append("non_independent_strategy_bucket")
    if not account_safe:
        blockers.append("paper_account_snapshot_not_verified_or_stale")
    return {
        "schema_version": "m15.contract-v1-rollout-check.v1",
        "generated_at": current.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "config": str(config.config_path),
        "test_epoch_id": config.formal_test_epoch_id,
        "short_test_epoch_id": config.formal_short_test_epoch_id,
        "allowed_runtime_count": len(allowed),
        "contract_count": len(contracts),
        "invalid_contract_runtime_ids": invalid_contracts,
        "non_independent_bucket_ids": non_independent_buckets,
        "account_state_path": str(snapshot_path),
        "account_snapshot_age_seconds": age,
        "paper_account_verified": snapshot.get("paper_account_verified") is True,
        "account_channel": snapshot.get("account_channel"),
        "position_count": len(snapshot.get("positions") or []),
        "open_order_count": len(snapshot.get("open_orders") or []),
        "pending_confirmation_count": sum(
            1
            for key in ("open_orders", "orders", "historical_orders")
            for row in (snapshot.get(key) or [])
            if isinstance(row, dict) and row.get("sdk_pending_confirmation")
        ),
        "ready_to_prepare": not blockers,
        "blockers": blockers,
    }


def prepare_rollout(config_path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    check = rollout_check(config_path, now=current)
    if not check["ready_to_prepare"]:
        return {**check, "status": "blocked"}
    config = load_config(config_path)
    raw_config = read_json(config.config_path)
    activate_not_before = str(
        (raw_config.get("formal_test_transition") or {}).get("activate_not_before") or ""
    )
    marker_path = config.formal_test_marker_path
    if marker_path.exists():
        archive_dir = marker_path.parent / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        suffix = current.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(marker_path, archive_dir / f"{marker_path.stem}.{suffix}.json")
    created_at = current.astimezone(UTC).isoformat().replace("+00:00", "Z")
    marker = {
        "schema_version": "m15.sdk-formal-test-epoch.v1",
        "status": "pending_flatten",
        "test_epoch_id": config.formal_test_epoch_id,
        "short_test_epoch_id": config.formal_short_test_epoch_id,
        "created_at": created_at,
        "test_started_at": "",
        "activation_blocker": "waiting_for_broker_positions_orders_and_pending_confirmations_to_reach_zero",
        "activate_not_before": activate_not_before,
        "blocks_new_entries": True,
        "prepared_by": "run_m15_contract_v1_rollout.py",
    }
    state = {
        "schema_version": "m15.sdk-runtime-auto-flatten.v1",
        "stage": "M15.sdk_runtime_auto_flatten",
        "status": "pending_flatten",
        "test_epoch_id": config.formal_test_epoch_id,
        "short_test_epoch_id": config.formal_short_test_epoch_id,
        "created_at": created_at,
        "updated_at": created_at,
        "blocks_new_entries": True,
        "confirmation": {
            "position_count": check["position_count"],
            "open_order_count": check["open_order_count"],
            "pending_confirmation_count": check["pending_confirmation_count"],
            "complete": False,
        },
        "cancel_attempts": {},
        "submissions": {},
    }
    write_state_atomic(marker_path, marker)
    write_state_atomic(config.formal_test_epoch_state_path, state)
    return {**check, "status": "prepared_pending_flatten", "marker": marker, "state": state}


def activate_validation_session(
    config_path: Path,
    *,
    validation_end_at: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    check = rollout_check(config_path, now=current)
    try:
        end_at = datetime.fromisoformat(validation_end_at.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return {**check, "status": "blocked", "blockers": [*check["blockers"], "invalid_validation_end_at"]}
    blockers = list(check["blockers"])
    if not in_regular_session(current):
        blockers.append("validation_requires_us_regular_session")
    if end_at <= current.astimezone(UTC):
        blockers.append("validation_end_must_be_in_future")
    if end_at.astimezone(UTC).date() != current.astimezone(UTC).date():
        blockers.append("validation_must_end_on_same_utc_date")
    if check["position_count"] or check["open_order_count"] or check["pending_confirmation_count"]:
        blockers.append("validation_requires_flat_paper_account")
    config = load_config(config_path)
    previous = read_json(config.formal_test_marker_path)
    if previous and (
        str(previous.get("test_epoch_id") or "") != config.formal_test_epoch_id
        or str(previous.get("short_test_epoch_id") or "") != config.formal_short_test_epoch_id
    ):
        blockers.append("formal_epoch_identity_mismatch")
    if blockers:
        return {**check, "status": "blocked", "blockers": sorted(set(blockers))}

    started_at = current.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raw_config = read_json(config.config_path)
    formal_activate_not_before = str(
        (raw_config.get("formal_test_transition") or {}).get("activate_not_before") or ""
    )
    marker = {
        "schema_version": "m15.sdk-formal-test-epoch.v1",
        "status": "active",
        "test_epoch_id": config.formal_test_epoch_id,
        "short_test_epoch_id": config.formal_short_test_epoch_id,
        "created_at": str(previous.get("created_at") or started_at),
        "test_started_at": started_at,
        "activated_at": started_at,
        "activation_blocker": "",
        "blocks_new_entries": False,
        "paper_simulated_only": True,
        "validation_session": True,
        "validation_started_at": started_at,
        "validation_end_at": end_at.isoformat().replace("+00:00", "Z"),
        "formal_activate_not_before": formal_activate_not_before,
        "prepared_by": "run_m15_contract_v1_rollout.py --activate-validation",
    }
    state = {
        "schema_version": "m15.sdk-runtime-auto-flatten.v1",
        "stage": "M15.sdk_runtime_auto_flatten",
        "status": "active",
        "test_epoch_id": config.formal_test_epoch_id,
        "short_test_epoch_id": config.formal_short_test_epoch_id,
        "test_started_at": started_at,
        "activated_at": started_at,
        "blocks_new_entries": False,
        "validation_session": True,
        "validation_end_at": marker["validation_end_at"],
        "cancel_attempts": {},
        "submissions": {},
    }
    write_state_atomic(config.formal_test_marker_path, marker)
    write_state_atomic(config.formal_test_epoch_state_path, state)
    return {**check, "status": "validation_active", "marker": marker, "state": state, "blockers": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and prepare the M15 contract-v1 paper rollout.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--activate-validation", action="store_true")
    parser.add_argument("--validation-end-at", default="", help="UTC timestamp when validation must stop opening positions and flatten.")
    args = parser.parse_args()
    if sum(bool(value) for value in (args.check, args.prepare, args.activate_validation)) != 1:
        parser.error("choose exactly one of --check, --prepare or --activate-validation")
    if args.activate_validation and not args.validation_end_at:
        parser.error("--activate-validation requires --validation-end-at")
    config_path = Path(args.config)
    if args.prepare:
        payload = prepare_rollout(config_path)
    elif args.activate_validation:
        payload = activate_validation_session(
            config_path,
            validation_end_at=args.validation_end_at,
        )
    else:
        payload = rollout_check(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ready_to_prepare") and payload.get("status") != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
