#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_paper_session_report_lib import DEFAULT_CONFIG_PATH, load_config, run_session_report  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a readonly Longbridge paper account session report.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args()
    payload = run_session_report(load_config(args.config), generated_at=args.generated_at)
    print(f"{payload['outputs']['summary']}\n{payload['plain_language_result']}")


if __name__ == "__main__":
    main()
