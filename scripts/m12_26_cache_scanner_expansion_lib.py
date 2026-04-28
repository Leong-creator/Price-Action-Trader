#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M125_DIR = M10_DIR / "scanner" / "m12_5_liquid_universe_scanner"
M128_DIR = M10_DIR / "kline_cache" / "m12_8_universe_kline_cache"
M1212_DIR = M10_DIR / "daily_observation" / "m12_12_loop"
M1225_DIR = M10_DIR / "daily_observation" / "m12_25_continuity"
OUTPUT_DIR = M10_DIR / "scanner" / "m12_26_cache_scanner_expansion"

AUTO_SCANNER_STRATEGIES = ("M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001")
OBSERVATION_ONLY_STRATEGIES = ("M10-PA-007",)
EXCLUDED_AUTO_SCANNER_STRATEGIES = (
    "M10-PA-003",
    "M10-PA-004",
    "M10-PA-005",
    "M10-PA-006",
    "M10-PA-007",
    "M10-PA-008",
    "M10-PA-009",
    "M10-PA-010",
    "M10-PA-011",
    "M10-PA-013",
    "M10-PA-014",
    "M10-PA-015",
    "M10-PA-016",
)
FORBIDDEN_OUTPUT_TEXT = (
    "PA-SC-",
    "SF-",
    "live-ready",
    "real_orders=true",
    "broker_connection=true",
    "paper_trading_approval=true",
    "order_id",
    "fill_id",
    "account_id",
    "cash_balance",
    "position_qty",
)


