#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_historical_pilot_lib import (
    CandidateEvent,
    DataWindow,
    DatasetRecord,
    dataset_record_to_json,
    detect_events,
    load_dataset_for_timeframe,
    project_path,
    resolve_repo_path,
    write_json,
    write_jsonl,
)


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m10_read_only_observation_replay.json"
OBSERVATION_STRATEGY_IDS = ("M10-PA-001", "M10-PA-002", "M10-PA-005", "M10-PA-012")
OBSERVATION_TIMEFRAMES = {
    "M10-PA-001": ("1d", "1h", "15m", "5m"),
    "M10-PA-002": ("1d", "1h", "15m", "5m"),
    "M10-PA-005": ("1d", "1h", "15m", "5m"),
    "M10-PA-012": ("15m", "5m"),
}
ALLOWED_REVIEW_STATUS = (
    "needs_definition_fix",
    "needs_visual_review",
    "continue_testing",
    "reject_for_now",
    "continue_observation",
)
BOUNDARY_KEYS = ("paper_simulated_only", "broker_connection", "real_orders", "live_execution")
FORBIDDEN_STRINGS = ("PA-SC-", "SF-", "retain", "promote", "live-ready")
QUANT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class ObservationConfig:
    title: str
    run_id: str
    symbols: tuple[str, ...]
    market: str
    timezone: str
    data_windows: dict[str, DataWindow]
    cache_roots: tuple[Path, ...]
    observation_queue_path: Path
    observation_schema_path: Path
    spec_index_path: Path
    output_dir: Path
    paper_simulated_only: bool
    recorded_replay_only: bool


def load_observation_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ObservationConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    data_windows = {
        timeframe: DataWindow(
            start=date.fromisoformat(window["start"]),
            end=date.fromisoformat(window["end"]),
            derive_from=window.get("derive_from"),
        )
        for timeframe, window in payload["data_windows"].items()
    }
    return ObservationConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m10_6_replay"),
        symbols=tuple(payload["symbols"]),
        market=payload.get("market", "US"),
        timezone=payload.get("timezone", "America/New_York"),
        data_windows=data_windows,
        cache_roots=tuple(resolve_repo_path(path) for path in payload["cache_roots"]),
        observation_queue_path=resolve_repo_path(payload["observation_queue_path"]),
        observation_schema_path=resolve_repo_path(payload["observation_schema_path"]),
        spec_index_path=resolve_repo_path(payload["spec_index_path"]),
        output_dir=resolve_repo_path(payload["output_dir"]),
        paper_simulated_only=bool(payload.get("paper_simulated_only", True)),
        recorded_replay_only=bool(payload.get("recorded_replay_only", True)),
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_observation_queue(path: Path) -> dict[str, Any]:
    queue = load_json(path)
    errors = validate_observation_queue(queue)
    if errors:
        raise ValueError("; ".join(errors))
    return queue


