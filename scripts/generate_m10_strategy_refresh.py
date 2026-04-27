#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - validator covers behavior without pypdf
    PdfReader = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
BROOKS_V2_ROOT = (
    PROJECT_ROOT
    / "knowledge"
    / "raw"
    / "brooks"
    / "transcribed_v2"
    / "al_brooks_price_action_course_v2"
)
CHATGPT_REFERENCE_PATH = (
    PROJECT_ROOT
    / "knowledge"
    / "raw"
    / "chatgpt"
    / "shares"
    / "69ed8224-a360-8327-a2cc-0976be6555d5"
    / "bpa_reference_summary.json"
)

SOURCE_PRIORITY = (
    "brooks_v2_manual_transcript",
    "fangfangtu_youtube_transcript",
    "fangfangtu_notes",
)
HIGH_PRIORITY_SOURCE_FAMILIES = {
    "brooks_v2_manual_transcript",
    "fangfangtu_youtube_transcript",
}
FORBIDDEN_CLEAN_ROOM_READ_PATHS = (
    PROJECT_ROOT / "knowledge" / "wiki" / "strategy_cards",
    PROJECT_ROOT / "reports" / "strategy_lab" / "strategy_catalog.json",
    PROJECT_ROOT / "reports" / "strategy_lab" / "specs",
    PROJECT_ROOT / "reports" / "strategy_lab" / "strategy_triage_matrix.json",
    PROJECT_ROOT / "reports" / "strategy_lab" / "cards",
)
LEGACY_COMPARISON_PATHS = (
    PROJECT_ROOT / "knowledge" / "wiki" / "strategy_cards",
    PROJECT_ROOT / "reports" / "strategy_lab" / "strategy_catalog.json",
    PROJECT_ROOT / "reports" / "strategy_lab" / "cards",
    PROJECT_ROOT / "reports" / "strategy_lab" / "specs",
    PROJECT_ROOT / "reports" / "strategy_lab" / "strategy_triage_matrix.json",
)
M10_1_BACKTEST_WAVE_A_IDS = ("M10-PA-001", "M10-PA-002", "M10-PA-005", "M10-PA-012")
M10_1_BACKTEST_WAVE_A_TIMEFRAMES = {
    "M10-PA-001": ("1d", "1h", "15m", "5m"),
    "M10-PA-002": ("1d", "1h", "15m", "5m"),
    "M10-PA-005": ("1d", "1h", "15m", "5m"),
    "M10-PA-012": ("15m", "5m"),
}
M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS = ("M10-PA-013",)
M10_1_VISUAL_GOLDEN_CASE_IDS = (
    "M10-PA-003",
    "M10-PA-004",
    "M10-PA-007",
    "M10-PA-008",
    "M10-PA-009",
    "M10-PA-010",
    "M10-PA-011",
)
M10_1_SUPPORTING_RULE_IDS = ("M10-PA-014", "M10-PA-015")
M10_1_RESEARCH_ONLY_IDS = ("M10-PA-006", "M10-PA-016")
M10_1_ALLOWED_WAVE_A_OUTCOMES = (
    "needs_definition_fix",
    "needs_visual_review",
    "continue_testing",
    "reject_for_now",
)
M10_3_NOT_ALLOWED = (
    "retain",
    "promote",
    "live_execution",
    "broker_connection",
    "real_orders",
)
M10_3_COST_MODEL_POLICY = {
    "policy_basis": "sensitivity_policy_only_no_broker_fee_claim",
    "price_impact_model": "fixed_bps_per_entry_and_exit_for_m10_4_pilot_sensitivity",
    "sensitivity_tiers": [
        {"tier": "baseline", "slippage_bps": 1, "fee_per_order": 0},
        {"tier": "stress_low", "slippage_bps": 2, "fee_per_order": 0},
        {"tier": "stress_high", "slippage_bps": 5, "fee_per_order": 0},
    ],
    "m10_3_limit": "freeze_policy_only_do_not_run_or_interpret_backtest_results",
}
M10_3_SAMPLE_GATE_POLICY = {
    "minimum_candidate_events_per_strategy_timeframe": 30,
    "minimum_executed_trades_after_skips_per_strategy_timeframe": 10,
    "below_gate_allowed_outcomes": ["continue_testing", "needs_definition_fix"],
    "allowed_outcomes_after_gate": list(M10_1_ALLOWED_WAVE_A_OUTCOMES),
    "retain_or_promote_allowed": False,
    "interpretation_rule": "sample_gate_permits_quality_interpretation_only_not_profitability_claims",
}
M10_3_SPEC_RULES = {
    "M10-PA-001": {
        "event_name": "trend_pullback_second_entry_continuation",
        "event_definition": {
            "ohlcv_approximation": "Trend, pullback, and second-entry are approximated from swing sequence, bar closes, and a 20-bar simple moving average.",
            "trend_context": {
                "lookback_bars": 20,
                "long_tests": [
                    "higher_high_higher_low_sequence_or_close_above_20_sma",
                    "most_recent_impulse_leg_has_directional_close",
                ],
                "short_tests": [
                    "lower_high_lower_low_sequence_or_close_below_20_sma",
                    "most_recent_impulse_leg_has_directional_close",
                ],
            },
            "pullback": {
                "min_countertrend_bars": 2,
                "allow_implied_pullback": True,
                "must_not_break_trend_invalidation_extreme": True,
            },
            "second_entry": {
                "approximation": "After the first pullback attempt fails to reverse the trend, require a second signal in the trend direction before creating a candidate event.",
                "long_trigger_structure": "H2_or_second_higher_low_signal_after_pullback",
                "short_trigger_structure": "L2_or_second_lower_high_signal_after_pullback",
            },
            "signal_bar": {
                "long": "bull_signal_bar_or_close_above_prior_bar_high_after_second_entry",
                "short": "bear_signal_bar_or_close_below_prior_bar_low_after_second_entry",
            },
        },
        "entry_rules": [
            "Create a long candidate when price closes above the signal-bar high after a valid second-entry pullback in an uptrend.",
            "Create a short candidate when price closes below the signal-bar low after a valid second-entry pullback in a downtrend.",
            "M10.4 fill convention must use next-bar-open after the trigger bar unless the pilot runner explicitly logs a different deterministic convention.",
        ],
        "stop_rules": [
            "Initial structural stop is beyond the pullback extreme.",
            "If signal-bar extreme is farther than the pullback extreme, log both and use the wider structural stop for risk notes.",
        ],
        "target_rules": [
            "Record 1R and 2R targets for sensitivity.",
            "Record prior swing high/low and measured-leg objective as non-promotional target labels.",
            "Do not treat target hit frequency as a retain/promote conclusion in M10.3.",
        ],
        "skip_rules": [
            {"skip_code": "m10_001_no_clear_trend", "reason": "20-bar context does not show trend sequence or clear close relative to 20 SMA."},
            {"skip_code": "m10_001_tight_trading_range", "reason": "Pullback occurs inside a narrow overlapping range with no trend resumption evidence."},
            {"skip_code": "m10_001_opposite_breakout", "reason": "Strong opposite breakout with follow-through cancels the continuation premise."},
            {"skip_code": "m10_001_insufficient_bar_count", "reason": "Not enough bars to evaluate trend, pullback, and second-entry sequence."},
        ],
    },
    "M10-PA-002": {
        "event_name": "breakout_follow_through_continuation",
        "event_definition": {
            "ohlcv_approximation": "Breakout and follow-through are approximated from a prior 20-bar range, breakout-bar body size, close location, and next 1-2 bars.",
            "breakout_range": {
                "lookback_bars": 20,
                "long_level": "prior_20_bar_high",
                "short_level": "prior_20_bar_low",
            },
            "breakout_bar": {
                "must_close_outside_prior_range": True,
                "body_to_true_range_min": 0.5,
                "directional_close_zone": "outer_third_of_bar_range",
            },
            "follow_through": {
                "window_bars": 2,
                "long": "at_least_one_follow_through_close_above_breakout_level_and_no_close_back_inside_range",
                "short": "at_least_one_follow_through_close_below_breakout_level_and_no_close_back_inside_range",
            },
        },
        "entry_rules": [
            "Create a long candidate after a qualified upside breakout bar and follow-through confirmation within the next 1-2 bars.",
            "Create a short candidate after a qualified downside breakout bar and follow-through confirmation within the next 1-2 bars.",
            "M10.4 fill convention must use next-bar-open after follow-through confirmation.",
        ],
        "stop_rules": [
            "Initial structural stop is the opposite extreme of the breakout bar.",
            "Also record breakout-leg extreme when it is wider than the breakout-bar stop.",
        ],
        "target_rules": [
            "Record 1R and 2R targets for sensitivity.",
            "Record measured move from prior 20-bar range height.",
            "Record prior support/resistance magnets when available from OHLCV-derived swing levels.",
        ],
        "skip_rules": [
            {"skip_code": "m10_002_weak_breakout_bar", "reason": "Breakout bar body is below 50% of true range or close is not in the directional third."},
            {"skip_code": "m10_002_no_follow_through", "reason": "No confirmation close within the next 1-2 bars."},
            {"skip_code": "m10_002_immediate_range_reentry", "reason": "Price closes back inside the prior range before confirmation."},
            {"skip_code": "m10_002_range_too_narrow_for_costs", "reason": "Prior range height is too small to evaluate after cost/slippage tiers."},
        ],
    },
    "M10-PA-005": {
        "event_name": "trading_range_failed_breakout_reversal",
        "event_definition": {
            "ohlcv_approximation": "Trading range and failed breakout are approximated from a 20-bar overlapping range, outside-edge attempt, and close back inside within 1-3 bars.",
            "trading_range": {
                "min_bars": 20,
                "requires_overlapping_high_low_structure": True,
                "no_sustained_close_outside_range": True,
            },
            "breakout_attempt": {
                "long_failure_setup": "price_trades_or_closes_above_range_high",
                "short_failure_setup": "price_trades_or_closes_below_range_low",
            },
            "failure_confirmation": {
                "window_bars": 3,
                "long_failure_short_entry_context": "close_back_inside_range_after_upside_breakout_attempt",
                "short_failure_long_entry_context": "close_back_inside_range_after_downside_breakout_attempt",
            },
        },
        "entry_rules": [
            "Create a short candidate when an upside range breakout fails and price closes back inside the range within 1-3 bars.",
            "Create a long candidate when a downside range breakout fails and price closes back inside the range within 1-3 bars.",
            "M10.4 fill convention must use next-bar-open after the re-entry confirmation bar.",
        ],
        "stop_rules": [
            "Initial structural stop is beyond the failed breakout extreme.",
            "Log range edge and failed breakout extreme separately for failure-mode review.",
        ],
        "target_rules": [
            "Primary target label is the range midpoint.",
            "Opposite range side is a runner label only and must not be required for candidate validity.",
            "Record 1R and 2R targets for sensitivity.",
        ],
        "skip_rules": [
            {"skip_code": "m10_005_no_mature_range", "reason": "Range has fewer than 20 bars or does not show overlapping two-sided structure."},
            {"skip_code": "m10_005_breakout_not_failed", "reason": "Breakout has follow-through or does not close back inside within 1-3 bars."},
            {"skip_code": "m10_005_ambiguous_range_bounds", "reason": "Range high/low cannot be determined from OHLCV without after-the-fact selection."},
            {"skip_code": "m10_005_range_height_unsuitable", "reason": "Range is too narrow for costs or too wide for the configured risk budget."},
        ],
    },
    "M10-PA-012": {
        "event_name": "opening_range_breakout",
        "event_definition": {
            "ohlcv_approximation": "Opening range breakout uses regular-session OHLCV, first 30 minutes of the session, breakout strength, and next 1-2 bars of follow-through.",
            "session": {
                "regular_session_only": True,
                "opening_range_minutes": 30,
                "5m_opening_range_bars": 6,
                "15m_opening_range_bars": 2,
                "requires_complete_session_metadata": True,
            },
            "breakout_bar": {
                "must_close_outside_opening_range": True,
                "body_to_true_range_min": 0.5,
                "directional_close_zone": "outer_third_of_bar_range",
            },
            "follow_through": {
                "window_bars": 2,
                "must_hold_outside_or_extend_opening_range": True,
            },
        },
        "entry_rules": [
            "Create a long candidate when price closes above the first-30-minute opening range and confirms within the next 1-2 bars.",
            "Create a short candidate when price closes below the first-30-minute opening range and confirms within the next 1-2 bars.",
            "M10.4 fill convention must use next-bar-open after follow-through confirmation.",
        ],
        "stop_rules": [
            "Initial structural stop is back inside the opening range or beyond the breakout-leg extreme, whichever is structurally wider.",
            "Log opening range high/low and breakout-leg extreme separately.",
        ],
        "target_rules": [
            "Primary target label is opening range height measured move.",
            "Record 1R and 2R targets for sensitivity.",
            "Prior-day magnets may be recorded only when the pilot data source provides prior-session levels.",
        ],
        "skip_rules": [
            {"skip_code": "m10_012_incomplete_session", "reason": "Missing regular-session open, timezone, or first-30-minute bars."},
            {"skip_code": "m10_012_range_too_narrow_for_costs", "reason": "Opening range is too narrow for cost/slippage tiers."},
            {"skip_code": "m10_012_range_too_wide_for_risk", "reason": "Opening range stop distance exceeds the pilot risk budget."},
            {"skip_code": "m10_012_failed_orb_routed_elsewhere", "reason": "Failed ORB is routed to Opening Reversal or Trading Range Failed Breakout queues, not executed here."},
        ],
    },
}
M10_1_VISUAL_CASE_REQUIREMENTS = {
    "positive_cases": 3,
    "negative_cases": 1,
    "boundary_cases": 1,
    "required_fields": (
        "brooks_v2_evidence_image_or_source_ref",
        "counterexample_source_ref",
        "boundary_case_source_ref",
        "pattern_decision_points",
        "ohlcv_approximation_risk",
    ),
}
M10_1_REQUIRED_OUTPUTS = (
    "candidate_events",
    "skip_no_trade_ledger",
    "source_ledger",
    "cost_slippage_sensitivity",
    "per_symbol_breakdown",
    "per_regime_breakdown",
    "failure_mode_notes",
)
M10_1_FUTURE_HANDOFFS = (
    {
        "stage": "M10.2",
        "name": "Visual Golden Case Pack",
        "handoff": "为高视觉策略建立 Brooks v2 正例、反例、边界例和人工复核记录。",
    },
    {
        "stage": "M10.3",
        "name": "Backtest Spec Freeze",
        "handoff": "为 Wave A 策略冻结事件识别、skip 规则、成本、样本门槛和失败标准。",
    },
    {
        "stage": "M10.4",
        "name": "Historical Backtest Pilot",
        "handoff": "只跑 Wave A 小范围 pilot，验证事件识别、ledger 和成本敏感性，不证明盈利。",
    },
    {
        "stage": "M10.5",
        "name": "Read-only Observation Plan",
        "handoff": "pilot 合格后才设计实时只读观察；仍不接 broker、不下单。",
    },
    {
        "stage": "M11",
        "name": "Paper Trading Candidate Gate",
        "handoff": "historical pilot、visual review、实时只读观察达标后才讨论 paper trading。",
    },
)
M10_2_VISUAL_CASE_TYPES = ("positive", "counterexample", "boundary")
M10_2_VISUAL_CASE_COUNTS = {
    "positive": 3,
    "counterexample": 1,
    "boundary": 1,
}
M10_2_GENERIC_BOUNDARY_TERMS = (
    "sometimes",
    "usually",
    "can be",
    "if",
    "difficult",
    "almost",
    "可能",
    "通常",
    "如果",
    "边界",
)
M10_2_STRATEGY_CASE_TERMS = {
    "M10-PA-003": {
        "positive": ("tight channel", "small pullback", "micro channel", "higher time frame", "only look", "紧密通道", "小回调"),
        "counterexample": ("first reversal", "minor reversal", "trading range", "broad", "too late", "第一次反转"),
        "boundary": ("difficult to know", "not much space", "usually", "if cannot", "sometimes"),
    },
    "M10-PA-004": {
        "positive": ("broad channel", "channel line", "limit orders", "fade test", "2nd leg trap", "second leg trap", "宽通道"),
        "counterexample": ("tight channel", "breakouts at start of trend", "strong breakout", "follow-through"),
        "boundary": ("reversals", "some just", "usually", "limit orders", "breakouts"),
    },
    "M10-PA-007": {
        "positive": ("2nd leg trap", "second leg trap", "trapped", "failed", "breakout mode", "交易区间"),
        "counterexample": ("eventually break out into trend", "trend", "successful breakout", "50% chance"),
        "boundary": ("breakout mode", "both bull and bear", "buy and sell setups", "50% chance"),
    },
    "M10-PA-008": {
        "positive": ("major trend reversal", "mtr", "requirements", "trendline", "test", "主要趋势反转"),
        "counterexample": ("minor reversal", "failed mtr", "too tight", "minor"),
        "boundary": ("requirements", "most reversal patterns", "trading ranges", "probability"),
    },
    "M10-PA-009": {
        "positive": ("wedge", "wedge flag", "triangle", "three pushes", "parabolic", "楔形"),
        "counterexample": ("failed wedge", "bad wedge", "early entry", "failed"),
        "boundary": ("can be flag", "major trend reversal", "imperfect", "variations", "context"),
    },
    "M10-PA-010": {
        "positive": ("final flag", "climax", "exhaustion", "climactic reversal", "tbtl", "高潮"),
        "counterexample": ("failed consecutive", "without reversal", "every trend bar", "continues"),
        "boundary": ("acceleration", "usually fails", "options", "support resistance", "measuring"),
    },
    "M10-PA-011": {
        "positive": ("opening reversals", "open", "yesterday", "gap", "early flags", "开盘"),
        "counterexample": ("strong trend day", "one direction", "opening trend", "breakout"),
        "boundary": ("3 parts to the day", "most days", "context", "gap openings"),
    },
}


