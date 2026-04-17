from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from .contracts import KnowledgeAtomHit
from .knowledge import PROJECT_ROOT, StrategyKnowledgeBundle


DEFAULT_SOURCE_MANIFEST_PATH = PROJECT_ROOT / "knowledge" / "indices" / "source_manifest.json"
DEFAULT_ATOM_PATH = PROJECT_ROOT / "knowledge" / "indices" / "knowledge_atoms.jsonl"
DEFAULT_CALLABLE_INDEX_PATH = PROJECT_ROOT / "knowledge" / "indices" / "knowledge_callable_index.json"

TRACE_TYPE_PRIORITY = {
    "concept": 0,
    "setup": 1,
    "rule": 2,
    "statement": 3,
    "contradiction": 4,
    "open_question": 5,
    "source_note": 6,
}

TRACE_TOTAL_CAP = 6
TRACE_STATEMENT_TOTAL_CAP = 2
TRACE_SUPPORTING_TOTAL_CAP = 1
TRACE_PER_FAMILY_CAP = 1
TRACE_MARKDOWN_SUMMARY_CAP = 3
TRACE_EXPLANATION_SUMMARY_CAP = 2
TRACE_VISIBLE_RULE_CHUNK_SET_MAX = 64


@dataclass(frozen=True, slots=True)
class KnowledgeAtom:
    atom_id: str
    atom_type: str
    content: str
    status: str
    confidence: str
    market: tuple[str, ...]
    timeframes: tuple[str, ...]
    pa_context: tuple[str, ...]
    applicability: tuple[str, ...]
    not_applicable: tuple[str, ...]
    contradictions: tuple[str, ...]
    source_ref: str
    raw_locator: dict[str, Any]
    evidence_chunk_ids: tuple[str, ...]
    callable_tags: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    evidence_locator_summary: tuple[str, ...] = ()
    field_mappings: tuple[str, ...] = ()
    claim_id: str | None = None
    promotion_theme: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    atom_type: str | None = None
    source_ids: tuple[str, ...] = ()
    source_families: tuple[str, ...] = ()
    market: str | None = None
    timeframe: str | None = None
    pa_context: str | None = None
    status: str | None = None
    confidence: str | None = None
    callable_tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KnowledgeTransitionalView:
    curated_atoms: tuple[KnowledgeAtom, ...]
    statement_atoms: tuple[KnowledgeAtom, ...]
    supporting_atoms: tuple[KnowledgeAtom, ...]
    legacy_source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeTraceResolution:
    visible_trace: tuple[KnowledgeAtomHit, ...]
    debug_trace: tuple[KnowledgeAtomHit, ...]
    actual_source_refs: tuple[str, ...]
    bundle_support_refs: tuple[str, ...]


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, tuple):
        return tuple(str(item) for item in value if str(item).strip())
    text = str(value).strip()
    return (text,) if text else ()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return tuple(records)


def _normalize_locator(locator: dict[str, Any]) -> dict[str, Any]:
    return dict(locator)


def _normalize_atom(record: dict[str, Any]) -> KnowledgeAtom:
    return KnowledgeAtom(
        atom_id=str(record["atom_id"]),
        atom_type=str(record["atom_type"]),
        content=str(record["content"]),
        status=str(record["status"]),
        confidence=str(record["confidence"]),
        market=_as_tuple(record.get("market")),
        timeframes=_as_tuple(record.get("timeframes")),
        pa_context=_as_tuple(record.get("pa_context")),
        applicability=_as_tuple(record.get("applicability")),
        not_applicable=_as_tuple(record.get("not_applicable")),
        contradictions=_as_tuple(record.get("contradictions")),
        source_ref=str(record["source_ref"]),
        raw_locator=_normalize_locator(record.get("raw_locator", {})),
        evidence_chunk_ids=_as_tuple(record.get("evidence_chunk_ids")),
        callable_tags=_as_tuple(record.get("callable_tags")),
        evidence_refs=_as_tuple(record.get("evidence_refs")),
        evidence_locator_summary=_as_tuple(record.get("evidence_locator_summary")),
        field_mappings=_as_tuple(record.get("field_mappings")),
        claim_id=str(record["claim_id"]) if record.get("claim_id") else None,
        promotion_theme=str(record["promotion_theme"]) if record.get("promotion_theme") else None,
    )


def _source_family_from_tags(tags: tuple[str, ...]) -> str | None:
    for tag in tags:
        if tag.startswith("source_family:"):
            return tag.split(":", 1)[1]
    return None


