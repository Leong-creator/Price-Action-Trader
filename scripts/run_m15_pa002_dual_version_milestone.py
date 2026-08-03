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

from scripts.m15_pa002_dual_version_milestone_lib import run_pa002_dual_version_milestone_evaluator


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate PA002 dual-version postmarket milestone status from Longbridge fills.")
    parser.add_argument("--account-config", default="config/examples/m15_longbridge_realtime_account_state.json")
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    generated_at = datetime.fromisoformat(args.generated_at.replace("Z", "+00:00")) if args.generated_at else datetime.now(UTC)
    payload = run_pa002_dual_version_milestone_evaluator(
        args.account_config,
        generated_at=generated_at,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
