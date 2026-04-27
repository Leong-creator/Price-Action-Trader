#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_definition_fix_and_retest.json"
OUTPUT_DIR = M10_DIR / "definition_fix" / "m12_4_definition_fix_and_retest"
TARGET_IDS = ("M10-PA-005", "M10-PA-004", "M10-PA-007")
PA005_ID = "M10-PA-005"
VISUAL_DEFINITION_IDS = ("M10-PA-004", "M10-PA-007")
STRATEGY_TITLES = {
    "M10-PA-005": "Trading Range Failed Breakout Reversal",
    "M10-PA-004": "Broad Channel Boundary Reversal",
    "M10-PA-007": "Second-Leg Trap Reversal",
}
FORBIDDEN_TEXT = (
    "PA-SC-",
    "SF-",
    "promote",
    "live-ready",
    "broker_connection=true",
    "real_orders=true",
    "live_execution=true",
    "uses_profit_curve_tuning,true",
)


@dataclass(frozen=True, slots=True)
class DefinitionFixConfig:
    title: str
    run_id: str
    m10_9_before_after_metrics_path: Path
    m10_9_summary_path: Path
    m10_10_visual_gate_summary_path: Path
    m12_3_visual_precheck_index_path: Path
    output_dir: Path
    paper_simulated_only: bool
    paper_trading_approval: bool
    broker_connection: bool
    real_orders: bool
    live_execution: bool


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def load_definition_fix_config(path: str | Path = DEFAULT_CONFIG_PATH) -> DefinitionFixConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    return DefinitionFixConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_4_definition_fix_and_retest"),
        m10_9_before_after_metrics_path=resolve_repo_path(payload["m10_9_before_after_metrics_path"]),
        m10_9_summary_path=resolve_repo_path(payload["m10_9_summary_path"]),
        m10_10_visual_gate_summary_path=resolve_repo_path(payload["m10_10_visual_gate_summary_path"]),
        m12_3_visual_precheck_index_path=resolve_repo_path(payload["m12_3_visual_precheck_index_path"]),
        output_dir=resolve_repo_path(payload["output_dir"]),
        paper_simulated_only=bool(payload.get("paper_simulated_only", True)),
        paper_trading_approval=bool(payload.get("paper_trading_approval", False)),
        broker_connection=bool(payload.get("broker_connection", False)),
        real_orders=bool(payload.get("real_orders", False)),
        live_execution=bool(payload.get("live_execution", False)),
    )


def run_m12_definition_fix_and_retest(
    config: DefinitionFixConfig,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    validate_config_boundaries(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    pa005_metrics = load_csv(config.m10_9_before_after_metrics_path)
    m10_9_summary = load_json(config.m10_9_summary_path)
    visual_gate_summary = load_json(config.m10_10_visual_gate_summary_path)
    visual_precheck = load_json(config.m12_3_visual_precheck_index_path)

    metrics_rows = build_metric_rows(config, pa005_metrics, visual_gate_summary, visual_precheck)
    summary = build_summary(config, generated_at, metrics_rows, m10_9_summary, visual_precheck)

    write_metrics(config.output_dir / "m12_4_before_after_metrics.csv", metrics_rows)
    write_json(config.output_dir / "m12_4_definition_fix_summary.json", summary)
    (config.output_dir / "m12_4_definition_fix_report.md").write_text(build_report(summary, metrics_rows), encoding="utf-8")
    (config.output_dir / "m12_4_retest_client_summary.md").write_text(
        build_client_summary(summary, metrics_rows),
        encoding="utf-8",
    )
    assert_no_forbidden_output(config.output_dir)
    return summary


def validate_config_boundaries(config: DefinitionFixConfig) -> None:
    if not config.paper_simulated_only:
        raise ValueError("M12.4 requires paper_simulated_only=true")
    if config.paper_trading_approval or config.broker_connection or config.real_orders or config.live_execution:
        raise ValueError("M12.4 keeps paper trading, broker, orders, and live execution disabled")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle)]


