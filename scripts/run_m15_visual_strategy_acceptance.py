#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_visual_strategy_acceptance_lib import generate_acceptance_evidence, load_acceptance_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Build machine-verifiable M15 visual strategy acceptance evidence.")
    parser.add_argument(
        "--config",
        default="config/examples/m15_visual_strategy_acceptance.json",
        help="Path to the visual acceptance config JSON.",
    )
    parser.add_argument("--generated-at", default=None, help="Deterministic acceptance timestamp.")
    args = parser.parse_args()
    summary = generate_acceptance_evidence(
        load_acceptance_config(args.config),
        generated_at=args.generated_at,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
