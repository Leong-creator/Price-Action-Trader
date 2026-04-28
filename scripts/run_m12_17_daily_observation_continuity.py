#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_17_daily_observation_continuity_lib import run_m12_17_daily_observation_continuity


def main() -> None:
    summary = run_m12_17_daily_observation_continuity()
    day = summary["current_day"]
    print(
        "M12.17 daily observation continuity complete: "
        f"opportunities={day['today_opportunity_count']} "
        f"pnl={day['today_simulated_unrealized_pnl']} "
        f"recorded_days={summary['day_count_recorded']}/10"
    )


if __name__ == "__main__":
    main()
