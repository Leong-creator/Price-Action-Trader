#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_29_current_day_scan_dashboard_lib import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    load_config,
    run_m12_29_current_day_scan_dashboard,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M12.29 current-day scan and readonly dashboard build.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to M12.29 config JSON.")
    parser.add_argument("--generated-at", default=None, help="UTC ISO timestamp override, e.g. 2026-04-29T02:30:00Z.")
    parser.add_argument("--no-fetch", action="store_true", help="Do not call readonly Longbridge kline fetch; use existing cache only.")
    parser.add_argument("--max-native-fetches", type=int, default=None, help="Limit readonly native fetch calls.")
    parser.add_argument("--no-refresh-quotes", action="store_true", help="Do not call readonly Longbridge quote; use fallback quote data.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    result = run_m12_29_current_day_scan_dashboard(
        config,
        generated_at=args.generated_at,
        execute_fetch=not args.no_fetch,
        max_native_fetches=args.max_native_fetches,
        refresh_quotes=not args.no_refresh_quotes,
    )
    summary = result["summary"]
    print(
        json.dumps(
            {
                "stage": summary["stage"],
                "scan_date": summary["scan_date"],
                "today_candidate_count": summary["today_candidate_count"],
                "visible_opportunity_count": summary["visible_opportunity_count"],
                "mainline_today_pnl": summary.get("mainline_today_pnl", ""),
                "experimental_today_pnl": summary.get("experimental_today_pnl", ""),
                "premarket_mover_count": summary.get("premarket_mover_count", 0),
                "postmarket_mover_count": summary.get("postmarket_mover_count", 0),
                "current_day_scan_complete": summary["current_day_scan_complete"],
                "output_dir": str(config.output_dir),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
