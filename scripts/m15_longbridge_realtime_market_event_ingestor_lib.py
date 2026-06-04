#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from scripts.longbridge_cli_env import build_longbridge_cli_env
from scripts.m12_liquid_universe_scanner_lib import US_LIQUID_SEED_V1
from scripts.m12_readonly_auth_preflight_lib import _assert_readonly_command, clean_cli_text
from scripts.m15_longbridge_realtime_execution_lib import (
    DEFAULT_DAILY_DIR,
    parse_utc_datetime,
    resolve_session_started_at,
    session_start_is_auto,
    to_iso,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_market_event_ingestor.json"
DEFAULT_MARKET_EVENTS = DEFAULT_OUTPUT_DIR / "m15_realtime_market_events.jsonl"
SUMMARY_JSON = "m15_longbridge_realtime_market_event_ingestor.json"
LEDGER_JSONL = "m15_longbridge_realtime_market_event_ingestor_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_market_event_ingestor.md"
TIMEFRAME_TO_LONGBRIDGE_PERIOD = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "1d": "day",
}
INTRADAY_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h"}

CommandRunner = Callable[[str, list[str], int], Any]


@dataclass(frozen=True, slots=True)
class RealtimeMarketEventIngestorConfig:
    stage: str
    title: str
    output_dir: Path
    market_events_path: Path
    session_started_at: str
    market: str
    symbols: tuple[str, ...]
    hot_symbols: tuple[str, ...]
    use_seed_universe: bool
    symbol_limit: int
    max_symbols_per_cycle: int
    symbol_cursor_path: Path
    timeframes: tuple[str, ...]
    kline_count: int
    watch_interval_seconds: int
    cli_timeout_seconds: int
    hard_boundaries: dict[str, bool]

    def __post_init__(self) -> None:
        validate_config(self)


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RealtimeMarketEventIngestorConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    outputs = payload.get("outputs", {})
    market_data = payload.get("longbridge_market_data", {})
    symbols = tuple(str(item).upper() for item in market_data.get("symbols", []))
    output_dir = resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR))
    return RealtimeMarketEventIngestorConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_market_event_ingestor")),
        title=str(payload.get("title", "长桥实时行情事件采集器")),
        output_dir=output_dir,
        market_events_path=resolve_repo_path(outputs.get("market_events", DEFAULT_MARKET_EVENTS)),
        session_started_at=str(market_data.get("session_started_at", "")),
        market=str(market_data.get("market", "US")).upper(),
        symbols=symbols,
        hot_symbols=tuple(str(item).upper().replace(".US", "") for item in market_data.get("hot_symbols", [])),
        use_seed_universe=bool(market_data.get("use_seed_universe", not symbols)),
        symbol_limit=int(market_data.get("symbol_limit", 147)),
        max_symbols_per_cycle=int(market_data.get("max_symbols_per_cycle", market_data.get("symbol_limit", 147))),
        symbol_cursor_path=resolve_repo_path(market_data.get("symbol_cursor_path", output_dir / "m15_realtime_symbol_cursor.json")),
        timeframes=tuple(str(item) for item in market_data.get("timeframes", ["1d", "5m"])),
        kline_count=int(market_data.get("kline_count", 2)),
        watch_interval_seconds=int(market_data.get("watch_interval_seconds", 1)),
        cli_timeout_seconds=int(market_data.get("cli_timeout_seconds", 6)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: RealtimeMarketEventIngestorConfig) -> None:
    if config.stage != "M15.longbridge_realtime_market_event_ingestor":
        raise ValueError("M15 realtime market event ingestor stage drift")
    if not config.session_started_at:
        raise ValueError("M15 realtime market event ingestor requires session_started_at")
    if not session_start_is_auto(config.session_started_at):
        parse_utc_datetime(config.session_started_at)
    if config.symbol_limit <= 0:
        raise ValueError("M15 realtime market event ingestor symbol_limit must be positive")
    if config.max_symbols_per_cycle <= 0:
        raise ValueError("M15 realtime market event ingestor max_symbols_per_cycle must be positive")
    if config.kline_count <= 0:
        raise ValueError("M15 realtime market event ingestor kline_count must be positive")
    if config.watch_interval_seconds <= 0:
        raise ValueError("M15 realtime market event ingestor watch interval must be positive")
    if config.cli_timeout_seconds <= 0:
        raise ValueError("M15 realtime market event ingestor CLI timeout must be positive")
    unsupported = sorted(set(config.timeframes) - set(TIMEFRAME_TO_LONGBRIDGE_PERIOD))
    if unsupported:
        raise ValueError(f"Unsupported M15 realtime timeframes: {unsupported}")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 realtime market event ingestor must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("M15 realtime market event ingestor cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("M15 realtime market event ingestor cannot enable real money actions")
    if config.hard_boundaries.get("account_or_order_commands", False):
        raise ValueError("M15 realtime market event ingestor cannot use account or order commands")
    if config.hard_boundaries.get("local_simulation_as_market_source", False):
        raise ValueError("M15 realtime market event ingestor cannot use local simulation as market source")


def run_realtime_market_event_ingestor(
    config: RealtimeMarketEventIngestorConfig | None = None,
    *,
    generated_at: str | None = None,
    command_runner: CommandRunner | None = None,
    cli_path: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    session_started_at = resolve_session_started_at(config.session_started_at, now)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.market_events_path.parent.mkdir(parents=True, exist_ok=True)

    existing_events = read_jsonl(config.market_events_path)
    existing_event_ids = {str(row.get("event_id")) for row in existing_events if row.get("event_id")}
    ledger_rows: list[dict[str, Any]] = []
    new_events: list[dict[str, Any]] = []
    deferred_rows: list[dict[str, Any]] = []
    binary = cli_path or shutil.which("longbridge")
    configured = configured_symbols(config)
    cycle_symbols = symbols_for_cycle(config, configured)

    if binary is None:
        deferred_rows.append({"scope": "market_data", "reason": "longbridge_cli_missing"})
    else:
        runner = command_runner or run_longbridge_json
        for symbol in cycle_symbols:
            for timeframe in config.timeframes:
                args = build_kline_args(config, symbol=symbol, timeframe=timeframe)
                try:
                    payload = runner(binary, args, config.cli_timeout_seconds)
                except Exception as exc:  # pragma: no cover - runtime provider path
                    ledger_rows.append(
                        {
                            "stage": config.stage,
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "ingest_status": "deferred_longbridge_kline_failed",
                            "reason": str(exc)[:300],
                            "readonly_command": ["longbridge", *args],
                        }
                    )
                    deferred_rows.append(
                        {
                            "scope": "kline",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "reason": "longbridge_kline_failed",
                            "detail": str(exc)[:300],
                        }
                    )
                    continue
                rows = normalize_kline_payload(payload)
                if not rows:
                    ledger_rows.append(
                        {
                            "stage": config.stage,
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "ingest_status": "deferred_no_kline_rows",
                            "reason": "no_kline_rows_returned",
                            "readonly_command": ["longbridge", *args],
                        }
                    )
                    deferred_rows.append(
                        {
                            "scope": "kline",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "reason": "no_kline_rows_returned",
                        }
                    )
                    continue
                for raw_bar in rows:
                    event = build_market_event(config, symbol=symbol, timeframe=timeframe, raw_bar=raw_bar, received_at=generated_at_iso)
                    status = "new_market_event_appended"
                    if event["event_id"] in existing_event_ids:
                        status = "duplicate_market_event_skipped"
                    else:
                        new_events.append(event)
                        existing_event_ids.add(event["event_id"])
                    ledger_rows.append(
                        {
                            "stage": config.stage,
                            "event_id": event["event_id"],
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "event_time": event["event_time"],
                            "ingest_status": status,
                            "readonly_command": ["longbridge", *args],
                            "local_simulation_ignored": True,
                            "account_or_order_command_used": False,
                        }
                    )

    write_jsonl(config.market_events_path, existing_events + new_events)
    write_jsonl(config.output_dir / LEDGER_JSONL, ledger_rows)
    summary = {
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at_iso,
        "source_mode": "longbridge_readonly_kline_market_events",
        "market": config.market,
        "session_started_at": session_started_at,
        "symbol_count": len(configured),
        "configured_symbol_count": len(configured),
        "cycle_symbol_count": len(cycle_symbols),
        "cycle_symbols": list(cycle_symbols),
        "hot_symbols": list(config.hot_symbols),
        "max_symbols_per_cycle": config.max_symbols_per_cycle,
        "timeframes": list(config.timeframes),
        "existing_market_event_count": len(existing_events),
        "new_market_event_count": len(new_events),
        "market_event_total_count": len(existing_events) + len(new_events),
        "deferred_count": len(deferred_rows),
        "deferred_rows": deferred_rows[:50],
        "local_simulation_isolated": True,
        "local_ledger_input_ref": "",
        "legacy_fast_queue_used": False,
        "account_or_order_command_used": False,
        "readonly_command_allowlist": ["kline"],
        "inputs": {
            "local_simulation_ledger": "",
            "fast_signal_queue": "",
            "account_state": "",
        },
        "outputs": {
            "market_events": project_path(config.market_events_path),
            "ingestor_summary": project_path(config.output_dir / SUMMARY_JSON),
            "ingestor_ledger": project_path(config.output_dir / LEDGER_JSONL),
            "ingestor_report": project_path(config.output_dir / REPORT_MD),
        },
        "plain_language_result": plain_language_result(len(new_events), len(deferred_rows), binary is not None),
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
    }
    write_json(config.output_dir / SUMMARY_JSON, summary)
    (config.output_dir / REPORT_MD).write_text(render_report(summary, ledger_rows), encoding="utf-8")
    return summary


def configured_symbols(config: RealtimeMarketEventIngestorConfig) -> tuple[str, ...]:
    if config.symbols:
        return tuple(symbol.upper().replace(f".{config.market}", "") for symbol in config.symbols[: config.symbol_limit])
    if config.use_seed_universe:
        return tuple(str(symbol).upper() for symbol in US_LIQUID_SEED_V1[: config.symbol_limit])
    return ()


def symbols_for_cycle(config: RealtimeMarketEventIngestorConfig, symbols: tuple[str, ...]) -> tuple[str, ...]:
    if not symbols:
        return ()
    normalized_hot = tuple(symbol for symbol in config.hot_symbols if symbol in set(symbols))
    selected: list[str] = []
    for symbol in normalized_hot:
        if symbol not in selected and len(selected) < config.max_symbols_per_cycle:
            selected.append(symbol)
    remaining_slots = config.max_symbols_per_cycle - len(selected)
    non_hot = [symbol for symbol in symbols if symbol not in set(selected)]
    if remaining_slots > 0 and non_hot:
        cursor = int_like(read_json(config.symbol_cursor_path).get("next_index", 0))
        for offset in range(min(remaining_slots, len(non_hot))):
            selected.append(non_hot[(cursor + offset) % len(non_hot)])
        next_index = (cursor + remaining_slots) % len(non_hot)
        config.symbol_cursor_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            config.symbol_cursor_path,
            {
                "schema_version": "m15.realtime-symbol-cursor.v1",
                "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "next_index": next_index,
                "symbol_count": len(symbols),
                "non_hot_symbol_count": len(non_hot),
            },
        )
    return tuple(selected)


def build_longbridge_symbol(symbol: str, market: str) -> str:
    return symbol if "." in symbol else f"{symbol}.{market.upper()}"


def build_kline_args(config: RealtimeMarketEventIngestorConfig, *, symbol: str, timeframe: str) -> list[str]:
    if timeframe not in TIMEFRAME_TO_LONGBRIDGE_PERIOD:
        raise ValueError(f"Unsupported M15 realtime timeframe: {timeframe}")
    args = [
        "kline",
        build_longbridge_symbol(symbol, config.market),
        "--period",
        TIMEFRAME_TO_LONGBRIDGE_PERIOD[timeframe],
        "--count",
        str(config.kline_count),
        "--format",
        "json",
    ]
    if timeframe in INTRADAY_TIMEFRAMES:
        args.extend(["--session", "intraday"])
    _assert_readonly_command(args)
    return args


def run_longbridge_json(cli_path: str, args: list[str], timeout_seconds: int) -> Any:
    _assert_readonly_command(args)
    completed = subprocess.run(
        [cli_path, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
        env=build_longbridge_cli_env(),
    )
    if completed.returncode != 0:
        detail = clean_cli_text((completed.stderr or completed.stdout or "").strip())
        raise RuntimeError(detail or f"longbridge {' '.join(args)} failed with {completed.returncode}")
    stdout = completed.stdout.strip()
    if not stdout:
        return []
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"longbridge returned non-JSON output for {' '.join(args)}") from exc


def normalize_kline_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected longbridge kline payload: {payload!r}")
    return [row for row in payload if isinstance(row, dict)]


def build_market_event(
    config: RealtimeMarketEventIngestorConfig,
    *,
    symbol: str,
    timeframe: str,
    raw_bar: dict[str, Any],
    received_at: str,
) -> dict[str, Any]:
    event_time = str(raw_bar.get("time") or raw_bar.get("timestamp") or raw_bar.get("date") or "")
    if not event_time:
        raise RuntimeError(f"Longbridge kline row has no time for {symbol} {timeframe}: {raw_bar!r}")
    close = str(raw_bar.get("close", ""))
    event_id = deterministic_event_id(symbol=symbol, timeframe=timeframe, event_time=event_time, close=close)
    return {
        "event_id": event_id,
        "event_type": "bar_close",
        "received_at": received_at,
        "event_time": event_time,
        "symbol": symbol.upper().replace(f".{config.market}", ""),
        "market": config.market,
        "timeframe": timeframe,
        "open": str(raw_bar.get("open", "")),
        "high": str(raw_bar.get("high", "")),
        "low": str(raw_bar.get("low", "")),
        "close": close,
        "volume": str(raw_bar.get("volume", "")),
        "turnover": str(raw_bar.get("turnover", "")),
        "quote_source": "longbridge_quote_readonly",
        "source": "longbridge_cli_readonly_kline",
        "local_simulation_source": False,
        "fast_queue_source": False,
        "account_state_source": False,
    }


def deterministic_event_id(*, symbol: str, timeframe: str, event_time: str, close: str) -> str:
    digest = sha256(f"{symbol.upper()}|{timeframe}|{event_time}|{close}".encode("utf-8")).hexdigest()[:16]
    return f"m15me-{digest}"


def plain_language_result(new_event_count: int, deferred_count: int, cli_available: bool) -> str:
    if not cli_available:
        return "长桥实时行情事件采集器未发现 longbridge CLI；没有生成假行情事件。"
    if new_event_count:
        return f"长桥只读行情采集器新增 {new_event_count} 条实时行情事件；没有读取本地模拟账本。"
    if deferred_count:
        return "长桥只读行情采集器本轮没有新增事件，部分 K 线读取失败或无返回；没有生成假行情。"
    return "长桥只读行情采集器已就绪；本轮没有新的 K 线事件。"


def render_report(summary: dict[str, Any], ledger_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 长桥实时行情事件采集器",
        "",
        f"- 生成时间: `{summary['generated_at']}`",
        f"- 行情来源: `{summary['source_mode']}`",
        f"- 新增事件: `{summary['new_market_event_count']}`",
        f"- 本地模拟隔离: `{summary['local_simulation_isolated']}`",
        f"- 结论: {summary['plain_language_result']}",
        "",
        "## 本轮采集",
        "",
        "| 标的 | 周期 | 状态 | 时间 |",
        "|---|---:|---|---|",
    ]
    for row in ledger_rows[:80]:
        lines.append(
            f"| `{row.get('symbol', '')}` | `{row.get('timeframe', '')}` | "
            f"`{row.get('ingest_status', '')}` | `{row.get('event_time', '')}` |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 采集器只调用长桥只读 K 线命令。",
            "- 不读取账户、持仓、订单、资产或本地模拟账本。",
            "- 输出只作为实时信号路由器的行情事件输入。",
            "",
        ]
    )
    return "\n".join(lines)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def int_like(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
