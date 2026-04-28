#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_25_daily_observation_continuity_lib import run_m12_25_daily_observation_continuity


def main() -> None:
    summary = run_m12_25_daily_observation_continuity()
    print(
        "M12.25 daily observation continuity complete: "
        f"days={summary['day_count_recorded']}/10 "
        f"mainline={','.join(summary['mainline_strategy_scope'])} "
        f"observation_only={','.join(summary['observation_only_strategy_scope'])}"
    )


if __name__ == "__main__":
    main()
