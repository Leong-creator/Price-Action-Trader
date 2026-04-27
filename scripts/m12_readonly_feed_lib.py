#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m12_readonly_auth_preflight_lib import _assert_readonly_command, clean_cli_text


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_BASE_DIR = M10_DIR / "m12_read_only_pipeline"
M12_1_DIR = M12_BASE_DIR / "m12_1_readonly_feed"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_longbridge_readonly_feed.json"
TIMEFRAME_TO_LONGBRIDGE_PERIOD = {
    "1d": "day",
    "1h": "1h",
    "15m": "15m",
    "5m": "5m",
}
DEFAULT_CORE_STRATEGIES = ("M10-PA-001", "M10-PA-002", "M10-PA-012")
FORBIDDEN_LEDGER_KEYS = {"order", "order_id", "fill", "fill_price", "position", "cash", "pnl", "profit_loss"}


@dataclass(frozen=True, slots=True)
class ReadonlyFeedConfig:
    title: str
    run_id: str
    symbols: tuple[str, ...]
    market: str
    timeframes: tuple[str, ...]
    strategy_scope: tuple[str, ...]
    auth_preflight_path: Path
    observation_queue_path: Path
    output_dir: Path
    paper_simulated_only: bool
    broker_connection: bool
    real_orders: bool
    live_execution: bool


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def load_readonly_feed_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ReadonlyFeedConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    return ReadonlyFeedConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_1_longbridge_readonly_feed"),
        symbols=tuple(payload["symbols"]),
        market=payload.get("market", "US"),
        timeframes=tuple(payload["timeframes"]),
        strategy_scope=tuple(payload.get("strategy_scope", DEFAULT_CORE_STRATEGIES)),
        auth_preflight_path=resolve_repo_path(payload["auth_preflight_path"]),
        observation_queue_path=resolve_repo_path(payload["observation_queue_path"]),
        output_dir=resolve_repo_path(payload["output_dir"]),
        paper_simulated_only=bool(payload.get("paper_simulated_only", True)),
        broker_connection=bool(payload.get("broker_connection", False)),
        real_orders=bool(payload.get("real_orders", False)),
        live_execution=bool(payload.get("live_execution", False)),
    )


