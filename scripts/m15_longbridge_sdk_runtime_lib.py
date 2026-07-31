#!/usr/bin/env python3
"""Persistent SDK market-data runtime for the isolated M15 paper chain.

The module intentionally keeps the existing JSONL market-event contract.  It
does not read local simulation artifacts and it never falls back to CLI K-line
polling for a new paper entry when the SDK connection is unavailable.
"""
from __future__ import annotations

import json
import os
import hashlib
from collections import Counter, deque
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from pathlib import Path
from time import monotonic, perf_counter, sleep
from typing import Any, Callable
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_realtime_execution_lib import DEFAULT_DAILY_DIR, longbridge_symbol, parse_utc_datetime, to_iso
from scripts.m15_longbridge_realtime_market_event_ingestor_lib import US_LIQUID_SEED_V1
from scripts.m15_universe_lib import load_m15_universe

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_sdk_runtime.json"
SUMMARY_JSON = "m15_longbridge_sdk_runtime.json"
NEW_YORK = ZoneInfo("America/New_York")
RUNTIME_CODE_PATHS = (
    ROOT / "scripts" / "m15_longbridge_sdk_runtime_lib.py",
    ROOT / "scripts" / "run_m15_longbridge_sdk_runtime.py",
    ROOT / "scripts" / "m15_longbridge_sdk_account_lib.py",
    ROOT / "scripts" / "m15_longbridge_sdk_account_worker_lib.py",
    ROOT / "scripts" / "m15_longbridge_fill_attribution_lib.py",
    ROOT / "scripts" / "m15_longbridge_realtime_signal_router_lib.py",
    ROOT / "scripts" / "m15_longbridge_realtime_execution_lib.py",
    ROOT / "scripts" / "m15_longbridge_realtime_position_manager_lib.py",
    ROOT / "scripts" / "m15_longbridge_realtime_market_event_ingestor_lib.py",
    ROOT / "scripts" / "m12_liquid_universe_scanner_lib.py",
    ROOT / "scripts" / "m15_universe_lib.py",
)


@dataclass(frozen=True, slots=True)
class SdkRuntimeConfig:
    config_path: Path
    output_dir: Path
    market_events_path: Path
    runtime_status_path: Path
    readonly_gate_path: Path
    client_id_file: Path
    quote_region: str
    trade_region: str
    market: str
    use_seed_universe: bool
    universe_path: Path | None
    symbol_limit: int
    trading_symbol_limit: int
    bar_minutes: int
    maximum_source_delivery_age_ms: int
    event_keep_lines: int
    daily_context_path: Path
    daily_context_bars: int
    daily_context_deadline_seconds: int
    daily_context_parallel_workers: int
    daily_context_batch_size: int
    daily_context_retry_count: int
    heartbeat_interval_seconds: int
    reconnect_backoff_seconds: int
    subscription_batch_size: int
    subscription_retry_count: int
    subscription_request_interval_seconds: float
    subscription_retry_backoff_seconds: float
    subscription_deadline_seconds: int
    maximum_consecutive_subscription_failures: int
    snapshot_poll_interval_seconds: float
    subscription_failures_before_snapshot_fallback: int
    snapshot_poll_dispatch_max_elapsed_ms: int
    snapshot_poll_min_successful_cycles: int
    market_data_heartbeat_deadline_seconds: int
    account_snapshot_interval_seconds: int
    account_snapshot_refresh_deadline_seconds: int
    account_snapshot_circuit_retry_seconds: int
    maximum_account_snapshot_age_seconds: int
    two_day_readonly_gate: bool
    router_config_path: Path
    execution_config_path: Path
    account_state_config_path: Path
    position_manager_config_path: Path
    stale_order_cleanup_config_path: Path
    paper_order_dispatch_enabled: bool
    paper_trading_only: bool
    live_execution: bool
    real_money_actions: bool
    enable_trade_private_push: bool
    account_maintenance_interval_seconds: int
    stale_entry_order_ttl_seconds: int
    exit_order_reprice_seconds: int
    formal_test_transition_enabled: bool
    formal_test_epoch_id: str
    formal_short_test_epoch_id: str
    formal_test_marker_path: Path
    formal_test_epoch_state_path: Path
    trading_universe_path: Path | None = None


def resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> SdkRuntimeConfig:
    config_path = resolve_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    outputs = payload.get("outputs", {})
    oauth = payload.get("oauth", {})
    market_data = payload.get("market_data", {})
    runtime = payload.get("runtime", {})
    routing = payload.get("routing", {})
    transition = payload.get("formal_test_transition", {})
    config = SdkRuntimeConfig(
        config_path=config_path,
        output_dir=resolve_path(outputs["output_dir"]),
        market_events_path=resolve_path(outputs["market_events"]),
        runtime_status_path=resolve_path(outputs["runtime_status"]),
        readonly_gate_path=resolve_path(outputs.get("readonly_gate", "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m15_longbridge_realtime_execution/m15_sdk_readonly_gate.json")),
        client_id_file=Path(str(oauth["client_id_file"])).expanduser(),
        quote_region=str(oauth.get("quote_region", "cn")),
        trade_region=str(oauth.get("trade_region", "cn")),
        market=str(market_data.get("market", "US")).upper(),
        use_seed_universe=bool(market_data.get("use_seed_universe", True)),
        universe_path=(
            resolve_path(market_data["universe_path"])
            if market_data.get("universe_path")
            else None
        ),
        symbol_limit=int(market_data.get("symbol_limit", 147)),
        trading_symbol_limit=int(market_data.get("trading_symbol_limit", market_data.get("symbol_limit", 147))),
        bar_minutes=int(market_data.get("bar_minutes", 5)),
        maximum_source_delivery_age_ms=int(market_data.get("maximum_source_delivery_age_ms", 2000)),
        event_keep_lines=int(market_data.get("event_keep_lines", 20000)),
        daily_context_path=resolve_path(market_data.get("daily_context", "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m15_longbridge_realtime_execution/m15_sdk_daily_context.jsonl")),
        daily_context_bars=int(market_data.get("daily_context_bars", 60)),
        daily_context_deadline_seconds=int(market_data.get("daily_context_deadline_seconds", 180)),
        daily_context_parallel_workers=int(market_data.get("daily_context_parallel_workers", 3)),
        daily_context_batch_size=int(market_data.get("daily_context_batch_size", 10)),
        daily_context_retry_count=int(market_data.get("daily_context_retry_count", 5)),
        heartbeat_interval_seconds=int(runtime.get("heartbeat_interval_seconds", 5)),
        reconnect_backoff_seconds=int(runtime.get("reconnect_backoff_seconds", 5)),
        subscription_batch_size=int(runtime.get("subscription_batch_size", 10)),
        subscription_retry_count=int(runtime.get("subscription_retry_count", 2)),
        subscription_request_interval_seconds=float(
            runtime.get("subscription_request_interval_seconds", 0.5)
        ),
        subscription_retry_backoff_seconds=float(
            runtime.get("subscription_retry_backoff_seconds", 2)
        ),
        subscription_deadline_seconds=int(runtime.get("subscription_deadline_seconds", 20)),
        maximum_consecutive_subscription_failures=int(runtime.get("maximum_consecutive_subscription_failures", 3)),
        snapshot_poll_interval_seconds=float(
            runtime.get("snapshot_poll_interval_seconds", 1)
        ),
        subscription_failures_before_snapshot_fallback=int(
            runtime.get("subscription_failures_before_snapshot_fallback", 1)
        ),
        snapshot_poll_dispatch_max_elapsed_ms=int(
            runtime.get("snapshot_poll_dispatch_max_elapsed_ms", 1000)
        ),
        snapshot_poll_min_successful_cycles=int(
            runtime.get("snapshot_poll_min_successful_cycles", 5)
        ),
        market_data_heartbeat_deadline_seconds=int(
            runtime.get("market_data_heartbeat_deadline_seconds", 5)
        ),
        account_snapshot_interval_seconds=int(runtime.get("account_snapshot_interval_seconds", 15)),
        account_snapshot_refresh_deadline_seconds=int(runtime.get("account_snapshot_refresh_deadline_seconds", 8)),
        account_snapshot_circuit_retry_seconds=int(runtime.get("account_snapshot_circuit_retry_seconds", 15)),
        maximum_account_snapshot_age_seconds=int(runtime.get("maximum_account_snapshot_age_seconds", 45)),
        two_day_readonly_gate=bool(runtime.get("two_day_readonly_gate", True)),
        router_config_path=resolve_path(routing.get("router_config", "config/examples/m15_longbridge_realtime_signal_router.json")),
        execution_config_path=resolve_path(
            routing.get("execution_config", "config/examples/m15_longbridge_realtime_execution.paper_orders_enabled.json")
        ),
        account_state_config_path=resolve_path(
            routing.get("account_state_config", "config/examples/m15_longbridge_realtime_account_state.json")
        ),
        position_manager_config_path=resolve_path(
            routing.get("position_manager_config", "config/examples/m15_longbridge_realtime_position_manager.json")
        ),
        stale_order_cleanup_config_path=resolve_path(
            routing.get("stale_order_cleanup_config", "config/examples/m15_longbridge_realtime_stale_order_cleanup.json")
        ),
        paper_order_dispatch_enabled=bool(routing.get("paper_order_dispatch_enabled", False)),
        paper_trading_only=bool(runtime.get("paper_trading_only", True)),
        live_execution=bool(runtime.get("live_execution", False)),
        real_money_actions=bool(runtime.get("real_money_actions", False)),
        enable_trade_private_push=bool(runtime.get("enable_trade_private_push", False)),
        account_maintenance_interval_seconds=int(runtime.get("account_maintenance_interval_seconds", 60)),
        stale_entry_order_ttl_seconds=int(runtime.get("stale_entry_order_ttl_seconds", 900)),
        exit_order_reprice_seconds=int(runtime.get("exit_order_reprice_seconds", 60)),
        formal_test_transition_enabled=bool(transition.get("enabled", False)),
        formal_test_epoch_id=str(transition.get("test_epoch_id") or ""),
        formal_short_test_epoch_id=str(transition.get("short_test_epoch_id") or ""),
        formal_test_marker_path=resolve_path(
            transition.get(
                "marker_path",
                "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/"
                "m15_longbridge_realtime_execution/m15_sdk_formal_test_epoch.json",
            )
        ),
        formal_test_epoch_state_path=resolve_path(
            transition.get(
                "epoch_state_path",
                "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/"
                "m15_longbridge_realtime_execution/m15_longbridge_virtual_account_epoch.json",
            )
        ),
        trading_universe_path=(
            resolve_path(market_data["trading_universe_path"])
            if market_data.get("trading_universe_path")
            else None
        ),
    )
    if not config.paper_trading_only or config.live_execution or config.real_money_actions:
        raise ValueError("M15 SDK runtime must remain paper-only")
    if config.symbol_limit <= 0 or config.symbol_limit > 500:
        raise ValueError("M15 SDK runtime symbol_limit must be between 1 and 500")
    if config.trading_symbol_limit <= 0 or config.trading_symbol_limit > config.symbol_limit:
        raise ValueError("M15 SDK runtime trading_symbol_limit must be between 1 and symbol_limit")
    if config.trading_symbol_limit > 147:
        upgrade_gate = market_data.get("expansion_trade_pool_upgrade_gate") or {}
        required_coverage = f"{config.symbol_limit}/{config.symbol_limit}"
        if (
            upgrade_gate.get("enabled") is not True
            or upgrade_gate.get("required_readonly_gate_passed") is not True
            or upgrade_gate.get("required_complete_trading_daily_context") is not True
            or upgrade_gate.get("required_complete_subscribed_daily_context") is not True
            or str(upgrade_gate.get("required_subscription_coverage") or "")
            != required_coverage
            or int(upgrade_gate.get("target_trading_symbol_limit") or 0)
            != config.trading_symbol_limit
        ):
            raise ValueError(
                "M15 SDK expanded trading universe requires a complete upgrade gate"
            )
    if config.universe_path is not None:
        universe_symbols = load_m15_universe(config.universe_path)
        if config.symbol_limit > len(universe_symbols):
            raise ValueError("M15 SDK runtime symbol_limit exceeds universe file length")
    if config.trading_universe_path is not None:
        trading_symbols = load_m15_universe(config.trading_universe_path)
        if len(trading_symbols) != config.trading_symbol_limit:
            raise ValueError(
                "M15 SDK frozen trading universe size must equal trading_symbol_limit"
            )
        subscribed_symbols = {
            symbol.removesuffix(f".{config.market}")
            for symbol in configured_symbols(config)
        }
        missing = sorted(set(trading_symbols) - subscribed_symbols)
        if missing:
            raise ValueError(
                "M15 SDK frozen trading universe contains unsubscribed symbols:"
                + ",".join(missing)
            )
    if config.bar_minutes != 5:
        raise ValueError("M15 SDK runtime currently supports only 5-minute bars")
    if config.account_maintenance_interval_seconds <= 0:
        raise ValueError("M15 SDK account maintenance interval must be positive")
    if config.stale_entry_order_ttl_seconds <= 0:
        raise ValueError("M15 SDK stale entry order TTL must be positive")
    if config.exit_order_reprice_seconds <= 0:
        raise ValueError("M15 SDK exit order reprice interval must be positive")
    if config.subscription_batch_size <= 0 or config.subscription_batch_size > 50:
        raise ValueError("M15 SDK subscription batch size must be between 1 and 50")
    if not 0 <= config.subscription_request_interval_seconds <= 5:
        raise ValueError("M15 SDK subscription request interval must be between 0 and 5 seconds")
    if not 0 <= config.subscription_retry_backoff_seconds <= 10:
        raise ValueError("M15 SDK subscription retry backoff must be between 0 and 10 seconds")
    if config.subscription_retry_count < 0 or config.subscription_retry_count > 5:
        raise ValueError("M15 SDK subscription retry count must be between 0 and 5")
    if config.subscription_deadline_seconds <= 0:
        raise ValueError("M15 SDK subscription deadline must be positive")
    if config.maximum_consecutive_subscription_failures <= 0:
        raise ValueError("M15 SDK consecutive subscription failure limit must be positive")
    if not 0.5 <= config.snapshot_poll_interval_seconds <= 5:
        raise ValueError("M15 SDK snapshot poll interval must be between 0.5 and 5 seconds")
    if (
        config.subscription_failures_before_snapshot_fallback <= 0
        or config.subscription_failures_before_snapshot_fallback
        > config.maximum_consecutive_subscription_failures
    ):
        raise ValueError(
            "M15 SDK snapshot fallback threshold must be within the subscription failure limit"
        )
    if config.snapshot_poll_dispatch_max_elapsed_ms <= 0:
        raise ValueError("M15 SDK snapshot poll dispatch latency limit must be positive")
    if not 1 <= config.snapshot_poll_min_successful_cycles <= 30:
        raise ValueError(
            "M15 SDK snapshot poll validation cycles must be between 1 and 30"
        )
    if (
        config.market_data_heartbeat_deadline_seconds
        <= config.snapshot_poll_interval_seconds
    ):
        raise ValueError(
            "M15 SDK market data heartbeat deadline must exceed the snapshot interval"
        )
    if config.daily_context_bars < 2:
        raise ValueError("M15 SDK daily context needs at least two bars")
    if config.daily_context_deadline_seconds <= 0:
        raise ValueError("M15 SDK daily context deadline must be positive")
    if config.daily_context_parallel_workers <= 0 or config.daily_context_parallel_workers > 4:
        raise ValueError("M15 SDK daily context parallel workers must be between 1 and 4")
    if config.daily_context_batch_size <= 0 or config.daily_context_batch_size > 25:
        raise ValueError("M15 SDK daily context batch size must be between 1 and 25")
    if config.daily_context_retry_count < 0 or config.daily_context_retry_count > 10:
        raise ValueError("M15 SDK daily context retry count must be between 0 and 10")
    if config.account_snapshot_interval_seconds <= 0 or config.maximum_account_snapshot_age_seconds < config.account_snapshot_interval_seconds:
        raise ValueError("M15 SDK account snapshot timing is invalid")
    if config.account_snapshot_refresh_deadline_seconds <= 0:
        raise ValueError("M15 SDK account snapshot refresh deadline must be positive")
    if config.account_snapshot_refresh_deadline_seconds >= config.maximum_account_snapshot_age_seconds:
        raise ValueError("M15 SDK account snapshot refresh deadline must stay below the maximum snapshot age")
    if config.account_snapshot_circuit_retry_seconds <= 0:
        raise ValueError("M15 SDK account snapshot circuit retry interval must be positive")
    if config.formal_test_transition_enabled and (
        not config.formal_test_epoch_id or not config.formal_short_test_epoch_id
    ):
        raise ValueError("M15 SDK formal test transition requires both epoch ids")
    validate_formal_epoch_alignment(config)
    return config


