#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_19_visual_detector_prototypes_lib import run_m12_19_visual_detector_prototypes


def main() -> None:
    summary = run_m12_19_visual_detector_prototypes()
    print(
        "M12.19 visual detector prototypes complete: "
        f"candidates={summary['candidate_count']} "
        f"PA004={summary['candidate_count_by_strategy'].get('M10-PA-004', 0)} "
        f"PA007={summary['candidate_count_by_strategy'].get('M10-PA-007', 0)}"
    )


if __name__ == "__main__":
    main()
