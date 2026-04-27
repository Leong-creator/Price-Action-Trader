#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


M10_DIR = ROOT / "reports" / "strategy_lab" / "m10_price_action_strategy_refresh"
M12_BASE_DIR = M10_DIR / "m12_read_only_pipeline"
M12_0_DIR = M12_BASE_DIR / "m12_0_auth_preflight"

READONLY_COMMAND_ALLOWLIST = frozenset({"check", "quote", "kline", "subscriptions"})
FORBIDDEN_COMMANDS = (
    "order",
    "assets",
    "positions",
    "portfolio",
    "statement",
    "cash-flow",
    "max-qty",
    "dca",
    "fund-positions",
    "profit-analysis",
)
BOUNDARY_FALSE_FLAGS = ("broker_connection", "real_orders", "live_execution", "paper_trading_approval")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    command: list[str]
    status: str
    returncode: int | None
    payload_summary: dict[str, Any]
    error: str


def run_m12_readonly_auth_preflight(
    output_dir: Path = M12_0_DIR,
    *,
    probe_symbol: str = "SPY.US",
    generated_at: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    boundary = build_runtime_boundary()
    cli_path = shutil.which("longbridge")
    probes: list[ProbeResult] = []
    if cli_path is None:
        probes.append(
            ProbeResult(
                name="cli_available",
                command=["longbridge"],
                status="missing_cli",
                returncode=None,
                payload_summary={},
                error="longbridge CLI is not installed or not on PATH",
            )
        )
        auth_status = "missing_cli"
    else:
        probes.extend(
            [
                _run_readonly_probe(cli_path, "auth_check", ["check", "--format", "json"]),
                _run_readonly_probe(cli_path, "quote_snapshot", ["quote", probe_symbol, "--format", "json"]),
                _run_readonly_probe(cli_path, "latest_kline", ["kline", probe_symbol, "--period", "day", "--count", "1", "--format", "json"]),
                _run_readonly_probe(cli_path, "subscription_snapshot", ["subscriptions", "--format", "json"]),
            ]
        )
        auth_status = _derive_auth_status(probes)

    artifact = {
        "schema_version": "m12.readonly-auth-preflight.v1",
        "stage": "M12.0.readonly_auth_preflight",
        "generated_at": generated_at,
        "probe_symbol": probe_symbol,
        "longbridge_cli_path": cli_path,
        "auth_status": auth_status,
        "runtime_boundary": boundary,
        "probes": [probe_to_json(probe) for probe in probes],
        "next_action": next_action_for(auth_status),
    }
    validate_preflight_artifact(artifact)
    write_json(output_dir / "m12_0_runtime_boundary.json", artifact)
    (output_dir / "m12_0_longbridge_readonly_auth_check.md").write_text(build_report(artifact), encoding="utf-8")
    return artifact


def build_runtime_boundary() -> dict[str, Any]:
    return {
        "mode": "longbridge_simulated_readonly",
        "paper_simulated_only": True,
        "paper_trading_approval": False,
        "broker_connection": False,
        "real_orders": False,
        "live_execution": False,
        "allowed_cli_commands": sorted(READONLY_COMMAND_ALLOWLIST),
        "forbidden_cli_commands": list(FORBIDDEN_COMMANDS),
        "allowed_capabilities": [
            "connectivity_check",
            "quote_snapshot",
            "latest_kline_snapshot",
            "subscription_status_read",
        ],
        "explicitly_excluded_capabilities": [
            "trading",
            "account_assets",
            "account_positions",
            "order_submit_cancel_replace",
            "cash_or_margin_information",
            "paper_or_live_execution",
        ],
    }


def _run_readonly_probe(cli_path: str, name: str, args: list[str]) -> ProbeResult:
    _assert_readonly_command(args)
    command = [cli_path, *args]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    stdout = completed.stdout.strip()
    stderr = clean_cli_text(completed.stderr.strip())
    if completed.returncode != 0:
        return ProbeResult(
            name=name,
            command=["longbridge", *args],
            status="failed",
            returncode=completed.returncode,
            payload_summary={},
            error=(stderr or clean_cli_text(stdout))[:500],
        )
    payload_summary: dict[str, Any]
    try:
        payload = json.loads(stdout) if stdout else {}
        payload_summary = summarize_payload(name, payload)
    except json.JSONDecodeError:
        payload_summary = {"raw_text_length": len(stdout)}
    return ProbeResult(
        name=name,
        command=["longbridge", *args],
        status="ok",
        returncode=completed.returncode,
        payload_summary=payload_summary,
        error=stderr[:500],
    )


def _assert_readonly_command(args: list[str]) -> None:
    if not args:
        raise ValueError("longbridge command args cannot be empty")
    command = args[0]
    if command not in READONLY_COMMAND_ALLOWLIST:
        raise ValueError(f"longbridge command is not allowed in readonly preflight: {command}")
    if any(token in FORBIDDEN_COMMANDS for token in args):
        raise ValueError(f"forbidden longbridge command token in readonly preflight: {args}")


def clean_cli_text(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value)


def summarize_payload(name: str, payload: Any) -> dict[str, Any]:
    if name == "auth_check" and isinstance(payload, dict):
        session = payload.get("session", {}) if isinstance(payload.get("session"), dict) else {}
        connectivity = payload.get("connectivity", {}) if isinstance(payload.get("connectivity"), dict) else {}
        return {
            "token": session.get("token", "unknown"),
            "connectivity_ok": all(bool(item.get("ok")) for item in connectivity.values() if isinstance(item, dict)),
            "active_region": payload.get("region", {}).get("active") if isinstance(payload.get("region"), dict) else None,
        }
    if isinstance(payload, list):
        first = payload[0] if payload else {}
        return {
            "row_count": len(payload),
            "first_keys": sorted(first.keys()) if isinstance(first, dict) else [],
            "first_symbol": first.get("symbol") if isinstance(first, dict) else None,
        }
    if isinstance(payload, dict):
        return {"keys": sorted(payload.keys())}
    return {"type": type(payload).__name__}


def _derive_auth_status(probes: list[ProbeResult]) -> str:
    by_name = {probe.name: probe for probe in probes}
    auth_probe = by_name.get("auth_check")
    if auth_probe is None:
        return "unknown"
    if auth_probe.status != "ok":
        return "auth_required_or_connectivity_failed"
    if auth_probe.payload_summary.get("token") == "valid":
        quote_ok = by_name.get("quote_snapshot", ProbeResult("", [], "", None, {}, "")).status == "ok"
        kline_ok = by_name.get("latest_kline", ProbeResult("", [], "", None, {}, "")).status == "ok"
        if quote_ok and kline_ok:
            return "valid_readonly_market_data"
        return "valid_token_market_data_probe_partial"
    return "token_not_valid"


def next_action_for(auth_status: str) -> str:
    if auth_status == "valid_readonly_market_data":
        return "ready_for_m12_1_readonly_feed"
    if auth_status == "missing_cli":
        return "install_longbridge_cli_then_run_longbridge_auth_login"
    return "run_longbridge_auth_login_with_quote_kline_market_data_permissions_only"


def probe_to_json(probe: ProbeResult) -> dict[str, Any]:
    return {
        "name": probe.name,
        "command": probe.command,
        "status": probe.status,
        "returncode": probe.returncode,
        "payload_summary": probe.payload_summary,
        "error": probe.error,
    }


def validate_preflight_artifact(artifact: dict[str, Any]) -> None:
    boundary = artifact["runtime_boundary"]
    for key in BOUNDARY_FALSE_FLAGS:
        if boundary.get(key) is not False:
            raise ValueError(f"M12.0 boundary must keep {key}=false")
    for probe in artifact["probes"]:
        command = probe.get("command", [])
        if len(command) > 1 and command[0] == "longbridge":
            _assert_readonly_command(command[1:])


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_report(artifact: dict[str, Any]) -> str:
    boundary = artifact["runtime_boundary"]
    lines = [
        "# M12.0 Longbridge Read-only Auth Check",
        "",
        "## 结论",
        "",
        f"- auth status: `{artifact['auth_status']}`",
        f"- next action: `{artifact['next_action']}`",
        "- 本阶段只验证 Longbridge 行情/K 线只读能力，不接交易账户、不下单、不批准 paper/live。",
        "",
        "## 运行边界",
        "",
        f"- paper_simulated_only: `{str(boundary['paper_simulated_only']).lower()}`",
        f"- paper_trading_approval: `{str(boundary['paper_trading_approval']).lower()}`",
        f"- broker_connection: `{str(boundary['broker_connection']).lower()}`",
        f"- real_orders: `{str(boundary['real_orders']).lower()}`",
        f"- live_execution: `{str(boundary['live_execution']).lower()}`",
        f"- allowed CLI commands: `{' / '.join(boundary['allowed_cli_commands'])}`",
        "- 禁止调用交易、资产、持仓、现金、融资、订单相关命令。",
        "",
        "## 探针结果",
        "",
        "| Probe | Status | Summary |",
        "|---|---|---|",
    ]
    for probe in artifact["probes"]:
        lines.append(f"| {probe['name']} | `{probe['status']}` | `{json.dumps(probe['payload_summary'], ensure_ascii=False, sort_keys=True)}` |")
    lines.extend(
        [
            "",
            "## M12.1 Handoff",
            "",
            "- 若 auth status 为 `valid_readonly_market_data`，下一阶段可以实现只读 bar-close feed。",
            "- 若 auth status 不是 valid，先执行 `longbridge auth login`，只授权 quote / K-line / market data。",
            "- 不允许为了通过预检而调用任何账户、资产、持仓或订单命令。",
        ]
    )
    return "\n".join(lines) + "\n"
