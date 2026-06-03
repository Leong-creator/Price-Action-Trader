#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.execution import ExecutionRequest, PaperBrokerAdapter, PaperPosition
from src.risk import PositionSnapshot, RiskConfig, SessionRiskState, evaluate_order_request
from src.strategy.contracts import Signal


DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_challenge_gate.json"
CHALLENGE_LEDGER = "m14_challenge_day_ledger.jsonl"
CHALLENGE_CORRECTION_LEDGER = "m14_challenge_day_correction_ledger.jsonl"
DECISION_LEDGER = "m14_strategy_decision_ledger.jsonl"
PAPER_GATE = "m14_paper_trial_gate.json"
EXECUTION_LEDGER = "m14_internal_paper_execution_ledger.jsonl"
SUMMARY_JSON = "m14_strategy_challenge_summary.json"
DASHBOARD_HTML = "m14_strategy_challenge_dashboard.html"
GOAL_STATUS_JSON = "m14_goal_status.json"
GOAL_PROMPT_MD = "m14_goal_prompt.md"
BLOCKER_STATES = {"not_connected", "detector_missing", "missing_data"}
ACTION_STATES = {
    "advance_internal_sim",
    "risk_limited_advance",
    "repair_now",
    "pause_runtime",
    "paper_candidate",
    "auxiliary_module",
}
DECISIONS = ACTION_STATES
INTERNAL_SIM_ACTION_STATES = {"advance_internal_sim", "risk_limited_advance", "paper_candidate"}
CHALLENGE_KEY_FIELDS = ("strategy_id", "runtime_id", "trading_date")
PARALLEL_MODIFY_VARIANTS = {
    "M10-PA-004-MBF": "M10-PA-004-MBF-QC",
}
RUNTIME_DEFAULT_ACTIONS = {
    "M10-PA-004-long-1d": {
        "action_state": "advance_internal_sim",
        "position_size_multiplier": Decimal("1.0"),
        "reason": "pa004_long_runtime_positive_primary_advance",
        "repair_focus": "",
        "trial_mode": "standard_internal_sim",
    },
    "M10-PA-005-5m": {
        "action_state": "risk_limited_advance",
        "position_size_multiplier": Decimal("0.25"),
        "reason": "pa005_5m_positive_but_high_drawdown_size_limited",
        "repair_focus": "tighten exposure cap, cooldown, and quality veto",
        "trial_mode": "risk_limited_internal_sim",
    },
    "M10-PA-005-1d": {
        "action_state": "risk_limited_advance",
        "position_size_multiplier": Decimal("0.25"),
        "reason": "pa005_1d_positive_small_sample_size_limited",
        "repair_focus": "keep one-day runtime separate and cap initial exposure",
        "trial_mode": "risk_limited_internal_sim",
    },
    "M10-PA-012-5m": {
        "action_state": "risk_limited_advance",
        "position_size_multiplier": Decimal("0.5"),
        "reason": "pa012_5m_positive_with_target_stop_repair",
        "repair_focus": "normalize target/stop geometry before increasing size",
        "trial_mode": "risk_limited_internal_sim",
    },
    "M10-PA-013-5m": {
        "action_state": "risk_limited_advance",
        "position_size_multiplier": Decimal("0.5"),
        "reason": "pa013_5m_positive_low_win_rate_size_limited",
        "repair_focus": "filter weak support-resistance failure signals",
        "trial_mode": "risk_limited_internal_sim",
    },
    "M10-PA-008-1d": {
        "action_state": "risk_limited_advance",
        "position_size_multiplier": Decimal("0.25"),
        "reason": "pa008_1d_positive_with_risk_cap_repair",
        "repair_focus": "keep quantity cap and single-order risk ceiling active",
        "trial_mode": "risk_limited_internal_sim",
    },
    "M10-PA-011-ORB-R1-5m": {
        "action_state": "repair_now",
        "position_size_multiplier": Decimal("0.10"),
        "reason": "pa011_orb_r1_high_drawdown_tiny_size_repair",
        "repair_focus": "repair opening-range breakout reversal drawdown before normal sizing",
        "trial_mode": "tiny_size_trial",
    },
    "M10-PA-011-5m": {
        "action_state": "repair_now",
        "position_size_multiplier": Decimal("0.10"),
        "reason": "pa011_orb_r1_high_drawdown_tiny_size_repair",
        "repair_focus": "repair opening-range breakout reversal drawdown before normal sizing",
        "trial_mode": "tiny_size_trial",
    },
}
AUXILIARY_MODULE_PURPOSES = {
    "M10-PA-003": "质量评分和排序模块，给主策略打分",
    "M10-PA-006": "限价入场过滤模块，过滤差入场",
    "M10-PA-010": "图形识别资料模块，帮助视觉策略补证据",
    "M10-PA-014": "目标价计算模块，服务止盈目标",
    "M10-PA-015": "止损和仓位模块，服务风控和数量计算",
    "M10-PA-016": "区间加仓辅助模块，服务已有主策略",
    "AI-TRADER-EXTERNAL": "外部参考信号，只做对照，不复制交易，不覆盖本项目判断",
}
ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class BoundaryConfig:
    paper_simulated_only: bool
    internal_simulated_account: bool
    broker_paper_connection: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool
    paper_trading_approval: bool


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    min_signal_days: int
    net_pnl_r_threshold: Decimal
    max_drawdown_percent_threshold: Decimal
    risk_block_ratio_threshold: Decimal
    data_mismatch_days_threshold: int


@dataclass(frozen=True, slots=True)
class InternalPaperConfig:
    enabled: bool
    max_risk_per_order: Decimal
    max_total_exposure: Decimal
    max_symbol_exposure_ratio: Decimal
    max_daily_loss: Decimal
    max_consecutive_losses: int


@dataclass(frozen=True, slots=True)
class M14Config:
    title: str
    run_id: str
    stage: str
    market: str
    output_dir: Path
    m13_output_dir: Path
    m12_29_output_dir: Path
    challenge_trading_days: int
    circuit_breaker: CircuitBreakerConfig
    internal_paper: InternalPaperConfig
    boundary: BoundaryConfig


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M14Config:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    circuit = payload["circuit_breaker"]
    paper = payload["internal_paper"]
    boundary = payload["boundary"]
    config = M14Config(
        title=payload["title"],
        run_id=payload.get("run_id", "m14_strategy_challenge_gate"),
        stage=payload["stage"],
        market=payload.get("market", "US"),
        output_dir=resolve_repo_path(payload["output_dir"]),
        m13_output_dir=resolve_repo_path(payload["m13_output_dir"]),
        m12_29_output_dir=resolve_repo_path(payload["m12_29_output_dir"]),
        challenge_trading_days=int(payload["challenge_trading_days"]),
        circuit_breaker=CircuitBreakerConfig(
            min_signal_days=int(circuit["min_signal_days"]),
            net_pnl_r_threshold=decimal(circuit["net_pnl_r_threshold"]),
            max_drawdown_percent_threshold=decimal(circuit["max_drawdown_percent_threshold"]),
            risk_block_ratio_threshold=decimal(circuit["risk_block_ratio_threshold"]),
            data_mismatch_days_threshold=int(circuit["data_mismatch_days_threshold"]),
        ),
        internal_paper=InternalPaperConfig(
            enabled=bool(paper["enabled"]),
            max_risk_per_order=decimal(paper["max_risk_per_order"]),
            max_total_exposure=decimal(paper["max_total_exposure"]),
            max_symbol_exposure_ratio=decimal(paper["max_symbol_exposure_ratio"]),
            max_daily_loss=decimal(paper["max_daily_loss"]),
            max_consecutive_losses=int(paper["max_consecutive_losses"]),
        ),
        boundary=BoundaryConfig(
            paper_simulated_only=bool(boundary["paper_simulated_only"]),
            internal_simulated_account=bool(boundary["internal_simulated_account"]),
            broker_paper_connection=bool(boundary["broker_paper_connection"]),
            trading_connection=bool(boundary["trading_connection"]),
            real_money_actions=bool(boundary["real_money_actions"]),
            live_execution=bool(boundary["live_execution"]),
            paper_trading_approval=bool(boundary["paper_trading_approval"]),
        ),
    )
    validate_config(config)
    return config


def validate_config(config: M14Config) -> None:
    if config.stage != "M14.strategy_challenge_paper_gate":
        raise ValueError("M14 stage drift")
    if config.challenge_trading_days != 10:
        raise ValueError("M14 challenge window must stay at 10 trading days")
    if config.circuit_breaker.min_signal_days < 3:
        raise ValueError("M14 circuit breaker cannot trigger before 3 signal days")
    if not config.boundary.paper_simulated_only or not config.boundary.internal_simulated_account:
        raise ValueError("M14 must stay paper/simulated with internal simulator enabled")
    if (
        config.boundary.broker_paper_connection
        or config.boundary.trading_connection
        or config.boundary.real_money_actions
        or config.boundary.live_execution
        or config.boundary.paper_trading_approval
    ):
        raise ValueError("M14 cannot enable broker paper, trading, live execution, real money, or approval")


