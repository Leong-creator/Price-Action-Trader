#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_21_detector_quality_review_lib import run_m12_21_detector_quality_review


def main() -> None:
    summary = run_m12_21_detector_quality_review()
    print(
        "M12.21 detector quality review complete: "
        f"reviewed={summary['reviewed_event_count']} "
        f"pass={summary['machine_pass_count']} "
        f"pass_percent={summary['machine_pass_percent']}% "
        f"spot_check={summary['needs_spot_check_count']} "
        f"reject={summary['auto_reject_count']}"
    )


if __name__ == "__main__":
    main()
