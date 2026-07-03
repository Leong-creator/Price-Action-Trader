#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time as wall_time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_realtime_execution_lib import (
    DEFAULT_DAILY_DIR,
    parse_utc_datetime,
    to_iso,
)
from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config
from scripts.m15_longbridge_realtime_execution_lib import run_realtime_execution
from scripts.m15_longbridge_realtime_account_state_lib import PNL_RECONCILIATION_JSON as ACCOUNT_PNL_RECONCILIATION_JSON
from scripts.m15_longbridge_realtime_account_state_lib import PNL_RECONCILIATION_MD as ACCOUNT_PNL_RECONCILIATION_MD
from scripts.m15_longbridge_realtime_account_state_lib import SUMMARY_JSON as ACCOUNT_STATE_SUMMARY_JSON
from scripts.m15_longbridge_realtime_account_state_lib import load_config as load_account_state_config
from scripts.m15_longbridge_realtime_account_state_lib import run_realtime_account_state
from scripts.m15_longbridge_realtime_market_event_ingestor_lib import load_config as load_ingestor_config
from scripts.m15_longbridge_realtime_market_event_ingestor_lib import run_realtime_market_event_ingestor
from scripts.m15_longbridge_realtime_position_manager_lib import load_config as load_position_manager_config
from scripts.m15_longbridge_realtime_position_manager_lib import run_realtime_position_manager
from scripts.m15_longbridge_realtime_signal_router_lib import load_config as load_router_config
from scripts.m15_longbridge_realtime_signal_router_lib import run_realtime_signal_router
from scripts.m15_longbridge_realtime_stale_order_cleanup_lib import load_config as load_stale_order_cleanup_config
from scripts.m15_longbridge_realtime_stale_order_cleanup_lib import run_stale_order_cleanup


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_session_supervisor.json"
DEFAULT_INGESTOR_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_market_event_ingestor.json"
DEFAULT_ROUTER_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_signal_router.json"
DEFAULT_ACCOUNT_STATE_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_account_state.json"
DEFAULT_STALE_ORDER_CLEANUP_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_stale_order_cleanup.json"
DEFAULT_POSITION_MANAGER_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_position_manager.json"
DEFAULT_EXECUTION_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_execution.json"
SUMMARY_JSON = "m15_longbridge_realtime_session_supervisor.json"
LEDGER_JSONL = "m15_longbridge_realtime_session_supervisor_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_session_supervisor.md"
PID_FILE = "m15_longbridge_realtime_session_supervisor.pid"
LOG_FILE = "m15_longbridge_realtime_session_supervisor.log"
MAX_SUPERVISOR_LEDGER_BYTES = 20 * 1024 * 1024
MAX_SUPERVISOR_LEDGER_LINES = 5000
MAX_SUPERVISOR_LOG_BYTES = 20 * 1024 * 1024

