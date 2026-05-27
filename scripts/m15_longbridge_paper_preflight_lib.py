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


@dataclass(frozen=True, slots=True)
class M15PaperPreflightConfig:
    title: str
    stage: str
    paper_gate_path: Path
    output_dir: Path
    cli_name: str
    market: str
    default_order_type: str
    regular_hours_only: bool


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
    return M15PaperPreflightConfig(
        title=payload.get("title", "M15 Longbridge paper preflight"),
        stage=payload.get("stage", "M15.longbridge_paper_preflight"),
        paper_gate_path=resolve_repo_path(payload.get("paper_gate_path", DEFAULT_GATE_PATH)),
        output_dir=resolve_repo_path(payload.get("output_dir", DEFAULT_OUTPUT_DIR)),
        cli_name=payload.get("cli_name", "longbridge"),
        market=payload.get("market", "US"),
        default_order_type=payload.get("default_order_type", "limit"),
        regular_hours_only=bool(payload.get("regular_hours_only", True)),
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
    gate_rows = list(gate.get("rows", []))
    cli_state = cli_probe(config.cli_name)
    fallback_block = summary_has_fallback_or_no_fetch(summary)
    candidates = [] if fallback_block else [build_candidate(row, config) for row in gate_rows if is_paper_candidate(row)]
    if fallback_block:
        status = "blocked_fallback_or_no_fetch_data"
    elif not candidates:
        status = "blocked_no_runtime_candidates"
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
        "longbridge_cli": cli_state,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "fallback_or_no_fetch_data": fallback_block,
        "paper_token_required": True,
        "live_token_allowed": False,
        "credential_injection_allowed_now": False,
        "first_paper_order_requires_user_approval": True,
        "broker_connection_attempted": False,
        "order_submitted": False,
        "real_money_actions": False,
        "live_execution": False,
        "plain_language_result": plain_result(status, candidates, cli_state),
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


def build_candidate(row: dict[str, Any], config: M15PaperPreflightConfig) -> dict[str, Any]:
    return {
        "runtime_id": str(row.get("runtime_id", "")),
        "strategy_id": str(row.get("strategy_id", "")),
        "timeframe": str(row.get("timeframe", "")),
        "action_state": str(row.get("action_state", "")),
        "position_size_multiplier": str(row.get("position_size_multiplier", "1")),
        "market": config.market,
        "order_type": config.default_order_type,
        "regular_hours_only": config.regular_hours_only,
        "us_paper_prepost_supported": False,
        "whitelist_runtime_required": True,
        "kill_switch_required": True,
        "paper_token_required": True,
        "live_token_allowed": False,
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


def summary_has_fallback_or_no_fetch(summary: dict[str, Any]) -> bool:
    text = " ".join(
        str(summary.get(key, ""))
        for key in ("m12_quote_source", "data_freshness_warning", "data_quality_state")
    ).lower()
    return any(token in text for token in ("fallback", "no-fetch", "no_fetch", "no-refresh", "no_refresh"))


def plain_result(status: str, candidates: list[dict[str, Any]], cli_state: dict[str, str]) -> str:
    if status == "ready_for_user_paper_credential_approval":
        return f"Longbridge paper preflight is ready for user approval; {len(candidates)} runtime candidates are paper-token-only dry-run candidates."
    if status == "blocked_fallback_or_no_fetch_data":
        return "Longbridge paper preflight is blocked because current M14/M12 data is fallback/no-fetch; paper candidates require fully refreshed data."
    if status == "blocked_cli_missing":
        return f"{len(candidates)} runtime candidates exist, but the Longbridge CLI is not available: {cli_state.get('error', '')}."
    return "No runtime currently qualifies for Longbridge paper preflight; repair or pause rows are excluded."


def render_markdown(preflight: dict[str, Any]) -> str:
    lines = [
        "# M15 Longbridge Paper Preflight",
        "",
        f"- Status: `{preflight['paper_preflight_status']}`",
        f"- Candidate runtimes: `{preflight['candidate_count']}`",
        f"- CLI: `{preflight['longbridge_cli'].get('path') or 'missing'}` `{preflight['longbridge_cli'].get('version', '')}`",
        "- Boundary: paper token only, live token forbidden, no credential injection, no broker connection, no order submission.",
        "- US paper path uses regular trading hours only; pre-market and post-market paper orders stay disabled.",
        "",
        "| Runtime | Strategy | Action | Size | Order |",
        "|---|---|---|---:|---|",
    ]
    for row in preflight["candidates"]:
        lines.append(
            f"| {row['runtime_id']} | {row['strategy_id']} | {row['action_state']} | {row['position_size_multiplier']} | {row['order_type']} |"
        )
    return "\n".join(lines) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
