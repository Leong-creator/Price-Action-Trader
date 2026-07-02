#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.m15_longbridge_realtime_session_supervisor_lib import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    MAX_SUPERVISOR_LOG_BYTES,
    SUMMARY_JSON,
    build_window_state,
    load_config,
    log_path,
    pid_path,
    rotate_text_log_if_needed,
    run_realtime_session_once,
    status_path,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supervise the isolated Longbridge realtime paper-account chain.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to realtime session supervisor config JSON.")
    parser.add_argument("--generated-at", default=None, help="Override generated_at ISO timestamp for deterministic tests.")
    parser.add_argument("--once", action="store_true", help="Run one supervised realtime cycle if the market window allows it.")
    parser.add_argument("--watch", action="store_true", help="Keep running supervised cycles in the foreground.")
    parser.add_argument("--daemon", action="store_true", help="Start the foreground watcher in the background.")
    parser.add_argument("--status", action="store_true", help="Print the latest supervisor status without running a cycle.")
    parser.add_argument("--stop", action="store_true", help="Stop a background realtime session supervisor started by --daemon.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if args.status:
        return print_status(config)
    if args.stop:
        return stop_daemon(config)
    if args.daemon:
        return start_daemon(args, config)
    if args.watch:
        return watch_loop(config, generated_at=args.generated_at)
    payload = run_realtime_session_once(config, generated_at=args.generated_at)
    print(config.output_dir / SUMMARY_JSON)
    print(payload.get("plain_language_result", ""))
    return 0


def watch_loop(config, *, generated_at: str | None = None) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pid_path(config).write_text(str(os.getpid()) + "\n", encoding="utf-8")
    last_print_key: tuple[str, str, bool, str] | None = None
    try:
        while True:
            try:
                payload = run_realtime_session_once(config, generated_at=generated_at)
                print_key = watch_print_key(payload)
                if should_print_watch_payload(payload, print_key, last_print_key):
                    print(config.output_dir / SUMMARY_JSON, flush=True)
                    print(payload.get("plain_language_result", ""), flush=True)
                    last_print_key = print_key
            except Exception as exc:  # pragma: no cover - daemon resilience path
                payload = build_watch_loop_exception_status(config, exc)
                print(config.output_dir / SUMMARY_JSON, flush=True)
                print(payload.get("plain_language_result", ""), flush=True)
                last_print_key = watch_print_key(payload)
            time.sleep(watch_sleep_seconds(config, payload))
    finally:
        try:
            if pid_path(config).exists() and pid_path(config).read_text(encoding="utf-8").strip() == str(os.getpid()):
                pid_path(config).unlink()
        except OSError:
            pass


def build_watch_loop_exception_status(config, exc: Exception) -> dict:
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": "m15.longbridge-realtime-session-supervisor.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": now,
        "supervisor_status": "watch_loop_exception",
        "cycle_ran": False,
        "window": build_window_state(config, generated_at=now),
        "session_should_run": False,
        "consecutive_failure_count": 1,
        "max_consecutive_failures": config.max_consecutive_failures,
        "failure_state": "watch_loop_exception",
        "failure_reason": str(exc)[:500],
        "step_rows": [],
        "new_market_event_count": 0,
        "new_signal_event_count": 0,
        "ready_order_count": 0,
        "submitted_count": 0,
        "local_simulation_isolated": True,
        "local_ledger_input_ref": "",
        "legacy_fast_queue_used": False,
        "manual_m12_37_once_used": False,
        "paper_simulated_only": True,
        "real_money_actions": False,
        "live_execution": False,
        "plain_language_result": f"长桥实时链路守护器遇到异常但保持运行，下一轮会继续尝试：{str(exc)[:200]}",
    }
    path = status_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return payload


def watch_sleep_seconds(config, payload: dict) -> int:
    window = payload.get("window", {}) if isinstance(payload.get("window"), dict) else {}
    if bool(window.get("session_should_run")) or bool(payload.get("cycle_ran")):
        return int(config.check_interval_seconds)
    seconds_until_next_session = int(window.get("seconds_until_next_session") or 0)
    if 0 < seconds_until_next_session <= 120:
        return min(int(config.check_interval_seconds), seconds_until_next_session)
    return int(config.idle_check_interval_seconds)


def watch_print_key(payload: dict) -> tuple[str, str, bool, str]:
    window = payload.get("window", {}) if isinstance(payload.get("window"), dict) else {}
    return (
        str(payload.get("supervisor_status") or ""),
        str(window.get("market_phase") or ""),
        bool(payload.get("cycle_ran")),
        str(payload.get("failure_state") or ""),
    )


def should_print_watch_payload(
    payload: dict,
    print_key: tuple[str, str, bool, str],
    previous_key: tuple[str, str, bool, str] | None,
) -> bool:
    if previous_key != print_key:
        return True
    if bool(payload.get("cycle_ran")):
        return True
    if payload.get("failure_state"):
        return True
    return False


def start_daemon(args: argparse.Namespace, config) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    existing_pid = read_pid(pid_path(config))
    if existing_pid and process_alive(existing_pid):
        print(f"长桥实时链路守护器已在运行，PID={existing_pid}")
        return 0
    rotate_text_log_if_needed(log_path(config), max_bytes=MAX_SUPERVISOR_LOG_BYTES)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--watch",
        "--config",
        str(args.config),
    ]
    if args.generated_at:
        command.extend(["--generated-at", args.generated_at])
    with log_path(config).open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    pid_path(config).write_text(str(process.pid) + "\n", encoding="utf-8")
    print(f"长桥实时链路守护器已启动，PID={process.pid}")
    return 0


def stop_daemon(config) -> int:
    existing_pid = read_pid(pid_path(config))
    if not existing_pid:
        print("长桥实时链路守护器没有 PID 文件。")
        return 0
    if not process_alive(existing_pid):
        pid_path(config).unlink(missing_ok=True)
        print("长桥实时链路守护器已不在运行，PID 文件已清理。")
        return 0
    os.kill(existing_pid, signal.SIGTERM)
    time.sleep(0.5)
    if process_alive(existing_pid):
        print(f"长桥实时链路守护器仍在运行，PID={existing_pid}")
        return 1
    pid_path(config).unlink(missing_ok=True)
    print(f"长桥实时链路守护器已停止，PID={existing_pid}")
    return 0


def print_status(config) -> int:
    path = status_path(config)
    existing_pid = read_pid(pid_path(config))
    alive = bool(existing_pid and process_alive(existing_pid))
    current_window = build_window_state(config)
    if not path.exists():
        pid_text = f"PID={existing_pid}" if existing_pid else "没有 PID 文件"
        print(f"长桥实时链路守护器还没有状态文件；进程存活={alive}，{pid_text}。")
        print(f"当前市场={current_window.get('market_status', '')}")
        return 0
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    generated_at = str(payload.get("generated_at") or "")
    age_text = status_age_label(generated_at)
    print(path)
    print(payload.get("plain_language_result", ""))
    print(
        f"进程存活={alive} PID={existing_pid or ''} "
        f"状态={payload.get('supervisor_status', '')} "
        f"状态时间={generated_at or '未知'} {age_text} "
        f"状态内市场={payload.get('window', {}).get('market_status', '')} "
        f"当前市场={current_window.get('market_status', '')}"
    )
    return 0


def read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def status_age_label(generated_at: str) -> str:
    if not generated_at:
        return "(无状态时间)"
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return "(状态时间无法解析)"
    age = int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds())
    if age < 0:
        return "(状态时间在未来)"
    return f"(距今 {age} 秒)"


if __name__ == "__main__":
    raise SystemExit(main())
