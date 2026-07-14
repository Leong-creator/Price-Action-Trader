#!/usr/bin/env python3
"""Persistent SDK market-data runtime for the isolated M15 paper chain.

The module intentionally keeps the existing JSONL market-event contract.  It
does not read local simulation artifacts and it never falls back to CLI K-line
polling for a new paper entry when the SDK connection is unavailable.
"""
from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_realtime_execution_lib import DEFAULT_DAILY_DIR, parse_utc_datetime, to_iso
from scripts.m15_longbridge_realtime_market_event_ingestor_lib import US_LIQUID_SEED_V1

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_sdk_runtime.json"
SUMMARY_JSON = "m15_longbridge_sdk_runtime.json"
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class SdkRuntimeConfig:
    config_path: Path
    output_dir: Path
    market_events_path: Path
    runtime_status_path: Path
    client_id_file: Path
    quote_region: str
    trade_region: str
    market: str
    use_seed_universe: bool
    symbol_limit: int
    bar_minutes: int
    maximum_source_delivery_age_ms: int
    event_keep_lines: int
    heartbeat_interval_seconds: int
    reconnect_backoff_seconds: int
    subscription_batch_size: int
    subscription_retry_count: int
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
    config = SdkRuntimeConfig(
        config_path=config_path,
        output_dir=resolve_path(outputs["output_dir"]),
        market_events_path=resolve_path(outputs["market_events"]),
        runtime_status_path=resolve_path(outputs["runtime_status"]),
        client_id_file=Path(str(oauth["client_id_file"])).expanduser(),
        quote_region=str(oauth.get("quote_region", "cn")),
        trade_region=str(oauth.get("trade_region", "cn")),
        market=str(market_data.get("market", "US")).upper(),
        use_seed_universe=bool(market_data.get("use_seed_universe", True)),
        symbol_limit=int(market_data.get("symbol_limit", 147)),
        bar_minutes=int(market_data.get("bar_minutes", 5)),
        maximum_source_delivery_age_ms=int(market_data.get("maximum_source_delivery_age_ms", 2000)),
        event_keep_lines=int(market_data.get("event_keep_lines", 20000)),
        heartbeat_interval_seconds=int(runtime.get("heartbeat_interval_seconds", 5)),
        reconnect_backoff_seconds=int(runtime.get("reconnect_backoff_seconds", 5)),
        subscription_batch_size=int(runtime.get("subscription_batch_size", 10)),
        subscription_retry_count=int(runtime.get("subscription_retry_count", 2)),
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
    )
    if not config.paper_trading_only or config.live_execution or config.real_money_actions:
        raise ValueError("M15 SDK runtime must remain paper-only")
    if config.symbol_limit <= 0 or config.symbol_limit > 500:
        raise ValueError("M15 SDK runtime symbol_limit must be between 1 and 500")
    if config.bar_minutes != 5:
        raise ValueError("M15 SDK runtime currently supports only 5-minute bars")
    if config.account_maintenance_interval_seconds <= 0:
        raise ValueError("M15 SDK account maintenance interval must be positive")
    if config.subscription_batch_size <= 0 or config.subscription_batch_size > 50:
        raise ValueError("M15 SDK subscription batch size must be between 1 and 50")
    if config.subscription_retry_count < 0 or config.subscription_retry_count > 5:
        raise ValueError("M15 SDK subscription retry count must be between 0 and 5")
    return config


def configured_symbols(config: SdkRuntimeConfig) -> tuple[str, ...]:
    if not config.use_seed_universe:
        return ()
    return tuple(f"{symbol}.{config.market}" for symbol in US_LIQUID_SEED_V1[: config.symbol_limit])


def floor_bar_open(value: datetime, minutes: int) -> datetime:
    value = value.astimezone(NEW_YORK)
    minute = value.minute - value.minute % minutes
    return value.replace(minute=minute, second=0, microsecond=0)


