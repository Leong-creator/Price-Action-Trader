#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if (
    VENV_PYTHON.exists()
    and Path(sys.prefix).resolve() != VENV_PYTHON.parent.parent.resolve()
    and os.environ.get("M15_SDK_RUNTIME_VENV_REEXEC") != "1"
):
    environment = dict(os.environ, M15_SDK_RUNTIME_VENV_REEXEC="1")
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__)), *sys.argv[1:]], environment)

from scripts.m15_longbridge_sdk_runtime_lib import (
    DEFAULT_CONFIG_PATH, FiveMinuteBarBuilder, MarketEventContext, SdkRealtimePaperClient, append_market_events,
    build_status, compact_market_events, configured_symbols, load_config, read_client_id, sdk_config_from_oauth,
    subscribe_private_trade_updates, subscribe_quote_and_trades, fresh_market_events, sdk_object_to_dict,
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
    sdk_error = ""
    try:
        import longbridge.openapi as lb
    except Exception as exc:
        lb = None
        sdk_error = f"sdk_import_failed:{exc}"
    client_id = ""
    oauth_error = ""
    try:
        client_id = read_client_id(config)
    except Exception as exc:
        oauth_error = str(exc)
    if sdk_error or oauth_error:
        reason = ";".join(item for item in (sdk_error, oauth_error) if item)
        build_status(
            config,
            status="blocked_sdk_prerequisite",
            reason=reason,
            sdk_installed=not bool(sdk_error),
            oauth_client_id_present=not bool(oauth_error),
        )
        print(f"SDK runtime blocked: {reason}")
        return 2
    if args.check:
        build_status(
            config,
            status="sdk_prerequisite_ready",
            reason="OAuth client id and SDK are available",
            sdk_installed=True,
            oauth_client_id_present=True,
        )
        print(f"SDK prerequisite ready; symbols={len(configured_symbols(config))}; client_id={client_id[:8]}...")
        return 0
    if args.dispatch and not config.paper_order_dispatch_enabled:
        build_status(
            config,
            status="blocked_dispatch_not_enabled",
            reason="paper_order_dispatch_enabled=false",
            sdk_installed=True,
            oauth_client_id_present=True,
        )
        print("SDK dispatch blocked: paper_order_dispatch_enabled=false")
        return 2
    if not args.watch:
        args.watch = True
    builder = FiveMinuteBarBuilder(config.bar_minutes)
    last_compaction = 0.0
    try:
        oauth = lb.OAuthBuilder(client_id).build(lambda url: print(f"OAuth authorization required: {url}", flush=True))
        quote = lb.QuoteContext(sdk_config_from_oauth(lb, oauth, config.quote_region))
        from scripts.m15_longbridge_realtime_signal_router_lib import load_config as load_router_config, read_jsonl_tail, run_realtime_signal_router
        router_config = load_router_config(config.router_config_path)
        market_event_context = MarketEventContext(
            read_jsonl_tail(config.market_events_path, router_config.max_market_event_rows_per_hot_run),
            maximum_rows=router_config.max_market_event_rows_per_hot_run,
        )
        trade = None
        paper_client = None
        execution_config = None
        if args.dispatch:
            trade = lb.TradeContext(sdk_config_from_oauth(lb, oauth, config.trade_region))
            subscribe_private_trade_updates(trade, lb, enabled=config.enable_trade_private_push)
            paper_client = SdkRealtimePaperClient(trade, lb)
            from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config
            execution_config = load_execution_config(config.execution_config_path)
            if not execution_config.execute_orders or not execution_config.paper_trading_approval:
                raise RuntimeError("sdk_dispatch_execution_config_not_paper_orders_enabled")
        def emit(rows):
            fresh_rows = fresh_market_events(rows, config.maximum_source_delivery_age_ms)
            append_market_events(config.market_events_path, fresh_rows, config.event_keep_lines)
            if fresh_rows and paper_client is not None:
                from scripts.m15_longbridge_realtime_execution_lib import run_realtime_execution
                now = fresh_rows[-1]["received_at"]
                new_rows = market_event_context.append(fresh_rows)
                emitted_signals: list[dict] = []
                run_realtime_signal_router(
                    router_config,
                    generated_at=now,
                    market_events_override=market_event_context.rows(),
                    active_market_event_ids={str(row["event_id"]) for row in new_rows},
                    emitted_signal_events=emitted_signals,
                )
                run_realtime_execution(
                    execution_config,
                    generated_at=now,
                    broker_client=paper_client,
                    signal_events_override=emitted_signals,
                )
        def on_quote(symbol, event):
            rows = builder.on_quote(symbol, sdk_object_to_dict(event), received_at=datetime.now(UTC))
            emit(rows)
        def on_trades(symbol, event):
            rows = builder.on_trade(symbol, sdk_object_to_dict(event), received_at=datetime.now(UTC))
            emit(rows)
        quote.set_on_quote(on_quote)
        quote.set_on_trades(on_trades)
        subscribe_quote_and_trades(quote, list(configured_symbols(config)), [lb.SubType.Quote, lb.SubType.Trade])
        build_status(config, status="running", connected=True, sdk_installed=True, oauth_client_id_present=True)
        while args.watch:
            rows = builder.flush(datetime.now(UTC))
            emit(rows)
            if time.monotonic() - last_compaction >= 60:
                compact_market_events(config.market_events_path, config.event_keep_lines)
                last_compaction = time.monotonic()
            build_status(
                config,
                status="running",
                connected=True,
                last_event_at=rows[-1]["received_at"] if rows else "",
                sdk_installed=True,
                oauth_client_id_present=True,
            )
            time.sleep(config.heartbeat_interval_seconds)
    except KeyboardInterrupt:
        build_status(config, status="stopped", sdk_installed=True, oauth_client_id_present=True)
        return 0
    except Exception as exc:
        build_status(config, status="connection_failed", reason=str(exc), sdk_installed=True, oauth_client_id_present=True)
        print(f"SDK runtime failed: {exc}")
        return 1
if __name__ == "__main__":
    raise SystemExit(main())