def validate_formal_epoch_alignment(config: SdkRuntimeConfig) -> None:
    if not config.formal_test_transition_enabled:
        return
    try:
        execution = json.loads(config.execution_config_path.read_text(encoding="utf-8"))
        router = json.loads(config.router_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"M15 SDK formal epoch linked config unreadable:{exc}") from exc
    execution_epoch = str((execution.get("test_epoch") or {}).get("test_epoch_id") or "")
    execution_short_epoch = str((execution.get("paper_short_testing") or {}).get("test_epoch_id") or "")
    router_short_epoch = str((router.get("paper_short_testing") or {}).get("test_epoch_id") or "")
    if execution_epoch != config.formal_test_epoch_id:
        raise ValueError("M15 SDK formal long epoch does not match execution config")
    if execution_short_epoch != config.formal_short_test_epoch_id:
        raise ValueError("M15 SDK formal short epoch does not match execution config")
    if router_short_epoch != config.formal_short_test_epoch_id:
        raise ValueError("M15 SDK formal short epoch does not match router config")


def configured_symbols(config: SdkRuntimeConfig) -> tuple[str, ...]:
    if config.universe_path is not None:
        symbols = load_m15_universe(config.universe_path)
        return tuple(f"{symbol}.{config.market}" for symbol in symbols[: config.symbol_limit])
    if not config.use_seed_universe:
        return ()
    return tuple(f"{symbol}.{config.market}" for symbol in US_LIQUID_SEED_V1[: config.symbol_limit])


def configured_trading_symbols(config: SdkRuntimeConfig) -> tuple[str, ...]:
    """Return the independently frozen symbols allowed to reach strategy routing."""
    trading_universe_path = getattr(config, "trading_universe_path", None)
    if trading_universe_path is not None:
        return tuple(
            f"{symbol}.{config.market}"
            for symbol in load_m15_universe(trading_universe_path)
        )
    return configured_symbols(config)[: config.trading_symbol_limit]


