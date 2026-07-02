#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_background_watchdog_lib import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    load_config,
    run_background_watchdog_once,
    start_daemon,
    status,
    stop_daemon,
    watch_loop,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Keep M12.47 and M15 Longbridge realtime daemons healthy.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to M15 background watchdog config JSON.")
    parser.add_argument("--once", action="store_true", help="Run one watchdog health pass.")
    parser.add_argument("--watch", action="store_true", help="Run continuous watchdog loop in foreground.")
    parser.add_argument("--daemon", action="store_true", help="Start watchdog loop in background.")
    parser.add_argument("--stop", action="store_true", help="Stop background watchdog.")
    parser.add_argument("--status", action="store_true", help="Print latest watchdog status.")
    parser.add_argument("--generated-at", default=None, help="UTC timestamp for deterministic tests.")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.status:
        print(json.dumps(status(config), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.stop:
        return stop_daemon(config)
    if args.daemon:
        return start_daemon(args.config, config)
    if args.watch:
        return watch_loop(config)
    payload = run_background_watchdog_once(config, generated_at=args.generated_at)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
