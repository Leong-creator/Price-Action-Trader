#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_sdk_analytics_lib import run_sdk_analytics


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Longbridge paper analytics through the SDK only.")
    parser.add_argument("--sdk-config", default="config/examples/m15_longbridge_sdk_runtime.json")
    parser.add_argument("--account-config", default="config/examples/m15_longbridge_realtime_account_state.json")
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated_at = datetime.fromisoformat(args.generated_at.replace("Z", "+00:00")) if args.generated_at else datetime.now(UTC)
    print(json.dumps(run_sdk_analytics(args.sdk_config, args.account_config, generated_at=generated_at), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
