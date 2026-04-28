#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
SOURCE_REVISIT_DIR = M10_DIR / "source_revisit" / "m12_14_source_strategy_closure"
FTD_RETEST_DIR = M10_DIR / "ftd_v02_ab_retest" / "m12_15"
OUTPUT_DIR = M10_DIR / "source_candidate_test_plan" / "m12_16"
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


def run_m12_16_source_candidate_test_plan(
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = load_json(SOURCE_REVISIT_DIR / "m12_14_source_revisit_strategy_candidates.json")
    best_variant = load_json(FTD_RETEST_DIR / "m12_15_best_variant.json")
    plan_rows = build_plan_rows(candidates["candidates"], best_variant)
    daily_queue = [row for row in plan_rows if row["queue"] == "daily_readonly_test"]
    filter_queue = [row for row in plan_rows if row["queue"] == "filter_or_ranking_factor"]
    observation_queue = [row for row in plan_rows if row["queue"] == "strict_observation"]

    summary = {
        "schema_version": "m12.16.source-candidate-test-plan.v1",
        "stage": "M12.16.source_candidate_test_plan",
        "generated_at": generated_at,
        "plain_language_result": "6条来源回看候选已排队：3条进每日只读测试，2条先做过滤/排名因子，1条进反转观察队列。",
        "candidate_count": len(plan_rows),
        "daily_readonly_test_count": len(daily_queue),
        "filter_or_ranking_factor_count": len(filter_queue),
        "strict_observation_count": len(observation_queue),
        "selected_ftd_variant": best_variant["selected_variant_id"],
        "selected_ftd_variant_metrics": best_variant["metrics"],
        "rows": plan_rows,
        "artifacts": {
            "daily_queue": project_path(output_dir / "m12_16_daily_test_queue.json"),
            "filter_queue": project_path(output_dir / "m12_16_filter_queue.json"),
            "observation_queue": project_path(output_dir / "m12_16_observation_queue.json"),
            "client_status_table": project_path(output_dir / "m12_16_source_candidate_status.md"),
        },
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }

    write_json(output_dir / "m12_16_source_candidate_test_plan.json", summary)
    write_json(output_dir / "m12_16_daily_test_queue.json", {"schema_version": "m12.16.daily-queue.v1", "rows": daily_queue})
    write_json(output_dir / "m12_16_filter_queue.json", {"schema_version": "m12.16.filter-queue.v1", "rows": filter_queue})
    write_json(output_dir / "m12_16_observation_queue.json", {"schema_version": "m12.16.observation-queue.v1", "rows": observation_queue})
    (output_dir / "m12_16_source_candidate_status.md").write_text(build_status_md(summary), encoding="utf-8")
    (output_dir / "m12_16_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def build_plan_rows(candidates: list[dict[str, Any]], best_variant: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {item["candidate_id"]: item for item in candidates}
    rows = [
        make_row(
            by_id["M12-SRC-001"],
            queue="daily_readonly_test",
            status="进入每日只读测试",
            action="使用 M12.15 选出的 pullback_guard 版本，先观察回撤是否比 baseline 稳定。",
            next_stage="M12.17",
            linked_runtime_id="M12-FTD-001",
            selected_variant=best_variant["selected_variant_id"],
            client_note="这是早期强策略的增强版，先放进每日观察，不直接批准模拟买卖。",
        ),
        make_row(
            by_id["M12-SRC-002"],
            queue="daily_readonly_test",
            status="进入每日只读测试",
            action="继续作为 M10-PA-001 主线，扫描第一批50只股票。",
            next_stage="M12.17",
            linked_runtime_id="M10-PA-001",
            client_note="这是已通过历史资金测试的核心顺势策略。",
        ),
        make_row(
            by_id["M12-SRC-003"],
            queue="daily_readonly_test",
            status="进入每日只读测试，并保留为 FTD 确认过滤器候选",
            action="继续作为 M10-PA-002 主线；后续可检查它能否过滤 FTD 假信号。",
            next_stage="M12.17",
            linked_runtime_id="M10-PA-002",
            client_note="它本身是核心策略，也能帮助判断强K线后有没有真实延续。",
        ),
        make_row(
            by_id["M12-SRC-004"],
            queue="filter_or_ranking_factor",
            status="先做选股排名因子",
            action="用于给强趋势股票加分，暂不作为独立买卖触发。",
            next_stage="M12.17/M12.18",
            linked_runtime_id="M10-PA-003",
            client_note="它更像帮我们从50只里挑更强的股票，不先单独统计盈利。",
        ),
        make_row(
            by_id["M12-SRC-005"],
            queue="filter_or_ranking_factor",
            status="作为 FTD 风险过滤器",
            action="已在 M12.15 验证为 pullback_guard；后续跟随 FTD 每日观察。",
            next_stage="M12.17",
            linked_runtime_id="M12-FTD-001-filter",
            selected_variant=best_variant["selected_variant_id"],
            client_note="它的作用是减少长回调里的差机会，不是独立策略。",
        ),
        make_row(
            by_id["M12-SRC-006"],
            queue="strict_observation",
            status="进入反转观察队列",
            action="与 M10-PA-008 合并，按严格反转定义观察，不进入自动触发主线。",
            next_stage="M12.18",
            linked_runtime_id="M10-PA-008",
            client_note="反转机会更依赖图形语境，先观察典型机会，不和主线策略混测。",
        ),
    ]
    return rows


def make_row(
    candidate: dict[str, Any],
    *,
    queue: str,
    status: str,
    action: str,
    next_stage: str,
    linked_runtime_id: str,
    client_note: str,
    selected_variant: str = "",
) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "name": candidate["name"],
        "linked_strategy": candidate["linked_strategy"],
        "linked_runtime_id": linked_runtime_id,
        "queue": queue,
        "status": status,
        "next_action": action,
        "next_stage": next_stage,
        "selected_variant": selected_variant,
        "client_note": client_note,
        "source_refs": candidate["source_refs"],
        "paper_gate_evidence_now": False,
    }


def build_status_md(summary: dict[str, Any]) -> str:
    lines = [
        "# M12.16 来源候选测试安排",
        "",
        "## 用人话结论",
        "",
        f"- 6 条候选已经排清楚：`{summary['daily_readonly_test_count']}` 条进入每日只读测试，"
        f"`{summary['filter_or_ranking_factor_count']}` 条先做过滤/排名因子，"
        f"`{summary['strict_observation_count']}` 条进入严格观察队列。",
        f"- 早期强策略下一步使用 `{summary['selected_ftd_variant']}` 版本，不再用 baseline 直接推进。",
        "- 本阶段只是测试安排，不接真实账户、不下真实订单、不批准模拟买卖试运行。",
        "",
        "## 候选状态表",
        "",
        "| 候选 | 名称 | 状态 | 下一步 |",
        "|---|---|---|---|",
    ]
    for row in summary["rows"]:
        lines.append(f"| `{row['candidate_id']}` | {row['name']} | {row['status']} | {row['next_action']} |")
    return "\n".join(lines) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "# M12.16 Handoff\n\n"
        "## 用人话结论\n\n"
        "6 条来源回看候选已经排队。M12.17 可以直接消费每日测试队列；M12.18 消费反转观察队列。\n\n"
        "## 下一步\n\n"
        "- M12.17：把 `M10-PA-001/002/012 + M12-FTD-001 pullback_guard` 接入连续每日只读测试。\n"
        "- M12.18：对 `M10-PA-008/009` 做严格定义观察。\n"
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
