from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.m15_strategy_contracts_lib import StrategyContractError, load_contracts


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config/examples/m15_formal_test_evidence.json"
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class FormalEvidenceConfig:
    runtime_status_path: Path
    account_state_path: Path
    execution_config_path: Path
    strategy_diagnostics_path: Path
    execution_ledger_path: Path
    order_reconciliation_path: Path
    fill_attribution_path: Path
    formal_epoch_path: Path
    visual_acceptance_path: Path
    market_calendar_path: Path
    session_ledger_path: Path
    summary_path: Path
    report_path: Path
    required_symbol_count: int
    required_boundary_count: int
    stable_session_target: int
    operational_session_target: int
    performance_minimum_clean_days: int
    performance_minimum_completed_trades: int


def _resolve(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path, maximum_rows: int | None = None) -> list[dict[str, Any]]:
    try:
        handle = path.open("r", encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    rows: list[dict[str, Any]] | deque[dict[str, Any]]
    rows = deque(maxlen=maximum_rows) if maximum_rows else []
    with handle:
        for line in handle:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return list(rows)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_ledger(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> FormalEvidenceConfig:
    payload = _read_json(_resolve(path))
    if payload.get("stage") != "M15.formal_test_evidence":
        raise ValueError("formal test evidence stage drift")
    inputs = payload.get("inputs") or {}
    outputs = payload.get("outputs") or {}
    acceptance = payload.get("acceptance") or {}
    config = FormalEvidenceConfig(
        runtime_status_path=_resolve(inputs["sdk_runtime_status"]),
        account_state_path=_resolve(inputs["account_state"]),
        execution_config_path=_resolve(inputs["execution_config"]),
        strategy_diagnostics_path=_resolve(inputs["strategy_signal_diagnostics"]),
        execution_ledger_path=_resolve(inputs["execution_ledger"]),
        order_reconciliation_path=_resolve(inputs["order_reconciliation"]),
        fill_attribution_path=_resolve(inputs["fill_attribution"]),
        formal_epoch_path=_resolve(inputs["formal_epoch"]),
        visual_acceptance_path=_resolve(inputs["visual_acceptance"]),
        market_calendar_path=_resolve(inputs["market_calendar"]),
        session_ledger_path=_resolve(outputs["session_ledger_jsonl"]),
        summary_path=_resolve(outputs["summary_json"]),
        report_path=_resolve(outputs["report_md"]),
        required_symbol_count=int(acceptance.get("required_symbol_count", 147)),
        required_boundary_count=int(acceptance.get("required_boundary_count", 78)),
        stable_session_target=int(acceptance.get("stable_session_target", 3)),
        operational_session_target=int(acceptance.get("operational_session_target", 5)),
        performance_minimum_clean_days=int(
            acceptance.get("performance_minimum_clean_days", 20)
        ),
        performance_minimum_completed_trades=int(
            acceptance.get("performance_minimum_completed_trades", 30)
        ),
    )
    if config.required_symbol_count != 147:
        raise ValueError("formal trading evidence must use the frozen 147-symbol universe")
    if config.required_boundary_count != 78:
        raise ValueError("formal trading evidence must require all 78 five-minute boundaries")
    if not config.market_calendar_path.exists():
        raise ValueError(f"market calendar missing: {config.market_calendar_path}")
    calendar = _read_json(config.market_calendar_path)
    if not isinstance(calendar.get("market_holidays"), list):
        raise ValueError("market calendar must define market_holidays as a list")
    return config


def _iso_market_date(value: Any) -> str:
    try:
        observed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return observed.astimezone(NEW_YORK).date().isoformat()


def _stable_distinct_key(row: dict[str, Any], *, kind: str) -> tuple[str, ...]:
    explicit_id = next(
        (
            str(row.get(field) or "")
            for field in (
                "signal_id",
                "candidate_id",
                "decision_id",
                "event_id",
                "fingerprint",
            )
            if str(row.get(field) or "")
        ),
        "",
    )
    if explicit_id:
        return (kind, explicit_id)
    return (
        kind,
        str(row.get("runtime_id") or ""),
        str(row.get("strategy_contract_hash") or ""),
        str(row.get("symbol") or ""),
        str(
            row.get("market_event_time")
            or row.get("source_event_at")
            or row.get("created_at")
            or row.get("submitted_at")
            or ""
        ),
        str(
            row.get("router_decision_status")
            or row.get("position_action")
            or row.get("side")
            or row.get("direction")
            or ""
        ),
    )


def _runtime_inventory(execution_config: dict[str, Any]) -> dict[str, Any]:
    realtime = execution_config.get("longbridge_realtime") or {}
    layering = execution_config.get("runtime_layering") or {}
    executable = [str(value) for value in realtime.get("allowed_runtime_ids") or []]
    visual = [str(value) for value in layering.get("visual_shadow_only") or []]
    retired = [str(value) for value in layering.get("retired_simplified_versions") or []]
    return {
        "executable_contract_runtime_ids": executable,
        "executable_contract_count": len(executable),
        "visual_contract_draft_runtime_ids": visual,
        "visual_contract_draft_count": len(visual),
        "retired_simplified_runtime_ids": retired,
        "retired_simplified_count": len(retired),
    }


def _current_contract_hashes(execution_config: dict[str, Any]) -> dict[str, str]:
    directory = str((execution_config.get("strategy_contracts") or {}).get("directory") or "")
    if not directory:
        return {}
    path = _resolve(directory)
    try:
        return {
            runtime_id: str(contract["contract_hash"])
            for runtime_id, contract in load_contracts(path).items()
        }
    except StrategyContractError:
        # Tests and migration fixtures may carry an explicit precomputed hash.
        # Production contracts are always validated and hashed by the contract loader.
        pass
    hashes: dict[str, str] = {}
    for contract_path in path.glob("*.json"):
        payload = _read_json(contract_path)
        runtime_id = str(payload.get("runtime_id") or "")
        contract_hash = str(payload.get("contract_hash") or "")
        if runtime_id and contract_hash:
            hashes[runtime_id] = contract_hash
    return hashes


def _market_session_layer(
    runtime: dict[str, Any], config: FormalEvidenceConfig
) -> dict[str, Any]:
    coverage = runtime.get("five_minute_session_coverage") or {}
    required_rows = config.required_symbol_count * config.required_boundary_count
    expected_boundaries = int(coverage.get("expected_boundary_count_so_far") or 0)
    complete_boundaries = int(coverage.get("complete_boundary_count") or 0)
    accepted_rows = int(coverage.get("accepted_row_count_so_far") or 0)
    duplicates = int(
        coverage.get("duplicate_row_count")
        if coverage.get("duplicate_row_count") is not None
        else coverage.get("duplicate_count") or 0
    )
    invalid_rows = int(
        coverage.get("invalid_row_count")
        if coverage.get("invalid_row_count") is not None
        else coverage.get("invalid_count") or 0
    )
    late_finalization_rows = int(
        coverage.get("late_finalization_row_count") or 0
    )
    partial = int(coverage.get("partial_boundary_count") or 0)
    missing = int(coverage.get("missing_boundary_count") or 0)
    final_window = expected_boundaries == config.required_boundary_count
    business_date = str(coverage.get("business_date") or "")
    calendar = _read_json(config.market_calendar_path)
    market_holidays = {
        str(value) for value in calendar.get("market_holidays") or []
    }
    try:
        business_day = datetime.fromisoformat(business_date).date()
        non_trading_day = (
            business_day.weekday() >= 5
            or business_day.isoformat() in market_holidays
        )
    except ValueError:
        non_trading_day = False
    complete = bool(
        final_window
        and coverage.get("session_complete") is True
        and complete_boundaries == config.required_boundary_count
        and accepted_rows == required_rows
        and duplicates == 0
        and invalid_rows == 0
        and late_finalization_rows == 0
        and partial == 0
        and missing == 0
    )
    if non_trading_day and expected_boundaries == 0:
        status = "not_applicable_non_trading_day"
        plain = "当前是非交易日，不生成正式会话结论，等待下一个美股交易日。"
    elif complete:
        status = "complete"
        plain = "147只标的的78个五分钟边界全部来自实时SDK行情，本交易日可计入正式测试。"
    elif late_finalization_rows:
        status = "incomplete_late_market_data"
        plain = (
            f"有{late_finalization_rows}条五分钟K线超过实时形成时限，"
            "即使最终补齐也不能计为完整正式测试日。"
        )
    elif not final_window:
        status = "waiting_for_session_close"
        plain = "常规交易时段尚未结束，等待78个五分钟边界全部形成。"
    else:
        status = "incomplete"
        plain = "实时五分钟行情存在缺口，本交易日保留交易审计，但不计为完整正式测试日。"
    return {
        "status": status,
        "complete": complete,
        "applicable": not non_trading_day,
        "business_date": business_date,
        "required_symbol_count": config.required_symbol_count,
        "required_boundary_count": config.required_boundary_count,
        "required_row_count": required_rows,
        "expected_boundary_count": expected_boundaries,
        "complete_boundary_count": complete_boundaries,
        "accepted_row_count": accepted_rows,
        "partial_boundary_count": partial,
        "missing_boundary_count": missing,
        "duplicate_count": duplicates,
        "invalid_row_count": invalid_rows,
        "late_finalization_row_count": late_finalization_rows,
        "maximum_allowed_finalization_delay_ms": int(
            coverage.get("maximum_allowed_finalization_delay_ms") or 0
        ),
        "maximum_observed_finalization_delay_ms": int(
            coverage.get("maximum_observed_finalization_delay_ms") or 0
        ),
        "late_finalization_examples": list(
            coverage.get("late_finalization_examples") or []
        ),
        "missing_boundary_times": list(coverage.get("missing_boundary_times") or []),
        "recovered_data_is_realtime_evidence": False,
        "plain_language_result": plain,
    }


def _strategy_operation_layer(
    diagnostics: dict[str, Any],
    inventory: dict[str, Any],
    current_contract_hashes: dict[str, str],
    business_date: str,
) -> dict[str, Any]:
    source_date = _iso_market_date(diagnostics.get("generated_at"))
    attempt_rows = [
        row
        for row in diagnostics.get("detector_attempt_rows") or []
        if isinstance(row, dict)
        and _iso_market_date(row.get("market_event_time")) == business_date
    ]
    decision_rows = [
        row
        for row in diagnostics.get("decision_rows") or []
        if isinstance(row, dict)
        and _iso_market_date(row.get("created_at")) == business_date
    ]
    runtime_rows: list[dict[str, Any]] = []
    total_attempt_count = 0
    total_candidate_count = 0
    total_distinct_candidate_count = 0
    total_signal_ready_count = 0
    total_distinct_signal_ready_count = 0
    for runtime_id in inventory["executable_contract_runtime_ids"]:
        runtime_attempts = [
            row for row in attempt_rows if str(row.get("runtime_id") or "") == runtime_id
        ]
        runtime_decisions = [
            row for row in decision_rows if str(row.get("runtime_id") or "") == runtime_id
        ]
        expected_hash = current_contract_hashes.get(runtime_id, "")
        hash_mismatch_count = sum(
            bool(expected_hash)
            and str(row.get("strategy_contract_hash") or "") != expected_hash
            for row in [*runtime_attempts, *runtime_decisions]
        )
        attempts = len(runtime_attempts)
        if source_date and source_date != business_date and not runtime_attempts:
            status = "source_date_mismatch"
        elif not expected_hash:
            status = "contract_hash_missing"
        elif attempts == 0:
            status = "not_evaluated"
        elif hash_mismatch_count:
            status = "contract_hash_mismatch"
        else:
            status = "operational"
        no_candidate_reasons: dict[str, int] = {}
        for row in runtime_attempts:
            reason = str(row.get("no_candidate_reason") or "")
            if reason:
                no_candidate_reasons[reason] = no_candidate_reasons.get(reason, 0) + 1
        router_blockers: dict[str, int] = {}
        for row in runtime_decisions:
            status_code = str(row.get("router_decision_status") or "")
            if status_code and status_code != "signal_event_ready":
                router_blockers[status_code] = router_blockers.get(status_code, 0) + 1
        candidate_rows = [
            row for row in runtime_attempts if row.get("candidate_emitted") is True
        ]
        signal_ready_rows = [
            row
            for row in runtime_decisions
            if str(row.get("router_decision_status") or "") == "signal_event_ready"
        ]
        distinct_candidate_count = len(
            {_stable_distinct_key(row, kind="candidate") for row in candidate_rows}
        )
        distinct_signal_ready_count = len(
            {
                _stable_distinct_key(row, kind="signal_ready")
                for row in signal_ready_rows
            }
        )
        total_attempt_count += attempts
        total_candidate_count += len(candidate_rows)
        total_distinct_candidate_count += distinct_candidate_count
        total_signal_ready_count += len(signal_ready_rows)
        total_distinct_signal_ready_count += distinct_signal_ready_count
        runtime_rows.append(
            {
                "runtime_id": runtime_id,
                "status": status,
                "attempt_count": attempts,
                "detector_attempted_count": attempts,
                "no_candidate_count": sum(
                    row.get("candidate_emitted") is not True for row in runtime_attempts
                ),
                "candidate_count": len(candidate_rows),
                "distinct_candidate_count": distinct_candidate_count,
                "signal_ready_count": len(signal_ready_rows),
                "distinct_signal_ready_count": distinct_signal_ready_count,
                "current_contract_hash": expected_hash,
                "contract_hash_mismatch_count": hash_mismatch_count,
                "top_no_candidate_reasons": no_candidate_reasons,
                "top_router_blockers": router_blockers,
            }
        )
    operational_count = sum(row["status"] == "operational" for row in runtime_rows)
    complete = operational_count == inventory["executable_contract_count"]
    return {
        "status": "complete" if complete else "incomplete",
        "complete": complete,
        "source_business_date": source_date,
        "expected_runtime_count": inventory["executable_contract_count"],
        "operational_runtime_count": operational_count,
        "attempt_count": total_attempt_count,
        "detector_attempted_count": total_attempt_count,
        "candidate_count": total_candidate_count,
        "distinct_candidate_count": total_distinct_candidate_count,
        "signal_ready_count": total_signal_ready_count,
        "distinct_signal_ready_count": total_distinct_signal_ready_count,
        "runtime_rows": runtime_rows,
        "plain_language_result": (
            "8条正式合同均完成了当天策略检测；没有候选不等于策略故障。"
            if complete
            else "至少一条正式合同没有留下当天检测证据，需要按运行单元定位缺失环节。"
        ),
    }


def _row_market_date(row: dict[str, Any]) -> str:
    for key in ("submitted_at", "processed_at", "created_at", "generated_at"):
        value = row.get(key)
        if value:
            market_date = _iso_market_date(value)
            if market_date:
                return market_date
    return ""


def _broker_execution_layer(
    execution_rows: list[dict[str, Any]],
    reconciliation: dict[str, Any],
    operation: dict[str, Any],
    business_date: str,
    contract_hashes: dict[str, str],
    formal_epoch: dict[str, Any],
) -> dict[str, Any]:
    account_status_by_order = {
        str(row.get("order_id") or ""): str(
            row.get("canonical_status")
            or row.get("longbridge_status")
            or row.get("status")
            or ""
        ).lower()
        for row in reconciliation.get("rows") or []
        if isinstance(row, dict) and str(row.get("order_id") or "")
    }
    runtime_rows: list[dict[str, Any]] = []
    unexplained_drop_count = 0
    excluded_noncurrent_execution_row_count = 0
    for operation_row in operation["runtime_rows"]:
        runtime_id = operation_row["runtime_id"]
        dated_rows = [
            row
            for row in execution_rows
            if str(row.get("runtime_id") or "") == runtime_id
            and _row_market_date(row) == business_date
        ]
        expected_epoch_id = str(
            (
                formal_epoch.get("short_test_epoch_id")
                if runtime_id.endswith("-short")
                else formal_epoch.get("test_epoch_id")
            )
            or ""
        )
        expected_contract_hash = str(contract_hashes.get(runtime_id) or "")
        rows = [
            row
            for row in dated_rows
            if str(row.get("test_epoch_id") or "") == expected_epoch_id
            and str(row.get("strategy_contract_hash") or "")
            == expected_contract_hash
        ]
        excluded_noncurrent_execution_row_count += len(dated_rows) - len(rows)
        order_ids = {
            str(row.get("longbridge_order_id") or row.get("broker_order_id") or row.get("order_id") or "")
            for row in rows
            if str(row.get("longbridge_order_id") or row.get("broker_order_id") or row.get("order_id") or "")
        }
        explicit_blocked = sum(
            bool(row.get("blockers")) or str(row.get("submission_status") or "").startswith("blocked")
            for row in rows
        )
        ready = int(operation_row.get("signal_ready_count") or 0)
        unexplained = ready > 0 and not order_ids and explicit_blocked == 0
        unexplained_drop_count += int(unexplained)
        if ready == 0:
            status = "normal_no_eligible_signal"
        elif unexplained:
            status = "unexplained_signal_drop"
        elif order_ids:
            status = "broker_order_created"
        else:
            status = "explained_risk_block"
        runtime_rows.append(
            {
                "runtime_id": runtime_id,
                "status": status,
                "signal_ready_count": ready,
                "execution_row_count": len(rows),
                "explicit_blocked_count": explicit_blocked,
                "broker_order_id_count": len(order_ids),
                "filled_or_partial_order_count": sum(
                    account_status_by_order.get(order_id) in {"filled", "partially_filled"}
                    for order_id in order_ids
                ),
            }
        )
    complete = operation["complete"] and unexplained_drop_count == 0
    return {
        "status": "operational" if complete else "needs_attention",
        "complete": complete,
        "unexplained_signal_drop_count": unexplained_drop_count,
        "excluded_noncurrent_execution_row_count": excluded_noncurrent_execution_row_count,
        "runtime_rows": runtime_rows,
        "plain_language_result": (
            "券商执行链路没有发现合格信号无解释消失；零订单策略已明确为无合格信号或风控阻断。"
            if complete
            else "存在合格信号未形成订单号且没有明确阻断原因，需要修复后才能计为执行正常。"
        ),
    }


def _performance_layer(
    fill_attribution: dict[str, Any],
    inventory: dict[str, Any],
    clean_day_count: int,
    config: FormalEvidenceConfig,
) -> dict[str, Any]:
    rows_by_runtime = {
        str(row.get("runtime_id") or ""): row
        for row in fill_attribution.get("strategy_performance") or []
        if isinstance(row, dict) and str(row.get("runtime_id") or "")
    }
    runtime_rows = []
    for runtime_id in inventory["executable_contract_runtime_ids"]:
        row = rows_by_runtime.get(runtime_id) or {}
        completed = int(row.get("completed_trade_count") or 0)
        clean_window_reached = clean_day_count >= config.performance_minimum_clean_days
        sample_sufficient = bool(
            clean_window_reached
            and completed >= config.performance_minimum_completed_trades
        )
        runtime_rows.append(
            {
                "runtime_id": runtime_id,
                "status": "sufficient" if sample_sufficient else "insufficient",
                "completed_trade_count": completed,
                "minimum_completed_trade_count": config.performance_minimum_completed_trades,
                "clean_formal_day_count": clean_day_count,
                "minimum_clean_day_count": config.performance_minimum_clean_days,
                "minimum_clean_day_window_reached": clean_window_reached,
                "gross_realized_pnl": row.get("gross_realized_pnl"),
                "win_rate_after_estimated_fees_pct": row.get("win_rate_after_estimated_fees_pct"),
                "profit_factor_after_estimated_fees": row.get("profit_factor_after_estimated_fees"),
            }
        )
    sufficient_count = sum(row["status"] == "sufficient" for row in runtime_rows)
    return {
        "status": "reference_only" if clean_day_count == 0 else (
            "sufficient"
            if sufficient_count == inventory["executable_contract_count"]
            else "insufficient"
        ),
        "evidence_scope": (
            "clean_formal_window"
            if clean_day_count >= config.performance_minimum_clean_days
            else "existing_contract_epoch_reference"
        ),
        "counts_as_clean_formal_performance": bool(
            clean_day_count >= config.performance_minimum_clean_days
            and sufficient_count == inventory["executable_contract_count"]
        ),
        "sufficient_runtime_count": sufficient_count,
        "expected_runtime_count": inventory["executable_contract_count"],
        "runtime_rows": runtime_rows,
        "plain_language_result": (
            "当前数字来自旧合同周期，只作参考；尚未建立稳定会话后的干净成绩基线。"
            if clean_day_count == 0
            else "全部正式策略已达到阶段评价样本。"
            if sufficient_count == inventory["executable_contract_count"]
            else "策略可以正常运行，但样本尚不足以评价最终盈利能力。"
        ),
    }


def _visual_layer(visual: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for strategy_id in ("PA004", "PA007", "PA008"):
        row = visual.get(strategy_id) or {}
        review = row.get("human_review_passed_counts") or {}
        complete = bool(
            row.get("no_future_data") is True
            and row.get("restart_parity") is True
            and int(row.get("realtime_shadow_sessions") or 0) >= 1
            and int(review.get("positive_examples") or 0) >= 10
            and int(review.get("negative_examples") or 0) >= 10
            and int(review.get("boundary_examples") or 0) >= 5
        )
        rows.append(
            {
                "strategy_id": strategy_id,
                "runtime_id": row.get("runtime_id"),
                "stage": "paper_v1_ready" if complete else "contract_draft_v1",
                "no_future_data": row.get("no_future_data") is True,
                "restart_parity": row.get("restart_parity") is True,
                "realtime_shadow_sessions": int(row.get("realtime_shadow_sessions") or 0),
                "positive_examples": int(review.get("positive_examples") or 0),
                "negative_examples": int(review.get("negative_examples") or 0),
                "boundary_examples": int(review.get("boundary_examples") or 0),
                "paper_orders_allowed": False,
            }
        )
    return {
        "status": "ready_for_contract_promotion" if all(row["stage"] == "paper_v1_ready" for row in rows) else "contract_draft",
        "runtime_rows": rows,
        "plain_language_result": "三条视觉策略保持只读草案；机器回放不能替代一次人工10/10/5图形确认。",
    }


def _consecutive_clean_days(rows: list[dict[str, Any]]) -> int:
    ordered = sorted(rows, key=lambda row: str(row.get("business_date") or ""), reverse=True)
    count = 0
    for row in ordered:
        if (row.get("market_session") or {}).get("complete") is not True:
            break
        count += 1
    return count


def _render_report(payload: dict[str, Any]) -> str:
    layers = payload["layers"]
    return "\n".join(
        [
            "# 长桥正式测试证据",
            "",
            f"- 交易日：`{payload['business_date']}`",
            f"- 行情会话：{layers['market_session']['plain_language_result']}",
            f"- 策略检测：{layers['strategy_operation']['plain_language_result']}",
            f"- 券商执行：{layers['broker_execution']['plain_language_result']}",
            f"- 成绩样本：{layers['performance_sample']['plain_language_result']}",
            f"- 连续完整交易日：`{payload['progress']['consecutive_clean_session_count']}/{payload['progress']['stable_session_target']}`",
            "",
            "只统计长桥SDK模拟账户事实；本地模拟、盘后补录和历史简化版不作为正式测试证据。",
            "",
        ]
    )


def generate_formal_test_evidence(
    config: FormalEvidenceConfig,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    runtime = _read_json(config.runtime_status_path)
    account = _read_json(config.account_state_path)
    execution_config = _read_json(config.execution_config_path)
    diagnostics = _read_json(config.strategy_diagnostics_path)
    execution_rows = _read_jsonl(config.execution_ledger_path, maximum_rows=50_000)
    reconciliation = _read_json(config.order_reconciliation_path)
    fill_attribution = _read_json(config.fill_attribution_path)
    formal_epoch = _read_json(config.formal_epoch_path)
    visual = _read_json(config.visual_acceptance_path)
    inventory = _runtime_inventory(execution_config)
    sdk_paper_runtime_ready = bool(
        str(runtime.get("runtime_engine") or "").lower() == "sdk"
        and runtime.get("sdk_connected") is True
        and account.get("paper_account_verified") is True
        and str(account.get("account_channel") or "") == "lb_papertrading"
    )
    market = _market_session_layer(runtime, config)
    business_date = market["business_date"] or _iso_market_date(generated_at)
    if market.get("applicable") is False:
        operation = {
            "status": "not_applicable_non_trading_day",
            "complete": False,
            "source_business_date": _iso_market_date(diagnostics.get("generated_at")),
            "expected_runtime_count": inventory["executable_contract_count"],
            "operational_runtime_count": 0,
            "runtime_rows": [],
            "plain_language_result": "非交易日不要求策略产生检测记录。",
        }
        broker = {
            "status": "not_applicable_non_trading_day",
            "complete": False,
            "unexplained_signal_drop_count": 0,
            "runtime_rows": [],
            "plain_language_result": "非交易日不要求产生策略订单。",
        }
    else:
        contract_hashes = _current_contract_hashes(execution_config)
        operation = _strategy_operation_layer(
            diagnostics,
            inventory,
            contract_hashes,
            business_date,
        )
        broker = _broker_execution_layer(
            execution_rows,
            reconciliation,
            operation,
            business_date,
            contract_hashes,
            formal_epoch,
        )
        if not sdk_paper_runtime_ready:
            for layer, message in (
                (market, "实际运行环境不是已连接的长桥SDK模拟账户，本交易日不能计为正式行情证据。"),
                (operation, "实际运行环境不是已连接的长桥SDK模拟账户，策略检测结果只保留审计。"),
                (broker, "实际运行环境不是已连接的长桥SDK模拟账户，订单结果不能计为正式执行证据。"),
            ):
                layer["source_status_before_runtime_gate"] = layer.get("status")
                layer["status"] = "blocked_runtime_prerequisite"
                layer["complete"] = False
                layer["plain_language_result"] = message

    existing = _read_jsonl(config.session_ledger_path)
    provisional_clean = bool(
        sdk_paper_runtime_ready
        and market["complete"]
        and operation["complete"]
        and broker["complete"]
    )
    current_stub = {
        "business_date": business_date,
        "market_session": {"complete": provisional_clean},
    }
    rows_for_progress = [row for row in existing if str(row.get("business_date") or "") != business_date]
    if market.get("applicable") is not False and market["status"] != "waiting_for_session_close":
        rows_for_progress.append(current_stub)
    clean_day_count = sum(
        bool((row.get("market_session") or {}).get("complete")) for row in rows_for_progress
    )
    performance = _performance_layer(fill_attribution, inventory, clean_day_count, config)
    visual_layer = _visual_layer(visual)
    record = {
        "schema_version": "m15.formal-test-evidence.v1",
        "generated_at": generated_at,
        "business_date": business_date,
        "test_epoch_id": formal_epoch.get("test_epoch_id"),
        "short_test_epoch_id": formal_epoch.get("short_test_epoch_id"),
        "paper_account_verified": account.get("paper_account_verified") is True,
        "account_channel": account.get("account_channel"),
        "sdk_paper_runtime_ready": sdk_paper_runtime_ready,
        "inventory": inventory,
        "layers": {
            "market_session": market,
            "strategy_operation": operation,
            "broker_execution": broker,
            "performance_sample": performance,
            "visual_contract_drafts": visual_layer,
        },
        "market_session": {"complete": provisional_clean},
    }
    if market.get("applicable") is not False and market["status"] != "waiting_for_session_close":
        ledger_rows = [
            row for row in existing if str(row.get("business_date") or "") != business_date
        ]
        ledger_rows.append(record)
        ledger_rows.sort(key=lambda row: str(row.get("business_date") or ""))
        _write_ledger(config.session_ledger_path, ledger_rows)
    else:
        ledger_rows = existing
    consecutive = _consecutive_clean_days(ledger_rows)
    clean_days = sum(bool((row.get("market_session") or {}).get("complete")) for row in ledger_rows)
    payload = {
        **record,
        "progress": {
            "clean_session_count": clean_days,
            "consecutive_clean_session_count": consecutive,
            "stable_session_target": config.stable_session_target,
            "operational_session_target": config.operational_session_target,
            "stable_environment_accepted": consecutive >= config.stable_session_target,
            "strategy_operation_accepted": consecutive >= config.operational_session_target,
        },
        "formal_performance_baseline": {
            "status": "eligible_to_start" if consecutive >= config.stable_session_target else "waiting_for_stable_sessions",
            "historical_incomplete_sessions_are_reference_only": True,
            "automatic_flatten_required": False,
        },
        "hard_boundaries": {
            "paper_simulated_only": True,
            "local_simulation_used": False,
            "recovered_rows_count_as_realtime": False,
            "changes_trading_permissions": False,
        },
    }
    _atomic_write_json(config.summary_path, payload)
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(_render_report(payload), encoding="utf-8")
    return payload
