#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_15_ftd_v02_ab_retest_lib import run_m12_15_ftd_v02_ab_retest


def main() -> None:
    summary = run_m12_15_ftd_v02_ab_retest()
    best = summary["best_variant"]
    metrics = best["metrics"]
    print(
        "M12.15 FTD v0.2 A/B retest complete: "
        f"best={best['selected_variant_id']} "
        f"return={metrics['return_percent']}% "
        f"max_drawdown={metrics['max_drawdown_percent']}% "
        f"win_rate={metrics['win_rate']}% "
        f"trades={metrics['trade_count']}"
    )


if __name__ == "__main__":
    main()
