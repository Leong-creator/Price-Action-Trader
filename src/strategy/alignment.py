from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

from src.data.replay import ReplayStep
from src.data.schema import NewsEvent, OhlcvRow

from .context import build_context_snapshot
from .knowledge import (
    PROJECT_ROOT,
    KnowledgeReferenceError,
    StrategyKnowledgeBundle,
    load_alignment_knowledge,
    reference_exists,
    resolve_reference_path,
)
from .signals import identify_setup_candidate


@dataclass(frozen=True, slots=True)
class KBAlignmentAssessment:
    action: str
    context: str
    confidence: str
    setup_type: str | None
    source_refs: tuple[str, ...]
    explanation: str
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoldenCase:
    case_id: str
    market: str
    timeframe: str
    expected_context: dict[str, Any]
    allowed_setups: tuple[str, ...]
    forbidden_setups: tuple[str, ...]
    required_source_refs: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    must_explain: tuple[str, ...]
    must_not_claim: tuple[str, ...]
    knowledge_boundary: str = ""
    confidence_floor: str = ""
    expected_resolution: str = ""


def assess_kb_alignment(
    bars: Sequence[OhlcvRow],
    *,
    knowledge: StrategyKnowledgeBundle | None = None,
    news_events: Sequence[NewsEvent] = (),
) -> KBAlignmentAssessment:
    active_knowledge = knowledge or load_alignment_knowledge()
    active_knowledge.validate()
    _validate_refs(active_knowledge.source_refs)

    combined_not_applicable = _flatten(page.not_applicable for page in active_knowledge.all_pages)
    combined_contradictions = _flatten(page.contradictions for page in active_knowledge.all_pages)
    has_news_role_guard = any(page.path.name == "m6-news-review-evidence-pack.md" for page in active_knowledge.supporting_pages)
    explanation_parts = [f"knowledge refs: {', '.join(active_knowledge.source_refs)}"]
    issues: list[str] = []

    if not bars:
        issues.append("insufficient_evidence")
        explanation_parts.append("insufficient evidence: no bars available; conservative wait/no-trade is required")
        return KBAlignmentAssessment(
            action="wait",
            context="transition",
            confidence="low",
            setup_type=None,
            source_refs=active_knowledge.source_refs,
            explanation="; ".join(explanation_parts),
            issues=tuple(issues),
        )

    step = ReplayStep(index=len(bars) - 1, bar=bars[-1], news_events=tuple(news_events))
    context = build_context_snapshot(bars, active_knowledge)
    candidate = identify_setup_candidate(
        bars,
        step,
        context=context,
        knowledge=active_knowledge,
        previous_direction=None,
    )

    explanation_parts.insert(0, f"context={context.market_cycle}")

    if combined_contradictions:
        issues.extend(("knowledge_conflict", "lower_confidence"))
        explanation_parts.append(
            "knowledge contradictions require explicit conflict handling: "
            + " | ".join(combined_contradictions)
        )
        return KBAlignmentAssessment(
            action="conflict",
            context=context.market_cycle,
            confidence="low",
            setup_type=candidate.setup_type if candidate is not None else None,
            source_refs=active_knowledge.source_refs,
            explanation="; ".join(explanation_parts),
            issues=tuple(issues),
        )

    if news_events and has_news_role_guard:
        issues.extend(("knowledge_conflict", "news_role_guard"))
        explanation_parts.append(
            "news role conflict: supporting rule keeps news as filter/explanation/risk_hint only"
        )
        return KBAlignmentAssessment(
            action="conflict",
            context=context.market_cycle,
            confidence="low",
            setup_type=candidate.setup_type if candidate is not None else None,
            source_refs=active_knowledge.source_refs,
            explanation="; ".join(explanation_parts),
            issues=tuple(issues),
        )

    if candidate is None:
        issues.append("insufficient_evidence")
        explanation_parts.append("insufficient evidence for an aligned setup; conservative wait/no-trade is allowed")
        return KBAlignmentAssessment(
            action="wait",
            context=context.market_cycle,
            confidence="low",
            setup_type=None,
            source_refs=active_knowledge.source_refs,
            explanation="; ".join(explanation_parts),
            issues=tuple(issues),
        )

    explanation_parts.append(f"setup={candidate.setup_type}")
    explanation_parts.append(f"candidate explanation: {candidate.explanation}")

    if combined_not_applicable:
        issues.extend(("not_applicable", "no_trade"))
        explanation_parts.append(
            "not_applicable guard active: " + " | ".join(combined_not_applicable)
        )
        explanation_parts.append(
            "knowledge boundary requires no-trade/wait; no executable trade claim is allowed"
        )
        return KBAlignmentAssessment(
            action="no-trade",
            context=context.market_cycle,
            confidence="low",
            setup_type=candidate.setup_type,
            source_refs=active_knowledge.source_refs,
            explanation="; ".join(explanation_parts),
            issues=tuple(issues),
        )

    if any(page.is_placeholder for page in active_knowledge.all_pages):
        issues.extend(("placeholder_knowledge", "research_only"))
        explanation_parts.append(
            "placeholder knowledge remains unresolved; keep output research-only and low-confidence"
        )
        return KBAlignmentAssessment(
            action="research_only_placeholder_signal",
            context=context.market_cycle,
            confidence="low",
            setup_type=candidate.setup_type,
            source_refs=active_knowledge.source_refs,
            explanation="; ".join(explanation_parts),
            issues=tuple(issues),
        )

    return KBAlignmentAssessment(
        action="signal",
        context=context.market_cycle,
        confidence=candidate.confidence,
        setup_type=candidate.setup_type,
        source_refs=active_knowledge.source_refs,
        explanation="; ".join(explanation_parts),
        issues=tuple(issues),
    )


