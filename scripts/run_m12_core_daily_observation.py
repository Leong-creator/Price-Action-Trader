#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_core_daily_observation_lib import (
    DEFAULT_CONFIG_PATH,
    load_daily_observation_config,
    run_m12_core_daily_observation,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M12.2 core strategy daily read-only observation.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to M12.2 config JSON.")
    parser.add_argument("--output-dir", default=None, help="Override output directory.")
    args = parser.parse_args()

    config = load_daily_observation_config(args.config)
    if args.output_dir:
        config = replace(config, output_dir=Path(args.output_dir))
    status = run_m12_core_daily_observation(config)
    print(
        "M12.2 daily observation complete: "
        f"{status['event_count']} rows, {status['candidate_event_count']} candidates -> {config.output_dir}"
    )


if __name__ == "__main__":
    main()
