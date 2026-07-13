#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time as wall_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_29_current_day_scan_dashboard_lib import (  # noqa: E402
    build_dashboard_html,
    build_longbridge_paper_dashboard_view,
    load_m14_terminal_context,
    load_config as load_m12_29_dashboard_config,
    load_json,
    write_json,
    write_text_atomic,
)
from scripts.m15_longbridge_paper_order_submitter_lib import (  # noqa: E402
    ACCOUNT_STATE_JSON as M15_ACCOUNT_STATE_JSON,
    load_config as load_m15_paper_submitter_config,
    refresh_paper_account_state,
)


DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_47_session_supervisor.json"
DEFAULT_M1237_CONFIG_PATH = ROOT / "config" / "examples" / "m12_37_intraday_auto_loop.json"
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh" / "daily_observation" / "m12_29_current_day_scan_dashboard"
M15_ACCOUNT_REFRESH_MIN_INTERVAL_SECONDS = 60
DEFAULT_STALE_RESTART_LIMIT = 3


@dataclass(frozen=True, slots=True)
class BoundaryConfig:
    paper_simulated_only: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool
    paper_trading_approval: bool


@dataclass(frozen=True, slots=True)
class SupervisorConfig:
    title: str
    run_id: str
    stage: str
    source_m12_37_config_path: Path
    output_dir: Path
    check_interval_seconds: int
    market_timezone: str
    preopen_start_time: str
    regular_session_start_time: str
    regular_session_end_time: str
    postclose_grace_minutes: int
    stale_restart_limit: int
    market_holidays: frozenset[date]
    boundary: BoundaryConfig


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> SupervisorConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    boundary = payload["boundary"]
    config = SupervisorConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_47_session_supervisor"),
        stage=payload["stage"],
        source_m12_37_config_path=resolve_repo_path(payload.get("source_m12_37_config_path", str(DEFAULT_M1237_CONFIG_PATH))),
        output_dir=resolve_repo_path(payload.get("output_dir", str(DEFAULT_OUTPUT_DIR))),
        check_interval_seconds=int(payload["check_interval_seconds"]),
        market_timezone=payload["market_timezone"],
        preopen_start_time=payload["preopen_start_time"],
        regular_session_start_time=payload["regular_session_start_time"],
        regular_session_end_time=payload["regular_session_end_time"],
        postclose_grace_minutes=int(payload["postclose_grace_minutes"]),
        stale_restart_limit=int(payload.get("stale_restart_limit", DEFAULT_STALE_RESTART_LIMIT)),
        market_holidays=parse_market_holidays(payload.get("market_holidays", [])),
        boundary=BoundaryConfig(
            paper_simulated_only=bool(boundary["paper_simulated_only"]),
            trading_connection=bool(boundary["trading_connection"]),
            real_money_actions=bool(boundary["real_money_actions"]),
            live_execution=bool(boundary["live_execution"]),
            paper_trading_approval=bool(boundary["paper_trading_approval"]),
        ),
    )
    validate_config(config)
    return config


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


def validate_config(config: SupervisorConfig) -> None:
    if config.stage != "M12.47.session_supervisor":
        raise ValueError("M12.47 stage drift")
    if config.check_interval_seconds <= 0:
        raise ValueError("M12.47 check interval must be positive")
    if config.stale_restart_limit <= 0:
        raise ValueError("M12.47 stale restart limit must be positive")
    if not config.boundary.paper_simulated_only:
        raise ValueError("M12.47 must stay paper/simulated only")
    if (
        config.boundary.trading_connection
        or config.boundary.real_money_actions
        or config.boundary.live_execution
        or config.boundary.paper_trading_approval
    ):
        raise ValueError("M12.47 cannot enable trading connection, real money actions, live execution, or paper approval")


