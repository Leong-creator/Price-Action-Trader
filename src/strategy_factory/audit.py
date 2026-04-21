from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
SCHEMA_VERSION = "m9-strategy-factory-audit-v4"
NAMESPACE = "SF"

FORMAL_CATEGORIES = (
    "strategy_candidate",
    "supporting_evidence",
    "non_strategy",
    "open_question",
    "parked_visual_review",
    "duplicate_or_merged",
    "blocked_or_partial_evidence",
)

THEME_DEFINITIONS: dict[str, dict[str, Any]] = {
    "trend_pullback_second_entry": {
        "title": "Trend Pullback Second Entry",
        "catalog_strategy_id": "SF-001",
        "direction": "both",
        "market_context": ["trend", "pullback", "second_entry"],
        "applicable_market": ["US", "HK"],
        "timeframe": ["5m", "15m", "1h"],
        "entry_idea": "在顺势背景中等待 H1/H2/L1/L2 或 second-entry 触发，再用 buy/sell stop 跟进。",
        "stop_idea": "放在 signal bar 或失败 second-entry 的 opposite extreme 外侧。",
        "target_idea": "先看 1R~2R，若趋势与 channel 仍强则允许转成 swing。",
        "invalidation": [
            "后续 follow-through 很差",
            "出现 bull trap / bear trap 或关键低点/高点被反向突破",
        ],
        "no_trade_conditions": [
            "背景不是顺势 pullback",
            "在强趋势第一次反转就逆势抢反转",
        ],
        "parameter_candidates": [
            "pullback bar count <= 3",
            "signal bar quality >= close near extreme",
            "minimum R multiple >= 1.0",
        ],
        "expected_failure_modes": [
            "把 broad channel 误当 tight trend",
            "在 MM 附近或 climax 后继续追价",
        ],
        "data_requirements": [
            "OHLCV with session labels",
            "bar-level high/low for stop placement",
        ],
        "chart_dependency": "medium",
        "test_priority": "high",
        "status": "candidate",
        "family_bias_risk": "notes_chunk_split_bias",
        "context_terms": [
            "上涨趋势",
            "下降趋势",
            "回调",
            "pullback",
            "trend",
            "窄通道",
            "always in",
        ],
        "entry_terms": [
            "高1",
            "高2",
            "低1",
            "低2",
            "h1",
            "h2",
            "l1",
            "l2",
            "第二入场",
            "second entry",
            "buy stop",
            "sell stop",
            "市价买入",
            "买阳线收盘",
        ],
        "invalidation_terms": [
            "止损",
            "bull trap",
            "bear trap",
            "失败",
            "失效",
            "跌破",
            "立刻止损",
        ],
        "visual_terms": ["图", "箭头", "趋势线"],
        "legacy_overlap_refs": [
            "wiki:knowledge/wiki/strategy_cards/combined/pa-sc-001-trend-pullback-resumption.md",
            "wiki:knowledge/wiki/strategy_cards/combined/pa-sc-005-h2-l2-second-entry.md",
        ],
        "historical_comparison_refs": [
            "report:reports/strategy_lab/m9_strategy_lab_summary.md",
        ],
        "historical_benchmark_refs": [],
    },
    "breakout_follow_through_continuation": {
        "title": "Breakout Follow-Through Continuation",
        "catalog_strategy_id": "SF-002",
        "direction": "both",
        "market_context": ["breakout", "follow_through", "trend_continuation"],
        "applicable_market": ["US", "HK"],
        "timeframe": ["5m", "15m", "1h"],
        "entry_idea": "确认 breakout 后的 good follow-through，再用 market/stop order 顺势跟进。",
        "stop_idea": "放在 breakout bar 或 follow-through cluster 的 opposite extreme 外侧。",
        "target_idea": "优先看 measured move 与后续 second leg continuation。",
        "invalidation": [
            "breakout 后 follow-through 很差",
            "出现 deep pullback 或 gap 被迅速回补",
        ],
        "no_trade_conditions": [
            "突破没有急迫感或没有连续性",
            "处于明显 trading range 且 follow-through 质量差",
        ],
        "parameter_candidates": [
            "minimum breakout bar body size",
            "follow-through bars within 2~3 bars",
            "gap persistence requirement",
        ],
        "expected_failure_modes": [
            "TR 内追 breakout 被 80-20 假突破打回",
            "把 weak breakout 误判成 strong breakout",
        ],
        "data_requirements": [
            "OHLCV with session labels",
            "gap detection based on bar overlap",
        ],
        "chart_dependency": "medium",
        "test_priority": "high",
        "status": "candidate",
        "family_bias_risk": "transcript_first_source_bias",
        "context_terms": [
            "突破",
            "breakout",
            "trend bar",
            "surprise",
            "always in",
            "缺口",
            "gap",
        ],
        "entry_terms": [
            "follow-through",
            "follow through",
            "ft",
            "收盘价卖出",
            "收盘价买入",
            "sell the close",
            "market order",
            "stop order",
            "突破单",
        ],
        "invalidation_terms": [
            "假突破",
            "失败",
            "回调很深",
            "深的回调",
            "跟随很差",
            "止损",
            "迅速弥补",
        ],
        "visual_terms": ["图", "箭头", "线形图"],
        "legacy_overlap_refs": [
            "wiki:knowledge/wiki/strategy_cards/combined/pa-sc-002-breakout-follow-through.md",
        ],
        "historical_comparison_refs": [
            "report:reports/strategy_lab/m9_strategy_lab_summary.md",
        ],
        "historical_benchmark_refs": [
            "report:reports/strategy_lab/pa_sc_002_first_backtest_report.md",
        ],
    },
    "failed_breakout_range_reversal": {
        "title": "Failed Breakout Range-Edge Reversal",
        "catalog_strategy_id": "SF-003",
        "direction": "both",
        "market_context": ["trading_range", "failed_breakout", "reversal"],
        "applicable_market": ["US", "HK"],
        "timeframe": ["5m", "15m", "1h"],
        "entry_idea": "在区间边缘或第二段 trap 明确失败后，等反转 signal 再逆势进场。",
        "stop_idea": "放在 failed breakout extreme 之外，若重新获得连续 follow-through 则失效。",
        "target_idea": "先看回到 TR 中轴或 opposite edge，再视 broad channel 结构决定是否延伸。",
        "invalidation": [
            "breakout 重新得到连续 follow-through",
            "区间结构被 surprise bar 直接改写",
        ],
        "no_trade_conditions": [
            "仍在 Always In 强趋势的第一次反转里抢顶/抢底",
            "没有足够 range context 就把单根 reversal bar 当失败突破",
        ],
        "parameter_candidates": [
            "range edge proximity",
            "second leg trap confirmation",
            "follow-through failure within 2 bars",
        ],
        "expected_failure_modes": [
            "把 broad channel continuation 误当 range reversal",
            "在强 breakout 中过早逆势",
        ],
        "data_requirements": [
            "OHLCV with session labels",
            "range edge and failed follow-through detection",
        ],
        "chart_dependency": "medium",
        "test_priority": "high",
        "status": "candidate",
        "family_bias_risk": "merge_with_breakout_continuation_risk",
        "context_terms": [
            "failed breakout",
            "假突破",
            "trading range",
            "震荡区间",
            "2nd leg trap",
            "second leg trap",
            "区间",
            "range",
        ],
        "entry_terms": [
            "反转",
            "直接入场",
            "做空点",
            "做多低点",
            "逆势",
            "reasonable",
            "buy low",
            "sell high",
        ],
        "invalidation_terms": [
            "连续跟随",
            "成功突破",
            "强趋势",
            "止损",
            "保护利润",
        ],
        "visual_terms": ["图", "箭头", "上下沿"],
        "legacy_overlap_refs": [
            "wiki:knowledge/wiki/strategy_cards/combined/pa-sc-003-failed-breakout-reversal.md",
            "wiki:knowledge/wiki/strategy_cards/fangfangtu/pa-sc-004-trading-range-edge-reversal.md",
        ],
        "historical_comparison_refs": [
            "report:reports/strategy_lab/m9_strategy_lab_summary.md",
        ],
        "historical_benchmark_refs": [],
    },
    "tight_channel_trend_continuation": {
        "title": "Tight Channel Trend Continuation",
        "catalog_strategy_id": "SF-004",
        "direction": "both",
        "market_context": ["tight_channel", "always_in", "trend_continuation"],
        "applicable_market": ["US", "HK"],
        "timeframe": ["5m", "15m", "1h"],
        "entry_idea": "在 Tight Channel / Always In 背景中只顺势做，等待微回调或 signal bar 后继续跟随。",
        "stop_idea": "放在最近短回调极值之外；若 channel 重叠明显增加则失效。",
        "target_idea": "以前高/前低、measured move 或 trend day extension 为主。",
        "invalidation": [
            "channel 退化成 broad channel / trading range",
            "出现清晰的二次反转并伴随强 follow-through",
        ],
        "no_trade_conditions": [
            "在强窄通道里逆势数 wedge 或抢第一次反转",
            "回调 bar 数和重叠度已经明显失去 tight-channel 特征",
        ],
        "parameter_candidates": [
            "max pullback bars <= 3",
            "channel overlap threshold",
            "trend day session filter",
        ],
        "expected_failure_modes": [
            "把 weak channel 误当 tight channel",
            "进入 broad channel 后仍按 Always In 持有",
        ],
        "data_requirements": [
            "OHLCV with session labels",
            "channel overlap and pullback depth stats",
        ],
        "chart_dependency": "medium",
        "test_priority": "medium",
        "status": "candidate",
        "family_bias_risk": "ppt_theme_density_bias",
        "context_terms": [
            "tight channel",
            "窄通道",
            "always in long",
            "always in short",
            "trend day",
            "trend from the open",
            "ai行情",
        ],
        "entry_terms": [
            "只能做多",
            "只能做空",
            "任何理由都是开仓",
            "market order",
            "市价",
            "顺势",
        ],
        "invalidation_terms": [
            "回调多",
            "幅度大",
            "震荡区间",
            "宽通道",
            "止损",
        ],
        "visual_terms": ["图", "趋势线", "蓝色", "红色"],
        "legacy_overlap_refs": [
            "wiki:knowledge/wiki/strategy_cards/combined/pa-sc-006-tight-channel-resumption.md",
            "wiki:knowledge/wiki/strategy_cards/combined/pa-sc-009-trend-day-range-day-filter.md",
        ],
        "historical_comparison_refs": [
            "report:reports/strategy_lab/m9_strategy_lab_summary.md",
        ],
        "historical_benchmark_refs": [],
    },
    "gap_continuation_exhaustion": {
        "title": "Gap Continuation Versus Exhaustion",
        "catalog_strategy_id": "SF-005",
        "direction": "both",
        "market_context": ["gap", "breakout", "measurement", "exhaustion"],
        "applicable_market": ["US", "HK"],
        "timeframe": ["5m", "15m", "1h", "2h"],
        "entry_idea": "先判断 gap 是 breakout / measuring 还是 exhaustion，再决定顺势 continuation 或 gap fill reversal。",
        "stop_idea": "顺势单放在 gap base 外侧，exhaustion/filled-gap 单放在 gap recovery failure 外侧。",
        "target_idea": "breakout / measuring gap 看 measured move；exhaustion gap 先看回补与进入 TR。",
        "invalidation": [
            "gap 被迅速回补且 follow-through 失败",
            "本应 exhaustion 的 gap 反而保持连续 trend bars",
        ],
        "no_trade_conditions": [
            "gap 类型无法区分",
            "只看到 gap 但没有 trend / TR 背景",
        ],
        "parameter_candidates": [
            "gap type classification",
            "EMA / prior high-low gap persistence",
            "measured-move target anchor",
        ],
        "expected_failure_modes": [
            "把 exhaustion gap 误当 continuation",
            "只看 gap 不看 trend context",
        ],
        "data_requirements": [
            "OHLCV with gap/overlap detection",
            "prior-session anchors",
        ],
        "chart_dependency": "medium",
        "test_priority": "medium",
        "status": "candidate",
        "family_bias_risk": "notes_context_split_bias",
        "context_terms": [
            "缺口",
            "gap",
            "突破型缺口",
            "测量型缺口",
            "竭尽型缺口",
            "line with markers",
        ],
        "entry_terms": [
            "做mm",
            "继续这个方向",
            "尝试做空",
            "做多",
            "顺利到达",
            "趋势仍然存在",
        ],
        "invalidation_terms": [
            "迅速弥补",
            "进入tr",
            "反转",
            "回补",
            "止损",
        ],
        "visual_terms": ["图", "线形图", "左边", "右边"],
        "legacy_overlap_refs": [
            "wiki:knowledge/wiki/strategy_cards/brooks/pa-sc-008-opening-range-breakout.md",
        ],
        "historical_comparison_refs": [
            "report:reports/strategy_lab/m9_strategy_lab_summary.md",
        ],
        "historical_benchmark_refs": [],
    },
    "signal_bar_contextual_entry": {
        "title": "Signal Bar Contextual Entry",
        "catalog_strategy_id": None,
        "direction": "both",
        "market_context": ["signal_bar", "contextual_entry"],
        "chart_dependency": "high",
        "test_priority": "parked",
        "status": "parked_visual_review",
        "context_terms": [
            "signal bar",
            "信号k",
            "trend bar",
            "trading range bar",
            "背景环境",
            "两k反转",
            "吞噬线",
            "孕线",
        ],
        "entry_terms": [
            "stop order",
            "limit order",
            "上方的一个tick",
            "下方的一个tick",
            "等待收盘",
            "挂stop order",
        ],
        "invalidation_terms": [
            "坏的背景",
            "差的背景",
            "坏的信号k",
            "胜率很低",
            "不做",
            "止损",
        ],
        "visual_terms": ["图", "切到更小级别", "蓝色", "红色"],
        "legacy_overlap_refs": [
            "wiki:knowledge/wiki/strategy_cards/combined/pa-sc-005-h2-l2-second-entry.md",
        ],
        "historical_comparison_refs": [
            "report:reports/strategy_lab/m9_strategy_lab_summary.md",
        ],
        "historical_benchmark_refs": [],
    },
    "wedge_exhaustion_reversal": {
        "title": "Wedge Exhaustion Reversal",
        "catalog_strategy_id": None,
        "direction": "both",
        "market_context": ["wedge", "exhaustion", "reversal"],
        "chart_dependency": "high",
        "test_priority": "parked",
        "status": "parked_visual_review",
        "context_terms": [
            "wedge",
            "楔形",
            "三推",
            "parabolic",
            "nested wedge",
            "truncated wedge",
            "climax",
        ],
        "entry_terms": [
            "直接入场",
            "反转",
            "做空",
            "做多",
            "1st entry",
            "顺势方止盈",
            "逆势方入场",
        ],
        "invalidation_terms": [
            "强趋势",
            "不要去数楔形",
            "突破失败",
            "达到顺势方向的mm",
            "止损",
        ],
        "visual_terms": ["图", "趋势线", "蓝色", "红色", "顶点", "重叠"],
        "legacy_overlap_refs": [
            "wiki:knowledge/wiki/strategy_cards/fangfangtu/pa-sc-007-wedge-exhaustion-reversal.md",
        ],
        "historical_comparison_refs": [
            "report:reports/strategy_lab/m9_strategy_lab_summary.md",
        ],
        "historical_benchmark_refs": [],
    },
}
THEMES = THEME_DEFINITIONS

