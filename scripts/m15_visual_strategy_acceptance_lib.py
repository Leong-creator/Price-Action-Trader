#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from scripts.m15_visual_strategy_shadow_lib import (
    DEFAULT_CONFIG_PATH,
    RUNTIME_IDS,
    STRATEGIES,
    atomic_write_json,
    empty_state,
    evaluate_bar,
    load_bars,
    load_config,
    new_stream_state,
    normalize_bar,
    resolve_path,
    stream_key,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "m15.visual-strategy-acceptance.v1"
POSITIVE_FLAGS = {
    "PA004": "boundary_failure",
    "PA007": "reverse_confirmation",
    "PA008": "reversal_confirmation",
}
NEGATIVE_FLAGS = {
    "PA004": "boundary_breach",
    "PA007": "trap_level_breach",
    "PA008": "trend_break",
}
BOUNDARY_FLAGS = {
    "PA004": "second_push",
    "PA007": "second_leg",
    "PA008": "second_test",
}
CASE_LIMIT_KEYS = {
    "positive": "positive_examples",
    "negative": "negative_examples",
    "boundary": "boundary_examples",
}


@dataclass(frozen=True, slots=True)
class AcceptanceConfig:
    shadow_config_path: Path = DEFAULT_CONFIG_PATH
    summary_path: Path = ROOT / "reports" / "m15_visual_strategy_shadow" / "run_summary.json"
    state_path: Path = ROOT / "reports" / "m15_visual_strategy_shadow" / "state.json"
    audit_path: Path = ROOT / "reports" / "m15_visual_strategy_shadow" / "audit_events.jsonl"
    realtime_shadow_ledger_path: Path | None = None
    session_daily_bars_path: Path | None = None
    output_path: Path = ROOT / "reports" / "m15_visual_strategy_shadow" / "acceptance_evidence.json"
    expected_symbol_count: int = 300
    expected_bars_per_symbol: int = 60
    segmented_chunk_size: int = 37
    negative_horizon_bars: int = 3
    realtime_shadow_sessions: int = 0
    positive_examples: int = 10
    negative_examples: int = 10
    boundary_examples: int = 5


@dataclass(frozen=True, slots=True)
class ReplayResult:
    events: list[dict[str, Any]]
    emitted_event_ids: list[str]
    watermarks: dict[str, str]
    stream_count: int
    accepted_bar_count: int
    input_bar_count: int
    prefix_checked_bar_count: int


def load_acceptance_config(path: str | Path) -> AcceptanceConfig:
    payload = json.loads(resolve_path(path).read_text(encoding="utf-8"))
    if payload.get("stage") not in (None, "M15.visual_strategy_acceptance"):
        raise ValueError("visual strategy acceptance stage drift")
    boundaries = payload.get("hard_boundaries", {})
    forbidden = [
        key
        for key in ("order_generation", "broker_connection", "real_orders", "live_execution")
        if boundaries.get(key) is not False
    ]
    if forbidden:
        raise ValueError(f"visual acceptance hard boundaries must be explicitly false: {forbidden}")
    limits = payload.get("example_limits", {})
    proofs = payload.get("proofs", {})
    outputs = payload["outputs"]
    inputs = payload["inputs"]
    return AcceptanceConfig(
        shadow_config_path=resolve_path(inputs.get("shadow_config", DEFAULT_CONFIG_PATH)),
        summary_path=resolve_path(inputs["shadow_run_summary"]),
        state_path=resolve_path(inputs["shadow_state"]),
        audit_path=resolve_path(inputs["shadow_audit_jsonl"]),
        realtime_shadow_ledger_path=resolve_path(inputs["realtime_shadow_ledger"])
        if inputs.get("realtime_shadow_ledger")
        else None,
        session_daily_bars_path=resolve_path(inputs["session_daily_bars"])
        if inputs.get("session_daily_bars")
        else None,
        output_path=resolve_path(outputs["acceptance_json"]),
        expected_symbol_count=int(proofs.get("expected_symbol_count", 300)),
        expected_bars_per_symbol=int(proofs.get("expected_bars_per_symbol", 60)),
        segmented_chunk_size=int(proofs.get("segmented_chunk_size", 37)),
        negative_horizon_bars=int(proofs.get("negative_horizon_bars", 3)),
        realtime_shadow_sessions=int(proofs.get("realtime_shadow_sessions", 0)),
        positive_examples=int(limits.get("positive_examples", 10)),
        negative_examples=int(limits.get("negative_examples", 10)),
        boundary_examples=int(limits.get("boundary_examples", 5)),
    )