def parse_clock(value: str) -> wall_time:
    hour, minute = value.split(":")
    return wall_time(int(hour), int(minute))


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def int_like(value: Any, *, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def current_times(config: SupervisorConfig, generated_at: str | None = None) -> tuple[datetime, datetime]:
    utc_dt = datetime.fromisoformat((generated_at or now_utc_iso()).replace("Z", "+00:00"))
    market_dt = utc_dt.astimezone(ZoneInfo(config.market_timezone))
    return utc_dt, market_dt


def is_trading_day(config: SupervisorConfig, value: date) -> bool:
    return value.weekday() < 5 and value not in config.market_holidays


def next_trading_day(config: SupervisorConfig, value: date) -> date:
    candidate = value + timedelta(days=1)
    while not is_trading_day(config, candidate):
        candidate += timedelta(days=1)
    return candidate


def previous_trading_day(config: SupervisorConfig, value: date) -> date:
    candidate = value - timedelta(days=1)
    while not is_trading_day(config, candidate):
        candidate -= timedelta(days=1)
    return candidate


def build_window_state(config: SupervisorConfig, generated_at: str | None = None) -> dict[str, str]:
    utc_dt, market_dt = current_times(config, generated_at)
    preopen_start = parse_clock(config.preopen_start_time)
    regular_open = parse_clock(config.regular_session_start_time)
    regular_close = parse_clock(config.regular_session_end_time)
    if not is_trading_day(config, market_dt.date()):
        phase = "非交易日等待"
        next_session_date = next_trading_day(config, market_dt.date())
    elif market_dt.time() < preopen_start:
        phase = "等待开盘前预热"
        next_session_date = market_dt.date()
    elif preopen_start <= market_dt.time() < regular_open:
        phase = "开盘前预热窗口"
        next_session_date = market_dt.date()
    elif regular_open <= market_dt.time() <= regular_close:
        phase = "美股常规交易时段"
        next_session_date = market_dt.date()
    elif market_dt.time() <= (datetime.combine(market_dt.date(), regular_close) + timedelta(minutes=config.postclose_grace_minutes)).time():
        phase = "收盘后收尾窗口"
        next_session_date = next_trading_day(config, market_dt.date())
    else:
        phase = "等待下一交易日"
        next_session_date = next_trading_day(config, market_dt.date())
    next_session_market_dt = datetime.combine(next_session_date, preopen_start, tzinfo=ZoneInfo(config.market_timezone))
    return {
        "generated_at": utc_dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "market_status": phase,
        "market_date": market_dt.date().isoformat(),
        "market_holiday": str(market_dt.date() in config.market_holidays).lower(),
        "new_york_time": market_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "beijing_time": utc_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "session_should_run": str(phase in {"开盘前预热窗口", "美股常规交易时段", "收盘后收尾窗口"}).lower(),
        "next_session_start_new_york": next_session_market_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "next_session_start_beijing": next_session_market_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z"),
    }


def pid_path(config: SupervisorConfig) -> Path:
    return config.output_dir / "m12_47_session_supervisor.pid"


def status_path(config: SupervisorConfig) -> Path:
    return config.output_dir / "m12_47_session_supervisor_status.json"


def failure_dossier_path(config: SupervisorConfig) -> Path:
    return config.output_dir / "m12_47_session_failure_dossier.json"


def log_path(config: SupervisorConfig) -> Path:
    return config.output_dir / "m12_47_session_supervisor.log"


def child_log_path(config: SupervisorConfig) -> Path:
    return config.output_dir / "m12_37_session.log"


def dashboard_json_path(config: SupervisorConfig) -> Path:
    return config.output_dir / "m12_32_minute_readonly_dashboard_data.json"


def auto_runner_manifest_path(config: SupervisorConfig) -> Path:
    return config.output_dir / "m12_37_auto_runner_manifest.json"


def postclose_final_daily_refresh_path(config: SupervisorConfig) -> Path:
    return config.output_dir / "m12_37_postclose_final_daily_refresh_147.json"


def m1237_refresh_seconds(config: SupervisorConfig) -> int:
    try:
        payload = json.loads(config.source_m12_37_config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return 60
    try:
        return max(int(payload.get("refresh_seconds", 60)), 1)
    except (TypeError, ValueError):
        return 60


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    for _ in range(3):
        try:
            return load_json(path)
        except (OSError, ValueError):
            time.sleep(0.2)
    return {}


def process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def find_processes_containing(*needles: str) -> list[int]:
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return []
    if completed.returncode != 0:
        return []
    current_pid = os.getpid()
    matches: list[int] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, args = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == current_pid:
            continue
        if all(needle in args for needle in needles):
            matches.append(pid)
    return matches


def discover_supervisor_pids() -> list[int]:
    return find_processes_containing("run_m12_47_session_supervisor.py", "--foreground")


def discover_child_session_pids(config: SupervisorConfig) -> list[int]:
    return find_processes_containing(
        "run_m12_37_intraday_auto_loop.py",
        "--session",
        str(config.source_m12_37_config_path),
    )


def terminate_pids(pids: list[int]) -> bool:
    unique_pids = sorted({pid for pid in pids if pid > 0 and process_alive(pid)})
    if not unique_pids:
        return False
    for pid in unique_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + 5
    while time.time() < deadline:
        if not any(process_alive(pid) for pid in unique_pids):
            return True
        time.sleep(0.2)
    for pid in unique_pids:
        if process_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    return True


def spawn_m1237_session(config: SupervisorConfig) -> subprocess.Popen[str]:
    child_log_path(config).parent.mkdir(parents=True, exist_ok=True)
    log_handle = child_log_path(config).open("a", encoding="utf-8")
    return subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_m12_37_intraday_auto_loop.py"),
            "--session",
            "--config",
            str(config.source_m12_37_config_path),
        ],
        cwd=ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def build_status_payload(
    config: SupervisorConfig,
    *,
    phase: dict[str, str],
    supervisor_pid: int,
    supervisor_process_alive: bool,
    child_pid: int | None,
    child_running: bool,
    child_started_at: str,
    child_last_exit_code: int | None,
    restart_count: int,
    failure_state: str = "",
    failure_reason: str = "",
    stale_dashboard_restart_count: int = 0,
    last_restart_reason: str = "",
    last_real_failure_reason: str = "",
) -> dict[str, Any]:
    dashboard = read_json_if_exists(dashboard_json_path(config))
    raw_refresh_progress = read_json_if_exists(auto_runner_manifest_path(config))
    refresh_progress = normalize_refresh_progress_for_supervisor_status(
        raw_refresh_progress,
        phase=phase,
        child_running=child_running,
    )
    progress_snapshot = child_progress_snapshot(
        config,
        phase=phase,
        child_started_at=child_started_at,
        child_running=child_running,
        manifest=raw_refresh_progress,
    )
    dashboard_generated_at = dashboard.get("generated_at", "")
    dashboard_update = dashboard.get("update_status", {})
    latest_dashboard_beijing_time = dashboard_generated_at_beijing_time(str(dashboard_generated_at))
    return {
        "schema_version": "m12.47.session-supervisor-status.v1",
        "stage": config.stage,
        "title": config.title,
        "supervisor_pid": supervisor_pid,
        "supervisor_process_alive": supervisor_process_alive,
        "supervisor_generated_at": phase["generated_at"],
        "new_york_time": phase["new_york_time"],
        "beijing_time": phase["beijing_time"],
        "market_status": phase["market_status"],
        "session_should_run": phase["session_should_run"] == "true",
        "child_pid": child_pid or 0,
        "child_running": child_running,
        "child_started_at": child_started_at,
        "child_last_exit_code": "" if child_last_exit_code is None else str(child_last_exit_code),
        "restart_count": restart_count,
        "stale_dashboard_restart_count": stale_dashboard_restart_count,
        "last_restart_reason": last_restart_reason,
        "failure_state": failure_state,
        "failure_reason": failure_reason,
        "last_real_failure_reason": last_real_failure_reason,
        "next_session_start_new_york": phase["next_session_start_new_york"],
        "next_session_start_beijing": phase["next_session_start_beijing"],
        "latest_dashboard_generated_at": dashboard_generated_at,
        "latest_dashboard_beijing_time": latest_dashboard_beijing_time or dashboard_update.get("beijing_time", ""),
        "latest_dashboard_runtime_status": dashboard_update.get("runtime_status", ""),
        "m12_37_refresh_state": refresh_progress.get("refresh_state", ""),
        "m12_37_refresh_started_at": refresh_progress.get("refresh_started_at", ""),
        "m12_37_active_step": refresh_progress.get("active_step", ""),
        "m12_37_previous_dashboard_generated_at": refresh_progress.get("previous_dashboard_generated_at", ""),
        "child_last_progress_at": progress_snapshot.get("progress_at", ""),
        "child_last_progress_age_seconds": progress_snapshot.get("progress_age_seconds", ""),
        "child_progress_source": progress_snapshot.get("progress_source", ""),
        "child_progress_state": progress_snapshot.get("progress_state", ""),
        "plain_language_result": build_plain_language_status(
            phase,
            supervisor_process_alive,
            child_running,
            child_pid,
            dashboard_generated_at,
            failure_state,
            failure_reason,
            refresh_state=str(refresh_progress.get("refresh_state", "")),
            refresh_started_at=str(refresh_progress.get("refresh_started_at", "")),
        ),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def normalize_refresh_progress_for_supervisor_status(
    refresh_progress: dict[str, Any],
    *,
    phase: dict[str, str],
    child_running: bool,
) -> dict[str, Any]:
    progress = dict(refresh_progress or {})
    if phase.get("session_should_run") == "true" or child_running:
        return progress
    if progress.get("refresh_state") != "refresh_in_progress":
        return progress
    progress.setdefault("refresh_state_before_idle_overlay", progress.get("refresh_state", ""))
    progress.setdefault("refresh_started_at_before_idle_overlay", progress.get("refresh_started_at", ""))
    progress.setdefault("active_step_before_idle_overlay", progress.get("active_step", ""))
    progress["refresh_state"] = "idle_waiting_market_window"
    progress["refresh_started_at"] = ""
    progress["active_step"] = "idle"
    return progress


def dashboard_generated_at_beijing_time(generated_at: str) -> str:
    if not generated_at:
        return ""
    try:
        generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return generated_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z")


def build_plain_language_status(
    phase: dict[str, str],
    supervisor_process_alive: bool,
    child_running: bool,
    child_pid: int | None,
    dashboard_generated_at: str,
    failure_state: str = "",
    failure_reason: str = "",
    refresh_state: str = "",
    refresh_started_at: str = "",
) -> str:
    if failure_state == "failed":
        return (
            f"自动调度器已熔断：{failure_reason or '连续失败'}；当前市场状态 {phase['market_status']}，"
            f"最近面板刷新 {dashboard_generated_at or '暂无'}。"
        )
    if not supervisor_process_alive:
        return (
            f"自动调度器没有运行；当前市场状态 {phase['market_status']}，"
            f"最近面板刷新 {dashboard_generated_at or '暂无'}。"
        )
    if child_running:
        if refresh_state == "refresh_in_progress":
            return (
                f"自动调度器正在运行；当前市场状态 {phase['market_status']}，子会话 PID {child_pid or 0}，"
                f"M12.37 正在刷新核心看板，开始 {refresh_started_at or '未知'}；"
                f"最近核心面板数据时间 {dashboard_generated_at or '暂无'}。"
            )
        return (
            f"自动调度器正在运行；当前市场状态 {phase['market_status']}，"
            f"子会话 PID {child_pid or 0}，最近面板刷新 {dashboard_generated_at or '暂无'}。"
        )
    return (
        f"自动调度器存活，但当前没有盘中子会话；市场状态 {phase['market_status']}，"
        f"最近面板刷新 {dashboard_generated_at or '暂无'}。"
    )


def write_status(config: SupervisorConfig, payload: dict[str, Any]) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(status_path(config), payload)


def dashboard_runtime_status_from_supervisor(payload: dict[str, Any]) -> str:
    market_status = str(payload.get("market_status", ""))
    if market_status == "非交易日等待":
        return "非交易日等待，M12.37 不会启动；当前面板保留上一有效审计快照。"
    if market_status == "等待下一交易日":
        return "等待下一交易日，M12.37 暂停刷新；当前面板保留上一有效审计快照。"
    if market_status == "等待开盘前预热":
        return "等待开盘前预热，M12.37 尚未进入预热窗口。"
    if market_status == "开盘前预热窗口":
        return "开盘前预热窗口，M12.37 可由守护器启动，只读预热不生成实盘订单。"
    if market_status == "收盘后收尾窗口":
        return "收盘后收尾窗口，M12.37 可进行只读收尾与盘后固化。"
    if payload.get("child_running") and payload.get("m12_37_refresh_state") == "refresh_in_progress":
        started_at = str(payload.get("m12_37_refresh_started_at") or "")
        active_step = str(payload.get("m12_37_active_step") or "unknown")
        return f"{market_status or '未知市场状态'}，M12.37 正在刷新核心看板（步骤 {active_step}，开始 {started_at or '未知'}）。"
    if payload.get("child_running") and payload.get("m12_37_refresh_state") == "light_heartbeat_waiting_next_5m_bar":
        return (
            f"{market_status or '未知市场状态'}，M12.37 轻量心跳正常；"
            "本地完整看板等待下一根 5 分钟 K 线再重算，长桥实时链路不受影响。"
        )
    if market_status == "美股常规交易时段":
        return "美股常规交易时段，M12.37 应由守护器保持只读刷新。"
    return f"{market_status or '未知市场状态'}；当前面板保留上一有效审计快照。"


def normalize_longbridge_freshness_warning_text(warning: str) -> str:
    if (
        "quote_source=longbridge_quote_readonly" in warning
        and "看板已生成但数据源降级 / fallback quotes / no-fetch：" in warning
    ):
        return warning.replace(
            "看板已生成但数据源降级 / fallback quotes / no-fetch：",
            "看板已生成但严格全量扫描口径未完成；长桥只读行情没有降级：",
            1,
        )
    return warning


def apply_dashboard_status_overlay(
    dashboard: dict[str, Any],
    payload: dict[str, Any],
    m14_context: dict[str, Any] | None = None,
) -> bool:
    if not dashboard:
        return False
    market_status = str(payload.get("market_status", ""))
    if not market_status:
        return False
    audit_only = market_status in {"非交易日等待", "等待下一交易日", "等待开盘前预热"}
    runtime_status = dashboard_runtime_status_from_supervisor(payload)
    supervisor_generated_at = str(payload.get("supervisor_generated_at", ""))
    now_dt = datetime.now(UTC).replace(microsecond=0)
    dashboard_generated_at = str(dashboard.get("generated_at") or dashboard.get("summary", {}).get("generated_at") or "")
    dashboard_beijing_time = dashboard_generated_at_beijing_time(dashboard_generated_at)
    dashboard_age_seconds = ""
    dashboard_stale = False
    prior_update_status = dashboard.get("update_status", {}) if isinstance(dashboard.get("update_status"), dict) else {}
    stale_after_seconds = int_like(prior_update_status.get("stale_after_seconds", 600), default=600)
    refresh_state = str(payload.get("m12_37_refresh_state") or "")
    refresh_started_at = str(payload.get("m12_37_refresh_started_at") or "")
    refresh_active_step = str(payload.get("m12_37_active_step") or "")
    refresh_started_dt = parse_utc_timestamp(refresh_started_at)
    refresh_age_seconds = ""
    refresh_in_progress = bool(payload.get("child_running")) and refresh_state == "refresh_in_progress"
    light_heartbeat = bool(payload.get("child_running")) and refresh_state == "light_heartbeat_waiting_next_5m_bar"
    refresh_within_expected_time = False
    if refresh_started_dt is not None:
        refresh_age = max(int((now_dt - refresh_started_dt).total_seconds()), 0)
        refresh_age_seconds = str(refresh_age)
        if refresh_in_progress:
            refresh_within_expected_time = refresh_age <= active_refresh_timeout_for_step(
                refresh_active_step,
                60,
            )
    if dashboard_generated_at:
        try:
            generated_dt = datetime.fromisoformat(dashboard_generated_at.replace("Z", "+00:00"))
            age_seconds = max(int((now_dt - generated_dt).total_seconds()), 0)
            dashboard_age_seconds = str(age_seconds)
            dashboard_stale = age_seconds > max(stale_after_seconds, 600)
        except ValueError:
            dashboard_age_seconds = ""
    session_liveness = "alive" if payload.get("child_running") else ("idle" if not payload.get("session_should_run") else "stopped")
    update_status = dashboard.setdefault("update_status", {})
    update_status.update(
        {
            "market_status": market_status,
            "new_york_time": str(payload.get("new_york_time", update_status.get("new_york_time", ""))),
            "beijing_time": dashboard_beijing_time or str(update_status.get("beijing_time") or payload.get("beijing_time", "")),
            "supervisor_beijing_time": str(payload.get("beijing_time", "")),
            "runtime_status": runtime_status,
            "session_liveness": session_liveness,
            "supervisor_process_alive": str(bool(payload.get("supervisor_process_alive"))).lower(),
            "last_heartbeat_at_utc": supervisor_generated_at,
            "last_heartbeat_beijing_time": str(payload.get("beijing_time", "")),
            "wall_clock_beijing_time": now_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z"),
            "dashboard_age_seconds": dashboard_age_seconds or str(update_status.get("dashboard_age_seconds", "")),
            "heartbeat_age_seconds": "0",
            "m12_37_refresh_state": refresh_state,
            "m12_37_refresh_started_at": refresh_started_at,
            "m12_37_refresh_age_seconds": refresh_age_seconds,
            "m12_37_active_step": refresh_active_step,
        }
    )
    if audit_only:
        update_status["freshness_state"] = "supervisor_idle"
    elif light_heartbeat:
        update_status["freshness_state"] = "light_heartbeat"
    elif refresh_in_progress and dashboard_stale and not refresh_within_expected_time:
        update_status["freshness_state"] = "refreshing_stale"
    elif refresh_in_progress:
        update_status["freshness_state"] = "refreshing"
    elif dashboard_stale:
        update_status["freshness_state"] = "stale"
    elif dashboard_age_seconds:
        update_status["freshness_state"] = "fresh"
    summary = dashboard.setdefault("summary", {})
    market_session = summary.setdefault("market_session", {})
    market_session.update(
        {
            "status": market_status,
            "new_york_time": str(payload.get("new_york_time", market_session.get("new_york_time", ""))),
            "beijing_time": str(payload.get("beijing_time", market_session.get("beijing_time", ""))),
        }
    )
    if audit_only:
        summary["current_day_runtime_ready"] = False
        summary["current_day_scan_complete"] = False
        overlay_warning = (
            f"市场状态由 M12.47 守护器覆盖为 {market_status}；"
            "当前面板是上一有效审计快照，不代表新的交易日测试。"
        )
        existing_warning = str(summary.get("data_freshness_warning", ""))
        if existing_warning and not summary.get("data_freshness_warning_before_audit_overlay"):
            summary["data_freshness_warning_before_audit_overlay"] = normalize_longbridge_freshness_warning_text(existing_warning)
        prior_warning = str(summary.get("data_freshness_warning_before_audit_overlay", ""))
        if prior_warning:
            summary["data_freshness_warning_before_audit_overlay"] = normalize_longbridge_freshness_warning_text(prior_warning)
        existing_plain_language = str(summary.get("plain_language_result", ""))
        if existing_plain_language and not summary.get("plain_language_result_before_audit_overlay"):
            summary["plain_language_result_before_audit_overlay"] = existing_plain_language
        summary["audit_only_snapshot"] = True
        summary["audit_only_snapshot_note"] = overlay_warning
        summary["data_freshness_warning"] = ""
        summary["plain_language_result"] = (
            f"{runtime_status} 守护器状态时间 {payload.get('beijing_time', '')}；"
            "当前不是新的交易日测试，不把当日行情缺口、零信号或旧账本状态当成刷新失败。"
        )
    else:
        summary["audit_only_snapshot"] = False
        summary["audit_only_snapshot_note"] = ""
    top_metrics = dashboard.setdefault("top_metrics", {})
    top_metrics["运行状态"] = runtime_status
    top_metrics["守护器状态时间"] = str(payload.get("beijing_time", ""))
    if audit_only:
        if market_status == "等待开盘前预热":
            top_metrics["数据快照状态"] = "等待开盘前预热：保留上一有效快照，未进入新交易日刷新窗口"
        elif market_status == "等待下一交易日":
            top_metrics["数据快照状态"] = "等待下一交易日：保留上一有效审计快照"
        else:
            top_metrics["数据快照状态"] = "非交易日审计快照"
    elif light_heartbeat:
        top_metrics["数据快照状态"] = "M12.37 轻量心跳：等待下一根 5 分钟 K 线再重算本地完整看板"
    elif refresh_in_progress and dashboard_stale and not refresh_within_expected_time:
        top_metrics["数据快照状态"] = (
            f"M12.37 正在刷新中：核心看板 {dashboard_age_seconds} 秒未更新，"
            f"本轮刷新已运行 {refresh_age_seconds or '未知'} 秒"
        )
    elif refresh_in_progress:
        top_metrics["数据快照状态"] = f"M12.37 正在刷新中：本轮刷新已运行 {refresh_age_seconds or '未知'} 秒"
    elif dashboard_stale:
        top_metrics["数据快照状态"] = f"交易窗口刷新滞后：核心看板 {dashboard_age_seconds} 秒未更新"
    else:
        top_metrics["数据快照状态"] = "交易窗口刷新中"
    terminal = dashboard.setdefault("broker_terminal_view", {})
    top_status = terminal.setdefault("top_status", {})
    top_status.update(
        {
            "market_status": market_status,
            "new_york_time": update_status["new_york_time"],
            "beijing_time": update_status["beijing_time"],
            "runtime_status": runtime_status,
            "session_liveness": session_liveness,
            "freshness_state": update_status.get("freshness_state", ""),
            "fully_ready_for_trading_display": "false" if audit_only else top_status.get("fully_ready_for_trading_display", "false"),
            "data_freshness_warning": summary.get("data_freshness_warning", ""),
            "audit_only_snapshot_note": summary.get("audit_only_snapshot_note", ""),
            "m12_37_refresh_state": refresh_state,
            "m12_37_refresh_started_at": refresh_started_at,
            "m12_37_refresh_age_seconds": refresh_age_seconds,
            "m12_37_active_step": refresh_active_step,
        }
    )
    if m14_context:
        apply_dashboard_m14_overlay(terminal, m14_context)
    if audit_only:
        prior_m13_status = str(top_status.get("m13_goal_status", ""))
        if prior_m13_status and not top_status.get("m13_goal_status_before_audit_overlay"):
            top_status["m13_goal_status_before_audit_overlay"] = prior_m13_status
        top_status["m13_goal_status"] = (
            f"audit_only_snapshot; last_m13_status={prior_m13_status or 'not_available'}; "
            "not_counted_as_new_trading_day"
        )
    terminal["status_overlay"] = {
        "schema_version": "m12.47.dashboard-status-overlay.v1",
        "source": "m12_47_session_supervisor",
        "applied_at": now_dt.isoformat().replace("+00:00", "Z"),
        "supervisor_generated_at": supervisor_generated_at,
        "market_status": market_status,
        "session_should_run": bool(payload.get("session_should_run")),
        "child_running": bool(payload.get("child_running")),
        "audit_only": audit_only,
        "m12_37_refresh_state": refresh_state,
        "m12_37_refresh_started_at": refresh_started_at,
        "m12_37_refresh_age_seconds": refresh_age_seconds,
    }
    return True


def apply_dashboard_m14_overlay(terminal: dict[str, Any], m14_context: dict[str, Any]) -> None:
    top_status = terminal.setdefault("top_status", {})
    top_status.update(
        {
            "m13_goal_status": str(m14_context.get("m13_goal_status", top_status.get("m13_goal_status", "not_available"))),
            "m14_goal_status": str(m14_context.get("m14_goal_status", top_status.get("m14_goal_status", "not_available"))),
            "paper_trial_gate_approved_count": str(
                m14_context.get("paper_trial_gate_approved_count", top_status.get("paper_trial_gate_approved_count", "0"))
            ),
        }
    )
    paper_gate_by_strategy = m14_context.get("paper_gate_by_strategy") or {}
    decision_by_strategy = m14_context.get("decision_by_strategy") or {}
    apply_m14_rows_overlay(terminal.get("strategy_accounts", []), paper_gate_by_strategy, decision_by_strategy)
    apply_m14_rows_overlay(
        terminal.get("pa004_comparison", {}).get("rows", []),
        paper_gate_by_strategy,
        decision_by_strategy,
    )


def apply_dashboard_longbridge_overlay(dashboard: dict[str, Any], longbridge_context: dict[str, Any]) -> None:
    dashboard["longbridge_paper_account"] = longbridge_context
    top_metrics = dashboard.setdefault("top_metrics", {})
    top_metrics["长桥模拟账户"] = str(longbridge_context.get("top_metric", "未生成长桥模拟账户状态"))
    top_metrics.pop("长桥可提交订单", None)
    top_metrics.pop("长桥配对成交胜率", None)
    top_metrics.pop("长桥已配对成交胜率", None)
    top_metrics.pop("长桥今日盈亏", None)
    top_metrics.pop("长桥总盈亏", None)
    top_metrics.pop("长桥交易总盈亏", None)
    top_metrics.pop("长桥当日总盈亏", None)
    top_metrics.pop("长桥账户当日盈亏", None)
    top_metrics.pop("长桥接口交易日盈亏", None)
    top_metrics.pop("长桥账户总盈亏", None)
    top_metrics.pop("长桥接口净值日内变化", None)
    top_metrics["长桥App当日盈亏"] = str(longbridge_context.get("longbridge_app_display_today_pnl", "等待长桥字段对齐"))
    top_metrics["长桥接口净值日内变化"] = str(longbridge_context.get("longbridge_account_intraday_pnl", "无法计算"))
    top_metrics["长桥接口持仓今日浮动"] = str(longbridge_context.get("longbridge_account_today_total_pnl", "暂无"))
    top_metrics["长桥当前持仓总盈亏"] = str(longbridge_context.get("longbridge_account_total_pnl", "暂无"))
    top_metrics["长桥账户总资产"] = str(longbridge_context.get("account_total_equity_estimate", "暂无"))
    top_metrics["长桥交易累计盈亏"] = str(longbridge_context.get("longbridge_stock_total_pnl", "暂无"))
    top_metrics["长桥逐标的胜率"] = str(longbridge_context.get("longbridge_symbol_win_rate_label", "暂无"))
    top_metrics["长桥交易胜率"] = str(longbridge_context.get("longbridge_closed_trade_win_rate_label", "暂无"))
    top_metrics["长桥修复后样本"] = str(longbridge_context.get("longbridge_post_fix_closed_trade_count", "0"))
    top_metrics["长桥最大回撤"] = str(longbridge_context.get("longbridge_max_drawdown_label", "样本不足"))
    top_metrics["长桥项目资金占用"] = str(longbridge_context.get("project_model_exposure_label", "暂无"))
    top_metrics["长桥本轮可新开仓"] = str(longbridge_context.get("submit_ready_count", "0"))


def apply_m14_rows_overlay(
    rows: Any,
    paper_gate_by_strategy: dict[str, Any],
    decision_by_strategy: dict[str, Any],
) -> None:
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        strategy_id = str(row.get("strategy_id", ""))
        if not strategy_id:
            continue
        gate = paper_gate_by_strategy.get(strategy_id, {})
        decision = decision_by_strategy.get(strategy_id, {})
        if decision:
            row["m14_decision"] = str(decision.get("decision", row.get("m14_decision", "not_available")))
            row["m14_decision_reason"] = str(decision.get("decision_reason", row.get("m14_decision_reason", "")))
        if gate:
            row["paper_trial_gate"] = str(gate.get("paper_trial_gate", row.get("paper_trial_gate", "gate_pending_or_auxiliary")))
            row["gate_reason"] = str(gate.get("gate_reason", row.get("gate_reason", "")))


def sync_dashboard_status_overlay(config: SupervisorConfig, payload: dict[str, Any]) -> bool:
    dashboard_path = dashboard_json_path(config)
    if not dashboard_path.exists():
        return False
    dashboard = read_json_if_exists(dashboard_path)
    if not dashboard:
        return False
    dashboard_config = replace(load_m12_29_dashboard_config(), output_dir=config.output_dir)
    m14_context = load_m14_terminal_context(dashboard_config)
    if not apply_dashboard_status_overlay(dashboard, payload, m14_context=m14_context):
        return False
    maybe_refresh_longbridge_account_state_for_dashboard(config, payload)
    apply_dashboard_longbridge_overlay(dashboard, build_longbridge_paper_dashboard_view(dashboard_config))
    write_json(dashboard_path, dashboard)
    overlay_error_path = config.output_dir / "m12_47_dashboard_status_overlay_error.json"
    try:
        write_text_atomic(
            config.output_dir / "m12_32_minute_readonly_dashboard.html",
            build_dashboard_html(dashboard_config, dashboard),
        )
        if overlay_error_path.exists():
            overlay_error_path.unlink()
    except Exception as exc:  # pragma: no cover - defensive artifact repair path
        write_json(
            overlay_error_path,
            {
                "schema_version": "m12.47.dashboard-status-overlay-error.v1",
                "generated_at": now_utc_iso(),
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
        )
    return True


def maybe_refresh_longbridge_account_state_for_dashboard(config: SupervisorConfig, payload: dict[str, Any]) -> bool:
    try:
        submitter_config = load_m15_paper_submitter_config()
        account_state_path = submitter_config.output_dir / M15_ACCOUNT_STATE_JSON
        if artifact_refresh_age_seconds(account_state_path) <= M15_ACCOUNT_REFRESH_MIN_INTERVAL_SECONDS:
            return False
        refresh_paper_account_state(submitter_config, generated_at=now_utc_iso())
        return True
    except Exception as exc:  # pragma: no cover - keeps dashboard overlay resilient when Longbridge is unavailable
        write_json(
            config.output_dir / "m12_47_longbridge_account_refresh_error.json",
            {
                "schema_version": "m12.47.longbridge-account-refresh-error.v1",
                "generated_at": now_utc_iso(),
                "error_type": exc.__class__.__name__,
                "error": str(exc),
                "paper_simulated_only": True,
                "real_money_actions": False,
                "live_execution": False,
            },
        )
        return False


def artifact_mtime_age_seconds(path: Path) -> int:
    if not path.exists():
        return 10**9
    return max(0, int(time.time() - path.stat().st_mtime))


def artifact_refresh_age_seconds(path: Path) -> int:
    if not path.exists():
        return 10**9
    mtime_age = artifact_mtime_age_seconds(path)
    payload = read_json_if_exists(path)
    if not payload:
        return 10**9
    generated_at = str(payload.get("generated_at", ""))
    try:
        generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return 10**9
    generated_age = max(0, int(datetime.now(UTC).timestamp() - generated_dt.timestamp()))
    return max(mtime_age, generated_age)


def sync_manifest_status_overlay(config: SupervisorConfig, payload: dict[str, Any]) -> bool:
    manifest_path = config.output_dir / "m12_37_auto_runner_manifest.json"
    if not manifest_path.exists():
        return False
    manifest = read_json_if_exists(manifest_path)
    if not manifest:
        return False
    market_status = str(payload.get("market_status", ""))
    if not market_status:
        return False
    prior_market_status = manifest.get("market_session", {}).get("status", "")
    manifest.setdefault("market_session", {})
    manifest["market_session"].update(
        {
            "status": market_status,
            "new_york_time": str(payload.get("new_york_time", "")),
            "beijing_time": str(payload.get("beijing_time", "")),
        }
    )
    audit_only = market_status in {"非交易日等待", "等待下一交易日", "等待开盘前预热"}
    if audit_only:
        manifest["loop_can_continue_now"] = False
        manifest["session_monitoring_active_now"] = False
        manifest["regular_session_active_now"] = False
        manifest["plain_language_result"] = dashboard_runtime_status_from_supervisor(payload)
        if not payload.get("child_running") and manifest.get("refresh_state") == "refresh_in_progress":
            manifest.setdefault("refresh_state_before_idle_overlay", manifest.get("refresh_state", ""))
            manifest.setdefault("refresh_started_at_before_idle_overlay", manifest.get("refresh_started_at", ""))
            manifest.setdefault("active_step_before_idle_overlay", manifest.get("active_step", ""))
            manifest["refresh_state"] = "idle_waiting_market_window"
            manifest["refresh_started_at"] = ""
            manifest["active_step"] = "idle"
    manifest["status_overlay"] = {
        "schema_version": "m12.47.manifest-status-overlay.v1",
        "source": "m12_47_session_supervisor",
        "applied_at": now_utc_iso(),
        "prior_market_status": prior_market_status,
        "market_status": market_status,
        "session_should_run": bool(payload.get("session_should_run")),
        "child_running": bool(payload.get("child_running")),
        "audit_only": audit_only,
        "manifest_refresh_state": str(manifest.get("refresh_state", "")),
    }
    write_json(manifest_path, manifest)
    return True


def parse_utc_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def child_progress_snapshot(
    config: SupervisorConfig,
    *,
    phase: dict[str, str],
    child_started_at: str,
    child_running: bool,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now_dt = parse_utc_timestamp(str(phase.get("generated_at") or ""))
    child_started_dt = parse_utc_timestamp(child_started_at)
    if now_dt is None or child_started_dt is None or not child_running:
        return {
            "progress_at": "",
            "progress_age_seconds": "",
            "progress_source": "",
            "progress_state": "",
            "recent_progress": False,
        }
    refresh_seconds = m1237_refresh_seconds(config)
    progress = manifest if manifest is not None else read_json_if_exists(auto_runner_manifest_path(config))
    progress_generated_dt = parse_utc_timestamp(str(progress.get("generated_at") or ""))
    refresh_started_dt = parse_utc_timestamp(str(progress.get("refresh_started_at") or ""))
    progress_state = str(progress.get("refresh_state") or "")
    active_step = str(progress.get("active_step") or "")
    progress_dt: datetime | None = None
    progress_source = ""
    if progress_generated_dt is not None and progress_generated_dt >= child_started_dt:
        progress_dt = progress_generated_dt
        progress_source = "manifest_generated_at"
    elif refresh_started_dt is not None and refresh_started_dt >= child_started_dt:
        progress_dt = refresh_started_dt
        progress_source = "manifest_refresh_started_at"
    else:
        log_file = child_log_path(config)
        if log_file.exists():
            log_dt = datetime.fromtimestamp(log_file.stat().st_mtime, UTC)
            if log_dt >= child_started_dt:
                progress_dt = log_dt
                progress_source = "child_log_mtime"
    recent_progress = False
    progress_age_seconds = ""
    if progress_dt is not None:
        progress_age = max(int((now_dt - progress_dt).total_seconds()), 0)
        progress_age_seconds = str(progress_age)
        within_seconds = max(refresh_seconds * 3, 180)
        if progress_state == "refresh_in_progress":
            within_seconds = active_refresh_timeout_for_step(active_step, refresh_seconds)
        recent_progress = progress_age <= within_seconds
    return {
        "progress_at": progress_dt.isoformat().replace("+00:00", "Z") if progress_dt is not None else "",
        "progress_age_seconds": progress_age_seconds,
        "progress_source": progress_source,
        "progress_state": progress_state,
        "recent_progress": recent_progress,
    }


def latest_child_failure_reason(config: SupervisorConfig, child_last_exit_code: int | None) -> str:
    manifest = read_json_if_exists(auto_runner_manifest_path(config))
    if str(manifest.get("refresh_state") or "") == "refresh_failed":
        error_type = str(manifest.get("error_type") or "").strip()
        error = str(manifest.get("error") or "").strip()
        detail = " ".join(part for part in (error_type, error) if part).strip()
        if detail:
            return detail
        plain = str(manifest.get("plain_language_result") or "").strip()
        if plain:
            return plain
    if child_last_exit_code not in (None, 0):
        return f"child_exit_code_{child_last_exit_code}"
    return ""


def stale_dashboard_restart_reason(config: SupervisorConfig, phase: dict[str, str], child_started_at: str) -> str:
    if phase.get("session_should_run") != "true":
        return ""
    now_dt = parse_utc_timestamp(phase.get("generated_at", ""))
    child_started_dt = parse_utc_timestamp(child_started_at)
    if now_dt is None or child_started_dt is None:
        return ""
    refresh_seconds = m1237_refresh_seconds(config)
    child_grace_seconds = max(refresh_seconds * 5, 300)
    child_age_seconds = int((now_dt - child_started_dt).total_seconds())
    if child_age_seconds < child_grace_seconds:
        return ""
    dashboard = read_json_if_exists(dashboard_json_path(config))
    dashboard_generated_at = str(dashboard.get("generated_at") or dashboard.get("summary", {}).get("generated_at") or "")
    dashboard_dt = parse_utc_timestamp(dashboard_generated_at)
    stale_after_seconds = max(refresh_seconds * 5, 600)
    progress = read_json_if_exists(auto_runner_manifest_path(config))
    progress_snapshot = child_progress_snapshot(
        config,
        phase=phase,
        child_started_at=child_started_at,
        child_running=True,
        manifest=progress,
    )
    if progress_snapshot["recent_progress"]:
        return ""
    refresh_state = str(progress.get("refresh_state") or "")
    refresh_started_dt = parse_utc_timestamp(str(progress.get("refresh_started_at") or ""))
    active_step = str(progress.get("active_step") or "")
    active_refresh_timeout_seconds = active_refresh_timeout_for_step(active_step, refresh_seconds)
    if refresh_state == "refresh_in_progress" and refresh_started_dt is not None:
        refresh_age_seconds = int((now_dt - refresh_started_dt).total_seconds())
        progress_belongs_to_child = refresh_started_dt >= child_started_dt
        if progress_belongs_to_child and refresh_age_seconds <= active_refresh_timeout_seconds:
            return ""
        if progress_belongs_to_child and child_has_recent_artifact_activity(config, now_dt, active_refresh_timeout_seconds):
            return ""
    if dashboard_dt is None:
        if child_has_recent_artifact_activity(config, now_dt, max(refresh_seconds * 10, 600)):
            return ""
        return f"dashboard_missing_after_child_age_{child_age_seconds}s"
    dashboard_age_seconds = int((now_dt - dashboard_dt).total_seconds())
    if dashboard_age_seconds > stale_after_seconds:
        return f"dashboard_stale_{dashboard_age_seconds}s_over_{stale_after_seconds}s"
    return ""


def active_refresh_timeout_for_step(active_step: str, refresh_seconds: int) -> int:
    default_timeout = max(refresh_seconds * 30, 1800)
    step_timeout_floor = {
        # Full current-day refresh can scan the expanded universe and run
        # downstream M13/M14 materialization before the dashboard timestamp
        # advances. The 147-symbol scan plus post-refresh reports can exceed
        # four hours, so keep this high enough to avoid killing a healthy
        # long refresh mid-session.
        "m12_29_current_day_scan_dashboard": 28800,
        "m13_daily_strategy_test_runner": 2400,
        "m14_strategy_challenge_gate": 2400,
    }
    return max(default_timeout, step_timeout_floor.get(active_step, 0))


def child_has_recent_artifact_activity(config: SupervisorConfig, now_dt: datetime, within_seconds: int) -> bool:
    newest_mtime: datetime | None = None
    roots: tuple[Path, ...] = (
        child_log_path(config),
        config.output_dir / "m12_12_current_day_source",
    )
    try:
        config.output_dir.resolve().relative_to(ROOT)
        roots = (
            *roots,
            ROOT / "local_data" / "longbridge_history",
            ROOT / "local_data" / "longbridge_intraday",
        )
    except ValueError:
        pass
    for root in roots:
        newest_mtime = newest_file_mtime(root, newest_mtime)
    if newest_mtime is None:
        return False
    return int((now_dt - newest_mtime).total_seconds()) <= within_seconds


def newest_file_mtime(path: Path, current: datetime | None = None) -> datetime | None:
    if not path.exists():
        return current
    if path.is_file():
        mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        return mtime if current is None or mtime > current else current
    newest = current
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(child.stat().st_mtime, UTC)
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def write_failure_dossier(config: SupervisorConfig, payload: dict[str, Any]) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(failure_dossier_path(config), payload)


def build_failure_payload(
    config: SupervisorConfig,
    *,
    phase: dict[str, str],
    consecutive_failures: int,
    child_last_exit_code: int | None,
    stale_restart_count: int = 0,
    last_real_failure_reason: str = "",
    failure_trigger: str = "child_exit_failures",
) -> dict[str, Any]:
    if failure_trigger == "stale_restart_limit":
        failure_reason = (
            f"M12.37 子会话 stale restart 已达 {stale_restart_count} 次，已停止自动重启。"
        )
    else:
        failure_reason = f"M12.37 子会话连续 {consecutive_failures} 次非零退出，已停止自动重启。"
    return {
        "schema_version": "m12.47.session-failure-dossier.v1",
        "stage": config.stage,
        "generated_at": phase["generated_at"],
        "failure_reason": failure_reason,
        "failure_trigger": failure_trigger,
        "consecutive_failures": consecutive_failures,
        "stale_restart_count": stale_restart_count,
        "last_exit_code": child_last_exit_code,
        "last_real_failure_reason": last_real_failure_reason,
        "market_status": phase["market_status"],
        "postclose_final_daily_refresh_147": read_json_if_exists(postclose_final_daily_refresh_path(config)),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
    }


def should_trip_failure_breaker(consecutive_failures: int) -> bool:
    return consecutive_failures >= 3


def write_pid(config: SupervisorConfig, pid: int) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pid_path(config).write_text(str(pid), encoding="utf-8")


def remove_pid_file(config: SupervisorConfig) -> None:
    try:
        pid_path(config).unlink()
    except FileNotFoundError:
        pass


def read_existing_pid(config: SupervisorConfig) -> int | None:
    path = pid_path(config)
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def stop_existing_supervisor(config: SupervisorConfig) -> bool:
    pid = read_existing_pid(config)
    pids = []
    if process_alive(pid):
        pids.append(int(pid))
    pids.extend(discover_child_session_pids(config))
    pids.extend(discover_supervisor_pids())
    if not pids:
        remove_pid_file(config)
        return False
    stopped = terminate_pids(pids)
    remove_pid_file(config)
    return stopped


def run_foreground(config: SupervisorConfig) -> int:
    existing = read_existing_pid(config)
    if process_alive(existing):
        print(f"supervisor_already_running pid={existing}")
        return 0
    write_pid(config, os.getpid())
    child: subprocess.Popen[str] | None = None
    child_started_at = ""
    child_last_exit_code: int | None = None
    restart_count = 0
    consecutive_failures = 0
    failure_state = ""
    failure_reason = ""
    stale_dashboard_restart_count = 0
    last_restart_reason = ""
    last_real_failure_reason = ""
    shutting_down = False

    def handle_term(signum, frame):  # type: ignore[no-untyped-def]
        nonlocal shutting_down
        shutting_down = True

    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)

    try:
        while not shutting_down:
            phase = build_window_state(config)
            should_run = phase["session_should_run"] == "true"
            child_running = child is not None and child.poll() is None
            if child is not None and not child_running:
                child_last_exit_code = child.poll()
                if child_last_exit_code not in (None, 0):
                    consecutive_failures += 1
                    last_real_failure_reason = latest_child_failure_reason(config, child_last_exit_code) or last_real_failure_reason
                else:
                    consecutive_failures = 0
                child = None
            if should_run and should_trip_failure_breaker(consecutive_failures):
                failure_state = "failed"
                failure_payload = build_failure_payload(
                    config,
                    phase=phase,
                    consecutive_failures=consecutive_failures,
                    child_last_exit_code=child_last_exit_code,
                    last_real_failure_reason=last_real_failure_reason,
                )
                failure_reason = failure_payload["failure_reason"]
                write_failure_dossier(config, failure_payload)
                should_run = False
            current_restart_reason = ""
            if should_run and child_running and child is not None:
                stale_reason = stale_dashboard_restart_reason(config, phase, child_started_at)
                if stale_reason:
                    stale_dashboard_restart_count += 1
                    current_restart_reason = stale_reason
                    last_restart_reason = stale_reason
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=10)
                    child_last_exit_code = child.returncode
                    child = None
                    child_running = False
                    consecutive_failures = 0
                    if stale_dashboard_restart_count >= config.stale_restart_limit:
                        failure_state = "failed"
                        failure_payload = build_failure_payload(
                            config,
                            phase=phase,
                            consecutive_failures=consecutive_failures,
                            child_last_exit_code=child_last_exit_code,
                            stale_restart_count=stale_dashboard_restart_count,
                            last_real_failure_reason=last_real_failure_reason,
                            failure_trigger="stale_restart_limit",
                        )
                        failure_reason = failure_payload["failure_reason"]
                        write_failure_dossier(config, failure_payload)
                        should_run = False
            if should_run and not child_running:
                child = spawn_m1237_session(config)
                child_started_at = phase["generated_at"]
                child_running = True
                if child_last_exit_code not in (None, 0):
                    restart_count += 1
            if not should_run and child_running and phase["market_status"] == "等待下一交易日":
                child.terminate()
                child.wait(timeout=10)
                child_last_exit_code = child.returncode
                child = None
                child_running = False
            write_status(
                config,
                build_status_payload(
                    config,
                    phase=phase,
                    supervisor_pid=os.getpid(),
                    supervisor_process_alive=True,
                    child_pid=child.pid if child_running and child else None,
                    child_running=child_running,
                    child_started_at=child_started_at,
                    child_last_exit_code=child_last_exit_code,
                    restart_count=restart_count,
                    failure_state=failure_state,
                    failure_reason=failure_reason,
                    stale_dashboard_restart_count=stale_dashboard_restart_count,
                    last_restart_reason=last_restart_reason or current_restart_reason,
                    last_real_failure_reason=last_real_failure_reason,
                ),
            )
            time.sleep(config.check_interval_seconds)
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        phase = build_window_state(config)
        write_status(
            config,
            build_status_payload(
                config,
                phase=phase,
                supervisor_pid=os.getpid(),
                supervisor_process_alive=True,
                child_pid=None,
                child_running=False,
                child_started_at=child_started_at,
                child_last_exit_code=child_last_exit_code,
                restart_count=restart_count,
                failure_state=failure_state,
                failure_reason=failure_reason,
                last_real_failure_reason=last_real_failure_reason,
            ),
        )
        return 0
    finally:
        remove_pid_file(config)


def start_daemon(config: SupervisorConfig, config_path: str | Path) -> int:
    existing = read_existing_pid(config)
    if process_alive(existing):
        print(f"supervisor_already_running pid={existing}")
        return 0
    discovered = [pid for pid in discover_supervisor_pids() if process_alive(pid)]
    if discovered:
        print(f"supervisor_already_running pid={discovered[0]}")
        return 0
    remove_pid_file(config)
    log_path(config).parent.mkdir(parents=True, exist_ok=True)
    with log_path(config).open("a", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--foreground",
                "--config",
                str(config_path),
            ],
            cwd=ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )
    print(json.dumps({"status": "started", "pid": proc.pid}, ensure_ascii=False))
    return 0


def print_status(config: SupervisorConfig) -> int:
    stored = read_json_if_exists(status_path(config))
    pid_file_pid = read_existing_pid(config) or 0
    stored_status_pid = int(stored.get("supervisor_pid") or 0) if stored else 0
    if process_alive(pid_file_pid):
        stored_pid = pid_file_pid
        supervisor_alive = True
    elif process_alive(stored_status_pid):
        stored_pid = stored_status_pid
        supervisor_alive = True
    else:
        stored_pid = stored_status_pid or pid_file_pid
        supervisor_alive = False
    child_pid = int(stored.get("child_pid") or 0) if stored else 0
    child_running = bool(stored.get("child_running")) and process_alive(child_pid)
    raw_exit_code = stored.get("child_last_exit_code") if stored else None
    try:
        child_last_exit_code = None if raw_exit_code in (None, "") else int(raw_exit_code)
    except (TypeError, ValueError):
        child_last_exit_code = None
    phase = build_window_state(config)
    payload = build_status_payload(
        config,
        phase=phase,
        supervisor_pid=stored_pid,
        supervisor_process_alive=supervisor_alive,
        child_pid=child_pid if child_running else None,
        child_running=child_running,
        child_started_at=stored.get("child_started_at", "") if stored else "",
        child_last_exit_code=child_last_exit_code,
        restart_count=int(stored.get("restart_count", 0)) if stored else 0,
        failure_state=stored.get("failure_state", "") if stored else "",
        failure_reason=stored.get("failure_reason", "") if stored else "",
        stale_dashboard_restart_count=int(stored.get("stale_dashboard_restart_count", 0)) if stored else 0,
        last_restart_reason=stored.get("last_restart_reason", "") if stored else "",
        last_real_failure_reason=stored.get("last_real_failure_reason", "") if stored else "",
    )
    write_status(config, payload)
    dashboard_synced = sync_dashboard_status_overlay(config, payload)
    sync_manifest_status_overlay(config, payload)
    if dashboard_synced:
        payload = build_status_payload(
            config,
            phase=phase,
            supervisor_pid=stored_pid,
            supervisor_process_alive=supervisor_alive,
            child_pid=child_pid if child_running else None,
            child_running=child_running,
            child_started_at=stored.get("child_started_at", "") if stored else "",
            child_last_exit_code=child_last_exit_code,
            restart_count=int(stored.get("restart_count", 0)) if stored else 0,
            failure_state=stored.get("failure_state", "") if stored else "",
            failure_reason=stored.get("failure_reason", "") if stored else "",
            stale_dashboard_restart_count=int(stored.get("stale_dashboard_restart_count", 0)) if stored else 0,
            last_restart_reason=stored.get("last_restart_reason", "") if stored else "",
            last_real_failure_reason=stored.get("last_real_failure_reason", "") if stored else "",
        )
        write_status(config, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M12.47 user-space session supervisor.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to supervisor config json.")
    parser.add_argument("--foreground", action="store_true", help="Run in foreground loop.")
    parser.add_argument("--daemon", action="store_true", help="Start detached background supervisor.")
    parser.add_argument("--status", action="store_true", help="Print current supervisor status.")
    parser.add_argument("--stop", action="store_true", help="Stop background supervisor.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if args.status:
        return print_status(config)
    if args.stop:
        stopped = stop_existing_supervisor(config)
        print(json.dumps({"status": "stopped" if stopped else "not_running"}, ensure_ascii=False))
        return 0
    if args.foreground:
        return run_foreground(config)
    if args.daemon:
        return start_daemon(config, args.config)
    return print_status(config)


if __name__ == "__main__":
    raise SystemExit(main())
