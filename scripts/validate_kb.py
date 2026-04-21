#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


ALLOWED_TYPES = {
    "concept",
    "setup",
    "rule",
    "indicator",
    "market-regime",
    "risk",
    "source",
    "glossary",
    "case-study",
}
ALLOWED_STATUS = {
    "draft",
    "active",
    "experimental",
    "superseded",
    "candidate",
    "tested",
    "promoted",
    "rejected",
}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_DIRECTION = {"long", "short", "both", "neutral"}
ALLOWED_CHART_DEPENDENCY = {"low", "medium", "high"}
ALLOWED_TEST_PRIORITY = {"high", "medium", "low"}
STRATEGY_CARD_PARENT_DIRS = {"brooks", "fangfangtu", "combined"}
SKIP_DIR_NAMES = {"templates"}

REQUIRED_FIELDS = [
    "title",
    "type",
    "status",
    "confidence",
    "source_refs",
    "last_reviewed",
]

SETUP_REQUIRED_FIELDS = [
    "pa_context",
    "signal_bar",
    "entry_trigger",
    "stop_rule",
    "invalidation",
]

LIST_FIELDS = [
    "market",
    "market_context",
    "timeframes",
    "source_refs",
    "tags",
    "applicability",
    "not_applicable",
    "contradictions",
    "missing_visuals",
    "open_questions",
    "pa_context",
    "market_cycle",
    "higher_timeframe_context",
    "bar_by_bar_notes",
    "signal_bar",
    "entry_trigger",
    "entry_bar",
    "stop_rule",
    "target_rule",
    "trade_management",
    "invalidation",
]

STRATEGY_CARD_REQUIRED_FIELDS = [
    "strategy_id",
    "source_family",
    "setup_family",
    "market_context",
    "evidence_quality",
    "chart_dependency",
    "needs_visual_review",
    "test_priority",
    "last_updated",
]


def parse_scalar(raw: str):
    value = raw.strip()
    if value == "":
        return ""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if inner == "":
            return []
        parts = [part.strip() for part in inner.split(",")]
        result = []
        for part in parts:
            if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'}:
                result.append(part[1:-1])
            else:
                result.append(part)
        return result
    if value in {"[]", "{}"} or value.startswith("{") or (
        len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}
    ):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value
    return value


def parse_frontmatter(text: str):
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return None

    data: dict[str, object] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return data
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = parse_scalar(value)
    return None


def should_skip_file(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def is_strategy_card(path: Path) -> bool:
    return "strategy_cards" in path.parts and path.parent.name in STRATEGY_CARD_PARENT_DIRS


def list_markdown_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if not should_skip_file(path))


def is_missing(value: object) -> bool:
    return value is None or value == "" or value == []


def is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def validate_enum(path: Path, frontmatter: dict[str, object], errors: list[str]) -> None:
    page_type = frontmatter.get("type")
    if page_type not in ALLOWED_TYPES:
        errors.append(f"{path}: invalid 'type' value '{page_type}'")

    status = frontmatter.get("status")
    if status not in ALLOWED_STATUS:
        errors.append(f"{path}: invalid 'status' value '{status}'")

    confidence = frontmatter.get("confidence")
    if confidence not in ALLOWED_CONFIDENCE:
        errors.append(f"{path}: invalid 'confidence' value '{confidence}'")

    direction = frontmatter.get("direction", "")
    if direction not in ("", *sorted(ALLOWED_DIRECTION)):
        errors.append(f"{path}: invalid 'direction' value '{direction}'")


def validate_list_fields(path: Path, frontmatter: dict[str, object], errors: list[str]) -> None:
    for field in LIST_FIELDS:
        value = frontmatter.get(field, [])
        if value == "":
            continue
        if not isinstance(value, list):
            errors.append(f"{path}: field '{field}' must be a list")


