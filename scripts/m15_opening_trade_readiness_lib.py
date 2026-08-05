#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.m15_longbridge_realtime_execution_lib import SUMMARY_JSON as EXECUTION_SUMMARY_JSON
from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config
from scripts.m15_longbridge_realtime_execution_lib import parse_utc_datetime
from scripts.m15_longbridge_realtime_execution_lib import read_jsonl as read_execution_jsonl
from scripts.m15_longbridge_realtime_session_supervisor_lib import (
    DEFAULT_CONFIG_PATH as DEFAULT_REALTIME_SUPERVISOR_CONFIG_PATH,
    build_window_state,
    load_config as load_realtime_supervisor_config,
    pid_path as realtime_pid_path,
    supervisor_health_issues,
)
from scripts.m15_longbridge_realtime_stale_order_cleanup_lib import load_config as load_stale_order_cleanup_config
from scripts.m15_longbridge_realtime_stale_order_cleanup_lib import stale_buy_open_orders
from scripts.m15_longbridge_sdk_runtime_lib import config_fingerprint as sdk_config_fingerprint
from scripts.m15_longbridge_sdk_runtime_lib import configured_trading_symbols as sdk_configured_trading_symbols
from scripts.m15_longbridge_sdk_runtime_lib import daily_context_is_complete as sdk_daily_context_is_complete
from scripts.m15_longbridge_sdk_runtime_lib import trading_universe_fingerprint as sdk_trading_universe_fingerprint


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAILY_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
)
DEFAULT_M12_DIR = DEFAULT_DAILY_DIR / "m12_29_current_day_scan_dashboard"
DEFAULT_M15_REALTIME_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_opening_trade_readiness"
# M15 now runs only through the SDK paper runtime.  Keeping the retired CLI
# readiness config as the implicit default lets an otherwise healthy runtime be
# reported as dead whenever callers omit --config.
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_opening_trade_readiness.paper_orders_enabled.json"
READINESS_JSON = "m15_opening_trade_readiness.json"
READINESS_MD = "m15_opening_trade_readiness.md"


@dataclass(frozen=True, slots=True)
class OpeningTradeReadinessConfig:
    stage: str
    m12_47_status_path: Path
    realtime_supervisor_config_path: Path
    execution_config_path: Path
    realtime_account_state_path: Path
    realtime_supervisor_status_path: Path
    realtime_runtime_engine: str
    sdk_runtime_config_path: Path
    sdk_runtime_status_path: Path
    output_dir: Path


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> OpeningTradeReadinessConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    return OpeningTradeReadinessConfig(
        stage=str(payload.get("stage", "M15.opening_trade_readiness")),
        m12_47_status_path=resolve_repo_path(inputs.get("m12_47_status", DEFAULT_M12_DIR / "m12_47_session_supervisor_status.json")),
        realtime_supervisor_config_path=resolve_repo_path(
            inputs.get("realtime_supervisor_config", DEFAULT_REALTIME_SUPERVISOR_CONFIG_PATH)
        ),
        execution_config_path=resolve_repo_path(
            inputs.get(
                "execution_config",
                ROOT / "config" / "examples" / "m15_longbridge_realtime_execution.paper_orders_enabled.json",
            )
        ),
        realtime_account_state_path=resolve_repo_path(
            inputs.get("realtime_account_state", DEFAULT_M15_REALTIME_DIR / "m15_longbridge_realtime_account_state.json")
        ),
        realtime_supervisor_status_path=resolve_repo_path(
            inputs.get("realtime_supervisor_status", DEFAULT_M15_REALTIME_DIR / "m15_longbridge_realtime_session_supervisor.json")
        ),
        realtime_runtime_engine=str(inputs.get("realtime_runtime_engine", "cli")).strip().lower(),
        sdk_runtime_config_path=resolve_repo_path(
            inputs.get("sdk_runtime_config", ROOT / "config" / "examples" / "m15_longbridge_sdk_runtime.json")
        ),
        sdk_runtime_status_path=resolve_repo_path(
            inputs.get("sdk_runtime_status", DEFAULT_M15_REALTIME_DIR / "m15_longbridge_sdk_runtime.json")
        ),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
    )


