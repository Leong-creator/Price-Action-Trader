#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_8_DIR = M10_DIR / "kline_cache" / "m12_8_universe_kline_cache"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_universe_kline_cache.json"
FORBIDDEN_CONFIG_KEYS = {"broker_connection", "real_orders", "live_execution", "paper_trading_approval"}
FORBIDDEN_OUTPUT_TEXT = ("PA-SC-", "SF-", "live-ready", "real_orders=true", "broker_connection=true")
COMPLETE_COVERAGE_STATUSES = {"complete_for_target_window", "complete_from_first_available_bar"}
CSV_NAME_RE = re.compile(
    r"^(?P<market>[a-z]+)_(?P<symbol>.+)_(?P<interval>[^_]+)_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})_(?P<source>[^.]+)\.csv$"
)


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    mode: str
    allow_readonly_fetch: bool
    max_fetch_symbols: int
    max_requests_per_run: int
    write_local_data: bool


@dataclass(frozen=True, slots=True)
class UniverseKlineCacheConfig:
    title: str
    run_id: str
    stage: str
    market: str
    universe_definition_path: Path
    local_data_roots: tuple[Path, ...]
    output_dir: Path
    daily_start: date
    daily_end: date
    intraday_start: date
    intraday_end: date
    daily_interval: str
    intraday_interval: str
    derived_timeframes: tuple[str, ...]
    fetch_policy: FetchPolicy


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def project_path(path: Path | None) -> str:
    if path is None:
        return ""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def load_universe_kline_cache_config(path: str | Path = DEFAULT_CONFIG_PATH) -> UniverseKlineCacheConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    forbidden = FORBIDDEN_CONFIG_KEYS & set(payload)
    if forbidden:
        raise ValueError(f"M12.8 config must not contain execution boundary fields: {sorted(forbidden)}")
    policy_payload = payload["fetch_policy"]
    config = UniverseKlineCacheConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_8_universe_kline_cache"),
        stage=payload["stage"],
        market=payload.get("market", "US"),
        universe_definition_path=resolve_repo_path(payload["universe_definition_path"]),
        local_data_roots=tuple(resolve_repo_path(item) for item in payload.get("local_data_roots", ["local_data"])),
        output_dir=resolve_repo_path(payload["output_dir"]),
        daily_start=date.fromisoformat(payload["daily_start"]),
        daily_end=date.fromisoformat(payload["daily_end"]),
        intraday_start=date.fromisoformat(payload["intraday_start"]),
        intraday_end=date.fromisoformat(payload["intraday_end"]),
        daily_interval=payload.get("daily_interval", "1d"),
        intraday_interval=payload.get("intraday_interval", "5m"),
        derived_timeframes=tuple(payload.get("derived_timeframes", ("15m", "1h"))),
        fetch_policy=FetchPolicy(
            mode=policy_payload["mode"],
            allow_readonly_fetch=bool(policy_payload.get("allow_readonly_fetch", False)),
            max_fetch_symbols=int(policy_payload.get("max_fetch_symbols", 0)),
            max_requests_per_run=int(policy_payload.get("max_requests_per_run", 0)),
            write_local_data=bool(policy_payload.get("write_local_data", False)),
        ),
    )
    validate_config(config)
    return config


def validate_config(config: UniverseKlineCacheConfig) -> None:
    if config.stage != "M12.8.universe_kline_cache_completion":
        raise ValueError("M12.8 stage drift")
    if config.daily_interval != "1d":
        raise ValueError("M12.8 daily interval must stay 1d")
    if config.intraday_interval != "5m":
        raise ValueError("M12.8 intraday native interval must stay 5m")
    if set(config.derived_timeframes) != {"15m", "1h"}:
        raise ValueError("M12.8 derived timeframes must be exactly 15m and 1h")
    if config.fetch_policy.allow_readonly_fetch or config.fetch_policy.write_local_data:
        raise ValueError("Default checked-in M12.8 config must be inventory/fetch-plan only")
    if config.fetch_policy.mode != "inventory_and_fetch_plan_only":
        raise ValueError("Default checked-in M12.8 mode must be inventory_and_fetch_plan_only")
    if config.fetch_policy.max_fetch_symbols != 0 or config.fetch_policy.max_requests_per_run != 0:
        raise ValueError("Default checked-in M12.8 config must not issue live requests")