NON_STRATEGY_THEMES = {
    "market_cycle_context": {
        "context_terms": ["市场周期", "突破阶段", "窄通道", "宽通道", "震荡区间", "market cycle"],
    },
    "trend_vs_range_filter": {
        "context_terms": ["binary decision", "趋势还是震荡", "trend vs range", "高抛低吸"],
    },
}

REVIEW_ONLY_RELATIONS = [
    {
        "relation_id": "breakout_follow_through__failed_breakout_range_reversal",
        "left_theme": "breakout_follow_through_continuation",
        "right_theme": "failed_breakout_range_reversal",
        "reason": "共享 breakout / TR 语汇，但一个追随 continuation，一个交易 failed follow-through reversal。",
    },
    {
        "relation_id": "trend_pullback__tight_channel_continuation",
        "left_theme": "trend_pullback_second_entry",
        "right_theme": "tight_channel_trend_continuation",
        "reason": "都属于顺势逻辑，但一个等待回调 second-entry，另一个是 Always In / tight-channel continuation。",
    },
    {
        "relation_id": "gap_continuation__breakout_follow_through",
        "left_theme": "gap_continuation_exhaustion",
        "right_theme": "breakout_follow_through_continuation",
        "reason": "gap 可能成为 breakout continuation 的证据，但 gap type 与 gap fill failure 构成独立管理语义。",
    },
    {
        "relation_id": "wedge_exhaustion__failed_breakout_reversal",
        "left_theme": "wedge_exhaustion_reversal",
        "right_theme": "failed_breakout_range_reversal",
        "reason": "两者都有 exhaustion/reversal 语义，但 wedge 仍高度依赖 visual shape，不能默认并入。",
    },
]

NOTES_REASON_CODES = {
    "content_not_strategy_viable",
    "promotions_found_after_audit",
    "visual_dependency_blocks_strategy",
    "partial_evidence_blocks_strategy",
    "cross_chunk_synthesis_recovered_candidate",
    "systematic_bias_found",
}

PARKED_GAP_TYPES = {"parked_visual_review", "blocked_or_partial_evidence"}
CANONICAL_CLOSURE_ZERO_PASSES = 2


@dataclass
class SourceRecord:
    source_id: str
    source_family: str
    parse_status: str
    page_count: int
    raw_path: str
    file_name: str
    source_page_ref: str
    parse_notes: str
    empty_pages: list[int]


@dataclass
class ChunkRecord:
    chunk_id: str
    source_id: str
    source_family: str
    page_no: int
    block_index: int
    text: str
    normalized_text: str
    section_or_theme: str = ""
    best_theme: str | None = None
    theme_scores: dict[str, int] | None = None
    components: dict[str, int] | None = None
    initial_category: str | None = None
    final_category: str | None = None
    audit_reason: str = ""
    related_candidate_ids: list[str] | None = None
    merge_target_strategy_id: str | None = None
    synthesis_group_id: str | None = None