def validate_scalar_fields(path: Path, frontmatter: dict[str, object], errors: list[str]) -> None:
    last_reviewed = frontmatter.get("last_reviewed")
    if last_reviewed is not None and not is_non_empty_string(last_reviewed):
        errors.append(f"{path}: field 'last_reviewed' must be a non-empty string")

    last_updated = frontmatter.get("last_updated")
    if last_updated not in ("", None) and not is_non_empty_string(last_updated):
        errors.append(f"{path}: field 'last_updated' must be a non-empty string when provided")

    measured_move = frontmatter.get("measured_move")
    if measured_move not in ("", None) and not isinstance(measured_move, bool):
        errors.append(f"{path}: field 'measured_move' must be boolean when provided")

    needs_visual_review = frontmatter.get("needs_visual_review")
    if needs_visual_review not in ("", None) and not isinstance(needs_visual_review, bool):
        errors.append(f"{path}: field 'needs_visual_review' must be boolean when provided")

    risk_reward_min = frontmatter.get("risk_reward_min")
    if risk_reward_min not in ("", None):
        if isinstance(risk_reward_min, bool):
            errors.append(f"{path}: field 'risk_reward_min' must be numeric when provided")
        elif isinstance(risk_reward_min, str):
            try:
                float(risk_reward_min)
            except ValueError:
                errors.append(f"{path}: field 'risk_reward_min' must be numeric when provided")

    for field in ("strategy_id", "source_family", "setup_family"):
        value = frontmatter.get(field)
        if value not in ("", None) and not is_non_empty_string(value):
            errors.append(f"{path}: field '{field}' must be a non-empty string when provided")


def validate_strategy_card_fields(
    path: Path,
    frontmatter: dict[str, object],
    errors: list[str],
) -> None:
    if not is_strategy_card(path):
        return

    for field in STRATEGY_CARD_REQUIRED_FIELDS:
        if field not in frontmatter or is_missing(frontmatter[field]):
            errors.append(f"{path}: strategy card missing required field '{field}'")

    evidence_quality = frontmatter.get("evidence_quality")
    if evidence_quality not in ("", None, *sorted(ALLOWED_CONFIDENCE)):
        errors.append(f"{path}: invalid 'evidence_quality' value '{evidence_quality}'")

    chart_dependency = frontmatter.get("chart_dependency")
    if chart_dependency not in ("", None, *sorted(ALLOWED_CHART_DEPENDENCY)):
        errors.append(f"{path}: invalid 'chart_dependency' value '{chart_dependency}'")

    test_priority = frontmatter.get("test_priority")
    if test_priority not in ("", None, *sorted(ALLOWED_TEST_PRIORITY)):
        errors.append(f"{path}: invalid 'test_priority' value '{test_priority}'")


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    frontmatter = parse_frontmatter(path.read_text(encoding="utf-8"))
    if frontmatter is None:
        return [f"{path}: missing YAML frontmatter"]

    for field in REQUIRED_FIELDS:
        if field not in frontmatter or is_missing(frontmatter[field]):
            errors.append(f"{path}: missing required field '{field}'")

    validate_enum(path, frontmatter, errors)
    validate_list_fields(path, frontmatter, errors)
    validate_scalar_fields(path, frontmatter, errors)
    validate_strategy_card_fields(path, frontmatter, errors)

    if frontmatter.get("type") == "setup":
        for field in SETUP_REQUIRED_FIELDS:
            if field not in frontmatter or is_missing(frontmatter[field]):
                errors.append(f"{path}: setup missing required field '{field}'")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate knowledge wiki frontmatter.")
    default_root = Path(__file__).resolve().parents[1] / "knowledge" / "wiki"
    parser.add_argument("root", nargs="?", default=str(default_root))
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"wiki root does not exist: {root}", file=sys.stderr)
        return 1

    files = list_markdown_files(root)
    if not files:
        print(f"No wiki markdown files found under {root}")
        return 0

    errors: list[str] = []
    for path in files:
        errors.extend(validate_file(path))

    if errors:
        print("KB validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"KB validation passed for {len(files)} markdown file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
