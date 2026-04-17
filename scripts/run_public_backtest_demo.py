#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.public_backtest_demo_lib import create_backtest_run, load_demo_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a user-readable historical backtest demo on cached public market data."
    )
    parser.add_argument(
        "--config",
        default="config/examples/public_history_backtest_demo.json",
        help="Path to the demo config JSON.",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Re-download the public market data before running the backtest.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional fixed run id. Defaults to a timestamp-based id.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_demo_config(args.config)
    outcome = create_backtest_run(
        config,
        refresh_data=args.refresh_data,
        run_id=args.run_id,
    )
    payload = {
        "status": "ok",
        "boundary": "paper/simulated",
        "run_id": outcome["run_id"],
        "report_dir": str(outcome["report_dir"]),
        "summary_path": str(Path(outcome["report_dir"]) / "summary.json"),
        "report_path": str(Path(outcome["report_dir"]) / "report.md"),
        "trades_path": str(Path(outcome["report_dir"]) / "trades.csv"),
        "equity_curve_path": str(Path(outcome["report_dir"]) / "equity_curve.png"),
        "core_results": outcome["summary"]["core_results"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
