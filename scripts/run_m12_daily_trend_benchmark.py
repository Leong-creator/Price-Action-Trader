#!/usr/bin/env python3
from __future__ import annotations

from m12_daily_trend_benchmark_lib import load_benchmark_config, run_m12_daily_trend_benchmark


def main() -> int:
    config = load_benchmark_config()
    summary = run_m12_daily_trend_benchmark(config)
    core = summary["core_results"]
    print(
        "M12.7 daily trend benchmark complete: "
        f"{summary['benchmark_decision']} / events={core['benchmark_event_count']} / "
        f"sim_return={core['simulated_return_percent']}% -> {summary['comparison_artifact']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