def _matches_dimension(values: tuple[str, ...], target: str | None) -> bool:
    if target is None:
        return True
    if not values:
        return True
    normalized = {value.lower() for value in values}
    target_lower = target.lower()
    return target_lower in normalized or "general" in normalized or "all" in normalized or "both" in normalized


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def _normalized_content(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]+", " ", text.lower()).split())


def _brief_raw_locator(raw_locator: dict[str, Any]) -> str:
    locator_kind = raw_locator.get("locator_kind", "unknown")
    if locator_kind == "page_block":
        page_no = raw_locator.get("page_no", "?")
        block_index = raw_locator.get("block_index", "?")
        fragment_index = raw_locator.get("fragment_index")
        suffix = f"#f{fragment_index}" if fragment_index is not None else ""
        return f"p{page_no}b{block_index}{suffix}"
    if locator_kind == "chunk_set":
        member_count = raw_locator.get("member_count", "?")
        return f"chunk_set[{member_count}]"
    if locator_kind == "bundle_support_summary":
        return str(raw_locator.get("label", "bundle_support"))
    return locator_kind


def summarize_knowledge_trace(
    trace: tuple[KnowledgeAtomHit, ...],
    *,
    max_items: int = TRACE_MARKDOWN_SUMMARY_CAP,
) -> tuple[dict[str, str], ...]:
    summaries: list[dict[str, str]] = []
    for hit in trace[:max_items]:
        summaries.append(
            {
                "atom_type": hit.atom_type,
                "atom_id": hit.atom_id,
                "source_ref": hit.source_ref,
                "raw_locator": _brief_raw_locator(hit.raw_locator),
                "evidence_refs": " | ".join(hit.evidence_refs),
                "evidence_locator_summary": " | ".join(hit.evidence_locator_summary),
                "field_mappings": " | ".join(hit.field_mappings),
            }
        )
    return tuple(summaries)


def render_trace_summary(
    trace: tuple[KnowledgeAtomHit, ...],
    *,
    max_items: int = TRACE_EXPLANATION_SUMMARY_CAP,
) -> str:
    summaries = summarize_knowledge_trace(trace, max_items=max_items)
    if not summaries:
        return "knowledge trace unavailable"
    return " | ".join(
        f"{item['atom_type']} {item['atom_id']} @ {item['raw_locator']}"
        for item in summaries
    )


def aggregate_legacy_source_refs(
    existing_refs: tuple[str, ...],
    trace: tuple[KnowledgeAtomHit, ...],
) -> tuple[str, ...]:
    combined = list(existing_refs)
    combined.extend(hit.source_ref for hit in trace)
    for hit in trace:
        combined.extend(hit.conflict_refs)
    return _dedupe(combined)