def run_m12_readonly_feed(config: ReadonlyFeedConfig, *, generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    validate_config_boundaries(config)

    auth_preflight = load_json(config.auth_preflight_path)
    auth_ready = auth_preflight.get("auth_status") == "valid_readonly_market_data"
    cli_path = shutil.which("longbridge")
    deferred: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    quote_snapshot: dict[str, Any] = {
        "status": "not_run",
        "row_count": 0,
        "symbols": [],
        "error": "",
    }

    if not auth_ready:
        deferred.append({"scope": "feed", "reason": "auth_preflight_not_ready", "auth_status": auth_preflight.get("auth_status", "unknown")})
    elif cli_path is None:
        deferred.append({"scope": "feed", "reason": "longbridge_cli_missing"})
    else:
        quote_snapshot = fetch_quote_snapshot(cli_path, config)
        for symbol in config.symbols:
            for timeframe in config.timeframes:
                try:
                    rows = fetch_latest_kline_rows(cli_path, symbol=symbol, market=config.market, timeframe=timeframe)
                except RuntimeError as exc:
                    deferred.append(
                        {
                            "scope": "bar",
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "reason": "longbridge_kline_failed",
                            "detail": str(exc)[:300],
                        }
                    )
                    continue
                if not rows:
                    deferred.append({"scope": "bar", "symbol": symbol, "timeframe": timeframe, "reason": "no_kline_rows_returned"})
                    continue
                ledger_rows.append(build_ledger_row(config, symbol=symbol, timeframe=timeframe, raw_bar=rows[-1], generated_at=generated_at))

    ledger_rows.sort(key=lambda item: (item["symbol"], item["timeframe"], item["bar_timestamp"]))
    for row in ledger_rows:
        validate_ledger_row(row)

    manifest = build_manifest(config, generated_at, auth_preflight, quote_snapshot, ledger_rows, deferred)
    write_json(config.output_dir / "m12_1_readonly_feed_manifest.json", manifest)
    write_jsonl(config.output_dir / "m12_1_bar_close_observation_ledger.jsonl", ledger_rows)
    write_json(config.output_dir / "m12_1_deferred_inputs.json", {"schema_version": "m12.deferred-inputs.v1", "stage": "M12.1.longbridge_readonly_feed", "items": deferred})
    (config.output_dir / "m12_1_feed_health_report.md").write_text(build_health_report(manifest), encoding="utf-8")
    return manifest


def validate_config_boundaries(config: ReadonlyFeedConfig) -> None:
    if not config.paper_simulated_only:
        raise ValueError("M12.1 requires paper_simulated_only=true")
    if config.broker_connection or config.real_orders or config.live_execution:
        raise ValueError("M12.1 must keep broker_connection, real_orders, and live_execution disabled")
    if config.strategy_scope != DEFAULT_CORE_STRATEGIES:
        raise ValueError(f"M12.1 strategy scope must stay Tier A only: {config.strategy_scope}")
    unsupported = sorted(set(config.timeframes) - set(TIMEFRAME_TO_LONGBRIDGE_PERIOD))
    if unsupported:
        raise ValueError(f"Unsupported M12.1 timeframes: {unsupported}")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_longbridge_symbol(symbol: str, market: str) -> str:
    return symbol if "." in symbol else f"{symbol}.{market.upper()}"


def fetch_quote_snapshot(cli_path: str, config: ReadonlyFeedConfig) -> dict[str, Any]:
    symbols = [build_longbridge_symbol(symbol, config.market) for symbol in config.symbols]
    command = ["quote", *symbols, "--format", "json"]
    payload = run_longbridge_json(cli_path, command)
    rows = payload if isinstance(payload, list) else []
    return {
        "status": "ok",
        "row_count": len(rows),
        "symbols": [row.get("symbol") for row in rows if isinstance(row, dict)],
        "error": "",
    }


def fetch_latest_kline_rows(cli_path: str, *, symbol: str, market: str, timeframe: str) -> list[dict[str, Any]]:
    period = TIMEFRAME_TO_LONGBRIDGE_PERIOD[timeframe]
    command = [
        "kline",
        build_longbridge_symbol(symbol, market),
        "--period",
        period,
        "--count",
        "1",
        "--format",
        "json",
    ]
    if timeframe in {"1h", "15m", "5m"}:
        command.extend(["--session", "intraday"])
    payload = run_longbridge_json(cli_path, command)
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected kline payload for {symbol} {timeframe}: {payload!r}")
    return [row for row in payload if isinstance(row, dict)]


def run_longbridge_json(cli_path: str, args: list[str]) -> Any:
    _assert_readonly_command(args)
    completed = subprocess.run([cli_path, *args], capture_output=True, text=True, check=False, timeout=30)
    if completed.returncode != 0:
        detail = clean_cli_text((completed.stderr or completed.stdout or "").strip())
        raise RuntimeError(detail or f"longbridge {' '.join(args)} failed with {completed.returncode}")
    stdout = completed.stdout.strip()
    if not stdout:
        return []
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"longbridge returned non-JSON output for {' '.join(args)}") from exc


