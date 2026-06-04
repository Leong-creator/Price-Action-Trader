#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_realtime_execution_lib import (
    DEFAULT_CONFIG_PATH,
    SUMMARY_JSON,
    load_config,
    run_realtime_execution,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the isolated Longbridge paper realtime execution path."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to the realtime execution config JSON.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at ISO timestamp for tests.")
    parser.add_argument("--watch", action="store_true", help="Keep running with the configured watch interval.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if args.watch:
        while True:
            payload = run_realtime_execution(config, generated_at=args.generated_at)
            print(config.output_dir / SUMMARY_JSON)
            if payload.get("submitted_count"):
                print(f"submitted={payload['submitted_count']}")
            time.sleep(config.watch_interval_seconds)
    payload = run_realtime_execution(config, generated_at=args.generated_at)
    print(config.output_dir / SUMMARY_JSON)
    print(payload.get("plain_language_result", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
