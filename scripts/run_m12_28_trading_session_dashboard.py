#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_28_trading_session_dashboard_lib import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    load_config,
    run_m12_28_trading_session_dashboard,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M12.28 trading-session readonly simulated dashboard.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="M12.28 config path.")
    parser.add_argument("--no-refresh-quotes", action="store_true", help="Use checked-in fallback quotes only.")
    parser.add_argument("--loop", action="store_true", help="Refresh repeatedly until interrupted.")
    parser.add_argument("--interval-seconds", type=int, default=None, help="Loop refresh interval.")
    parser.add_argument("--max-iterations", type=int, default=0, help="Optional loop limit for smoke tests.")
    args = parser.parse_args()

    config = load_config(args.config)
    interval = args.interval_seconds or config.dashboard_refresh_seconds
    iteration = 0
    while True:
        dashboard = run_m12_28_trading_session_dashboard(
            config,
            refresh_quotes=not args.no_refresh_quotes,
        )
        summary = dashboard["summary"]
        print(
            "M12.28 dashboard refreshed: "
            f"opportunities={summary['total_visible_opportunity_count']}, "
            f"simulated_pnl={summary['total_simulated_intraday_pnl']}, "
            f"quotes={summary['quote_count']} -> {config.output_dir}"
        )
        iteration += 1
        if not args.loop or (args.max_iterations and iteration >= args.max_iterations):
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
