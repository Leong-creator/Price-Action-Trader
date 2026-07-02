#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from scripts.longbridge_cli_env import build_longbridge_cli_env
from scripts.m12_readonly_auth_preflight_lib import clean_cli_text
from scripts.m15_longbridge_realtime_account_state_lib import is_open_order_row
from scripts.m15_longbridge_realtime_execution_lib import DEFAULT_DAILY_DIR, parse_utc_datetime, project_path, to_iso


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_stale_order_cleanup.json"
DEFAULT_ACCOUNT_STATE = DEFAULT_OUTPUT_DIR / "m15_longbridge_realtime_account_state.json"
SUMMARY_JSON = "m15_longbridge_realtime_stale_order_cleanup.json"
LEDGER_JSONL = "m15_longbridge_realtime_stale_order_cleanup_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_stale_order_cleanup.md"

CommandRunner = Callable[[list[str]], Any]


@dataclass(frozen=True, slots=True)
class StaleOrderCleanupConfig:
    stage: str
    title: str
    account_state_path: Path
    output_dir: Path
    required_account_channel: str
    cli_name: str
    cli_timeout_seconds: int
    cancel_stale_buy_orders: bool
    cleanup_current_session_stale_buy_orders: bool
    stale_buy_order_ttl_seconds: int
    max_cancel_per_run: int
    hard_boundaries: dict[str, bool]

    def __post_init__(self) -> None:
        validate_config(self)


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StaleOrderCleanupConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    cleanup = payload.get("stale_order_cleanup", {})
    return StaleOrderCleanupConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_stale_order_cleanup")),
        title=str(payload.get("title", "长桥模拟账户旧挂单清理")),
        account_state_path=resolve_repo_path(inputs.get("account_state", DEFAULT_ACCOUNT_STATE)),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        required_account_channel=str(cleanup.get("required_account_channel", "lb_papertrading")),
        cli_name=str(cleanup.get("cli_name", "longbridge")),
        cli_timeout_seconds=int(cleanup.get("cli_timeout_seconds", 6)),
        cancel_stale_buy_orders=bool(cleanup.get("cancel_stale_buy_orders", True)),
        cleanup_current_session_stale_buy_orders=bool(cleanup.get("cleanup_current_session_stale_buy_orders", True)),
        stale_buy_order_ttl_seconds=int(cleanup.get("stale_buy_order_ttl_seconds", 900)),
        max_cancel_per_run=int(cleanup.get("max_cancel_per_run", 20)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: StaleOrderCleanupConfig) -> None:
    if config.stage != "M15.longbridge_realtime_stale_order_cleanup":
        raise ValueError("M15 stale order cleanup stage drift")
    if config.required_account_channel != "lb_papertrading":
        raise ValueError("M15 stale order cleanup requires Longbridge paper-trading account channel")
    if config.cli_timeout_seconds <= 0:
        raise ValueError("M15 stale order cleanup CLI timeout must be positive")
    if not config.cancel_stale_buy_orders:
        raise ValueError("M15 stale order cleanup must be enabled explicitly")
    if config.stale_buy_order_ttl_seconds <= 0:
        raise ValueError("M15 stale order cleanup TTL must be positive")
    if config.max_cancel_per_run <= 0:
        raise ValueError("M15 stale order cleanup max_cancel_per_run must be positive")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 stale order cleanup must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("M15 stale order cleanup cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("M15 stale order cleanup cannot enable real money actions")
    if config.hard_boundaries.get("cancel_sell_orders", False):
        raise ValueError("M15 stale order cleanup cannot cancel sell orders")


def run_stale_order_cleanup(
    config: StaleOrderCleanupConfig | None = None,
    *,
    generated_at: str | None = None,
    session_started_at: str,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    session_start = parse_utc_datetime(session_started_at)
    account_state = read_json(config.account_state_path)
    blockers = account_blockers(config, account_state)
    stale_orders = stale_buy_open_orders(config, account_state, session_start, now)
    runner = command_runner or (lambda command: run_command(command, timeout_seconds=config.cli_timeout_seconds))
    cli_path = shutil.which(config.cli_name) or config.cli_name
    ledger_rows: list[dict[str, Any]] = []
    canceled_count = 0
    failed_count = 0
    if not blockers:
        for order in stale_orders[: config.max_cancel_per_run]:
            command, command_blockers = cancel_command(cli_path, order)
            response: dict[str, Any]
            status = "blocked_not_canceled"
            if command_blockers:
                response = {"blockers": command_blockers, "command": redact_command(command)}
                failed_count += 1
            else:
                result = runner(command)
                response = command_response(result, command)
                if response.get("canceled"):
                    status = "canceled"
                    canceled_count += 1
                else:
                    status = str(response.get("status", "cancel_failed"))
                    failed_count += 1
            ledger_rows.append(cleanup_row(config, generated_at_iso, session_started_at, order, status, response))
    skipped_count = max(0, len(stale_orders) - len(ledger_rows))
    summary_status = summary_status_for(blockers, stale_orders, canceled_count, failed_count, skipped_count)
    summary = {
        "schema_version": "m15.longbridge-realtime-stale-order-cleanup.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at_iso,
        "session_started_at": session_started_at,
        "source_mode": "longbridge_paper_account_open_orders_only",
        "cleanup_status": summary_status,
        "blockers": blockers,
        "paper_account_verified": bool(account_state.get("paper_account_verified") is True and not blockers),
        "account_channel": str(account_state.get("account_channel") or ""),
        "stale_buy_open_order_count": len(stale_orders),
        "current_session_stale_buy_open_order_count": sum(
            1 for row in stale_orders if row.get("cleanup_reason") == "current_session_buy_order_ttl_expired"
        ),
        "canceled_count": canceled_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "max_cancel_per_run": config.max_cancel_per_run,
        "cleanup_current_session_stale_buy_orders": config.cleanup_current_session_stale_buy_orders,
        "stale_buy_order_ttl_seconds": config.stale_buy_order_ttl_seconds,
        "stale_buy_order_symbols": [base_symbol(str(row.get("symbol") or "")) for row in stale_orders],
        "cancel_sell_orders": False,
        "local_simulation_isolated": True,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "inputs": {"account_state": project_path(config.account_state_path)},
        "outputs": {
            "summary": project_path(config.output_dir / SUMMARY_JSON),
            "ledger": project_path(config.output_dir / LEDGER_JSONL),
            "report": project_path(config.output_dir / REPORT_MD),
        },
        "plain_language_result": plain_language(summary_status, len(stale_orders), canceled_count, failed_count),
    }
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / SUMMARY_JSON, summary)
    if ledger_rows:
        append_jsonl(config.output_dir / LEDGER_JSONL, ledger_rows)
    (config.output_dir / REPORT_MD).write_text(render_report(summary, ledger_rows), encoding="utf-8")
    return summary


def account_blockers(config: StaleOrderCleanupConfig, account_state: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not account_state:
        blockers.append("account_state_missing")
    if str(account_state.get("account_channel") or "") != config.required_account_channel:
        blockers.append("account_channel_not_paper")
    if account_state.get("paper_account_verified") is not True:
        blockers.append("paper_account_not_verified")
    if account_state.get("live_execution") is True or account_state.get("real_money_actions") is True:
        blockers.append("live_or_real_money_boundary_enabled")
    return blockers


def stale_buy_open_orders(
    config: StaleOrderCleanupConfig,
    account_state: dict[str, Any],
    session_start: datetime,
    now: datetime,
) -> list[dict[str, Any]]:
    rows = account_state.get("open_orders") if isinstance(account_state.get("open_orders"), list) else []
    stale: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or not is_open_order_row(row):
            continue
        if str(row.get("side") or "").strip().lower() != "buy":
            continue
        created_at = parse_order_time(row.get("created_at"))
        if not created_at:
            continue
        order = dict(row)
        if created_at < session_start:
            order["cleanup_reason"] = "previous_session_buy_order"
            stale.append(order)
            continue
        age_seconds = max(0, int((now - created_at).total_seconds()))
        if config.cleanup_current_session_stale_buy_orders and age_seconds >= config.stale_buy_order_ttl_seconds:
            order["cleanup_reason"] = "current_session_buy_order_ttl_expired"
            order["age_seconds"] = str(age_seconds)
            stale.append(order)
    return stale


def parse_order_time(value: Any) -> datetime | None:
    raw = str(value or "")
    if not raw:
        return None
    try:
        return parse_utc_datetime(raw)
    except ValueError:
        return None


def cancel_command(cli_path: str, order: dict[str, Any]) -> tuple[list[str], list[str]]:
    order_id = str(order.get("order_id") or order.get("id") or "")
    blockers: list[str] = []
    if not order_id:
        blockers.append("missing_order_id")
    if str(order.get("side") or "").strip().lower() != "buy":
        blockers.append("cancel_sell_order_forbidden")
    if blockers:
        return [], blockers
    command = [cli_path, "order", "cancel", order_id, "--yes", "--format", "json"]
    assert_cancel_command(command)
    return command, []


def assert_cancel_command(command: list[str]) -> None:
    args = command[1:]
    if len(args) < 3 or args[0] != "order" or args[1] != "cancel":
        raise ValueError(f"Longbridge stale order cleanup command is not a cancel command: {args}")
    if "--yes" not in args or "--format" not in args:
        raise ValueError(f"Longbridge stale order cleanup command is missing safety flags: {args}")


def run_command(command: list[str], *, timeout_seconds: int = 30) -> Any:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
        env=build_longbridge_cli_env(),
    )


def command_response(result: Any, command: list[str]) -> dict[str, Any]:
    returncode = int(getattr(result, "returncode", 1))
    stdout = str(getattr(result, "stdout", ""))
    stderr = clean_cli_text(str(getattr(result, "stderr", "")))
    if returncode != 0:
        return {
            "canceled": False,
            "status": "cancel_failed",
            "error": (stderr or clean_cli_text(stdout))[:300],
            "command": redact_command(command),
        }
    response = parse_json(stdout)
    return {
        "canceled": True,
        "status": "canceled",
        "response": response,
        "command": redact_command(command),
    }


def cleanup_row(
    config: StaleOrderCleanupConfig,
    generated_at: str,
    session_started_at: str,
    order: dict[str, Any],
    status: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stage": config.stage,
        "generated_at": generated_at,
        "session_started_at": session_started_at,
        "order_id": str(order.get("order_id") or order.get("id") or ""),
        "symbol": base_symbol(str(order.get("symbol") or "")),
        "side": str(order.get("side") or ""),
        "order_type": str(order.get("order_type") or ""),
        "quantity": str(order.get("quantity") or ""),
        "price": str(order.get("price") or ""),
        "created_at": str(order.get("created_at") or ""),
        "cleanup_reason": str(order.get("cleanup_reason") or ""),
        "age_seconds": str(order.get("age_seconds") or ""),
        "cleanup_status": status,
        "response": response,
        "local_simulation_ignored": True,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
    }


def summary_status_for(blockers: list[str], stale_orders: list[dict[str, Any]], canceled_count: int, failed_count: int, skipped_count: int) -> str:
    if blockers:
        return "blocked_cleanup_not_safe"
    if not stale_orders:
        return "no_stale_buy_open_orders"
    if failed_count or skipped_count:
        return "partial_cleanup_failed"
    if canceled_count:
        return "stale_buy_open_orders_canceled"
    return "no_stale_buy_open_orders"


def plain_language(status: str, stale_count: int, canceled_count: int, failed_count: int) -> str:
    if status == "stale_buy_open_orders_canceled":
        return f"已清理 {canceled_count} 个长桥模拟账户旧买入挂单，释放被旧挂单占用的模拟仓位；卖出保护单不会被撤。"
    if status == "no_stale_buy_open_orders":
        return "没有发现需要清理的旧买入挂单。"
    if status == "partial_cleanup_failed":
        return f"发现 {stale_count} 个旧买入挂单，已撤 {canceled_count} 个，失败 {failed_count} 个；开盘前需要继续检查。"
    return "旧挂单清理没有通过安全检查，未执行撤单。"


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 长桥模拟账户旧挂单清理",
        "",
        f"- 状态：`{summary['cleanup_status']}`",
        f"- 旧买入挂单：`{summary['stale_buy_open_order_count']}`",
        f"- 已撤：`{summary['canceled_count']}`",
        f"- 失败：`{summary['failed_count']}`",
        f"- 说明：{summary['plain_language_result']}",
        "",
        "## 订单",
    ]
    if not rows:
        lines.append("- 无")
    for row in rows:
        lines.append(
            f"- `{row['symbol']}` `{row['side']}` `{row['quantity']}` @ `{row['price']}`：`{row['cleanup_status']}`"
        )
    return "\n".join(lines) + "\n"


def redact_command(command: list[str]) -> list[str]:
    return [item for item in command if item != "--yes"]


def base_symbol(symbol: str) -> str:
    return symbol.upper().split(".")[0]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_json(text: str) -> Any:
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
