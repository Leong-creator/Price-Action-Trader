#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_realtime_position_manager_lib import DEFAULT_CONFIG_PATH, SUMMARY_JSON, load_config, run_realtime_position_manager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage Longbridge paper realtime position exits.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to realtime position-manager config JSON.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at ISO timestamp for deterministic tests.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    payload = run_realtime_position_manager(config, generated_at=args.generated_at)
    print(config.output_dir / SUMMARY_JSON)
    print(payload.get("plain_language_result", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
