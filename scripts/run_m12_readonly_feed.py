#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_readonly_feed_lib import DEFAULT_CONFIG_PATH, load_readonly_feed_config, run_m12_readonly_feed


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M12.1 Longbridge readonly feed prototype.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to M12.1 readonly feed config.")
    parser.add_argument("--output-dir", default=None, help="Optional output directory override.")
    args = parser.parse_args()
    config = load_readonly_feed_config(args.config)
    if args.output_dir:
        config = type(config)(
            title=config.title,
            run_id=config.run_id,
            symbols=config.symbols,
            market=config.market,
            timeframes=config.timeframes,
            strategy_scope=config.strategy_scope,
            auth_preflight_path=config.auth_preflight_path,
            observation_queue_path=config.observation_queue_path,
            output_dir=Path(args.output_dir),
            paper_simulated_only=config.paper_simulated_only,
            broker_connection=config.broker_connection,
            real_orders=config.real_orders,
            live_execution=config.live_execution,
        )
    manifest = run_m12_readonly_feed(config)
    print(
        "M12.1 readonly feed complete: "
        f"{manifest['ledger_row_count']} rows, {manifest['deferred_count']} deferred -> {config.output_dir}"
    )


if __name__ == "__main__":
    main()