def _flatten(groups: Sequence[tuple[str, ...]] | Sequence[Sequence[str]]) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def load_golden_case(path: str | Path) -> GoldenCase:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return GoldenCase(
        case_id=str(raw["case_id"]),
        market=str(raw["market"]),
        timeframe=str(raw["timeframe"]),
        expected_context=dict(raw["expected_context"]),
        allowed_setups=_as_str_tuple(raw["allowed_setups"]),
        forbidden_setups=_as_str_tuple(raw["forbidden_setups"]),
        required_source_refs=_as_str_tuple(raw["required_source_refs"]),
        allowed_actions=_as_str_tuple(raw["allowed_actions"]),
        must_explain=_as_str_tuple(raw["must_explain"]),
        must_not_claim=_as_str_tuple(raw["must_not_claim"]),
        knowledge_boundary=str(raw.get("knowledge_boundary", "")),
        confidence_floor=str(raw.get("confidence_floor", "")),
        expected_resolution=str(raw.get("expected_resolution", "")),
    )


def discover_golden_cases(root: str | Path | None = None) -> tuple[GoldenCase, ...]:
    base_path = Path(root) if root is not None else PROJECT_ROOT / "tests" / "golden_cases" / "cases"
    if not base_path.exists():
        return ()
    return tuple(load_golden_case(path) for path in sorted(base_path.glob("*.json")))


def _as_str_tuple(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise KnowledgeReferenceError("golden case list fields must be arrays")
    return tuple(str(value) for value in values)


def _validate_refs(source_refs: Sequence[str]) -> None:
    if not source_refs:
        raise KnowledgeReferenceError("source_refs must not be empty")
    for reference in source_refs:
        if not reference.strip():
            raise KnowledgeReferenceError("source_refs must not contain blank values")
        if reference.startswith("wiki:"):
            path = resolve_reference_path(reference)
            if path is None or not path.is_file() or not reference_exists(reference):
                raise KnowledgeReferenceError(f"knowledge reference does not exist: {reference}")
