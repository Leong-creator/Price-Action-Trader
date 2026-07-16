#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_dashboard_lib import DEFAULT_CONFIG_PATH, load_config, run_dashboard  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="生成独立的长桥 SDK 模拟账户看板。")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args()
    payload = run_dashboard(load_config(args.config), generated_at=args.generated_at)
    print(f"{payload['data_status']} runtime={payload['strategy_inventory']['runtime_count']}")


if __name__ == "__main__":
    main()
