#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


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


def is_missing(value: object) -> bool:
    return value is None or value == ""


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    frontmatter = parse_frontmatter(path.read_text(encoding="utf-8"))
    if frontmatter is None:
        return [f"{path}: missing YAML frontmatter"]

    for field in REQUIRED_FIELDS:
        if field not in frontmatter or is_missing(frontmatter[field]):
            errors.append(f"{path}: missing required field '{field}'")

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

    files = sorted(root.rglob("*.md"))
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