def run_m14_strategy_challenge_gate(
    config: M14Config | None = None,
    *,
    generated_at: str | None = None,
    trading_date: str | date | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    resolved_trading_date = resolve_trading_date(config, generated_at, trading_date)
    run_id = f"{config.run_id}:{resolved_trading_date.isoformat()}:{generated_at}"

    signal_rows = [
        row
        for row in read_jsonl(config.m13_output_dir / "m13_strategy_signal_ledger.jsonl")
        if row.get("trading_date") == resolved_trading_date.isoformat()
    ]
    account_rows = [
        row
        for row in read_jsonl(config.m13_output_dir / "m13_account_operation_ledger.jsonl")
        if row.get("trading_date") == resolved_trading_date.isoformat()
    ]
    if not signal_rows:
        raise ValueError(f"No M13 signal ledger rows found for {resolved_trading_date.isoformat()}")

    m13_summary = read_json(config.m13_output_dir / "m13_daily_strategy_test_summary.json")
    m12_summary = load_m12_summary(config.m12_29_output_dir)
    scorecards_by_runtime = {
        row.get("runtime_id", ""): row
        for row in read_csv(config.m12_29_output_dir / "m12_46_account_scorecards.csv")
    }
    m12_trade_rows = filter_rows_for_trading_date(
        read_jsonl(config.m12_29_output_dir / "m12_46_account_trade_ledger.jsonl"),
        resolved_trading_date,
    )
    data_quality = build_data_quality_state(m12_summary)

    new_challenge_rows = build_challenge_day_rows(
        config=config,
        run_id=run_id,
        generated_at=generated_at,
        trading_date=resolved_trading_date,
        signal_rows=signal_rows,
        account_rows=account_rows,
        scorecards_by_runtime=scorecards_by_runtime,
        data_quality=data_quality,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    challenge_path = config.output_dir / CHALLENGE_LEDGER
    appended_challenge_rows = append_unique_jsonl(
        challenge_path,
        new_challenge_rows,
        key_fields=CHALLENGE_KEY_FIELDS,
    )
    raw_challenge_rows = read_jsonl(challenge_path)
    correction_path = config.output_dir / CHALLENGE_CORRECTION_LEDGER
    appended_correction_rows = append_challenge_corrections(
        correction_path,
        new_challenge_rows,
        raw_challenge_rows,
        generated_at=generated_at,
        key_fields=CHALLENGE_KEY_FIELDS,
    )
    challenge_rows = effective_challenge_rows(raw_challenge_rows, read_jsonl(correction_path), key_fields=CHALLENGE_KEY_FIELDS)
    strategy_aggregates = build_strategy_aggregates(config, challenge_rows)
    decision_rows = build_strategy_decision_rows(
        config=config,
        generated_at=generated_at,
        trading_date=resolved_trading_date,
        aggregates=strategy_aggregates,
    )
    decision_path = config.output_dir / DECISION_LEDGER
    decision_snapshot_rows = write_jsonl_snapshot(decision_path, decision_rows)
    latest_decisions = {runtime_key(row): row for row in decision_rows}
    paper_gate = build_paper_trial_gate(
        config,
        generated_at,
        latest_decisions,
        strategy_aggregates,
        allow_paper_candidates=paper_candidates_allowed(m12_summary, data_quality),
    )
    write_json(config.output_dir / PAPER_GATE, paper_gate)

    execution_rows = run_internal_paper_bridge(
        config=config,
        run_id=run_id,
        generated_at=generated_at,
        trading_date=resolved_trading_date,
        paper_gate=paper_gate,
        m12_trade_rows=m12_trade_rows,
    )
    appended_execution_rows = append_unique_jsonl(
        config.output_dir / EXECUTION_LEDGER,
        execution_rows,
        key_fields=("execution_event_id",),
    )

    summary = build_summary(
        config=config,
        generated_at=generated_at,
        trading_date=resolved_trading_date,
        m13_summary=m13_summary,
        m12_summary=m12_summary,
        data_quality=data_quality,
        challenge_rows=challenge_rows,
        appended_challenge_rows=appended_challenge_rows,
        appended_correction_rows=appended_correction_rows,
        decision_snapshot_rows=decision_snapshot_rows,
        appended_execution_rows=appended_execution_rows,
        strategy_aggregates=strategy_aggregates,
        decisions=latest_decisions,
        paper_gate=paper_gate,
    )
    goal_status = build_goal_status(summary)
    dashboard_html = build_dashboard_html(summary, strategy_aggregates, latest_decisions, paper_gate)

    write_json(config.output_dir / SUMMARY_JSON, summary)
    write_json(config.output_dir / GOAL_STATUS_JSON, goal_status)
    (config.output_dir / DASHBOARD_HTML).write_text(dashboard_html, encoding="utf-8")
    (config.output_dir / GOAL_PROMPT_MD).write_text(build_goal_prompt_md(), encoding="utf-8")
    return {
        "summary": summary,
        "goal_status": goal_status,
        "challenge_rows": challenge_rows,
        "raw_challenge_rows": raw_challenge_rows,
        "new_challenge_rows": new_challenge_rows,
        "appended_challenge_rows": appended_challenge_rows,
        "appended_correction_rows": appended_correction_rows,
        "decision_rows": decision_rows,
        "appended_decision_rows": decision_snapshot_rows,
        "paper_gate": paper_gate,
        "execution_rows": execution_rows,
        "appended_execution_rows": appended_execution_rows,
        "strategy_aggregates": strategy_aggregates,
    }


def run_m14_strategy_challenge_recompute(
    config: M14Config | None = None,
    *,
    generated_at: str | None = None,
    trading_date: str | date | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    raw_challenge_rows = read_jsonl(config.output_dir / CHALLENGE_LEDGER)
    correction_rows = read_jsonl(config.output_dir / CHALLENGE_CORRECTION_LEDGER)
    challenge_rows = effective_challenge_rows(raw_challenge_rows, correction_rows, key_fields=CHALLENGE_KEY_FIELDS)
    if not challenge_rows:
        raise ValueError("No M14 challenge history found for recompute")
    if trading_date is None:
        resolved_trading_date = date.fromisoformat(max(str(row.get("trading_date", "")) for row in challenge_rows if row.get("trading_date")))
    else:
        resolved_trading_date = date.fromisoformat(trading_date) if isinstance(trading_date, str) else trading_date

    strategy_aggregates = build_strategy_aggregates(config, challenge_rows)
    decision_rows = build_strategy_decision_rows(
        config=config,
        generated_at=generated_at,
        trading_date=resolved_trading_date,
        aggregates=strategy_aggregates,
    )
    decision_path = config.output_dir / DECISION_LEDGER
    decision_snapshot_rows = write_jsonl_snapshot(decision_path, decision_rows)
    latest_decisions = {runtime_key(row): row for row in decision_rows}
    m12_summary = load_m12_summary(config.m12_29_output_dir)
    paper_gate = build_paper_trial_gate(
        config,
        generated_at,
        latest_decisions,
        strategy_aggregates,
        allow_paper_candidates=paper_candidates_allowed(m12_summary, {"state": "history_recompute_from_existing_challenge", "warning": ""}),
    )
    write_json(config.output_dir / PAPER_GATE, paper_gate)
    m13_summary = read_json(config.m13_output_dir / "m13_daily_strategy_test_summary.json")
    summary = build_summary(
        config=config,
        generated_at=generated_at,
        trading_date=resolved_trading_date,
        m13_summary=m13_summary,
        m12_summary=m12_summary,
        data_quality={"state": "history_recompute_from_existing_challenge", "warning": ""},
        challenge_rows=challenge_rows,
        appended_challenge_rows=[],
        appended_correction_rows=[],
        decision_snapshot_rows=decision_snapshot_rows,
        appended_execution_rows=[],
        strategy_aggregates=strategy_aggregates,
        decisions=latest_decisions,
        paper_gate=paper_gate,
    )
    summary["recompute_only"] = True
    summary["recompute_reason"] = "existing_challenge_history_gate_recalculation"
    goal_status = build_goal_status(summary)
    dashboard_html = build_dashboard_html(summary, strategy_aggregates, latest_decisions, paper_gate)
    write_json(config.output_dir / SUMMARY_JSON, summary)
    write_json(config.output_dir / GOAL_STATUS_JSON, goal_status)
    (config.output_dir / DASHBOARD_HTML).write_text(dashboard_html, encoding="utf-8")
    (config.output_dir / GOAL_PROMPT_MD).write_text(build_goal_prompt_md(), encoding="utf-8")
    return {
        "summary": summary,
        "goal_status": goal_status,
        "challenge_rows": challenge_rows,
        "raw_challenge_rows": raw_challenge_rows,
        "decision_rows": decision_rows,
        "appended_decision_rows": decision_snapshot_rows,
        "paper_gate": paper_gate,
        "execution_rows": [],
        "appended_execution_rows": [],
        "strategy_aggregates": strategy_aggregates,
    }


def build_challenge_day_rows(
    *,
    config: M14Config,
    run_id: str,
    generated_at: str,
    trading_date: date,
    signal_rows: list[dict[str, Any]],
    account_rows: list[dict[str, Any]],
    scorecards_by_runtime: dict[str, dict[str, str]],
    data_quality: dict[str, str],
) -> list[dict[str, Any]]:
    account_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in account_rows:
        account_by_key[(str(row.get("strategy_id", "")), str(row.get("runtime_id", "")))].append(row)

    rows: list[dict[str, Any]] = []
    for signal in sorted(signal_rows, key=lambda row: (str(row.get("strategy_id", "")), str(row.get("runtime_id", "")))):
        strategy_id = str(signal.get("strategy_id", ""))
        runtime_id = str(signal.get("runtime_id", ""))
        operations = account_by_key.get((strategy_id, runtime_id), [])
        realized_pnl = sum((decimal_or_zero(row.get("realized_pnl")) for row in operations if row.get("event_type") == "close"), ZERO)
        open_count = sum(1 for row in operations if row.get("event_type") == "open")
        close_count = sum(1 for row in operations if row.get("event_type") == "close")
        risk_blocked_count = sum(1 for row in operations if row.get("test_state") == "risk_blocked")
        signal_count = int_or_zero(signal.get("signal_count"))
        scorecard = scorecards_by_runtime.get(runtime_id, {})
        equity = latest_non_empty([row.get("equity", "") for row in operations]) or scorecard.get("equity", "")
        max_drawdown = scorecard.get("max_drawdown_percent", "")
        test_states = sorted({str(signal.get("test_state", ""))} | {str(row.get("test_state", "")) for row in operations if row.get("test_state")})
        blocker_reason = build_blocker_reason(test_states, data_quality)
        rows.append(
            {
                "schema_version": "m14.challenge-day-ledger.v1",
                "stage": config.stage,
                "run_id": run_id,
                "generated_at": generated_at,
                "trading_date": trading_date.isoformat(),
                "strategy_id": strategy_id,
                "display_name": signal.get("display_name", ""),
                "module_role": signal.get("module_role", ""),
                "runtime_id": runtime_id,
                "lane": signal.get("lane", ""),
                "timeframe": signal.get("timeframe", ""),
                "variant_id": signal.get("variant_id", ""),
                "required_for_goal": bool(signal.get("required_for_goal", False)),
                "detector_id": signal.get("detector_id", ""),
                "test_state": signal.get("test_state", ""),
                "account_test_states": ",".join(test_states),
                "signal_count": signal_count,
                "zero_signal_day": signal_count == 0 and signal.get("test_state") == "zero_signal",
                "open_count": open_count,
                "close_count": close_count,
                "risk_blocked_count": risk_blocked_count,
                "realized_pnl": money(realized_pnl),
                "net_pnl_r": fmt_decimal(safe_div(realized_pnl, config.internal_paper.max_risk_per_order)),
                "equity": equity,
                "max_drawdown_percent": max_drawdown,
                "blocker_reason": blocker_reason,
                "data_quality_state": data_quality["state"],
                "data_freshness_warning": data_quality["warning"],
                "next_action": signal.get("next_action", ""),
                "paper_simulated_only": True,
                "internal_simulated_account": True,
                "broker_paper_connection": False,
                "trading_connection": False,
                "real_money_actions": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return rows


def build_strategy_aggregates(config: M14Config, challenge_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in challenge_rows:
        grouped[runtime_key(row)].append(row)

    aggregates: dict[str, dict[str, Any]] = {}
    for group_key, rows in grouped.items():
        dates = sorted({str(row.get("trading_date", "")) for row in rows if row.get("trading_date")})
        by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_date[str(row.get("trading_date", ""))].append(row)
        valid_dates = sorted(
            day
            for day, day_rows in by_date.items()
            if day and all(row.get("data_quality_state") == "fully_ready" for row in day_rows)
        )
        valid_date_set = set(valid_dates)
        valid_rows = [row for row in rows if str(row.get("trading_date", "")) in valid_date_set]
        signal_days = sum(1 for day_rows in by_date.values() if sum(int_or_zero(row.get("signal_count")) for row in day_rows) > 0)
        valid_signal_days = sum(
            1
            for day, day_rows in by_date.items()
            if day in valid_date_set and sum(int_or_zero(row.get("signal_count")) for row in day_rows) > 0
        )
        zero_signal_days = sum(
            1
            for day, day_rows in by_date.items()
            if day in valid_date_set
            and sum(int_or_zero(row.get("signal_count")) for row in day_rows) == 0
            and any(row.get("test_state") == "zero_signal" for row in day_rows)
        )
        observed_zero_signal_days = sum(
            1
            for day_rows in by_date.values()
            if sum(int_or_zero(row.get("signal_count")) for row in day_rows) == 0
            and any(row.get("test_state") == "zero_signal" for row in day_rows)
        )
        observed_data_mismatch_days = sum(
            1 for day_rows in by_date.values() if any(row.get("data_quality_state") != "fully_ready" for row in day_rows)
        )
        data_mismatch_days = sum(
            1
            for day, day_rows in by_date.items()
            if day in valid_date_set and any(row.get("data_quality_state") != "fully_ready" for row in day_rows)
        )
        realized_pnl = sum((decimal_or_zero(row.get("realized_pnl")) for row in valid_rows), ZERO)
        total_signals = sum(int_or_zero(row.get("signal_count")) for row in valid_rows)
        risk_blocks = sum(int_or_zero(row.get("risk_blocked_count")) for row in valid_rows)
        max_drawdown = max((decimal_or_zero(row.get("max_drawdown_percent")) for row in valid_rows), default=ZERO)
        latest = sorted(rows, key=lambda row: (str(row.get("trading_date", "")), str(row.get("generated_at", ""))))[-1]
        runtime_id = str(latest.get("runtime_id") or group_key)
        strategy_id = str(latest.get("strategy_id") or group_key)
        aggregates[group_key] = {
            "runtime_key": group_key,
            "runtime_id": runtime_id,
            "strategy_id": strategy_id,
            "timeframe": latest.get("timeframe", ""),
            "display_name": latest.get("display_name", ""),
            "module_role": latest.get("module_role", ""),
            "required_for_goal": bool(latest.get("required_for_goal", False)),
            "runtime_ids": sorted({str(row.get("runtime_id", "")) for row in rows if row.get("runtime_id")}),
            "variant_ids": sorted({str(row.get("variant_id", "")) for row in rows if row.get("variant_id")}),
            "observed_trading_days": len(dates),
            "completed_trading_days": len(valid_dates),
            "required_trading_days": config.challenge_trading_days,
            "progress_label": f"{min(len(valid_dates), config.challenge_trading_days)}/{config.challenge_trading_days}",
            "first_trading_date": dates[0] if dates else "",
            "latest_trading_date": dates[-1] if dates else "",
            "first_valid_trading_date": valid_dates[0] if valid_dates else "",
            "latest_valid_trading_date": valid_dates[-1] if valid_dates else "",
            "signal_days": valid_signal_days,
            "observed_signal_days": signal_days,
            "zero_signal_days": zero_signal_days,
            "observed_zero_signal_days": observed_zero_signal_days,
            "total_signal_count": total_signals,
            "open_count": sum(int_or_zero(row.get("open_count")) for row in valid_rows),
            "close_count": sum(int_or_zero(row.get("close_count")) for row in valid_rows),
            "risk_blocked_count": risk_blocks,
            "risk_block_ratio": fmt_decimal(safe_div(Decimal(risk_blocks), Decimal(max(total_signals, 1)))),
            "realized_pnl": money(realized_pnl),
            "net_pnl_r": fmt_decimal(safe_div(realized_pnl, config.internal_paper.max_risk_per_order)),
            "max_drawdown_percent": fmt_decimal(max_drawdown),
            "data_mismatch_days": data_mismatch_days,
            "observed_data_mismatch_days": observed_data_mismatch_days,
            "blocker_reasons": sorted({str(row.get("blocker_reason", "")) for row in rows if row.get("blocker_reason")}),
            "data_freshness_warnings": sorted({str(row.get("data_freshness_warning", "")) for row in rows if row.get("data_freshness_warning")}),
        }
    return aggregates


def build_strategy_decision_rows(
    *,
    config: M14Config,
    generated_at: str,
    trading_date: date,
    aggregates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(aggregates):
        aggregate = aggregates[key]
        decision, reason, circuit, frozen, modify_candidate, variant, position_size, repair_focus, trial_mode = decide_strategy(config, aggregate, trading_date)
        if decision not in DECISIONS:
            raise ValueError(f"Unsupported M14 decision: {decision}")
        rows.append(
            {
                "schema_version": "m14.strategy-decision-ledger.v1",
                "stage": config.stage,
                "generated_at": generated_at,
                "trading_date": trading_date.isoformat(),
                "runtime_id": str(aggregate.get("runtime_id") or aggregate.get("strategy_id") or ""),
                "strategy_id": str(aggregate.get("strategy_id") or aggregate.get("runtime_id") or ""),
                "timeframe": str(aggregate.get("timeframe", "")),
                "display_name": clean_auxiliary_text(aggregate["display_name"]),
                "module_role": aggregate["module_role"],
                "runtime_role": runtime_role_for(decision, str(aggregate.get("strategy_id") or "")),
                "auxiliary_module_purpose": auxiliary_module_purpose(str(aggregate.get("strategy_id") or ""), str(aggregate.get("module_role") or "")),
                "standalone_trading_allowed": decision != "auxiliary_module",
                "display_action": display_action_for(
                    decision,
                    str(aggregate.get("strategy_id") or ""),
                    str(aggregate.get("module_role") or ""),
                ),
                "required_for_goal": aggregate["required_for_goal"],
                "decision": decision,
                "action_state": decision,
                "decision_reason": reason,
                "repair_focus": repair_focus,
                "trial_mode": trial_mode,
                "position_size_multiplier": fmt_decimal(position_size),
                "paper_candidate": decision in INTERNAL_SIM_ACTION_STATES,
                "circuit_breaker_triggered": circuit,
                "frozen": frozen,
                "modify_candidate": modify_candidate,
                "next_variant_id": variant,
                "observed_trading_days": aggregate.get("observed_trading_days", aggregate["completed_trading_days"]),
                "completed_trading_days": aggregate["completed_trading_days"],
                "required_trading_days": config.challenge_trading_days,
                "observed_signal_days": aggregate.get("observed_signal_days", aggregate["signal_days"]),
                "signal_days": aggregate["signal_days"],
                "observed_zero_signal_days": aggregate.get("observed_zero_signal_days", aggregate["zero_signal_days"]),
                "zero_signal_days": aggregate["zero_signal_days"],
                "total_signal_count": aggregate["total_signal_count"],
                "open_count": aggregate["open_count"],
                "close_count": aggregate["close_count"],
                "realized_pnl": aggregate["realized_pnl"],
                "net_pnl_r": aggregate["net_pnl_r"],
                "max_drawdown_percent": aggregate["max_drawdown_percent"],
                "risk_blocked_count": aggregate["risk_blocked_count"],
                "risk_block_ratio": aggregate["risk_block_ratio"],
                "data_mismatch_days": aggregate["data_mismatch_days"],
                "observed_data_mismatch_days": aggregate.get("observed_data_mismatch_days", aggregate["data_mismatch_days"]),
                "paper_simulated_only": True,
                "internal_simulated_account": True,
                "broker_paper_connection": False,
                "trading_connection": False,
                "real_money_actions": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return rows


def decide_strategy(
    config: M14Config,
    aggregate: dict[str, Any],
    trading_date: date,
) -> tuple[str, str, bool, bool, bool, str, Decimal, str, str]:
    role = aggregate["module_role"]
    completed_days = int(aggregate["completed_trading_days"])
    signal_days = int(aggregate["signal_days"])
    net_pnl_r = decimal_or_zero(aggregate["net_pnl_r"])
    max_drawdown = decimal_or_zero(aggregate["max_drawdown_percent"])
    risk_block_ratio = decimal_or_zero(aggregate["risk_block_ratio"])
    data_mismatch_days = int(aggregate["data_mismatch_days"])
    observed_data_mismatch_days = int(aggregate.get("observed_data_mismatch_days", data_mismatch_days))
    total_signal_count = int(aggregate["total_signal_count"])
    open_count = int(aggregate["open_count"])
    close_count = int(aggregate["close_count"])
    runtime_id = str(aggregate.get("runtime_id") or aggregate.get("strategy_id") or "")
    strategy_id = str(aggregate.get("strategy_id") or runtime_id)
    auxiliary_purpose = auxiliary_module_purpose(strategy_id, role)

    def result(
        action_state: str,
        reason: str,
        circuit: bool,
        frozen: bool,
        modify_candidate: bool,
        variant: str = "",
        position_size: Decimal = Decimal("1.0"),
        repair_focus: str = "",
        trial_mode: str = "",
    ) -> tuple[str, str, bool, bool, bool, str, Decimal, str, str]:
        return (
            action_state,
            reason,
            circuit,
            frozen,
            modify_candidate,
            variant,
            position_size,
            repair_focus,
            trial_mode or action_state,
        )

    if auxiliary_purpose:
        return result(
            "auxiliary_module",
            "auxiliary_module_not_standalone_trading",
            False,
            False,
            False,
            repair_focus=f"辅助模块：{auxiliary_purpose}，不作为独立交易策略",
            trial_mode="auxiliary_module_support",
        )
    if role == "external_research":
        return result("auxiliary_module", "auxiliary_module_not_standalone_trading", False, False, False, repair_focus="辅助模块：外部参考信号，只做对照，不复制交易，不覆盖本项目判断", trial_mode="auxiliary_module_support")
    if role == "research_only":
        return result("auxiliary_module", "auxiliary_module_not_standalone_trading", False, False, False, repair_focus="辅助模块：资料和图形证据服务主策略，不作为独立交易策略", trial_mode="auxiliary_module_support")
    if role == "plugin_filter":
        return result("auxiliary_module", "auxiliary_module_not_standalone_trading", False, False, False, repair_focus="辅助模块：筛选、风控或目标价服务主策略，不作为独立交易策略", trial_mode="auxiliary_module_support")
    if data_mismatch_days >= config.circuit_breaker.data_mismatch_days_threshold or (
        observed_data_mismatch_days > 0 and completed_days == 0
    ):
        return result("pause_runtime", "data_quality_circuit_breaker_no_paper_candidate", True, True, False, repair_focus="rerun only after fully-ready M12/M13 ledger")

    default = RUNTIME_DEFAULT_ACTIONS.get(runtime_id)
    if default and default["action_state"] != "repair_now":
        return result(
            str(default["action_state"]),
            str(default["reason"]),
            bool(max_drawdown > config.circuit_breaker.max_drawdown_percent_threshold or risk_block_ratio > config.circuit_breaker.risk_block_ratio_threshold),
            False,
            False,
            "",
            default["position_size_multiplier"],
            str(default["repair_focus"]),
            str(default["trial_mode"]),
        )
    if default and default["action_state"] == "repair_now":
        return result(
            "repair_now",
            str(default["reason"]),
            True,
            False,
            True,
            f"{strategy_id}-m14-repair-{trading_date.strftime('%Y%m%d')}",
            default["position_size_multiplier"],
            str(default["repair_focus"]),
            str(default["trial_mode"]),
        )

    if signal_days >= config.circuit_breaker.min_signal_days:
        variant = f"{strategy_id}-m14-repair-{trading_date.strftime('%Y%m%d')}"
        parallel_variant = PARALLEL_MODIFY_VARIANTS.get(strategy_id)
        if net_pnl_r < config.circuit_breaker.net_pnl_r_threshold:
            if parallel_variant:
                return result("risk_limited_advance", "parallel_repair_variant_started_size_limited_original", True, False, True, parallel_variant, Decimal("0.50"), "compare parallel variant while preserving original evidence")
            return result("repair_now", "net_pnl_below_minus_2r", True, False, True, variant, Decimal("0.10"), "repair entry quality, stop distance, and loss controls before normal sizing", "tiny_size_trial")
        if max_drawdown > config.circuit_breaker.max_drawdown_percent_threshold:
            if parallel_variant:
                return result("risk_limited_advance", "parallel_repair_variant_started_size_limited_original", True, False, True, parallel_variant, Decimal("0.50"), "drawdown warning; keep size capped")
            return result("risk_limited_advance", "max_drawdown_warning_size_limited", True, False, True, variant, Decimal("0.25"), "reduce size and repair drawdown controls")
        if risk_block_ratio > config.circuit_breaker.risk_block_ratio_threshold:
            if parallel_variant:
                return result("risk_limited_advance", "parallel_repair_variant_started_size_limited_original", True, False, True, parallel_variant, Decimal("0.50"), "risk-block warning; keep size capped")
            return result("risk_limited_advance", "risk_blocks_dominate_signals_size_limited", True, False, True, variant, Decimal("0.25"), "repair risk filters and exposure controls")

    if completed_days >= config.challenge_trading_days:
        if total_signal_count == 0:
            return result("repair_now", "ten_days_no_viable_signal", False, False, True, f"{strategy_id}-m14-repair-{trading_date.strftime('%Y%m%d')}", Decimal("0.10"), "rebuild detector or pause runtime after no-signal audit", "tiny_size_trial")
        if net_pnl_r > ZERO and max_drawdown <= config.circuit_breaker.max_drawdown_percent_threshold and data_mismatch_days == 0:
            return result("advance_internal_sim", "ten_day_positive_expectancy_internal_sim_candidate", False, False, False)
        if net_pnl_r <= ZERO:
            variant = f"{strategy_id}-m14-repair-{trading_date.strftime('%Y%m%d')}"
            return result("repair_now", "ten_day_losing_repair_candidate", False, False, True, variant, Decimal("0.10"), "repair losing runtime; do not advance until current ledger turns positive", "tiny_size_trial")
        return result("risk_limited_advance", "ten_day_positive_but_risk_limited", False, False, False, position_size=Decimal("0.25"), repair_focus="positive ledger, but risk metrics require capped sizing")

    if total_signal_count == 0 and open_count == 0 and close_count == 0:
        return result("repair_now", "zero_signal_or_no_execution_repair_now", False, False, True, f"{strategy_id}-m14-repair-{trading_date.strftime('%Y%m%d')}", Decimal("0.10"), "fix detector/input mapping; no generic observation state", "tiny_size_trial")
    if net_pnl_r > ZERO:
        return result("risk_limited_advance", "positive_before_full_window_size_limited", False, False, False, position_size=Decimal("0.50"), repair_focus="advance with capped size while challenge evidence continues")
    return result("repair_now", "incomplete_window_no_profit_repair_now", False, False, True, f"{strategy_id}-m14-repair-{trading_date.strftime('%Y%m%d')}", Decimal("0.10"), "repair signal quality or execution mapping before next run", "tiny_size_trial")


def auxiliary_module_purpose(strategy_id: str, module_role: str = "") -> str:
    if strategy_id in AUXILIARY_MODULE_PURPOSES:
        return AUXILIARY_MODULE_PURPOSES[strategy_id]
    if module_role == "external_research":
        return AUXILIARY_MODULE_PURPOSES["AI-TRADER-EXTERNAL"]
    if module_role == "research_only":
        return "资料和图形证据服务主策略"
    if module_role == "plugin_filter":
        return "筛选、风控、目标价或仓位服务主策略"
    return ""


def runtime_role_for(action_state: str, strategy_id: str) -> str:
    if action_state == "auxiliary_module" or strategy_id in AUXILIARY_MODULE_PURPOSES:
        return "auxiliary_module"
    return "trading_runtime"


def display_action_for(action_state: str, strategy_id: str, module_role: str = "") -> str:
    purpose = auxiliary_module_purpose(strategy_id, module_role)
    if action_state == "auxiliary_module" or purpose:
        return f"辅助模块：启用为{purpose}，不作为独立交易策略"
    labels = {
        "advance_internal_sim": "推进内部模拟",
        "risk_limited_advance": "风险受限推进",
        "repair_now": "立即修复",
        "pause_runtime": "暂停运行单元直到数据或执行链修复",
        "paper_candidate": "长桥模拟账户候选",
    }
    return labels.get(action_state, action_state)


def clean_auxiliary_text(value: Any) -> str:
    text = str(value)
    replacements = {
        "research-only": "auxiliary-module",
        "Research-only": "Auxiliary-module",
        "shadow/plugin/research": "auxiliary-module",
        "plugin/filter": "auxiliary",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def build_paper_trial_gate(
    config: M14Config,
    generated_at: str,
    decisions: dict[str, dict[str, Any]],
    aggregates: dict[str, dict[str, Any]],
    *,
    allow_paper_candidates: bool = True,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for key in sorted(aggregates):
        aggregate = aggregates[key]
        decision = decisions[key]
        completed_days = int(decision["completed_trading_days"])
        data_mismatch_days = int(decision["data_mismatch_days"])
        observed_data_mismatch_days = int(decision.get("observed_data_mismatch_days", data_mismatch_days))
        action_state = str(decision.get("action_state") or decision.get("decision", ""))
        position_size = decimal_or_zero(decision.get("position_size_multiplier", "1"))
        if (
            action_state == "advance_internal_sim"
            and int(decision["completed_trading_days"]) >= config.challenge_trading_days
            and int(decision["data_mismatch_days"]) == 0
        ):
            gate_status = "approved_internal_sim_only"
            reason = "Runtime has positive 10-day evidence; internal simulator only."
        elif action_state == "advance_internal_sim":
            gate_status = "advance_internal_sim"
            reason = "Runtime advances in internal simulation; broker paper remains disabled."
        elif action_state == "risk_limited_advance":
            gate_status = "risk_limited_internal_sim"
            reason = f"Runtime advances with position size multiplier {fmt_decimal(position_size)}; risk warning stays active."
        elif action_state == "repair_now":
            gate_status = "repair_now"
            reason = f"Runtime needs concrete repair: {decision.get('repair_focus', '') or decision.get('decision_reason', '')}."
        elif action_state == "auxiliary_module":
            gate_status = "auxiliary_module"
            reason = str(decision.get("display_action") or decision.get("repair_focus") or "辅助模块：不作为独立交易策略")
        elif action_state == "pause_runtime":
            gate_status = "pause_runtime"
            reason = f"Runtime is paused until blocker is fixed: {decision.get('repair_focus', '') or decision.get('decision_reason', '')}."
        elif (data_mismatch_days > 0 or observed_data_mismatch_days > 0) and completed_days == 0:
            gate_status = "pause_runtime"
            reason = "No fully-ready challenge day is available yet; fallback/no-fetch days cannot enter paper candidate."
        elif data_mismatch_days > 0 or (observed_data_mismatch_days > 0 and completed_days < config.challenge_trading_days):
            gate_status = "pause_runtime"
            reason = "Only fully-ready trading days count; degraded days are audit-only and cannot enter paper candidate."
        else:
            gate_status = "repair_now"
            reason = "No generic observation state is allowed; define the next repair or sizing action."
        paper_candidate = (
            allow_paper_candidates
            and action_state in {"advance_internal_sim", "risk_limited_advance", "paper_candidate"}
            and data_mismatch_days == 0
        )
        rows.append(
            {
                "runtime_id": aggregate["runtime_id"],
                "strategy_id": aggregate["strategy_id"],
                "timeframe": aggregate["timeframe"],
                "display_name": clean_auxiliary_text(aggregate["display_name"]),
                "module_role": aggregate.get("module_role", ""),
                "runtime_role": decision.get("runtime_role", runtime_role_for(action_state, str(aggregate.get("strategy_id", "")))),
                "auxiliary_module_purpose": decision.get("auxiliary_module_purpose", ""),
                "standalone_trading_allowed": bool(decision.get("standalone_trading_allowed", action_state != "auxiliary_module")),
                "display_action": decision.get("display_action", display_action_for(action_state, str(aggregate.get("strategy_id", "")), str(aggregate.get("module_role", "")))),
                "paper_trial_gate": gate_status,
                "gate_reason": reason,
                "decision": decision["decision"],
                "action_state": action_state,
                "decision_reason": decision["decision_reason"],
                "repair_focus": decision.get("repair_focus", ""),
                "trial_mode": decision.get("trial_mode", ""),
                "position_size_multiplier": fmt_decimal(position_size),
                "paper_candidate": paper_candidate,
                "completed_trading_days": decision["completed_trading_days"],
                "required_trading_days": config.challenge_trading_days,
                "runtime_ids": aggregate["runtime_ids"],
                "broker_paper_connection": False,
                "trading_connection": False,
                "real_money_actions": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return {
        "schema_version": "m14.paper-trial-gate.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "gate_scope": "internal_simulated_account_only",
        "rows": rows,
        "approved_internal_sim_strategy_ids": sorted({row["strategy_id"] for row in rows if row["action_state"] in INTERNAL_SIM_ACTION_STATES}),
        "approved_internal_sim_runtime_ids": [row["runtime_id"] for row in rows if row["action_state"] in INTERNAL_SIM_ACTION_STATES],
        "risk_limited_runtime_ids": [row["runtime_id"] for row in rows if row["action_state"] == "risk_limited_advance"],
        "auxiliary_module_runtime_ids": [row["runtime_id"] for row in rows if row["action_state"] == "auxiliary_module"],
        "auxiliary_module_strategy_ids": sorted({row["strategy_id"] for row in rows if row["action_state"] == "auxiliary_module"}),
        "paper_candidate_runtime_ids": [row["runtime_id"] for row in rows if row["paper_candidate"]],
        "paper_simulated_only": True,
        "internal_simulated_account": True,
        "broker_paper_connection": False,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def run_internal_paper_bridge(
    *,
    config: M14Config,
    run_id: str,
    generated_at: str,
    trading_date: date,
    paper_gate: dict[str, Any],
    m12_trade_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not config.internal_paper.enabled:
        return []
    approved = {row["runtime_id"] for row in paper_gate["rows"] if row.get("action_state") in INTERNAL_SIM_ACTION_STATES}
    sizing_by_runtime = {
        str(row.get("runtime_id", "")): decimal_or_zero(row.get("position_size_multiplier", "1"))
        for row in paper_gate["rows"]
        if row.get("action_state") in INTERNAL_SIM_ACTION_STATES
    }
    if not approved:
        return []
    adapter = PaperBrokerAdapter()
    risk_config = RiskConfig(
        max_risk_per_order=config.internal_paper.max_risk_per_order,
        max_total_exposure=config.internal_paper.max_total_exposure,
        max_symbol_exposure_ratio=config.internal_paper.max_symbol_exposure_ratio,
        max_daily_loss=config.internal_paper.max_daily_loss,
        max_consecutive_losses=config.internal_paper.max_consecutive_losses,
    )
    positions_by_runtime: dict[str, tuple[PaperPosition, ...]] = defaultdict(tuple)
    seen_by_runtime: dict[str, frozenset[str]] = defaultdict(frozenset)
    state_by_runtime: dict[str, SessionRiskState] = defaultdict(lambda: SessionRiskState(session_key=trading_date.isoformat()))
    events: list[dict[str, Any]] = []
    bridge_rows = [
        row
        for row in m12_trade_rows
        if row.get("event_type") in {"open", "close"} and row.get("runtime_id") in approved
    ]
    indexed_rows = list(enumerate(bridge_rows))
    for source_index, row in sorted(
        indexed_rows,
        key=lambda item: (
            str(item[1].get("event_time", "")),
            str(item[1].get("runtime_id", "")),
            0 if item[1].get("event_type") == "open" else 1,
            item[0],
        ),
    ):
        if row.get("event_type") == "close":
            runtime_id = str(row.get("runtime_id", ""))
            row = scaled_trade_row(row, sizing_by_runtime.get(runtime_id, Decimal("1")))
            positions = positions_by_runtime[runtime_id]
            session_state = state_by_runtime[runtime_id]
            matched_position = match_close_position(row, positions)
            if matched_position is None:
                events.append(
                    {
                        "schema_version": "m14.internal-paper-execution-ledger.v1",
                        "stage": config.stage,
                        "execution_event_id": f"{run_id}:{runtime_id}:{row.get('symbol', '')}:{source_index}:position_close_unmatched",
                        "run_id": run_id,
                        "generated_at": generated_at,
                        "trading_date": trading_date.isoformat(),
                        "strategy_id": row.get("strategy_id", ""),
                        "runtime_id": runtime_id,
                        "signal_id": "",
                        "symbol": row.get("symbol", ""),
                        "timeframe": row.get("timeframe", ""),
                        "direction": normalize_direction(str(row.get("direction", ""))),
                        "action": "position_close_unmatched",
                        "status": "error",
                        "risk_outcome": "",
                        "reason_codes": "missing_open_position_in_internal_bridge",
                        "quantity": fmt_decimal(decimal_or_zero(row.get("quantity"))),
                        "entry_price": fmt_decimal(decimal_or_zero(row.get("entry_price"))),
                        "exit_price": fmt_decimal(decimal_or_zero(row.get("exit_price"))),
                        "stop_price": fmt_decimal(decimal_or_zero(row.get("stop_price"))),
                        "target_price": fmt_decimal(decimal_or_zero(row.get("target_price"))),
                        "related_position_id": "",
                        "related_fill_id": "",
                        "fill_simulated": False,
                        "simulated": True,
                        "internal_simulated_account": True,
                        "broker_paper_connection": False,
                        "trading_connection": False,
                        "real_money_actions": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    }
                )
                continue
            close_result = adapter.close_position(
                position_id=matched_position.position_id,
                exit_price=decimal(row.get("exit_price")),
                closed_at=parse_datetime(str(row.get("event_time", trading_date.isoformat()))),
                positions=positions,
                session_state=session_state,
                config=risk_config,
                session_key=trading_date.isoformat(),
                exit_reason=str(row.get("exit_reason", "ledger_close")),
            )
            positions_by_runtime[runtime_id] = close_result.resulting_positions
            state_by_runtime[runtime_id] = close_result.session_state
            for log_index, log in enumerate(close_result.logs):
                events.append(
                    {
                        "schema_version": "m14.internal-paper-execution-ledger.v1",
                        "stage": config.stage,
                        "execution_event_id": f"{run_id}:{runtime_id}:{matched_position.position_id}:{source_index}:{log_index}:{log.action}",
                        "run_id": run_id,
                        "generated_at": generated_at,
                        "trading_date": trading_date.isoformat(),
                        "strategy_id": row.get("strategy_id", ""),
                        "runtime_id": runtime_id,
                        "signal_id": log.signal_id or "",
                        "symbol": log.symbol or row.get("symbol", ""),
                        "timeframe": row.get("timeframe", ""),
                        "direction": normalize_direction(str(row.get("direction", ""))),
                        "action": log.action,
                        "status": log.status,
                        "risk_outcome": "",
                        "reason_codes": ",".join(log.reason_codes),
                        "quantity": fmt_decimal(log.quantity) if log.quantity is not None else "",
                        "entry_price": fmt_decimal(log.entry_price) if log.entry_price is not None else "",
                        "exit_price": fmt_decimal(log.exit_price) if log.exit_price is not None else "",
                        "realized_pnl": fmt_decimal(log.realized_pnl) if log.realized_pnl is not None else "",
                        "stop_price": fmt_decimal(decimal_or_zero(row.get("stop_price"))),
                        "target_price": fmt_decimal(decimal_or_zero(row.get("target_price"))),
                        "related_position_id": log.related_position_id or "",
                        "related_fill_id": log.related_fill_id or "",
                        "fill_simulated": False,
                        "simulated": True,
                        "internal_simulated_account": True,
                        "broker_paper_connection": False,
                        "trading_connection": False,
                        "real_money_actions": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    }
                )
            continue
        runtime_id = str(row.get("runtime_id", ""))
        row = scaled_trade_row(row, sizing_by_runtime.get(runtime_id, Decimal("1")))
        request = execution_request_from_trade_row(row, trading_date)
        positions = positions_by_runtime[runtime_id]
        session_state = state_by_runtime[runtime_id]
        risk_positions = [
            PositionSnapshot(symbol=position.symbol, quantity=position.quantity, market_value=position.market_value)
            for position in positions
        ]
        risk_decision = evaluate_order_request(
            request.signal,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            proposed_quantity=request.proposed_quantity,
            positions=risk_positions,
            session_state=session_state,
            config=risk_config,
            market_is_open=True,
        )
        result = adapter.submit(
            request,
            risk_decision=risk_decision,
            session_state=session_state,
            positions=positions,
            seen_signal_ids=seen_by_runtime[runtime_id],
        )
        positions_by_runtime[runtime_id] = result.resulting_positions
        seen_by_runtime[runtime_id] = result.resulting_seen_signal_ids
        state_by_runtime[runtime_id] = result.session_state
        for index, log in enumerate(result.logs):
            events.append(
                {
                    "schema_version": "m14.internal-paper-execution-ledger.v1",
                    "stage": config.stage,
                    "execution_event_id": f"{run_id}:{runtime_id}:{request.signal.signal_id}:{index}:{log.action}",
                    "run_id": run_id,
                    "generated_at": generated_at,
                    "trading_date": trading_date.isoformat(),
                    "strategy_id": row.get("strategy_id", ""),
                    "runtime_id": runtime_id,
                    "signal_id": request.signal.signal_id,
                    "symbol": request.signal.symbol,
                    "timeframe": request.signal.timeframe,
                    "direction": request.signal.direction,
                    "action": log.action,
                    "status": log.status,
                    "risk_outcome": risk_decision.outcome,
                    "reason_codes": ",".join(log.reason_codes),
                    "quantity": fmt_decimal(log.quantity) if log.quantity is not None else "",
                    "entry_price": fmt_decimal(log.entry_price) if log.entry_price is not None else "",
                    "stop_price": fmt_decimal(request.stop_price),
                    "target_price": fmt_decimal(request.target_price),
                    "related_position_id": log.related_position_id or "",
                    "related_fill_id": log.related_fill_id or "",
                    "fill_simulated": bool(result.fill_event and log.action == "simulated_fill" and result.fill_event.simulated),
                    "simulated": True,
                    "internal_simulated_account": True,
                    "broker_paper_connection": False,
                    "trading_connection": False,
                    "real_money_actions": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                }
            )
    return events


def match_close_position(row: dict[str, Any], positions: tuple[PaperPosition, ...]) -> PaperPosition | None:
    symbol = str(row.get("symbol", ""))
    direction = normalize_direction(str(row.get("direction", "")))
    quantity = decimal_or_zero(row.get("quantity"))
    entry = decimal_or_zero(row.get("entry_price"))
    for position in positions:
        if position.symbol != symbol:
            continue
        if position.direction != direction:
            continue
        if position.quantity != quantity:
            continue
        if position.entry_price != entry:
            continue
        return position
    return None


def scaled_trade_row(row: dict[str, Any], multiplier: Decimal) -> dict[str, Any]:
    if multiplier == Decimal("1"):
        return row
    scaled = dict(row)
    quantity = decimal_or_zero(row.get("quantity"))
    scaled["original_quantity"] = str(row.get("quantity", ""))
    scaled["quantity"] = fmt_decimal(quantity * multiplier)
    scaled["position_size_multiplier"] = fmt_decimal(multiplier)
    return scaled


def execution_request_from_trade_row(row: dict[str, Any], trading_date: date) -> ExecutionRequest:
    signal_time = str(row.get("signal_time") or row.get("event_time") or trading_date.isoformat())
    event_time = str(row.get("event_time") or signal_time)
    direction = normalize_direction(str(row.get("direction", "")))
    runtime_id = str(row.get("runtime_id", ""))
    symbol = str(row.get("symbol", ""))
    signal_id = stable_signal_id(runtime_id, symbol, event_time, row.get("entry_price"), row.get("quantity"))
    signal = Signal(
        signal_id=signal_id,
        symbol=symbol,
        market="US",
        timeframe=str(row.get("timeframe", "")),
        direction=direction,
        setup_type=str(row.get("strategy_id", "")),
        pa_context="m14_internal_paper_gate",
        entry_trigger="approved_m13_ledger_open_event",
        stop_rule="ledger_stop_price",
        target_rule="ledger_target_price",
        invalidation="ledger_stop_or_risk_block",
        confidence="paper_trial_gate",
        source_refs=("reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m13_real_daily_strategy_testing/m13_account_operation_ledger.jsonl",),
        explanation="M14 converts approved M13 ledger signals into internal simulated execution requests only.",
        risk_notes=("risk_evaluate_order_request_before_paper_fill",),
    )
    return ExecutionRequest(
        signal=signal,
        requested_at=parse_datetime(event_time),
        session_key=trading_date.isoformat(),
        entry_price=decimal(row.get("entry_price")),
        stop_price=decimal(row.get("stop_price")),
        target_price=decimal(row.get("target_price")),
        proposed_quantity=decimal(row.get("quantity")),
    )


def build_summary(
    *,
    config: M14Config,
    generated_at: str,
    trading_date: date,
    m13_summary: dict[str, Any],
    m12_summary: dict[str, Any],
    data_quality: dict[str, str],
    challenge_rows: list[dict[str, Any]],
    appended_challenge_rows: list[dict[str, Any]],
    appended_correction_rows: list[dict[str, Any]],
    decision_snapshot_rows: list[dict[str, Any]],
    appended_execution_rows: list[dict[str, Any]],
    strategy_aggregates: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    paper_gate: dict[str, Any],
) -> dict[str, Any]:
    required = [row for row in strategy_aggregates.values() if row["required_for_goal"]]
    completed_or_decided = [
        key
        for key, aggregate in strategy_aggregates.items()
        if (
            int(aggregate["completed_trading_days"]) >= config.challenge_trading_days
            or decisions[key]["action_state"] in ACTION_STATES
            or decisions[key]["circuit_breaker_triggered"]
        )
    ]
    required_completed_or_decided = [key for key in completed_or_decided if strategy_aggregates[key]["required_for_goal"]]
    approved = paper_gate["approved_internal_sim_strategy_ids"]
    approved_runtimes = paper_gate.get("approved_internal_sim_runtime_ids", [])
    completed_day_counts = [int(row["completed_trading_days"]) for row in strategy_aggregates.values()]
    required_completed_day_counts = [int(row["completed_trading_days"]) for row in required]
    effective_completed_days = max(completed_day_counts, default=0)
    required_min_effective_completed_days = min(required_completed_day_counts, default=0)
    challenge_progress_label = f"{min(effective_completed_days, config.challenge_trading_days)}/{config.challenge_trading_days}"
    return {
        "schema_version": "m14.strategy-challenge-summary.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "trading_date": trading_date.isoformat(),
        "m13_summary_ref": project_path(config.m13_output_dir / "m13_daily_strategy_test_summary.json"),
        "m12_dashboard_ref": project_path(config.m12_29_output_dir / "m12_32_minute_readonly_dashboard_data.json"),
        "challenge_ledger_ref": project_path(config.output_dir / CHALLENGE_LEDGER),
        "challenge_correction_ledger_ref": project_path(config.output_dir / CHALLENGE_CORRECTION_LEDGER),
        "strategy_decision_ledger_ref": project_path(config.output_dir / DECISION_LEDGER),
        "paper_trial_gate_ref": project_path(config.output_dir / PAPER_GATE),
        "internal_paper_execution_ledger_ref": project_path(config.output_dir / EXECUTION_LEDGER),
        "m13_ready_for_complete_reliable_testing": bool(m13_summary.get("ready_for_complete_reliable_testing", False)),
        "data_quality_state": data_quality["state"],
        "data_freshness_warning": data_quality["warning"],
        "m12_current_day_runtime_ready": bool(m12_summary.get("current_day_runtime_ready", False)),
        "m12_current_day_scan_complete": bool(m12_summary.get("current_day_scan_complete", False)),
        "m12_quote_source": m12_summary.get("quote_source", ""),
        "active_universe_symbol_count": m12_summary.get("active_universe_symbol_count", ""),
        "active_universe_daily_ready_symbols": m12_summary.get("active_universe_daily_ready_symbols", m12_summary.get("first50_daily_ready_symbols", "")),
        "active_universe_current_5m_ready_symbols": m12_summary.get("active_universe_current_5m_ready_symbols", m12_summary.get("first50_current_5m_ready_symbols", "")),
        "first50_daily_ready_symbols": m12_summary.get("first50_daily_ready_symbols", ""),
        "first50_current_5m_ready_symbols": m12_summary.get("first50_current_5m_ready_symbols", ""),
        "challenge_trading_days": config.challenge_trading_days,
        "required_challenge_trading_days": config.challenge_trading_days,
        "effective_challenge_trading_days": effective_completed_days,
        "required_min_effective_challenge_trading_days": required_min_effective_completed_days,
        "challenge_progress_label": challenge_progress_label,
        "strategy_count": len({row["strategy_id"] for row in strategy_aggregates.values()}),
        "runtime_count": len(strategy_aggregates),
        "required_strategy_count": len(required),
        "challenge_day_ledger_row_count": len(challenge_rows),
        "appended_challenge_day_row_count": len(appended_challenge_rows),
        "appended_challenge_correction_row_count": len(appended_correction_rows),
        "decision_snapshot_row_count": len(decision_snapshot_rows),
        "appended_internal_paper_execution_row_count": len(appended_execution_rows),
        "strategies_completed_or_circuit_decided": sorted(completed_or_decided),
        "required_strategies_completed_or_circuit_decided": sorted(required_completed_or_decided),
        "approved_internal_sim_strategy_ids": approved,
        "approved_internal_sim_runtime_ids": approved_runtimes,
        "risk_limited_runtime_ids": paper_gate.get("risk_limited_runtime_ids", []),
        "auxiliary_module_runtime_ids": paper_gate.get("auxiliary_module_runtime_ids", []),
        "auxiliary_module_strategy_ids": paper_gate.get("auxiliary_module_strategy_ids", []),
        "paper_candidate_runtime_ids": paper_gate.get("paper_candidate_runtime_ids", []),
        "paper_trial_gate_approved_count": len(approved),
        "auxiliary_module_count": len(paper_gate.get("auxiliary_module_runtime_ids", [])),
        "paper_simulated_only": True,
        "internal_simulated_account": True,
        "broker_paper_connection": False,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "plain_language_result": (
            f"M14 effective challenge progress is {challenge_progress_label}. "
            f"It has {len(challenge_rows)} append-only challenge rows including audit-only degraded days. "
            f"{len(approved_runtimes)} runtimes can advance in internal simulation with per-runtime sizing. "
            f"Data quality: {data_quality['warning'] or data_quality['state']}."
        ),
    }


def build_goal_status(summary: dict[str, Any]) -> dict[str, Any]:
    complete = (
        int(summary["required_strategy_count"]) > 0
        and len(summary["required_strategies_completed_or_circuit_decided"]) == int(summary["required_strategy_count"])
    )
    return {
        "schema_version": "m14.goal-status.v1",
        "goal_name": "Build a reliable strategy challenge and internal paper-trading gate",
        "generated_at": summary["generated_at"],
        "trading_date": summary["trading_date"],
        "goal_complete": complete,
        "continue_without_stopping": not complete,
        "data_quality_state": summary["data_quality_state"],
        "challenge_progress_label": summary["challenge_progress_label"],
        "effective_challenge_trading_days": summary["effective_challenge_trading_days"],
        "required_challenge_trading_days": summary["required_challenge_trading_days"],
        "approved_internal_sim_strategy_ids": summary["approved_internal_sim_strategy_ids"],
        "approved_internal_sim_runtime_ids": summary.get("approved_internal_sim_runtime_ids", []),
        "risk_limited_runtime_ids": summary.get("risk_limited_runtime_ids", []),
        "auxiliary_module_runtime_ids": summary.get("auxiliary_module_runtime_ids", []),
        "auxiliary_module_strategy_ids": summary.get("auxiliary_module_strategy_ids", []),
        "paper_candidate_runtime_ids": summary.get("paper_candidate_runtime_ids", []),
        "paper_trial_gate_approved_count": summary["paper_trial_gate_approved_count"],
        "plain_language_result": summary["plain_language_result"],
        "next_action": (
            "Advance viable runtimes with sizing controls; repair or pause blocked runtimes with explicit fixes."
            if not complete
            else "Review completed/circuit decisions, keep broker paper and real-money execution disabled."
        ),
    }


def build_dashboard_html(
    summary: dict[str, Any],
    aggregates: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    paper_gate: dict[str, Any],
) -> str:
    gate_by_runtime = {runtime_key(row): row for row in paper_gate["rows"]}
    warning = summary.get("data_freshness_warning") or ""
    warning_section = (
        f"<section class=\"warning\"><strong>看板数据未刷新 / fallback quotes / no-fetch</strong><p>{html.escape(warning)}</p></section>"
        if warning else ""
    )
    rows = "\n".join(
        strategy_dashboard_row(aggregates[key], decisions[key], gate_by_runtime[key])
        for key in sorted(aggregates)
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>M14 策略挑战与模拟准入</title>
  <style>
    body {{ margin:0; font-family:Arial,"Noto Sans SC",sans-serif; background:#f5f7fb; color:#1f2937; letter-spacing:0; }}
    header {{ padding:18px 22px; background:#fff; border-bottom:1px solid #d8dee9; }}
    h1 {{ margin:0 0 8px; font-size:24px; }}
    main {{ padding:18px 22px; display:grid; gap:16px; }}
    .goal,.warning,.panel {{ background:#fff; border:1px solid #d8dee9; border-radius:8px; padding:14px 16px; }}
    .goal {{ border-left:6px solid #155eef; }}
    .warning {{ border-left:6px solid #b42318; background:#fff7f5; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:10px; }}
    .metric {{ background:#fff; border:1px solid #d8dee9; border-radius:8px; padding:12px; }}
    .metric span {{ display:block; color:#667085; font-size:12px; }}
    .metric strong {{ display:block; margin-top:8px; font-size:22px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; background:#fff; }}
    th,td {{ padding:9px 10px; border-bottom:1px solid #e5e7eb; text-align:left; vertical-align:top; }}
    th {{ background:#eef2f7; }}
    .good {{ color:#18794e; font-weight:700; }}
    .bad {{ color:#b42318; font-weight:700; }}
    .muted {{ color:#667085; }}
    @media (max-width:920px) {{ .metrics {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .panel {{ overflow:auto; }} }}
  </style>
</head>
<body>
  <header>
    <h1>M14：稳定策略测试、调参决策与内部模拟准入</h1>
    <div>交易日：{html.escape(summary['trading_date'])} ｜ 生成时间：{html.escape(summary['generated_at'])} ｜ 边界：只读行情 + internal simulated account，不接真实账户。</div>
  </header>
  <main>
    <section class="goal"><strong>Goal</strong><p>Build a reliable strategy challenge and internal paper-trading gate. 默认 10 个纽约交易日，亏损策略冻结并新建变体 A/B，不静默覆盖旧结果。</p></section>
    {warning_section}
    <div class="metrics">
      <section class="metric"><span>策略数</span><strong>{html.escape(str(summary['strategy_count']))}</strong></section>
      <section class="metric"><span>有效挑战进度</span><strong>{html.escape(str(summary['challenge_progress_label']))}</strong></section>
      <section class="metric"><span>内部模拟准入</span><strong>{html.escape(str(summary['paper_trial_gate_approved_count']))}</strong></section>
      <section class="metric"><span>数据状态</span><strong>{html.escape(str(summary['data_quality_state']))}</strong></section>
    </div>
    <section class="panel">
      <h2>策略挑战榜</h2>
      <table>
        <thead><tr><th>策略</th><th>进度</th><th>PnL / R</th><th>回撤</th><th>信号/开/平</th><th>零信号天</th><th>阻塞</th><th>决策</th><th>准入</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def strategy_dashboard_row(aggregate: dict[str, Any], decision: dict[str, Any], gate: dict[str, Any]) -> str:
    pnl = decimal_or_zero(aggregate["realized_pnl"])
    cls = "good" if pnl > ZERO else "bad" if pnl < ZERO else "muted"
    blocker = "; ".join(aggregate["blocker_reasons"][:3]) or "无"
    decision_label = str(decision.get("display_action") or display_action_for(str(decision["action_state"]), str(aggregate.get("strategy_id", "")), str(aggregate.get("module_role", ""))))
    gate_reason = str(gate.get("gate_reason", ""))
    return (
        "<tr>"
        f"<td>{html.escape(aggregate['runtime_id'])}<br><small>{html.escape(aggregate['strategy_id'])} / {html.escape(aggregate.get('timeframe', ''))}</small></td>"
        f"<td>{html.escape(aggregate['progress_label'])}</td>"
        f"<td class=\"{cls}\">{html.escape(aggregate['realized_pnl'])} / {html.escape(aggregate['net_pnl_r'])}R</td>"
        f"<td>{html.escape(aggregate['max_drawdown_percent'])}%</td>"
        f"<td>{html.escape(str(aggregate['total_signal_count']))} / {html.escape(str(aggregate['open_count']))} / {html.escape(str(aggregate['close_count']))}</td>"
        f"<td>{html.escape(str(aggregate['zero_signal_days']))}</td>"
        f"<td>{html.escape(blocker)}</td>"
        f"<td>{html.escape(decision_label)}<br><small>{html.escape(decision['decision_reason'])}</small></td>"
        f"<td>{html.escape(gate['paper_trial_gate'])}<br><small>size {html.escape(str(gate.get('position_size_multiplier', '1')))} ｜ {html.escape(gate_reason)}</small></td>"
        "</tr>"
    )


def build_goal_prompt_md() -> str:
    return """# M14 Codex Goal

Goal: Build a reliable strategy challenge and internal paper-trading gate.

Hard constraints:
- No real-money execution, no live broker orders, no fabricated trades or profits.
- Run M12.37/M12.29 + M13 every New York trading day.
- Keep every strategy in append-only daily ledger history.
- Use 10 NY trading days as the default challenge window.
- Evaluate and advance each runtime separately; do not merge 1d and 5m gate decisions by parent strategy.
- Use sizing and repair actions for high-drawdown or low-win-rate profitable runtimes instead of blanket rejection.
- Internal simulated account is the default; broker paper/sim account requires separate approval.
- Losing or zero-signal runtimes must get a concrete repair or pause action, not a generic observation state.
"""


def resolve_trading_date(config: M14Config, generated_at: str, trading_date: str | date | None) -> date:
    if isinstance(trading_date, date):
        return trading_date
    if isinstance(trading_date, str) and trading_date:
        return date.fromisoformat(trading_date)
    m13_summary_path = config.m13_output_dir / "m13_daily_strategy_test_summary.json"
    if m13_summary_path.exists():
        summary = read_json(m13_summary_path)
        if summary.get("trading_date"):
            return date.fromisoformat(str(summary["trading_date"]))
    dashboard_data = config.m12_29_output_dir / "m12_32_minute_readonly_dashboard_data.json"
    if dashboard_data.exists():
        payload = read_json(dashboard_data)
        scan_date = payload.get("summary", {}).get("scan_date") or payload.get("scan_date")
        if scan_date:
            return date.fromisoformat(str(scan_date))
    return datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date()


def load_m12_summary(m12_output_dir: Path) -> dict[str, Any]:
    dashboard_path = m12_output_dir / "m12_32_minute_readonly_dashboard_data.json"
    if dashboard_path.exists():
        return dict(read_json(dashboard_path).get("summary", {}))
    summary_path = m12_output_dir / "m12_29_current_day_scan_summary.json"
    if summary_path.exists():
        return read_json(summary_path)
    return {}


def build_data_quality_state(summary: dict[str, Any]) -> dict[str, str]:
    quote_source = str(summary.get("quote_source", ""))
    runtime_ready = bool(summary.get("current_day_runtime_ready", False))
    scan_complete = bool(summary.get("current_day_scan_complete", False))
    fallback_or_no_fetch = any(token in quote_source.lower() for token in ("fallback", "no-fetch", "no_fetch", "no-refresh", "no_refresh"))
    if runtime_ready and not fallback_or_no_fetch:
        return {"state": "fully_ready" if scan_complete else "runtime_ready_partial_scan", "warning": ""}
    note = str(summary.get("runtime_readiness_note", "") or "当前看板不是完整当日刷新。")
    active_count = summary.get("active_universe_symbol_count", 50)
    warning = (
        f"看板数据未刷新 / fallback quotes / no-fetch: quote_source={quote_source or 'unknown'}, "
        f"current_day_runtime_ready={str(runtime_ready).lower()}, "
        f"current_day_scan_complete={str(scan_complete).lower()}, "
        f"active_universe_daily_ready={summary.get('active_universe_daily_ready_symbols', summary.get('first50_daily_ready_symbols', 'unknown'))}/{active_count}, "
        f"active_universe_5m_ready={summary.get('active_universe_current_5m_ready_symbols', summary.get('first50_current_5m_ready_symbols', 'unknown'))}/{active_count}. {note}"
    )
    return {"state": "degraded_no_fetch_or_fallback_quotes", "warning": warning}


def paper_candidates_allowed(summary: dict[str, Any], data_quality: dict[str, str]) -> bool:
    text = " ".join(
        [
            str(summary.get("quote_source", "")),
            str(summary.get("data_freshness_warning", "")),
            str(data_quality.get("state", "")),
            str(data_quality.get("warning", "")),
        ]
    ).lower()
    return not any(token in text for token in ("fallback", "no-fetch", "no_fetch", "no-refresh", "no_refresh"))


def build_blocker_reason(test_states: list[str], data_quality: dict[str, str]) -> str:
    blockers = [state for state in test_states if state in BLOCKER_STATES]
    if blockers:
        return ",".join(blockers)
    if data_quality["state"] != "fully_ready":
        return data_quality["state"]
    return ""


def append_unique_jsonl(path: Path, rows: list[dict[str, Any]], *, key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    existing = read_jsonl(path)
    seen = {tuple(str(row.get(field, "")) for field in key_fields) for row in existing}
    append_rows: list[dict[str, Any]] = []
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        append_rows.append(row)
    if append_rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in append_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    elif not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return append_rows


def write_jsonl_snapshot(path: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return rows


def append_challenge_corrections(
    path: Path,
    new_rows: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    *,
    generated_at: str,
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    base_keys = {row_key(row, key_fields) for row in raw_rows}
    current_by_key = {row_key(row, key_fields): row for row in effective_challenge_rows(raw_rows, read_jsonl(path), key_fields=key_fields)}
    append_rows: list[dict[str, Any]] = []
    seen_new_keys: set[tuple[str, ...]] = set()
    for row in new_rows:
        key = row_key(row, key_fields)
        if key not in base_keys or key in seen_new_keys:
            continue
        seen_new_keys.add(key)
        current = current_by_key.get(key)
        if current is not None and challenge_row_fingerprint(current) == challenge_row_fingerprint(row):
            continue
        correction = dict(row)
        correction.update(
            {
                "correction_schema_version": "m14.challenge-day-correction.v1",
                "correction_generated_at": generated_at,
                "correction_reason": "source_daily_ledger_changed_for_existing_challenge_key",
            }
        )
        append_rows.append(correction)
    if append_rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in append_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    elif not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return append_rows


def effective_challenge_rows(
    raw_rows: list[dict[str, Any]],
    correction_rows: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    effective = [dict(row) for row in raw_rows]
    index_by_key = {row_key(row, key_fields): index for index, row in enumerate(effective)}
    for correction in correction_rows:
        key = row_key(correction, key_fields)
        corrected = {
            item_key: item_value
            for item_key, item_value in correction.items()
            if not item_key.startswith("correction_")
        }
        if key in index_by_key:
            effective[index_by_key[key]] = corrected
        else:
            index_by_key[key] = len(effective)
            effective.append(corrected)
    return effective


def row_key(row: dict[str, Any], key_fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(row.get(field, "")) for field in key_fields)


def runtime_key(row: dict[str, Any]) -> str:
    return str(row.get("runtime_id") or row.get("strategy_id") or "")


def challenge_row_fingerprint(row: dict[str, Any]) -> str:
    ignored = {"generated_at", "run_id"}
    payload = {
        key: value
        for key, value in row.items()
        if key not in ignored and not key.startswith("correction_")
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def filter_rows_for_trading_date(rows: list[dict[str, Any]], trading_date: date) -> list[dict[str, Any]]:
    return [row for row in rows if iso_to_ny_trading_date(str(row.get("event_time", ""))) == trading_date]


def iso_to_ny_trading_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.fromisoformat(value[:10] + "T00:00:00+00:00")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stable_signal_id(runtime_id: str, symbol: str, event_time: str, entry_price: Any, quantity: Any) -> str:
    safe = "-".join(str(part).replace(":", "").replace("/", "-").replace(" ", "T") for part in [runtime_id, symbol, event_time, entry_price, quantity])
    return f"m14-{safe}"


def normalize_direction(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"long", "buy", "bull", "看涨", "多", "做多"}:
        return "long"
    if normalized in {"short", "sell", "bear", "看跌", "空", "做空"}:
        return "short"
    return normalized


def latest_non_empty(values: list[Any]) -> str:
    for value in reversed(values):
        text = str(value or "")
        if text:
            return text
    return ""


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def decimal(value: Any) -> Decimal:
    parsed = decimal_or_none(value)
    if parsed is None:
        raise ValueError(f"Expected decimal value, got {value!r}")
    return parsed


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def decimal_or_zero(value: Any) -> Decimal:
    return decimal_or_none(value) or ZERO


def safe_div(numerator: Decimal, denominator: Decimal) -> Decimal:
    return numerator / denominator if denominator != ZERO else ZERO


def money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def fmt_decimal(value: Any) -> str:
    if value is None:
        return ""
    parsed = decimal_or_none(value) if not isinstance(value, Decimal) else value
    if parsed is None:
        return str(value)
    normalized = parsed.normalize()
    text = format(normalized, "f")
    return "0" if text == "-0" else text
