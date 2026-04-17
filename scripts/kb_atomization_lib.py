from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from pypdf import PdfReader
    from pypdf import __version__ as PYPDF_VERSION
except Exception:  # pragma: no cover - exercised by validator behavior
    PdfReader = None
    PYPDF_VERSION = "missing"


logging.getLogger("pypdf").setLevel(logging.ERROR)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
WIKI_ROOT = KNOWLEDGE_ROOT / "wiki"
INDICES_ROOT = KNOWLEDGE_ROOT / "indices"

SOURCE_MANIFEST_SCHEMA = "m8b2.source-registry.v1"
CHUNK_REGISTRY_SCHEMA = "m8b2.chunk-registry.v1"
KNOWLEDGE_ATOM_SCHEMA = "m8b2.knowledge-atoms.v1"
CALLABLE_INDEX_SCHEMA = "m8b2.callable-index.v1"

ALLOWED_SOURCE_TYPES = {"note_pdf", "transcript_pdf", "ppt_pdf"}
ALLOWED_PARSE_STATUS = {"parsed", "partial", "blocked"}
ALLOWED_ATOM_TYPES = {
    "concept",
    "setup",
    "rule",
    "statement",
    "contradiction",
    "open_question",
    "source_note",
}

KEY_CURATED_PAGE_REFS = (
    "wiki:knowledge/wiki/concepts/market-cycle-overview.md",
    "wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md",
    "wiki:knowledge/wiki/rules/m3-research-reference-pack.md",
)

DEFAULT_SOURCE_OUTPUT = INDICES_ROOT / "source_manifest.json"
DEFAULT_CHUNK_OUTPUT = INDICES_ROOT / "chunk_manifest.jsonl"
DEFAULT_ATOM_OUTPUT = INDICES_ROOT / "knowledge_atoms.jsonl"
DEFAULT_CALLABLE_OUTPUT = INDICES_ROOT / "knowledge_callable_index.json"

_NOISE_PREFIXES = (
    "专题系列",
    "译者序",
    "price_action",
    "price action",
    "模块一",
)
_HEADER_CONNECTORS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_REJECT_EXACT_FRAGMENTS = {
    "brooks trading course",
    "price action方方土",
    "price_action方方土",
    "专题系列",
    "译者序",
}
_REJECT_STATEMENT_PATTERNS = (
    re.compile(r"\.\s*com\b", re.IGNORECASE),
    re.compile(r"\bslide\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bslide\b", re.IGNORECASE),
    re.compile(r"qihua\s*\d+", re.IGNORECASE),
)
_QUESTION_HEADING_PREFIXES = ("what ", "why ", "when ", "where ", "who ", "how ")
_SECTION_HEADING_PATTERNS = (
    re.compile(r"^(?:模块|阶段)[一二三四五六七八九十0-9]+[:：]"),
    re.compile(r"^《.+》[:：]"),
    re.compile(r"^[A-Z][A-Za-z0-9\s()/'&.+-]{2,}[:：]$"),
)


@dataclass(frozen=True, slots=True)
class SourceSpec:
    raw_path: str
    source_family: str
    source_type: str
    slug: str
    source_page_ref: str

    @property
    def raw_ref(self) -> str:
        return f"raw:{self.raw_path}"

    @property
    def source_id(self) -> str:
        digest = short_sha1(self.raw_path, length=8)
        return f"{self.source_family}--{self.slug}--{digest}"

    @property
    def file_name(self) -> str:
        return Path(self.raw_path).name


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        raw_path="knowledge/raw/notes/方方土视频笔记 - 市场周期.pdf",
        source_family="fangfangtu_notes",
        source_type="note_pdf",
        slug="market-cycle-note",
        source_page_ref="wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md",
    ),
    SourceSpec(
        raw_path="knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf",
        source_family="fangfangtu_notes",
        source_type="note_pdf",
        slug="signal-bar-entry-note",
        source_page_ref="wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md",
    ),
    SourceSpec(
        raw_path="knowledge/raw/notes/方方土视频笔记 - 回调&数K线.pdf",
        source_family="fangfangtu_notes",
        source_type="note_pdf",
        slug="pullback-counting-bars-note",
        source_page_ref="wiki:knowledge/wiki/sources/fangfangtu-pullback-counting-bars-note.md",
    ),
    SourceSpec(
        raw_path="knowledge/raw/notes/方方土视频笔记 - 新手篇.pdf",
        source_family="fangfangtu_notes",
        source_type="note_pdf",
        slug="beginner-note",
        source_page_ref="wiki:knowledge/wiki/sources/fangfangtu-beginner-note.md",
    ),
    SourceSpec(
        raw_path="knowledge/raw/notes/方方土视频笔记 - 楔形.pdf",
        source_family="fangfangtu_notes",
        source_type="note_pdf",
        slug="wedge-note",
        source_page_ref="wiki:knowledge/wiki/sources/fangfangtu-wedge-note.md",
    ),
    SourceSpec(
        raw_path="knowledge/raw/notes/方方土视频笔记 - 缺口.pdf",
        source_family="fangfangtu_notes",
        source_type="note_pdf",
        slug="gap-note",
        source_page_ref="wiki:knowledge/wiki/sources/fangfangtu-gap-note.md",
    ),
    SourceSpec(
        raw_path="knowledge/raw/notes/方方土视频笔记-突破.pdf",
        source_family="fangfangtu_notes",
        source_type="note_pdf",
        slug="breakout-note",
        source_page_ref="wiki:knowledge/wiki/sources/fangfangtu-breakout-note.md",
    ),
    SourceSpec(
        raw_path="knowledge/raw/youtube/fangfangtu/transcripts/Price_Action方方土.pdf",
        source_family="fangfangtu_transcript",
        source_type="transcript_pdf",
        slug="price-action-transcript",
        source_page_ref="wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md",
    ),
    SourceSpec(
        raw_path="knowledge/raw/brooks/ppt/AIbrooks价格行为通用版1-36单元.pdf",
        source_family="al_brooks_ppt",
        source_type="ppt_pdf",
        slug="price-action-ppt-1-36-units",
        source_page_ref="wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md",
    ),
    SourceSpec(
        raw_path="knowledge/raw/brooks/ppt/AIbrooks价格行为通用版37-52单元.pdf",
        source_family="al_brooks_ppt",
        source_type="ppt_pdf",
        slug="price-action-ppt-37-52-units",
        source_page_ref="wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-37-52-units.md",
    ),
)


