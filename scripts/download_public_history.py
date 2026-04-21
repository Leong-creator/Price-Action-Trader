#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.public_backtest_demo_lib import download_and_cache_dataset, load_demo_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and cache historical market data for the user-readable backtest demo."
    )
    parser.add_argument(
        "--config",
        default="config/examples/public_history_backtest_long_horizon_longbridge.json",
        help="Path to the demo config JSON.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-download even when the local cache file already exists.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_demo_config(args.config)
    downloaded = []
    for instrument in config.instruments:
        record = download_and_cache_dataset(config, instrument, refresh=args.refresh)
        downloaded.append(
            {
                "symbol": instrument.symbol,
                "label": instrument.label,
                "source": record.source,
                "csv_path": str(record.csv_path),
                "metadata_path": str(record.metadata_path),
                "row_count": record.row_count,
            }
        )
    payload = {
        "status": "ok",
        "boundary": "paper/simulated",
        "config": str(Path(args.config).resolve()),
        "downloaded": downloaded,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
