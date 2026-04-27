#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_read_only_runbook_lib import M10_13_DIR, run_m10_13_read_only_runbook


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate M10.13 read-only observation runbook artifacts.")
    parser.add_argument(
        "--output-dir",
        default=str(M10_13_DIR),
        help="Output directory for M10.13 read-only observation runbook artifacts.",
    )
    args = parser.parse_args()
    summary = run_m10_13_read_only_runbook(Path(args.output_dir))
    print(
        "M10.13 read-only observation runbook complete: "
        f"{summary['primary_strategy_count']} strategies / "
        f"{summary['primary_strategy_timeframe_count']} strategy-timeframes -> {summary['output_dir']}"
    )


if __name__ == "__main__":
    main()
