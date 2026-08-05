#!/usr/bin/env python3
from __future__ import annotations

import json
import fcntl
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAILY_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
)
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_background_watchdog"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_background_watchdog.json"
SUMMARY_JSON = "m15_background_watchdog_status.json"
REPORT_MD = "m15_background_watchdog_status.md"
LEDGER_JSONL = "m15_background_watchdog_ledger.jsonl"
PID_FILE = "m15_background_watchdog.pid"
LOG_FILE = "m15_background_watchdog.log"
START_LOCK_FILE = "m15_background_watchdog.start.lock"
RUN_LOCK_FILE = "m15_background_watchdog.run.lock"
HEALTH_LEDGER_INTERVAL_SECONDS = 300

CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class BackgroundWatchdogConfig:
    stage: str
    output_dir: Path
    check_interval_seconds: int
    command_timeout_seconds: int
    analytics_refresh_interval_seconds: int
    analytics_command_timeout_seconds: int
    runtime_recovery_grace_seconds: int
    m15_realtime_supervisor_config_path: Path
    m15_runtime_engine: str
    m15_sdk_runtime_config_path: Path
    m15_dashboard_config_path: Path
    m15_account_state_config_path: Path
    readiness_config_path: Path
    monday_acceptance_config_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> BackgroundWatchdogConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {}) if isinstance(payload.get("inputs"), dict) else {}
    outputs = payload.get("outputs", {}) if isinstance(payload.get("outputs"), dict) else {}
    watchdog = payload.get("watchdog", {}) if isinstance(payload.get("watchdog"), dict) else {}
    config = BackgroundWatchdogConfig(
        stage=str(payload.get("stage", "M15.background_watchdog")),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        check_interval_seconds=int(watchdog.get("check_interval_seconds", 60)),
        command_timeout_seconds=int(watchdog.get("command_timeout_seconds", 30)),
        analytics_refresh_interval_seconds=int(watchdog.get("analytics_refresh_interval_seconds", 300)),
        analytics_command_timeout_seconds=int(watchdog.get("analytics_command_timeout_seconds", 90)),
        runtime_recovery_grace_seconds=int(watchdog.get("runtime_recovery_grace_seconds", 20)),
        m15_realtime_supervisor_config_path=resolve_repo_path(
            inputs.get(
                "m15_realtime_supervisor_config",
                ROOT / "config" / "examples" / "m15_longbridge_realtime_session_supervisor.paper_orders_enabled.json",
            )
        ),
        m15_runtime_engine=str(inputs.get("m15_runtime_engine", "cli")).strip().lower(),
        m15_sdk_runtime_config_path=resolve_repo_path(
            inputs.get("m15_sdk_runtime_config", ROOT / "config" / "examples" / "m15_longbridge_sdk_runtime.json")
        ),
        m15_dashboard_config_path=resolve_repo_path(
            inputs.get("m15_dashboard_config", "config/examples/m15_longbridge_dashboard.json")
        ),
        m15_account_state_config_path=resolve_repo_path(
            inputs.get(
                "m15_account_state_config",
                ROOT / "config" / "examples" / "m15_longbridge_realtime_account_state.json",
            )
        ),
        readiness_config_path=resolve_repo_path(
            inputs.get("readiness_config", ROOT / "config" / "examples" / "m15_opening_trade_readiness.json")
        ),
        monday_acceptance_config_path=resolve_repo_path(
            inputs.get(
                "monday_acceptance_config",
                ROOT / "config" / "examples" / "m15_monday_refresh_acceptance.json",
            )
        ),
        hard_boundaries={str(k): bool(v) for k, v in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: BackgroundWatchdogConfig) -> None:
    if config.stage != "M15.background_watchdog":
        raise ValueError("M15 background watchdog stage drift")
    if config.check_interval_seconds <= 0:
        raise ValueError("M15 background watchdog check interval must be positive")
    if config.command_timeout_seconds <= 0:
        raise ValueError("M15 background watchdog command timeout must be positive")
    if config.analytics_refresh_interval_seconds <= 0:
        raise ValueError("M15 background watchdog analytics refresh interval must be positive")
    if config.analytics_command_timeout_seconds <= 0:
        raise ValueError("M15 background watchdog analytics command timeout must be positive")
    if config.runtime_recovery_grace_seconds < 0:
        raise ValueError("M15 background watchdog runtime recovery grace cannot be negative")
    if config.m15_runtime_engine not in {"cli", "sdk"}:
        raise ValueError("M15 background watchdog runtime engine must be cli or sdk")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 background watchdog must stay paper/simulated only")
    for key in ("live_execution", "real_money_actions", "manual_m12_37_once", "margin_financing"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M15 background watchdog cannot enable {key}")


def run_background_watchdog_once(
    config: BackgroundWatchdogConfig | None = None,
    *,
    generated_at: str | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or now_utc_iso()
    runner = command_runner or run_command
    previous = read_json(config.output_dir / SUMMARY_JSON)
    analytics_step = analytics_refresh_step(config, runner, generated_at, previous=previous)
    steps = [
        m15_runtime_daemon_step(config, runner),
        m15_runtime_status_step(config, runner),
        analytics_step,
        pa002_milestone_refresh_step(
            config,
            runner,
            generated_at,
            previous=previous,
            analytics_step=analytics_step,
        ),
        run_step(
            "m15_longbridge_dashboard",
            "M15 独立长桥看板刷新",
            [
                sys.executable,
                "scripts/run_m15_longbridge_dashboard.py",
                "--config",
                project_path(config.m15_dashboard_config_path),
            ],
            config,
            runner,
        ),
        run_step(
            "m15_opening_readiness",
            "M15 开盘值守验收",
            [
                sys.executable,
                "scripts/run_m15_opening_trade_readiness.py",
                "--config",
                project_path(config.readiness_config_path),
            ],
            config,
            runner,
        ),
        run_step(
            "m15_monday_acceptance",
            "M15 SDK 周一综合验收",
            [
                sys.executable,
                "scripts/run_m15_monday_refresh_acceptance.py",
                "--config",
                project_path(config.monday_acceptance_config_path),
            ],
            config,
            runner,
        ),
    ]
    failed_steps = [step for step in steps if step["returncode"] != 0]
    payload = {
        "schema_version": "m15.background-watchdog.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "watchdog_status": "healthy" if not failed_steps else "needs_attention",
        "step_count": len(steps),
        "failed_step_count": len(failed_steps),
        "steps": steps,
        "next_check_interval_seconds": config.check_interval_seconds,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "manual_m12_37_once_used": False,
        "local_research_non_blocking": {
            "m12_47_managed_elsewhere": True,
        },
        "plain_language_result": plain_language_result(failed_steps, config.m15_runtime_engine),
        "refs": {
            "m15_realtime_supervisor_config": project_path(config.m15_realtime_supervisor_config_path),
            "m15_runtime_engine": config.m15_runtime_engine,
            "m15_sdk_runtime_config": project_path(config.m15_sdk_runtime_config_path),
            "m15_account_state_config": project_path(config.m15_account_state_config_path),
            "readiness_config": project_path(config.readiness_config_path),
            "monday_acceptance_config": project_path(config.monday_acceptance_config_path),
        },
    }
    append_ledger = should_append_watchdog_ledger(previous, payload)
    payload["last_ledger_at"] = generated_at if append_ledger else str(
        previous.get("last_ledger_at") or previous.get("generated_at") or ""
    )
    write_json(config.output_dir / SUMMARY_JSON, payload)
    if append_ledger:
        append_jsonl(config.output_dir / LEDGER_JSONL, [payload])
    (config.output_dir / REPORT_MD).write_text(render_markdown(payload), encoding="utf-8")
    return payload


def run_step(
    step_id: str,
    label: str,
    command: list[str],
    config: BackgroundWatchdogConfig,
    runner: CommandRunner,
    *,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    assert_safe_watchdog_command(command)
    effective_timeout = timeout_seconds or config.command_timeout_seconds
    started = time.perf_counter()
    try:
        completed = runner(command, effective_timeout)
        returncode = int(completed.returncode)
        stdout = str(completed.stdout or "")
        stderr = str(completed.stderr or "")
        semantic_failure = semantic_watchdog_failure(step_id, stdout) if returncode == 0 else ""
        if semantic_failure:
            returncode = 3
            stderr = semantic_failure
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = str(exc.stdout or "")
        stderr = f"timeout after {effective_timeout}s"
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "step_id": step_id,
        "label": label,
        "returncode": returncode,
        "elapsed_ms": elapsed_ms,
        "command": printable_command(command),
        "stdout_tail": clean_text(stdout)[-800:],
        "stderr_tail": clean_text(stderr)[-800:],
    }


def semantic_watchdog_failure(step_id: str, stdout: str) -> str:
    """Treat blocked JSON results as failures even when the CLI exits zero."""
    try:
        payload = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    if step_id == "m15_sdk_runtime_status":
        if payload.get("runtime_process_alive") is not True:
            return "sdk_runtime_process_not_alive"
        if payload.get("status") != "running" or payload.get("sdk_connected") is not True:
            return f"sdk_runtime_not_ready:{payload.get('status') or 'unknown'}"
        if payload.get("account_snapshot_healthy") is not True:
            return "sdk_account_snapshot_not_healthy"
    if step_id == "m15_opening_readiness":
        status_value = str(payload.get("readiness_status") or "")
        if status_value.startswith("blocked"):
            return f"opening_readiness_blocked:{status_value}"
    if step_id == "m15_monday_acceptance":
        status_value = str(payload.get("acceptance_status") or "")
        if status_value.startswith("blocked"):
            return f"monday_acceptance_blocked:{status_value}"
    return ""


def m15_runtime_daemon_step(config: BackgroundWatchdogConfig, runner: CommandRunner) -> dict[str, Any]:
    if config.m15_runtime_engine == "sdk":
        return run_step(
            "m15_sdk_runtime_daemon",
            "M15 长桥 SDK 实时运行层自愈拉起",
            [
                sys.executable,
                "scripts/run_m15_longbridge_sdk_runtime.py",
                "--daemon",
                "--dispatch",
                "--config",
                project_path(config.m15_sdk_runtime_config_path),
            ],
            config,
            runner,
        )
    return run_step(
        "m15_realtime_daemon",
        "M15 长桥实时守护器自愈拉起",
        [
            sys.executable,
            "scripts/run_m15_longbridge_realtime_session_supervisor.py",
            "--daemon",
            "--replace-config-drift",
            "--config",
            project_path(config.m15_realtime_supervisor_config_path),
        ],
        config,
        runner,
    )


def m15_runtime_status_step(
    config: BackgroundWatchdogConfig,
    runner: CommandRunner,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if config.m15_runtime_engine == "sdk":
        command = [
            sys.executable,
            "scripts/run_m15_longbridge_sdk_runtime.py",
            "--status",
            "--config",
            project_path(config.m15_sdk_runtime_config_path),
        ]
        started_at = monotonic()
        attempts = 0
        while True:
            step = run_step(
                "m15_sdk_runtime_status",
                "M15 长桥 SDK 实时运行层状态",
                command,
                config,
                runner,
            )
            attempts += 1
            if not sdk_runtime_step_is_transient_recovery(step):
                step["recovery_check_attempts"] = attempts
                step["recovered_within_grace"] = attempts > 1 and step["returncode"] == 0
                return step
            elapsed = monotonic() - started_at
            if elapsed >= config.runtime_recovery_grace_seconds:
                step["recovery_check_attempts"] = attempts
                step["recovered_within_grace"] = False
                step["recovery_grace_exhausted"] = True
                return step
            sleep(min(1.0, config.runtime_recovery_grace_seconds - elapsed))
    return run_step(
        "m15_realtime_status",
        "M15 长桥实时守护器状态",
        [
            sys.executable,
            "scripts/run_m15_longbridge_realtime_session_supervisor.py",
            "--status",
            "--config",
            project_path(config.m15_realtime_supervisor_config_path),
        ],
        config,
        runner,
    )


def sdk_runtime_step_is_transient_recovery(step: dict[str, Any]) -> bool:
    if int(step.get("returncode", 0) or 0) != 3:
        return False
    reason = str(step.get("stderr_tail") or "")
    return reason.startswith("sdk_runtime_not_ready:") and reason.split(":", 1)[1] in {
        "starting",
        "starting_context_restore",
        "connecting",
        "reconnecting_market_data_circuit",
    }


def assert_safe_watchdog_command(command: list[str]) -> None:
    joined = " ".join(command)
    forbidden = (
        "run_m12_37_intraday_auto_loop.py --once",
        "--no-fetch",
        "--no-refresh-quotes",
        " order buy ",
        " order sell ",
        " order cancel ",
        " order replace ",
    )
    if any(token in joined for token in forbidden):
        raise ValueError(f"unsafe watchdog command blocked: {joined}")
    allowed_scripts = {
        "scripts/run_m15_longbridge_realtime_session_supervisor.py",
        "scripts/run_m15_longbridge_realtime_account_state.py",
        "scripts/run_m15_opening_trade_readiness.py",
        "scripts/run_m15_longbridge_sdk_runtime.py",
        "scripts/run_m15_longbridge_sdk_analytics.py",
        "scripts/run_m15_longbridge_dashboard.py",
        "scripts/run_m15_monday_refresh_acceptance.py",
        "scripts/run_m15_pa002_dual_version_milestone.py",
    }
    script_tokens = [token for token in command if token.startswith("scripts/")]
    if not script_tokens or script_tokens[0] not in allowed_scripts:
        raise ValueError(f"watchdog command is not allowed: {joined}")


def printable_command(command: list[str]) -> str:
    return " ".join(command)


def clean_text(value: str) -> str:
    return value.replace("\r", "").strip()


def plain_language_result(failed_steps: list[dict[str, Any]], runtime_engine: str) -> str:
    runtime_label = "M15 SDK 实时运行层" if runtime_engine == "sdk" else "M15 实时守护器"
    if not failed_steps:
        return f"后台看护已完成：{runtime_label}、账户快照慢路径和开盘验收已检查；M12.47 仅保留本地 research 状态，不作为看护前置。"
    failed_labels = "、".join(str(step["label"]) for step in failed_steps)
    return f"后台看护发现异常：{failed_labels} 未通过；不会手动跑 M12.37 once，也不会直接提交订单。"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# M15 后台看护状态",
        "",
        f"- 状态: `{payload['watchdog_status']}`",
        f"- 生成时间: `{payload['generated_at']}`",
        f"- 结果: {payload['plain_language_result']}",
        f"- 下一次检查间隔: `{payload['next_check_interval_seconds']}` 秒",
        "",
        "| 步骤 | 状态 | 耗时(ms) | 摘要 |",
        "|---|---:|---:|---|",
    ]
    for step in payload.get("steps", []):
        summary = markdown_table_cell(str(step.get("stdout_tail") or step.get("stderr_tail") or ""))[:120]
        lines.append(
            f"| {markdown_table_cell(str(step.get('label', '')))} | {step.get('returncode', '')} | "
            f"{step.get('elapsed_ms', '')} | {summary} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 只维护 M15 运行层与 readiness；M12.47 仅作本地 research 非阻断信息。",
            "- 只通过只读账户脚本做慢路径 analytics 刷新。",
            "- 不手动运行 M12.37 once。",
            "- 不提交、撤销或修改订单。",
            "- 仍只限长桥模拟账户。",
        ]
    )
    return "\n".join(lines) + "\n"


def markdown_table_cell(value: str) -> str:
    return clean_text(value).replace("|", "\\|").replace("\n", "<br>")


def run_command(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )


def analytics_refresh_step(
    config: BackgroundWatchdogConfig,
    runner: CommandRunner,
    generated_at: str,
    *,
    previous: dict[str, Any],
) -> dict[str, Any]:
    previous_success_at = latest_step_generated_at(previous, "m15_account_state_full_refresh")
    if not analytics_refresh_due(generated_at, previous_success_at, config.analytics_refresh_interval_seconds):
        return {
            "step_id": "m15_account_state_full_refresh",
            "label": "M15 只读账户慢路径 analytics 刷新",
            "returncode": 0,
            "elapsed_ms": 0,
            "command": "",
            "stdout_tail": f"skipped_until_due interval={config.analytics_refresh_interval_seconds}s",
            "stderr_tail": "",
            "skipped_due_to_throttle": True,
            "last_success_generated_at": previous_success_at,
        }
    if config.m15_runtime_engine == "sdk":
        command = [
            sys.executable,
            "scripts/run_m15_longbridge_sdk_analytics.py",
            "--sdk-config",
            project_path(config.m15_sdk_runtime_config_path),
            "--account-config",
            project_path(config.m15_account_state_config_path),
            "--generated-at",
            generated_at,
        ]
        label = "M15 SDK 只读账户慢路径 analytics 刷新"
    else:
        command = [
            sys.executable,
            "scripts/run_m15_longbridge_realtime_account_state.py",
            "--config",
            project_path(config.m15_account_state_config_path),
            "--generated-at",
            generated_at,
        ]
        label = "M15 只读账户慢路径 analytics 刷新"
    step = run_step(
        "m15_account_state_full_refresh",
        label,
        command,
        config,
        runner,
        timeout_seconds=config.analytics_command_timeout_seconds,
    )
    step["skipped_due_to_throttle"] = False
    step["last_success_generated_at"] = (
        generated_at if int(step.get("returncode", 1)) == 0 else previous_success_at
    )
    return step


def analytics_refresh_due(generated_at: str, previous_success_at: str, interval_seconds: int) -> bool:
    if not previous_success_at:
        return True
    try:
        current = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        previous = datetime.fromisoformat(previous_success_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (current - previous).total_seconds() >= interval_seconds


def pa002_milestone_refresh_step(
    config: BackgroundWatchdogConfig,
    runner: CommandRunner,
    generated_at: str,
    *,
    previous: dict[str, Any],
    analytics_step: dict[str, Any],
) -> dict[str, Any]:
    previous_success_at = latest_step_generated_at(previous, "m15_pa002_dual_version_milestone")
    if analytics_step.get("skipped_due_to_throttle") is True:
        return {
            "step_id": "m15_pa002_dual_version_milestone",
            "label": "PA002 双版本盘后里程碑评估",
            "returncode": 0,
            "elapsed_ms": 0,
            "command": "",
            "stdout_tail": f"skipped_until_due interval={config.analytics_refresh_interval_seconds}s",
            "stderr_tail": "",
            "skipped_due_to_throttle": True,
            "last_success_generated_at": previous_success_at,
        }
    if int(analytics_step.get("returncode", 1)) != 0:
        return {
            "step_id": "m15_pa002_dual_version_milestone",
            "label": "PA002 双版本盘后里程碑评估",
            "returncode": 0,
            "elapsed_ms": 0,
            "command": "",
            "stdout_tail": "skipped_because_fill_attribution_refresh_failed",
            "stderr_tail": "",
            "skipped_due_to_throttle": False,
            "skipped_due_to_analytics_failure": True,
            "last_success_generated_at": previous_success_at,
        }
    step = run_step(
        "m15_pa002_dual_version_milestone",
        "PA002 双版本盘后里程碑评估",
        [
            sys.executable,
            "scripts/run_m15_pa002_dual_version_milestone.py",
            "--account-config",
            project_path(config.m15_account_state_config_path),
            "--generated-at",
            generated_at,
        ],
        config,
        runner,
    )
    step["skipped_due_to_throttle"] = False
    step["skipped_due_to_analytics_failure"] = False
    step["last_success_generated_at"] = generated_at if step.get("returncode") == 0 else previous_success_at
    return step


def latest_step_generated_at(payload: dict[str, Any], step_id: str) -> str:
    if not isinstance(payload.get("steps"), list):
        return ""
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        if step.get("step_id") != step_id:
            continue
        persisted = str(step.get("last_success_generated_at") or "")
        if persisted:
            return persisted
        if int(step.get("returncode", 1)) == 0 and not step.get("skipped_due_to_throttle"):
            return str(payload.get("generated_at") or "")
    return ""


def watch_loop(config: BackgroundWatchdogConfig) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pid_file = config.output_dir / PID_FILE
    run_lock = (config.output_dir / RUN_LOCK_FILE).open("a+", encoding="utf-8")
    try:
        fcntl.flock(run_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        run_lock.seek(0)
        owner_pid = parse_pid(run_lock.read())
        if owner_pid and process_alive(owner_pid):
            pid_file.write_text(str(owner_pid) + "\n", encoding="utf-8")
        run_lock.close()
        print(f"M15 后台看护器已有实例持有运行锁，PID={owner_pid or 'unknown'}；本进程退出。", flush=True)
        return 0
    run_lock.seek(0)
    run_lock.truncate()
    run_lock.write(str(os.getpid()) + "\n")
    run_lock.flush()
    pid_file.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    try:
        while True:
            payload = run_background_watchdog_once(config)
            print(config.output_dir / SUMMARY_JSON, flush=True)
            print(payload.get("plain_language_result", ""), flush=True)
            time.sleep(config.check_interval_seconds)
    finally:
        try:
            if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                pid_file.unlink()
        except OSError:
            pass
        fcntl.flock(run_lock.fileno(), fcntl.LOCK_UN)
        run_lock.close()


def start_daemon(config_path: str | Path, config: BackgroundWatchdogConfig) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    with (config.output_dir / START_LOCK_FILE).open("a+", encoding="utf-8") as start_lock:
        fcntl.flock(start_lock.fileno(), fcntl.LOCK_EX)
        pid_file = config.output_dir / PID_FILE
        existing_pid = read_pid(pid_file)
        if existing_pid and process_alive(existing_pid):
            print(f"M15 后台看护器已在运行，PID={existing_pid}")
            return 0
        lock_owner_pid = read_pid(config.output_dir / RUN_LOCK_FILE)
        if lock_owner_pid and process_alive(lock_owner_pid):
            pid_file.write_text(str(lock_owner_pid) + "\n", encoding="utf-8")
            print(f"M15 后台看护器已在运行，PID={lock_owner_pid}")
            return 0
        command = [
            sys.executable,
            str(ROOT / "scripts" / "run_m15_background_watchdog.py"),
            "--watch",
            "--config",
            str(config_path),
        ]
        with (config.output_dir / LOG_FILE).open("a", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
            )
        pid_file.write_text(str(process.pid) + "\n", encoding="utf-8")
        print(f"M15 后台看护器已启动，PID={process.pid}")
    return 0


def should_append_watchdog_ledger(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if not previous:
        return True
    if previous.get("watchdog_status") != current.get("watchdog_status"):
        return True
    previous_failed = sorted(
        str(step.get("step_id") or "")
        for step in previous.get("steps", [])
        if isinstance(step, dict) and int(step.get("returncode", 0) or 0) != 0
    )
    current_failed = sorted(
        str(step.get("step_id") or "")
        for step in current.get("steps", [])
        if isinstance(step, dict) and int(step.get("returncode", 0) or 0) != 0
    )
    if previous_failed != current_failed:
        return True
    try:
        previous_at = datetime.fromisoformat(
            str(previous.get("last_ledger_at") or previous.get("generated_at") or "").replace("Z", "+00:00")
        )
        current_at = datetime.fromisoformat(str(current.get("generated_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return True
    return (current_at - previous_at).total_seconds() >= HEALTH_LEDGER_INTERVAL_SECONDS


def stop_daemon(config: BackgroundWatchdogConfig) -> int:
    pid_file = config.output_dir / PID_FILE
    existing_pid = read_pid(pid_file)
    if not existing_pid:
        print("M15 后台看护器没有 PID 文件。")
        return 0
    if not process_alive(existing_pid):
        pid_file.unlink(missing_ok=True)
        print("M15 后台看护器已不在运行，PID 文件已清理。")
        return 0
    os.kill(existing_pid, signal.SIGTERM)
    time.sleep(0.5)
    if process_alive(existing_pid):
        print(f"M15 后台看护器仍在运行，PID={existing_pid}")
        return 1
    pid_file.unlink(missing_ok=True)
    print(f"M15 后台看护器已停止，PID={existing_pid}")
    return 0


def status(config: BackgroundWatchdogConfig) -> dict[str, Any]:
    pid_file = config.output_dir / PID_FILE
    existing_pid = read_pid(pid_file)
    alive = bool(existing_pid and process_alive(existing_pid))
    payload = read_json(config.output_dir / SUMMARY_JSON)
    reported_status = str(payload.get("watchdog_status") or "missing")
    reported_result = str(payload.get("plain_language_result") or "尚未生成看护状态。")
    if not alive:
        reported_status = "stopped"
        reported_result = "M15 后台看护未运行；历史健康结果已失效。"
    return {
        "pid": existing_pid or "",
        "process_alive": alive,
        "watchdog_status": reported_status,
        "generated_at": payload.get("generated_at", ""),
        "plain_language_result": reported_result,
    }


def read_pid(path: Path) -> int | None:
    try:
        return parse_pid(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def parse_pid(raw: str) -> int | None:
    value = raw.strip()
    try:
        return int(value) if value else None
    except ValueError:
        return None


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