def run_m12_universe_kline_cache(
    config: UniverseKlineCacheConfig,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    validate_config(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    universe = load_universe_symbols(config)
    manifest_rows: list[dict[str, Any]] = []
    for symbol in universe:
        daily = best_cache_file(config.local_data_roots, "longbridge_history", config.market, symbol, config.daily_interval)
        intraday = best_cache_file(config.local_data_roots, "longbridge_intraday", config.market, symbol, config.intraday_interval)
        daily_row = build_manifest_row(
            config=config,
            symbol=symbol,
            timeframe=config.daily_interval,
            lineage="native_cache",
            cache_path=daily,
            target_start=config.daily_start,
            target_end=config.daily_end,
            source_timeframe=config.daily_interval,
        )
        intraday_row = build_manifest_row(
            config=config,
            symbol=symbol,
            timeframe=config.intraday_interval,
            lineage="native_cache",
            cache_path=intraday,
            target_start=config.intraday_start,
            target_end=config.intraday_end,
            source_timeframe=config.intraday_interval,
        )
        manifest_rows.append(daily_row)
        manifest_rows.append(intraday_row)
        for derived in config.derived_timeframes:
            manifest_rows.append(
                build_manifest_row(
                    config=config,
                    symbol=symbol,
                    timeframe=derived,
                    lineage="derived_from_5m",
                    cache_path=intraday,
                    target_start=config.intraday_start,
                    target_end=config.intraday_end,
                    source_timeframe=config.intraday_interval,
                )
            )

    deferred = build_deferred_ledger(manifest_rows)
    fetch_plan = build_fetch_plan(config, manifest_rows, generated_at)
    available = build_available_universe(config, universe, manifest_rows, generated_at)
    summary = build_summary(config, generated_at, universe, manifest_rows, deferred, fetch_plan, available)

    write_json(config.output_dir / "m12_8_universe_cache_manifest.json", {
        "schema_version": "m12.universe-cache-manifest.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "items": manifest_rows,
    })
    write_json(config.output_dir / "m12_8_deferred_or_error_ledger.json", {
        "schema_version": "m12.universe-cache-deferred-ledger.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "items": deferred,
    })
    write_json(config.output_dir / "m12_8_fetch_plan.json", fetch_plan)
    write_json(config.output_dir / "m12_8_scanner_available_universe.json", available)
    write_json(config.output_dir / "m12_8_cache_completion_summary.json", summary)
    (config.output_dir / "m12_8_cache_coverage_report.md").write_text(
        build_report(summary, available, fetch_plan),
        encoding="utf-8",
    )
    (config.output_dir / "m12_8_handoff.md").write_text(build_handoff(config, summary), encoding="utf-8")
    assert_no_forbidden_output(config.output_dir)
    return summary


def load_universe_symbols(config: UniverseKlineCacheConfig) -> list[str]:
    payload = json.loads(config.universe_definition_path.read_text(encoding="utf-8"))
    symbols = list(dict.fromkeys(payload.get("symbols", [])))
    if payload.get("stage") != "M12.5.liquid_universe_scanner":
        raise ValueError("M12.8 must consume M12.5 universe definition")
    if payload.get("market") != config.market:
        raise ValueError("M12.8 market must match M12.5 universe definition")
    if len(symbols) != 147:
        raise ValueError(f"M12.8 expected 147 M12.5 seed symbols, got {len(symbols)}")
    return symbols


def best_cache_file(roots: Iterable[Path], subdir: str, market: str, symbol: str, interval: str) -> Path | None:
    candidates: list[Path] = []
    pattern = f"{market.lower()}_{symbol.replace('.', '-')}_{interval}_*_longbridge.csv"
    for root in roots:
        directory = root / subdir
        if directory.exists():
            candidates.extend(directory.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda path: (cache_file_date_window(path)[1] or date.min, csv_stats(path)["row_count"], path.name))


def build_manifest_row(
    *,
    config: UniverseKlineCacheConfig,
    symbol: str,
    timeframe: str,
    lineage: str,
    cache_path: Path | None,
    target_start: date,
    target_end: date,
    source_timeframe: str,
) -> dict[str, Any]:
    stats = csv_stats(cache_path)
    coverage = coverage_status(stats, target_start, target_end)
    return {
        "symbol": symbol,
        "market": config.market,
        "timeframe": timeframe,
        "lineage": lineage,
        "source_timeframe": source_timeframe,
        "target_start": target_start.isoformat(),
        "target_end": target_end.isoformat(),
        "cache_exists": cache_path is not None,
        "cache_path": project_path(cache_path),
        "checksum": sha256_file(cache_path),
        "row_count": stats["row_count"],
        "cache_start": stats["start_date"],
        "cache_end": stats["end_date"],
        "timezone": stats["timezone"],
        "coverage_status": coverage["status"],
        "coverage_reason": coverage["reason"],
        "local_data_tracked": False,
        "ready_for_scanner_full_universe": is_complete_coverage_status(coverage["status"]),
    }


def csv_stats(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"row_count": 0, "start_date": "", "end_date": "", "timezone": "", "request_start_date": "", "request_end_date": ""}
    request_start, request_end = cache_file_date_window(path)
    row_count = 0
    first_timestamp = ""
    last_timestamp = ""
    timezone = ""
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            timestamp = row.get("timestamp", "")
            if row_count == 1:
                first_timestamp = timestamp
                timezone = row.get("timezone", "")
            last_timestamp = timestamp
    return {
        "row_count": row_count,
        "start_date": timestamp_date(first_timestamp).isoformat() if first_timestamp else "",
        "end_date": timestamp_date(last_timestamp).isoformat() if last_timestamp else "",
        "timezone": timezone,
        "request_start_date": request_start.isoformat() if request_start else "",
        "request_end_date": request_end.isoformat() if request_end else "",
    }


def timestamp_date(value: str) -> date:
    return datetime.fromisoformat(value).date()


def coverage_status(stats: dict[str, Any], target_start: date, target_end: date) -> dict[str, str]:
    if not stats["row_count"]:
        return {"status": "missing_cache", "reason": "No local CSV cache found for this symbol/timeframe."}
    cache_start = date.fromisoformat(stats["start_date"])
    cache_end = date.fromisoformat(stats["end_date"])
    if cache_end < target_end:
        return {
            "status": "stale_cache",
            "reason": f"Cache ends at {cache_end.isoformat()}, before target end {target_end.isoformat()}.",
        }
    if cache_start > target_start:
        request_start_value = stats.get("request_start_date", "")
        if request_start_value and date.fromisoformat(request_start_value) <= target_start:
            return {
                "status": "complete_from_first_available_bar",
                "reason": (
                    f"Cache was requested from {request_start_value} and first available bar is "
                    f"{cache_start.isoformat()}; treat as late listing / first available coverage through "
                    f"{cache_end.isoformat()}."
                ),
            }
        return {
            "status": "start_after_target_or_availability_gap",
            "reason": (
                f"Cache starts at {cache_start.isoformat()}, after requested start {target_start.isoformat()}; "
                "treat as availability gap until the first available bar is verified from a target-start request."
            ),
        }
    return {"status": "complete_for_target_window", "reason": "Cache covers requested target window."}


def is_complete_coverage_status(status: str) -> bool:
    return status in COMPLETE_COVERAGE_STATUSES


def build_deferred_ledger(manifest_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deferred: list[dict[str, Any]] = []
    for row in manifest_rows:
        if is_complete_coverage_status(row["coverage_status"]):
            continue
        action = "derive_after_5m_cache_complete" if row["lineage"] == "derived_from_5m" else "fetch_or_refresh_readonly_cache"
        deferred.append(
            {
                "symbol": row["symbol"],
                "market": row["market"],
                "timeframe": row["timeframe"],
                "lineage": row["lineage"],
                "reason": row["coverage_status"],
                "detail": row["coverage_reason"],
                "action": action,
                "fake_data_created": False,
            }
        )
    return deferred


def build_fetch_plan(
    config: UniverseKlineCacheConfig,
    manifest_rows: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    native_rows = [row for row in manifest_rows if row["lineage"] == "native_cache"]
    for row in native_rows:
        if is_complete_coverage_status(row["coverage_status"]):
            continue
        start = config.daily_start if row["timeframe"] == config.daily_interval else config.intraday_start
        end = config.daily_end if row["timeframe"] == config.daily_interval else config.intraday_end
        subdir = "longbridge_history" if row["timeframe"] == config.daily_interval else "longbridge_intraday"
        estimated_chunks = estimate_longbridge_chunks(start, end, row["timeframe"])
        requests.append(
            {
                "symbol": row["symbol"],
                "market": row["market"],
                "timeframe": row["timeframe"],
                "target_start": start.isoformat(),
                "target_end": end.isoformat(),
                "destination_path": project_path(
                    ROOT / "local_data" / subdir / f"{config.market.lower()}_{row['symbol']}_{row['timeframe']}_{start.isoformat()}_{end.isoformat()}_longbridge.csv"
                ),
                "estimated_longbridge_chunks": estimated_chunks,
                "readonly_command_template": (
                    f"longbridge kline history {row['symbol']}.{config.market} --start {start.isoformat()} "
                    f"--end {end.isoformat()} --period {'day' if row['timeframe'] == '1d' else row['timeframe']} "
                    "--adjust none --format json"
                ),
                "request_status": "planned_not_executed",
                "reason": row["coverage_status"],
            }
        )
    return {
        "schema_version": "m12.universe-cache-fetch-plan.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "fetch_enabled": False,
        "policy": {
            "mode": config.fetch_policy.mode,
            "allow_readonly_fetch": config.fetch_policy.allow_readonly_fetch,
            "max_fetch_symbols": config.fetch_policy.max_fetch_symbols,
            "max_requests_per_run": config.fetch_policy.max_requests_per_run,
            "write_local_data": config.fetch_policy.write_local_data,
            "missing_data_behavior": "deferred_no_fake_cache",
        },
        "request_count": len(requests),
        "estimated_chunk_count": sum(item["estimated_longbridge_chunks"] for item in requests),
        "requests": requests,
    }


def estimate_longbridge_chunks(start: date, end: date, timeframe: str) -> int:
    max_days = 900 if timeframe == "1d" else 5
    days = (end - start).days + 1
    return max(1, (days + max_days - 1) // max_days)


def build_available_universe(
    config: UniverseKlineCacheConfig,
    universe: list[str],
    manifest_rows: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    by_symbol: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in universe}
    for row in manifest_rows:
        by_symbol[row["symbol"]].append(row)
    cache_present_symbols = sorted(
        symbol
        for symbol, rows in by_symbol.items()
        if any(row["cache_exists"] and row["lineage"] == "native_cache" for row in rows)
    )
    target_complete_symbols = sorted(
        symbol
        for symbol, rows in by_symbol.items()
        if all(is_complete_coverage_status(row["coverage_status"]) for row in rows)
    )
    return {
        "schema_version": "m12.scanner-available-universe.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "universe_symbol_count": len(universe),
        "cache_present_symbol_count": len(cache_present_symbols),
        "target_complete_symbol_count": len(target_complete_symbols),
        "cache_present_symbols": cache_present_symbols,
        "target_complete_symbols": target_complete_symbols,
        "scanner_scope_note": (
            "Only target_complete_symbols may be called full-window ready. "
            "cache_present_symbols can be used for limited local-cache diagnostics only."
        ),
    }


def build_summary(
    config: UniverseKlineCacheConfig,
    generated_at: str,
    universe: list[str],
    manifest_rows: list[dict[str, Any]],
    deferred: list[dict[str, Any]],
    fetch_plan: dict[str, Any],
    available: dict[str, Any],
) -> dict[str, Any]:
    native_rows = [row for row in manifest_rows if row["lineage"] == "native_cache"]
    derived_rows = [row for row in manifest_rows if row["lineage"] == "derived_from_5m"]
    complete_native = [row for row in native_rows if is_complete_coverage_status(row["coverage_status"])]
    status_counts = Counter(row["coverage_status"] for row in manifest_rows)
    timeframe_status_counts = {
        timeframe: dict(Counter(row["coverage_status"] for row in manifest_rows if row["timeframe"] == timeframe))
        for timeframe in (config.daily_interval, config.intraday_interval, *config.derived_timeframes)
    }
    return {
        "schema_version": "m12.universe-cache-summary.v1",
        "stage": config.stage,
        "run_id": config.run_id,
        "generated_at": generated_at,
        "market": config.market,
        "universe_symbol_count": len(universe),
        "native_timeframe_rows": len(native_rows),
        "derived_timeframe_rows": len(derived_rows),
        "complete_native_timeframe_rows": len(complete_native),
        "target_complete_symbol_count": available["target_complete_symbol_count"],
        "cache_present_symbol_count": available["cache_present_symbol_count"],
        "deferred_item_count": len(deferred),
        "coverage_status_counts": dict(status_counts),
        "timeframe_status_counts": timeframe_status_counts,
        "fetch_plan_request_count": fetch_plan["request_count"],
        "fetch_plan_estimated_chunk_count": fetch_plan["estimated_chunk_count"],
        "fetch_enabled": fetch_plan["fetch_enabled"],
        "local_data_git_policy": "local_data_not_tracked; checked-in artifacts record path/checksum/coverage only",
        "no_fake_cache": True,
        "artifacts": {
            "cache_manifest": project_path(config.output_dir / "m12_8_universe_cache_manifest.json"),
            "deferred_or_error_ledger": project_path(config.output_dir / "m12_8_deferred_or_error_ledger.json"),
            "fetch_plan": project_path(config.output_dir / "m12_8_fetch_plan.json"),
            "scanner_available_universe": project_path(config.output_dir / "m12_8_scanner_available_universe.json"),
            "coverage_report": project_path(config.output_dir / "m12_8_cache_coverage_report.md"),
            "summary": project_path(config.output_dir / "m12_8_cache_completion_summary.json"),
            "handoff": project_path(config.output_dir / "m12_8_handoff.md"),
        },
    }


def build_report(summary: dict[str, Any], available: dict[str, Any], fetch_plan: dict[str, Any]) -> str:
    return f"""# M12.8 Universe Kline Cache Completion

## 摘要

- 股票池：`{summary['universe_symbol_count']}` 只 M12.5 US liquid seed。
- 当前有任一 native cache 的标的：`{summary['cache_present_symbol_count']}` 只。
- 完整覆盖目标窗口或已从首根可用 bar 覆盖到目标终点的标的：`{summary['target_complete_symbol_count']}` 只。
- deferred/error ledger 条目：`{summary['deferred_item_count']}` 条。
- fetch plan 请求：`{summary['fetch_plan_request_count']}` 条，估算 Longbridge chunk `{summary['fetch_plan_estimated_chunk_count']}` 个。

## 结论

M12.8 当前没有伪造 K 线，也没有把 `SPY/QQQ/NVDA/TSLA` 的局部缓存描述为全 universe 可用。
在 fetch plan 真正执行并重新生成 coverage 之前，scanner 只能把 `cache_present_symbols` 当作局部诊断输入，不能宣称 `147` 只股票全量可扫描。

## 可用集合

- cache present symbols：`{', '.join(available['cache_present_symbols']) or '-'}`
- target complete symbols：`{', '.join(available['target_complete_symbols']) or '-'}`

## 边界

- `local_data/` 继续不进入 Git；tracked artifact 只记录 logical path、checksum、row count、date span 和 lineage。
- `15m / 1h` 只从 `5m` 聚合，必须保留 `derived_from_5m`。
- 缺失、过期、限流或供应商异常只能进入 deferred/error ledger，不补假数据、不补假候选。
"""


def build_handoff(config: UniverseKlineCacheConfig, summary: dict[str, Any]) -> str:
    return f"""task_id: M12.8 Universe Kline Cache Completion
role: main_agent
branch_or_worktree: feature/m12-8-universe-kline-cache
objective: Inventory the full 147-symbol M12.5 universe, produce cache coverage/deferred/fetch-plan artifacts, and prevent partial-cache claims from being treated as full-universe scanner readiness.
status: success
files_changed:
  - config/examples/m12_universe_kline_cache.json
  - scripts/m12_universe_kline_cache_lib.py
  - scripts/run_m12_universe_kline_cache.py
  - tests/unit/test_m12_universe_kline_cache.py
  - README.md
  - docs/status.md
  - plans/active-plan.md
  - reports/strategy_lab/README.md
  - reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_universe_cache_manifest.json
  - reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_deferred_or_error_ledger.json
  - reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_fetch_plan.json
  - reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_scanner_available_universe.json
  - reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_cache_completion_summary.json
  - reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_cache_coverage_report.md
  - reports/strategy_lab/m10_price_action_strategy_refresh/kline_cache/m12_8_universe_kline_cache/m12_8_handoff.md
interfaces_changed:
  - Added M12.8 cache coverage and fetch-plan runner.
commands_run:
  - python scripts/run_m12_universe_kline_cache.py
tests_run:
  - see docs/status.md and final agent validation; this handoff is generated by the inventory runner and does not certify tests by itself
assumptions:
  - M12.8 checked-in run is inventory/fetch-plan only and does not issue mass Longbridge downloads.
  - Existing local cache is trusted only as path/checksum/date-span evidence.
risks:
  - Full 147-symbol scanner cannot be claimed ready until planned cache requests are executed and coverage is regenerated.
qa_focus:
  - Confirm manifest covers 147 symbols x 4 timeframes.
  - Confirm missing/stale rows are deferred and no fake cache is created.
rollback_notes:
  - Revert M12.8 commit or remove {project_path(config.output_dir)} artifacts.
next_recommended_action: Execute controlled readonly cache batches or continue to M12.9 visual closure while cache completion is scheduled.
needs_user_decision: false
user_decision_needed:
summary:
  universe_symbol_count: {summary['universe_symbol_count']}
  cache_present_symbol_count: {summary['cache_present_symbol_count']}
  target_complete_symbol_count: {summary['target_complete_symbol_count']}
  deferred_item_count: {summary['deferred_item_count']}
"""


def cache_file_date_window(path: Path) -> tuple[date | None, date | None]:
    match = CSV_NAME_RE.match(path.name)
    if not match:
        return None, None
    return date.fromisoformat(match.group("start")), date.fromisoformat(match.group("end"))


def sha256_file(path: Path | None) -> str:
    if path is None:
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output_dir.glob("m12_8_*")
        if path.is_file()
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_TEXT:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden M12.8 output text found: {forbidden}")
