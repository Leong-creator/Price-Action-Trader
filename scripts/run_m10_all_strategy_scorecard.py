#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_all_strategy_scorecard_lib import M10_12_DIR, run_m10_12_all_strategy_scorecard


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate M10.12 all-strategy scorecard artifacts.")
    parser.add_argument(
        "--output-dir",
        default=str(M10_12_DIR),
        help="Output directory for M10.12 all-strategy scorecard artifacts.",
    )
    args = parser.parse_args()
    summary = run_m10_12_all_strategy_scorecard(Path(args.output_dir))
    portfolio = summary["portfolio_proxy"]
    print(
        "M10.12 all-strategy scorecard complete: "
        f"{summary['strategy_count']} strategies, proxy final equity "
        f"{portfolio['proxy_final_equity']} -> {summary['output_dir']}"
    )


if __name__ == "__main__":
    main()
