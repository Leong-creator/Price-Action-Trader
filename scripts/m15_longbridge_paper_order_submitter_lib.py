#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, time as wall_time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_paper_order_submitter.json"
DEFAULT_DAILY_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
)
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_paper_order_submitter"
DEFAULT_FAST_SIGNAL_QUEUE_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_fast_signal_queue"
SUMMARY_JSON = "m15_longbridge_paper_order_submitter.json"
LEDGER_JSONL = "m15_longbridge_paper_order_submitter_ledger.jsonl"
ACCOUNT_STATE_JSON = "m15_longbridge_paper_account_state.json"
REPORT_MD = "m15_longbridge_paper_order_submitter.md"
LOG_FILE = "m15_longbridge_paper_order_submitter.log"
MONEY = Decimal("0.01")
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class M15PaperSubmitterConfig:
    stage: str
    title: str
    connection_check_path: Path
    order_preview_summary_path: Path
    order_preview_ledger_path: Path
    output_dir: Path
    cli_name: str
    required_account_channel: str
    paper_account_start_at: str
    submit_only_new_open_orders_after_start: bool
    ignore_local_sim_positions_before_start: bool
    submit_orders: bool
    paper_trading_approval: bool
    user_approval_note: str
    outside_rth: str
    time_in_force: str
    regular_hours_only: bool
    max_orders_per_run: int
    allowed_order_types: tuple[str, ...]
    allowed_soft_preview_blockers: tuple[str, ...]
    paper_account_equity: Decimal
    max_total_exposure: Decimal
    max_symbol_exposure: Decimal
    max_risk_per_order: Decimal
    min_cash_reserve: Decimal
    allow_fractional_shares: bool
    allow_short_selling: bool
    allow_options: bool
    market_timezone: str
    regular_open: str
    regular_close: str
    market_holidays: frozenset[date]
    watch_interval_seconds: int
    backoff_interval_seconds: int
    run_queue_before_submit: bool
    queue_command: tuple[str, ...]
    run_preview_before_submit: bool
    preview_command: tuple[str, ...]
    hard_boundaries: dict[str, bool]

    def __post_init__(self) -> None:
        validate_config(self)


