#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if (
    VENV_PYTHON.exists()
    and Path(sys.prefix).resolve() != VENV_PYTHON.parent.parent.resolve()
    and os.environ.get("M15_SDK_RUNTIME_VENV_REEXEC") != "1"
):
    environment = dict(os.environ, M15_SDK_RUNTIME_VENV_REEXEC="1")
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__)), *sys.argv[1:]], environment)

from scripts.m15_longbridge_sdk_runtime_lib import (
    DEFAULT_CONFIG_PATH, FiveMinuteBarBuilder, MarketEventContext, SdkRealtimePaperClient, append_market_events,
    build_status, compact_market_events, configured_symbols, load_config, read_client_id, sdk_config_from_oauth,
    subscribe_private_trade_updates, subscribe_quote_and_trades, fresh_market_events, sdk_object_to_dict,
)


PID_FILE = "m15_longbridge_sdk_runtime.pid"
LOG_FILE = "m15_longbridge_sdk_runtime.log"
LEGACY_CLI_PID_FILE = "m15_longbridge_realtime_session_supervisor.pid"


class PipelineLatencyMetrics:
    """Small in-process latency window for the SDK event-to-order hot path."""

    def __init__(self) -> None:
        self._elapsed_ms: deque[int] = deque(maxlen=200)
        self._last_elapsed_ms = 0
        self._lock = threading.Lock()

    def record(self, elapsed_ms: int) -> None:
        with self._lock:
            self._last_elapsed_ms = max(0, elapsed_ms)
            self._elapsed_ms.append(self._last_elapsed_ms)

    def payload(self) -> dict[str, int]:
        with self._lock:
            rows = sorted(self._elapsed_ms)
            last_elapsed_ms = self._last_elapsed_ms
        if not rows:
            return {"completed_event_count": 0}
        percentile_index = min(len(rows) - 1, max(0, int(len(rows) * 0.95) - 1))
        return {
            "completed_event_count": len(rows),
            "last_pipeline_elapsed_ms": last_elapsed_ms,
            "median_pipeline_elapsed_ms": rows[len(rows) // 2],
            "p95_pipeline_elapsed_ms": rows[percentile_index],
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the persistent Longbridge SDK quote-push runtime.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--check", action="store_true", help="Validate SDK/OAuth prerequisites without subscribing.")
    parser.add_argument("--watch", action="store_true", help="Connect and keep receiving quote/trade pushes.")
    parser.add_argument("--dispatch", action="store_true", help="Dispatch finalized SDK bars to the isolated router and paper executor.")
    parser.add_argument("--daemon", action="store_true", help="Run the SDK runtime in the background.")
    parser.add_argument("--status", action="store_true", help="Print SDK runtime status without connecting.")
    parser.add_argument("--stop", action="store_true", help="Stop the SDK runtime daemon.")
    parser.add_argument(
        "--replace-cli-supervisor",
        action="store_true",
        help="Stop the paper-only CLI realtime supervisor before the SDK runtime takes over.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    if args.status:
        return print_runtime_status(config)
    if args.stop:
        return stop_runtime(config)
    if args.daemon:
        return start_runtime_daemon(args, config)
    sdk_error = ""
    try:
        import longbridge.openapi as lb
    except Exception as exc:
        lb = None
        sdk_error = f"sdk_import_failed:{exc}"
    client_id = ""
    oauth_error = ""
    try:
        client_id = read_client_id(config)
    except Exception as exc:
        oauth_error = str(exc)
    if sdk_error or oauth_error:
        reason = ";".join(item for item in (sdk_error, oauth_error) if item)
        build_status(
            config,
            status="blocked_sdk_prerequisite",
            reason=reason,
            sdk_installed=not bool(sdk_error),
            oauth_client_id_present=not bool(oauth_error),
        )
        print(f"SDK runtime blocked: {reason}")
        return 2
    if args.check:
        build_status(
            config,
            status="sdk_prerequisite_ready",
            reason="OAuth client id and SDK are available",
            sdk_installed=True,
            oauth_client_id_present=True,
        )
        print(f"SDK prerequisite ready; symbols={len(configured_symbols(config))}; client_id={client_id[:8]}...")
        return 0
    if args.dispatch and not config.paper_order_dispatch_enabled:
        build_status(
            config,
            status="blocked_dispatch_not_enabled",
            reason="paper_order_dispatch_enabled=false",
            sdk_installed=True,
            oauth_client_id_present=True,
        )
        print("SDK dispatch blocked: paper_order_dispatch_enabled=false")
        return 2
    if not args.watch:
        args.watch = True
    builder = FiveMinuteBarBuilder(config.bar_minutes)
    pipeline_metrics = PipelineLatencyMetrics()
    last_compaction = 0.0
    maintenance = None
    try:
        oauth = lb.OAuthBuilder(client_id).build(lambda url: print(f"OAuth authorization required: {url}", flush=True))
        quote = lb.QuoteContext(sdk_config_from_oauth(lb, oauth, config.quote_region))
        from scripts.m15_longbridge_realtime_signal_router_lib import load_config as load_router_config, read_jsonl_tail, run_realtime_signal_router
        router_config = load_router_config(config.router_config_path)
        market_event_context = MarketEventContext(
            read_jsonl_tail(config.market_events_path, router_config.max_market_event_rows_per_hot_run),
            maximum_rows=router_config.max_market_event_rows_per_hot_run,
        )
        trade = None
        paper_client = None
        execution_config = None
        if args.dispatch:
            trade = lb.TradeContext(sdk_config_from_oauth(lb, oauth, config.trade_region))
            subscribe_private_trade_updates(trade, lb, enabled=config.enable_trade_private_push)
            paper_client = SdkRealtimePaperClient(trade, lb)
            from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config
            execution_config = load_execution_config(config.execution_config_path)
            if not execution_config.execute_orders or not execution_config.paper_trading_approval:
                raise RuntimeError("sdk_dispatch_execution_config_not_paper_orders_enabled")
            maintenance = SdkAccountMaintenance(config)
            maintenance.start()
        def emit(rows):
            fresh_rows = fresh_market_events(rows, config.maximum_source_delivery_age_ms)
            append_market_events(config.market_events_path, fresh_rows, config.event_keep_lines)
            if fresh_rows and paper_client is not None:
                pipeline_started = time.perf_counter()
                from scripts.m15_longbridge_realtime_execution_lib import run_realtime_execution
                from scripts.m15_longbridge_realtime_position_manager_lib import load_config as load_position_manager_config
                from scripts.m15_longbridge_realtime_position_manager_lib import run_realtime_position_manager
                now = fresh_rows[-1]["received_at"]
                new_rows = market_event_context.append(fresh_rows)
                emitted_signals: list[dict] = []
                run_realtime_signal_router(
                    router_config,
                    generated_at=now,
                    market_events_override=market_event_context.rows(),
                    active_market_event_ids={str(row["event_id"]) for row in new_rows},
                    emitted_signal_events=emitted_signals,
                )
                position_config = load_position_manager_config(config.position_manager_config_path)
                position_config = replace(position_config, market_events_path=config.market_events_path)
                position_payload = run_realtime_position_manager(position_config, generated_at=now)
                run_realtime_execution(
                    execution_config,
                    generated_at=now,
                    broker_client=paper_client,
                    signal_events_override=emitted_signals + list(position_payload.get("emitted_exit_signal_events", [])),
                )
                pipeline_metrics.record(int((time.perf_counter() - pipeline_started) * 1000))
        def on_quote(symbol, event):
            rows = builder.on_quote(symbol, sdk_object_to_dict(event), received_at=datetime.now(UTC))
            emit(rows)
        def on_trades(symbol, event):
            rows = builder.on_trade(symbol, sdk_object_to_dict(event), received_at=datetime.now(UTC))
            emit(rows)
        quote.set_on_quote(on_quote)
        quote.set_on_trades(on_trades)
        subscribe_quote_and_trades(
            quote,
            list(configured_symbols(config)),
            [lb.SubType.Quote, lb.SubType.Trade],
            batch_size=config.subscription_batch_size,
        )
        build_status(config, status="running", connected=True, sdk_installed=True, oauth_client_id_present=True)
        write_pid(config)
        while args.watch:
            rows = builder.flush(datetime.now(UTC))
            emit(rows)
            if time.monotonic() - last_compaction >= 60:
                compact_market_events(config.market_events_path, config.event_keep_lines)
                last_compaction = time.monotonic()
            build_status(
                config,
                status="running",
                connected=True,
                last_event_at=rows[-1]["received_at"] if rows else "",
                sdk_installed=True,
                oauth_client_id_present=True,
                pipeline_metrics=pipeline_metrics.payload(),
            )
            time.sleep(config.heartbeat_interval_seconds)
    except KeyboardInterrupt:
        build_status(config, status="stopped", sdk_installed=True, oauth_client_id_present=True)
        return 0
    except Exception as exc:
        build_status(config, status="connection_failed", reason=str(exc), sdk_installed=True, oauth_client_id_present=True)
        print(f"SDK runtime failed: {exc}")
        return 1
    finally:
        if maintenance is not None:
            maintenance.stop()
        clear_pid(config)


class SdkAccountMaintenance:
    """Run slow CLI account reconciliation outside SDK quote and order callbacks."""

    def __init__(self, config) -> None:
        self.config = config
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="m15-sdk-account-maintenance", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        from scripts.m15_longbridge_realtime_account_state_lib import load_config as load_account_state_config
        from scripts.m15_longbridge_realtime_account_state_lib import run_realtime_account_state
        from scripts.m15_longbridge_realtime_stale_order_cleanup_lib import load_config as load_cleanup_config
        from scripts.m15_longbridge_realtime_stale_order_cleanup_lib import run_stale_order_cleanup
        from scripts.m15_longbridge_realtime_session_supervisor_lib import (
            build_window_state,
            load_config as load_session_supervisor_config,
        )

        while not self._stop.is_set():
            try:
                account_config = load_account_state_config(self.config.account_state_config_path)
                run_realtime_account_state(account_config, refresh_analytics=False, refresh_historical_order_history=False)
                cleanup_config = load_cleanup_config(self.config.stale_order_cleanup_config_path)
                window = build_window_state(
                    load_session_supervisor_config(
                        ROOT / "config" / "examples" / "m15_longbridge_realtime_session_supervisor.paper_orders_enabled.json"
                    )
                )
                run_stale_order_cleanup(cleanup_config, session_started_at=str(window["session_started_at"]))
            except Exception as exc:  # The hot path independently rejects stale account state.
                print(f"SDK account maintenance failed: {exc}", flush=True)
            self._stop.wait(self.config.account_maintenance_interval_seconds)


def pid_path(config) -> Path:
    return config.output_dir / PID_FILE


def log_path(config) -> Path:
    return config.output_dir / LOG_FILE


def read_pid(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
        return value if value > 0 else None
    except (OSError, ValueError):
        return None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def write_pid(config) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pid_path(config).write_text(f"{os.getpid()}\n", encoding="utf-8")


def clear_pid(config) -> None:
    path = pid_path(config)
    if read_pid(path) == os.getpid():
        path.unlink(missing_ok=True)


def stop_runtime(config) -> int:
    pid = read_pid(pid_path(config))
    if not pid or not process_alive(pid):
        pid_path(config).unlink(missing_ok=True)
        print("SDK 实时运行层未在运行。")
        return 0
    os.killpg(pid, signal.SIGTERM)
    print(f"已停止 SDK 实时运行层，PID={pid}")
    return 0


def stop_legacy_cli_supervisor(config) -> None:
    path = config.output_dir / LEGACY_CLI_PID_FILE
    pid = read_pid(path)
    if not pid or not process_alive(pid):
        path.unlink(missing_ok=True)
        return
    try:
        command_line = Path(f"/proc/{pid}/cmdline").read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise RuntimeError(f"cannot_validate_legacy_cli_supervisor:{exc}") from exc
    if "run_m15_longbridge_realtime_session_supervisor.py" not in command_line:
        raise RuntimeError("refusing_to_stop_unrecognised_process")
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if process_alive(pid):
        raise RuntimeError("legacy_cli_supervisor_did_not_stop")
    path.unlink(missing_ok=True)


def start_runtime_daemon(args: argparse.Namespace, config) -> int:
    if not args.dispatch or not config.paper_order_dispatch_enabled:
        print("拒绝后台启动：SDK 模拟下单必须同时传入 --dispatch 且配置显式启用。")
        return 2
    existing = read_pid(pid_path(config))
    if existing and process_alive(existing):
        print(f"SDK 实时运行层已在运行，PID={existing}")
        return 0
    if args.replace_cli_supervisor:
        stop_legacy_cli_supervisor(config)
    command = [sys.executable, str(Path(__file__).resolve()), "--watch", "--dispatch", "--config", str(args.config)]
    config.output_dir.mkdir(parents=True, exist_ok=True)
    with log_path(config).open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(command, cwd=str(ROOT), stdout=handle, stderr=handle, start_new_session=True)
    pid_path(config).write_text(f"{process.pid}\n", encoding="utf-8")
    print(f"SDK 实时运行层已启动，PID={process.pid}")
    return 0


def print_runtime_status(config) -> int:
    status_path = config.runtime_status_path
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    pid = read_pid(pid_path(config))
    payload["runtime_process_alive"] = bool(pid and process_alive(pid))
    payload["runtime_pid"] = pid or ""
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
