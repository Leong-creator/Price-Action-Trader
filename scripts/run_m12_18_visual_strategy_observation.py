#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_18_visual_strategy_observation_lib import run_m12_18_visual_strategy_observation


def main() -> None:
    summary = run_m12_18_visual_strategy_observation()
    print(
        "M12.18 visual strategy observation complete: "
        f"events={summary['event_count']} "
        f"MTR={summary['event_count_by_strategy'].get('M10-PA-008', 0)} "
        f"wedge={summary['event_count_by_strategy'].get('M10-PA-009', 0)}"
    )


if __name__ == "__main__":
    main()
