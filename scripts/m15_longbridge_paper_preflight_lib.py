#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_paper_preflight.json"
DEFAULT_DAILY_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
)
DEFAULT_GATE_PATH = DEFAULT_DAILY_DIR / "m14_strategy_challenge" / "m14_paper_trial_gate.json"
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_longbridge_paper_preflight"
PREFLIGHT_JSON = "m15_longbridge_paper_preflight.json"
PREFLIGHT_MD = "m15_longbridge_paper_preflight.md"
PAPER_CANDIDATE_ACTIONS = {"advance_internal_sim", "risk_limited_advance", "paper_candidate"}
SUPPORTED_ORDER_TYPES = {"limit", "trigger_limit"}


@dataclass(frozen=True, slots=True)
class M15PaperPreflightConfig:
    title: str
    stage: str
    paper_gate_path: Path
    output_dir: Path
    cli_name: str
    market: str
    default_order_type: str
    allowed_order_types: tuple[str, ...]
    breakout_order_type: str
    regular_hours_only: bool
    token_mode: str
    live_token_allowed: bool
    kill_switch_enabled: bool
    max_orders_per_day: int
    max_risk_per_order: str
    max_total_exposure: str
    paper_account_equity: str
    min_cash_reserve: str
    max_symbol_exposure: str
    allow_fractional_shares: bool
    allow_short_selling: bool
    allow_options: bool
    include_all_non_repair_paper_candidates: bool
    first_order_single_strategy_only: bool
    approved_strategy_whitelist: tuple[str, ...]
    first_paper_order_strategy_whitelist: tuple[str, ...]
    runtime_whitelist: tuple[str, ...]
    symbol_whitelist: tuple[str, ...]


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M15PaperPreflightConfig:
    config_path = resolve_repo_path(path)
    if config_path.exists():
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        payload = {}
    safety = payload.get("safety_controls", {})
    candidate_policy = payload.get("candidate_policy", {})
    whitelists = payload.get("whitelists", {})
    return M15PaperPreflightConfig(
        title=payload.get("title", "M15 Longbridge paper preflight"),
        stage=payload.get("stage", "M15.longbridge_paper_preflight"),
        paper_gate_path=resolve_repo_path(payload.get("paper_gate_path", DEFAULT_GATE_PATH)),
        output_dir=resolve_repo_path(payload.get("output_dir", DEFAULT_OUTPUT_DIR)),
        cli_name=payload.get("cli_name", "longbridge"),
        market=payload.get("market", "US"),
        default_order_type=payload.get("default_order_type", "limit"),
        allowed_order_types=tuple(str(item) for item in payload.get("allowed_order_types", ["limit"])),
        breakout_order_type=str(payload.get("breakout_order_type", "trigger_limit")),
        regular_hours_only=bool(payload.get("regular_hours_only", True)),
        token_mode=str(safety.get("token_mode", payload.get("token_mode", "paper"))),
        live_token_allowed=bool(safety.get("live_token_allowed", False)),
        kill_switch_enabled=bool(safety.get("kill_switch_enabled", True)),
        max_orders_per_day=int(safety.get("max_orders_per_day", 6)),
        max_risk_per_order=str(safety.get("max_risk_per_order", "20")),
        max_total_exposure=str(safety.get("max_total_exposure", "6000")),
        paper_account_equity=str(safety.get("paper_account_equity", "10000")),
        min_cash_reserve=str(safety.get("min_cash_reserve", "4000")),
        max_symbol_exposure=str(safety.get("max_symbol_exposure", "1500")),
        allow_fractional_shares=bool(safety.get("allow_fractional_shares", False)),
        allow_short_selling=bool(safety.get("allow_short_selling", False)),
        allow_options=bool(safety.get("allow_options", False)),
        include_all_non_repair_paper_candidates=bool(candidate_policy.get("include_all_non_repair_paper_candidates", False)),
        first_order_single_strategy_only=bool(candidate_policy.get("first_order_single_strategy_only", True)),
        approved_strategy_whitelist=tuple(str(item) for item in whitelists.get("approved_strategy_whitelist", [])),
        first_paper_order_strategy_whitelist=tuple(
            str(item) for item in whitelists.get("first_paper_order_strategy_whitelist", [])
        ),
        runtime_whitelist=tuple(str(item) for item in whitelists.get("runtime_whitelist", [])),
        symbol_whitelist=tuple(str(item) for item in whitelists.get("symbol_whitelist", [])),
    )


