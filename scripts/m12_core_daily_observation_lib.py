#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_BASE_DIR = M10_DIR / "m12_read_only_pipeline"
M12_2_DIR = M12_BASE_DIR / "m12_2_daily_observation"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_core_strategy_daily_observation.json"
TIER_A_STRATEGY_IDS = ("M10-PA-001", "M10-PA-002", "M10-PA-012")
VISUAL_CONDITIONAL_IDS = ("M10-PA-008", "M10-PA-009")
FORBIDDEN_KEYS = {"order", "order_id", "fill", "fill_price", "position", "cash", "pnl", "profit_loss"}
FORBIDDEN_TEXT = ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true", "live_execution=true")


@dataclass(frozen=True, slots=True)
class DailyObservationConfig:
    title: str
    run_id: str
    feed_manifest_path: Path
    feed_ledger_path: Path
    observation_queue_path: Path
    paper_gate_candidate_path: Path
    backtest_spec_dir: Path
    output_dir: Path
    paper_simulated_only: bool
    broker_connection: bool
    real_orders: bool
    live_execution: bool


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def load_daily_observation_config(path: str | Path = DEFAULT_CONFIG_PATH) -> DailyObservationConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    return DailyObservationConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_2_core_strategy_daily_observation"),
        feed_manifest_path=resolve_repo_path(payload["feed_manifest_path"]),
        feed_ledger_path=resolve_repo_path(payload["feed_ledger_path"]),
        observation_queue_path=resolve_repo_path(payload["observation_queue_path"]),
        paper_gate_candidate_path=resolve_repo_path(payload["paper_gate_candidate_path"]),
        backtest_spec_dir=resolve_repo_path(payload["backtest_spec_dir"]),
        output_dir=resolve_repo_path(payload["output_dir"]),
        paper_simulated_only=bool(payload.get("paper_simulated_only", True)),
        broker_connection=bool(payload.get("broker_connection", False)),
        real_orders=bool(payload.get("real_orders", False)),
        live_execution=bool(payload.get("live_execution", False)),
    )


