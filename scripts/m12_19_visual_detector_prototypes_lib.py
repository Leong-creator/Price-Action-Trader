#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
VISUAL_CASE_DIR = M10_DIR / "visual_golden_cases"
OUTPUT_DIR = M10_DIR / "visual_detectors" / "m12_19"
DETECTOR_STRATEGIES = ("M10-PA-004", "M10-PA-007")
FORBIDDEN_OUTPUT_TEXT = ("live-ready", "real_orders=true", "broker_connection=true", "paper approval", "order_id", "fill_id", "account_id")


DETECTOR_RULES = {
    "M10-PA-004": {
        "name": "宽通道边界反转检测器原型",
        "machine_needs_to_detect": ["宽通道", "通道边界", "触边", "触边后反转确认", "强突破失效条件"],
        "minimum_ohlcv_fields": ["swing_high_low_sequence", "channel_width_proxy", "boundary_touch_count", "reversal_bar", "breakout_follow_through"],
        "prototype_decision": "detector_prototype_ready_not_backtest_ready",
        "why": "Brooks 图例足够说明要检测什么，但仅靠当前 OHLCV 近似还不能稳定判断通道画线质量。",
    },
    "M10-PA-007": {
        "name": "第二腿陷阱反转检测器原型",
        "machine_needs_to_detect": ["第一腿", "第二腿", "陷阱点", "反向失败点", "反转确认K线"],
        "minimum_ohlcv_fields": ["leg1_extreme", "leg2_extreme", "trap_break_level", "failure_close", "reversal_bar"],
        "prototype_decision": "detector_prototype_ready_not_backtest_ready",
        "why": "Brooks 图例足够说明腿部和陷阱结构，但当前还缺稳定的腿部计数器和陷阱确认器。",
    },
}