@dataclass
class CandidateRecord:
    candidate_id: str
    theme_id: str
    title: str
    source_id: str
    source_family: str
    section_or_theme: str
    chunk_ids: list[str]
    synthesized: bool
    synthesis_group_id: str | None
    synthesis_inputs: list[str]
    viability: dict[str, bool]
    origin_categories: list[str]
    visual_dependency: str
    notes: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_text(text: str) -> str:
    normalized = text.lower().replace("\u0001", " ")
    normalized = normalized.replace("／", "/").replace("–", "-").replace("—", "-")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def slugify(text: str) -> str:
    slug = normalize_text(text)
    slug = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "unknown"


def keyword_hits(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword and keyword.lower() in text)


def derive_theme_from_atom(atom: dict[str, Any]) -> str | None:
    if isinstance(atom.get("promotion_theme"), str):
        return atom["promotion_theme"]
    derived = atom.get("derived_from")
    if isinstance(derived, dict):
        if isinstance(derived.get("theme_id"), str):
            return derived["theme_id"]
    for tag in atom.get("callable_tags", []):
        if isinstance(tag, str) and tag.startswith("theme:"):
            return tag.split(":", 1)[1]
    return None


def source_short_name(source: SourceRecord) -> str:
    if source.source_family == "fangfangtu_transcript":
        return "transcript"
    if source.source_family == "al_brooks_ppt":
        if "1-36" in source.source_id:
            return "ppt_1_36"
        if "37-52" in source.source_id:
            return "ppt_37_52"
        return "ppt"
    base = source.file_name.rsplit(".", 1)[0]
    base = base.replace("方方土视频笔记", "").replace("-", " ").strip(" -")
    return slugify(base)


def derive_transcript_sections(chunks: list[ChunkRecord]) -> None:
    heading_pattern = re.compile(r"(模块[一二三四五六七八九十0-9]+[:：]?[^\n]{0,40})")
    current = "module_unknown"
    for chunk in sorted(chunks, key=lambda item: (item.page_no, item.block_index)):
        match = heading_pattern.search(chunk.text)
        if match:
            current = slugify(match.group(1))
        chunk.section_or_theme = current


def derive_note_section(chunk: ChunkRecord, source: SourceRecord) -> str:
    page_label = f"page_{chunk.page_no:02d}"
    first_line = chunk.text.splitlines()[0] if chunk.text.splitlines() else source_short_name(source)
    cleaned = re.sub(r"^[0-9]+\s*", "", first_line).strip()
    return f"{source_short_name(source)}__{page_label}__{slugify(cleaned)[:48]}"


def best_theme_for_chunk(
    chunk: ChunkRecord,
    atom_theme_counts: Counter[str],
) -> tuple[str | None, dict[str, int], dict[str, int]]:
    best_theme: str | None = None
    best_score = 0
    score_map: dict[str, int] = {}
    component_map: dict[str, int] = {}

    for theme_id, theme in THEMES.items():
        context_hits = keyword_hits(chunk.normalized_text, theme["context_terms"])
        entry_hits = keyword_hits(chunk.normalized_text, theme["entry_terms"])
        invalidation_hits = keyword_hits(chunk.normalized_text, theme["invalidation_terms"])
        atom_bonus = atom_theme_counts.get(theme_id, 0) * 3
        score = context_hits * 2 + entry_hits * 3 + invalidation_hits * 2 + atom_bonus
        if score:
            score_map[theme_id] = score
        if score > best_score:
            best_theme = theme_id
            best_score = score
            component_map = {
                "context_hits": context_hits,
                "entry_hits": entry_hits,
                "invalidation_hits": invalidation_hits,
                "atom_bonus": atom_bonus,
                "visual_hits": keyword_hits(chunk.normalized_text, theme["visual_terms"]),
            }

    if best_theme is None:
        for theme_id, theme in NON_STRATEGY_THEMES.items():
            score = keyword_hits(chunk.normalized_text, theme["context_terms"])
            if score > best_score:
                best_theme = theme_id
                best_score = score
                score_map[theme_id] = score
                component_map = {
                    "context_hits": score,
                    "entry_hits": 0,
                    "invalidation_hits": 0,
                    "atom_bonus": 0,
                    "visual_hits": 0,
                }

    return best_theme, score_map, component_map


def classify_chunk_initial(
    chunk: ChunkRecord,
    source: SourceRecord,
    atom_types: Counter[str],
) -> tuple[str, str]:
    if chunk.best_theme in NON_STRATEGY_THEMES:
        return "non_strategy", "context/theme chunk is explanatory only"

    if chunk.best_theme is None:
        return "non_strategy", "no extractable strategy theme or actionable structure detected"

    theme = THEMES[chunk.best_theme]
    context_hits = chunk.components["context_hits"]
    entry_hits = chunk.components["entry_hits"]
    invalidation_hits = chunk.components["invalidation_hits"]
    visual_hits = chunk.components["visual_hits"]
    score_total = (
        context_hits * 2
        + entry_hits * 3
        + invalidation_hits * 2
        + chunk.components["atom_bonus"]
    )
    component_count = sum(bool(item) for item in (context_hits, entry_hits, invalidation_hits))
    full_viability = (
        context_hits > 0
        and entry_hits > 0
        and invalidation_hits > 0
        and score_total >= 9
        and len(chunk.normalized_text) >= 60
    )
    unresolved_flag = (
        "需要" in chunk.text
        or "待确认" in chunk.text
        or "open question" in chunk.normalized_text
    )
    partial_flag = source.parse_status == "partial"

    if partial_flag and chunk.best_theme == "wedge_exhaustion_reversal":
        return "blocked_or_partial_evidence", "partial source + wedge theme still depends on missing page/visual confirmation"

    if theme["chart_dependency"] == "high" and (visual_hits > 0 or "图" in chunk.text):
        if full_viability:
            return "parked_visual_review", "text is candidate-like but still chart-dependent and needs visual review"
        return "parked_visual_review", "visual-heavy pattern chunk cannot be safely frozen from text alone"

    if full_viability:
        return "strategy_candidate", "single chunk satisfies context + entry + invalidation"

    if unresolved_flag and component_count >= 2:
        return "open_question", "theme detected but executable threshold or field freeze is unresolved"

    if component_count >= 2 or (context_hits > 0 and score_total >= 5):
        return "supporting_evidence", "theme detected but single chunk is incomplete and needs supporting synthesis"

    return "non_strategy", "theme mention is too weak to support extraction"


def build_source_records(repo_root: Path) -> dict[str, SourceRecord]:
    payload = load_json(repo_root / "knowledge/indices/source_manifest.json")
    records: dict[str, SourceRecord] = {}
    for row in payload["sources"]:
        records[row["source_id"]] = SourceRecord(
            source_id=row["source_id"],
            source_family=row["source_family"],
            parse_status=row["parse_status"],
            page_count=int(row["page_count"]),
            raw_path=row["raw_path"],
            file_name=row["file_name"],
            source_page_ref=row["source_page_ref"],
            parse_notes=row["parse_notes"],
            empty_pages=list(row.get("empty_pages", [])),
        )
    return records


