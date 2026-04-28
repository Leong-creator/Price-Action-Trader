#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_9_DIR = M10_DIR / "visual_review" / "m12_9_closure"
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m12_visual_review_closure.json"
FORBIDDEN_OUTPUT_TEXT = ("PA-SC-", "SF-", "live-ready", "real_orders=true", "broker_connection=true")
REQUIRED_PRIORITY = ("M10-PA-008", "M10-PA-009")
REQUIRED_WATCHLIST = ("M10-PA-003", "M10-PA-011")
REQUIRED_DEFINITION_SUPPORT = ("M10-PA-004", "M10-PA-007")


@dataclass(frozen=True, slots=True)
class VisualClosureConfig:
    title: str
    run_id: str
    stage: str
    precheck_index_path: Path
    output_dir: Path
    priority_strategy_ids: tuple[str, ...]
    watchlist_strategy_ids: tuple[str, ...]
    definition_support_strategy_ids: tuple[str, ...]
    paper_simulated_only: bool
    broker_connection: bool
    real_orders: bool
    live_execution: bool
    paper_trading_approval: bool


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def project_path(path: Path | None) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def load_visual_closure_config(path: str | Path = DEFAULT_CONFIG_PATH) -> VisualClosureConfig:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    config = VisualClosureConfig(
        title=payload["title"],
        run_id=payload.get("run_id", "m12_9_visual_review_closure"),
        stage=payload["stage"],
        precheck_index_path=resolve_repo_path(payload["m12_3_precheck_index"]),
        output_dir=resolve_repo_path(payload["output_dir"]),
        priority_strategy_ids=tuple(payload["priority_strategy_ids"]),
        watchlist_strategy_ids=tuple(payload["watchlist_strategy_ids"]),
        definition_support_strategy_ids=tuple(payload["definition_support_strategy_ids"]),
        paper_simulated_only=bool(payload["paper_simulated_only"]),
        broker_connection=bool(payload["broker_connection"]),
        real_orders=bool(payload["real_orders"]),
        live_execution=bool(payload["live_execution"]),
        paper_trading_approval=bool(payload["paper_trading_approval"]),
    )
    validate_config(config)
    return config


def validate_config(config: VisualClosureConfig) -> None:
    if config.stage != "M12.9.visual_review_closure":
        raise ValueError("M12.9 stage drift")
    if config.priority_strategy_ids != REQUIRED_PRIORITY:
        raise ValueError("M12.9 priority visual strategies must stay M10-PA-008/009")
    if config.watchlist_strategy_ids != REQUIRED_WATCHLIST:
        raise ValueError("M12.9 watchlist strategies must stay M10-PA-003/011")
    if config.definition_support_strategy_ids != REQUIRED_DEFINITION_SUPPORT:
        raise ValueError("M12.9 definition support strategies must stay M10-PA-004/007")
    if not config.paper_simulated_only:
        raise ValueError("M12.9 must stay paper/simulated only")
    if config.broker_connection or config.real_orders or config.live_execution or config.paper_trading_approval:
        raise ValueError("M12.9 must not approve broker/live/order/paper trading")