def informational_check_row(check: str, required_result: str, **extra: Any) -> dict[str, Any]:
    row = check_row(check, required_result, "informational", **extra)
    row["non_blocking"] = True
    return row


def run_m15_opening_trade_readiness(
    config: OpeningTradeReadinessConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = build_readiness(config, generated_at)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / READINESS_JSON, payload)
    (config.output_dir / READINESS_MD).write_text(render_markdown(payload), encoding="utf-8")
    if config.realtime_runtime_engine == "sdk" and config.output_dir.resolve() == DEFAULT_OUTPUT_DIR.resolve():
        legacy_path = DEFAULT_M15_REALTIME_DIR / READINESS_JSON
        write_json(
            legacy_path,
            {
                "schema_version": "m15.opening-trade-readiness.legacy-pointer.v1",
                "generated_at": generated_at,
                "readiness_status": "superseded_use_canonical_sdk_readiness",
                "canonical_path": project_path(config.output_dir / READINESS_JSON),
                "trading_decision_allowed": False,
                "plain_language_result": "此旧路径已停用；请读取 canonical_path 指向的 SDK 开盘验收。",
            },
        )
        (DEFAULT_M15_REALTIME_DIR / READINESS_MD).write_text(
            "# Superseded readiness path\n\n"
            f"Use `{project_path(config.output_dir / READINESS_JSON)}`.\n",
            encoding="utf-8",
        )
    return payload


