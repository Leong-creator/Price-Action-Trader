#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_sdk_runtime_lib import (
    DEFAULT_CONFIG_PATH, FiveMinuteBarBuilder, SdkRealtimePaperClient, append_market_events,
    build_status, compact_market_events, configured_symbols, load_config, read_client_id,
    fresh_market_events, sdk_object_to_dict,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the persistent Longbridge SDK quote-push runtime.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--check", action="store_true", help="Validate SDK/OAuth prerequisites without subscribing.")
    parser.add_argument("--watch", action="store_true", help="Connect and keep receiving quote/trade pushes.")
    parser.add_argument("--dispatch", action="store_true", help="Dispatch finalized SDK bars to the isolated router and paper executor.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    try:
        client_id = read_client_id(config)
        import longbridge.openapi as lb
    except Exception as exc:
        build_status(config, status="blocked_sdk_prerequisite", reason=str(exc))
        print(f"SDK runtime blocked: {exc}")
        return 2
    if args.check:
        build_status(config, status="sdk_prerequisite_ready", reason="OAuth client id and SDK are available")
        print(f"SDK prerequisite ready; symbols={len(configured_symbols(config))}; client_id={client_id[:8]}...")
        return 0
    if not args.watch:
        args.watch = True
    builder = FiveMinuteBarBuilder(config.bar_minutes)
    last_compaction = 0.0
    previous_region = __import__("os").environ.get("LONGBRIDGE_REGION")
    __import__("os").environ["LONGBRIDGE_REGION"] = config.quote_region
    try:
        oauth = lb.OAuthBuilder(client_id).build(lambda url: print(f"OAuth authorization required: {url}", flush=True))
        quote = lb.QuoteContext(lb.Config.from_oauth(oauth))
        trade = None
        paper_client = None
        if args.dispatch:
            __import__("os").environ["LONGBRIDGE_REGION"] = config.trade_region
            trade = lb.TradeContext(lb.Config.from_oauth(oauth))
            trade.subscribe([lb.TopicType.Private])
            paper_client = SdkRealtimePaperClient(trade, lb)
            __import__("os").environ["LONGBRIDGE_REGION"] = config.quote_region
        def emit(rows):
            fresh_rows = fresh_market_events(rows, config.maximum_source_delivery_age_ms)
            append_market_events(config.market_events_path, fresh_rows, config.event_keep_lines)
            if fresh_rows and paper_client is not None:
                from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config, run_realtime_execution
                from scripts.m15_longbridge_realtime_signal_router_lib import load_config as load_router_config, run_realtime_signal_router
                now = fresh_rows[-1]["received_at"]
                run_realtime_signal_router(load_router_config(), generated_at=now)
                run_realtime_execution(load_execution_config(), generated_at=now, broker_client=paper_client)
        def on_quote(symbol, event):
            rows = builder.on_quote(symbol, sdk_object_to_dict(event), received_at=datetime.now(UTC))
            emit(rows)
        def on_trades(symbol, event):
            rows = builder.on_trade(symbol, sdk_object_to_dict(event), received_at=datetime.now(UTC))
            emit(rows)
        quote.set_on_quote(on_quote)
        quote.set_on_trades(on_trades)
        quote.subscribe(list(configured_symbols(config)), [lb.SubType.Quote, lb.SubType.Trade], is_first_push=True)
        build_status(config, status="running", connected=True)
        while args.watch:
            rows = builder.flush(datetime.now(UTC))
            emit(rows)
            if time.monotonic() - last_compaction >= 60:
                compact_market_events(config.market_events_path, config.event_keep_lines)
                last_compaction = time.monotonic()
            build_status(config, status="running", connected=True, last_event_at=rows[-1]["received_at"] if rows else "")
            time.sleep(config.heartbeat_interval_seconds)
    except KeyboardInterrupt:
        build_status(config, status="stopped")
        return 0
    except Exception as exc:
        build_status(config, status="connection_failed", reason=str(exc))
        print(f"SDK runtime failed: {exc}")
        return 1
    finally:
        if previous_region is None:
            __import__("os").environ.pop("LONGBRIDGE_REGION", None)
        else:
            __import__("os").environ["LONGBRIDGE_REGION"] = previous_region


if __name__ == "__main__":
    raise SystemExit(main())
