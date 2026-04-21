#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from strategy_factory import run_full_extraction_audit  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the M9 Strategy Factory Full Extraction Completeness Audit v4."
    )
    parser.add_argument(
        "--repo-root",
        default=ROOT,
        type=Path,
        help="Repository root. Defaults to the current project root.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_full_extraction_audit(args.repo_root.resolve())
    audit = result["full_extraction_audit"]
    print(
        "Strategy Factory full extraction audit completed: "
        f"chunks={audit['total_parseable_chunks']} "
        f"strategies={audit['final_strategy_card_count']} "
        f"text_extractable_closure={str(audit['text_extractable_closure']).lower()} "
        f"full_source_closure={str(audit['full_source_closure']).lower()} "
        f"ready_for_backtest={str(audit['ready_for_backtest']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