StepRunner = Callable[[str | None], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RealtimeSessionSupervisorConfig:
    stage: str
    title: str
    output_dir: Path
    ingestor_config_path: Path
    router_config_path: Path
    account_state_config_path: Path
    stale_order_cleanup_config_path: Path
    position_manager_config_path: Path
    execution_config_path: Path
    check_interval_seconds: int
    idle_check_interval_seconds: int
    market_timezone: str
    regular_session_start_time: str
    regular_session_end_time: str
    active_market_phases: tuple[str, ...]
    market_holidays: frozenset[date]
    max_consecutive_failures: int
    run_ingestor: bool
    run_router: bool
    run_account_state: bool
    run_stale_order_cleanup: bool
    run_position_manager: bool
    run_execution: bool
    hard_boundaries: dict[str, bool]

    def __post_init__(self) -> None:
        validate_config(self)


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RealtimeSessionSupervisorConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    session = payload.get("realtime_session_supervisor", {})
    return RealtimeSessionSupervisorConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_session_supervisor")),
        title=str(payload.get("title", "长桥实时链路守护器")),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        ingestor_config_path=resolve_repo_path(inputs.get("ingestor_config", DEFAULT_INGESTOR_CONFIG_PATH)),
        router_config_path=resolve_repo_path(inputs.get("router_config", DEFAULT_ROUTER_CONFIG_PATH)),
        account_state_config_path=resolve_repo_path(inputs.get("account_state_config", DEFAULT_ACCOUNT_STATE_CONFIG_PATH)),
        stale_order_cleanup_config_path=resolve_repo_path(
            inputs.get("stale_order_cleanup_config", DEFAULT_STALE_ORDER_CLEANUP_CONFIG_PATH)
        ),
        position_manager_config_path=resolve_repo_path(inputs.get("position_manager_config", DEFAULT_POSITION_MANAGER_CONFIG_PATH)),
        execution_config_path=resolve_repo_path(inputs.get("execution_config", DEFAULT_EXECUTION_CONFIG_PATH)),
        check_interval_seconds=int(session.get("check_interval_seconds", 5)),
        idle_check_interval_seconds=int(session.get("idle_check_interval_seconds", 60)),
        market_timezone=str(session.get("market_timezone", "America/New_York")),
        regular_session_start_time=str(session.get("regular_session_start_time", "09:30")),
        regular_session_end_time=str(session.get("regular_session_end_time", "16:00")),
        active_market_phases=tuple(str(item) for item in session.get("active_market_phases", ["regular_session"])),
        market_holidays=parse_market_holidays(session.get("market_holidays", [])),
        max_consecutive_failures=int(session.get("max_consecutive_failures", 3)),
        run_ingestor=bool(session.get("run_ingestor", True)),
        run_router=bool(session.get("run_router", True)),
        run_account_state=bool(session.get("run_account_state", True)),
        run_stale_order_cleanup=bool(session.get("run_stale_order_cleanup", True)),
        run_position_manager=bool(session.get("run_position_manager", True)),
        run_execution=bool(session.get("run_execution", True)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: RealtimeSessionSupervisorConfig) -> None:
    if config.stage != "M15.longbridge_realtime_session_supervisor":
        raise ValueError("M15 realtime session supervisor stage drift")
    if config.check_interval_seconds <= 0:
        raise ValueError("M15 realtime session supervisor check interval must be positive")
    if config.idle_check_interval_seconds <= 0:
        raise ValueError("M15 realtime session supervisor idle check interval must be positive")
    if config.max_consecutive_failures <= 0:
        raise ValueError("M15 realtime session supervisor max_consecutive_failures must be positive")
    if not (
        config.run_ingestor
        or config.run_router
        or config.run_account_state
        or config.run_stale_order_cleanup
        or config.run_position_manager
        or config.run_execution
    ):
        raise ValueError("M15 realtime session supervisor must run at least one step")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 realtime session supervisor must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("M15 realtime session supervisor cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("M15 realtime session supervisor cannot enable real money actions")
    if config.hard_boundaries.get("local_simulation_as_signal_source", False):
        raise ValueError("M15 realtime session supervisor cannot use local simulation as signal source")
    if config.hard_boundaries.get("manual_m12_37_once", False):
        raise ValueError("M15 realtime session supervisor cannot enable manual M12.37 once-mode")
    if config.hard_boundaries.get("margin_financing", False):
        raise ValueError("M15 realtime session supervisor cannot enable margin financing")


def parse_market_holidays(values: list[str]) -> frozenset[date]:
    holidays: set[date] = set()
    for raw_value in values:
        if not isinstance(raw_value, str):
            raise ValueError("market_holidays must contain ISO date strings")
        try:
            holidays.add(date.fromisoformat(raw_value))
        except ValueError as exc:
            raise ValueError(f"invalid market holiday date: {raw_value}") from exc
    return frozenset(holidays)


def parse_clock(value: str) -> wall_time:
    hour, minute = value.split(":")
    return wall_time(int(hour), int(minute))


def is_trading_day(config: RealtimeSessionSupervisorConfig, value: date) -> bool:
    return value.weekday() < 5 and value not in config.market_holidays


def next_trading_day(config: RealtimeSessionSupervisorConfig, value: date) -> date:
    candidate = value + timedelta(days=1)
    while not is_trading_day(config, candidate):
        candidate += timedelta(days=1)
    return candidate


def build_window_state(
    config: RealtimeSessionSupervisorConfig,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    utc_dt = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    market_dt = utc_dt.astimezone(ZoneInfo(config.market_timezone))
    regular_open = parse_clock(config.regular_session_start_time)
    regular_close = parse_clock(config.regular_session_end_time)
    if not is_trading_day(config, market_dt.date()):
        phase = "non_trading_day"
        plain = "非交易日等待"
        next_session_date = next_trading_day(config, market_dt.date())
    elif market_dt.time() < regular_open:
        phase = "before_regular_session"
        plain = "等待常规交易时段"
        next_session_date = market_dt.date()
    elif regular_open <= market_dt.time() <= regular_close:
        phase = "regular_session"
        plain = "美股常规交易时段"
        next_session_date = market_dt.date()
    else:
        phase = "after_regular_session"
        plain = "等待下一交易日"
        next_session_date = next_trading_day(config, market_dt.date())
    should_run = phase in set(config.active_market_phases)
    next_session_market_dt = datetime.combine(next_session_date, regular_open, tzinfo=ZoneInfo(config.market_timezone))
    current_session_market_dt = datetime.combine(market_dt.date(), regular_open, tzinfo=ZoneInfo(config.market_timezone))
    effective_session_market_dt = current_session_market_dt if phase == "regular_session" else next_session_market_dt
    seconds_until_next_session = max(0, int((next_session_market_dt.astimezone(UTC) - utc_dt).total_seconds()))
    return {
        "generated_at": to_iso(utc_dt),
        "market_phase": phase,
        "market_status": plain,
        "market_date": market_dt.date().isoformat(),
        "session_started_at": to_iso(effective_session_market_dt),
        "session_should_run": should_run,
        "new_york_time": market_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "beijing_time": utc_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "next_session_start_new_york": next_session_market_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "next_session_start_beijing": next_session_market_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "seconds_until_next_session": seconds_until_next_session,
    }


def run_realtime_session_once(
    config: RealtimeSessionSupervisorConfig | None = None,
    *,
    generated_at: str | None = None,
    ingestor_runner: StepRunner | None = None,
    router_runner: StepRunner | None = None,
    account_state_runner: StepRunner | None = None,
    stale_order_cleanup_runner: StepRunner | None = None,
    position_manager_runner: StepRunner | None = None,
    execution_runner: StepRunner | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    window = build_window_state(config, generated_at=generated_at_iso)
    previous = read_json(status_path(config))
    previous_failures = int_like(previous.get("consecutive_failure_count", 0))
    breaker_already_tripped = previous_failures >= config.max_consecutive_failures
    step_rows: list[dict[str, Any]] = []
    step_payloads: dict[str, dict[str, Any]] = {}
    failure_state = ""
    failure_reason = ""
    cycle_ran = False

    if not window["session_should_run"]:
        status = "waiting_market_window"
        if config.run_account_state:
            started = datetime.now(UTC)
            cached_account_state: dict[str, Any] = {}
            cached_account_summary: dict[str, Any] = {}
            cached_pnl_reconciliation: dict[str, Any] = {}
            cached_pnl_report = ""
            account_state_config = None
            try:
                account_state_config = load_account_state_config(config.account_state_config_path)
                cached_account_state = read_json(account_state_config.account_state_path)
                cached_account_summary = read_json(account_state_config.output_dir / ACCOUNT_STATE_SUMMARY_JSON)
                cached_pnl_reconciliation = read_json(account_state_config.output_dir / ACCOUNT_PNL_RECONCILIATION_JSON)
                cached_pnl_report_path = account_state_config.output_dir / ACCOUNT_PNL_RECONCILIATION_MD
                cached_pnl_report = cached_pnl_report_path.read_text(encoding="utf-8") if cached_pnl_report_path.exists() else ""
            except ValueError:
                cached_account_state = {}
            try:
                if account_state_runner is None:
                    account_state_config = account_state_config or load_account_state_config(config.account_state_config_path)
                    account_state_payload = run_realtime_account_state(account_state_config, generated_at=generated_at_iso)
                else:
                    account_state_payload = account_state_runner(generated_at_iso)
                elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
                if not account_state_is_valid_paper(account_state_payload):
                    if account_state_is_valid_paper(cached_account_state):
                        failure_state = "account_state_refresh_failed"
                        failure_reason = "account_state_refresh_returned_non_paper_or_empty_snapshot"
                        step_payloads["account_state"] = cached_account_state
                        if account_state_config is not None:
                            restore_cached_account_artifacts(
                                account_state_config,
                                account_state=cached_account_state,
                                account_summary=cached_account_summary,
                                pnl_reconciliation=cached_pnl_reconciliation,
                                pnl_report=cached_pnl_report,
                            )
                        step_rows.append(
                            {
                                "step_id": "account_state_refresh_only",
                                "status": "failed_using_cached",
                                "elapsed_ms": elapsed_ms,
                                "error": failure_reason,
                                "summary": payload_summary("account_state", cached_account_state),
                            }
                        )
                        account_state_payload = None
                    else:
                        step_payloads["account_state"] = account_state_payload
                else:
                    step_payloads["account_state"] = account_state_payload
                if account_state_payload is None:
                    continue_waiting_status = True
                else:
                    continue_waiting_status = False
                if continue_waiting_status:
                    pass
                else:
                    step_rows.append(
                        {
                            "step_id": "account_state_refresh_only",
                            "status": "ok",
                            "elapsed_ms": elapsed_ms,
                            "summary": payload_summary("account_state", account_state_payload),
                        }
                    )
            except Exception as exc:
                elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
                failure_state = "account_state_refresh_failed"
                failure_reason = str(exc)[:500]
                step_rows.append(
                    {
                        "step_id": "account_state_refresh_only",
                        "status": "failed",
                        "elapsed_ms": elapsed_ms,
                        "error": failure_reason,
                    }
                )
                if account_state_is_valid_paper(cached_account_state):
                    step_payloads["account_state"] = cached_account_state
                    if account_state_config is not None:
                        restore_cached_account_artifacts(
                            account_state_config,
                            account_state=cached_account_state,
                            account_summary=cached_account_summary,
                            pnl_reconciliation=cached_pnl_reconciliation,
                            pnl_report=cached_pnl_report,
                        )
    elif breaker_already_tripped:
        status = "failure_breaker_tripped"
        failure_state = "failure_breaker_tripped"
        failure_reason = str(previous.get("failure_reason") or "consecutive failure breaker is tripped")
    else:
        status = "running"
        cycle_ran = True
        steps = build_step_plan(
            config,
            ingestor_runner,
            router_runner,
            account_state_runner,
            stale_order_cleanup_runner,
            position_manager_runner,
            execution_runner,
            str(window["session_started_at"]),
        )
        for step_id, runner in steps:
            started = datetime.now(UTC)
            try:
                payload = runner(generated_at_iso)
                elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
                step_payloads[step_id] = payload
                step_rows.append(
                    {
                        "step_id": step_id,
                        "status": "ok",
                        "elapsed_ms": elapsed_ms,
                        "summary": payload_summary(step_id, payload),
                    }
                )
            except Exception as exc:  # pragma: no cover - runtime provider path
                elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
                failure_state = f"{step_id}_failed"
                failure_reason = str(exc)[:500]
                step_rows.append(
                    {
                        "step_id": step_id,
                        "status": "failed",
                        "elapsed_ms": elapsed_ms,
                        "error": failure_reason,
                    }
                )
                status = "cycle_failed"
                break
        if not failure_state:
            status = "cycle_completed"

    consecutive_failures = 0 if status in {"cycle_completed", "waiting_market_window"} else previous_failures + 1
    if consecutive_failures >= config.max_consecutive_failures and status == "cycle_failed":
        status = "failure_breaker_tripped"
        failure_state = failure_state or "failure_breaker_tripped"
        failure_reason = failure_reason or "consecutive failure breaker is tripped"
    summary = build_status_payload(
        config=config,
        generated_at=generated_at_iso,
        window=window,
        status=status,
        cycle_ran=cycle_ran,
        step_rows=step_rows,
        step_payloads=step_payloads,
        consecutive_failures=consecutive_failures,
        failure_state=failure_state,
        failure_reason=failure_reason,
    )
    write_json(status_path(config), summary)
    append_jsonl(ledger_path(config), summary)
    write_text_atomic(report_path(config), render_report(summary))
    dashboard_synced = sync_m12_dashboard_longbridge_panel(config)
    if dashboard_synced:
        summary["m12_dashboard_longbridge_panel_synced"] = True
        write_json(status_path(config), summary)
    return summary


def build_step_plan(
    config: RealtimeSessionSupervisorConfig,
    ingestor_runner: StepRunner | None,
    router_runner: StepRunner | None,
    account_state_runner: StepRunner | None,
    stale_order_cleanup_runner: StepRunner | None,
    position_manager_runner: StepRunner | None,
    execution_runner: StepRunner | None,
    session_started_at: str,
) -> list[tuple[str, StepRunner]]:
    steps: list[tuple[str, StepRunner]] = []
    if config.run_ingestor:
        if ingestor_runner is None:
            def ingestor_runner(generated_at: str | None) -> dict[str, Any]:
                ingestor_config = load_ingestor_config(config.ingestor_config_path)
                ingestor_config = replace(ingestor_config, session_started_at=session_started_at)
                return run_realtime_market_event_ingestor(ingestor_config, generated_at=generated_at)

        steps.append(("market_event_ingestor", ingestor_runner))
    if config.run_router:
        if router_runner is None:
            def router_runner(generated_at: str | None) -> dict[str, Any]:
                router_config = load_router_config(config.router_config_path)
                router_config = replace(router_config, session_started_at=session_started_at)
                return run_realtime_signal_router(router_config, generated_at=generated_at)

        steps.append(("signal_router", router_runner))
    if config.run_account_state:
        if account_state_runner is None:
            def account_state_runner(generated_at: str | None) -> dict[str, Any]:
                account_state_config = load_account_state_config(config.account_state_config_path)
                return run_realtime_account_state(account_state_config, generated_at=generated_at)

        steps.append(("account_state", account_state_runner))
    if config.run_stale_order_cleanup:
        if stale_order_cleanup_runner is None:
            def stale_order_cleanup_runner(generated_at: str | None) -> dict[str, Any]:
                cleanup_config = load_stale_order_cleanup_config(config.stale_order_cleanup_config_path)
                return run_stale_order_cleanup(
                    cleanup_config,
                    generated_at=generated_at,
                    session_started_at=session_started_at,
                )

        steps.append(("stale_order_cleanup", stale_order_cleanup_runner))
        if config.run_account_state:
            if account_state_runner is None:
                def account_state_after_cleanup_runner(generated_at: str | None) -> dict[str, Any]:
                    account_state_config = load_account_state_config(config.account_state_config_path)
                    return run_realtime_account_state(account_state_config, generated_at=generated_at)
            else:
                account_state_after_cleanup_runner = account_state_runner

            steps.append(("account_state_after_cleanup", account_state_after_cleanup_runner))
    if config.run_position_manager:
        if position_manager_runner is None:
            def position_manager_runner(generated_at: str | None) -> dict[str, Any]:
                position_manager_config = load_position_manager_config(config.position_manager_config_path)
                return run_realtime_position_manager(position_manager_config, generated_at=generated_at)

        steps.append(("position_manager", position_manager_runner))
    if config.run_execution:
        if execution_runner is None:
            def execution_runner(generated_at: str | None) -> dict[str, Any]:
                execution_config = load_execution_config(config.execution_config_path)
                execution_config = replace(execution_config, session_started_at=session_started_at)
                return run_realtime_execution(execution_config, generated_at=generated_at)

        steps.append(("paper_execution", execution_runner))
    return steps


def build_status_payload(
    *,
    config: RealtimeSessionSupervisorConfig,
    generated_at: str,
    window: dict[str, Any],
    status: str,
    cycle_ran: bool,
    step_rows: list[dict[str, Any]],
    step_payloads: dict[str, dict[str, Any]],
    consecutive_failures: int,
    failure_state: str,
    failure_reason: str,
) -> dict[str, Any]:
    ingestor = step_payloads.get("market_event_ingestor", {})
    router = step_payloads.get("signal_router", {})
    account_state = step_payloads.get("account_state", {})
    stale_order_cleanup = step_payloads.get("stale_order_cleanup", {})
    account_state_after_cleanup = step_payloads.get("account_state_after_cleanup", {})
    effective_account_state = account_state_after_cleanup or account_state
    position_manager = step_payloads.get("position_manager", {})
    execution = step_payloads.get("paper_execution", {})
    return {
        "schema_version": "m15.longbridge-realtime-session-supervisor.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at,
        "supervisor_status": status,
        "cycle_ran": cycle_ran,
        "window": window,
        "session_should_run": bool(window.get("session_should_run")),
        "consecutive_failure_count": consecutive_failures,
        "max_consecutive_failures": config.max_consecutive_failures,
        "failure_state": failure_state,
        "failure_reason": failure_reason,
        "step_rows": step_rows,
        "market_event_count": int_like(router.get("market_event_count", ingestor.get("market_event_total_count", 0))),
        "new_market_event_count": int_like(ingestor.get("new_market_event_count", 0)),
        "new_signal_event_count": int_like(router.get("new_signal_event_count", 0)),
        "paper_account_verified": bool(effective_account_state.get("paper_account_verified", False)),
        "account_position_row_count": int_like(effective_account_state.get("position_row_count", 0)),
        "account_open_order_count": int_like(effective_account_state.get("open_order_count", 0)),
        "stale_order_cleanup_status": str(stale_order_cleanup.get("cleanup_status") or ""),
        "stale_buy_open_order_count": int_like(stale_order_cleanup.get("stale_buy_open_order_count", 0)),
        "stale_buy_open_order_canceled_count": int_like(stale_order_cleanup.get("canceled_count", 0)),
        "stale_buy_open_order_cleanup_failed_count": int_like(stale_order_cleanup.get("failed_count", 0)),
        "new_exit_signal_event_count": int_like(position_manager.get("new_exit_signal_event_count", 0)),
        "ready_order_count": int_like(execution.get("ready_order_count", 0)),
        "submitted_count": int_like(execution.get("submitted_count", 0)),
        "local_simulation_isolated": True,
        "local_ledger_input_ref": "",
        "legacy_fast_queue_used": False,
        "manual_m12_37_once_used": False,
        "paper_simulated_only": True,
        "real_money_actions": False,
        "live_execution": False,
        "inputs": {
            "ingestor_config": project_path(config.ingestor_config_path),
            "router_config": project_path(config.router_config_path),
            "account_state_config": project_path(config.account_state_config_path),
            "stale_order_cleanup_config": project_path(config.stale_order_cleanup_config_path),
            "position_manager_config": project_path(config.position_manager_config_path),
            "execution_config": project_path(config.execution_config_path),
            "local_simulation_ledger": "",
            "fast_signal_queue": "",
        },
        "outputs": {
            "supervisor_status": project_path(status_path(config)),
            "supervisor_ledger": project_path(ledger_path(config)),
            "supervisor_report": project_path(report_path(config)),
        },
        "plain_language_result": plain_language_result(status, window, step_rows, failure_reason),
    }


def payload_summary(step_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if step_id == "market_event_ingestor":
        return {
            "new_market_event_count": int_like(payload.get("new_market_event_count", 0)),
            "deferred_count": int_like(payload.get("deferred_count", 0)),
        }
    if step_id == "signal_router":
        return {
            "market_event_count": int_like(payload.get("market_event_count", 0)),
            "new_signal_event_count": int_like(payload.get("new_signal_event_count", 0)),
        }
    if step_id == "account_state":
        return {
            "account_status": str(payload.get("account_status", "")),
            "paper_account_verified": bool(payload.get("paper_account_verified", False)),
            "position_row_count": int_like(payload.get("position_row_count", 0)),
            "open_order_count": int_like(payload.get("open_order_count", 0)),
        }
    if step_id == "stale_order_cleanup":
        return {
            "cleanup_status": str(payload.get("cleanup_status", "")),
            "stale_buy_open_order_count": int_like(payload.get("stale_buy_open_order_count", 0)),
            "canceled_count": int_like(payload.get("canceled_count", 0)),
            "failed_count": int_like(payload.get("failed_count", 0)),
        }
    if step_id == "account_state_after_cleanup":
        return {
            "account_status": str(payload.get("account_status", "")),
            "paper_account_verified": bool(payload.get("paper_account_verified", False)),
            "position_row_count": int_like(payload.get("position_row_count", 0)),
            "open_order_count": int_like(payload.get("open_order_count", 0)),
        }
    if step_id == "position_manager":
        return {
            "position_count": int_like(payload.get("position_count", 0)),
            "new_exit_signal_event_count": int_like(payload.get("new_exit_signal_event_count", 0)),
        }
    if step_id == "paper_execution":
        return {
            "signal_event_count": int_like(payload.get("signal_event_count", 0)),
            "ready_order_count": int_like(payload.get("ready_order_count", 0)),
            "submitted_count": int_like(payload.get("submitted_count", 0)),
        }
    return {}


def account_state_is_valid_paper(payload: dict[str, Any]) -> bool:
    channel = payload.get("account_channel", "lb_papertrading")
    return bool(payload.get("paper_account_verified")) and channel == "lb_papertrading"


def restore_cached_account_artifacts(
    account_state_config: Any,
    *,
    account_state: dict[str, Any],
    account_summary: dict[str, Any],
    pnl_reconciliation: dict[str, Any],
    pnl_report: str,
) -> None:
    write_json(account_state_config.account_state_path, account_state)
    if account_summary:
        write_json(account_state_config.output_dir / ACCOUNT_STATE_SUMMARY_JSON, account_summary)
    if pnl_reconciliation:
        write_json(account_state_config.output_dir / ACCOUNT_PNL_RECONCILIATION_JSON, pnl_reconciliation)
    if pnl_report:
        write_text_atomic(account_state_config.output_dir / ACCOUNT_PNL_RECONCILIATION_MD, pnl_report)


def plain_language_result(status: str, window: dict[str, Any], step_rows: list[dict[str, Any]], failure_reason: str) -> str:
    if status == "waiting_market_window":
        account_refresh = next((row for row in step_rows if row.get("step_id") == "account_state_refresh_only"), {})
        if account_refresh.get("status") == "ok":
            return (
                f"长桥实时链路守护器未运行交易循环：当前是{window.get('market_status')}，"
                "已只读刷新长桥账户状态，等待下一次美股常规交易时段。"
            )
        if account_refresh.get("status") == "failed_using_cached":
            return (
                f"长桥实时链路守护器未运行交易循环：当前是{window.get('market_status')}，"
                "长桥账户本轮只读刷新返回空快照，已保留上一份有效模拟账户状态，等待下一次美股常规交易时段。"
            )
        if account_refresh.get("status") == "failed":
            return (
                f"长桥实时链路守护器未运行交易循环：当前是{window.get('market_status')}，"
                f"长桥账户只读刷新失败，继续等待下一次美股常规交易时段：{failure_reason}。"
            )
        return f"长桥实时链路守护器未运行交易循环：当前是{window.get('market_status')}，等待下一次美股常规交易时段。"
    if status == "failure_breaker_tripped":
        return f"长桥实时链路守护器已触发连续失败熔断：{failure_reason or '等待人工检查'}。"
    if status == "cycle_failed":
        failed = next((row for row in step_rows if row.get("status") == "failed"), {})
        return f"长桥实时链路本轮失败，失败步骤是 {failed.get('step_id', 'unknown')}：{failure_reason}。"
    if status == "cycle_completed":
        return "长桥实时链路本轮已完成：只读行情、实时信号、模拟账户执行链路已按顺序串联；没有读取本地模拟账本。"
    return "长桥实时链路守护器状态已更新。"


def apply_dashboard_longbridge_panel_overlay(dashboard: dict[str, Any], longbridge_context: dict[str, Any]) -> None:
    dashboard["longbridge_paper_account"] = longbridge_context
    top_metrics = dashboard.setdefault("top_metrics", {})
    top_metrics["长桥模拟账户"] = str(longbridge_context.get("top_metric", "未生成长桥模拟账户状态"))
    for legacy_key in (
        "长桥可提交订单",
        "长桥配对成交胜率",
        "长桥已配对成交胜率",
        "长桥今日盈亏",
        "长桥总盈亏",
        "长桥交易总盈亏",
        "长桥当日总盈亏",
        "长桥App当日盈亏",
        "长桥账户总盈亏",
    ):
        top_metrics.pop(legacy_key, None)
    top_metrics["长桥账户当日盈亏"] = str(longbridge_context.get("longbridge_account_intraday_pnl") or longbridge_context.get("app_display_today_pnl") or "暂无")
    top_metrics["长桥接口持仓今日浮动"] = str(longbridge_context.get("today_total_pnl", "暂无"))
    top_metrics["长桥当前持仓总盈亏"] = str(longbridge_context.get("total_pnl", "暂无"))
    top_metrics["长桥账户总资产"] = str(longbridge_context.get("account_total_equity_estimate", "暂无"))
    top_metrics["长桥交易累计盈亏"] = str(longbridge_context.get("longbridge_stock_total_pnl", "暂无"))
    top_metrics["长桥逐标的胜率"] = str(longbridge_context.get("longbridge_symbol_win_rate_label", "暂无"))
    top_metrics["长桥交易胜率"] = str(longbridge_context.get("longbridge_closed_trade_win_rate_label", "暂无"))
    top_metrics["长桥修复后样本"] = str(longbridge_context.get("longbridge_post_fix_closed_trade_count", "0"))
    top_metrics["长桥最大回撤"] = str(longbridge_context.get("longbridge_max_drawdown_label", "样本不足"))
    top_metrics["长桥项目资金占用"] = str(longbridge_context.get("project_model_exposure_label", "暂无"))
    top_metrics["长桥本轮可新开仓"] = str(longbridge_context.get("submit_ready_count", "0"))


def sync_m12_dashboard_longbridge_panel(config: RealtimeSessionSupervisorConfig) -> bool:
    dashboard_dir = config.output_dir.parent / "m12_29_current_day_scan_dashboard"
    dashboard_path = dashboard_dir / "m12_32_minute_readonly_dashboard_data.json"
    if not dashboard_path.exists():
        return False
    try:
        from scripts.m12_29_current_day_scan_dashboard_lib import (
            build_dashboard_html,
            build_longbridge_paper_dashboard_view,
            load_config as load_m12_29_dashboard_config,
            write_text_atomic as write_m12_text_atomic,
        )

        dashboard_config = replace(load_m12_29_dashboard_config(), output_dir=dashboard_dir)
        dashboard = read_json(dashboard_path)
        longbridge_context = build_longbridge_paper_dashboard_view(dashboard_config)
        apply_dashboard_longbridge_panel_overlay(dashboard, longbridge_context)
        write_json(dashboard_path, dashboard)
        try:
            write_m12_text_atomic(
                dashboard_dir / "m12_32_minute_readonly_dashboard.html",
                build_dashboard_html(dashboard_config, dashboard),
            )
        except Exception as exc:  # pragma: no cover - display-only repair path
            write_json(
                config.output_dir / "m15_m12_dashboard_html_sync_error.json",
                {
                    "schema_version": "m15.m12-dashboard-html-sync-error.v1",
                    "generated_at": to_iso(datetime.now(UTC)),
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                    "paper_simulated_only": True,
                    "real_money_actions": False,
                    "live_execution": False,
                },
            )
        return True
    except Exception as exc:  # pragma: no cover - display-only repair path
        write_json(
            config.output_dir / "m15_m12_dashboard_longbridge_sync_error.json",
            {
                "schema_version": "m15.m12-dashboard-longbridge-sync-error.v1",
                "generated_at": to_iso(datetime.now(UTC)),
                "error_type": exc.__class__.__name__,
                "error": str(exc),
                "paper_simulated_only": True,
                "real_money_actions": False,
                "live_execution": False,
            },
        )
        return False


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# 长桥实时链路守护器",
        "",
        f"- 生成时间: `{summary['generated_at']}`",
        f"- 状态: `{summary['supervisor_status']}`",
        f"- 市场窗口: `{summary['window']['market_status']}`",
        f"- 是否运行交易循环: `{summary['cycle_ran']}`",
        f"- 结论: {summary['plain_language_result']}",
        "",
        "## 本轮步骤",
        "",
        "| 步骤 | 状态 | 耗时毫秒 | 摘要 |",
        "|---|---|---:|---|",
    ]
    for row in summary.get("step_rows", []):
        lines.append(
            f"| `{row.get('step_id', '')}` | `{row.get('status', '')}` | "
            f"`{row.get('elapsed_ms', '')}` | `{json.dumps(row.get('summary', row.get('error', '')), ensure_ascii=False)}` |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 只串联 M15 实时链路，不运行 M12.37 once-mode。",
            "- 不读取本地模拟账本，不读取旧快速队列。",
            "- 默认仍是长桥模拟账户链路，真实资金和实盘继续禁用。",
            "",
        ]
    )
    return "\n".join(lines)


def status_path(config: RealtimeSessionSupervisorConfig) -> Path:
    return config.output_dir / SUMMARY_JSON


def ledger_path(config: RealtimeSessionSupervisorConfig) -> Path:
    return config.output_dir / LEDGER_JSONL


def report_path(config: RealtimeSessionSupervisorConfig) -> Path:
    return config.output_dir / REPORT_MD


def pid_path(config: RealtimeSessionSupervisorConfig) -> Path:
    return config.output_dir / PID_FILE


def log_path(config: RealtimeSessionSupervisorConfig) -> Path:
    return config.output_dir / LOG_FILE


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    rotate_jsonl_if_needed(path, max_bytes=MAX_SUPERVISOR_LEDGER_BYTES, keep_lines=MAX_SUPERVISOR_LEDGER_LINES)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def rotate_jsonl_if_needed(path: Path, *, max_bytes: int, keep_lines: int) -> None:
    if max_bytes <= 0 or keep_lines <= 0 or not path.exists() or path.stat().st_size <= max_bytes:
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) <= keep_lines:
        return
    archive_dir = path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = archive_dir / f"{path.stem}.{timestamp}.archived.jsonl"
    archived_lines = lines[:-keep_lines]
    retained_lines = lines[-keep_lines:]
    write_text_atomic(archive_path, "\n".join(archived_lines) + "\n")
    write_text_atomic(path, "\n".join(retained_lines) + "\n")


def rotate_text_log_if_needed(path: Path, *, max_bytes: int) -> Path | None:
    if max_bytes <= 0 or not path.exists() or path.stat().st_size <= max_bytes:
        return None
    archive_dir = path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = archive_dir / f"{path.stem}.{timestamp}.archived.log"
    path.replace(archive_path)
    return archive_path


def int_like(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
