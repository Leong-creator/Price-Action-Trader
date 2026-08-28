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
    runtime, runtime_artifact = read_json_artifact(config.sdk_runtime_status_path)
    readiness, readiness_artifact = read_json_artifact(config.opening_readiness_path)
    account, account_artifact = read_json_artifact(config.account_state_path)
    dashboard, dashboard_artifact = read_json_artifact(config.dashboard_path)
    formal_epoch, formal_epoch_artifact = read_json_artifact(config.formal_epoch_path)
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
    readiness_status = str(readiness.get("readiness_status") or "")
    pending_flatten = (
        str(formal_epoch.get("status") or "") == "pending_flatten"
        and formal_epoch.get("blocks_new_entries") is True
        and readiness_status == "armed_waiting_flatten_session"
    )
    readonly_gate_waiting = (
        runtime.get("dispatch_requested") is True
        and runtime.get("dispatch_enabled") is False
        and str(runtime.get("dispatch_block_reason") or "")
        == "complete_market_session_gate"
        and int(runtime.get("complete_sessions_passed") or 0)
        < int(runtime.get("complete_sessions_required") or 1)
    )
    marketdata_gate = marketdata_gate_truth(runtime, readiness, runtime_artifact, readiness_artifact)
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
        check_row(
            "json_gate_artifacts_healthy",
            "所有关键 JSON 状态/门禁文件必须存在且可解析，缺失与损坏要明确区分",
            all(
                artifact.get("status") == "ok"
                for artifact in (
                    runtime_artifact,
                    readiness_artifact,
                    account_artifact,
                    dashboard_artifact,
                    formal_epoch_artifact,
                )
            ),
            render_artifact_statuses(
                [
                    ("runtime", runtime_artifact),
                    ("readiness", readiness_artifact),
                    ("account", account_artifact),
                    ("dashboard", dashboard_artifact),
                    ("formal_epoch", formal_epoch_artifact),
                ]
            ),
        ),
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
        transition_check_row(
            "paper_dispatch_armed",
            "模拟账户下单通道已武装",
            runtime.get("dispatch_enabled") is True and runtime.get("dispatch_requested") is True,
            (pending_flatten or readonly_gate_waiting) and runtime.get("dispatch_requested") is True and marketdata_gate["artifacts_healthy"],
            f"enabled={runtime.get('dispatch_enabled')}, requested={runtime.get('dispatch_requested')}",
            waiting_status=(
                "waiting_for_marketdata_acceptance"
                if readonly_gate_waiting
                else "waiting_for_flatten"
            ),
        ),
        transition_check_row(
            "formal_epoch_active",
            "正式测试编号已激活且一致",
            formal_consistent,
            pending_flatten,
            str(formal_epoch.get("test_epoch_id") or "missing"),
        ),
        transition_check_row(
            "opening_readiness",
            "开盘验收没有失败项",
            int(readiness.get("fail_count") or 0) == 0
            and (
                (
                    readiness_status == "armed_waiting_regular_session"
                    and readiness.get("paper_order_submission_enabled") is True
                )
                or (
                    readiness_status
                    in {"ready_for_regular_session", "ready_for_longbridge_paper_orders"}
                    and readiness.get("paper_order_submission_enabled") is True
                    and readiness.get("new_position_submission_enabled") is True
                )
            ),
            (
                pending_flatten
                or (
                    readonly_gate_waiting
                    and readiness_status == "waiting_for_marketdata_acceptance"
                )
            )
            and int(readiness.get("fail_count") or 0) == 0
            and marketdata_gate["artifacts_healthy"],
            readiness_status or "missing",
            waiting_status=(
                "waiting_for_marketdata_acceptance"
                if readonly_gate_waiting
                else "waiting_for_flatten"
            ),
        ),
        transition_check_row(
            "marketdata_integrity_gate",
            "完整交易日行情门禁必须明确给出结果；未通过时关闭新开仓，并展示完整边界与实时 K 线事实",
            marketdata_gate["gate_passed"],
            (marketdata_gate["waiting"] or pending_flatten)
            and marketdata_gate["artifacts_healthy"],
            marketdata_gate["summary"],
            waiting_status="waiting_for_marketdata_acceptance",
        ),
        check_row(
            "dashboard_sdk_source",
            "长桥看板只使用 SDK 和长桥账户事实源；统计暂不可用不阻断交易链路",
            dashboard.get("source_of_truth") == "longbridge_sdk_paper_account",
            f"source={dashboard.get('source_of_truth')}, status={dashboard.get('data_status')}",
        ),
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
    elif pending_flatten:
        status = "armed_waiting_flatten_session"
    elif readonly_gate_waiting:
        status = "armed_waiting_marketdata_acceptance"
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
        "paper_order_submission_enabled": readiness.get("paper_order_submission_enabled") is True,
        "new_position_submission_enabled": bool(
            readiness.get("new_position_submission_enabled") is True
            and not pending_flatten
            and not readonly_gate_waiting
            and marketdata_gate["artifacts_healthy"]
            and marketdata_gate["gate_passed"]
            and fail_count == 0
        ),
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
        "input_artifacts": {
            "sdk_runtime_status": runtime_artifact,
            "opening_readiness": readiness_artifact,
            "account_state": account_artifact,
            "longbridge_dashboard": dashboard_artifact,
            "formal_epoch": formal_epoch_artifact,
        },
        "marketdata_integrity_gate": marketdata_gate,
        "plain_language_result": plain_result(status, fail_count, marketdata_gate),
    }


