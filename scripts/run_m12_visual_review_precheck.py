#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_visual_review_precheck_lib import (
    DEFAULT_CONFIG_PATH,
    load_visual_precheck_config,
    run_m12_visual_precheck,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M12.3 visual review precheck.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to M12.3 config JSON.")
    parser.add_argument("--output-dir", default=None, help="Override output directory.")
    args = parser.parse_args()

    config = load_visual_precheck_config(args.config)
    if args.output_dir:
        config = replace(config, output_dir=Path(args.output_dir))
    index = run_m12_visual_precheck(config)
    print(
        "M12.3 visual precheck complete: "
        f"{index['strategy_count']} strategies, {index['case_count']} cases -> {config.output_dir}"
    )


if __name__ == "__main__":
    main()
