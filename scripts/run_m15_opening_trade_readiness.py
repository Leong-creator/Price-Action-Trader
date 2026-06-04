#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.m15_opening_trade_readiness_lib import load_config, run_m15_opening_trade_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the M15 opening trade readiness artifact.")
    parser.add_argument("--config", default=None, help="Path to M15 opening trade readiness config JSON.")
    parser.add_argument("--generated-at", default=None, help="UTC timestamp used for deterministic artifacts.")
    args = parser.parse_args()
    config = load_config(args.config) if args.config else load_config()
    payload = run_m15_opening_trade_readiness(config, generated_at=args.generated_at)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