class FiveMinuteBarBuilder:
    """Build final regular-session bars from SDK quote/trade pushes."""

    def __init__(self, minutes: int = 5) -> None:
        self.minutes = minutes
        self._bars: dict[tuple[str, datetime], dict[str, Any]] = {}

    def on_quote(self, symbol: str, payload: dict[str, Any], *, received_at: datetime) -> list[dict[str, Any]]:
        source_at = unix_to_utc(payload.get("timestamp"), received_at)
        price = decimal(payload.get("last_done"))
        if price <= Decimal("0"):
            return []
        return self._append(symbol, source_at, received_at, price, int_like(payload.get("current_volume")))

    def on_trade(self, symbol: str, payload: dict[str, Any], *, received_at: datetime) -> list[dict[str, Any]]:
        finished: list[dict[str, Any]] = []
        for trade in payload.get("trades", []) if isinstance(payload.get("trades"), list) else []:
            source_at = unix_to_utc(trade.get("timestamp"), received_at)
            price = decimal(trade.get("price"))
            if price > Decimal("0"):
                finished.extend(self._append(symbol, source_at, received_at, price, int_like(trade.get("volume"))))
        return finished

    def flush(self, now: datetime) -> list[dict[str, Any]]:
        completed: list[dict[str, Any]] = []
        for key, bar in list(self._bars.items()):
            if bar["bar_close_at"] <= now.astimezone(NEW_YORK):
                completed.append(self._finalize(key, bar, emitted_at=now))
        return completed

    def _append(self, symbol: str, source_at: datetime, received_at: datetime, price: Decimal, volume: int) -> list[dict[str, Any]]:
        source_ny = source_at.astimezone(NEW_YORK)
        if source_ny.weekday() >= 5 or not (source_ny.hour > 9 or (source_ny.hour == 9 and source_ny.minute >= 30)) or source_ny.hour >= 16:
            return []
        bar_open = floor_bar_open(source_ny, self.minutes)
        key = (symbol.upper(), bar_open)
        bar = self._bars.get(key)
        if bar is None:
            bar = {
                "symbol": symbol.upper(), "bar_open_at": bar_open, "bar_close_at": bar_open + timedelta(minutes=self.minutes),
                "open": price, "high": price, "low": price, "close": price, "volume": 0,
                "source_event_at": source_at, "received_at": received_at,
            }
            self._bars[key] = bar
        else:
            bar["high"] = max(bar["high"], price)
            bar["low"] = min(bar["low"], price)
            bar["close"] = price
            bar["source_event_at"] = max(bar["source_event_at"], source_at)
            bar["received_at"] = max(bar["received_at"], received_at)
        bar["volume"] += max(0, volume)
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
            "source_mode": "longbridge_sdk_push",
            "open": fmt(bar["open"]), "high": fmt(bar["high"]), "low": fmt(bar["low"]),
            "close": fmt(bar["close"]), "volume": str(bar["volume"]),
            "local_simulation_ignored": True,
        }


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


def fresh_market_events(rows: list[dict[str, Any]], maximum_age_ms: int) -> list[dict[str, Any]]:
    """Reject delayed pushes before they can create a current order intent."""
    return [
        row
        for row in rows
        if int_like(row.get("source_delivery_age_ms")) <= maximum_age_ms
    ]


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
) -> dict[str, Any]:
    now = datetime.now(UTC)
    payload = {
        "stage": "M15.longbridge_sdk_runtime", "generated_at": to_iso(now), "status": status,
        "reason": reason, "sdk_connected": connected, "last_event_at": last_event_at,
        "source_mode": "longbridge_sdk_push", "configured_symbol_count": len(configured_symbols(config)),
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
        "pipeline_latency": pipeline_metrics or {},
        "subscription_failed_symbols": subscription_failed_symbols or [],
    }
    config.runtime_status_path.parent.mkdir(parents=True, exist_ok=True)
    config.runtime_status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


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
) -> list[str]:
    """Subscribe in bounded requests and preserve healthy symbols on failures."""
    if batch_size <= 0:
        raise ValueError("subscription batch size must be positive")
    if retry_count < 0:
        raise ValueError("subscription retry count cannot be negative")
    failed_symbols: list[str] = []
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
                continue
    return failed_symbols


