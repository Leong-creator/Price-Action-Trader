#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_23_detector_tightening_rerun_lib import run_m12_23_detector_tightening_rerun


def main() -> None:
    summary = run_m12_23_detector_tightening_rerun()
    counts = summary["strict_visual_review_counts"]
    print(
        "M12.23 detector tightening rerun complete: "
        f"retained={summary['strict_retained_event_count']} "
        f"valid={counts['looks_valid']} "
        f"borderline={counts['borderline_needs_chart_review']} "
        f"false_positive={counts['likely_false_positive']} "
        f"small_pilot={summary['can_enter_small_pilot_next']}"
    )


if __name__ == "__main__":
    main()
