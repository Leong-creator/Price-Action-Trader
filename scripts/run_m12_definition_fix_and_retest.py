#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_definition_fix_and_retest_lib import (  # noqa: E402
    load_definition_fix_config,
    run_m12_definition_fix_and_retest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M12.4 definition fix and retest summary.")
    parser.add_argument(
        "--config",
        default="config/examples/m12_definition_fix_and_retest.json",
        help="Path to the M12.4 config JSON.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional output directory override.",
    )
    args = parser.parse_args()

    config = load_definition_fix_config(args.config)
    if args.output_dir:
        config = replace(config, output_dir=Path(args.output_dir))
    summary = run_m12_definition_fix_and_retest(config)
    print(f"M12.4 definition fix summary complete: {summary['run_id']} -> {summary['artifacts']['summary_json']}")


if __name__ == "__main__":
    main()