def build_readiness(config: OpeningTradeReadinessConfig, generated_at: str) -> dict[str, Any]:
    if config.realtime_runtime_engine not in {"cli", "sdk"}:
        raise ValueError("M15 opening readiness runtime engine must be cli or sdk")
    m12_status = read_json(config.m12_47_status_path)
    realtime_config = load_realtime_supervisor_config(config.realtime_supervisor_config_path)
    sdk_config = None
    if config.realtime_runtime_engine == "sdk":
        from scripts.m15_longbridge_sdk_runtime_lib import load_config as load_sdk_runtime_config
        sdk_config = load_sdk_runtime_config(config.sdk_runtime_config_path)
    execution_config_error = ""
    try:
        execution_config = load_execution_config(config.execution_config_path)
    except ValueError as exc:
        execution_config = None
        execution_config_error = str(exc)
    execution_payload = read_json_payload(config.execution_config_path)
    execution_summary = read_json(execution_config.output_dir / EXECUTION_SUMMARY_JSON) if execution_config else {}
    account_state = read_json(config.realtime_account_state_path)
    realtime_status = read_json(
        config.sdk_runtime_status_path if sdk_config is not None else config.realtime_supervisor_status_path
    )
    window = build_window_state(realtime_config, generated_at=generated_at)
    cleanup_config = load_stale_order_cleanup_config(realtime_config.stale_order_cleanup_config_path)
    realtime_pid = read_pid(
        sdk_config.output_dir / "m15_longbridge_sdk_runtime.pid" if sdk_config is not None else realtime_pid_path(realtime_config)
    )
    realtime_alive = bool(realtime_pid and process_alive(realtime_pid))
    realtime_status_generated_at = str(realtime_status.get("generated_at") or "")
    realtime_status_age_seconds = artifact_age_seconds(realtime_status_generated_at, generated_at)
    m12_reported_alive = bool(m12_status.get("supervisor_process_alive", False))
    try:
        m12_pid = int(m12_status.get("supervisor_pid") or 0)
    except (TypeError, ValueError):
        m12_pid = 0
    m12_alive = m12_reported_alive and (not m12_pid or process_alive(m12_pid))
    linked_execution_config_path = (
        sdk_config.execution_config_path if sdk_config is not None else realtime_config.execution_config_path
    )
    execution_config_linked = config.execution_config_path.resolve() == linked_execution_config_path.resolve()
    paper_orders_enabled = bool(execution_config and execution_config.execute_orders and execution_config.paper_trading_approval)
    runtime_dispatch_enabled = bool(realtime_status.get("dispatch_enabled", False))
    formal_transition = realtime_status.get("formal_test_transition", {})
    formal_transition = formal_transition if isinstance(formal_transition, dict) else {}
    pending_formal_flatten = str(formal_transition.get("status") or "") == "pending_flatten"
    formal_test_active = str(formal_transition.get("status") or "") == "active"
    validation_test_active = bool(
        str(formal_transition.get("status") or "") == "validation_active"
        and formal_transition.get("validation_session") is True
        and formal_transition.get("blocks_new_entries") is False
    )
    flatten_confirmation = (
        realtime_status.get("sdk_auto_flatten", {}).get("confirmation", {})
        if isinstance(realtime_status.get("sdk_auto_flatten"), dict)
        and isinstance(realtime_status.get("sdk_auto_flatten", {}).get("confirmation"), dict)
        else {}
    )
    validation_end_at = (
        parse_utc_datetime(sdk_config.validation_end_at)
        if sdk_config is not None and sdk_config.validation_end_at
        else None
    )
    generated_datetime = parse_utc_datetime(generated_at)
    validation_session_waiting = bool(
        pending_formal_flatten
        and sdk_config is not None
        and sdk_config.validation_business_date
        and validation_end_at is not None
        and generated_datetime is not None
        and str(window.get("market_date") or "") <= sdk_config.validation_business_date
        and generated_datetime < validation_end_at
        and flatten_confirmation.get("complete") is True
        and int(flatten_confirmation.get("remaining_position_count") or 0) == 0
        and int(flatten_confirmation.get("open_order_count") or 0) == 0
        and int(flatten_confirmation.get("pending_confirmation_count") or 0) == 0
    )
    execution_epoch = (
        read_json(execution_config.test_epoch_state_path)
        if execution_config is not None
        else {}
    )
    execution_epoch = execution_epoch if isinstance(execution_epoch, dict) else {}
    expected_epoch_id = str(
        formal_transition.get("validation_test_epoch_id")
        if validation_test_active
        else formal_transition.get("test_epoch_id")
        or ""
    )
    expected_epoch_start = str(
        (
            formal_transition.get("validation_test_started_at")
            or formal_transition.get("validation_activated_at")
        )
        if validation_test_active
        else (
            formal_transition.get("test_started_at")
            or formal_transition.get("activated_at")
        )
        or ""
    )
    execution_epoch_start = str(execution_epoch.get("test_started_at") or "")
    execution_epoch_consistent = (
        not (formal_test_active or validation_test_active)
        or (
            bool(expected_epoch_start)
            and execution_epoch_start == expected_epoch_start
            and str(execution_epoch.get("test_epoch_id") or "")
            == expected_epoch_id
        )
    )
    runtime_dispatch_requested = bool(realtime_status.get("dispatch_requested", False))
    sdk_paper_channel_armed = bool(
        sdk_config is not None
        and sdk_config.paper_order_dispatch_enabled
        and runtime_dispatch_requested
        and paper_orders_enabled
    )
    if sdk_config is not None:
        effective_paper_orders_enabled = (
            sdk_paper_channel_armed if pending_formal_flatten else runtime_dispatch_enabled
        )
    else:
        effective_paper_orders_enabled = paper_orders_enabled
    new_position_submission_enabled = (
        effective_paper_orders_enabled
        and not pending_formal_flatten
        and execution_epoch_consistent
    )
    readonly_gate_waiting = bool(
        sdk_config is not None
        and sdk_config.two_day_readonly_gate
        and realtime_status.get("readonly_gate_passed") is not True
    )
    paper_account_ready = paper_account_verified(account_state)
    realtime_health_issues = (
        sdk_runtime_health_issues(realtime_status, sdk_config, realtime_alive)
        if sdk_config is not None
        else supervisor_health_issues(
            realtime_config,
            realtime_status,
            expected_pid=realtime_pid,
            process_alive_now=realtime_alive,
        )
    )
    stale_buy_orders = stale_buy_open_orders(
        cleanup_config,
        account_state,
        parse_utc_datetime(str(window["session_started_at"])),
        parse_utc_datetime(generated_at),
    )
    cleanup_enabled = bool(sdk_config is not None or getattr(realtime_config, "run_stale_order_cleanup", False))
    sdk_order_maintenance = realtime_status.get("order_maintenance", {}) if sdk_config is not None else {}
    sdk_order_maintenance = sdk_order_maintenance if isinstance(sdk_order_maintenance, dict) else {}
    cleanup_status = (
        str(sdk_order_maintenance.get("status") or "not_yet_run")
        if sdk_config is not None
        else str(realtime_status.get("stale_order_cleanup_status") or "")
    )
    cleanup_failed = (
        cleanup_status in {"failed", "blocked"}
        if sdk_config is not None
        else int(realtime_status.get("stale_buy_open_order_cleanup_failed_count", 0) or 0) > 0
    )
    actual_runtime_ids = execution_summary.get("runtime_ids_seen_this_cycle", []) if isinstance(execution_summary, dict) else []
    recent_execution_inputs = build_recent_execution_inputs(execution_summary, execution_config)
    if not actual_runtime_ids:
        actual_runtime_ids = sorted(
            {
                str(row.get("runtime_id") or "")
                for row in recent_execution_inputs
                if isinstance(row, dict) and str(row.get("runtime_id") or "")
            }
        )
    execution_runtime_identity = (
        execution_summary.get("runtime_identity", {}) if isinstance(execution_summary, dict) else {}
    )
    if pending_formal_flatten:
        # A pending flatten belongs to the new epoch, while the latest execution
        # summary can still describe the archived epoch. Do not present it as
        # current contract-v1 activity.
        actual_runtime_ids = []
        recent_execution_inputs = []
        execution_runtime_identity = {}
    checks = [
        informational_check_row(
            "m12_47_daemon_alive",
            "M12.47 只作为本地 research/watch 面信息展示，不影响 readiness",
            actual=str(m12_alive),
        ),
        check_row(
            "m15_realtime_daemon_alive",
            "M15 长桥实时运行层存活",
            "pass" if realtime_alive and not realtime_health_issues else "fail",
            actual=pid_health_label(realtime_pid, realtime_alive, realtime_status_generated_at, realtime_status_age_seconds)
            + (f", issues={','.join(realtime_health_issues)}" if realtime_health_issues else ""),
        ),
        check_row(
            "regular_session_window",
            "只在美股常规交易时段提交模拟订单",
            "pass" if window["market_phase"] == "regular_session" else "waiting",
            actual=str(window.get("market_status", "")),
        ),
        check_row(
            "paper_orders_enabled",
            (
                "已武装长桥模拟账户订单提交；当前 SDK 运行配置不启用额外只读门禁"
                if sdk_config is not None and not sdk_config.two_day_readonly_gate
                else "已武装长桥模拟账户订单提交；两日只读验收完成前必须等待"
            ),
            "waiting" if readonly_gate_waiting else ("pass" if effective_paper_orders_enabled else "fail"),
            actual=execution_config_error
            or (
                f"execute_orders={execution_config.execute_orders}, paper_trading_approval={execution_config.paper_trading_approval}, "
                f"runtime_dispatch_enabled={runtime_dispatch_enabled}, runtime_dispatch_requested={runtime_dispatch_requested}, "
                f"readonly_sessions={realtime_status.get('readonly_sessions_passed', 0)}/{realtime_status.get('readonly_sessions_required', 2)}"
            ),
        ),
        check_row(
            "paper_account_verified",
            "账户必须是长桥模拟账户",
            "pass" if paper_account_ready else "fail",
            actual=f"channel={account_state.get('account_channel', '')}, verified={account_state.get('paper_account_verified', '')}",
        ),
        check_row(
            "paper_enabled_config_linked",
            "实时运行层使用模拟订单启用版执行配置",
            "pass" if execution_config_linked else "fail",
            actual=project_path(linked_execution_config_path),
        ),
        check_row(
            "order_safety_boundaries",
            "整股、受限纸面做空、不开期权、常规交易时段、只限日内单",
            "pass" if execution_config and order_safety_ok(execution_config) else "fail",
            actual=execution_config_error or f"RTH={execution_config.outside_rth}, tif={execution_config.time_in_force}",
        ),
        check_row(
            "paper_only_boundaries",
            "禁止实盘和真实资金动作",
            "pass" if paper_only_boundaries_ok(execution_payload, sdk_runtime_boundaries(sdk_config, realtime_config)) else "fail",
            actual=str(execution_payload.get("hard_boundaries", {})),
        ),
        check_row(
            "local_simulation_isolated",
            "长桥实时链路不得读取本地模拟账本",
            "pass" if local_simulation_isolated(realtime_status) else "fail",
            actual=f"local_ref={realtime_status.get('local_ledger_input_ref', '')}",
        ),
        check_row(
            "repair_auxiliary_isolated",
            "修复策略、影子变体和辅助模块不进入长桥实时下单",
            "pass" if repair_auxiliary_isolated(execution_payload) else "fail",
            actual=f"whitelist={len(execution_config.allowed_runtime_ids) if execution_config else 0}",
        ),
        check_row(
            "actual_runtime_ids_seen",
            "值守检查必须展示最近真实执行涉及的 runtime",
            "pass" if execution_summary else "waiting",
            actual=",".join(str(item) for item in actual_runtime_ids) or "none",
        ),
        check_row(
            "recent_execution_input_seen",
            "值守检查必须展示最近执行输入",
            "pass" if recent_execution_inputs else "waiting",
            actual=render_recent_execution_inputs(recent_execution_inputs),
        ),
        check_row(
            "stale_open_buy_order_cleanup",
            "上一交易窗口遗留买入挂单必须在执行新信号前清理或阻断",
            "fail" if stale_buy_orders and (not cleanup_enabled or cleanup_failed) else "pass",
            actual=(
                f"stale_buy_orders={len(stale_buy_orders)}, cleanup_enabled={cleanup_enabled}, "
                f"last_cleanup_status={cleanup_status}, "
                f"cleanup_failed={cleanup_failed}"
            ),
        ),
        check_row(
            "formal_test_flatten_transition",
            "验收持仓清空前只允许平仓，不允许新开仓",
            "waiting" if pending_formal_flatten else "pass",
            actual=(
                f"status={formal_transition.get('status', 'not_configured')}, "
                f"blocker={formal_transition.get('activation_blocker', '')}"
            ),
        ),
        check_row(
            "formal_test_execution_epoch",
            "当前验收或正式测试标记与实时执行器必须使用同一编号和开始时间",
            "fail" if not execution_epoch_consistent else "pass",
            actual=(
                f"formal_epoch={formal_transition.get('test_epoch_id', '')}, "
                f"active_epoch={expected_epoch_id}, "
                f"active_started_at={expected_epoch_start}, "
                f"execution_epoch={execution_epoch.get('test_epoch_id', '')}, "
                f"execution_started_at={execution_epoch_start}"
            ),
        ),
    ]
    fail_count = sum(1 for row in checks if row["status"] == "fail")
    waiting_count = sum(1 for row in checks if row["status"] == "waiting")
    pass_count = sum(1 for row in checks if row["status"] == "pass")
    informational_count = sum(1 for row in checks if row["status"] == "informational")
    if fail_count:
        readiness_status = "blocked_opening_trade_watch"
    elif validation_session_waiting:
        readiness_status = (
            "ready_for_validation_session_start"
            if window["market_phase"] == "regular_session"
            else "armed_waiting_validation_session"
        )
    elif pending_formal_flatten:
        readiness_status = "ready_for_paper_exit_only" if window["market_phase"] == "regular_session" else "armed_waiting_flatten_session"
    elif window["market_phase"] == "regular_session":
        readiness_status = "ready_for_longbridge_paper_orders"
    else:
        readiness_status = "armed_waiting_regular_session"
    return {
        "schema_version": "m15.opening-trade-readiness.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "readiness_status": readiness_status,
        "market_window": window,
        "paper_order_submission_enabled": effective_paper_orders_enabled,
        "new_position_submission_enabled": new_position_submission_enabled,
        "validation_session_waiting": validation_session_waiting,
        "formal_test_transition": formal_transition,
        "m12_47_daemon_alive": m12_alive,
        "m15_realtime_daemon_alive": realtime_alive,
        "m15_realtime_daemon_pid": realtime_pid or "",
        "m15_realtime_status_generated_at": realtime_status_generated_at,
        "m15_realtime_status_age_seconds": realtime_status_age_seconds,
        "paper_account_verified": paper_account_ready,
        "execution_runtime_identity": execution_runtime_identity,
        "actual_runtime_ids_seen": actual_runtime_ids,
        "recent_execution_inputs": recent_execution_inputs,
        "pass_count": pass_count,
        "waiting_count": waiting_count,
        "fail_count": fail_count,
        "informational_count": informational_count,
        "checks": checks,
        "runtime_whitelist": list(execution_config.allowed_runtime_ids) if execution_config else [],
        "boundaries": {
            "paper_simulated_only": True,
            "live_execution": False,
            "real_money_actions": False,
            "fractional_shares": False,
            "short_selling": bool(execution_config and execution_config.paper_short_testing_enabled),
            "options": False,
            "margin_financing": False,
            "manual_m12_37_once": False,
            "local_simulation_as_order_source": False,
        },
        "input_refs": {
            "m12_47_status": project_path(config.m12_47_status_path),
            "realtime_supervisor_config": project_path(config.realtime_supervisor_config_path),
            "realtime_runtime_engine": config.realtime_runtime_engine,
            "sdk_runtime_config": project_path(config.sdk_runtime_config_path),
            "execution_config": project_path(config.execution_config_path),
            "execution_summary": project_path(execution_config.output_dir / EXECUTION_SUMMARY_JSON) if execution_config else "",
            "realtime_account_state": project_path(config.realtime_account_state_path),
            "realtime_supervisor_status": (
                "legacy_cli_not_used_by_sdk"
                if sdk_config is not None
                else project_path(config.realtime_supervisor_status_path)
            ),
            "sdk_runtime_status": project_path(config.sdk_runtime_status_path),
        },
        "local_research_non_blocking": {
            "m12_47_status_only": True,
        },
        "plain_language_result": plain_result(readiness_status, fail_count, waiting_count, window),
    }


