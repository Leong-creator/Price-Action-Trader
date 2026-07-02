#!/usr/bin/env python3
from __future__ import annotations

import json
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

CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class BackgroundWatchdogConfig:
    stage: str
    output_dir: Path
    check_interval_seconds: int
    command_timeout_seconds: int
    m12_47_config_path: Path
    m15_realtime_supervisor_config_path: Path
    readiness_config_path: Path
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
        m12_47_config_path=resolve_repo_path(
            inputs.get("m12_47_config", ROOT / "config" / "examples" / "m12_47_session_supervisor.json")
        ),
        m15_realtime_supervisor_config_path=resolve_repo_path(
            inputs.get(
                "m15_realtime_supervisor_config",
                ROOT / "config" / "examples" / "m15_longbridge_realtime_session_supervisor.paper_orders_enabled.json",
            )
        ),
        readiness_config_path=resolve_repo_path(
            inputs.get("readiness_config", ROOT / "config" / "examples" / "m15_opening_trade_readiness.json")
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
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 background watchdog must stay paper/simulated only")
    for key in ("live_execution", "real_money_actions", "manual_m12_37_once"):
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
    steps = [
        run_step(
            "m12_47_daemon",
            "M12.47 守护器自愈拉起",
            [
                sys.executable,
                "scripts/run_m12_47_session_supervisor.py",
                "--daemon",
                "--config",
                project_path(config.m12_47_config_path),
            ],
            config,
            runner,
        ),
        run_step(
            "m15_realtime_daemon",
            "M15 长桥实时守护器自愈拉起",
            [
                sys.executable,
                "scripts/run_m15_longbridge_realtime_session_supervisor.py",
                "--daemon",
                "--config",
                project_path(config.m15_realtime_supervisor_config_path),
            ],
            config,
            runner,
        ),
        run_step(
            "m12_47_status",
            "M12.47 守护器状态",
            [
                sys.executable,
                "scripts/run_m12_47_session_supervisor.py",
                "--status",
                "--config",
                project_path(config.m12_47_config_path),
            ],
            config,
            runner,
        ),
        run_step(
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
        "plain_language_result": plain_language_result(failed_steps),
        "refs": {
            "m12_47_config": project_path(config.m12_47_config_path),
            "m15_realtime_supervisor_config": project_path(config.m15_realtime_supervisor_config_path),
            "readiness_config": project_path(config.readiness_config_path),
        },
    }
    write_json(config.output_dir / SUMMARY_JSON, payload)
    append_jsonl(config.output_dir / LEDGER_JSONL, [payload])
    (config.output_dir / REPORT_MD).write_text(render_markdown(payload), encoding="utf-8")
    return payload


def run_step(
    step_id: str,
    label: str,
    command: list[str],
    config: BackgroundWatchdogConfig,
    runner: CommandRunner,
) -> dict[str, Any]:
    assert_safe_watchdog_command(command)
    started = time.perf_counter()
    try:
        completed = runner(command, config.command_timeout_seconds)
        returncode = int(completed.returncode)
        stdout = str(completed.stdout or "")
        stderr = str(completed.stderr or "")
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = str(exc.stdout or "")
        stderr = f"timeout after {config.command_timeout_seconds}s"
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
        "scripts/run_m12_47_session_supervisor.py",
        "scripts/run_m15_longbridge_realtime_session_supervisor.py",
        "scripts/run_m15_opening_trade_readiness.py",
    }
    script_tokens = [token for token in command if token.startswith("scripts/")]
    if not script_tokens or script_tokens[0] not in allowed_scripts:
        raise ValueError(f"watchdog command is not allowed: {joined}")


def printable_command(command: list[str]) -> str:
    return " ".join(command)


def clean_text(value: str) -> str:
    return value.replace("\r", "").strip()


def plain_language_result(failed_steps: list[dict[str, Any]]) -> str:
    if not failed_steps:
        return "后台看护已完成：M12.47 与 M15 长桥实时守护器已按 daemon/status/readiness 顺序检查；没有手动运行 M12.37 once。"
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
        lines.append(
            f"| {step.get('label', '')} | {step.get('returncode', '')} | {step.get('elapsed_ms', '')} | "
            f"{str(step.get('stdout_tail') or step.get('stderr_tail') or '')[:120]} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 只维护 M12.47 / M15 守护器。",
            "- 不手动运行 M12.37 once。",
            "- 不提交、撤销或修改订单。",
            "- 仍只限长桥模拟账户。",
        ]
    )
    return "\n".join(lines) + "\n"


def run_command(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )


def watch_loop(config: BackgroundWatchdogConfig) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pid_file = config.output_dir / PID_FILE
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


def start_daemon(config_path: str | Path, config: BackgroundWatchdogConfig) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pid_file = config.output_dir / PID_FILE
    existing_pid = read_pid(pid_file)
    if existing_pid and process_alive(existing_pid):
        print(f"M15 后台看护器已在运行，PID={existing_pid}")
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
    return {
        "pid": existing_pid or "",
        "process_alive": alive,
        "watchdog_status": payload.get("watchdog_status", "missing"),
        "generated_at": payload.get("generated_at", ""),
        "plain_language_result": payload.get("plain_language_result", "尚未生成看护状态。"),
    }


def read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
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