def run_m12_core_daily_observation(config: DailyObservationConfig, *, generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    validate_config_boundaries(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    feed_manifest = load_json(config.feed_manifest_path)
    feed_rows = load_jsonl(config.feed_ledger_path)
    queue = load_json(config.observation_queue_path)
    paper_gate = load_json(config.paper_gate_candidate_path)
    tier_a_queue = build_tier_a_queue(queue, paper_gate)
    specs = load_specs_for_queue(config, tier_a_queue)

    validate_feed_manifest(feed_manifest)
    validate_feed_rows(feed_rows)
    events = build_daily_observation_events(
        generated_at=generated_at,
        feed_ledger_ref=project_path(config.feed_ledger_path),
        feed_rows=feed_rows,
        tier_a_queue=tier_a_queue,
        specs=specs,
    )
    events.sort(key=event_sort_key)
    for event in events:
        validate_observation_event(event)

    status_matrix = build_status_matrix(
        config=config,
        generated_at=generated_at,
        feed_manifest=feed_manifest,
        tier_a_queue=tier_a_queue,
        events=events,
    )
    write_jsonl(config.output_dir / "m12_2_observation_events.jsonl", events)
    write_events_csv(config.output_dir / "m12_2_observation_events.csv", events)
    write_json(config.output_dir / "m12_2_strategy_status_matrix.json", status_matrix)
    (config.output_dir / "m12_2_daily_observation_report.md").write_text(build_daily_report(status_matrix), encoding="utf-8")
    assert_no_forbidden_text(config.output_dir)
    return status_matrix


def validate_config_boundaries(config: DailyObservationConfig) -> None:
    if not config.paper_simulated_only:
        raise ValueError("M12.2 requires paper_simulated_only=true")
    if config.broker_connection or config.real_orders or config.live_execution:
        raise ValueError("M12.2 must keep broker_connection, real_orders, and live_execution disabled")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_feed_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("stage") != "M12.1.longbridge_readonly_feed":
        raise ValueError("M12.2 must consume the M12.1 feed manifest")
    if manifest.get("strategy_scope") != list(TIER_A_STRATEGY_IDS):
        raise ValueError(f"M12.1 feed scope must stay Tier A only: {manifest.get('strategy_scope')}")
    if manifest.get("broker_connection") or manifest.get("real_orders") or manifest.get("live_execution"):
        raise ValueError("M12.1 feed manifest boundary drift")
    if manifest.get("deferred_count", 0) != 0:
        raise ValueError("M12.2 does not fabricate observations when M12.1 feed has deferred inputs")


def validate_feed_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if row.get("stage") != "M12.1.longbridge_readonly_feed":
            raise ValueError("Feed row stage drift")
        if row.get("eligible_strategy_ids") != list(TIER_A_STRATEGY_IDS):
            raise ValueError(f"Feed row strategy scope drift: {row.get('eligible_strategy_ids')}")
        if row.get("paper_simulated_only") is not True:
            raise ValueError("Feed row must be paper_simulated_only")
        if row.get("broker_connection") or row.get("real_orders") or row.get("live_execution"):
            raise ValueError("Feed row boundary drift")
        forbidden = find_forbidden_keys(row)
        if forbidden:
            raise ValueError(f"Feed row contains forbidden execution/account keys: {sorted(forbidden)}")


def build_tier_a_queue(queue: dict[str, Any], paper_gate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidate_groups = paper_gate.get("candidate_groups", {})
    tier_a_ids = tuple(candidate_groups.get("tier_a_core_after_read_only_observation", ()))
    if tier_a_ids != TIER_A_STRATEGY_IDS:
        raise ValueError(f"Unexpected M11 Tier A queue: {tier_a_ids}")

    primary_by_id = {item["strategy_id"]: item for item in queue.get("primary_observation_queue", [])}
    missing = [strategy_id for strategy_id in TIER_A_STRATEGY_IDS if strategy_id not in primary_by_id]
    if missing:
        raise ValueError(f"M10.13 primary queue missing Tier A ids: {missing}")
    visual_overlap = set(VISUAL_CONDITIONAL_IDS) & set(TIER_A_STRATEGY_IDS)
    if visual_overlap:
        raise ValueError(f"Visual conditional ids cannot enter Tier A: {sorted(visual_overlap)}")

    tier_a_queue: dict[str, dict[str, Any]] = {}
    for strategy_id in TIER_A_STRATEGY_IDS:
        item = primary_by_id[strategy_id]
        if item.get("requires_visual_review_context"):
            raise ValueError(f"Tier A strategy unexpectedly requires visual review: {strategy_id}")
        tier_a_queue[strategy_id] = item
    return tier_a_queue


def load_specs_for_queue(config: DailyObservationConfig, tier_a_queue: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for strategy_id, queue_item in tier_a_queue.items():
        path = config.backtest_spec_dir / f"{strategy_id}.json"
        spec = load_json(path)
        if spec.get("strategy_id") != strategy_id:
            raise ValueError(f"Spec id mismatch for {strategy_id}")
        for timeframe in queue_item.get("timeframes", []):
            if timeframe not in spec.get("timeframes", []):
                raise ValueError(f"{strategy_id} queue timeframe not in frozen spec: {timeframe}")
        specs[strategy_id] = spec
    return specs


def build_daily_observation_events(
    *,
    generated_at: str,
    feed_ledger_ref: str,
    feed_rows: list[dict[str, Any]],
    tier_a_queue: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_timeframe: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in feed_rows:
        rows_by_timeframe[row["timeframe"]].append(row)

    events: list[dict[str, Any]] = []
    for strategy_id, queue_item in tier_a_queue.items():
        spec = specs[strategy_id]
        for timeframe in queue_item["timeframes"]:
            for feed_row in rows_by_timeframe.get(timeframe, []):
                events.append(
                    build_skip_event(
                        generated_at=generated_at,
                        feed_ledger_ref=feed_ledger_ref,
                        feed_row=feed_row,
                        queue_item=queue_item,
                        spec=spec,
                    )
                )
    return events


def build_skip_event(
    *,
    generated_at: str,
    feed_ledger_ref: str,
    feed_row: dict[str, Any],
    queue_item: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    strategy_id = queue_item["strategy_id"]
    code = skip_code_for(strategy_id)
    return {
        "schema_version": "m12.daily-observation-event.v1",
        "stage": "M12.2.core_strategy_daily_observation",
        "generated_at": generated_at,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "strategy_id": strategy_id,
        "strategy_title": queue_item["title"],
        "symbol": feed_row["symbol"],
        "market": feed_row["market"],
        "timeframe": feed_row["timeframe"],
        "bar_timestamp": feed_row["bar_timestamp"],
        "event_or_skip": {
            "kind": "skip_no_trade",
            "code": code,
            "notes": "M12.2 records bar-close input only; full strategy trigger validation requires a context window and is not fabricated from one bar.",
        },
        "hypothetical_trade": {
            "direction": "none",
            "entry_price": None,
            "stop_price": None,
            "target_price": None,
        },
        "source_refs": compact_source_refs(spec),
        "spec_ref": project_path(M10_DIR / "backtest_specs" / f"{strategy_id}.json"),
        "data_source": {
            "provider": feed_row.get("lineage", {}).get("provider", "longbridge"),
            "lineage": "readonly_kline_poll",
            "timeframe_source": feed_ledger_ref,
            "feed_stage": feed_row["stage"],
            "observation_semantics": feed_row["observation_semantics"],
        },
        "review_status": "continue_observation",
        "pause_conditions": [],
    }


def skip_code_for(strategy_id: str) -> str:
    if strategy_id == "M10-PA-001":
        return "m12_2_context_window_required_second_entry"
    if strategy_id == "M10-PA-002":
        return "m12_2_context_window_required_breakout_follow_through"
    if strategy_id == "M10-PA-012":
        return "m12_2_opening_range_window_required"
    raise ValueError(f"Unsupported M12.2 strategy id: {strategy_id}")


def validate_observation_event(event: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "stage",
        "generated_at",
        "paper_simulated_only",
        "broker_connection",
        "real_orders",
        "live_execution",
        "strategy_id",
        "strategy_title",
        "symbol",
        "market",
        "timeframe",
        "bar_timestamp",
        "event_or_skip",
        "hypothetical_trade",
        "source_refs",
        "spec_ref",
        "data_source",
        "review_status",
        "pause_conditions",
    }
    missing = required - set(event)
    if missing:
        raise ValueError(f"M12.2 event missing fields: {sorted(missing)}")
    extras = set(event) - required
    if extras:
        raise ValueError(f"M12.2 event has unsupported fields: {sorted(extras)}")
    if event["strategy_id"] not in TIER_A_STRATEGY_IDS:
        raise ValueError(f"M12.2 event contains non-Tier-A strategy: {event['strategy_id']}")
    if event["strategy_id"] in VISUAL_CONDITIONAL_IDS:
        raise ValueError("M12.2 event cannot include visual conditional strategy")
    if event["paper_simulated_only"] is not True:
        raise ValueError("M12.2 event must be paper_simulated_only")
    if event["broker_connection"] or event["real_orders"] or event["live_execution"]:
        raise ValueError("M12.2 event boundary drift")
    if event["event_or_skip"]["kind"] not in {"candidate_event", "skip_no_trade"}:
        raise ValueError("Unexpected event_or_skip kind")
    if event["hypothetical_trade"]["direction"] not in {"long", "short", "none"}:
        raise ValueError("Unexpected hypothetical direction")
    if not event["source_refs"]:
        raise ValueError("M12.2 event requires source refs")
    forbidden = find_forbidden_keys(event)
    if forbidden:
        raise ValueError(f"M12.2 event contains forbidden execution/account keys: {sorted(forbidden)}")


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


def build_status_matrix(
    *,
    config: DailyObservationConfig,
    generated_at: str,
    feed_manifest: dict[str, Any],
    tier_a_queue: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    kind_counts = Counter(event["event_or_skip"]["kind"] for event in events)
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_strategy[event["strategy_id"]].append(event)
    strategy_statuses = []
    for strategy_id, queue_item in tier_a_queue.items():
        rows = by_strategy[strategy_id]
        row_counts = Counter(row["event_or_skip"]["kind"] for row in rows)
        strategy_statuses.append(
            {
                "strategy_id": strategy_id,
                "title": queue_item["title"],
                "timeframes": queue_item["timeframes"],
                "symbols": queue_item["symbols"],
                "event_count": len(rows),
                "candidate_event_count": row_counts["candidate_event"],
                "skip_no_trade_count": row_counts["skip_no_trade"],
                "review_status": "continue_observation",
                "requires_visual_review_context": False,
                "m11_gate_evidence_now": False,
                "notes": "M12.2 validates daily read-only observation flow; one-bar feed rows are not treated as completed strategy triggers.",
            }
        )
    return {
        "schema_version": "m12.daily-observation-status-matrix.v1",
        "stage": "M12.2.core_strategy_daily_observation",
        "generated_at": generated_at,
        "run_id": config.run_id,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "profitability_claim_allowed": False,
        "input_refs": {
            "feed_manifest": project_path(config.feed_manifest_path),
            "feed_ledger": project_path(config.feed_ledger_path),
            "observation_queue": project_path(config.observation_queue_path),
            "paper_gate_candidates": project_path(config.paper_gate_candidate_path),
        },
        "feed_snapshot": {
            "ledger_row_count": feed_manifest.get("ledger_row_count", 0),
            "deferred_count": feed_manifest.get("deferred_count", 0),
            "symbols": feed_manifest.get("symbols", []),
            "timeframes": feed_manifest.get("timeframes", []),
            "auth_status": feed_manifest.get("auth_status", "unknown"),
        },
        "tier_a_strategy_ids": list(TIER_A_STRATEGY_IDS),
        "excluded_from_auto_observation": {
            "visual_conditional": list(VISUAL_CONDITIONAL_IDS),
            "definition_fix": ["M10-PA-004", "M10-PA-005", "M10-PA-007"],
            "watchlist_or_non_positive": ["M10-PA-003", "M10-PA-011", "M10-PA-013"],
            "supporting_or_research": ["M10-PA-006", "M10-PA-010", "M10-PA-014", "M10-PA-015", "M10-PA-016"],
        },
        "event_count": len(events),
        "candidate_event_count": kind_counts["candidate_event"],
        "skip_no_trade_count": kind_counts["skip_no_trade"],
        "pause_condition_hits": [],
        "strategy_statuses": strategy_statuses,
        "boundary_note": "M12.2 produces read-only observation records only; no paper trading approval, broker connection, orders, or live execution is created.",
    }


def build_daily_report(status_matrix: dict[str, Any]) -> str:
    rows = [
        "| strategy | timeframes | events | candidates | skips | review |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in status_matrix["strategy_statuses"]:
        rows.append(
            f"| {item['strategy_id']} | {' / '.join(item['timeframes'])} | {item['event_count']} | "
            f"{item['candidate_event_count']} | {item['skip_no_trade_count']} | `{item['review_status']}` |"
        )
    return "\n".join(
        [
            "# M12.2 Core Strategy Daily Observation",
            "",
            "## Summary",
            "",
            f"- feed rows consumed: `{status_matrix['feed_snapshot']['ledger_row_count']}`",
            f"- observation rows written: `{status_matrix['event_count']}`",
            f"- candidate events: `{status_matrix['candidate_event_count']}`",
            f"- skip / no-trade rows: `{status_matrix['skip_no_trade_count']}`",
            "- 当前仅把 M12.1 只读 K 线输入转成每日观察 ledger，不从单根 bar 编造完整策略触发。",
            "- M11 paper gate remains closed.",
            "",
            "## Strategy Status",
            "",
            *rows,
            "",
            "## Boundary",
            "",
            "- broker_connection=false",
            "- real_orders=false",
            "- live_execution=false",
            "- paper_trading_approval=false",
            "",
        ]
    )


def write_events_csv(path: Path, events: list[dict[str, Any]]) -> None:
    fieldnames = [
        "strategy_id",
        "strategy_title",
        "symbol",
        "market",
        "timeframe",
        "bar_timestamp",
        "event_kind",
        "event_code",
        "review_status",
        "direction",
        "entry_price",
        "stop_price",
        "target_price",
        "spec_ref",
        "source_ref_count",
        "data_provider",
        "lineage",
        "pause_condition_count",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    "strategy_id": event["strategy_id"],
                    "strategy_title": event["strategy_title"],
                    "symbol": event["symbol"],
                    "market": event["market"],
                    "timeframe": event["timeframe"],
                    "bar_timestamp": event["bar_timestamp"],
                    "event_kind": event["event_or_skip"]["kind"],
                    "event_code": event["event_or_skip"]["code"],
                    "review_status": event["review_status"],
                    "direction": event["hypothetical_trade"]["direction"],
                    "entry_price": event["hypothetical_trade"]["entry_price"],
                    "stop_price": event["hypothetical_trade"]["stop_price"],
                    "target_price": event["hypothetical_trade"]["target_price"],
                    "spec_ref": event["spec_ref"],
                    "source_ref_count": len(event["source_refs"]),
                    "data_provider": event["data_source"]["provider"],
                    "lineage": event["data_source"]["lineage"],
                    "pause_condition_count": len(event["pause_conditions"]),
                }
            )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def event_sort_key(event: dict[str, Any]) -> tuple[str, str, str, str]:
    return (event["strategy_id"], event["timeframe"], event["symbol"], event["bar_timestamp"])


def find_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                found.add(key)
            found.update(find_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(find_forbidden_keys(child))
    return found


def assert_no_forbidden_text(output_dir: Path) -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in output_dir.glob("m12_2_*") if path.is_file())
    lowered = combined.lower()
    for forbidden in FORBIDDEN_TEXT:
        if forbidden.lower() in lowered:
            raise ValueError(f"M12.2 output contains forbidden text: {forbidden}")


def project_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)