def run_m15_longbridge_paper_preflight(
    config: M15PaperPreflightConfig | None = None,
    *,
    generated_at: str | None = None,
    cli_probe: Callable[[str], dict[str, str]] | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    preflight = build_preflight(config, generated_at=generated_at, cli_probe=cli_probe or probe_cli)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / PREFLIGHT_JSON, preflight)
    (config.output_dir / PREFLIGHT_MD).write_text(render_markdown(preflight), encoding="utf-8")
    return preflight


def build_preflight(
    config: M15PaperPreflightConfig,
    *,
    generated_at: str,
    cli_probe: Callable[[str], dict[str, str]],
) -> dict[str, Any]:
    gate = read_json(config.paper_gate_path)
    summary = read_json(config.paper_gate_path.with_name("m14_strategy_challenge_summary.json"))
    dashboard = read_json(resolve_repo_path(summary.get("m12_dashboard_ref", ""))) if summary.get("m12_dashboard_ref") else {}
    quote_source = current_quote_source(summary, dashboard)
    scan_date = current_scan_date(dashboard)
    m14_trading_date = str(summary.get("trading_date", ""))
    gate_rows = list(gate.get("rows", []))
    cli_state = cli_probe(config.cli_name)
    policy_blockers = config_policy_blockers(config)
    fallback_block = summary_has_fallback_or_no_fetch(summary, dashboard)
    quote_source_blockers = quote_source_policy_blockers(quote_source)
    current_day_blockers = current_day_policy_blockers(scan_date, m14_trading_date)
    blocked_rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    if not fallback_block and not policy_blockers and not quote_source_blockers and not current_day_blockers:
        for row in gate_rows:
            if not is_paper_candidate(row):
                continue
            row_blockers = candidate_blockers(row, config)
            if row_blockers:
                blocked_rows.append(build_blocked_candidate(row, row_blockers))
                continue
            candidates.append(build_candidate(row, config))
    first_order_candidates = [row for row in candidates if row["eligible_for_first_paper_order"]]
    if policy_blockers:
        status = "blocked_preflight_policy"
    elif fallback_block:
        status = "blocked_fallback_or_no_fetch_data"
    elif quote_source_blockers:
        status = "blocked_quote_source_not_longbridge"
    elif current_day_blockers:
        status = "blocked_current_day_m14_not_recomputed"
    elif not candidates:
        status = "blocked_no_runtime_candidates"
    elif not first_order_candidates:
        status = "blocked_no_first_order_candidate"
    elif cli_state["available"] != "true":
        status = "blocked_cli_missing"
    else:
        status = "ready_for_user_paper_credential_approval"
    return {
        "schema_version": "m15.longbridge-paper-preflight.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at,
        "paper_gate_ref": project_path(config.paper_gate_path),
        "paper_preflight_status": status,
        "quote_source": quote_source,
        "quote_source_blockers": quote_source_blockers,
        "fresh_longbridge_quote_required": True,
        "scan_date": scan_date,
        "m14_trading_date": m14_trading_date,
        "current_day_blockers": current_day_blockers,
        "longbridge_cli": cli_state,
        "candidate_count": len(candidates),
        "first_paper_order_candidate_count": len(first_order_candidates),
        "candidates": candidates,
        "blocked_candidate_count": len(blocked_rows),
        "blocked_candidates": blocked_rows,
        "fallback_or_no_fetch_data": fallback_block,
        "policy_blockers": policy_blockers,
        "paper_token_required": True,
        "paper_token_only": True,
        "token_mode": config.token_mode,
        "live_token_allowed": config.live_token_allowed,
        "credential_injection_allowed_now": False,
        "first_paper_order_requires_user_approval": True,
        "include_all_non_repair_paper_candidates": config.include_all_non_repair_paper_candidates,
        "first_order_single_strategy_only": config.first_order_single_strategy_only,
        "first_paper_order_strategy_whitelist": list(config.first_paper_order_strategy_whitelist),
        "approved_strategy_whitelist": list(config.approved_strategy_whitelist),
        "runtime_whitelist": list(config.runtime_whitelist),
        "symbol_whitelist": list(config.symbol_whitelist),
        "default_order_type": config.default_order_type,
        "allowed_order_types": list(config.allowed_order_types),
        "breakout_order_type": config.breakout_order_type,
        "limit_orders_only": False,
        "breakout_orders_allowed": "trigger_limit" in set(config.allowed_order_types),
        "regular_hours_only": config.regular_hours_only,
        "us_paper_prepost_supported": False,
        "kill_switch_enabled": config.kill_switch_enabled,
        "max_orders_per_day": config.max_orders_per_day,
        "max_risk_per_order": config.max_risk_per_order,
        "max_total_exposure": config.max_total_exposure,
        "paper_account_equity": config.paper_account_equity,
        "min_cash_reserve": config.min_cash_reserve,
        "max_symbol_exposure": config.max_symbol_exposure,
        "allow_fractional_shares": config.allow_fractional_shares,
        "allow_short_selling": config.allow_short_selling,
        "allow_options": config.allow_options,
        "broker_connection_attempted": False,
        "order_submitted": False,
        "real_money_actions": False,
        "live_execution": False,
        "plain_language_result": plain_result(status, candidates, cli_state, policy_blockers, quote_source_blockers, current_day_blockers),
    }