def build_ledger_row(
    config: ReadonlyFeedConfig,
    *,
    symbol: str,
    timeframe: str,
    raw_bar: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    timestamp = str(raw_bar.get("time", ""))
    if not timestamp:
        raise RuntimeError(f"Longbridge kline row has no time for {symbol} {timeframe}: {raw_bar!r}")
    return {
        "schema_version": "m12.readonly-feed-event.v1",
        "stage": "M12.1.longbridge_readonly_feed",
        "generated_at": generated_at,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "source": "longbridge_cli_readonly_kline",
        "symbol": symbol,
        "market": config.market,
        "timeframe": timeframe,
        "bar_timestamp": timestamp,
        "bar_status": bar_status_for(timeframe),
        "observation_semantics": observation_semantics_for(timeframe),
        "eligible_strategy_ids": list(config.strategy_scope),
        "ohlcv": {
            "open": str(raw_bar.get("open", "")),
            "high": str(raw_bar.get("high", "")),
            "low": str(raw_bar.get("low", "")),
            "close": str(raw_bar.get("close", "")),
            "volume": str(raw_bar.get("volume", "")),
        },
        "lineage": {
            "provider": "longbridge",
            "command": "kline",
            "period": TIMEFRAME_TO_LONGBRIDGE_PERIOD[timeframe],
            "session": "intraday" if timeframe in {"1h", "15m", "5m"} else "regular_daily",
            "quote_snapshot_role": "liveness_only",
        },
        "review_status": "input_ready_for_m12_2_observation",
    }


def bar_status_for(timeframe: str) -> str:
    if timeframe == "1d":
        return "latest_daily_bar_requires_after_close_use"
    return "latest_intraday_bar_requires_bar_close_use"


def observation_semantics_for(timeframe: str) -> str:
    if timeframe == "1d":
        return "daily_after_close_observation_only"
    return "regular_session_bar_close_observation_only"


def validate_ledger_row(row: dict[str, Any]) -> None:
    for key in ("paper_simulated_only", "broker_connection", "real_orders", "live_execution"):
        if key == "paper_simulated_only" and row.get(key) is not True:
            raise ValueError("M12.1 ledger row must be paper_simulated_only")
        if key != "paper_simulated_only" and row.get(key) is not False:
            raise ValueError(f"M12.1 ledger row must keep {key}=false")
    forbidden = find_forbidden_keys(row)
    if forbidden:
        raise ValueError(f"M12.1 ledger row contains execution/account keys: {sorted(forbidden)}")


def find_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_LEDGER_KEYS:
                found.add(key)
            found.update(find_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(find_forbidden_keys(child))
    return found


def build_manifest(
    config: ReadonlyFeedConfig,
    generated_at: str,
    auth_preflight: dict[str, Any],
    quote_snapshot: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    deferred: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "m12.readonly-feed-manifest.v1",
        "stage": "M12.1.longbridge_readonly_feed",
        "generated_at": generated_at,
        "run_id": config.run_id,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "auth_preflight_ref": project_path(config.auth_preflight_path),
        "auth_status": auth_preflight.get("auth_status", "unknown"),
        "observation_queue_ref": project_path(config.observation_queue_path),
        "symbols": list(config.symbols),
        "timeframes": list(config.timeframes),
        "strategy_scope": list(config.strategy_scope),
        "quote_snapshot": quote_snapshot,
        "ledger_row_count": len(ledger_rows),
        "deferred_count": len(deferred),
        "lineage": {
            "provider": "longbridge",
            "primary_input": "readonly_kline_poll",
            "quote_role": "health_check_only",
            "subscriptions_role": "diagnostic_only",
        },
        "output_refs": {
            "manifest": project_path(config.output_dir / "m12_1_readonly_feed_manifest.json"),
            "ledger": project_path(config.output_dir / "m12_1_bar_close_observation_ledger.jsonl"),
            "deferred": project_path(config.output_dir / "m12_1_deferred_inputs.json"),
            "report": project_path(config.output_dir / "m12_1_feed_health_report.md"),
        },
    }


def build_health_report(manifest: dict[str, Any]) -> str:
    lines = [
        "# M12.1 Longbridge Read-only Feed Health Report",
        "",
        "## 结论",
        "",
        f"- auth status: `{manifest['auth_status']}`",
        f"- ledger rows: `{manifest['ledger_row_count']}`",
        f"- deferred inputs: `{manifest['deferred_count']}`",
        "- 本阶段只生成只读 bar-close 输入，不运行策略、不生成执行字段、不输出盈亏结论。",
        "",
        "## 范围",
        "",
        f"- symbols: `{' / '.join(manifest['symbols'])}`",
        f"- timeframes: `{' / '.join(manifest['timeframes'])}`",
        f"- strategy scope: `{' / '.join(manifest['strategy_scope'])}`",
        "- `1d` 只用于收盘后观察；`1h / 15m / 5m` 只用于 regular-session bar close 后观察。",
        "",
        "## 数据角色",
        "",
        "- K 线轮询是主输入。",
        "- Quote snapshot 只做健康检查。",
        "- Subscriptions 只做诊断，不作为当前依赖。",
    ]
    return "\n".join(lines) + "\n"


def project_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
