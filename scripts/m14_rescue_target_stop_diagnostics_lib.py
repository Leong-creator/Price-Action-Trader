#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_target_stop_diagnostics.json"
ZERO = Decimal("0")
HUNDRED = Decimal("100")
LEVERAGED_ETFS = frozenset({"TQQQ", "SQQQ"})
REWARD_LEVELS = (Decimal("1.00"), Decimal("1.10"), Decimal("1.20"))


@dataclass(frozen=True, slots=True)
class RescueTargetStopDiagnosticsConfig:
    stage: str
    dashboard_data_path: Path
    zero_signal_diagnostics_path: Path
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


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueTargetStopDiagnosticsConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueTargetStopDiagnosticsConfig(
        stage=str(payload["stage"]),
        dashboard_data_path=resolve_repo_path(inputs["m12_dashboard_data"]),
        zero_signal_diagnostics_path=resolve_repo_path(inputs["m14_rescue_zero_signal_diagnostics"]),
        diagnostics_json_path=resolve_repo_path(outputs["diagnostics_json"]),
        diagnostics_md_path=resolve_repo_path(outputs["diagnostics_md"]),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueTargetStopDiagnosticsConfig) -> None:
    if config.stage != "M14.rescue_target_stop_diagnostics":
        raise ValueError("M14 rescue target/stop diagnostics stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue target/stop diagnostics must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue target/stop diagnostics cannot enable {key}")


