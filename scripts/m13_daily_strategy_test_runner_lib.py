#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m13_daily_strategy_test_runner.json"
VALID_DAILY_STATES = {
    "not_connected",
    "detector_missing",
    "missing_data",
    "zero_signal",
    "signal_generated",
    "open",
    "close",
    "risk_blocked",
    "plugin_ab_attached",
}
BLOCKER_STATES = {"not_connected", "detector_missing", "missing_data"}
INDEPENDENT_ROLE = "independent_runtime"
PLUGIN_ROLE = "plugin_filter"
RESEARCH_ROLE = "research_only"
EXTERNAL_ROLE = "external_research"


@dataclass(frozen=True, slots=True)
class BoundaryConfig:
    paper_simulated_only: bool
    trading_connection: bool
    real_money_actions: bool
    live_execution: bool
    paper_trading_approval: bool
    ai_trader_copy_trading: bool


@dataclass(frozen=True, slots=True)
class M13Config:
    title: str
    run_id: str
    stage: str
    market: str
    output_dir: Path
    registry_path: Path
    m12_29_output_dir: Path
    min_challenge_trading_days: int
    boundary: BoundaryConfig


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M13Config:
    payload = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    boundary = payload["boundary"]
    config = M13Config(
        title=payload["title"],
        run_id=payload.get("run_id", "m13_daily_strategy_test_runner"),
        stage=payload["stage"],
        market=payload.get("market", "US"),
        output_dir=resolve_repo_path(payload["output_dir"]),
        registry_path=resolve_repo_path(payload["registry_path"]),
        m12_29_output_dir=resolve_repo_path(payload["m12_29_output_dir"]),
        min_challenge_trading_days=int(payload["min_challenge_trading_days"]),
        boundary=BoundaryConfig(
            paper_simulated_only=bool(boundary["paper_simulated_only"]),
            trading_connection=bool(boundary["trading_connection"]),
            real_money_actions=bool(boundary["real_money_actions"]),
            live_execution=bool(boundary["live_execution"]),
            paper_trading_approval=bool(boundary["paper_trading_approval"]),
            ai_trader_copy_trading=bool(boundary["ai_trader_copy_trading"]),
        ),
    )
    validate_config(config)
    return config


def validate_config(config: M13Config) -> None:
    if config.stage != "M13.real_daily_strategy_testing":
        raise ValueError("M13 stage drift")
    if config.min_challenge_trading_days != 10:
        raise ValueError("M13 challenge window must stay at 10 trading days")
    if not config.boundary.paper_simulated_only:
        raise ValueError("M13 must stay paper/simulated only")
    if (
        config.boundary.trading_connection
        or config.boundary.real_money_actions
        or config.boundary.live_execution
        or config.boundary.paper_trading_approval
        or config.boundary.ai_trader_copy_trading
    ):
        raise ValueError("M13 cannot enable trading, real-money, paper approval, or AI-Trader copy trading")


def load_registry(path: Path) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    validate_registry(registry)
    return registry


def validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("schema_version") != "m13.strategy-runtime-registry.v1":
        raise ValueError("M13 registry schema drift")
    declared_states = set(registry.get("required_daily_states", []))
    if declared_states != VALID_DAILY_STATES:
        raise ValueError(f"M13 registry daily states drift: {sorted(declared_states)}")
    strategy_ids: set[str] = set()
    runtime_ids: set[str] = set()
    required_ids = {
        "M10-PA-001",
        "M10-PA-002",
        "M10-PA-003",
        "M10-PA-004",
        "M10-PA-005",
        "M10-PA-006",
        "M10-PA-007",
        "M10-PA-008",
        "M10-PA-009",
        "M10-PA-011",
        "M10-PA-012",
        "M10-PA-013",
        "M10-PA-014",
        "M10-PA-015",
        "M10-PA-016",
        "M12-FTD-001",
    }
    for strategy in registry.get("strategies", []):
        strategy_id = strategy.get("strategy_id", "")
        if not strategy_id or strategy_id in strategy_ids:
            raise ValueError(f"Duplicate or missing strategy_id: {strategy_id}")
        strategy_ids.add(strategy_id)
        role = strategy.get("module_role", "")
        if role not in {INDEPENDENT_ROLE, PLUGIN_ROLE, RESEARCH_ROLE, EXTERNAL_ROLE}:
            raise ValueError(f"Unsupported M13 role for {strategy_id}: {role}")
        accounts = strategy.get("runtime_accounts", [])
        if role == INDEPENDENT_ROLE and not accounts:
            raise ValueError(f"Independent runtime missing account: {strategy_id}")
        if role == PLUGIN_ROLE and not strategy.get("plugin_targets"):
            raise ValueError(f"Plugin/filter missing targets: {strategy_id}")
        for account in accounts:
            runtime_id = account.get("runtime_id", "")
            if not runtime_id or runtime_id in runtime_ids:
                raise ValueError(f"Duplicate or missing runtime_id: {runtime_id}")
            runtime_ids.add(runtime_id)
    missing = required_ids - strategy_ids
    if missing:
        raise ValueError(f"M13 registry missing required strategy ids: {sorted(missing)}")


