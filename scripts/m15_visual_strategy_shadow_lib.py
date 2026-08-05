#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_visual_strategy_shadow.json"
SCHEMA_VERSION = "m15.visual-strategy-shadow.v1"
STATE_SCHEMA_VERSION = "m15.visual-strategy-shadow-state.v1"
DETECTOR_VERSION = "m15.visual-strategy-shadow.detector.v1"
STRATEGIES = ("PA004", "PA007", "PA008")
RUNTIME_IDS = {
    "PA004": "M10-PA-004-long-1d",
    "PA007": "M10-PA-007-1d",
    "PA008": "M10-PA-008-1d",
}
ALLOWED_CONTRACT_STAGES = {"contract-draft-v1", "shadow-v1"}


@dataclass(frozen=True, slots=True)
class ShadowConfig:
    input_path: Path
    state_path: Path
    audit_path: Path
    summary_path: Path
    acceptance_path: Path | None = None
    contract_stage: str = "shadow-v1"
    channel_lookback: int = 12
    channel_tolerance: Decimal = Decimal("0.08")
    trend_short_window: int = 3
    trend_long_window: int = 6
    history_limit: int = 64


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ShadowConfig:
    payload = json.loads(resolve_path(path).read_text(encoding="utf-8"))
    contract = payload.get("contract", {})
    boundaries = payload.get("hard_boundaries", {})
    stage = str(contract.get("stage", "shadow-v1"))
    if stage not in ALLOWED_CONTRACT_STAGES:
        raise ValueError("visual strategy contract stage must remain contract-draft-v1 or shadow-v1")
    forbidden_true = [
        key
        for key in ("broker_connection", "real_orders", "order_generation", "live_execution")
        if boundaries.get(key) is not False
    ]
    if forbidden_true:
        raise ValueError(f"shadow hard boundaries must be explicitly false: {forbidden_true}")
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    state = payload["state"]
    detector = payload.get("detector", {})
    config = ShadowConfig(
        input_path=resolve_path(inputs["bars"]),
        state_path=resolve_path(state["path"]),
        audit_path=resolve_path(outputs["audit_jsonl"]),
        summary_path=resolve_path(outputs["run_summary"]),
        acceptance_path=resolve_path(outputs["acceptance_json"]) if outputs.get("acceptance_json") else None,
        contract_stage=stage,
        channel_lookback=int(detector.get("channel_lookback", 12)),
        channel_tolerance=_decimal(detector.get("channel_tolerance", "0.08")),
        trend_short_window=int(detector.get("trend_short_window", 3)),
        trend_long_window=int(detector.get("trend_long_window", 6)),
        history_limit=int(state.get("history_limit", 64)),
    )
    if config.channel_lookback < 4 or config.trend_short_window < 2:
        raise ValueError("detector windows are too short")
    if config.trend_long_window <= config.trend_short_window:
        raise ValueError("trend_long_window must exceed trend_short_window")
    if config.history_limit < max(config.channel_lookback + 2, config.trend_long_window + 2):
        raise ValueError("history_limit is smaller than the detector lookback")
    return config


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "detector_version": DETECTOR_VERSION,
        "detector_base": "M12.20.visual_detector_implementation",
        "streams": {},
        "emitted_event_ids": [],
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot restore visual shadow state: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("visual shadow state schema mismatch")
    if payload.get("detector_version") != DETECTOR_VERSION:
        raise ValueError("visual shadow detector version mismatch")
    if not isinstance(payload.get("streams"), dict):
        raise ValueError("visual shadow state streams must be an object")
    payload.setdefault("emitted_event_ids", [])
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def load_bars(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = []
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL bar at line {line_number}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"bar at line {line_number} must be an object")
                rows.append(row)
    return sorted(rows, key=lambda row: (str(row.get("event_time") or row.get("timestamp") or ""), stream_key(row)))


