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
DECISION_LEDGER = "m14_strategy_decision_ledger.jsonl"
PAPER_GATE = "m14_paper_trial_gate.json"
EXECUTION_LEDGER = "m14_internal_paper_execution_ledger.jsonl"
SUMMARY_JSON = "m14_strategy_challenge_summary.json"
DASHBOARD_HTML = "m14_strategy_challenge_dashboard.html"
GOAL_STATUS_JSON = "m14_goal_status.json"
GOAL_PROMPT_MD = "m14_goal_prompt.md"
BLOCKER_STATES = {"not_connected", "detector_missing", "missing_data"}
DECISIONS = {"promote", "modify", "reject", "continue_testing"}
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
        key_fields=("strategy_id", "runtime_id", "trading_date"),
    )
    challenge_rows = read_jsonl(challenge_path)
    strategy_aggregates = build_strategy_aggregates(config, challenge_rows)
    decision_rows = build_strategy_decision_rows(
        config=config,
        generated_at=generated_at,
        trading_date=resolved_trading_date,
        aggregates=strategy_aggregates,
    )
    decision_path = config.output_dir / DECISION_LEDGER
    appended_decision_rows = append_unique_jsonl(
        decision_path,
        decision_rows,
        key_fields=("strategy_id", "trading_date", "decision", "decision_reason"),
    )
    latest_decisions = {row["strategy_id"]: row for row in decision_rows}
    paper_gate = build_paper_trial_gate(config, generated_at, latest_decisions, strategy_aggregates)
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
        appended_decision_rows=appended_decision_rows,
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
        "new_challenge_rows": new_challenge_rows,
        "appended_challenge_rows": appended_challenge_rows,
        "decision_rows": decision_rows,
        "appended_decision_rows": appended_decision_rows,
        "paper_gate": paper_gate,
        "execution_rows": execution_rows,
        "appended_execution_rows": appended_execution_rows,
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
        grouped[str(row.get("strategy_id", ""))].append(row)

    aggregates: dict[str, dict[str, Any]] = {}
    for strategy_id, rows in grouped.items():
        dates = sorted({str(row.get("trading_date", "")) for row in rows if row.get("trading_date")})
        by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_date[str(row.get("trading_date", ""))].append(row)
        signal_days = sum(1 for day_rows in by_date.values() if sum(int_or_zero(row.get("signal_count")) for row in day_rows) > 0)
        zero_signal_days = sum(
            1
            for day_rows in by_date.values()
            if sum(int_or_zero(row.get("signal_count")) for row in day_rows) == 0
            and any(row.get("test_state") == "zero_signal" for row in day_rows)
        )
        data_mismatch_days = sum(
            1 for day_rows in by_date.values() if any(row.get("data_quality_state") != "fully_ready" for row in day_rows)
        )
        realized_pnl = sum((decimal_or_zero(row.get("realized_pnl")) for row in rows), ZERO)
        total_signals = sum(int_or_zero(row.get("signal_count")) for row in rows)
        risk_blocks = sum(int_or_zero(row.get("risk_blocked_count")) for row in rows)
        max_drawdown = max((decimal_or_zero(row.get("max_drawdown_percent")) for row in rows), default=ZERO)
        latest = sorted(rows, key=lambda row: (str(row.get("trading_date", "")), str(row.get("generated_at", ""))))[-1]
        aggregates[strategy_id] = {
            "strategy_id": strategy_id,
            "display_name": latest.get("display_name", ""),
            "module_role": latest.get("module_role", ""),
            "required_for_goal": bool(latest.get("required_for_goal", False)),
            "runtime_ids": sorted({str(row.get("runtime_id", "")) for row in rows if row.get("runtime_id")}),
            "variant_ids": sorted({str(row.get("variant_id", "")) for row in rows if row.get("variant_id")}),
            "completed_trading_days": len(dates),
            "required_trading_days": config.challenge_trading_days,
            "progress_label": f"{min(len(dates), config.challenge_trading_days)}/{config.challenge_trading_days}",
            "first_trading_date": dates[0] if dates else "",
            "latest_trading_date": dates[-1] if dates else "",
            "signal_days": signal_days,
            "zero_signal_days": zero_signal_days,
            "total_signal_count": total_signals,
            "open_count": sum(int_or_zero(row.get("open_count")) for row in rows),
            "close_count": sum(int_or_zero(row.get("close_count")) for row in rows),
            "risk_blocked_count": risk_blocks,
            "risk_block_ratio": fmt_decimal(safe_div(Decimal(risk_blocks), Decimal(max(total_signals, 1)))),
            "realized_pnl": money(realized_pnl),
            "net_pnl_r": fmt_decimal(safe_div(realized_pnl, config.internal_paper.max_risk_per_order)),
            "max_drawdown_percent": fmt_decimal(max_drawdown),
            "data_mismatch_days": data_mismatch_days,
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
    for strategy_id in sorted(aggregates):
        aggregate = aggregates[strategy_id]
        decision, reason, circuit, frozen, modify_candidate, variant = decide_strategy(config, aggregate, trading_date)
        if decision not in DECISIONS:
            raise ValueError(f"Unsupported M14 decision: {decision}")
        rows.append(
            {
                "schema_version": "m14.strategy-decision-ledger.v1",
                "stage": config.stage,
                "generated_at": generated_at,
                "trading_date": trading_date.isoformat(),
                "strategy_id": strategy_id,
                "display_name": aggregate["display_name"],
                "module_role": aggregate["module_role"],
                "required_for_goal": aggregate["required_for_goal"],
                "decision": decision,
                "decision_reason": reason,
                "circuit_breaker_triggered": circuit,
                "frozen": frozen,
                "modify_candidate": modify_candidate,
                "next_variant_id": variant,
                "completed_trading_days": aggregate["completed_trading_days"],
                "required_trading_days": config.challenge_trading_days,
                "signal_days": aggregate["signal_days"],
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
) -> tuple[str, str, bool, bool, bool, str]:
    role = aggregate["module_role"]
    completed_days = int(aggregate["completed_trading_days"])
    signal_days = int(aggregate["signal_days"])
    net_pnl_r = decimal_or_zero(aggregate["net_pnl_r"])
    max_drawdown = decimal_or_zero(aggregate["max_drawdown_percent"])
    risk_block_ratio = decimal_or_zero(aggregate["risk_block_ratio"])
    data_mismatch_days = int(aggregate["data_mismatch_days"])

    if role == "external_research":
        return ("continue_testing", "external_shadow_research_only", False, True, False, "")
    if role == "research_only":
        return ("continue_testing", "research_only_blocker", False, True, False, "")
    if role == "plugin_filter":
        return ("continue_testing", "plugin_filter_ab_coverage", False, False, False, "")
    if data_mismatch_days >= config.circuit_breaker.data_mismatch_days_threshold:
        return ("continue_testing", "data_quality_circuit_breaker", True, True, False, "")

    if signal_days >= config.circuit_breaker.min_signal_days:
        variant = f"{aggregate['strategy_id']}-m14-modify-{trading_date.strftime('%Y%m%d')}"
        if net_pnl_r < config.circuit_breaker.net_pnl_r_threshold:
            return ("modify", "net_pnl_below_minus_2r", True, True, True, variant)
        if max_drawdown > config.circuit_breaker.max_drawdown_percent_threshold:
            return ("modify", "max_drawdown_above_3_percent", True, True, True, variant)
        if risk_block_ratio > config.circuit_breaker.risk_block_ratio_threshold:
            return ("modify", "risk_blocks_dominate_signals", True, True, True, variant)

    if completed_days >= config.challenge_trading_days:
        if int(aggregate["total_signal_count"]) == 0:
            return ("reject", "ten_days_no_viable_signal", False, True, False, "")
        if net_pnl_r > ZERO and max_drawdown <= config.circuit_breaker.max_drawdown_percent_threshold and data_mismatch_days == 0:
            return ("promote", "ten_day_positive_expectancy_internal_sim_candidate", False, False, False, "")
        if net_pnl_r <= ZERO:
            variant = f"{aggregate['strategy_id']}-m14-modify-{trading_date.strftime('%Y%m%d')}"
            return ("modify", "ten_day_losing_modify_candidate", False, True, True, variant)
        return ("continue_testing", "ten_day_result_needs_manual_review", False, True, False, "")

    return ("continue_testing", "challenge_incomplete", False, False, False, "")


def build_paper_trial_gate(
    config: M14Config,
    generated_at: str,
    decisions: dict[str, dict[str, Any]],
    aggregates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for strategy_id in sorted(aggregates):
        aggregate = aggregates[strategy_id]
        decision = decisions[strategy_id]
        if decision["decision"] == "promote" and int(decision["completed_trading_days"]) >= config.challenge_trading_days and int(decision["data_mismatch_days"]) == 0:
            gate_status = "approved_internal_sim_only"
            reason = "10 trading-day challenge passed; internal simulator only."
        elif decision["decision"] == "modify":
            gate_status = "not_approved_modify_candidate"
            reason = "Baseline is frozen; create a variant and A/B test before any promotion."
        elif decision["decision"] == "reject":
            gate_status = "not_approved_rejected"
            reason = "Strategy is rejected for the current challenge window."
        elif int(decision["data_mismatch_days"]) > 0:
            gate_status = "not_approved_data_quality"
            reason = "Challenge includes no-fetch/fallback or incomplete current-day data."
        else:
            gate_status = "not_approved_challenge_incomplete"
            reason = "Strategy has not completed the required 10 NY trading-day challenge."
        rows.append(
            {
                "strategy_id": strategy_id,
                "display_name": aggregate["display_name"],
                "paper_trial_gate": gate_status,
                "gate_reason": reason,
                "decision": decision["decision"],
                "decision_reason": decision["decision_reason"],
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
        "approved_internal_sim_strategy_ids": [row["strategy_id"] for row in rows if row["paper_trial_gate"] == "approved_internal_sim_only"],
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
    approved = {row["strategy_id"] for row in paper_gate["rows"] if row["paper_trial_gate"] == "approved_internal_sim_only"}
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
    open_rows = [row for row in m12_trade_rows if row.get("event_type") == "open" and row.get("strategy_id") in approved]
    for row in sorted(open_rows, key=lambda item: (str(item.get("event_time", "")), str(item.get("runtime_id", "")), str(item.get("symbol", "")))):
        request = execution_request_from_trade_row(row, trading_date)
        runtime_id = str(row.get("runtime_id", ""))
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
    appended_decision_rows: list[dict[str, Any]],
    appended_execution_rows: list[dict[str, Any]],
    strategy_aggregates: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    paper_gate: dict[str, Any],
) -> dict[str, Any]:
    required = [row for row in strategy_aggregates.values() if row["required_for_goal"]]
    completed_or_decided = [
        strategy_id
        for strategy_id, aggregate in strategy_aggregates.items()
        if (
            int(aggregate["completed_trading_days"]) >= config.challenge_trading_days
            or decisions[strategy_id]["decision"] in {"modify", "reject"}
            or decisions[strategy_id]["circuit_breaker_triggered"]
        )
    ]
    required_completed_or_decided = [
        strategy_id
        for strategy_id in completed_or_decided
        if strategy_aggregates[strategy_id]["required_for_goal"]
    ]
    approved = paper_gate["approved_internal_sim_strategy_ids"]
    return {
        "schema_version": "m14.strategy-challenge-summary.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "trading_date": trading_date.isoformat(),
        "m13_summary_ref": project_path(config.m13_output_dir / "m13_daily_strategy_test_summary.json"),
        "m12_dashboard_ref": project_path(config.m12_29_output_dir / "m12_32_minute_readonly_dashboard_data.json"),
        "challenge_ledger_ref": project_path(config.output_dir / CHALLENGE_LEDGER),
        "strategy_decision_ledger_ref": project_path(config.output_dir / DECISION_LEDGER),
        "paper_trial_gate_ref": project_path(config.output_dir / PAPER_GATE),
        "internal_paper_execution_ledger_ref": project_path(config.output_dir / EXECUTION_LEDGER),
        "m13_ready_for_complete_reliable_testing": bool(m13_summary.get("ready_for_complete_reliable_testing", False)),
        "data_quality_state": data_quality["state"],
        "data_freshness_warning": data_quality["warning"],
        "m12_current_day_runtime_ready": bool(m12_summary.get("current_day_runtime_ready", False)),
        "m12_current_day_scan_complete": bool(m12_summary.get("current_day_scan_complete", False)),
        "m12_quote_source": m12_summary.get("quote_source", ""),
        "first50_daily_ready_symbols": m12_summary.get("first50_daily_ready_symbols", ""),
        "first50_current_5m_ready_symbols": m12_summary.get("first50_current_5m_ready_symbols", ""),
        "challenge_trading_days": config.challenge_trading_days,
        "strategy_count": len(strategy_aggregates),
        "required_strategy_count": len(required),
        "challenge_day_ledger_row_count": len(challenge_rows),
        "appended_challenge_day_row_count": len(appended_challenge_rows),
        "appended_decision_row_count": len(appended_decision_rows),
        "appended_internal_paper_execution_row_count": len(appended_execution_rows),
        "strategies_completed_or_circuit_decided": sorted(completed_or_decided),
        "required_strategies_completed_or_circuit_decided": sorted(required_completed_or_decided),
        "approved_internal_sim_strategy_ids": approved,
        "paper_trial_gate_approved_count": len(approved),
        "paper_simulated_only": True,
        "internal_simulated_account": True,
        "broker_paper_connection": False,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "plain_language_result": (
            f"M14 has {len(challenge_rows)} append-only challenge rows. "
            f"{len(approved)} strategies are approved for internal simulated trading only. "
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
        "approved_internal_sim_strategy_ids": summary["approved_internal_sim_strategy_ids"],
        "next_action": (
            "Continue the 10 NY trading-day challenge; do not modify baseline strategies unless a circuit breaker triggers."
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
    gate_by_strategy = {row["strategy_id"]: row for row in paper_gate["rows"]}
    warning = summary.get("data_freshness_warning") or ""
    warning_section = (
        f"<section class=\"warning\"><strong>看板数据未刷新 / fallback quotes / no-fetch</strong><p>{html.escape(warning)}</p></section>"
        if warning else ""
    )
    rows = "\n".join(
        strategy_dashboard_row(aggregates[strategy_id], decisions[strategy_id], gate_by_strategy[strategy_id])
        for strategy_id in sorted(aggregates)
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
      <section class="metric"><span>挑战账本行</span><strong>{html.escape(str(summary['challenge_day_ledger_row_count']))}</strong></section>
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
    return (
        "<tr>"
        f"<td>{html.escape(aggregate['strategy_id'])}<br><small>{html.escape(aggregate['display_name'])}</small></td>"
        f"<td>{html.escape(aggregate['progress_label'])}</td>"
        f"<td class=\"{cls}\">{html.escape(aggregate['realized_pnl'])} / {html.escape(aggregate['net_pnl_r'])}R</td>"
        f"<td>{html.escape(aggregate['max_drawdown_percent'])}%</td>"
        f"<td>{html.escape(str(aggregate['total_signal_count']))} / {html.escape(str(aggregate['open_count']))} / {html.escape(str(aggregate['close_count']))}</td>"
        f"<td>{html.escape(str(aggregate['zero_signal_days']))}</td>"
        f"<td>{html.escape(blocker)}</td>"
        f"<td>{html.escape(decision['decision'])}<br><small>{html.escape(decision['decision_reason'])}</small></td>"
        f"<td>{html.escape(gate['paper_trial_gate'])}<br><small>{html.escape(gate['gate_reason'])}</small></td>"
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
- Allow early modification/rejection only on circuit breaker conditions.
- Internal simulated account is the default; broker paper/sim account requires separate approval.
- Losing strategies must be frozen, diagnosed, and A/B tested as new variants, not silently overwritten.
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
    warning = (
        f"看板数据未刷新 / fallback quotes / no-fetch: quote_source={quote_source or 'unknown'}, "
        f"current_day_runtime_ready={str(runtime_ready).lower()}, "
        f"current_day_scan_complete={str(scan_complete).lower()}, "
        f"first50_daily_ready={summary.get('first50_daily_ready_symbols', 'unknown')}/50, "
        f"first50_5m_ready={summary.get('first50_current_5m_ready_symbols', 'unknown')}/50. {note}"
    )
    return {"state": "degraded_no_fetch_or_fallback_quotes", "warning": warning}


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
