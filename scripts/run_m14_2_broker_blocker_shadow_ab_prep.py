#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m14_2_broker_blocker_shadow_ab_prep_lib import load_config, run_broker_blocker_shadow_ab_prep


def main() -> int:
    parser = argparse.ArgumentParser(description="Build M14.2 broker blocker shadow A/B prep artifacts.")
    parser.add_argument("--config", default=None, help="Path to M14.2 broker blocker shadow A/B prep config.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp for reproducible tests.")
    args = parser.parse_args()

    config = load_config(args.config) if args.config else load_config()
    result = run_broker_blocker_shadow_ab_prep(config, generated_at=args.generated_at)
    print(result["plain_language_result"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
