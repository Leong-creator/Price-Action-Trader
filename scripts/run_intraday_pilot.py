#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.intraday_pilot_lib import create_intraday_pilot_run, load_intraday_pilot_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a single-symbol intraday paper/simulated pilot on cached SPY 15m data."
    )
    parser.add_argument(
        "--config",
        default="config/examples/intraday_pilot_spy_15m.json",
        help="Path to the intraday pilot config JSON.",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Refresh the local intraday cache before running the pilot.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional fixed run id. Defaults to a timestamp-based id.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_intraday_pilot_config(args.config)
    outcome = create_intraday_pilot_run(
        config,
        refresh_data=args.refresh_data,
        run_id=args.run_id,
    )
    report_dir = Path(outcome["report_dir"])
    payload = {
        "status": "ok",
        "boundary": "paper/simulated",
        "run_id": outcome["run_id"],
        "report_dir": str(report_dir),
        "summary_path": str(report_dir / "summary.json"),
        "session_summary_path": str(report_dir / "session_summary.json"),
        "session_quality_path": str(report_dir / "session_quality.json"),
        "knowledge_trace_path": str(report_dir / "knowledge_trace.json"),
        "knowledge_trace_coverage_path": str(report_dir / "knowledge_trace_coverage.json"),
        "no_trade_wait_path": str(report_dir / "no_trade_wait.jsonl"),
        "report_path": str(report_dir / "report.md"),
        "trades_path": str(report_dir / "trades.csv"),
        "equity_curve_path": str(report_dir / "equity_curve.png"),
        "core_results": outcome["summary"]["core_results"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