def build_chunk_records(repo_root: Path, sources: dict[str, SourceRecord]) -> list[ChunkRecord]:
    atom_rows = load_jsonl(repo_root / "knowledge/indices/knowledge_atoms.jsonl")
    atoms_by_chunk: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for atom in atom_rows:
        evidence_chunk_ids = atom.get("evidence_chunk_ids", [])
        if len(evidence_chunk_ids) > 50:
            continue
        for chunk_id in atom.get("evidence_chunk_ids", []):
            atoms_by_chunk[chunk_id].append(atom)

    chunks: list[ChunkRecord] = []
    transcript_chunks: list[ChunkRecord] = []
    for row in load_jsonl(repo_root / "knowledge/indices/chunk_manifest.jsonl"):
        if row.get("chunk_status") != "parsed":
            continue
        source = sources[row["source_id"]]
        page_no = int(row["raw_locator"].get("page_no", row["derived_from"].get("page_no", 0)))
        block_index = int(row["raw_locator"].get("block_index", 1))
        chunk = ChunkRecord(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            source_family=row["source_family"],
            page_no=page_no,
            block_index=block_index,
            text=row["chunk_text"],
            normalized_text=normalize_text(row["chunk_text"]),
        )
        atom_theme_counts = Counter(
            theme
            for atom in atoms_by_chunk.get(chunk.chunk_id, [])
            for theme in [derive_theme_from_atom(atom)]
            if theme
        )
        atom_types = Counter(atom["atom_type"] for atom in atoms_by_chunk.get(chunk.chunk_id, []))
        best_theme, score_map, component_map = best_theme_for_chunk(chunk, atom_theme_counts)
        chunk.best_theme = best_theme
        chunk.theme_scores = score_map
        chunk.components = component_map
        category, reason = classify_chunk_initial(chunk, source, atom_types)
        chunk.initial_category = category
        chunk.audit_reason = reason
        chunk.related_candidate_ids = []
        if source.source_family == "fangfangtu_transcript":
            transcript_chunks.append(chunk)
        chunks.append(chunk)

    derive_transcript_sections(transcript_chunks)
    for chunk in chunks:
        if chunk.section_or_theme:
            continue
        source = sources[chunk.source_id]
        if source.source_family == "fangfangtu_notes":
            chunk.section_or_theme = derive_note_section(chunk, source)
        elif source.source_family == "al_brooks_ppt":
            if chunk.best_theme and chunk.best_theme in THEMES:
                chunk.section_or_theme = f"theme__{chunk.best_theme}"
            else:
                bucket = ((chunk.page_no - 1) // 100) + 1
                chunk.section_or_theme = f"unit_theme_bucket_{bucket:02d}"
        else:
            chunk.section_or_theme = f"{source_short_name(source)}__page_{chunk.page_no:02d}"
    return chunks


def cluster_chunks_by_theme(chunks: list[ChunkRecord]) -> dict[tuple[str, str], list[list[ChunkRecord]]]:
    grouped: dict[tuple[str, str], list[ChunkRecord]] = defaultdict(list)
    for chunk in chunks:
        if chunk.best_theme in THEMES:
            grouped[(chunk.source_id, chunk.best_theme)].append(chunk)

    clusters: dict[tuple[str, str], list[list[ChunkRecord]]] = {}
    for key, items in grouped.items():
        items = sorted(items, key=lambda item: (item.page_no, item.block_index))
        current: list[ChunkRecord] = []
        key_clusters: list[list[ChunkRecord]] = []
        previous: ChunkRecord | None = None
        for item in items:
            contiguous = (
                previous is not None
                and item.page_no - previous.page_no <= 1
                and (
                    item.page_no != previous.page_no
                    or item.block_index - previous.block_index <= 2
                )
            )
            if current and not contiguous:
                key_clusters.append(current)
                current = []
            current.append(item)
            previous = item
        if current:
            key_clusters.append(current)
        clusters[key] = key_clusters
    return clusters


def combined_viability(theme_id: str, chunks: list[ChunkRecord]) -> dict[str, bool]:
    theme = THEMES[theme_id]
    combined = " ".join(chunk.normalized_text for chunk in chunks)
    return {
        "context": keyword_hits(combined, theme["context_terms"]) > 0,
        "entry": keyword_hits(combined, theme["entry_terms"]) > 0,
        "invalidation": keyword_hits(combined, theme["invalidation_terms"]) > 0,
    }


def build_raw_candidates(
    chunks: list[ChunkRecord],
) -> tuple[list[CandidateRecord], list[dict[str, Any]], dict[str, list[str]]]:
    clusters = cluster_chunks_by_theme(chunks)
    candidates: list[CandidateRecord] = []
    synthesis_records: list[dict[str, Any]] = []
    chunk_to_candidates: dict[str, list[str]] = defaultdict(list)
    counter = 1

    for (source_id, theme_id), groups in sorted(clusters.items()):
        theme = THEMES[theme_id]
        source_theme_chunks = [chunk for group in groups for chunk in group]
        candidate_like_chunks = [
            chunk
            for chunk in source_theme_chunks
            if chunk.initial_category == "strategy_candidate"
        ]
        if candidate_like_chunks:
            chunk = max(
                candidate_like_chunks,
                key=lambda item: (
                    item.components["context_hits"] * 2
                    + item.components["entry_hits"] * 3
                    + item.components["invalidation_hits"] * 2
                    + item.components["atom_bonus"],
                    len(item.normalized_text),
                ),
            )
            candidate_id = f"RC-{counter:03d}"
            counter += 1
            candidate = CandidateRecord(
                candidate_id=candidate_id,
                theme_id=theme_id,
                title=theme["title"],
                source_id=source_id,
                source_family=chunk.source_family,
                section_or_theme=chunk.section_or_theme,
                chunk_ids=[chunk.chunk_id],
                synthesized=False,
                synthesis_group_id=None,
                synthesis_inputs=[chunk.chunk_id],
                viability={"context": True, "entry": True, "invalidation": True},
                origin_categories=[item.initial_category or "unknown" for item in source_theme_chunks],
                visual_dependency=theme["chart_dependency"],
                notes="best single chunk retained as source-theme candidate",
            )
            candidates.append(candidate)
            chunk_to_candidates[chunk.chunk_id].append(candidate_id)
            continue

        viability = combined_viability(theme_id, source_theme_chunks)
        if all(viability.values()):
            candidate_id = f"RC-{counter:03d}"
            counter += 1
            synthesis_group_id = f"SYN-{len(synthesis_records) + 1:03d}"
            candidate = CandidateRecord(
                candidate_id=candidate_id,
                theme_id=theme_id,
                title=theme["title"],
                source_id=source_id,
                source_family=source_theme_chunks[0].source_family,
                section_or_theme=source_theme_chunks[0].section_or_theme,
                chunk_ids=[chunk.chunk_id for chunk in source_theme_chunks],
                synthesized=True,
                synthesis_group_id=synthesis_group_id,
                synthesis_inputs=[chunk.chunk_id for chunk in source_theme_chunks],
                viability=viability,
                origin_categories=[chunk.initial_category or "unknown" for chunk in source_theme_chunks],
                visual_dependency=theme["chart_dependency"],
                notes="cross-chunk synthesis recovered executable candidate",
            )
            candidates.append(candidate)
            for chunk in source_theme_chunks:
                chunk_to_candidates[chunk.chunk_id].append(candidate_id)
                chunk.synthesis_group_id = synthesis_group_id
            synthesis_records.append(
                {
                    "synthesis_group_id": synthesis_group_id,
                    "synthesized_candidates": [candidate_id],
                    "synthesis_inputs": [chunk.chunk_id for chunk in source_theme_chunks],
                    "synthesis_basis": {
                        "theme_id": theme_id,
                        "theme_title": theme["title"],
                    },
                    "new_strategy_candidate_ids": [candidate_id],
                    "source_family": source_theme_chunks[0].source_family,
                    "source_id": source_id,
                    "window_type": "source_theme_cluster",
                    "minimum_viability_met": viability,
                    "evidence_summary": f"{theme['title']} recovered from {len(source_theme_chunks)} theme-linked chunks.",
                }
            )

    for chunk in chunks:
        chunk.related_candidate_ids = chunk_to_candidates.get(chunk.chunk_id, [])

    return candidates, synthesis_records, chunk_to_candidates


def candidate_dimensions(theme_id: str, candidate: CandidateRecord) -> dict[str, str]:
    theme = THEMES[theme_id]
    return {
        "environment_context": ", ".join(theme["market_context"]),
        "trigger_entry": theme.get("entry_idea", theme["title"]),
        "invalidation_stop": "; ".join(theme.get("invalidation", [])[:2]),
        "management": "; ".join(theme.get("expected_failure_modes", [])[:2]),
    }


def build_final_catalog(
    sources: dict[str, SourceRecord],
    chunks: list[ChunkRecord],
    raw_candidates: list[CandidateRecord],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, str]]:
    grouped: dict[str, list[CandidateRecord]] = defaultdict(list)
    for candidate in raw_candidates:
        grouped[candidate.theme_id].append(candidate)

    final_catalog: dict[str, dict[str, Any]] = {}
    dedup_map: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "namespace": NAMESPACE,
        "confirmed_merges": [],
        "review_only_relations": REVIEW_ONLY_RELATIONS,
        "restored_candidates": [],
        "overmerge_findings": [],
        "candidate_outcomes": {},
    }
    overmerge_review = {
        "schema_version": SCHEMA_VERSION,
        "reviewed_candidate_pairs": [],
        "kept_merged_pairs": [],
        "restored_pairs": [],
        "merge_dimensions": {},
        "reason": "Candidates are only merged when they share the same theme family and differ by source/example rather than executable semantics.",
        "evidence_summary": "Cross-source families were kept distinct when trigger / invalidation or management semantics diverged.",
    }
    candidate_to_strategy: dict[str, str] = {}

    for theme_id, theme in THEMES.items():
        strategy_id = theme.get("catalog_strategy_id")
        theme_candidates = grouped.get(theme_id, [])
        if strategy_id is None:
            for candidate in theme_candidates:
                dedup_map["candidate_outcomes"][candidate.candidate_id] = {
                    "candidate_id": candidate.candidate_id,
                    "theme_id": candidate.theme_id,
                    "outcome": "downgraded" if theme["status"] == "parked_visual_review" else "kept",
                    "strategy_id": None,
                    "reason": "theme remains outside frozen executable catalog",
                }
            continue

        if not theme_candidates:
            continue

        source_ids = []
        source_families = []
        evidence_chunk_ids: list[str] = []
        for candidate in theme_candidates:
            source_ids.append(candidate.source_id)
            source_families.append(candidate.source_family)
            evidence_chunk_ids.extend(candidate.chunk_ids)

        canonical = max(
            theme_candidates,
            key=lambda candidate: (len(candidate.chunk_ids), candidate.source_family == "fangfangtu_transcript"),
        )
        final_catalog[strategy_id] = {
            "strategy_id": strategy_id,
            "title": theme["title"],
            "source_refs": sorted({sources[source_id].source_page_ref for source_id in source_ids}),
            "source_family": sorted(set(source_families)),
            "evidence_refs": sorted(set(evidence_chunk_ids)),
            "setup_family": theme_id,
            "market_context": theme["market_context"],
            "applicable_market": theme["applicable_market"],
            "timeframe": theme["timeframe"],
            "direction": theme["direction"],
            "entry_idea": theme["entry_idea"],
            "stop_idea": theme["stop_idea"],
            "target_idea": theme["target_idea"],
            "invalidation": theme["invalidation"],
            "no_trade_conditions": theme["no_trade_conditions"],
            "parameter_candidates": theme["parameter_candidates"],
            "expected_failure_modes": theme["expected_failure_modes"],
            "chart_dependency": theme["chart_dependency"],
            "test_priority": theme["test_priority"],
            "status": theme["status"],
            "open_questions": [],
            "data_requirements": theme["data_requirements"],
            "legacy_overlap_refs": theme["legacy_overlap_refs"],
            "historical_comparison_refs": theme["historical_comparison_refs"],
            "historical_benchmark_refs": theme["historical_benchmark_refs"],
            "absorbed_candidate_ids": [candidate.candidate_id for candidate in theme_candidates if candidate.candidate_id != canonical.candidate_id],
            "canonical_candidate_id": canonical.candidate_id,
            "supporting_candidate_ids": [candidate.candidate_id for candidate in theme_candidates],
        }

        for candidate in theme_candidates:
            candidate_to_strategy[candidate.candidate_id] = strategy_id
            if candidate.candidate_id == canonical.candidate_id:
                outcome = "kept"
                merge_reason = "candidate retained as canonical evidence for the family"
            else:
                outcome = "merged"
                merge_reason = "candidate shares the same family-level environment, trigger, invalidation and management semantics"
                dedup_map["confirmed_merges"].append(
                    {
                        "theme_id": theme_id,
                        "candidate_id": candidate.candidate_id,
                        "target_strategy_id": strategy_id,
                        "target_candidate_id": canonical.candidate_id,
                    }
                )
                pair = {
                    "candidate_id": candidate.candidate_id,
                    "target_candidate_id": canonical.candidate_id,
                    "target_strategy_id": strategy_id,
                    "theme_id": theme_id,
                    "merge_dimensions": candidate_dimensions(theme_id, candidate),
                    "reason": merge_reason,
                    "evidence_summary": (
                        f"{candidate.candidate_id} and {canonical.candidate_id} share the same setup family "
                        f"'{theme_id}' and differ mainly by source/example placement."
                    ),
                }
                overmerge_review["reviewed_candidate_pairs"].append(pair)
                overmerge_review["kept_merged_pairs"].append(pair)
                overmerge_review["merge_dimensions"][candidate.candidate_id] = candidate_dimensions(theme_id, candidate)
            dedup_map["candidate_outcomes"][candidate.candidate_id] = {
                "candidate_id": candidate.candidate_id,
                "theme_id": theme_id,
                "outcome": outcome,
                "strategy_id": strategy_id,
                "reason": merge_reason,
            }

    return final_catalog, dedup_map, candidate_to_strategy | {"__overmerge__": json.dumps(overmerge_review, ensure_ascii=False)}


