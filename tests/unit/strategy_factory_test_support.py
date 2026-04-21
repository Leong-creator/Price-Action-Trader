from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORMAL_CATEGORIES = {
    "strategy_candidate",
    "supporting_evidence",
    "non_strategy",
    "open_question",
    "parked_visual_review",
    "duplicate_or_merged",
    "blocked_or_partial_evidence",
}


def load_json(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def load_jsonl(relative_path: str):
    rows = []
    with (ROOT / relative_path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")
