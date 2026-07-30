#!/usr/bin/env python3
"""Build the pre-session acceptance from the SDK-only M15 control plane."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAILY_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh" / "daily_observation"
DEFAULT_REALTIME_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_monday_refresh_acceptance.json"
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_monday_refresh_acceptance"
ACCEPTANCE_JSON = "m15_monday_refresh_acceptance.json"
ACCEPTANCE_MD = "m15_monday_refresh_acceptance.md"


@dataclass(frozen=True, slots=True)
class MondayRefreshAcceptanceConfig:
    stage: str
    sdk_runtime_status_path: Path
    opening_readiness_path: Path
    watchdog_status_path: Path
    account_state_path: Path
    dashboard_path: Path
    formal_epoch_path: Path
    output_dir: Path


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> MondayRefreshAcceptanceConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload.get("inputs", {}) if isinstance(payload.get("inputs"), dict) else {}
    outputs = payload.get("outputs", {}) if isinstance(payload.get("outputs"), dict) else {}
    return MondayRefreshAcceptanceConfig(
        stage=str(payload.get("stage") or "M15.monday_refresh_acceptance"),
        sdk_runtime_status_path=resolve_repo_path(
            inputs.get("sdk_runtime_status", DEFAULT_REALTIME_DIR / "m15_longbridge_sdk_runtime.json")
        ),
        opening_readiness_path=resolve_repo_path(
            inputs.get(
                "opening_readiness",
                DEFAULT_DAILY_DIR / "m15_opening_trade_readiness" / "m15_opening_trade_readiness.json",
            )
        ),
        watchdog_status_path=resolve_repo_path(
            inputs.get(
                "background_watchdog_status",
                DEFAULT_DAILY_DIR / "m15_background_watchdog" / "m15_background_watchdog_status.json",
            )
        ),
        account_state_path=resolve_repo_path(
            inputs.get("account_state", DEFAULT_REALTIME_DIR / "m15_longbridge_realtime_account_state.json")
        ),
        dashboard_path=resolve_repo_path(
            inputs.get("longbridge_dashboard", DEFAULT_REALTIME_DIR / "m15_longbridge_dashboard_data.json")
        ),
        formal_epoch_path=resolve_repo_path(
            inputs.get("formal_epoch", DEFAULT_REALTIME_DIR / "m15_sdk_formal_test_epoch.json")
        ),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
    )


def run_m15_monday_refresh_acceptance(
    config: MondayRefreshAcceptanceConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = build_acceptance(config, generated_at)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / ACCEPTANCE_JSON, payload)
    (config.output_dir / ACCEPTANCE_MD).write_text(render_markdown(payload), encoding="utf-8")
    return payload


def build_acceptance(config: MondayRefreshAcceptanceConfig, generated_at: str) -> dict[str, Any]:
    runtime = read_json(config.sdk_runtime_status_path)
    readiness = read_json(config.opening_readiness_path)
    account = read_json(config.account_state_path)
    dashboard = read_json(config.dashboard_path)
    formal_epoch = read_json(config.formal_epoch_path)
    configured = int(runtime.get("trading_symbol_count") or runtime.get("configured_symbol_count") or 0)
    coverage = str(
        runtime.get("trading_market_data_coverage")
        or runtime.get("trading_subscription_coverage")
        or runtime.get("subscription_coverage")
        or ""
    )
    daily_rows = int(runtime.get("trading_daily_context_row_count") or runtime.get("daily_context_row_count") or 0)
    expected_daily_rows = configured * 60
    runtime_alive = str(runtime.get("status") or "") == "running" and process_alive(runtime.get("runtime_pid"))
    formal_active = str(formal_epoch.get("status") or "") == "active"
    formal_consistent = (
        formal_active
        and str(formal_epoch.get("test_epoch_id") or "")
        == str(readiness.get("formal_test_transition", {}).get("test_epoch_id") or "")
    )
    boundaries = readiness.get("boundaries") if isinstance(readiness.get("boundaries"), dict) else {}
    paper_only = (
        boundaries.get("paper_simulated_only") is True
        and boundaries.get("live_execution") is False
        and boundaries.get("real_money_actions") is False
        and boundaries.get("local_simulation_as_order_source") is False
    )
    market_window = readiness.get("market_window") if isinstance(readiness.get("market_window"), dict) else {}
    session_should_run = bool(market_window.get("session_should_run"))
    paper_account_connected = (
        runtime.get("sdk_connected") is True
        and account.get("paper_account_verified") is True
        and account.get("account_channel") == "lb_papertrading"
    )
    account_snapshot_age = runtime.get("account_snapshot_age_seconds")
    try:
        account_snapshot_age_seconds = int(account_snapshot_age)
    except (TypeError, ValueError):
        account_snapshot_age_seconds = 999999
    checks = [
        check_row("sdk_runtime_alive", "M15 SDK 常驻进程存活", runtime_alive, f"pid={runtime.get('runtime_pid')}, engine={runtime.get('runtime_engine')}"),
        check_row("sdk_connected", "SDK 行情和账户连接正常", runtime.get("sdk_connected") is True, str(runtime.get("sdk_connected"))),
        check_row("market_data_complete", "交易股票池实时行情覆盖完整", configured > 0 and coverage == f"{configured}/{configured}", coverage or "missing"),
        check_row(
            "daily_context_complete",
            "交易股票池每个标的最近 60 根日线完整",
            (
                runtime.get("trading_daily_context_ready") is True
                if "trading_daily_context_ready" in runtime
                else runtime.get("daily_context_state") == "complete" and daily_rows == expected_daily_rows
            ),
            f"{daily_rows}/{expected_daily_rows}",
        ),
        check_row(
            "account_snapshot_fresh",
            "账户快照不超过 45 秒",
            runtime.get("account_snapshot_healthy") is True and 0 <= account_snapshot_age_seconds <= 45,
            f"age={account_snapshot_age}s",
        ),
        check_row("paper_account_verified", "只连接长桥模拟账户", account.get("paper_account_verified") is True and account.get("account_channel") == "lb_papertrading", f"channel={account.get('account_channel')}"),
        check_row("paper_dispatch_armed", "模拟账户下单通道已武装", runtime.get("dispatch_enabled") is True and runtime.get("dispatch_requested") is True, f"enabled={runtime.get('dispatch_enabled')}, requested={runtime.get('dispatch_requested')}"),
        check_row("formal_epoch_active", "正式测试编号已激活且一致", formal_consistent, str(formal_epoch.get("test_epoch_id") or "missing")),
        check_row(
            "opening_readiness",
            "开盘验收没有失败项",
            int(readiness.get("fail_count") or 0) == 0
            and str(readiness.get("readiness_status") or "")
            in {
                "armed_waiting_regular_session",
                "ready_for_regular_session",
                "ready_for_longbridge_paper_orders",
            },
            str(readiness.get("readiness_status") or "missing"),
        ),
        check_row("dashboard_sdk_source", "长桥看板只使用 SDK 和长桥账户事实源", dashboard.get("source_of_truth") == "longbridge_sdk_paper_account" and dashboard.get("data_status") in {"trustworthy", "trading_ready_statistics_stale"}, f"source={dashboard.get('source_of_truth')}, status={dashboard.get('data_status')}"),
        check_row("paper_only_boundaries", "不接实盘、真实资金或本地模拟信号", paper_only, str(boundaries)),
        {
            "check": "regular_us_market_window",
            "required_result": "只在美股常规交易时段提交模拟订单",
            "status": "pass" if session_should_run else "waiting_for_regular_session",
            "actual": str(market_window.get("market_status") or "waiting"),
        },
    ]
    fail_count = sum(1 for row in checks if row["status"] == "fail")
    waiting_count = sum(1 for row in checks if row["status"].startswith("waiting"))
    pass_count = sum(1 for row in checks if row["status"] == "pass")
    if fail_count:
        status = "blocked_monday_acceptance"
    elif session_should_run:
        status = "ready_regular_session"
    else:
        status = "armed_waiting_regular_session"
    return {
        "schema_version": "m15.monday-refresh-acceptance.sdk.v2",
        "stage": config.stage,
        "generated_at": generated_at,
        "acceptance_status": status,
        "session_should_run": session_should_run,
        "pass_count": pass_count,
        "waiting_count": waiting_count,
        "fail_count": fail_count,
        "checks": checks,
        "runtime_whitelist_count": len(readiness.get("runtime_whitelist") or []),
        "paper_account_verified": bool(account.get("paper_account_verified")),
        "formal_test_epoch_id": formal_epoch.get("test_epoch_id"),
        "broker_connection": paper_account_connected,
        "paper_simulated_only": True,
        "real_order": False,
        "live_execution": False,
        "real_money_actions": False,
        "local_simulation_isolated": True,
        "input_refs": {
            "sdk_runtime_status": project_path(config.sdk_runtime_status_path),
            "opening_readiness": project_path(config.opening_readiness_path),
            "background_watchdog_status": project_path(config.watchdog_status_path),
            "account_state": project_path(config.account_state_path),
            "longbridge_dashboard": project_path(config.dashboard_path),
            "formal_epoch": project_path(config.formal_epoch_path),
        },
        "plain_language_result": plain_result(status, fail_count),
    }


def check_row(check: str, required_result: str, passed: bool, actual: str) -> dict[str, Any]:
    return {"check": check, "required_result": required_result, "status": "pass" if passed else "fail", "actual": actual}


def plain_result(status: str, fail_count: int) -> str:
    if status == "ready_regular_session":
        return "M15 SDK 模拟交易链路已通过当前交易窗口验收。"
    if status == "armed_waiting_regular_session":
        return "M15 SDK 模拟交易链路已武装；当前只是在等待美股常规交易时段。"
    return f"M15 SDK 周一验收被阻断：{fail_count} 个检查失败。"


def process_alive(value: Any) -> bool:
    try:
        pid = int(value)
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# M15 SDK Monday Acceptance",
        "",
        f"- Status: `{payload['acceptance_status']}`",
        f"- Pass / waiting / fail: `{payload['pass_count']}/{payload['waiting_count']}/{payload['fail_count']}`",
        f"- Formal epoch: `{payload.get('formal_test_epoch_id')}`",
        "- Boundary: Longbridge paper account only; no live money or local-simulation order source.",
        "",
        "| Check | Status | Actual |",
        "|---|---|---|",
    ]
    for row in payload["checks"]:
        lines.append(f"| {row['check']} | {row['status']} | {row.get('actual', '')} |")
    return "\n".join(lines) + "\n"