def check_row(check: str, required_result: str, status: str, **extra: Any) -> dict[str, Any]:
    row = {"check": check, "required_result": required_result, "status": status}
    row.update(extra)
    return row


def pid_health_label(pid: int | None, alive: bool, status_generated_at: str, status_age_seconds: int | None) -> str:
    pid_text = f"pid={pid}" if pid else "pid=missing"
    process_text = "alive" if alive else "dead"
    if status_age_seconds is None:
        return f"{pid_text}, process={process_text}, status_generated_at={status_generated_at or 'missing'}"
    return (
        f"{pid_text}, process={process_text}, "
        f"status_generated_at={status_generated_at or 'missing'}, status_age_seconds={status_age_seconds}"
    )


def artifact_age_seconds(generated_at: str, now_iso: str) -> int | None:
    if not generated_at:
        return None
    try:
        generated_dt = parse_utc_datetime(generated_at)
        now_dt = parse_utc_datetime(now_iso)
    except ValueError:
        return None
    return max(0, int((now_dt - generated_dt).total_seconds()))


def paper_account_verified(account_state: dict[str, Any]) -> bool:
    if not account_state:
        return False
    if str(account_state.get("account_channel") or account_state.get("channel") or "") != "lb_papertrading":
        return False
    if account_state.get("paper_account_verified") is False:
        return False
    if account_state.get("live_execution") is True or account_state.get("real_money_actions") is True:
        return False
    return True