def check_row(check: str, required_result: str, passed: bool, actual: str) -> dict[str, Any]:
    return {"check": check, "required_result": required_result, "status": "pass" if passed else "fail", "actual": actual}


def transition_check_row(
    check: str,
    required_result: str,
    passed: bool,
    waiting: bool,
    actual: str,
    waiting_status: str = "waiting_for_flatten",
) -> dict[str, Any]:
    status = "pass" if passed else waiting_status if waiting else "fail"
    return {"check": check, "required_result": required_result, "status": status, "actual": actual}


def plain_result(status: str, fail_count: int, marketdata_gate: dict[str, Any]) -> str:
    if status == "ready_regular_session":
        return "M15 SDK 模拟交易链路已通过当前交易窗口验收。"
    if status == "armed_waiting_regular_session":
        return "M15 SDK 模拟交易链路已武装；当前只是在等待美股常规交易时段。"
    if status == "armed_waiting_flatten_session":
        return "M15 SDK 清仓链路已武装；清仓确认完成前保持停止新开仓。"
    if status == "armed_waiting_marketdata_acceptance":
        return f"M15 SDK 链路健康；{marketdata_gate.get('summary')}"
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


def read_json_artifact(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, {"path": project_path(path), "status": "missing"}
    except (OSError, json.JSONDecodeError) as exc:
        return {}, {"path": project_path(path), "status": "corrupt", "detail": str(exc)}
    if not isinstance(payload, dict):
        return {}, {"path": project_path(path), "status": "corrupt", "detail": "top_level_not_object"}
    return payload, {"path": project_path(path), "status": "ok"}


def render_artifact_statuses(rows: list[tuple[str, dict[str, Any]]]) -> str:
    return "; ".join(f"{label}={artifact.get('status')}" for label, artifact in rows)


def marketdata_gate_truth(
    runtime: dict[str, Any],
    readiness: dict[str, Any],
    runtime_artifact: dict[str, Any],
    readiness_artifact: dict[str, Any],
) -> dict[str, Any]:
    artifacts_healthy = runtime_artifact.get("status") == "ok" and readiness_artifact.get("status") == "ok"
    complete_boundary_count = safe_int(runtime.get("complete_boundary_count"))
    realtime_tradable_bar_count = safe_int(runtime.get("realtime_tradable_bar_count"))
    readiness_status = str(readiness.get("readiness_status") or "")
    gate_block_reason = str(runtime.get("dispatch_block_reason") or "")
    readonly_waiting = (
        readiness_status == "waiting_for_marketdata_acceptance"
        or gate_block_reason == "complete_market_session_gate"
    )
    explicit_gate_passed = runtime.get("complete_session_gate_passed") is True
    active_dispatch_proves_gate = bool(
        runtime.get("sdk_connected") is True
        and runtime.get("dispatch_enabled") is True
        and readiness.get("new_position_submission_enabled") is True
        and readiness_status
        in {
            "armed_waiting_regular_session",
            "ready_for_regular_session",
            "ready_for_longbridge_paper_orders",
            "ready_regular_session",
        }
    )
    gate_passed = explicit_gate_passed or active_dispatch_proves_gate
    if not artifacts_healthy:
        summary = (
            f"行情门禁工件异常：runtime={runtime_artifact.get('status')}，readiness={readiness_artifact.get('status')}；"
            f"完整边界 {complete_boundary_count}，实时 K 线 {realtime_tradable_bar_count}；关闭新开仓，已有持仓退出仍需要实时行情。"
        )
        status = "corrupt" if "corrupt" in {runtime_artifact.get('status'), readiness_artifact.get('status')} else "missing"
        return {
            "status": status,
            "artifacts_healthy": False,
            "gate_passed": False,
            "waiting": False,
            "complete_boundary_count": complete_boundary_count,
            "realtime_tradable_bar_count": realtime_tradable_bar_count,
            "summary": summary,
        }
    return {
        "status": "passed" if gate_passed else "blocked",
        "artifacts_healthy": True,
        "gate_passed": gate_passed,
        "waiting": readonly_waiting,
        "complete_boundary_count": complete_boundary_count,
        "realtime_tradable_bar_count": realtime_tradable_bar_count,
        "summary": (
            f"完整交易日行情门禁未通过，完整边界 {complete_boundary_count}，实时 K 线 {realtime_tradable_bar_count}；"
            "关闭新开仓，已有持仓退出仍需要实时行情。"
            if not gate_passed
            else f"完整交易日行情门禁已通过，完整边界 {complete_boundary_count}，实时 K 线 {realtime_tradable_bar_count}。"
        ),
    }


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