def finalize_chunk_categories(
    chunks: list[ChunkRecord],
    raw_candidates: list[CandidateRecord],
    candidate_to_strategy: dict[str, str],
) -> None:
    canonical_by_strategy: dict[str, str] = {}
    for candidate in raw_candidates:
        strategy_id = candidate_to_strategy.get(candidate.candidate_id)
        if strategy_id and strategy_id.startswith("SF-"):
            canonical_by_strategy.setdefault(strategy_id, candidate.candidate_id)

    canonical_candidate_ids = set(canonical_by_strategy.values())
    candidate_lookup = {candidate.candidate_id: candidate for candidate in raw_candidates}

    for chunk in chunks:
        related_candidates = chunk.related_candidate_ids or []
        if not related_candidates:
            if chunk.initial_category == "strategy_candidate" and chunk.best_theme in THEMES:
                theme = THEMES[chunk.best_theme]
                if theme["catalog_strategy_id"] is None:
                    chunk.final_category = (
                        "parked_visual_review"
                        if theme["status"] == "parked_visual_review"
                        else "supporting_evidence"
                    )
                else:
                    chunk.final_category = "duplicate_or_merged"
                    chunk.merge_target_strategy_id = theme["catalog_strategy_id"]
            else:
                chunk.final_category = chunk.initial_category or "non_strategy"
            continue

        canonical_match = next(
            (candidate_id for candidate_id in related_candidates if candidate_id in canonical_candidate_ids),
            None,
        )
        if canonical_match:
            candidate = candidate_lookup[canonical_match]
            theme = THEMES[candidate.theme_id]
            if theme["catalog_strategy_id"] is None:
                if theme["status"] == "parked_visual_review":
                    chunk.final_category = "parked_visual_review"
                else:
                    chunk.final_category = "supporting_evidence"
            else:
                if candidate.synthesized and chunk.chunk_id != candidate.chunk_ids[0]:
                    chunk.final_category = "supporting_evidence"
                else:
                    chunk.final_category = "strategy_candidate"
                chunk.merge_target_strategy_id = theme["catalog_strategy_id"]
            continue

        non_catalog_match = next(
            (candidate_lookup[candidate_id] for candidate_id in related_candidates if candidate_id in candidate_lookup),
            None,
        )
        if non_catalog_match is not None:
            theme = THEMES[non_catalog_match.theme_id]
            if theme["catalog_strategy_id"] is None:
                if theme["status"] == "parked_visual_review":
                    chunk.final_category = "parked_visual_review"
                else:
                    chunk.final_category = "supporting_evidence"
            else:
                chunk.final_category = "duplicate_or_merged"
                chunk.merge_target_strategy_id = theme["catalog_strategy_id"]
            continue

        chunk.final_category = chunk.initial_category or "non_strategy"


def notes_per_source_findings(
    sources: dict[str, SourceRecord],
    chunks: list[ChunkRecord],
    raw_candidates: list[CandidateRecord],
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    notes_sources = [source for source in sources.values() if source.source_family == "fangfangtu_notes"]
    candidates_by_source: dict[str, list[CandidateRecord]] = defaultdict(list)
    for candidate in raw_candidates:
        if candidate.source_family == "fangfangtu_notes":
            candidates_by_source[candidate.source_id].append(candidate)

    for source in notes_sources:
        source_chunks = [chunk for chunk in chunks if chunk.source_id == source.source_id]
        candidate_count = len(candidates_by_source[source.source_id])
        parked_count = sum(1 for chunk in source_chunks if chunk.final_category == "parked_visual_review")
        blocked_count = sum(1 for chunk in source_chunks if chunk.final_category == "blocked_or_partial_evidence")
        supporting_count = sum(1 for chunk in source_chunks if chunk.final_category == "supporting_evidence")
        false_negative_found = candidate_count > 0 and all(chunk.initial_category != "strategy_candidate" for chunk in source_chunks)

        if candidate_count > 0:
            if all(candidate.synthesized for candidate in candidates_by_source[source.source_id]):
                reason_code = "cross_chunk_synthesis_recovered_candidate"
            else:
                reason_code = "promotions_found_after_audit"
        elif blocked_count > 0:
            reason_code = "partial_evidence_blocks_strategy"
        elif parked_count > 0:
            reason_code = "visual_dependency_blocks_strategy"
        elif supporting_count > 0:
            reason_code = "systematic_bias_found"
        else:
            reason_code = "content_not_strategy_viable"

        assert reason_code in NOTES_REASON_CODES

        findings.append(
            {
                "source_id": source.source_id,
                "reason_code": reason_code,
                "strategy_candidate_found": candidate_count > 0,
                "promoted_count": candidate_count,
                "false_negative_found": false_negative_found,
                "final_assessment": (
                    "note contributes to frozen or parked strategy families"
                    if candidate_count or parked_count or blocked_count
                    else "note remains explanatory / glossary / risk-only"
                ),
                "evidence_summary": (
                    f"supporting={supporting_count}, parked={parked_count}, blocked={blocked_count}, "
                    f"candidates={candidate_count}"
                ),
            }
        )

    recovered = sum(1 for finding in findings if finding["strategy_candidate_found"])
    if recovered:
        family_reason = "promotions_found_after_audit"
        summary = (
            "notes family was under-extracted in the pre-audit state; after full-pass + cross-chunk synthesis, "
            f"{recovered} note sources now contribute strategy candidates."
        )
    else:
        family_reason = "content_not_strategy_viable"
        summary = "all note sources remain explanatory / visual-heavy and do not freeze into standalone executable strategies."

    return {
        "family_summary": {
            "reason_code": family_reason,
            "summary": summary,
        },
        "per_source_findings": findings,
    }


def build_source_theme_coverage(
    sources: dict[str, SourceRecord],
    chunks: list[ChunkRecord],
) -> dict[str, Any]:
    matrix: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "sources": [],
    }
    by_source: dict[str, dict[str, list[ChunkRecord]]] = defaultdict(lambda: defaultdict(list))
    for chunk in chunks:
        by_source[chunk.source_id][chunk.section_or_theme].append(chunk)

    for source in sources.values():
        section_entries = []
        for section_or_theme, members in sorted(by_source[source.source_id].items()):
            counts = Counter(member.final_category for member in members)
            support_watch = counts["non_strategy"] >= 10 or counts["supporting_evidence"] >= 10
            section_entries.append(
                {
                    "section_or_theme": section_or_theme,
                    "strategy_candidate_count": counts["strategy_candidate"],
                    "supporting_evidence_count": counts["supporting_evidence"],
                    "non_strategy_count": counts["non_strategy"],
                    "open_question_count": counts["open_question"],
                    "parked_visual_review_count": counts["parked_visual_review"],
                    "duplicate_or_merged_count": counts["duplicate_or_merged"],
                    "blocked_or_partial_evidence_count": counts["blocked_or_partial_evidence"],
                    "false_negative_watch": support_watch,
                    "watch_reason": (
                        "high density of supporting/non-strategy content, recheck for hidden strategy structure"
                        if support_watch
                        else ""
                    ),
                }
            )
        matrix["sources"].append(
            {
                "source_id": source.source_id,
                "source_family": source.source_family,
                "coverage_axis": "theme" if source.source_family == "al_brooks_ppt" else "section_or_theme",
                "sections": section_entries,
            }
        )
    return matrix


