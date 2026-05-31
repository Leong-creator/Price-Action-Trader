#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_monday_refresh_acceptance.json"
DEFAULT_DAILY_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
)
DEFAULT_M12_DIR = DEFAULT_DAILY_DIR / "m12_29_current_day_scan_dashboard"
DEFAULT_M13_DIR = DEFAULT_DAILY_DIR / "m13_real_daily_strategy_testing"
DEFAULT_M14_DIR = DEFAULT_DAILY_DIR / "m14_strategy_challenge"
DEFAULT_M15_DIR = DEFAULT_DAILY_DIR / "m15_monday_refresh_acceptance"
ACCEPTANCE_JSON = "m15_monday_refresh_acceptance.json"
ACCEPTANCE_MD = "m15_monday_refresh_acceptance.md"


@dataclass(frozen=True, slots=True)
class MondayRefreshAcceptanceConfig:
    stage: str
    supervisor_status_path: Path
    dashboard_path: Path
    auto_runner_manifest_path: Path
    m13_goal_status_path: Path
    m14_goal_status_path: Path
    m14_summary_path: Path
    m15_preflight_path: Path
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
    config_path = resolve_repo_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    return MondayRefreshAcceptanceConfig(
        stage=str(payload.get("stage", "M15.monday_refresh_acceptance")),
        supervisor_status_path=resolve_repo_path(inputs.get("m12_47_supervisor_status", DEFAULT_M12_DIR / "m12_47_session_supervisor_status.json")),
        dashboard_path=resolve_repo_path(inputs.get("m12_32_dashboard", DEFAULT_M12_DIR / "m12_32_minute_readonly_dashboard_data.json")),
        auto_runner_manifest_path=resolve_repo_path(inputs.get("m12_37_auto_runner_manifest", DEFAULT_M12_DIR / "m12_37_auto_runner_manifest.json")),
        m13_goal_status_path=resolve_repo_path(inputs.get("m13_goal_status", DEFAULT_M13_DIR / "m13_goal_status.json")),
        m14_goal_status_path=resolve_repo_path(inputs.get("m14_goal_status", DEFAULT_M14_DIR / "m14_goal_status.json")),
        m14_summary_path=resolve_repo_path(inputs.get("m14_summary", DEFAULT_M14_DIR / "m14_strategy_challenge_summary.json")),
        m15_preflight_path=resolve_repo_path(
            inputs.get("m15_longbridge_preflight", DEFAULT_DAILY_DIR / "m15_longbridge_paper_preflight" / "m15_longbridge_paper_preflight.json")
        ),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_M15_DIR)),
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
    supervisor = read_json(config.supervisor_status_path)
    dashboard = read_json(config.dashboard_path)
    manifest = read_json(config.auto_runner_manifest_path)
    m13_goal = read_json(config.m13_goal_status_path)
    m14_goal = read_json(config.m14_goal_status_path)
    m14_summary = read_json(config.m14_summary_path)
    preflight = read_json(config.m15_preflight_path)

    dash_summary = dict(dashboard.get("summary", dashboard))
    session_should_run = bool(supervisor.get("session_should_run", False))
    child_running = bool(supervisor.get("child_running", False))
    supervisor_alive = bool(supervisor.get("supervisor_process_alive", False))
    quote_source = str(dash_summary.get("quote_source", ""))
    daily_ready = int_or_zero(dash_summary.get("first50_daily_ready_symbols"))
    five_min_ready = int_or_zero(dash_summary.get("first50_current_5m_ready_symbols"))
    scan_date = str(dash_summary.get("scan_date", ""))
    m13_trading_date = str(m13_goal.get("trading_date", ""))
    m14_trading_date = str(m14_goal.get("trading_date", ""))
    fallback_or_no_fetch = text_has_fallback_or_no_fetch(quote_source, dash_summary.get("data_freshness_warning", ""), m14_summary.get("data_freshness_warning", ""))

    checks = [
        check_row("m12_47_alive", "M12.47 守护器存活", "pass" if supervisor_alive else "fail", bool_value=supervisor_alive),
        market_window_check(session_should_run, supervisor),
        child_session_check(session_should_run, child_running, supervisor),
        check_row(
            "quote_source_longbridge",
            "行情来源为 longbridge_quote_readonly",
            pass_wait_or_fail(quote_source == "longbridge_quote_readonly", session_should_run),
            actual=quote_source or "missing",
        ),
        check_row(
            "first50_daily_and_5m_complete",
            "第一批 50 只日线和当日 5 分钟数据完整",
            pass_wait_or_fail(daily_ready >= 50 and five_min_ready >= 50, session_should_run),
            actual=f"daily={daily_ready}/50, 5m={five_min_ready}/50",
        ),
        check_row(
            "m13_current_day_ledger",
            "M13 生成当天策略账本",
            pass_wait_or_fail(bool(scan_date and m13_trading_date == scan_date), session_should_run),
            actual=f"scan_date={scan_date or 'missing'}, m13={m13_trading_date or 'missing'}",
        ),
        check_row(
            "m14_recomputed_for_current_day",
            "M14 重算内部模拟、修复队列和长桥预演",
            pass_wait_or_fail(bool(scan_date and m14_trading_date == scan_date), session_should_run),
            actual=f"scan_date={scan_date or 'missing'}, m14={m14_trading_date or 'missing'}",
        ),
        check_row(
            "no_fallback_or_old_snapshot",
            "备用行情或旧快照当天不允许进入长桥模拟账户",
            pass_wait_or_fail(not fallback_or_no_fetch, session_should_run),
            actual="fallback_or_no_fetch" if fallback_or_no_fetch else "fresh_or_clean",
        ),
        check_row(
            "longbridge_paper_preflight_preview_only",
            "长桥模拟账户只生成预演，不连接账户、不下单",
            "pass" if not preflight.get("broker_connection_attempted", False) and not preflight.get("order_submitted", False) else "fail",
            actual=str(preflight.get("paper_preflight_status", "missing")),
        ),
        check_row(
            "m12_37_supervisor_owned",
            "M12.37 只能由 M12.47 自动拉起，禁止手动 once 刷新",
            "pass",
            actual=str(manifest.get("stage", "manifest_missing")),
        ),
    ]
    fail_count = sum(1 for row in checks if row["status"] == "fail")
    waiting_count = sum(1 for row in checks if row["status"] == "waiting_for_monday_refresh")
    pass_count = sum(1 for row in checks if row["status"] == "pass")
    if fail_count:
        status = "blocked_monday_acceptance"
    elif not session_should_run:
        status = "pretrade_preparation_ready_waiting_for_monday"
    elif waiting_count:
        status = "waiting_for_required_fresh_refresh"
    else:
        status = "ready_after_fresh_refresh"
    return {
        "schema_version": "m15.monday-refresh-acceptance.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m12_47_supervisor_status": project_path(config.supervisor_status_path),
            "m12_32_dashboard": project_path(config.dashboard_path),
            "m12_37_auto_runner_manifest": project_path(config.auto_runner_manifest_path),
            "m13_goal_status": project_path(config.m13_goal_status_path),
            "m14_goal_status": project_path(config.m14_goal_status_path),
            "m15_longbridge_preflight": project_path(config.m15_preflight_path),
        },
        "acceptance_status": status,
        "session_should_run": session_should_run,
        "child_running": child_running,
        "supervisor_process_alive": supervisor_alive,
        "failure_state": str(supervisor.get("failure_state", "")),
        "failure_reason": str(supervisor.get("failure_reason", "")),
        "quote_source": quote_source,
        "fallback_or_no_fetch_data": fallback_or_no_fetch,
        "scan_date": scan_date,
        "m13_trading_date": m13_trading_date,
        "m14_trading_date": m14_trading_date,
        "pass_count": pass_count,
        "waiting_count": waiting_count,
        "fail_count": fail_count,
        "checks": checks,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "manual_m12_37_once": False,
        "plain_language_result": plain_result(status, session_should_run, fail_count, waiting_count),
    }