class CallableKnowledgeAccess:
    def __init__(
        self,
        *,
        atoms: tuple[KnowledgeAtom, ...],
        callable_index: dict[str, Any],
        source_manifest: dict[str, Any],
    ) -> None:
        self._atoms = atoms
        self._atoms_by_id = {atom.atom_id: atom for atom in atoms}
        self._callable_index = callable_index["indices"]
        self._source_manifest = source_manifest
        self._records_by_source_id = {
            record["source_id"]: record for record in source_manifest["sources"]
        }
        self._records_by_source_page = {
            record["source_page_ref"]: record for record in source_manifest["sources"]
        }
        self._records_by_raw_ref = {
            f"raw:{record['raw_path']}": record for record in source_manifest["sources"]
        }
        self._atom_to_source_ids = self._build_atom_to_source_ids()
        self._source_ref_order = self._build_source_ref_order()

    @classmethod
    def from_files(
        cls,
        *,
        atom_path: Path = DEFAULT_ATOM_PATH,
        callable_index_path: Path = DEFAULT_CALLABLE_INDEX_PATH,
        source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST_PATH,
    ) -> CallableKnowledgeAccess:
        atoms = tuple(_normalize_atom(record) for record in _load_jsonl(atom_path))
        callable_index = _load_json(callable_index_path)
        source_manifest = _load_json(source_manifest_path)
        return cls(atoms=atoms, callable_index=callable_index, source_manifest=source_manifest)

    def filtered(
        self,
        *,
        exclude_atom_types: tuple[str, ...] = (),
    ) -> CallableKnowledgeAccess:
        excluded = set(exclude_atom_types)
        if not excluded:
            return self
        filtered_atoms = tuple(atom for atom in self._atoms if atom.atom_type not in excluded)
        filtered_index = {
            "indices": {
                bucket_name: {
                    key: [atom_id for atom_id in atom_ids if atom_id in {atom.atom_id for atom in filtered_atoms}]
                    for key, atom_ids in bucket.items()
                }
                for bucket_name, bucket in self._callable_index.items()
            }
        }
        return CallableKnowledgeAccess(
            atoms=filtered_atoms,
            callable_index=filtered_index,
            source_manifest=self._source_manifest,
        )

    def query_atoms(self, query: KnowledgeQuery) -> tuple[KnowledgeAtom, ...]:
        candidate_ids = set(self._atoms_by_id)
        for key, value in (
            ("by_atom_type", query.atom_type),
            ("by_status", query.status),
            ("by_confidence", query.confidence),
        ):
            if value is None:
                continue
            candidate_ids &= set(self._callable_index.get(key, {}).get(value, ()))

        if query.source_ids:
            source_matches: set[str] = set()
            for source_id in query.source_ids:
                source_matches |= set(self._callable_index.get("by_source_id", {}).get(source_id, ()))
            candidate_ids &= source_matches

        if query.source_families:
            family_matches: set[str] = set()
            for source_family in query.source_families:
                family_matches |= set(self._callable_index.get("by_source_family", {}).get(source_family, ()))
            candidate_ids &= family_matches

        for tag in query.callable_tags:
            candidate_ids &= set(self._callable_index.get("by_callable_tag", {}).get(tag, ()))

        atoms = tuple(self._atoms_by_id[atom_id] for atom_id in sorted(candidate_ids))
        return tuple(atom for atom in atoms if self._matches_query(atom, query))

    def build_transitional_view(
        self,
        *,
        knowledge: StrategyKnowledgeBundle,
        market: str,
        timeframe: str,
        pa_context: str,
    ) -> KnowledgeTransitionalView:
        curated_atoms = self._resolve_curated_atoms(knowledge)
        source_refs = knowledge.source_refs
        source_ids_in_order = self._ordered_source_ids(source_refs)
        family_order = self._ordered_source_families(source_ids_in_order)
        statement_atoms = self._select_statement_atoms(
            source_ids_in_order=source_ids_in_order,
            family_order=family_order,
            market=market,
            timeframe=timeframe,
            pa_context=pa_context,
        )
        supporting_atoms = self._select_supporting_atoms(
            source_ids_in_order=source_ids_in_order,
            family_order=family_order,
            market=market,
            timeframe=timeframe,
            pa_context=pa_context,
        )
        return KnowledgeTransitionalView(
            curated_atoms=curated_atoms,
            statement_atoms=statement_atoms,
            supporting_atoms=supporting_atoms,
            legacy_source_refs=source_refs,
        )

    def resolve_trace(
        self,
        *,
        knowledge: StrategyKnowledgeBundle,
        market: str,
        timeframe: str,
        pa_context: str,
    ) -> tuple[KnowledgeAtomHit, ...]:
        return self.resolve_trace_bundle(
            knowledge=knowledge,
            market=market,
            timeframe=timeframe,
            pa_context=pa_context,
        ).visible_trace

    def resolve_trace_bundle(
        self,
        *,
        knowledge: StrategyKnowledgeBundle,
        market: str,
        timeframe: str,
        pa_context: str,
    ) -> KnowledgeTraceResolution:
        view = self.build_transitional_view(
            knowledge=knowledge,
            market=market,
            timeframe=timeframe,
            pa_context=pa_context,
        )
        visible_hits: list[KnowledgeAtomHit] = []
        debug_hits: list[KnowledgeAtomHit] = []
        for atom in view.curated_atoms:
            if self._is_broad_bundle_rule(atom):
                debug_hits.append(
                    self._atom_to_hit(
                        atom,
                        match_reason="bundle_rule_support",
                        applicability_state="supporting",
                        reference_tier="bundle_support",
                        raw_locator=self._bundle_support_locator(atom),
                        governance_notes=self._governance_notes(atom),
                    )
                )
                continue
            visible_hits.append(
                self._atom_to_hit(
                    atom,
                    match_reason=f"curated_{atom.atom_type}",
                    applicability_state=self._signal_applicability_state(atom),
                    governance_notes=self._governance_notes(atom),
                )
            )
        for atom in view.statement_atoms:
            visible_hits.append(
                self._atom_to_hit(
                    atom,
                    match_reason="statement_support",
                    applicability_state="supporting",
                )
            )
        for atom in view.supporting_atoms:
            debug_hits.append(
                self._atom_to_hit(
                    atom,
                    match_reason=f"{atom.atom_type}_support",
                    applicability_state=self._support_applicability_state(atom),
                    reference_tier="bundle_support",
                    governance_notes=self._governance_notes(atom),
                )
            )
        visible_trace = self._apply_trace_caps(
            tuple(sorted(self._dedupe_hits(tuple(visible_hits)), key=self._trace_sort_key))
        )
        debug_trace = tuple(sorted(self._dedupe_hits(tuple(debug_hits)), key=self._trace_sort_key))
        actual_source_refs = self._source_refs_from_hits(visible_trace)
        bundle_support_refs = self._bundle_support_refs(
            view=view,
            actual_source_refs=actual_source_refs,
            debug_trace=debug_trace,
        )
        return KnowledgeTraceResolution(
            visible_trace=visible_trace,
            debug_trace=debug_trace,
            actual_source_refs=actual_source_refs,
            bundle_support_refs=bundle_support_refs,
        )

    def _build_atom_to_source_ids(self) -> dict[str, tuple[str, ...]]:
        atom_to_source_ids: dict[str, set[str]] = {atom.atom_id: set() for atom in self._atoms}
        for source_id, atom_ids in self._callable_index.get("by_source_id", {}).items():
            for atom_id in atom_ids:
                atom_to_source_ids.setdefault(atom_id, set()).add(source_id)
        return {atom_id: tuple(sorted(source_ids)) for atom_id, source_ids in atom_to_source_ids.items()}

    def _build_source_ref_order(self) -> dict[str, int]:
        order: dict[str, int] = {}
        for index, record in enumerate(self._source_manifest["sources"]):
            order[record["source_page_ref"]] = index
            order[f"raw:{record['raw_path']}"] = index
        return order

    def _source_families_for_atom(self, atom_id: str) -> tuple[str, ...]:
        families = [
            self._records_by_source_id[source_id]["source_family"]
            for source_id in self._atom_to_source_ids.get(atom_id, ())
            if source_id in self._records_by_source_id
        ]
        return _dedupe(families)

    def _matches_query(self, atom: KnowledgeAtom, query: KnowledgeQuery) -> bool:
        return (
            _matches_dimension(atom.market, query.market)
            and _matches_dimension(atom.timeframes, query.timeframe)
            and _matches_dimension(atom.pa_context, query.pa_context)
        )

    def _resolve_curated_atoms(self, knowledge: StrategyKnowledgeBundle) -> tuple[KnowledgeAtom, ...]:
        ordered_refs = (
            knowledge.concept_page.page_ref,
            knowledge.setup_page.page_ref,
            *(page.page_ref for page in knowledge.supporting_pages),
        )
        hits: list[KnowledgeAtom] = []
        for ref in ordered_refs:
            candidates = [
                atom
                for atom in self._atoms
                if atom.source_ref == ref and atom.atom_type in {"concept", "setup", "rule"}
            ]
            if candidates:
                hits.append(
                    sorted(
                        candidates,
                        key=lambda atom: (
                            0 if "promoted_curated" in atom.callable_tags else 1,
                            0 if atom.evidence_refs else 1,
                            atom.atom_id,
                        ),
                    )[0]
                )
        return tuple(hits)

    def _ordered_source_ids(self, source_refs: tuple[str, ...]) -> tuple[str, ...]:
        source_ids: list[str] = []
        seen: set[str] = set()
        for ref in source_refs:
            record = self._records_by_source_page.get(ref) or self._records_by_raw_ref.get(ref)
            if record is None:
                continue
            source_id = record["source_id"]
            if source_id in seen:
                continue
            seen.add(source_id)
            source_ids.append(source_id)
        return tuple(source_ids)

    def _ordered_source_families(self, source_ids_in_order: tuple[str, ...]) -> tuple[str, ...]:
        families: list[str] = []
        seen: set[str] = set()
        for source_id in source_ids_in_order:
            family = self._records_by_source_id[source_id]["source_family"]
            if family in seen:
                continue
            seen.add(family)
            families.append(family)
        return tuple(families)

    def _select_statement_atoms(
        self,
        *,
        source_ids_in_order: tuple[str, ...],
        family_order: tuple[str, ...],
        market: str,
        timeframe: str,
        pa_context: str,
    ) -> tuple[KnowledgeAtom, ...]:
        family_best: list[KnowledgeAtom] = []
        for family in family_order:
            family_atoms = self.query_atoms(
                KnowledgeQuery(
                    atom_type="statement",
                    source_ids=tuple(
                        source_id
                        for source_id in source_ids_in_order
                        if self._records_by_source_id[source_id]["source_family"] == family
                    ),
                    market=market,
                    timeframe=timeframe,
                    pa_context=pa_context,
                    callable_tags=("statement_candidate",),
                )
            )
            if not family_atoms:
                continue
            family_best.append(
                sorted(
                    family_atoms,
                    key=lambda atom: self._statement_sort_key(atom, market=market, timeframe=timeframe, pa_context=pa_context),
                )[0]
            )
            if len(family_best) >= TRACE_STATEMENT_TOTAL_CAP:
                break
        return tuple(family_best)

    def _select_supporting_atoms(
        self,
        *,
        source_ids_in_order: tuple[str, ...],
        family_order: tuple[str, ...],
        market: str,
        timeframe: str,
        pa_context: str,
    ) -> tuple[KnowledgeAtom, ...]:
        selected: list[KnowledgeAtom] = []
        used_families: set[str] = set()
        for family in family_order:
            source_ids = tuple(
                source_id
                for source_id in source_ids_in_order
                if self._records_by_source_id[source_id]["source_family"] == family
            )
            candidates = self.query_atoms(
                KnowledgeQuery(
                    source_ids=source_ids,
                    market=market,
                    timeframe=timeframe,
                    pa_context=pa_context,
                )
            )
            filtered = [
                atom
                for atom in candidates
                if atom.atom_type in {"source_note", "contradiction", "open_question"}
            ]
            if not filtered or family in used_families:
                continue
            selected.append(sorted(filtered, key=self._supporting_sort_key)[0])
            used_families.add(family)
            if len(selected) >= TRACE_SUPPORTING_TOTAL_CAP:
                break
        return tuple(selected)

    def _statement_sort_key(
        self,
        atom: KnowledgeAtom,
        *,
        market: str,
        timeframe: str,
        pa_context: str,
    ) -> tuple[Any, ...]:
        family = _source_family_from_tags(atom.callable_tags) or ""
        normalized_pa_context = {value.lower() for value in atom.pa_context}
        normalized_timeframes = {value.lower() for value in atom.timeframes}
        normalized_markets = {value.lower() for value in atom.market}
        preferred_length = abs(len(atom.content) - 96)
        return (
            0 if pa_context.lower() in normalized_pa_context else 1,
            0 if timeframe.lower() in normalized_timeframes else 1,
            0 if market.lower() in normalized_markets else 1,
            self._source_ref_order.get(atom.source_ref, 9999),
            preferred_length,
            family,
            atom.atom_id,
        )

    def _supporting_sort_key(self, atom: KnowledgeAtom) -> tuple[Any, ...]:
        atom_priority = TRACE_TYPE_PRIORITY.get(atom.atom_type, 99)
        return (
            atom_priority,
            self._source_ref_order.get(atom.source_ref, 9999),
            abs(len(atom.content) - 88),
            atom.atom_id,
        )

    def _signal_applicability_state(self, atom: KnowledgeAtom) -> str:
        if atom.atom_type == "contradiction":
            return "conflict"
        if atom.atom_type == "open_question":
            return "open_question"
        if atom.contradictions:
            return "conflict"
        if atom.atom_type in {"concept", "setup", "rule"}:
            return "matched"
        return "supporting"

    def _support_applicability_state(self, atom: KnowledgeAtom) -> str:
        if atom.atom_type == "contradiction":
            return "conflict"
        if atom.atom_type == "open_question":
            return "open_question"
        return "supporting"

    def _governance_notes(self, atom: KnowledgeAtom) -> tuple[str, ...]:
        return _dedupe(atom.not_applicable)

    def _is_broad_bundle_rule(self, atom: KnowledgeAtom) -> bool:
        if atom.atom_type != "rule":
            return False
        raw_locator = atom.raw_locator
        return (
            raw_locator.get("locator_kind") == "chunk_set"
            and int(raw_locator.get("member_count", 0) or 0) > TRACE_VISIBLE_RULE_CHUNK_SET_MAX
        )

    def _bundle_support_locator(self, atom: KnowledgeAtom) -> dict[str, Any]:
        raw_locator = dict(atom.raw_locator)
        if raw_locator.get("locator_kind") != "chunk_set":
            return raw_locator
        member_locators = raw_locator.get("member_locators", ())
        source_ids = tuple(
            sorted(
                {
                    str(item.get("source_id"))
                    for item in member_locators
                    if isinstance(item, dict) and item.get("source_id")
                }
            )
        )
        member_count = int(raw_locator.get("member_count", 0) or 0)
        return {
            "locator_kind": "bundle_support_summary",
            "member_count": member_count,
            "source_ids": source_ids,
            "label": f"bundle_support[{len(source_ids)} sources/{member_count} chunks]",
        }

    def _atom_to_hit(
        self,
        atom: KnowledgeAtom,
        *,
        match_reason: str,
        applicability_state: str,
        reference_tier: str = "actual_hit",
        raw_locator: dict[str, Any] | None = None,
        governance_notes: tuple[str, ...] = (),
    ) -> KnowledgeAtomHit:
        return KnowledgeAtomHit(
            atom_id=atom.atom_id,
            atom_type=atom.atom_type,
            source_ref=atom.source_ref,
            raw_locator=dict(raw_locator or atom.raw_locator),
            match_reason=match_reason,
            applicability_state=applicability_state,
            conflict_refs=_dedupe(atom.contradictions),
            reference_tier=reference_tier,
            governance_notes=governance_notes,
            evidence_refs=atom.evidence_refs,
            evidence_locator_summary=atom.evidence_locator_summary,
            field_mappings=atom.field_mappings,
            claim_id=atom.claim_id,
            promotion_theme=atom.promotion_theme,
        )

    def _source_refs_from_hits(self, hits: tuple[KnowledgeAtomHit, ...]) -> tuple[str, ...]:
        refs: list[str] = []
        for hit in hits:
            refs.append(hit.source_ref)
            refs.extend(hit.conflict_refs)
        return _dedupe(refs)

    def _bundle_support_refs(
        self,
        *,
        view: KnowledgeTransitionalView,
        actual_source_refs: tuple[str, ...],
        debug_trace: tuple[KnowledgeAtomHit, ...],
    ) -> tuple[str, ...]:
        refs = [ref for ref in view.legacy_source_refs if ref not in actual_source_refs]
        for hit in debug_trace:
            if hit.source_ref not in actual_source_refs:
                refs.append(hit.source_ref)
            refs.extend(ref for ref in hit.conflict_refs if ref not in actual_source_refs)
        return _dedupe(refs)

    def _dedupe_hits(self, hits: tuple[KnowledgeAtomHit, ...]) -> tuple[KnowledgeAtomHit, ...]:
        seen: set[str] = set()
        deduped: list[KnowledgeAtomHit] = []
        for hit in hits:
            if hit.atom_id in seen:
                continue
            seen.add(hit.atom_id)
            deduped.append(hit)
        return tuple(deduped)

    def _apply_trace_caps(self, hits: tuple[KnowledgeAtomHit, ...]) -> tuple[KnowledgeAtomHit, ...]:
        capped: list[KnowledgeAtomHit] = []
        family_counts: dict[str, int] = {}
        statement_count = 0
        supporting_count = 0

        for hit in hits:
            families = self._source_families_for_atom(hit.atom_id) or ("",)
            dominant_family = families[0]
            atom_type = hit.atom_type

            if atom_type in {"statement", "source_note", "contradiction", "open_question"}:
                if family_counts.get(dominant_family, 0) >= TRACE_PER_FAMILY_CAP:
                    continue

            if atom_type == "statement":
                if statement_count >= TRACE_STATEMENT_TOTAL_CAP:
                    continue
                statement_count += 1
                family_counts[dominant_family] = family_counts.get(dominant_family, 0) + 1
            elif atom_type in {"source_note", "contradiction", "open_question"}:
                if supporting_count >= TRACE_SUPPORTING_TOTAL_CAP:
                    continue
                supporting_count += 1
                family_counts[dominant_family] = family_counts.get(dominant_family, 0) + 1

            capped.append(hit)
            if len(capped) >= TRACE_TOTAL_CAP:
                break

        return tuple(capped)

    def _trace_sort_key(self, hit: KnowledgeAtomHit) -> tuple[Any, ...]:
        families = self._source_families_for_atom(hit.atom_id)
        family = families[0] if families else ""
        return (
            TRACE_TYPE_PRIORITY.get(hit.atom_type, 99),
            self._source_ref_order.get(hit.source_ref, 9999),
            family,
            hit.atom_id,
        )


@lru_cache(maxsize=1)
def load_default_knowledge_access() -> CallableKnowledgeAccess:
    return CallableKnowledgeAccess.from_files()
