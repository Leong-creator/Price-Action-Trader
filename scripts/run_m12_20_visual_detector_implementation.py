#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_20_visual_detector_implementation_lib import run_m12_20_visual_detector_implementation


def main() -> None:
    summary = run_m12_20_visual_detector_implementation()
    counts = summary["detector_event_count_by_strategy"]
    print(
        "M12.20 visual detectors complete: "
        f"events={summary['detector_event_count']} "
        f"PA004={counts.get('M10-PA-004', 0)} "
        f"PA007={counts.get('M10-PA-007', 0)} "
        f"daily_cache_ready_symbols={summary['daily_cache_ready_symbols']}"
    )


if __name__ == "__main__":
    main()