def generate_acceptance_evidence(
    config: AcceptanceConfig,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    observed_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    shadow_config = load_config(config.shadow_config_path)
    historical_bars = [normalize_bar(row) for row in load_bars(shadow_config.input_path)]
    session_bars = (
        [normalize_bar(row) for row in _load_jsonl(config.session_daily_bars_path)]
        if config.session_daily_bars_path and config.session_daily_bars_path.exists()
        else []
    )
    session_dates = {_market_date(row) for row in session_bars}
    bars = sorted(
        [row for row in historical_bars if _market_date(row) not in session_dates] + session_bars,
        key=lambda row: (row["event_time"], stream_key(row)),
    )
    summary = _load_json(config.summary_path)
    state = _load_json(config.state_path)
    audit_rows = _load_jsonl(config.audit_path)
    realtime_shadow_rows = (
        _load_jsonl(config.realtime_shadow_ledger_path)
        if config.realtime_shadow_ledger_path and config.realtime_shadow_ledger_path.exists()
        else []
    )
    realtime_shadow_sessions = _count_completed_shadow_sessions(
        realtime_shadow_rows,
        expected_symbol_count=config.expected_symbol_count,
    )

    batch = _replay_events(shadow_config, bars, observed_at)
    segmented = _replay_events(shadow_config, bars, observed_at, chunk_size=config.segmented_chunk_size)
    prefix = _replay_events(shadow_config, bars, observed_at, chunk_size=1, prefix_reference=batch.events)

    audit_matches = _events_equal(audit_rows, batch.events)
    state_matches = _state_matches(state, batch)
    summary_matches = _summary_matches(summary, batch, config.expected_symbol_count)
    historical_counts: dict[str, int] = {}
    for row in bars:
        key = stream_key(row)
        historical_counts[key] = historical_counts.get(key, 0) + 1
    historical_symbol_count = len(historical_counts)
    historical_bar_count = len(bars)
    expected_bar_count = config.expected_symbol_count * config.expected_bars_per_symbol
    expected_audit_event_count = expected_bar_count * len(STRATEGIES)
    historical_replay_ok = (
        historical_symbol_count == config.expected_symbol_count
        and historical_bar_count == expected_bar_count
        and len(audit_rows) == expected_audit_event_count
        and set(historical_counts.values()) == {config.expected_bars_per_symbol}
    )
    all_audit_no_future = all(row.get("uses_future_data") is False for row in audit_rows)
    restart_parity_ok = _events_equal(batch.events, segmented.events) and batch.watermarks == segmented.watermarks
    no_future_ok = audit_matches and prefix.prefix_checked_bar_count == len(bars) and all_audit_no_future

    bars_by_stream = _group_bars_by_stream(bars)
    audit_by_strategy_stream = _group_audit_by_strategy_stream(audit_rows)
    candidate_pools = _build_candidate_pools(
        audit_by_strategy_stream=audit_by_strategy_stream,
        bars_by_stream=bars_by_stream,
        negative_horizon_bars=config.negative_horizon_bars,
    )

    required_limits = {
        "positive": config.positive_examples,
        "negative": config.negative_examples,
        "boundary": config.boundary_examples,
    }
    replay_proofs = {
        "historical_replay_symbol_count": {
            "passed": historical_replay_ok,
            "observed": historical_symbol_count,
            "expected": config.expected_symbol_count,
            "observed_bar_count": historical_bar_count,
            "expected_bar_count": expected_bar_count,
            "expected_bars_per_symbol": config.expected_bars_per_symbol,
            "observed_bars_per_symbol_values": sorted(set(historical_counts.values())),
            "observed_audit_event_count": len(audit_rows),
            "expected_audit_event_count": expected_audit_event_count,
            "summary_stream_count": int(summary.get("stream_count", -1)),
            "state_stream_count": len(state.get("streams", {})),
        },
        "audit_matches_replay": {
            "passed": audit_matches,
            "audit_event_count": len(audit_rows),
            "replayed_event_count": len(batch.events),
        },
        "summary_matches_replay": {
            "passed": summary_matches,
            "accepted_bar_count": int(summary.get("accepted_bar_count", -1)),
            "replayed_accepted_bar_count": batch.accepted_bar_count,
            "audit_event_count": int(summary.get("audit_event_count", -1)),
            "replayed_audit_event_count": len(batch.events),
        },
        "state_matches_replay": {
            "passed": state_matches,
            "state_stream_count": len(state.get("streams", {})),
            "replayed_stream_count": batch.stream_count,
        },
        "no_future_data": {
            "passed": no_future_ok,
            "audit_uses_future_data_false": all_audit_no_future,
            "prefix_checked_bar_count": prefix.prefix_checked_bar_count,
            "expected_prefix_checked_bar_count": len(bars),
        },
        "restart_parity": {
            "passed": restart_parity_ok,
            "segmented_chunk_size": config.segmented_chunk_size,
            "batch_event_count": len(batch.events),
            "segmented_event_count": len(segmented.events),
        },
    }

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": observed_at,
        "stage": "M15.visual_strategy_acceptance",
        "mode": "read_only_shadow_acceptance",
        "hard_boundaries": {
            "order_generation": False,
            "broker_connection": False,
            "real_orders": False,
            "live_execution": False,
        },
        "source_artifacts": {
            "shadow_config_path": str(config.shadow_config_path),
            "shadow_run_summary": str(config.summary_path),
            "shadow_state": str(config.state_path),
            "shadow_audit_jsonl": str(config.audit_path),
            "daily_context_bars": str(shadow_config.input_path),
            "realtime_shadow_ledger": str(config.realtime_shadow_ledger_path) if config.realtime_shadow_ledger_path else "",
            "session_daily_bars": str(config.session_daily_bars_path) if config.session_daily_bars_path else "",
        },
        "realtime_shadow_ledger_summary": {
            "completed_unique_business_dates": realtime_shadow_sessions,
            "ledger_row_count": len(realtime_shadow_rows),
            "counting_rule": "count unique business_date where status=completed and session_complete=true",
            "source_modes": sorted({str(row.get('source_mode', '')) for row in realtime_shadow_rows if row.get('source_mode')}),
        },
        "replay_proofs": replay_proofs,
    }
    for strategy in STRATEGIES:
        strategy_pool = candidate_pools[strategy]
        selected = {
            case_type: _select_candidates(
                strategy_pool[case_type],
                required_limits[case_type],
            )
            for case_type in ("positive", "negative", "boundary")
        }
        covered_regimes = sorted(
            {
                regime
                for case_type in ("positive", "negative", "boundary")
                for candidate in strategy_pool[case_type]
                for regime in candidate["covered_regimes"]
            }
        )
        payload[strategy] = {
            "runtime_id": RUNTIME_IDS[strategy],
            "positive_examples": 0,
            "negative_examples": 0,
            "boundary_examples": 0,
            "historical_replay_symbol_count": historical_symbol_count,
            "historical_replay_bars_per_symbol": (
                config.expected_bars_per_symbol if historical_replay_ok else 0
            ),
            "historical_replay_bar_count": historical_bar_count,
            "historical_replay_audit_event_count": len(audit_rows),
            "covered_regimes": covered_regimes,
            "no_future_data": no_future_ok,
            "restart_parity": restart_parity_ok,
            "realtime_shadow_sessions": realtime_shadow_sessions,
            "example_count_basis": "human_review_passed_only",
            "reviewed_counts": {
                "positive_examples": 0,
                "negative_examples": 0,
                "boundary_examples": 0,
            },
            "human_review_passed_counts": {
                "positive_examples": 0,
                "negative_examples": 0,
                "boundary_examples": 0,
            },
            "machine_candidate_pool_counts": {
                "positive_examples": len(strategy_pool["positive"]),
                "negative_examples": len(strategy_pool["negative"]),
                "boundary_examples": len(strategy_pool["boundary"]),
            },
            "hard_boundaries": {
                "order_generation": False,
                "broker_connection": False,
                "real_orders": False,
                "live_execution": False,
            },
            "machine_proofs": {
                "historical_replay_symbol_count": replay_proofs["historical_replay_symbol_count"],
                "no_future_data": replay_proofs["no_future_data"],
                "restart_parity": replay_proofs["restart_parity"],
            },
            "candidate_examples": {
                "positive": selected["positive"],
                "negative": selected["negative"],
                "boundary": selected["boundary"],
            },
        }
    atomic_write_json(config.output_path, payload)
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} must contain JSON objects")
            rows.append(row)
    return rows