def is_paper_candidate(row: dict[str, Any]) -> bool:
    action_state = str(row.get("action_state") or row.get("decision") or "")
    gate = str(row.get("paper_trial_gate", ""))
    reason = str(row.get("gate_reason", "")).lower()
    if any(token in reason for token in ("fallback", "no-fetch", "no_refresh", "no-refresh")):
        return False
    if gate in {"pause_runtime", "repair_now"}:
        return False
    return bool(row.get("paper_candidate", False)) and action_state in PAPER_CANDIDATE_ACTIONS


def config_policy_blockers(config: M15PaperPreflightConfig) -> list[str]:
    blockers: list[str] = []
    if config.token_mode != "paper":
        blockers.append("paper_token_only_required")
    if config.live_token_allowed:
        blockers.append("live_token_forbidden")
    if config.default_order_type not in SUPPORTED_ORDER_TYPES:
        blockers.append("supported_order_type_required")
    if not config.allowed_order_types:
        blockers.append("allowed_order_types_required")
    if set(config.allowed_order_types) - SUPPORTED_ORDER_TYPES:
        blockers.append("unsupported_order_type_configured")
    if "limit" not in set(config.allowed_order_types):
        blockers.append("limit_order_support_required")
    if "trigger_limit" not in set(config.allowed_order_types):
        blockers.append("breakout_trigger_limit_order_support_required")
    if config.breakout_order_type not in set(config.allowed_order_types):
        blockers.append("breakout_order_type_must_be_allowed")
    if not config.regular_hours_only:
        blockers.append("us_regular_hours_only_required")
    if not config.kill_switch_enabled:
        blockers.append("kill_switch_required")
    if config.max_orders_per_day <= 0:
        blockers.append("max_orders_per_day_required")
    if config.allow_fractional_shares:
        blockers.append("fractional_shares_forbidden_now")
    if config.allow_short_selling:
        blockers.append("short_selling_forbidden_now")
    if config.allow_options:
        blockers.append("options_forbidden_now")
    return blockers


def candidate_blockers(row: dict[str, Any], config: M15PaperPreflightConfig) -> list[str]:
    blockers: list[str] = []
    strategy_id = str(row.get("strategy_id", ""))
    runtime_id = str(row.get("runtime_id", ""))
    symbol = str(row.get("symbol", ""))
    if config.approved_strategy_whitelist and strategy_id not in set(config.approved_strategy_whitelist):
        blockers.append("strategy_not_in_first_batch_whitelist")
    if config.runtime_whitelist and runtime_id not in set(config.runtime_whitelist):
        blockers.append("runtime_not_in_first_batch_whitelist")
    if symbol and config.symbol_whitelist and symbol not in set(config.symbol_whitelist):
        blockers.append("symbol_not_in_whitelist")
    return blockers


def build_blocked_candidate(row: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "runtime_id": str(row.get("runtime_id", "")),
        "strategy_id": str(row.get("strategy_id", "")),
        "timeframe": str(row.get("timeframe", "")),
        "symbol": str(row.get("symbol", "")),
        "action_state": str(row.get("action_state", "")),
        "paper_trial_gate": str(row.get("paper_trial_gate", "")),
        "blockers": blockers,
        "paper_order_preview_allowed": False,
        "broker_connection_attempted": False,
        "order_submitted": False,
    }


