#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.strategy_factory import run_strategy_factory_batch_backtest  # noqa: E402


def main() -> int:
    result = run_strategy_factory_batch_backtest(ROOT)
    summary = {
        "run_id": result["run_id"],
        "provider": result["provider"],
        "eligible_strategy_count": result["batch_summary"]["eligible_strategy_count"],
        "tested_strategy_count": result["batch_summary"]["tested_strategy_count"],
        "triage_counts": result["batch_summary"]["triage_counts"],
        "report_path": str(result["report_path"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
