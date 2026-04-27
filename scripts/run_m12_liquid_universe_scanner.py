#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_liquid_universe_scanner_lib import (  # noqa: E402
    load_scanner_config,
    run_m12_liquid_universe_scanner,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M12.5 liquid universe scanner.")
    parser.add_argument(
        "--config",
        default="config/examples/m12_liquid_universe_scanner.json",
        help="Path to M12.5 scanner config.",
    )
    parser.add_argument("--output-dir", default=None, help="Optional output directory override.")
    args = parser.parse_args()

    config = load_scanner_config(args.config)
    if args.output_dir:
        config = replace(config, output_dir=Path(args.output_dir))
    summary = run_m12_liquid_universe_scanner(config)
    print(f"M12.5 scanner complete: {summary['candidate_count']} candidates -> {summary['artifacts']['scanner_summary']}")


if __name__ == "__main__":
    main()
