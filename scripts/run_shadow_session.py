#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest import run_backtest
from src.data import DataValidationError, NewsEvent, OhlcvRow, build_replay, load_news_events, load_ohlcv_csv
from src.execution import ExecutionRequest, PaperBrokerAdapter
from src.news import evaluate_news_context
from src.review import build_review_report
from src.risk import RiskConfig, SessionRiskState, evaluate_order_request
from src.strategy import Signal, generate_signals


Mode = Literal["shadow", "paper"]
SessionType = Literal["paper", "simulated"]

ALLOWED_MARKETS = frozenset({"US", "HK", "CN", "FX", "CRYPTO"})
ALLOWED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "1d"})
ALLOWED_SOURCE_TYPES = frozenset(
    {
        "local_curated",
        "local_export",
        "local_snapshot",
        "realtime_recorded",
    }
)
ALLOWED_APPROVED_FOR = frozenset(
    {
        "offline_replay",
        "m8d_history_validation",
        "m8d_shadow_paper",
        "research_only",
    }
)
ALLOWED_REGIME_TAGS = frozenset(
    {
        "trend_up",
        "trend_down",
        "range",
        "breakout",
        "reversal",
        "high_volatility",
        "low_volatility",
        "event_driven",
        "illiquid",
        "gap_heavy",
    }
)
DISCOVERY_DIRS = (
    ROOT / "tests" / "test_data" / "real_history_small",
    ROOT / "tests" / "reliability" / "real_history",
    ROOT / "data" / "real_history",
    ROOT / "data" / "realtime_recordings",
    ROOT / "local_data" / "real_history",
    ROOT / "local_data" / "realtime_recordings",
)
MANIFEST_FILENAME = "dataset.manifest.json"
SAMPLE_MANIFEST_PATH = (
    ROOT
    / "tests"
    / "test_data"
    / "real_history_small"
    / "sample_us_5m_recorded_session"
    / MANIFEST_FILENAME
)


@dataclass(frozen=True, slots=True)
class TimeRange:
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    manifest_path: Path
    dataset_name: str
    dataset_version: str
    source_type: str
    market: str
    symbol: str
    timeframe: str
    timezone: str
    time_range: TimeRange
    regime_tags: tuple[str, ...]
    origin: str
    approved_for: tuple[str, ...]
    limitations: tuple[str, ...]
    session_type: SessionType
    ohlcv_path: Path
    news_path: Path | None


class DatasetManifestError(ValueError):
    def __init__(self, manifest_path: Path, issues: list[str]) -> None:
        self.manifest_path = manifest_path
        self.issues = tuple(issues)
        super().__init__(f"{manifest_path}: {'; '.join(self.issues)}")


def discover_dataset_manifests() -> list[Path]:
    manifests: list[Path] = []
    for base in DISCOVERY_DIRS:
        if not base.exists():
            continue
        manifests.extend(path for path in base.rglob(MANIFEST_FILENAME) if path.is_file())
    return sorted(dict.fromkeys(manifests))


def build_deferred_result(
    reason: str,
    *,
    discovered_manifests: list[Path] | tuple[Path, ...] = (),
    requested_mode: Mode = "shadow",
) -> dict[str, Any]:
    return {
        "status": "deferred",
        "reason": reason,
        "mode": requested_mode,
        "boundary": "paper/simulated",
        "live_execution": False,
        "broker_connected": False,
        "discovered_manifests": [str(path) for path in discovered_manifests],
    }


def load_dataset_manifest(path: str | Path) -> DatasetManifest:
    manifest_path = Path(path).resolve()
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return validate_dataset_manifest(raw, manifest_path)


