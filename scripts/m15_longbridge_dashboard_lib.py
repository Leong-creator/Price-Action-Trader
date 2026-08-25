from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_fill_attribution_lib import (
    build_virtual_position_layers,
    group_completed_trade_performance_rows,
    summarize_completed_trade_rows,
)
from scripts.m15_strategy_contracts_lib import load_contracts_cached


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config/examples/m15_longbridge_dashboard.json"
DEFAULT_FILL_ATTRIBUTION_PATH = (
    ROOT
    / "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/"
    "m15_longbridge_realtime_execution/m15_longbridge_fill_attribution_v2.json"
)
DEFAULT_PA004_MIGRATION_STATUS_NAME = "m15_capital_bucket_migration_state.json"
DEFAULT_PA002_MILESTONE_STATUS = (
    DEFAULT_FILL_ATTRIBUTION_PATH.parent
    / "m15_pa002_dual_version_milestone_status.json"
)
PA004_MIGRATION_BUCKETS = {"pa004_mbf", "pa004_mbf_qc"}
NEW_YORK = ZoneInfo("America/New_York")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _quantity(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0001")), "f")


def _resolve(path: str | Path) -> Path:
    value = Path(path).expanduser()
    return value if value.is_absolute() else ROOT / value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json_artifact(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, {"path": str(path), "status": "missing"}
    except (json.JSONDecodeError, OSError) as exc:
        return {}, {"path": str(path), "status": "corrupt", "detail": str(exc)}
    if not isinstance(payload, dict):
        return {}, {"path": str(path), "status": "corrupt", "detail": "top_level_not_object"}
    return payload, {"path": str(path), "status": "ok"}


def _read_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return _read_json(path)


def _read_recent_jsonl(path: Path, maximum_rows: int = 5000) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-maximum_rows:]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _merge_short_execution_funnel(
    short_diagnostics: dict[str, Any],
    execution_rows: list[dict[str, Any]],
    reconciliation_rows: list[dict[str, Any]],
    expected_runtime_ids: list[str] | None = None,
) -> dict[str, Any]:
    output = dict(short_diagnostics)
    runtime_rows = {
        str(row.get("runtime_id") or ""): dict(row)
        for row in output.get("runtime_summaries", [])
        if isinstance(row, dict) and str(row.get("runtime_id") or "")
    }
    short_epoch = str(output.get("test_epoch_id") or "")
    order_status_by_id = {
        str(row.get("order_id") or ""): str(row.get("longbridge_status") or row.get("status") or "").lower()
        for row in reconciliation_rows
        if isinstance(row, dict) and str(row.get("order_id") or "")
    }
    relevant_rows = [
        row
        for row in execution_rows
        if str(row.get("position_action") or "") == "open_short"
        and (not short_epoch or str(row.get("test_epoch_id") or "") == short_epoch)
    ]
    for runtime_id in sorted(
        set(runtime_rows)
        | set(expected_runtime_ids or [])
        | {
            str(row.get("runtime_id") or "")
            for row in relevant_rows
            if str(row.get("runtime_id") or "")
        }
    ):
        current = runtime_rows.get(runtime_id, {"runtime_id": runtime_id})
        rows = [row for row in relevant_rows if str(row.get("runtime_id") or "") == runtime_id]
        capacity_checked = [
            row
            for row in rows
            if str(row.get("short_capacity_check_status") or "") not in {"", "not_applicable"}
        ]
        capacity_blockers = Counter(
            blocker
            for row in rows
            for blocker in (row.get("blockers") or [])
            if str(blocker).startswith("blocked_short_capacity_")
            or str(blocker).startswith("blocked_short_broker_capacity")
        )
        capacity_failure_classes = Counter(
            str(row.get("short_capacity_blocker_class") or "")
            for row in rows
            if str(row.get("short_capacity_blocker_class") or "")
        )
        order_ids = {
            str(row.get("longbridge_order_id") or row.get("broker_order_id") or row.get("order_id") or "")
            for row in rows
            if str(row.get("longbridge_order_id") or row.get("broker_order_id") or row.get("order_id") or "")
        }
        filled_order_ids = {
            order_id
            for order_id in order_ids
            if order_status_by_id.get(order_id) in {"filled", "partially_filled"}
        }
        partially_filled_order_ids = {
            order_id for order_id in order_ids
            if order_status_by_id.get(order_id) == "partially_filled"
        }
        fully_filled_order_ids = {
            order_id for order_id in order_ids
            if order_status_by_id.get(order_id) == "filled"
        }
        current.update(
            {
                "broker_capacity_checked_count": len(capacity_checked),
                "broker_capacity_cache_hit_count": sum(
                    str(row.get("short_capacity_source") or "") == "broker_sdk_cache"
                    for row in capacity_checked
                ),
                "broker_capacity_live_query_count": sum(
                    str(row.get("short_capacity_source") or "") == "broker_sdk_live"
                    for row in capacity_checked
                ),
                "broker_capacity_blocked_count": sum(capacity_blockers.values()),
                "broker_capacity_blockers": dict(capacity_blockers),
                "broker_capacity_failure_classes": dict(capacity_failure_classes),
                "broker_order_id_count": len(order_ids),
                "broker_filled_order_count": len(filled_order_ids),
                "broker_partially_filled_order_count": len(partially_filled_order_ids),
                "broker_fully_filled_order_count": len(fully_filled_order_ids),
            }
        )
        runtime_rows[runtime_id] = current
    output["runtime_summaries"] = list(runtime_rows.values())
    base_summary = dict(output.get("summary") or {})
    base_summary.update(
        {
            "broker_capacity_checked_count": sum(
                int(row.get("broker_capacity_checked_count") or 0)
                for row in runtime_rows.values()
            ),
            "broker_capacity_cache_hit_count": sum(
                int(row.get("broker_capacity_cache_hit_count") or 0)
                for row in runtime_rows.values()
            ),
            "broker_capacity_live_query_count": sum(
                int(row.get("broker_capacity_live_query_count") or 0)
                for row in runtime_rows.values()
            ),
            "broker_capacity_blocked_count": sum(
                int(row.get("broker_capacity_blocked_count") or 0)
                for row in runtime_rows.values()
            ),
            "broker_capacity_failure_classes": dict(
                sum(
                    (
                        Counter(row.get("broker_capacity_failure_classes") or {})
                        for row in runtime_rows.values()
                    ),
                    Counter(),
                )
            ),
            "broker_order_id_count": sum(
                int(row.get("broker_order_id_count") or 0)
                for row in runtime_rows.values()
            ),
            "broker_filled_order_count": sum(
                int(row.get("broker_filled_order_count") or 0)
                for row in runtime_rows.values()
            ),
            "broker_partially_filled_order_count": sum(
                int(row.get("broker_partially_filled_order_count") or 0)
                for row in runtime_rows.values()
            ),
            "broker_fully_filled_order_count": sum(
                int(row.get("broker_fully_filled_order_count") or 0)
                for row in runtime_rows.values()
            ),
        }
    )
    output["summary"] = base_summary
    output["funnel_source"] = (
        "router_short_diagnostics_plus_realtime_execution_ledger_plus_longbridge_order_reconciliation"
    )
    return output


def _build_short_position_views(
    fill_attribution: dict[str, Any],
    execution_rows: list[dict[str, Any]],
    reconciliation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    symbol_rows: dict[str, dict[str, Any]] = {}
    open_short_lots: list[dict[str, Any]] = []
    status_by_order_id = {
        str(row.get("order_id") or ""): str(
            row.get("canonical_status") or row.get("longbridge_status") or row.get("status") or ""
        ).lower()
        for row in reconciliation_rows
        if isinstance(row, dict) and str(row.get("order_id") or "")
    }
    covers_by_open_order: dict[str, list[dict[str, Any]]] = {}
    for row in execution_rows:
        if str(row.get("position_action") or "") != "close_short":
            continue
        source_order_id = str(row.get("source_open_order_id") or "")
        if source_order_id:
            covers_by_open_order.setdefault(source_order_id, []).append(row)

    for batch in fill_attribution.get("batches", []):
        if not isinstance(batch, dict):
            continue
        symbol = str(batch.get("symbol") or "").upper().removesuffix(".US")
        if not symbol:
            continue
        direction = str(batch.get("direction") or "long").lower()
        remaining = _decimal(batch.get("remaining_quantity"))
        filled = _decimal(batch.get("filled_quantity"))
        current = symbol_rows.setdefault(
            symbol,
            {
                "symbol": symbol,
                "long_quantity": Decimal("0"),
                "short_quantity": Decimal("0"),
                "long_lot_count": 0,
                "short_lot_count": 0,
                "long_runtime_ids": set(),
                "short_runtime_ids": set(),
            },
        )
        side_key = "short" if direction == "short" else "long"
        current[f"{side_key}_quantity"] += remaining
        current[f"{side_key}_lot_count"] += 1
        runtime_id = str(batch.get("runtime_id") or "")
        if runtime_id:
            current[f"{side_key}_runtime_ids"].add(runtime_id)
        if direction != "short":
            continue
        open_order_id = str(batch.get("open_order_id") or "")
        cover_rows = covers_by_open_order.get(open_order_id, [])
        cover_statuses = [
            status_by_order_id.get(
                str(row.get("longbridge_order_id") or row.get("broker_order_id") or row.get("order_id") or ""),
                str(row.get("submission_status") or "").lower(),
            )
            for row in cover_rows
        ]
        open_short_lots.append(
            {
                "batch_id": str(batch.get("batch_id") or ""),
                "open_order_id": open_order_id,
                "trade_id": str(batch.get("trade_id") or ""),
                "runtime_id": runtime_id,
                "capital_bucket": str(batch.get("capital_bucket") or ""),
                "symbol": symbol,
                "filled_quantity": _quantity(filled),
                "remaining_quantity": _quantity(remaining),
                "covered_quantity": _quantity(max(Decimal("0"), filled - remaining)),
                "lifecycle_status": "partially_covered" if filled > remaining else "open",
                "cover_intent_count": len(cover_rows),
                "pending_cover_order_count": sum(
                    status in {"new", "submitted", "pending", "partially_filled", "submit_unconfirmed_missing_order_id"}
                    for status in cover_statuses
                ),
                "filled_cover_order_count": sum(status == "filled" for status in cover_statuses),
            }
        )

    net_rows = []
    for row in symbol_rows.values():
        long_quantity = row.pop("long_quantity")
        short_quantity = row.pop("short_quantity")
        long_runtimes = sorted(row.pop("long_runtime_ids"))
        short_runtimes = sorted(row.pop("short_runtime_ids"))
        net_rows.append(
            {
                **row,
                "long_quantity": _quantity(long_quantity),
                "short_quantity": _quantity(short_quantity),
                "net_quantity": _quantity(long_quantity - short_quantity),
                "gross_quantity": _quantity(long_quantity + short_quantity),
                "contains_both_directions": long_quantity > 0 and short_quantity > 0,
                "long_runtime_ids": long_runtimes,
                "short_runtime_ids": short_runtimes,
            }
        )
    completed_short_lots = [
        row for row in fill_attribution.get("completed_trades", [])
        if isinstance(row, dict) and str(row.get("direction") or "").lower() == "short"
    ]
    return {
        "same_symbol_long_short_net": sorted(net_rows, key=lambda row: row["symbol"]),
        "short_lot_lifecycle": {
            "summary": {
                "open_lot_count": len(open_short_lots),
                "partially_covered_lot_count": sum(
                    row["lifecycle_status"] == "partially_covered" for row in open_short_lots
                ),
                "pending_cover_order_count": sum(
                    int(row["pending_cover_order_count"]) for row in open_short_lots
                ),
                "completed_lot_count": len(completed_short_lots),
            },
            "open_lots": open_short_lots,
            "recent_completed_lots": completed_short_lots[-20:],
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    return json.loads(_resolve(path).read_text(encoding="utf-8"))


def _age_seconds(value: Any, now: datetime) -> float | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds())


def _process_alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return int(pid) > 0
    except (OSError, TypeError, ValueError):
        return False


def _inventory(execution_config: dict[str, Any]) -> dict[str, Any]:
    buckets = execution_config.get("virtual_capital_buckets") or {}
    contract_config = execution_config.get("strategy_contracts") or {}
    contracts: dict[str, dict[str, Any]] = {}
    if contract_config.get("directory"):
        try:
            contracts = load_contracts_cached(str(_resolve(contract_config["directory"])))
        except (FileNotFoundError, OSError, ValueError):
            contracts = {}
    rows: list[dict[str, Any]] = []
    runtime_ids: list[str] = []
    contract_rows: list[dict[str, Any]] = []
    for bucket_id, bucket in buckets.items():
        ids = list(bucket.get("runtime_ids") or [])
        runtime_ids.extend(ids)
        bucket_contracts = []
        for runtime_id in ids:
            contract = contracts.get(runtime_id) or {}
            contract_row = {
                "runtime_id": runtime_id,
                "contract_stage": contract.get("stage"),
                "contract_stage_zh": contract.get("stage_zh"),
                "contract_hash": contract.get("contract_hash"),
                "contract_schema_version": contract.get("schema_version"),
                "contract_loaded": bool(contract),
            }
            contract_rows.append(contract_row)
            bucket_contracts.append(contract_row)
        rows.append(
            {
                "bucket_id": bucket_id,
                "label": bucket.get("label") or bucket_id,
                "direction": bucket.get("position_direction") or "long",
                "runtime_ids": ids,
                "runtime_count": len(ids),
                "equity": bucket.get("equity"),
                "max_total_exposure": bucket.get("max_total_exposure"),
                "max_symbol_exposure": bucket.get("max_symbol_exposure"),
                "max_risk_per_order": bucket.get("max_risk_per_order"),
                "strategy_contracts": bucket_contracts,
            }
        )
    long_count = sum(row["runtime_count"] for row in rows if row["direction"] != "short")
    short_count = sum(row["runtime_count"] for row in rows if row["direction"] == "short")
    return {
        "bucket_count": len(rows),
        "runtime_count": len(runtime_ids),
        "long_runtime_count": long_count,
        "short_runtime_count": short_count,
        "runtime_ids": runtime_ids,
        "strategy_contracts_required": bool(contract_config.get("required", False)),
        "contract_loaded_count": sum(row["contract_loaded"] for row in contract_rows),
        "contract_rows": contract_rows,
        "buckets": rows,
    }


def _local_inventory(registry: dict[str, Any]) -> dict[str, int]:
    strategies = registry.get("strategies") if isinstance(registry.get("strategies"), list) else []
    trading = [row for row in strategies if row.get("module_role") == "independent_runtime"]
    auxiliaries = [row for row in strategies if row.get("module_role") != "independent_runtime"]
    return {
        "parent_strategy_count": len(trading),
        "local_runtime_count": sum(len(row.get("runtime_accounts") or []) for row in trading),
        "auxiliary_module_count": len(auxiliaries),
    }


def _derive_migration_status_path(config: dict[str, Any], fill_attribution_path: Path) -> Path:
    configured = (config.get("inputs") or {}).get("pa004_migration_status")
    if configured:
        return _resolve(configured)
    return fill_attribution_path.parent / DEFAULT_PA004_MIGRATION_STATUS_NAME


def _holding_rows(account: dict[str, Any], pnl: dict[str, Any]) -> list[dict[str, Any]]:
    rows = account.get("positions") if isinstance(account.get("positions"), list) else []
    if rows:
        return [dict(row) for row in rows if isinstance(row, dict)]
    rows = pnl.get("current_holdings") if isinstance(pnl.get("current_holdings"), list) else []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _parse_iso_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _trade_baseline_timestamp(row: dict[str, Any]) -> datetime | None:
    return _parse_iso_utc(row.get("opened_at")) or _parse_iso_utc(row.get("closed_at"))


def _apply_pa004_migration_views(
    fill_attribution: dict[str, Any],
    migration_status: dict[str, Any],
) -> dict[str, Any]:
    completed_trades = [
        dict(row) for row in fill_attribution.get("completed_trades", []) if isinstance(row, dict)
    ]
    bucket_baselines = migration_status.get("bucket_baselines") if isinstance(migration_status.get("bucket_baselines"), dict) else {}
    active_baselines = {
        bucket: started_at
        for bucket, payload in bucket_baselines.items()
        if bucket in PA004_MIGRATION_BUCKETS
        and isinstance(payload, dict)
        and str(payload.get("started_at") or "")
        for started_at in [str(payload.get("started_at") or "")]
    }
    if not active_baselines or not completed_trades:
        return {
            "display_summary": dict(fill_attribution.get("summary") or {}),
            "display_strategy_performance": list(fill_attribution.get("strategy_performance") or []),
            "display_bucket_performance": list(fill_attribution.get("bucket_performance") or []),
            "display_recent_completed_trades": list(fill_attribution.get("completed_trades") or [])[-50:],
            "archived_summary": summarize_completed_trade_rows([]),
            "archived_strategy_performance": [],
            "archived_bucket_performance": [],
            "archived_recent_completed_trades": [],
            "active_bucket_baselines": active_baselines,
        }

    display_rows: list[dict[str, Any]] = []
    archived_rows: list[dict[str, Any]] = []
    for row in completed_trades:
        bucket = str(row.get("capital_bucket") or "")
        started_at = active_baselines.get(bucket)
        if not started_at:
            display_rows.append(row)
            continue
        baseline = _parse_iso_utc(started_at)
        trade_timestamp = _trade_baseline_timestamp(row)
        if baseline is not None and trade_timestamp is not None and trade_timestamp >= baseline:
            display_rows.append(row)
        else:
            archived_rows.append(row)
    display_normal = [row for row in display_rows if not bool(row.get("fault_day"))]
    archived_normal = [row for row in archived_rows if not bool(row.get("fault_day"))]
    return {
        "display_summary": {
            **summarize_completed_trade_rows(display_rows),
            "exit_fill_event_count": sum(int(row.get("exit_fill_event_count") or 0) for row in display_rows),
        },
        "display_strategy_performance": group_completed_trade_performance_rows(display_normal, "runtime_id"),
        "display_bucket_performance": group_completed_trade_performance_rows(display_normal, "capital_bucket"),
        "display_recent_completed_trades": display_rows[-50:],
        "archived_summary": {
            **summarize_completed_trade_rows(archived_rows),
            "exit_fill_event_count": sum(int(row.get("exit_fill_event_count") or 0) for row in archived_rows),
        },
        "archived_strategy_performance": group_completed_trade_performance_rows(archived_normal, "runtime_id"),
        "archived_bucket_performance": group_completed_trade_performance_rows(archived_normal, "capital_bucket"),
        "archived_recent_completed_trades": archived_rows[-50:],
        "active_bucket_baselines": active_baselines,
    }


def build_dashboard(config: dict[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    inputs = config["inputs"]
    runtime_path = _resolve(inputs["sdk_runtime_status"])
    account_path = _resolve(inputs["account_state"])
    account_summary_path = _resolve(inputs["account_state_summary"])
    execution_path = _resolve(inputs["execution_status"])
    epoch_path = _resolve(inputs["epoch_state"])
    formal_epoch_path = _resolve(inputs["formal_epoch_marker"])
    reconciliation_path = _resolve(inputs["order_reconciliation"])
    fill_attribution_path = _resolve(inputs.get("fill_attribution") or DEFAULT_FILL_ATTRIBUTION_PATH)
    pnl_path = _resolve(inputs["pnl_reconciliation"])
    execution_config_path = _resolve(inputs["execution_config"])
    runtime, runtime_artifact = _read_json_artifact(runtime_path)
    account, account_artifact = _read_json_artifact(account_path)
    account_summary, account_summary_artifact = _read_json_artifact(account_summary_path)
    execution, execution_artifact = _read_json_artifact(execution_path)
    execution_ledger = (
        _read_recent_jsonl(_resolve(inputs["execution_ledger"]))
        if inputs.get("execution_ledger")
        else []
    )
    epoch, epoch_artifact = _read_json_artifact(epoch_path)
    formal_epoch, formal_epoch_artifact = _read_json_artifact(formal_epoch_path)
    reconciliation, reconciliation_artifact = _read_json_artifact(reconciliation_path)
    fill_attribution, fill_attribution_artifact = _read_json_artifact(fill_attribution_path)
    short_diagnostics, short_diagnostics_artifact = (
        _read_json_artifact(_resolve(inputs["short_signal_diagnostics"]))
        if inputs.get("short_signal_diagnostics")
        else ({}, {"path": "", "status": "missing"})
    )
    pnl, pnl_artifact = _read_json_artifact(pnl_path)
    execution_config, execution_config_artifact = _read_json_artifact(execution_config_path)
    inventory = _inventory(execution_config)
    expected_short_runtime_ids = [
        runtime_id
        for bucket in inventory["buckets"]
        if bucket["direction"] == "short"
        for runtime_id in bucket["runtime_ids"]
    ]
    migration_status = _read_optional_json(_derive_migration_status_path(config, fill_attribution_path))
    pa002_milestone = _read_optional_json(
        _resolve(inputs.get("pa002_dual_version_milestone") or DEFAULT_PA002_MILESTONE_STATUS)
    )
    short_diagnostics = _merge_short_execution_funnel(
        short_diagnostics,
        execution_ledger,
        reconciliation.get("rows") or [],
        expected_runtime_ids=expected_short_runtime_ids,
    )
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    now = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    health = config.get("health") or {}
    runtime_age = _age_seconds(runtime.get("generated_at"), now)
    account_age = _age_seconds(account.get("generated_at"), now)
    summary_age = _age_seconds(account_summary.get("generated_at"), now)
    orders_age = _age_seconds(reconciliation.get("generated_at"), now)
    pnl_age = _age_seconds(pnl.get("generated_at"), now)
    fill_attribution_age = _age_seconds(fill_attribution.get("generated_at"), now)
    pa002_milestone_age = _age_seconds(pa002_milestone.get("generated_at"), now)
    runtime_process_alive = _process_alive(runtime.get("runtime_pid"))
    runtime_fresh = runtime_age is not None and runtime_age <= float(health.get("maximum_runtime_age_seconds", 10))
    account_fresh = account_age is not None and account_age <= float(health.get("maximum_account_age_seconds", 45))
    slow_limit = float(health.get("maximum_statistics_age_seconds", 300))
    account_summary_fresh = summary_age is not None and summary_age <= slow_limit
    orders_fresh = orders_age is not None and orders_age <= slow_limit
    pnl_fresh = pnl_age is not None and pnl_age <= slow_limit
    fill_attribution_fresh = fill_attribution_age is not None and fill_attribution_age <= slow_limit
    pa002_source_fill_generated_at = str(
        (pa002_milestone.get("source_status") or {}).get("fill_attribution_generated_at") or ""
    )
    current_fill_generated_at = str(fill_attribution.get("generated_at") or "")
    pa002_milestone_fresh = bool(
        fill_attribution_fresh
        and pa002_milestone_age is not None
        and pa002_milestone_age <= slow_limit
        and pa002_source_fill_generated_at
        and pa002_source_fill_generated_at == current_fill_generated_at
    )
    if pa002_milestone_fresh:
        pa002_milestone_view = {**pa002_milestone, "data_available": True}
    else:
        pa002_milestone_view = {
            "evaluation_status": "stale_source_blocked",
            "data_available": False,
            "plain_language_result": "长桥实际成交归因未刷新或与里程碑不一致，PA002 双版本统计暂不可计算。",
            "source_status": {
                "fill_attribution_fresh": fill_attribution_fresh,
                "milestone_fresh": (
                    pa002_milestone_age is not None and pa002_milestone_age <= slow_limit
                ),
                "source_fill_generated_at": pa002_source_fill_generated_at,
                "current_fill_generated_at": current_fill_generated_at,
            },
        }
    coverage = str(runtime.get("subscription_coverage") or "")
    try:
        subscribed_count = int(coverage.split("/", 1)[0])
    except (ValueError, IndexError):
        subscribed_count = runtime.get("subscribed_symbol_count")
    market_data_mode = str(runtime.get("market_data_mode") or "")
    market_data_coverage = str(
        runtime.get("market_data_coverage")
        or runtime.get("subscription_coverage")
        or ""
    )
    trading_market_data_coverage = str(
        runtime.get("trading_market_data_coverage")
        or runtime.get("trading_subscription_coverage")
        or ""
    )

    position_count = int(account.get("position_row_count") or len(account.get("positions") or []))
    open_order_count = int(account.get("open_order_count") or len(account.get("open_orders") or []))
    pending_count = int(execution.get("pending_confirmation_count") or 0)
    epoch_status = formal_epoch.get("status") or epoch.get("status") or "unknown"
    if "new_position_submission_enabled" in runtime:
        entries_enabled = bool(runtime.get("new_position_submission_enabled"))
    else:
        entries_enabled = bool(runtime.get("dispatch_enabled") and runtime.get("dispatch_requested", True))
    if epoch_status != "active":
        entries_enabled = False
    marketdata_gate_enforced = bool(
        runtime.get(
            "complete_session_gate_enabled",
            runtime.get("two_day_readonly_gate", True),
        )
    )
    marketdata_gate_passed = bool(
        (not marketdata_gate_enforced)
        or runtime.get(
            "complete_session_gate_passed",
            runtime.get("readonly_gate_passed"),
        ) is True
    )

    source_checks = {
        "sdk_runtime": runtime_artifact.get("status") == "ok" and runtime_process_alive and runtime_fresh and runtime.get("sdk_connected") is True,
        "account": account_artifact.get("status") == "ok" and account_fresh,
        "execution": execution_artifact.get("status") == "ok",
        "account_statistics": account_summary_artifact.get("status") == "ok" and account_summary_fresh,
        "orders": reconciliation_artifact.get("status") == "ok" and orders_fresh,
        "pnl": pnl_artifact.get("status") == "ok" and pnl_fresh,
        "fill_attribution": fill_attribution_artifact.get("status") == "ok" and fill_attribution_fresh,
    }
    trading_sources_trustworthy = (
        source_checks["sdk_runtime"]
        and source_checks["account"]
        and bool(account.get("paper_account_verified"))
    )
    statistics_trustworthy = all(
        source_checks[key] for key in ("account_statistics", "orders", "pnl", "fill_attribution")
    )
    daily_context_complete = (
        bool(runtime.get("trading_daily_context_ready"))
        if runtime.get("trading_daily_context_ready") is not None
        else (
            bool(runtime.get("daily_context_complete"))
            if runtime.get("daily_context_complete") is not None
            else runtime.get("daily_context_state") == "complete"
        )
    )
    daily_context_loading = (
        runtime.get("trading_daily_context_ready") is False
        or (
            runtime.get("trading_daily_context_ready") is None
            and runtime.get("daily_context_state") == "loading"
        )
    )
    data_status = (
        "marketdata_gate_artifact_error"
        if runtime_artifact.get("status") != "ok"
        else
        "sdk_starting_daily_context"
        if trading_sources_trustworthy and daily_context_loading
        else
        "trustworthy"
        if trading_sources_trustworthy and statistics_trustworthy
        else "trading_ready_statistics_stale"
        if trading_sources_trustworthy
        else "temporarily_unavailable"
    )
    market_date = now.astimezone(NEW_YORK).date().isoformat()
    holding_rows = _holding_rows(account, pnl)
    if fill_attribution_fresh:
        short_position_views = _build_short_position_views(
            fill_attribution,
            execution_ledger,
            reconciliation.get("rows") or [],
        )
        fill_attribution = {
            **fill_attribution,
            "position_layers": build_virtual_position_layers(
                fill_attribution,
                holding_rows,
                market_date=market_date,
            ),
            **short_position_views,
        }
    else:
        short_position_views = {
            "same_symbol_long_short_net": [],
            "short_lot_lifecycle": {
                "summary": {"status": "stale_source_blocked"},
                "open_lots": [],
                "recent_completed_lots": [],
            },
        }
    migration_views = _apply_pa004_migration_views(fill_attribution, migration_status) if fill_attribution_fresh else {
        "display_summary": {"status": "stale_source_blocked"},
        "display_strategy_performance": [],
        "display_bucket_performance": [],
        "display_recent_completed_trades": [],
        "archived_summary": {"status": "stale_source_blocked"},
        "archived_strategy_performance": [],
        "archived_bucket_performance": [],
        "archived_recent_completed_trades": [],
        "active_bucket_baselines": {},
    }
    return {
        "schema_version": "1.0",
        "stage": "M15.longbridge_dashboard",
        "title": "长桥模拟账户",
        "generated_at": timestamp,
        "source_of_truth": "longbridge_sdk_paper_account",
        "local_simulation_isolated": True,
        "legacy_queue_used": False,
        "legacy_cli_used": False,
        "data_status": data_status,
        "input_artifacts": {
            "sdk_runtime_status": runtime_artifact,
            "account_state": account_artifact,
            "account_state_summary": account_summary_artifact,
            "execution_status": execution_artifact,
            "epoch_state": epoch_artifact,
            "formal_epoch_marker": formal_epoch_artifact,
            "order_reconciliation": reconciliation_artifact,
            "fill_attribution": fill_attribution_artifact,
            "short_signal_diagnostics": short_diagnostics_artifact,
            "pnl_reconciliation": pnl_artifact,
            "execution_config": execution_config_artifact,
        },
        "source_checks": source_checks,
        "marketdata_integrity_gate": {
            "status": (
                runtime_artifact.get("status")
                if runtime_artifact.get("status") != "ok"
                else ("passed" if marketdata_gate_passed else "blocked")
            ),
            "artifacts_healthy": runtime_artifact.get("status") == "ok",
            "gate_passed": marketdata_gate_passed,
            "new_position_submission_enabled": entries_enabled,
            "complete_boundary_count": int(runtime.get("complete_boundary_count") or 0),
            "realtime_tradable_bar_count": int(runtime.get("realtime_tradable_bar_count") or 0),
            "summary": (
                f"行情门禁状态文件 {runtime_artifact.get('status')}；完整边界 {int(runtime.get('complete_boundary_count') or 0)}，"
                f"实时 K 线 {int(runtime.get('realtime_tradable_bar_count') or 0)}；关闭新开仓，已有持仓退出仍需要实时行情。"
                if runtime_artifact.get("status") != "ok"
                else (
                    f"完整交易日行情门禁未通过，完整边界 {int(runtime.get('complete_boundary_count') or 0)}，"
                    f"实时 K 线 {int(runtime.get('realtime_tradable_bar_count') or 0)}；关闭新开仓，已有持仓退出仍需要实时行情。"
                    if not marketdata_gate_passed
                    else f"完整交易日行情门禁已通过，完整边界 {int(runtime.get('complete_boundary_count') or 0)}，实时 K 线 {int(runtime.get('realtime_tradable_bar_count') or 0)}。"
                )
            ),
        },
        "runtime": {
            "runtime_engine": runtime.get("runtime_engine"),
            "status": runtime.get("status"),
            "runtime_process_alive": runtime_process_alive,
            "runtime_status_age_seconds": runtime_age,
            "sdk_connected": runtime.get("sdk_connected"),
            "paper_account_verified": account.get("paper_account_verified"),
            "account_channel": account.get("account_channel"),
            "configured_symbol_count": runtime.get("configured_symbol_count"),
            "subscribed_symbol_count": subscribed_count,
            "market_data_mode": market_data_mode,
            "market_data_transport": runtime.get("market_data_transport"),
            "quote_worker_generation": runtime.get("quote_worker_generation"),
            "subscription_set_sha256": runtime.get("subscription_set_sha256"),
            "reference_push_heartbeat": runtime.get("reference_push_heartbeat") or {},
            "complete_boundary_count": int(runtime.get("complete_boundary_count") or 0),
            "incomplete_boundary_count": int(runtime.get("incomplete_boundary_count") or 0),
            "late_boundary_count": int(runtime.get("late_boundary_count") or 0),
            "last_complete_boundary": runtime.get("last_complete_boundary"),
            "last_incomplete_boundary": runtime.get("last_incomplete_boundary"),
            "last_boundary_missing_symbols": runtime.get("last_boundary_missing_symbols") or [],
            "realtime_tradable_bar_count": int(runtime.get("realtime_tradable_bar_count") or 0),
            "no_trade_carry_forward_count": int(runtime.get("no_trade_carry_forward_count") or 0),
            "postclose_repair_bar_count": int(runtime.get("postclose_repair_bar_count") or 0),
            "thread_count": runtime.get("thread_count"),
            "file_descriptor_count": runtime.get("file_descriptor_count"),
            "resident_memory_kib": runtime.get("resident_memory_kib"),
            "deployment_manifest_verified": runtime.get("deployment_manifest_verified"),
            "deployment_manifest_issues": runtime.get("deployment_manifest_issues") or [],
            "deployment_branch": runtime.get("deployment_branch"),
            "deployment_commit": runtime.get("deployment_commit"),
            "deployment_worktree_clean": runtime.get("deployment_worktree_clean"),
            "market_data_coverage": market_data_coverage,
            "trading_symbol_count": runtime.get("trading_symbol_count"),
            "trading_subscription_coverage": runtime.get("trading_subscription_coverage"),
            "trading_market_data_coverage": trading_market_data_coverage,
            "position_monitoring_symbol_count": runtime.get("position_monitoring_symbol_count"),
            "position_monitoring_symbols": runtime.get("position_monitoring_symbols") or [],
            "position_monitoring_subscription_coverage": runtime.get("position_monitoring_subscription_coverage"),
            "position_monitoring_failed_symbols": runtime.get("position_monitoring_failed_symbols") or [],
            "position_monitoring_exit_only": runtime.get("position_monitoring_exit_only"),
            "position_monitoring_new_entries_allowed": runtime.get("position_monitoring_new_entries_allowed"),
            "readonly_expansion_symbol_count": runtime.get("readonly_expansion_symbol_count"),
            "readonly_expansion_subscription_coverage": runtime.get("readonly_expansion_subscription_coverage"),
            "readonly_expansion_acceptance_status": runtime.get("readonly_expansion_acceptance_status"),
            "daily_context_row_count": runtime.get("daily_context_row_count"),
            "trading_daily_context_row_count": runtime.get("trading_daily_context_row_count"),
            "trading_daily_context_expected_row_count": runtime.get("trading_daily_context_expected_row_count"),
            "daily_context_complete": daily_context_complete,
            "last_event_at": runtime.get("last_event_at"),
            "account_snapshot_generated_at": account.get("generated_at"),
            "account_snapshot_age_seconds": account_age,
            "dispatch_configured": runtime.get("paper_order_dispatch_enabled"),
            "dispatch_enabled": runtime.get("dispatch_enabled"),
            "new_position_submission_enabled": entries_enabled,
            "submission_armed": entries_enabled,
            "config_fingerprint": runtime.get("config_fingerprint"),
            "account_worker_status": runtime.get("account_snapshot_worker_status"),
            "account_worker_pid": runtime.get("account_snapshot_worker_pid"),
            "account_worker_generation": runtime.get("account_snapshot_worker_generation"),
            "account_worker_last_elapsed_seconds": runtime.get("account_snapshot_worker_elapsed_seconds"),
            "account_worker_restart_count": runtime.get("account_snapshot_worker_restart_count"),
            "account_worker_timeout_count": runtime.get("account_snapshot_worker_timeout_count"),
            "account_worker_circuit_open": runtime.get("account_snapshot_circuit_open"),
        },
        "formal_test": {
            "status": epoch_status,
            "test_epoch_id": formal_epoch.get("test_epoch_id") or epoch.get("test_epoch_id"),
            "short_test_epoch_id": formal_epoch.get("short_test_epoch_id"),
            "test_started_at": formal_epoch.get("test_started_at") or epoch.get("test_started_at"),
            "activation_blocker": formal_epoch.get("activation_blocker") or epoch.get("activation_blocker"),
            "positions": position_count,
            "open_orders": open_order_count,
            "pending_orders": pending_count,
        },
        "account": {
            "cash": account_summary.get("cash") if account_summary_fresh else account.get("cash"),
            "usd_available_cash": account.get("usd_available_cash"),
            "total_equity": account_summary.get("account_total_equity_estimate") if account_summary_fresh else account.get("account_total_equity_estimate"),
            "total_equity_currency": account_summary.get("account_total_equity_currency") if account_summary_fresh else account.get("account_total_equity_currency"),
            "buying_power": account.get("account_buying_power")
            or (account_summary.get("buying_power") if account_summary_fresh else None),
            "buying_power_currency": account.get("account_buying_power_currency"),
            "today_pnl": account_summary.get("account_today_total_pnl") if account_summary_fresh else None,
            "today_pnl_source": account_summary.get("account_today_total_pnl_source") if account_summary_fresh else "stale_source_blocked",
            "position_count": position_count,
            "open_order_count": open_order_count,
        },
        "pnl": {
            "account_pnl": pnl.get("account_pnl") if pnl_fresh else None,
            "today_account_pnl": pnl.get("today_account_pnl") if pnl_fresh else None,
            "market_day_profit_analysis": pnl.get("market_day_profit_analysis") if pnl_fresh else None,
            "trading_pnl": pnl.get("trading_pnl") if pnl_fresh else None,
            "current_holdings": pnl.get("current_holdings") if pnl_fresh else None,
            "source_status": pnl.get("source_status") if pnl_fresh else {"status": "stale_source_blocked"},
        },
        "orders": {
            "summary": (reconciliation.get("summary") or {})
            if orders_fresh
            else {"status": "stale_source_blocked"},
            "rows": (reconciliation.get("rows") or []) if orders_fresh else [],
        },
        "fill_attribution": {
            "fresh": fill_attribution_fresh,
            "generated_at": fill_attribution.get("generated_at"),
            "age_seconds": fill_attribution_age,
            "summary": fill_attribution.get("summary") if fill_attribution_fresh else {"status": "stale_source_blocked"},
            "display_summary": migration_views["display_summary"],
            "archived_summary": migration_views["archived_summary"],
            "fee_model": fill_attribution.get("fee_model") if fill_attribution_fresh else None,
            "strategy_performance": (
                migration_views["display_strategy_performance"]
            ) if fill_attribution_fresh else [],
            "bucket_performance": (
                migration_views["display_bucket_performance"]
            ) if fill_attribution_fresh else [],
            "archived_strategy_performance": (
                migration_views["archived_strategy_performance"]
            ) if fill_attribution_fresh else [],
            "archived_bucket_performance": (
                migration_views["archived_bucket_performance"]
            ) if fill_attribution_fresh else [],
            "recent_completed_trades": (
                migration_views["display_recent_completed_trades"]
            ) if fill_attribution_fresh else [],
            "archived_recent_completed_trades": (
                migration_views["archived_recent_completed_trades"]
            ) if fill_attribution_fresh else [],
            "symbol_mismatch_count": sum(
                1 for row in fill_attribution.get("symbol_checks", [])
                if isinstance(row, dict) and not bool(row.get("matches_broker_net"))
            ) if fill_attribution_fresh else None,
            "position_layers": fill_attribution.get("position_layers") if fill_attribution_fresh else None,
            "same_symbol_long_short_net": short_position_views["same_symbol_long_short_net"],
            "short_lot_lifecycle": short_position_views["short_lot_lifecycle"],
            "strategy_metrics_trustworthy": bool(
                fill_attribution_fresh
                and not fill_attribution.get("anomalies")
                and all(
                    bool(row.get("matches_broker_net"))
                    for row in fill_attribution.get("symbol_checks", [])
                    if isinstance(row, dict)
                )
            ),
        },
        "paper_short_diagnostics": {
            "generated_at": short_diagnostics.get("generated_at"),
            "test_epoch_id": short_diagnostics.get("test_epoch_id") or formal_epoch.get("short_test_epoch_id"),
            "summary": short_diagnostics.get("summary") or {
                "runtime_count": inventory["short_runtime_count"],
                "candidate_count": 0,
                "signal_ready_count": 0,
                "blocked_count": 0,
                "top_blockers": {},
            },
            "runtime_summaries": short_diagnostics.get("runtime_summaries") or [],
            "detector_attempt_rows": list(short_diagnostics.get("detector_attempt_rows") or [])[-50:],
            "short_lot_lifecycle": short_position_views["short_lot_lifecycle"],
            "recent_decisions": list(short_diagnostics.get("decision_rows") or [])[-20:],
        },
        "strategy_inventory": inventory,
        "pa002_dual_version_milestone": pa002_milestone_view,
        "pa004_migration": {
            "status_file": str(_derive_migration_status_path(config, fill_attribution_path)),
            "active_bucket_baselines": migration_views["active_bucket_baselines"],
            "raw": migration_status if migration_status else {},
            "enabled": bool(migration_views["active_bucket_baselines"]),
        },
        "notes": [
            "所有长桥成绩只统计长桥实际订单、成交和持仓。",
            "看板不读取本地模拟账本或本地策略 registry，只展示长桥事实源与归因层。",
            "正式测试未激活时，配置中的运行单元全部禁止新开仓。",
            "完整交易日行情门禁未通过时只关闭新开仓；已有持仓退出仍需要实时行情，不能把无实时推送当作退出可用。",
        ],
    }


def _render_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>长桥模拟账户</title><style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f5f6f8;color:#17202a}}header,main{{max-width:1400px;margin:auto;padding:16px}}header{{background:#fff;border-bottom:1px solid #dfe3e8;max-width:none}}h1{{font-size:20px;margin:0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}.card{{background:#fff;border:1px solid #dfe3e8;border-radius:6px;padding:12px}}.v{{font-size:22px;font-weight:650;margin-top:6px}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{text-align:left;border-bottom:1px solid #e7eaee;padding:8px;font-size:13px}}.bad{{color:#a61b1b}}.ok{{color:#136b36}}</style></head>
<body><header><h1>长桥模拟账户</h1></header><main><div id=\"app\"></div><script>
const d={data}; const v=x=>x===null||x===undefined||x===''?'暂不可计算':x;
const cls=d.data_status==='trustworthy'?'ok':'bad';
const statusText={{trustworthy:'全部数据正常',sdk_starting_daily_context:'日线装载中，暂不允许新开仓',trading_ready_statistics_stale:'交易核心正常，统计待刷新',temporarily_unavailable:'数据暂不可用',marketdata_gate_artifact_error:'行情门禁状态文件缺失或损坏',pending_flatten:'等待清理旧持仓',active:'正式测试运行中'}};
const money=(value,currency)=>value===null||value===undefined||value===''?'暂不可计算':`${{value}} ${{currency||''}}`.trim();
const positionLayers=d.fill_attribution.position_layers||{{}};
const displaySummary=d.fill_attribution.display_summary||{{}};
const archivedSummary=d.fill_attribution.archived_summary||{{}};
const migrationSummary=Object.entries(d.pa004_migration.active_bucket_baselines||{{}}).map(([bucket,startedAt])=>`${{bucket}}: ${{startedAt}}`).join('；')||'未启用';
const pa002Milestone=d.pa002_dual_version_milestone||{{}};
const cards=[['数据状态',statusText[d.data_status]||d.data_status],['行情门禁',v(d.marketdata_integrity_gate?.status)],['门禁说明',v(d.marketdata_integrity_gate?.summary)],['SDK连接',d.runtime.sdk_connected?'已连接':'未连接'],['行情传输',v(d.runtime.market_data_transport)],['行情模式',v(d.runtime.market_data_mode)],['全部行情覆盖',v(d.runtime.market_data_coverage)],['交易池行情覆盖',v(d.runtime.trading_market_data_coverage)],['已有持仓额外监控',v(d.runtime.position_monitoring_subscription_coverage)],['额外监控失败',v(d.runtime.position_monitoring_failed_symbols?.length||0)],['按时完整边界',v(d.runtime.complete_boundary_count)],['不完整边界',v(d.runtime.incomplete_boundary_count)],['迟到边界',v(d.runtime.late_boundary_count)],['实时K线',v(d.runtime.realtime_tradable_bar_count)],['盘后补录K线',v(d.runtime.postclose_repair_bar_count)],['部署清单',d.runtime.deployment_manifest_verified?'已验证':'未验证'],['工作区',d.runtime.deployment_worktree_clean?'干净':'有改动'],['账户快照进程',d.runtime.account_worker_circuit_open?'熔断':v(d.runtime.account_worker_status)],['账户快照重启',d.runtime.account_worker_restart_count],['只读扩展池',v(d.runtime.readonly_expansion_subscription_coverage)],['扩展验收',v(d.runtime.readonly_expansion_acceptance_status)],['交易日线',`${{v(d.runtime.trading_daily_context_row_count)}}/${{v(d.runtime.trading_daily_context_expected_row_count)}}`],['正式测试',statusText[d.formal_test.status]||d.formal_test.status],['App口径当日盈亏',d.account.today_pnl],['纽约交易日收益分析',d.pnl.market_day_profit_analysis?.sum_profit],['账户净资产',money(d.account.total_equity,d.account.total_equity_currency)],['美元可用现金',money(d.account.usd_available_cash,'USD')],['真实账户持仓浮盈',positionLayers.actual_account_total?.unrealized_pnl],['虚拟归因持仓浮盈',positionLayers.attributed_virtual_total?.unrealized_pnl],['无法归因浮盈差额',positionLayers.unreconciled_delta?.unrealized_pnl],['真实持仓市值',positionLayers.actual_account_total?.gross_market_value],['虚拟归因市值',positionLayers.attributed_virtual_total?.gross_market_value],['对账差额市值',positionLayers.unreconciled_delta?.gross_market_value],['展示成绩完整交易',displaySummary.completed_trade_count],['展示成绩扣费后已实现',displaySummary.estimated_net_realized_pnl],['PA002双版本阶段',v(pa002Milestone.milestone_phase)],['PA002有效交易日',v(pa002Milestone.aggregate?.effective_trading_day_count)],['PA002完整交易',v(pa002Milestone.aggregate?.completed_trade_count)],['PA002当前建议',v(pa002Milestone.recommendation?.plain_text)],['归档成绩完整交易',archivedSummary.completed_trade_count],['迁移新基线',migrationSummary],['当天买入后已卖出',positionLayers.today_buy_flow?.bought_then_sold_count],['当天买入仍持有',positionLayers.today_buy_flow?.still_held_batch_count],['当天买入仍持有浮盈',positionLayers.today_buy_flow?.still_held_unrealized_pnl],['做空候选',d.paper_short_diagnostics.summary?.candidate_count],['做空路由通过',d.paper_short_diagnostics.summary?.signal_ready_count],['做空容量阻断',d.paper_short_diagnostics.summary?.broker_capacity_blocked_count],['做空取得订单号',d.paper_short_diagnostics.summary?.broker_order_id_count],['做空实际成交单',d.paper_short_diagnostics.summary?.broker_filled_order_count],['精确归因异常',d.fill_attribution.summary?.anomaly_count],['持仓归因不一致',d.fill_attribution.symbol_mismatch_count],['长桥运行单元',d.strategy_inventory.runtime_count],['长桥资金池',d.strategy_inventory.bucket_count]];
cards.push(['做空检测尝试',d.paper_short_diagnostics.summary?.detector_attempted_count],['做空未形成候选',d.paper_short_diagnostics.summary?.no_candidate_count],['容量查询失败',d.paper_short_diagnostics.summary?.broker_capacity_failure_classes?.query_failed],['无借券库存',d.paper_short_diagnostics.summary?.broker_capacity_failure_classes?.no_borrow_inventory],['借券数量不足',d.paper_short_diagnostics.summary?.broker_capacity_failure_classes?.insufficient],['做空部分成交',d.paper_short_diagnostics.summary?.broker_partially_filled_order_count],['做空完全成交',d.paper_short_diagnostics.summary?.broker_fully_filled_order_count]);
const shortRows=d.paper_short_diagnostics.runtime_summaries||[];
const longShortNetRows=d.fill_attribution.same_symbol_long_short_net||[];
const shortLotLifecycle=d.fill_attribution.short_lot_lifecycle||{{summary:{{}},open_lots:[]}};
const performanceRows=d.fill_attribution.strategy_performance||[];
const bucketPerformanceRows=d.fill_attribution.bucket_performance||[];
const runtimeOpenRows=positionLayers.runtime_rows||[];
const bucketOpenRows=positionLayers.bucket_rows||[];
const concentrationRows=(positionLayers.cross_bucket_concentration||[]).filter(x=>Number(x.bucket_count||0)>1);
const symbolRows=(positionLayers.symbol_rows||[]).filter(x=>x.unreconciled_net_quantity!=='0.0000'||x.unreconciled_gross_market_value!=='0.00');
document.getElementById('app').innerHTML=`<section class=\"grid\">${{cards.map(x=>`<div class=\"card\"><div>${{x[0]}}</div><div class=\"v ${{x[0]==='数据状态'?cls:''}}\">${{v(x[1])}}</div></div>`).join('')}}</section><h2>策略实际成交成绩（默认按新基线展示，排除故障日）</h2><table><thead><tr><th>运行单元</th><th>完整交易</th><th>扣费后胜率</th><th>毛盈亏</th><th>估算费用</th><th>扣费后盈亏</th><th>扣费后盈利因子</th><th>最大回撤</th></tr></thead><tbody>${{performanceRows.map(x=>`<tr><td>${{v(x.runtime_id)}}</td><td>${{v(x.completed_trade_count)}}</td><td>${{v(x.win_rate_after_estimated_fees_pct)}}%</td><td>${{v(x.gross_realized_pnl)}}</td><td>${{v(x.estimated_fees)}}</td><td>${{v(x.estimated_net_realized_pnl)}}</td><td>${{v(x.profit_factor_after_estimated_fees)}}</td><td>${{v(x.maximum_drawdown_after_estimated_fees)}}</td></tr>`).join('')}}</tbody></table><h2>分仓实际成交成绩（默认按新基线展示，排除故障日）</h2><table><thead><tr><th>资金池</th><th>完整交易</th><th>扣费后胜率</th><th>毛盈亏</th><th>估算费用</th><th>扣费后盈亏</th><th>扣费后盈利因子</th><th>最大回撤</th></tr></thead><tbody>${{bucketPerformanceRows.map(x=>`<tr><td>${{v(x.capital_bucket)}}</td><td>${{v(x.completed_trade_count)}}</td><td>${{v(x.win_rate_after_estimated_fees_pct)}}%</td><td>${{v(x.gross_realized_pnl)}}</td><td>${{v(x.estimated_fees)}}</td><td>${{v(x.estimated_net_realized_pnl)}}</td><td>${{v(x.profit_factor_after_estimated_fees)}}</td><td>${{v(x.maximum_drawdown_after_estimated_fees)}}</td></tr>`).join('')}}</tbody></table><h2>当前持仓三层口径</h2><table><thead><tr><th>层级</th><th>净数量</th><th>市值</th><th>持仓浮盈</th><th>说明</th></tr></thead><tbody><tr><td>真实账户总口径</td><td>${{v(positionLayers.actual_account_total?.net_quantity)}}</td><td>${{v(positionLayers.actual_account_total?.gross_market_value)}}</td><td>${{v(positionLayers.actual_account_total?.unrealized_pnl)}}</td><td>只用长桥实际持仓价格</td></tr><tr><td>策略虚拟归因汇总</td><td>${{v(positionLayers.attributed_virtual_total?.net_quantity)}}</td><td>${{v(positionLayers.attributed_virtual_total?.gross_market_value)}}</td><td>${{v(positionLayers.attributed_virtual_total?.unrealized_pnl)}}</td><td>按虚拟批次乘长桥实际持仓价格</td></tr><tr><td>无法归因/对账差额</td><td>${{v(positionLayers.unreconciled_delta?.net_quantity)}}</td><td>${{v(positionLayers.unreconciled_delta?.gross_market_value)}}</td><td>${{v(positionLayers.unreconciled_delta?.unrealized_pnl)}}</td><td>真实账户减虚拟归因</td></tr></tbody></table><h2>分仓当前持仓浮盈</h2><table><thead><tr><th>资金池</th><th>批次数</th><th>净数量</th><th>当前市值</th><th>当前浮盈</th></tr></thead><tbody>${{bucketOpenRows.map(x=>`<tr><td>${{v(x.capital_bucket)}}</td><td>${{v(x.batch_count)}}</td><td>${{v(x.net_quantity)}}</td><td>${{v(x.gross_market_value)}}</td><td>${{v(x.unrealized_pnl)}}</td></tr>`).join('')}}</tbody></table><h2>策略当前持仓浮盈</h2><table><thead><tr><th>运行单元</th><th>批次数</th><th>净数量</th><th>当前市值</th><th>当前浮盈</th></tr></thead><tbody>${{runtimeOpenRows.map(x=>`<tr><td>${{v(x.runtime_id)}}</td><td>${{v(x.batch_count)}}</td><td>${{v(x.net_quantity)}}</td><td>${{v(x.gross_market_value)}}</td><td>${{v(x.unrealized_pnl)}}</td></tr>`).join('')}}</tbody></table><h2>同标的跨仓集中度</h2><table><thead><tr><th>标的</th><th>涉及分仓</th><th>涉及运行单元</th><th>虚拟归因市值</th><th>占全部虚拟持仓</th><th>分仓拆分</th></tr></thead><tbody>${{concentrationRows.map(x=>`<tr><td>${{v(x.symbol)}}</td><td>${{v(x.bucket_count)}}</td><td>${{v(x.runtime_count)}}</td><td>${{v(x.gross_market_value)}}</td><td>${{v(x.share_of_virtual_gross_exposure_pct)}}%</td><td>${{(x.bucket_breakdown||[]).map(y=>`${{y.capital_bucket}} ${{y.gross_market_value}}`).join('；')}}</td></tr>`).join('')}}</tbody></table><h2>无法归因/对账差额明细</h2><table><thead><tr><th>标的</th><th>真实净数量</th><th>虚拟净数量</th><th>净数量差额</th><th>市值差额</th><th>浮盈差额</th></tr></thead><tbody>${{symbolRows.map(x=>`<tr><td>${{v(x.symbol)}}</td><td>${{v(x.actual_net_quantity)}}</td><td>${{v(x.attributed_net_quantity)}}</td><td>${{v(x.unreconciled_net_quantity)}}</td><td>${{v(x.unreconciled_gross_market_value)}}</td><td>${{v(x.unreconciled_unrealized_pnl)}}</td></tr>`).join('')}}</tbody></table><p>费用为配置中的保守估算；长桥未提供可直接核对的实际费用字段时，不把估算冒充券商实际费用。未成交、取消、拒绝订单不进入成绩。PA004 若存在迁移状态文件，则默认展示新基线之后的成绩，旧成绩保留为归档。</p><h2>策略与虚拟仓</h2><table><thead><tr><th>仓位</th><th>方向</th><th>运行单元</th><th>资金</th><th>敞口上限</th></tr></thead><tbody>${{d.strategy_inventory.buckets.map(x=>`<tr><td>${{x.label}}</td><td>${{x.direction==='short'?'做空':'做多'}}</td><td>${{x.runtime_ids.join(', ')}}</td><td>${{v(x.equity)}}</td><td>${{v(x.max_total_exposure)}}</td></tr>`).join('')}}</tbody></table><h2>做空信号诊断</h2><table><thead><tr><th>策略运行单元</th><th>结构候选</th><th>路由通过</th><th>容量检查</th><th>容量阻断</th><th>订单号</th><th>实际成交</th><th>主要原因</th></tr></thead><tbody>${{shortRows.map(x=>`<tr><td>${{v(x.runtime_id)}}</td><td>${{v(x.candidate_count)}}</td><td>${{v(x.signal_ready_count)}}</td><td>${{v(x.broker_capacity_checked_count)}}</td><td>${{v(x.broker_capacity_blocked_count)}}</td><td>${{v(x.broker_order_id_count)}}</td><td>${{v(x.broker_filled_order_count)}}</td><td>${{Object.entries({{...(x.blockers||{{}}),...(x.broker_capacity_blockers||{{}})}}).slice(0,3).map(([k,n])=>`${{k}} ${{n}}`).join('；')||'暂无'}}</td></tr>`).join('')}}</tbody></table>`;
document.getElementById('app').insertAdjacentHTML('beforeend',`<h2>策略合同版本</h2><table><thead><tr><th>运行单元</th><th>合同阶段</th><th>合同哈希</th><th>装载状态</th></tr></thead><tbody>${{(d.strategy_inventory.contract_rows||[]).map(x=>`<tr><td>${{v(x.runtime_id)}}</td><td>${{v(x.contract_stage_zh||x.contract_stage)}}</td><td>${{x.contract_hash?x.contract_hash.slice(0,12):'未装载'}}</td><td>${{x.contract_loaded?'已锁定':'未装载'}}</td></tr>`).join('')}}</tbody></table>`);
document.getElementById('app').insertAdjacentHTML('beforeend',`<h2>三条 Short 分阶段漏斗</h2><table><thead><tr><th>运行单元</th><th>检测尝试</th><th>未形成候选</th><th>结构候选</th><th>路由通过</th><th>容量检查</th><th>容量阻断</th><th>订单号</th><th>成交</th><th>主要原因</th></tr></thead><tbody>${{shortRows.map(x=>`<tr><td>${{v(x.runtime_id)}}</td><td>${{v(x.detector_attempted_count)}}</td><td>${{v(x.no_candidate_count)}}</td><td>${{v(x.candidate_count)}}</td><td>${{v(x.signal_ready_count)}}</td><td>${{v(x.broker_capacity_checked_count)}}</td><td>${{v(x.broker_capacity_blocked_count)}}</td><td>${{v(x.broker_order_id_count)}}</td><td>${{v(x.broker_filled_order_count)}}</td><td>${{Object.entries({{...(x.no_candidate_reasons||{{}}),...(x.broker_capacity_failure_classes||{{}})}}).slice(0,3).map(([k,n])=>`${{k}} ${{n}}`).join('；')||'暂无'}}</td></tr>`).join('')}}</tbody></table><h2>同标的多空净额</h2><table><thead><tr><th>标的</th><th>多头数量</th><th>空头数量</th><th>净数量</th><th>总数量</th><th>同时多空</th></tr></thead><tbody>${{longShortNetRows.map(x=>`<tr><td>${{v(x.symbol)}}</td><td>${{v(x.long_quantity)}}</td><td>${{v(x.short_quantity)}}</td><td>${{v(x.net_quantity)}}</td><td>${{v(x.gross_quantity)}}</td><td>${{x.contains_both_directions?'是':'否'}}</td></tr>`).join('')}}</tbody></table><h2>Short lot 生命周期</h2><table><thead><tr><th>开仓订单</th><th>运行单元</th><th>标的</th><th>开仓数量</th><th>剩余数量</th><th>已回补</th><th>状态</th><th>待确认回补</th></tr></thead><tbody>${{(shortLotLifecycle.open_lots||[]).map(x=>`<tr><td>${{v(x.open_order_id)}}</td><td>${{v(x.runtime_id)}}</td><td>${{v(x.symbol)}}</td><td>${{v(x.filled_quantity)}}</td><td>${{v(x.remaining_quantity)}}</td><td>${{v(x.covered_quantity)}}</td><td>${{v(x.lifecycle_status)}}</td><td>${{v(x.pending_cover_order_count)}}</td></tr>`).join('')}}</tbody></table>`);
</script></main></body></html>"""


def run_dashboard(config: dict[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    payload = build_dashboard(config, generated_at=generated_at)
    outputs = config["outputs"]
    json_path = _resolve(outputs["json"])
    html_path = _resolve(outputs["html"])
    _write_json(json_path, payload)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(_render_html(payload), encoding="utf-8")
    return payload