def _count_completed_shadow_sessions(
    rows: list[dict[str, Any]],
    *,
    expected_symbol_count: int,
) -> int:
    completed_dates: set[str] = set()
    for row in rows:
        business_date = str(row.get("business_date", "")).strip()
        if not business_date:
            continue
        if str(row.get("status", "")).strip() != "completed":
            continue
        if row.get("session_complete") is not True:
            continue
        if row.get("schema_version") != "m15.visual-strategy-shadow-session.v1":
            continue
        if row.get("mode") != "read_only_sdk_session_shadow":
            continue
        if row.get("source_mode") != "longbridge_sdk_rth_5m_aggregate":
            continue
        required = int(row.get("required_symbol_count") or 0)
        completed = int(row.get("complete_symbol_count") or 0)
        if required != expected_symbol_count or completed != required:
            continue
        completed_dates.add(business_date)
    return len(completed_dates)


def _replay_events(
    shadow_config: Any,
    bars: list[dict[str, Any]],
    generated_at: str,
    *,
    chunk_size: int | None = None,
    prefix_reference: list[dict[str, Any]] | None = None,
) -> ReplayResult:
    state = empty_state()
    events: list[dict[str, Any]] = []
    emitted_ids: list[str] = []
    accepted = 0
    prefix_checked = 0
    chunk = max(1, int(chunk_size or len(bars) or 1))
    for start in range(0, len(bars), chunk):
        for bar in bars[start : start + chunk]:
            key = stream_key(bar)
            stream = state["streams"].setdefault(key, new_stream_state(bar))
            history = list(stream.get("history", []))
            history.append(bar)
            history = history[-shadow_config.history_limit :]
            stream_events = evaluate_bar(shadow_config, bar, history, stream, generated_at)
            events.extend(stream_events)
            emitted_ids.extend(row["event_id"] for row in stream_events)
            stream["history"] = history
            stream["watermark_event_time"] = bar["event_time"]
            stream["last_bar_id"] = stream_events[0]["source_bar_id"]
            accepted += 1
            if prefix_reference is not None:
                expected_end = len(events)
                if not _events_equal(events[-len(STRATEGIES) :], prefix_reference[expected_end - len(STRATEGIES) : expected_end]):
                    break
                prefix_checked += 1
        else:
            continue
        break
    return ReplayResult(
        events=events,
        emitted_event_ids=emitted_ids,
        watermarks={key: row.get("watermark_event_time", "") for key, row in sorted(state["streams"].items())},
        stream_count=len(state["streams"]),
        accepted_bar_count=accepted,
        input_bar_count=len(bars),
        prefix_checked_bar_count=prefix_checked,
    )


