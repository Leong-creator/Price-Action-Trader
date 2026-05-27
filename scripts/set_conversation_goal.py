#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "conversation_goal"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_goal(goal: str) -> str:
    normalized = " ".join(goal.strip().split())
    if not normalized:
        raise ValueError("goal must not be empty")
    return normalized


def build_goal_record(
    goal: str,
    *,
    generated_at: str | None = None,
    source: str = "manual",
    context: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "conversation.goal.v1",
        "goal": normalize_goal(goal),
        "generated_at": generated_at or utc_now_iso(),
        "source": source,
        "context": context or "",
        "priority": "below_AGENTS_active_plan_implement_status",
        "hard_constraints": [
            "Follow AGENTS.md, plans/active-plan.md, docs/implement.md, and docs/status.md.",
            "Do not connect real broker accounts, place orders, or enable real-money execution.",
            "Do not fabricate market data, trades, backtest results, paper results, or approvals.",
        ],
    }


def render_goal_markdown(record: dict[str, Any]) -> str:
    constraints = "\n".join(f"- {item}" for item in record["hard_constraints"])
    context = record["context"] or "无"
    return f"""# Conversation Goal

Goal: {record["goal"]}

Generated at: `{record["generated_at"]}`

Source: `{record["source"]}`

Context: {context}

Priority: `{record["priority"]}`

Hard constraints:
{constraints}
"""


def write_goal_files(record: dict[str, Any], output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "current_goal.json"
    md_path = output_dir / "current_goal.md"
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_goal_markdown(record), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Set the repo-local conversation goal. This is the supported fallback when "
            "the Codex client does not expose a /goal slash command."
        )
    )
    parser.add_argument("goal", nargs="*", help="Goal text. Prefer a concise single sentence.")
    parser.add_argument("--goal", dest="goal_flag", default=None, help="Goal text, equivalent to the positional form.")
    parser.add_argument("--context", default=None, help="Optional context for the current conversation.")
    parser.add_argument("--source", default="manual", help="Where this goal came from.")
    parser.add_argument("--generated-at", default=None, help="Deterministic UTC timestamp for tests or replay.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for current_goal.json/current_goal.md.")
    args = parser.parse_args()

    goal = args.goal_flag if args.goal_flag is not None else " ".join(args.goal)
    try:
        record = build_goal_record(
            goal,
            generated_at=args.generated_at,
            source=args.source,
            context=args.context,
        )
    except ValueError as exc:
        parser.error(str(exc))

    paths = write_goal_files(record, Path(args.output_dir))
    print(json.dumps({name: str(path) for name, path in paths.items()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
