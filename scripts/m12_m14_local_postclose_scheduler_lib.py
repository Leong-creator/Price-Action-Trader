#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, time as wall_time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_m14_local_postclose_scheduler.json"
PID_FILE = "m12_m14_local_postclose_scheduler.pid"
LOG_FILE = "m12_m14_local_postclose_scheduler.log"
STATUS_FILE = "m12_m14_local_postclose_scheduler_status.json"
STATE_FILE = "m12_m14_local_postclose_scheduler_state.json"
LEDGER_FILE = "m12_m14_local_postclose_scheduler_ledger.jsonl"

BatchRunner = Callable[[Path, str | None], dict[str, Any]]
VisualShadowRunner = Callable[[Path, str, str | None], dict[str, Any]]
FormalEvidenceRunner = Callable[[Path, str | None], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class BoundaryConfig:
    paper_simulated_only: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool
    paper_trading_approval: bool


@dataclass(frozen=True, slots=True)
class LocalPostcloseSchedulerConfig:
    config_path: Path
    title: str
    run_id: str
    stage: str
    output_dir: Path
    batch_config_path: Path
    retention_config_path: Path | None
    visual_shadow_session_config_path: Path | None
    formal_test_evidence_config_path: Path | None
    check_interval_seconds: int
    market_timezone: str
    regular_close_time: str
    trigger_delay_minutes: int
    boundary: BoundaryConfig


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_scheduler_config(path: str | Path = DEFAULT_CONFIG_PATH) -> LocalPostcloseSchedulerConfig:
    config_path = resolve_repo_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    boundary = payload["boundary"]
    config = LocalPostcloseSchedulerConfig(
        config_path=config_path,
        title=str(payload["title"]),
        run_id=str(payload.get("run_id", "m12_m14_local_postclose_scheduler")),
        stage=str(payload["stage"]),
        output_dir=resolve_repo_path(payload["output_dir"]),
        batch_config_path=resolve_repo_path(payload["batch_config_path"]),
        retention_config_path=(
            resolve_repo_path(payload["retention_config_path"])
            if payload.get("retention_config_path")
            else None
        ),
        visual_shadow_session_config_path=(
            resolve_repo_path(payload["visual_shadow_session_config_path"])
            if payload.get("visual_shadow_session_config_path")
            else None
        ),
        formal_test_evidence_config_path=(
            resolve_repo_path(payload["formal_test_evidence_config_path"])
            if payload.get("formal_test_evidence_config_path")
            else None
        ),
        check_interval_seconds=int(payload["check_interval_seconds"]),
        market_timezone=str(payload["market_timezone"]),
        regular_close_time=str(payload["regular_close_time"]),
        trigger_delay_minutes=int(payload["trigger_delay_minutes"]),
        boundary=BoundaryConfig(
            paper_simulated_only=bool(boundary["paper_simulated_only"]),
            trading_connection=bool(boundary["trading_connection"]),
            real_money_actions=bool(boundary["real_money_actions"]),
            live_execution=bool(boundary["live_execution"]),
            paper_trading_approval=bool(boundary["paper_trading_approval"]),
        ),
    )
    validate_scheduler_config(config)
    return config


def validate_scheduler_config(config: LocalPostcloseSchedulerConfig) -> None:
    if config.stage != "M12-M14.local_postclose_scheduler":
        raise ValueError("Local postclose scheduler stage drift")
    if config.check_interval_seconds <= 0:
        raise ValueError("Local postclose scheduler check interval must be positive")
    if config.trigger_delay_minutes < 0:
        raise ValueError("Local postclose scheduler trigger_delay_minutes must be non-negative")
    parse_clock(config.regular_close_time)
    if not config.boundary.paper_simulated_only:
        raise ValueError("Local postclose scheduler must stay paper/simulated only")
    if (
        config.boundary.trading_connection
        or config.boundary.real_money_actions
        or config.boundary.live_execution
        or config.boundary.paper_trading_approval
    ):
        raise ValueError("Local postclose scheduler cannot enable trading or live execution")
    if not config.batch_config_path.exists():
        raise ValueError(f"Local postclose batch config missing: {config.batch_config_path}")
    batch_payload = read_json(config.batch_config_path)
    if batch_payload.get("stage") != "M12-M14.local_postclose_batch":
        raise ValueError("Local postclose batch config stage drift")
    if config.visual_shadow_session_config_path is not None:
        if not config.visual_shadow_session_config_path.exists():
            raise ValueError(
                f"Visual shadow session config missing: {config.visual_shadow_session_config_path}"
            )
        visual_payload = read_json(config.visual_shadow_session_config_path)
        if visual_payload.get("stage") != "M15.visual_strategy_shadow_session":
            raise ValueError("Visual shadow session config stage drift")
    if config.formal_test_evidence_config_path is not None:
        if not config.formal_test_evidence_config_path.exists():
            raise ValueError(
                f"Formal test evidence config missing: {config.formal_test_evidence_config_path}"
            )
        evidence_payload = read_json(config.formal_test_evidence_config_path)
        if evidence_payload.get("stage") != "M15.formal_test_evidence":
            raise ValueError("Formal test evidence config stage drift")


def parse_clock(value: str) -> wall_time:
    hour, minute = value.split(":")
    return wall_time(hour=int(hour), minute=int(minute))


def scheduler_pid_path(config: LocalPostcloseSchedulerConfig) -> Path:
    return config.output_dir / PID_FILE


def scheduler_log_path(config: LocalPostcloseSchedulerConfig) -> Path:
    return config.output_dir / LOG_FILE


def scheduler_status_path(config: LocalPostcloseSchedulerConfig) -> Path:
    return config.output_dir / STATUS_FILE


def scheduler_state_path(config: LocalPostcloseSchedulerConfig) -> Path:
    return config.output_dir / STATE_FILE


def scheduler_ledger_path(config: LocalPostcloseSchedulerConfig) -> Path:
    return config.output_dir / LEDGER_FILE


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def current_market_dt(config: LocalPostcloseSchedulerConfig, generated_at: str | None = None) -> tuple[datetime, datetime]:
    utc_dt = datetime.fromisoformat((generated_at or now_utc_iso()).replace("Z", "+00:00"))
    return utc_dt, utc_dt.astimezone(ZoneInfo(config.market_timezone))


def scheduler_window(config: LocalPostcloseSchedulerConfig, generated_at: str | None = None) -> dict[str, Any]:
    utc_dt, market_dt = current_market_dt(config, generated_at)
    trigger_dt = datetime.combine(
        market_dt.date(),
        parse_clock(config.regular_close_time),
        tzinfo=ZoneInfo(config.market_timezone),
    ) + timedelta(minutes=config.trigger_delay_minutes)
    is_weekday = market_dt.weekday() < 5
    eligible = is_weekday and market_dt >= trigger_dt
    reason = "eligible" if eligible else ("weekend" if not is_weekday else "before_trigger_window")
    return {
        "generated_at": utc_dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "new_york_time": market_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "business_date": market_dt.date().isoformat(),
        "weekday_index": market_dt.weekday(),
        "trigger_at_new_york": trigger_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "eligible_now": eligible,
        "reason": reason,
    }


def default_batch_runner(batch_config_path: Path, generated_at: str | None) -> dict[str, Any]:
    config = load_batch_config(batch_config_path)
    return run_local_postclose_batch(config, generated_at=generated_at)


def default_visual_shadow_runner(
    visual_config_path: Path,
    business_date: str,
    generated_at: str | None,
) -> dict[str, Any]:
    from scripts.m15_visual_strategy_shadow_session_lib import load_config as load_visual_config
    from scripts.m15_visual_strategy_shadow_session_lib import run_visual_shadow_session

    return run_visual_shadow_session(
        load_visual_config(visual_config_path),
        business_date=business_date,
        generated_at=generated_at,
    )


def default_formal_evidence_runner(
    evidence_config_path: Path,
    generated_at: str | None,
) -> dict[str, Any]:
    from scripts.m15_formal_test_evidence_lib import generate_formal_test_evidence
    from scripts.m15_formal_test_evidence_lib import load_config as load_evidence_config

    return generate_formal_test_evidence(
        load_evidence_config(evidence_config_path),
        generated_at=generated_at,
    )


def build_state_after_trigger(
    previous: dict[str, Any],
    *,
    business_date: str,
    generated_at: str,
    outcome: str,
    error_message: str = "",
    batch_summary_ref: str = "",
) -> dict[str, Any]:
    state = dict(previous)
    state.update(
        {
            "schema_version": "m12-m14.local-postclose-scheduler-state.v1",
            "last_triggered_business_date": business_date,
            "last_triggered_at": generated_at,
            "last_outcome": outcome,
            "last_error": error_message,
            "last_batch_summary_ref": batch_summary_ref,
        }
    )
    return state


def run_scheduler_once(
    config: LocalPostcloseSchedulerConfig,
    *,
    generated_at: str | None = None,
    batch_runner: BatchRunner | None = None,
    visual_shadow_runner: VisualShadowRunner | None = None,
    formal_evidence_runner: FormalEvidenceRunner | None = None,
) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or now_utc_iso()
    window = scheduler_window(config, generated_at)
    previous_state = read_json(scheduler_state_path(config))
    last_triggered_business_date = str(previous_state.get("last_triggered_business_date") or "")
    payload: dict[str, Any] = {
        "schema_version": "m12-m14.local-postclose-scheduler-status.v1",
        "title": config.title,
        "run_id": config.run_id,
        "stage": config.stage,
        "generated_at": generated_at,
        "window": window,
        "batch_config_path": project_path(config.batch_config_path),
        "visual_shadow_session_config_path": (
            project_path(config.visual_shadow_session_config_path)
            if config.visual_shadow_session_config_path is not None
            else ""
        ),
        "formal_test_evidence_config_path": (
            project_path(config.formal_test_evidence_config_path)
            if config.formal_test_evidence_config_path is not None
            else ""
        ),
        "state_file": project_path(scheduler_state_path(config)),
        "pid_file": project_path(scheduler_pid_path(config)),
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "m15_isolation": {
            "failure_blocks_m15": False,
            "starts_or_stops_m15": False,
        },
        "last_triggered_business_date": last_triggered_business_date,
    }
    if not bool(window["eligible_now"]):
        payload.update(
            {
                "scheduler_status": "waiting_for_window",
                "triggered": False,
                "skip_reason": str(window["reason"]),
                "plain_language_result": "当前未到纽约工作日盘后触发窗口；本轮不运行本地盘后 batch。",
            }
        )
        write_json(scheduler_status_path(config), payload)
        append_jsonl(scheduler_ledger_path(config), payload)
        return payload
    business_date = str(window["business_date"])
    if last_triggered_business_date == business_date:
        payload.update(
            {
                "scheduler_status": "already_triggered_today",
                "triggered": False,
                "skip_reason": "already_triggered_today",
                "plain_language_result": "今日纽约盘后 batch 已触发过；本轮保持幂等，不重复运行。",
                "last_outcome": str(previous_state.get("last_outcome") or ""),
                "last_error": str(previous_state.get("last_error") or ""),
                "last_batch_summary_ref": str(previous_state.get("last_batch_summary_ref") or ""),
            }
        )
        write_json(scheduler_status_path(config), payload)
        append_jsonl(scheduler_ledger_path(config), payload)
        return payload

    runner = batch_runner or default_batch_runner
    visual_runner = visual_shadow_runner or default_visual_shadow_runner
    evidence_runner = formal_evidence_runner or default_formal_evidence_runner
    visual_result: dict[str, Any] = {}
    visual_error = ""
    evidence_result: dict[str, Any] = {}
    evidence_error = ""
    try:
        batch_result = runner(config.batch_config_path, generated_at)
        if runner is default_batch_runner and config.retention_config_path is not None:
            from scripts.m15_artifact_retention_lib import load_config as load_retention_config
            from scripts.m15_artifact_retention_lib import run_artifact_retention

            batch_result["artifact_retention"] = run_artifact_retention(
                load_retention_config(config.retention_config_path),
                execute=True,
                generated_at=generated_at,
            )
        if config.visual_shadow_session_config_path is not None:
            try:
                visual_result = visual_runner(
                    config.visual_shadow_session_config_path,
                    business_date,
                    generated_at,
                )
            except Exception as exc:
                visual_error = f"{type(exc).__name__}: {exc}"
        if config.formal_test_evidence_config_path is not None:
            try:
                evidence_result = evidence_runner(
                    config.formal_test_evidence_config_path,
                    generated_at,
                )
            except Exception as exc:
                evidence_error = f"{type(exc).__name__}: {exc}"
        batch_summary = batch_result.get("summary", {}) if isinstance(batch_result, dict) else {}
        batch_summary_ref = ""
        if isinstance(batch_summary, dict):
            batch_summary_ref = str(batch_summary.get("summary_path_ref") or "")
        state = build_state_after_trigger(
            previous_state,
            business_date=business_date,
            generated_at=generated_at,
            outcome="success",
            batch_summary_ref=batch_summary_ref,
        )
        write_json(scheduler_state_path(config), state)
        payload.update(
            {
                "scheduler_status": "triggered_successfully",
                "triggered": True,
                "batch_status": "success",
                "batch_result": batch_result,
                "visual_shadow_session": visual_result,
                "visual_shadow_status": (
                    str(visual_result.get("status") or "not_configured")
                    if not visual_error
                    else "failed"
                ),
                "visual_shadow_error": visual_error,
                "formal_test_evidence": evidence_result,
                "formal_test_evidence_status": (
                    str((evidence_result.get("layers") or {}).get("market_session", {}).get("status") or "not_configured")
                    if not evidence_error
                    else "failed"
                ),
                "formal_test_evidence_error": evidence_error,
                "plain_language_result": "已在纽约盘后窗口触发本地研究与修复系统；重试次数由盘后批处理内部控制。",
            }
        )
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        if config.visual_shadow_session_config_path is not None:
            try:
                visual_result = visual_runner(
                    config.visual_shadow_session_config_path,
                    business_date,
                    generated_at,
                )
            except Exception as visual_exc:
                visual_error = f"{type(visual_exc).__name__}: {visual_exc}"
        if config.formal_test_evidence_config_path is not None:
            try:
                evidence_result = evidence_runner(
                    config.formal_test_evidence_config_path,
                    generated_at,
                )
            except Exception as evidence_exc:
                evidence_error = f"{type(evidence_exc).__name__}: {evidence_exc}"
        state = build_state_after_trigger(
            previous_state,
            business_date=business_date,
            generated_at=generated_at,
            outcome="failed",
            error_message=error_message,
        )
        write_json(scheduler_state_path(config), state)
        payload.update(
            {
                "scheduler_status": "triggered_with_batch_failure",
                "triggered": True,
                "batch_status": "failed",
                "error_type": type(exc).__name__,
                "error_message": error_message,
                "visual_shadow_session": visual_result,
                "visual_shadow_status": (
                    str(visual_result.get("status") or "not_configured")
                    if not visual_error
                    else "failed"
                ),
                "visual_shadow_error": visual_error,
                "formal_test_evidence": evidence_result,
                "formal_test_evidence_status": (
                    str((evidence_result.get("layers") or {}).get("market_session", {}).get("status") or "not_configured")
                    if not evidence_error
                    else "failed"
                ),
                "formal_test_evidence_error": evidence_error,
                "plain_language_result": "本地盘后 batch 已触发但执行失败；失败不会阻断 M15，且今日不再重复触发。",
            }
        )
    write_json(scheduler_status_path(config), payload)
    append_jsonl(scheduler_ledger_path(config), payload)
    return payload


def run_scheduler_subprocess_once(
    config: LocalPostcloseSchedulerConfig,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Run one heavy post-close cycle outside the long-lived scheduler.

    The local batch imports and retains sizeable market/replay modules. Running
    the complete cycle in a disposable process prevents those allocations from
    becoming the scheduler daemon's permanent resident set.
    """
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_m12_m14_local_postclose_scheduler.py"),
        "--config",
        str(config.config_path),
    ]
    if generated_at:
        command.extend(["--generated-at", generated_at])
    with scheduler_log_path(config).open("a", encoding="utf-8") as log_handle:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            stdout=log_handle,
            stderr=log_handle,
            check=False,
        )
    payload = read_json(scheduler_status_path(config))
    if payload:
        payload["scheduler_child_exit_code"] = result.returncode
        return payload
    return {
        "scheduler_status": "subprocess_failed_without_status",
        "triggered": True,
        "batch_status": "failed",
        "error_message": (
            "local postclose child exited without a status artifact:"
            f"{result.returncode}"
        ),
        "scheduler_child_exit_code": result.returncode,
        "plain_language_result": "本地盘后子进程退出且没有生成状态产物；该故障不影响 M15。",
    }


def scheduler_tick(
    config: LocalPostcloseSchedulerConfig,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Keep waiting/idempotence checks light; isolate only an eligible run."""
    generated_at = generated_at or now_utc_iso()
    window = scheduler_window(config, generated_at)
    state = read_json(scheduler_state_path(config))
    already_triggered = (
        str(state.get("last_triggered_business_date") or "")
        == str(window.get("business_date") or "")
    )
    if bool(window.get("eligible_now")) and not already_triggered:
        return run_scheduler_subprocess_once(config, generated_at=generated_at)
    return run_scheduler_once(config, generated_at=generated_at)


def watch_loop(config: LocalPostcloseSchedulerConfig) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pid_file = scheduler_pid_path(config)
    pid_file.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    try:
        while True:
            payload = scheduler_tick(config)
            print(project_path(scheduler_status_path(config)), flush=True)
            print(payload.get("plain_language_result", ""), flush=True)
            time.sleep(config.check_interval_seconds)
    finally:
        try:
            if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                pid_file.unlink()
        except OSError:
            pass


def start_daemon(config_path: str | Path, config: LocalPostcloseSchedulerConfig) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pid_file = scheduler_pid_path(config)
    existing_pid = read_pid(pid_file)
    if existing_pid and process_alive(existing_pid):
        print(f"本地盘后调度器已在运行，PID={existing_pid}")
        return 0
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_m12_m14_local_postclose_scheduler.py"),
        "--watch",
        "--config",
        str(config_path),
    ]
    with scheduler_log_path(config).open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    pid_file.write_text(str(process.pid) + "\n", encoding="utf-8")
    print(f"本地盘后调度器已启动，PID={process.pid}")
    return 0


def stop_daemon(config: LocalPostcloseSchedulerConfig) -> int:
    pid_file = scheduler_pid_path(config)
    existing_pid = read_pid(pid_file)
    if not existing_pid:
        print("本地盘后调度器没有 PID 文件。")
        return 0
    if not process_alive(existing_pid):
        pid_file.unlink(missing_ok=True)
        print("本地盘后调度器已不在运行，PID 文件已清理。")
        return 0
    os.kill(existing_pid, signal.SIGTERM)
    time.sleep(0.5)
    if process_alive(existing_pid):
        print(f"本地盘后调度器仍在运行，PID={existing_pid}")
        return 1
    pid_file.unlink(missing_ok=True)
    print(f"本地盘后调度器已停止，PID={existing_pid}")
    return 0


def status(config: LocalPostcloseSchedulerConfig, *, generated_at: str | None = None) -> dict[str, Any]:
    existing_pid = read_pid(scheduler_pid_path(config))
    alive = bool(existing_pid and process_alive(existing_pid))
    payload = read_json(scheduler_status_path(config))
    current_window = scheduler_window(config, generated_at)
    reported_status = str(payload.get("scheduler_status") or "missing")
    reported_result = str(payload.get("plain_language_result") or "尚未生成本地盘后调度状态。")
    if not alive:
        reported_status = "stopped"
        reported_result = "本地盘后调度器未运行；历史状态仅供参考。"
    return {
        "pid": existing_pid or "",
        "process_alive": alive,
        "scheduler_status": reported_status,
        "generated_at": str(payload.get("generated_at") or ""),
        "plain_language_result": reported_result,
        "current_window": current_window,
        "last_triggered_business_date": str(payload.get("last_triggered_business_date") or ""),
        "m15_isolation": {
            "failure_blocks_m15": False,
            "starts_or_stops_m15": False,
        },
    }


def load_batch_config(path: str | Path) -> Any:
    from scripts.m12_m14_local_postclose_batch_lib import load_local_postclose_batch_config

    return load_local_postclose_batch_config(path)


def run_local_postclose_batch(config: Any, *, generated_at: str | None = None) -> dict[str, Any]:
    from scripts.m12_m14_local_postclose_batch_lib import run_local_postclose_batch as _run_local_postclose_batch

    return _run_local_postclose_batch(config, generated_at=generated_at)