def build_candidate(row: dict[str, Any], config: M15PaperPreflightConfig) -> dict[str, Any]:
    strategy_id = str(row.get("strategy_id", ""))
    runtime_id = str(row.get("runtime_id", ""))
    symbol = str(row.get("symbol", ""))
    eligible_first_order = (
        strategy_id in set(config.first_paper_order_strategy_whitelist)
        if config.first_order_single_strategy_only and config.first_paper_order_strategy_whitelist
        else True
    )
    return {
        "runtime_id": runtime_id,
        "strategy_id": strategy_id,
        "timeframe": str(row.get("timeframe", "")),
        "symbol": symbol,
        "action_state": str(row.get("action_state", "")),
        "position_size_multiplier": str(row.get("position_size_multiplier", "1")),
        "market": config.market,
        "order_type": config.default_order_type,
        "allowed_order_types": list(config.allowed_order_types),
        "breakout_order_type": config.breakout_order_type,
        "limit_orders_only": False,
        "breakout_orders_allowed": "trigger_limit" in set(config.allowed_order_types),
        "regular_hours_only": config.regular_hours_only,
        "us_paper_prepost_supported": False,
        "whitelist_runtime_required": True,
        "strategy_whitelisted": (not config.approved_strategy_whitelist) or strategy_id in set(config.approved_strategy_whitelist),
        "runtime_whitelisted": (not config.runtime_whitelist) or runtime_id in set(config.runtime_whitelist),
        "symbol_whitelisted": (not symbol) or (not config.symbol_whitelist) or symbol in set(config.symbol_whitelist),
        "eligible_for_first_paper_order": eligible_first_order,
        "first_paper_order_strategy_only": list(config.first_paper_order_strategy_whitelist),
        "paper_order_preview_allowed": eligible_first_order,
        "kill_switch_required": True,
        "kill_switch_enabled": config.kill_switch_enabled,
        "max_orders_per_day": config.max_orders_per_day,
        "max_risk_per_order": config.max_risk_per_order,
        "max_total_exposure": config.max_total_exposure,
        "paper_account_equity": config.paper_account_equity,
        "min_cash_reserve": config.min_cash_reserve,
        "max_symbol_exposure": config.max_symbol_exposure,
        "allow_fractional_shares": config.allow_fractional_shares,
        "allow_short_selling": config.allow_short_selling,
        "allow_options": config.allow_options,
        "paper_token_required": True,
        "paper_token_only": True,
        "live_token_allowed": config.live_token_allowed,
        "credential_injection_allowed_now": False,
        "first_paper_order_requires_user_approval": True,
        "broker_connection_attempted": False,
        "order_submitted": False,
    }


def probe_cli(cli_name: str) -> dict[str, str]:
    path = shutil.which(cli_name) or ""
    if not path:
        return {"available": "false", "path": "", "version": "", "error": "cli_not_found"}
    try:
        completed = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": "false", "path": path, "version": "", "error": str(exc)}
    output = (completed.stdout or completed.stderr or "").strip()
    return {"available": "true", "path": path, "version": output, "error": ""}


def current_quote_source(summary: dict[str, Any], dashboard: dict[str, Any]) -> str:
    dashboard_summary = dashboard.get("summary", {}) if isinstance(dashboard.get("summary", {}), dict) else {}
    return str(
        dashboard_summary.get("quote_source")
        or summary.get("m12_quote_source")
        or summary.get("quote_source")
        or ""
    )


def current_scan_date(dashboard: dict[str, Any]) -> str:
    dashboard_summary = dashboard.get("summary", {}) if isinstance(dashboard.get("summary", {}), dict) else {}
    return str(dashboard_summary.get("scan_date", ""))


def quote_source_policy_blockers(quote_source: str) -> list[str]:
    if quote_source == "longbridge_quote_readonly":
        return []
    if not quote_source:
        return ["quote_source_missing"]
    return ["quote_source_not_longbridge_readonly"]


def current_day_policy_blockers(scan_date: str, m14_trading_date: str) -> list[str]:
    if scan_date and m14_trading_date and scan_date != m14_trading_date:
        return ["m14_not_recomputed_for_current_scan_date"]
    return []


def summary_has_fallback_or_no_fetch(summary: dict[str, Any], dashboard: dict[str, Any] | None = None) -> bool:
    dashboard = dashboard or {}
    dashboard_summary = dashboard.get("summary", {}) if isinstance(dashboard.get("summary", {}), dict) else {}
    text = " ".join(
        str(summary.get(key, ""))
        for key in ("m12_quote_source", "data_freshness_warning", "data_quality_state")
    ).lower()
    text += " " + " ".join(
        str(dashboard_summary.get(key, ""))
        for key in ("quote_source", "data_freshness_warning", "data_quality_state")
    ).lower()
    return any(token in text for token in ("fallback", "no-fetch", "no_fetch", "no-refresh", "no_refresh"))


