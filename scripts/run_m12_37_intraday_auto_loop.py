#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time as wall_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_29_current_day_scan_dashboard_lib import (  # noqa: E402
    load_config as load_m12_29_config,
    market_session_status,
    project_path,
    run_m12_29_current_day_scan_dashboard,
    validate_generated_at_for_artifacts,
    write_json,
)
from scripts.m13_daily_strategy_test_runner_lib import (  # noqa: E402
    load_config as load_m13_config,
    run_m13_daily_strategy_test_runner,
)
from scripts.m14_strategy_challenge_gate_lib import (  # noqa: E402
    load_config as load_m14_config,
    run_m14_strategy_challenge_gate,
)


DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_37_intraday_auto_loop.json"
PREOPEN_NATIVE_FETCH_BUDGET = 100
REGULAR_NATIVE_FETCH_BUDGET = 20


@dataclass(frozen=True, slots=True)
class M1237AutoLoopConfig:
    title: str
    run_id: str
    stage: str
    source_m12_29_config_path: Path
    refresh_seconds: int
    observer_interval_minutes: int
    market_timezone: str
    codex_observer_enabled: bool
    codex_observer_mode: str
    post_run_strategy_ledgers_enabled: bool
    post_run_m13_config_path: Path
    post_run_m14_config_path: Path
    post_run_m14_finalize_policy: str
    paper_simulated_only: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool
    paper_trading_approval: bool


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def load_auto_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M1237AutoLoopConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    boundary = payload["boundary"]
    observer = payload["codex_observer"]
    post_run = payload.get("post_run_strategy_ledgers", {})
    config = M1237AutoLoopConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_37_intraday_auto_loop"),
        stage=payload["stage"],
        source_m12_29_config_path=resolve_repo_path(payload["source_m12_29_config_path"]),
        refresh_seconds=int(payload["refresh_seconds"]),
        observer_interval_minutes=int(payload["observer_interval_minutes"]),
        market_timezone=payload["market_timezone"],
        codex_observer_enabled=bool(observer["enabled"]),
        codex_observer_mode=observer["mode"],
        post_run_strategy_ledgers_enabled=bool(post_run.get("enabled", False)),
        post_run_m13_config_path=resolve_repo_path(post_run.get("m13_config_path", "config/examples/m13_daily_strategy_test_runner.json")),
        post_run_m14_config_path=resolve_repo_path(post_run.get("m14_config_path", "config/examples/m14_strategy_challenge_gate.json")),
        post_run_m14_finalize_policy=post_run.get("m14_finalize_policy", "postmarket_only"),
        paper_simulated_only=bool(boundary["paper_simulated_only"]),
        trading_connection=bool(boundary["trading_connection"]),
        real_money_actions=bool(boundary["real_money_actions"]),
        live_execution=bool(boundary["live_execution"]),
        paper_trading_approval=bool(boundary["paper_trading_approval"]),
    )
    validate_auto_config(config)
    return config


def validate_auto_config(config: M1237AutoLoopConfig) -> None:
    if config.stage != "M12.37.intraday_auto_loop":
        raise ValueError("M12.37 stage drift")
    if config.refresh_seconds != 60:
        raise ValueError("M12.37 refresh interval must stay 60 seconds")
    if config.observer_interval_minutes != 15:
        raise ValueError("M12.37 Codex observer interval must stay 15 minutes")
    if not config.paper_simulated_only:
        raise ValueError("M12.37 must stay paper/simulated only")
    if config.trading_connection or config.real_money_actions or config.live_execution or config.paper_trading_approval:
        raise ValueError("M12.37 cannot enable account connection, real money actions, live execution, or trial approval")
    if config.post_run_m14_finalize_policy not in {"postmarket_only", "runtime_ready_only", "postmarket_or_runtime_ready", "never"}:
        raise ValueError("Unsupported M14 finalize policy")


