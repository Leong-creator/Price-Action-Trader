#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m11_paper_gate_lib import M11_DIR, run_m11_paper_gate


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate M11 paper gate artifacts.")
    parser.add_argument(
        "--output-dir",
        default=str(M11_DIR),
        help="Output directory for M11 paper gate artifacts.",
    )
    args = parser.parse_args()
    summary = run_m11_paper_gate(Path(args.output_dir))
    print(
        "M11 paper gate complete: "
        f"{summary['gate_decision']}, {summary['candidate_strategy_count']} candidates -> {summary['output_dir']}"
    )


if __name__ == "__main__":
    main()