def trading_universe_fingerprint(config: SdkRuntimeConfig) -> str:
    payload = "\n".join(configured_trading_symbols(config)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def trading_market_events(
    config: SdkRuntimeConfig,
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    """Keep only events that are explicitly allowed to reach strategy routing."""
    allowed = {symbol.upper() for symbol in configured_trading_symbols(config)}
    return [
        row
        for row in rows
        if not str(row.get("market_data_blocked_reason") or "")
        if f"{str(row.get('symbol') or '').upper().removesuffix(f'.{config.market}')}.{config.market}" in allowed
    ]


def market_event_is_tradable(config: SdkRuntimeConfig, row: dict[str, Any]) -> bool:
    return bool(trading_market_events(config, [row]))


def daily_context_row_count_for_symbols(
    config: SdkRuntimeConfig,
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    symbols: tuple[str, ...] | list[str],
) -> int:
    expected = {
        str(symbol).upper().removesuffix(f".{config.market}")
        for symbol in symbols
    }
    return sum(
        1
        for row in rows
        if str(row.get("timeframe") or "") == "1d"
        and str(row.get("symbol") or "").upper().removesuffix(f".{config.market}") in expected
    )


def daily_context_covers_symbols(
    config: SdkRuntimeConfig,
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    symbols: tuple[str, ...] | list[str],
    failed_symbols: list[str] | tuple[str, ...],
) -> bool:
    """Check a symbol subset without requiring readonly expansion rows."""
    expected = {
        str(symbol).upper().removesuffix(f".{config.market}")
        for symbol in symbols
    }
    failed = {
        str(symbol).upper().removesuffix(f".{config.market}")
        for symbol in failed_symbols
    }
    if not expected or expected & failed:
        return False
    counts = Counter(
        str(row.get("symbol") or "").upper().removesuffix(f".{config.market}")
        for row in rows
        if str(row.get("timeframe") or "") == "1d"
    )
    return all(counts[symbol] >= config.daily_context_bars for symbol in expected)


def daily_context_is_complete(
    config: SdkRuntimeConfig,
    state: str,
    row_count: int,
    failed_symbols: list[str] | tuple[str, ...],
) -> bool:
    """Require the full daily input before allowing SDK order dispatch."""
    expected_rows = len(configured_symbols(config)) * config.daily_context_bars
    return state == "complete" and not failed_symbols and row_count >= expected_rows


def required_daily_context_date(now: datetime) -> str:
    """Return the latest completed US session date needed by daily strategies."""
    local = now.astimezone(NEW_YORK)
    candidate = local.date()
    if local.weekday() < 5 and (local.hour, local.minute) >= (16, 10):
        return candidate.isoformat()
    candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate.isoformat()


def load_valid_daily_context_cache(path: Path, config: SdkRuntimeConfig, now: datetime) -> list[dict[str, Any]]:
    """Reuse only a complete cache containing the latest completed daily bar."""
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []
    expected_symbols = {symbol.removesuffix(f".{config.market}") for symbol in configured_symbols(config)}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("timeframe") != "1d":
            return []
        symbol = str(row.get("symbol") or "")
        grouped.setdefault(symbol, []).append(row)
    if set(grouped) != expected_symbols:
        return []
    if any(len(symbol_rows) != config.daily_context_bars for symbol_rows in grouped.values()):
        return []
    required_date = required_daily_context_date(now)
    for symbol_rows in grouped.values():
        latest = max(str(row.get("event_time") or "") for row in symbol_rows)
        try:
            latest_date = datetime.fromisoformat(latest.replace("Z", "+00:00")).astimezone(NEW_YORK).date().isoformat()
        except ValueError:
            return []
        if latest_date < required_date:
            return []
    return rows


def write_daily_context_cache(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    temporary.replace(path)


def config_fingerprint(config: SdkRuntimeConfig) -> str:
    """Stable identity used by watchdog/readiness to reject runtime drift."""
    loaded_values: dict[str, Any] = {}
    for field in fields(config):
        value = getattr(config, field.name)
        if isinstance(value, Path):
            loaded_values[field.name] = str(value.resolve())
        elif isinstance(value, tuple):
            loaded_values[field.name] = list(value)
        else:
            loaded_values[field.name] = value
    linked_files = {}
    linked_paths = [
        config.config_path,
        config.router_config_path,
        config.execution_config_path,
        config.account_state_config_path,
        config.position_manager_config_path,
        config.stale_order_cleanup_config_path,
    ]
    if config.universe_path is not None:
        linked_paths.append(config.universe_path)
    for path in linked_paths:
        try:
            linked_files[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            linked_files[str(path.resolve())] = "missing"
    runtime_code_files = {}
    for path in RUNTIME_CODE_PATHS:
        try:
            runtime_code_files[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            runtime_code_files[str(path.resolve())] = "missing"
    payload = {
        "loaded_values": loaded_values,
        "linked_files": linked_files,
        "runtime_code_files": runtime_code_files,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def load_readonly_gate(path: Path, *, required_sessions: int = 2) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    completed = payload.get("completed_sessions", [])
    return {
        "schema_version": "m15.sdk-readonly-gate.v1",
        "required_sessions": required_sessions,
        "completed_sessions": [item for item in completed if isinstance(item, dict)],
    }


def record_readonly_session(
    path: Path,
    session_date: str,
    evidence: dict[str, Any],
    *,
    required_sessions: int = 2,
) -> dict[str, Any]:
    """Persist one completed regular-session SDK validation, once per date."""
    gate = load_readonly_gate(path, required_sessions=required_sessions)
    sessions = [item for item in gate["completed_sessions"] if item.get("session_date") != session_date]
    sessions.append({"session_date": session_date, **evidence})
    sessions.sort(key=lambda item: str(item.get("session_date") or ""))
    gate["completed_sessions"] = sessions[-10:]
    gate["passed"] = len(gate["completed_sessions"]) >= int(gate["required_sessions"])
    gate["generated_at"] = to_iso(datetime.now(UTC))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return gate


def readonly_gate_passed(path: Path, *, required_sessions: int = 2) -> tuple[bool, int, int]:
    gate = load_readonly_gate(path, required_sessions=required_sessions)
    completed = len(gate["completed_sessions"])
    required = int(gate["required_sessions"])
    return completed >= required, completed, required


def floor_bar_open(value: datetime, minutes: int) -> datetime:
    value = value.astimezone(NEW_YORK)
    minute = value.minute - value.minute % minutes
    return value.replace(minute=minute, second=0, microsecond=0)


class FiveMinuteBarBuilder:
    """Build final regular-session bars from SDK quote/trade pushes."""

    def __init__(
        self,
        minutes: int = 5,
        *,
        complete_bar_open_not_before: datetime | None = None,
    ) -> None:
        self.minutes = minutes
        self.complete_bar_open_not_before = (
            complete_bar_open_not_before.astimezone(NEW_YORK)
            if complete_bar_open_not_before is not None
            else None
        )
        self._bars: dict[tuple[str, datetime], dict[str, Any]] = {}
        self._quote_total_volume: dict[str, int] = {}
        self._quote_last_source_at: dict[str, datetime] = {}
        self._snapshot_total_volume: dict[str, int] = {}

    @property
    def open_bar_count(self) -> int:
        return len(self._bars)

    def on_quote(self, symbol: str, payload: dict[str, Any], *, received_at: datetime) -> list[dict[str, Any]]:
        source_at = unix_to_utc(payload.get("timestamp"), received_at)
        price = decimal(payload.get("last_done"))
        if price <= Decimal("0"):
            return []
        normalized_symbol = symbol.upper()
        volume, blocked_reason = self._quote_volume_delta(
            normalized_symbol,
            payload,
            source_at=source_at,
        )
        return self._append(
            symbol,
            source_at,
            received_at,
            price,
            volume,
            source_mode="longbridge_sdk_push",
            blocked_reason=blocked_reason,
        )

    def on_snapshot(
        self,
        symbol: str,
        payload: dict[str, Any],
        *,
        received_at: datetime,
    ) -> list[dict[str, Any]]:
        """Aggregate one SDK quote snapshot without treating total volume as an increment."""
        source_at = unix_to_utc(payload.get("timestamp"), received_at)
        price = decimal(payload.get("last_done"))
        if price <= Decimal("0"):
            return []
        normalized_symbol = symbol.upper()
        total_volume = max(0, int_like(payload.get("volume")))
        previous_total = self._snapshot_total_volume.get(normalized_symbol)
        self._snapshot_total_volume[normalized_symbol] = total_volume
        volume_delta = (
            max(0, total_volume - previous_total)
            if previous_total is not None
            else 0
        )
        return self._append(
            symbol,
            source_at,
            received_at,
            price,
            volume_delta,
            source_mode="longbridge_sdk_snapshot_poll",
            bar_at=received_at,
        )

    def on_trade(self, symbol: str, payload: dict[str, Any], *, received_at: datetime) -> list[dict[str, Any]]:
        finished: list[dict[str, Any]] = []
        for trade in payload.get("trades", []) if isinstance(payload.get("trades"), list) else []:
            source_at = unix_to_utc(trade.get("timestamp"), received_at)
            price = decimal(trade.get("price"))
            if price > Decimal("0"):
                finished.extend(
                    self._append(
                        symbol,
                        source_at,
                        received_at,
                        price,
                        int_like(trade.get("volume")),
                        source_mode="longbridge_sdk_push",
                    )
                )
        return finished

    def flush(self, now: datetime) -> list[dict[str, Any]]:
        completed: list[dict[str, Any]] = []
        for key, bar in list(self._bars.items()):
            if bar["bar_close_at"] <= now.astimezone(NEW_YORK):
                completed.append(self._finalize(key, bar, emitted_at=now))
        return completed

    def _append(
        self,
        symbol: str,
        source_at: datetime,
        received_at: datetime,
        price: Decimal,
        volume: int,
        *,
        source_mode: str,
        bar_at: datetime | None = None,
        blocked_reason: str = "",
    ) -> list[dict[str, Any]]:
        bar_clock_ny = (bar_at or source_at).astimezone(NEW_YORK)
        if bar_clock_ny.weekday() >= 5 or not (bar_clock_ny.hour > 9 or (bar_clock_ny.hour == 9 and bar_clock_ny.minute >= 30)) or bar_clock_ny.hour >= 16:
            return []
        bar_open = floor_bar_open(bar_clock_ny, self.minutes)
        if self.complete_bar_open_not_before is not None and bar_open < self.complete_bar_open_not_before:
            return self.flush(received_at)
        key = (symbol.upper(), bar_open)
        bar = self._bars.get(key)
        if bar is None:
            bar = {
                "symbol": symbol.upper(), "bar_open_at": bar_open, "bar_close_at": bar_open + timedelta(minutes=self.minutes),
                "open": price, "high": price, "low": price, "close": price, "volume": 0,
                "source_event_at": source_at, "received_at": received_at,
                "source_mode": source_mode,
                "market_data_blocked_reasons": set(),
            }
            self._bars[key] = bar
        else:
            bar["high"] = max(bar["high"], price)
            bar["low"] = min(bar["low"], price)
            bar["close"] = price
            bar["source_event_at"] = max(bar["source_event_at"], source_at)
            bar["received_at"] = max(bar["received_at"], received_at)
        bar["volume"] += max(0, volume)
        if blocked_reason:
            bar["market_data_blocked_reasons"].add(blocked_reason)
        return self.flush(received_at)

    def _finalize(self, key: tuple[str, datetime], bar: dict[str, Any], *, emitted_at: datetime) -> dict[str, Any]:
        self._bars.pop(key, None)
        source_at = bar["source_event_at"]
        # A final bar is executable only once its interval has actually
        # closed. The last quote timestamp is source evidence, not delivery.
        received_at = emitted_at.astimezone(UTC)
        event_id = f"sdk-5m|{bar['symbol']}|{to_iso(bar['bar_close_at'].astimezone(UTC))}"
        return {
            "schema_version": "m15.realtime-market-event.v2",
            "event_id": event_id,
            "symbol": bar["symbol"].replace(".US", ""),
            "timeframe": "5m",
            "event_time": to_iso(bar["bar_close_at"].astimezone(UTC)),
            "bar_open_at": to_iso(bar["bar_open_at"].astimezone(UTC)),
            "bar_close_at": to_iso(bar["bar_close_at"].astimezone(UTC)),
            "source_event_at": to_iso(source_at),
            "received_at": to_iso(received_at),
            "source_delivery_age_ms": max(0, int((received_at - source_at).total_seconds() * 1000)),
            "bar_final": True,
            "source_mode": str(bar.get("source_mode") or "longbridge_sdk_push"),
            "open": fmt(bar["open"]), "high": fmt(bar["high"]), "low": fmt(bar["low"]),
            "close": fmt(bar["close"]), "volume": str(bar["volume"]),
            "market_data_blocked_reason": ",".join(sorted(bar.get("market_data_blocked_reasons") or ())),
            "local_simulation_ignored": True,
        }

    def _quote_volume_delta(
        self,
        symbol: str,
        payload: dict[str, Any],
        *,
        source_at: datetime,
    ) -> tuple[int, str]:
        raw_total = payload.get("volume")
        if raw_total in (None, ""):
            return 0, "quote_total_volume_missing"
        total_volume = max(0, int_like(raw_total))
        previous_total = self._quote_total_volume.get(symbol)
        previous_source_at = self._quote_last_source_at.get(symbol)
        if previous_source_at is not None and source_at < previous_source_at:
            return 0, "quote_timestamp_regressed"
        if previous_total is not None and total_volume < previous_total:
            return 0, "quote_total_volume_regressed"
        self._quote_last_source_at[symbol] = source_at
        self._quote_total_volume[symbol] = total_volume
        if previous_total is None:
            return 0, ""
        return total_volume - previous_total, ""


class MarketEventContext:
    """Bounded in-memory context for SDK-driven strategy evaluation."""

    def __init__(self, rows: list[dict[str, Any]] | None = None, *, maximum_rows: int = 4096) -> None:
        self.maximum_rows = maximum_rows
        self._rows: deque[dict[str, Any]] = deque()
        self._event_ids: set[str] = set()
        self.append(rows or [])

    def append(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        appended: list[dict[str, Any]] = []
        for row in rows:
            event_id = str(row.get("event_id") or "")
            if not event_id or event_id in self._event_ids:
                continue
            self._rows.append(row)
            self._event_ids.add(event_id)
            appended.append(row)
            while len(self._rows) > self.maximum_rows:
                removed = self._rows.popleft()
                self._event_ids.discard(str(removed.get("event_id") or ""))
        return appended

    def rows(self) -> list[dict[str, Any]]:
        return list(self._rows)


def append_market_events(path: Path, rows: list[dict[str, Any]], keep_lines: int) -> None:
    """Append finalized SDK bars without rereading the audit stream.

    The router de-duplicates event IDs and the SDK event IDs are deterministic,
    so the hot path must not scan or rewrite historical JSONL on every bar.
    Retention compaction is deliberately performed by the heartbeat, outside
    the quote callback.
    """
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_current_sdk_intraday_context(
    path: Path,
    session_started_at: datetime,
    *,
    bars_per_symbol: int = 20,
) -> list[dict[str, Any]]:
    """Restore a bounded same-session SDK bar history after a runtime restart.

    These rows are context only: the dispatcher receives only bars delivered
    after startup, so no historical signal or order can be replayed.
    """
    if bars_per_symbol <= 0 or not path.exists():
        return []
    session_start = session_started_at.astimezone(UTC)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
            received_at = datetime.fromisoformat(str(row.get("received_at") or "").replace("Z", "+00:00"))
        except (ValueError, json.JSONDecodeError):
            continue
        if received_at.astimezone(UTC) < session_start:
            continue
        if (
            str(row.get("source_mode") or "")
            not in {"longbridge_sdk_push", "longbridge_sdk_snapshot_poll"}
            or str(row.get("timeframe") or "") != "5m"
            or not bool(row.get("bar_final"))
            or str(row.get("market_data_blocked_reason") or "")
        ):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        grouped.setdefault((symbol, "5m"), []).append(row)
    restored: list[dict[str, Any]] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: str(row.get("event_time") or row.get("received_at") or ""))
        restored.extend(rows[-bars_per_symbol:])
    return sorted(restored, key=lambda row: (str(row.get("event_time") or ""), str(row.get("symbol") or "")))


def fresh_market_events(
    rows: list[dict[str, Any]],
    maximum_age_ms: int,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Reject delayed pushes without discarding a freshly finalized bar.

    A quote timestamp is evidence for the price within a five-minute bar, not
    the time at which the completed bar is delivered.  Liquid symbols can
    legitimately have no new quote in the final seconds of an interval.  SDK
    bars are therefore checked against their finalization time, while raw and
    non-SDK events retain the source-delivery-age guard.
    """
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    fresh: list[dict[str, Any]] = []
    for row in rows:
        is_final_sdk_bar = (
            bool(row.get("bar_final"))
            and str(row.get("source_mode") or "")
            in {"longbridge_sdk_push", "longbridge_sdk_snapshot_poll"}
            and str(row.get("timeframe") or "") == "5m"
        )
        if is_final_sdk_bar:
            try:
                finalized_at = datetime.fromisoformat(str(row.get("received_at") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            finalization_age_ms = max(0, int((checked_at - finalized_at.astimezone(UTC)).total_seconds() * 1000))
            if finalization_age_ms <= maximum_age_ms:
                fresh.append(row)
            continue
        if int_like(row.get("source_delivery_age_ms")) <= maximum_age_ms:
            fresh.append(row)
    return fresh


def compact_market_events(path: Path, keep_lines: int) -> None:
    """Keep the event audit file bounded from the low-frequency heartbeat."""
    if keep_lines <= 0 or not path.exists():
        return
    lines = tail_lines(path, keep_lines + 1)
    if len(lines) <= keep_lines:
        return
    tmp = path.with_suffix(path.suffix + ".compact.tmp")
    tmp.write_text("\n".join(lines[-keep_lines:]) + "\n", encoding="utf-8")
    tmp.replace(path)


def tail_lines(path: Path, count: int, *, block_size: int = 65536) -> list[str]:
    """Read only the tail of a JSONL file without parsing its full history."""
    if count <= 0 or not path.exists():
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        chunks: list[bytes] = []
        newline_count = 0
        while position > 0 and newline_count <= count:
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")
    data = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    return [line for line in data.splitlines() if line.strip()][-count:]


def build_status(
    config: SdkRuntimeConfig,
    *,
    status: str,
    reason: str = "",
    connected: bool = False,
    last_event_at: str = "",
    sdk_installed: bool | None = None,
    oauth_client_id_present: bool | None = None,
    pipeline_metrics: dict[str, Any] | None = None,
    subscription_failed_symbols: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    payload = {
        "stage": "M15.longbridge_sdk_runtime", "generated_at": to_iso(now), "status": status,
        "reason": reason, "sdk_connected": connected, "last_event_at": last_event_at,
        "source_mode": "longbridge_sdk_push", "configured_symbol_count": len(configured_symbols(config)),
        "trading_symbol_count": len(configured_trading_symbols(config)),
        "trading_universe_path": (
            str(config.trading_universe_path)
            if config.trading_universe_path is not None
            else ""
        ),
        "trading_universe_fingerprint": trading_universe_fingerprint(config),
        "paper_simulated_only": True, "live_execution": False, "real_money_actions": False,
        "local_simulation_isolated": True,
        "local_ledger_input_ref": "",
        "legacy_fast_queue_used": False,
        "manual_m12_37_once_used": False,
        "sdk_installed": sdk_installed,
        "oauth_client_id_present": oauth_client_id_present,
        "router_config": str(config.router_config_path),
        "execution_config": str(config.execution_config_path),
        "paper_order_dispatch_enabled": config.paper_order_dispatch_enabled,
        "quote_region": config.quote_region,
        "trade_region": config.trade_region,
        "trade_private_push_enabled": config.enable_trade_private_push,
        "runtime_engine": "sdk",
        "config_fingerprint": config_fingerprint(config),
        "pipeline_latency": pipeline_metrics or {},
        "subscription_failed_symbols": subscription_failed_symbols or [],
    }
    payload.update(extra or {})
    config.runtime_status_path.parent.mkdir(parents=True, exist_ok=True)
    config.runtime_status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def summarize_latency_samples(samples: list[int] | tuple[int, ...]) -> dict[str, Any]:
    """Return stable rolling latency metrics without external dependencies."""
    values = sorted(max(0, int(value)) for value in samples)
    if not values:
        return {}

    def percentile(percent: int) -> int:
        index = max(0, min(len(values) - 1, ((len(values) * percent + 99) // 100) - 1))
        return values[index]

    return {
        "sample_count": len(values),
        "latest_ms": int(samples[-1]),
        "p50_ms": percentile(50),
        "p95_ms": percentile(95),
        "maximum_ms": values[-1],
        "within_1s_count": sum(value <= 1000 for value in values),
        "within_5s_count": sum(value <= 5000 for value in values),
        "over_5s_count": sum(value > 5000 for value in values),
    }


def load_formal_test_marker(config: SdkRuntimeConfig) -> dict[str, Any]:
    if not config.formal_test_transition_enabled or not config.formal_test_marker_path.exists():
        return {}
    try:
        marker = json.loads(config.formal_test_marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if str(marker.get("status") or "") not in {"pending_flatten", "scheduled", "active"}:
        return {}
    if str(marker.get("test_epoch_id") or "") != config.formal_test_epoch_id:
        return {}
    if str(marker.get("short_test_epoch_id") or "") != config.formal_short_test_epoch_id:
        return {}
    return marker


def read_client_id(config: SdkRuntimeConfig) -> str:
    if not config.client_id_file.exists():
        raise RuntimeError(f"sdk_oauth_client_id_missing:{config.client_id_file}")
    value = config.client_id_file.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("sdk_oauth_client_id_empty")
    return value


def sdk_endpoint_overrides(region: str) -> dict[str, str]:
    """Return an explicit OpenAPI endpoint set for the configured region."""
    normalized = region.strip().lower()
    if normalized == "cn":
        suffix = "cn"
    elif normalized in {"global", "hk"}:
        suffix = "com"
    else:
        raise ValueError(f"unsupported_longbridge_sdk_region:{region}")
    return {
        "http_url": f"https://openapi.longbridge.{suffix}",
        "quote_ws_url": f"wss://openapi-quote.longbridge.{suffix}/v2",
        "trade_ws_url": f"wss://openapi-trade.longbridge.{suffix}/v2",
    }


def sdk_config_from_oauth(sdk: Any, oauth: Any, region: str) -> Any:
    return sdk.Config.from_oauth(oauth, **sdk_endpoint_overrides(region))


def subscribe_quote_and_trades(
    quote_context: Any,
    symbols: list[str],
    subscription_types: list[Any],
    *,
    batch_size: int = 10,
    retry_count: int = 2,
    progress_callback: Callable[[int, int], None] | None = None,
    request_interval_seconds: float = 0,
    retry_backoff_seconds: float = 0,
) -> list[str]:
    """Subscribe in bounded requests and identify every failed symbol."""
    if batch_size <= 0:
        raise ValueError("subscription batch size must be positive")
    if retry_count < 0:
        raise ValueError("subscription retry count cannot be negative")
    if request_interval_seconds < 0 or retry_backoff_seconds < 0:
        raise ValueError("subscription delays cannot be negative")
    failed_symbols: list[str] = []
    total_symbols = len(symbols)
    for offset in range(0, len(symbols), batch_size):
        batch = symbols[offset : offset + batch_size]
        for attempt in range(retry_count + 1):
            try:
                quote_context.subscribe(batch, subscription_types)
                break
            except Exception:
                if attempt == retry_count:
                    for symbol in batch:
                        try:
                            quote_context.subscribe([symbol], subscription_types)
                        except Exception:
                            failed_symbols.append(symbol)
                elif retry_backoff_seconds:
                    sleep(retry_backoff_seconds)
                continue
        if progress_callback is not None:
            progress_callback(min(offset + len(batch), total_symbols), total_symbols)
        if request_interval_seconds and offset + len(batch) < total_symbols:
            sleep(request_interval_seconds)
    return failed_symbols


def subscribe_private_trade_updates(trade_context: Any, sdk: Any, *, enabled: bool) -> bool:
    """Keep the order hot path independent from an optional trade WebSocket."""
    if not enabled:
        return False
    trade_context.subscribe([sdk.TopicType.Private])
    return True


def is_oauth_refresh_failure(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return (
        ("oauth error" in text and "failed to refresh token" in text)
        or "oauth token refresh failed" in text
        or "invalid_grant" in text
    )


class SdkRealtimePaperClient:
    """Small adapter used by the event loop; no subprocess is started per order."""

    def __init__(
        self,
        trade_context: Any,
        sdk: Any,
        *,
        request_gate: Any = None,
        on_submission: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
        short_capacity_cache_ttl_seconds: int = 900,
        short_capacity_failure_cache_ttl_seconds: int = 30,
        short_capacity_price_tolerance_pct: Decimal = Decimal("2"),
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self.trade_context = trade_context
        self.sdk = sdk
        self.request_gate = request_gate
        self.on_submission = on_submission
        self.short_capacity_cache_ttl_seconds = max(0, int(short_capacity_cache_ttl_seconds))
        self.short_capacity_failure_cache_ttl_seconds = max(
            0, int(short_capacity_failure_cache_ttl_seconds)
        )
        self.short_capacity_price_tolerance_pct = max(
            Decimal("0"), decimal(short_capacity_price_tolerance_pct)
        )
        self.monotonic_clock = monotonic_clock
        self._short_capacity_cache: dict[str, dict[str, Any]] = {}
        self.trade_context_refresh_required = False
        self.trade_context_refresh_reason = ""

    def healthcheck(self) -> dict[str, Any]:
        """Refresh OAuth on a harmless read before the next order is needed."""
        if self.trade_context_refresh_required:
            return {
                "ok": False,
                "status": "trade_context_refresh_required",
                "trade_context_refresh_required": True,
                "error": self.trade_context_refresh_reason,
            }
        method = getattr(self.trade_context, "today_orders", None)
        if not callable(method):
            return {
                "ok": False,
                "status": "trade_context_healthcheck_unavailable",
                "trade_context_refresh_required": False,
                "error": "sdk_trade_context_today_orders_unavailable",
            }
        started_at = perf_counter()
        try:
            callback = lambda: method()
            self.request_gate.call(callback) if self.request_gate is not None else callback()
        except Exception as exc:
            error = str(exc)[:500]
            refresh_required = is_oauth_refresh_failure(error)
            if refresh_required:
                self.trade_context_refresh_required = True
                self.trade_context_refresh_reason = error
            return {
                "ok": False,
                "status": (
                    "trade_context_refresh_required"
                    if refresh_required
                    else "trade_context_healthcheck_failed"
                ),
                "trade_context_refresh_required": refresh_required,
                "error": error,
                "elapsed_ms": max(0, int((perf_counter() - started_at) * 1000)),
            }
        return {
            "ok": True,
            "status": "trade_context_healthy",
            "trade_context_refresh_required": False,
            "error": "",
            "elapsed_ms": max(0, int((perf_counter() - started_at) * 1000)),
        }

    def submit_order(self, order_payload: dict[str, Any]) -> dict[str, Any]:
        if self.trade_context_refresh_required:
            return {
                "submitted": False,
                "status": "submit_blocked_trade_context_refresh_required",
                "order_id": "",
                "explicit_reject": False,
                "trade_context_refresh_required": True,
                "error": self.trade_context_refresh_reason,
                "response": {"error": self.trade_context_refresh_reason},
            }
        side_name = "Buy" if str(order_payload.get("side") or "").lower() == "buy" else "Sell"
        normalized_order_type = str(order_payload.get("order_type") or "")
        if normalized_order_type == "trigger_limit":
            order_type_name = "LIT"
        elif normalized_order_type == "market":
            order_type_name = "MO"
        else:
            order_type_name = "LO"
        side = getattr(self.sdk.OrderSide, side_name)
        order_type = getattr(self.sdk.OrderType, order_type_name)
        outside_rth = getattr(getattr(self.sdk, "OutsideRTH", None), "RTHOnly", None)
        if outside_rth is None:
            raise RuntimeError("sdk_outside_rth_rth_only_unavailable")
        kwargs: dict[str, Any] = {
            "side": side,
            "symbol": longbridge_symbol(str(order_payload["symbol"])),
            "order_type": order_type,
            "submitted_quantity": decimal(order_payload.get("quantity")),
            "time_in_force": self.sdk.TimeInForceType.Day,
            "outside_rth": outside_rth,
            "remark": (
                f"PAT-RT {order_payload.get('signal_id') or 'm15-paper'} "
                f"{order_payload.get('client_request_id') or ''}"
            )[:64],
        }
        if order_type_name != "MO":
            kwargs["submitted_price"] = decimal(order_payload.get("limit_price"))
        if order_type_name == "LIT":
            kwargs["trigger_price"] = decimal(order_payload.get("trigger_price"))
        callback = lambda: self.trade_context.submit_order(**kwargs)
        try:
            response = self.request_gate.call(callback) if self.request_gate is not None else callback()
        except Exception as exc:
            error = str(exc)[:500]
            refresh_required = is_oauth_refresh_failure(error)
            if refresh_required:
                self.trade_context_refresh_required = True
                self.trade_context_refresh_reason = error
            return {
                "submitted": False,
                "status": (
                    "submit_blocked_trade_context_refresh_required"
                    if refresh_required
                    else "submit_rejected_without_order_id"
                ),
                "order_id": "",
                "explicit_reject": not refresh_required,
                "trade_context_refresh_required": refresh_required,
                "error": error,
                "response": {"error": error},
            }
        order_id = str(getattr(response, "order_id", "") or "")
        result = {
            "submitted": bool(order_id),
            "status": "submitted" if order_id else "submit_unconfirmed_missing_order_id",
            "order_id": order_id,
            "response": {"order_id": order_id},
        }
        if result["submitted"] and self.on_submission is not None:
            self.on_submission(order_payload, result)
        return result

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        callback = lambda: self.trade_context.cancel_order(str(order_id))
        self.request_gate.call(callback) if self.request_gate is not None else callback()
        return {"canceled": True, "status": "cancel_requested", "order_id": str(order_id)}

    def replace_order(self, order_id: str, quantity: Decimal, price: Decimal) -> dict[str, Any]:
        callback = lambda: self.trade_context.replace_order(
            str(order_id),
            decimal(quantity),
            price=decimal(price),
        )
        self.request_gate.call(callback) if self.request_gate is not None else callback()
        return {
            "replaced": True,
            "status": "replace_requested",
            "order_id": str(order_id),
            "quantity": fmt(decimal(quantity)),
            "price": fmt(decimal(price)),
        }

    def max_short_quantity(self, symbol: str, limit_price: Decimal) -> dict[str, Any]:
        # The SDK reports borrowed-stock capacity for a Sell open-short request
        # in margin_max_qty. cash_max_qty can instead describe owned shares.
        normalized_symbol = longbridge_symbol(symbol)
        now = self.monotonic_clock()
        cached = self._short_capacity_cache.get(normalized_symbol)
        if cached is not None:
            age_seconds = max(0.0, now - float(cached["cached_at"]))
            cached_price = decimal(cached.get("limit_price"))
            price_change_pct = (
                abs(decimal(limit_price) - cached_price) * Decimal("100") / cached_price
                if cached_price > 0
                else Decimal("0")
            )
            cache_ttl = (
                self.short_capacity_cache_ttl_seconds
                if bool(cached.get("ok"))
                else self.short_capacity_failure_cache_ttl_seconds
            )
            if age_seconds <= cache_ttl and price_change_pct <= self.short_capacity_price_tolerance_pct:
                return {
                    "ok": bool(cached.get("ok")),
                    "status": "sdk_short_capacity_cached",
                    "underlying_status": str(cached.get("status") or ""),
                    "max_quantity": decimal(cached.get("max_quantity")),
                    "cash_max_quantity": decimal(
                        cached.get("cash_max_quantity")
                    ),
                    "margin_max_quantity": decimal(
                        cached.get("margin_max_quantity")
                    ),
                    "capacity_basis": str(cached.get("capacity_basis") or ""),
                    "elapsed_ms": 0,
                    "cache_age_seconds": round(age_seconds, 3),
                    "capacity_source": "broker_sdk_cache",
                }
        method = getattr(self.trade_context, "estimate_max_purchase_quantity", None)
        if not callable(method):
            return {
                "ok": False,
                "status": "short_capacity_sdk_method_unavailable",
                "max_quantity": Decimal("0"),
                "elapsed_ms": 0,
                "cache_age_seconds": None,
                "capacity_source": "broker_sdk_unavailable",
            }
        started_at = perf_counter()
        try:
            callback = lambda: method(
                normalized_symbol,
                self.sdk.OrderType.LO,
                price=limit_price,
                side=self.sdk.OrderSide.Sell,
            )
            response = self.request_gate.call(callback) if self.request_gate is not None else callback()
            cash_quantity = decimal(getattr(response, "cash_max_qty", "0"))
            margin_quantity = decimal(getattr(response, "margin_max_qty", "0"))
            # For an open-short Sell request Longbridge reports borrowed-stock
            # capacity in margin_max_qty. cash_max_qty can represent shares
            # already owned, so using it here would confuse closing a long with
            # opening a new short. Normal buys still enforce USD cash only.
            quantity = margin_quantity
            result = {
                "ok": quantity > 0,
                "status": "sdk_short_capacity",
                "max_quantity": quantity,
                "cash_max_quantity": cash_quantity,
                "margin_max_quantity": margin_quantity,
                "capacity_basis": "margin_max_qty_for_sell_short",
                "elapsed_ms": max(0, int((perf_counter() - started_at) * 1000)),
                "cache_age_seconds": 0,
                "capacity_source": "broker_sdk_live",
            }
            self._short_capacity_cache[normalized_symbol] = {
                **result,
                "cached_at": now,
                "limit_price": decimal(limit_price),
            }
            return result
        except Exception as exc:
            result = {
                "ok": False,
                "status": f"short_capacity_sdk_failed:{exc}",
                "max_quantity": Decimal("0"),
                "cash_max_quantity": Decimal("0"),
                "margin_max_quantity": Decimal("0"),
                "capacity_basis": "margin_max_qty_for_sell_short",
                "elapsed_ms": max(0, int((perf_counter() - started_at) * 1000)),
                "cache_age_seconds": None,
                "capacity_source": "broker_sdk_error",
            }
            self._short_capacity_cache[normalized_symbol] = {
                **result,
                "cached_at": now,
                "limit_price": decimal(limit_price),
            }
            return result


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def sdk_order_maintenance_actions(
    account_state: dict[str, Any],
    execution_rows: list[dict[str, Any]],
    market_events: list[dict[str, Any]],
    *,
    now: datetime,
    stale_entry_order_ttl_seconds: int,
    exit_order_reprice_seconds: int,
) -> list[dict[str, Any]]:
    """Plan SDK-native maintenance only for orders attributable to M15 signals."""
    execution_by_signal = {
        str(row.get("signal_id") or ""): row
        for row in execution_rows
        if isinstance(row, dict) and str(row.get("signal_id") or "")
    }
    latest_prices: dict[str, tuple[str, Decimal]] = {}
    for row in market_events:
        if str(row.get("timeframe") or "") != "5m":
            continue
        symbol = str(row.get("symbol") or "").upper().replace(".US", "")
        price = decimal(row.get("close"))
        event_time = str(row.get("event_time") or row.get("received_at") or "")
        if symbol and price > 0 and (symbol not in latest_prices or event_time >= latest_prices[symbol][0]):
            latest_prices[symbol] = (event_time, price)

    actions: list[dict[str, Any]] = []
    for order in account_state.get("open_orders", []):
        if not isinstance(order, dict) or order.get("sdk_pending_confirmation"):
            continue
        order_id = str(order.get("order_id") or "")
        remark = str(order.get("remark") or "").strip()
        signal_id = remark if remark in execution_by_signal else next(
            (token for token in remark.split() if token in execution_by_signal),
            "",
        )
        metadata = execution_by_signal.get(signal_id)
        if not order_id or metadata is None:
            continue
        submitted_at = _sdk_order_datetime(order.get("updated_at") or order.get("submitted_at"))
        if submitted_at is None:
            continue
        age_seconds = max(0, int((now.astimezone(UTC) - submitted_at).total_seconds()))
        side = _sdk_order_side(order.get("side"))
        position_action = str(metadata.get("position_action") or metadata.get("exit_reason") or "").lower()
        is_exit = position_action in {"stop_loss", "take_profit", "close_long", "exit_long", "close_short"}
        quantity = decimal(order.get("quantity"))
        executed_quantity = decimal(order.get("executed_quantity"))
        symbol = str(order.get("symbol") or metadata.get("symbol") or "").upper().replace(".US", "")

        if not is_exit:
            if age_seconds >= stale_entry_order_ttl_seconds:
                actions.append({
                    "action": "cancel",
                    "reason": "stale_entry_order_ttl_expired",
                    "order_id": order_id,
                    "signal_id": signal_id,
                    "symbol": symbol,
                    "side": side,
                    "age_seconds": age_seconds,
                })
            continue

        if age_seconds < exit_order_reprice_seconds or executed_quantity > 0 or quantity <= 0:
            continue
        if str(metadata.get("original_order_type") or metadata.get("order_type") or "") == "market":
            continue
        if bool(metadata.get("market_exit_no_reprice")):
            continue
        latest_price = latest_prices.get(symbol, ("", Decimal("0")))[1]
        current_price = decimal(order.get("price"))
        if latest_price <= 0 or current_price <= 0:
            continue
        if position_action == "close_short" and side == "buy":
            replacement_price = (latest_price * Decimal("1.005")).quantize(Decimal("0.01"), rounding=ROUND_UP)
            improves_execution = replacement_price > current_price
            price_source = "current_sdk_price_plus_short_cover_buffer"
        elif side == "sell":
            replacement_price = (latest_price * Decimal("0.995")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            improves_execution = replacement_price < current_price
            price_source = "current_sdk_price_minus_long_exit_buffer"
        else:
            continue
        if not improves_execution:
            continue
        actions.append({
            "action": "replace",
            "reason": "stale_exit_order_repriced",
            "order_id": order_id,
            "signal_id": signal_id,
            "symbol": symbol,
            "side": side,
            "position_action": position_action,
            "quantity": fmt(quantity),
            "old_price": fmt(current_price),
            "new_price": fmt(replacement_price),
            "price_source": price_source,
            "age_seconds": age_seconds,
        })
    return actions


def _sdk_order_side(value: Any) -> str:
    return str(value or "").strip().split(".")[-1].lower().replace("_", "")


def _sdk_order_datetime(value: Any) -> datetime | None:
    raw = str(value or "")
    if not raw:
        return None
    try:
        return parse_utc_datetime(raw)
    except ValueError:
        return None


def int_like(value: Any) -> int:
    try:
        return int(str(value or "0"))
    except Exception:
        return 0


def unix_to_utc(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        try:
            return datetime.fromtimestamp(value.timestamp(), UTC)
        except (ValueError, OSError):
            return fallback.astimezone(UTC)
    try:
        return datetime.fromtimestamp(int(str(value)), UTC)
    except Exception:
        return fallback.astimezone(UTC)


def fmt(value: Decimal) -> str:
    return format(value, "f")


def sdk_object_to_dict(value: Any) -> dict[str, Any]:
    """Normalise PyO3 SDK callback objects without depending on internals."""
    if isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key in (
        "symbol", "sub_types", "timestamp", "last_done", "current_volume", "volume", "trades", "price", "open",
        "high", "low", "close", "turnover", "trade_session", "sequence",
    ):
        if hasattr(value, key):
            item = getattr(value, key)
            if key == "trades" and item is not None:
                result[key] = [sdk_object_to_dict(trade) for trade in item]
            else:
                result[key] = item
    return result
