#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_m14_local_postclose_batch_lib import (
    load_local_postclose_batch_config,
    run_local_postclose_batch,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local postclose M12 -> M13 -> M14 batch once.")
    parser.add_argument("--config", default=None, help="Path to the local postclose batch config.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at in UTC ISO8601 format.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_local_postclose_batch_config(args.config) if args.config else load_local_postclose_batch_config()
    run_local_postclose_batch(config, generated_at=args.generated_at)


if __name__ == "__main__":
    main()
