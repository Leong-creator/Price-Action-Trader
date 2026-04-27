#!/usr/bin/env python3
from __future__ import annotations

from m12_weekly_client_scorecard_lib import load_scorecard_config, run_m12_weekly_client_scorecard


def main() -> int:
    config = load_scorecard_config()
    summary = run_m12_weekly_client_scorecard(config)
    print(
        f"M12.6 weekly scorecard complete: {summary['strategy_count']} strategies -> "
        f"{summary['output_dir']}/m12_6_weekly_client_scorecard.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