def subscribe_private_trade_updates(trade_context: Any, sdk: Any, *, enabled: bool) -> bool:
    """Keep the order hot path independent from an optional trade WebSocket."""
    if not enabled:
        return False
    trade_context.subscribe([sdk.TopicType.Private])
    return True


class SdkRealtimePaperClient:
    """Small adapter used by the event loop; no subprocess is started per order."""

    def __init__(self, trade_context: Any, sdk: Any) -> None:
        self.trade_context = trade_context
        self.sdk = sdk

    def submit_order(self, order_payload: dict[str, Any]) -> dict[str, Any]:
        side_name = "Buy" if str(order_payload.get("side") or "").lower() == "buy" else "Sell"
        order_type_name = "LIT" if str(order_payload.get("order_type") or "") == "trigger_limit" else "LO"
        side = getattr(self.sdk.OrderSide, side_name)
        order_type = getattr(self.sdk.OrderType, order_type_name)
        outside_rth = getattr(getattr(self.sdk, "OutsideRTH", None), "RTHOnly", None)
        if outside_rth is None:
            raise RuntimeError("sdk_outside_rth_rth_only_unavailable")
        kwargs: dict[str, Any] = {
            "side": side,
            "symbol": str(order_payload["symbol"]),
            "order_type": order_type,
            "submitted_price": decimal(order_payload.get("limit_price")),
            "submitted_quantity": decimal(order_payload.get("quantity")),
            "time_in_force": self.sdk.TimeInForceType.Day,
            "outside_rth": outside_rth,
            "remark": str(order_payload.get("signal_id") or "m15-paper")[:64],
        }
        if order_type_name == "LIT":
            kwargs["trigger_price"] = decimal(order_payload.get("trigger_price"))
        response = self.trade_context.submit_order(**kwargs)
        order_id = str(getattr(response, "order_id", "") or "")
        return {
            "submitted": bool(order_id),
            "status": "submitted" if order_id else "submit_unconfirmed_missing_order_id",
            "order_id": order_id,
            "response": {"order_id": order_id},
        }

    def max_short_quantity(self, symbol: str, limit_price: Decimal) -> dict[str, Any]:
        # SDK method signatures have changed across releases.  Until the
        # installed SDK exposes a sell-capacity method, keep the short gate
        # closed instead of guessing capacity or using margin.
        method = getattr(self.trade_context, "estimate_max_purchase_quantity", None)
        if not callable(method):
            return {"ok": False, "status": "short_capacity_sdk_method_unavailable", "max_quantity": Decimal("0"), "elapsed_ms": 0}
        try:
            response = method(symbol, self.sdk.OrderType.LO, price=limit_price, side=self.sdk.OrderSide.Sell)
            quantity = decimal(getattr(response, "cash_max_qty", "0"))
            return {"ok": quantity > 0, "status": "sdk_short_capacity", "max_quantity": quantity, "elapsed_ms": 0}
        except Exception as exc:
            return {"ok": False, "status": f"short_capacity_sdk_failed:{exc}", "max_quantity": Decimal("0"), "elapsed_ms": 0}


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def int_like(value: Any) -> int:
    try:
        return int(str(value or "0"))
    except Exception:
        return 0


def unix_to_utc(value: Any, fallback: datetime) -> datetime:
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
        "timestamp", "last_done", "current_volume", "volume", "trades", "price",
        "trade_session", "sequence",
    ):
        if hasattr(value, key):
            item = getattr(value, key)
            if key == "trades" and item is not None:
                result[key] = [sdk_object_to_dict(trade) for trade in item]
            else:
                result[key] = item
    return result
