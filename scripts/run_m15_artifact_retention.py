#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.m15_artifact_retention_lib import load_config, parse_args, run_artifact_retention


def main() -> None:
    args = parse_args()
    payload = run_artifact_retention(
        load_config(args.config),
        execute=args.execute,
        generated_at=args.generated_at,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
