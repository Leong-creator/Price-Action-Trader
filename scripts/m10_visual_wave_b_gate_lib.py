#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M10_10_DIR = M10_DIR / "visual_wave_b_gate" / "m10_10"
VISUAL_INDEX_PATH = M10_DIR / "m10_visual_golden_case_index.json"
VISUAL_IDS = ("M10-PA-003", "M10-PA-004", "M10-PA-007", "M10-PA-008", "M10-PA-009", "M10-PA-010", "M10-PA-011")
PRE_EXISTING_WAVE_B_IDS = ("M10-PA-013",)
NOT_IN_GATE_IDS = ("M10-PA-001", "M10-PA-002", "M10-PA-005", "M10-PA-006", "M10-PA-012", "M10-PA-014", "M10-PA-015", "M10-PA-016")
ALLOWED_DECISIONS = (
    "ready_for_wave_b_backtest",
    "needs_definition_fix",
    "visual_only_not_backtestable",
    "blocked_missing_evidence",
)
FORBIDDEN_OUTPUT_STRINGS = ("PA-SC-", "SF-", "live-ready", "broker_connection=true", "real_orders=true")


@dataclass(frozen=True, slots=True)
class VisualGateRule:
    strategy_id: str
    decision: str
    ohlcv_proxy_quality: str
    wave_b_timeframes: tuple[str, ...]
    gate_reason: str
    spec_requirements: tuple[str, ...]
    client_note: str


GATE_RULES: dict[str, VisualGateRule] = {
    "M10-PA-003": VisualGateRule(
        strategy_id="M10-PA-003",
        decision="ready_for_wave_b_backtest",
        ohlcv_proxy_quality="medium",
        wave_b_timeframes=("1h", "15m", "5m"),
        gate_reason="tight channel can be approximated with consecutive directional closes, small pullbacks, and channel-break disqualifiers.",
        spec_requirements=(
            "minimum consecutive channel bars",
            "pullback depth cap",
            "opposite follow-through disqualifier",
        ),
        client_note="可进入 Wave B，但只能作为紧密通道的近似回测。",
    ),
    "M10-PA-004": VisualGateRule(
        strategy_id="M10-PA-004",
        decision="needs_definition_fix",
        ohlcv_proxy_quality="low",
        wave_b_timeframes=(),
        gate_reason="broad channel boundary depends on drawn channel line quality and boundary tests that are not yet encoded.",
        spec_requirements=(
            "channel boundary anchor persistence",
            "boundary touch tolerance",
            "strong breakout disqualifier",
        ),
        client_note="先补通道边界定义，不进入本轮 Wave B。",
    ),
    "M10-PA-007": VisualGateRule(
        strategy_id="M10-PA-007",
        decision="needs_definition_fix",
        ohlcv_proxy_quality="low",
        wave_b_timeframes=(),
        gate_reason="second-leg trap needs range edge, first leg, second leg, and trap confirmation fields before reliable backtest.",
        spec_requirements=(
            "first-leg and second-leg labels",
            "range edge or breakout edge",
            "trap confirmation bar",
        ),
        client_note="与失败突破类问题相似，需要先补结构字段。",
    ),
    "M10-PA-008": VisualGateRule(
        strategy_id="M10-PA-008",
        decision="ready_for_wave_b_backtest",
        ohlcv_proxy_quality="medium",
        wave_b_timeframes=("1d", "1h", "15m", "5m"),
        gate_reason="major trend reversal can be approximated with prior trend, trend break, test, and reversal confirmation.",
        spec_requirements=(
            "prior trend strength",
            "trend break confirmation",
            "test or higher-low/lower-high structure",
        ),
        client_note="可进入 Wave B，但必须保留趋势反转近似风险。",
    ),
    "M10-PA-009": VisualGateRule(
        strategy_id="M10-PA-009",
        decision="ready_for_wave_b_backtest",
        ohlcv_proxy_quality="medium_low",
        wave_b_timeframes=("1d", "1h", "15m", "5m"),
        gate_reason="wedge can be approximated by three pushes using swing pivots, but drawn wedge quality remains a review risk.",
        spec_requirements=(
            "three-push pivot detector",
            "push spacing bounds",
            "failed wedge disqualifier",
        ),
        client_note="可进入 Wave B，结果必须标注 wedge 画线风险。",
    ),
    "M10-PA-010": VisualGateRule(
        strategy_id="M10-PA-010",
        decision="visual_only_not_backtestable",
        ohlcv_proxy_quality="low",
        wave_b_timeframes=(),
        gate_reason="final flag, climax, and TBTL combine multiple visual/context labels that cannot be safely reduced to one Wave B trigger yet.",
        spec_requirements=(
            "separate final flag from climax",
            "define exhaustion versus continuation",
            "define TBTL measurement window",
        ),
        client_note="先保留为 visual-only，不进入本轮自动回测。",
    ),
    "M10-PA-011": VisualGateRule(
        strategy_id="M10-PA-011",
        decision="ready_for_wave_b_backtest",
        ohlcv_proxy_quality="medium",
        wave_b_timeframes=("15m", "5m"),
        gate_reason="opening reversal can be approximated with session open anchors, gap/opening context, and early reversal confirmation.",
        spec_requirements=(
            "regular-session opening anchor",
            "first 30-60 minute reversal window",
            "trend-from-open disqualifier",
        ),
        client_note="可进入 Wave B，只跑 `15m / 5m`。",
    ),
}


