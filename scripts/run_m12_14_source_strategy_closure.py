#!/usr/bin/env python3
from __future__ import annotations

from m12_14_source_strategy_closure_lib import run_m12_14_source_strategy_closure


def main() -> None:
    summary = run_m12_14_source_strategy_closure()
    metrics = summary["early_strategy_result"]["current_metrics"]
    print(
        "M12.14 source strategy closure complete: "
        f"early_strategy={summary['early_strategy_result']['strategy_id']} "
        f"return={metrics['return_percent']}% "
        f"max_drawdown={metrics['max_drawdown_percent']}% "
        f"source_candidates={summary['source_revisit_candidate_count']} "
        f"visual_cases_closed={summary['visual_cases_closed_without_user_review']}"
    )


if __name__ == "__main__":
    main()