def validate_dataset_manifest(raw: dict[str, Any], manifest_path: Path) -> DatasetManifest:
    issues: list[str] = []

    dataset_name = _require_str(raw, "dataset_name", issues)
    dataset_version = _require_str(raw, "dataset_version", issues)
    source_type = _require_str(raw, "source_type", issues)
    market = _require_str(raw, "market", issues)
    symbol = _require_str(raw, "symbol", issues)
    timeframe = _require_str(raw, "timeframe", issues)
    timezone = _require_str(raw, "timezone", issues)
    origin = _require_str(raw, "origin", issues)
    session_type = _require_str(raw, "session_type", issues)
    approved_for = _require_list_of_strings(raw, "approved_for", issues)
    limitations = _require_list_of_strings(raw, "limitations", issues)
    regime_tags = _require_list_of_strings(raw, "regime_tags", issues)

    if market and market not in ALLOWED_MARKETS:
        issues.append(f"market must be one of {sorted(ALLOWED_MARKETS)}")
    if timeframe and timeframe not in ALLOWED_TIMEFRAMES:
        issues.append(f"timeframe must be one of {sorted(ALLOWED_TIMEFRAMES)}")
    if source_type and source_type not in ALLOWED_SOURCE_TYPES:
        issues.append(f"source_type must be one of {sorted(ALLOWED_SOURCE_TYPES)}")
    if session_type not in {"paper", "simulated"}:
        issues.append("session_type must be 'paper' or 'simulated'")
    if not approved_for:
        issues.append("approved_for must be a non-empty list")
    elif any(item not in ALLOWED_APPROVED_FOR for item in approved_for):
        issues.append(f"approved_for must be subset of {sorted(ALLOWED_APPROVED_FOR)}")
    if not regime_tags:
        issues.append("regime_tags must be a non-empty list")
    elif any(item not in ALLOWED_REGIME_TAGS for item in regime_tags):
        issues.append(f"regime_tags must be subset of {sorted(ALLOWED_REGIME_TAGS)}")

    try:
        ZoneInfo(timezone)
    except Exception:
        issues.append("timezone must be a valid IANA timezone")

    time_range = raw.get("time_range")
    if not isinstance(time_range, dict):
        issues.append("time_range must be an object with start/end")
        parsed_range = None
    else:
        start_raw = time_range.get("start")
        end_raw = time_range.get("end")
        parsed_range = _parse_time_range(start_raw, end_raw, issues)

    files_obj = raw.get("files")
    if not isinstance(files_obj, dict):
        issues.append("files must be an object with ohlcv/news paths")
        ohlcv_path = None
        news_path = None
    else:
        ohlcv_rel = files_obj.get("ohlcv")
        news_rel = files_obj.get("news")
        ohlcv_path = _resolve_data_path(manifest_path, ohlcv_rel, "ohlcv", issues)
        news_path = _resolve_optional_data_path(manifest_path, news_rel, "news", issues)

    if ohlcv_path is not None and ohlcv_path.suffix.lower() != ".csv":
        issues.append("files.ohlcv must point to a local CSV file")
    if news_path is not None and news_path.suffix.lower() != ".json":
        issues.append("files.news must point to a local JSON file")

    if issues:
        raise DatasetManifestError(manifest_path, issues)

    return DatasetManifest(
        manifest_path=manifest_path,
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        source_type=source_type,
        market=market,
        symbol=symbol,
        timeframe=timeframe,
        timezone=timezone,
        time_range=parsed_range,
        regime_tags=tuple(regime_tags),
        origin=origin,
        approved_for=tuple(approved_for),
        limitations=tuple(limitations),
        session_type=session_type,
        ohlcv_path=ohlcv_path,
        news_path=news_path,
    )


