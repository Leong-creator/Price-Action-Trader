#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.m15_longbridge_realtime_session_supervisor_lib import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    SUMMARY_JSON,
    load_config,
    log_path,
    pid_path,
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
    try:
        while True:
            payload = run_realtime_session_once(config, generated_at=generated_at)
            print(config.output_dir / SUMMARY_JSON)
            print(payload.get("plain_language_result", ""))
            time.sleep(config.check_interval_seconds)
    finally:
        try:
            if pid_path(config).exists() and pid_path(config).read_text(encoding="utf-8").strip() == str(os.getpid()):
                pid_path(config).unlink()
        except OSError:
            pass


def start_daemon(args: argparse.Namespace, config) -> int:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    existing_pid = read_pid(pid_path(config))
    if existing_pid and process_alive(existing_pid):
        print(f"长桥实时链路守护器已在运行，PID={existing_pid}")
        return 0
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
    if not path.exists():
        print("长桥实时链路守护器还没有状态文件。")
        return 0
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    print(path)
    print(payload.get("plain_language_result", ""))
    print(f"状态={payload.get('supervisor_status', '')} 市场={payload.get('window', {}).get('market_status', '')}")
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


if __name__ == "__main__":
    raise SystemExit(main())
