#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from scripts.longbridge_cli_env import build_longbridge_cli_env
from scripts.m12_readonly_auth_preflight_lib import clean_cli_text
from scripts.m15_longbridge_realtime_execution_lib import DEFAULT_DAILY_DIR, project_path, to_iso


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_realtime_execution"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_realtime_account_state.json"
ACCOUNT_STATE_JSON = "m15_longbridge_realtime_account_state.json"
SUMMARY_JSON = "m15_longbridge_realtime_account_state_summary.json"
LEDGER_JSONL = "m15_longbridge_realtime_account_state_ledger.jsonl"
REPORT_MD = "m15_longbridge_realtime_account_state.md"
MONEY = Decimal("0.01")
ZERO = Decimal("0")

CommandRunner = Callable[[list[str]], Any]


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class RealtimeAccountStateConfig:
    stage: str
    title: str
    output_dir: Path
    account_state_path: Path
    cli_name: str
    required_account_channel: str
    cli_timeout_seconds: int
    hard_boundaries: dict[str, bool]

    def __post_init__(self) -> None:
        validate_config(self)


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RealtimeAccountStateConfig:
    config_path = resolve_repo_path(path)
    payload = read_json(config_path) if config_path.exists() else {}
    outputs = payload.get("outputs", {})
    account = payload.get("longbridge_account_state", {})
    output_dir = resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR))
    return RealtimeAccountStateConfig(
        stage=str(payload.get("stage", "M15.longbridge_realtime_account_state")),
        title=str(payload.get("title", "长桥模拟账户实时账户状态")),
        output_dir=output_dir,
        account_state_path=resolve_repo_path(outputs.get("account_state", output_dir / ACCOUNT_STATE_JSON)),
        cli_name=str(account.get("cli_name", "longbridge")),
        required_account_channel=str(account.get("required_account_channel", "lb_papertrading")),
        cli_timeout_seconds=int(account.get("cli_timeout_seconds", 6)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: RealtimeAccountStateConfig) -> None:
    if config.stage != "M15.longbridge_realtime_account_state":
        raise ValueError("M15 realtime account state stage drift")
    if config.required_account_channel != "lb_papertrading":
        raise ValueError("M15 realtime account state requires Longbridge paper-trading account channel")
    if config.cli_timeout_seconds <= 0:
        raise ValueError("M15 realtime account state CLI timeout must be positive")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 realtime account state must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("M15 realtime account state cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("M15 realtime account state cannot enable real money actions")
    if config.hard_boundaries.get("local_simulation_as_account_source", False):
        raise ValueError("M15 realtime account state cannot use local simulation as account source")
    if config.hard_boundaries.get("order_submit_or_cancel_commands", False):
        raise ValueError("M15 realtime account state cannot submit or cancel orders")


def run_realtime_account_state(
    config: RealtimeAccountStateConfig | None = None,
    *,
    generated_at: str | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    now = parse_utc_datetime(generated_at) if generated_at else datetime.now(UTC)
    generated_at_iso = to_iso(now)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.account_state_path.parent.mkdir(parents=True, exist_ok=True)
    cli_path = shutil.which(config.cli_name) or config.cli_name
    runner = command_runner or run_command

    auth = probe_json(runner, [cli_path, "auth", "status", "--format", "json"], config.cli_timeout_seconds)
    assets = probe_json(runner, [cli_path, "assets", "--format", "json"], config.cli_timeout_seconds)
    positions = probe_json(runner, [cli_path, "positions", "--format", "json"], config.cli_timeout_seconds)
    orders = probe_json(runner, [cli_path, "order", "--format", "json"], config.cli_timeout_seconds)
    account_state = build_account_state(config, generated_at_iso, auth, assets, positions, orders)
    summary = build_summary(config, generated_at_iso, account_state, auth, assets, positions, orders)
    ledger_row = {
        "stage": config.stage,
        "generated_at": generated_at_iso,
        "account_status": summary["account_status"],
        "paper_account_verified": account_state["paper_account_verified"],
        "position_row_count": account_state["position_row_count"],
        "open_order_count": account_state["open_order_count"],
        "buying_power": account_state["buying_power"],
        "blockers": summary["blockers"],
        "local_simulation_ignored": True,
        "order_submit_or_cancel_command_used": False,
    }
    write_json(config.account_state_path, account_state)
    write_json(config.output_dir / SUMMARY_JSON, summary)
    append_jsonl(config.output_dir / LEDGER_JSONL, [ledger_row])
    (config.output_dir / REPORT_MD).write_text(render_report(summary, account_state), encoding="utf-8")
    return summary


def build_summary(
    config: RealtimeAccountStateConfig,
    generated_at: str,
    account_state: dict[str, Any],
    auth: dict[str, Any],
    assets: dict[str, Any],
    positions: dict[str, Any],
    orders: dict[str, Any],
) -> dict[str, Any]:
    blockers = account_blockers(config, account_state, auth, assets, positions, orders)
    status = "paper_account_ready" if not blockers else blockers[0]
    return {
        "schema_version": "m15.longbridge-realtime-account-state-summary.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at,
        "source_mode": "longbridge_realtime_account_state_only",
        "account_status": status,
        "blockers": blockers,
        "paper_account_verified": account_state["paper_account_verified"],
        "account_channel": account_state["account_channel"],
        "buying_power": account_state["buying_power"],
        "cash": account_state["cash"],
        "held_symbols": account_state["held_symbols"],
        "position_row_count": account_state["position_row_count"],
        "open_order_count": account_state["open_order_count"],
        "total_position_notional": account_state["total_position_notional"],
        "total_open_order_notional": account_state["total_open_order_notional"],
        "latency_ms": {
            "auth": auth.get("elapsed_ms", 0),
            "assets": assets.get("elapsed_ms", 0),
            "positions": positions.get("elapsed_ms", 0),
            "orders": orders.get("elapsed_ms", 0),
        },
        "local_simulation_isolated": True,
        "local_simulation_account_source": "",
        "order_submit_or_cancel_command_used": False,
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "outputs": {
            "account_state": project_path(config.account_state_path),
            "summary": project_path(config.output_dir / SUMMARY_JSON),
            "ledger": project_path(config.output_dir / LEDGER_JSONL),
            "report": project_path(config.output_dir / REPORT_MD),
        },
        "plain_language_result": plain_language_result(status, account_state),
    }


def build_account_state(
    config: RealtimeAccountStateConfig,
    generated_at: str,
    auth: dict[str, Any],
    assets: dict[str, Any],
    positions: dict[str, Any],
    orders: dict[str, Any],
) -> dict[str, Any]:
    auth_json = auth.get("json", {}) if isinstance(auth.get("json"), dict) else {}
    account = auth_json.get("account", {}) if isinstance(auth_json.get("account"), dict) else {}
    position_rows = positions.get("json") if isinstance(positions.get("json"), list) else []
    order_rows = orders.get("json") if isinstance(orders.get("json"), list) else []
    open_order_rows = [row for row in order_rows if is_open_order_row(row)]
    position_notional = exposure_by_symbol(position_rows, quantity_keys=("quantity", "qty"), price_keys=("market_price", "last_done", "cost_price", "price"))
    open_order_notional = exposure_by_symbol(open_order_rows, quantity_keys=("quantity", "qty"), price_keys=("price", "limit_price", "submitted_price"))
    channel = str(account.get("account_channel", ""))
    return {
        "schema_version": "m15.longbridge-realtime-account-state.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "source": "longbridge_realtime_account_state_only",
        "local_simulation_isolated": True,
        "local_sim_position_migration": False,
        "auth_ok": bool(auth.get("ok")),
        "assets_ok": bool(assets.get("ok")),
        "positions_ok": bool(positions.get("ok")),
        "orders_ok": bool(orders.get("ok")),
        "account_channel": channel,
        "account_type": account.get("account_type"),
        "paper_account_detected": channel == config.required_account_channel,
        "paper_account_verified": bool(auth.get("ok")) and channel == config.required_account_channel,
        "cash": fmt_money(available_cash(assets)),
        "buying_power": fmt_money(available_buying_power(assets)),
        "held_symbols": sorted(held_symbol_set(position_rows)),
        "position_row_count": len(position_rows),
        "order_row_count": len(order_rows),
        "open_order_count": len(open_order_rows),
        "positions": position_rows,
        "open_orders": open_order_rows,
        "position_notional_by_symbol": {key: fmt_money(value) for key, value in sorted(position_notional.items())},
        "open_order_notional_by_symbol": {key: fmt_money(value) for key, value in sorted(open_order_notional.items())},
        "total_position_notional": fmt_money(sum(position_notional.values(), ZERO)),
        "total_open_order_notional": fmt_money(sum(open_order_notional.values(), ZERO)),
        "submitted_signal_ids": [],
        "real_money_actions": False,
        "live_execution": False,
    }


def account_blockers(
    config: RealtimeAccountStateConfig,
    account_state: dict[str, Any],
    auth: dict[str, Any],
    assets: dict[str, Any],
    positions: dict[str, Any],
    orders: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if auth.get("ok") is not True:
        blockers.append("auth_status_read_failed")
    if account_state.get("account_channel") != config.required_account_channel:
        blockers.append("account_channel_not_paper")
    if assets.get("ok") is not True:
        blockers.append("assets_read_failed")
    if positions.get("ok") is not True:
        blockers.append("positions_read_failed")
    if orders.get("ok") is not True:
        blockers.append("orders_read_failed")
    return blockers


def probe_json(runner: CommandRunner, command: list[str], timeout_seconds: int) -> dict[str, Any]:
    assert_account_state_command(command)
    started = time.perf_counter()
    try:
        result = runner(command)
    except Exception as exc:  # pragma: no cover - runtime provider path
        return {"ok": False, "json": {}, "elapsed_ms": int((time.perf_counter() - started) * 1000), "stderr": str(exc)[:300]}
    stdout = str(getattr(result, "stdout", ""))
    stderr = str(getattr(result, "stderr", ""))
    returncode = int(getattr(result, "returncode", 1))
    if returncode != 0:
        return {
            "ok": False,
            "json": {},
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "stderr": clean_cli_text(stderr or stdout)[:300],
        }
    return {
        "ok": True,
        "json": parse_json(stdout),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "stderr": clean_cli_text(stderr)[:300],
    }


def assert_account_state_command(command: list[str]) -> None:
    if len(command) < 2:
        raise ValueError("Longbridge account state command cannot be empty")
    args = command[1:]
    if args[:2] == ["auth", "status"] and "--format" in args:
        return
    if args[:1] in (["assets"], ["positions"], ["order"]) and "--format" in args:
        forbidden = {"buy", "sell", "cancel", "replace", "--yes"}
        if any(token in forbidden for token in args):
            raise ValueError(f"Longbridge account state command cannot submit or cancel orders: {args}")
        return
    raise ValueError(f"Longbridge account state command is not allowed: {args}")


def run_command(command: list[str]) -> CommandResult:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=build_longbridge_cli_env(),
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def parse_json(text: str) -> Any:
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}


def is_open_order_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    status = str(row.get("status") or "").strip().lower()
    if not status:
        return True
    return status not in {"filled", "canceled", "cancelled", "rejected", "expired", "withdrawn", "deleted", "failed"}


def held_symbol_set(rows: list[dict[str, Any]]) -> set[str]:
    symbols: set[str] = set()
    for row in rows:
        if decimal(row.get("quantity", row.get("qty", "0"))) > ZERO and row.get("symbol"):
            symbols.add(base_symbol(str(row.get("symbol", ""))))
    return symbols


def exposure_by_symbol(rows: list[dict[str, Any]], *, quantity_keys: tuple[str, ...], price_keys: tuple[str, ...]) -> dict[str, Decimal]:
    exposures: dict[str, Decimal] = {}
    for row in rows:
        symbol = base_symbol(str(row.get("symbol", "")))
        if not symbol:
            continue
        quantity = first_decimal(row, quantity_keys)
        price = first_decimal(row, price_keys)
        if quantity <= ZERO or price <= ZERO:
            continue
        exposures[symbol] = exposures.get(symbol, ZERO) + quantity * price
    return exposures


def available_buying_power(assets: dict[str, Any]) -> Decimal:
    payload = assets.get("json")
    rows = payload if isinstance(payload, list) else []
    if not rows:
        return ZERO
    return first_decimal(rows[0], ("buy_power", "buying_power", "available_cash", "cash", "total_cash"))


def available_cash(assets: dict[str, Any]) -> Decimal:
    payload = assets.get("json")
    rows = payload if isinstance(payload, list) else []
    if not rows:
        return ZERO
    return first_decimal(rows[0], ("cash", "available_cash", "total_cash", "buy_power", "buying_power"))


def first_decimal(row: dict[str, Any], keys: tuple[str, ...]) -> Decimal:
    for key in keys:
        if row.get(key) not in (None, ""):
            return decimal(row.get(key))
    return ZERO


def base_symbol(symbol: str) -> str:
    return symbol.upper().split(".")[0]


def plain_language_result(status: str, account_state: dict[str, Any]) -> str:
    if status == "paper_account_ready":
        return (
            f"长桥模拟账户状态已读取：现金/购买力 {account_state['buying_power']}，"
            f"持仓 {account_state['position_row_count']} 条，未完成挂单 {account_state['open_order_count']} 条。"
        )
    return f"长桥模拟账户状态读取未通过：{status}。"


def render_report(summary: dict[str, Any], account_state: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# 长桥模拟账户实时账户状态",
            "",
            f"- 生成时间: `{summary['generated_at']}`",
            f"- 状态: `{summary['account_status']}`",
            f"- 账户通道: `{summary['account_channel']}`",
            f"- 现金/购买力: `{summary['buying_power']}`",
            f"- 持仓条数: `{summary['position_row_count']}`",
            f"- 未完成挂单: `{summary['open_order_count']}`",
            f"- 本地模拟隔离: `{summary['local_simulation_isolated']}`",
            f"- 结论: {summary['plain_language_result']}",
            "",
            "## 边界",
            "",
            "- 只读取长桥模拟账户自身现金、持仓、挂单和账户通道。",
            "- 不读取本地模拟账本，不迁移本地持仓。",
            "- 不提交、不撤单、不改订单。",
            "",
        ]
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(json_ready(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(json_ready(row), ensure_ascii=False, sort_keys=True) + "\n")


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return fmt_decimal(value)
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def parse_utc_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, ""):
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f") if value == value.to_integral_value() else format(value, "f")


def fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY))