def run_shadow_session(
    manifest: DatasetManifest,
    *,
    mode: Mode = "shadow",
) -> dict[str, Any]:
    if "m8d_shadow_paper" not in manifest.approved_for and mode in {"shadow", "paper"}:
        raise DatasetManifestError(
            manifest.manifest_path,
            [f"manifest is not approved for mode={mode}; approved_for={manifest.approved_for}"],
        )

    bars = tuple(load_ohlcv_csv(manifest.ohlcv_path))
    news_events = tuple(load_news_events(manifest.news_path)) if manifest.news_path else ()
    replay = build_replay(bars, news_events)
    signals = generate_signals(replay)
    backtest_report = run_backtest(bars, signals)
    signal_timestamps = _index_signal_timestamps(bars, signals)
    trade_by_signal = {trade.signal_id: trade for trade in backtest_report.trades}

    adapter = PaperBrokerAdapter()
    session_key = bars[0].timestamp.date().isoformat() if bars else manifest.time_range.start.date().isoformat()
    session_state = SessionRiskState(session_key=session_key)
    positions = ()
    seen_signal_ids = frozenset()
    news_decisions = []
    execution_logs = []
    execution_status_counts = {"filled": 0, "blocked": 0, "closed": 0, "error": 0}

    for signal in signals:
        reference_timestamp = signal_timestamps.get(signal.signal_id)
        if reference_timestamp is None:
            continue
        news_decision = evaluate_news_context(
            signal,
            news_events,
            reference_timestamp=reference_timestamp,
        )
        news_decisions.append(news_decision)

        trade = trade_by_signal.get(signal.signal_id)
        if trade is None:
            continue

        request = ExecutionRequest(
            signal=signal,
            requested_at=trade.entry_timestamp,
            session_key=session_key,
            entry_price=trade.entry_price,
            stop_price=trade.stop_price,
            target_price=trade.target_price,
            proposed_quantity=Decimal("1"),
        )
        risk_decision = evaluate_order_request(
            signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=tuple(_to_position_snapshot(position) for position in positions),
            session_state=session_state,
            config=_default_risk_config(),
            market_is_open=True,
        )
        execution_result = adapter.submit(
            request,
            risk_decision=risk_decision,
            session_state=session_state,
            positions=positions,
            seen_signal_ids=seen_signal_ids,
        )
        execution_logs.extend(execution_result.logs)
        execution_status_counts[execution_result.status] += 1
        session_state = execution_result.session_state
        positions = execution_result.resulting_positions
        seen_signal_ids = execution_result.resulting_seen_signal_ids

        if execution_result.fill_event is not None:
            close_result = adapter.close_position(
                position_id=execution_result.fill_event.position_id,
                exit_price=trade.exit_price,
                closed_at=trade.exit_timestamp,
                positions=positions,
                session_state=session_state,
                config=_default_risk_config(),
                session_key=session_key,
                exit_reason=trade.exit_reason,
            )
            execution_logs.extend(close_result.logs)
            execution_status_counts[close_result.status] += 1
            session_state = close_result.session_state
            positions = close_result.resulting_positions

    review_report = build_review_report(
        signals,
        news_decisions,
        backtest_report,
        execution_logs=tuple(execution_logs),
    )
    generated_at = datetime.now(UTC)
    return {
        "status": "completed",
        "generated_at": generated_at.isoformat(),
        "mode": mode,
        "boundary": "paper/simulated",
        "live_execution": False,
        "broker_connected": False,
        "dataset": {
            "dataset_name": manifest.dataset_name,
            "dataset_version": manifest.dataset_version,
            "source_type": manifest.source_type,
            "market": manifest.market,
            "symbol": manifest.symbol,
            "timeframe": manifest.timeframe,
            "timezone": manifest.timezone,
            "regime_tags": list(manifest.regime_tags),
            "origin": manifest.origin,
            "approved_for": list(manifest.approved_for),
            "limitations": list(manifest.limitations),
            "manifest_path": str(manifest.manifest_path),
            "ohlcv_path": str(manifest.ohlcv_path),
            "news_path": str(manifest.news_path) if manifest.news_path else None,
            "time_range": {
                "start": manifest.time_range.start.isoformat(),
                "end": manifest.time_range.end.isoformat(),
            },
        },
        "session": {
            "session_type": manifest.session_type,
            "input_mode": "recorded_replay" if manifest.source_type == "realtime_recorded" else "historical_replay",
            "read_only_input": True,
            "simulated_output": True,
            "requested_mode": mode,
            "market_is_open_assumption": "historical/offline replay only",
        },
        "summary": {
            "bar_count": len(bars),
            "news_event_count": len(news_events),
            "signal_count": len(signals),
            "trade_count": backtest_report.stats.trade_count,
            "closed_trade_count": backtest_report.stats.closed_trade_count,
            "warnings": list(backtest_report.warnings),
            "assumptions": list(backtest_report.assumptions),
            "execution_status_counts": execution_status_counts,
        },
        "review_traceability": {
            "source_refs": list(review_report.source_refs),
            "items": [_serialize_review_item(item) for item in review_report.items],
        },
    }


