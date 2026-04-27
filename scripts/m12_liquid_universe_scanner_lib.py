#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_5_DIR = M10_DIR / "scanner" / "m12_5_liquid_universe_scanner"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_liquid_universe_scanner.json"
TIER_A_STRATEGY_IDS = ("M10-PA-001", "M10-PA-002", "M10-PA-012")
VISUAL_OR_BLOCKED_IDS = (
    "M10-PA-003",
    "M10-PA-004",
    "M10-PA-005",
    "M10-PA-006",
    "M10-PA-007",
    "M10-PA-008",
    "M10-PA-009",
    "M10-PA-010",
    "M10-PA-011",
    "M10-PA-013",
    "M10-PA-014",
    "M10-PA-015",
    "M10-PA-016",
)
FORBIDDEN_TEXT = (
    "PA-SC-",
    "SF-",
    "live-ready",
    "broker_connection",
    "real_orders",
    "live_execution",
    "paper_trading_approval",
)
FORBIDDEN_CONFIG_KEYS = {"broker_connection", "real_orders", "live_execution", "paper_trading_approval"}
FORBIDDEN_KEYS = {"order", "order_id", "fill", "fill_price", "position", "cash", "pnl", "profit_loss"}
US_LIQUID_SEED_V1 = (
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "VTI",
    "VOO",
    "IVV",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLY",
    "XLI",
    "XLP",
    "XLU",
    "XLC",
    "XLB",
    "SMH",
    "SOXX",
    "TQQQ",
    "SQQQ",
    "GLD",
    "SLV",
    "USO",
    "TLT",
    "HYG",
    "LQD",
    "EEM",
    "EFA",
    "ARKK",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "GOOG",
    "META",
    "TSLA",
    "AVGO",
    "AMD",
    "INTC",
    "MU",
    "QCOM",
    "ORCL",
    "CRM",
    "ADBE",
    "NOW",
    "SNOW",
    "PLTR",
    "PANW",
    "CRWD",
    "NET",
    "DDOG",
    "MDB",
    "TEAM",
    "SHOP",
    "UBER",
    "ABNB",
    "NFLX",
    "DIS",
    "CMCSA",
    "WBD",
    "PARA",
    "T",
    "VZ",
    "TMUS",
    "COST",
    "WMT",
    "TGT",
    "HD",
    "LOW",
    "NKE",
    "SBUX",
    "MCD",
    "CMG",
    "YUM",
    "KO",
    "PEP",
    "MNST",
    "PG",
    "CL",
    "KMB",
    "EL",
    "LULU",
    "JPM",
    "BAC",
    "WFC",
    "C",
    "GS",
    "MS",
    "SCHW",
    "BLK",
    "AXP",
    "V",
    "MA",
    "PYPL",
    "COIN",
    "HOOD",
    "UNH",
    "LLY",
    "JNJ",
    "MRK",
    "PFE",
    "ABBV",
    "AMGN",
    "GILD",
    "BMY",
    "CVS",
    "HUM",
    "TMO",
    "ISRG",
    "BA",
    "CAT",
    "DE",
    "GE",
    "RTX",
    "LMT",
    "NOC",
    "HON",
    "UPS",
    "FDX",
    "XOM",
    "CVX",
    "COP",
    "SLB",
    "OXY",
    "F",
    "GM",
    "RIVN",
    "LCID",
    "BABA",
    "PDD",
    "JD",
    "BIDU",
    "NIO",
    "LI",
    "SE",
    "MELI",
    "ENPH",
    "FSLR",
    "MRVL",
    "ADI",
    "TXN",
    "AMAT",
    "LRCX",
    "KLAC",
    "TSM",
)


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    title: str
    run_id: str
    market: str
    universe_preset: str
    strategy_scope: tuple[str, ...]
    observation_queue_path: Path
    paper_gate_candidate_path: Path
    backtest_spec_dir: Path
    local_data_roots: tuple[Path, ...]
    max_universe_size: int
    max_live_request_symbols: int
    output_dir: Path


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    market: str
    timeframe: str
    timestamp: str
    timezone: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def load_scanner_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ScannerConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    forbidden_keys = FORBIDDEN_CONFIG_KEYS & set(payload)
    if forbidden_keys:
        raise ValueError(f"M12.5 scanner config must not contain execution boundary fields: {sorted(forbidden_keys)}")
    return ScannerConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_5_liquid_universe_scanner"),
        market=payload.get("market", "US"),
        universe_preset=payload.get("universe_preset", "us_liquid_seed_v1"),
        strategy_scope=tuple(payload.get("strategy_scope", TIER_A_STRATEGY_IDS)),
        observation_queue_path=resolve_repo_path(payload["observation_queue_path"]),
        paper_gate_candidate_path=resolve_repo_path(payload["paper_gate_candidate_path"]),
        backtest_spec_dir=resolve_repo_path(payload["backtest_spec_dir"]),
        local_data_roots=tuple(resolve_repo_path(item) for item in payload.get("local_data_roots", ["local_data"])),
        max_universe_size=int(payload.get("max_universe_size", 200)),
        max_live_request_symbols=int(payload.get("max_live_request_symbols", 0)),
        output_dir=resolve_repo_path(payload["output_dir"]),
    )