def _events_equal(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    if len(left) != len(right):
        return False
    return [_event_signature(row) for row in left] == [_event_signature(row) for row in right]


def _event_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("event_id"),
        row.get("strategy_id"),
        row.get("runtime_id"),
        row.get("symbol"),
        row.get("market"),
        row.get("timeframe"),
        row.get("event_time"),
        json.dumps(row.get("conditions", {}), ensure_ascii=False, sort_keys=True),
        row.get("order_generation"),
        row.get("broker_connection"),
        row.get("real_orders"),
        row.get("live_execution"),
        row.get("uses_future_data"),
        row.get("backfilled"),
    )


def _state_matches(state: dict[str, Any], replay: ReplayResult) -> bool:
    streams = state.get("streams", {})
    if not isinstance(streams, dict):
        return False
    emitted = sorted(str(item) for item in state.get("emitted_event_ids", []))
    watermarks = {key: row.get("watermark_event_time", "") for key, row in sorted(streams.items())}
    return watermarks == replay.watermarks and emitted == sorted(replay.emitted_event_ids)


def _summary_matches(summary: dict[str, Any], replay: ReplayResult, expected_symbol_count: int) -> bool:
    boundaries_ok = (
        str(summary.get("mode", "")) == "read_only_shadow_audit"
        and summary.get("hard_boundaries", {}).get("order_generation") is False
        and summary.get("hard_boundaries", {}).get("broker_connection") is False
    )
    full_replay_summary = int(summary.get("input_bar_count", -1)) == replay.input_bar_count
    accepted = int(summary.get("accepted_bar_count", -1))
    incremental_summary = (
        accepted > 0
        and int(summary.get("input_bar_count", -1)) >= accepted
        and int(summary.get("audit_event_count", -1)) == accepted * len(STRATEGIES)
        and int(summary.get("stale_bar_count", -1)) == 0
    )
    return (
        boundaries_ok
        and int(summary.get("stream_count", -1)) == expected_symbol_count
        and (full_replay_summary or incremental_summary)
    )


