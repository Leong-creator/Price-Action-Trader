#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_visual_strategy_shadow_session_lib import load_config, run_visual_shadow_session


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and process one complete M15 SDK visual shadow session.")
    parser.add_argument("--config", default=None, help="Path to visual shadow session config JSON.")
    parser.add_argument("--business-date", default=None, help="New York trading date in YYYY-MM-DD format.")
    parser.add_argument("--generated-at", default=None, help="Deterministic UTC observation timestamp.")
    args = parser.parse_args()
    config = load_config(args.config) if args.config else load_config()
    result = run_visual_shadow_session(
        config,
        business_date=args.business_date,
        generated_at=args.generated_at,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"completed", "already_completed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
