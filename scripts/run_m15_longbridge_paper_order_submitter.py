#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.m15_longbridge_paper_order_submitter_lib import (
    load_config,
    run_paper_submitter,
    watch_paper_submitter,
)


def pid_path(config) -> Path:
    return config.output_dir / "m15_longbridge_paper_order_submitter.pid"


def daemon_log_path(config) -> Path:
    return config.output_dir / "m15_longbridge_paper_order_submitter_daemon.out"


def process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid(config) -> int:
    path = pid_path(config)
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return 0


def start_daemon(config, config_path: str | None) -> int:
    existing = read_pid(config)
    if process_alive(existing):
        print(json.dumps({"status": "already_running", "pid": existing}, ensure_ascii=False))
        return 0
    config.output_dir.mkdir(parents=True, exist_ok=True)
    with daemon_log_path(config).open("a", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--foreground",
                "--config",
                str(config_path or ""),
            ],
            cwd=ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )
    pid_path(config).write_text(str(proc.pid), encoding="utf-8")
    print(json.dumps({"status": "started", "pid": proc.pid}, ensure_ascii=False))
    return 0


def stop_daemon(config) -> int:
    pid = read_pid(config)
    if not process_alive(pid):
        print(json.dumps({"status": "not_running"}, ensure_ascii=False))
        return 0
    os.kill(pid, signal.SIGTERM)
    print(json.dumps({"status": "stopped", "pid": pid}, ensure_ascii=False))
    return 0


def print_status(config) -> int:
    pid = read_pid(config)
    summary_path = config.output_dir / "m15_longbridge_paper_order_submitter.json"
    summary = {}
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    payload = {
        "status": "running" if process_alive(pid) else "not_running",
        "pid": pid,
        "latest_submission_status": summary.get("submission_status", ""),
        "latest_market_status": (summary.get("market_window") or {}).get("market_status", ""),
        "latest_preview_scan_date": summary.get("preview_scan_date", ""),
        "eligible_order_count": summary.get("eligible_order_count", 0),
        "submitted_order_count": summary.get("submitted_order_count", 0),
        "paper_account_start_at": summary.get("paper_account_start_at", config.paper_account_start_at),
        "plain_language_result": summary.get("plain_language_result", ""),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit approved Longbridge paper orders under M15 guardrails.")
    parser.add_argument("--config", default=None, help="Path to M15 paper order submitter config JSON.")
    parser.add_argument("--generated-at", default=None, help="UTC timestamp for deterministic one-shot checks.")
    parser.add_argument("--foreground", action="store_true", help="Run the watch loop in foreground.")
    parser.add_argument("--daemon", action="store_true", help="Start detached paper-order submitter daemon.")
    parser.add_argument("--status", action="store_true", help="Print paper-order submitter daemon status.")
    parser.add_argument("--stop", action="store_true", help="Stop detached paper-order submitter daemon.")
    parser.add_argument("--watch", action="store_true", help="Keep checking until regular session submits or closes.")
    parser.add_argument("--max-iterations", type=int, default=None, help="Optional watch loop limit for tests/manual dry checks.")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate orders without submitting them.")
    args = parser.parse_args()

    config = load_config(args.config) if args.config else load_config()
    if args.status:
        return print_status(config)
    if args.stop:
        return stop_daemon(config)
    if args.daemon:
        return start_daemon(config, args.config)
    if args.foreground or args.watch:
        payload = watch_paper_submitter(config, max_iterations=args.max_iterations)
    else:
        payload = run_paper_submitter(config, generated_at=args.generated_at, execute_orders=not args.dry_run)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