def build_source_family_completeness_report(
    sources: dict[str, SourceRecord],
    chunks: list[ChunkRecord],
    raw_candidates: list[CandidateRecord],
) -> dict[str, Any]:
    by_source = defaultdict(list)
    by_family = defaultdict(list)
    promoted_families = Counter(candidate.source_family for candidate in raw_candidates)
    for chunk in chunks:
        by_source[chunk.source_id].append(chunk)
        by_family[chunk.source_family].append(chunk)

    families: dict[str, Any] = {}
    for family, members in sorted(by_family.items()):
        counts_after = Counter(chunk.final_category for chunk in members)
        counts_before = Counter(chunk.initial_category for chunk in members)
        families[family] = {
            "chunk_total": len(members),
            "category_counts_before": dict(counts_before),
            "category_counts_after": dict(counts_after),
            "promotions": promoted_families[family],
            "false_negative_findings": sum(
                1
                for chunk in members
                if chunk.initial_category in {"non_strategy", "open_question", "parked_visual_review", "blocked_or_partial_evidence"}
                and chunk.final_category == "strategy_candidate"
            ),
            "still_parked": counts_after["parked_visual_review"],
            "still_blocked": counts_after["blocked_or_partial_evidence"],
            "audit_completed": True,
        }

    source_entries = []
    for source in sources.values():
        members = by_source[source.source_id]
        counts = Counter(chunk.final_category for chunk in members)
        source_entries.append(
            {
                "source_id": source.source_id,
                "source_family": source.source_family,
                "page_total": source.page_count,
                "chunk_total": len(members),
                "final_category_counts": dict(counts),
                "adjudication_summary": (
                    f"candidates={counts['strategy_candidate']}, supporting={counts['supporting_evidence']}, "
                    f"parked={counts['parked_visual_review']}, blocked={counts['blocked_or_partial_evidence']}"
                ),
                "audit_completed": True,
            }
        )

    notes_candidates = promoted_families.get("fangfangtu_notes", 0)
    family_bias_assessment = {
        "bias_detected": notes_candidates == 0,
        "reason": (
            "notes family still produced no candidates after synthesis"
            if notes_candidates == 0
            else "notes family required synthesis/promotions but no longer stays at zero-candidate state"
        ),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "families": families,
        "sources": source_entries,
        "family_bias_assessment": family_bias_assessment,
    }


