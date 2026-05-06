#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
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
    write_json,
)


DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_37_intraday_auto_loop.json"


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
    observer = result["dashboard"]["codex_observer"]
    manifest = {
        "schema_version": "m12.37.auto-runner-manifest.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "market_session": market,
        "refresh_seconds": config.refresh_seconds,
        "observer_interval_minutes": config.observer_interval_minutes,
        "codex_observer_enabled": config.codex_observer_enabled,
        "codex_observer_mode": config.codex_observer_mode,
        "loop_can_continue_now": market["status"] == "美股常规交易时段",
        "latest_dashboard_json": project_path(m12_29_config.output_dir / "m12_32_minute_readonly_dashboard_data.json"),
        "latest_dashboard_html": project_path(m12_29_config.output_dir / "m12_32_minute_readonly_dashboard.html"),
        "latest_observer_json": project_path(m12_29_config.output_dir / "m12_38_codex_observer_latest.json"),
        "observer_inbox": project_path(m12_29_config.output_dir / "m12_38_codex_observer_inbox.jsonl"),
        "plain_language_result": observer["recommended_codex_message"],
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


def session_refresh_policy(generated_at: str, market_status: str, *, no_fetch: bool, no_refresh_quotes: bool) -> dict[str, Any]:
    ny_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
    preopen_window = market_status == "盘前" and wall_time(9, 25) <= ny_dt.time() < wall_time(9, 30)
    kline_refresh_due = market_status == "美股常规交易时段" and ny_dt.minute % 5 == 0
    if market_status == "美股常规交易时段":
        return {
            "execute_fetch": (not no_fetch) and kline_refresh_due,
            "refresh_quotes": not no_refresh_quotes,
            "max_native_fetches": 1 if (not no_fetch) and kline_refresh_due else 0,
            "continue_session": True,
            "entered_regular_session": True,
        }
    if preopen_window:
        return {
            "execute_fetch": not no_fetch,
            "refresh_quotes": not no_refresh_quotes,
            "max_native_fetches": 3 if not no_fetch else 0,
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


def main() -> int:
    args = parse_args()
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
