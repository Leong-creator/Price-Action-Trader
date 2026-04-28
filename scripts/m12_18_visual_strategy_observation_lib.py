#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
WAVE_B_DIR = M10_DIR / "capital_backtest" / "m10_11_wave_b"
SOURCE_REVISIT_DIR = M10_DIR / "source_revisit" / "m12_14_source_strategy_closure"
OUTPUT_DIR = M10_DIR / "visual_observation" / "m12_18"
VISUAL_STRATEGIES = ("M10-PA-008", "M10-PA-009")
FORBIDDEN_OUTPUT_TEXT = ("live-ready", "real_orders=true", "broker_connection=true", "paper approval", "order_id", "fill_id", "account_id")


STRICT_RULES = {
    "M10-PA-008": {
        "name": "主要趋势反转严格观察",
        "must_have": ["趋势先被破坏", "至少一次二次测试", "反转方向确认K线"],
        "disallow": ["第一根反向K线直接当机会", "没有趋势破坏的普通回调", "只靠单根长影线判断"],
        "route": "反转观察队列，不进入自动买卖主线",
    },
    "M10-PA-009": {
        "name": "楔形反转严格观察",
        "must_have": ["三次推动", "可识别通道或三角结构", "反转方向确认K线"],
        "disallow": ["两次推动冒充楔形", "没有通道结构的普通回调", "把反例当正例"],
        "route": "楔形观察队列，不进入自动买卖主线",
    },
}