def run_m14_rescue_target_stop_diagnostics(
    config: RescueTargetStopDiagnosticsConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    dashboard_data = read_json(config.dashboard_data_path)
    zero_signal_diagnostics = read_json(config.zero_signal_diagnostics_path)
    signal_watchlist = [dict(row) for row in dashboard_data.get("signal_watchlist", [])]

    rows = [
        build_runtime_diagnostic(zero_row, signal_watchlist)
        for zero_row in zero_signal_diagnostics.get("rows", [])
        if target_stop_candidate_zero_row(zero_row)
    ]
    rows.sort(key=lambda row: (row["dominant_target_stop_issue"], row["runtime_id"]))

    issue_counts = Counter(row["dominant_target_stop_issue"] for row in rows)
    summary = {
        "diagnosed_runtime_count": len(rows),
        "target_stop_issue_runtime_count": sum(
            1 for row in rows if row["dominant_target_stop_issue"] != "has_shadow_candidate_after_target_stop_normalization"
        ),
        "shadow_candidate_runtime_count": issue_counts.get("has_shadow_candidate_after_target_stop_normalization", 0),
        "runtime_ids": [row["runtime_id"] for row in rows],
        "strategy_ids": sorted({row["strategy_id"] for row in rows}),
        "parent_strategy_ids": sorted({row["parent_strategy_id"] for row in rows}),
        "dominant_target_stop_issue_counts": dict(sorted(issue_counts.items())),
        "reward_ge_1_0_runtime_count": sum(1 for row in rows if row["reward_ge_1_0_count"] > 0),
        "reward_ge_1_1_runtime_count": sum(1 for row in rows if row["reward_ge_1_1_count"] > 0),
        "reward_ge_1_2_runtime_count": sum(1 for row in rows if row["reward_ge_1_2_count"] > 0),
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-target-stop-diagnostics.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m12_dashboard_data": project_path(config.dashboard_data_path),
            "m14_rescue_zero_signal_diagnostics": project_path(config.zero_signal_diagnostics_path),
        },
        "summary": summary,
        "rows": rows,
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


def target_stop_candidate_zero_row(row: dict[str, Any]) -> bool:
    dominant_issue = str(row.get("dominant_issue", ""))
    rejection_counts = row.get("rejection_reason_counts", {})
    if dominant_issue == "reward_filter_blocks_all":
        return True
    if int_or_zero(rejection_counts.get("reward_r_below_min")) > 0:
        return True
    return False


def build_runtime_diagnostic(zero_row: dict[str, Any], signal_watchlist: list[dict[str, Any]]) -> dict[str, Any]:
    runtime_id = str(zero_row.get("runtime_id", ""))
    strategy_id = str(zero_row.get("strategy_id", ""))
    parent_strategy_id = str(zero_row.get("parent_strategy_id", ""))
    timeframe = str(zero_row.get("timeframe", ""))
    source_rows = [
        row
        for row in signal_watchlist
        if str(row.get("strategy_id", "")) == parent_strategy_id
        and str(row.get("timeframe", "")) == timeframe
    ]
    evaluated = [evaluate_source_row(row, strategy_id=strategy_id, timeframe=timeframe) for row in source_rows]
    valid_rows = [row for row in evaluated if row["valid_price_geometry"]]
    bullish_rows = [row for row in valid_rows if row["direction_gate_pass"]]
    non_leveraged_bullish = [row for row in bullish_rows if not row["leveraged_etf_excluded"]]
    risk_pass_rows = [row for row in non_leveraged_bullish if row["risk_gate_pass"]]
    reward_values = [Decimal(str(row["reward_r"])) for row in risk_pass_rows if row["reward_r"] is not None]

    reward_pass_counts = {
        f"{reward_level:.1f}R": sum(1 for row in risk_pass_rows if row["reward_r"] is not None and Decimal(str(row["reward_r"])) >= reward_level)
        for reward_level in REWARD_LEVELS
    }
    issue = classify_target_stop_issue(
        source_row_count=len(source_rows),
        valid_price_count=len(valid_rows),
        non_leveraged_bullish_valid_count=len(non_leveraged_bullish),
        risk_gate_pass_count=len(risk_pass_rows),
        reward_ge_1_0_count=reward_pass_counts["1.0R"],
    )
    row_payload = {
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "parent_strategy_id": parent_strategy_id,
        "timeframe": timeframe,
        "source_zero_signal_issue": str(zero_row.get("dominant_issue", "")),
        "source_row_count": len(source_rows),
        "valid_price_geometry_count": len(valid_rows),
        "bullish_source_row_count": len(bullish_rows),
        "non_leveraged_bullish_valid_count": len(non_leveraged_bullish),
        "risk_gate_pass_count": len(risk_pass_rows),
        "reward_ge_1_0_count": reward_pass_counts["1.0R"],
        "reward_ge_1_1_count": reward_pass_counts["1.1R"],
        "reward_ge_1_2_count": reward_pass_counts["1.2R"],
        "reward_r_min": decimal_to_str(min(reward_values)) if reward_values else None,
        "reward_r_median": decimal_to_str(decimal_median(reward_values)) if reward_values else None,
        "reward_r_max": decimal_to_str(max(reward_values)) if reward_values else None,
        "dominant_target_stop_issue": issue,
        "recommended_action": recommended_action(issue),
        "sample_rows": sample_evaluated_rows(evaluated),
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }
    return row_payload


def evaluate_source_row(row: dict[str, Any], *, strategy_id: str, timeframe: str) -> dict[str, Any]:
    entry = decimal_or_none(row.get("hypothetical_entry_price"))
    stop = decimal_or_none(row.get("hypothetical_stop_price"))
    target = decimal_or_none(row.get("hypothetical_target_price"))
    direction = str(row.get("direction", ""))
    symbol = str(row.get("symbol", ""))
    valid_price_geometry = (
        entry is not None
        and stop is not None
        and target is not None
        and entry > ZERO
        and stop > ZERO
        and target > ZERO
        and abs(entry - stop) > ZERO
        and abs(target - entry) > ZERO
    )
    risk: Decimal | None = None
    reward: Decimal | None = None
    reward_r: Decimal | None = None
    risk_percent: Decimal | None = None
    if valid_price_geometry and entry is not None and stop is not None and target is not None:
        risk = abs(entry - stop)
        reward = abs(target - entry)
        reward_r = reward / risk if risk > ZERO else None
        risk_percent = risk / entry * HUNDRED if entry > ZERO else None
    max_risk_percent = max_risk_percent_for(strategy_id=strategy_id, timeframe=timeframe)
    risk_gate_pass = bool(risk_percent is not None and risk_percent <= max_risk_percent)
    direction_gate_pass = direction == "看涨"
    leveraged_etf_excluded = symbol in LEVERAGED_ETFS
    blockers: list[str] = []
    if not valid_price_geometry:
        blockers.append("missing_or_invalid_price_geometry")
    if leveraged_etf_excluded:
        blockers.append("leveraged_etf_excluded")
    if not direction_gate_pass:
        blockers.append("direction_not_long")
    if valid_price_geometry and not risk_gate_pass:
        blockers.append("risk_percent_above_limit")
    if valid_price_geometry and risk_gate_pass and reward_r is not None and reward_r < Decimal("1.00"):
        blockers.append("target_reward_below_1r")
    return {
        "symbol": symbol,
        "timeframe": str(row.get("timeframe", "")),
        "direction": direction,
        "entry": decimal_to_str(entry),
        "stop": decimal_to_str(stop),
        "target": decimal_to_str(target),
        "latest_price_source": str(row.get("latest_price_source", "")),
        "valid_price_geometry": valid_price_geometry,
        "risk": decimal_to_str(risk),
        "reward": decimal_to_str(reward),
        "reward_r": decimal_to_str(reward_r),
        "risk_percent": decimal_to_str(risk_percent),
        "max_risk_percent": decimal_to_str(max_risk_percent),
        "direction_gate_pass": direction_gate_pass,
        "leveraged_etf_excluded": leveraged_etf_excluded,
        "risk_gate_pass": risk_gate_pass,
        "reward_pass_1_0": bool(reward_r is not None and reward_r >= Decimal("1.00")),
        "reward_pass_1_1": bool(reward_r is not None and reward_r >= Decimal("1.10")),
        "reward_pass_1_2": bool(reward_r is not None and reward_r >= Decimal("1.20")),
        "blockers": blockers,
    }


def max_risk_percent_for(*, strategy_id: str, timeframe: str) -> Decimal:
    if strategy_id == "M10-PA-004-MBF-QC-m14-modify-20260522":
        return Decimal("4.00")
    return Decimal("6.00") if timeframe == "1d" else Decimal("2.50")


def classify_target_stop_issue(
    *,
    source_row_count: int,
    valid_price_count: int,
    non_leveraged_bullish_valid_count: int,
    risk_gate_pass_count: int,
    reward_ge_1_0_count: int,
) -> str:
    if source_row_count == 0 or valid_price_count == 0:
        return "missing_or_invalid_price_geometry"
    if non_leveraged_bullish_valid_count == 0:
        return "direction_or_leverage_blocks_candidate"
    if risk_gate_pass_count == 0:
        return "risk_gate_blocks_candidate"
    if reward_ge_1_0_count == 0:
        return "target_reward_below_1r_after_quality_gates"
    return "has_shadow_candidate_after_target_stop_normalization"


def recommended_action(issue: str) -> str:
    if issue == "target_reward_below_1r_after_quality_gates":
        return (
            "Inspect and shadow-test the ORB target/stop generator before lowering min-R; "
            "try measured-move/opening-range-height or normalized 1.0R targets only in simulated diagnostics."
        )
    if issue == "risk_gate_blocks_candidate":
        return "Inspect stop-distance generation and risk-percent caps before touching reward thresholds."
    if issue == "direction_or_leverage_blocks_candidate":
        return "Confirm rescue runtime direction and leveraged-ETF exclusions before changing target/stop math."
    if issue == "missing_or_invalid_price_geometry":
        return "Fix missing entry/stop/target geometry before evaluating reward thresholds."
    return "Shadow-test target/stop normalization candidates and collect 10 trading-day A/B evidence before promotion."


def sample_evaluated_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[int, int, Decimal, str]:
        reward_r = decimal_or_none(row.get("reward_r")) or Decimal("-1")
        quality_rank = 0 if row["direction_gate_pass"] and not row["leveraged_etf_excluded"] else 1
        risk_rank = 0 if row["risk_gate_pass"] else 1
        return (quality_rank, risk_rank, -reward_r, row["symbol"])

    return sorted(rows, key=sort_key)[:8]


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    issue_counts = summary["dominant_target_stop_issue_counts"]
    return (
        f"Target/stop diagnostics reviewed {summary['diagnosed_runtime_count']} rescue runtimes that were reward/R candidates. "
        f"Target/stop issues remain on {summary['target_stop_issue_runtime_count']} runtimes. "
        f"Issue counts: {issue_counts}. "
        "This is read-only and simulated; no broker connection, real order, live execution, or paper-trading approval is enabled."
    )


def build_diagnostics_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue Target/Stop Diagnostics",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Diagnosed rescue runtimes: `{summary['diagnosed_runtime_count']}`",
        f"- Target/stop issue runtimes: `{summary['target_stop_issue_runtime_count']}`",
        f"- Shadow-candidate runtimes: `{summary['shadow_candidate_runtime_count']}`",
        f"- Reward >= 1.0R runtime count: `{summary['reward_ge_1_0_runtime_count']}`",
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
                f"- Dominant target/stop issue: `{row['dominant_target_stop_issue']}`",
                f"- Source rows: `{row['source_row_count']}`",
                f"- Valid geometry: `{row['valid_price_geometry_count']}`",
                f"- Bullish rows: `{row['bullish_source_row_count']}`",
                f"- Non-leveraged bullish valid rows: `{row['non_leveraged_bullish_valid_count']}`",
                f"- Risk gate pass: `{row['risk_gate_pass_count']}`",
                f"- Reward pass counts: `1.0R={row['reward_ge_1_0_count']}, 1.1R={row['reward_ge_1_1_count']}, 1.2R={row['reward_ge_1_2_count']}`",
                f"- Reward/R min/median/max: `{row['reward_r_min']} / {row['reward_r_median']} / {row['reward_r_max']}`",
                f"- Action: {row['recommended_action']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Summary",
            "",
            f"- Dominant target/stop issues: `{summary['dominant_target_stop_issue_counts']}`",
            f"- Runtime ids: `{', '.join(summary['runtime_ids']) or 'none'}`",
            "",
        ]
    )
    return "\n".join(lines)


def decimal_median(values: list[Decimal]) -> Decimal:
    result = median(values)
    return result if isinstance(result, Decimal) else Decimal(str(result))


def decimal_to_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.0001")), "f")


def decimal_or_none(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
