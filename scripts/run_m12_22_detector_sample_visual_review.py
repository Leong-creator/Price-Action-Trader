#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_22_detector_sample_visual_review_lib import run_m12_22_detector_sample_visual_review


def main() -> None:
    summary = run_m12_22_detector_sample_visual_review()
    counts = summary["visual_review_decision_counts"]
    print(
        "M12.22 detector sample visual review complete: "
        f"reviewed={summary['reviewed_event_count']} "
        f"charts={summary['annotated_chart_packet_count']} "
        f"valid={counts['looks_valid']} "
        f"borderline={counts['borderline_needs_chart_review']} "
        f"false_positive={counts['likely_false_positive']}"
    )


if __name__ == "__main__":
    main()