def order_safety_ok(execution_config: Any) -> bool:
    controlled_short_testing = (
        execution_config.allow_short_selling
        and execution_config.paper_short_testing_enabled
        and bool(execution_config.paper_short_runtime_ids)
        and bool(execution_config.short_test_epoch_id)
        and execution_config.hard_boundaries.get("short_selling") is True
    )
    return (
        execution_config.outside_rth == "RTH_ONLY"
        and execution_config.time_in_force.lower() == "day"
        and not execution_config.allow_fractional_shares
        and (not execution_config.allow_short_selling or controlled_short_testing)
        and not execution_config.allow_options
        and not execution_config.allow_margin_financing
    )


def paper_only_boundaries_ok(execution_payload: dict[str, Any], supervisor_boundaries: dict[str, bool]) -> bool:
    boundaries = execution_payload.get("hard_boundaries", {})
    return (
        boundaries.get("paper_simulated_only") is True
        and boundaries.get("live_execution") is False
        and boundaries.get("real_money_actions") is False
        and boundaries.get("margin_financing") is False
        and supervisor_boundaries.get("paper_simulated_only") is True
        and supervisor_boundaries.get("live_execution") is False
        and supervisor_boundaries.get("real_money_actions") is False
    )


def sdk_runtime_boundaries(sdk_config: Any, realtime_config: Any) -> dict[str, bool]:
    if sdk_config is None:
        return realtime_config.hard_boundaries
    return {
        "paper_simulated_only": bool(sdk_config.paper_trading_only),
        "live_execution": bool(sdk_config.live_execution),
        "real_money_actions": bool(sdk_config.real_money_actions),
    }