def run_m13_daily_strategy_test_runner(
    config: M13Config | None = None,
    *,
    generated_at: str | None = None,
    trading_date: str | date | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    registry = load_registry(config.registry_path)
    resolved_trading_date = resolve_trading_date(config, generated_at, trading_date)
    run_id = f"{config.run_id}:{resolved_trading_date.isoformat()}:{generated_at}"

    audit_rows = load_m12_account_input_audit(config.m12_29_output_dir)
    audit_by_runtime = {row.get("runtime_id", ""): row for row in audit_rows}
    m12_trade_ledger_rows = filter_rows_for_trading_date(
        read_jsonl(config.m12_29_output_dir / "m12_46_account_trade_ledger.jsonl"),
        resolved_trading_date,
    )
    scorecards_by_runtime = {
        row.get("runtime_id", ""): row
        for row in read_csv(config.m12_29_output_dir / "m12_46_account_scorecards.csv")
    }

    signal_ledger_rows: list[dict[str, Any]] = []
    account_ledger_rows: list[dict[str, Any]] = []
    for strategy in registry["strategies"]:
        role = strategy["module_role"]
        if role == INDEPENDENT_ROLE:
            strategy_signal_rows, strategy_account_rows = build_independent_runtime_rows(
                strategy=strategy,
                audit_by_runtime=audit_by_runtime,
                m12_trade_ledger_rows=m12_trade_ledger_rows,
                scorecards_by_runtime=scorecards_by_runtime,
                run_id=run_id,
                generated_at=generated_at,
                trading_date=resolved_trading_date,
            )
        else:
            strategy_signal_rows, strategy_account_rows = build_non_runtime_rows(
                strategy=strategy,
                run_id=run_id,
                generated_at=generated_at,
                trading_date=resolved_trading_date,
            )
        signal_ledger_rows.extend(strategy_signal_rows)
        account_ledger_rows.extend(strategy_account_rows)

    scorecard_rows = build_scorecard_rows(registry["strategies"], signal_ledger_rows, account_ledger_rows)
    summary = build_summary(
        config=config,
        registry=registry,
        generated_at=generated_at,
        trading_date=resolved_trading_date,
        signal_ledger_rows=signal_ledger_rows,
        account_ledger_rows=account_ledger_rows,
        scorecard_rows=scorecard_rows,
    )
    goal_status = build_goal_status(summary)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(config.output_dir / "m13_strategy_signal_ledger.jsonl", signal_ledger_rows)
    write_jsonl(config.output_dir / "m13_account_operation_ledger.jsonl", account_ledger_rows)
    write_csv(config.output_dir / "m13_daily_strategy_scorecard.csv", scorecard_rows)
    write_json(config.output_dir / "m13_daily_strategy_scorecard.json", {"rows": scorecard_rows})
    write_json(config.output_dir / "m13_daily_strategy_test_summary.json", summary)
    write_json(config.output_dir / "m13_goal_status.json", goal_status)
    (config.output_dir / "m13_goal_prompt.md").write_text(build_goal_prompt_md(), encoding="utf-8")

    return {
        "summary": summary,
        "goal_status": goal_status,
        "signal_ledger_rows": signal_ledger_rows,
        "account_ledger_rows": account_ledger_rows,
        "scorecard_rows": scorecard_rows,
    }


def build_independent_runtime_rows(
    *,
    strategy: dict[str, Any],
    audit_by_runtime: dict[str, dict[str, str]],
    m12_trade_ledger_rows: list[dict[str, Any]],
    scorecards_by_runtime: dict[str, dict[str, str]],
    run_id: str,
    generated_at: str,
    trading_date: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    signal_rows: list[dict[str, Any]] = []
    account_rows: list[dict[str, Any]] = []
    for account in strategy.get("runtime_accounts", []):
        runtime_id = account["runtime_id"]
        audit = audit_by_runtime.get(runtime_id, {})
        state = state_from_audit(strategy, audit)
        signal_count = int_or_zero(audit.get("today_formal_signal_count", "0"))
        signal_rows.append(
            base_signal_row(strategy, run_id, generated_at, trading_date)
            | {
                "runtime_id": runtime_id,
                "lane": account.get("lane", ""),
                "timeframe": account.get("timeframe", ""),
                "variant_id": account.get("variant_id", ""),
                "test_state": state,
                "signal_count": signal_count,
                "input_status": audit.get("input_status", "missing_account_input_audit"),
                "current_scanner_connected": audit.get("current_scanner_connected", "false"),
                "source_row_count": int_or_zero(audit.get("source_row_count", "0")),
                "plain_language_result": audit.get("plain_language_result", "No account input audit row was found."),
            }
        )
        matching_operations = [row for row in m12_trade_ledger_rows if row.get("runtime_id") == runtime_id]
        if matching_operations:
            for operation in matching_operations:
                event_type = str(operation.get("event_type", ""))
                account_rows.append(
                    base_account_row(strategy, run_id, generated_at, trading_date)
                    | {
                        "runtime_id": runtime_id,
                        "lane": account.get("lane", ""),
                        "timeframe": account.get("timeframe", ""),
                        "variant_id": account.get("variant_id", ""),
                        "event_type": event_type,
                        "test_state": event_type if event_type in {"open", "close"} else state,
                        "symbol": operation.get("symbol", ""),
                        "direction": operation.get("direction", ""),
                        "quantity": operation.get("quantity", ""),
                        "entry_price": operation.get("entry_price", ""),
                        "exit_price": operation.get("exit_price", ""),
                        "realized_pnl": operation.get("realized_pnl", ""),
                        "source_event_time": operation.get("event_time", ""),
                        "equity": scorecards_by_runtime.get(runtime_id, {}).get("equity", ""),
                    }
                )
        else:
            account_rows.append(
                base_account_row(strategy, run_id, generated_at, trading_date)
                | {
                    "runtime_id": runtime_id,
                    "lane": account.get("lane", ""),
                    "timeframe": account.get("timeframe", ""),
                    "variant_id": account.get("variant_id", ""),
                    "event_type": "no_account_operation",
                    "test_state": state,
                    "symbol": "",
                    "direction": "",
                    "quantity": "",
                    "entry_price": "",
                    "exit_price": "",
                    "realized_pnl": "",
                    "source_event_time": "",
                    "equity": scorecards_by_runtime.get(runtime_id, {}).get("equity", ""),
                }
            )
    return signal_rows, account_rows


def build_non_runtime_rows(
    *,
    strategy: dict[str, Any],
    run_id: str,
    generated_at: str,
    trading_date: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    role = strategy["module_role"]
    if role == PLUGIN_ROLE:
        state = "plugin_ab_attached"
        detail = "Plugin/filter is attached through A/B ledger coverage and is not an independent account."
    elif role == EXTERNAL_ROLE:
        state = "not_connected"
        detail = "External AI-Trader signals require authorized read-only shadow ingestion before testing."
    else:
        state = "detector_missing"
        detail = "Research-only module has no minimum detector contract yet."
    signal_row = base_signal_row(strategy, run_id, generated_at, trading_date) | {
        "runtime_id": "",
        "lane": "",
        "timeframe": "",
        "variant_id": "",
        "test_state": state,
        "signal_count": 0,
        "input_status": role,
        "current_scanner_connected": "false",
        "source_row_count": 0,
        "plain_language_result": detail,
    }
    account_row = base_account_row(strategy, run_id, generated_at, trading_date) | {
        "runtime_id": "",
        "lane": "",
        "timeframe": "",
        "variant_id": "",
        "event_type": state,
        "test_state": state,
        "symbol": "",
        "direction": "",
        "quantity": "",
        "entry_price": "",
        "exit_price": "",
        "realized_pnl": "",
        "source_event_time": "",
        "equity": "",
    }
    return [signal_row], [account_row]


def state_from_audit(strategy: dict[str, Any], audit: dict[str, str]) -> str:
    detector_status = strategy.get("detector_status", "")
    if detector_status == "detector_missing":
        return "detector_missing"
    if not audit:
        return "not_connected" if detector_status == "not_connected" else "missing_data"
    input_status = audit.get("input_status", "")
    if input_status == "not_connected_to_current_scanner":
        return "not_connected"
    if input_status == "connected_with_signal_today":
        return "signal_generated"
    if input_status == "connected_zero_signal_today":
        return "zero_signal"
    return "missing_data"


def base_signal_row(strategy: dict[str, Any], run_id: str, generated_at: str, trading_date: date) -> dict[str, Any]:
    return {
        "schema_version": "m13.strategy-signal-ledger.v1",
        "run_id": run_id,
        "generated_at": generated_at,
        "trading_date": trading_date.isoformat(),
        "strategy_id": strategy["strategy_id"],
        "display_name": strategy.get("display_name", ""),
        "module_role": strategy["module_role"],
        "detector_id": strategy.get("detector_id", ""),
        "detector_status": strategy.get("detector_status", ""),
        "required_for_goal": bool(strategy.get("required_for_goal", False)),
        "next_action": strategy.get("next_action", ""),
    }


def base_account_row(strategy: dict[str, Any], run_id: str, generated_at: str, trading_date: date) -> dict[str, Any]:
    return {
        "schema_version": "m13.account-operation-ledger.v1",
        "run_id": run_id,
        "generated_at": generated_at,
        "trading_date": trading_date.isoformat(),
        "strategy_id": strategy["strategy_id"],
        "display_name": strategy.get("display_name", ""),
        "module_role": strategy["module_role"],
        "required_for_goal": bool(strategy.get("required_for_goal", False)),
        "next_action": strategy.get("next_action", ""),
    }


def build_scorecard_rows(
    strategies: list[dict[str, Any]],
    signal_rows: list[dict[str, Any]],
    account_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    signal_by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    account_by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in signal_rows:
        signal_by_strategy[row["strategy_id"]].append(row)
    for row in account_rows:
        account_by_strategy[row["strategy_id"]].append(row)
    rows: list[dict[str, Any]] = []
    for strategy in strategies:
        strategy_id = strategy["strategy_id"]
        signals = signal_by_strategy[strategy_id]
        accounts = account_by_strategy[strategy_id]
        states = sorted({str(row.get("test_state", "")) for row in signals if row.get("test_state")})
        blockers = [state for state in states if state in BLOCKER_STATES]
        rows.append(
            {
                "strategy_id": strategy_id,
                "display_name": strategy.get("display_name", ""),
                "module_role": strategy["module_role"],
                "required_for_goal": str(bool(strategy.get("required_for_goal", False))).lower(),
                "runtime_account_count": str(len(strategy.get("runtime_accounts", []))),
                "ledger_state_count": str(len(signals)),
                "test_states": ",".join(states),
                "goal_blocked": str(bool(strategy.get("required_for_goal", False)) and bool(blockers)).lower(),
                "blocker_states": ",".join(blockers),
                "signal_count": str(sum(int_or_zero(row.get("signal_count", 0)) for row in signals)),
                "open_count": str(sum(1 for row in accounts if row.get("event_type") == "open")),
                "close_count": str(sum(1 for row in accounts if row.get("event_type") == "close")),
                "risk_blocked_count": str(sum(1 for row in accounts if row.get("test_state") == "risk_blocked")),
                "challenge_status": challenge_status(strategy, blockers),
                "next_action": strategy.get("next_action", ""),
            }
        )
    return rows


def challenge_status(strategy: dict[str, Any], blockers: list[str]) -> str:
    role = strategy["module_role"]
    if role == PLUGIN_ROLE:
        return "plugin_ab_ledger"
    if role == EXTERNAL_ROLE:
        return "external_shadow_research_only"
    if role == RESEARCH_ROLE:
        return "research_only_blocked"
    if blockers:
        return "blocked_before_challenge"
    return "ready_for_10_day_challenge"


def build_summary(
    *,
    config: M13Config,
    registry: dict[str, Any],
    generated_at: str,
    trading_date: date,
    signal_ledger_rows: list[dict[str, Any]],
    account_ledger_rows: list[dict[str, Any]],
    scorecard_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    required_scorecards = [row for row in scorecard_rows if row["required_for_goal"] == "true"]
    blocked = [row["strategy_id"] for row in required_scorecards if row["goal_blocked"] == "true"]
    missing_ledger = [row["strategy_id"] for row in required_scorecards if row["ledger_state_count"] == "0"]
    return {
        "schema_version": "m13.daily-strategy-test-summary.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "trading_date": trading_date.isoformat(),
        "registry_ref": project_path(config.registry_path),
        "m12_29_output_ref": project_path(config.m12_29_output_dir),
        "strategy_count": len(registry["strategies"]),
        "required_strategy_count": len(required_scorecards),
        "signal_ledger_event_count": len(signal_ledger_rows),
        "account_ledger_event_count": len(account_ledger_rows),
        "open_count": sum(1 for row in account_ledger_rows if row.get("event_type") == "open"),
        "close_count": sum(1 for row in account_ledger_rows if row.get("event_type") == "close"),
        "missing_ledger_strategy_ids": missing_ledger,
        "blocked_strategy_ids": blocked,
        "all_required_have_ledger_state": not missing_ledger,
        "ready_for_complete_reliable_testing": not missing_ledger and not blocked,
        "min_challenge_trading_days": config.min_challenge_trading_days,
        "paper_simulated_only": True,
        "trading_connection": False,
        "real_money_actions": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "ai_trader_copy_trading": False,
        "plain_language_result": (
            f"M13 wrote daily ledger states for {len(signal_ledger_rows)} strategy/account rows. "
            f"{len(blocked)} required strategies or modules are still blocked before a reliable 10-day challenge."
        ),
    }


def build_goal_status(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "m13.goal-status.v1",
        "goal_name": "Build a real daily strategy testing loop for Price-Action-Trader",
        "generated_at": summary["generated_at"],
        "trading_date": summary["trading_date"],
        "goal_complete": bool(summary["ready_for_complete_reliable_testing"]),
        "continue_without_stopping": not bool(summary["ready_for_complete_reliable_testing"]),
        "blocked_strategy_ids": summary["blocked_strategy_ids"],
        "missing_ledger_strategy_ids": summary["missing_ledger_strategy_ids"],
        "next_action": (
            "Connect missing detector/input adapters and rerun the daily ledger."
            if not summary["ready_for_complete_reliable_testing"]
            else "Start or continue the 10 trading-day challenge."
        ),
    }


def build_goal_prompt_md() -> str:
    return """# M13 Codex Goal

Goal: Build a real daily strategy testing loop for Price-Action-Trader.

Hard constraints:
- Follow AGENTS.md, plans/active-plan.md, docs/implement.md, docs/status.md.
- Use Simplified Chinese for user-facing updates.
- Do not connect real broker accounts, place real orders, or enable real-money execution.
- Do not fabricate market data, trades, backtest results, paper results, or approvals.
- Every run must distinguish: not_connected, detector_missing, missing_data, zero_signal, signal_generated, open, close, risk_blocked, plugin_ab_attached.

Primary objective:
Every M10/M12 strategy or module must enter an auditable daily test ledger. A strategy is not tested today unless it has a ledger event for the current New York trading date.
"""


def resolve_trading_date(config: M13Config, generated_at: str, trading_date: str | date | None) -> date:
    if isinstance(trading_date, date):
        return trading_date
    if isinstance(trading_date, str) and trading_date:
        return date.fromisoformat(trading_date)
    dashboard_data = config.m12_29_output_dir / "m12_32_minute_readonly_dashboard_data.json"
    if dashboard_data.exists():
        payload = json.loads(dashboard_data.read_text(encoding="utf-8"))
        scan_date = payload.get("summary", {}).get("scan_date") or payload.get("scan_date")
        if scan_date:
            return date.fromisoformat(str(scan_date))
    return datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date()


def load_m12_account_input_audit(m12_output_dir: Path) -> list[dict[str, str]]:
    path = m12_output_dir / "m12_46_account_input_audit.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [dict(row) for row in payload.get("rows", [])]


def filter_rows_for_trading_date(rows: list[dict[str, Any]], trading_date: date) -> list[dict[str, Any]]:
    return [row for row in rows if iso_to_ny_trading_date(str(row.get("event_time", ""))) == trading_date]


def iso_to_ny_trading_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
