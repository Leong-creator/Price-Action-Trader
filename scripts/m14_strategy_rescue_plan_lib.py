from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_strategy_rescue_plan.json"


@dataclass(frozen=True, slots=True)
class RescuePlanConfig:
    stage: str
    m14_summary_path: Path
    paper_gate_path: Path
    decision_ledger_path: Path
    rescue_plan_json_path: Path
    rescue_plan_md_path: Path
    external_references: tuple[dict[str, str], ...]
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescuePlanConfig:
    payload = read_json(resolve_repo_path(path))
    if payload.get("stage") != "M14.strategy_rescue_plan":
        raise ValueError("M14 rescue plan stage drift")
    inputs = payload["input_paths"]
    outputs = payload["output_paths"]
    hard_boundaries = dict(payload.get("hard_boundaries", {}))
    if not hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue plan must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue plan cannot enable {key}")
    return RescuePlanConfig(
        stage=payload["stage"],
        m14_summary_path=resolve_repo_path(inputs["m14_summary"]),
        paper_gate_path=resolve_repo_path(inputs["m14_paper_trial_gate"]),
        decision_ledger_path=resolve_repo_path(inputs["m14_strategy_decision_ledger"]),
        rescue_plan_json_path=resolve_repo_path(outputs["rescue_plan_json"]),
        rescue_plan_md_path=resolve_repo_path(outputs["rescue_plan_md"]),
        external_references=tuple(dict(item) for item in payload.get("external_references", [])),
        hard_boundaries=hard_boundaries,
    )


def run_m14_strategy_rescue_plan(
    config: RescuePlanConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary = read_json(config.m14_summary_path)
    paper_gate = read_json(config.paper_gate_path)
    latest_decisions = latest_by_strategy(read_jsonl(config.decision_ledger_path))
    gate_by_strategy = {str(row.get("strategy_id")): row for row in paper_gate.get("rows", []) if row.get("strategy_id")}

    approved_ids = sorted(str(item) for item in paper_gate.get("approved_internal_sim_strategy_ids", []))
    rows = []
    for strategy_id in sorted(latest_decisions):
        decision = latest_decisions[strategy_id]
        gate = gate_by_strategy.get(strategy_id, {})
        rows.append(build_rescue_row(strategy_id, decision, gate, approved_ids))

    plan = {
        "schema_version": "m14.strategy-rescue-plan.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "m14_trading_date": summary.get("trading_date", ""),
        "challenge_progress_label": summary.get("challenge_progress_label", ""),
        "paper_trial_gate_approved_count": len(approved_ids),
        "approved_internal_sim_strategy_ids": approved_ids,
        "summary_ref": project_path(config.m14_summary_path),
        "paper_gate_ref": project_path(config.paper_gate_path),
        "decision_ledger_ref": project_path(config.decision_ledger_path),
        "external_references": list(config.external_references),
        "rows": rows,
        "counts": {
            "approved_internal_sim": sum(1 for row in rows if row["lane"] == "approved_internal_sim"),
            "rescue_candidate": sum(1 for row in rows if row["lane"] == "rescue_candidate"),
            "research_or_plugin": sum(1 for row in rows if row["lane"] == "research_or_plugin"),
            "detector_rebuild": sum(1 for row in rows if row["lane"] == "detector_rebuild"),
        },
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
        },
        "plain_language_result": build_plain_language_result(approved_ids, rows),
    }
    write_json(config.rescue_plan_json_path, plan)
    config.rescue_plan_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.rescue_plan_md_path.write_text(build_rescue_plan_md(plan), encoding="utf-8")
    return plan