def validate_observation_queue(queue: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    candidate_ids = [item.get("strategy_id") for item in queue.get("candidate_queue", [])]
    if candidate_ids != list(OBSERVATION_STRATEGY_IDS):
        errors.append(f"M10.6 queue must use exact M10.5 Wave A ids: {candidate_ids}")
    excluded = set()
    for ids in queue.get("excluded_strategy_ids", {}).values():
        excluded.update(ids)
    if set(candidate_ids) & excluded:
        errors.append("Observation queue overlaps excluded strategy ids")
    for item in queue.get("candidate_queue", []):
        strategy_id = item.get("strategy_id", "")
        expected = list(OBSERVATION_TIMEFRAMES.get(strategy_id, ()))
        if item.get("timeframes") != expected:
            errors.append(f"{strategy_id} timeframes drifted: {item.get('timeframes')}")
    boundaries = queue.get("boundaries", {})
    if not boundaries.get("paper_simulated_only", False):
        errors.append("M10.6 requires paper_simulated_only queue boundary")
    if boundaries.get("broker_connection") or boundaries.get("real_orders") or boundaries.get("live_execution"):
        errors.append("M10.6 queue must not permit broker, orders, or live execution")
    return errors


def load_specs_for_queue(queue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for item in queue["candidate_queue"]:
        spec = load_json(resolve_repo_path(item["spec_ref"]))
        strategy_id = item["strategy_id"]
        if spec["strategy_id"] != strategy_id:
            raise ValueError(f"Spec id mismatch for {strategy_id}")
        if spec.get("timeframes") != item["timeframes"]:
            raise ValueError(f"Spec timeframe mismatch for {strategy_id}")
        specs[strategy_id] = spec
    if set(specs) != set(OBSERVATION_STRATEGY_IDS):
        raise ValueError(f"M10.6 loaded unexpected specs: {sorted(specs)}")
    return specs


def run_m10_read_only_observation(config: ObservationConfig) -> dict[str, Any]:
    queue = load_observation_queue(config.observation_queue_path)
    schema = load_json(config.observation_schema_path)
    specs = load_specs_for_queue(queue)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    required_timeframes = sorted({timeframe for item in queue["candidate_queue"] for timeframe in item["timeframes"]})
    data_by_key: dict[tuple[str, str], list[Any]] = {}
    records_by_key: dict[tuple[str, str], DatasetRecord] = {}
    inventory: list[DatasetRecord] = []
    for symbol in config.symbols:
        for timeframe in required_timeframes:
            bars, record = load_dataset_for_timeframe(symbol=symbol, timeframe=timeframe, config=config)
            data_by_key[(symbol, timeframe)] = bars
            records_by_key[(symbol, timeframe)] = record
            inventory.append(record)

    deferred_records = [record for record in inventory if record.status != "available"]
    ledger_rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for item in queue["candidate_queue"]:
        spec = specs[item["strategy_id"]]
        for timeframe in item["timeframes"]:
            quality_flag = quality_flag_for(item, timeframe)
            result_counter: Counter[str] = Counter()
            symbols_with_data = 0
            symbols_deferred = 0
            for symbol in config.symbols:
                record = records_by_key[(symbol, timeframe)]
                bars = data_by_key[(symbol, timeframe)]
                if not bars:
                    symbols_deferred += 1
                    continue
                symbols_with_data += 1
                events, skips = detect_events(spec, bars)
                for event in events:
                    row = build_candidate_observation_event(
                        event=event,
                        spec=spec,
                        spec_ref=item["spec_ref"],
                        record=record,
                        quality_flag=quality_flag,
                        schema=schema,
                    )
                    validate_observation_event(row, schema)
                    ledger_rows.append(row)
                    result_counter["candidate_event"] += 1
                for skip in skips:
                    if not skip.get("timestamp"):
                        result_counter["skip_without_timestamp"] += 1
                        continue
                    row = build_skip_observation_event(
                        skip=skip,
                        spec=spec,
                        spec_ref=item["spec_ref"],
                        record=record,
                        quality_flag=quality_flag,
                        schema=schema,
                    )
                    validate_observation_event(row, schema)
                    ledger_rows.append(row)
                    result_counter["skip_no_trade"] += 1
            results.append(
                {
                    "strategy_id": item["strategy_id"],
                    "timeframe": timeframe,
                    "quality_flag": quality_flag,
                    "symbols_with_data": symbols_with_data,
                    "symbols_deferred": symbols_deferred,
                    "candidate_event_count": result_counter["candidate_event"],
                    "skip_no_trade_count": result_counter["skip_no_trade"],
                    "skip_without_timestamp_count": result_counter["skip_without_timestamp"],
                    "review_status": review_status_for_quality_flag(quality_flag),
                }
            )

    ledger_rows.sort(key=ledger_sort_key)
    manifest = build_input_manifest(config, queue, inventory)
    deferred = build_deferred_inputs(config, deferred_records)
    summary = build_summary(config, queue, manifest, deferred, results, ledger_rows)
    write_json(config.output_dir / "m10_6_input_manifest.json", manifest)
    write_jsonl(config.output_dir / "m10_6_observation_ledger.jsonl", ledger_rows)
    write_json(config.output_dir / "m10_6_deferred_inputs.json", deferred)
    write_json(config.output_dir / "m10_6_observation_summary.json", summary)
    (config.output_dir / "m10_6_observation_report.md").write_text(build_report(summary), encoding="utf-8")
    return summary


def build_candidate_observation_event(
    *,
    event: CandidateEvent,
    spec: dict[str, Any],
    spec_ref: str,
    record: DatasetRecord,
    quality_flag: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": schema["properties"]["schema_version"]["const"],
        "stage": schema["properties"]["stage"]["const"],
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "strategy_id": event.strategy_id,
        "symbol": event.symbol,
        "timeframe": event.timeframe,
        "bar_timestamp": event.signal_timestamp.isoformat(),
        "event_or_skip": {
            "kind": "candidate_event",
            "code": event.setup_notes,
            "notes": f"recorded_replay_bar_close; quality_flag={quality_flag}",
        },
        "hypothetical_trade": {
            "direction": event.direction,
            "entry_price": str(event.entry_price),
            "stop_price": str(event.stop_price),
            "target_price": str(event.target_price),
        },
        "source_refs": compact_source_refs(spec),
        "spec_ref": project_path(resolve_repo_path(spec_ref)),
        "data_source": data_source_payload(record),
        "review_status": review_status_for_quality_flag(quality_flag),
    }


def build_skip_observation_event(
    *,
    skip: dict[str, Any],
    spec: dict[str, Any],
    spec_ref: str,
    record: DatasetRecord,
    quality_flag: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": schema["properties"]["schema_version"]["const"],
        "stage": schema["properties"]["stage"]["const"],
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "strategy_id": skip["strategy_id"],
        "symbol": skip["symbol"],
        "timeframe": skip["timeframe"],
        "bar_timestamp": skip["timestamp"],
        "event_or_skip": {
            "kind": "skip_no_trade",
            "code": skip["skip_code"],
            "notes": f"{skip['reason']} quality_flag={quality_flag}",
        },
        "hypothetical_trade": {
            "direction": "none",
            "entry_price": None,
            "stop_price": None,
            "target_price": None,
        },
        "source_refs": compact_source_refs(spec),
        "spec_ref": project_path(resolve_repo_path(spec_ref)),
        "data_source": data_source_payload(record),
        "review_status": review_status_for_quality_flag(quality_flag),
    }


def validate_observation_event(event: dict[str, Any], schema: dict[str, Any]) -> None:
    required = set(schema["required"])
    missing = required - set(event)
    if missing:
        raise ValueError(f"Observation event missing required fields: {sorted(missing)}")
    extras = set(event) - set(schema["properties"])
    if extras:
        raise ValueError(f"Observation event has unsupported fields: {sorted(extras)}")
    for key in BOUNDARY_KEYS:
        expected = schema["properties"][key]["const"]
        if event[key] is not expected:
            raise ValueError(f"Observation event boundary drift: {key}={event[key]}")
    if event["schema_version"] != schema["properties"]["schema_version"]["const"]:
        raise ValueError("Observation event schema version drift")
    if event["stage"] != schema["properties"]["stage"]["const"]:
        raise ValueError("Observation event stage drift")
    if event["strategy_id"] not in schema["properties"]["strategy_id"]["enum"]:
        raise ValueError(f"Unexpected strategy id: {event['strategy_id']}")
    if event["timeframe"] not in schema["timeframe_constraints"][event["strategy_id"]]:
        raise ValueError(f"Unexpected timeframe for {event['strategy_id']}: {event['timeframe']}")
    if event["review_status"] not in ALLOWED_REVIEW_STATUS:
        raise ValueError(f"Unexpected review status: {event['review_status']}")
    if event["event_or_skip"]["kind"] not in {"candidate_event", "skip_no_trade"}:
        raise ValueError("Unexpected event_or_skip kind")
    if event["hypothetical_trade"]["direction"] not in {"long", "short", "none"}:
        raise ValueError("Unexpected hypothetical direction")
    if not event["source_refs"] or not all(isinstance(ref, str) and ref for ref in event["source_refs"]):
        raise ValueError("Observation event source_refs must be non-empty strings")
    if event["data_source"]["lineage"] not in schema["properties"]["data_source"]["properties"]["lineage"]["enum"]:
        raise ValueError(f"Unexpected data lineage: {event['data_source']['lineage']}")


def compact_source_refs(spec: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for item in spec.get("source_refs", []):
        source_ref = item.get("source_ref") if isinstance(item, dict) else str(item)
        if source_ref and source_ref not in refs:
            refs.append(source_ref)
        if len(refs) >= 3:
            break
    if not refs and spec.get("source_ledger_ref"):
        refs.append(str(spec["source_ledger_ref"]))
    return refs


def data_source_payload(record: DatasetRecord) -> dict[str, str]:
    if record.csv_path:
        timeframe_source = project_path(record.csv_path)
    else:
        timeframe_source = record.deferred_reason or "observation_input_deferred"
    return {
        "provider": record.source,
        "lineage": record.lineage,
        "timeframe_source": timeframe_source,
    }


def quality_flag_for(queue_item: dict[str, Any], timeframe: str) -> str:
    for result in queue_item.get("m10_4_results", []):
        if result["timeframe"] == timeframe:
            return result["quality_flag"]
    return "normal_density_review"


def review_status_for_quality_flag(quality_flag: str) -> str:
    if quality_flag == "definition_breadth_review":
        return "needs_definition_fix"
    return "continue_observation"


def ledger_sort_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        row["strategy_id"],
        row["timeframe"],
        row["symbol"],
        row["bar_timestamp"],
        row["event_or_skip"]["kind"],
    )


def build_input_manifest(config: ObservationConfig, queue: dict[str, Any], inventory: list[DatasetRecord]) -> dict[str, Any]:
    return {
        "schema_version": "m10.6.read-only-observation-input-manifest.v1",
        "run_id": config.run_id,
        "title": config.title,
        "recorded_replay_only": config.recorded_replay_only,
        "paper_simulated_only": config.paper_simulated_only,
        "broker_connection": False,
        "live_execution": False,
        "real_orders": False,
        "symbols": list(config.symbols),
        "data_windows": {
            timeframe: {
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
                "derive_from": window.derive_from,
            }
            for timeframe, window in config.data_windows.items()
        },
        "cache_roots": [path.as_posix() for path in config.cache_roots],
        "observation_queue_ref": project_path(config.observation_queue_path),
        "observation_schema_ref": project_path(config.observation_schema_path),
        "queue_strategy_ids": [item["strategy_id"] for item in queue["candidate_queue"]],
        "dataset_records": [dataset_record_to_json(record) for record in inventory],
        "available_dataset_count": sum(1 for record in inventory if record.status == "available"),
        "deferred_dataset_count": sum(1 for record in inventory if record.status != "available"),
    }


def build_deferred_inputs(config: ObservationConfig, deferred_records: list[DatasetRecord]) -> dict[str, Any]:
    return {
        "schema_version": "m10.6.deferred-inputs.v1",
        "run_id": config.run_id,
        "deferred_count": len(deferred_records),
        "rule": "Missing local input creates deferred records only; no synthetic observation events are generated.",
        "records": [dataset_record_to_json(record) for record in deferred_records],
    }


def build_summary(
    config: ObservationConfig,
    queue: dict[str, Any],
    manifest: dict[str, Any],
    deferred: dict[str, Any],
    results: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    kind_counts = Counter(row["event_or_skip"]["kind"] for row in ledger_rows)
    lineage_counts = Counter(record["lineage"] for record in manifest["dataset_records"])
    return {
        "schema_version": "m10.6.read-only-observation-summary.v1",
        "run_id": config.run_id,
        "title": config.title,
        "recorded_replay_only": True,
        "paper_simulated_only": True,
        "broker_connection": False,
        "live_execution": False,
        "real_orders": False,
        "strategy_status_upgrade_allowed": False,
        "profitability_claim_allowed": False,
        "m11_paper_gate": "closed",
        "queue_strategy_ids": [item["strategy_id"] for item in queue["candidate_queue"]],
        "event_count": len(ledger_rows),
        "candidate_event_count": kind_counts["candidate_event"],
        "skip_no_trade_count": kind_counts["skip_no_trade"],
        "deferred_input_count": deferred["deferred_count"],
        "lineage_counts": dict(sorted(lineage_counts.items())),
        "strategy_timeframe_results": results,
        "allowed_review_status": list(ALLOWED_REVIEW_STATUS),
        "boundary_note": "Recorded replay ledger validates input and schema flow only; no strategy effectiveness claim is made.",
    }


def build_report(summary: dict[str, Any]) -> str:
    rows = [
        "| strategy | timeframe | candidates | skips | deferred symbols | review status |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in summary["strategy_timeframe_results"]:
        rows.append(
            f"| {item['strategy_id']} | {item['timeframe']} | {item['candidate_event_count']} | "
            f"{item['skip_no_trade_count']} | {item['symbols_deferred']} | `{item['review_status']}` |"
        )
    return "\n".join(
        [
            "# M10.6 Read-only Observation Recorded Replay",
            "",
            "## Summary",
            "",
            "- Recorded replay only.",
            "- Uses local cached OHLCV input.",
            "- The ledger validates input, schema, and bar-close observation flow.",
            "- It does not prove strategy effectiveness.",
            "- M11 paper gate remains closed.",
            "",
            "## Counts",
            "",
            f"- event_count: `{summary['event_count']}`",
            f"- candidate_event_count: `{summary['candidate_event_count']}`",
            f"- skip_no_trade_count: `{summary['skip_no_trade_count']}`",
            f"- deferred_input_count: `{summary['deferred_input_count']}`",
            "",
            "## Strategy Timeframes",
            "",
            *rows,
            "",
        ]
    )


def decimal_to_density(value: Decimal) -> str:
    return str(value.quantize(QUANT, rounding=ROUND_HALF_UP))