def run_visual_strategy_shadow(
    config: ShadowConfig,
    *,
    bars: Iterable[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    observed_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    state = load_state(config.state_path)
    existing_ids = load_existing_event_ids(config.audit_path)
    emitted_ids = set(str(item) for item in state.get("emitted_event_ids", [])) | existing_ids
    events: list[dict[str, Any]] = []
    accepted = stale = duplicates = 0

    source_rows = list(bars) if bars is not None else load_bars(config.input_path)
    normalized = sorted(
        (normalize_bar(row) for row in source_rows),
        key=lambda row: (row["event_time"], stream_key(row)),
    )
    for bar in normalized:
        key = stream_key(bar)
        stream = state["streams"].setdefault(key, new_stream_state(bar))
        watermark = str(stream.get("watermark_event_time") or "")
        if watermark and bar["event_time"] < watermark:
            stale += 1
            continue
        if watermark and bar["event_time"] == watermark:
            duplicates += 1
            continue

        history = list(stream.get("history", []))
        history.append(bar)
        history = history[-config.history_limit :]
        stream_events = evaluate_bar(config, bar, history, stream, observed_at)
        for event in stream_events:
            event_id = event["event_id"]
            if event_id in emitted_ids:
                duplicates += 1
                continue
            emitted_ids.add(event_id)
            events.append(event)
        stream["history"] = history
        stream["watermark_event_time"] = bar["event_time"]
        stream["last_bar_id"] = bar_id(bar)
        accepted += 1

    state["generated_at"] = observed_at
    state["contract_stage"] = config.contract_stage
    state["emitted_event_ids"] = sorted(emitted_ids)
    append_jsonl(config.audit_path, events)
    atomic_write_json(config.state_path, state)
    summary = {
        "schema_version": f"{SCHEMA_VERSION}.run-summary",
        "generated_at": observed_at,
        "contract_stage": config.contract_stage,
        "mode": "read_only_shadow_audit",
        "input_bar_count": len(normalized),
        "accepted_bar_count": accepted,
        "stale_bar_count": stale,
        "duplicate_bar_or_event_count": duplicates,
        "audit_event_count": len(events),
        "stream_count": len(state["streams"]),
        "watermarks": {key: row.get("watermark_event_time", "") for key, row in sorted(state["streams"].items())},
        "state_path": str(config.state_path),
        "audit_path": str(config.audit_path),
        "hard_boundaries": {
            "order_generation": False,
            "broker_connection": False,
            "real_orders": False,
            "live_execution": False,
            "future_data": False,
            "backfill": False,
        },
        "paper_promotion_acceptance": build_promotion_acceptance(config),
    }
    atomic_write_json(config.summary_path, summary)
    return summary


def evaluate_bar(
    config: ShadowConfig,
    bar: dict[str, Any],
    history: list[dict[str, Any]],
    stream: dict[str, Any],
    observed_at: str,
) -> list[dict[str, Any]]:
    conditions = {
        "PA004": evaluate_pa004(config, history, stream["strategies"]["PA004"]),
        "PA007": evaluate_pa007(history, stream["strategies"]["PA007"]),
        "PA008": evaluate_pa008(config, history, stream["strategies"]["PA008"]),
    }
    return [build_audit_event(config, strategy, bar, values, observed_at) for strategy, values in conditions.items()]


def evaluate_pa004(config: ShadowConfig, history: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    fields = false_fields("first_push", "second_push", "boundary_breach", "boundary_failure", "back_in_channel")
    prior = history[:-1]
    if len(prior) < config.channel_lookback:
        return finish(state, fields, "insufficient_history")
    window = prior[-config.channel_lookback :]
    high = max(_decimal(row["high"]) for row in window)
    low = min(_decimal(row["low"]) for row in window)
    width = high - low
    if width <= 0:
        return finish(state, fields, "invalid_channel")
    bar = history[-1]
    midpoint = (high + low) / 2
    tolerance = width * config.channel_tolerance
    phase = state.get("phase", "idle")
    direction = state.get("direction", "")
    lower_touch = _decimal(bar["low"]) <= low + tolerance
    upper_touch = _decimal(bar["high"]) >= high - tolerance
    if phase == "idle" and (lower_touch or upper_touch):
        direction = "long" if lower_touch else "short"
        fields["first_push"] = True
        phase = "first_push"
        state["retreat_seen"] = False
    elif phase == "first_push":
        touched = lower_touch if direction == "long" else upper_touch
        retreated = (
            _decimal(bar["close"]) > midpoint
            if direction == "long"
            else _decimal(bar["close"]) < midpoint
        )
        if not touched and retreated:
            state["retreat_seen"] = True
        if touched and state.get("retreat_seen"):
            fields["second_push"] = True
            phase = "second_push"
    elif phase == "second_push":
        breached = _decimal(bar["low"]) < low if direction == "long" else _decimal(bar["high"]) > high
        if breached:
            fields["boundary_breach"] = True
            phase = "outside"
            state["boundary_level"] = str(low if direction == "long" else high)
            inside = _decimal(bar["close"]) >= low if direction == "long" else _decimal(bar["close"]) <= high
            if inside:
                fields["boundary_failure"] = True
                phase = "failed"
    elif phase == "outside":
        level = _decimal(state.get("boundary_level"))
        if (_decimal(bar["close"]) >= level) if direction == "long" else (_decimal(bar["close"]) <= level):
            fields["boundary_failure"] = True
            phase = "failed"
    elif phase == "failed":
        if low <= _decimal(bar["close"]) <= high:
            fields["back_in_channel"] = True
            phase = "idle"
            state["retreat_seen"] = False
    state.update({"phase": phase, "direction": direction, "channel_high": str(high), "channel_low": str(low)})
    return finish(state, fields)


def evaluate_pa007(history: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    fields = false_fields("first_leg", "second_leg", "trap_level_breach", "failure", "reverse_confirmation")
    if len(history) < 3:
        return finish(state, fields, "insufficient_history")
    bar, previous, two_back = history[-1], history[-2], history[-3]
    phase = state.get("phase", "idle")
    direction = state.get("direction", "")
    down_leg = _decimal(bar["low"]) < _decimal(previous["low"]) < _decimal(two_back["low"])
    up_leg = _decimal(bar["high"]) > _decimal(previous["high"]) > _decimal(two_back["high"])
    if phase == "idle" and (down_leg or up_leg):
        direction = "down" if down_leg else "up"
        fields["first_leg"] = True
        phase = "first_leg"
        state["leg1_extreme"] = str(_decimal(bar["low"] if down_leg else bar["high"]))
        state["pullback_seen"] = False
    elif phase == "first_leg":
        pullback = (
            _decimal(bar["close"]) > _decimal(previous["close"])
            if direction == "down"
            else _decimal(bar["close"]) < _decimal(previous["close"])
        )
        state["pullback_seen"] = bool(state.get("pullback_seen") or pullback)
        resumed = (
            _decimal(bar["low"]) < _decimal(previous["low"])
            if direction == "down"
            else _decimal(bar["high"]) > _decimal(previous["high"])
        )
        if state["pullback_seen"] and resumed:
            fields["second_leg"] = True
            phase = "second_leg"
            state["trap_level"] = str(_decimal(state["leg1_extreme"]))
    elif phase == "second_leg":
        level = _decimal(state.get("trap_level"))
        breached = _decimal(bar["low"]) < level if direction == "down" else _decimal(bar["high"]) > level
        if breached:
            fields["trap_level_breach"] = True
            phase = "trap_breached"
            failed = _decimal(bar["close"]) > level if direction == "down" else _decimal(bar["close"]) < level
            if failed:
                fields["failure"] = True
                phase = "failed"
    elif phase == "trap_breached":
        level = _decimal(state.get("trap_level"))
        if (_decimal(bar["close"]) > level) if direction == "down" else (_decimal(bar["close"]) < level):
            fields["failure"] = True
            phase = "failed"
    elif phase == "failed":
        confirmed = (
            _decimal(bar["close"]) > _decimal(previous["high"])
            if direction == "down"
            else _decimal(bar["close"]) < _decimal(previous["low"])
        )
        if confirmed:
            fields["reverse_confirmation"] = True
            phase = "idle"
            state["pullback_seen"] = False
    state.update({"phase": phase, "direction": direction})
    return finish(state, fields)


def evaluate_pa008(config: ShadowConfig, history: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    fields = false_fields("trend", "trend_break", "second_test", "reversal_confirmation")
    if len(history) < config.trend_long_window:
        return finish(state, fields, "insufficient_history")
    closes = [_decimal(row["close"]) for row in history]
    short_ma = sum(closes[-config.trend_short_window :]) / config.trend_short_window
    long_ma = sum(closes[-config.trend_long_window :]) / config.trend_long_window
    bar, previous = history[-1], history[-2]
    phase = state.get("phase", "idle")
    direction = state.get("direction", "")
    uptrend = short_ma > long_ma and closes[-1] > closes[-2]
    downtrend = short_ma < long_ma and closes[-1] < closes[-2]
    if phase == "idle" and (uptrend or downtrend):
        direction = "up" if uptrend else "down"
        fields["trend"] = True
        phase = "trend"
    elif phase == "trend":
        broken = (
            closes[-1] < short_ma and _decimal(bar["low"]) < _decimal(previous["low"])
            if direction == "up"
            else closes[-1] > short_ma and _decimal(bar["high"]) > _decimal(previous["high"])
        )
        if broken:
            fields["trend_break"] = True
            phase = "broken"
            state["test_level"] = str(short_ma)
    elif phase == "broken":
        level = _decimal(state.get("test_level"))
        tested = (
            _decimal(bar["high"]) >= level and closes[-1] < level
            if direction == "up"
            else _decimal(bar["low"]) <= level and closes[-1] > level
        )
        if tested:
            fields["second_test"] = True
            phase = "tested"
    elif phase == "tested":
        confirmed = (
            closes[-1] < _decimal(previous["low"])
            if direction == "up"
            else closes[-1] > _decimal(previous["high"])
        )
        if confirmed:
            fields["reversal_confirmation"] = True
            phase = "idle"
    state.update({"phase": phase, "direction": direction, "short_ma": str(short_ma), "long_ma": str(long_ma)})
    return finish(state, fields)


def build_audit_event(
    config: ShadowConfig,
    strategy: str,
    bar: dict[str, Any],
    values: dict[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA_VERSION,
        "detector_version": DETECTOR_VERSION,
        "detector_base": "M12.20.visual_detector_implementation",
        "contract_stage": config.contract_stage,
        "mode": "read_only_shadow_audit",
        "strategy_id": strategy,
        "runtime_id": RUNTIME_IDS[strategy],
        "symbol": bar["symbol"],
        "market": bar["market"],
        "timeframe": bar["timeframe"],
        "event_time": bar["event_time"],
        "observed_at": observed_at,
        "source_bar_id": bar_id(bar),
        "conditions": values,
        "order_generation": False,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "uses_future_data": False,
        "backfilled": False,
    }
    raw = "|".join((DETECTOR_VERSION, strategy, bar_id(bar)))
    row["event_id"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return row


def build_promotion_acceptance(config: ShadowConfig) -> dict[str, Any]:
    required = {
        "positive_examples": 10,
        "negative_examples": 10,
        "boundary_examples": 5,
        "historical_replay_symbol_count": 300,
        "required_regimes": ["strong_trend", "range", "gap", "abnormal_volume"],
        "no_future_data": True,
        "restart_parity": True,
        "realtime_shadow_sessions": 1,
    }
    observed: dict[str, Any] = {}
    if config.acceptance_path and config.acceptance_path.exists():
        payload = json.loads(config.acceptance_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("visual shadow acceptance payload must be an object")
        observed = payload
    strategy_rows: dict[str, Any] = {}
    for strategy in STRATEGIES:
        row = observed.get(strategy, {}) if isinstance(observed.get(strategy), dict) else {}
        regimes = set(str(item) for item in row.get("covered_regimes", []))
        checks = {
            "positive_examples": int(row.get("positive_examples", 0)) >= required["positive_examples"],
            "negative_examples": int(row.get("negative_examples", 0)) >= required["negative_examples"],
            "boundary_examples": int(row.get("boundary_examples", 0)) >= required["boundary_examples"],
            "historical_replay_symbol_count": int(row.get("historical_replay_symbol_count", 0))
            >= required["historical_replay_symbol_count"],
            "required_regimes": set(required["required_regimes"]).issubset(regimes),
            "no_future_data": row.get("no_future_data") is True,
            "restart_parity": row.get("restart_parity") is True,
            "realtime_shadow_sessions": int(row.get("realtime_shadow_sessions", 0))
            >= required["realtime_shadow_sessions"],
        }
        strategy_rows[strategy] = {
            "runtime_id": RUNTIME_IDS[strategy],
            "required": required,
            "observed": row,
            "checks": checks,
            "ready_for_paper": all(checks.values()) and config.contract_stage == "shadow-v1",
        }
    return {
        "status": "ready" if all(row["ready_for_paper"] for row in strategy_rows.values()) else "blocked",
        "strategies": strategy_rows,
    }


def normalize_bar(row: dict[str, Any]) -> dict[str, Any]:
    event_time = str(row.get("event_time") or row.get("timestamp") or "")
    required = ("symbol", "timeframe", "open", "high", "low", "close")
    missing = [key for key in required if row.get(key) in (None, "")]
    if not event_time:
        missing.append("event_time")
    if missing:
        raise ValueError(f"bar missing required fields: {sorted(set(missing))}")
    try:
        parsed = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid event_time: {event_time}") from exc
    if parsed.tzinfo is None:
        raise ValueError("event_time must include a timezone")
    normalized = {
        "symbol": str(row["symbol"]),
        "market": str(row.get("market") or "US"),
        "timeframe": str(row["timeframe"]),
        "event_time": parsed.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "open": str(_decimal(row["open"])),
        "high": str(_decimal(row["high"])),
        "low": str(_decimal(row["low"])),
        "close": str(_decimal(row["close"])),
        "volume": str(_decimal(row.get("volume", "0"))),
    }
    if _decimal(normalized["low"]) > min(_decimal(normalized["open"]), _decimal(normalized["close"])):
        raise ValueError("bar low exceeds open or close")
    if _decimal(normalized["high"]) < max(_decimal(normalized["open"]), _decimal(normalized["close"])):
        raise ValueError("bar high is below open or close")
    return normalized


def new_stream_state(bar: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": bar["symbol"],
        "market": bar["market"],
        "timeframe": bar["timeframe"],
        "watermark_event_time": "",
        "last_bar_id": "",
        "history": [],
        "strategies": {strategy: {"phase": "idle", "direction": ""} for strategy in STRATEGIES},
    }


def false_fields(*names: str) -> dict[str, Any]:
    return {name: False for name in names}


def finish(state: dict[str, Any], fields: dict[str, Any], reason: str = "evaluated") -> dict[str, Any]:
    fields["evaluation"] = reason
    fields["phase"] = state.get("phase", "idle")
    fields["direction"] = state.get("direction", "")
    return fields


def stream_key(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(key, "")) for key in ("market", "symbol", "timeframe"))


def bar_id(bar: dict[str, Any]) -> str:
    identity_fields = ("market", "symbol", "timeframe", "event_time", "open", "high", "low", "close", "volume")
    raw = "|".join(str(bar.get(key, "")) for key in identity_fields)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def load_existing_event_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"cannot restore audit event ids from {path}") from exc
            if row.get("event_id"):
                ids.add(str(row["event_id"]))
    return ids


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _decimal(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc
    if not number.is_finite():
        raise ValueError(f"non-finite decimal value: {value}")
    return number


def config_as_dict(config: ShadowConfig) -> dict[str, Any]:
    payload = asdict(config)
    return {key: str(value) if isinstance(value, (Path, Decimal)) else value for key, value in payload.items()}
