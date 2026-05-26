#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m14_rescue_target_stop_shadow_normalization.json"
ZERO = Decimal("0")
HUNDRED = Decimal("100")
LEVERAGED_ETFS = frozenset({"TQQQ", "SQQQ"})
RISK_MULTIPLE_VARIANTS = (
    ("risk_normalized_1_0r", Decimal("1.00")),
    ("risk_normalized_1_1r", Decimal("1.10")),
    ("risk_normalized_1_2r", Decimal("1.20")),
)


@dataclass(frozen=True, slots=True)
class RescueTargetStopShadowNormalizationConfig:
    stage: str
    dashboard_data_path: Path
    target_stop_diagnostics_path: Path
    normalization_json_path: Path
    normalization_md_path: Path
    opening_range_minutes: int
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> RescueTargetStopShadowNormalizationConfig:
    payload = read_json(resolve_repo_path(path))
    inputs = payload["inputs"]
    outputs = payload["outputs"]
    config = RescueTargetStopShadowNormalizationConfig(
        stage=str(payload["stage"]),
        dashboard_data_path=resolve_repo_path(inputs["m12_dashboard_data"]),
        target_stop_diagnostics_path=resolve_repo_path(inputs["m14_rescue_target_stop_diagnostics"]),
        normalization_json_path=resolve_repo_path(outputs["normalization_json"]),
        normalization_md_path=resolve_repo_path(outputs["normalization_md"]),
        opening_range_minutes=int(payload.get("opening_range_minutes", 30)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", {}).items()},
    )
    validate_config(config)
    return config


def validate_config(config: RescueTargetStopShadowNormalizationConfig) -> None:
    if config.stage != "M14.rescue_target_stop_shadow_normalization":
        raise ValueError("M14 rescue target/stop shadow normalization stage drift")
    if config.opening_range_minutes <= 0:
        raise ValueError("opening_range_minutes must be positive")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M14 rescue target/stop shadow normalization must stay paper/simulated only")
    for key in ("broker_connection", "real_order", "live_execution", "paper_trading_approval"):
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M14 rescue target/stop shadow normalization cannot enable {key}")


def run_m14_rescue_target_stop_shadow_normalization(
    config: RescueTargetStopShadowNormalizationConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    dashboard_data = read_json(config.dashboard_data_path)
    target_stop_diagnostics = read_json(config.target_stop_diagnostics_path)
    signal_watchlist = [dict(row) for row in dashboard_data.get("signal_watchlist", [])]

    rows = [
        build_runtime_normalization(row, signal_watchlist, opening_range_minutes=config.opening_range_minutes)
        for row in target_stop_diagnostics.get("rows", [])
        if row.get("dominant_target_stop_issue") == "target_reward_below_1r_after_quality_gates"
    ]
    rows.sort(key=lambda row: (row["best_variant_id"], row["runtime_id"]))
    best_variant_counts = Counter(row["best_variant_id"] for row in rows if row["best_variant_id"])
    summary = {
        "diagnosed_runtime_count": len(rows),
        "runtime_with_shadow_candidate_count": sum(1 for row in rows if row["best_variant_id"]),
        "runtime_without_shadow_candidate_count": sum(1 for row in rows if not row["best_variant_id"]),
        "source_candidate_row_count": sum(row["eligible_source_row_count"] for row in rows),
        "best_variant_candidate_row_count": sum(row["best_variant_candidate_count"] for row in rows),
        "best_variant_id_counts": dict(sorted(best_variant_counts.items())),
        "runtime_ids": [row["runtime_id"] for row in rows],
        "strategy_ids": sorted({row["strategy_id"] for row in rows}),
        "parent_strategy_ids": sorted({row["parent_strategy_id"] for row in rows}),
        "opening_range_minutes": config.opening_range_minutes,
    }
    payload: dict[str, Any] = {
        "schema_version": "m14.rescue-target-stop-shadow-normalization.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "input_refs": {
            "m12_dashboard_data": project_path(config.dashboard_data_path),
            "m14_rescue_target_stop_diagnostics": project_path(config.target_stop_diagnostics_path),
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
    write_json(config.normalization_json_path, payload)
    config.normalization_md_path.parent.mkdir(parents=True, exist_ok=True)
    config.normalization_md_path.write_text(build_normalization_md(payload), encoding="utf-8")
    return payload


def build_runtime_normalization(
    diagnostic_row: dict[str, Any],
    signal_watchlist: list[dict[str, Any]],
    *,
    opening_range_minutes: int,
) -> dict[str, Any]:
    runtime_id = str(diagnostic_row.get("runtime_id", ""))
    strategy_id = str(diagnostic_row.get("strategy_id", ""))
    parent_strategy_id = str(diagnostic_row.get("parent_strategy_id", ""))
    timeframe = str(diagnostic_row.get("timeframe", ""))
    source_rows = [
        row
        for row in signal_watchlist
        if str(row.get("strategy_id", "")) == parent_strategy_id
        and str(row.get("timeframe", "")) == timeframe
    ]
    eligible_rows = [
        row
        for row in (evaluate_source_row(row, strategy_id=strategy_id, timeframe=timeframe) for row in source_rows)
        if row["eligible_for_target_stop_shadow"]
    ]
    variant_summaries = [build_risk_multiple_variant(eligible_rows, variant_id, reward_r) for variant_id, reward_r in RISK_MULTIPLE_VARIANTS]
    variant_summaries.append(
        build_opening_range_variant(
            eligible_rows,
            variant_id=f"opening_range_height_{opening_range_minutes}m",
            opening_range_minutes=opening_range_minutes,
        )
    )
    variant_summaries.sort(
        key=lambda row: (
            -row["candidate_count"],
            decimal_or_none(row["median_target_shift_percent"]) or Decimal("999999"),
            row["variant_id"],
        )
    )
    best_variant = variant_summaries[0] if variant_summaries and variant_summaries[0]["candidate_count"] > 0 else {}
    return {
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "parent_strategy_id": parent_strategy_id,
        "timeframe": timeframe,
        "source_target_stop_issue": str(diagnostic_row.get("dominant_target_stop_issue", "")),
        "source_row_count": len(source_rows),
        "eligible_source_row_count": len(eligible_rows),
        "current_reward_ge_1_0_count": sum(1 for row in eligible_rows if row["current_reward_r"] >= Decimal("1.00")),
        "current_reward_r_min": decimal_to_str(min((row["current_reward_r"] for row in eligible_rows), default=None)),
        "current_reward_r_median": decimal_to_str(decimal_median([row["current_reward_r"] for row in eligible_rows])),
        "current_reward_r_max": decimal_to_str(max((row["current_reward_r"] for row in eligible_rows), default=None)),
        "variant_summaries": variant_summaries,
        "best_variant_id": str(best_variant.get("variant_id", "")),
        "best_variant_candidate_count": int_or_zero(best_variant.get("candidate_count")),
        "best_variant_candidate_runtime_id": (
            f"{strategy_id}-target-stop-{best_variant.get('variant_id')}-shadow"
            if best_variant.get("variant_id")
            else ""
        ),
        "recommended_action": recommended_action(best_variant),
        "sample_shadow_rows": build_sample_shadow_rows(eligible_rows, best_variant),
        "promotion_gate": "shadow-only design; needs fresh-data rerun and 10 rescue A/B trading days before M14 review",
        "paper_simulated_only": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
    }


def evaluate_source_row(row: dict[str, Any], *, strategy_id: str, timeframe: str) -> dict[str, Any]:
    entry = decimal_or_none(row.get("hypothetical_entry_price"))
    stop = decimal_or_none(row.get("hypothetical_stop_price"))
    target = decimal_or_none(row.get("hypothetical_target_price"))
    direction = str(row.get("direction", ""))
    symbol = str(row.get("symbol", ""))
    valid_geometry = (
        entry is not None
        and stop is not None
        and target is not None
        and entry > ZERO
        and stop > ZERO
        and target > ZERO
        and abs(entry - stop) > ZERO
        and abs(target - entry) > ZERO
    )
    risk = abs(entry - stop) if valid_geometry and entry is not None and stop is not None else None
    reward = abs(target - entry) if valid_geometry and entry is not None and target is not None else None
    reward_r = reward / risk if risk and reward and risk > ZERO else None
    risk_percent = risk / entry * HUNDRED if risk and entry and entry > ZERO else None
    risk_gate_pass = bool(risk_percent is not None and risk_percent <= max_risk_percent_for(strategy_id=strategy_id, timeframe=timeframe))
    eligible = bool(
        valid_geometry
        and direction == "看涨"
        and symbol not in LEVERAGED_ETFS
        and risk_gate_pass
        and reward_r is not None
        and entry is not None
        and stop is not None
        and target is not None
    )
    return {
        "raw": row,
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk": risk,
        "reward": reward,
        "current_reward_r": reward_r or ZERO,
        "risk_percent": risk_percent,
        "eligible_for_target_stop_shadow": eligible,
        "latest_price_source": str(row.get("latest_price_source", "")),
        "signal_time": str(row.get("signal_time", "")),
        "data_path": str(row.get("data_path", "")),
    }


def build_risk_multiple_variant(rows: list[dict[str, Any]], variant_id: str, reward_r: Decimal) -> dict[str, Any]:
    candidates = []
    for row in rows:
        entry = row["entry"]
        risk = row["risk"]
        if entry is None or risk is None:
            continue
        target = entry + risk * reward_r
        candidates.append(build_candidate_result(row, target, target_policy="risk_multiple", variant_reward_r=reward_r))
    return summarize_variant(variant_id, "risk_multiple", candidates)


def build_opening_range_variant(
    rows: list[dict[str, Any]],
    *,
    variant_id: str,
    opening_range_minutes: int,
) -> dict[str, Any]:
    candidates = []
    for row in rows:
        entry = row["entry"]
        if entry is None:
            continue
        opening_range_height = opening_range_height_for(row["data_path"], opening_range_minutes=opening_range_minutes)
        if opening_range_height is None or opening_range_height <= ZERO:
            continue
        target = entry + opening_range_height
        candidates.append(
            build_candidate_result(
                row,
                target,
                target_policy="opening_range_height",
                opening_range_height=opening_range_height,
            )
        )
    return summarize_variant(variant_id, "opening_range_height", candidates)


def build_candidate_result(
    row: dict[str, Any],
    target: Decimal,
    *,
    target_policy: str,
    variant_reward_r: Decimal | None = None,
    opening_range_height: Decimal | None = None,
) -> dict[str, Any]:
    entry = row["entry"]
    risk = row["risk"]
    if entry is None or risk is None or risk <= ZERO:
        reward_r = ZERO
        target_shift_percent = ZERO
    else:
        reward_r = abs(target - entry) / risk
        target_shift_percent = abs(target - row["target"]) / entry * HUNDRED if row["target"] is not None else ZERO
    return {
        "symbol": row["symbol"],
        "target_policy": target_policy,
        "entry": decimal_to_str(entry),
        "stop": decimal_to_str(row["stop"]),
        "current_target": decimal_to_str(row["target"]),
        "shadow_target": decimal_to_str(target),
        "current_reward_r": decimal_to_str(row["current_reward_r"]),
        "shadow_reward_r": decimal_to_str(reward_r),
        "target_shift_percent": decimal_to_str(target_shift_percent),
        "risk_percent": decimal_to_str(row["risk_percent"]),
        "opening_range_height": decimal_to_str(opening_range_height),
        "configured_reward_r": decimal_to_str(variant_reward_r),
        "reward_ge_1_0": reward_r >= Decimal("1.00"),
        "reward_ge_1_1": reward_r >= Decimal("1.10"),
        "reward_ge_1_2": reward_r >= Decimal("1.20"),
        "latest_price_source": row["latest_price_source"],
        "signal_time": row["signal_time"],
    }


def summarize_variant(variant_id: str, target_policy: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    reward_values = [Decimal(str(row["shadow_reward_r"])) for row in candidates if row["shadow_reward_r"] is not None]
    shift_values = [
        Decimal(str(row["target_shift_percent"]))
        for row in candidates
        if row["target_shift_percent"] is not None
    ]
    return {
        "variant_id": variant_id,
        "target_policy": target_policy,
        "evaluated_row_count": len(candidates),
        "candidate_count": sum(1 for row in candidates if row["reward_ge_1_0"]),
        "reward_ge_1_0_count": sum(1 for row in candidates if row["reward_ge_1_0"]),
        "reward_ge_1_1_count": sum(1 for row in candidates if row["reward_ge_1_1"]),
        "reward_ge_1_2_count": sum(1 for row in candidates if row["reward_ge_1_2"]),
        "shadow_reward_r_min": decimal_to_str(min(reward_values) if reward_values else None),
        "shadow_reward_r_median": decimal_to_str(decimal_median(reward_values)),
        "shadow_reward_r_max": decimal_to_str(max(reward_values) if reward_values else None),
        "median_target_shift_percent": decimal_to_str(decimal_median(shift_values)) or "0.0000",
        "max_target_shift_percent": decimal_to_str(max(shift_values) if shift_values else None),
        "sample_candidates": sorted(candidates, key=lambda row: (row["symbol"], row["signal_time"]))[:8],
    }


def build_sample_shadow_rows(rows: list[dict[str, Any]], best_variant: dict[str, Any]) -> list[dict[str, Any]]:
    samples = list(best_variant.get("sample_candidates", [])) if best_variant else []
    if samples:
        return samples
    return [
        {
            "symbol": row["symbol"],
            "entry": decimal_to_str(row["entry"]),
            "stop": decimal_to_str(row["stop"]),
            "current_target": decimal_to_str(row["target"]),
            "current_reward_r": decimal_to_str(row["current_reward_r"]),
            "risk_percent": decimal_to_str(row["risk_percent"]),
            "latest_price_source": row["latest_price_source"],
            "signal_time": row["signal_time"],
        }
        for row in rows[:8]
    ]


def recommended_action(best_variant: dict[str, Any]) -> str:
    if not best_variant:
        return "No target/stop shadow candidate is available from current source rows; inspect raw ORB geometry before changing runtime thresholds."
    return (
        f"Create a shadow-only PA012 target/stop candidate using `{best_variant['variant_id']}`; "
        "rerun after the next fresh M12.47 quote refresh, then require 10 rescue A/B trading days before any M14 promote/modify/reject decision."
    )


def opening_range_height_for(path_value: str, *, opening_range_minutes: int) -> Decimal | None:
    path = resolve_repo_path(path_value)
    if not path.exists():
        return None
    highs: list[Decimal] = []
    lows: list[Decimal] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            timestamp = str(row.get("timestamp", ""))
            bar_time = time_from_timestamp(timestamp)
            if bar_time is None or bar_time < time(9, 30) or bar_time >= minute_time(9, 30 + opening_range_minutes):
                continue
            high = decimal_or_none(row.get("high"))
            low = decimal_or_none(row.get("low"))
            if high is not None and low is not None:
                highs.append(high)
                lows.append(low)
    if not highs or not lows:
        return None
    return max(highs) - min(lows)


def minute_time(hour: int, minute_value: int) -> time:
    hour += minute_value // 60
    minute_value %= 60
    return time(hour, minute_value)


def time_from_timestamp(timestamp: str) -> time | None:
    try:
        return datetime.fromisoformat(timestamp).time()
    except ValueError:
        return None


def max_risk_percent_for(*, strategy_id: str, timeframe: str) -> Decimal:
    if strategy_id == "M10-PA-004-MBF-QC-m14-modify-20260522":
        return Decimal("4.00")
    return Decimal("6.00") if timeframe == "1d" else Decimal("2.50")


def build_plain_language_result(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return (
        f"Target/stop shadow normalization reviewed {summary['diagnosed_runtime_count']} reward/R-blocked runtimes. "
        f"{summary['runtime_with_shadow_candidate_count']} have a shadow-only candidate; "
        f"best candidate rows: {summary['best_variant_candidate_row_count']}/{summary['source_candidate_row_count']}. "
        f"Best variant counts: {summary['best_variant_id_counts']}. "
        "No broker connection, real order, live execution, or paper-trading approval is enabled."
    )


def build_normalization_md(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M14 Rescue Target/Stop Shadow Normalization",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Diagnosed runtimes: `{summary['diagnosed_runtime_count']}`",
        f"- Runtime with shadow candidate: `{summary['runtime_with_shadow_candidate_count']}`",
        f"- Best candidate rows: `{summary['best_variant_candidate_row_count']}/{summary['source_candidate_row_count']}`",
        f"- Best variant counts: `{summary['best_variant_id_counts']}`",
        "- Boundary: shadow-only design; no broker connection, no real orders, no live execution.",
        "",
        "## Plain Result",
        "",
        payload["plain_language_result"],
        "",
        "## Runtime Candidates",
        "",
    ]
    for row in payload["rows"]:
        lines.extend(
            [
                f"### {row['runtime_id']}",
                "",
                f"- Parent/timeframe: `{row['parent_strategy_id']} / {row['timeframe']}`",
                f"- Eligible source rows: `{row['eligible_source_row_count']}/{row['source_row_count']}`",
                f"- Current reward/R min/median/max: `{row['current_reward_r_min']} / {row['current_reward_r_median']} / {row['current_reward_r_max']}`",
                f"- Best variant: `{row['best_variant_id']}`",
                f"- Shadow runtime id candidate: `{row['best_variant_candidate_runtime_id']}`",
                f"- Best candidate rows: `{row['best_variant_candidate_count']}`",
                f"- Action: {row['recommended_action']}",
                "",
            ]
        )
        for variant in row["variant_summaries"]:
            lines.append(
                f"- Variant `{variant['variant_id']}`: candidates `{variant['candidate_count']}/{variant['evaluated_row_count']}`, "
                f"reward/R `{variant['shadow_reward_r_min']} / {variant['shadow_reward_r_median']} / {variant['shadow_reward_r_max']}`, "
                f"median target shift `{variant['median_target_shift_percent']}%`"
            )
        lines.append("")
    lines.extend(["## Summary", "", f"- Runtime ids: `{', '.join(summary['runtime_ids']) or 'none'}`", ""])
    return "\n".join(lines)


def decimal_median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
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
