#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.strategy_factory import run_strategy_factory_wave3_validation  # noqa: E402


def main() -> int:
    result = run_strategy_factory_wave3_validation(ROOT)
    summary = {
        "run_id": result["run_id"],
        "provider": result["provider"],
        "strict_holdout_available": result["strict_holdout_available"],
        "data_window": result["data_window"],
        "triage_counts": result["triage_counts"],
        "report_path": str(result["report_path"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
