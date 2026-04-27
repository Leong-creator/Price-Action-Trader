#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_read_only_observation_lib import DEFAULT_CONFIG_PATH, load_observation_config, run_m10_read_only_observation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the M10.6 recorded replay read-only observation prototype.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the M10.6 read-only observation config JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_observation_config(args.config)
    summary = run_m10_read_only_observation(config)
    print(
        json.dumps(
            {
                "status": "ok",
                "run_id": summary["run_id"],
                "output_dir": config.output_dir.as_posix(),
                "recorded_replay_only": summary["recorded_replay_only"],
                "paper_simulated_only": summary["paper_simulated_only"],
                "broker_connection": summary["broker_connection"],
                "live_execution": summary["live_execution"],
                "real_orders": summary["real_orders"],
                "event_count": summary["event_count"],
                "candidate_event_count": summary["candidate_event_count"],
                "skip_no_trade_count": summary["skip_no_trade_count"],
                "deferred_input_count": summary["deferred_input_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
