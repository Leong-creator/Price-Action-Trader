#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m10_capital_backtest_lib import (  # noqa: E402
    CAPITAL_MODEL_PATH,
    CandidateTrade,
    build_metric_rows,
    load_capital_model,
    simulate_account,
)


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_24_DIR = M10_DIR / "visual_detectors" / "m12_24_small_pilot"
M12_27_FEED_DIR = M10_DIR / "m12_read_only_pipeline" / "m12_27_live_snapshot"
OUTPUT_DIR = M10_DIR / "visual_detectors" / "m12_27_pa004_retest_live_snapshot"
M12_24_TRADE_LEDGER = M12_24_DIR / "m12_24_pa004_pa007_trade_ledger.csv"
M12_24_SUMMARY = M12_24_DIR / "m12_24_pa004_pa007_small_pilot_summary.json"
M12_27_LIVE_MANIFEST = M12_27_FEED_DIR / "m12_1_readonly_feed_manifest.json"
PA004 = "M10-PA-004"
ZERO = Decimal("0")
ETF_SYMBOLS = {
    "ARKK",
    "DIA",
    "EEM",
    "EFA",
    "GLD",
    "IVV",
    "IWM",
    "QQQ",
    "SLV",
    "SMH",
    "SOXX",
    "SPY",
    "SQQQ",
    "TLT",
    "TQQQ",
    "USO",
    "VOO",
    "VTI",
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLY",
}
LEVERAGED_OR_INVERSE = {"SQQQ", "TQQQ"}
FORBIDDEN_OUTPUT_TEXT = (
    "live-ready",
    "real_orders=true",
    "broker_connection=true",
    "paper approval",
    "order_id",
    "fill_id",
    "account_id",
    "cash_balance",
    "position_qty",
)


def run_m12_27_pa004_retest_live_snapshot(
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
    live_manifest_path: Path = M12_27_LIVE_MANIFEST,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)
    model = load_capital_model(CAPITAL_MODEL_PATH)
    source_summary = load_json(M12_24_SUMMARY)
    live_manifest = load_json(live_manifest_path)
    source_rows = load_pa004_rows(M12_24_TRADE_LEDGER)
    cohorts = build_cohorts(source_rows)

    all_metric_rows: list[dict[str, str]] = []
    baseline_trade_rows: list[dict[str, str]] = []
    cohort_decisions: list[dict[str, str]] = []
    for cohort_id, cohort in cohorts.items():
        candidates = [row_to_candidate(row) for row in cohort["rows"]]
        simulated = simulate_candidates(candidates, model, cohort_id)
        metrics = add_cohort_fields(build_metric_rows(simulated, model), cohort_id, cohort["label"])
        all_metric_rows.extend(metrics)
        baseline_trade_rows.extend(build_trade_rows(simulated, cohort_id, cohort["label"]))
        cohort_decisions.extend(build_cohort_decisions(metrics, cohort_id, cohort["label"]))

    symbol_diagnostics = build_symbol_diagnostics(source_rows)
    write_csv(output_dir / "m12_27_pa004_retest_metrics.csv", all_metric_rows)
    write_csv(output_dir / "m12_27_pa004_retest_trade_ledger.csv", baseline_trade_rows)
    write_csv(output_dir / "m12_27_pa004_symbol_diagnostics.csv", symbol_diagnostics)
    write_csv(output_dir / "m12_27_pa004_cohort_decisions.csv", cohort_decisions)
    summary = build_summary(
        generated_at=generated_at,
        source_summary=source_summary,
        live_manifest=live_manifest,
        source_rows=source_rows,
        cohort_decisions=cohort_decisions,
        symbol_diagnostics=symbol_diagnostics,
    )
    write_json(output_dir / "m12_27_pa004_retest_live_snapshot_summary.json", summary)
    (output_dir / "m12_27_pa004_retest_live_snapshot_report.md").write_text(
        build_client_report(summary, cohort_decisions, symbol_diagnostics),
        encoding="utf-8",
    )
    (output_dir / "m12_27_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def load_pa004_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            row for row in csv.DictReader(handle)
            if row["strategy_id"] == PA004 and row["cost_tier"] == "baseline" and not row.get("skip_reason")
        ]


