#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pa_sc_002_backtest_lib import build_default_config, run_experiment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the PA-SC-002 + PA-SC-009 minimum SPY 5m experiment.",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Refresh the cached SPY 5m dataset from yfinance before running.",
    )
    parser.add_argument(
        "--summary-json",
        action="store_true",
        help="Print the generated summary JSON to stdout after the run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = build_default_config()
    summary = run_experiment(config, refresh_data=args.refresh_data)
    print(f"report={config.report_path}")
    print(f"summary={config.summary_path}")
    if args.summary_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