def sdk_runtime_health_issues(status: dict[str, Any], sdk_config: Any, process_alive_now: bool) -> list[str]:
    issues: list[str] = []
    if not process_alive_now:
        issues.append("process_not_alive")
    if not status:
        issues.append("status_missing")
    elif status.get("status") != "running":
        issues.append(f"runtime_status={status.get('status') or 'missing'}")
    if status.get("sdk_connected") is not True:
        issues.append("sdk_not_connected")
    if status.get("runtime_engine") not in {"", "sdk"}:
        issues.append("runtime_engine_not_sdk")
    expected_fingerprint = sdk_config_fingerprint(sdk_config) if sdk_config is not None else ""
    if expected_fingerprint and str(status.get("config_fingerprint") or "") != expected_fingerprint:
        issues.append("sdk_config_fingerprint_drift")
    expected_trading_fingerprint = (
        sdk_trading_universe_fingerprint(sdk_config)
        if sdk_config is not None
        else ""
    )
    if expected_trading_fingerprint and str(
        status.get("trading_universe_fingerprint") or ""
    ) != expected_trading_fingerprint:
        issues.append("sdk_trading_universe_fingerprint_drift")
    expected_count = len(sdk_configured_trading_symbols(sdk_config)) if sdk_config is not None else 0
    expected_coverage = f"{expected_count}/{expected_count}" if expected_count else ""
    actual_trading_coverage = str(
        status.get("trading_market_data_coverage")
        or status.get("trading_subscription_coverage")
        or status.get("subscription_coverage")
        or ""
    )
    if expected_coverage and actual_trading_coverage != expected_coverage:
        issues.append("sdk_trading_market_data_coverage_incomplete")
    trading_daily_ready = status.get("trading_daily_context_ready")
    if trading_daily_ready is None and sdk_config is not None:
        trading_daily_ready = sdk_daily_context_is_complete(
            sdk_config,
            str(status.get("daily_context_state") or ""),
            int(status.get("daily_context_row_count", 0) or 0),
            [str(value) for value in (status.get("daily_context_failed_symbols") or [])],
        )
    if sdk_config is not None and trading_daily_ready is not True:
        issues.append("sdk_daily_context_incomplete")
    if status.get("account_snapshot_healthy") is not True:
        issues.append("sdk_account_snapshot_stale")
    if status.get("account_snapshot_circuit_open") is True:
        issues.append("sdk_account_snapshot_circuit_open")
    worker_status = str(status.get("account_snapshot_worker_status") or "")
    if worker_status and worker_status not in {"healthy", "healthy_circuit_probe", "healthy_circuit_recovered"}:
        issues.append(f"sdk_account_worker_status={worker_status}")
    return issues


