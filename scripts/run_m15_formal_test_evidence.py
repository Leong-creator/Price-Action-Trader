#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_formal_test_evidence_lib import (
    DEFAULT_CONFIG_PATH,
    generate_formal_test_evidence,
    load_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate layered M15 formal-test evidence.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args()
    payload = generate_formal_test_evidence(
        load_config(args.config), generated_at=args.generated_at
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
