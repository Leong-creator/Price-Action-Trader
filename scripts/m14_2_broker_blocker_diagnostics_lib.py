#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_2_broker_blocker_diagnostics.json"
MONEY = Decimal("0.01")
QTY = Decimal("0.0001")
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class BrokerBlockerDiagnosticsConfig:
    stage: str
    broker_readiness_path: Path
    challenge_config_path: Path
    diagnostics_json_path: Path
    diagnostics_md_path: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> BrokerBlockerDiagnosticsConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = BrokerBlockerDiagnosticsConfig(
        stage=str(payload["stage"]),
        broker_readiness_path=resolve_repo_path(inputs["m14_2_broker_readiness_plan"]),
        challenge_config_path=resolve_repo_path(inputs["m14_strategy_challenge_config"]),
        diagnostics_json_path=resolve_repo_path(outputs["diagnostics_json"]),
        diagnostics_md_path=resolve_repo_path(outputs["diagnostics_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: BrokerBlockerDiagnosticsConfig) -> None:
    if config.stage != "M14.2.broker_blocker_diagnostics":
        raise ValueError("M14.2 broker blocker diagnostics stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14.2 broker blocker diagnostics must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14.2 broker blocker diagnostics cannot enable {key}")


def run_broker_blocker_diagnostics(
    config: BrokerBlockerDiagnosticsConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    broker_readiness = read_json(config.broker_readiness_path)
    challenge_config = read_json(config.challenge_config_path)
    internal_paper = challenge_config.get("internal_paper", {})
    limits = {
        "max_risk_per_order": decimal(internal_paper.get("max_risk_per_order", "0")),
        "max_total_exposure": decimal(internal_paper.get("max_total_exposure", "0")),
        "max_consecutive_losses": int_or_zero(internal_paper.get("max_consecutive_losses")),
    }
    ledger_rows = read_jsonl(resolve_repo_path(broker_readiness.get("internal_paper_execution_ledger_ref", "")))
    ledger_by_event_id = {str(row.get("execution_event_id", "")): row for row in ledger_rows}
    blocked_rows = [
        dict(row)
        for row in broker_readiness.get("rows", [])
        if str(row.get("readiness_status", "")) == "blocked"
    ]
    diagnostics_rows = [
        build_diagnostic_row(row, ledger_by_event_id.get(str(row.get("source_execution_event_id", "")), {}), limits)
        for row in blocked_rows
    ]
    diagnostics_rows.sort(key=lambda row: (row["strategy_id"], row["runtime_id"], row["signal_id"]))
    strategy_summaries = build_strategy_summaries(diagnostics_rows)
    reason_counts = Counter()
    family_counts = Counter()
    for row in diagnostics_rows:
        reason_counts.update(row["reason_codes"])
        family_counts[row["diagnostic_family"]] += 1

    summary = {
        "source_readiness_rows": len(broker_readiness.get("rows", [])),
        "blocked_count": len(diagnostics_rows),
        "blocked_strategy_count": len(strategy_summaries),
        "reason_counts": dict(sorted(reason_counts.items())),
        "diagnostic_family_counts": dict(sorted(family_counts.items())),
        "sizing_repair_candidate_count": family_counts.get("quantity_cap_stop_geometry", 0),
        "exposure_ranking_candidate_count": family_counts.get("portfolio_exposure_ranking", 0),
        "cooldown_candidate_count": family_counts.get("loss_streak_cooldown_quality_veto", 0),
    }
    payload = {
        "schema_version": "m14.2.broker-blocker-diagnostics.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m14_2_broker_readiness_plan": project_path(config.broker_readiness_path),
            "m14_strategy_challenge_config": project_path(config.challenge_config_path),
            "m14_internal_paper_execution_ledger": str(broker_readiness.get("internal_paper_execution_ledger_ref", "")),
        },
        "internal_paper_limits": {
            "max_risk_per_order": fmt_decimal(limits["max_risk_per_order"]),
            "max_total_exposure": fmt_decimal(limits["max_total_exposure"]),
            "max_consecutive_losses": limits["max_consecutive_losses"],
        },
        "summary": summary,
        "rows": diagnostics_rows,
        "strategy_summaries": strategy_summaries,
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
        },
        "paper_or_live_approval": False,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    payload["plain_language_result"] = build_plain_language_result(payload)
    write_json(config.diagnostics_json_path, payload)
    config.diagnostics_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.diagnostics_md_path.write_text(build_diagnostics_md(payload), encoding="utf-8")
    return payload


def build_diagnostic_row(
    broker_row: dict[str, Any],
    source_row: dict[str, Any],
    limits: dict[str, Decimal | int],
) -> dict[str, Any]:
    entry = decimal(source_row.get("entry_price") or broker_row.get("limit_price") or "0")
    stop = decimal(source_row.get("stop_price") or broker_row.get("stop_price") or "0")
    target = decimal(source_row.get("target_price") or broker_row.get("target_price") or "0")
    quantity = decimal(source_row.get("quantity") or broker_row.get("quantity") or "0")
    risk_per_share = abs(entry - stop)
    reward_per_share = abs(target - entry)
    source_risk_amount = risk_per_share * quantity
    notional_exposure = abs(entry * quantity)
    max_risk = Decimal(str(limits["max_risk_per_order"]))
    max_total_exposure = Decimal(str(limits["max_total_exposure"]))
    quantity_cap = safe_div(max_risk, risk_per_share).quantize(QTY, rounding=ROUND_DOWN) if risk_per_share > 0 else ZERO
    quantity_delta = max(ZERO, quantity - quantity_cap)
    risk_excess = max(ZERO, source_risk_amount - max_risk)
    exposure_headroom_ratio = safe_div(max_total_exposure - notional_exposure, max_total_exposure)
    reason_codes = reason_codes_for(broker_row)
    diagnostic_family, next_action = classify_blocker(reason_codes)
    return {
        "row_id": f"m14-2-broker-blocker-{slug(str(broker_row.get('signal_id', '')))}",
        "strategy_id": str(broker_row.get("strategy_id", "")),
        "runtime_id": str(broker_row.get("runtime_id", "")),
        "signal_id": str(broker_row.get("signal_id", "")),
        "source_execution_event_id": str(broker_row.get("source_execution_event_id", "")),
        "trading_date": str(broker_row.get("trading_date", "")),
        "symbol": str(broker_row.get("symbol", "")),
        "timeframe": str(broker_row.get("timeframe", "")),
        "direction": str(broker_row.get("direction", "")),
        "risk_outcome": str(broker_row.get("risk_outcome", "")),
        "reason_codes": reason_codes,
        "diagnostic_family": diagnostic_family,
        "entry_price": fmt_decimal(entry),
        "stop_price": fmt_decimal(stop),
        "target_price": fmt_decimal(target),
        "source_quantity": fmt_decimal(quantity),
        "risk_per_share": fmt_decimal(risk_per_share),
        "reward_per_share": fmt_decimal(reward_per_share),
        "reward_r": fmt_decimal(safe_div(reward_per_share, risk_per_share)),
        "source_risk_amount": fmt_money(source_risk_amount),
        "source_notional_exposure": fmt_money(notional_exposure),
        "max_risk_per_order": fmt_decimal(max_risk),
        "max_total_exposure": fmt_decimal(max_total_exposure),
        "risk_excess_amount": fmt_money(risk_excess),
        "risk_excess_ratio": fmt_decimal(safe_div(risk_excess, max_risk)),
        "quantity_cap_for_risk_limit": fmt_decimal(quantity_cap),
        "quantity_delta_to_risk_cap": fmt_decimal(quantity_delta),
        "exposure_headroom_ratio_after_this_signal_only": fmt_decimal(exposure_headroom_ratio),
        "preview_blocked": True,
        "recommended_shadow_fix": recommended_shadow_fix(diagnostic_family),
        "next_action": next_action,
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def classify_blocker(reason_codes: list[str]) -> tuple[str, str]:
    reasons = set(reason_codes)
    if "max_risk_per_order_exceeded" in reasons:
        return (
            "quantity_cap_stop_geometry",
            "Shadow-test a quantity cap to the existing max risk per order; do not raise the risk limit or change broker readiness status.",
        )
    if "consecutive_losses_limit" in reasons:
        return (
            "loss_streak_cooldown_quality_veto",
            "Keep the loss-streak halt active and test a same-session cooldown or quality veto before allowing more simulated entries.",
        )
    if "max_total_exposure_exceeded" in reasons:
        return (
            "portfolio_exposure_ranking",
            "Shadow-test exposure allocation and signal ranking so lower-priority entries defer instead of increasing total exposure.",
        )
    return (
        "risk_reason_review",
        "Review the source risk reason codes and keep this row blocked until a simulated-only repair is proven.",
    )


def recommended_shadow_fix(diagnostic_family: str) -> str:
    if diagnostic_family == "quantity_cap_stop_geometry":
        return "risk_budget_quantity_cap_without_setup_change"
    if diagnostic_family == "loss_streak_cooldown_quality_veto":
        return "post_loss_cooldown_and_quality_veto_shadow"
    if diagnostic_family == "portfolio_exposure_ranking":
        return "portfolio_exposure_ranker_shadow"
    return "manual_risk_reason_audit"


def build_strategy_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_strategy[row["strategy_id"]].append(row)
    summaries: list[dict[str, Any]] = []
    for strategy_id, strategy_rows in sorted(by_strategy.items()):
        reason_counts = Counter()
        family_counts = Counter()
        symbols: set[str] = set()
        for row in strategy_rows:
            reason_counts.update(row["reason_codes"])
            family_counts[row["diagnostic_family"]] += 1
            if row["symbol"]:
                symbols.add(row["symbol"])
        summaries.append(
            {
                "strategy_id": strategy_id,
                "blocked_count": len(strategy_rows),
                "symbols": sorted(symbols),
                "reason_counts": dict(sorted(reason_counts.items())),
                "diagnostic_family_counts": dict(sorted(family_counts.items())),
                "priority": "P0" if any(row["diagnostic_family"] != "risk_reason_review" for row in strategy_rows) else "P1",
                "recommended_next_action": strategy_next_action(strategy_id, set(family_counts)),
                "paper_simulated_only": True,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
            }
        )
    return summaries


def strategy_next_action(strategy_id: str, families: set[str]) -> str:
    if "loss_streak_cooldown_quality_veto" in families:
        return f"{strategy_id}: keep the loss-streak guard and shadow-test cooldown/quality veto before more simulated entries."
    if "portfolio_exposure_ranking" in families:
        return f"{strategy_id}: add simulated-only exposure ranking so lower-priority entries defer under the existing cap."
    if "quantity_cap_stop_geometry" in families:
        return f"{strategy_id}: shadow-test quantity capping to max_risk_per_order before any broker-paper review."
    return f"{strategy_id}: keep blocked and audit risk reason attribution."


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"M14.2 broker blocker diagnostics found {summary['blocked_count']} blocked dry-run rows across "
        f"{summary['blocked_strategy_count']} strategies. "
        f"Sizing candidates: {summary['sizing_repair_candidate_count']}; "
        f"exposure ranking candidates: {summary['exposure_ranking_candidate_count']}; "
        f"cooldown candidates: {summary['cooldown_candidate_count']}. "
        "Rows stay blocked; no broker connection, real order, live execution, or paper-trading approval is enabled."
    )


def build_diagnostics_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    limits = payload["internal_paper_limits"]
    lines = [
        "# M14.2 Broker Blocker Diagnostics",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Blocked dry-run rows: `{summary['blocked_count']}`",
        f"- Blocked strategies: `{summary['blocked_strategy_count']}`",
        f"- Reason counts: `{summary['reason_counts']}`",
        f"- Diagnostic families: `{summary['diagnostic_family_counts']}`",
        f"- Internal simulated risk cap: `{limits['max_risk_per_order']}` per order; total exposure cap `{limits['max_total_exposure']}`; max consecutive losses `{limits['max_consecutive_losses']}`",
        "- Boundary: diagnostics only; rows remain blocked; no broker connection, no real orders, no live execution.",
        "",
        "## Strategy Actions",
        "",
    ]
    for row in payload["strategy_summaries"]:
        lines.extend(
            [
                f"### {row['strategy_id']}",
                "",
                f"- Blocked rows: `{row['blocked_count']}`",
                f"- Symbols: `{', '.join(row['symbols'])}`",
                f"- Reasons: `{row['reason_counts']}`",
                f"- Diagnostic families: `{row['diagnostic_family_counts']}`",
                f"- Next action: {row['recommended_next_action']}",
                "",
            ]
        )
    lines.extend(["## Blocked Rows", ""])
    for row in payload["rows"]:
        lines.extend(
            [
                f"### {row['strategy_id']} / {row['symbol']} / {row['timeframe']}",
                "",
                f"- Reason codes: `{row['reason_codes']}`",
                f"- Family: `{row['diagnostic_family']}`",
                f"- Entry/stop/target: `{row['entry_price']} / {row['stop_price']} / {row['target_price']}`",
                f"- Quantity/risk/notional: `{row['source_quantity']} / {row['source_risk_amount']} / {row['source_notional_exposure']}`",
                f"- Reward R: `{row['reward_r']}`",
                f"- Risk cap candidate quantity: `{row['quantity_cap_for_risk_limit']}`; delta `{row['quantity_delta_to_risk_cap']}`",
                f"- Shadow fix: `{row['recommended_shadow_fix']}`",
                f"- Action: {row['next_action']}",
                "",
            ]
        )
    lines.extend(["## Summary", "", payload["plain_language_result"], ""])
    return "\n".join(lines)


def reason_codes_for(row: dict[str, Any]) -> list[str]:
    source_reasons = row.get("source_risk_reason_codes")
    if isinstance(source_reasons, list) and source_reasons:
        return [str(item) for item in source_reasons]
    reasons = row.get("reason_codes")
    if isinstance(reasons, list) and reasons:
        return [str(item) for item in reasons]
    return [str(row.get("risk_outcome", "blocked"))]


def safe_div(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return ZERO
    return numerator / denominator


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def fmt_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text == "-0" else text


def fmt_money(value: Decimal) -> str:
    return fmt_decimal(value.quantize(MONEY))


def slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
