#!/usr/bin/env python3
"""Bounded read-only raw SDK probe. Never reads accounts or writes production state."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import queue
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_marketdata_diagnostics_lib import (
    PipelineDiagnostics, acquire_quote_owner_lock, append_diagnostic_snapshot,
    assert_no_legacy_quote_processes,
)
from scripts.m15_longbridge_sdk_runtime_lib import (
    DEFAULT_CONFIG_PATH, configured_symbols, load_config, read_client_id,
    sdk_config_from_oauth, sdk_object_to_dict,
)
from scripts.m15_longbridge_sdk_quote_transport_lib import _subscription_symbols


def validate_output_dir(path: Path, production_dir: Path) -> Path:
    path = path.expanduser().resolve()
    if path == production_dir.resolve() or production_dir.resolve() in path.parents:
        raise ValueError("diagnostics_must_not_write_production_output")
    if path == ROOT or ROOT in path.parents:
        raise ValueError("diagnostics_output_must_be_outside_worktree")
    if path.exists() and any(path.iterdir()):
        raise ValueError("diagnostics_output_must_be_new_or_empty")
    return path


async def collect(config: Any, symbols: list[str], duration: float, output: Path, sdk: Any,
                  stop: asyncio.Event) -> dict[str, Any]:
    diagnostics = PipelineDiagnostics()
    events: queue.Queue = queue.Queue(maxsize=250_000)
    errors: queue.Queue = queue.Queue(maxsize=1)
    started = time.monotonic()
    deadline = started + duration
    quote = None
    def callback(kind: str, symbol: str, event: Any) -> None:
        symbol = str(symbol).upper()
        diagnostics.record("raw_callback", symbol, kind)
        try:
            normalized = sdk_object_to_dict(event)
            diagnostics.record("normalized", symbol, kind)
            events.put_nowait((kind, symbol, normalized))
            diagnostics.record("enqueued", symbol, kind)
        except Exception as exc:
            diagnostics.record("callback_error", symbol, kind)
            try:
                errors.put_nowait(type(exc).__name__)
            except queue.Full:
                pass
    result = {"mode": "isolated_raw_sdk_diagnostic", "symbols": symbols,
              "started_at": datetime.now(UTC).isoformat(), "duration_limit_seconds": duration,
              "account_access": False, "order_access": False, "production_acceptance": False,
              "bar_formation": "not_assessed_raw_callback_probe", "status": "collecting"}
    try:
        oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
        quote = sdk.AsyncQuoteContext.create(sdk_config_from_oauth(sdk, oauth, config.quote_region))
        quote.set_on_quote(lambda symbol, event: callback("quote", symbol, event))
        quote.set_on_trades(lambda symbol, event: callback("trade", symbol, event))
        sub_types = [sdk.SubType.Quote, sdk.SubType.Trade]
        async def request(awaitable):
            return await asyncio.wait_for(awaitable, timeout=max(0.001, min(30, deadline - time.monotonic())))
        batch = config.sdk_subscribe_batch_size
        for offset in range(0, len(symbols), batch):
            await request(quote.subscribe(symbols[offset:offset + batch], sub_types))
        actual = _subscription_symbols(await request(quote.subscriptions()), tuple(sub_types))
        result["missing_subscriptions"] = sorted(set(symbols) - actual)
        if result["missing_subscriptions"]:
            raise RuntimeError("subscription_coverage_incomplete")
        result["subscription_coverage"] = f"{len(symbols)}/{len(symbols)}"
        last_audit = 0.0
        while time.monotonic() < deadline and not stop.is_set():
            if not errors.empty():
                raise RuntimeError("callback_failure:" + errors.get_nowait())
            for _ in range(10_000):
                try:
                    kind, symbol, _payload = events.get_nowait()
                except queue.Empty:
                    break
                diagnostics.record("dequeued", symbol, kind)
            if time.monotonic() - last_audit >= 1:
                snapshot = diagnostics.snapshot(drain_samples=True)
                snapshot["queue_depth"] = events.qsize()
                append_diagnostic_snapshot(output / "pipeline.jsonl", snapshot)
                last_audit = time.monotonic()
            await asyncio.sleep(0.05)
        result["status"] = "operator_stopped" if stop.is_set() else "duration_completed"
    except Exception as exc:
        # Exception types are sufficient here; credential-bearing SDK errors are not echoed.
        result.update(status="failed", error_type=type(exc).__name__)
    finally:
        quote = None  # SDK has no public close; process exit is the cleanup boundary.
        result.update(finished_at=datetime.now(UTC).isoformat(),
                      elapsed_seconds=round(time.monotonic() - started, 3),
                      diagnostics=diagnostics.snapshot(drain_samples=True),
                      native_transport_close="unobservable_until_process_exit")
        append_diagnostic_snapshot(output / "pipeline.jsonl", result["diagnostics"])
        (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    universe = parser.add_mutually_exclusive_group(required=True)
    universe.add_argument("--symbols", help="Comma separated symbols, e.g. SPY.US,QQQ.US")
    universe.add_argument("--production-universe", action="store_true")
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.duration_seconds) or not 1 <= args.duration_seconds <= 86400:
        parser.error("duration must be finite, between 1 and 86400 seconds")
    config = load_config(args.config)
    symbols = list(configured_symbols(config)) if args.production_universe else list(dict.fromkeys(
        value.strip().upper() for value in args.symbols.split(",") if value.strip()))
    if not symbols or any(symbol not in configured_symbols(config) for symbol in symbols):
        parser.error("symbols must be in the configured production universe")
    output = validate_output_dir(args.output_dir, config.output_dir)
    from scripts.m15_sdk_provenance_lib import verify_environment
    verification = verify_environment(ROOT)
    if not verification["verified"]:
        print(json.dumps({"status": "blocked_environment_provenance", "issues": verification["issues"]}))
        return 2
    owner = acquire_quote_owner_lock()
    try:
        assert_no_legacy_quote_processes()
        owner.seek(0)
        owner.truncate()
        owner.write(f"{os.getpid()}\n")
        owner.flush()
        os.environ["LONGBRIDGE_PRINT_QUOTE_PACKAGES"] = "false"
        import longbridge.openapi as sdk
        output.mkdir(parents=True, exist_ok=True)
        (output / "environment.json").write_text(json.dumps(verification, indent=2) + "\n")
        async def run():
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signum, stop.set)
            try:
                return await asyncio.wait_for(collect(config, symbols, args.duration_seconds, output, sdk, stop),
                                              timeout=args.duration_seconds + 5)
            finally:
                for signum in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(signum)
        result = asyncio.run(run())
        print(json.dumps({"status": result["status"], "output_dir": str(output),
                          "production_acceptance": False}))
        return 0 if result["status"] != "failed" else 4
    finally:
        owner.close()


if __name__ == "__main__":
    raise SystemExit(main())