def run_m12_18_visual_strategy_observation(
    *,
    generated_at: str | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output_dir.mkdir(parents=True, exist_ok=True)
    visual_decision = load_json(SOURCE_REVISIT_DIR / "m12_14_visual_decision_ledger.json")
    source_ledgers = {sid: load_json(M10_DIR / "source_ledgers" / f"{sid}.json") for sid in VISUAL_STRATEGIES}
    candidate_events = read_csv(WAVE_B_DIR / "m10_11_wave_b_candidate_events.csv")
    events = [build_event(generated_at, row, source_ledgers[row["strategy_id"]]) for row in candidate_events if row["strategy_id"] in VISUAL_STRATEGIES]
    counts = Counter(row["strategy_id"] for row in events)
    by_symbol = build_symbol_counts(events)
    example_pack = build_example_pack(events)
    summary = {
        "schema_version": "m12.18.visual-strategy-observation.v1",
        "stage": "M12.18.visual_strategy_observation",
        "generated_at": generated_at,
        "plain_language_result": "M10-PA-008/009 已从图例确认转入严格观察；这批事件只说明哪里可能有图形机会，不等于自动买卖信号。",
        "strategy_scope": list(VISUAL_STRATEGIES),
        "strict_rules": STRICT_RULES,
        "event_count": len(events),
        "event_count_by_strategy": dict(counts),
        "event_count_by_symbol": by_symbol,
        "example_pack": example_pack,
        "visual_decision_ref": project_path(SOURCE_REVISIT_DIR / "m12_14_visual_decision_ledger.json"),
        "visual_decision_user_review_count": visual_decision["needs_user_review_count"],
        "next_decision": {
            "M10-PA-008": "继续观察，积累典型成功/失败样例后再决定是否重跑历史回测",
            "M10-PA-009": "继续观察，积累典型成功/失败样例后再决定是否重跑历史回测",
        },
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    write_json(output_dir / "m12_18_visual_observation_summary.json", summary)
    write_json(output_dir / "m12_18_strict_definition_rules.json", {"schema_version": "m12.18.strict-rules.v1", "rules": STRICT_RULES})
    write_json(output_dir / "m12_18_visual_example_pack.json", example_pack)
    write_jsonl(output_dir / "m12_18_visual_observation_events.jsonl", events)
    write_csv(output_dir / "m12_18_visual_observation_events.csv", events)
    (output_dir / "m12_18_visual_observation_report.md").write_text(build_report_md(summary), encoding="utf-8")
    (output_dir / "m12_18_handoff.md").write_text(build_handoff_md(summary), encoding="utf-8")
    assert_no_forbidden_output(output_dir)
    return summary


def build_event(generated_at: str, row: dict[str, str], source_ledger: dict[str, Any]) -> dict[str, str]:
    strategy_id = row["strategy_id"]
    return {
        "schema_version": "m12.18.visual-observation-event.v1",
        "stage": "M12.18.visual_strategy_observation",
        "generated_at": generated_at,
        "strategy_id": strategy_id,
        "strategy_name": STRICT_RULES[strategy_id]["name"],
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "direction": "看涨" if row["direction"] == "long" else "看跌",
        "signal_timestamp": row["signal_timestamp"],
        "hypothetical_entry_price": row["entry_price"],
        "hypothetical_stop_price": row["stop_price"],
        "hypothetical_target_price": row["target_price"],
        "observation_outcome_hint": classify_outcome_hint(row["exit_reason"]),
        "strict_review_status": "strict_observation_candidate",
        "definition_summary": "；".join(STRICT_RULES[strategy_id]["must_have"]),
        "disqualifiers": "；".join(STRICT_RULES[strategy_id]["disallow"]),
        "source_refs": ";".join(normalize_source_refs(source_ledger.get("source_refs", []))),
        "paper_gate_evidence_now": "false",
    }


def classify_outcome_hint(exit_reason: str) -> str:
    if exit_reason == "target_hit":
        return "典型成功候选"
    if exit_reason in {"stop_hit", "stop_before_target_same_bar"}:
        return "典型失败候选"
    return "边界/未完成候选"


def normalize_source_refs(raw_refs: list[Any]) -> list[str]:
    refs: list[str] = []
    for item in raw_refs:
        if isinstance(item, str):
            refs.append(item)
        elif isinstance(item, dict) and item.get("source_ref"):
            refs.append(str(item["source_ref"]))
    return refs


def build_symbol_counts(events: list[dict[str, str]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in events:
        counts[row["strategy_id"]][row["symbol"]] += 1
    return {sid: dict(counter) for sid, counter in counts.items()}


def build_example_pack(events: list[dict[str, str]]) -> dict[str, Any]:
    pack: dict[str, Any] = {"schema_version": "m12.18.visual-example-pack.v1", "strategies": {}}
    for strategy_id in VISUAL_STRATEGIES:
        strategy_events = [row for row in events if row["strategy_id"] == strategy_id]
        success = [row for row in strategy_events if row["observation_outcome_hint"] == "典型成功候选"][:3]
        failure = [row for row in strategy_events if row["observation_outcome_hint"] == "典型失败候选"][:3]
        boundary = [row for row in strategy_events if row["observation_outcome_hint"] == "边界/未完成候选"][:2]
        pack["strategies"][strategy_id] = {
            "success_examples": success,
            "failure_examples": failure,
            "boundary_examples": boundary,
        }
    return pack


def build_report_md(summary: dict[str, Any]) -> str:
    lines = [
        "# M12.18 图形策略严格观察报告",
        "",
        "## 用人话结论",
        "",
        f"- `M10-PA-008/009` 不再卡人工逐图确认，已经进入严格观察队列。",
        f"- 本轮从既有 Wave B 近似事件中整理出 `{summary['event_count']}` 条观察候选："
        f"`M10-PA-008` {summary['event_count_by_strategy'].get('M10-PA-008', 0)} 条，"
        f"`M10-PA-009` {summary['event_count_by_strategy'].get('M10-PA-009', 0)} 条。",
        "- 这些不是自动买卖信号，只是后续要看的图形机会清单。",
        "",
        "## 严格规则",
        "",
    ]
    for strategy_id, rule in STRICT_RULES.items():
        lines.append(f"### {strategy_id} {rule['name']}")
        lines.append(f"- 必须看到：{'、'.join(rule['must_have'])}")
        lines.append(f"- 排除：{'、'.join(rule['disallow'])}")
        lines.append(f"- 路径：{rule['route']}")
        lines.append("")
    lines.extend([
        "## 下一步",
        "",
        "- 继续把这些事件作为观察样例，不和每日主线自动触发混在一起。",
        "- 样例稳定后，再决定是否进入下一轮历史回测。",
    ])
    return "\n".join(lines) + "\n"


def build_handoff_md(summary: dict[str, Any]) -> str:
    return (
        "# M12.18 Handoff\n\n"
        "## 用人话结论\n\n"
        "`M10-PA-008/009` 已进入严格观察队列，不再等人工逐图确认，也不进入自动买卖主线。\n\n"
        "## 下一步\n\n"
        "- M12.19：为 `M10-PA-004/007` 做图形检测器原型。\n"
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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
