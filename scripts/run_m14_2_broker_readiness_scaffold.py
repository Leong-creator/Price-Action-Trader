#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m14_2_broker_readiness_scaffold_lib import load_config, run_broker_readiness_scaffold


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build M14.2 broker readiness dry-run artifacts.")
    parser.add_argument("--config", default=None, help="Path to M14.2 broker readiness scaffold config.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at ISO timestamp.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config) if args.config else load_config()
    result = run_broker_readiness_scaffold(config, generated_at=args.generated_at)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