CommandRunner = Callable[[list[str]], CommandResult]


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M15PaperSubmitterConfig:
    config_path = resolve_repo_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    inputs = payload.get("inputs", {})
    outputs = payload.get("outputs", {})
    longbridge = payload.get("longbridge", {})
    account_model = payload.get("paper_account_model", {})
    market = payload.get("market_session", {})
    watch = payload.get("watch", {})
    return M15PaperSubmitterConfig(
        stage=str(payload.get("stage", "M15.longbridge_paper_order_submitter")),
        title=str(payload.get("title", "长桥模拟账户订单提交器")),
        connection_check_path=resolve_repo_path(
            inputs.get(
                "connection_check",
                DEFAULT_DAILY_DIR
                / "m15_longbridge_paper_connection_check"
                / "m15_longbridge_paper_connection_check.json",
            )
        ),
        order_preview_summary_path=resolve_repo_path(
            inputs.get(
                "fast_signal_queue_summary",
                inputs.get(
                    "order_preview_summary",
                    DEFAULT_FAST_SIGNAL_QUEUE_DIR / "m15_longbridge_fast_signal_queue.json",
                ),
            )
        ),
        order_preview_ledger_path=resolve_repo_path(
            inputs.get(
                "fast_signal_queue_ledger",
                inputs.get(
                    "order_preview_ledger",
                    DEFAULT_FAST_SIGNAL_QUEUE_DIR / "m15_longbridge_fast_signal_queue_ledger.jsonl",
                ),
            )
        ),
        output_dir=resolve_repo_path(outputs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        cli_name=str(longbridge.get("cli_name", "longbridge")),
        required_account_channel=str(longbridge.get("required_account_channel", "lb_papertrading")),
        paper_account_start_at=str(longbridge.get("paper_account_start_at", "")),
        submit_only_new_open_orders_after_start=bool(longbridge.get("submit_only_new_open_orders_after_start", True)),
        ignore_local_sim_positions_before_start=bool(longbridge.get("ignore_local_sim_positions_before_start", True)),
        submit_orders=bool(longbridge.get("submit_orders", False)),
        paper_trading_approval=bool(longbridge.get("paper_trading_approval", False)),
        user_approval_note=str(longbridge.get("user_approval_note", "")),
        outside_rth=str(longbridge.get("outside_rth", "RTH_ONLY")),
        time_in_force=str(longbridge.get("time_in_force", "day")),
        regular_hours_only=bool(longbridge.get("regular_hours_only", True)),
        max_orders_per_run=int(longbridge.get("max_orders_per_run", 6)),
        allowed_order_types=tuple(str(item) for item in longbridge.get("allowed_order_types", ["limit"])),
        allowed_soft_preview_blockers=tuple(
            str(item)
            for item in longbridge.get(
                "allowed_soft_preview_blockers",
                ["broker_connection_disabled", "order_submission_disabled", "paper_trading_approval_false"],
            )
        ),
        paper_account_equity=decimal(account_model.get("equity", "10000")),
        max_total_exposure=decimal(account_model.get("max_total_exposure", "6000")),
        max_symbol_exposure=decimal(account_model.get("max_symbol_exposure", "1500")),
        max_risk_per_order=decimal(account_model.get("max_risk_per_order", "20")),
        min_cash_reserve=decimal(account_model.get("min_cash_reserve", "4000")),
        allow_fractional_shares=bool(account_model.get("allow_fractional_shares", False)),
        allow_short_selling=bool(account_model.get("allow_short_selling", False)),
        allow_options=bool(account_model.get("allow_options", False)),
        market_timezone=str(market.get("timezone", "America/New_York")),
        regular_open=str(market.get("regular_open", "09:30")),
        regular_close=str(market.get("regular_close", "16:00")),
        market_holidays=parse_holidays(market.get("market_holidays", [])),
        watch_interval_seconds=int(watch.get("interval_seconds", 15)),
        backoff_interval_seconds=int(watch.get("backoff_interval_seconds", 60)),
        run_queue_before_submit=bool(watch.get("run_queue_before_submit", True)),
        queue_command=tuple(str(item) for item in watch.get("queue_command", [])),
        run_preview_before_submit=bool(watch.get("run_preview_before_submit", False)),
        preview_command=tuple(str(item) for item in watch.get("preview_command", [])),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )


def validate_config(config: M15PaperSubmitterConfig) -> None:
    if config.stage != "M15.longbridge_paper_order_submitter":
        raise ValueError("M15 paper submitter stage drift")
    if not config.submit_orders:
        raise ValueError("M15 paper submitter requires explicit submit_orders=true")
    if not config.paper_trading_approval:
        raise ValueError("M15 paper submitter requires explicit paper_trading_approval=true")
    if not config.user_approval_note:
        raise ValueError("M15 paper submitter requires a user approval note")
    if config.hard_boundaries.get("paper_simulated_only") is not True:
        raise ValueError("M15 paper submitter must stay paper/simulated only")
    if config.hard_boundaries.get("live_execution", False):
        raise ValueError("M15 paper submitter cannot enable live execution")
    if config.hard_boundaries.get("real_money_actions", False):
        raise ValueError("M15 paper submitter cannot enable real money actions")
    if config.hard_boundaries.get("manual_m12_37_once", False):
        raise ValueError("M15 paper submitter cannot run M12.37 once-mode")
    if config.required_account_channel != "lb_papertrading":
        raise ValueError("M15 paper submitter requires Longbridge paper-trading account channel")
    if not config.paper_account_start_at:
        raise ValueError("M15 paper submitter requires a paper account start timestamp")
    parse_utc_datetime(config.paper_account_start_at)
    if not config.submit_only_new_open_orders_after_start:
        raise ValueError("M15 paper submitter must only submit new open orders after paper account start")
    if not config.ignore_local_sim_positions_before_start:
        raise ValueError("M15 paper submitter must not migrate local simulated positions")
    if config.allow_fractional_shares:
        raise ValueError("M15 paper submitter forbids fractional shares")
    if config.allow_short_selling:
        raise ValueError("M15 paper submitter forbids short selling")
    if config.allow_options:
        raise ValueError("M15 paper submitter forbids options")
    if set(config.allowed_order_types) - {"limit", "trigger_limit"}:
        raise ValueError("M15 paper submitter order types must be limit or trigger_limit")
    if config.max_orders_per_run <= 0:
        raise ValueError("M15 paper submitter max_orders_per_run must be positive")
    if config.max_risk_per_order <= ZERO:
        raise ValueError("M15 paper submitter max_risk_per_order must be positive")
    if config.watch_interval_seconds <= 0:
        raise ValueError("M15 paper submitter watch interval must be positive")
    if config.backoff_interval_seconds < config.watch_interval_seconds:
        raise ValueError("M15 paper submitter backoff interval must be >= watch interval")


def run_paper_submitter(
    config: M15PaperSubmitterConfig | None = None,
    *,
    generated_at: str | None = None,
    command_runner: CommandRunner | None = None,
    execute_orders: bool = True,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or now_utc_iso()
    runner = command_runner or run_command
    summary, ledger_rows, account_state = build_and_maybe_submit(config, generated_at, runner, execute_orders=execute_orders)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / SUMMARY_JSON, summary)
    write_json(config.output_dir / ACCOUNT_STATE_JSON, account_state)
    append_jsonl(config.output_dir / LEDGER_JSONL, ledger_rows)
    (config.output_dir / REPORT_MD).write_text(render_markdown(summary, ledger_rows), encoding="utf-8")
    return summary


def watch_paper_submitter(
    config: M15PaperSubmitterConfig,
    *,
    command_runner: CommandRunner | None = None,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    runner = command_runner or run_command
    final: dict[str, Any] = {}
    iteration = 0
    while True:
        iteration += 1
        if config.run_queue_before_submit and config.queue_command:
            runner(list(config.queue_command))
        elif config.run_preview_before_submit and config.preview_command:
            runner(list(config.preview_command))
        final = run_paper_submitter(config, generated_at=now_utc_iso(), command_runner=runner, execute_orders=True)
        append_log(config, f"{now_utc_iso()} {final.get('submission_status')} {final.get('plain_language_result', '')}")
        if final.get("submitted_order_count", 0) > 0:
            return final
        if final.get("market_window", {}).get("market_status") == "after_regular_session":
            return final
        if max_iterations is not None and iteration >= max_iterations:
            return final
        time.sleep(int(final.get("next_interval_seconds", config.watch_interval_seconds)))


def build_and_maybe_submit(
    config: M15PaperSubmitterConfig,
    generated_at: str,
    command_runner: CommandRunner,
    *,
    execute_orders: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    preview_summary = read_json(config.order_preview_summary_path)
    preview_rows = read_jsonl(config.order_preview_ledger_path)
    connection_check = read_json(config.connection_check_path)
    market = market_window(config, generated_at)
    cli_path = shutil.which(config.cli_name) or config.cli_name
    auth = probe_json(command_runner, [cli_path, "auth", "status", "--format", "json"])
    assets = probe_json(command_runner, [cli_path, "assets", "--format", "json"])
    positions = probe_json(command_runner, [cli_path, "positions", "--format", "json"])
    existing_orders = probe_json(command_runner, [cli_path, "order", "--format", "json"])
    submitted_ids = existing_submission_ids(config)
    global_blockers = global_blockers_for(
        config,
        preview_summary,
        connection_check,
        market,
        auth,
        assets,
        positions,
        existing_orders,
    )
    eligible = eligible_preview_rows(config, preview_summary, preview_rows, market, submitted_ids, positions)
    ledger_rows: list[dict[str, Any]] = []
    submitted_count = 0
    for row in eligible[: config.max_orders_per_run]:
        row_blockers = list(global_blockers)
        if row_blockers:
            ledger_rows.append(build_submission_row(row, generated_at, "blocked_global_gate", row_blockers, {}, []))
            continue
        command, command_blockers = order_command(config, cli_path, row)
        if command_blockers:
            ledger_rows.append(build_submission_row(row, generated_at, "blocked_order_command", command_blockers, {}, []))
            continue
        if not execute_orders:
            ledger_rows.append(build_submission_row(row, generated_at, "dry_run_ready_not_submitted", [], {}, redact_command(command)))
            continue
        result = command_runner(command)
        if result.returncode == 0:
            response = parse_json(result.stdout)
            ledger_rows.append(build_submission_row(row, generated_at, "submitted", [], response, redact_command(command)))
            submitted_count += 1
        else:
            ledger_rows.append(
                build_submission_row(
                    row,
                    generated_at,
                    "submit_failed",
                    [safe_error(result.stderr or result.stdout)],
                    {},
                    redact_command(command),
                )
            )
    if not eligible:
        ledger_rows.append(empty_submission_row(generated_at, "no_eligible_orders", global_blockers))
    post_submit_account_refresh_performed = False
    if submitted_count > 0 and execute_orders:
        assets = probe_json(command_runner, [cli_path, "assets", "--format", "json"])
        positions = probe_json(command_runner, [cli_path, "positions", "--format", "json"])
        existing_orders = probe_json(command_runner, [cli_path, "order", "--format", "json"])
        post_submit_account_refresh_performed = True
    current_submitted_ids = {
        str(row.get("signal_fingerprint") or row.get("preview_id") or "")
        for row in ledger_rows
        if row.get("submission_status") == "submitted"
    }
    current_submitted_ids.discard("")
    account_state_submitted_ids = submitted_ids | current_submitted_ids
    status = submission_status(global_blockers, eligible, submitted_count, market)
    backoff_reasons = backoff_reasons_for(auth, assets, positions, existing_orders)
    next_interval_seconds = config.backoff_interval_seconds if backoff_reasons else config.watch_interval_seconds
    account_state = build_account_state(config, generated_at, auth, assets, positions, existing_orders, account_state_submitted_ids)
    summary = {
        "schema_version": "m15.longbridge-paper-order-submitter.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at,
        "submission_status": status,
        "market_window": market,
        "input_refs": {
            "connection_check": project_path(config.connection_check_path),
            "order_source_summary": project_path(config.order_preview_summary_path),
            "order_source_ledger": project_path(config.order_preview_ledger_path),
        },
        "output_refs": {
            "summary": project_path(config.output_dir / SUMMARY_JSON),
            "submission_ledger": project_path(config.output_dir / LEDGER_JSONL),
            "paper_account_state": project_path(config.output_dir / ACCOUNT_STATE_JSON),
            "markdown_report": project_path(config.output_dir / REPORT_MD),
        },
        "order_source_mode": preview_summary.get("source_mode", "all_strategy_order_preview"),
        "longbridge_account": summarize_account_probe(auth, assets, positions),
        "connection_check_status": connection_check.get("connection_check_status", ""),
        "preview_status": preview_summary.get("preview_status", ""),
        "preview_scan_date": preview_summary.get("scan_date", ""),
        "preview_quote_source": preview_summary.get("quote_source", ""),
        "current_day_strategy_confirmation_status": preview_summary.get("current_day_strategy_confirmation_status", ""),
        "global_blockers": global_blockers,
        "paper_account_start_at": config.paper_account_start_at,
        "submit_only_new_open_orders_after_start": config.submit_only_new_open_orders_after_start,
        "ignore_local_sim_positions_before_start": config.ignore_local_sim_positions_before_start,
        "eligible_order_count": len(eligible),
        "attempted_order_count": sum(1 for row in ledger_rows if row.get("submission_status") in {"submitted", "submit_failed"}),
        "submitted_order_count": submitted_count,
        "post_submit_account_refresh_performed": post_submit_account_refresh_performed,
        "max_orders_per_run": config.max_orders_per_run,
        "paper_account_equity_model": fmt_money(config.paper_account_equity),
        "max_total_exposure": fmt_money(config.max_total_exposure),
        "max_symbol_exposure": fmt_money(config.max_symbol_exposure),
        "max_risk_per_order": fmt_money(config.max_risk_per_order),
        "min_cash_reserve": fmt_money(config.min_cash_reserve),
        "watch_interval_seconds": config.watch_interval_seconds,
        "backoff_interval_seconds": config.backoff_interval_seconds,
        "next_interval_seconds": next_interval_seconds,
        "backoff_reasons": backoff_reasons,
        "latency_ms": {
            "auth": auth.get("elapsed_ms", 0),
            "assets": assets.get("elapsed_ms", 0),
            "positions": positions.get("elapsed_ms", 0),
            "orders": existing_orders.get("elapsed_ms", 0),
            "total": int((time.perf_counter() - started) * 1000),
        },
        "order_submitted": submitted_count > 0,
        "real_money_actions": False,
        "live_execution": False,
        "plain_language_result": plain_language_result(status, global_blockers, eligible, submitted_count, market),
    }
    return summary, ledger_rows, account_state


def market_window(config: M15PaperSubmitterConfig, generated_at: str) -> dict[str, Any]:
    utc_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    market_dt = utc_dt.astimezone(ZoneInfo(config.market_timezone))
    regular_open = parse_clock(config.regular_open)
    regular_close = parse_clock(config.regular_close)
    if market_dt.date() in config.market_holidays or market_dt.weekday() >= 5:
        status = "non_trading_day"
    elif market_dt.time() < regular_open:
        status = "before_regular_session"
    elif regular_open <= market_dt.time() <= regular_close:
        status = "regular_session"
    else:
        status = "after_regular_session"
    return {
        "market_status": status,
        "market_date": market_dt.date().isoformat(),
        "new_york_time": market_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "beijing_time": utc_dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "regular_hours_only": config.regular_hours_only,
    }


def global_blockers_for(
    config: M15PaperSubmitterConfig,
    preview_summary: dict[str, Any],
    connection_check: dict[str, Any],
    market: dict[str, Any],
    auth: dict[str, Any],
    assets: dict[str, Any],
    positions: dict[str, Any],
    existing_orders: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if market.get("market_status") != "regular_session":
        blockers.append("not_us_regular_session")
    if connection_check.get("paper_account_verified") is not True:
        blockers.append("paper_account_not_verified")
    if auth_account_channel(auth) != config.required_account_channel:
        blockers.append("longbridge_account_channel_not_paper")
    if preview_summary.get("quote_source") != "longbridge_quote_readonly":
        blockers.append("quote_source_not_longbridge_readonly")
    if preview_summary.get("scan_date") != market.get("market_date"):
        blockers.append("preview_not_current_market_date")
    if preview_summary.get("m14_trading_date") != preview_summary.get("scan_date"):
        blockers.append("m14_not_recomputed_for_preview_date")
    if (
        preview_summary.get("source_mode") == "fast_signal_queue"
        and preview_summary.get("current_day_strategy_confirmation_status") != "confirmed"
    ):
        blockers.append("strategy_list_not_confirmed_for_today")
    if (
        preview_summary.get("source_mode") == "fast_signal_queue"
        and (
            preview_summary.get("snapshot_freshness_status") == "stale_snapshot"
            or preview_summary.get("fast_queue_status") == "stale_snapshot_waiting_for_current_refresh"
        )
    ):
        blockers.append("fast_queue_stale_snapshot")
    if assets.get("ok") is not True:
        blockers.append("assets_read_failed")
    if positions.get("ok") is not True:
        blockers.append("positions_read_failed")
    if existing_orders.get("ok") is not True:
        blockers.append("orders_read_failed")
    if available_buying_power(assets) < config.min_cash_reserve:
        blockers.append("cash_below_min_reserve")
    return blockers


def eligible_preview_rows(
    config: M15PaperSubmitterConfig,
    preview_summary: dict[str, Any],
    preview_rows: list[dict[str, Any]],
    market: dict[str, Any],
    submitted_ids: set[str],
    positions: dict[str, Any],
) -> list[dict[str, Any]]:
    held_symbols = held_symbol_set(positions)
    fast_source = preview_summary.get("source_mode") == "fast_signal_queue"
    accepted_comparison_statuses = {"matched", "fast_queue_no_m13_wait"} if fast_source else {"matched"}
    selected_total = ZERO
    selected_by_symbol: dict[str, Decimal] = {}
    rows: list[dict[str, Any]] = []
    for row in sorted(preview_rows, key=eligible_priority_key):
        signal_id = str(row.get("signal_fingerprint") or row.get("preview_id", ""))
        if signal_id in submitted_ids:
            continue
        if row.get("trading_date") != market.get("market_date"):
            continue
        if row.get("longbridge_paper_order_preview_status") != "local_order_preview_created_ready_after_user_approval":
            continue
        if row.get("m13_comparison_status") not in accepted_comparison_statuses:
            continue
        if row.get("broker_order_side") != "buy" or row.get("local_event_type") != "open":
            continue
        if config.submit_only_new_open_orders_after_start and not row_is_after_paper_account_start(row, config):
            continue
        if row.get("symbol") in held_symbols:
            continue
        if set(row.get("blockers", [])) - set(config.allowed_soft_preview_blockers):
            continue
        if row.get("order_type") not in set(config.allowed_order_types):
            continue
        if decimal(row.get("quantity", "0")) <= ZERO:
            continue
        risk_amount = decimal(row.get("estimated_open_risk", "0"))
        if risk_amount > config.max_risk_per_order:
            continue
        notional = decimal(row.get("notional", "0"))
        symbol = str(row.get("symbol", ""))
        if notional > config.max_symbol_exposure:
            continue
        if selected_by_symbol.get(symbol, ZERO) + notional > config.max_symbol_exposure:
            continue
        if selected_total + notional > config.max_total_exposure:
            continue
        if preview_summary.get("scan_date") != market.get("market_date"):
            continue
        selected_total += notional
        selected_by_symbol[symbol] = selected_by_symbol.get(symbol, ZERO) + notional
        rows.append(row)
    rows.sort(key=eligible_priority_key)
    return rows


def eligible_priority_key(row: dict[str, Any]) -> tuple[int, Decimal, Decimal, Decimal, Decimal, str, str]:
    rank = int_or_large(row.get("submission_priority_rank", ""))
    return (
        rank,
        -decimal(row.get("net_profit_after_fees_at_target", "0")),
        -decimal(row.get("strategy_quality_score", "0")),
        -decimal(row.get("reward_r", "0")),
        -decimal(row.get("confluence_multiplier", "1")),
        str(row.get("symbol", "")),
        str(row.get("runtime_id", "")),
    )


def int_or_large(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 10**9


def order_command(config: M15PaperSubmitterConfig, cli_path: str, row: dict[str, Any]) -> tuple[list[str], list[str]]:
    symbol = longbridge_symbol(str(row.get("symbol", "")))
    quantity = int(decimal(row.get("quantity", "0")))
    limit_price = str(row.get("limit_price", ""))
    order_type = str(row.get("order_type", ""))
    if not symbol or quantity <= 0 or not limit_price:
        return [], ["missing_symbol_quantity_or_limit_price"]
    signal_id = row.get("signal_fingerprint") or row.get("preview_id", "")
    remark = f"PAT {signal_id} {row.get('runtime_id','')}"[:255]
    command = [
        cli_path,
        "order",
        "buy",
        symbol,
        str(quantity),
        "--price",
        limit_price,
        "--tif",
        config.time_in_force,
        "--outside-rth",
        config.outside_rth,
        "--remark",
        remark,
        "--yes",
        "--format",
        "json",
    ]
    if order_type == "limit":
        command.extend(["--order-type", "LO"])
        return command, []
    if order_type == "trigger_limit":
        trigger_price = str(row.get("trigger_price") or row.get("limit_price") or "")
        if not trigger_price:
            return [], ["missing_trigger_price"]
        command.extend(["--order-type", "LIT", "--trigger-price", trigger_price])
        return command, []
    return [], ["unsupported_order_type"]


def build_submission_row(
    preview_row: dict[str, Any],
    generated_at: str,
    status: str,
    blockers: list[str],
    response: dict[str, Any],
    command: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "m15.longbridge-paper-order-submission-row.v1",
        "stage": "M15.longbridge_paper_order_submitter",
        "generated_at": generated_at,
        "preview_id": preview_row.get("preview_id", ""),
        "signal_fingerprint": preview_row.get("signal_fingerprint") or preview_row.get("preview_id", ""),
        "runtime_id": preview_row.get("runtime_id", ""),
        "strategy_id": preview_row.get("strategy_id", ""),
        "symbol": preview_row.get("symbol", ""),
        "trading_date": preview_row.get("trading_date", ""),
        "broker_order_side": preview_row.get("broker_order_side", ""),
        "order_type": preview_row.get("order_type", ""),
        "quantity": preview_row.get("quantity", ""),
        "limit_price": preview_row.get("limit_price", ""),
        "notional": preview_row.get("notional", ""),
        "estimated_open_risk": preview_row.get("estimated_open_risk", ""),
        "net_profit_after_fees_at_target": preview_row.get("net_profit_after_fees_at_target", ""),
        "submission_priority_rank": preview_row.get("submission_priority_rank", ""),
        "submission_status": status,
        "blockers": blockers,
        "longbridge_order_id": str(response.get("order_id", "")) if isinstance(response, dict) else "",
        "longbridge_response_keys": sorted(response.keys()) if isinstance(response, dict) else [],
        "command": command,
        "real_money_actions": False,
        "live_execution": False,
    }


def empty_submission_row(generated_at: str, status: str, blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "m15.longbridge-paper-order-submission-row.v1",
        "stage": "M15.longbridge_paper_order_submitter",
        "generated_at": generated_at,
        "preview_id": "",
        "runtime_id": "",
        "strategy_id": "",
        "symbol": "",
        "trading_date": "",
        "submission_status": status,
        "blockers": blockers,
        "real_money_actions": False,
        "live_execution": False,
    }


def submission_status(global_blockers: list[str], eligible: list[dict[str, Any]], submitted_count: int, market: dict[str, Any]) -> str:
    if submitted_count:
        return "paper_orders_submitted"
    if global_blockers:
        return "blocked_global_gate"
    if market.get("market_status") != "regular_session":
        return "waiting_for_regular_session"
    if not eligible:
        return "no_eligible_orders"
    return "ready_but_not_submitted"


def plain_language_result(
    status: str,
    blockers: list[str],
    eligible: list[dict[str, Any]],
    submitted_count: int,
    market: dict[str, Any],
) -> str:
    if status == "paper_orders_submitted":
        return f"已向长桥模拟账户提交 {submitted_count} 笔订单；仍未触碰真实资金。"
    if status == "blocked_global_gate":
        return f"模拟下单被全局门禁阻断：{', '.join(blockers)}。当前窗口：{market.get('new_york_time')}。"
    if status == "waiting_for_regular_session":
        return f"正在等待美股常规交易时段。当前窗口：{market.get('new_york_time')}。"
    if status == "no_eligible_orders":
        return "当前没有符合提交条件的模拟订单；可能是新看板还未刷新，或订单已被风控过滤。"
    return f"已有 {len(eligible)} 笔订单满足门槛，但本轮未提交。"


def parse_clock(value: str) -> wall_time:
    hour, minute = value.split(":")
    return wall_time(int(hour), int(minute))


def row_is_after_paper_account_start(row: dict[str, Any], config: M15PaperSubmitterConfig) -> bool:
    start = parse_utc_datetime(config.paper_account_start_at)
    for key in ("source_event_time", "generated_at"):
        candidate = str(row.get(key, ""))
        if not candidate:
            continue
        try:
            return parse_utc_datetime(candidate) >= start
        except ValueError:
            continue
    return False


def parse_utc_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {value}")
    return parsed.astimezone(UTC)


def parse_holidays(values: list[str]) -> frozenset[date]:
    return frozenset(date.fromisoformat(str(item)) for item in values)


def run_command(args: list[str]) -> CommandResult:
    completed = subprocess.run(args, check=False, capture_output=True, text=True, timeout=30)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def probe_json(command_runner: CommandRunner, args: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    result = command_runner(args)
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "json": parse_json(result.stdout),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "stderr": safe_error(result.stderr),
    }


def parse_json(text: str) -> Any:
    try:
        return json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}


def summarize_account_probe(auth: dict[str, Any], assets: dict[str, Any], positions: dict[str, Any]) -> dict[str, Any]:
    auth_json = auth.get("json", {}) if isinstance(auth.get("json"), dict) else {}
    account = auth_json.get("account", {}) if isinstance(auth_json.get("account"), dict) else {}
    return {
        "auth_ok": bool(auth.get("ok")),
        "assets_ok": bool(assets.get("ok")),
        "positions_ok": bool(positions.get("ok")),
        "account_channel": account.get("account_channel"),
        "account_type": account.get("account_type"),
        "paper_account_detected": account.get("account_channel") == "lb_papertrading",
        "buying_power": fmt_money(available_buying_power(assets)),
        "held_symbol_count": len(held_symbol_set(positions)),
    }


def build_account_state(
    config: M15PaperSubmitterConfig,
    generated_at: str,
    auth: dict[str, Any],
    assets: dict[str, Any],
    positions: dict[str, Any],
    existing_orders: dict[str, Any],
    submitted_ids: set[str],
) -> dict[str, Any]:
    auth_json = auth.get("json", {}) if isinstance(auth.get("json"), dict) else {}
    account = auth_json.get("account", {}) if isinstance(auth_json.get("account"), dict) else {}
    position_rows = positions.get("json") if isinstance(positions.get("json"), list) else []
    order_rows = existing_orders.get("json") if isinstance(existing_orders.get("json"), list) else []
    return {
        "schema_version": "m15.longbridge-paper-account-state.v1",
        "stage": "M15.longbridge_paper_order_submitter",
        "generated_at": generated_at,
        "source": "longbridge_paper_account_only",
        "local_sim_position_migration": False,
        "paper_account_start_at": config.paper_account_start_at,
        "auth_ok": bool(auth.get("ok")),
        "assets_ok": bool(assets.get("ok")),
        "positions_ok": bool(positions.get("ok")),
        "orders_ok": bool(existing_orders.get("ok")),
        "account_channel": account.get("account_channel"),
        "account_type": account.get("account_type"),
        "paper_account_detected": account.get("account_channel") == config.required_account_channel,
        "buying_power": fmt_money(available_buying_power(assets)),
        "held_symbols": sorted(held_symbol_set(positions)),
        "position_row_count": len(position_rows),
        "open_order_count": len(order_rows),
        "submitted_signal_fingerprints": sorted(submitted_ids),
        "real_money_actions": False,
        "live_execution": False,
    }


def backoff_reasons_for(
    auth: dict[str, Any],
    assets: dict[str, Any],
    positions: dict[str, Any],
    existing_orders: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if auth.get("ok") is not True:
        reasons.append("auth_probe_failed")
    if assets.get("ok") is not True:
        reasons.append("assets_probe_failed")
    if positions.get("ok") is not True:
        reasons.append("positions_probe_failed")
    if existing_orders.get("ok") is not True:
        reasons.append("orders_probe_failed")
    return reasons


def auth_account_channel(auth: dict[str, Any]) -> str:
    payload = auth.get("json", {}) if isinstance(auth.get("json"), dict) else {}
    account = payload.get("account", {}) if isinstance(payload.get("account"), dict) else {}
    return str(account.get("account_channel", ""))


def available_buying_power(assets: dict[str, Any]) -> Decimal:
    payload = assets.get("json")
    rows = payload if isinstance(payload, list) else []
    if not rows:
        return ZERO
    return decimal(rows[0].get("buy_power") or rows[0].get("total_cash") or "0")


def held_symbol_set(positions: dict[str, Any]) -> set[str]:
    payload = positions.get("json")
    rows = payload if isinstance(payload, list) else []
    symbols: set[str] = set()
    for row in rows:
        if decimal(row.get("quantity", "0")) > ZERO and row.get("symbol"):
            symbols.add(str(row.get("symbol", "")).split(".")[0])
    return symbols


def existing_submission_ids(config: M15PaperSubmitterConfig) -> set[str]:
    path = config.output_dir / LEDGER_JSONL
    if not path.exists():
        return set()
    rows = read_jsonl(path)
    return {
        str(row.get("signal_fingerprint") or row.get("preview_id", ""))
        for row in rows
        if row.get("submission_status") == "submitted"
    }


def longbridge_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    return symbol if "." in symbol else f"{symbol}.US"


def redact_command(command: list[str]) -> list[str]:
    return [item for item in command if item != "--yes"]


def safe_error(value: str) -> str:
    return " ".join(value.strip().split())[:300]


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def decimal(value: Any) -> Decimal:
    try:
        if value in (None, ""):
            return ZERO
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY))


def render_markdown(summary: dict[str, Any], ledger_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 长桥模拟账户订单提交器",
        "",
        f"- 状态：`{summary['submission_status']}`",
        f"- 人话结论：{summary['plain_language_result']}",
        f"- 纽约时间：`{summary['market_window'].get('new_york_time')}`",
        f"- 北京时间：`{summary['market_window'].get('beijing_time')}`",
        f"- 订单来源：`{summary.get('order_source_mode', '')}`",
        f"- 队列日期：`{summary.get('preview_scan_date', '')}`",
        f"- 行情来源：`{summary.get('preview_quote_source', '')}`",
        f"- 当天策略名单确认：`{summary.get('current_day_strategy_confirmation_status', '')}`",
        f"- 模拟账户通道：`{summary['longbridge_account'].get('account_channel')}`",
        f"- 新账户起点：`{summary.get('paper_account_start_at')}`",
        "- 旧本地模拟持仓/旧订单迁移：否，只提交新账户起点之后的新开仓信号。",
        f"- 可用购买力：`{summary['longbridge_account'].get('buying_power')}`",
        f"- 下一轮检查间隔秒：`{summary.get('next_interval_seconds', '')}`",
        f"- 符合提交条件订单：`{summary.get('eligible_order_count', 0)}`",
        f"- 已提交订单：`{summary.get('submitted_order_count', 0)}`",
        f"- 全局阻断：`{', '.join(summary.get('global_blockers', [])) or 'none'}`",
        "- 边界：只限长桥模拟账户，不做碎股、不做融券做空、不做期权、不触碰真实资金。",
        "",
        "## 本轮明细",
        "",
        "| 状态 | 运行单元 | 标的 | 数量 | 限价 | 金额 | 阻断 |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in ledger_rows:
        lines.append(
            f"| {row.get('submission_status', '')} | {row.get('runtime_id', '')} | {row.get('symbol', '')} | "
            f"{row.get('quantity', '')} | {row.get('limit_price', '')} | {row.get('notional', '')} | "
            f"{', '.join(row.get('blockers', [])) or 'none'} |"
        )
    return "\n".join(lines) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_log(config: M15PaperSubmitterConfig, line: str) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    with (config.output_dir / LOG_FILE).open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
