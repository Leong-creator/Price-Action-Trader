#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_definition_tightening_lib import M10_9_DIR, run_m10_9_definition_tightening


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M10.9 PA-005 definition tightening retest.")
    parser.add_argument(
        "--output-dir",
        default=str(M10_9_DIR),
        help="Output directory for M10.9 definition tightening artifacts.",
    )
    args = parser.parse_args()
    summary = run_m10_9_definition_tightening(Path(args.output_dir))
    print(
        "M10.9 definition tightening complete: "
        f"{summary['strategy_id']} -> {summary['output_dir']}"
    )


if __name__ == "__main__":
    main()