def run_m12_19_visual_detector_prototypes(
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)
    packs = {sid: load_json(VISUAL_CASE_DIR / f"{sid}.json") for sid in DETECTOR_STRATEGIES}
    candidates = []
    for strategy_id, pack in packs.items():
        for case in pack["cases"]:
            candidates.append(build_detector_candidate(generated_at, strategy_id, case))
    summary = {
        "schema_version": "m12.19.visual-detector-prototypes.v1",
        "stage": "M12.19.visual_detector_prototypes",
        "generated_at": generated_at,
        "plain_language_result": "M10-PA-004/007 已不再挂“等确认”；现在状态是检测器原型已定义，但还不能当交易策略回测。",
        "strategy_scope": list(DETECTOR_STRATEGIES),
        "detector_rules": DETECTOR_RULES,
        "candidate_count": len(candidates),
        "candidate_count_by_strategy": {
            strategy_id: sum(1 for row in candidates if row["strategy_id"] == strategy_id)
            for strategy_id in DETECTOR_STRATEGIES
        },
        "key_example_pack": build_key_example_pack(candidates),
        "strategy_decisions": {
            strategy_id: {
                "decision": DETECTOR_RULES[strategy_id]["prototype_decision"],
                "plain_language": "先做检测器原型和样例，不进入自动回测；检测器稳定后再开历史测试。",
                "next_step": "后续若继续推进，需要把 OHLCV swing/leg/channel detector 做成可重复单测。",
            }
            for strategy_id in DETECTOR_STRATEGIES
        },
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_json(output_dir / "m12_19_visual_detector_summary.json", summary)
    write_json(output_dir / "m12_19_detector_rules.json", {"schema_version": "m12.19.detector-rules.v1", "rules": DETECTOR_RULES})
    write_json(output_dir / "m12_19_key_example_pack.json", summary["key_example_pack"])
    write_jsonl(output_dir / "m12_19_detector_candidates.jsonl", candidates)
    write_csv(output_dir / "m12_19_detector_candidates.csv", candidates)
    (output_dir / "m12_19_visual_detector_report.md").write_text(build_report_md(summary), encoding="utf-8")
    (output_dir / "m12_19_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def build_detector_candidate(generated_at: str, strategy_id: str, case: dict[str, Any]) -> dict[str, str]:
    rule = DETECTOR_RULES[strategy_id]
    return {
        "schema_version": "m12.19.detector-candidate.v1",
        "stage": "M12.19.visual_detector_prototypes",
        "generated_at": generated_at,
        "strategy_id": strategy_id,
        "detector_name": rule["name"],
        "case_id": case["case_id"],
        "case_type": case["case_type"],
        "brooks_unit_ref": case["brooks_unit_ref"],
        "evidence_image_logical_path": case["evidence_image_logical_path"],
        "evidence_image_checksum": case["evidence_image_checksum"],
        "automatic_reason": build_reason(strategy_id, case),
        "machine_needs_to_detect": "；".join(rule["machine_needs_to_detect"]),
        "minimum_ohlcv_fields": "；".join(rule["minimum_ohlcv_fields"]),
        "detector_status": rule["prototype_decision"],
        "not_trade_signal": "true",
    }


def build_reason(strategy_id: str, case: dict[str, Any]) -> str:
    if strategy_id == "M10-PA-004":
        return "该图例用于训练机器识别宽通道、边界触碰和触边后失败反转，不直接代表可交易信号。"
    return "该图例用于训练机器识别第一腿、第二腿、陷阱点和反向失败确认，不直接代表可交易信号。"


def build_key_example_pack(candidates: list[dict[str, str]]) -> dict[str, Any]:
    pack = {"schema_version": "m12.19.key-example-pack.v1", "strategies": {}}
    for strategy_id in DETECTOR_STRATEGIES:
        rows = [row for row in candidates if row["strategy_id"] == strategy_id]
        pack["strategies"][strategy_id] = {
            "positive_examples": [row for row in rows if row["case_type"] == "positive"][:3],
            "counter_or_boundary_examples": [row for row in rows if row["case_type"] != "positive"][:3],
        }
    return pack


def build_report_md(summary: dict[str, Any]) -> str:
    lines = [
        "# M12.19 图形检测器原型报告",
        "",
        "## 用人话结论",
        "",
        "- `M10-PA-004/007` 不再拖在“等图例确认”状态。",
        "- 当前处理方式是：先做机器检测器原型，明确机器要识别什么图形，再决定以后是否值得回测。",
        f"- 本轮整理出 `{summary['candidate_count']}` 个检测器候选图例："
        f"`M10-PA-004` {summary['candidate_count_by_strategy']['M10-PA-004']} 个，"
        f"`M10-PA-007` {summary['candidate_count_by_strategy']['M10-PA-007']} 个。",
        "- 这些不是交易信号，也不输出盈利、胜率或回撤。",
        "",
        "## 检测器规则",
        "",
    ]
    for strategy_id, rule in DETECTOR_RULES.items():
        lines.append(f"### {strategy_id} {rule['name']}")
        lines.append(f"- 机器要识别：{'、'.join(rule['machine_needs_to_detect'])}")
        lines.append(f"- 最少字段：{'、'.join(rule['minimum_ohlcv_fields'])}")
        lines.append(f"- 当前结论：{rule['prototype_decision']}")
        lines.append(f"- 原因：{rule['why']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "# M12.19 Handoff\n\n"
        "## 用人话结论\n\n"
        "`M10-PA-004/007` 已关闭等待状态，改为检测器原型任务；当前不进入自动回测或模拟买卖准入。\n\n"
        "## 下一步\n\n"
        "- 继续每日只读测试累计到10个交易日。\n"
        "- 如果要继续推进这两条图形策略，需要单独实现 swing/leg/channel 检测器并补单测。\n"
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def assert_no_forbidden_output(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_OUTPUT_TEXT:
            if forbidden in text:
                raise AssertionError(f"Forbidden text {forbidden!r} found in {path}")