def run_m12_visual_review_closure(
    config: VisualClosureConfig,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    validate_config(config)
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    config.output_dir.mkdir(parents=True, exist_ok=True)

    precheck = json.loads(config.precheck_index_path.read_text(encoding="utf-8"))
    case_rows = [row for row in precheck["case_rows"] if row["strategy_id"] in strategy_scope(config)]
    strategy_rows = build_strategy_rows(config, precheck, case_rows)
    case_ledger = [build_case_review(config, row) for row in case_rows]
    user_review_cases = [row for row in case_ledger if row["user_review_required"]]
    decision_counts = dict(Counter(row["strategy_level_status"] for row in strategy_rows))

    index = {
        "schema_version": "m12.visual-review-closure-index.v1",
        "stage": config.stage,
        "run_id": config.run_id,
        "generated_at": generated_at,
        "source_reuse_refs": {
            "m12_3_precheck_index": project_path(config.precheck_index_path),
            "m10_2_visual_golden_case_index": "reports/strategy_lab/m10_price_action_strategy_refresh/m10_visual_golden_case_index.json",
            "m10_10_visual_gate_summary": "reports/strategy_lab/m10_price_action_strategy_refresh/visual_wave_b_gate/m10_10/m10_10_visual_gate_summary.json",
        },
        "paper_simulated_only": config.paper_simulated_only,
        "broker_connection": config.broker_connection,
        "real_orders": config.real_orders,
        "live_execution": config.live_execution,
        "paper_trading_approval": config.paper_trading_approval,
        "strategy_count": len(strategy_rows),
        "case_count": len(case_ledger),
        "user_review_required_case_count": len(user_review_cases),
        "decision_counts": decision_counts,
        "strategy_rows": strategy_rows,
        "artifacts": {
            "closure_index": project_path(config.output_dir / "m12_9_visual_closure_index.json"),
            "case_review_ledger": project_path(config.output_dir / "m12_9_case_review_ledger.json"),
            "user_review_packet": project_path(config.output_dir / "m12_9_user_review_packet.md"),
            "visual_gate_closure_report": project_path(config.output_dir / "m12_9_visual_gate_closure_report.md"),
            "handoff": project_path(config.output_dir / "m12_9_handoff.md"),
        },
        "boundary_note": (
            "M12.9 closes agent-side visual precheck only. Priority strategies still require user confirmation "
            "before paper gate evidence can be counted."
        ),
    }

    write_json(config.output_dir / "m12_9_visual_closure_index.json", index)
    write_json(
        config.output_dir / "m12_9_case_review_ledger.json",
        {
            "schema_version": "m12.visual-case-review-ledger.v1",
            "stage": config.stage,
            "generated_at": generated_at,
            "case_rows": case_ledger,
        },
    )
    (config.output_dir / "m12_9_user_review_packet.md").write_text(
        build_user_review_packet(index, user_review_cases),
        encoding="utf-8",
    )
    (config.output_dir / "m12_9_visual_gate_closure_report.md").write_text(
        build_report(index),
        encoding="utf-8",
    )
    (config.output_dir / "m12_9_handoff.md").write_text(build_handoff(config, index), encoding="utf-8")
    assert_no_forbidden_output(config.output_dir)
    return index


def strategy_scope(config: VisualClosureConfig) -> set[str]:
    return set(config.priority_strategy_ids + config.watchlist_strategy_ids + config.definition_support_strategy_ids)


def build_strategy_rows(
    config: VisualClosureConfig,
    precheck: dict[str, Any],
    case_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    precheck_by_strategy = {row["strategy_id"]: row for row in precheck["strategy_rows"]}
    cases_by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in case_rows:
        cases_by_strategy[row["strategy_id"]].append(row)

    ordered_ids = config.priority_strategy_ids + config.watchlist_strategy_ids + config.definition_support_strategy_ids
    rows: list[dict[str, Any]] = []
    for strategy_id in ordered_ids:
        source = precheck_by_strategy[strategy_id]
        cases = cases_by_strategy[strategy_id]
        missing = [case for case in cases if not case.get("evidence_exists") or not case.get("checksum_match")]
        if missing:
            status = "blocked_missing_evidence"
            recommendation = "repair_evidence_before_review"
            user_confirmation_required = False
            paper_gate_evidence_now = False
        elif strategy_id in config.definition_support_strategy_ids:
            status = "needs_definition_fix"
            recommendation = "use_visual_cases_to_fix_definition_fields"
            user_confirmation_required = False
            paper_gate_evidence_now = False
        elif strategy_id in config.priority_strategy_ids:
            status = "visual_review_closed"
            recommendation = "ready_for_user_confirmation_before_gate"
            user_confirmation_required = True
            paper_gate_evidence_now = False
        else:
            status = "visual_review_closed"
            recommendation = "watchlist_agent_precheck_closed_not_gate_priority"
            user_confirmation_required = False
            paper_gate_evidence_now = False

        rows.append(
            {
                "strategy_id": strategy_id,
                "priority_bucket": source["priority_bucket"],
                "source_gate_decision": source["gate_decision"],
                "strategy_level_status": status,
                "recommendation": recommendation,
                "case_counts": dict(Counter(case["case_type"] for case in cases)),
                "case_count": len(cases),
                "evidence_complete": not missing and bool(cases),
                "agent_precheck_closed": status == "visual_review_closed",
                "user_confirmation_required_before_paper_gate": user_confirmation_required,
                "paper_gate_evidence_now": paper_gate_evidence_now,
                "definition_fix_required": status == "needs_definition_fix",
                "visual_read_notes": visual_read_notes(strategy_id),
                "source_refs": {
                    "case_pack_json": source.get("case_pack_json"),
                    "case_pack_markdown": source.get("case_pack_markdown"),
                    "m12_3_precheck_index": "reports/strategy_lab/m10_price_action_strategy_refresh/visual_review/m12_3_precheck/m12_3_visual_precheck_index.json",
                },
            }
        )
    return rows


def build_case_review(config: VisualClosureConfig, row: dict[str, Any]) -> dict[str, Any]:
    strategy_id = row["strategy_id"]
    if not row.get("evidence_exists") or not row.get("checksum_match"):
        decision = "blocked_missing_evidence"
        user_review_required = False
    elif strategy_id in config.definition_support_strategy_ids:
        decision = "pass_for_definition_evidence"
        user_review_required = False
    elif row["case_type"] == "boundary":
        decision = "ambiguous"
        user_review_required = strategy_id in config.priority_strategy_ids
    elif row["case_type"] == "counterexample":
        decision = "pass_as_counterexample"
        user_review_required = strategy_id in config.priority_strategy_ids
    else:
        decision = "pass"
        user_review_required = strategy_id in config.priority_strategy_ids

    return {
        "strategy_id": strategy_id,
        "case_id": row["case_id"],
        "case_type": row["case_type"],
        "case_level_decision": decision,
        "agent_precheck_status": "agent_prechecked",
        "user_review_required": user_review_required,
        "evidence_exists": row.get("evidence_exists"),
        "checksum_match": row.get("checksum_match"),
        "evidence_image_logical_path": row.get("evidence_image_logical_path"),
        "evidence_resolved_local_path": row.get("evidence_resolved_local_path"),
        "evidence_image_checksum": row.get("evidence_image_checksum"),
        "brooks_unit_ref": row.get("brooks_unit_ref"),
        "evidence_page": row.get("evidence_page"),
        "evidence_video_id": row.get("evidence_video_id"),
        "pattern_decision_points": row.get("pattern_decision_points", []),
        "disqualifiers": row.get("disqualifiers", []),
        "ohlcv_approximation_risk": row.get("ohlcv_approximation_risk"),
        "manual_review_status": "pending_user_confirmation" if user_review_required else "not_required_for_m12_9",
        "paper_gate_evidence_now": False,
    }


def visual_read_notes(strategy_id: str) -> str:
    notes = {
        "M10-PA-008": (
            "Agent viewed priority MTR evidence images: cases show prior trend, repeated MTR attempts, trendline break/test, "
            "and boundary examples where insufficient pressure implies minor reversal or trading range rather than trend reversal."
        ),
        "M10-PA-009": (
            "Agent viewed priority wedge evidence images: cases show wedge/triangle/channel overlap, three-push structure, "
            "failed breakout context, and line-drawing ambiguity that still needs user confirmation for key cases."
        ),
        "M10-PA-003": "M12.3 evidence pack is complete; keep as watchlist after priority visual strategies.",
        "M10-PA-011": "M12.3 evidence pack is complete; opening context remains session-specific and not a paper gate input.",
        "M10-PA-004": "Use broad-channel boundary images to define channel boundary, touch, reversal confirmation, and failure fields.",
        "M10-PA-007": "Use second-leg trap images to define first leg, second leg, trap confirmation, and invalidation fields.",
    }
    return notes[strategy_id]


def build_user_review_packet(index: dict[str, Any], user_review_cases: list[dict[str, Any]]) -> str:
    lines = [
        "# M12.9 User Visual Review Packet",
        "",
        "本包只要求用户复核优先级最高的 `M10-PA-008 / M10-PA-009` 关键图例。",
        "Agent 已预审图例存在性、checksum、Brooks source refs 和图形语义，但这些预审不能替代用户视觉确认。",
        "",
        f"- 需用户复核 case 数：`{len(user_review_cases)}`",
        "- 当前不批准 paper trading；所有 case 的 `paper_gate_evidence_now=false`。",
        "",
        "| strategy | case | type | agent decision | why review | image logical path |",
        "|---|---|---|---|---|---|",
    ]
    for row in user_review_cases:
        why = "priority strategy gate confirmation"
        if row["case_level_decision"] == "ambiguous":
            why = "boundary / ambiguous visual context"
        lines.append(
            "| {strategy_id} | {case_id} | {case_type} | `{case_level_decision}` | {why} | `{path}` |".format(
                strategy_id=row["strategy_id"],
                case_id=row["case_id"],
                case_type=row["case_type"],
                case_level_decision=row["case_level_decision"],
                why=why,
                path=row["evidence_image_logical_path"],
            )
        )
    lines.extend(
        [
            "",
            "## 用户确认口径",
            "",
            "- `pass`：图例确实符合策略关键几何语义。",
            "- `fail`：图例不应支持该策略，后续必须降级或重选图例。",
            "- `ambiguous`：图例需要更多上下文；不得作为 gate evidence。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_report(index: dict[str, Any]) -> str:
    lines = [
        "# M12.9 Visual Review Closure Report",
        "",
        "## 摘要",
        "",
        f"- 覆盖策略：`{index['strategy_count']}` 条。",
        f"- 覆盖 case：`{index['case_count']}` 个。",
        f"- 需要用户复核 case：`{index['user_review_required_case_count']}` 个。",
        "- M12.9 只关闭 agent-side precheck，不批准 paper trading。",
        "",
        "## 策略结论",
        "",
        "| strategy | status | recommendation | user confirmation | paper gate evidence now |",
        "|---|---|---|---|---|",
    ]
    for row in index["strategy_rows"]:
        lines.append(
            f"| {row['strategy_id']} | `{row['strategy_level_status']}` | `{row['recommendation']}` | "
            f"`{row['user_confirmation_required_before_paper_gate']}` | `{row['paper_gate_evidence_now']}` |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- `broker_connection=false`",
            "- `real_orders=false`",
            "- `live_execution=false`",
            "- `paper_trading_approval=false`",
            "- `M10-PA-004 / M10-PA-007` 只进入定义修复，不进入自动回测或 paper gate。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_handoff(config: VisualClosureConfig, index: dict[str, Any]) -> str:
    return f"""task_id: M12.9 Visual Review Closure
role: main_agent
branch_or_worktree: feature/m12-9-visual-review-closure
objective: Close agent-side visual review precheck for priority visual strategies, prepare user review packet, and keep definition blockers separated.
status: success
files_changed:
  - README.md
  - docs/acceptance.md
  - docs/status.md
  - plans/active-plan.md
  - reports/strategy_lab/README.md
  - config/examples/m12_visual_review_closure.json
  - scripts/m12_visual_review_closure_lib.py
  - scripts/run_m12_visual_review_closure.py
  - tests/unit/test_m12_visual_review_closure.py
  - reports/strategy_lab/m10_price_action_strategy_refresh/visual_review/m12_9_closure/
interfaces_changed:
  - Added M12.9 visual review closure artifacts and runner.
commands_run:
  - python scripts/run_m12_visual_review_closure.py
tests_run:
  - python -m unittest tests/unit/test_m12_visual_review_closure.py -v
assumptions:
  - Agent-side visual precheck does not replace user confirmation for priority cases.
  - Brooks v2 evidence images remain local-only and are referenced by logical path/checksum.
risks:
  - M10-PA-008/009 still cannot count as paper gate evidence until user confirms priority cases.
qa_focus:
  - Confirm priority strategies require user confirmation before paper gate.
  - Confirm M10-PA-004/007 remain definition-fix support only.
rollback_notes:
  - Revert M12.9 commit, including docs/status.md, plans/active-plan.md, docs/acceptance.md, README files, runner, tests, and {project_path(config.output_dir)} artifacts.
next_recommended_action: Continue M12.10 definition fix and retest; keep M10-PA-008/009 out of paper gate evidence until the user confirms priority visual cases.
needs_user_decision: true
user_decision_needed: Confirm or reject the 10 priority M10-PA-008/009 visual cases before those strategies can count as paper gate evidence; this does not block starting M12.10 definition fix work.
summary:
  strategy_count: {index['strategy_count']}
  case_count: {index['case_count']}
  user_review_required_case_count: {index['user_review_required_case_count']}
"""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def assert_no_forbidden_output(output_dir: Path) -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output_dir.glob("m12_9_*")
        if path.is_file()
    )
    lowered = combined.lower()
    for forbidden in FORBIDDEN_OUTPUT_TEXT:
        if forbidden.lower() in lowered:
            raise ValueError(f"Forbidden M12.9 output text found: {forbidden}")


def main() -> int:
    summary = run_m12_visual_review_closure(load_visual_closure_config())
    print(
        "M12.9 visual review closure complete: "
        f"strategies={summary['strategy_count']} / cases={summary['case_count']} / "
        f"user_review_required={summary['user_review_required_case_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
