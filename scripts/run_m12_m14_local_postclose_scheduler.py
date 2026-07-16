#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_m14_local_postclose_scheduler_lib import (
    DEFAULT_CONFIG_PATH,
    load_scheduler_config,
    run_scheduler_once,
    start_daemon,
    status,
    stop_daemon,
    watch_loop,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行本地研究与修复系统盘后调度器。")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to scheduler config JSON.")
    parser.add_argument("--watch", action="store_true", help="Run continuous scheduling loop in foreground.")
    parser.add_argument("--daemon", action="store_true", help="Start continuous scheduling loop in background.")
    parser.add_argument("--stop", action="store_true", help="Stop background scheduler.")
    parser.add_argument("--status", action="store_true", help="Print latest scheduler status.")
    parser.add_argument("--generated-at", default=None, help="UTC timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_scheduler_config(args.config)
    if args.status:
        print(json.dumps(status(config, generated_at=args.generated_at), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.stop:
        return stop_daemon(config)
    if args.daemon:
        return start_daemon(args.config, config)
    if args.watch:
        return watch_loop(config)
    payload = run_scheduler_once(config, generated_at=args.generated_at)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if payload.get("batch_status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
