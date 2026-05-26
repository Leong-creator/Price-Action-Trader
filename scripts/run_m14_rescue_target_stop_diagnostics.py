#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m14_rescue_target_stop_diagnostics_lib import load_config, run_m14_rescue_target_stop_diagnostics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose M14 rescue target/stop geometry for reward/R blockers.")
    parser.add_argument("--config", default=None, help="Path to M14 rescue target/stop diagnostics config.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at ISO timestamp.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config) if args.config else load_config()
    result = run_m14_rescue_target_stop_diagnostics(config, generated_at=args.generated_at)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
