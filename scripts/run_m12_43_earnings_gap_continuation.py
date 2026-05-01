#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.m12_40_news_earnings_lib import load_config, run_m12_43


def main() -> int:
    parser = argparse.ArgumentParser(description="Run M12.43 earnings gap continuation prototype.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args()
    summary = run_m12_43(load_config(args.config) if args.config else None, generated_at=args.generated_at)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
