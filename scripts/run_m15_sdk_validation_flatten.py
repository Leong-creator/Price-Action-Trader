#!/usr/bin/env python3
"""Safely clear the Longbridge paper account after a single SDK validation session."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_longbridge_realtime_execution_lib import to_iso, write_json
from scripts.m15_longbridge_sdk_account_lib import SdkAccountStateProvider, SdkTradeRequestGate, sdk_plain
from scripts.m15_longbridge_sdk_runtime_lib import DEFAULT_CONFIG_PATH, read_client_id, sdk_config_from_oauth, load_config
from scripts.m15_sdk_validation_flatten_lib import (
    build_flatten_plan,
    flatten_confirmation,
    formal_epoch_payload,
    in_regular_session,
    market_date,
    next_regular_session_start,
    pending_formal_epoch_payload,
)

FLATTEN_CONFIRMATION_TIMEOUT_SECONDS = 75
FLATTEN_CONFIRMATION_POLL_SECONDS = 2
OPEN_ORDER_CANCEL_TIMEOUT_SECONDS = 30
READ_RETRY_COUNT = 3
READ_RETRY_DELAY_SECONDS = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clear a paper account only after the approved SDK validation session.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--expected-market-date", required=True, help="New York market date authorized for this one cleanup.")
    parser.add_argument("--execute", action="store_true", help="Actually submit paper-account close orders.")
    return parser.parse_args()


def require_sdk() -> Any:
    import longbridge.openapi as sdk

    missing = [name for name in ("QuoteContext", "TradeContext", "PortfolioContext") if not getattr(sdk, name, None)]
    if missing:
        raise RuntimeError(f"sdk_contract_missing:{','.join(missing)}")
    return sdk


def sdk_contexts(config: Any) -> tuple[Any, Any, Any, Any]:
    sdk = require_sdk()
    oauth = sdk.OAuthBuilder(read_client_id(config)).build(lambda _url: None)
    trade = sdk.TradeContext(sdk_config_from_oauth(sdk, oauth, config.trade_region))
    portfolio = sdk.PortfolioContext(sdk_config_from_oauth(sdk, oauth, config.trade_region))
    quote = sdk.QuoteContext(sdk_config_from_oauth(sdk, oauth, config.quote_region))
    return sdk, trade, portfolio, quote


def latest_prices(quote: Any, symbols: list[str]) -> dict[str, Decimal]:
    prices: dict[str, dict[str, Any]] = {}
    if not symbols:
        return prices
    requested_at = datetime.now(UTC)
    response = sdk_plain(quote.quote(symbols))
    rows = response if isinstance(response, list) else [response]
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        for key in ("last_done", "last_price", "market_price", "current_price", "price", "close"):
            try:
                value = Decimal(str(row.get(key) or "0"))
            except Exception:
                value = Decimal("0")
            if symbol and value > 0:
                quote_at = None
                raw_timestamp = row.get("timestamp") or row.get("trade_timestamp") or row.get("updated_at")
                try:
                    if isinstance(raw_timestamp, datetime):
                        quote_at = raw_timestamp.astimezone(UTC) if raw_timestamp.tzinfo else raw_timestamp.replace(tzinfo=UTC)
                    elif raw_timestamp is not None:
                        quote_at = datetime.fromtimestamp(int(str(raw_timestamp)), UTC)
                except Exception:
                    quote_at = None
                age_ms = max(0, int((requested_at - quote_at).total_seconds() * 1000)) if quote_at else -1
                prices[symbol] = {"price": value, "age_ms": age_ms}
                break
    return prices


def latest_prices_with_fallback(
    quote: Any,
    symbols: list[str],
    *,
    retry_count: int = READ_RETRY_COUNT,
) -> tuple[dict[str, Decimal], list[str]]:
    errors: list[str] = []
    for attempt in range(1, retry_count + 1):
        try:
            return latest_prices(quote, symbols), errors
        except Exception as exc:
            errors.append(f"attempt={attempt}:{type(exc).__name__}:{exc}")
            if attempt < retry_count:
                time.sleep(READ_RETRY_DELAY_SECONDS)
    # build_flatten_plan has a conservative cost-price fallback. A quote-only
    # outage must not discard an otherwise verified paper-account close plan.
    return {}, errors


def refresh_account_with_retry(
    provider: SdkAccountStateProvider,
    *,
    retry_count: int = READ_RETRY_COUNT,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    account: dict[str, Any] = {}
    for attempt in range(1, retry_count + 1):
        account = provider.refresh()
        critical = list(account.get("critical_errors") or [])
        if account.get("paper_account_verified") and not critical:
            return account, errors
        errors.append(f"attempt={attempt}:" + ",".join(critical or ["paper_account_not_verified"]))
        if attempt < retry_count:
            time.sleep(READ_RETRY_DELAY_SECONDS)
    return account, errors


def account_snapshot_summary(account: dict[str, Any]) -> dict[str, Any]:
    positions = [row for row in account.get("positions", []) if isinstance(row, dict)]
    open_orders = [row for row in account.get("open_orders", []) if isinstance(row, dict)]
    return {
        "verified_position_count": len(positions),
        "verified_position_symbols": sorted(str(row.get("symbol") or "") for row in positions if row.get("symbol")),
        "verified_open_order_count": len(open_orders),
        "verified_open_order_ids": sorted(
            str(row.get("order_id") or row.get("id") or "") for row in open_orders if row.get("order_id") or row.get("id")
        ),
    }


def project_cli_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def canonical_watchdog_config_path(runtime_config_path: Path) -> Path:
    runtime_path = runtime_config_path.resolve()
    suffix = ""
    if runtime_path.name.startswith("m15_longbridge_sdk_runtime") and runtime_path.name.endswith(".json"):
        suffix = runtime_path.name[len("m15_longbridge_sdk_runtime") : -len(".json")]
    candidates = []
    if suffix:
        candidates.append(runtime_path.with_name(f"m15_background_watchdog{suffix}.json"))
    candidates.append(ROOT / "config" / "examples" / "m15_background_watchdog.contract_v1.json")
    candidates.append(ROOT / "config" / "examples" / "m15_background_watchdog.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def stop_trading_processes(runtime_config_path: Path) -> list[dict[str, Any]]:
    watchdog_config_path = canonical_watchdog_config_path(runtime_config_path)
    commands = [
        [
            sys.executable,
            "scripts/run_m15_background_watchdog.py",
            "--stop",
            "--config",
            project_cli_path(watchdog_config_path),
        ],
        [
            sys.executable,
            "scripts/run_m15_longbridge_sdk_runtime.py",
            "--stop",
            "--config",
            project_cli_path(runtime_config_path),
        ],
    ]
    results: list[dict[str, Any]] = []
    for command in commands:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
        results.append({"command": command[1], "returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()})
        if completed.returncode != 0:
            raise RuntimeError(f"failed_to_stop_trading_process:{command[1]}")
    return results


def cancel_open_orders(trade: Any, gate: SdkTradeRequestGate, account: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    orders = account.get("open_orders") if isinstance(account.get("open_orders"), list) else []
    for order in orders:
        if not isinstance(order, dict):
            continue
        order_id = str(order.get("order_id") or order.get("id") or "").strip()
        if not order_id:
            raise RuntimeError("open_order_missing_order_id")
        gate.call(lambda order_id=order_id: trade.cancel_order(order_id))
        results.append({"order_id": order_id, "status": "cancel_requested"})
    return results


def submit_plan(sdk: Any, trade: Any, gate: SdkTradeRequestGate, plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    outside_rth = getattr(getattr(sdk, "OutsideRTH", None), "RTHOnly", None)
    if outside_rth is None:
        raise RuntimeError("sdk_outside_rth_rth_only_unavailable")
    for item in plan:
        side = sdk.OrderSide.Buy if item["side"] == "buy" else sdk.OrderSide.Sell
        base_kwargs = {
            "symbol": item["symbol"],
            "order_type": sdk.OrderType.MO,
            "side": side,
            "submitted_quantity": Decimal(item["quantity"]),
            "time_in_force": sdk.TimeInForceType.Day,
            "outside_rth": outside_rth,
            "remark": f"m15-sdk-validation-flatten-{item['position_action']}"[:64],
        }
        fallback_kwargs = {
            **base_kwargs,
            "order_type": sdk.OrderType.LO,
            "submitted_price": Decimal(item["fallback_limit_price"]),
        }
        try:
            response = gate.call(lambda: trade.submit_order(**base_kwargs))
            order_id = str(getattr(response, "order_id", "") or "")
            results.append({**item, "order_id": order_id, "status": "submitted" if order_id else "submit_unconfirmed_missing_order_id"})
        except Exception as exc:
            can_fallback = (
                int(item.get("fallback_quote_age_ms", -1)) >= 0
                and int(item.get("fallback_quote_age_ms", -1)) <= 2000
            )
            if not can_fallback:
                raise
            fallback = gate.call(lambda: trade.submit_order(**fallback_kwargs))
            order_id = str(getattr(fallback, "order_id", "") or "")
            results.append(
                {
                    **item,
                    "order_id": order_id,
                    "status": "submitted" if order_id else "submit_unconfirmed_missing_order_id",
                    "fallback_used": True,
                    "fallback_reason": str(exc)[:300],
                }
            )
    return results


def prepare_formal_test_transition(config: Any, now: datetime) -> dict[str, Any]:
    if not config.formal_test_transition_enabled:
        return {}
    start_at = next_regular_session_start(now)
    marker = formal_epoch_payload(
        test_epoch_id=config.formal_test_epoch_id,
        short_test_epoch_id=config.formal_short_test_epoch_id,
        test_started_at=start_at,
        prepared_at=now,
    )
    epoch_state = {
        "schema_version": "m15.longbridge-virtual-account-epoch.v1",
        "enabled": True,
        "test_epoch_id": config.formal_test_epoch_id,
        "status": "active",
        "created_at": to_iso(now),
        "test_started_at": marker["test_started_at"],
        "archive_before": marker["test_started_at"],
        "archive_previous_records": True,
        "flatten_existing_positions_before_activation": True,
        "activation_blocker": "",
        "last_flatten_check_at": to_iso(now),
        "activated_at": marker["test_started_at"],
    }
    write_json(config.formal_test_marker_path, marker)
    write_json(config.formal_test_epoch_state_path, epoch_state)
    return marker


def prepare_pending_formal_test_transition(config: Any, now: datetime, reason: str) -> dict[str, Any]:
    if not config.formal_test_transition_enabled:
        return {}
    marker = pending_formal_epoch_payload(
        test_epoch_id=config.formal_test_epoch_id,
        short_test_epoch_id=config.formal_short_test_epoch_id,
        prepared_at=now,
        reason=reason,
    )
    epoch_state = {
        "schema_version": "m15.longbridge-virtual-account-epoch.v1",
        "enabled": True,
        "test_epoch_id": config.formal_test_epoch_id,
        "status": "pending_flatten",
        "created_at": to_iso(now),
        "test_started_at": "",
        "archive_before": to_iso(now),
        "archive_previous_records": True,
        "flatten_existing_positions_before_activation": True,
        "activation_blocker": reason,
        "last_flatten_check_at": to_iso(now),
    }
    write_json(config.formal_test_marker_path, marker)
    write_json(config.formal_test_epoch_state_path, epoch_state)
    return marker


def wait_for_flatten_confirmation(
    provider: SdkAccountStateProvider,
    order_ids: list[str],
    *,
    timeout_seconds: int = FLATTEN_CONFIRMATION_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    account: dict[str, Any] = {}
    confirmation: dict[str, Any] = {}
    while time.monotonic() < deadline:
        time.sleep(FLATTEN_CONFIRMATION_POLL_SECONDS)
        account = provider.refresh()
        if account.get("critical_errors"):
            continue
        confirmation = flatten_confirmation(account, order_ids)
        if confirmation["complete"]:
            return account, confirmation
    return account, confirmation or flatten_confirmation(account, order_ids)


def wait_for_open_orders_cleared(
    provider: SdkAccountStateProvider,
    *,
    timeout_seconds: int = OPEN_ORDER_CANCEL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    account: dict[str, Any] = {}
    while time.monotonic() < deadline:
        time.sleep(1)
        account = provider.refresh()
        if not account.get("critical_errors") and not account.get("open_orders"):
            return account
    raise RuntimeError("open_orders_remain_after_cancel_request")


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    now = datetime.now(UTC)
    output_path = config.output_dir / "m15_sdk_validation_flatten.json"
    payload: dict[str, Any] = {
        "stage": "M15.sdk_validation_flatten",
        "generated_at": to_iso(now),
        "expected_market_date": args.expected_market_date,
        "actual_market_date": market_date(now),
        "execute_requested": bool(args.execute),
        "paper_simulated_only": True,
        "live_execution": False,
        "real_money_actions": False,
        "local_simulation_isolated": True,
    }
    trading_stopped = False
    paper_account_verified = False
    if market_date(now) != args.expected_market_date:
        payload.update({"status": "not_authorized_market_date", "reason": "scheduled_cleanup_date_has_passed_or_not_arrived"})
        write_json(output_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not in_regular_session(now):
        payload.update({"status": "blocked_outside_regular_session", "reason": "paper_cleanup_orders_are_rth_only"})
        write_json(output_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2 if args.execute else 0
    try:
        sdk, trade, portfolio, quote = sdk_contexts(config)
        gate = SdkTradeRequestGate()
        provider = SdkAccountStateProvider(trade, portfolio, request_gate=gate)
        account, account_retry_errors = refresh_account_with_retry(provider)
        payload["account_channel"] = account.get("account_channel")
        payload["paper_account_verified"] = bool(account.get("paper_account_verified"))
        payload["account_retry_errors"] = account_retry_errors
        payload["account_errors"] = list(account.get("errors") or [])
        payload.update(account_snapshot_summary(account))
        paper_account_verified = bool(account.get("paper_account_verified")) and not account.get("critical_errors")
        if not account.get("paper_account_verified") or account.get("critical_errors"):
            raise RuntimeError("paper_account_verification_failed")
        if not args.execute:
            prices, quote_errors = latest_prices_with_fallback(
                quote,
                [str(row.get("symbol") or "") for row in account.get("positions", []) if isinstance(row, dict)],
            )
            plan, blockers = build_flatten_plan(account, prices)
            payload.update({
                "status": "dry_run_ready" if not blockers else "dry_run_blocked",
                "plan": plan,
                "blockers": blockers,
                "quote_retry_errors": quote_errors,
                "quote_fallback_used": bool(quote_errors),
            })
        else:
            payload["stopped_processes"] = stop_trading_processes(config.config_path)
            trading_stopped = True
            # M15 may have submitted an order between the first preflight
            # snapshot and its orderly shutdown. Re-read before canceling or
            # planning any close order so this cleanup never acts on stale state.
            account, post_stop_retry_errors = refresh_account_with_retry(provider)
            payload["post_stop_account_retry_errors"] = post_stop_retry_errors
            payload.update(account_snapshot_summary(account))
            if not account.get("paper_account_verified") or account.get("critical_errors"):
                raise RuntimeError("paper_account_verification_failed_after_runtime_stop")
            cancel_results = cancel_open_orders(trade, gate, account)
            payload["cancel_results"] = cancel_results
            if cancel_results:
                account = wait_for_open_orders_cleared(provider)
            prices, quote_errors = latest_prices_with_fallback(
                quote,
                [str(row.get("symbol") or "") for row in account.get("positions", []) if isinstance(row, dict)],
            )
            payload["quote_retry_errors"] = quote_errors
            payload["quote_fallback_used"] = bool(quote_errors)
            plan, blockers = build_flatten_plan(account, prices)
            payload["planned_position_count"] = len(plan)
            payload["planned_symbols"] = [str(item.get("symbol") or "") for item in plan]
            if blockers:
                payload.update({"status": "blocked_flatten_plan", "cancel_results": cancel_results, "blockers": blockers})
            elif not plan:
                payload.update({
                    "status": "no_positions",
                    "cancel_results": cancel_results,
                    "plan": [],
                    "confirmation": flatten_confirmation(account, []),
                    "formal_test_transition": prepare_formal_test_transition(config, datetime.now(UTC)),
                })
            else:
                submissions = submit_plan(sdk, trade, gate, plan)
                order_ids = [str(item.get("order_id") or "") for item in submissions]
                if not all(order_ids):
                    payload.update({
                        "status": "submitted_with_unconfirmed_orders",
                        "cancel_results": cancel_results,
                        "plan": plan,
                        "submissions": submissions,
                    })
                else:
                    _confirmed_account, confirmation = wait_for_flatten_confirmation(provider, order_ids)
                    completed = bool(confirmation.get("complete"))
                    payload.update({
                        "status": "completed" if completed else "submitted_pending_confirmation",
                        "cancel_results": cancel_results,
                        "plan": plan,
                        "submissions": submissions,
                        "confirmation": confirmation,
                        "formal_test_transition": (
                            prepare_formal_test_transition(config, datetime.now(UTC)) if completed else {}
                        ),
                    })
    except Exception as exc:
        reason = f"{type(exc).__name__}:{exc}"
        payload.update({"status": "failed", "reason": reason})
        if trading_stopped and paper_account_verified:
            payload["formal_test_transition"] = prepare_pending_formal_test_transition(
                config,
                datetime.now(UTC),
                f"validation_flatten_incomplete:{reason}",
            )
    write_json(output_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") in {"dry_run_ready", "completed", "no_positions"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