def plain_result(
    status: str,
    candidates: list[dict[str, Any]],
    cli_state: dict[str, str],
    policy_blockers: list[str] | None = None,
    quote_source_blockers: list[str] | None = None,
    current_day_blockers: list[str] | None = None,
) -> str:
    if status == "ready_for_user_paper_credential_approval":
        first_count = sum(1 for row in candidates if row.get("eligible_for_first_paper_order"))
        return (
            "长桥模拟账户预演已准备好等待用户批准；"
            f"{len(candidates)} 个非修复运行单元可进入模拟账户测试名单，"
            f"{first_count} 个可在用户批准后进入提交链路。当前按 10000 美元共享资金、整股、只做多、普通限价/突破触发限价规则预演。"
        )
    if status == "blocked_preflight_policy":
        return f"长桥模拟账户预演被安全策略阻断：{', '.join(policy_blockers or [])}。"
    if status == "blocked_fallback_or_no_fetch_data":
        return "长桥模拟账户预演被阻断：当前 M14/M12 数据仍是备用行情或 no-fetch，必须等 M12.47 在交易窗口拉起 fresh refresh。"
    if status == "blocked_quote_source_not_longbridge":
        return f"长桥模拟账户预演被阻断：当前看板行情来源不是 longbridge_quote_readonly（{', '.join(quote_source_blockers or [])}）。"
    if status == "blocked_current_day_m14_not_recomputed":
        return f"长桥模拟账户预演被阻断：M14 还没有重算到当前看板交易日（{', '.join(current_day_blockers or [])}）。"
    if status == "blocked_no_first_order_candidate":
        return "长桥模拟账户预演被阻断：没有符合用户批准后提交条件的非修复运行单元。"
    if status == "blocked_cli_missing":
        return f"{len(candidates)} 个运行单元符合白名单，但本地 Longbridge CLI 不可用：{cli_state.get('error', '')}。"
    return "当前没有运行单元符合长桥模拟账户预演；需要先修复数据、风控或白名单。"


def render_markdown(preflight: dict[str, Any]) -> str:
    lines = [
        "# M15 Longbridge Paper Preflight",
        "",
        f"- Status: `{preflight['paper_preflight_status']}`",
        f"- Quote source: `{preflight.get('quote_source', '')}`",
        f"- Scan date / M14 trading date: `{preflight.get('scan_date', '')}` / `{preflight.get('m14_trading_date', '')}`",
        f"- Candidate runtimes: `{preflight['candidate_count']}`",
        f"- First paper order candidates: `{preflight['first_paper_order_candidate_count']}`",
        f"- CLI: `{preflight['longbridge_cli'].get('path') or 'missing'}` `{preflight['longbridge_cli'].get('version', '')}`",
        "- Boundary: paper token only, live token forbidden, no credential injection, no broker connection, no order submission.",
        f"- Paper account model: `{preflight.get('paper_account_equity', '')}` USD equity, max exposure `{preflight.get('max_total_exposure', '')}`, max symbol exposure `{preflight.get('max_symbol_exposure', '')}`.",
        "- Fractional shares: disabled. Short selling: disabled. Options: disabled.",
        f"- Allowed order types: `{', '.join(preflight.get('allowed_order_types', []))}`.",
        "- US paper path uses regular trading hours only; pre-market and post-market paper orders stay disabled.",
        f"- First paper order whitelist: `{', '.join(preflight['first_paper_order_strategy_whitelist'])}`",
        f"- Policy blockers: `{', '.join(preflight['policy_blockers']) or 'none'}`",
        f"- Quote source blockers: `{', '.join(preflight.get('quote_source_blockers', [])) or 'none'}`",
        f"- Current-day blockers: `{', '.join(preflight.get('current_day_blockers', [])) or 'none'}`",
        "",
        "| Runtime | Strategy | Action | Size | Order | First paper order |",
        "|---|---|---|---:|---|---|",
    ]
    for row in preflight["candidates"]:
        lines.append(
            f"| {row['runtime_id']} | {row['strategy_id']} | {row['action_state']} | {row['position_size_multiplier']} | {row['order_type']} | {row['eligible_for_first_paper_order']} |"
        )
    if preflight["blocked_candidates"]:
        lines.extend(["", "## Blocked Whitelist Rows", "", "| Runtime | Strategy | Blockers |", "|---|---|---|"])
        for row in preflight["blocked_candidates"]:
            lines.append(f"| {row['runtime_id']} | {row['strategy_id']} | {', '.join(row['blockers'])} |")
    return "\n".join(lines) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
