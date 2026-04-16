#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


INDEX_FIELDS = [
    "path",
    "title",
    "type",
    "status",
    "confidence",
    "market",
    "timeframes",
    "direction",
    "source_refs",
    "pa_context",
    "tags",
    "open_questions",
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


def ensure_list(value):
    if isinstance(value, list):
        return value
    if value in ("", None):
        return []
    return [value]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a lightweight knowledge wiki index.")
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument("root", nargs="?", default=str(repo_root / "knowledge" / "wiki"))
    parser.add_argument(
        "--output",
        default=str(repo_root / "knowledge" / "wiki_index.json"),
        help="Output JSON path.",
    )
    args = parser.parse_args()

    root = Path(args.root)
    output = Path(args.output)
    files = sorted(root.rglob("*.md")) if root.exists() else []

    index = []
    for path in files:
        frontmatter = parse_frontmatter(path.read_text(encoding="utf-8"))
        if frontmatter is None:
            continue
        relative_path = (
            path.relative_to(repo_root).as_posix()
            if path.is_relative_to(repo_root)
            else path.as_posix()
        )
        record = {
            "path": relative_path,
            "title": frontmatter.get("title", ""),
            "type": frontmatter.get("type", ""),
            "status": frontmatter.get("status", ""),
            "confidence": frontmatter.get("confidence", ""),
            "market": ensure_list(frontmatter.get("market")),
            "timeframes": ensure_list(frontmatter.get("timeframes")),
            "direction": frontmatter.get("direction", ""),
            "source_refs": ensure_list(frontmatter.get("source_refs")),
            "pa_context": ensure_list(frontmatter.get("pa_context")),
            "tags": ensure_list(frontmatter.get("tags")),
            "open_questions": ensure_list(frontmatter.get("open_questions")),
        }
        index.append({field: record[field] for field in INDEX_FIELDS})

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(index)} record(s) to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
