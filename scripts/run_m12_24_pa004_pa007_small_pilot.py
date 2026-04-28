#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_24_pa004_pa007_small_pilot_lib import run_m12_24_pa004_pa007_small_pilot


def main() -> None:
    summary = run_m12_24_pa004_pa007_small_pilot()
    decisions = {row["strategy_id"]: row["decision"] for row in summary["decision_rows"]}
    print(
        "M12.24 PA004/PA007 small pilot complete: "
        f"candidate_trades={summary['candidate_trade_count']} "
        f"executed={summary['baseline_executed_trade_count']} "
        f"decisions={decisions}"
    )


if __name__ == "__main__":
    main()
