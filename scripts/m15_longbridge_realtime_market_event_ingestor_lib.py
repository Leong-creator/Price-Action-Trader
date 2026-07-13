#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from scripts.longbridge_cli_env import build_longbridge_quote_cli_env
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
DEFAULT_MAX_MARKET_EVENT_FILE_BYTES = 60 * 1024 * 1024
DEFAULT_KEEP_MARKET_EVENT_LINES = 20000
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
    daily_refresh_interval_seconds: int
    daily_refresh_state_path: Path
    max_parallel_kline_requests: int
    kline_count: int
    kline_retry_attempts: int
    kline_retry_sleep_seconds: float
    watch_interval_seconds: int
    cli_timeout_seconds: int
    max_market_event_file_bytes: int
    keep_market_event_lines: int
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
        daily_refresh_interval_seconds=int(market_data.get("daily_refresh_interval_seconds", 0)),
        daily_refresh_state_path=resolve_repo_path(
            market_data.get("daily_refresh_state_path", output_dir / "m15_realtime_daily_refresh_state.json")
        ),
        max_parallel_kline_requests=int(market_data.get("max_parallel_kline_requests", 1)),
        kline_count=int(market_data.get("kline_count", 2)),
        kline_retry_attempts=int(market_data.get("kline_retry_attempts", 3)),
        kline_retry_sleep_seconds=float(market_data.get("kline_retry_sleep_seconds", 0.2)),
        watch_interval_seconds=int(market_data.get("watch_interval_seconds", 1)),
        cli_timeout_seconds=int(market_data.get("cli_timeout_seconds", 6)),
        max_market_event_file_bytes=int(
            market_data.get("max_market_event_file_bytes", DEFAULT_MAX_MARKET_EVENT_FILE_BYTES)
        ),
        keep_market_event_lines=int(market_data.get("keep_market_event_lines", DEFAULT_KEEP_MARKET_EVENT_LINES)),
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
    if config.kline_retry_attempts <= 0:
        raise ValueError("M15 realtime market event ingestor kline_retry_attempts must be positive")
    if config.kline_retry_sleep_seconds < 0:
        raise ValueError("M15 realtime market event ingestor kline_retry_sleep_seconds cannot be negative")
    if config.watch_interval_seconds <= 0:
        raise ValueError("M15 realtime market event ingestor watch interval must be positive")
    if config.daily_refresh_interval_seconds < 0:
        raise ValueError("M15 realtime daily refresh interval cannot be negative")
    if config.max_parallel_kline_requests <= 0:
        raise ValueError("M15 realtime max parallel kline requests must be positive")
    if config.cli_timeout_seconds <= 0:
        raise ValueError("M15 realtime market event ingestor CLI timeout must be positive")
    if config.max_market_event_file_bytes <= 0:
        raise ValueError("M15 realtime market event ingestor market event file byte limit must be positive")
    if config.keep_market_event_lines <= 0:
        raise ValueError("M15 realtime market event ingestor keep_market_event_lines must be positive")
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
    archive_before_path = rotate_market_events_if_needed(
        config.market_events_path,
        max_bytes=config.max_market_event_file_bytes,
        keep_lines=config.keep_market_event_lines,
    )

    existing_events = read_jsonl(config.market_events_path)
    existing_event_ids = {str(row.get("event_id")) for row in existing_events if row.get("event_id")}
    ledger_rows: list[dict[str, Any]] = []
    new_events: list[dict[str, Any]] = []
    deferred_rows: list[dict[str, Any]] = []
    binary = cli_path or shutil.which("longbridge")
    configured = configured_symbols(config)
    cycle_symbols = symbols_for_cycle(config, configured)
    cycle_timeframes = timeframes_for_cycle(config, now)

    if binary is None:
        deferred_rows.append({"scope": "market_data", "reason": "longbridge_cli_missing"})
    else:
        runner = command_runner or run_longbridge_json
        requests = [
            (symbol, timeframe, build_kline_args(config, symbol=symbol, timeframe=timeframe))
            for symbol in cycle_symbols
            for timeframe in cycle_timeframes
        ]
        results = run_kline_requests(config, runner, binary, requests)
        for symbol, timeframe, args, payload, retry_attempts_used, error in results:
                if error:
                    ledger_rows.append(
                        {
                            "stage": config.stage,
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "ingest_status": "deferred_longbridge_kline_failed",
                            "reason": error[:300],
                            "retry_attempts": config.kline_retry_attempts,
                            "readonly_command": ["longbridge", *args],
                        }
                    )
                    deferred_rows.append(
                        {
                            "scope": "kline",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "reason": "longbridge_kline_failed",
                            "detail": error[:300],
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
                            "retry_attempts": retry_attempts_used,
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
                            "retry_attempts": retry_attempts_used,
                            "readonly_command": ["longbridge", *args],
                            "local_simulation_ignored": True,
                            "account_or_order_command_used": False,
                        }
                    )

    write_jsonl(config.market_events_path, existing_events + new_events)
    archive_after_path = rotate_market_events_if_needed(
        config.market_events_path,
        max_bytes=config.max_market_event_file_bytes,
        keep_lines=config.keep_market_event_lines,
    )
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
        "cycle_timeframes": list(cycle_timeframes),
        "daily_refresh_interval_seconds": config.daily_refresh_interval_seconds,
        "max_parallel_kline_requests": config.max_parallel_kline_requests,
        "kline_retry_attempts": config.kline_retry_attempts,
        "existing_market_event_count": len(existing_events),
        "new_market_event_count": len(new_events),
        "market_event_total_count": len(existing_events) + len(new_events),
        "market_event_archive_before": project_path(archive_before_path) if archive_before_path else "",
        "market_event_archive_after": project_path(archive_after_path) if archive_after_path else "",
        "market_event_file_max_bytes": config.max_market_event_file_bytes,
        "market_event_keep_lines": config.keep_market_event_lines,
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