def build_metric_rows(
    config: DefinitionFixConfig,
    pa005_metrics: list[dict[str, str]],
    visual_gate_summary: dict[str, Any],
    visual_precheck: dict[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for source_row in pa005_metrics:
        rows.append(pa005_metric_row(config, source_row))

    gate_by_id = {row["strategy_id"]: row for row in visual_gate_summary["review_rows"]}
    precheck_by_id = {row["strategy_id"]: row for row in visual_precheck["strategy_rows"]}
    case_counts = {
        strategy_id: sum(1 for row in visual_precheck["case_rows"] if row["strategy_id"] == strategy_id)
        for strategy_id in VISUAL_DEFINITION_IDS
    }
    for strategy_id in VISUAL_DEFINITION_IDS:
        rows.append(visual_definition_row(config, strategy_id, gate_by_id[strategy_id], precheck_by_id[strategy_id], case_counts[strategy_id]))
    validate_metric_rows(rows)
    return rows


def pa005_metric_row(config: DefinitionFixConfig, row: dict[str, str]) -> dict[str, str]:
    return {
        "strategy_id": row["strategy_id"],
        "title": STRATEGY_TITLES[row["strategy_id"]],
        "work_type": "structural_retest_reused_from_m10_9",
        "timeframe": row["timeframe"],
        "cost_tier": row["cost_tier"],
        "before_trade_count": row["before_trade_count"],
        "after_trade_count": row["after_trade_count"],
        "removed_count": row["removed_count"],
        "removed_percent": row["removed_percent"],
        "before_net_profit": row["before_net_profit"],
        "after_net_profit": row["after_net_profit"],
        "delta_net_profit": row["delta_net_profit"],
        "before_return_percent": row["before_return_percent"],
        "after_return_percent": row["after_return_percent"],
        "before_win_rate": row["before_win_rate"],
        "after_win_rate": row["after_win_rate"],
        "before_max_drawdown": row["before_max_drawdown"],
        "after_max_drawdown": row["after_max_drawdown"],
        "definition_action": "dedupe_confirmation_and_apply_intraday_20_bar_cooldown",
        "definition_status": row["definition_tightening_status"],
        "retest_status": row["after_status"],
        "definition_breadth_review_cleared": "false",
        "uses_profit_curve_tuning": "false",
        "manual_visual_review_required": "false",
        "visual_case_count": "",
        "evidence_ref": project_path(config.m10_9_summary_path),
        "source_metric_ref": project_path(config.m10_9_before_after_metrics_path),
        "notes": row["review_note"],
    }


def visual_definition_row(
    config: DefinitionFixConfig,
    strategy_id: str,
    gate_row: dict[str, Any],
    precheck_row: dict[str, Any],
    case_count: int,
) -> dict[str, str]:
    return {
        "strategy_id": strategy_id,
        "title": STRATEGY_TITLES[strategy_id],
        "work_type": "definition_fields_required_before_retest",
        "timeframe": "",
        "cost_tier": "",
        "before_trade_count": "",
        "after_trade_count": "",
        "removed_count": "",
        "removed_percent": "",
        "before_net_profit": "",
        "after_net_profit": "",
        "delta_net_profit": "",
        "before_return_percent": "",
        "after_return_percent": "",
        "before_win_rate": "",
        "after_win_rate": "",
        "before_max_drawdown": "",
        "after_max_drawdown": "",
        "definition_action": "; ".join(gate_row["spec_requirements"]),
        "definition_status": gate_row["decision"],
        "retest_status": "not_rerun_no_executable_definition_change",
        "definition_breadth_review_cleared": "false",
        "uses_profit_curve_tuning": "false",
        "manual_visual_review_required": str(bool(precheck_row["required_manual_review"])).lower(),
        "visual_case_count": str(case_count),
        "evidence_ref": project_path(config.m12_3_visual_precheck_index_path),
        "source_metric_ref": project_path(config.m10_10_visual_gate_summary_path),
        "notes": gate_row["gate_reason"],
    }


def validate_metric_rows(rows: list[dict[str, str]]) -> None:
    strategy_ids = {row["strategy_id"] for row in rows}
    if strategy_ids != set(TARGET_IDS):
        raise ValueError(f"M12.4 scope drift: {sorted(strategy_ids)}")
    if any(row["uses_profit_curve_tuning"] != "false" for row in rows):
        raise ValueError("M12.4 must not tune definitions by profit curve")
    for strategy_id in VISUAL_DEFINITION_IDS:
        rows_for_strategy = [row for row in rows if row["strategy_id"] == strategy_id]
        if len(rows_for_strategy) != 1:
            raise ValueError(f"{strategy_id} should have one definition-readiness row")
        if rows_for_strategy[0]["retest_status"] != "not_rerun_no_executable_definition_change":
            raise ValueError(f"{strategy_id} must not be reported as retested")


def build_summary(
    config: DefinitionFixConfig,
    generated_at: str,
    metrics_rows: list[dict[str, str]],
    m10_9_summary: dict[str, Any],
    visual_precheck: dict[str, Any],
) -> dict[str, Any]:
    baseline_pa005 = [
        row for row in metrics_rows if row["strategy_id"] == PA005_ID and row["cost_tier"] == "baseline"
    ]
    return {
        "schema_version": "m12.definition-fix-and-retest-summary.v1",
        "generated_at": generated_at,
        "stage": "M12.4.definition_fix_and_retest",
        "run_id": config.run_id,
        "strategy_ids": list(TARGET_IDS),
        "retest_completed_strategy_ids": [PA005_ID],
        "definition_field_only_strategy_ids": list(VISUAL_DEFINITION_IDS),
        "paper_simulated_only": True,
        "paper_trading_approval": False,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "uses_profit_curve_tuning": False,
        "source_refs": {
            "m10_9_summary": project_path(config.m10_9_summary_path),
            "m10_9_metrics": project_path(config.m10_9_before_after_metrics_path),
            "m10_10_visual_gate": project_path(config.m10_10_visual_gate_summary_path),
            "m12_3_visual_precheck": project_path(config.m12_3_visual_precheck_index_path),
        },
        "pa005_definition_cleared": bool(m10_9_summary["definition_cleared"]),
        "pa005_definition_cleared_reason": m10_9_summary["definition_cleared_reason"],
        "pa005_baseline_rows": baseline_pa005,
        "visual_definition_case_count": visual_definition_case_count(visual_precheck),
        "strategy_status": [
            {
                "strategy_id": PA005_ID,
                "status": "needs_definition_fix",
                "reason": "M10.9 reduced duplicate and over-dense triggers, but range geometry fields remain unavailable.",
                "retest_status": "completed_with_definition_blocker",
            },
            {
                "strategy_id": "M10-PA-004",
                "status": "needs_definition_fix",
                "reason": "Broad channel boundary quality, touch tolerance, and strong breakout disqualifier are not yet executable fields.",
                "retest_status": "deferred_until_definition_fields_exist",
            },
            {
                "strategy_id": "M10-PA-007",
                "status": "needs_definition_fix",
                "reason": "First leg, second leg, trap confirmation, and range/breakout edge labels are not yet executable fields.",
                "retest_status": "deferred_until_definition_fields_exist",
            },
        ],
        "artifacts": {
            "metrics_csv": project_path(config.output_dir / "m12_4_before_after_metrics.csv"),
            "definition_fix_report": project_path(config.output_dir / "m12_4_definition_fix_report.md"),
            "client_summary": project_path(config.output_dir / "m12_4_retest_client_summary.md"),
            "summary_json": project_path(config.output_dir / "m12_4_definition_fix_summary.json"),
        },
    }


def write_metrics(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "strategy_id",
        "title",
        "work_type",
        "timeframe",
        "cost_tier",
        "before_trade_count",
        "after_trade_count",
        "removed_count",
        "removed_percent",
        "before_net_profit",
        "after_net_profit",
        "delta_net_profit",
        "before_return_percent",
        "after_return_percent",
        "before_win_rate",
        "after_win_rate",
        "before_max_drawdown",
        "after_max_drawdown",
        "definition_action",
        "definition_status",
        "retest_status",
        "definition_breadth_review_cleared",
        "uses_profit_curve_tuning",
        "manual_visual_review_required",
        "visual_case_count",
        "evidence_ref",
        "source_metric_ref",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def visual_definition_case_count(visual_precheck: dict[str, Any]) -> int:
    return sum(1 for row in visual_precheck["case_rows"] if row["strategy_id"] in VISUAL_DEFINITION_IDS)


def build_report(summary: dict[str, Any], metrics_rows: list[dict[str, str]]) -> str:
    baseline_pa005 = summary["pa005_baseline_rows"]
    visual_rows = [row for row in metrics_rows if row["strategy_id"] in VISUAL_DEFINITION_IDS]
    lines = [
        "# M12.4 定义修正与复测报告",
        "",
        "## 摘要",
        "",
        "- 范围只覆盖 `M10-PA-005`、`M10-PA-004`、`M10-PA-007`。",
        "- `M10-PA-005` 复用 M10.9 的结构性清理复测结果：移除重复确认，并对日内同方向触发加入 20-bar 冷却。",
        "- `M10-PA-004/007` 本阶段只沉淀可执行字段缺口，不生成交易结果。",
        "- 本阶段没有根据资金曲线、收益率、胜率或回撤调参。",
        "- 仍然不接 broker、不接真实账户、不下单，也不批准 paper trading。",
        "",
        "## M10-PA-005 Baseline 复测结果",
        "",
        "| Timeframe | Trades Before | Trades After | Net Profit Before | Net Profit After | Return Before | Return After | Win Rate Before | Win Rate After | Max DD Before | Max DD After | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in baseline_pa005:
        lines.append(
            f"| {row['timeframe']} | {row['before_trade_count']} | {row['after_trade_count']} | "
            f"{row['before_net_profit']} | {row['after_net_profit']} | {row['before_return_percent']} | "
            f"{row['after_return_percent']} | {row['before_win_rate']} | {row['after_win_rate']} | "
            f"{row['before_max_drawdown']} | {row['after_max_drawdown']} | {row['retest_status']} |"
        )
    lines.extend(
        [
            "",
            "结论：`M10-PA-005` 的噪音明显下降，但 `range_high/range_low/range_midpoint/breakout_extreme/reentry_confirmation_index` 仍未在上游 detector 中持久化，所以继续保持 `needs_definition_fix`。",
            "",
            "## M10-PA-004/007 定义字段缺口",
            "",
            "| Strategy | Visual Cases | Required Fields | Retest Status | Notes |",
            "|---|---:|---|---|---|",
        ]
    )
    for row in visual_rows:
        lines.append(
            f"| {row['strategy_id']} | {row['visual_case_count']} | {row['definition_action']} | "
            f"{row['retest_status']} | {row['notes']} |"
        )
    lines.extend(
        [
            "",
            "## 后续处理",
            "",
            "- `M10-PA-005`：下一轮要在 detector 层持久化交易区间几何字段，然后再复跑，不再只从交易行反推。",
            "- `M10-PA-004`：先补通道边界 anchor、边界触碰容差、强突破排除字段，再判断是否能进入复测。",
            "- `M10-PA-007`：先补第一腿、第二腿、陷阱确认 bar、区间或突破边界标签，再判断是否能进入复测。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_client_summary(summary: dict[str, Any], metrics_rows: list[dict[str, str]]) -> str:
    pa005_baseline = summary["pa005_baseline_rows"]
    visual_rows = [row for row in metrics_rows if row["strategy_id"] in VISUAL_DEFINITION_IDS]
    lines = [
        "# M12.4 复测客户摘要",
        "",
        "## 这一步解决了什么",
        "",
        "本阶段把不能继续推进的几条策略拆清楚：哪一条已经有复测数字，哪几条还缺可执行定义。没有为了凑结果补假交易。",
        "",
        "## 已有数字的策略",
        "",
        "| 策略 | 周期 | 修正前交易数 | 修正后交易数 | 修正后净利润 | 修正后胜率 | 当前状态 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in pa005_baseline:
        lines.append(
            f"| {row['strategy_id']} | {row['timeframe']} | {row['before_trade_count']} | "
            f"{row['after_trade_count']} | {row['after_net_profit']} | {row['after_win_rate']} | "
            f"{row['retest_status']} |"
        )
    lines.extend(
        [
            "",
            "## 暂不能给交易数字的策略",
            "",
            "| 策略 | 已有图例数 | 为什么先不复测 | 下一步要补什么 |",
            "|---|---:|---|---|",
        ]
    )
    for row in visual_rows:
        lines.append(
            f"| {row['strategy_id']} | {row['visual_case_count']} | {row['notes']} | {row['definition_action']} |"
        )
    lines.extend(
        [
            "",
            "## 甲方视角结论",
            "",
            "`M10-PA-005` 有复测数字，但仍不够干净，暂不进入自动观察或选股扫描。`M10-PA-004/007` 有图例证据，但还没有可执行定义，不能硬跑历史回测。下一阶段应进入 M12.5 选股扫描，第一版只接 Tier A 主线，同时把这些策略留在定义修正队列。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def project_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output_dir.glob("m12_4_*")
        if path.is_file()
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_TEXT:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden output string found: {forbidden}")


if __name__ == "__main__":
    run_m12_definition_fix_and_retest(load_definition_fix_config())
