#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_zero_signal_diagnostics.json"
ZERO = Decimal("0")
HUNDRED = Decimal("100")
FRESH_QUOTE_SOURCE = "longbridge_quote_readonly"
LEVERAGED_ETFS = frozenset({"TQQQ", "SQQQ"})


@dataclass(frozen=True, slots=True)
class RescueZeroSignalDiagnosticsConfig:
    stage: str
    dashboard_data_path: Path
    rescue_coverage_path: Path
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


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueZeroSignalDiagnosticsConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueZeroSignalDiagnosticsConfig(
        stage=str(payload["stage"]),
        dashboard_data_path=resolve_repo_path(inputs["m12_dashboard_data"]),
        rescue_coverage_path=resolve_repo_path(inputs["m14_rescue_runtime_coverage"]),
        diagnostics_json_path=resolve_repo_path(outputs["diagnostics_json"]),
        diagnostics_md_path=resolve_repo_path(outputs["diagnostics_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueZeroSignalDiagnosticsConfig) -> None:
    if config.stage != "M14.rescue_zero_signal_diagnostics":
        raise ValueError("M14 rescue zero-signal diagnostics stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue zero-signal diagnostics must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue zero-signal diagnostics cannot enable {key}")


def run_m14_rescue_zero_signal_diagnostics(
    config: RescueZeroSignalDiagnosticsConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    dashboard_data = read_json(config.dashboard_data_path)
    rescue_coverage = read_json(config.rescue_coverage_path)

    signal_watchlist = [dict(row) for row in dashboard_data.get("signal_watchlist", [])]
    audit_rows = [dict(row) for row in dashboard_data.get("account_input_audit", {}).get("rows", [])]
    coverage_by_runtime = {
        str(runtime_id): dict(row)
        for row in rescue_coverage.get("rows", [])
        for runtime_id in row.get("runtime_ids", [])
    }

    diagnostic_rows = [
        build_diagnostic_row(
            audit_row=row,
            coverage_row=coverage_by_runtime.get(str(row.get("runtime_id", "")), {}),
            signal_watchlist=signal_watchlist,
        )
        for row in audit_rows
        if str(row.get("lane", "")) == "rescue"
        and str(row.get("input_status", "")) == "connected_zero_signal_today"
    ]
    diagnostic_rows.sort(key=lambda row: (row["dominant_issue"], row["runtime_id"]))

    dominant_issue_counts = Counter(row["dominant_issue"] for row in diagnostic_rows)
    rejection_counts = Counter()
    for row in diagnostic_rows:
        rejection_counts.update(row["rejection_reason_counts"])

    summary = {
        "zero_signal_runtime_count": len(diagnostic_rows),
        "zero_signal_strategy_count": len({row["strategy_id"] for row in diagnostic_rows}),
        "parent_source_available_runtime_count": sum(1 for row in diagnostic_rows if row["parent_source_row_count"] > 0),
        "parent_source_absent_runtime_count": dominant_issue_counts.get("parent_source_absent_for_timeframe", 0),
        "quote_refresh_candidate_runtime_count": dominant_issue_counts.get("stale_quote_source_blocks_candidate", 0),
        "quality_filter_blocked_runtime_count": sum(
            count
            for issue, count in dominant_issue_counts.items()
            if issue in {"reward_filter_blocks_all", "strict_quality_filter_blocks_all"}
        ),
        "potential_signal_if_fresh_quote_count": sum(row["eligible_if_fresh_quote_count"] for row in diagnostic_rows),
        "filter_pass_count": sum(row["filter_pass_count"] for row in diagnostic_rows),
        "dominant_issue_counts": dict(sorted(dominant_issue_counts.items())),
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-zero-signal-diagnostics.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m12_dashboard_data": project_path(config.dashboard_data_path),
            "m14_rescue_runtime_coverage": project_path(config.rescue_coverage_path),
        },
        "summary": summary,
        "rows": diagnostic_rows,
        "hard_boundaries": {
            "paper_simulated_only": True,
            "broker_connection": False,
            "real_order": False,
            "live_execution": False,
            "paper_trading_approval": False,
        },
        "paper_simulated_only": True,
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
    *,
    audit_row: dict[str, Any],
    coverage_row: dict[str, Any],
    signal_watchlist: list[dict[str, Any]],
) -> dict[str, Any]:
    strategy_id = str(audit_row.get("strategy_id", ""))
    runtime_id = str(audit_row.get("runtime_id", ""))
    timeframe = str(audit_row.get("timeframe", ""))
    parent_strategy_id = str(coverage_row.get("parent_strategy_id", ""))
    source_rows = [
        row
        for row in signal_watchlist
        if str(row.get("strategy_id", "")) == parent_strategy_id
        and str(row.get("timeframe", "")) == timeframe
    ]

    rejection_counts: Counter[str] = Counter()
    quote_source_counts: Counter[str] = Counter()
    direction_counts: Counter[str] = Counter()
    filter_pass_count = 0
    eligible_if_fresh_quote_count = 0
    for row in source_rows:
        quote_source_counts.update([str(row.get("latest_price_source", "")) or "missing"])
        direction_counts.update([str(row.get("direction", "")) or "missing"])
        reasons = rescue_filter_rejection_reasons(row, strategy_id, timeframe)
        if reasons:
            rejection_counts.update(reasons)
        else:
            filter_pass_count += 1
        if not [reason for reason in reasons if reason != "stale_quote_source"]:
            eligible_if_fresh_quote_count += 1

    dominant_issue = classify_dominant_issue(
        source_row_count=len(source_rows),
        filter_pass_count=filter_pass_count,
        eligible_if_fresh_quote_count=eligible_if_fresh_quote_count,
        rejection_counts=rejection_counts,
    )
    return {
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "parent_strategy_id": parent_strategy_id,
        "timeframe": timeframe,
        "input_source_type": str(audit_row.get("input_source_type", "")),
        "dominant_issue": dominant_issue,
        "recommended_action": recommended_action(dominant_issue),
        "parent_source_row_count": len(source_rows),
        "filter_pass_count": filter_pass_count,
        "eligible_if_fresh_quote_count": eligible_if_fresh_quote_count,
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "source_quote_source_counts": dict(sorted(quote_source_counts.items())),
        "source_direction_counts": dict(sorted(direction_counts.items())),
        "sample_symbols": sorted({str(row.get("symbol", "")) for row in source_rows if row.get("symbol")})[:8],
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def rescue_filter_rejection_reasons(row: dict[str, Any], strategy_id: str, timeframe: str) -> list[str]:
    reasons: list[str] = []
    if str(row.get("symbol", "")) in LEVERAGED_ETFS:
        reasons.append("leveraged_etf_excluded")
    if str(row.get("direction", "")) != "看涨":
        reasons.append("direction_not_long")
    entry = decimal_or_none(row.get("hypothetical_entry_price", ""))
    stop = decimal_or_none(row.get("hypothetical_stop_price", ""))
    target = decimal_or_none(row.get("hypothetical_target_price", ""))
    if entry is None or stop is None or target is None or entry <= ZERO or stop <= ZERO or target <= ZERO:
        reasons.append("invalid_prices")
    else:
        risk = abs(entry - stop)
        reward = abs(target - entry)
        min_reward_r = Decimal("1.50") if strategy_id == "M10-PA-004-MBF-QC-m14-modify-20260522" else Decimal("1.20")
        if risk <= ZERO or reward <= ZERO:
            reasons.append("invalid_risk_reward")
        elif reward < risk * min_reward_r:
            reasons.append("reward_r_below_min")
        max_risk_percent = Decimal("4.00") if strategy_id == "M10-PA-004-MBF-QC-m14-modify-20260522" else Decimal("6.00") if timeframe == "1d" else Decimal("2.50")
        if risk > ZERO and entry > ZERO and risk / entry * HUNDRED > max_risk_percent:
            reasons.append("risk_percent_above_limit")
    if row.get("signal_date") and str(row.get("latest_price_source", "")) != FRESH_QUOTE_SOURCE:
        reasons.append("stale_quote_source")
    return reasons


def classify_dominant_issue(
    *,
    source_row_count: int,
    filter_pass_count: int,
    eligible_if_fresh_quote_count: int,
    rejection_counts: Counter[str],
) -> str:
    if source_row_count == 0:
        return "parent_source_absent_for_timeframe"
    if filter_pass_count > 0:
        return "account_audit_mismatch"
    if eligible_if_fresh_quote_count > 0:
        return "stale_quote_source_blocks_candidate"
    if rejection_counts.get("reward_r_below_min", 0) >= source_row_count:
        return "reward_filter_blocks_all"
    return "strict_quality_filter_blocks_all"


def recommended_action(dominant_issue: str) -> str:
    if dominant_issue == "parent_source_absent_for_timeframe":
        return "Fix parent detector/timeframe source mapping before waiting for more A/B days."
    if dominant_issue == "stale_quote_source_blocks_candidate":
        return "Wait for the next M12.47-owned fresh Longbridge quote refresh before changing rescue parameters."
    if dominant_issue == "reward_filter_blocks_all":
        return "Test a shadow-only reward/R normalization family, such as 1.0R or 1.1R minimum, before changing the frozen rescue runtime."
    if dominant_issue == "account_audit_mismatch":
        return "Audit account_input_audit generation because filtered rows appear to pass but the runtime stayed zero-signal."
    return "Inspect direction, risk-percent, leveraged ETF, and price-validity gates; change only one parameter family at a time in shadow."


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Zero-signal rescue diagnostics reviewed {summary['zero_signal_runtime_count']} rescue runtimes. "
        f"{summary['quote_refresh_candidate_runtime_count']} are blocked mainly by stale/non-fresh quote source and should be rechecked on the next M12.47 fresh refresh; "
        f"{summary['quality_filter_blocked_runtime_count']} need parameter/filter work; "
        f"{summary['parent_source_absent_runtime_count']} have no parent source rows for the configured timeframe. "
        f"Potential entries if fresh quote gate clears: {summary['potential_signal_if_fresh_quote_count']}. "
        "No broker connection, real order, live execution, or paper-trading approval is enabled."
    )


def build_diagnostics_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue Zero-Signal Diagnostics",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Zero-signal rescue runtimes: `{summary['zero_signal_runtime_count']}`",
        f"- Parent source available: `{summary['parent_source_available_runtime_count']}`",
        f"- Quote-refresh candidates: `{summary['quote_refresh_candidate_runtime_count']}`",
        f"- Quality/filter blocked: `{summary['quality_filter_blocked_runtime_count']}`",
        f"- Parent source absent: `{summary['parent_source_absent_runtime_count']}`",
        f"- Potential entries if fresh quote gate clears: `{summary['potential_signal_if_fresh_quote_count']}`",
        "- Boundary: internal simulated only; no broker connection, no real orders, no live execution.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Runtime Diagnostics",
        "",
    ]
    for row in payload["rows"]:
        lines.extend(
            [
                f"### {row['runtime_id']}",
                "",
                f"- Parent/timeframe: `{row['parent_strategy_id']} / {row['timeframe']}`",
                f"- Dominant issue: `{row['dominant_issue']}`",
                f"- Parent source rows: `{row['parent_source_row_count']}`",
                f"- Eligible if fresh quote: `{row['eligible_if_fresh_quote_count']}`",
                f"- Rejection reasons: `{row['rejection_reason_counts']}`",
                f"- Quote sources: `{row['source_quote_source_counts']}`",
                f"- Sample symbols: `{', '.join(row['sample_symbols']) or 'none'}`",
                f"- Action: {row['recommended_action']}",
                "",
            ]
        )
    lines.extend(["## Summary", "", f"- Dominant issues: `{summary['dominant_issue_counts']}`", f"- Rejection reasons: `{summary['rejection_reason_counts']}`", ""])
    return "\n".join(lines)


def decimal_or_none(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
