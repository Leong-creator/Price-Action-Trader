#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, time as wall_time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_29_current_day_scan_dashboard_lib import load_json, write_json  # noqa: E402


DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_47_session_supervisor.json"
DEFAULT_M1237_CONFIG_PATH = ROOT / "config" / "examples" / "m12_37_intraday_auto_loop.json"
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh" / "daily_observation" / "m12_29_current_day_scan_dashboard"


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


def validate_config(config: SupervisorConfig) -> None:
    if config.stage != "M12.47.session_supervisor":
        raise ValueError("M12.47 stage drift")
    if config.check_interval_seconds <= 0:
        raise ValueError("M12.47 check interval must be positive")
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


def current_times(config: SupervisorConfig, generated_at: str | None = None) -> tuple[datetime, datetime]:
    utc_dt = datetime.fromisoformat((generated_at or now_utc_iso()).replace("Z", "+00:00"))
    market_dt = utc_dt.astimezone(ZoneInfo(config.market_timezone))
    return utc_dt, market_dt


def next_business_day(value: date) -> date:
    candidate = value + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def previous_business_day(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def build_window_state(config: SupervisorConfig, generated_at: str | None = None) -> dict[str, str]:
    utc_dt, market_dt = current_times(config, generated_at)
    preopen_start = parse_clock(config.preopen_start_time)
    regular_open = parse_clock(config.regular_session_start_time)
    regular_close = parse_clock(config.regular_session_end_time)
    if market_dt.weekday() >= 5:
        phase = "非交易日等待"
        next_session_date = next_business_day(market_dt.date())
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
        next_session_date = next_business_day(market_dt.date())
    else:
        phase = "等待下一交易日"
        next_session_date = next_business_day(market_dt.date())
    next_session_market_dt = datetime.combine(next_session_date, preopen_start, tzinfo=ZoneInfo(config.market_timezone))
    return {
        "generated_at": utc_dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "market_status": phase,
        "market_date": market_dt.date().isoformat(),
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


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_json(path)


def process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
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
) -> dict[str, Any]:
    dashboard = read_json_if_exists(dashboard_json_path(config))
    dashboard_generated_at = dashboard.get("generated_at", "")
    dashboard_update = dashboard.get("update_status", {})
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
        "failure_state": failure_state,
        "failure_reason": failure_reason,
        "next_session_start_new_york": phase["next_session_start_new_york"],
        "next_session_start_beijing": phase["next_session_start_beijing"],
        "latest_dashboard_generated_at": dashboard_generated_at,
        "latest_dashboard_beijing_time": dashboard_update.get("beijing_time", ""),
        "latest_dashboard_runtime_status": dashboard_update.get("runtime_status", ""),
        "plain_language_result": build_plain_language_status(
            phase,
            supervisor_process_alive,
            child_running,
            child_pid,
            dashboard_generated_at,
            failure_state,
            failure_reason,
        ),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_plain_language_status(
    phase: dict[str, str],
    supervisor_process_alive: bool,
    child_running: bool,
    child_pid: int | None,
    dashboard_generated_at: str,
    failure_state: str = "",
    failure_reason: str = "",
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


def write_failure_dossier(config: SupervisorConfig, payload: dict[str, Any]) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(failure_dossier_path(config), payload)


def build_failure_payload(
    config: SupervisorConfig,
    *,
    phase: dict[str, str],
    consecutive_failures: int,
    child_last_exit_code: int | None,
) -> dict[str, Any]:
    return {
        "schema_version": "m12.47.session-failure-dossier.v1",
        "stage": config.stage,
        "generated_at": phase["generated_at"],
        "failure_reason": f"M12.37 子会话连续 {consecutive_failures} 次非零退出，已停止自动重启。",
        "consecutive_failures": consecutive_failures,
        "last_exit_code": child_last_exit_code,
        "market_status": phase["market_status"],
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
    if not process_alive(pid):
        remove_pid_file(config)
        return False
    os.kill(pid, signal.SIGTERM)
    return True


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
    stored_pid = int(stored.get("supervisor_pid") or read_existing_pid(config) or 0) if stored else (read_existing_pid(config) or 0)
    supervisor_alive = process_alive(stored_pid)
    child_pid = int(stored.get("child_pid") or 0) if stored else 0
    child_running = bool(stored.get("child_running")) and process_alive(child_pid)
    raw_exit_code = stored.get("child_last_exit_code") if stored else None
    try:
        child_last_exit_code = None if raw_exit_code in (None, "") else int(raw_exit_code)
    except (TypeError, ValueError):
        child_last_exit_code = None
    payload = build_status_payload(
        config,
        phase=build_window_state(config),
        supervisor_pid=stored_pid,
        supervisor_process_alive=supervisor_alive,
        child_pid=child_pid if child_running else None,
        child_running=child_running,
        child_started_at=stored.get("child_started_at", "") if stored else "",
        child_last_exit_code=child_last_exit_code,
        restart_count=int(stored.get("restart_count", 0)) if stored else 0,
        failure_state=stored.get("failure_state", "") if stored else "",
        failure_reason=stored.get("failure_reason", "") if stored else "",
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