def run_m12_26_cache_scanner_expansion(
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)

    universe = load_json(M125_DIR / "m12_5_universe_definition.json")
    first50_summary = load_json(M1212_DIR / "m12_12_first50_cache_summary.json")
    first50_inventory = load_json(M1212_DIR / "m12_12_first50_cache_inventory.json")["items"]
    m12_8_summary = load_json(M128_DIR / "m12_8_cache_completion_summary.json")
    m12_8_manifest = load_json(M128_DIR / "m12_8_universe_cache_manifest.json")["items"]
    m12_25_queue = load_json(M1225_DIR / "m12_25_strategy_observation_queue.json")["rows"]
    daily_candidates = read_csv(M1212_DIR / "m12_12_daily_candidates.csv")

    first50_symbols = first50_summary["daily_ready_symbol_list"]
    universe_symbols = universe["symbols"]
    additional_symbols = [symbol for symbol in universe_symbols if symbol not in set(first50_symbols)]
    first50_rows = build_first50_coverage_rows(first50_inventory)
    universe_rows = build_universe_rows(universe_symbols, first50_summary, m12_8_manifest)
    deferred_rows = build_deferred_rows(first50_summary, additional_symbols, m12_8_summary)
    safe_candidates = filter_safe_candidates(daily_candidates, first50_summary)
    hit_rows = build_hit_distribution_rows(safe_candidates)
    available = build_available_symbols(first50_summary, additional_symbols)
    summary = build_summary(
        generated_at=generated_at,
        universe=universe,
        first50_summary=first50_summary,
        m12_8_summary=m12_8_summary,
        additional_symbols=additional_symbols,
        safe_candidates=safe_candidates,
        hit_rows=hit_rows,
        m12_25_queue=m12_25_queue,
    )

    write_json(output_dir / "m12_26_cache_scanner_expansion_summary.json", summary)
    write_json(output_dir / "m12_26_first50_data_coverage.json", {"schema_version": "m12.26.first50-coverage.v1", "items": first50_rows})
    write_csv(output_dir / "m12_26_first50_data_coverage.csv", first50_rows)
    write_json(output_dir / "m12_26_universe147_coverage.json", {"schema_version": "m12.26.universe147-coverage.v1", "items": universe_rows})
    write_csv(output_dir / "m12_26_universe147_coverage.csv", universe_rows)
    write_json(output_dir / "m12_26_scanner_available_symbols.json", available)
    write_json(output_dir / "m12_26_deferred_symbols.json", {"schema_version": "m12.26.deferred-symbols.v1", "items": deferred_rows})
    write_csv(output_dir / "m12_26_deferred_symbols.csv", deferred_rows)
    write_csv(output_dir / "m12_26_scanner_candidates.csv", safe_candidates)
    write_csv(output_dir / "m12_26_strategy_hit_distribution.csv", hit_rows)
    (output_dir / "m12_26_scanner_expansion_report.md").write_text(build_report_md(summary), encoding="utf-8")
    (output_dir / "m12_26_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def build_first50_coverage_rows(inventory: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for row in inventory:
        rows.append(
            {
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "coverage_status": row["coverage_status"],
                "ready_for_daily_test": str(bool(row["ready_for_daily_test"])).lower(),
                "lineage": row["lineage"],
                "cache_path": row["cache_path"],
                "cache_start": row["cache_start"],
                "cache_end": row["cache_end"],
                "row_count": str(row["row_count"]),
                "coverage_reason": row["coverage_reason"],
            }
        )
    return rows


def build_universe_rows(
    universe_symbols: list[str],
    first50_summary: dict[str, Any],
    m12_8_manifest: list[dict[str, Any]],
) -> list[dict[str, str]]:
    first50 = set(first50_summary["daily_ready_symbol_list"])
    current5 = set(first50_summary["current_5m_ready_symbol_list"])
    full5 = set(first50_summary["full_5m_target_ready_symbol_list"])
    m12_8_by_symbol = {}
    for row in m12_8_manifest:
        if row["timeframe"] in {"1d", "5m"}:
            m12_8_by_symbol.setdefault(row["symbol"], {})[row["timeframe"]] = row["coverage_status"]
    rows = []
    for symbol in universe_symbols:
        rows.append(
            {
                "symbol": symbol,
                "in_first50": str(symbol in first50).lower(),
                "daily_ready": str(symbol in first50).lower(),
                "current_5m_ready": str(symbol in current5).lower(),
                "long_5m_full_ready": str(symbol in full5).lower(),
                "scanner_ready_scope": "daily_and_current_session" if symbol in first50 and symbol in current5 else "deferred",
                "m12_8_daily_status": m12_8_by_symbol.get(symbol, {}).get("1d", ""),
                "m12_8_5m_status": m12_8_by_symbol.get(symbol, {}).get("5m", ""),
            }
        )
    return rows


def build_deferred_rows(
    first50_summary: dict[str, Any],
    additional_symbols: list[str],
    m12_8_summary: dict[str, Any],
) -> list[dict[str, str]]:
    rows = []
    for symbol in first50_summary["daily_ready_symbol_list"]:
        if symbol not in set(first50_summary["full_5m_target_ready_symbol_list"]):
            rows.append(
                {
                    "symbol": symbol,
                    "scope": "first50_long_history_5m",
                    "reason": "长历史5分钟窗口未完整覆盖；可做当日只读观察，但不能宣称两年日内历史完整。",
                    "next_action": "补齐 2024-04-01 到最新已完成 regular session 的 5m cache。",
                }
            )
    for symbol in additional_symbols:
        rows.append(
            {
                "symbol": symbol,
                "scope": "universe147_expansion",
                "reason": "不在第一批50只可用缓存内；不能放入 scanner 可用候选。",
                "next_action": "按 M12.8 fetch plan 分批补 1d 与 5m cache。",
            }
        )
    rows.append(
        {
            "symbol": "ALL",
            "scope": "m12_8_fetch_plan",
            "reason": f"M12.8 fetch plan 仍有 {m12_8_summary['fetch_plan_request_count']} 个只读缓存请求和约 {m12_8_summary['fetch_plan_estimated_chunk_count']} 个分片。",
            "next_action": "分批执行只读 K 线补齐，不把缺失标的伪装为可用。",
        }
    )
    return rows


def filter_safe_candidates(candidates: list[dict[str, str]], first50_summary: dict[str, Any]) -> list[dict[str, str]]:
    ready_symbols = set(first50_summary["daily_ready_symbol_list"]) | set(first50_summary["current_5m_ready_symbol_list"])
    rows = []
    for row in candidates:
        if row["symbol"] not in ready_symbols:
            continue
        if row["strategy_id"] not in set(AUTO_SCANNER_STRATEGIES):
            continue
        safe = dict(row)
        safe["m12_26_queue"] = "scanner_candidate_from_available_cache"
        safe["paper_trial_candidate_now"] = "false"
        rows.append(safe)
    return rows


def build_hit_distribution_rows(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    counts = Counter((row["strategy_id"], row["strategy_title"], row["timeframe"]) for row in candidates)
    return [
        {
            "strategy_id": strategy_id,
            "strategy_title": title,
            "timeframe": timeframe,
            "candidate_count": str(count),
        }
        for (strategy_id, title, timeframe), count in sorted(counts.items())
    ]


def build_available_symbols(first50_summary: dict[str, Any], additional_symbols: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "m12.26.scanner-available-symbols.v1",
        "scanner_scope_note": "第一批50只可用于日线和当日5m只读观察；长历史5m和147扩展仍按缺口处理。",
        "daily_and_current_session_ready_count": len(first50_summary["daily_ready_symbol_list"]),
        "daily_and_current_session_ready_symbols": first50_summary["daily_ready_symbol_list"],
        "full_intraday_history_ready_count": len(first50_summary["full_5m_target_ready_symbol_list"]),
        "full_intraday_history_ready_symbols": first50_summary["full_5m_target_ready_symbol_list"],
        "deferred_expansion_symbol_count": len(additional_symbols),
        "deferred_expansion_symbols": additional_symbols,
    }


def build_summary(
    *,
    generated_at: str,
    universe: dict[str, Any],
    first50_summary: dict[str, Any],
    m12_8_summary: dict[str, Any],
    additional_symbols: list[str],
    safe_candidates: list[dict[str, str]],
    hit_rows: list[dict[str, str]],
    m12_25_queue: list[dict[str, str]],
) -> dict[str, Any]:
    candidate_counts = Counter(row["strategy_id"] for row in safe_candidates)
    candidate_symbol_count = len({row["symbol"] for row in safe_candidates})
    observation_only = [row for row in m12_25_queue if row["strategy_id"] in set(OBSERVATION_ONLY_STRATEGIES)]
    return {
        "schema_version": "m12.26.cache-scanner-expansion-summary.v1",
        "stage": "M12.26.cache_scanner_expansion",
        "generated_at": generated_at,
        "plain_language_result": (
            "第一批50只现在可做日线和当日5分钟只读扫描；147只扩展还没全量可用。"
            "本阶段没有把缺数据股票放进候选。"
        ),
        "universe_symbol_count": universe["symbol_count"],
        "first50_daily_ready_symbols": first50_summary["daily_ready_symbols"],
        "first50_current_5m_ready_symbols": first50_summary["current_5m_ready_symbols"],
        "first50_long_history_5m_ready_symbols": first50_summary["full_5m_target_ready_symbols"],
        "additional_deferred_symbol_count": len(additional_symbols),
        "m12_8_target_complete_symbol_count": m12_8_summary["target_complete_symbol_count"],
        "scanner_candidate_count": len(safe_candidates),
        "scanner_candidate_symbol_count": candidate_symbol_count,
        "strategy_candidate_counts": dict(sorted(candidate_counts.items())),
        "strategy_hit_distribution_ref": project_path(OUTPUT_DIR / "m12_26_strategy_hit_distribution.csv"),
        "auto_scanner_strategy_ids": list(AUTO_SCANNER_STRATEGIES),
        "observation_only_strategy_ids": list(OBSERVATION_ONLY_STRATEGIES),
        "observation_only_rows": observation_only,
        "excluded_auto_scanner_strategy_ids": list(EXCLUDED_AUTO_SCANNER_STRATEGIES),
        "scanner_expansion_allowed_now": True,
        "full_147_universe_available_now": False,
        "full_intraday_history_available_now": False,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "artifacts": {
            "first50_data_coverage": project_path(OUTPUT_DIR / "m12_26_first50_data_coverage.csv"),
            "universe147_coverage": project_path(OUTPUT_DIR / "m12_26_universe147_coverage.csv"),
            "scanner_available_symbols": project_path(OUTPUT_DIR / "m12_26_scanner_available_symbols.json"),
            "deferred_symbols": project_path(OUTPUT_DIR / "m12_26_deferred_symbols.csv"),
            "scanner_candidates": project_path(OUTPUT_DIR / "m12_26_scanner_candidates.csv"),
            "report": project_path(OUTPUT_DIR / "m12_26_scanner_expansion_report.md"),
        },
        "hit_rows": hit_rows,
    }


def build_report_md(summary: dict[str, Any]) -> str:
    lines = [
        "# M12.26 数据缓存与选股扩展报告",
        "",
        "## 用人话结论",
        "",
        f"- 第一批 `50` 只股票/ETF：日线可用 `{summary['first50_daily_ready_symbols']}` 只，当日 5 分钟可用 `{summary['first50_current_5m_ready_symbols']}` 只。",
        f"- 长历史 5 分钟完整覆盖仍是 `{summary['first50_long_history_5m_ready_symbols']}/50`，所以不能把日内历史结果说成两年完整回测。",
        f"- 147 只扩展还差 `{summary['additional_deferred_symbol_count']}` 只未进入可扫描缓存；本阶段没有把这些缺数据标的放进候选。",
        f"- 今日 scanner 可交付候选 `{summary['scanner_candidate_count']}` 条，覆盖 `{summary['scanner_candidate_symbol_count']}` 只股票。",
        "- `M10-PA-007` 只进入观察队列，暂不进入自动 scanner；`M10-PA-004` 继续保留图形研究。",
        "- 当前仍然没有真实账户、真实下单或模拟买卖试运行批准。",
        "",
        "## 策略命中分布",
        "",
        "| 策略 | 周期 | 候选数 |",
        "|---|---:|---:|",
    ]
    for row in summary["hit_rows"]:
        lines.append(f"| `{row['strategy_id']}` {row['strategy_title']} | `{row['timeframe']}` | {row['candidate_count']} |")
    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "- 分批补第一批 50 只的长历史 5 分钟窗口。",
            "- 再按 M12.8 fetch plan 扩到 147 只，缺数据继续写入缺口表。",
            "- 满 10 个交易日稳定看板记录后，再进入 M11.6 模拟买卖试运行准入复查。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "# M12.26 Handoff\n\n"
        "## 用人话结论\n\n"
        f"第一批50只可继续用于日线和当日5分钟只读 scanner；当前候选 `{summary['scanner_candidate_count']}` 条。"
        f"147只扩展还有 `{summary['additional_deferred_symbol_count']}` 只未补齐，不得宣称全量可用。\n\n"
        "## 下一步\n\n"
        "- 继续补长历史5分钟数据。\n"
        "- 每日看板继续累计到10个交易日。\n"
        "- M11.6 仍要等数据稳定、记录天数和用户审批。\n"
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def project_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")