def run_m12_liquid_universe_scanner(config: ScannerConfig, *, generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    validate_config(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    queue = load_json(config.observation_queue_path)
    paper_gate = load_json(config.paper_gate_candidate_path)
    tier_a_queue = build_tier_a_queue(queue, paper_gate)
    specs = load_specs(config, tier_a_queue)
    universe = build_universe(config)

    candidates: list[dict[str, str]] = []
    scan_attempts: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    cache_inventory: list[dict[str, Any]] = []
    for symbol in universe:
        availability = resolve_symbol_data(config, symbol)
        cache_inventory.extend(build_cache_inventory_rows(symbol, availability))
        if not availability["daily_path"] and not availability["intraday_5m_path"]:
            deferred.append(deferred_symbol(symbol, "symbol_unscanned_no_local_cache"))
            continue
        symbol_candidates, symbol_attempts, symbol_deferred = scan_symbol(
            config=config,
            generated_at=generated_at,
            symbol=symbol,
            availability=availability,
            tier_a_queue=tier_a_queue,
            specs=specs,
        )
        candidates.extend(symbol_candidates)
        scan_attempts.extend(symbol_attempts)
        deferred.extend(symbol_deferred)

    candidates.sort(key=lambda row: (row["symbol"], row["strategy_id"], row["timeframe"], row["bar_timestamp"]))
    for row in candidates:
        validate_candidate_row(row)

    universe_definition = build_universe_definition(config, generated_at, universe)
    summary = build_summary(config, generated_at, universe, candidates, scan_attempts, deferred)
    write_json(config.output_dir / "m12_5_universe_definition.json", universe_definition)
    write_json(
        config.output_dir / "m12_5_cache_inventory.json",
        {
            "schema_version": "m12.scanner-cache-inventory.v1",
            "stage": "M12.5.liquid_universe_scanner",
            "items": cache_inventory,
        },
    )
    write_candidates_csv(config.output_dir / "m12_5_scanner_candidates.csv", candidates)
    write_json(config.output_dir / "m12_5_scanner_summary.json", summary)
    write_json(config.output_dir / "m12_5_deferred_inputs.json", {"schema_version": "m12.scanner-deferred-inputs.v1", "stage": "M12.5.liquid_universe_scanner", "items": deferred})
    (config.output_dir / "m12_5_scanner_report.md").write_text(build_report(summary, candidates), encoding="utf-8")
    assert_no_forbidden_output(config.output_dir)
    return summary


def validate_config(config: ScannerConfig) -> None:
    if config.strategy_scope != TIER_A_STRATEGY_IDS:
        raise ValueError(f"M12.5 scanner must stay Tier A only: {config.strategy_scope}")
    if config.max_live_request_symbols != 0:
        raise ValueError("M12.5 first pass is local-cache only and must not issue live requests")
    if config.max_universe_size < 100 or config.max_universe_size > 200:
        raise ValueError("M12.5 first pass universe size must stay within 100-200")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_tier_a_queue(queue: dict[str, Any], paper_gate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tier_a = tuple(paper_gate.get("candidate_groups", {}).get("tier_a_core_after_read_only_observation", ()))
    if tier_a != TIER_A_STRATEGY_IDS:
        raise ValueError(f"M11 Tier A drift: {tier_a}")
    primary = {
        item["strategy_id"]: item
        for item in queue.get("primary_observation_queue", [])
        if item["strategy_id"] in TIER_A_STRATEGY_IDS
    }
    if set(primary) != set(TIER_A_STRATEGY_IDS):
        raise ValueError(f"M10.13 queue missing Tier A strategies: {sorted(set(TIER_A_STRATEGY_IDS) - set(primary))}")
    for item in primary.values():
        if item.get("requires_visual_review_context"):
            raise ValueError(f"Tier A scanner cannot require visual review: {item['strategy_id']}")
    return primary


def load_specs(config: ScannerConfig, queue: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for strategy_id, item in queue.items():
        path = config.backtest_spec_dir / f"{strategy_id}.json"
        spec = load_json(path)
        if spec.get("strategy_id") != strategy_id:
            raise ValueError(f"Spec id mismatch for {strategy_id}")
        for timeframe in item["timeframes"]:
            if timeframe not in spec.get("timeframes", []):
                raise ValueError(f"{strategy_id} {timeframe} not in frozen spec")
        specs[strategy_id] = spec
    return specs


def build_universe(config: ScannerConfig) -> list[str]:
    if config.universe_preset != "us_liquid_seed_v1":
        raise ValueError(f"Unsupported universe preset: {config.universe_preset}")
    universe = list(dict.fromkeys(US_LIQUID_SEED_V1))
    if len(universe) > config.max_universe_size:
        universe = universe[: config.max_universe_size]
    if not 100 <= len(universe) <= 200:
        raise ValueError(f"M12.5 universe must contain 100-200 symbols, got {len(universe)}")
    return universe


def resolve_symbol_data(config: ScannerConfig, symbol: str) -> dict[str, Any]:
    return {
        "daily_path": find_best_csv(config.local_data_roots, "longbridge_history", f"us_{symbol}_1d_*_longbridge.csv"),
        "intraday_5m_path": find_best_csv(config.local_data_roots, "longbridge_intraday", f"us_{symbol}_5m_*_longbridge.csv"),
    }


def find_best_csv(roots: Iterable[Path], subdir: str, pattern: str) -> Path | None:
    candidates: list[Path] = []
    for root in roots:
        directory = root / subdir
        if directory.exists():
            candidates.extend(directory.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda path: (last_timestamp_for_file(path), path.stat().st_size, path.as_posix()))


def last_timestamp_for_file(path: Path) -> str:
    last = ""
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            last = row.get("timestamp", last)
    return last


def build_cache_inventory_rows(symbol: str, availability: dict[str, Any]) -> list[dict[str, Any]]:
    daily_path = availability["daily_path"]
    intraday_path = availability["intraday_5m_path"]
    return [
        cache_inventory_row(symbol, "1d", "native_cache", daily_path),
        cache_inventory_row(symbol, "5m", "native_cache", intraday_path),
        cache_inventory_row(symbol, "15m", "derived_from_5m", intraday_path),
        cache_inventory_row(symbol, "1h", "derived_from_5m", intraday_path),
    ]


def cache_inventory_row(symbol: str, timeframe: str, lineage: str, path: Path | None) -> dict[str, Any]:
    stats = csv_stats(path)
    anomaly_path = vendor_anomaly_path(path) if path else None
    return {
        "symbol": symbol,
        "market": "US",
        "timeframe": timeframe,
        "lineage": lineage,
        "cache_exists": path is not None,
        "cache_path": project_path(path) if path else "",
        "checksum": sha256_file(path) if path else "",
        "row_count": stats["row_count"],
        "start": stats["start"],
        "end": stats["end"],
        "timezone": stats["timezone"],
        "vendor_anomalies_ref": project_path(anomaly_path) if anomaly_path and anomaly_path.exists() else "",
    }


def csv_stats(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"row_count": 0, "start": "", "end": "", "timezone": ""}
    row_count = 0
    start = ""
    end = ""
    timezone = ""
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            timestamp = row.get("timestamp", "")
            if row_count == 1:
                start = timestamp
                timezone = row.get("timezone", "")
            end = timestamp
    return {"row_count": row_count, "start": start, "end": end, "timezone": timezone}


def vendor_anomaly_path(path: Path) -> Path:
    return path.with_name(path.name.replace(".csv", ".vendor_anomalies.json"))


def scan_symbol(
    *,
    config: ScannerConfig,
    generated_at: str,
    symbol: str,
    availability: dict[str, Any],
    tier_a_queue: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    bars_by_timeframe: dict[str, tuple[list[Bar], str, Path | None]] = {}
    deferred: list[dict[str, Any]] = []
    if availability["daily_path"]:
        daily_bars = load_bars(availability["daily_path"])
        bars_by_timeframe["1d"] = (daily_bars, "native_daily_cache", availability["daily_path"])
    if availability["intraday_5m_path"]:
        five_minute = load_bars(availability["intraday_5m_path"])
        bars_by_timeframe["5m"] = (five_minute, "native_5m_cache", availability["intraday_5m_path"])
        bars_by_timeframe["15m"] = (aggregate_bars(five_minute, "15m"), "derived_from_5m", availability["intraday_5m_path"])
        bars_by_timeframe["1h"] = (aggregate_bars(five_minute, "1h"), "derived_from_5m", availability["intraday_5m_path"])

    candidates: list[dict[str, str]] = []
    scan_attempts: list[dict[str, Any]] = []
    for strategy_id, item in tier_a_queue.items():
        for timeframe in item["timeframes"]:
            bars, lineage, path = bars_by_timeframe.get(timeframe, ([], "", None))
            if not bars:
                deferred.append(
                    {
                        "symbol": symbol,
                        "strategy_id": strategy_id,
                        "timeframe": timeframe,
                        "reason": "required_timeframe_cache_missing",
                    }
                )
                continue
            scan_attempts.append({"symbol": symbol, "strategy_id": strategy_id, "timeframe": timeframe, "lineage": lineage, "bar_count": len(bars)})
            candidate = evaluate_strategy_candidate(
                generated_at=generated_at,
                strategy_id=strategy_id,
                strategy_title=item["title"],
                timeframe=timeframe,
                bars=bars,
                lineage=lineage,
                data_path=path,
                spec=specs[strategy_id],
            )
            if candidate:
                candidates.append(candidate)
    return candidates, scan_attempts, deferred


def load_bars(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                bars.append(
                    Bar(
                        symbol=row["symbol"],
                        market=row["market"],
                        timeframe=row["timeframe"],
                        timestamp=row["timestamp"],
                        timezone=row.get("timezone", ""),
                        open=Decimal(row["open"]),
                        high=Decimal(row["high"]),
                        low=Decimal(row["low"]),
                        close=Decimal(row["close"]),
                        volume=Decimal(row.get("volume", "0") or "0"),
                    )
                )
            except (KeyError, InvalidOperation) as exc:
                raise ValueError(f"Invalid OHLCV row in {path}") from exc
    return sorted(bars, key=lambda bar: bar.timestamp)


def aggregate_bars(bars: list[Bar], timeframe: str) -> list[Bar]:
    if timeframe not in {"15m", "1h"}:
        raise ValueError(f"Unsupported aggregation timeframe: {timeframe}")
    grouped: dict[tuple[str, int, int], list[Bar]] = defaultdict(list)
    for bar in bars:
        stamp = datetime.fromisoformat(bar.timestamp)
        minute = (stamp.minute // 15) * 15 if timeframe == "15m" else 0
        grouped[(stamp.date().isoformat(), stamp.hour, minute)].append(bar)
    aggregated: list[Bar] = []
    for items in grouped.values():
        ordered = sorted(items, key=lambda bar: bar.timestamp)
        aggregated.append(
            Bar(
                symbol=ordered[0].symbol,
                market=ordered[0].market,
                timeframe=timeframe,
                timestamp=ordered[-1].timestamp,
                timezone=ordered[0].timezone,
                open=ordered[0].open,
                high=max(item.high for item in ordered),
                low=min(item.low for item in ordered),
                close=ordered[-1].close,
                volume=sum((item.volume for item in ordered), Decimal("0")),
            )
        )
    return sorted(aggregated, key=lambda bar: bar.timestamp)


def evaluate_strategy_candidate(
    *,
    generated_at: str,
    strategy_id: str,
    strategy_title: str,
    timeframe: str,
    bars: list[Bar],
    lineage: str,
    data_path: Path | None,
    spec: dict[str, Any],
) -> dict[str, str] | None:
    if strategy_id == "M10-PA-001":
        return evaluate_trend_pullback(generated_at, strategy_id, strategy_title, timeframe, bars, lineage, data_path, spec)
    if strategy_id == "M10-PA-002":
        return evaluate_breakout(generated_at, strategy_id, strategy_title, timeframe, bars, lineage, data_path, spec)
    if strategy_id == "M10-PA-012":
        return evaluate_opening_range_breakout(generated_at, strategy_id, strategy_title, timeframe, bars, lineage, data_path, spec)
    raise ValueError(f"Unsupported scanner strategy: {strategy_id}")


def evaluate_trend_pullback(
    generated_at: str,
    strategy_id: str,
    strategy_title: str,
    timeframe: str,
    bars: list[Bar],
    lineage: str,
    data_path: Path | None,
    spec: dict[str, Any],
) -> dict[str, str] | None:
    if len(bars) < 55:
        return None
    last = bars[-1]
    previous = bars[-2]
    sma20 = average_close(bars[-21:-1])
    sma50 = average_close(bars[-51:-1])
    recent = bars[-8:-1]
    direction = ""
    if sma20 > sma50 and min(bar.low for bar in recent) < sma20 and last.high > previous.high:
        direction = "long"
        entry = last.high
        stop = min(bar.low for bar in recent)
    elif sma20 < sma50 and max(bar.high for bar in recent) > sma20 and last.low < previous.low:
        direction = "short"
        entry = last.low
        stop = max(bar.high for bar in recent)
    else:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = entry + risk * Decimal("2") if direction == "long" else entry - risk * Decimal("2")
    return candidate_row(
        generated_at=generated_at,
        strategy_id=strategy_id,
        strategy_title=strategy_title,
        timeframe=timeframe,
        bar=last,
        status="watch_candidate",
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        risk_level=risk_level_for(risk, entry),
        queue_action="eligible_for_read_only_observation",
        lineage=lineage,
        data_path=data_path,
        spec=spec,
        notes="Trend and pullback proxy found; requires bar-by-bar confirmation before any future status change.",
    )


def evaluate_breakout(
    generated_at: str,
    strategy_id: str,
    strategy_title: str,
    timeframe: str,
    bars: list[Bar],
    lineage: str,
    data_path: Path | None,
    spec: dict[str, Any],
) -> dict[str, str] | None:
    if len(bars) < 22:
        return None
    last = bars[-1]
    prior = bars[-21:-1]
    range_high = max(bar.high for bar in prior)
    range_low = min(bar.low for bar in prior)
    true_range = last.high - last.low
    if true_range <= 0:
        return None
    body_fraction = abs(last.close - last.open) / true_range
    direction = ""
    if last.close > range_high and body_fraction >= Decimal("0.5") and (last.high - last.close) / true_range <= Decimal("0.34"):
        direction = "long"
        entry = last.close
        stop = last.low
    elif last.close < range_low and body_fraction >= Decimal("0.5") and (last.close - last.low) / true_range <= Decimal("0.34"):
        direction = "short"
        entry = last.close
        stop = last.high
    else:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = entry + risk * Decimal("2") if direction == "long" else entry - risk * Decimal("2")
    return candidate_row(
        generated_at=generated_at,
        strategy_id=strategy_id,
        strategy_title=strategy_title,
        timeframe=timeframe,
        bar=last,
        status="trigger_candidate",
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        risk_level=risk_level_for(risk, entry),
        queue_action="eligible_for_read_only_observation",
        lineage=lineage,
        data_path=data_path,
        spec=spec,
        notes="20-bar breakout proxy matched; follow-through still needs bar-close observation.",
    )


def evaluate_opening_range_breakout(
    generated_at: str,
    strategy_id: str,
    strategy_title: str,
    timeframe: str,
    bars: list[Bar],
    lineage: str,
    data_path: Path | None,
    spec: dict[str, Any],
) -> dict[str, str] | None:
    if timeframe not in {"15m", "5m"} or len(bars) < 20:
        return None
    latest_date = datetime.fromisoformat(bars[-1].timestamp).date()
    session = [bar for bar in bars if datetime.fromisoformat(bar.timestamp).date() == latest_date]
    if len(session) < 8:
        return None
    opening = session[:2] if timeframe == "15m" else session[:6]
    after_open = session[len(opening) :]
    if not after_open:
        return None
    opening_high = max(bar.high for bar in opening)
    opening_low = min(bar.low for bar in opening)
    height = opening_high - opening_low
    if height <= 0:
        return None
    for index, bar in enumerate(after_open):
        if bar.close > opening_high:
            direction = "long"
            entry = bar.close
            stop = opening_low
            target = entry + height
        elif bar.close < opening_low:
            direction = "short"
            entry = bar.close
            stop = opening_high
            target = entry - height
        else:
            continue
        follow_through = after_open[index + 1 : index + 3]
        if not follow_through:
            continue
        return candidate_row(
            generated_at=generated_at,
            strategy_id=strategy_id,
            strategy_title=strategy_title,
            timeframe=timeframe,
            bar=bar,
            status="trigger_candidate",
            direction=direction,
            entry=entry,
            stop=stop,
            target=target,
            risk_level=risk_level_for(abs(entry - stop), entry),
            queue_action="eligible_for_read_only_observation",
            lineage=lineage,
            data_path=data_path,
            spec=spec,
            notes="Opening range breakout proxy found in recorded local cache; observe only, no execution.",
        )
    return None


def average_close(bars: list[Bar]) -> Decimal:
    return sum((bar.close for bar in bars), Decimal("0")) / Decimal(len(bars))


def risk_level_for(risk: Decimal, entry: Decimal) -> str:
    if entry == 0:
        return "unknown"
    risk_percent = abs(risk / entry)
    if risk_percent <= Decimal("0.005"):
        return "low"
    if risk_percent <= Decimal("0.015"):
        return "medium"
    return "high"


def candidate_row(
    *,
    generated_at: str,
    strategy_id: str,
    strategy_title: str,
    timeframe: str,
    bar: Bar,
    status: str,
    direction: str,
    entry: Decimal,
    stop: Decimal,
    target: Decimal,
    risk_level: str,
    queue_action: str,
    lineage: str,
    data_path: Path | None,
    spec: dict[str, Any],
    notes: str,
) -> dict[str, str]:
    return {
        "schema_version": "m12.scanner-candidate.v1",
        "stage": "M12.5.liquid_universe_scanner",
        "generated_at": generated_at,
        "symbol": bar.symbol,
        "market": bar.market,
        "strategy_id": strategy_id,
        "strategy_title": strategy_title,
        "timeframe": timeframe,
        "candidate_status": status,
        "signal_direction": direction,
        "bar_timestamp": bar.timestamp,
        "entry_price": money(entry),
        "stop_price": money(stop),
        "target_price": money(target),
        "risk_per_share": money(abs(entry - stop)),
        "risk_level": risk_level,
        "queue_action": queue_action,
        "source_refs": ";".join(source_refs_for(spec)),
        "spec_ref": f"reports/strategy_lab/m10_price_action_strategy_refresh/backtest_specs/{strategy_id}.json",
        "data_lineage": lineage,
        "data_path": project_path(data_path) if data_path else "",
        "data_checksum": sha256_file(data_path) if data_path else "",
        "review_status": "needs_read_only_bar_close_review",
        "notes": notes,
    }


def validate_candidate_row(row: dict[str, str]) -> None:
    if row["strategy_id"] not in TIER_A_STRATEGY_IDS:
        raise ValueError(f"Scanner candidate outside Tier A: {row['strategy_id']}")
    if row["strategy_id"] in VISUAL_OR_BLOCKED_IDS:
        raise ValueError(f"Scanner candidate includes excluded strategy: {row['strategy_id']}")
    forbidden = FORBIDDEN_KEYS & set(row)
    if forbidden:
        raise ValueError(f"Scanner candidate has execution/account keys: {sorted(forbidden)}")
    forbidden_boundary_keys = {"paper_simulated_only"} | FORBIDDEN_CONFIG_KEYS
    leaked = forbidden_boundary_keys & set(row)
    if leaked:
        raise ValueError(f"Scanner candidate leaked boundary fields: {sorted(leaked)}")


def source_refs_for(spec: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for item in spec.get("source_refs", []):
        if isinstance(item, str):
            refs.append(item)
        elif isinstance(item, dict) and item.get("source_ref"):
            refs.append(str(item["source_ref"]))
    return refs


def deferred_symbol(symbol: str, reason: str) -> dict[str, Any]:
    return {"symbol": symbol, "reason": reason, "scope": "symbol", "action": "deferred_no_fake_candidate"}


def build_universe_definition(config: ScannerConfig, generated_at: str, universe: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "m12.universe-definition.v1",
        "generated_at": generated_at,
        "stage": "M12.5.liquid_universe_scanner",
        "market": config.market,
        "universe_preset": config.universe_preset,
        "symbol_count": len(universe),
        "symbols": universe,
        "selection_note": "Static v1 seed of liquid US-listed equities and ETFs; not a current liquidity ranking and must be refreshed before production use.",
        "request_policy": {
            "max_universe_size": config.max_universe_size,
            "max_live_request_symbols": config.max_live_request_symbols,
            "mode": "local_cache_only_first_pass",
        },
    }


def build_summary(
    config: ScannerConfig,
    generated_at: str,
    universe: list[str],
    candidates: list[dict[str, str]],
    scan_attempts: list[dict[str, Any]],
    deferred: list[dict[str, Any]],
) -> dict[str, Any]:
    scanned_symbols = sorted({row["symbol"] for row in scan_attempts})
    return {
        "schema_version": "m12.scanner-summary.v1",
        "generated_at": generated_at,
        "stage": "M12.5.liquid_universe_scanner",
        "run_id": config.run_id,
        "strategy_scope": list(TIER_A_STRATEGY_IDS),
        "excluded_strategy_ids": list(VISUAL_OR_BLOCKED_IDS),
        "universe_symbol_count": len(universe),
        "scanned_symbol_count": len(scanned_symbols),
        "deferred_symbol_count": len({item.get("symbol") for item in deferred if item.get("scope") == "symbol"}),
        "scan_attempt_count": len(scan_attempts),
        "candidate_count": len(candidates),
        "candidate_status_counts": dict(Counter(row["candidate_status"] for row in candidates)),
        "strategy_candidate_counts": dict(Counter(row["strategy_id"] for row in candidates)),
        "lineage_counts": dict(Counter(row["lineage"] for row in scan_attempts)),
        "request_policy": {
            "max_live_request_symbols": config.max_live_request_symbols,
            "live_requests_used": 0,
            "missing_data_behavior": "deferred_no_fake_candidate",
        },
        "artifacts": {
            "universe_definition": project_path(config.output_dir / "m12_5_universe_definition.json"),
            "cache_inventory": project_path(config.output_dir / "m12_5_cache_inventory.json"),
            "scanner_candidates": project_path(config.output_dir / "m12_5_scanner_candidates.csv"),
            "deferred_inputs": project_path(config.output_dir / "m12_5_deferred_inputs.json"),
            "scanner_report": project_path(config.output_dir / "m12_5_scanner_report.md"),
            "scanner_summary": project_path(config.output_dir / "m12_5_scanner_summary.json"),
        },
    }


def write_candidates_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "schema_version",
        "stage",
        "generated_at",
        "symbol",
        "market",
        "strategy_id",
        "strategy_title",
        "timeframe",
        "candidate_status",
        "signal_direction",
        "bar_timestamp",
        "entry_price",
        "stop_price",
        "target_price",
        "risk_per_share",
        "risk_level",
        "queue_action",
        "source_refs",
        "spec_ref",
        "data_lineage",
        "data_path",
        "data_checksum",
        "review_status",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_report(summary: dict[str, Any], candidates: list[dict[str, str]]) -> str:
    lines = [
        "# M12.5 Liquid Universe Scanner Report",
        "",
        "## 摘要",
        "",
        f"- 股票池：{summary['universe_symbol_count']} 只 US-listed 股票/ETF seed。",
        f"- 实际有本地数据并完成扫描的标的：{summary['scanned_symbol_count']} 只。",
        f"- 输出候选：{summary['candidate_count']} 条。",
        "- 本阶段只用本地 OHLCV cache；缺数据的标的全部 deferred，不补假机会。",
        "- 自动 scanner 只接 Tier A：`M10-PA-001/002/012`。",
        "- 不接 broker、不接账户、不下单、不批准 paper trading。",
        "",
        "## 候选明细",
        "",
        "| Symbol | Strategy | Timeframe | Status | Direction | Entry | Stop | Target | Risk | Queue |",
        "|---|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in candidates[:50]:
        lines.append(
            f"| {row['symbol']} | {row['strategy_id']} | {row['timeframe']} | {row['candidate_status']} | "
            f"{row['signal_direction']} | {row['entry_price']} | {row['stop_price']} | {row['target_price']} | "
            f"{row['risk_level']} | {row['queue_action']} |"
        )
    if not candidates:
        lines.append("| - | - | - | no_candidate | - | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "下一阶段可以把 scanner 输出接到每周成绩单。扩大覆盖前，应先补齐更多 universe 标的的只读 K 线缓存或受控 Longbridge 读取计划。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.0001'))}"


def sha256_file(path: Path | None) -> str:
    if path is None:
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_path(path: Path | None) -> str:
    if path is None:
        return ""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output_dir.glob("m12_5_*")
        if path.is_file()
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_TEXT:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


if __name__ == "__main__":
    run_m12_liquid_universe_scanner(load_scanner_config())