@dataclass(frozen=True)
class SourceDoc:
    family: str
    source_ref: str
    locator: dict[str, Any]
    title: str
    text: str


@dataclass(frozen=True)
class StrategySeed:
    strategy_id: str
    title: str
    keywords: tuple[str, ...]
    market_context: tuple[str, ...]
    direction: str
    timeframes: tuple[str, ...]
    entry_logic: tuple[str, ...]
    stop_logic: tuple[str, ...]
    target_logic: tuple[str, ...]
    invalidation: tuple[str, ...]
    no_trade_conditions: tuple[str, ...]
    visual_dependency: str
    ohlcv_approximable: bool
    default_status: str
    bpa_refs: tuple[str, ...]


STRATEGY_SEEDS: tuple[StrategySeed, ...] = (
    StrategySeed(
        strategy_id="M10-PA-001",
        title="Trend Pullback Second-Entry Continuation",
        keywords=("pullback", "second entry", "high 2", "low 2", "h2", "l2", "two legs", "回调", "第二", "二次入场"),
        market_context=("trend", "pullback", "always-in direction"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=(
            "Only trade in the active trend direction after a pullback has formed a second-entry structure.",
            "Prefer signal bars near the moving average, prior breakout point, or channel support/resistance.",
        ),
        stop_logic=("Protect beyond the pullback extreme or signal-bar extreme.",),
        target_logic=("Initial target uses prior swing test or measured leg; runner can trail under higher lows/lower highs.",),
        invalidation=("A strong opposite breakout with follow-through cancels the continuation premise.",),
        no_trade_conditions=("Tight trading range without trend resumption evidence.", "Second entry against a strong channel without reversal proof."),
        visual_dependency="medium",
        ohlcv_approximable=True,
        default_status="backtest_candidate",
        bpa_refs=("BPA-001",),
    ),
    StrategySeed(
        strategy_id="M10-PA-002",
        title="Breakout Follow-Through Continuation",
        keywords=("breakout", "follow-through", "2nd bar", "second bar", "strong breakout", "突破", "后续", "跟进"),
        market_context=("breakout", "trend resumption", "breakout mode"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=(
            "Enter with the breakout only when the breakout bar is strong and at least one follow-through bar supports it.",
            "A small-start breakout is acceptable if subsequent bars create a tight channel or higher-timeframe trend bar.",
        ),
        stop_logic=("Use the breakout leg extreme or a volatility-adjusted stop; reduce size when stop distance is large.",),
        target_logic=("Use measured move from the breakout range and partial exits at prior support/resistance magnets.",),
        invalidation=("Follow-through bar reverses strongly or closes back inside the breakout range.",),
        no_trade_conditions=("Weak breakout in a trading range with no second bar confirmation.",),
        visual_dependency="medium",
        ohlcv_approximable=True,
        default_status="backtest_candidate",
        bpa_refs=("BPA-002", "BPA-015"),
    ),
    StrategySeed(
        strategy_id="M10-PA-003",
        title="Tight Channel Trend Continuation",
        keywords=("tight channel", "micro channel", "small pullback", "紧密通道", "小回调", "channel"),
        market_context=("tight channel", "trend", "small pullback trend"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=(
            "Trade with the channel direction after small pullbacks, avoiding early countertrend fades.",
            "Treat first reversal attempts as minor unless there is a strong breakout of the channel.",
        ),
        stop_logic=("Protect beyond the recent channel pullback extreme; avoid oversizing because channels can accelerate.",),
        target_logic=("Trail with channel structure; initial target at prior extreme or measured channel leg.",),
        invalidation=("Clear channel break followed by opposite follow-through.",),
        no_trade_conditions=("Late entry after a climactic channel extension without room to target.",),
        visual_dependency="high",
        ohlcv_approximable=True,
        default_status="backtest_candidate",
        bpa_refs=("BPA-003",),
    ),
    StrategySeed(
        strategy_id="M10-PA-004",
        title="Broad Channel Boundary Reversal",
        keywords=("broad channel", "channel line", "second leg trap", "higher low", "lower high", "宽通道", "通道边界", "第二腿陷阱"),
        market_context=("broad channel", "two-sided trading", "boundary test"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=(
            "Fade broad-channel boundary tests only after a failed second push or trapped breakout attempt.",
            "Require evidence that the boundary is broad and two-sided, not a tight trend channel.",
        ),
        stop_logic=("Protect beyond the tested channel extreme.",),
        target_logic=("Target midline, prior swing, or opposite broad-channel boundary depending on volatility.",),
        invalidation=("Strong breakout beyond the boundary with follow-through.",),
        no_trade_conditions=("Boundary fade against a tight channel or strong always-in trend.",),
        visual_dependency="high",
        ohlcv_approximable=True,
        default_status="visual_review_then_backtest",
        bpa_refs=("BPA-004",),
    ),
    StrategySeed(
        strategy_id="M10-PA-005",
        title="Trading Range Failed Breakout Reversal",
        keywords=("trading range", "failed breakout", "range edge", "fade breakout", "失败突破", "交易区间", "区间边缘"),
        market_context=("trading range", "failed breakout", "range edge"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=(
            "Fade failed breakouts at the range edge after price returns inside the range and the breakout lacks follow-through.",
            "Prefer entries when breakout traders are trapped and there is enough room back toward the range midpoint.",
        ),
        stop_logic=("Protect beyond the failed breakout extreme.",),
        target_logic=("Use range midpoint first, then opposite side if two-sided pressure persists.",),
        invalidation=("Successful breakout with follow-through and measured-move projection.",),
        no_trade_conditions=("Early fade before the breakout has actually failed.",),
        visual_dependency="medium",
        ohlcv_approximable=True,
        default_status="backtest_candidate",
        bpa_refs=("BPA-005", "BPA-006", "BPA-017"),
    ),
    StrategySeed(
        strategy_id="M10-PA-006",
        title="Trading Range BLSHS Limit-Order Framework",
        keywords=("blshs", "buy low sell high scalp", "limit order", "trading range", "限价单", "低买高卖", "交易区间"),
        market_context=("trading range", "limit order market", "scalping"),
        direction="both",
        timeframes=("1h", "15m", "5m"),
        entry_logic=(
            "In a mature trading range, buy low and sell high with limit-order logic rather than breakout-chasing.",
            "Only research this as a framework until range maturity and transaction-cost assumptions are frozen.",
        ),
        stop_logic=("Protect beyond the range edge or abandon if the range converts to a trend.",),
        target_logic=("Scalp toward the range midpoint or opposite edge; costs and slippage are first-order constraints.",),
        invalidation=("Breakout converts into trend with follow-through.",),
        no_trade_conditions=("Immature range, news shock, or insufficient spread/cost margin.",),
        visual_dependency="high",
        ohlcv_approximable=False,
        default_status="research_only",
        bpa_refs=("BPA-007", "BPA-020"),
    ),
    StrategySeed(
        strategy_id="M10-PA-007",
        title="Second-Leg Trap Reversal",
        keywords=("second leg trap", "trap", "trapped", "second entry", "failed second", "第二腿陷阱", "陷阱"),
        market_context=("trap", "two-legged move", "failed continuation"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=(
            "Enter against the failed second leg when trapped traders are forced to exit and the reversal bar has context.",
            "Prefer traps near support/resistance, moving average, or channel boundary.",
        ),
        stop_logic=("Protect beyond the trap extreme.",),
        target_logic=("Target prior swing or measured move back through the failed leg.",),
        invalidation=("Second leg resumes strongly with follow-through.",),
        no_trade_conditions=("Trap label without visible trapped-trader evidence.",),
        visual_dependency="high",
        ohlcv_approximable=True,
        default_status="visual_review_then_backtest",
        bpa_refs=("BPA-008",),
    ),
    StrategySeed(
        strategy_id="M10-PA-008",
        title="Major Trend Reversal",
        keywords=("major trend reversal", "mtr", "moving average gap bar", "trend reversal", "主要趋势反转", "反转"),
        market_context=("trend exhaustion", "major reversal", "support resistance"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=(
            "Require a prior trend, a break of trendline/channel, and a test forming a credible higher low/lower high or failed final push.",
            "Do not treat the first countertrend bar as sufficient proof.",
        ),
        stop_logic=("Protect beyond the reversal extreme; wider initial risk may be required.",),
        target_logic=("Minimum target is the prior major swing or measured move; partials before major support/resistance.",),
        invalidation=("Original trend resumes with strong breakout and follow-through.",),
        no_trade_conditions=("Minor reversal inside a tight channel.",),
        visual_dependency="high",
        ohlcv_approximable=True,
        default_status="visual_review_then_backtest",
        bpa_refs=("BPA-009",),
    ),
    StrategySeed(
        strategy_id="M10-PA-009",
        title="Wedge Reversal and Wedge Flag",
        keywords=("wedge", "wedge flag", "parabolic wedge", "three pushes", "楔形", "三推"),
        market_context=("wedge", "three pushes", "climax or flag"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=(
            "Trade a wedge only after three pushes are visible in context and the reversal signal is strong enough.",
            "Classify whether the wedge is reversal, flag, or failed wedge before backtest eligibility.",
        ),
        stop_logic=("Protect beyond the third push extreme.",),
        target_logic=("Target two-legged correction or measured move from wedge height depending on context.",),
        invalidation=("Failed wedge breakout with follow-through in the original direction.",),
        no_trade_conditions=("Forcing wedge labels onto overlapping noise.",),
        visual_dependency="high",
        ohlcv_approximable=True,
        default_status="visual_review_then_backtest",
        bpa_refs=("BPA-010",),
    ),
    StrategySeed(
        strategy_id="M10-PA-010",
        title="Final Flag or Climax TBTL Reversal",
        keywords=("final flag", "climax", "two bars two legs", "tbtl", "exhaustion", "末端旗形", "高潮"),
        market_context=("late trend", "climax", "final flag"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=(
            "Look for late-trend final flag or climax behavior, then require a reversal entry with follow-through.",
            "Treat TBTL as a testing and review hypothesis, not a standalone entry without context.",
        ),
        stop_logic=("Protect beyond the climax/final-flag extreme.",),
        target_logic=("Target two legs or a test of the prior breakout point.",),
        invalidation=("Climax continues as a strong trend without reversal follow-through.",),
        no_trade_conditions=("Countertrend entry before the trend shows exhaustion.",),
        visual_dependency="high",
        ohlcv_approximable=True,
        default_status="visual_review_then_backtest",
        bpa_refs=("BPA-012", "BPA-013"),
    ),
    StrategySeed(
        strategy_id="M10-PA-011",
        title="Opening Reversal",
        keywords=("trading the open", "opening reversal", "yesterday", "gap opening", "开盘", "开盘反转"),
        market_context=("session open", "gap or prior-day test", "opening reversal"),
        direction="both",
        timeframes=("15m", "5m"),
        entry_logic=(
            "At the session open, require a failed test of prior-day levels, opening range, or gap context before reversal entry.",
            "Separate this from daily strategy tests because session microstructure is primary.",
        ),
        stop_logic=("Protect beyond opening extreme or failed test level.",),
        target_logic=("Target opening range midpoint, prior-day level, or measured opening swing.",),
        invalidation=("Opening trend breakout with follow-through.",),
        no_trade_conditions=("No clean prior-day or opening-range context.",),
        visual_dependency="high",
        ohlcv_approximable=True,
        default_status="visual_review_then_backtest",
        bpa_refs=("BPA-014",),
    ),
    StrategySeed(
        strategy_id="M10-PA-012",
        title="Opening Range Breakout",
        keywords=("opening range", "breakout mode", "trading the open", "开盘区间", "突破模式"),
        market_context=("session open", "opening range", "breakout mode"),
        direction="both",
        timeframes=("15m", "5m"),
        entry_logic=(
            "Define the opening range first, then require breakout strength and follow-through before continuation entry.",
            "Failed opening range breakouts route to the Opening Reversal or Trading Range failed-breakout queue.",
        ),
        stop_logic=("Protect back inside the opening range or beyond the breakout leg.",),
        target_logic=("Use opening range height and prior-day magnets.",),
        invalidation=("Breakout fails back into the range without follow-through.",),
        no_trade_conditions=("Range too narrow for costs or too wide for risk budget.",),
        visual_dependency="medium",
        ohlcv_approximable=True,
        default_status="backtest_candidate",
        bpa_refs=("BPA-015",),
    ),
    StrategySeed(
        strategy_id="M10-PA-013",
        title="Support and Resistance Failed Test",
        keywords=("support resistance", "failed test", "magnet", "prior high", "prior low", "支撑", "阻力", "失败测试"),
        market_context=("support resistance", "failed test", "magnet"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=(
            "Use prior high/low, round number, moving average, or measured-move level as the test area.",
            "Enter only after the test fails and price returns with a signal bar or follow-through.",
        ),
        stop_logic=("Protect beyond the failed test extreme.",),
        target_logic=("Target next magnet, range midpoint, or measured-move objective.",),
        invalidation=("Clean breakout through the level with follow-through.",),
        no_trade_conditions=("Level selected after the fact or too imprecise for a test rule.",),
        visual_dependency="medium",
        ohlcv_approximable=True,
        default_status="backtest_candidate",
        bpa_refs=("BPA-017",),
    ),
    StrategySeed(
        strategy_id="M10-PA-014",
        title="Measured Move Target Engine",
        keywords=("measured move", "leg 1 equals leg 2", "target", "profit target", "测量移动", "目标"),
        market_context=("targeting", "trade management", "measured move"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=("This is a target/risk module attached to eligible setup strategies, not a standalone entry.",),
        stop_logic=("No independent stop; inherits parent setup risk.",),
        target_logic=("Compute leg-based, range-height, and breakout-height measured move objectives.",),
        invalidation=("Parent setup invalidates or measured move conflicts with closer major magnet.",),
        no_trade_conditions=("Do not use as an entry trigger.",),
        visual_dependency="medium",
        ohlcv_approximable=True,
        default_status="supporting_rule",
        bpa_refs=("BPA-018",),
    ),
    StrategySeed(
        strategy_id="M10-PA-015",
        title="Protective Stops and Position Sizing",
        keywords=("protective stop", "position size", "actual risk", "wide stop", "risk", "止损", "仓位", "风险"),
        market_context=("risk", "trade management", "position sizing"),
        direction="both",
        timeframes=("1d", "1h", "15m", "5m"),
        entry_logic=("This is a risk-control module required before any historical backtest is promoted.",),
        stop_logic=("Stops must be structurally valid first, then sized to fixed risk budget.",),
        target_logic=("Targets must be evaluated against actual risk and cost assumptions.",),
        invalidation=("If structural stop exceeds risk budget, strategy must skip or reduce size.",),
        no_trade_conditions=("No trade when stop is arbitrary or position size would exceed risk limits.",),
        visual_dependency="medium",
        ohlcv_approximable=True,
        default_status="supporting_rule",
        bpa_refs=("BPA-019",),
    ),
    StrategySeed(
        strategy_id="M10-PA-016",
        title="Trading Range Scaling-In Research",
        keywords=("scaling in", "scale in", "trading range", "losing positions", "加仓", "交易区间"),
        market_context=("trading range", "scaling in", "risk research"),
        direction="both",
        timeframes=("1h", "15m", "5m"),
        entry_logic=(
            "Only document scaling-in behavior as research until hard risk, capital, and range-maturity limits are specified.",
        ),
        stop_logic=("Requires explicit maximum loss and no averaging-down path before any simulation.",),
        target_logic=("Research target only; no execution queue in M10.",),
        invalidation=("Any path that increases exposure without bounded loss remains blocked.",),
        no_trade_conditions=("All live, broker, or real-money usage is out of scope.",),
        visual_dependency="high",
        ohlcv_approximable=False,
        default_status="research_only",
        bpa_refs=("BPA-020",),
    ),
)


CHATGPT_BPA_REFERENCE = {
    "BPA-001": "趋势中两腿回调顺势入场",
    "BPA-002": "强突破 + 跟进顺势入场",
    "BPA-003": "紧密通道顺势策略",
    "BPA-004": "宽通道边界反转策略",
    "BPA-005": "交易区间顶部失败突破做空",
    "BPA-006": "交易区间底部失败突破做多",
    "BPA-007": "交易区间 BLSHS 限价单策略",
    "BPA-008": "强第二腿陷阱反转策略",
    "BPA-009": "主要趋势反转 MTR 策略",
    "BPA-010": "楔形反转 / 楔形旗形策略",
    "BPA-011": "双顶双底失败后反向策略",
    "BPA-012": "Final Flag 末端旗形反转策略",
    "BPA-013": "高潮后 TBTL 策略",
    "BPA-014": "Opening Reversal 开盘反转策略",
    "BPA-015": "Opening Range Breakout 开盘区间突破策略",
    "BPA-016": "尾盘趋势恢复 / 尾盘突破策略",
    "BPA-017": "支撑阻力失败测试策略",
    "BPA-018": "Measured Move 目标与止盈策略",
    "BPA-019": "保护性止损与仓位缩放规则",
    "BPA-020": "交易区间加仓策略，暂时只研究不执行",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def assert_clean_room_inputs(paths: list[Path]) -> None:
    resolved_forbidden = [path.resolve() for path in FORBIDDEN_CLEAN_ROOM_READ_PATHS]
    for path in paths:
        resolved = path.resolve()
        for forbidden in resolved_forbidden:
            if resolved == forbidden or forbidden in resolved.parents:
                raise ValueError(f"clean-room extraction attempted to read legacy path: {path}")


def classify_support_for_strategy(source_families: set[str]) -> dict[str, str]:
    if "brooks_v2_manual_transcript" in source_families:
        confidence = "high" if len(source_families & HIGH_PRIORITY_SOURCE_FAMILIES) > 1 else "medium"
        return {
            "support_level": "high_priority_supported",
            "confidence": confidence,
            "policy_decision": "eligible_from_brooks_v2_without_cross_source_requirement",
        }
    if "fangfangtu_youtube_transcript" in source_families:
        confidence = "medium"
        return {
            "support_level": "high_priority_supported",
            "confidence": confidence,
            "policy_decision": "eligible_from_youtube_without_cross_source_requirement",
        }
    if "fangfangtu_notes" in source_families:
        return {
            "support_level": "notes_only",
            "confidence": "low",
            "policy_decision": "downgrade_to_needs_corroboration",
        }
    return {
        "support_level": "unsupported",
        "confidence": "low",
        "policy_decision": "blocked_no_high_priority_source",
    }


def keyword_matches(text: str, keywords: tuple[str, ...]) -> tuple[int, list[str]]:
    lowered = text.lower()
    matched: list[str] = []
    score = 0
    for keyword in keywords:
        needle = keyword.lower()
        count = lowered.count(needle)
        if count:
            matched.append(keyword)
            score += count
    return score, matched


def excerpt_for(text: str, matches: list[str], limit: int = 220) -> str:
    normalized = normalize(text)
    if not normalized:
        return ""
    lowered = normalized.lower()
    start = 0
    for match in matches:
        index = lowered.find(match.lower())
        if index >= 0:
            start = max(index - 60, 0)
            break
    return normalized[start : start + limit]


def source_ref(path: Path) -> str:
    return f"raw:{path.relative_to(PROJECT_ROOT).as_posix()}"


def collect_brooks_v2_docs(root: Path = BROOKS_V2_ROOT) -> list[SourceDoc]:
    units_dir = root / "units"
    assert_clean_room_inputs([units_dir])
    docs: list[SourceDoc] = []
    for path in sorted(units_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        title = next((line.lstrip("#").strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
        docs.append(
            SourceDoc(
                family="brooks_v2_manual_transcript",
                source_ref=source_ref(path),
                locator={"kind": "markdown_unit", "path": path.relative_to(root).as_posix()},
                title=title,
                text=text,
            )
        )
    return docs


def collect_pdf_docs(path: Path, family: str, title_prefix: str) -> list[SourceDoc]:
    assert_clean_room_inputs([path])
    if PdfReader is None or not path.exists():
        return []
    docs: list[SourceDoc] = []
    try:
        reader = PdfReader(str(path))
    except Exception:
        return []
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if not normalize(text):
            continue
        docs.append(
            SourceDoc(
                family=family,
                source_ref=source_ref(path),
                locator={"kind": "pdf_page", "page_no": page_index},
                title=f"{title_prefix} p{page_index}",
                text=text,
            )
        )
    return docs


def collect_clean_room_docs() -> list[SourceDoc]:
    docs = collect_brooks_v2_docs()
    docs.extend(
        collect_pdf_docs(
            PROJECT_ROOT / "knowledge" / "raw" / "youtube" / "fangfangtu" / "transcripts" / "Price_Action方方土.pdf",
            "fangfangtu_youtube_transcript",
            "fangfangtu YouTube transcript",
        )
    )
    notes_dir = PROJECT_ROOT / "knowledge" / "raw" / "notes"
    assert_clean_room_inputs([notes_dir])
    for path in sorted(notes_dir.glob("*.pdf")):
        docs.extend(collect_pdf_docs(path, "fangfangtu_notes", path.stem))
    return docs


def rank_support(seed: StrategySeed, docs: list[SourceDoc], family: str, limit: int) -> list[dict[str, Any]]:
    scored: list[tuple[int, SourceDoc, list[str]]] = []
    for doc in docs:
        if doc.family != family:
            continue
        haystack = f"{doc.title}\n{doc.source_ref}\n{doc.text}"
        score, matched = keyword_matches(haystack, seed.keywords)
        if score > 0:
            scored.append((score, doc, matched))
    scored.sort(key=lambda item: (-item[0], item[1].source_ref, json.dumps(item[1].locator, sort_keys=True)))
    return [
        {
            "source_family": doc.family,
            "source_ref": doc.source_ref,
            "locator": doc.locator,
            "title": doc.title,
            "matched_keywords": matched,
            "score": score,
            "excerpt": excerpt_for(doc.text, matched),
        }
        for score, doc, matched in scored[:limit]
    ]


def build_catalog_from_docs(docs: list[SourceDoc]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    catalog: list[dict[str, Any]] = []
    support_matrix: list[dict[str, Any]] = []
    visual_gap_ledger: list[dict[str, Any]] = []
    backtest_matrix: list[dict[str, Any]] = []
    asset_root = BROOKS_V2_ROOT / "assets" / "evidence"

    for seed in STRATEGY_SEEDS:
        support_by_family = {
            family: rank_support(seed, docs, family, 3 if family == "brooks_v2_manual_transcript" else 2)
            for family in SOURCE_PRIORITY
        }
        supported_families = {family for family, entries in support_by_family.items() if entries}
        support_policy = classify_support_for_strategy(supported_families)
        primary_family = next((family for family in SOURCE_PRIORITY if support_by_family[family]), "")
        status = seed.default_status
        if support_policy["support_level"] == "notes_only":
            status = "needs_corroboration"
        elif support_policy["support_level"] == "unsupported":
            status = "blocked_source_gap"

        source_refs = [
            {
                "source_family": entry["source_family"],
                "source_ref": entry["source_ref"],
                "locator": entry["locator"],
                "title": entry["title"],
                "matched_keywords": entry["matched_keywords"],
            }
            for family in SOURCE_PRIORITY
            for entry in support_by_family[family]
        ]
        catalog.append(
            {
                "strategy_id": seed.strategy_id,
                "namespace": "M10-PA",
                "title": seed.title,
                "status": status,
                "source_priority_basis": primary_family,
                "support_level": support_policy["support_level"],
                "confidence": support_policy["confidence"],
                "policy_decision": support_policy["policy_decision"],
                "source_refs": source_refs,
                "source_families": sorted(supported_families, key=SOURCE_PRIORITY.index),
                "market_context": list(seed.market_context),
                "timeframes": list(seed.timeframes),
                "direction": seed.direction,
                "entry_logic": list(seed.entry_logic),
                "stop_logic": list(seed.stop_logic),
                "target_logic": list(seed.target_logic),
                "invalidation": list(seed.invalidation),
                "no_trade_conditions": list(seed.no_trade_conditions),
                "visual_dependency": seed.visual_dependency,
                "backtest_eligibility": {
                    "ohlcv_approximable": seed.ohlcv_approximable,
                    "eligible_for_historical_backtest": (
                        seed.ohlcv_approximable
                        and support_policy["support_level"] == "high_priority_supported"
                        and seed.default_status not in {"research_only", "supporting_rule"}
                    ),
                    "route": backtest_route(seed, support_policy["support_level"]),
                },
                "clean_room_guard": {
                    "legacy_ids_used_in_extraction": [],
                    "forbidden_legacy_inputs": [path.relative_to(PROJECT_ROOT).as_posix() for path in FORBIDDEN_CLEAN_ROOM_READ_PATHS],
                },
                "chatgpt_bpa_reference_overlap": list(seed.bpa_refs),
            }
        )
        support_matrix.append(
            {
                "strategy_id": seed.strategy_id,
                "title": seed.title,
                "support_counts": {family: len(entries) for family, entries in support_by_family.items()},
                "supported_families": sorted(supported_families, key=SOURCE_PRIORITY.index),
                "source_priority_basis": primary_family,
                "support_level": support_policy["support_level"],
                "policy_decision": support_policy["policy_decision"],
                "brooks_or_youtube_only_allowed": bool(supported_families & HIGH_PRIORITY_SOURCE_FAMILIES),
                "notes_only_downgraded": support_policy["support_level"] == "notes_only",
            }
        )
        visual_gap_ledger.append(
            {
                "strategy_id": seed.strategy_id,
                "title": seed.title,
                "visual_dependency": seed.visual_dependency,
                "source_assets_available": asset_root.exists(),
                "requires_golden_case": seed.strategy_id in M10_1_VISUAL_GOLDEN_CASE_IDS,
                "visual_gap_status": visual_gap_status(seed),
                "notes": visual_gap_note(seed),
            }
        )
        backtest_matrix.append(
            {
                "strategy_id": seed.strategy_id,
                "title": seed.title,
                "timeframe_test_lines": {
                    "1d": "independent_daily_line" if "1d" in seed.timeframes else "not_primary",
                    "1h": "independent_intraday_swing_line" if "1h" in seed.timeframes else "not_primary",
                    "15m": "independent_intraday_structure_line" if "15m" in seed.timeframes else "not_primary",
                    "5m": "independent_intraday_execution_line" if "5m" in seed.timeframes else "not_primary",
                },
                "ohlcv_approximable": seed.ohlcv_approximable,
                "eligible_for_historical_backtest": catalog[-1]["backtest_eligibility"]["eligible_for_historical_backtest"],
                "test_route": catalog[-1]["backtest_eligibility"]["route"],
                "prerequisites": backtest_prerequisites(seed),
            }
        )
    return catalog, support_matrix, visual_gap_ledger, backtest_matrix


def backtest_route(seed: StrategySeed, support_level: str) -> str:
    if seed.default_status == "supporting_rule":
        return "supporting_rule_attached_to_parent_setups"
    if seed.default_status == "research_only" or not seed.ohlcv_approximable:
        return "research_or_visual_review_queue"
    if support_level != "high_priority_supported":
        return "source_gap_review"
    if seed.visual_dependency == "high":
        return "visual_golden_case_then_historical_backtest"
    return "historical_backtest_queue"


def visual_gap_note(seed: StrategySeed) -> str:
    if seed.strategy_id in M10_1_VISUAL_GOLDEN_CASE_IDS:
        return "Pattern geometry or trapped-trader context must be reviewed against Brooks v2 evidence images before promotion."
    if seed.strategy_id in M10_1_RESEARCH_ONLY_IDS:
        return "Research-only item; do not run ordinary visual review or standalone trigger tests in M10.1."
    if seed.strategy_id in M10_1_SUPPORTING_RULE_IDS:
        return "Supporting rule; attach to parent setup specs and do not review as a standalone visual trigger."
    if seed.visual_dependency == "medium":
        return "OHLCV approximation can start, but sample failures require chart review before promotion."
    return "Text-first historical approximation is acceptable."


def backtest_prerequisites(seed: StrategySeed) -> list[str]:
    items = ["source_refs_exist", "paper_simulated_only", "no_broker_or_live_order_path"]
    if seed.visual_dependency == "high":
        items.append("golden_visual_case_before_promotion")
    if seed.default_status == "supporting_rule":
        items.append("attach_to_parent_strategy_not_standalone")
    if seed.default_status == "research_only":
        items.append("risk_definition_freeze_before_simulation")
    return items


def m10_1_route_for(strategy_id: str) -> str:
    if strategy_id in M10_1_BACKTEST_WAVE_A_IDS:
        return "backtest_wave_a"
    if strategy_id in M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS:
        return "backtest_wave_b_candidate"
    if strategy_id in M10_1_VISUAL_GOLDEN_CASE_IDS:
        return "visual_golden_case_first"
    if strategy_id in M10_1_SUPPORTING_RULE_IDS:
        return "supporting_rule"
    if strategy_id in M10_1_RESEARCH_ONLY_IDS:
        return "research_only"
    return "unassigned"


def visual_gap_status(seed: StrategySeed) -> str:
    if seed.strategy_id in M10_1_VISUAL_GOLDEN_CASE_IDS:
        return "visual_golden_case_first"
    if seed.strategy_id in M10_1_RESEARCH_ONLY_IDS:
        return "research_only_no_standard_visual_review"
    if seed.strategy_id in M10_1_SUPPORTING_RULE_IDS:
        return "supporting_rule_no_standard_visual_review"
    return "text_first_ok"


def source_ref_local_path(source_ref_value: str) -> Path | None:
    if not source_ref_value.startswith("raw:"):
        return None
    local_part = source_ref_value[len("raw:") :].split("#", 1)[0]
    return PROJECT_ROOT / local_part


def source_ref_review(strategy: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    non_local: list[str] = []
    for ref in strategy.get("source_refs", []):
        source_ref_value = ref.get("source_ref", "")
        local_path = source_ref_local_path(source_ref_value)
        if local_path is None:
            non_local.append(source_ref_value)
        elif not local_path.exists():
            missing.append(source_ref_value)
    families = set(strategy.get("source_families", []))
    high_priority_source_support = bool(families & HIGH_PRIORITY_SOURCE_FAMILIES)
    notes_only = families == {"fangfangtu_notes"}
    if missing:
        status = "missing_source_ref"
    elif non_local:
        status = "non_local_source_ref_needs_manual_check"
    elif high_priority_source_support:
        status = "high_priority_source_confirmed"
    elif notes_only:
        status = "notes_only_downgraded"
    else:
        status = "needs_source_corroboration"
    return {
        "status": status,
        "source_ref_count": len(strategy.get("source_refs", [])),
        "missing_source_refs": missing,
        "non_local_source_refs": non_local,
        "high_priority_source_support": high_priority_source_support,
        "notes_only": notes_only,
    }


def allowed_next_outcomes_for_route(route: str) -> list[str]:
    if route == "backtest_wave_a":
        return list(M10_1_ALLOWED_WAVE_A_OUTCOMES)
    if route == "backtest_wave_b_candidate":
        return ["queue_for_wave_b_spec_after_m10_3"]
    if route == "visual_golden_case_first":
        return ["visual_case_pass_then_wave_b_candidate", "visual_case_fail_to_research_or_visual_review_only"]
    if route == "supporting_rule":
        return ["attach_to_parent_spec_only"]
    if route == "research_only":
        return ["research_only", "needs_corroboration"]
    return ["needs_manual_classification"]


def freeze_decision_for_route(route: str) -> str:
    return {
        "backtest_wave_a": "freeze_for_wave_a_spec_work",
        "backtest_wave_b_candidate": "freeze_as_wave_b_candidate",
        "visual_golden_case_first": "freeze_with_visual_golden_case_gate",
        "supporting_rule": "freeze_as_attached_supporting_rule_no_standalone_trigger",
        "research_only": "freeze_as_research_only",
    }.get(route, "blocked_until_classified")


def build_m10_1_review_rows(
    *,
    catalog: list[dict[str, Any]],
    support_matrix: list[dict[str, Any]],
    backtest_matrix: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    support_by_id = {row["strategy_id"]: row for row in support_matrix}
    backtest_by_id = {row["strategy_id"]: row for row in backtest_matrix}
    rows: list[dict[str, Any]] = []
    for strategy in catalog:
        strategy_id = strategy["strategy_id"]
        route = m10_1_route_for(strategy_id)
        source_review = source_ref_review(strategy)
        legacy_id_leak_detected = bool(re.search(r"\b(?:PA-SC|SF)-\d{3}\b", json.dumps(strategy, ensure_ascii=False)))
        rows.append(
            {
                "strategy_id": strategy_id,
                "title": strategy["title"],
                "m10_1_route": route,
                "source_families": strategy.get("source_families", []),
                "source_priority_basis": strategy.get("source_priority_basis", ""),
                "support_level": strategy.get("support_level", ""),
                "policy_decision": strategy.get("policy_decision", ""),
                "support_counts": support_by_id.get(strategy_id, {}).get("support_counts", {}),
                "source_review": source_review,
                "clean_room_review": {
                    "legacy_id_leak_detected": legacy_id_leak_detected,
                    "legacy_input_policy": "legacy artifacts are comparison-only after clean-room extraction",
                },
                "component_review": {
                    "strategy_name": "supported_by_clean_room_source_refs",
                    "entry_logic": "accepted_for_catalog_freeze; executable thresholds deferred_to_m10_3",
                    "stop_and_target": "accepted_for_catalog_freeze; exact sizing/target math deferred_to_m10_3",
                    "invalidation": "accepted_for_catalog_freeze; skip/no-trade ledger required in testing",
                    "visual_geometry": (
                        "requires_m10_2_golden_case_pack"
                        if route == "visual_golden_case_first"
                        else "not_a_m10_1_prerequisite"
                    ),
                },
                "backtest_snapshot": backtest_by_id.get(strategy_id, {}),
                "freeze_decision": freeze_decision_for_route(route),
                "allowed_next_outcomes": allowed_next_outcomes_for_route(route),
            }
        )
    return rows


def build_strategy_catalog_m10_frozen(catalog: list[dict[str, Any]], review_rows: list[dict[str, Any]]) -> dict[str, Any]:
    review_by_id = {row["strategy_id"]: row for row in review_rows}
    frozen_strategies: list[dict[str, Any]] = []
    for strategy in catalog:
        strategy_id = strategy["strategy_id"]
        route = m10_1_route_for(strategy_id)
        frozen_strategy = dict(strategy)
        frozen_strategy["frozen_stage"] = "M10.1.catalog_review_and_test_queue_freeze"
        frozen_strategy["m10_1_route"] = route
        frozen_strategy["visual_golden_case_required"] = strategy_id in M10_1_VISUAL_GOLDEN_CASE_IDS
        frozen_strategy["standalone_trigger_allowed"] = strategy_id not in M10_1_SUPPORTING_RULE_IDS + M10_1_RESEARCH_ONLY_IDS
        frozen_strategy["allowed_next_outcomes"] = allowed_next_outcomes_for_route(route)
        frozen_strategy["m10_1_review"] = review_by_id[strategy_id]
        frozen_strategies.append(frozen_strategy)

    return {
        "schema_version": "m10.strategy-catalog-frozen.v1",
        "generated_at": utc_now(),
        "frozen_stage": "M10.1.catalog_review_and_test_queue_freeze",
        "strategy_count": len(frozen_strategies),
        "source_priority": list(SOURCE_PRIORITY),
        "source_rules": {
            "brooks_v2_only_allowed": True,
            "youtube_only_allowed": True,
            "cross_source_corroboration_required_for_admission": False,
            "notes_only_policy": "downgrade_to_research_only_or_needs_corroboration",
            "chatgpt_share_role": "reference_only_not_source_of_truth",
        },
        "allowed_wave_a_outcomes": list(M10_1_ALLOWED_WAVE_A_OUTCOMES),
        "strategies": frozen_strategies,
    }


def catalog_title_map(catalog: list[dict[str, Any]]) -> dict[str, str]:
    return {item["strategy_id"]: item["title"] for item in catalog}


def build_m10_1_strategy_test_queue(catalog: list[dict[str, Any]]) -> dict[str, Any]:
    titles = catalog_title_map(catalog)

    def title(strategy_id: str) -> str:
        return titles.get(strategy_id, "")

    return {
        "schema_version": "m10.strategy-test-queue.v1",
        "generated_at": utc_now(),
        "stage": "M10.1.catalog_review_and_test_queue_freeze",
        "boundaries": {
            "paper_simulated_only": True,
            "real_broker_connection": False,
            "real_account": False,
            "live_execution": False,
            "automatic_real_orders": False,
            "daily_1h_15m_5m_are_independent_lines": True,
            "visual_golden_case_is_not_global_prerequisite": True,
        },
        "allowed_wave_a_outcomes": list(M10_1_ALLOWED_WAVE_A_OUTCOMES),
        "queues": {
            "backtest_wave_a": [
                {
                    "strategy_id": strategy_id,
                    "title": title(strategy_id),
                    "timeframes": list(M10_1_BACKTEST_WAVE_A_TIMEFRAMES[strategy_id]),
                    "required_outputs": list(M10_1_REQUIRED_OUTPUTS),
                    "allowed_outcomes": list(M10_1_ALLOWED_WAVE_A_OUTCOMES),
                    "retain_or_promote_allowed": False,
                }
                for strategy_id in M10_1_BACKTEST_WAVE_A_IDS
            ],
            "backtest_wave_b_candidate": [
                {
                    "strategy_id": strategy_id,
                    "title": title(strategy_id),
                    "timeframes": ["1d", "1h", "15m", "5m"],
                    "entry_gate": "M10.3_or_later_spec_freeze",
                    "allowed_outcomes": ["queue_for_wave_b_spec_after_m10_3"],
                }
                for strategy_id in M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS
            ],
            "visual_promotion_to_wave_b": [
                {
                    "strategy_id": strategy_id,
                    "title": title(strategy_id),
                    "entry_gate": "must_pass_m10_2_visual_golden_case_pack",
                }
                for strategy_id in M10_1_VISUAL_GOLDEN_CASE_IDS
            ],
            "visual_golden_case_first": [
                {
                    "strategy_id": strategy_id,
                    "title": title(strategy_id),
                    "requirements": {
                        "brooks_v2_positive_cases": M10_1_VISUAL_CASE_REQUIREMENTS["positive_cases"],
                        "counterexamples": M10_1_VISUAL_CASE_REQUIREMENTS["negative_cases"],
                        "boundary_cases": M10_1_VISUAL_CASE_REQUIREMENTS["boundary_cases"],
                        "required_fields": list(M10_1_VISUAL_CASE_REQUIREMENTS["required_fields"]),
                    },
                    "failure_policy": "failed_visual_review_remains_research_or_visual_review_only",
                }
                for strategy_id in M10_1_VISUAL_GOLDEN_CASE_IDS
            ],
            "supporting_rule": [
                {
                    "strategy_id": strategy_id,
                    "title": title(strategy_id),
                    "standalone_trigger_allowed": False,
                    "usage": "attach_to_parent_strategy_for_target_risk_or_position_sizing",
                }
                for strategy_id in M10_1_SUPPORTING_RULE_IDS
            ],
            "research_only": [
                {
                    "strategy_id": strategy_id,
                    "title": title(strategy_id),
                    "standalone_trigger_allowed": False,
                    "usage": "research_only_until_risk_definition_and_source_scope_are_frozen",
                }
                for strategy_id in M10_1_RESEARCH_ONLY_IDS
            ],
        },
        "future_handoffs": list(M10_1_FUTURE_HANDOFFS),
    }


def source_family_label(family: str) -> str:
    return {
        "brooks_v2_manual_transcript": "Brooks v2",
        "fangfangtu_youtube_transcript": "YouTube",
        "fangfangtu_notes": "notes",
    }.get(family, family)


def route_label(route: str) -> str:
    return {
        "backtest_wave_a": "Backtest Wave A",
        "backtest_wave_b_candidate": "Backtest Wave B candidate",
        "visual_golden_case_first": "Visual golden case first",
        "supporting_rule": "Supporting rule",
        "research_only": "Research only",
    }.get(route, route)


def build_m10_1_catalog_review_markdown(review_rows: list[dict[str, Any]], queue: dict[str, Any]) -> str:
    table_lines = [
        "| ID | 策略 | 来源 | M10.1 分流 | source refs | 复审结论 |",
        "|---|---|---|---|---:|---|",
    ]
    for row in review_rows:
        source_labels = " + ".join(source_family_label(family) for family in row["source_families"]) or "none"
        source_review = row["source_review"]
        conclusion = row["freeze_decision"]
        if source_review["missing_source_refs"]:
            conclusion = "blocked_missing_source_ref"
        table_lines.append(
            "| {strategy_id} | {title} | {sources} | {route} | {refs} | {conclusion} |".format(
                strategy_id=row["strategy_id"],
                title=row["title"],
                sources=source_labels,
                route=route_label(row["m10_1_route"]),
                refs=source_review["source_ref_count"],
                conclusion=conclusion,
            )
        )

    wave_a = ", ".join(item["strategy_id"] for item in queue["queues"]["backtest_wave_a"])
    wave_b = ", ".join(item["strategy_id"] for item in queue["queues"]["backtest_wave_b_candidate"])
    visual = ", ".join(item["strategy_id"] for item in queue["queues"]["visual_golden_case_first"])
    supporting = ", ".join(item["strategy_id"] for item in queue["queues"]["supporting_rule"])
    research = ", ".join(item["strategy_id"] for item in queue["queues"]["research_only"])
    future_lines = [f"- `{item['stage']}` {item['name']}: {item['handoff']}" for item in M10_1_FUTURE_HANDOFFS]

    return "\n".join(
        [
            "# M10.1 Catalog Review and Test Queue",
            "",
            "## 摘要",
            "",
            f"- 当前 clean-room catalog 冻结为 `{len(review_rows)}` 条 `M10-PA-*` 策略/规则条目。",
            "- M10.1 不启动大规模回测；本阶段只完成目录复审、来源复核、测试分流和后续阶段承接。",
            "- Visual golden case 不是所有策略的统一前置门槛，只适用于强图形依赖策略。",
            "- Brooks-only / YouTube-only 不因缺少交叉验证而自动拒绝；notes-only 必须降级。",
            "- 旧 `PA-SC-*` / `SF-*` 仅用于 comparison artifact，不作为 M10 clean-room catalog 来源。",
            "",
            "## 策略复审表",
            "",
            *table_lines,
            "",
            "## 测试分流",
            "",
            f"- `backtest_wave_a`: {wave_a}",
            f"- `backtest_wave_b_candidate`: {wave_b}",
            f"- `visual_golden_case_first`: {visual}",
            f"- `supporting_rule`: {supporting}",
            f"- `research_only`: {research}",
            "",
            "## Visual Golden Case 规则",
            "",
            "- Visual golden case 是图例审查，不是所有策略的前置门槛。",
            "- 需要先过 visual golden case 的策略必须准备 `3` 个 Brooks v2 正例、`1` 个反例、`1` 个边界例。",
            "- 每个案例必须包含 evidence image/source ref、图形判定要点和 OHLCV 近似风险说明。",
            "- 未通过 visual review 的策略不得把历史回测结果解释为有效策略，只能保留为 research / visual-review-only。",
            "",
            "## Historical Backtest Wave A",
            "",
            "- `M10-PA-001`: `1d / 1h / 15m / 5m`",
            "- `M10-PA-002`: `1d / 1h / 15m / 5m`",
            "- `M10-PA-005`: `1d / 1h / 15m / 5m`",
            "- `M10-PA-012`: `15m / 5m`",
            "- 每条必须输出 candidate events、skip/no-trade ledger、source ledger、成本/滑点敏感性、per-symbol、per-regime、failure-mode notes。",
            "- 本阶段不输出 `retain/promote`；只允许 `needs_definition_fix / needs_visual_review / continue_testing / reject_for_now`。",
            "",
            "## Supporting Rules",
            "",
            "- `M10-PA-014` 只作为目标/止盈模块。",
            "- `M10-PA-015` 只作为止损/仓位/实际风险模块。",
            "- 两者不得生成独立 entry trigger。",
            "",
            "## 后续阶段铺垫",
            "",
            *future_lines,
            "",
            "## 边界",
            "",
            "- M10 继续保持 `paper / simulated`。",
            "- 不接真实 broker，不接真实账户，不进入 live execution，不自动下单。",
            "",
        ]
    )


def validate_m10_1_artifacts(frozen_catalog: dict[str, Any], test_queue: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_ids = {seed.strategy_id for seed in STRATEGY_SEEDS}
    frozen_ids = {item["strategy_id"] for item in frozen_catalog.get("strategies", [])}
    if frozen_ids != expected_ids:
        errors.append(f"frozen catalog ids mismatch: expected={sorted(expected_ids)} actual={sorted(frozen_ids)}")
    if frozen_catalog.get("strategy_count") != len(STRATEGY_SEEDS):
        errors.append("frozen catalog strategy_count mismatch")
    if re.search(r"\b(?:PA-SC|SF)-\d{3}\b", json.dumps(frozen_catalog.get("strategies", []), ensure_ascii=False)):
        errors.append("legacy id leaked into frozen M10 catalog")

    queues = test_queue.get("queues", {})
    exact_sets = {
        "backtest_wave_a": set(M10_1_BACKTEST_WAVE_A_IDS),
        "backtest_wave_b_candidate": set(M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS),
        "visual_golden_case_first": set(M10_1_VISUAL_GOLDEN_CASE_IDS),
        "supporting_rule": set(M10_1_SUPPORTING_RULE_IDS),
        "research_only": set(M10_1_RESEARCH_ONLY_IDS),
    }
    for queue_name, expected in exact_sets.items():
        actual = {item["strategy_id"] for item in queues.get(queue_name, [])}
        if actual != expected:
            errors.append(f"{queue_name} mismatch: expected={sorted(expected)} actual={sorted(actual)}")

    overlap = set(M10_1_BACKTEST_WAVE_A_IDS) & set(M10_1_VISUAL_GOLDEN_CASE_IDS)
    if overlap:
        errors.append(f"wave A overlaps visual-first queue: {sorted(overlap)}")
    for item in queues.get("backtest_wave_a", []):
        expected_timeframes = list(M10_1_BACKTEST_WAVE_A_TIMEFRAMES[item["strategy_id"]])
        if item.get("timeframes") != expected_timeframes:
            errors.append(f"wave A timeframe mismatch for {item['strategy_id']}")
        if item.get("allowed_outcomes") != list(M10_1_ALLOWED_WAVE_A_OUTCOMES):
            errors.append(f"wave A allowed outcomes mismatch for {item['strategy_id']}")
        if item.get("retain_or_promote_allowed") is not False:
            errors.append(f"wave A retain/promote flag must be false for {item['strategy_id']}")

    strategy_by_id = {item["strategy_id"]: item for item in frozen_catalog.get("strategies", [])}
    for strategy_id in M10_1_SUPPORTING_RULE_IDS + M10_1_RESEARCH_ONLY_IDS:
        strategy = strategy_by_id.get(strategy_id, {})
        if strategy.get("standalone_trigger_allowed") is not False:
            errors.append(f"{strategy_id} must not be a standalone trigger")
    for strategy_id in M10_1_VISUAL_GOLDEN_CASE_IDS:
        strategy = strategy_by_id.get(strategy_id, {})
        if strategy.get("visual_golden_case_required") is not True:
            errors.append(f"{strategy_id} must require visual golden case")
    for strategy in frozen_catalog.get("strategies", []):
        review = strategy.get("m10_1_review", {}).get("source_review", {})
        if review.get("missing_source_refs"):
            errors.append(f"missing source refs for {strategy['strategy_id']}")
        if strategy["m10_1_route"] != "research_only" and not review.get("high_priority_source_support"):
            errors.append(f"missing high-priority source support for {strategy['strategy_id']}")
    return errors


def load_asset_checksums(brooks_root: Path = BROOKS_V2_ROOT) -> dict[str, str]:
    checksum_path = brooks_root / "assets_evidence_checksums.sha256"
    if not checksum_path.exists():
        return {}
    checksums: dict[str, str] = {}
    for line in checksum_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        checksum, logical_path = parts
        checksums[logical_path] = checksum
    return checksums


def brooks_video_id_from_ref(source_ref_value: str) -> str | None:
    match = re.search(r"\b(video_\d{3}[A-Z]?)(?=[^A-Za-z0-9]|$)", source_ref_value)
    return match.group(1) if match else None


def brooks_asset_logical_path(asset_ref: str, brooks_root: Path = BROOKS_V2_ROOT) -> str:
    try:
        raw_root = brooks_root.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        raw_root = brooks_root.as_posix()
    if asset_ref.startswith("knowledge_base_v2/"):
        return f"{raw_root}/{asset_ref[len('knowledge_base_v2/') :]}"
    if asset_ref.startswith("assets/evidence/"):
        return f"{raw_root}/{asset_ref}"
    return asset_ref


def brooks_asset_checksum_key(asset_logical_path: str, brooks_root: Path = BROOKS_V2_ROOT) -> str:
    try:
        raw_root = brooks_root.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        raw_root = brooks_root.as_posix()
    if asset_logical_path.startswith(raw_root + "/"):
        return asset_logical_path[len(raw_root) + 1 :]
    return asset_logical_path


def project_logical_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def evidence_excerpt(raw_text: str, limit: int = 180) -> str:
    return normalize(raw_text)[:limit]


def evidence_score(raw_text: str, terms: tuple[str, ...]) -> tuple[int, list[str]]:
    lowered = raw_text.lower()
    matches: list[str] = []
    score = 0
    for term in terms:
        term_lower = term.lower()
        count = lowered.count(term_lower)
        if count:
            matches.append(term)
            score += count
    return score, matches


def strategy_by_id_from_frozen(frozen_catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["strategy_id"]: item for item in frozen_catalog.get("strategies", [])}


def brooks_unit_refs_by_video(strategy: dict[str, Any]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for ref in strategy.get("source_refs", []):
        if ref.get("source_family") != "brooks_v2_manual_transcript":
            continue
        source_ref_value = ref.get("source_ref", "")
        video_id = brooks_video_id_from_ref(source_ref_value)
        if video_id and video_id not in refs:
            refs[video_id] = source_ref_value
    return refs


def collect_visual_evidence_candidates(
    strategy: dict[str, Any],
    *,
    brooks_root: Path = BROOKS_V2_ROOT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    assert_clean_room_inputs([brooks_root / "assets" / "evidence"])
    checksums = load_asset_checksums(brooks_root)
    unit_refs_by_video = brooks_unit_refs_by_video(strategy)
    candidates: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    for video_id, unit_ref in unit_refs_by_video.items():
        evidence_path = brooks_root / "assets" / "evidence" / video_id / "evidence.json"
        video_row = {
            "video_id": video_id,
            "brooks_unit_ref": unit_ref,
            "evidence_json": project_logical_path(evidence_path) if evidence_path.exists() else "",
            "evidence_json_exists": evidence_path.exists(),
            "candidate_count": 0,
        }
        if not evidence_path.exists():
            ledger_rows.append(video_row)
            continue
        try:
            evidence_items = json.loads(evidence_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            evidence_items = []
        for item in evidence_items if isinstance(evidence_items, list) else []:
            crop_ref = item.get("crop_image") or ""
            page_ref = item.get("page_image") or ""
            selected_ref = crop_ref or page_ref
            if not selected_ref:
                continue
            evidence_image_logical_path = brooks_asset_logical_path(selected_ref, brooks_root)
            page_image_logical_path = brooks_asset_logical_path(page_ref, brooks_root) if page_ref else ""
            crop_image_logical_path = brooks_asset_logical_path(crop_ref, brooks_root) if crop_ref else ""
            checksum_key = brooks_asset_checksum_key(evidence_image_logical_path, brooks_root)
            candidates.append(
                {
                    "video_id": video_id,
                    "brooks_unit_ref": unit_ref,
                    "evidence_page": item.get("page"),
                    "evidence_image_logical_path": evidence_image_logical_path,
                    "page_image_logical_path": page_image_logical_path,
                    "crop_image_logical_path": crop_image_logical_path,
                    "evidence_image_checksum": checksums.get(checksum_key, ""),
                    "raw_text": item.get("raw_text") or "",
                    "source_key": item.get("source_key") or "",
                    "image_exists": (PROJECT_ROOT / evidence_image_logical_path).exists(),
                }
            )
        video_row["candidate_count"] = len([candidate for candidate in candidates if candidate["video_id"] == video_id])
        ledger_rows.append(video_row)
    return candidates, ledger_rows


def select_visual_cases_for_type(
    *,
    strategy_id: str,
    case_type: str,
    candidates: list[dict[str, Any]],
    used_images: set[str],
    count: int,
) -> list[dict[str, Any]]:
    terms = tuple(M10_2_STRATEGY_CASE_TERMS.get(strategy_id, {}).get(case_type, ()))
    if case_type == "boundary":
        terms = terms + M10_2_GENERIC_BOUNDARY_TERMS
    scored: list[tuple[int, dict[str, Any], list[str]]] = []
    for candidate in candidates:
        if candidate["evidence_image_logical_path"] in used_images:
            continue
        score, matched = evidence_score(candidate.get("raw_text", ""), terms)
        scored.append((score, candidate, matched))
    scored.sort(
        key=lambda item: (
            -item[0],
            item[1]["video_id"],
            item[1]["evidence_page"] if item[1]["evidence_page"] is not None else 10**9,
            item[1]["evidence_image_logical_path"],
        )
    )
    selected: list[dict[str, Any]] = []
    for score, candidate, matched_terms in scored:
        if len(selected) >= count:
            break
        if score <= 0 and selected:
            continue
        used_images.add(candidate["evidence_image_logical_path"])
        selected.append(
            {
                **candidate,
                "matched_terms": matched_terms,
                "selection_reason": "term_match" if score > 0 else "fallback_same_source_video",
            }
        )
    if len(selected) < count:
        for candidate in candidates:
            if len(selected) >= count:
                break
            if candidate["evidence_image_logical_path"] in used_images:
                continue
            used_images.add(candidate["evidence_image_logical_path"])
            selected.append({**candidate, "matched_terms": [], "selection_reason": "fallback_same_source_video"})
    return selected


def visual_pattern_decision_points(strategy: dict[str, Any], case_type: str) -> list[str]:
    base = [
        "Match the Brooks v2 chart context before treating the setup as mechanically testable.",
        "Confirm the pattern geometry before translating it into OHLCV approximation rules.",
    ]
    if case_type == "positive":
        return base + list(strategy.get("entry_logic", []))[:2]
    if case_type == "counterexample":
        return base + list(strategy.get("no_trade_conditions", []))[:2]
    return base + list(strategy.get("invalidation", []))[:1]


def visual_disqualifiers(strategy: dict[str, Any]) -> list[str]:
    return list(strategy.get("invalidation", [])) + list(strategy.get("no_trade_conditions", []))


def build_visual_case(
    *,
    strategy: dict[str, Any],
    case_type: str,
    ordinal: int,
    selected: dict[str, Any],
) -> dict[str, Any]:
    strategy_id = strategy["strategy_id"]
    return {
        "case_id": f"{strategy_id}-{case_type}-{ordinal:03d}",
        "strategy_id": strategy_id,
        "case_type": case_type,
        "brooks_unit_ref": selected["brooks_unit_ref"],
        "evidence_video_id": selected["video_id"],
        "evidence_page": selected["evidence_page"],
        "evidence_image_logical_path": selected["evidence_image_logical_path"],
        "page_image_logical_path": selected["page_image_logical_path"],
        "crop_image_logical_path": selected["crop_image_logical_path"],
        "evidence_image_checksum": selected["evidence_image_checksum"],
        "evidence_exists": bool(selected["image_exists"]),
        "checksum_resolved": bool(selected["evidence_image_checksum"]),
        "matched_terms": selected["matched_terms"],
        "selection_reason": selected["selection_reason"],
        "raw_text_excerpt": evidence_excerpt(selected.get("raw_text", "")),
        "pattern_decision_points": visual_pattern_decision_points(strategy, case_type),
        "disqualifiers": visual_disqualifiers(strategy),
        "ohlcv_approximation_risk": (
            "High visual dependency: OHLCV can approximate sequence and extremes, but cannot confirm drawn channel quality, trapped-trader context, or chart readability without image review."
        ),
        "review_status": "agent_selected_pending_manual_review",
    }


def build_visual_case_pack(
    strategy: dict[str, Any],
    *,
    brooks_root: Path = BROOKS_V2_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates, source_ledger = collect_visual_evidence_candidates(strategy, brooks_root=brooks_root)
    used_images: set[str] = set()
    cases: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    for case_type in M10_2_VISUAL_CASE_TYPES:
        selected_items = select_visual_cases_for_type(
            strategy_id=strategy["strategy_id"],
            case_type=case_type,
            candidates=candidates,
            used_images=used_images,
            count=M10_2_VISUAL_CASE_COUNTS[case_type],
        )
        for ordinal, selected in enumerate(selected_items, start=1):
            case = build_visual_case(strategy=strategy, case_type=case_type, ordinal=ordinal, selected=selected)
            cases.append(case)
            selection_rows.append(
                {
                    "case_id": case["case_id"],
                    "case_type": case_type,
                    "video_id": selected["video_id"],
                    "evidence_page": selected["evidence_page"],
                    "selection_reason": selected["selection_reason"],
                    "matched_terms": selected["matched_terms"],
                    "evidence_image_logical_path": selected["evidence_image_logical_path"],
                }
            )

    case_counts = {case_type: len([case for case in cases if case["case_type"] == case_type]) for case_type in M10_2_VISUAL_CASE_TYPES}
    evidence_complete = all(case["evidence_exists"] and case["checksum_resolved"] for case in cases)
    counts_complete = all(case_counts[case_type] >= M10_2_VISUAL_CASE_COUNTS[case_type] for case_type in M10_2_VISUAL_CASE_TYPES)
    pack_status = "visual_pack_ready" if evidence_complete and counts_complete else "blocked_insufficient_visual_evidence"
    pack = {
        "schema_version": "m10.visual-golden-case-pack.v1",
        "generated_at": utc_now(),
        "stage": "M10.2.visual_golden_case_pack",
        "strategy_id": strategy["strategy_id"],
        "title": strategy["title"],
        "pack_status": pack_status,
        "review_status": "agent_selected_pending_manual_review",
        "case_counts": case_counts,
        "requirements": {
            "positive_cases": M10_2_VISUAL_CASE_COUNTS["positive"],
            "counterexamples": M10_2_VISUAL_CASE_COUNTS["counterexample"],
            "boundary_cases": M10_2_VISUAL_CASE_COUNTS["boundary"],
            "brooks_v2_images_are_local_only": True,
        },
        "source_policy": {
            "primary_case_source": "brooks_v2_manual_transcript_assets",
            "youtube_notes_role": "terminology_or_explanation_only_not_visual_case_replacement",
            "legacy_pa_sc_sf_role": "forbidden_as_case_source",
        },
        "cases": cases,
        "gap_notes": [] if pack_status == "visual_pack_ready" else ["Not enough resolvable Brooks v2 evidence images/checksums for the required 3/1/1 case structure."],
    }
    ledger = {
        "strategy_id": strategy["strategy_id"],
        "title": strategy["title"],
        "source_selection_policy": "frozen_catalog_brooks_v2_source_refs_first",
        "source_videos": source_ledger,
        "selected_cases": selection_rows,
        "pack_status": pack_status,
    }
    return pack, ledger


def build_m10_2_visual_artifacts(
    frozen_catalog: dict[str, Any],
    *,
    brooks_root: Path = BROOKS_V2_ROOT,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    strategies = strategy_by_id_from_frozen(frozen_catalog)
    packs: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    for strategy_id in M10_1_VISUAL_GOLDEN_CASE_IDS:
        strategy = strategies[strategy_id]
        pack, ledger = build_visual_case_pack(strategy, brooks_root=brooks_root)
        packs.append(pack)
        ledger_rows.append(ledger)
    index_rows = [
        {
            "strategy_id": pack["strategy_id"],
            "title": pack["title"],
            "pack_status": pack["pack_status"],
            "review_status": pack["review_status"],
            "case_counts": pack["case_counts"],
            "evidence_complete": pack["pack_status"] == "visual_pack_ready",
            "case_pack_json": f"visual_golden_cases/{pack['strategy_id']}.json",
            "case_pack_markdown": f"visual_golden_cases/{pack['strategy_id']}.md",
        }
        for pack in packs
    ]
    index = {
        "schema_version": "m10.visual-golden-case-index.v1",
        "generated_at": utc_now(),
        "stage": "M10.2.visual_golden_case_pack",
        "visual_strategy_ids": list(M10_1_VISUAL_GOLDEN_CASE_IDS),
        "excluded_strategy_ids": list(M10_1_BACKTEST_WAVE_A_IDS + M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS + M10_1_SUPPORTING_RULE_IDS + M10_1_RESEARCH_ONLY_IDS),
        "brooks_v2_images_git_policy": "local_only_ignored_by_git_checksums_tracked",
        "ready_count": len([row for row in index_rows if row["pack_status"] == "visual_pack_ready"]),
        "blocked_count": len([row for row in index_rows if row["pack_status"] != "visual_pack_ready"]),
        "packs": index_rows,
    }
    selection_ledger = {
        "schema_version": "m10.visual-case-selection-ledger.v1",
        "generated_at": utc_now(),
        "stage": "M10.2.visual_golden_case_pack",
        "source_policy": {
            "first_choice": "Brooks v2 source refs from strategy_catalog_m10_frozen.json",
            "fallback": "other Brooks v2 same-theme units only if frozen refs lack resolvable evidence",
            "youtube_notes": "terminology_only_not_visual_case_replacement",
            "legacy": "not_read_for_case_selection",
        },
        "strategies": ledger_rows,
    }
    return packs, index, selection_ledger


def validate_m10_2_artifacts(
    visual_packs: list[dict[str, Any]],
    visual_index: dict[str, Any],
    handoff: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    pack_ids = {pack["strategy_id"] for pack in visual_packs}
    expected_visual_ids = set(M10_1_VISUAL_GOLDEN_CASE_IDS)
    if pack_ids != expected_visual_ids:
        errors.append(f"visual pack ids mismatch: expected={sorted(expected_visual_ids)} actual={sorted(pack_ids)}")
    excluded = set(visual_index.get("excluded_strategy_ids", []))
    if expected_visual_ids & excluded:
        errors.append("visual strategy ids leaked into excluded ids")
    for strategy_id in M10_1_BACKTEST_WAVE_A_IDS + M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS + M10_1_SUPPORTING_RULE_IDS + M10_1_RESEARCH_ONLY_IDS:
        if strategy_id in pack_ids:
            errors.append(f"non-visual strategy incorrectly has visual case pack: {strategy_id}")
    for pack in visual_packs:
        counts = pack.get("case_counts", {})
        if pack.get("pack_status") == "visual_pack_ready":
            for case_type, required in M10_2_VISUAL_CASE_COUNTS.items():
                if counts.get(case_type, 0) < required:
                    errors.append(f"{pack['strategy_id']} missing required {case_type} cases")
            for case in pack.get("cases", []):
                if not case.get("evidence_image_logical_path") or not case.get("evidence_image_checksum"):
                    errors.append(f"{case.get('case_id')} missing evidence path or checksum")
                if case.get("strategy_id") != pack["strategy_id"]:
                    errors.append(f"{case.get('case_id')} strategy mismatch")
        if re.search(r"\b(?:PA-SC|SF)-\d{3}\b", json.dumps(pack, ensure_ascii=False)):
            errors.append(f"legacy id leaked into visual pack: {pack['strategy_id']}")
    if set(handoff.get("wave_a_strategy_ids", [])) != set(M10_1_BACKTEST_WAVE_A_IDS):
        errors.append("M10.3 handoff must reference only Wave A ids")
    if handoff.get("formal_spec_generated") is not False:
        errors.append("M10.3 handoff must not generate formal specs")
    if handoff.get("backtest_conclusions") != []:
        errors.append("M10.3 handoff must not generate backtest conclusions")
    if handoff.get("promote_or_retain_allowed") is not False:
        errors.append("M10.3 handoff must not allow promote/retain")
    return errors


def build_visual_case_pack_markdown(pack: dict[str, Any]) -> str:
    case_lines = [
        "| case_id | type | video | page | evidence image | checksum | status |",
        "|---|---|---|---:|---|---|---|",
    ]
    for case in pack["cases"]:
        checksum = case["evidence_image_checksum"][:12] if case["evidence_image_checksum"] else "missing"
        case_lines.append(
            f"| `{case['case_id']}` | `{case['case_type']}` | `{case['evidence_video_id']}` | {case['evidence_page']} | `{case['evidence_image_logical_path']}` | `{checksum}` | `{case['review_status']}` |"
        )
    return "\n".join(
        [
            f"# {pack['strategy_id']} Visual Golden Case Pack",
            "",
            "## Summary",
            "",
            f"- title: `{pack['title']}`",
            f"- pack_status: `{pack['pack_status']}`",
            f"- review_status: `{pack['review_status']}`",
            "- Brooks v2 evidence images remain local-only; this file stores logical paths and checksums only.",
            "",
            "## Cases",
            "",
            *case_lines,
            "",
            "## Review Notes",
            "",
            "- These cases are selected for visual review and do not prove profitability.",
            "- Failed or incomplete visual review blocks Wave B promotion and keeps the strategy research / visual-review-only.",
            "- Legacy `PA-SC-*` and `SF-*` artifacts were not used as visual case sources.",
            "",
        ]
    )


def build_m10_2_visual_review_summary(visual_index: dict[str, Any]) -> str:
    rows = [
        "| ID | status | positive | counterexample | boundary | case pack |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in visual_index["packs"]:
        counts = item["case_counts"]
        rows.append(
            f"| {item['strategy_id']} | `{item['pack_status']}` | {counts.get('positive', 0)} | {counts.get('counterexample', 0)} | {counts.get('boundary', 0)} | `{item['case_pack_markdown']}` |"
        )
    return "\n".join(
        [
            "# M10.2 Visual Golden Case Review Summary",
            "",
            "## 摘要",
            "",
            f"- 本阶段只覆盖 `M10-PA-003/004/007/008/009/010/011`，不对所有策略设置 visual gate。",
            f"- ready_count: `{visual_index['ready_count']}`",
            f"- blocked_count: `{visual_index['blocked_count']}`",
            "- `visual_pack_ready` 只表示图例包证据完整，仍需人工 visual review；不代表策略有效或盈利。",
            "- 本阶段不启动历史回测，不输出 `retain/promote`。",
            "",
            "## Pack Index",
            "",
            *rows,
            "",
            "## 边界",
            "",
            "- Brooks v2 图片资产继续 local-only；tracked artifact 只保存 logical path 和 checksum。",
            "- YouTube / notes 只能补充术语解释，不替代 Brooks v2 图例。",
            "- 未通过 visual review 的策略不得进入 Wave B。",
            "",
        ]
    )


def build_m10_3_backtest_spec_handoff(queue: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "m10.backtest-spec-handoff.v1",
        "generated_at": utc_now(),
        "stage": "M10.3.backtest_spec_freeze_handoff",
        "artifact_type": "handoff_only_not_executable_spec",
        "wave_a_strategy_ids": list(M10_1_BACKTEST_WAVE_A_IDS),
        "wave_a_timeframes": {strategy_id: list(timeframes) for strategy_id, timeframes in M10_1_BACKTEST_WAVE_A_TIMEFRAMES.items()},
        "required_outputs": list(M10_1_REQUIRED_OUTPUTS),
        "allowed_outcomes": list(M10_1_ALLOWED_WAVE_A_OUTCOMES),
        "formal_spec_generated": False,
        "backtest_started": False,
        "backtest_conclusions": [],
        "promote_or_retain_allowed": False,
        "visual_dependency_boundary": {
            "visual_first_strategy_ids": list(M10_1_VISUAL_GOLDEN_CASE_IDS),
            "wave_b_entry_gate": "M10.2 visual_pack_ready plus manual visual review before Wave B spec work",
        },
        "source_queue_ref": "m10_strategy_test_queue.json",
        "queue_snapshot": queue["queues"]["backtest_wave_a"],
    }


def build_m10_3_backtest_spec_handoff_markdown(handoff: dict[str, Any]) -> str:
    rows = [
        "| ID | timeframes |",
        "|---|---|",
    ]
    for strategy_id in handoff["wave_a_strategy_ids"]:
        rows.append(f"| {strategy_id} | `{' / '.join(handoff['wave_a_timeframes'][strategy_id])}` |")
    return "\n".join(
        [
            "# M10.3 Backtest Spec Freeze Handoff",
            "",
            "## Summary",
            "",
            "- This is a handoff-only artifact for the next phase.",
            "- It does not generate executable backtest specs, start backtests, or make strategy conclusions.",
            "- M10 remains paper / simulated only.",
            "",
            "## Wave A Scope",
            "",
            *rows,
            "",
            "## Required Outputs For Future Spec Freeze",
            "",
            *markdown_list(handoff["required_outputs"]),
            "",
            "## Allowed Future Outcomes",
            "",
            *markdown_list(handoff["allowed_outcomes"]),
            "",
            "## Boundary",
            "",
            "- Visual-first strategies must pass M10.2 visual review before any Wave B spec work.",
            "- This handoff does not permit retain/promote conclusions.",
            "",
        ]
    )


def build_m10_3_cost_sample_gate_policy() -> dict[str, Any]:
    return {
        "schema_version": "m10.cost-sample-gate-policy.v1",
        "generated_at": utc_now(),
        "stage": "M10.3.backtest_spec_freeze",
        "paper_simulated_only": True,
        "cost_model_policy": M10_3_COST_MODEL_POLICY,
        "sample_gate_policy": M10_3_SAMPLE_GATE_POLICY,
        "not_allowed": list(M10_3_NOT_ALLOWED),
        "boundary": {
            "backtest_started": False,
            "broker_connection": False,
            "real_account": False,
            "live_execution": False,
            "automatic_real_orders": False,
        },
    }


def build_m10_3_backtest_spec(
    *,
    strategy: dict[str, Any],
    queue_item: dict[str, Any],
) -> dict[str, Any]:
    strategy_id = strategy["strategy_id"]
    rules = M10_3_SPEC_RULES[strategy_id]
    return {
        "schema_version": "m10.backtest-spec.v1",
        "generated_at": utc_now(),
        "stage": "M10.3.backtest_spec_freeze",
        "artifact_type": "executable_backtest_spec_no_results",
        "strategy_id": strategy_id,
        "title": strategy["title"],
        "timeframes": list(M10_1_BACKTEST_WAVE_A_TIMEFRAMES[strategy_id]),
        "timeframe_policy": {
            "independent_test_lines": True,
            "daily_is_not_intraday_filter": True,
            "session_required": strategy_id == "M10-PA-012",
        },
        "paper_simulated_only": True,
        "source_refs": strategy.get("source_refs", []),
        "source_ledger_ref": f"source_ledgers/{strategy_id}.json",
        "source_policy": {
            "source_priority": list(SOURCE_PRIORITY),
            "source_priority_basis": strategy.get("source_priority_basis", ""),
            "uses_only_m10_clean_room_sources": True,
            "legacy_pa_sc_sf_not_used": True,
            "chatgpt_role": "reference_only_not_source_of_truth",
        },
        "supporting_rules": [
            {
                "strategy_id": "M10-PA-014",
                "usage": "target_labels_and_measured_move_reference_only_not_entry_trigger",
                "standalone_trigger_allowed": False,
            },
            {
                "strategy_id": "M10-PA-015",
                "usage": "structural_stop_actual_risk_and_position_sizing_reference_only_not_entry_trigger",
                "standalone_trigger_allowed": False,
            },
        ],
        "event_definition": {
            "event_name": rules["event_name"],
            **rules["event_definition"],
        },
        "entry_rules": rules["entry_rules"],
        "stop_rules": rules["stop_rules"],
        "target_rules": rules["target_rules"],
        "skip_rules": rules["skip_rules"],
        "cost_model_policy": {
            "policy_ref": "m10_cost_sample_gate_policy.json#cost_model_policy",
            **M10_3_COST_MODEL_POLICY,
        },
        "sample_gate_policy": {
            "policy_ref": "m10_cost_sample_gate_policy.json#sample_gate_policy",
            **M10_3_SAMPLE_GATE_POLICY,
        },
        "outputs_required": list(queue_item.get("required_outputs", M10_1_REQUIRED_OUTPUTS)),
        "allowed_outcomes": list(M10_1_ALLOWED_WAVE_A_OUTCOMES),
        "not_allowed": list(M10_3_NOT_ALLOWED),
        "backtest_started": False,
        "backtest_conclusions": [],
        "retain_or_promote_allowed": False,
        "m10_4_handoff": {
            "runner_must_emit_candidate_events": True,
            "runner_must_emit_skip_no_trade_ledger": True,
            "runner_must_emit_source_ledger": True,
            "runner_must_emit_cost_slippage_sensitivity": True,
            "runner_must_emit_per_symbol_and_per_regime_breakdowns": True,
            "runner_must_emit_failure_mode_notes": True,
        },
    }


def build_m10_3_backtest_spec_artifacts(
    *,
    frozen_catalog: dict[str, Any],
    test_queue: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    strategies = strategy_by_id_from_frozen(frozen_catalog)
    queue_items = {item["strategy_id"]: item for item in test_queue["queues"]["backtest_wave_a"]}
    specs = [
        build_m10_3_backtest_spec(strategy=strategies[strategy_id], queue_item=queue_items[strategy_id])
        for strategy_id in M10_1_BACKTEST_WAVE_A_IDS
    ]
    index = {
        "schema_version": "m10.backtest-spec-index.v1",
        "generated_at": utc_now(),
        "stage": "M10.3.backtest_spec_freeze",
        "spec_count": len(specs),
        "wave_a_strategy_ids": list(M10_1_BACKTEST_WAVE_A_IDS),
        "excluded_strategy_ids": list(
            M10_1_BACKTEST_WAVE_B_CANDIDATE_IDS
            + M10_1_VISUAL_GOLDEN_CASE_IDS
            + M10_1_SUPPORTING_RULE_IDS
            + M10_1_RESEARCH_ONLY_IDS
        ),
        "boundaries": {
            "paper_simulated_only": True,
            "backtest_started": False,
            "daily_1h_15m_5m_are_independent_lines": True,
            "daily_is_not_5m_filter": True,
            "retain_or_promote_allowed": False,
            "broker_connection": False,
            "live_execution": False,
        },
        "specs": [
            {
                "strategy_id": spec["strategy_id"],
                "title": spec["title"],
                "timeframes": spec["timeframes"],
                "spec_json": f"backtest_specs/{spec['strategy_id']}.json",
                "spec_markdown": f"backtest_specs/{spec['strategy_id']}.md",
                "allowed_outcomes": spec["allowed_outcomes"],
                "backtest_started": False,
                "retain_or_promote_allowed": False,
            }
            for spec in specs
        ],
    }
    event_definition_ledger = {
        "schema_version": "m10.event-definition-ledger.v1",
        "generated_at": utc_now(),
        "stage": "M10.3.backtest_spec_freeze",
        "entries": [
            {
                "strategy_id": spec["strategy_id"],
                "title": spec["title"],
                "event_name": spec["event_definition"]["event_name"],
                "timeframes": spec["timeframes"],
                "definition_ref": f"backtest_specs/{spec['strategy_id']}.json#event_definition",
                "ohlcv_approximation": spec["event_definition"]["ohlcv_approximation"],
                "visual_review_fallback": "needs_visual_review_if_ohlcv_sequence_cannot_represent_source_context",
            }
            for spec in specs
        ],
    }
    skip_rule_ledger = {
        "schema_version": "m10.skip-rule-ledger.v1",
        "generated_at": utc_now(),
        "stage": "M10.3.backtest_spec_freeze",
        "entries": [
            {
                "strategy_id": spec["strategy_id"],
                "title": spec["title"],
                "skip_code": skip_rule["skip_code"],
                "reason": skip_rule["reason"],
                "spec_ref": f"backtest_specs/{spec['strategy_id']}.json#skip_rules",
            }
            for spec in specs
            for skip_rule in spec["skip_rules"]
        ],
    }
    cost_sample_policy = build_m10_3_cost_sample_gate_policy()
    return specs, index, event_definition_ledger, skip_rule_ledger, cost_sample_policy


def validate_m10_3_artifacts(
    *,
    specs: list[dict[str, Any]],
    spec_index: dict[str, Any],
    event_definition_ledger: dict[str, Any],
    skip_rule_ledger: dict[str, Any],
    cost_sample_policy: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    expected_ids = set(M10_1_BACKTEST_WAVE_A_IDS)
    spec_ids = {spec.get("strategy_id", "") for spec in specs}
    if spec_ids != expected_ids:
        errors.append(f"M10.3 spec ids mismatch: expected={sorted(expected_ids)} actual={sorted(spec_ids)}")
    if spec_index.get("spec_count") != len(M10_1_BACKTEST_WAVE_A_IDS):
        errors.append("M10.3 spec index count mismatch")
    if set(spec_index.get("wave_a_strategy_ids", [])) != expected_ids:
        errors.append("M10.3 spec index wave A ids mismatch")
    excluded = set(spec_index.get("excluded_strategy_ids", []))
    forbidden_in_index = set(M10_1_VISUAL_GOLDEN_CASE_IDS + M10_1_SUPPORTING_RULE_IDS + M10_1_RESEARCH_ONLY_IDS)
    if not forbidden_in_index.issubset(excluded):
        errors.append("M10.3 index missing visual/supporting/research exclusions")
    for spec in specs:
        strategy_id = spec["strategy_id"]
        if spec.get("schema_version") != "m10.backtest-spec.v1":
            errors.append(f"{strategy_id} schema mismatch")
        if spec.get("stage") != "M10.3.backtest_spec_freeze":
            errors.append(f"{strategy_id} stage mismatch")
        if spec.get("timeframes") != list(M10_1_BACKTEST_WAVE_A_TIMEFRAMES[strategy_id]):
            errors.append(f"{strategy_id} timeframe mismatch")
        if strategy_id == "M10-PA-012" and spec.get("timeframes") != ["15m", "5m"]:
            errors.append("M10-PA-012 must only use 15m/5m")
        if not spec.get("source_refs"):
            errors.append(f"{strategy_id} missing source refs")
        for field_name in ("event_definition", "entry_rules", "stop_rules", "target_rules", "skip_rules", "outputs_required"):
            if not spec.get(field_name):
                errors.append(f"{strategy_id} missing {field_name}")
        if spec.get("allowed_outcomes") != list(M10_1_ALLOWED_WAVE_A_OUTCOMES):
            errors.append(f"{strategy_id} allowed outcomes mismatch")
        if set(spec.get("not_allowed", [])) != set(M10_3_NOT_ALLOWED):
            errors.append(f"{strategy_id} not_allowed mismatch")
        if spec.get("backtest_started") is not False or spec.get("backtest_conclusions") != []:
            errors.append(f"{strategy_id} must not contain backtest results")
        if spec.get("retain_or_promote_allowed") is not False:
            errors.append(f"{strategy_id} retain/promote must be false")
        spec_text = json.dumps(spec, ensure_ascii=False)
        if re.search(r"\b(?:PA-SC|SF)-\d{3}\b", spec_text):
            errors.append(f"legacy id leaked into M10.3 spec: {strategy_id}")
        for supporting_rule in spec.get("supporting_rules", []):
            if supporting_rule.get("standalone_trigger_allowed") is not False:
                errors.append(f"{strategy_id} supporting rule must not be standalone trigger")
    if len(event_definition_ledger.get("entries", [])) != len(M10_1_BACKTEST_WAVE_A_IDS):
        errors.append("M10.3 event definition ledger count mismatch")
    if len(skip_rule_ledger.get("entries", [])) < len(M10_1_BACKTEST_WAVE_A_IDS):
        errors.append("M10.3 skip rule ledger is unexpectedly small")
    if cost_sample_policy.get("cost_model_policy", {}).get("sensitivity_tiers") != M10_3_COST_MODEL_POLICY["sensitivity_tiers"]:
        errors.append("M10.3 cost sensitivity tiers mismatch")
    if cost_sample_policy.get("sample_gate_policy", {}).get("minimum_candidate_events_per_strategy_timeframe") != 30:
        errors.append("M10.3 sample gate candidate event minimum mismatch")
    if cost_sample_policy.get("sample_gate_policy", {}).get("minimum_executed_trades_after_skips_per_strategy_timeframe") != 10:
        errors.append("M10.3 sample gate executed trade minimum mismatch")
    artifacts_text = json.dumps(
        {
            "spec_index": spec_index,
            "event_definition_ledger": event_definition_ledger,
            "skip_rule_ledger": skip_rule_ledger,
            "cost_sample_policy": cost_sample_policy,
        },
        ensure_ascii=False,
    )
    if re.search(r"\b(?:PA-SC|SF)-\d{3}\b", artifacts_text):
        errors.append("legacy id leaked into M10.3 aggregate artifacts")
    return errors


def build_m10_3_backtest_spec_markdown(spec: dict[str, Any]) -> str:
    source_lines = [
        f"- `{ref['source_family']}` {ref['source_ref']} {json.dumps(ref['locator'], ensure_ascii=False, sort_keys=True)}"
        for ref in spec["source_refs"]
    ]
    skip_lines = [f"- `{row['skip_code']}`: {row['reason']}" for row in spec["skip_rules"]]
    return "\n".join(
        [
            f"# {spec['strategy_id']} Backtest Spec Freeze",
            "",
            "## Summary",
            "",
            f"- title: `{spec['title']}`",
            f"- stage: `{spec['stage']}`",
            f"- timeframes: `{' / '.join(spec['timeframes'])}`",
            "- status: executable spec frozen for future pilot; no backtest has been run.",
            "- boundary: paper / simulated only; no broker, no live execution, no real orders.",
            "",
            "## Source Ledger",
            "",
            f"- source ledger ref: `{spec['source_ledger_ref']}`",
            *source_lines,
            "",
            "## Event Definition",
            "",
            f"- event_name: `{spec['event_definition']['event_name']}`",
            f"- OHLCV approximation: {spec['event_definition']['ohlcv_approximation']}",
            "",
            "## Entry Rules",
            "",
            *markdown_list(spec["entry_rules"]),
            "",
            "## Stop Rules",
            "",
            *markdown_list(spec["stop_rules"]),
            "",
            "## Target Rules",
            "",
            *markdown_list(spec["target_rules"]),
            "",
            "## Skip / No-Trade Rules",
            "",
            *skip_lines,
            "",
            "## Required Outputs",
            "",
            *markdown_list(spec["outputs_required"]),
            "",
            "## Allowed Outcomes",
            "",
            *markdown_list(spec["allowed_outcomes"]),
            "",
            "## Not Allowed",
            "",
            *markdown_list(spec["not_allowed"]),
            "",
        ]
    )


def build_m10_3_spec_freeze_summary(spec_index: dict[str, Any], cost_sample_policy: dict[str, Any]) -> str:
    rows = [
        "| ID | timeframes | spec | allowed outcomes |",
        "|---|---|---|---|",
    ]
    for item in spec_index["specs"]:
        rows.append(
            f"| {item['strategy_id']} | `{' / '.join(item['timeframes'])}` | `{item['spec_markdown']}` | `{', '.join(item['allowed_outcomes'])}` |"
        )
    tiers = cost_sample_policy["cost_model_policy"]["sensitivity_tiers"]
    tier_lines = [f"- `{tier['tier']}`: slippage `{tier['slippage_bps']} bps`, fee_per_order `{tier['fee_per_order']}`" for tier in tiers]
    sample_gate = cost_sample_policy["sample_gate_policy"]
    return "\n".join(
        [
            "# M10.3 Backtest Spec Freeze Summary",
            "",
            "## 摘要",
            "",
            "- 本阶段只冻结 Wave A 可执行回测规格，不运行 historical backtest。",
            "- 覆盖 `M10-PA-001/002/005/012`；不把 visual-first、supporting、research-only 条目放入 Wave A spec。",
            "- 所有 spec 保持 `paper / simulated`，不接 broker、不接真实账户、不下单。",
            "- 本阶段不得输出 `retain/promote`、收益判断或实盘能力结论。",
            "",
            "## Wave A Spec Index",
            "",
            *rows,
            "",
            "## Cost Sensitivity Policy",
            "",
            *tier_lines,
            "",
            "## Sample Gate",
            "",
            f"- 每个 strategy/timeframe 至少 `{sample_gate['minimum_candidate_events_per_strategy_timeframe']}` 个 candidate events。",
            f"- skip 后至少 `{sample_gate['minimum_executed_trades_after_skips_per_strategy_timeframe']}` 个 executed trades。",
            "- 低于样本门槛只能标记 `continue_testing` 或 `needs_definition_fix`。",
            "- 样本门槛只允许解释测试质量，不允许宣称盈利稳定性。",
            "",
            "## M10.4 Handoff",
            "",
            "- 下一阶段只允许做 Historical Backtest Pilot。",
            "- Pilot 必须输出 candidate events、skip/no-trade ledger、source ledger、成本/滑点敏感性、per-symbol、per-regime 与 failure-mode notes。",
            "- Pilot 结果仍只能进入 `needs_definition_fix / needs_visual_review / continue_testing / reject_for_now`。",
            "",
        ]
    )


def write_m10_3_backtest_spec_artifacts(
    *,
    output_dir: Path,
    specs: list[dict[str, Any]],
    spec_index: dict[str, Any],
    event_definition_ledger: dict[str, Any],
    skip_rule_ledger: dict[str, Any],
    cost_sample_policy: dict[str, Any],
) -> None:
    spec_dir = output_dir / "backtest_specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        strategy_id = spec["strategy_id"]
        write_json(spec_dir / f"{strategy_id}.json", spec)
        (spec_dir / f"{strategy_id}.md").write_text(build_m10_3_backtest_spec_markdown(spec), encoding="utf-8")
    write_json(output_dir / "m10_backtest_spec_index.json", spec_index)
    write_json(output_dir / "m10_event_definition_ledger.json", event_definition_ledger)
    write_json(output_dir / "m10_skip_rule_ledger.json", skip_rule_ledger)
    write_json(output_dir / "m10_cost_sample_gate_policy.json", cost_sample_policy)
    (output_dir / "m10_3_backtest_spec_freeze_summary.md").write_text(
        build_m10_3_spec_freeze_summary(spec_index, cost_sample_policy),
        encoding="utf-8",
    )


def write_m10_2_visual_artifacts(
    *,
    output_dir: Path,
    visual_packs: list[dict[str, Any]],
    visual_index: dict[str, Any],
    selection_ledger: dict[str, Any],
    handoff: dict[str, Any],
) -> None:
    case_dir = output_dir / "visual_golden_cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    for pack in visual_packs:
        strategy_id = pack["strategy_id"]
        write_json(case_dir / f"{strategy_id}.json", pack)
        (case_dir / f"{strategy_id}.md").write_text(build_visual_case_pack_markdown(pack), encoding="utf-8")
    write_json(output_dir / "m10_visual_golden_case_index.json", visual_index)
    write_json(output_dir / "m10_visual_case_selection_ledger.json", selection_ledger)
    (output_dir / "m10_2_visual_review_summary.md").write_text(build_m10_2_visual_review_summary(visual_index), encoding="utf-8")
    (output_dir / "m10_3_backtest_spec_handoff.md").write_text(build_m10_3_backtest_spec_handoff_markdown(handoff), encoding="utf-8")


def build_chatgpt_comparison(catalog: list[dict[str, Any]]) -> dict[str, Any]:
    bpa_reference = CHATGPT_BPA_REFERENCE
    if CHATGPT_REFERENCE_PATH.exists():
        try:
            loaded = json.loads(CHATGPT_REFERENCE_PATH.read_text(encoding="utf-8"))
            bpa_reference = {
                item["bpa_id"]: item["title"]
                for item in loaded.get("bpa_reference_pack", [])
                if item.get("bpa_id") and item.get("title")
            } or bpa_reference
        except Exception:
            bpa_reference = CHATGPT_BPA_REFERENCE

    mapped_bpa = {bpa for item in catalog for bpa in item.get("chatgpt_bpa_reference_overlap", [])}
    return {
        "schema_version": "m10.chatgpt-bpa-comparison.v1",
        "comparison_role": "external_reference_only_not_source_of_truth",
        "chatgpt_share_url": "https://chatgpt.com/share/69ed8224-a360-8327-a2cc-0976be6555d5",
        "m10_to_bpa": [
            {
                "strategy_id": item["strategy_id"],
                "m10_title": item["title"],
                "bpa_refs": [
                    {"bpa_id": bpa_id, "title": bpa_reference.get(bpa_id, "")}
                    for bpa_id in item.get("chatgpt_bpa_reference_overlap", [])
                ],
                "decision": "compare_only_no_retrofit_to_clean_room_catalog",
            }
            for item in catalog
        ],
        "bpa_not_directly_split_in_m10": [
            {"bpa_id": bpa_id, "title": title}
            for bpa_id, title in sorted(bpa_reference.items())
            if bpa_id not in mapped_bpa
        ],
        "absorbed_testing_suggestions": [
            "Separate visual-heavy strategies into golden-case review before promotion.",
            "Treat source priority as Brooks v2 first, FangFangTu YouTube second, notes third.",
            "Historical backtest precedes read-only observation, paper trading, and any future live approval.",
        ],
    }


def collect_legacy_inventory() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in LEGACY_COMPARISON_PATHS:
        if not path.exists():
            records.append({"path": path.relative_to(PROJECT_ROOT).as_posix(), "exists": False, "file_count": 0, "ids": []})
            continue
        files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
        ids: set[str] = set()
        for file_path in files:
            ids.update(re.findall(r"\b(?:PA-SC|SF)-\d{3}\b", file_path.as_posix()))
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                text = ""
            ids.update(re.findall(r"\b(?:PA-SC|SF)-\d{3}\b", text[:20000]))
        records.append(
            {
                "path": path.relative_to(PROJECT_ROOT).as_posix(),
                "exists": True,
                "file_count": len(files),
                "ids": sorted(ids),
            }
        )
    return {
        "schema_version": "m10.legacy-comparison.v1",
        "comparison_phase": "after_clean_room_catalog_generation",
        "legacy_policy": "inventory_and_diff_only_no_feedback_into_m10_catalog",
        "legacy_records": records,
    }


def run_git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=PROJECT_ROOT, text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as exc:
        return exc.output.strip()


def build_workspace_audit(legacy: dict[str, Any]) -> str:
    branch = run_git(["branch", "--show-current"])
    status = run_git(["status", "--short", "--branch"])
    worktrees = run_git(["worktree", "list", "--porcelain"])
    legacy_lines = []
    for record in legacy["legacy_records"]:
        legacy_lines.append(
            f"- `{record['path']}`: exists={record['exists']} files={record['file_count']} ids={', '.join(record['ids'][:12])}"
        )
    return "\n".join(
        [
            "# M10 Workspace Audit and Legacy Inventory",
            "",
            "## Branch",
            "",
            f"- current branch: `{branch}`",
            f"- expected branch: `codex/m10-price-action-strategy-refresh`",
            "",
            "## Git Status",
            "",
            "```text",
            status,
            "```",
            "",
            "## Worktrees",
            "",
            "```text",
            worktrees,
            "```",
            "",
            "## Legacy-Only Inventory",
            "",
            "The following paths are registered only for post-extraction comparison. They are forbidden as clean-room extraction inputs.",
            "",
            *legacy_lines,
            "",
        ]
    )


def build_test_plan(catalog: list[dict[str, Any]], backtest_matrix: list[dict[str, Any]]) -> str:
    _ = backtest_matrix
    queue = build_m10_1_strategy_test_queue(catalog)
    backtest_ids = [row["strategy_id"] for row in queue["queues"]["backtest_wave_a"]]
    visual_ids = [row["strategy_id"] for row in queue["queues"]["visual_golden_case_first"]]
    research_ids = [row["strategy_id"] for row in queue["queues"]["research_only"]]
    supporting_ids = [row["strategy_id"] for row in queue["queues"]["supporting_rule"]]
    return "\n".join(
        [
            "# M10 Test Plan",
            "",
            "## Boundaries",
            "",
            "- M10 remains `paper / simulated` only.",
            "- No real account, broker connection, live execution, or automated real order path is introduced.",
            "- Daily, 1h, 15m, and 5m are independent test lines; daily is not a 5m auxiliary filter.",
            "- Missing cross-source corroboration changes confidence and review order, not admission, when Brooks v2 or FangFangTu YouTube supports the strategy.",
            "",
            "## Source Integrity",
            "",
            "- Verify Brooks v2 `README.md`, `units/`, `evidence/`, `manifest.json`, `checksums.sha256`, and `assets_evidence_checksums.sha256` exist.",
            "- Verify FangFangTu YouTube transcript and notes raw PDFs still resolve.",
            "- Rebuild and validate source/chunk/atom/callable indexes after source ingestion.",
            "",
            "## Clean-Room Guard",
            "",
            "- M10 catalog generation reads only Brooks v2 manual transcript, FangFangTu YouTube transcript, FangFangTu notes, and reference-only ChatGPT summary.",
            "- Legacy `PA-SC-*`, `SF-*`, old strategy cards, old specs, old triage, and old catalog are only read after catalog generation for comparison artifacts.",
            "",
            "## Historical Backtest Queue",
            "",
            "- M10.1 Wave A IDs: " + ", ".join(backtest_ids),
            "- `M10-PA-001`: `1d / 1h / 15m / 5m`.",
            "- `M10-PA-002`: `1d / 1h / 15m / 5m`.",
            "- `M10-PA-005`: `1d / 1h / 15m / 5m`.",
            "- `M10-PA-012`: `15m / 5m`.",
            "- Historical backtest output must include candidate events, skip/no-trade ledger, source ledger, cost/slippage sensitivity, per-symbol, per-regime, and failure-mode notes.",
            "- M10.1 outcomes are limited to `needs_definition_fix`, `needs_visual_review`, `continue_testing`, or `reject_for_now`.",
            "- Wave B is not executed in M10.1; `M10-PA-013` is reserved as a low-visual Wave B candidate, and visual strategies can join only after passing M10.2.",
            "",
            "## M10.3 Backtest Spec Freeze",
            "",
            "- M10.3 freezes executable specs for Wave A only: `backtest_specs/M10-PA-001.json`, `M10-PA-002.json`, `M10-PA-005.json`, `M10-PA-012.json`.",
            "- The spec index is `m10_backtest_spec_index.json`; event definitions, skip rules, and cost/sample gates are tracked in dedicated ledgers.",
            "- Cost sensitivity tiers are fixed at baseline `1 bps`, stress low `2 bps`, and stress high `5 bps`; fees remain `0` in this policy placeholder.",
            "- Sample gates are fixed at at least 30 candidate events and 10 executed trades after skips per strategy/timeframe before interpreting test quality.",
            "- M10.3 does not run backtests and does not permit `retain/promote` conclusions.",
            "",
            "## Visual Review Queue",
            "",
            "- Candidate IDs: " + ", ".join(visual_ids),
            "- Visual golden case is not a global prerequisite. It applies only to the listed high-visual strategies.",
            "- Each visual strategy needs 3 Brooks v2 positive cases, 1 counterexample, 1 boundary case, evidence image/source ref, pattern decision points, and OHLCV approximation risk notes.",
            "",
            "## Research and Supporting Rules",
            "",
            "- Research-only IDs: " + ", ".join(research_ids),
            "- Supporting-rule IDs: " + ", ".join(supporting_ids),
            "- Supporting rules can modify test reports and risk/target interpretation but cannot create standalone entry triggers in M10.",
            "",
            "## Phase Order",
            "",
            "1. Historical backtest on eligible OHLCV-approximable strategies.",
            "2. Real-time read-only observation with no order path.",
            "3. Paper trading only after backtest and observation gates pass.",
            "4. Live approval remains out of M10 scope.",
            "",
        ]
    )


def markdown_list(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- None"]


def build_strategy_card(strategy: dict[str, Any]) -> str:
    source_lines = [
        f"- `{ref['source_family']}` {ref['source_ref']} {json.dumps(ref['locator'], ensure_ascii=False, sort_keys=True)}"
        for ref in strategy["source_refs"]
    ]
    return "\n".join(
        [
            f"# {strategy['strategy_id']} {strategy['title']}",
            "",
            "## Status",
            "",
            f"- status: `{strategy['status']}`",
            f"- confidence: `{strategy['confidence']}`",
            f"- support_level: `{strategy['support_level']}`",
            f"- source_priority_basis: `{strategy['source_priority_basis']}`",
            f"- visual_dependency: `{strategy['visual_dependency']}`",
            f"- backtest_route: `{strategy['backtest_eligibility']['route']}`",
            "",
            "## Source Ledger",
            "",
            *source_lines,
            "",
            "## Market Context",
            "",
            *markdown_list(strategy["market_context"]),
            "",
            "## Entry Logic",
            "",
            *markdown_list(strategy["entry_logic"]),
            "",
            "## Stop Logic",
            "",
            *markdown_list(strategy["stop_logic"]),
            "",
            "## Target Logic",
            "",
            *markdown_list(strategy["target_logic"]),
            "",
            "## Invalidation",
            "",
            *markdown_list(strategy["invalidation"]),
            "",
            "## No-Trade Conditions",
            "",
            *markdown_list(strategy["no_trade_conditions"]),
            "",
            "## Boundary",
            "",
            "- This M10 card is research/backtest/paper-only.",
            "- It does not connect to broker/live/real-money execution.",
            "- Legacy `PA-SC-*` and `SF-*` artifacts were not used as extraction inputs.",
            "",
        ]
    )


def write_strategy_cards_specs_and_ledgers(
    *,
    output_dir: Path,
    catalog: list[dict[str, Any]],
    support_matrix: list[dict[str, Any]],
) -> None:
    matrix_by_id = {row["strategy_id"]: row for row in support_matrix}
    cards_dir = output_dir / "cards"
    specs_dir = output_dir / "specs"
    ledgers_dir = output_dir / "source_ledgers"
    for directory in (cards_dir, specs_dir, ledgers_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for strategy in catalog:
        strategy_id = strategy["strategy_id"]
        (cards_dir / f"{strategy_id}.md").write_text(build_strategy_card(strategy), encoding="utf-8")
        write_json(
            specs_dir / f"{strategy_id}.json",
            {
                "schema_version": "m10.strategy-spec.v1",
                "strategy": strategy,
                "paper_simulated_only": True,
            },
        )
        write_json(
            ledgers_dir / f"{strategy_id}.json",
            {
                "schema_version": "m10.strategy-source-ledger.v1",
                "strategy_id": strategy_id,
                "title": strategy["title"],
                "source_priority": list(SOURCE_PRIORITY),
                "support_summary": matrix_by_id[strategy_id],
                "source_refs": strategy["source_refs"],
                "legacy_influence": strategy["clean_room_guard"],
            },
        )


def build_source_ingestion_report() -> dict[str, Any]:
    manifest_path = BROOKS_V2_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    return {
        "schema_version": "m10.source-ingestion-report.v1",
        "generated_at": utc_now(),
        "source_priority": list(SOURCE_PRIORITY),
        "brooks_v2": {
            "raw_root": BROOKS_V2_ROOT.relative_to(PROJECT_ROOT).as_posix(),
            "manifest_path": manifest_path.relative_to(PROJECT_ROOT).as_posix(),
            "manifest_exists": manifest_path.exists(),
            "checksums_path": (BROOKS_V2_ROOT / "checksums.sha256").relative_to(PROJECT_ROOT).as_posix(),
            "asset_checksums_path": (BROOKS_V2_ROOT / "assets_evidence_checksums.sha256").relative_to(PROJECT_ROOT).as_posix(),
            "import_manifest": manifest,
        },
        "reference_only": {
            "chatgpt_share": "https://chatgpt.com/share/69ed8224-a360-8327-a2cc-0976be6555d5",
            "codex_thread": "codex://threads/019dbf29-e38d-7660-aed8-48fb252a7300",
        },
    }


def validate_catalog(catalog: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for item in catalog:
        if not item["strategy_id"].startswith("M10-PA-"):
            errors.append(f"invalid namespace: {item['strategy_id']}")
        if re.search(r"\b(?:PA-SC|SF)-\d{3}\b", json.dumps(item, ensure_ascii=False)):
            errors.append(f"legacy id leaked into clean-room catalog: {item['strategy_id']}")
        families = set(item["source_families"])
        policy = classify_support_for_strategy(families)
        if families & HIGH_PRIORITY_SOURCE_FAMILIES and policy["policy_decision"].startswith("blocked"):
            errors.append(f"high-priority-only source incorrectly blocked: {item['strategy_id']}")
        if families == {"fangfangtu_notes"} and item["status"] != "needs_corroboration":
            errors.append(f"notes-only strategy not downgraded: {item['strategy_id']}")
        if not families:
            errors.append(f"strategy missing high-priority source evidence: {item['strategy_id']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate M10 clean-room strategy refresh artifacts.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    docs = collect_clean_room_docs()
    catalog, support_matrix, visual_gap_ledger, backtest_matrix = build_catalog_from_docs(docs)
    errors = validate_catalog(catalog)
    if errors:
        for error in errors:
            print(f"M10 catalog validation error: {error}", file=sys.stderr)
        return 1
    review_rows = build_m10_1_review_rows(
        catalog=catalog,
        support_matrix=support_matrix,
        backtest_matrix=backtest_matrix,
    )
    frozen_catalog = build_strategy_catalog_m10_frozen(catalog, review_rows)
    m10_1_test_queue = build_m10_1_strategy_test_queue(catalog)
    m10_1_errors = validate_m10_1_artifacts(frozen_catalog, m10_1_test_queue)
    if m10_1_errors:
        for error in m10_1_errors:
            print(f"M10.1 validation error: {error}", file=sys.stderr)
        return 1
    visual_packs, visual_index, selection_ledger = build_m10_2_visual_artifacts(frozen_catalog)
    m10_3_handoff = build_m10_3_backtest_spec_handoff(m10_1_test_queue)
    m10_2_errors = validate_m10_2_artifacts(visual_packs, visual_index, m10_3_handoff)
    if m10_2_errors:
        for error in m10_2_errors:
            print(f"M10.2 validation error: {error}", file=sys.stderr)
        return 1
    m10_3_specs, m10_3_spec_index, m10_3_event_ledger, m10_3_skip_ledger, m10_3_cost_sample_policy = (
        build_m10_3_backtest_spec_artifacts(
            frozen_catalog=frozen_catalog,
            test_queue=m10_1_test_queue,
        )
    )
    m10_3_errors = validate_m10_3_artifacts(
        specs=m10_3_specs,
        spec_index=m10_3_spec_index,
        event_definition_ledger=m10_3_event_ledger,
        skip_rule_ledger=m10_3_skip_ledger,
        cost_sample_policy=m10_3_cost_sample_policy,
    )
    if m10_3_errors:
        for error in m10_3_errors:
            print(f"M10.3 validation error: {error}", file=sys.stderr)
        return 1

    legacy = collect_legacy_inventory()
    chatgpt = build_chatgpt_comparison(catalog)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "strategy_catalog_m10.json", {"schema_version": "m10.strategy-catalog.v1", "generated_at": utc_now(), "strategies": catalog})
    write_json(output_dir / "source_support_matrix_m10.json", {"schema_version": "m10.source-support-matrix.v1", "generated_at": utc_now(), "source_priority": list(SOURCE_PRIORITY), "matrix": support_matrix})
    write_json(output_dir / "chatgpt_bpa_comparison.json", chatgpt)
    write_json(output_dir / "legacy_comparison_m10.json", legacy)
    write_json(output_dir / "visual_gap_ledger.json", {"schema_version": "m10.visual-gap-ledger.v1", "generated_at": utc_now(), "ledger": visual_gap_ledger})
    write_json(output_dir / "backtest_eligibility_matrix.json", {"schema_version": "m10.backtest-eligibility-matrix.v1", "generated_at": utc_now(), "matrix": backtest_matrix})
    write_json(output_dir / "m10_source_ingestion_report.json", build_source_ingestion_report())
    write_json(output_dir / "strategy_catalog_m10_frozen.json", frozen_catalog)
    write_json(output_dir / "m10_strategy_test_queue.json", m10_1_test_queue)
    write_m10_2_visual_artifacts(
        output_dir=output_dir,
        visual_packs=visual_packs,
        visual_index=visual_index,
        selection_ledger=selection_ledger,
        handoff=m10_3_handoff,
    )
    write_m10_3_backtest_spec_artifacts(
        output_dir=output_dir,
        specs=m10_3_specs,
        spec_index=m10_3_spec_index,
        event_definition_ledger=m10_3_event_ledger,
        skip_rule_ledger=m10_3_skip_ledger,
        cost_sample_policy=m10_3_cost_sample_policy,
    )
    write_strategy_cards_specs_and_ledgers(output_dir=output_dir, catalog=catalog, support_matrix=support_matrix)
    (output_dir / "m10_test_plan.md").write_text(build_test_plan(catalog, backtest_matrix), encoding="utf-8")
    (output_dir / "m10_catalog_review.md").write_text(
        build_m10_1_catalog_review_markdown(review_rows, m10_1_test_queue),
        encoding="utf-8",
    )
    (output_dir / "workspace_audit_legacy_inventory_m10.md").write_text(build_workspace_audit(legacy), encoding="utf-8")

    print(f"Wrote M10 artifacts to {output_dir.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