def local_simulation_isolated(realtime_status: dict[str, Any]) -> bool:
    if not realtime_status:
        return True
    return (
        realtime_status.get("local_simulation_isolated") is True
        and str(realtime_status.get("local_ledger_input_ref") or "") == ""
        and realtime_status.get("legacy_fast_queue_used") is False
        and realtime_status.get("manual_m12_37_once_used") is False
    )


def repair_auxiliary_isolated(execution_payload: dict[str, Any]) -> bool:
    layering = execution_payload.get("runtime_layering", {})
    local_only = layering.get("local_repair_or_shadow_only", [])
    auxiliary = layering.get("auxiliary_modules_local_only", [])
    candidates = set(str(item) for item in layering.get("longbridge_realtime_candidates", []))
    forbidden = set(str(item) for item in local_only + auxiliary if not str(item).startswith("all "))
    return bool(local_only and auxiliary) and not (candidates & forbidden)


def plain_result(status: str, fail_count: int, waiting_count: int, window: dict[str, Any]) -> str:
    if status == "ready_for_longbridge_paper_orders":
        return "开盘值守已就绪：长桥模拟账户订单提交已启用，实时链路会在常规交易时段按风控提交模拟订单。"
    if status == "armed_waiting_regular_session":
        return f"开盘值守已武装：当前是{window.get('market_status')}，等待美股常规交易时段；到点后只走长桥模拟账户。"
    if status == "ready_for_paper_exit_only":
        return "长桥模拟账户仅允许平仓：先清除 SDK 验收持仓，清仓确认完成后才启用新开仓。"
    if status == "ready_for_validation_session_start":
        return "今晚自然信号验收条件已满足：SDK 正在按配置自动开启纸面账户验收，不制造订单、不降低策略门槛。"
    if status == "armed_waiting_validation_session":
        return f"今晚自然信号验收已武装：当前是{window.get('market_status')}，到常规交易时段自动开启纸面账户全链路验收。"
    if status == "armed_waiting_flatten_session":
        return f"清仓链路已武装：当前是{window.get('market_status')}，下个常规交易时段只处理验收持仓退出。"
    return f"开盘值守未就绪：{fail_count} 个检查失败，{waiting_count} 个检查等待交易窗口。"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# M15 Opening Trade Readiness",
        "",
        f"- Status: `{payload['readiness_status']}`",
        f"- Paper order submission enabled: `{payload['paper_order_submission_enabled']}`",
        f"- M12.47 daemon alive: `{payload['m12_47_daemon_alive']}`",
        f"- M15 realtime daemon alive: `{payload['m15_realtime_daemon_alive']}`",
        f"- Paper account verified: `{payload['paper_account_verified']}`",
        f"- Actual runtimes seen: `{','.join(payload.get('actual_runtime_ids_seen', [])) or 'none'}`",
        f"- Pass / waiting / fail / informational: `{payload['pass_count']}/{payload['waiting_count']}/{payload['fail_count']}/{payload.get('informational_count', 0)}`",
        f"- Result: {payload['plain_language_result']}",
        "",
        "| Check | Status | Actual |",
        "|---|---|---|",
    ]
    for row in payload["checks"]:
        lines.append(f"| {row['check']} | {row['status']} | {row.get('actual', '')} |")
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- 只允许长桥模拟账户，不允许实盘或真实资金动作。",
            "- 不做碎股、不做期权；只允许三条明确白名单的纸面做空测试运行单元，其他做空一律阻断。",
            "- 修复策略、影子变体和辅助模块继续留在本地模拟。",
            "- 长桥实时链路不读取本地模拟账本，也不使用旧快速队列作为下单来源。",
            "",
        ]
    )
    return "\n".join(lines)


def build_recent_execution_inputs(
    execution_summary: dict[str, Any],
    execution_config: Any | None,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    summary_rows = execution_summary.get("recent_execution_inputs", []) if isinstance(execution_summary, dict) else []
    if isinstance(summary_rows, list):
        normalized_rows = [row for row in summary_rows if isinstance(row, dict)]
        if normalized_rows:
            return normalized_rows[:limit]
    if execution_config is None or not execution_config.realtime_signal_events_path.exists():
        return []
    rows = read_execution_jsonl(execution_config.realtime_signal_events_path)
    return [
        {
            "signal_id": str(row.get("signal_id") or ""),
            "runtime_id": str(row.get("runtime_id") or ""),
            "symbol": str(row.get("symbol") or ""),
            "created_at": str(row.get("created_at") or row.get("generated_at") or ""),
        }
        for row in rows[-limit:]
        if isinstance(row, dict)
    ]


def render_recent_execution_inputs(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "none"
    return "; ".join(
        f"{row.get('signal_id', '')}/{row.get('runtime_id', '')}/{row.get('symbol', '')}/{row.get('created_at', '')}"
        for row in rows
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
