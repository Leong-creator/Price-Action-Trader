#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_12_DIR = M10_DIR / "daily_observation" / "m12_12_loop"
M12_9_DIR = M10_DIR / "visual_review" / "m12_9_closure"
M12_10_DIR = M10_DIR / "definition_fix" / "m12_10_definition_fix_and_retest"
OUTPUT_DIR = M10_DIR / "source_revisit" / "m12_14_source_strategy_closure"

FORMAL_STRATEGY_ID = "M12-FTD-001"
FORBIDDEN_OUTPUT_TEXT = (
    "PA-SC-",
    "SF-",
    "live-ready",
    "real_orders=true",
    "broker_connection=true",
    "paper approval",
)


def project_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_m12_14_source_strategy_closure(*, generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    formal_summary = load_json(M12_12_DIR / "m12_12_formal_daily_strategy_summary.json")
    definition_field_ledger = load_json(M12_10_DIR / "m12_10_definition_field_ledger.json")
    visual_case_ledger = load_json(M12_9_DIR / "m12_9_case_review_ledger.json")

    source_ledger = build_early_strategy_source_ledger(generated_at, formal_summary)
    candidate_catalog = build_source_revisit_candidates(generated_at)
    visual_decision_ledger = build_visual_decision_ledger(generated_at, visual_case_ledger)
    definition_closure = build_definition_closure(generated_at, definition_field_ledger)
    summary = build_summary(
        generated_at,
        formal_summary,
        source_ledger,
        candidate_catalog,
        visual_decision_ledger,
        definition_closure,
    )

    write_json(OUTPUT_DIR / "m12_14_early_strategy_multisource_definition_ledger.json", source_ledger)
    write_json(OUTPUT_DIR / "m12_14_source_revisit_strategy_candidates.json", candidate_catalog)
    write_json(OUTPUT_DIR / "m12_14_visual_decision_ledger.json", visual_decision_ledger)
    write_json(OUTPUT_DIR / "m12_14_definition_closure.json", definition_closure)
    write_json(OUTPUT_DIR / "m12_14_summary.json", summary)

    (OUTPUT_DIR / "m12_14_early_strategy_upgrade_plan.md").write_text(
        build_early_strategy_upgrade_plan_md(source_ledger, formal_summary),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "m12_14_source_revisit_strategy_candidates.md").write_text(
        build_candidate_md(candidate_catalog),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "m12_14_visual_decision_report.md").write_text(
        build_visual_report_md(visual_decision_ledger),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "m12_14_definition_closure_report.md").write_text(
        build_definition_report_md(definition_closure),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "m12_14_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")

    assert_no_forbidden_output(OUTPUT_DIR)
    return summary


def build_early_strategy_source_ledger(generated_at: str, formal_summary: dict[str, Any]) -> dict[str, Any]:
    fields = [
        {
            "field": "行情背景",
            "current_problem": "旧版只说日线明显上涨或下跌，太粗，容易把震荡里的强K线也当成机会。",
            "new_definition": "先把行情分成突破、紧密通道、宽通道、震荡区间、过渡期；只有趋势背景足够清楚时才允许顺势信号K进入测试。",
            "source_refs": [
                "wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md",
                "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md",
                "raw:knowledge/raw/youtube/fangfangtu/transcripts/Price_Action方方土.pdf",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_012A_market_cycle_four_parts_pullback_channel_trading_range.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_014E_trends_tight_channel_small_pullback.md",
            ],
            "test_effect": "预期减少震荡里的误触发，重点观察回撤是否下降。",
        },
        {
            "field": "信号K质量",
            "current_problem": "旧版只要求顺势强K线，没有拆实体、收盘位置、影线和背景是否配合。",
            "new_definition": "拆成实体强度、收盘位置、影线比例、是否与背景同向、下一根是否跟进；弱信号K只能观察，不能作为正式触发。",
            "source_refs": [
                "wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md",
                "raw:knowledge/raw/notes/方方土视频笔记 - 信号K线 & 入场.pdf",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_008A_candles_setups_signal_bars_trend_tr_entry_bad_signal.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_015D_breakouts_second_leg_traps_strong_breakouts.md",
            ],
            "test_effect": "预期过滤差K线，候选数会下降，胜率和回撤要重新看。",
        },
        {
            "field": "更高周期一致性",
            "current_problem": "旧版没有判断更高周期，可能在日线看起来强，但周线其实处于区间上沿。",
            "new_definition": "日线信号优先要求更高周期不处于明显阻力边缘；若更高周期是震荡区间边缘，则信号降级为观察。",
            "source_refs": [
                "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_009C_pullbacks_endless_higher_lower_timeframes_countertrend_exit.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_012A_market_cycle_four_parts_pullback_channel_trading_range.md",
            ],
            "test_effect": "预期减少高位追涨和低位追空。",
        },
        {
            "field": "长回调保护",
            "current_problem": "旧版把趋势中的所有顺势信号都近似看待，没有区分普通回调和已经拖太久的回调。",
            "new_definition": "如果回调已经持续约20根K线以上，不再按普通趋势恢复处理，必须重新评估是否已经进入区间或反转。",
            "source_refs": [
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_009C_pullbacks_endless_higher_lower_timeframes_countertrend_exit.md",
                "raw:knowledge/raw/notes/方方土视频笔记 - 回调&数K线.pdf",
                "wiki:knowledge/wiki/sources/fangfangtu-pullback-counting-bars-note.md",
            ],
            "test_effect": "这是降低大回撤的第一优先过滤器。",
        },
        {
            "field": "入场确认",
            "current_problem": "旧版只看突破信号K高低点，容易把第二天无跟进的假信号也纳入。",
            "new_definition": "区分突破信号K入场和下一根K线收盘确认；若突破后1-2根K线没有跟进，取消或降级。",
            "source_refs": [
                "wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_015B_breakouts_follow_through_reversal_small_start.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_015D_breakouts_second_leg_traps_strong_breakouts.md",
            ],
            "test_effect": "这是把高收益策略变得更稳的第二优先过滤器。",
        },
        {
            "field": "止损和目标",
            "current_problem": "旧版固定信号K另一端止损、2R目标，解释力不够。",
            "new_definition": "保留信号K止损，同时记录波段止损、实际风险止损、前高前低、测量目标，回测输出多目标对比。",
            "source_refs": [
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_020A_measured_moves_leg1_equals_leg2_prior_leg.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_034A_actual_risk_traders_equation_profit_targets.md",
                "reports/strategy_lab/m10_price_action_strategy_refresh/source_ledgers/M10-PA-014.json",
                "reports/strategy_lab/m10_price_action_strategy_refresh/source_ledgers/M10-PA-015.json",
            ],
            "test_effect": "不是为了调参，而是为了知道收益来自哪里、回撤由什么造成。",
        },
    ]

    return {
        "schema_version": "m12.14.early-strategy-multisource-definition-ledger.v1",
        "stage": "M12.14.source_strategy_closure",
        "generated_at": generated_at,
        "strategy_id": FORMAL_STRATEGY_ID,
        "strategy_name": "方方土日线趋势顺势信号K 多来源增强版",
        "plain_language_result": "早期策略收益确实强，应该进入下一轮重点测试；但先补背景、信号K质量、长回调保护和跟进确认，目标是保留收益能力同时压回撤。",
        "current_m12_12_metrics": formal_summary.get("overall_metrics", {}),
        "source_families": [
            "fangfangtu_notes",
            "fangfangtu_youtube_transcript",
            "brooks_v2_manual_transcript",
            "al_brooks_ppt_or_supporting_source_pages",
        ],
        "not_source_of_truth": [
            "早期截图",
            "M12-BENCH-001",
            "signal_bar_entry_placeholder",
        ],
        "upgrade_fields": fields,
        "next_test": {
            "name": "M12-FTD-001 v0.2 A/B 重测",
            "baseline": "M12.12 简化口径",
            "variants": [
                "只加长回调保护",
                "只加1-2根K线跟进确认",
                "加行情背景分类 + 信号K质量",
                "完整多来源增强版",
            ],
            "success_focus": "不是只看收益更高，而是看最大回撤、亏损连续性、分标的稳定性是否改善。",
        },
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
    }


def build_source_revisit_candidates(generated_at: str) -> dict[str, Any]:
    candidates = [
        {
            "candidate_id": "M12-SRC-001",
            "name": "日线趋势顺势信号K增强版",
            "role": "正式策略候选",
            "linked_strategy": "M12-FTD-001",
            "why_now": "早期策略收益强，但回撤大，最值得先做定义增强和A/B重测。",
            "test_priority": 1,
            "test_route": "立即进入下一轮历史A/B重测，然后继续每日只读观察。",
            "source_refs": [
                "wiki:knowledge/wiki/sources/fangfangtu-market-cycle-note.md",
                "wiki:knowledge/wiki/sources/fangfangtu-signal-bar-entry-note.md",
                "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_008A_candles_setups_signal_bars_trend_tr_entry_bad_signal.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_012A_market_cycle_four_parts_pullback_channel_trading_range.md",
            ],
            "daily_test_fit": "高",
            "scanner_fit": "高",
        },
        {
            "candidate_id": "M12-SRC-002",
            "name": "趋势回调二次入场",
            "role": "正式策略候选",
            "linked_strategy": "M10-PA-001",
            "why_now": "它和早期日线策略同属顺势，但比单根强K线更强调回调后的再次启动，可能更稳。",
            "test_priority": 2,
            "test_route": "保留每日只读主线，并扩大到50只股票扫描。",
            "source_refs": [
                "reports/strategy_lab/m10_price_action_strategy_refresh/source_ledgers/M10-PA-001.json",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_009A_pullbacks_bar_counting_basics_high_low_1_2.md",
                "raw:knowledge/raw/notes/方方土视频笔记 - 回调&数K线.pdf",
            ],
            "daily_test_fit": "高",
            "scanner_fit": "高",
        },
        {
            "candidate_id": "M12-SRC-003",
            "name": "突破后1-2根K线跟进",
            "role": "正式策略候选",
            "linked_strategy": "M10-PA-002",
            "why_now": "它能解释强K线之后有没有真正延续，是早期策略降低假信号的直接补充。",
            "test_priority": 3,
            "test_route": "保留每日只读主线，并作为 M12-FTD-001 的确认过滤器。",
            "source_refs": [
                "reports/strategy_lab/m10_price_action_strategy_refresh/source_ledgers/M10-PA-002.json",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_015A_breakouts_definition_80_rule_reversal_tr.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_015B_breakouts_follow_through_reversal_small_start.md",
                "raw:knowledge/raw/notes/方方土视频笔记-突破.pdf",
            ],
            "daily_test_fit": "高",
            "scanner_fit": "高",
        },
        {
            "candidate_id": "M12-SRC-004",
            "name": "紧密通道/小回调顺势",
            "role": "选股过滤器候选",
            "linked_strategy": "M10-PA-003",
            "why_now": "它更像筛选强趋势股票的条件，适合先提高 scanner 排名，而不是马上当独立交易触发。",
            "test_priority": 4,
            "test_route": "先做 scanner 排名因子，再决定是否单独回测。",
            "source_refs": [
                "reports/strategy_lab/m10_price_action_strategy_refresh/source_ledgers/M10-PA-003.json",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_014E_trends_tight_channel_small_pullback.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_017A_tight_channels_micro_channels_definitions.md",
            ],
            "daily_test_fit": "中高",
            "scanner_fit": "高",
        },
        {
            "candidate_id": "M12-SRC-005",
            "name": "长回调保护",
            "role": "回撤控制过滤器",
            "linked_strategy": "M12-FTD-001-filter",
            "why_now": "它专门解决早期策略回撤大的问题：趋势回调拖太久时，不再当普通顺势机会。",
            "test_priority": 5,
            "test_route": "先叠加到 M12-FTD-001 做A/B测试。",
            "source_refs": [
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_009C_pullbacks_endless_higher_lower_timeframes_countertrend_exit.md",
                "wiki:knowledge/wiki/sources/fangfangtu-pullback-counting-bars-note.md",
            ],
            "daily_test_fit": "高",
            "scanner_fit": "中高",
        },
        {
            "candidate_id": "M12-SRC-006",
            "name": "主要趋势反转观察",
            "role": "反转观察候选",
            "linked_strategy": "M10-PA-008",
            "why_now": "M10-PA-008 的关键图例这轮已经由 agent 关闭，不再卡人工确认；下一步可以做严格定义后的观察测试。",
            "test_priority": 6,
            "test_route": "先进入反转观察清单，不直接进入全自动交易触发。",
            "source_refs": [
                "reports/strategy_lab/m10_price_action_strategy_refresh/source_ledgers/M10-PA-008.json",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_022A_major_trend_reversals_requirements_minor_mtr_probability.md",
                "raw:knowledge/raw/brooks/transcribed_v2/al_brooks_price_action_course_v2/units/video_021A_reversals_definition_minor_major_breakouts.md",
            ],
            "daily_test_fit": "中",
            "scanner_fit": "中",
        },
    ]
    return {
        "schema_version": "m12.14.source-revisit-strategy-candidates.v1",
        "stage": "M12.14.source_strategy_closure",
        "generated_at": generated_at,
        "plain_language_result": "回头看早期策略来源后，最值得继续看的不是一条，而是一组：顺势信号K、回调二次入场、突破跟进、紧密通道筛选、长回调保护、主要趋势反转观察。",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
    }


def build_visual_decision_ledger(generated_at: str, visual_case_ledger: dict[str, Any]) -> dict[str, Any]:
    by_id = {row["case_id"]: row for row in visual_case_ledger["case_rows"]}
    decisions = [
        decision_row(
            by_id,
            "M10-PA-008-positive-001",
            "通过",
            "这张图明确支持强下跌后的 HH MTR；可以作为 M10-PA-008 正例。",
            "保留为正例证据。",
        ),
        decision_row(
            by_id,
            "M10-PA-008-boundary-001",
            "剔除正例",
            "这张图写的是卖压不足，通常只是小反转进入交易区间或牛旗；不应再当 MTR 正例或模糊图。",
            "保留为排除/边界证据，不再要求用户确认。",
        ),
        decision_row(
            by_id,
            "M10-PA-009-counterexample-001",
            "通过为反例",
            "这张图适合作为楔形策略的反例，不适合作为正例；原来的 counterexample 角色正确。",
            "保留为反例证据。",
        ),
        decision_row(
            by_id,
            "M10-PA-009-boundary-001",
            "通过",
            "这张图给出楔形最低要求：三次强推动、形成通道，收敛更可靠但不是必要条件；不再算模糊。",
            "保留为可接受边界例。",
        ),
    ]
    return {
        "schema_version": "m12.14.visual-decision-ledger.v1",
        "stage": "M12.14.source_strategy_closure",
        "generated_at": generated_at,
        "plain_language_result": "M10-PA-008/009 的关键图例已经由 agent 直接判定，不再挂“等用户确认”。",
        "needs_user_review_count": 0,
        "paper_gate_evidence_now": False,
        "paper_gate_note": "图例确认已关闭，但还要经过对应策略规则和历史/每日测试，不能直接等同于批准模拟交易。",
        "case_decisions": decisions,
        "strategy_decisions": [
            {
                "strategy_id": "M10-PA-008",
                "decision": "图例确认关闭",
                "next_status": "可以进入严格定义后的反转观察/复测队列",
                "needs_user_review": False,
            },
            {
                "strategy_id": "M10-PA-009",
                "decision": "图例确认关闭",
                "next_status": "可以进入严格楔形定义后的观察/复测队列",
                "needs_user_review": False,
            },
        ],
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
    }


def decision_row(
    by_id: dict[str, dict[str, Any]],
    case_id: str,
    agent_decision_cn: str,
    rationale: str,
    action: str,
) -> dict[str, Any]:
    row = by_id[case_id]
    return {
        "case_id": case_id,
        "strategy_id": row["strategy_id"],
        "case_type": row["case_type"],
        "old_decision": row.get("case_level_decision"),
        "old_manual_status": row.get("manual_review_status"),
        "agent_decision_cn": agent_decision_cn,
        "direct_close": True,
        "needs_user_review": False,
        "paper_gate_evidence_now": False,
        "rationale": rationale,
        "action": action,
        "evidence_image_logical_path": row.get("evidence_image_logical_path"),
        "evidence_resolved_local_path": row.get("evidence_resolved_local_path"),
        "checksum_match": bool(row.get("checksum_match")),
        "brooks_unit_ref": row.get("brooks_unit_ref"),
    }


def build_definition_closure(generated_at: str, definition_field_ledger: dict[str, Any]) -> dict[str, Any]:
    rows = []
    by_id = {row["strategy_id"]: row for row in definition_field_ledger["strategy_rows"]}
    pa005 = by_id["M10-PA-005"]
    rows.append(
        {
            "strategy_id": "M10-PA-005",
            "plain_status": "已补几何字段并复测，但结果弱，暂不进每日测试主线。",
            "what_was_fixed": [
                "range high/low",
                "range height",
                "breakout edge",
                "re-entry close",
                "failed breakout extreme",
            ],
            "current_decision": pa005["definition_decision"],
            "next_action": "不再拖主线；如果后续要救这条，只能作为单独研究项重做交易区间检测器。",
            "paper_gate_evidence_now": False,
        }
    )
    for strategy_id, label in (
        ("M10-PA-004", "宽通道边界反转"),
        ("M10-PA-007", "第二腿陷阱反转"),
    ):
        source = by_id[strategy_id]
        rows.append(
            {
                "strategy_id": strategy_id,
                "plain_status": f"{label} 当前不能靠普通 OHLCV 自动确认，已正式降级，不再挂“等用户确认”。",
                "what_is_missing": list(source["required_fields"].keys()),
                "current_decision": source["definition_decision"],
                "next_action": "若要继续，下一步是新建图形检测器/人工标签数据集；不进入当前每日自动测试。",
                "paper_gate_evidence_now": False,
            }
        )
    return {
        "schema_version": "m12.14.definition-closure.v1",
        "stage": "M12.14.source_strategy_closure",
        "generated_at": generated_at,
        "plain_language_result": "定义问题已经给出明确处理：005 已补字段但不进主线；004/007 降级为图形研究，不再等待你确认。",
        "strategy_rows": rows,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
    }


def build_summary(
    generated_at: str,
    formal_summary: dict[str, Any],
    source_ledger: dict[str, Any],
    candidate_catalog: dict[str, Any],
    visual_decision_ledger: dict[str, Any],
    definition_closure: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "m12.14.summary.v1",
        "stage": "M12.14.source_strategy_closure",
        "generated_at": generated_at,
        "plain_language_result": "本轮已把早期高收益策略、多来源定义、其他值得测试策略、图形确认和定义阻塞一次性收口。",
        "early_strategy_result": {
            "strategy_id": FORMAL_STRATEGY_ID,
            "current_metrics": formal_summary.get("overall_metrics", {}),
            "status_after_m12_14": "重点升级测试候选，不再只是 placeholder 或 benchmark。",
            "next_test": source_ledger["next_test"],
        },
        "source_revisit_candidate_count": candidate_catalog["candidate_count"],
        "visual_cases_closed_without_user_review": len(visual_decision_ledger["case_decisions"]),
        "visual_needs_user_review_count": visual_decision_ledger["needs_user_review_count"],
        "definition_blockers_closed": len(definition_closure["strategy_rows"]),
        "next_delivery": [
            "先跑 M12-FTD-001 v0.2 A/B 重测，目标是降低回撤而不是扫参数。",
            "把 M10-PA-001/002/012 + M12-FTD-001 继续放进50只股票每日只读测试。",
            "M10-PA-008/009 不再等图例确认，进入严格定义后的观察/复测准备。",
            "M10-PA-005/004/007 不拖主线：005暂不进每日测试，004/007降级为图形研究。",
        ],
        "artifacts": {
            "definition_ledger": project_path(OUTPUT_DIR / "m12_14_early_strategy_multisource_definition_ledger.json"),
            "upgrade_plan": project_path(OUTPUT_DIR / "m12_14_early_strategy_upgrade_plan.md"),
            "candidate_catalog": project_path(OUTPUT_DIR / "m12_14_source_revisit_strategy_candidates.json"),
            "candidate_report": project_path(OUTPUT_DIR / "m12_14_source_revisit_strategy_candidates.md"),
            "visual_decision_ledger": project_path(OUTPUT_DIR / "m12_14_visual_decision_ledger.json"),
            "visual_report": project_path(OUTPUT_DIR / "m12_14_visual_decision_report.md"),
            "definition_closure": project_path(OUTPUT_DIR / "m12_14_definition_closure.json"),
            "definition_report": project_path(OUTPUT_DIR / "m12_14_definition_closure_report.md"),
        },
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
    }


def build_early_strategy_upgrade_plan_md(source_ledger: dict[str, Any], formal_summary: dict[str, Any]) -> str:
    metrics = formal_summary["overall_metrics"]
    lines = [
        "# M12.14 早期日线策略多来源升级计划",
        "",
        "## 直接结论",
        "",
        "- 早期日线策略不能再只叫 benchmark；它已经升级为 `M12-FTD-001` 的重点正式候选。",
        f"- 当前历史模拟：收益 `{metrics['return_percent']}%`，盈利 `{metrics['net_profit']}`，胜率 `{metrics['win_rate']}%`，最大回撤 `{metrics['max_drawdown_percent']}%`，交易 `{metrics['trade_count']}` 笔。",
        "- 现在要做的不是盲目调参数，而是按来源补强定义，再做 A/B 重测，重点看最大回撤能否下降。",
        "",
        "## 要补强的定义",
        "",
    ]
    for item in source_ledger["upgrade_fields"]:
        lines.extend(
            [
                f"### {item['field']}",
                "",
                f"- 当前问题：{item['current_problem']}",
                f"- 新定义：{item['new_definition']}",
                f"- 测试看点：{item['test_effect']}",
                "- 来源：",
            ]
        )
        for ref in item["source_refs"]:
            lines.append(f"  - `{ref}`")
        lines.append("")
    lines.extend(
        [
            "## 下一次测试怎么跑",
            "",
            "- 对照组：M12.12 简化版。",
            "- 测试组 1：只加长回调保护。",
            "- 测试组 2：只加 1-2 根K线跟进确认。",
            "- 测试组 3：加行情背景分类 + 信号K质量。",
            "- 测试组 4：完整多来源增强版。",
            "- 成功标准：不是收益更高就算赢，而是收益、最大回撤、连续亏损、分标的稳定性一起看。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_candidate_md(candidate_catalog: dict[str, Any]) -> str:
    lines = [
        "# M12.14 回看早期来源后新增测试候选",
        "",
        "## 直接结论",
        "",
        candidate_catalog["plain_language_result"],
        "",
        "| 优先级 | ID | 名称 | 角色 | 下一步 |",
        "|---:|---|---|---|---|",
    ]
    for item in candidate_catalog["candidates"]:
        lines.append(
            f"| {item['test_priority']} | `{item['candidate_id']}` | {item['name']} | {item['role']} | {item['test_route']} |"
        )
    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- 这里不是把早期截图直接包装成正式策略，而是回到方方土、Brooks v2 和相关 notes 的来源重新提炼。")
    lines.append("- 最优先的是 `M12-SRC-001`，也就是 `M12-FTD-001` 的多来源增强版。")
    return "\n".join(lines) + "\n"


def build_visual_report_md(visual_decision_ledger: dict[str, Any]) -> str:
    lines = [
        "# M12.14 图形确认关闭报告",
        "",
        "## 直接结论",
        "",
        "- `M10-PA-008` 和 `M10-PA-009` 的关键图例已经由 agent 直接判定。",
        "- 不再需要你逐张确认这些图例。",
        "- 图例通过不等于策略已经可以交易；它只表示图形阻塞关闭，下一步可以做严格规则和测试。",
        "",
        "| 策略 | case | 结论 | 处理 |",
        "|---|---|---|---|",
    ]
    for item in visual_decision_ledger["case_decisions"]:
        lines.append(
            f"| `{item['strategy_id']}` | `{item['case_id']}` | {item['agent_decision_cn']} | {item['action']} |"
        )
    return "\n".join(lines) + "\n"


def build_definition_report_md(definition_closure: dict[str, Any]) -> str:
    lines = [
        "# M12.14 定义问题关闭报告",
        "",
        "## 直接结论",
        "",
        definition_closure["plain_language_result"],
        "",
        "| 策略 | 当前处理 | 下一步 |",
        "|---|---|---|",
    ]
    for row in definition_closure["strategy_rows"]:
        lines.append(f"| `{row['strategy_id']}` | {row['plain_status']} | {row['next_action']} |")
    return "\n".join(lines) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "# M12.14 Handoff\n\n"
        "## 用人话结论\n\n"
        f"{summary['plain_language_result']}\n\n"
        "## 下一步\n\n"
        + "\n".join(f"- {item}" for item in summary["next_delivery"])
        + "\n"
    )


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")
