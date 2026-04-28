#!/usr/bin/env python3
from __future__ import annotations

import argparse

from m12_12_daily_observation_loop_lib import load_config, run_m12_12_daily_observation_loop


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M12.12 first-batch readonly daily observation loop.")
    parser.add_argument("--config", default=None, help="Path to config JSON.")
    parser.add_argument("--no-fetch", action="store_true", help="Do not issue readonly Longbridge K-line fetches.")
    parser.add_argument("--max-native-fetches", type=int, default=None, help="Override native fetch budget for this run.")
    args = parser.parse_args()

    config = load_config(args.config) if args.config else load_config()
    summary = run_m12_12_daily_observation_loop(
        config,
        execute_fetch=not args.no_fetch,
        max_native_fetches=args.max_native_fetches,
    )
    cache = summary["first50_cache"]
    daily = summary["formal_daily_strategy"]["overall_metrics"]
    print(
        "M12.12 daily loop complete: "
        f"first50={cache['symbol_count']} daily_ready={cache['daily_ready_symbols']} "
        f"current_5m_ready={cache['current_5m_ready_symbols']} "
        f"candidates={summary['daily_loop']['candidate_count']} "
        f"formal_return={daily['return_percent']}%"
    )


if __name__ == "__main__":
    main()
