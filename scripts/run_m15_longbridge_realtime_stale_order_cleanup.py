#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_realtime_stale_order_cleanup_lib import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    SUMMARY_JSON,
    load_config,
    run_stale_order_cleanup,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cancel stale Longbridge paper buy open orders before realtime execution.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to stale order cleanup config JSON.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at ISO timestamp.")
    parser.add_argument("--session-started-at", required=True, help="Current regular session start timestamp.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    payload = run_stale_order_cleanup(config, generated_at=args.generated_at, session_started_at=args.session_started_at)
    print(config.output_dir / SUMMARY_JSON)
    print(payload.get("plain_language_result", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
