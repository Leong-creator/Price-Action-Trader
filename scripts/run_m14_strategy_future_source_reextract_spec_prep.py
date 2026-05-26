#!/usr/bin/env python3
from __future__ import annotations

import argparse

from m14_strategy_future_source_reextract_spec_prep_lib import (
    load_config,
    run_m14_strategy_future_source_reextract_spec_prep,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare M14 conditional future source-reextract spec drafts."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to M14 strategy future source-reextract spec prep config JSON.",
    )
    args = parser.parse_args()
    config = load_config(args.config) if args.config else load_config()
    payload = run_m14_strategy_future_source_reextract_spec_prep(config)
    summary = payload["summary"]
    print(
        "M14 strategy future source-reextract spec prep generated "
        f"{summary['future_source_reextract_spec_prep_row_count']} rows; "
        f"unblocked={summary['future_spec_unblocked_count']}; "
        f"blocked={summary['blocked_until_manual_visual_confirmation_count']}; "
        f"legacy_history_inputs={summary['legacy_historical_profit_planning_input_count']}."
    )


if __name__ == "__main__":
    main()
