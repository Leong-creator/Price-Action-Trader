#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_2_broker_blocker_shadow_repair.json"
MONEY = Decimal("0.01")
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class BrokerBlockerShadowRepairConfig:
    stage: str
    diagnostics_path: Path
    shadow_repair_json_path: Path
    shadow_repair_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> BrokerBlockerShadowRepairConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = BrokerBlockerShadowRepairConfig(
        stage=str(payload["stage"]),
        diagnostics_path=resolve_repo_path(inputs["broker_blocker_diagnostics"]),
        shadow_repair_json_path=resolve_repo_path(outputs["shadow_repair_json"]),
        shadow_repair_md_path=resolve_repo_path(outputs["shadow_repair_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: BrokerBlockerShadowRepairConfig) -> None:
    if config.stage != "M14.2.broker_blocker_shadow_repair":
        raise ValueError("M14.2 broker blocker shadow repair stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14.2 broker blocker shadow repair must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14.2 broker blocker shadow repair cannot enable {key}")


def run_broker_blocker_shadow_repair(
    config: BrokerBlockerShadowRepairConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    diagnostics = read_json(config.diagnostics_path)
    rows = [build_shadow_repair_row(dict(row)) for row in diagnostics.get("rows", [])]
    rows.sort(key=lambda row: (row["strategy_id"], row["runtime_id"], row["symbol"], row["signal_id"]))
    strategy_summaries = build_strategy_summaries(rows)
    action_counts = Counter(row["shadow_action"] for row in rows)
    status_counts = Counter(row["shadow_repair_status"] for row in rows)
    summary = {
        "source_blocked_rows": len(rows),
        "shadow_rows": len(rows),
        "strategy_count": len(strategy_summaries),
        "shadow_action_counts": dict(sorted(action_counts.items())),
        "shadow_status_counts": dict(sorted(status_counts.items())),
        "risk_cap_candidate_count": action_counts.get("apply_quantity_cap", 0),
        "defer_for_exposure_count": action_counts.get("defer_until_exposure_frees", 0),
        "cooldown_defer_count": action_counts.get("keep_loss_streak_halt", 0),
        "would_change_original_readiness_count": 0,
        "broker_or_live_enabled": False,
    }
    payload = {
        "schema_version": "m14.2.broker-blocker-shadow-repair.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "broker_blocker_diagnostics": project_path(config.diagnostics_path),
            "source_broker_readiness_plan": diagnostics.get("input_refs", {}).get("m14_2_broker_readiness_plan", ""),
        },
        "summary": summary,
        "rows": rows,
        "strategy_summaries": strategy_summaries,
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
        },
        "readiness_status_mutation": False,
        "paper_or_live_approval": False,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.shadow_repair_json_path, payload)
    config.shadow_repair_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.shadow_repair_md_path.write_text(build_shadow_repair_md(payload), encoding="utf-8")
    return payload


def build_shadow_repair_row(row: dict[str, Any]) -> dict[str, Any]:
    family = str(row.get("diagnostic_family", ""))
    source_quantity = decimal(row.get("source_quantity", "0"))
    risk_per_share = decimal(row.get("risk_per_share", "0"))
    quantity_cap = decimal(row.get("quantity_cap_for_risk_limit", "0"))
    source_risk_amount = decimal(row.get("source_risk_amount", "0"))
    source_notional = decimal(row.get("source_notional_exposure", "0"))
    if family == "quantity_cap_stop_geometry" and quantity_cap > 0 and quantity_cap < source_quantity:
        proposed_quantity = quantity_cap
        proposed_risk = risk_per_share * proposed_quantity
        return base_shadow_row(
            row,
            shadow_action="apply_quantity_cap",
            shadow_repair_status="shadow_repair_candidate",
            proposed_quantity=proposed_quantity,
            proposed_risk_amount=proposed_risk,
            proposed_notional_exposure=safe_notional(row, proposed_quantity),
            expected_blocker_reduction=("max_risk_per_order_exceeded",),
            next_action="Run a simulated-only quantity-cap A/B row; keep the original dry-run row blocked until fresh ledger evidence confirms the cap.",
        )
    if family == "portfolio_exposure_ranking":
        return base_shadow_row(
            row,
            shadow_action="defer_until_exposure_frees",
            shadow_repair_status="defer_not_repair",
            proposed_quantity=ZERO,
            proposed_risk_amount=ZERO,
            proposed_notional_exposure=ZERO,
            expected_blocker_reduction=("max_total_exposure_exceeded",),
            next_action="Do not force this entry through; shadow-test ranking so this signal waits for exposure headroom or loses to higher-ranked signals.",
        )
    if family == "loss_streak_cooldown_quality_veto":
        return base_shadow_row(
            row,
            shadow_action="keep_loss_streak_halt",
            shadow_repair_status="defer_not_repair",
            proposed_quantity=ZERO,
            proposed_risk_amount=ZERO,
            proposed_notional_exposure=ZERO,
            expected_blocker_reduction=("consecutive_losses_limit",),
            next_action="Keep the halt active; shadow-test same-session cooldown and a quality veto before allowing later simulated entries.",
        )
    return base_shadow_row(
        row,
        shadow_action="manual_risk_reason_review",
        shadow_repair_status="manual_review_needed",
        proposed_quantity=ZERO,
        proposed_risk_amount=ZERO,
        proposed_notional_exposure=ZERO,
        expected_blocker_reduction=tuple(row.get("reason_codes", [])),
        next_action="Keep blocked and review risk reason attribution before defining a shadow repair.",
    )


def base_shadow_row(
    row: dict[str, Any],
    *,
    shadow_action: str,
    shadow_repair_status: str,
    proposed_quantity: Decimal,
    proposed_risk_amount: Decimal,
    proposed_notional_exposure: Decimal,
    expected_blocker_reduction: tuple[str, ...],
    next_action: str,
) -> dict[str, Any]:
    source_quantity = decimal(row.get("source_quantity", "0"))
    source_risk_amount = decimal(row.get("source_risk_amount", "0"))
    source_notional = decimal(row.get("source_notional_exposure", "0"))
    return {
        "row_id": str(row.get("row_id", "")),
        "strategy_id": str(row.get("strategy_id", "")),
        "runtime_id": str(row.get("runtime_id", "")),
        "signal_id": str(row.get("signal_id", "")),
        "source_execution_event_id": str(row.get("source_execution_event_id", "")),
        "trading_date": str(row.get("trading_date", "")),
        "symbol": str(row.get("symbol", "")),
        "timeframe": str(row.get("timeframe", "")),
        "direction": str(row.get("direction", "")),
        "original_reason_codes": list(row.get("reason_codes", [])),
        "diagnostic_family": str(row.get("diagnostic_family", "")),
        "shadow_action": shadow_action,
        "shadow_repair_status": shadow_repair_status,
        "source_quantity": fmt_decimal(source_quantity),
        "proposed_quantity": fmt_decimal(proposed_quantity),
        "quantity_delta": fmt_decimal(source_quantity - proposed_quantity),
        "source_risk_amount": fmt_money(source_risk_amount),
        "proposed_risk_amount": fmt_money(proposed_risk_amount),
        "risk_amount_delta": fmt_money(source_risk_amount - proposed_risk_amount),
        "source_notional_exposure": fmt_money(source_notional),
        "proposed_notional_exposure": fmt_money(proposed_notional_exposure),
        "notional_exposure_delta": fmt_money(source_notional - proposed_notional_exposure),
        "expected_blocker_reduction": list(expected_blocker_reduction),
        "original_readiness_status_remains_blocked": True,
        "readiness_status_mutation": False,
        "next_action": next_action,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def safe_notional(row: dict[str, Any], quantity: Decimal) -> Decimal:
    entry = decimal(row.get("entry_price", "0"))
    return abs(entry * quantity)


def build_strategy_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_strategy[row["strategy_id"]].append(row)
    summaries: list[dict[str, Any]] = []
    for strategy_id, strategy_rows in sorted(by_strategy.items()):
        action_counts = Counter(row["shadow_action"] for row in strategy_rows)
        status_counts = Counter(row["shadow_repair_status"] for row in strategy_rows)
        symbols = sorted({row["symbol"] for row in strategy_rows if row["symbol"]})
        summaries.append(
            {
                "strategy_id": strategy_id,
                "blocked_rows": len(strategy_rows),
                "symbols": symbols,
                "shadow_action_counts": dict(sorted(action_counts.items())),
                "shadow_status_counts": dict(sorted(status_counts.items())),
                "ready_for_next_ab_step": action_counts.get("apply_quantity_cap", 0) > 0,
                "recommended_next_action": strategy_next_action(strategy_id, set(action_counts)),
                "paper_simulated_only": True,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return summaries


def strategy_next_action(strategy_id: str, actions: set[str]) -> str:
    if "keep_loss_streak_halt" in actions:
        return f"{strategy_id}: do not add entries after the halt; test cooldown and quality veto in the next internal-sim refresh."
    if "defer_until_exposure_frees" in actions:
        return f"{strategy_id}: add an exposure ranker shadow row so lower-ranked signals wait instead of exceeding total exposure."
    if "apply_quantity_cap" in actions:
        return f"{strategy_id}: add a quantity-cap shadow row and require new M13/M14 evidence before any readiness change."
    return f"{strategy_id}: keep blocked and audit risk attribution."


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"M14.2 shadow repair plan prepared {summary['shadow_rows']} blocked-row actions across "
        f"{summary['strategy_count']} strategies: {summary['risk_cap_candidate_count']} quantity-cap candidate, "
        f"{summary['defer_for_exposure_count']} exposure deferral, {summary['cooldown_defer_count']} cooldown halt. "
        "Original broker readiness rows remain blocked; no broker connection, real order, live execution, or paper-trading approval is enabled."
    )


def build_shadow_repair_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14.2 Broker Blocker Shadow Repair Plan",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Source blocked rows: `{summary['source_blocked_rows']}`",
        f"- Shadow actions: `{summary['shadow_action_counts']}`",
        f"- Shadow statuses: `{summary['shadow_status_counts']}`",
        "- Boundary: original readiness rows remain blocked; no broker connection, no real orders, no live execution.",
        "",
        "## Strategy Plan",
        "",
    ]
    for row in payload["strategy_summaries"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Blocked rows: `{row['blocked_rows']}`",
                f"- Symbols: `{', '.join(row['symbols'])}`",
                f"- Shadow actions: `{row['shadow_action_counts']}`",
                f"- Statuses: `{row['shadow_status_counts']}`",
                f"- Next action: {row['recommended_next_action']}",
                "",
            ]
        )
    lines.extend(["## Row Actions", ""])
    for row in payload["rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} / {row['symbol']} / {row['timeframe']}",
                "",
                f"- Original reasons: `{row['original_reason_codes']}`",
                f"- Shadow action: `{row['shadow_action']}`",
                f"- Status: `{row['shadow_repair_status']}`",
                f"- Quantity source/proposed/delta: `{row['source_quantity']} / {row['proposed_quantity']} / {row['quantity_delta']}`",
                f"- Risk source/proposed/delta: `{row['source_risk_amount']} / {row['proposed_risk_amount']} / {row['risk_amount_delta']}`",
                f"- Notional source/proposed/delta: `{row['source_notional_exposure']} / {row['proposed_notional_exposure']} / {row['notional_exposure_delta']}`",
                f"- Original readiness remains blocked: `{row['original_readiness_status_remains_blocked']}`",
                f"- Action: {row['next_action']}",
                "",
            ]
        )
    lines.extend(["## Summary", "", payload["plain_language_result"], ""])
    return "\n".join(lines)


def safe_div(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return ZERO
    return numerator / denominator


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc


def fmt_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text == "-0" else text


def fmt_money(value: Decimal) -> str:
    return fmt_decimal(value.quantize(MONEY))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