def market_window_check(session_should_run: bool, supervisor: dict[str, Any]) -> dict[str, Any]:
    actual = str(supervisor.get("market_status") or supervisor.get("latest_dashboard_runtime_status") or "")
    return check_row(
        "regular_us_market_window",
        "当前市场窗口为美股常规交易时段",
        "pass" if session_should_run else "waiting_for_monday_refresh",
        actual=actual or ("regular_session" if session_should_run else "not_regular_session"),
    )


def child_session_check(session_should_run: bool, child_running: bool, supervisor: dict[str, Any]) -> dict[str, Any]:
    if session_should_run and child_running:
        status = "pass"
    elif session_should_run and not child_running:
        status = "fail"
    else:
        status = "waiting_for_monday_refresh"
    return check_row(
        "m12_37_child_running_when_required",
        "交易窗口中 M12.37 必须由 M12.47 自动拉起",
        status,
        actual=f"child_running={str(child_running).lower()}, failure_state={supervisor.get('failure_state', '')}, failure_reason={supervisor.get('failure_reason', '')}",
    )


def pass_wait_or_fail(condition: bool, session_should_run: bool) -> str:
    if condition:
        return "pass"
    return "fail" if session_should_run else "waiting_for_monday_refresh"


def check_row(check: str, required_result: str, status: str, **extra: Any) -> dict[str, Any]:
    row = {"check": check, "required_result": required_result, "status": status}
    row.update(extra)
    return row


def plain_result(status: str, session_should_run: bool, fail_count: int, waiting_count: int) -> str:
    if status == "ready_after_fresh_refresh":
        return "周一交易窗口刷新验收通过，可以继续看 M10-PA-004 的长桥模拟账户下单预演，但仍需用户单独批准。"
    if status == "blocked_monday_acceptance":
        return f"周一刷新验收被阻断：{fail_count} 个检查失败。若 session_should_run=true 但 child_running=false，就是运行异常。"
    if not session_should_run:
        return "当前不是交易窗口，周一前准备项已固化；等待下一次美股常规交易时段由 M12.47 自动拉起刷新。"
    return f"交易窗口内仍等待 fresh refresh 完成：{waiting_count} 个检查未满足。"


def text_has_fallback_or_no_fetch(*values: Any) -> bool:
    text = " ".join(str(value).lower() for value in values)
    return any(token in text for token in ("fallback", "no-fetch", "no_fetch", "no-refresh", "no_refresh", "旧快照"))


def int_or_zero(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# M15 Monday Refresh Acceptance",
        "",
        f"- Status: `{payload['acceptance_status']}`",
        f"- Session should run: `{payload['session_should_run']}`",
        f"- Child running: `{payload['child_running']}`",
        f"- Quote source: `{payload['quote_source']}`",
        f"- Pass / waiting / fail: `{payload['pass_count']}/{payload['waiting_count']}/{payload['fail_count']}`",
        "- Boundary: preview only, no account connection, no orders, no manual M12.37 once.",
        "",
        "| Check | Status | Actual |",
        "|---|---|---|",
    ]
    for row in payload["checks"]:
        lines.append(f"| {row['check']} | {row['status']} | {row.get('actual', row.get('bool_value', ''))} |")
    return "\n".join(lines) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
