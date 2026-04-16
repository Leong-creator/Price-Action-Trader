from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONCEPT_PATH = PROJECT_ROOT / "knowledge" / "wiki" / "concepts" / "market-cycle-overview.md"
DEFAULT_SETUP_PATH = PROJECT_ROOT / "knowledge" / "wiki" / "setups" / "signal-bar-entry-placeholder.md"
DEFAULT_RULE_PACK_REF = "wiki:knowledge/wiki/rules/m3-research-reference-pack.md"


class KnowledgeReferenceError(ValueError):
    """Raised when strategy knowledge cannot satisfy traceability requirements."""


@dataclass(frozen=True, slots=True)
class KnowledgePage:
    path: Path
    title: str
    page_type: str
    status: str
    confidence: str
    source_refs: tuple[str, ...]
    pa_context: tuple[str, ...]
    higher_timeframe_context: tuple[str, ...]
    bar_by_bar_notes: tuple[str, ...]
    entry_trigger: tuple[str, ...]
    stop_rule: tuple[str, ...]
    target_rule: tuple[str, ...]
    invalidation: tuple[str, ...]
    raw_frontmatter: dict[str, Any]

    @property
    def is_placeholder(self) -> bool:
        text_values: list[str] = [self.title, self.status, self.confidence]
        for field in (
            self.pa_context,
            self.higher_timeframe_context,
            self.bar_by_bar_notes,
            self.entry_trigger,
            self.stop_rule,
            self.target_rule,
            self.invalidation,
        ):
            text_values.extend(field)
        lowered = " ".join(text_values).lower()
        return "placeholder" in lowered or "待确认" in lowered or self.status == "draft"

    @property
    def page_ref(self) -> str:
        relative = self.path.resolve().relative_to(PROJECT_ROOT)
        return f"wiki:{relative.as_posix()}"


@dataclass(frozen=True, slots=True)
class StrategyKnowledgeBundle:
    concept_page: KnowledgePage
    setup_page: KnowledgePage

    @property
    def source_refs(self) -> tuple[str, ...]:
        return _dedupe(
            (
                self.concept_page.page_ref,
                self.setup_page.page_ref,
                DEFAULT_RULE_PACK_REF,
            )
            + self.concept_page.source_refs
            + self.setup_page.source_refs
        )

    def validate(self) -> None:
        if not self.concept_page.source_refs:
            raise KnowledgeReferenceError(
                f"concept page {self.concept_page.path} is missing source_refs"
            )
        if not self.setup_page.source_refs:
            raise KnowledgeReferenceError(
                f"setup page {self.setup_page.path} is missing source_refs"
            )


def load_default_knowledge() -> StrategyKnowledgeBundle:
    return load_strategy_knowledge(DEFAULT_CONCEPT_PATH, DEFAULT_SETUP_PATH)


def load_strategy_knowledge(concept_path: Path, setup_path: Path) -> StrategyKnowledgeBundle:
    bundle = StrategyKnowledgeBundle(
        concept_page=_load_page(concept_path),
        setup_page=_load_page(setup_path),
    )
    bundle.validate()
    return bundle


def _load_page(path: Path) -> KnowledgePage:
    frontmatter = _parse_frontmatter(path.read_text(encoding="utf-8"))
    return KnowledgePage(
        path=path,
        title=str(frontmatter.get("title", "")).strip(),
        page_type=str(frontmatter.get("type", "")).strip(),
        status=str(frontmatter.get("status", "")).strip(),
        confidence=str(frontmatter.get("confidence", "")).strip(),
        source_refs=_as_tuple(frontmatter.get("source_refs")),
        pa_context=_as_tuple(frontmatter.get("pa_context")),
        higher_timeframe_context=_as_tuple(frontmatter.get("higher_timeframe_context")),
        bar_by_bar_notes=_as_tuple(frontmatter.get("bar_by_bar_notes")),
        entry_trigger=_as_tuple(frontmatter.get("entry_trigger")),
        stop_rule=_as_tuple(frontmatter.get("stop_rule")),
        target_rule=_as_tuple(frontmatter.get("target_rule")),
        invalidation=_as_tuple(frontmatter.get("invalidation")),
        raw_frontmatter=frontmatter,
    )


def _parse_frontmatter(content: str) -> dict[str, Any]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise KnowledgeReferenceError("knowledge page is missing frontmatter header")

    frontmatter_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        frontmatter_lines.append(line)
    else:
        raise KnowledgeReferenceError("knowledge page is missing frontmatter terminator")

    parsed: dict[str, Any] = {}
    for line in frontmatter_lines:
        if not line.strip():
            continue
        key, sep, raw_value = line.partition(":")
        if not sep:
            raise KnowledgeReferenceError(f"invalid frontmatter line: {line!r}")
        parsed[key.strip()] = _parse_scalar(raw_value.strip())
    return parsed


def _parse_scalar(raw_value: str) -> Any:
    if raw_value == "":
        return None
    lowered = raw_value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if raw_value.startswith("[") or raw_value.startswith("{") or raw_value.startswith(("'", '"')):
        return ast.literal_eval(raw_value)
    return raw_value


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    text = str(value).strip()
    return (text,) if text else ()


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)
