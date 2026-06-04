#!/usr/bin/env python3
from __future__ import annotations

import json
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
from scripts.m15_longbridge_realtime_account_state_lib import load_config as load_account_state_config
from scripts.m15_longbridge_realtime_account_state_lib import run_realtime_account_state
from scripts.m15_longbridge_realtime_market_event_ingestor_lib import load_config as load_ingestor_config
from scripts.m15_longbridge_realtime_market_event_ingestor_lib import run_realtime_market_event_ingestor
from scripts.m15_longbridge_realtime_position_manager_lib import load_config as load_position_manager_config
from scripts.m15_longbridge_realtime_position_manager_lib import run_realtime_position_manager
from scripts.m15_longbridge_realtime_signal_router_lib import load_config as load_router_config
from scripts.m15_longbridge_realtime_signal_router_lib import run_realtime_signal_router


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_session_supervisor.json"
DEFAULT_INGESTOR_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_market_event_ingestor.json"
DEFAULT_ROUTER_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_signal_router.json"
DEFAULT_ACCOUNT_STATE_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_account_state.json"
DEFAULT_POSITION_MANAGER_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_position_manager.json"
DEFAULT_EXECUTION_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_execution.json"
SUMMARY_JSON = "m15_longbridge_realtime_session_supervisor.json"
LEDGER_JSONL = "m15_longbridge_realtime_session_supervisor_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_session_supervisor.md"
PID_FILE = "m15_longbridge_realtime_session_supervisor.pid"
LOG_FILE = "m15_longbridge_realtime_session_supervisor.log"

StepRunner = Callable[[str | None], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RealtimeSessionSupervisorConfig:
    stage: str
    title: str
    output_dir: Path
    ingestor_config_path: Path
    router_config_path: Path
    account_state_config_path: Path
    position_manager_config_path: Path
    execution_config_path: Path
    check_interval_seconds: int
    market_timezone: str
    regular_session_start_time: str
    regular_session_end_time: str
    active_market_phases: tuple[str, ...]
    market_holidays: frozenset[date]
    max_consecutive_failures: int
    run_ingestor: bool
    run_router: bool
    run_account_state: bool
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
        position_manager_config_path=resolve_repo_path(inputs.get("position_manager_config", DEFAULT_POSITION_MANAGER_CONFIG_PATH)),
        execution_config_path=resolve_repo_path(inputs.get("execution_config", DEFAULT_EXECUTION_CONFIG_PATH)),
        check_interval_seconds=int(session.get("check_interval_seconds", 5)),
        market_timezone=str(session.get("market_timezone", "America/New_York")),
        regular_session_start_time=str(session.get("regular_session_start_time", "09:30")),
        regular_session_end_time=str(session.get("regular_session_end_time", "16:00")),
        active_market_phases=tuple(str(item) for item in session.get("active_market_phases", ["regular_session"])),
        market_holidays=parse_market_holidays(session.get("market_holidays", [])),
        max_consecutive_failures=int(session.get("max_consecutive_failures", 3)),
        run_ingestor=bool(session.get("run_ingestor", True)),
        run_router=bool(session.get("run_router", True)),
        run_account_state=bool(session.get("run_account_state", True)),
        run_position_manager=bool(session.get("run_position_manager", True)),
        run_execution=bool(session.get("run_execution", True)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: RealtimeSessionSupervisorConfig) -> None:
    if config.stage != "M15.longbridge_realtime_session_supervisor":
        raise ValueError("M15 realtime session supervisor stage drift")
    if config.check_interval_seconds <= 0:
        raise ValueError("M15 realtime session supervisor check interval must be positive")
    if config.max_consecutive_failures <= 0:
        raise ValueError("M15 realtime session supervisor max_consecutive_failures must be positive")
    if not (config.run_ingestor or config.run_router or config.run_account_state or config.run_position_manager or config.run_execution):
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
    }


def run_realtime_session_once(
    config: RealtimeSessionSupervisorConfig | None = None,
    *,
    generated_at: str | None = None,
    ingestor_runner: StepRunner | None = None,
    router_runner: StepRunner | None = None,
    account_state_runner: StepRunner | None = None,
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
    report_path(config).write_text(render_report(summary), encoding="utf-8")
    return summary


def build_step_plan(
    config: RealtimeSessionSupervisorConfig,
    ingestor_runner: StepRunner | None,
    router_runner: StepRunner | None,
    account_state_runner: StepRunner | None,
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
        "paper_account_verified": bool(account_state.get("paper_account_verified", False)),
        "account_position_row_count": int_like(account_state.get("position_row_count", 0)),
        "account_open_order_count": int_like(account_state.get("open_order_count", 0)),
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


def plain_language_result(status: str, window: dict[str, Any], step_rows: list[dict[str, Any]], failure_reason: str) -> str:
    if status == "waiting_market_window":
        return f"长桥实时链路守护器未运行交易循环：当前是{window.get('market_status')}，等待下一次美股常规交易时段。"
    if status == "failure_breaker_tripped":
        return f"长桥实时链路守护器已触发连续失败熔断：{failure_reason or '等待人工检查'}。"
    if status == "cycle_failed":
        failed = next((row for row in step_rows if row.get("status") == "failed"), {})
        return f"长桥实时链路本轮失败，失败步骤是 {failed.get('step_id', 'unknown')}：{failure_reason}。"
    if status == "cycle_completed":
        return "长桥实时链路本轮已完成：只读行情、实时信号、模拟账户执行链路已按顺序串联；没有读取本地模拟账本。"
    return "长桥实时链路守护器状态已更新。"


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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def int_like(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