def write_report(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _serialize_review_item(item: Any) -> dict[str, Any]:
    return _to_jsonable(item)


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def _default_risk_config() -> RiskConfig:
    return RiskConfig(
        max_risk_per_order=Decimal("150"),
        max_total_exposure=Decimal("1000"),
        max_symbol_exposure_ratio=Decimal("1"),
        max_daily_loss=Decimal("200"),
        max_consecutive_losses=2,
        allow_manual_resume_from_loss_streak=True,
    )


def _to_position_snapshot(position: Any) -> Any:
    from src.risk import PositionSnapshot

    return PositionSnapshot(
        symbol=position.symbol,
        quantity=position.quantity,
        market_value=position.market_value,
    )


def _index_signal_timestamps(
    bars: tuple[OhlcvRow, ...],
    signals: tuple[Signal, ...],
) -> dict[str, datetime]:
    lookup: dict[str, datetime] = {}
    for signal in signals:
        for bar in bars:
            if _build_signal_id(signal.setup_type, bar, signal.direction) == signal.signal_id:
                lookup[signal.signal_id] = bar.timestamp
                break
    return lookup


def _build_signal_id(setup_type: str, bar: OhlcvRow, direction: str) -> str:
    payload = "|".join(
        [
            setup_type,
            direction,
            bar.symbol,
            bar.market,
            bar.timeframe,
            bar.timestamp.isoformat(),
        ]
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def _parse_time_range(start_raw: Any, end_raw: Any, issues: list[str]) -> TimeRange | None:
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        issues.append("time_range.start and time_range.end must be ISO-8601 strings")
        return None
    try:
        start = datetime.fromisoformat(start_raw)
        end = datetime.fromisoformat(end_raw)
    except ValueError:
        issues.append("time_range values must be valid ISO-8601 timestamps")
        return None
    if start > end:
        issues.append("time_range.start must be earlier than or equal to time_range.end")
        return None
    return TimeRange(start=start, end=end)


def _resolve_data_path(
    manifest_path: Path,
    raw_value: Any,
    field_name: str,
    issues: list[str],
) -> Path | None:
    if not isinstance(raw_value, str) or not raw_value.strip():
        issues.append(f"files.{field_name} must be a non-empty relative path")
        return None
    path = (manifest_path.parent / raw_value).resolve()
    if not path.exists():
        issues.append(f"files.{field_name} points to a missing file: {path}")
        return None
    return path


def _resolve_optional_data_path(
    manifest_path: Path,
    raw_value: Any,
    field_name: str,
    issues: list[str],
) -> Path | None:
    if raw_value in (None, ""):
        return None
    return _resolve_data_path(manifest_path, raw_value, field_name, issues)


def _require_str(raw: dict[str, Any], key: str, issues: list[str]) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{key} must be a non-empty string")
        return ""
    return value.strip()


def _require_list_of_strings(raw: dict[str, Any], key: str, issues: list[str]) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        issues.append(f"{key} must be a non-empty list of strings")
        return []
    return [item.strip() for item in value]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run M8 shadow/paper baseline validation on local recorded or historical datasets only."
    )
    parser.add_argument("--manifest", type=Path, help="Path to dataset.manifest.json")
    parser.add_argument(
        "--sample-manifest",
        action="store_true",
        help="Use the bundled sample manifest under tests/test_data/real_history_small.",
    )
    parser.add_argument(
        "--mode",
        choices=["shadow", "paper"],
        default="shadow",
        help="Requested session mode. Output remains paper/simulated in all cases.",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        help="Optional JSON output path for the generated local report.",
    )
    parser.add_argument(
        "--list-manifests",
        action="store_true",
        help="List discoverable local dataset manifests and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    manifests = discover_dataset_manifests()

    if args.list_manifests:
        print(json.dumps({"discovered_manifests": [str(path) for path in manifests]}, ensure_ascii=False, indent=2))
        return 0

    manifest_path: Path | None
    if args.sample_manifest:
        manifest_path = SAMPLE_MANIFEST_PATH
    else:
        manifest_path = args.manifest

    if manifest_path is None:
        payload = build_deferred_result(
            "manifest not provided; use --manifest or --sample-manifest",
            discovered_manifests=manifests,
            requested_mode=args.mode,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    try:
        manifest = load_dataset_manifest(manifest_path)
        payload = run_shadow_session(manifest, mode=args.mode)
    except (DatasetManifestError, DataValidationError, ValueError, OSError) as exc:
        payload = build_deferred_result(
            str(exc),
            discovered_manifests=manifests,
            requested_mode=args.mode,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    if args.report_output is not None:
        write_report(payload, args.report_output)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
