#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m14_strategy_rescue_plan_lib import load_config, run_m14_strategy_rescue_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the M14 strategy rescue and optimization plan.")
    parser.add_argument("--config", default=None, help="Path to M14 rescue plan config JSON.")
    parser.add_argument("--generated-at", default=None, help="UTC timestamp used for deterministic artifacts.")
    args = parser.parse_args()

    config = load_config(args.config) if args.config else load_config()
    result = run_m14_strategy_rescue_plan(config, generated_at=args.generated_at)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
