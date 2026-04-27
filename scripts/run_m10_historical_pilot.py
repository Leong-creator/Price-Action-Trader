#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_historical_pilot_lib import DEFAULT_CONFIG_PATH, load_pilot_config, run_m10_historical_pilot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the M10.4 Wave A historical pilot.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the M10.4 pilot config JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_pilot_config(args.config)
    summary = run_m10_historical_pilot(config)
    print(
        json.dumps(
            {
                "status": "ok",
                "run_id": summary["run_id"],
                "output_dir": config.output_dir.as_posix(),
                "paper_simulated_only": summary["paper_simulated_only"],
                "broker_connection": summary["broker_connection"],
                "live_execution": summary["live_execution"],
                "real_orders": summary["real_orders"],
                "strategy_timeframe_count": len(summary["strategy_timeframe_results"]),
                "available_datasets": summary["data_availability"]["available_count"],
                "deferred_datasets": summary["data_availability"]["deferred_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
