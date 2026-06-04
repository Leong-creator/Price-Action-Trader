#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config
from scripts.m15_longbridge_realtime_execution_lib import run_realtime_execution
from scripts.m15_longbridge_realtime_signal_router_lib import (
    DEFAULT_CONFIG_PATH,
    SUMMARY_JSON,
    load_config,
    run_realtime_signal_router,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Route realtime Longbridge market events into paper-account signal events.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to realtime signal router config JSON.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at ISO timestamp for deterministic tests.")
    parser.add_argument("--watch", action="store_true", help="Keep running with the configured watch interval.")
    parser.add_argument("--run-execution", action="store_true", help="After routing, run the realtime execution dry-run/submitter.")
    parser.add_argument(
        "--execution-config",
        default="config/examples/m15_longbridge_realtime_execution.json",
        help="Realtime execution config used when --run-execution is set.",
    )
    return parser.parse_args()


def run_once(args: argparse.Namespace) -> dict:
    config = load_config(args.config)
    payload = run_realtime_signal_router(config, generated_at=args.generated_at)
    print(config.output_dir / SUMMARY_JSON)
    print(payload.get("plain_language_result", ""))
    if args.run_execution:
        execution_config = load_execution_config(args.execution_config)
        execution_payload = run_realtime_execution(execution_config, generated_at=args.generated_at)
        print(execution_config.output_dir / "m15_longbridge_realtime_execution.json")
        print(execution_payload.get("plain_language_result", ""))
    return payload


def main() -> int:
    args = parse_args()
    if args.watch:
        while True:
            payload = run_once(args)
            config = load_config(args.config)
            if payload.get("new_signal_event_count"):
                print(f"new_signal_event_count={payload['new_signal_event_count']}")
            time.sleep(1)
    run_once(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
