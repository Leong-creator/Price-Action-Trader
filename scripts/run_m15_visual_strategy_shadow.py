#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_visual_strategy_shadow_lib import load_config, run_visual_strategy_shadow


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the read-only M15 visual strategy shadow audit.")
    parser.add_argument("--config", default=None, help="Path to visual strategy shadow config JSON.")
    parser.add_argument("--generated-at", default=None, help="Deterministic audit observation timestamp.")
    args = parser.parse_args()
    config = load_config(args.config) if args.config else load_config()
    summary = run_visual_strategy_shadow(config, generated_at=args.generated_at)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