def short_sha1(value: str, *, length: int = 12) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def deterministic_generated_at(paths: list[Path]) -> str:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return "1970-01-01T00:00:00Z"
    latest = max(path.stat().st_mtime for path in existing)
    return (
        datetime.fromtimestamp(latest, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text)
    text = re.sub(r"[\t\f\v]+", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def frontmatter_and_body(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        raise ValueError(f"{path} missing frontmatter header")

    fm_lines: list[str] = []
    body_start = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = index + 1
            break
        fm_lines.append(line)

    if body_start is None:
        raise ValueError(f"{path} missing frontmatter terminator")

    data = yaml.safe_load("\n".join(fm_lines)) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} frontmatter must be a mapping")
    body = "\n".join(lines[body_start:]).strip()
    return data, body


def resolve_reference_path(reference: str) -> Path | None:
    if ":" not in reference:
        return None
    prefix, payload = reference.split(":", 1)
    if prefix not in {"wiki", "raw"} or not payload.strip():
        return None
    return PROJECT_ROOT / payload


def list_frontmatter(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def raw_ref_from_record(record: dict[str, Any]) -> str:
    return f"raw:{record['raw_path']}"


def discover_filtered_files() -> list[str]:
    filtered: list[str] = []
    scan_roots = (
        PROJECT_ROOT / "knowledge" / "raw" / "notes",
        PROJECT_ROOT / "knowledge" / "raw" / "youtube" / "fangfangtu" / "transcripts",
        PROJECT_ROOT / "knowledge" / "raw" / "brooks" / "ppt",
    )
    for root in scan_roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name.endswith(":Zone.Identifier"):
                filtered.append(path.relative_to(PROJECT_ROOT).as_posix())
    return filtered


def meaningful_page_text(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    alnum_count = sum(char.isalnum() for char in normalized)
    return alnum_count >= 8


def probe_pdf(path: Path) -> dict[str, Any]:
    if PdfReader is None:
        return {
            "parse_status": "blocked",
            "machine_readable": False,
            "parse_notes": "pypdf not installed",
            "page_count": 0,
            "non_empty_pages": 0,
            "empty_pages": [],
        }

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # pragma: no cover - exercised only on broken PDFs
        return {
            "parse_status": "blocked",
            "machine_readable": False,
            "parse_notes": f"failed to open pdf: {type(exc).__name__}: {exc}",
            "page_count": 0,
            "non_empty_pages": 0,
            "empty_pages": [],
        }

    page_count = len(reader.pages)
    non_empty_pages = 0
    empty_pages: list[int] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if meaningful_page_text(text):
            non_empty_pages += 1
        else:
            empty_pages.append(index)

    if page_count == 0 or non_empty_pages == 0:
        status = "blocked"
        notes = "no stable text extracted"
    elif empty_pages:
        status = "partial"
        notes = f"{len(empty_pages)} page(s) produced no stable text"
    else:
        status = "parsed"
        notes = "stable text extracted from all pages"

    return {
        "parse_status": status,
        "machine_readable": status != "blocked",
        "parse_notes": notes,
        "page_count": page_count,
        "non_empty_pages": non_empty_pages,
        "empty_pages": empty_pages,
    }


def build_source_manifest() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    generated_paths: list[Path] = []

    for spec in SOURCE_SPECS:
        raw_path = PROJECT_ROOT / spec.raw_path
        source_page_path = resolve_reference_path(spec.source_page_ref)
        if not raw_path.exists():
            raise FileNotFoundError(f"in-scope raw file is missing: {raw_path}")
        if source_page_path is None or not source_page_path.exists():
            raise FileNotFoundError(f"source page is missing: {spec.source_page_ref}")

        generated_paths.extend([raw_path, source_page_path])
        probe = probe_pdf(raw_path)
        record = {
            "source_id": spec.source_id,
            "source_family": spec.source_family,
            "source_type": spec.source_type,
            "raw_path": spec.raw_path,
            "file_name": spec.file_name,
            "parse_status": probe["parse_status"],
            "machine_readable": probe["machine_readable"],
            "source_page_ref": spec.source_page_ref,
            "parse_notes": probe["parse_notes"],
            "reviewed_at": deterministic_generated_at([raw_path, source_page_path]),
            "page_count": probe["page_count"],
            "non_empty_pages": probe["non_empty_pages"],
            "empty_pages": probe["empty_pages"],
        }
        records.append(record)

    filtered_files = discover_filtered_files()
    counts = {"parsed": 0, "partial": 0, "blocked": 0}
    for record in records:
        counts[record["parse_status"]] += 1

    return {
        "schema_version": SOURCE_MANIFEST_SCHEMA,
        "generated_at": deterministic_generated_at(generated_paths),
        "sources": records,
        "coverage_summary": {
            "total_expected": len(SOURCE_SPECS),
            "total_registered": len(records),
            "parse_status_counts": counts,
            "filtered_files": filtered_files,
        },
    }


def _split_long_block(text: str, *, max_chars: int = 900) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    blocks: list[str] = []
    start = 0
    while start < len(text):
        block = text[start : start + max_chars].strip()
        if block:
            blocks.append(block)
        start += max_chars
    return blocks


def split_page_blocks(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    parts = [normalize_text(part) for part in re.split(r"\n\s*\n+", normalized)]
    parts = [part for part in parts if part]
    if not parts:
        parts = [normalized]

    blocks: list[str] = []
    for part in parts:
        blocks.extend(_split_long_block(part))
    return blocks


def chunk_record(
    *,
    source_id: str,
    source_family: str,
    page_no: int,
    block_index: int,
    chunk_text: str,
    chunk_status: str,
) -> dict[str, Any]:
    raw_locator = {
        "locator_kind": "page_block",
        "page_no": page_no,
        "block_index": block_index,
    }
    base = f"{source_id}|{page_no}|{block_index}|{chunk_text}"
    return {
        "chunk_id": f"chunk--{short_sha1(base, length=14)}",
        "source_id": source_id,
        "source_family": source_family,
        "locator_kind": "page_block",
        "raw_locator": raw_locator,
        "chunk_text": chunk_text,
        "chunk_status": chunk_status,
        "parser_name": "pypdf",
        "parser_version": PYPDF_VERSION,
        "derived_from": {
            "source_id": source_id,
            "page_no": page_no,
        },
    }


def build_chunk_manifest(source_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    source_records = source_manifest["sources"]

    for source in source_records:
        raw_path = PROJECT_ROOT / source["raw_path"]
        if source["parse_status"] == "blocked":
            continue
        reader = PdfReader(str(raw_path))
        for page_no, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            blocks = split_page_blocks(text)
            if not blocks:
                records.append(
                    chunk_record(
                        source_id=source["source_id"],
                        source_family=source["source_family"],
                        page_no=page_no,
                        block_index=0,
                        chunk_text="",
                        chunk_status="blocked",
                    )
                )
                continue

            for block_index, block in enumerate(blocks, start=1):
                records.append(
                    chunk_record(
                        source_id=source["source_id"],
                        source_family=source["source_family"],
                        page_no=page_no,
                        block_index=block_index,
                        chunk_text=block,
                        chunk_status="parsed",
                    )
                )

    records.sort(
        key=lambda item: (
            item["source_id"],
            item["raw_locator"]["page_no"],
            item["raw_locator"]["block_index"],
        )
    )
    return records


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=False) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def source_record_maps(source_manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_source_id = {record["source_id"]: record for record in source_manifest["sources"]}
    by_raw_ref = {raw_ref_from_record(record): record for record in source_manifest["sources"]}
    return by_source_id, by_raw_ref


def parsed_chunks_by_source(chunks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        if chunk["chunk_status"] != "parsed":
            continue
        grouped.setdefault(chunk["source_id"], []).append(chunk)
    return grouped


def page_ref(path: Path) -> str:
    return f"wiki:{path.relative_to(PROJECT_ROOT).as_posix()}"


def body_summary(body: str) -> str:
    for line in body.splitlines():
        cleaned = normalize_text(line.lstrip("#").strip())
        if cleaned:
            return cleaned[:280]
    return ""


def source_ids_for_reference(
    reference: str,
    *,
    raw_ref_map: dict[str, dict[str, Any]],
    visited: set[str] | None = None,
) -> set[str]:
    visited = visited or set()
    if reference in visited:
        return set()
    visited.add(reference)

    if reference.startswith("raw:"):
        record = raw_ref_map.get(reference)
        return {record["source_id"]} if record else set()

    if not reference.startswith("wiki:"):
        return set()

    page_path = resolve_reference_path(reference)
    if page_path is None or not page_path.exists():
        return set()
    frontmatter, _ = frontmatter_and_body(page_path)
    source_refs = list_frontmatter(frontmatter.get("source_refs"))
    source_ids: set[str] = set()
    for ref in source_refs:
        source_ids.update(source_ids_for_reference(ref, raw_ref_map=raw_ref_map, visited=visited))
    return source_ids


def build_chunk_set_locator(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    members = [
        {
            "source_id": chunk["source_id"],
            "page_no": chunk["raw_locator"]["page_no"],
            "block_index": chunk["raw_locator"]["block_index"],
        }
        for chunk in chunks[:20]
    ]
    return {
        "locator_kind": "chunk_set",
        "member_count": len(chunks),
        "member_locators": members,
        "complete_via_evidence_chunk_ids": True,
    }


def _base_atom(
    *,
    atom_type: str,
    content: str,
    status: str,
    confidence: str,
    market: list[str],
    timeframes: list[str],
    pa_context: list[str],
    signal_bar: list[str],
    entry_bar: list[str],
    applicability: list[str],
    not_applicable: list[str],
    contradictions: list[str],
    derived_from: dict[str, Any],
    source_ref: str,
    raw_locator: dict[str, Any],
    evidence_chunk_ids: list[str],
    callable_tags: list[str],
    reviewed_at: str,
    last_updated: str,
    identity_seed: str,
) -> dict[str, Any]:
    return {
        "atom_id": f"atom--{short_sha1(identity_seed, length=16)}",
        "atom_type": atom_type,
        "content": content,
        "status": status,
        "confidence": confidence,
        "market": market,
        "timeframes": timeframes,
        "pa_context": pa_context,
        "signal_bar": signal_bar,
        "entry_bar": entry_bar,
        "applicability": applicability,
        "not_applicable": not_applicable,
        "contradictions": contradictions,
        "derived_from": derived_from,
        "source_ref": source_ref,
        "raw_locator": raw_locator,
        "evidence_chunk_ids": evidence_chunk_ids,
        "callable_tags": callable_tags,
        "reviewed_at": reviewed_at,
        "last_updated": last_updated,
    }


def qualifies_statement(fragment: str) -> bool:
    text = normalize_text(fragment)
    if len(text) < 18 or len(text) > 280:
        return False
    if text.lower().startswith(("http://", "https://")):
        return False
    lowered = text.lower()
    collapsed = re.sub(r"\s+", "", lowered).replace("1", "i")
    if contains_statement_boilerplate(text, lowered=lowered, collapsed=collapsed):
        return False
    if any(lowered.startswith(prefix) and len(text) < 40 for prefix in _NOISE_PREFIXES):
        return False
    if looks_like_header_fragment(text):
        return False
    symbol_count = sum(char.isalnum() for char in text)
    if symbol_count < 8:
        return False
    if re.fullmatch(r"[\d\s\-/.:]+", text):
        return False
    if looks_like_low_value_statement(text):
        return False
    return True


def looks_like_header_fragment(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized or len(normalized) > 48:
        return False

    ascii_words = re.findall(r"[A-Za-z][A-Za-z0-9']*", normalized)
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", normalized))
    if ascii_words and not has_cjk and len(ascii_words) <= 5 and not re.search(r"[。！？!?;；:：]", normalized):
        return True
    if re.search(r"[。！？!?;；:：,，]", normalized):
        return False
    if ascii_words and not has_cjk and len(ascii_words) <= 6 and all(
        word[:1].isupper() or word.lower() in _HEADER_CONNECTORS for word in ascii_words
    ):
        return True
    return False


def contains_statement_boilerplate(text: str, *, lowered: str | None = None, collapsed: str | None = None) -> bool:
    normalized = normalize_text(text)
    lowered = lowered or normalized.lower()
    collapsed = collapsed or re.sub(r"\s+", "", lowered).replace("1", "i")

    if lowered in _REJECT_EXACT_FRAGMENTS or collapsed == "brookstradingcourse":
        return True
    if "官方中文全集" in normalized:
        return True
    if "brookspriceaction" in collapsed or "brookstradingcourse" in collapsed:
        return True
    if collapsed.startswith("brooks") and "course" in collapsed:
        return True
    return any(pattern.search(normalized) for pattern in _REJECT_STATEMENT_PATTERNS)


def looks_like_low_value_statement(text: str) -> bool:
    normalized = normalize_text(text)
    lowered = normalized.lower()
    digit_count = sum(char.isdigit() for char in normalized)
    alpha_count = sum(char.isalpha() for char in normalized)
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", normalized))

    if re.search(r"(?:^|[/\s~'\":])\d{1,4}/\d{1,2}(?:/\d{1,4})?(?:[\s.:]|$)", normalized) and digit_count >= 4:
        return True
    if digit_count >= 6 and digit_count >= alpha_count and normalized.count("/") >= 1:
        return True
    if digit_count >= 8 and digit_count >= alpha_count:
        return True
    if digit_count >= 8 and normalized.count("/") >= 3:
        return True
    if re.match(r"^[%+~·•-]", normalized):
        return True
    if re.match(r"^[：:，,；;、)\]】】]", normalized):
        return True
    if any(pattern.match(normalized) for pattern in _SECTION_HEADING_PATTERNS):
        return True
    if re.search(r"(?:\b[A-Za-z]\s+){3,}[A-Za-z]\b", normalized):
        return True
    if re.search(r"[^A-Za-z0-9\u4e00-\u9fff\s,.;:!?()/%&'\"+-]", normalized):
        weird_chars = sum(
            1 for char in normalized if not re.match(r"[A-Za-z0-9\u4e00-\u9fff\s,.;:!?()/%&'\"+-]", char)
        )
        if weird_chars >= 8 or (weird_chars >= 3 and not has_cjk):
            return True
    if re.match(r"^[a-z]", normalized):
        return True
    if re.search(r"[,，;；(/-]$", normalized):
        return True
    if re.search(r"[:：]\s*$", normalized):
        return True
    if lowered.startswith(_QUESTION_HEADING_PREFIXES):
        return True
    if re.search(r"\b(?:19|20)\d{2}\b|\b\d{1,2}:\d{2}\b", normalized):
        return True
    if not has_cjk and re.search(r"\b\d{4}(?:\.\d{1,2})?\b", normalized):
        return True
    if not has_cjk and re.search(r"\b(or|and|to|of|for|with|than|from|on|in|at|but|a|an)$", lowered):
        return True
    return False


def extract_statement_fragments(chunk_text: str) -> list[str]:
    normalized = normalize_text(chunk_text)
    if not normalized:
        return []

    split_parts = re.split(r"(?:[•●▪■◦○◆◇]+|\n+)", normalized)
    candidates = [normalize_text(part) for part in split_parts if normalize_text(part)]
    if not candidates:
        candidates = [normalized]

    statements: list[str] = []
    for candidate in candidates:
        candidate = re.sub(r"^[\d\.\-]+\s*", "", candidate)
        candidate = normalize_text(candidate)
        if not qualifies_statement(candidate):
            continue
        if candidate not in statements:
            statements.append(candidate)
        if len(statements) >= 4:
            break
    return statements


def build_knowledge_atoms(
    source_manifest: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    atoms: list[dict[str, Any]] = []
    by_source_id, by_raw_ref = source_record_maps(source_manifest)
    parsed_by_source = parsed_chunks_by_source(chunks)
    source_page_cache: dict[str, tuple[dict[str, Any], str]] = {}

    def source_page_frontmatter(page_reference: str) -> tuple[dict[str, Any], str]:
        if page_reference not in source_page_cache:
            page_path = resolve_reference_path(page_reference)
            if page_path is None:
                raise ValueError(f"invalid wiki reference: {page_reference}")
            source_page_cache[page_reference] = frontmatter_and_body(page_path)
        return source_page_cache[page_reference]

    for source in source_manifest["sources"]:
        source_frontmatter, _ = source_page_frontmatter(source["source_page_ref"])
        source_chunks = parsed_by_source.get(source["source_id"], [])
        reviewed_at = str(source_frontmatter.get("last_reviewed", source["reviewed_at"]))
        last_updated = source["reviewed_at"]
        base_tags = [
            f"source_family:{source['source_family']}",
            f"source_type:{source['source_type']}",
            "explanation_only",
            "review_only",
        ]

        seen_statement_fingerprints: set[str] = set()
        for chunk in source_chunks:
            content = chunk["chunk_text"]
            atoms.append(
                _base_atom(
                    atom_type="source_note",
                    content=content,
                    status="draft",
                    confidence=str(source_frontmatter.get("confidence", "low")),
                    market=list_frontmatter(source_frontmatter.get("market")),
                    timeframes=list_frontmatter(source_frontmatter.get("timeframes")),
                    pa_context=list_frontmatter(source_frontmatter.get("pa_context")),
                    signal_bar=list_frontmatter(source_frontmatter.get("signal_bar")),
                    entry_bar=list_frontmatter(source_frontmatter.get("entry_bar")),
                    applicability=list_frontmatter(source_frontmatter.get("applicability")),
                    not_applicable=list_frontmatter(source_frontmatter.get("not_applicable")),
                    contradictions=[],
                    derived_from={"source_id": source["source_id"], "chunk_id": chunk["chunk_id"]},
                    source_ref=source["source_page_ref"],
                    raw_locator=chunk["raw_locator"],
                    evidence_chunk_ids=[chunk["chunk_id"]],
                    callable_tags=base_tags,
                    reviewed_at=reviewed_at,
                    last_updated=last_updated,
                    identity_seed=f"source_note|{source['source_id']}|{chunk['chunk_id']}",
                )
            )

            for fragment_index, fragment in enumerate(extract_statement_fragments(content), start=1):
                fingerprint = " ".join(
                    re.sub(r"[^\w\s]+", " ", fragment.lower()).split()
                )
                if fingerprint in seen_statement_fingerprints:
                    continue
                seen_statement_fingerprints.add(fingerprint)
                atoms.append(
                    _base_atom(
                        atom_type="statement",
                        content=fragment,
                        status="draft",
                        confidence=str(source_frontmatter.get("confidence", "low")),
                        market=list_frontmatter(source_frontmatter.get("market")),
                        timeframes=list_frontmatter(source_frontmatter.get("timeframes")),
                        pa_context=list_frontmatter(source_frontmatter.get("pa_context")),
                        signal_bar=list_frontmatter(source_frontmatter.get("signal_bar")),
                        entry_bar=list_frontmatter(source_frontmatter.get("entry_bar")),
                        applicability=list_frontmatter(source_frontmatter.get("applicability")),
                        not_applicable=list_frontmatter(source_frontmatter.get("not_applicable")),
                        contradictions=[],
                        derived_from={
                            "source_id": source["source_id"],
                            "chunk_id": chunk["chunk_id"],
                            "fragment_index": fragment_index,
                        },
                        source_ref=source["source_page_ref"],
                        raw_locator={
                            **chunk["raw_locator"],
                            "fragment_index": fragment_index,
                        },
                        evidence_chunk_ids=[chunk["chunk_id"]],
                        callable_tags=base_tags + ["statement_candidate"],
                        reviewed_at=reviewed_at,
                        last_updated=last_updated,
                        identity_seed=f"statement|{source['source_id']}|{chunk['chunk_id']}|{fragment_index}|{fragment}",
                    )
                )

        evidence_chunks = source_chunks
        if evidence_chunks:
            raw_locator = build_chunk_set_locator(evidence_chunks)
            evidence_chunk_ids = [chunk["chunk_id"] for chunk in evidence_chunks]
            shared_tags = base_tags
            for field_name, atom_type in (("open_questions", "open_question"), ("contradictions", "contradiction")):
                for item in list_frontmatter(source_frontmatter.get(field_name)):
                    atoms.append(
                        _base_atom(
                            atom_type=atom_type,
                            content=item,
                            status="draft",
                            confidence=str(source_frontmatter.get("confidence", "low")),
                            market=list_frontmatter(source_frontmatter.get("market")),
                            timeframes=list_frontmatter(source_frontmatter.get("timeframes")),
                            pa_context=list_frontmatter(source_frontmatter.get("pa_context")),
                            signal_bar=list_frontmatter(source_frontmatter.get("signal_bar")),
                            entry_bar=list_frontmatter(source_frontmatter.get("entry_bar")),
                            applicability=list_frontmatter(source_frontmatter.get("applicability")),
                            not_applicable=list_frontmatter(source_frontmatter.get("not_applicable")),
                            contradictions=[],
                            derived_from={
                                "source_id": source["source_id"],
                                "field": field_name,
                            },
                            source_ref=source["source_page_ref"],
                            raw_locator=raw_locator,
                            evidence_chunk_ids=evidence_chunk_ids,
                            callable_tags=shared_tags,
                            reviewed_at=reviewed_at,
                            last_updated=last_updated,
                            identity_seed=f"{atom_type}|{source['source_id']}|{item}",
                        )
                    )

    for page_ref in KEY_CURATED_PAGE_REFS:
        page_path = resolve_reference_path(page_ref)
        if page_path is None:
            raise ValueError(f"invalid curated page ref: {page_ref}")
        frontmatter, body = frontmatter_and_body(page_path)
        source_ids: set[str] = set()
        for reference in list_frontmatter(frontmatter.get("source_refs")):
            source_ids.update(source_ids_for_reference(reference, raw_ref_map=by_raw_ref))
        evidence_chunks: list[dict[str, Any]] = []
        for source_id in sorted(source_ids):
            evidence_chunks.extend(parsed_by_source.get(source_id, []))
        evidence_chunks.sort(
            key=lambda chunk: (
                chunk["source_id"],
                chunk["raw_locator"]["page_no"],
                chunk["raw_locator"]["block_index"],
            )
        )
        evidence_chunk_ids = [chunk["chunk_id"] for chunk in evidence_chunks]
        raw_locator = build_chunk_set_locator(evidence_chunks)
        callable_tags = ["curated_callable", "explanation_only", "review_only"]
        for source_id in sorted(source_ids):
            callable_tags.append(f"source_family:{by_source_id[source_id]['source_family']}")

        content = body_summary(body) or str(frontmatter.get("title", ""))
        reviewed_at = str(frontmatter.get("last_reviewed", ""))
        last_updated = deterministic_generated_at([page_path])
        atoms.append(
            _base_atom(
                atom_type=str(frontmatter.get("type", "")),
                content=content,
                status=str(frontmatter.get("status", "draft")),
                confidence=str(frontmatter.get("confidence", "low")),
                market=list_frontmatter(frontmatter.get("market")),
                timeframes=list_frontmatter(frontmatter.get("timeframes")),
                pa_context=list_frontmatter(frontmatter.get("pa_context")),
                signal_bar=list_frontmatter(frontmatter.get("signal_bar")),
                entry_bar=list_frontmatter(frontmatter.get("entry_bar")),
                applicability=list_frontmatter(frontmatter.get("applicability")),
                not_applicable=list_frontmatter(frontmatter.get("not_applicable")),
                contradictions=list_frontmatter(frontmatter.get("contradictions")),
                derived_from={"page_ref": page_ref},
                source_ref=page_ref,
                raw_locator=raw_locator,
                evidence_chunk_ids=evidence_chunk_ids,
                callable_tags=sorted(set(callable_tags)),
                reviewed_at=reviewed_at,
                last_updated=last_updated,
                identity_seed=f"curated|{page_ref}|{content}|{','.join(evidence_chunk_ids)}",
            )
        )

        for field_name, atom_type in (("open_questions", "open_question"), ("contradictions", "contradiction")):
            for item in list_frontmatter(frontmatter.get(field_name)):
                atoms.append(
                    _base_atom(
                        atom_type=atom_type,
                        content=item,
                        status=str(frontmatter.get("status", "draft")),
                        confidence=str(frontmatter.get("confidence", "low")),
                        market=list_frontmatter(frontmatter.get("market")),
                        timeframes=list_frontmatter(frontmatter.get("timeframes")),
                        pa_context=list_frontmatter(frontmatter.get("pa_context")),
                        signal_bar=list_frontmatter(frontmatter.get("signal_bar")),
                        entry_bar=list_frontmatter(frontmatter.get("entry_bar")),
                        applicability=list_frontmatter(frontmatter.get("applicability")),
                        not_applicable=list_frontmatter(frontmatter.get("not_applicable")),
                        contradictions=[],
                        derived_from={"page_ref": page_ref, "field": field_name},
                        source_ref=page_ref,
                        raw_locator=raw_locator,
                        evidence_chunk_ids=evidence_chunk_ids,
                        callable_tags=sorted(set(callable_tags)),
                        reviewed_at=reviewed_at,
                        last_updated=last_updated,
                        identity_seed=f"{atom_type}|{page_ref}|{item}|{','.join(evidence_chunk_ids)}",
                    )
                )

    atoms.sort(key=lambda atom: (atom["atom_type"], atom["source_ref"], atom["atom_id"]))
    return atoms


def build_callable_index(
    source_manifest: dict[str, Any],
    chunks: list[dict[str, Any]],
    atoms: list[dict[str, Any]],
) -> dict[str, Any]:
    index = {
        "by_atom_type": {},
        "by_source_id": {},
        "by_source_family": {},
        "by_market": {},
        "by_timeframe": {},
        "by_pa_context": {},
        "by_status": {},
        "by_confidence": {},
        "by_callable_tag": {},
    }

    by_source_id, _ = source_record_maps(source_manifest)
    chunk_source_map = {
        chunk["chunk_id"]: chunk["source_id"]
        for chunk in chunks
        if chunk["chunk_status"] == "parsed"
    }

    def add(bucket: dict[str, list[str]], key: str, atom_id: str) -> None:
        if not key:
            return
        bucket.setdefault(key, []).append(atom_id)

    for atom in atoms:
        atom_id = atom["atom_id"]
        add(index["by_atom_type"], atom["atom_type"], atom_id)
        add(index["by_status"], atom["status"], atom_id)
        add(index["by_confidence"], atom["confidence"], atom_id)
        for market in atom["market"]:
            add(index["by_market"], market, atom_id)
        for timeframe in atom["timeframes"]:
            add(index["by_timeframe"], timeframe, atom_id)
        for context in atom["pa_context"]:
            add(index["by_pa_context"], context, atom_id)
        for tag in atom["callable_tags"]:
            add(index["by_callable_tag"], tag, atom_id)

        evidence_chunk_ids = atom["evidence_chunk_ids"]
        source_ids = sorted({chunk_source_map[chunk_id] for chunk_id in evidence_chunk_ids if chunk_id in chunk_source_map})
        if not source_ids and atom["source_ref"].startswith("wiki:knowledge/wiki/sources/"):
            for record in source_manifest["sources"]:
                if record["source_page_ref"] == atom["source_ref"]:
                    source_ids = [record["source_id"]]
                    break
        for source_id in source_ids:
            add(index["by_source_id"], source_id, atom_id)
            add(index["by_source_family"], by_source_id[source_id]["source_family"], atom_id)

    for bucket in index.values():
        for key, values in list(bucket.items()):
            bucket[key] = sorted(set(values))

    return {
        "schema_version": CALLABLE_INDEX_SCHEMA,
        "generated_at": source_manifest["generated_at"],
        "atom_count": len(atoms),
        "indices": index,
    }


def validate_source_manifest(source_manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    records = source_manifest.get("sources", [])
    if len(records) != len(SOURCE_SPECS):
        errors.append(f"expected {len(SOURCE_SPECS)} source records, found {len(records)}")

    expected_raw_paths = {spec.raw_path for spec in SOURCE_SPECS}
    actual_raw_paths = {record.get("raw_path") for record in records}
    missing = sorted(expected_raw_paths - actual_raw_paths)
    if missing:
        errors.append(f"missing source records for: {missing}")

    for record in records:
        for field in (
            "source_id",
            "source_family",
            "source_type",
            "raw_path",
            "file_name",
            "parse_status",
            "machine_readable",
            "source_page_ref",
            "parse_notes",
            "reviewed_at",
        ):
            if field not in record:
                errors.append(f"source record missing field: {field}")
        if record.get("source_type") not in ALLOWED_SOURCE_TYPES:
            errors.append(f"invalid source_type: {record.get('source_type')}")
        if record.get("parse_status") not in ALLOWED_PARSE_STATUS:
            errors.append(f"invalid parse_status: {record.get('parse_status')}")
        source_page_path = resolve_reference_path(str(record.get("source_page_ref", "")))
        if source_page_path is None or not source_page_path.exists():
            errors.append(f"missing source page for {record.get('source_id')}: {record.get('source_page_ref')}")

    filtered_files = source_manifest.get("coverage_summary", {}).get("filtered_files", [])
    if any(not item.endswith(":Zone.Identifier") for item in filtered_files):
        errors.append("filtered_files contains non-sidecar entries")
    if "knowledge/raw/youtube/fangfangtu/transcripts/Price_Action方方土.pdf:Zone.Identifier" not in filtered_files:
        errors.append("Zone.Identifier sidecar is not recorded in filtered_files")
    blocked_count = source_manifest.get("coverage_summary", {}).get("parse_status_counts", {}).get("blocked", 0)
    if blocked_count >= 4:
        errors.append(f"blocked source fuse triggered: blocked={blocked_count}")
    return errors


def validate_knowledge_atoms(
    source_manifest: dict[str, Any],
    chunks: list[dict[str, Any]],
    atoms: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    chunk_ids = {chunk["chunk_id"] for chunk in chunks if chunk["chunk_status"] == "parsed"}
    seen_curated_refs: set[str] = set()

    for atom in atoms:
        for field in (
            "atom_id",
            "atom_type",
            "content",
            "status",
            "confidence",
            "source_ref",
            "raw_locator",
            "evidence_chunk_ids",
            "callable_tags",
        ):
            if field not in atom or atom[field] in ("", [], None):
                errors.append(f"atom missing required field {field}: {atom.get('atom_id')}")

        atom_type = atom.get("atom_type")
        if atom_type not in ALLOWED_ATOM_TYPES:
            errors.append(f"invalid atom_type: {atom_type}")
        reference_path = resolve_reference_path(str(atom.get("source_ref", "")))
        if reference_path is None or not reference_path.exists():
            errors.append(f"atom source_ref does not resolve: {atom.get('source_ref')}")
        evidence_ids = atom.get("evidence_chunk_ids", [])
        for chunk_id in evidence_ids:
            if chunk_id not in chunk_ids:
                errors.append(f"atom references unknown or blocked chunk: {atom.get('atom_id')} -> {chunk_id}")
        if atom_type == "statement":
            if atom.get("status") != "draft":
                errors.append(f"statement must default to draft: {atom.get('atom_id')}")
            if "strategy_candidate" in atom.get("callable_tags", []):
                errors.append(f"statement must not carry strategy_candidate: {atom.get('atom_id')}")
            content = str(atom.get("content", ""))
            if (
                looks_like_header_fragment(content)
                or contains_statement_boilerplate(content)
                or looks_like_low_value_statement(content)
            ):
                errors.append(f"statement contains header-like boilerplate: {atom.get('atom_id')}")
        if atom_type in {"source_note", "open_question", "contradiction"} and "strategy_candidate" in atom.get(
            "callable_tags", []
        ):
            errors.append(f"{atom_type} must not carry strategy_candidate: {atom.get('atom_id')}")
        if atom_type in {"concept", "setup", "rule"}:
            seen_curated_refs.add(str(atom.get("source_ref")))
            if not evidence_ids:
                errors.append(f"curated atom missing evidence: {atom.get('atom_id')}")

    for required_ref in KEY_CURATED_PAGE_REFS:
        if required_ref not in seen_curated_refs:
            errors.append(f"missing evidence-backed curated atom for {required_ref}")

    blocked_count = source_manifest["coverage_summary"]["parse_status_counts"]["blocked"]
    if blocked_count >= 4:
        errors.append(f"blocked sources triggered fuse gate: {blocked_count}")
    return errors


def query_atoms(
    *,
    atoms: list[dict[str, Any]],
    callable_index: dict[str, Any],
    atom_type: str | None = None,
    source_id: str | None = None,
    source_family: str | None = None,
    market: str | None = None,
    timeframe: str | None = None,
    pa_context: str | None = None,
    status: str | None = None,
    confidence: str | None = None,
    callable_tag: str | None = None,
) -> list[dict[str, Any]]:
    atoms_by_id = {atom["atom_id"]: atom for atom in atoms}
    indices = callable_index["indices"]
    candidates: set[str] = set(atoms_by_id)

    filters = [
        (atom_type, indices["by_atom_type"]),
        (source_id, indices["by_source_id"]),
        (source_family, indices["by_source_family"]),
        (market, indices["by_market"]),
        (timeframe, indices["by_timeframe"]),
        (pa_context, indices["by_pa_context"]),
        (status, indices["by_status"]),
        (confidence, indices["by_confidence"]),
        (callable_tag, indices["by_callable_tag"]),
    ]

    for value, bucket in filters:
        if value is None:
            continue
        candidates &= set(bucket.get(value, []))

    return [atoms_by_id[atom_id] for atom_id in sorted(candidates)]
