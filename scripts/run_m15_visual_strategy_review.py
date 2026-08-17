#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_visual_strategy_acceptance_lib import (
    generate_acceptance_evidence,
    load_acceptance_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record one explicit human review for an M15 visual-strategy candidate."
    )
    parser.add_argument(
        "--config",
        default="config/examples/m15_visual_strategy_acceptance.json",
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--decision", required=True, choices=("pass", "reject"))
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    config = load_acceptance_config(args.config)
    if config.human_review_ledger_path is None:
        raise SystemExit("human_review_ledger is not configured")
    evidence = json.loads(config.output_path.read_text(encoding="utf-8"))
    candidate = None
    for strategy_id in ("PA004", "PA007", "PA008"):
        for case_type in ("positive", "negative", "boundary"):
            for row in (evidence.get(strategy_id) or {}).get("candidate_examples", {}).get(case_type, []):
                if str(row.get("case_id") or "") == args.case_id:
                    candidate = row
                    break
            if candidate is not None:
                break
        if candidate is not None:
            break
    if candidate is None:
        raise SystemExit(f"candidate not found in current acceptance evidence: {args.case_id}")

    review = {
        "schema_version": "m15.visual-strategy-human-review.v1",
        "reviewed_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "reviewer": args.reviewer,
        "strategy_id": candidate["strategy_id"],
        "runtime_id": candidate["runtime_id"],
        "case_id": candidate["case_id"],
        "case_type": candidate["case_type"],
        "candidate_fingerprint": candidate["candidate_fingerprint"],
        "decision": args.decision,
        "note": args.note,
    }
    config.human_review_ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with config.human_review_ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(review, ensure_ascii=False, sort_keys=True) + "\n")
    refreshed = generate_acceptance_evidence(config)
    print(
        json.dumps(
            {
                "recorded_review": review,
                "current_strategy_acceptance": refreshed.get(review["strategy_id"]),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
