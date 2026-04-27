#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_wave_b_capital_backtest_lib import M10_11_DIR, run_m10_11_wave_b_capital_backtest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M10.11 Wave B capital backtest.")
    parser.add_argument(
        "--output-dir",
        default=str(M10_11_DIR),
        help="Output directory for M10.11 Wave B capital backtest artifacts.",
    )
    args = parser.parse_args()
    summary = run_m10_11_wave_b_capital_backtest(Path(args.output_dir))
    print(
        "M10.11 Wave B capital backtest complete: "
        f"{summary['trade_ledger_rows']} baseline trades -> {summary['output_dir']}"
    )


if __name__ == "__main__":
    main()