def run_once(
    config: M1237AutoLoopConfig,
    *,
    generated_at: str | None = None,
    execute_fetch: bool = True,
    max_native_fetches: int | None = None,
    refresh_quotes: bool = True,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    m12_29_config = load_m12_29_config(config.source_m12_29_config_path)
    result = run_m12_29_current_day_scan_dashboard(
        m12_29_config,
        generated_at=generated_at,
        execute_fetch=execute_fetch,
        max_native_fetches=max_native_fetches,
        refresh_quotes=refresh_quotes,
    )
    market = market_session_status(generated_at)
    post_run_strategy_ledgers = run_post_run_strategy_ledgers(
        config,
        generated_at=generated_at,
        trading_date=str(result["summary"].get("scan_date", "")),
        market_status=market["status"],
        m12_29_output_dir=m12_29_config.output_dir,
        m12_summary=result["summary"],
    )
    observer = result["dashboard"]["codex_observer"]
    monitoring_active = market["status"] in {"盘前", "美股常规交易时段", "盘后"}
    manifest = {
        "schema_version": "m12.37.auto-runner-manifest.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "market_session": market,
        "refresh_seconds": config.refresh_seconds,
        "observer_interval_minutes": config.observer_interval_minutes,
        "codex_observer_enabled": config.codex_observer_enabled,
        "codex_observer_mode": config.codex_observer_mode,
        "loop_can_continue_now": monitoring_active,
        "session_monitoring_active_now": monitoring_active,
        "regular_session_active_now": market["status"] == "美股常规交易时段",
        "latest_dashboard_json": project_path(m12_29_config.output_dir / "m12_32_minute_readonly_dashboard_data.json"),
        "latest_dashboard_html": project_path(m12_29_config.output_dir / "m12_32_minute_readonly_dashboard.html"),
        "latest_observer_json": project_path(m12_29_config.output_dir / "m12_38_codex_observer_latest.json"),
        "observer_inbox": project_path(m12_29_config.output_dir / "m12_38_codex_observer_inbox.jsonl"),
        "plain_language_result": observer["recommended_codex_message"],
        "post_run_strategy_ledgers": post_run_strategy_ledgers,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_json(m12_29_config.output_dir / "m12_37_auto_runner_manifest.json", manifest)
    return {
        "result": result,
        "manifest": manifest,
    }


def run_post_run_strategy_ledgers(
    config: M1237AutoLoopConfig,
    *,
    generated_at: str,
    trading_date: str,
    market_status: str,
    m12_29_output_dir: Path,
    m12_summary: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "m12.37.post-run-strategy-ledgers.v1",
        "enabled": config.post_run_strategy_ledgers_enabled,
        "generated_at": generated_at,
        "trading_date": trading_date,
        "market_status": market_status,
        "m13_ran": False,
        "m14_ran": False,
        "m14_skip_reason": "",
        "m13_error_type": "",
        "m13_error": "",
        "m14_error_type": "",
        "m14_error": "",
        "m13_goal_complete": False,
        "m14_goal_complete": False,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    if not config.post_run_strategy_ledgers_enabled:
        payload["m14_skip_reason"] = "post_run_strategy_ledgers_disabled"
        return payload

    try:
        m13_config = replace(
            load_m13_config(config.post_run_m13_config_path),
            m12_29_output_dir=m12_29_output_dir,
        )
        m13_result = run_m13_daily_strategy_test_runner(
            m13_config,
            generated_at=generated_at,
            trading_date=trading_date,
        )
    except Exception as exc:
        payload.update(
            {
                "m13_error_type": exc.__class__.__name__,
                "m13_error": str(exc),
                "m14_skip_reason": "m13_post_run_failed",
            }
        )
        return payload
    payload.update(
        {
            "m13_ran": True,
            "m13_goal_complete": bool(m13_result["goal_status"]["goal_complete"]),
            "m13_summary_ref": project_path(m13_config.output_dir / "m13_daily_strategy_test_summary.json"),
            "m13_goal_status_ref": project_path(m13_config.output_dir / "m13_goal_status.json"),
        }
    )

    should_run_m14, reason = should_run_m14_finalization(
        config.post_run_m14_finalize_policy,
        market_status=market_status,
        m12_summary=m12_summary,
    )
    if not should_run_m14:
        payload["m14_skip_reason"] = reason
        return payload

    try:
        m14_config = replace(
            load_m14_config(config.post_run_m14_config_path),
            m13_output_dir=m13_config.output_dir,
            m12_29_output_dir=m12_29_output_dir,
        )
        m14_result = run_m14_strategy_challenge_gate(
            m14_config,
            generated_at=generated_at,
            trading_date=trading_date,
        )
    except Exception as exc:
        payload.update(
            {
                "m14_error_type": exc.__class__.__name__,
                "m14_error": str(exc),
                "m14_skip_reason": "m14_post_run_failed",
            }
        )
        return payload
    payload.update(
        {
            "m14_ran": True,
            "m14_goal_complete": bool(m14_result["goal_status"]["goal_complete"]),
            "m14_summary_ref": project_path(m14_config.output_dir / "m14_strategy_challenge_summary.json"),
            "m14_goal_status_ref": project_path(m14_config.output_dir / "m14_goal_status.json"),
            "m14_paper_trial_gate_ref": project_path(m14_config.output_dir / "m14_paper_trial_gate.json"),
            "m14_skip_reason": "",
        }
    )
    return payload


def should_run_m14_finalization(
    policy: str,
    *,
    market_status: str,
    m12_summary: dict[str, Any],
) -> tuple[bool, str]:
    runtime_ready = bool(m12_summary.get("current_day_runtime_ready", False))
    postmarket = market_status == "盘后"
    if policy == "never":
        return False, "m14_finalize_policy_never"
    if policy == "postmarket_only":
        return (True, "") if postmarket else (False, "not_postmarket")
    if policy == "runtime_ready_only":
        return (True, "") if runtime_ready else (False, "current_day_runtime_not_ready")
    if policy == "postmarket_or_runtime_ready":
        if postmarket or runtime_ready:
            return True, ""
        return False, "not_postmarket_and_runtime_not_ready"
    raise ValueError("Unsupported M14 finalize policy")


def session_refresh_policy(generated_at: str, market_status: str, *, no_fetch: bool, no_refresh_quotes: bool) -> dict[str, Any]:
    ny_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
    preopen_window = market_status == "盘前" and wall_time(9, 25) <= ny_dt.time() < wall_time(9, 30)
    kline_refresh_due = market_status == "美股常规交易时段" and ny_dt.minute % 5 == 0
    if market_status == "美股常规交易时段":
        return {
            "execute_fetch": (not no_fetch) and kline_refresh_due,
            "refresh_quotes": not no_refresh_quotes,
            "max_native_fetches": REGULAR_NATIVE_FETCH_BUDGET if (not no_fetch) and kline_refresh_due else 0,
            "continue_session": True,
            "entered_regular_session": True,
        }
    if preopen_window:
        return {
            "execute_fetch": not no_fetch,
            "refresh_quotes": not no_refresh_quotes,
            "max_native_fetches": PREOPEN_NATIVE_FETCH_BUDGET if not no_fetch else 0,
            "continue_session": True,
            "entered_regular_session": False,
        }
    if market_status == "盘前":
        return {
            "execute_fetch": False,
            "refresh_quotes": not no_refresh_quotes,
            "max_native_fetches": 0,
            "continue_session": True,
            "entered_regular_session": False,
        }
    if market_status == "盘后":
        return {
            "execute_fetch": False,
            "refresh_quotes": not no_refresh_quotes,
            "max_native_fetches": 0,
            "continue_session": True,
            "entered_regular_session": True,
        }
    return {
        "execute_fetch": False,
        "refresh_quotes": False,
        "max_native_fetches": 0,
        "continue_session": False,
        "entered_regular_session": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M12.37 readonly simulated intraday auto loop.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to M12.37 auto-loop config JSON.")
    parser.add_argument("--generated-at", default=None, help="UTC ISO timestamp override, e.g. 2026-04-29T14:00:00Z.")
    parser.add_argument("--once", action="store_true", help="Run one refresh and exit. This is the default safe mode.")
    parser.add_argument("--loop", action="store_true", help="Refresh repeatedly during regular US trading session.")
    parser.add_argument("--session", action="store_true", help="Start before open, preheat during pre-market, then loop through the regular session until close.")
    parser.add_argument("--max-iterations", type=int, default=0, help="Optional loop limit for smoke tests.")
    parser.add_argument("--no-fetch", action="store_true", help="Do not call readonly Longbridge kline fetch; use existing cache only.")
    parser.add_argument("--max-native-fetches", type=int, default=None, help="Limit readonly native fetch calls.")
    parser.add_argument("--no-refresh-quotes", action="store_true", help="Do not call readonly Longbridge quote; use fallback quote data.")
    return parser.parse_args()


def validate_generated_at(value: str | None) -> None:
    if not value:
        return
    validate_generated_at_for_artifacts(value)


def main() -> int:
    args = parse_args()
    try:
        validate_generated_at(args.generated_at)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    config = load_auto_config(args.config)
    loop_enabled = args.loop and not args.once
    session_enabled = args.session and not args.once
    iteration = 0
    entered_regular_session = False
    while True:
        generated_at = args.generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        market = market_session_status(generated_at)
        if session_enabled:
            policy = session_refresh_policy(
                generated_at,
                market["status"],
                no_fetch=args.no_fetch,
                no_refresh_quotes=args.no_refresh_quotes,
            )
            execute_fetch = policy["execute_fetch"]
            refresh_quotes = policy["refresh_quotes"]
            max_native_fetches = policy["max_native_fetches"]
        else:
            execute_fetch = not args.no_fetch
            refresh_quotes = not args.no_refresh_quotes
            max_native_fetches = args.max_native_fetches
        outcome = run_once(
            config,
            generated_at=generated_at,
            execute_fetch=execute_fetch,
            max_native_fetches=max_native_fetches,
            refresh_quotes=refresh_quotes,
        )
        manifest = outcome["manifest"]
        print(json.dumps({
            "stage": manifest["stage"],
            "market_status": manifest["market_session"]["status"],
            "loop_can_continue_now": manifest["loop_can_continue_now"],
            "post_run_strategy_ledgers": {
                "m13_ran": manifest["post_run_strategy_ledgers"]["m13_ran"],
                "m14_ran": manifest["post_run_strategy_ledgers"]["m14_ran"],
                "m14_skip_reason": manifest["post_run_strategy_ledgers"]["m14_skip_reason"],
                "m13_error_type": manifest["post_run_strategy_ledgers"]["m13_error_type"],
                "m14_error_type": manifest["post_run_strategy_ledgers"]["m14_error_type"],
            },
            "summary": manifest["plain_language_result"],
        }, ensure_ascii=False, indent=2, sort_keys=True))
        iteration += 1
        if not loop_enabled and not session_enabled:
            break
        if args.max_iterations and iteration >= args.max_iterations:
            break
        if session_enabled:
            if market["status"] == "美股常规交易时段":
                entered_regular_session = True
            elif entered_regular_session:
                break
            elif not policy["continue_session"]:
                break
        elif not manifest["loop_can_continue_now"]:
            break
        time.sleep(config.refresh_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
