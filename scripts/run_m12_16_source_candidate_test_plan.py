#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_16_source_candidate_test_plan_lib import run_m12_16_source_candidate_test_plan


def main() -> None:
    summary = run_m12_16_source_candidate_test_plan()
    print(
        "M12.16 source candidate test plan complete: "
        f"daily={summary['daily_readonly_test_count']} "
        f"filters={summary['filter_or_ranking_factor_count']} "
        f"observation={summary['strict_observation_count']} "
        f"ftd_variant={summary['selected_ftd_variant']}"
    )


if __name__ == "__main__":
    main()