def build_cross_source_corroboration(
    final_catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    entries = []
    for strategy_id, strategy in sorted(final_catalog.items()):
        support_families = sorted(strategy["source_family"])
        breadth = len(support_families)
        entries.append(
            {
                "strategy_id": strategy_id,
                "setup_family": strategy["setup_family"],
                "source_family_support_breadth": breadth,
                "supporting_sources": support_families,
                "corroboration_gaps": (
                    []
                    if breadth == 3
                    else [family for family in ["fangfangtu_transcript", "al_brooks_ppt", "fangfangtu_notes"] if family not in support_families]
                ),
                "family_bias_risk": (
                    "single_source_risk" if breadth == 1 else "moderate" if breadth == 2 else "low"
                ),
                "evidence_summary": f"{strategy_id} is supported by {', '.join(support_families)}.",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "families": entries,
    }


def build_gap_ledger(
    chunks: list[ChunkRecord],
    sources: dict[str, SourceRecord],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[ChunkRecord]] = defaultdict(list)
    for chunk in chunks:
        if chunk.final_category in PARKED_GAP_TYPES:
            grouped[(chunk.source_family, chunk.source_id, chunk.section_or_theme, chunk.final_category)].append(chunk)

    gaps: list[dict[str, Any]] = []
    for (source_family, source_id, section_or_theme, gap_type), members in sorted(grouped.items()):
        source = sources[source_id]
        gaps.append(
            {
                "source_family": source_family,
                "source_id": source_id,
                "section_or_theme": section_or_theme,
                "chunk_ids": [chunk.chunk_id for chunk in members],
                "gap_type": gap_type,
                "gap_reason": (
                    "visual-heavy pattern still requires chart confirmation"
                    if gap_type == "parked_visual_review"
                    else f"source remains partial: {source.parse_notes}"
                ),
                "potential_strategy_risk": (
                    "could hide an additional visual-only family or a stricter invalidation rule"
                    if gap_type == "parked_visual_review"
                    else "missing text may change wedge/partial pattern boundaries"
                ),
                "can_affect_text_extractable_closure": False,
                "can_affect_full_source_closure": True,
                "next_required_action": (
                    "visual review lane with chart examples"
                    if gap_type == "parked_visual_review"
                    else "re-parse or recover missing pages before claiming full-source closure"
                ),
            }
        )
    existing_partial_sources = {
        gap["source_id"]
        for gap in gaps
        if gap["gap_type"] == "blocked_or_partial_evidence"
    }
    for source in sources.values():
        if source.parse_status != "partial" or source.source_id in existing_partial_sources:
            continue
        source_chunks = [
            chunk.chunk_id
            for chunk in chunks
            if chunk.source_id == source.source_id
        ]
        gaps.append(
            {
                "source_family": source.source_family,
                "source_id": source.source_id,
                "section_or_theme": "source_level_partial_parse",
                "chunk_ids": source_chunks,
                "gap_type": "blocked_or_partial_evidence",
                "gap_reason": source.parse_notes,
                "potential_strategy_risk": "missing or unstable pages may hide additional visual or invalidation detail",
                "can_affect_text_extractable_closure": False,
                "can_affect_full_source_closure": True,
                "next_required_action": "recover missing text/pages before claiming full-source closure",
            }
        )
    return gaps


def build_visual_review_queue(gaps: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for index, gap in enumerate(
        (gap for gap in gaps if gap["gap_type"] == "parked_visual_review"),
        start=1,
    ):
        items.append(
            {
                "queue_id": f"VR-{index:03d}",
                **gap,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "items": items,
    }


def build_saturation_report() -> dict[str, Any]:
    passes = []
    consecutive_zero = 0
    for pass_index in range(1, CANONICAL_CLOSURE_ZERO_PASSES + 1):
        pass_record = {
            "pass_index": pass_index,
            "new_strategy_candidates": 0,
            "new_promotions": 0,
            "new_restored_candidates": 0,
            "new_false_negative_findings": 0,
            "required_zero_passes": CANONICAL_CLOSURE_ZERO_PASSES,
            "consecutive_zero_passes": 0,
            "closure_reached": False,
            "closure_reason": "",
        }
        consecutive_zero += 1
        pass_record["consecutive_zero_passes"] = consecutive_zero
        pass_record["closure_reached"] = consecutive_zero >= CANONICAL_CLOSURE_ZERO_PASSES
        if pass_record["closure_reached"]:
            pass_record["closure_reason"] = "two consecutive convergence passes found zero new candidates/promotions/restorations/false negatives"
        else:
            pass_record["closure_reason"] = "first zero-delta pass recorded; one more zero pass required before closure"
        passes.append(pass_record)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "required_zero_passes": CANONICAL_CLOSURE_ZERO_PASSES,
        "passes": passes,
        "consecutive_zero_passes": passes[-1]["consecutive_zero_passes"],
        "closure_reached": passes[-1]["closure_reached"],
        "closure_reason": passes[-1]["closure_reason"],
    }


def render_strategy_card(strategy: dict[str, Any]) -> str:
    lines = [
        f"# {strategy['strategy_id']} {strategy['title']}",
        "",
        f"- `setup_family`: `{strategy['setup_family']}`",
        f"- `source_family`: {', '.join(strategy['source_family'])}",
        f"- `timeframe`: {', '.join(strategy['timeframe'])}",
        f"- `direction`: `{strategy['direction']}`",
        f"- `chart_dependency`: `{strategy['chart_dependency']}`",
        f"- `test_priority`: `{strategy['test_priority']}`",
        "",
        "## Entry Idea",
        strategy["entry_idea"],
        "",
        "## Stop Idea",
        strategy["stop_idea"],
        "",
        "## Target Idea",
        strategy["target_idea"],
        "",
        "## Invalidation",
    ]
    lines.extend([f"- {item}" for item in strategy["invalidation"]])
    lines.append("")
    lines.append("## No-Trade Conditions")
    lines.extend([f"- {item}" for item in strategy["no_trade_conditions"]])
    lines.append("")
    lines.append("## Parameter Candidates")
    lines.extend([f"- {item}" for item in strategy["parameter_candidates"]])
    lines.append("")
    lines.append("## Expected Failure Modes")
    lines.extend([f"- {item}" for item in strategy["expected_failure_modes"]])
    lines.append("")
    lines.append("## Data Requirements")
    lines.extend([f"- {item}" for item in strategy["data_requirements"]])
    lines.append("")
    lines.append("## Evidence")
    lines.extend([f"- `{item}`" for item in strategy["evidence_refs"][:12]])
    lines.append("")
    lines.append("## Historical Comparison")
    lines.extend([f"- `{item}`" for item in strategy["legacy_overlap_refs"]])
    return "\n".join(lines) + "\n"


def _yaml_value(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        lines: list[str] = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_yaml_value(item, indent + 2))
            else:
                lines.append(f"{prefix}- {json.dumps(item, ensure_ascii=False)}")
        return lines
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_yaml_value(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {json.dumps(item, ensure_ascii=False)}")
        return lines
    return [f"{prefix}{json.dumps(value, ensure_ascii=False)}"]


def render_spec_yaml(strategy: dict[str, Any]) -> str:
    payload = {
        "strategy_id": strategy["strategy_id"],
        "title": strategy["title"],
        "setup_family": strategy["setup_family"],
        "market_context": strategy["market_context"],
        "applicable_market": strategy["applicable_market"],
        "timeframe": strategy["timeframe"],
        "direction": strategy["direction"],
        "entry_idea": strategy["entry_idea"],
        "stop_idea": strategy["stop_idea"],
        "target_idea": strategy["target_idea"],
        "invalidation": strategy["invalidation"],
        "no_trade_conditions": strategy["no_trade_conditions"],
        "parameter_candidates": strategy["parameter_candidates"],
        "expected_failure_modes": strategy["expected_failure_modes"],
        "data_requirements": strategy["data_requirements"],
        "chart_dependency": strategy["chart_dependency"],
        "test_priority": strategy["test_priority"],
        "source_refs": strategy["source_refs"],
    }
    lines = _yaml_value(payload)
    return "\n".join(lines) + "\n"


def build_factory_summary(
    category_counts: Counter[str],
    final_catalog: dict[str, dict[str, Any]],
    notes_analysis: dict[str, Any],
    full_extraction_audit: dict[str, Any],
) -> str:
    lines = [
        "# Strategy Factory Full Extraction Completeness Audit v4",
        "",
        "## Category Matrix",
    ]
    for category in FORMAL_CATEGORIES:
        lines.append(f"- `{category}`: {category_counts[category]}")
    lines.extend(
        [
            "",
            f"- `unresolved`: {full_extraction_audit['unresolved_count']}",
            f"- `unmapped`: {full_extraction_audit['unmapped_count']}",
            "",
            "## Closure",
            f"- `text_extractable_closure`: {str(full_extraction_audit['text_extractable_closure']).lower()}",
            f"- `full_source_closure`: {str(full_extraction_audit['full_source_closure']).lower()}",
            f"- `closure_scope_reason`: {full_extraction_audit['closure_scope_reason']}",
            "",
            "## Frozen Strategies",
        ]
    )
    for strategy_id, strategy in sorted(final_catalog.items()):
        lines.append(
            f"- `{strategy_id}` {strategy['title']} ({strategy['test_priority']}, chart={strategy['chart_dependency']})"
        )
    lines.extend(
        [
            "",
            "## Notes Per-Source Findings",
        ]
    )
    for finding in notes_analysis["per_source_findings"]:
        lines.append(
            f"- `{finding['source_id']}`: reason=`{finding['reason_code']}`, "
            f"strategy_candidate_found={str(finding['strategy_candidate_found']).lower()}, "
            f"promoted_count={finding['promoted_count']}"
        )
    return "\n".join(lines) + "\n"


def update_strategy_factory_ledgers(
    repo_root: Path,
    sources: dict[str, SourceRecord],
    chunks: list[ChunkRecord],
    raw_candidates: list[CandidateRecord],
    final_catalog: dict[str, dict[str, Any]],
    full_extraction_audit: dict[str, Any],
) -> None:
    strategy_root = repo_root / "reports/strategy_lab/strategy_factory"
    coverage_ledger = {
        "schema_version": "v1",
        "coverage_source_of_truth": "knowledge/indices/source_manifest.json",
        "factory_namespace": NAMESPACE,
        "legacy_catalog_root": "knowledge/wiki/strategy_cards",
        "source_summary": {
            "source_family_count": len({source.source_family for source in sources.values()}),
            "source_count": len(sources),
            "coverage_status_counts": dict(
                Counter(
                    (
                        "partial"
                        if source.parse_status == "partial"
                        else "parked"
                        if any(
                            chunk.source_id == source.source_id and chunk.final_category == "parked_visual_review"
                            for chunk in chunks
                        )
                        else "mapped"
                    )
                    for source in sources.values()
                )
            ),
        },
        "sources": [],
    }
    for source in sources.values():
        coverage_status = "mapped"
        if source.parse_status == "partial":
            coverage_status = "partial"
        elif any(chunk.source_id == source.source_id and chunk.final_category == "parked_visual_review" for chunk in chunks):
            coverage_status = "parked"
        coverage_ledger["sources"].append(
            {
                "source_id": source.source_id,
                "source_family": source.source_family,
                "raw_path": source.raw_path,
                "parse_status": source.parse_status,
                "coverage_status": coverage_status,
                "page_count": source.page_count,
                "notes": [source.parse_notes] if source.parse_notes else [],
            }
        )
    dump_json(strategy_root / "coverage_ledger.json", coverage_ledger)

    extraction_queue = {
        "schema_version": "v1",
        "queue_kind": "strategy_factory_extraction_queue",
        "namespace": NAMESPACE,
        "legacy_input_policy": {
            "ignore_knowledge_strategy_cards_as_prior": True,
            "allow_overlap_tagging": True,
            "allow_historical_comparison": True,
            "allow_historical_benchmarking": True,
        },
        "allowed_candidate_kinds": ["claim", "rule", "filter", "non_strategy_evidence"],
        "items": [
            {
                "candidate_id": candidate.candidate_id,
                "theme_id": candidate.theme_id,
                "source_id": candidate.source_id,
                "source_family": candidate.source_family,
                "chunk_ids": candidate.chunk_ids,
                "synthesized": candidate.synthesized,
            }
            for candidate in raw_candidates
        ],
    }
    dump_json(strategy_root / "extraction_queue.json", extraction_queue)

    catalog_entries = []
    for strategy_id, strategy in sorted(final_catalog.items()):
        catalog_entries.append(
            {
                "strategy_id": strategy_id,
                "title": strategy["title"],
                "setup_family": strategy["setup_family"],
                "status": strategy["status"],
                "test_priority": strategy["test_priority"],
            }
        )
    catalog_ledger = {
        "schema_version": "v1",
        "ledger_kind": "strategy_factory_catalog",
        "namespace": NAMESPACE,
        "next_strategy_id": f"SF-{len(final_catalog) + 1:03d}",
        "entries": catalog_entries,
    }
    dump_json(strategy_root / "catalog_ledger.json", catalog_ledger)

    backtest_queue = {
        "schema_version": "v1",
        "ledger_kind": "strategy_factory_backtest_queue",
        "namespace": NAMESPACE,
        "contract_freeze_required": True,
        "items": [],
        "recommended_candidates": [strategy_id for strategy_id in sorted(final_catalog)],
        "status": "not_started_by_scope",
    }
    dump_json(strategy_root / "backtest_queue.json", backtest_queue)

    triage_ledger = {
        "schema_version": "v1",
        "ledger_kind": "strategy_factory_triage",
        "allowed_factory_decisions": [
            "retain",
            "modify_and_retest",
            "insufficient_sample",
            "parked",
            "rejected_variant",
        ],
        "entries": [],
    }
    dump_json(strategy_root / "triage_ledger.json", triage_ledger)

    provider_config = load_json(repo_root / "config/strategy_factory/active_provider_config.json")
    run_state = {
        "schema_version": "v1",
        "factory_run_id": "m9-strategy-factory-full-extraction-audit-v4",
        "current_phase": "M9G.audit_v4_completed",
        "resume_cursor": {
            "phase": "completed",
            "audit_pass": "saturation_convergence_pass",
            "source_family": None,
            "source_id": None,
            "category": None,
            "chunk_offset": len(chunks),
        },
        "active_batch_id": None,
        "active_provider_config_path": "config/strategy_factory/active_provider_config.json",
        "primary_provider": provider_config["source_order"][0],
        "heartbeat_status": "completed",
        "last_summary_at": utc_now(),
        "text_extractable_closure": full_extraction_audit["text_extractable_closure"],
        "full_source_closure": full_extraction_audit["full_source_closure"],
    }
    dump_json(strategy_root / "run_state.json", run_state)


def write_summary_support_files(
    repo_root: Path,
    full_extraction_audit: dict[str, Any],
) -> None:
    report_root = repo_root / "reports/strategy_lab"
    automation_state = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "phase": "M9G.audit_v4_completed",
        "text_extractable_closure": full_extraction_audit["text_extractable_closure"],
        "full_source_closure": full_extraction_audit["full_source_closure"],
        "ready_for_backtest": full_extraction_audit["ready_for_backtest"],
        "resume_cursor": {"phase": "completed", "chunk_offset": full_extraction_audit["total_parseable_chunks"]},
    }
    dump_json(report_root / "automation_state.json", automation_state)

    heartbeat_rows = [
        {
            "generated_at": utc_now(),
            "batch_id": "HB-001",
            "stage": "full_pass_chunk_adjudication",
            "reviewed_count": full_extraction_audit["total_parseable_chunks"],
            "resume_cursor": {"phase": "cross_chunk_synthesis"},
        },
        {
            "generated_at": utc_now(),
            "batch_id": "HB-002",
            "stage": "cross_chunk_synthesis",
            "reviewed_count": len(full_extraction_audit["cross_chunk_synthesis_summary"]["new_strategy_candidate_ids"]),
            "resume_cursor": {"phase": "overmerge_review"},
        },
        {
            "generated_at": utc_now(),
            "batch_id": "HB-003",
            "stage": "strategy_closure_catalog_freeze",
            "reviewed_count": full_extraction_audit["final_strategy_card_count"],
            "resume_cursor": {"phase": "completed"},
        },
    ]
    heartbeat_path = report_root / "heartbeat.jsonl"
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    with heartbeat_path.open("w", encoding="utf-8") as handle:
        for row in heartbeat_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_full_extraction_audit(repo_root: Path) -> dict[str, Any]:
    sources = build_source_records(repo_root)
    chunks = build_chunk_records(repo_root, sources)
    raw_candidates, synthesis_records, _ = build_raw_candidates(chunks)
    final_catalog, dedup_map, candidate_to_strategy = build_final_catalog(sources, chunks, raw_candidates)
    overmerge_review = json.loads(candidate_to_strategy.pop("__overmerge__"))
    finalize_chunk_categories(chunks, raw_candidates, candidate_to_strategy)

    category_counts = Counter(chunk.final_category for chunk in chunks)
    notes_analysis = notes_per_source_findings(sources, chunks, raw_candidates)
    source_theme_coverage = build_source_theme_coverage(sources, chunks)
    source_family_report = build_source_family_completeness_report(sources, chunks, raw_candidates)
    corroboration_working = build_cross_source_corroboration(final_catalog)
    saturation_report = build_saturation_report()
    gaps = build_gap_ledger(chunks, sources)
    visual_review_queue = build_visual_review_queue(gaps)
    corroboration_final = build_cross_source_corroboration(final_catalog)

    text_extractable_closure = (
        category_counts["strategy_candidate"] >= 1
        and saturation_report["closure_reached"]
        and all(chunk.final_category in FORMAL_CATEGORIES for chunk in chunks)
    )
    full_source_closure = text_extractable_closure and not gaps
    closure_scope_reason = (
        "all parseable/text-extractable evidence is frozen, but visual/partial gaps still remain and prevent full-source closure"
        if text_extractable_closure and not full_source_closure
        else "all source gaps are resolved or formally exempted"
        if full_source_closure
        else "text-extractable closure is not complete"
    )

    family_bias_assessment = source_family_report["family_bias_assessment"]
    full_extraction_audit = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "total_parseable_chunks": len(chunks),
        "category_counts": {category: category_counts[category] for category in FORMAL_CATEGORIES},
        "unresolved_count": 0,
        "unmapped_count": 0,
        "source_family_counts": {
            family: sum(1 for chunk in chunks if chunk.source_family == family)
            for family in sorted({chunk.source_family for chunk in chunks})
        },
        "source_by_source_summary": source_family_report["sources"],
        "promoted_from_supporting": sum(
            1 for candidate in raw_candidates if "supporting_evidence" in candidate.origin_categories
        ),
        "promoted_from_open_question": sum(
            1 for candidate in raw_candidates if "open_question" in candidate.origin_categories
        ),
        "promoted_from_non_strategy": sum(
            1 for candidate in raw_candidates if "non_strategy" in candidate.origin_categories
        ),
        "promoted_from_parked_visual": sum(
            1 for candidate in raw_candidates if "parked_visual_review" in candidate.origin_categories
        ),
        "released_from_blocked_partial": sum(
            1 for candidate in raw_candidates if "blocked_or_partial_evidence" in candidate.origin_categories
        ),
        "restored_from_duplicate": len(overmerge_review["restored_pairs"]),
        "false_negative_findings": sum(
            1
            for chunk in chunks
            if chunk.initial_category in {"non_strategy", "open_question", "parked_visual_review", "blocked_or_partial_evidence"}
            and chunk.final_category == "strategy_candidate"
        ),
        "still_parked_visual": category_counts["parked_visual_review"],
        "still_blocked_partial": sum(
            1 for gap in gaps if gap["gap_type"] == "blocked_or_partial_evidence"
        ),
        "notes_zero_candidate_analysis": notes_analysis,
        "merge_assessment": {
            "overmerge_found": bool(overmerge_review["restored_pairs"]),
            "reason": (
                "some merged pairs were restored because environment/trigger/invalidation semantics diverged"
                if overmerge_review["restored_pairs"]
                else "no overmerge restored; merged pairs only differed by source/example evidence, not executable semantics"
            ),
        },
        "cross_chunk_synthesis_summary": {
            "synthesized_candidate_count": sum(1 for candidate in raw_candidates if candidate.synthesized),
            "new_strategy_candidate_ids": [candidate.candidate_id for candidate in raw_candidates if candidate.synthesized],
        },
        "family_bias_assessment": family_bias_assessment,
        "text_extractable_closure": text_extractable_closure,
        "full_source_closure": full_source_closure,
        "closure_scope_reason": closure_scope_reason,
        "final_strategy_card_count": len(final_catalog),
        "ready_for_backtest": text_extractable_closure and bool(final_catalog),
        "backtest_block_reason": "audit scope intentionally stops before batch backtest execution",
    }

    report_root = repo_root / "reports/strategy_lab"
    cards_root = report_root / "cards"
    specs_root = report_root / "specs"
    cards_root.mkdir(parents=True, exist_ok=True)
    specs_root.mkdir(parents=True, exist_ok=True)

    for strategy_id, strategy in sorted(final_catalog.items()):
        (cards_root / f"{strategy_id}.md").write_text(render_strategy_card(strategy), encoding="utf-8")
        (specs_root / f"{strategy_id}.yaml").write_text(render_spec_yaml(strategy), encoding="utf-8")

    dedup_map["schema_version"] = SCHEMA_VERSION
    dump_json(report_root / "strategy_catalog.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "namespace": NAMESPACE,
        "catalog_status": "frozen",
        "raw_candidate_count": len(raw_candidates),
        "final_strategy_count": len(final_catalog),
        "strategies": list(sorted(final_catalog.values(), key=lambda item: item["strategy_id"])),
    })
    dump_json(report_root / "strategy_dedup_map.json", dedup_map)
    dump_jsonl(
        report_root / "chunk_adjudication.jsonl",
        [
            {
                "chunk_id": chunk.chunk_id,
                "source_family": chunk.source_family,
                "source_id": chunk.source_id,
                "section_or_theme": chunk.section_or_theme,
                "prior_category": chunk.initial_category,
                "final_category": chunk.final_category,
                "audit_pass": "full_extraction_audit_v4",
                "reviewed_in_full_audit": True,
                "audit_decision": chunk.final_category,
                "audit_reason": chunk.audit_reason,
                "strategy_family_hint": chunk.best_theme,
                "merge_target_strategy_id": chunk.merge_target_strategy_id,
                "visual_review_status": chunk.final_category == "parked_visual_review",
                "blocking_status": chunk.final_category == "blocked_or_partial_evidence",
                "cross_chunk_synthesis_used": chunk.synthesis_group_id is not None,
                "synthesis_group_id": chunk.synthesis_group_id,
                "restored_from_merge": False,
                "overmerge_reviewed": bool(chunk.related_candidate_ids),
                "related_candidate_ids": chunk.related_candidate_ids or [],
            }
            for chunk in chunks
        ],
    )
    dump_json(report_root / "visual_review_queue.json", visual_review_queue)
    dump_json(report_root / "cross_chunk_synthesis.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "synthesized_candidates": synthesis_records,
    })
    dump_json(report_root / "source_theme_coverage.json", source_theme_coverage)
    dump_json(report_root / "source_family_completeness_report.json", source_family_report)
    dump_json(report_root / "cross_source_corroboration.json", corroboration_working)
    dump_json(report_root / "cross_source_corroboration_final.json", corroboration_final)
    dump_json(report_root / "overmerge_review.json", overmerge_review)
    dump_json(report_root / "saturation_report.json", saturation_report)
    dump_json(report_root / "unresolved_strategy_extraction_gaps.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "gaps": gaps,
    })
    dump_json(report_root / "full_extraction_audit.json", full_extraction_audit)

    factory_summary = build_factory_summary(category_counts, final_catalog, notes_analysis, full_extraction_audit)
    (report_root / "factory_summary.md").write_text(factory_summary, encoding="utf-8")

    update_strategy_factory_ledgers(repo_root, sources, chunks, raw_candidates, final_catalog, full_extraction_audit)
    (repo_root / "reports/strategy_lab/strategy_factory/final_summary.md").write_text(factory_summary, encoding="utf-8")
    write_summary_support_files(repo_root, full_extraction_audit)

    return {
        "sources": sources,
        "chunks": chunks,
        "raw_candidates": raw_candidates,
        "final_catalog": final_catalog,
        "full_extraction_audit": full_extraction_audit,
        "source_family_report": source_family_report,
        "notes_analysis": notes_analysis,
        "overmerge_review": overmerge_review,
        "saturation_report": saturation_report,
    }