def build_rescue_row(
    strategy_id: str,
    decision: dict[str, Any],
    gate: dict[str, Any],
    approved_ids: list[str],
) -> dict[str, Any]:
    decision_name = str(decision.get("decision", ""))
    reason = str(decision.get("decision_reason", ""))
    gate_status = str(gate.get("paper_trial_gate", "not_available"))
    pnl_r = decimal_or_zero(decision.get("net_pnl_r"))
    drawdown = decimal_or_zero(decision.get("max_drawdown_percent"))
    signal_days = int_or_zero(decision.get("signal_days"))
    risk_block_ratio = decimal_or_zero(decision.get("risk_block_ratio"))
    variant_id = str(decision.get("next_variant_id") or f"{strategy_id}-m14-rescue-v1")

    if strategy_id in approved_ids and gate_status == "approved_internal_sim_only":
        lane = "approved_internal_sim"
        rescue_mode = "do_not_change_baseline"
        next_action = "Keep the approved baseline running in internal simulated trading; monitor fills, risk blocks, drawdown, and slippage sensitivity."
        optimization_hypothesis = "No parameter change before new internal-sim evidence contradicts the 10-day challenge."
    elif decision_name == "reject" and "no_viable_signal" in reason:
        lane = "detector_rebuild"
        rescue_mode = "rebuild_detector_before_abandon"
        next_action = "Do not discard yet; rebuild the detector contract and run a new shadow variant before final rejection."
        optimization_hypothesis = "The problem is likely no actionable detector coverage, not proven negative expectancy."
    elif decision_name == "modify" or pnl_r < Decimal("0") or drawdown > Decimal("3"):
        lane = "rescue_candidate"
        rescue_mode = classify_rescue_mode(reason, pnl_r, drawdown, risk_block_ratio)
        next_action = f"Freeze baseline semantics, create variant {variant_id}, and A/B test it against the old baseline."
        optimization_hypothesis = build_optimization_hypothesis(reason, pnl_r, drawdown, risk_block_ratio, signal_days)
    else:
        lane = "research_or_plugin"
        rescue_mode = "keep_shadow_or_ab_filter"
        next_action = "Keep it in plugin/filter/research coverage; do not present it as an independent trading account."
        optimization_hypothesis = "Use as a supporting filter or research source until it has independent detector and account evidence."

    return {
        "strategy_id": strategy_id,
        "decision": decision_name,
        "decision_reason": reason,
        "paper_trial_gate": gate_status,
        "lane": lane,
        "rescue_mode": rescue_mode,
        "next_variant_id": variant_id if lane in {"rescue_candidate", "detector_rebuild"} else "",
        "next_action": next_action,
        "optimization_hypothesis": optimization_hypothesis,
        "realized_pnl": str(decision.get("realized_pnl", "0.00")),
        "net_pnl_r": str(decision.get("net_pnl_r", "0")),
        "max_drawdown_percent": str(decision.get("max_drawdown_percent", "0")),
        "signal_days": signal_days,
        "open_count": int_or_zero(decision.get("open_count")),
        "close_count": int_or_zero(decision.get("close_count")),
        "risk_block_ratio": str(decision.get("risk_block_ratio", "0")),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def classify_rescue_mode(reason: str, pnl_r: Decimal, drawdown: Decimal, risk_block_ratio: Decimal) -> str:
    if risk_block_ratio >= Decimal("0.5"):
        return "resize_or_risk_gate_variant"
    if pnl_r <= Decimal("-2") or "net_pnl_below_minus_2r" in reason:
        return "entry_quality_and_filter_variant"
    if drawdown > Decimal("3"):
        return "drawdown_control_variant"
    if "ten_day_losing" in reason:
        return "expectancy_repair_variant"
    return "parameter_rescue_variant"


def build_optimization_hypothesis(
    reason: str,
    pnl_r: Decimal,
    drawdown: Decimal,
    risk_block_ratio: Decimal,
    signal_days: int,
) -> str:
    if risk_block_ratio >= Decimal("0.5"):
        return "Risk blocks dominate generated signals; test smaller sizing, wider quality stops, or stricter exposure allocation before changing setup logic."
    if drawdown > Decimal("3") and pnl_r > Decimal("0"):
        return "Positive PnL with unacceptable drawdown; test volatility regime filter, lower per-trade risk, and trailing stop/target cleanup."
    if pnl_r <= Decimal("-2"):
        return "Negative expectancy crossed the circuit threshold; test stronger trend/context filter, news/event veto, and lower-frequency entry confirmation."
    if signal_days == 0:
        return "No signal coverage; detector thresholds or universe/timeframe mapping likely need redesign."
    if "ten_day_losing" in reason:
        return "Loss is not catastrophic but expectancy is weak; test parameter grid on entry confirmation, stop distance, and profit-taking."
    return "Run a small A/B variant with one changed parameter family only, then compare against the frozen baseline."


def latest_by_strategy(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        strategy_id = str(row.get("strategy_id", ""))
        if strategy_id:
            latest[strategy_id] = row
    return latest


def build_plain_language_result(approved_ids: list[str], rows: list[dict[str, Any]]) -> str:
    rescue = [row["strategy_id"] for row in rows if row["lane"] == "rescue_candidate"]
    rebuild = [row["strategy_id"] for row in rows if row["lane"] == "detector_rebuild"]
    return (
        f"{len(approved_ids)} strategies can continue into internal simulated trading: {', '.join(approved_ids) or 'none'}. "
        f"{len(rescue)} strategies need rescue variants: {', '.join(rescue) or 'none'}. "
        f"{len(rebuild)} strategies need detector rebuild before abandonment: {', '.join(rebuild) or 'none'}."
    )


def build_rescue_plan_md(plan: dict[str, Any]) -> str:
    lines = [
        "# M14 Strategy Rescue Plan",
        "",
        f"- Generated at: `{plan['generated_at']}`",
        f"- Challenge progress: `{plan['challenge_progress_label']}`",
        f"- Approved internal sim: `{', '.join(plan['approved_internal_sim_strategy_ids']) or 'none'}`",
        f"- Boundary: internal simulated only; no broker connection, no real orders, no live execution.",
        "",
        "## Summary",
        "",
        plan["plain_language_result"],
        "",
        "## External References",
        "",
    ]
    for ref in plan["external_references"]:
        lines.append(f"- `{ref['project']}`: {ref['url']} - {ref['usable_pattern']} Boundary: {ref['boundary']}")
    lines.extend(["", "## Strategy Rows", ""])
    for row in plan["rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Decision: `{row['decision']}` / `{row['decision_reason']}`",
                f"- Gate: `{row['paper_trial_gate']}`",
                f"- Lane: `{row['lane']}`",
                f"- Rescue mode: `{row['rescue_mode']}`",
                f"- Next variant: `{row['next_variant_id'] or 'n/a'}`",
                f"- Result: PnL `{row['realized_pnl']}`, R `{row['net_pnl_r']}`, drawdown `{row['max_drawdown_percent']}%`",
                f"- Next action: {row['next_action']}",
                f"- Hypothesis: {row['optimization_hypothesis']}",
                "",
            ]
        )
    return "\n".join(lines)


def int_or_zero(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def decimal_or_zero(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def project_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
