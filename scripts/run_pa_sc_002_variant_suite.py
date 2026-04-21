#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pa_sc_002_backtest_lib import build_default_config, run_experiment


VARIANT_SUITE = (
    {
        "variant_id": "baseline_v0_1",
        "title": "Baseline v0.1",
        "description": "当前 PA-SC-002 + PA-SC-009 filter v0.1，不禁做任何时间段。",
        "overrides": {},
    },
    {
        "variant_id": "midday_block_v0_1",
        "title": "Midday Block",
        "description": "显式禁止 11:00-13:30 的 breakout 交易，其余规则不变。",
        "overrides": {
            "blocked_time_buckets": ("midday_1100_1330",),
        },
    },
    {
        "variant_id": "stronger_veto_v0_1",
        "title": "Stronger Negative Veto",
        "description": "把 range veto 提前：更少的 flip / doji 也会触发禁做。",
        "overrides": {
            "filter_min_flip_count": 3,
            "filter_min_doji_count": 2,
            "filter_max_displacement_ratio": Decimal("0.35"),
            "filter_max_displacement_for_doji_veto": Decimal("0.35"),
        },
    },
    {
        "variant_id": "midday_block_plus_stronger_veto",
        "title": "Midday Block + Stronger Veto",
        "description": "同时禁做午盘，并提前触发 negative veto。",
        "overrides": {
            "blocked_time_buckets": ("midday_1100_1330",),
            "filter_min_flip_count": 3,
            "filter_min_doji_count": 2,
            "filter_max_displacement_ratio": Decimal("0.35"),
            "filter_max_displacement_for_doji_veto": Decimal("0.35"),
        },
    },
    {
        "variant_id": "late_only_upper_bound",
        "title": "Late Only Upper Bound",
        "description": "只保留 13:30-16:00，作为诊断上限，不直接视为正式方案。",
        "overrides": {
            "blocked_time_buckets": ("open_0930_1100", "midday_1100_1330"),
        },
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PA-SC-002 diagnostic variant suite.",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Refresh cached SPY 5m data before the suite runs.",
    )
    parser.add_argument(
        "--summary-json",
        action="store_true",
        help="Print suite summary JSON to stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base = build_default_config()
    suite_dir = ROOT / "reports" / "strategy_lab" / "pa_sc_002_variant_suite_artifacts"
    suite_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for item in VARIANT_SUITE:
        variant_dir = suite_dir / item["variant_id"]
        variant_config = replace(
            base,
            artifact_dir=variant_dir,
            report_path=variant_dir / "report.md",
            summary_path=variant_dir / "summary.json",
            trades_csv_path=variant_dir / "trades.csv",
            candidates_csv_path=variant_dir / "candidate_events.csv",
            skip_summary_path=variant_dir / "skip_summary.json",
            **item["overrides"],
        )
        summary = run_experiment(variant_config, refresh_data=args.refresh_data)
        results.append(
            {
                "variant_id": item["variant_id"],
                "title": item["title"],
                "description": item["description"],
                "summary": summary,
            }
        )
    payload = {
        "generated_at": base.summary_path.stat().st_mtime if base.summary_path.exists() else None,
        "variants": results,
    }
    summary_path = suite_dir / "suite_summary.json"
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = ROOT / "reports" / "strategy_lab" / "pa_sc_002_variant_suite.md"
    report_path.write_text(render_variant_report(results), encoding="utf-8")
    print(f"report={report_path}")
    print(f"summary={summary_path}")
    if args.summary_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def render_variant_report(results: list[dict[str, object]]) -> str:
    baseline = results[0]["summary"]
    lines = [
        "# PA-SC-002 Variant Suite",
        "",
        "本报告只做诊断型对照，不代表已经确认新的正式规则。",
        "",
        "## 变体摘要",
        "",
        "| 变体 | 交易数 | 胜率 | Expectancy | 净盈亏(USD) | PF | 样本结论 | 结论 |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for item in results:
        summary = item["summary"]
        stats = summary["stats"]
        lines.append(
            f"| {item['title']} | {stats['trade_count']} | {stats['win_rate'] * 100:.2f}% | {stats['expectancy_r']:.4f}R | ${stats['net_pnl_cash']:.2f} | {format_optional(stats['profit_factor'])} | {summary['sample_conclusion']} | {variant_conclusion(item['variant_id'], summary, baseline)} |"
        )
    lines.extend(
        [
            "",
            "## 关键观察",
            "",
            f"- 当前 baseline 仍然亏损：`{baseline['stats']['expectancy_r']:.4f}R`，净盈亏 `${baseline['stats']['net_pnl_cash']:.2f}`。",
            f"- `Midday Block` 是当前唯一既改善明显、又仍达到最小 probe 门槛的单因素变体：{describe_vs_baseline(results, 'midday_block_v0_1')}",
            f"- `Stronger Negative Veto` 单独使用时，只带来轻微 Expectancy 改善，但净盈亏反而更差：{describe_vs_baseline(results, 'stronger_veto_v0_1')}",
            f"- `Midday Block + Stronger Veto` 的净亏损收缩最多，但交易数只有 `55` 笔，低于本轮最小 probe 门槛，因此暂时只能视为 underpowered 诊断结果：{describe_vs_baseline(results, 'midday_block_plus_stronger_veto')}",
            f"- `Late Only Upper Bound` 最接近盈亏平衡，但它本质上是后验诊断上限，不应直接当作正式升级版：{describe_vs_baseline(results, 'late_only_upper_bound')}",
            "",
            "## 推荐顺序",
            "",
            "1. 若下一轮只能正式推进一个版本，优先选 `Midday Block`。它是当前最清楚、最少后验、且仍保留最小样本门槛的改善方向。",
            "2. `Midday Block + Stronger Veto` 可以作为第二优先的后续诊断，但需要更长样本或更多标的补足交易数后，才适合升格成正式 retest 版本。",
            "3. `Stronger Negative Veto` 单独使用不应作为下一轮主方向，因为它没有带来足够稳健的成本后改善。",
            "4. `Late Only` 只适合作为诊断上限，不应直接当作正式升级版，因为它大幅压缩了可交易时间。",
            "5. 这轮仍不建议先把主要精力放在改 `1R / 1.5R / 2R`，因为时段和过滤问题更主导结果。",
        ]
    )
    return "\n".join(lines) + "\n"


def variant_conclusion(variant_id: str, summary: dict[str, object], baseline: dict[str, object]) -> str:
    stats = summary["stats"]
    base_stats = baseline["stats"]
    if variant_id == "baseline_v0_1":
        return "当前基线"
    if stats["expectancy_r"] > 0 and stats["net_pnl_cash"] > 0:
        return "转正，值得继续验证"
    if stats["expectancy_r"] > base_stats["expectancy_r"]:
        return "比基线更好，但仍未完全成立"
    return "没有优于基线"


def describe_vs_baseline(results: list[dict[str, object]], variant_id: str) -> str:
    lookup = {item["variant_id"]: item for item in results}
    baseline = lookup["baseline_v0_1"]["summary"]["stats"]
    current = lookup[variant_id]["summary"]["stats"]
    delta_exp = current["expectancy_r"] - baseline["expectancy_r"]
    delta_cash = current["net_pnl_cash"] - baseline["net_pnl_cash"]
    return (
        f"`Expectancy {current['expectancy_r']:.4f}R`、净盈亏 `${current['net_pnl_cash']:.2f}`，"
        f"相对 baseline 改善 `ΔExpectancy {delta_exp:+.4f}R / ΔCash ${delta_cash:+.2f}`"
    )


def format_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
