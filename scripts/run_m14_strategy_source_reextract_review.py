#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from m14_strategy_source_reextract_review_lib import (
    DEFAULT_CONFIG_PATH,
    load_config,
    run_m14_strategy_source_reextract_review,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build M14 strategy source reextract review.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Config JSON path.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at timestamp.")
    args = parser.parse_args()

    payload = run_m14_strategy_source_reextract_review(
        load_config(args.config),
        generated_at=args.generated_at,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
