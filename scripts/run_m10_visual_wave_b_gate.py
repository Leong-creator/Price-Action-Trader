#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_visual_wave_b_gate_lib import M10_10_DIR, run_m10_10_visual_wave_b_gate


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M10.10 visual Wave B gate.")
    parser.add_argument(
        "--output-dir",
        default=str(M10_10_DIR),
        help="Output directory for M10.10 visual Wave B gate artifacts.",
    )
    args = parser.parse_args()
    summary = run_m10_10_visual_wave_b_gate(Path(args.output_dir))
    print(
        "M10.10 visual Wave B gate complete: "
        f"{len(summary['wave_b_strategy_ids'])} Wave B candidates -> {summary['output_dir']}"
    )


if __name__ == "__main__":
    main()