def _group_bars_by_stream(bars: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in bars:
        grouped.setdefault(stream_key(row), []).append(row)
    return grouped


def _group_audit_by_strategy_stream(
    audit_rows: list[dict[str, Any]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {strategy: {} for strategy in STRATEGIES}
    for row in audit_rows:
        strategy = str(row.get("strategy_id"))
        key = stream_key(row)
        grouped.setdefault(strategy, {}).setdefault(key, []).append(row)
    return grouped


def _build_candidate_pools(
    *,
    audit_by_strategy_stream: dict[str, dict[str, list[dict[str, Any]]]],
    bars_by_stream: dict[str, list[dict[str, Any]]],
    negative_horizon_bars: int,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    pools = {strategy: {"positive": [], "negative": [], "boundary": []} for strategy in STRATEGIES}
    for strategy in STRATEGIES:
        positive_flag = POSITIVE_FLAGS[strategy]
        negative_flag = NEGATIVE_FLAGS[strategy]
        boundary_flag = BOUNDARY_FLAGS[strategy]
        for key, events in audit_by_strategy_stream.get(strategy, {}).items():
            ordered = sorted(events, key=lambda row: str(row.get("event_time", "")))
            index_by_bar_id = {row.get("source_bar_id"): idx for idx, row in enumerate(ordered)}
            bars = bars_by_stream.get(key, [])
            bar_lookup = {row_key(row): row for row in bars}
            for idx, row in enumerate(ordered):
                conditions = row.get("conditions", {})
                if conditions.get(positive_flag) is True:
                    pools[strategy]["positive"].append(
                        _build_candidate(
                            strategy=strategy,
                            case_type="positive",
                            event=row,
                            bars=bars,
                            bar_lookup=bar_lookup,
                            event_index=index_by_bar_id[row.get("source_bar_id")],
                            reason=f"{positive_flag} observed on replayed historical bar",
                        )
                    )
                if conditions.get(boundary_flag) is True and conditions.get(positive_flag) is not True:
                    pools[strategy]["boundary"].append(
                        _build_candidate(
                            strategy=strategy,
                            case_type="boundary",
                            event=row,
                            bars=bars,
                            bar_lookup=bar_lookup,
                            event_index=index_by_bar_id[row.get("source_bar_id")],
                            reason=f"{boundary_flag} observed without terminal confirmation on the same bar",
                        )
                    )
                if conditions.get(negative_flag) is True and conditions.get(positive_flag) is not True:
                    future = ordered[idx + 1 : idx + 1 + max(1, negative_horizon_bars)]
                    if not any(next_row.get("conditions", {}).get(positive_flag) is True for next_row in future):
                        pools[strategy]["negative"].append(
                            _build_candidate(
                                strategy=strategy,
                                case_type="negative",
                                event=row,
                                bars=bars,
                                bar_lookup=bar_lookup,
                                event_index=index_by_bar_id[row.get("source_bar_id")],
                                reason=f"{negative_flag} observed and no {positive_flag} arrived within {negative_horizon_bars} bars",
                            )
                        )
    return pools


def _build_candidate(
    *,
    strategy: str,
    case_type: str,
    event: dict[str, Any],
    bars: list[dict[str, Any]],
    bar_lookup: dict[str, dict[str, Any]],
    event_index: int,
    reason: str,
) -> dict[str, Any]:
    current = bar_lookup[row_key_from_event(event)]
    previous = bars[event_index - 1] if event_index > 0 else None
    next_bar = bars[event_index + 1] if event_index + 1 < len(bars) else None
    context_start = max(0, event_index - 24)
    context_end = min(len(bars), event_index + 4)
    context_bars = bars[context_start:context_end]
    covered_regimes = _classify_regimes(bars, event_index)
    return {
        "case_id": f"{RUNTIME_IDS[strategy]}-{case_type}-{event['symbol']}-{event['event_time'][:10]}-{event['source_bar_id'][:8]}",
        "case_type": case_type,
        "strategy_id": strategy,
        "runtime_id": RUNTIME_IDS[strategy],
        "symbol": event["symbol"],
        "market": event["market"],
        "timeframe": event["timeframe"],
        "event_time": event["event_time"],
        "source_bar_id": event["source_bar_id"],
        "candidate_status": "machine_generated_candidate",
        "manual_review_status": "pending_manual_review",
        "manually_reviewed": False,
        "manually_passed": False,
        "automatic_reason": reason,
        "covered_regimes": covered_regimes,
        "conditions": event["conditions"],
        "bar": current,
        "previous_bar": previous,
        "next_bar": next_bar,
        "context_bars": context_bars,
        "context_before_count": event_index - context_start,
        "context_after_count": max(0, context_end - event_index - 1),
    }


def _select_candidates(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_symbols: set[str] = set()
    covered: set[str] = set()
    for candidate in sorted(candidates, key=_candidate_sort_key):
        adds_regime = any(regime not in covered for regime in candidate["covered_regimes"])
        fresh_symbol = candidate["symbol"] not in used_symbols
        if adds_regime or fresh_symbol or len(selected) < min(limit, 3):
            selected.append(candidate)
            used_symbols.add(candidate["symbol"])
            covered.update(candidate["covered_regimes"])
        if len(selected) >= limit:
            return selected
    for candidate in sorted(candidates, key=_candidate_sort_key):
        marker = (candidate["source_bar_id"], candidate["case_type"])
        if any((row["source_bar_id"], row["case_type"]) == marker for row in selected):
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -len(candidate["covered_regimes"]),
        candidate["event_time"],
        candidate["symbol"],
        candidate["case_id"],
    )


def _classify_regimes(bars: list[dict[str, Any]], index: int) -> list[str]:
    current = bars[index]
    previous = bars[index - 1] if index > 0 else None
    window = bars[max(0, index - 19) : index + 1]
    closes = [_decimal(row["close"]) for row in window]
    highs = [_decimal(row["high"]) for row in window]
    lows = [_decimal(row["low"]) for row in window]
    volumes = [_decimal(row["volume"]) for row in window]
    regimes: list[str] = []
    if previous is not None:
        prev_close = _decimal(previous["close"])
        if prev_close > 0:
            gap = abs(_decimal(current["open"]) - prev_close) / prev_close
            if gap >= Decimal("0.02"):
                regimes.append("gap")
    if len(volumes) >= 6:
        baseline = median(volumes[:-1] or volumes)
        if baseline and volumes[-1] >= baseline * Decimal("1.8"):
            regimes.append("abnormal_volume")
    if closes:
        start = closes[0]
        end = closes[-1]
        net_move = abs(end - start)
        total_move = sum(abs(closes[pos] - closes[pos - 1]) for pos in range(1, len(closes)))
        if start > 0 and net_move / start >= Decimal("0.08") and (net_move > 0 and total_move / net_move <= Decimal("1.8")):
            regimes.append("strong_trend")
    if len(highs) >= 6:
        high = max(highs)
        low = min(lows)
        last_close = closes[-1]
        if last_close > 0 and (high - low) / last_close <= Decimal("0.06"):
            regimes.append("range")
    return sorted(set(regimes))


def row_key(row: dict[str, Any]) -> str:
    return "|".join(
        (
            str(row.get("market") or "US"),
            str(row.get("symbol", "")),
            str(row.get("timeframe", "")),
            str(row.get("event_time", "")),
        )
    )


def row_key_from_event(row: dict[str, Any]) -> str:
    return "|".join(
        (
            str(row.get("market") or "US"),
            str(row.get("symbol", "")),
            str(row.get("timeframe", "")),
            str(row.get("event_time", "")),
        )
    )


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _market_date(row: dict[str, Any]) -> str:
    return (
        datetime.fromisoformat(str(row["event_time"]).replace("Z", "+00:00"))
        .astimezone(ZoneInfo("America/New_York"))
        .date()
        .isoformat()
    )
