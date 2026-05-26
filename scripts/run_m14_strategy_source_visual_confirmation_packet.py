#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from m14_strategy_source_visual_confirmation_packet_lib import (
    DEFAULT_CONFIG_PATH,
    load_config,
    run_m14_strategy_source_visual_confirmation_packet,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the M14 strategy source visual confirmation packet.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config JSON.")
    args = parser.parse_args()
    payload = run_m14_strategy_source_visual_confirmation_packet(load_config(args.config))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