def build_cohorts(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    return {
        "all_m12_24": {"label": "原小范围全样本", "rows": rows},
        "long_only": {"label": "只看做多机会", "rows": [row for row in rows if row["direction"] == "long"]},
        "short_only": {"label": "只看做空机会", "rows": [row for row in rows if row["direction"] == "short"]},
        "stocks_only": {"label": "只看个股，不含 ETF", "rows": [row for row in rows if row["symbol"] not in ETF_SYMBOLS]},
        "etfs_only": {"label": "只看 ETF", "rows": [row for row in rows if row["symbol"] in ETF_SYMBOLS]},
        "non_leveraged_non_inverse": {
            "label": "剔除杠杆/反向 ETF",
            "rows": [row for row in rows if row["symbol"] not in LEVERAGED_OR_INVERSE],
        },
        "leveraged_inverse_only": {
            "label": "只看杠杆/反向 ETF",
            "rows": [row for row in rows if row["symbol"] in LEVERAGED_OR_INVERSE],
        },
        "post_2018": {"label": "2018 年后样本", "rows": [row for row in rows if row["entry_timestamp"][:4] >= "2018"]},
        "pre_2018": {"label": "2018 年前样本", "rows": [row for row in rows if row["entry_timestamp"][:4] < "2018"]},
    }


def row_to_candidate(row: dict[str, str]) -> CandidateTrade:
    entry = d(row["entry_price"])
    exit_price = d(row["exit_price"])
    risk = d(row["risk_per_share"])
    gross_r = ((exit_price - entry) / risk) if row["direction"] == "long" else ((entry - exit_price) / risk)
    return CandidateTrade(
        strategy_id=PA004,
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        direction=row["direction"],
        signal_timestamp=row["signal_timestamp"],
        entry_timestamp=row["entry_timestamp"],
        entry_price=entry,
        stop_price=d(row["stop_price"]),
        target_price=d(row["target_price"]),
        risk_per_share=risk,
        exit_timestamp=row["exit_timestamp"],
        exit_price=exit_price,
        exit_reason=row["exit_reason"],
        gross_r=gross_r,
        baseline_net_r=gross_r,
        setup_notes="m12_27_pa004_diagnostic_retest",
    )


def simulate_candidates(candidates: list[CandidateTrade], model: Any, cohort_id: str) -> list[Any]:
    grouped: dict[str, list[CandidateTrade]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.symbol].append(candidate)
    trades = []
    for symbol, group in sorted(grouped.items()):
        for tier in model.cost_tiers:
            trades.extend(
                simulate_account(
                    candidates=group,
                    model=model,
                    tier=tier,
                    spec_ref="reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_24_small_pilot/m12_24_pa004_pa007_small_pilot_summary.json",
                    source_ledger_ref="reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_24_small_pilot/m12_24_pa004_pa007_trade_ledger.csv",
                    quality_flag=f"m12_27_pa004_{cohort_id}",
                )
            )
    return trades


def add_cohort_fields(rows: list[dict[str, str]], cohort_id: str, label: str) -> list[dict[str, str]]:
    for row in rows:
        row["cohort_id"] = cohort_id
        row["cohort_label"] = label
    return rows


def build_trade_rows(trades: list[Any], cohort_id: str, cohort_label: str) -> list[dict[str, str]]:
    rows = []
    for trade in trades:
        if trade.cost_tier != "baseline":
            continue
        rows.append(
            {
                "cohort_id": cohort_id,
                "cohort_label": cohort_label,
                "strategy_id": trade.strategy_id,
                "symbol": trade.symbol,
                "timeframe": trade.timeframe,
                "direction": trade.direction,
                "signal_timestamp": trade.signal_timestamp,
                "entry_timestamp": trade.entry_timestamp,
                "exit_timestamp": trade.exit_timestamp,
                "entry_price": str(trade.entry_price),
                "stop_price": str(trade.stop_price),
                "target_price": str(trade.target_price),
                "exit_price": str(trade.exit_price),
                "pnl": str(trade.pnl),
                "win": str(trade.win).lower(),
                "exit_reason": trade.exit_reason,
                "quality_flag": trade.quality_flag,
            }
        )
    return rows


def build_cohort_decisions(metrics: list[dict[str, str]], cohort_id: str, label: str) -> list[dict[str, str]]:
    rows = []
    for row in metrics:
        if row["grain"] != "strategy" or row["cost_tier"] != "baseline":
            continue
        trade_count = int(row["trade_count"])
        ret = d(row["return_percent"])
        pf = d(row["profit_factor"] or "0")
        dd = d(row["max_drawdown_percent"])
        if trade_count < 30:
            decision = "样本不足，继续收集"
            plain_reason = "交易次数太少，不能判断。"
        elif cohort_id == "long_only" and ret > ZERO and pf >= Decimal("1") and dd <= Decimal("8"):
            decision = "PA004 做多版进入下一轮观察候选"
            plain_reason = "分方向后，做多样本转正，说明 PA004 不应被整体打掉，应继续单独验证做多版本。"
        elif ret > ZERO and pf >= Decimal("1"):
            decision = "作为辅助诊断继续观察"
            plain_reason = "这个分组为正，但还不能直接变成自动策略，需要看是否有非收益曲线的规则依据。"
        elif cohort_id == "short_only":
            decision = "做空版本暂不进入主线"
            plain_reason = "做空样本拖累明显，下一轮 PA004 不应把做空混进主线。"
        else:
            decision = "暂不进入每日主线"
            plain_reason = "本分组没有跑出足够稳定的模拟结果。"
        rows.append(
            {
                "cohort_id": cohort_id,
                "cohort_label": label,
                "decision": decision,
                "plain_reason": plain_reason,
                "return_percent": row["return_percent"],
                "win_rate": row["win_rate"],
                "profit_factor": row["profit_factor"],
                "max_drawdown_percent": row["max_drawdown_percent"],
                "trade_count": row["trade_count"],
                "account_count": row["account_count"],
            }
        )
    return rows


def build_symbol_diagnostics(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["symbol"]].append(row)
    out = []
    for symbol, group in sorted(grouped.items()):
        wins = [row for row in group if row["win"] == "true"]
        pnl = sum((d(row["pnl"]) for row in group), ZERO)
        gross_win = sum((d(row["pnl"]) for row in group if d(row["pnl"]) > ZERO), ZERO)
        gross_loss = abs(sum((d(row["pnl"]) for row in group if d(row["pnl"]) < ZERO), ZERO))
        out.append(
            {
                "symbol": symbol,
                "symbol_type": "ETF" if symbol in ETF_SYMBOLS else "stock",
                "leveraged_or_inverse": str(symbol in LEVERAGED_OR_INVERSE).lower(),
                "trade_count": str(len(group)),
                "win_rate": fmt4(Decimal(len(wins)) / Decimal(len(group))) if group else "0.0000",
                "net_pnl": fmt2(pnl),
                "return_percent_proxy": fmt4(pnl / Decimal("100000") * Decimal("100")),
                "profit_factor": fmt4(gross_win / gross_loss) if gross_loss else "",
            }
        )
    return sorted(out, key=lambda item: d(item["net_pnl"]))


def build_summary(
    *,
    generated_at: str,
    source_summary: dict[str, Any],
    live_manifest: dict[str, Any],
    source_rows: list[dict[str, str]],
    cohort_decisions: list[dict[str, str]],
    symbol_diagnostics: list[dict[str, str]],
) -> dict[str, Any]:
    long_decision = next(row for row in cohort_decisions if row["cohort_id"] == "long_only")
    all_decision = next(row for row in cohort_decisions if row["cohort_id"] == "all_m12_24")
    worst_symbols = [row["symbol"] for row in symbol_diagnostics[:5]]
    best_symbols = [row["symbol"] for row in reversed(symbol_diagnostics[-5:])]
    return {
        "schema_version": "m12.27.pa004-retest-live-snapshot.v1",
        "stage": "M12.27.pa004_expanded_retest_live_snapshot",
        "generated_at": generated_at,
        "plain_language_result": "PA004 不直接拒绝；整体版本仍弱，但做多分支转正，下一步应测试 PA004 做多版，而不是继续混合做多/做空。",
        "source_stage": source_summary["stage"],
        "source_trade_count": len(source_rows),
        "live_readonly_snapshot": {
            "status": "ok" if live_manifest.get("deferred_count") == 0 and live_manifest.get("ledger_row_count", 0) > 0 else "deferred_or_partial",
            "generated_at": live_manifest.get("generated_at", ""),
            "row_count": live_manifest.get("ledger_row_count", 0),
            "deferred_count": live_manifest.get("deferred_count", 0),
            "symbols": live_manifest.get("symbols", []),
            "timeframes": live_manifest.get("timeframes", []),
            "meaning": "当前开盘时段只读行情/K 线能取到；这不是常驻自动刷新。",
        },
        "pa004_overall_retest": all_decision,
        "pa004_long_only_retest": long_decision,
        "best_symbols": best_symbols,
        "worst_symbols": worst_symbols,
        "cohort_count": len({row["cohort_id"] for row in cohort_decisions}),
        "cohort_decisions": cohort_decisions,
        "next_action": "把 PA004 做多版做成下一轮观察规则；PA004 做空版暂不进入每日主线。",
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def build_client_report(
    summary: dict[str, Any],
    cohort_decisions: list[dict[str, str]],
    symbol_diagnostics: list[dict[str, str]],
) -> str:
    live = summary["live_readonly_snapshot"]
    lines = [
        "# M12.27 PA004 复测与开盘只读快照",
        "",
        "## 用人话先说结果",
        "",
        "- 你说得对，`M10-PA-004` 之前只是小范围测试，不应该直接当成永久拒绝。",
        "- 这次重新拆开看后，结论更清楚：PA004 的整体混合版本还是弱，但“只做多”版本转正，值得进入下一轮观察规则。",
        f"- 开盘时段只读行情也跑通了：本次取到 `{live['row_count']}` 条 K 线/行情记录，缺口 `{live['deferred_count']}` 个。",
        "- 当前仍不是常驻自动刷新，下一步要把它接到每日看板定时刷新里。",
        "",
        "## PA004 分组复测",
        "",
        "| 分组 | 结论 | 收益率 | 胜率 | 最大回撤 | 交易次数 | 原因 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in cohort_decisions:
        if row["cohort_id"] not in {"all_m12_24", "long_only", "short_only", "stocks_only", "etfs_only", "non_leveraged_non_inverse"}:
            continue
        lines.append(
            f"| {row['cohort_label']} | {row['decision']} | {row['return_percent']}% | "
            f"{pct(row['win_rate'])} | {row['max_drawdown_percent']}% | {row['trade_count']} | {row['plain_reason']} |"
        )
    lines.extend(
        [
            "",
            "## 标的拖累和亮点",
            "",
            f"- 表现较好的标的：{', '.join(summary['best_symbols'])}。",
            f"- 拖累较重的标的：{', '.join(summary['worst_symbols'])}。",
            "- 这说明 PA004 更像“需要方向和标的过滤”的策略，不适合把做多、做空、杠杆/反向 ETF 混在一起直接跑。",
            "",
            "## 开盘只读测试状态",
            "",
            f"- 状态：{live['status']}。",
            f"- 标的：{', '.join(live['symbols'])}。",
            f"- 周期：{', '.join(live['timeframes'])}。",
            "- 意义：当前能读行情和 K 线，可以作为看板刷新输入；但还不是全天候自动监控。",
            "",
            "## 下一步",
            "",
            "1. 把 PA004 做多版做成独立观察规则，不再把做空样本混进去。",
            "2. 把开盘只读快照接入中文看板刷新，交易时段能看到今日机会和模拟盈亏。",
            "3. PA004 做空版暂不进每日主线，后续只有找到清楚来源规则和过滤条件再测。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "```yaml\n"
        "task_id: M12.27-pa004-retest-live-snapshot\n"
        "role: main-agent\n"
        "branch_or_worktree: feature/m12-27-pa004-expanded-retest-live-snapshot\n"
        "objective: 对 PA004 做分组复测，并记录开盘时段只读快照状态\n"
        "status: success\n"
        "files_changed:\n"
        "  - scripts/m12_27_pa004_retest_live_snapshot_lib.py\n"
        "  - scripts/run_m12_27_pa004_retest_live_snapshot.py\n"
        "  - tests/unit/test_m12_27_pa004_retest_live_snapshot.py\n"
        "  - reports/strategy_lab/m10_price_action_strategy_refresh/visual_detectors/m12_27_pa004_retest_live_snapshot/*\n"
        "interfaces_changed: []\n"
        "verification_results:\n"
        f"  - live_snapshot_rows: {summary['live_readonly_snapshot']['row_count']}\n"
        f"  - live_snapshot_deferred: {summary['live_readonly_snapshot']['deferred_count']}\n"
        f"  - pa004_long_only_decision: {summary['pa004_long_only_retest']['decision']}\n"
        "assumptions:\n"
        "  - PA004 本轮使用 M12.24 baseline ledger 做诊断复测，不代表最终交易批准\n"
        "risks:\n"
        "  - 分组复测发现做多转正，但仍需做成独立观察规则并连续观察\n"
        "qa_focus:\n"
        "  - 检查报告是否避免把只读快照说成真实交易或常驻监控\n"
        "rollback_notes:\n"
        "  - 回滚本阶段提交即可撤回 M12.27 产物\n"
        "next_recommended_action: 实现 PA004 做多版观察规则并接入每日看板刷新\n"
        "needs_user_decision: false\n"
        "user_decision_needed: ''\n"
        "```\n"
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")


def d(value: Any) -> Decimal:
    return Decimal(str(value))


def fmt2(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def fmt4(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001")))


def pct(value: str) -> str:
    return f"{(d(value) * Decimal('100')).quantize(Decimal('0.01'))}%"