def run_m10_10_visual_wave_b_gate(output_dir: Path = M10_10_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    index = load_json(VISUAL_INDEX_PATH)
    packs_by_id = {pack["strategy_id"]: pack for pack in index["packs"]}
    review_rows = []
    for strategy_id in VISUAL_IDS:
        pack = packs_by_id[strategy_id]
        rule = GATE_RULES[strategy_id]
        evidence_ok = (
            pack.get("pack_status") == "visual_pack_ready"
            and pack.get("evidence_complete") is True
            and pack.get("case_counts", {}).get("positive", 0) >= 3
            and pack.get("case_counts", {}).get("counterexample", 0) >= 1
            and pack.get("case_counts", {}).get("boundary", 0) >= 1
        )
        decision = rule.decision if evidence_ok else "blocked_missing_evidence"
        review_rows.append(build_review_row(pack, rule, decision, evidence_ok))

    queue = build_queue(review_rows)
    write_json(output_dir / "m10_10_wave_b_entry_queue.json", queue)
    write_json(output_dir / "m10_10_visual_gate_summary.json", build_summary(review_rows, queue, output_dir))
    write_visual_review(output_dir / "m10_10_visual_strategy_review.md", review_rows, queue)
    write_client_summary(output_dir / "m10_10_visual_client_summary.md", review_rows, queue)
    validate_outputs(output_dir)
    return build_summary(review_rows, queue, output_dir)


def build_review_row(
    pack: dict[str, Any],
    rule: VisualGateRule,
    decision: str,
    evidence_ok: bool,
) -> dict[str, Any]:
    return {
        "strategy_id": rule.strategy_id,
        "title": pack["title"],
        "decision": decision,
        "pack_status": pack["pack_status"],
        "evidence_complete": evidence_ok,
        "case_counts": pack["case_counts"],
        "ohlcv_proxy_quality": rule.ohlcv_proxy_quality,
        "wave_b_timeframes": list(rule.wave_b_timeframes) if decision == "ready_for_wave_b_backtest" else [],
        "gate_reason": rule.gate_reason,
        "spec_requirements": list(rule.spec_requirements),
        "client_note": rule.client_note,
        "case_pack_json": pack["case_pack_json"],
        "case_pack_markdown": pack["case_pack_markdown"],
    }


def build_queue(review_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ready_visual = [row for row in review_rows if row["decision"] == "ready_for_wave_b_backtest"]
    return {
        "schema_version": "m10.10.wave-b-entry-queue.v1",
        "generated_at": "2026-04-27T00:00:00Z",
        "stage": "M10.10.visual_wave_b_gate",
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "paper_trading_approval": False,
        "ready_visual_strategy_ids": [row["strategy_id"] for row in ready_visual],
        "pre_existing_wave_b_candidate_ids": list(PRE_EXISTING_WAVE_B_IDS),
        "wave_b_strategy_ids": [*PRE_EXISTING_WAVE_B_IDS, *[row["strategy_id"] for row in ready_visual]],
        "entries": [
            {
                "strategy_id": strategy_id,
                "source": "pre_existing_wave_b_candidate",
                "timeframes": ["1d", "1h", "15m", "5m"],
                "requires_new_spec": True,
            }
            for strategy_id in PRE_EXISTING_WAVE_B_IDS
        ]
        + [
            {
                "strategy_id": row["strategy_id"],
                "source": "m10_10_visual_gate",
                "timeframes": row["wave_b_timeframes"],
                "requires_new_spec": True,
                "ohlcv_proxy_quality": row["ohlcv_proxy_quality"],
            }
            for row in ready_visual
        ],
        "not_in_queue": [
            {"strategy_id": row["strategy_id"], "decision": row["decision"]}
            for row in review_rows
            if row["decision"] != "ready_for_wave_b_backtest"
        ],
        "excluded_strategy_ids": list(NOT_IN_GATE_IDS),
        "boundary_note": "Wave B entry means eligible for a future simulated spec/backtest, not strategy approval.",
    }


def build_summary(
    review_rows: list[dict[str, Any]],
    queue: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    counts: dict[str, int] = {decision: 0 for decision in ALLOWED_DECISIONS}
    for row in review_rows:
        counts[row["decision"]] += 1
    return {
        "schema_version": "m10.10.visual-wave-b-gate-summary.v1",
        "generated_at": "2026-04-27T00:00:00Z",
        "stage": "M10.10.visual_wave_b_gate",
        "visual_strategy_ids": list(VISUAL_IDS),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "paper_trading_approval": False,
        "decision_counts": counts,
        "review_rows": review_rows,
        "wave_b_queue_ref": "reports/strategy_lab/m10_price_action_strategy_refresh/visual_wave_b_gate/m10_10/m10_10_wave_b_entry_queue.json",
        "wave_b_strategy_ids": queue["wave_b_strategy_ids"],
        "output_dir": output_dir.relative_to(ROOT).as_posix(),
    }


def write_visual_review(path: Path, rows: list[dict[str, Any]], queue: dict[str, Any]) -> None:
    lines = [
        "# M10.10 Visual Wave B Gate Review",
        "",
        "## 摘要",
        "",
        "- 本阶段只复核 `M10-PA-003/004/007/008/009/010/011` 这 7 条强图形策略。",
        "- `ready_for_wave_b_backtest` 只表示可进入后续模拟规格冻结和历史回测，不代表策略有效或盈利。",
        "- M10.10 不启动回测、不接 broker、不批准 paper trading。",
        "",
        "## Gate 结果",
        "",
        "| Strategy | Decision | OHLCV Proxy | Timeframes | Note |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        timeframes = " / ".join(row["wave_b_timeframes"]) if row["wave_b_timeframes"] else "-"
        lines.append(
            f"| {row['strategy_id']} | `{row['decision']}` | {row['ohlcv_proxy_quality']} | "
            f"{timeframes} | {row['client_note']} |"
        )
    lines.extend(
        [
            "",
            "## Wave B Queue",
            "",
            f"- ready visual strategies: `{', '.join(queue['ready_visual_strategy_ids'])}`",
            f"- plus existing Wave B candidate: `{', '.join(queue['pre_existing_wave_b_candidate_ids'])}`",
            "",
            "## 后续规格要求",
            "",
        ]
    )
    for row in rows:
        lines.append(f"### {row['strategy_id']}")
        lines.append(f"- decision: `{row['decision']}`")
        lines.append(f"- reason: {row['gate_reason']}")
        lines.append("- spec requirements:")
        for requirement in row["spec_requirements"]:
            lines.append(f"  - {requirement}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_client_summary(path: Path, rows: list[dict[str, Any]], queue: dict[str, Any]) -> None:
    ready = [row for row in rows if row["decision"] == "ready_for_wave_b_backtest"]
    blocked = [row for row in rows if row["decision"] != "ready_for_wave_b_backtest"]
    lines = [
        "# M10.10 Visual Strategy Client Summary",
        "",
        "## 给甲方看的结论",
        "",
        f"- 可进入 Wave B 模拟测试的视觉策略：`{', '.join(row['strategy_id'] for row in ready)}`。",
        f"- 暂不进入 Wave B 的视觉策略：`{', '.join(row['strategy_id'] for row in blocked)}`。",
        f"- Wave B 还会带上低视觉候选：`{', '.join(queue['pre_existing_wave_b_candidate_ids'])}`。",
        "- 这一步只是决定能不能继续做模拟测试，不是策略批准。",
        "",
        "## 策略状态",
        "",
        "| Strategy | Status | Client Note |",
        "|---|---|---|",
    ]
    for row in rows:
        lines.append(f"| {row['strategy_id']} | `{row['decision']}` | {row['client_note']} |")
    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "进入 M10.11 后，只对本 queue 中的策略生成资金曲线测试；暂不进入 queue 的策略先补定义或保留为图形复核材料。",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def validate_outputs(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in [
            output_dir / "m10_10_wave_b_entry_queue.json",
            output_dir / "m10_10_visual_gate_summary.json",
            output_dir / "m10_10_visual_strategy_review.md",
            output_dir / "m10_10_visual_client_summary.md",
        ]
        if path.exists()
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_STRINGS:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run_m10_10_visual_wave_b_gate()