def timeframes_for_cycle(config: RealtimeMarketEventIngestorConfig, now: datetime) -> tuple[str, ...]:
    if "1d" not in config.timeframes or config.daily_refresh_interval_seconds == 0:
        return config.timeframes
    state = read_json(config.daily_refresh_state_path)
    last_daily_refresh = parse_optional_datetime(str(state.get("last_daily_refresh_at") or ""))
    elapsed_seconds = (now - last_daily_refresh).total_seconds() if last_daily_refresh else None
    daily_due = last_daily_refresh is None or elapsed_seconds is None or elapsed_seconds >= config.daily_refresh_interval_seconds
    if daily_due:
        config.daily_refresh_state_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            config.daily_refresh_state_path,
            {
                "schema_version": "m15.realtime-daily-refresh-state.v1",
                "last_daily_refresh_at": to_iso(now),
                "daily_refresh_interval_seconds": config.daily_refresh_interval_seconds,
            },
        )
        return config.timeframes
    return tuple(timeframe for timeframe in config.timeframes if timeframe != "1d")


def parse_optional_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return parse_utc_datetime(value)
    except ValueError:
        return None


def run_kline_requests(
    config: RealtimeMarketEventIngestorConfig,
    runner: CommandRunner,
    cli_path: str,
    requests: list[tuple[str, str, list[str]]],
) -> list[tuple[str, str, list[str], Any, int, str]]:
    def fetch(request: tuple[str, str, list[str]]) -> tuple[str, str, list[str], Any, int, str]:
        symbol, timeframe, args = request
        try:
            payload, retry_attempts = run_with_kline_retries(config, runner, cli_path, args)
            return symbol, timeframe, args, payload, retry_attempts, ""
        except Exception as exc:  # pragma: no cover - provider failure behavior
            return symbol, timeframe, args, [], config.kline_retry_attempts, str(exc)

    if config.max_parallel_kline_requests == 1 or len(requests) < 2:
        return [fetch(request) for request in requests]
    with ThreadPoolExecutor(max_workers=min(config.max_parallel_kline_requests, len(requests))) as executor:
        return list(executor.map(fetch, requests))


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


def run_with_kline_retries(
    config: RealtimeMarketEventIngestorConfig,
    runner: CommandRunner,
    cli_path: str,
    args: list[str],
) -> tuple[Any, int]:
    last_exc: Exception | None = None
    for attempt in range(1, config.kline_retry_attempts + 1):
        try:
            return runner(cli_path, args, config.cli_timeout_seconds), attempt
        except Exception as exc:
            last_exc = exc
            if attempt < config.kline_retry_attempts and config.kline_retry_sleep_seconds:
                time.sleep(config.kline_retry_sleep_seconds)
    raise RuntimeError(str(last_exc) if last_exc else "longbridge kline failed after retries")


def run_longbridge_json(cli_path: str, args: list[str], timeout_seconds: int) -> Any:
    _assert_readonly_command(args)
    process = subprocess.Popen(
        [cli_path, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=build_longbridge_quote_cli_env(),
        start_new_session=True,
    )
    try:
        stdout_text, stderr_text = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        process.communicate()
        raise RuntimeError(f"longbridge {' '.join(args)} timed out after {timeout_seconds}s") from exc
    if process.returncode != 0:
        detail = clean_cli_text((stderr_text or stdout_text or "").strip())
        raise RuntimeError(detail or f"longbridge {' '.join(args)} failed with {process.returncode}")
    stdout = stdout_text.strip()
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


def rotate_market_events_if_needed(path: Path, *, max_bytes: int, keep_lines: int) -> Path | None:
    if not path.exists() or path.stat().st_size <= max_bytes:
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= keep_lines:
        return None
    archive_dir = path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = archive_dir / f"{path.stem}.{timestamp}.archived.jsonl"
    archived_lines = lines[:-keep_lines]
    kept_lines = lines[-keep_lines:]
    tmp_archive = archive_path.with_name(f".{archive_path.name}.{os.getpid()}.tmp")
    tmp_current = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_archive.write_text("\n".join(archived_lines) + "\n", encoding="utf-8")
    tmp_current.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
    tmp_archive.replace(archive_path)
    tmp_current.replace(path)
    return archive_path


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    tmp_path.replace(path)
