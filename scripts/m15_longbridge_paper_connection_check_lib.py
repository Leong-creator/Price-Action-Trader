#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_longbridge_paper_connection_check.json"
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
    / "m15_longbridge_paper_connection_check"
)
CHECK_JSON = "m15_longbridge_paper_connection_check.json"
CHECK_MD = "m15_longbridge_paper_connection_check.md"
PAPER_ACCOUNT_MARKERS = ("paper", "simulate", "simulation", "simulated", "demo", "virtual")


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class M15PaperConnectionConfig:
    title: str
    stage: str
    output_dir: Path
    cli_name: str
    authentication_method: str
    require_paper_account: bool
    require_paper_account_marker: bool
    user_confirmed_paper_account: bool
    paper_account_assertion_source: str
    live_token_allowed: bool
    allow_asset_read_after_paper_verified: bool
    paper_account_equity: str


CommandRunner = Callable[[list[str]], CommandResult]


def resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> M15PaperConnectionConfig:
    config_path = resolve_repo_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    return M15PaperConnectionConfig(
        title=str(payload.get("title", "M15 Longbridge paper connection check")),
        stage=str(payload.get("stage", "M15.longbridge_paper_connection_check")),
        output_dir=resolve_repo_path(payload.get("output_dir", DEFAULT_OUTPUT_DIR)),
        cli_name=str(payload.get("cli_name", "longbridge")),
        authentication_method=str(payload.get("authentication_method", "oauth")),
        require_paper_account=bool(payload.get("require_paper_account", True)),
        require_paper_account_marker=bool(payload.get("require_paper_account_marker", True)),
        user_confirmed_paper_account=bool(payload.get("user_confirmed_paper_account", False)),
        paper_account_assertion_source=str(payload.get("paper_account_assertion_source", "")),
        live_token_allowed=bool(payload.get("live_token_allowed", False)),
        allow_asset_read_after_paper_verified=bool(payload.get("allow_asset_read_after_paper_verified", False)),
        paper_account_equity=str(payload.get("paper_account_equity", "10000")),
    )


def run_m15_longbridge_paper_connection_check(
    config: M15PaperConnectionConfig | None = None,
    *,
    generated_at: str | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = build_connection_check(config, generated_at=generated_at, command_runner=command_runner or run_command)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / CHECK_JSON, payload)
    (config.output_dir / CHECK_MD).write_text(render_markdown(payload), encoding="utf-8")
    return payload


def build_connection_check(
    config: M15PaperConnectionConfig,
    *,
    generated_at: str,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    cli_path = shutil.which(config.cli_name) or ""
    cli = {"available": bool(cli_path), "path": cli_path, "name": config.cli_name}
    policy_blockers = connection_policy_blockers(config)
    check_probe = empty_probe("longbridge_check")
    auth_probe = empty_probe("longbridge_auth_status")

    if cli_path:
        check_probe = probe_json(command_runner, [cli_path, "check", "--format", "json"], "longbridge_check")
        auth_probe = probe_json(command_runner, [cli_path, "auth", "status", "--format", "json"], "longbridge_auth_status")

    connection_summary = summarize_check_probe(check_probe)
    auth_summary = summarize_auth_probe(auth_probe)
    paper_marker_verified = paper_account_marker_verified(auth_summary)
    paper_assertion_accepted = paper_account_assertion_accepted(config)
    paper_verified = paper_marker_verified or paper_assertion_accepted
    status = connection_status(config, cli, check_probe, auth_probe, auth_summary, paper_verified, policy_blockers)
    asset_read_allowed = (
        status == "connected_verified_paper_account"
        and config.allow_asset_read_after_paper_verified
        and not policy_blockers
    )

    return {
        "schema_version": "m15.longbridge-paper-connection-check.v1",
        "stage": config.stage,
        "title": config.title,
        "generated_at": generated_at,
        "connection_check_status": status,
        "cli": cli,
        "longbridge_check": connection_summary,
        "auth_status": auth_summary,
        "authentication_method": config.authentication_method,
        "paper_account_required": config.require_paper_account,
        "paper_account_marker_required": config.require_paper_account_marker,
        "paper_account_marker_verified": paper_marker_verified,
        "user_confirmed_paper_account": config.user_confirmed_paper_account,
        "paper_account_assertion_source": config.paper_account_assertion_source,
        "paper_account_assertion_accepted": paper_assertion_accepted,
        "paper_account_verified": paper_verified,
        "paper_account_equity_model": config.paper_account_equity,
        "live_token_allowed": config.live_token_allowed,
        "allow_asset_read_after_paper_verified": config.allow_asset_read_after_paper_verified,
        "asset_read_allowed_now": asset_read_allowed,
        "asset_read_attempted": False,
        "position_read_attempted": False,
        "order_submitted": False,
        "real_money_actions": False,
        "policy_blockers": policy_blockers,
        "plain_language_result": plain_language_result(status, connection_summary, auth_summary, paper_verified),
    }


def run_command(args: list[str]) -> CommandResult:
    try:
        completed = subprocess.run(args, check=False, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(returncode=124, stdout="", stderr=str(exc))
    return CommandResult(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)


def probe_json(command_runner: CommandRunner, args: list[str], name: str) -> dict[str, Any]:
    result = command_runner(args)
    payload: dict[str, Any] | None = None
    parse_error = ""
    if result.returncode == 0:
        try:
            parsed = json.loads(result.stdout or "{}")
            payload = parsed if isinstance(parsed, dict) else {"value_type": type(parsed).__name__}
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
    return {
        "name": name,
        "returncode": result.returncode,
        "ok": result.returncode == 0 and not parse_error,
        "json": payload or {},
        "parse_error": parse_error,
        "stderr_present": bool(result.stderr.strip()),
    }


def empty_probe(name: str) -> dict[str, Any]:
    return {"name": name, "returncode": None, "ok": False, "json": {}, "parse_error": "", "stderr_present": False}


def connection_policy_blockers(config: M15PaperConnectionConfig) -> list[str]:
    blockers: list[str] = []
    if config.authentication_method != "oauth":
        blockers.append("oauth_authentication_required")
    if not config.require_paper_account:
        blockers.append("paper_account_required")
    if config.live_token_allowed:
        blockers.append("live_token_forbidden")
    return blockers


def summarize_check_probe(probe: dict[str, Any]) -> dict[str, Any]:
    payload = probe.get("json", {}) if isinstance(probe.get("json", {}), dict) else {}
    connectivity = payload.get("connectivity", {}) if isinstance(payload.get("connectivity", {}), dict) else {}
    session = payload.get("session", {}) if isinstance(payload.get("session", {}), dict) else {}
    region = payload.get("region", {}) if isinstance(payload.get("region", {}), dict) else {}
    endpoints: dict[str, Any] = {}
    for name, value in connectivity.items():
        if isinstance(value, dict):
            endpoints[str(name)] = {"ok": bool(value.get("ok")), "ms": value.get("ms")}
    return {
        "ok": bool(probe.get("ok")),
        "returncode": probe.get("returncode"),
        "endpoints": endpoints,
        "active_region": region.get("active"),
        "cached_region": region.get("cached"),
        "session_token_status": session.get("token"),
        "session_detail_present": bool(session.get("detail")),
        "parse_error": probe.get("parse_error", ""),
    }


def summarize_auth_probe(probe: dict[str, Any]) -> dict[str, Any]:
    payload = probe.get("json", {}) if isinstance(probe.get("json", {}), dict) else {}
    account = payload.get("account", {}) if isinstance(payload.get("account", {}), dict) else {}
    token = payload.get("token", {}) if isinstance(payload.get("token", {}), dict) else {}
    return {
        "ok": bool(probe.get("ok")),
        "returncode": probe.get("returncode"),
        "token_status": token.get("status"),
        "token_path_present": bool(token.get("path")),
        "account_type": account.get("account_type"),
        "account_channel": account.get("account_channel"),
        "account_no_present": bool(account.get("account_no")),
        "member_id_present": bool(account.get("member_id")),
        "activated_package_count": len(account.get("activated_packages") or []),
        "unactivated_package_count": len(account.get("unactivated_packages") or []),
        "parse_error": probe.get("parse_error", ""),
    }


def paper_account_marker_verified(auth_summary: dict[str, Any]) -> bool:
    values = [auth_summary.get("account_type"), auth_summary.get("account_channel")]
    return any(marker in str(value).lower() for value in values for marker in PAPER_ACCOUNT_MARKERS)


def paper_account_assertion_accepted(config: M15PaperConnectionConfig) -> bool:
    return (
        config.authentication_method == "oauth"
        and config.require_paper_account
        and not config.require_paper_account_marker
        and config.user_confirmed_paper_account
        and bool(config.paper_account_assertion_source)
    )


def connection_status(
    config: M15PaperConnectionConfig,
    cli: dict[str, Any],
    check_probe: dict[str, Any],
    auth_probe: dict[str, Any],
    auth_summary: dict[str, Any],
    paper_verified: bool,
    policy_blockers: list[str],
) -> str:
    if policy_blockers:
        return "blocked_connection_policy"
    if not cli.get("available"):
        return "blocked_cli_missing"
    if not check_probe.get("ok"):
        return "blocked_longbridge_check_failed"
    if not auth_probe.get("ok"):
        return "blocked_longbridge_auth_status_failed"
    if auth_summary.get("token_status") != "valid":
        return "blocked_longbridge_token_invalid"
    if config.require_paper_account and not paper_verified:
        return "blocked_paper_account_not_verified"
    if config.require_paper_account_marker:
        return "connected_verified_paper_account"
    return "connected_oauth_user_confirmed_paper_account"


def plain_language_result(
    status: str,
    connection_summary: dict[str, Any],
    auth_summary: dict[str, Any],
    paper_verified: bool,
) -> str:
    if status == "connected_verified_paper_account":
        return "长桥模拟账户已通过只读连接检查；当前仍没有读取资产、没有读取持仓、没有下单。"
    if status == "connected_oauth_user_confirmed_paper_account":
        return "长桥 OAuth 授权已通过，且本轮按用户确认的模拟账户授权处理；当前仍没有读取资产、没有读取持仓、没有下单。"
    if status == "blocked_paper_account_not_verified":
        token_text = "有效" if auth_summary.get("token_status") == "valid" else "无效或未知"
        return (
            "长桥平台连接正常，登录令牌也"
            f"{token_text}，但当前认证结果没有显示模拟账户标识；"
            "所以我没有继续读取资产或持仓，避免误连实盘账户。"
        )
    if status == "blocked_longbridge_check_failed":
        return "长桥连接检查失败；需要先修复 CLI 网络或登录状态。"
    if status == "blocked_longbridge_auth_status_failed":
        return "长桥认证状态读取失败；需要重新登录或检查 CLI 权限。"
    if status == "blocked_longbridge_token_invalid":
        return "长桥登录令牌不是有效状态；需要重新登录模拟账户。"
    if status == "blocked_cli_missing":
        return "本机找不到长桥命令行工具，暂时无法连接模拟账户。"
    if status == "blocked_connection_policy":
        return "连接策略配置不安全，已阻断；必须只允许模拟账户，禁止实盘令牌。"
    if paper_verified:
        return "长桥模拟账户标识已识别，但连接检查未完全通过。"
    endpoint_state = "正常" if connection_summary.get("ok") else "异常"
    return f"长桥平台连接状态{endpoint_state}，但模拟账户连接没有完成。"


def render_markdown(payload: dict[str, Any]) -> str:
    auth = payload.get("auth_status", {})
    check = payload.get("longbridge_check", {})
    lines = [
        "# M15 Longbridge Paper Connection Check",
        "",
        f"- Status: `{payload['connection_check_status']}`",
        f"- Plain result: {payload['plain_language_result']}",
        f"- CLI: `{payload['cli'].get('path') or 'missing'}`",
        f"- Longbridge check ok: `{check.get('ok')}`",
        f"- Region: `{check.get('active_region')}` / `{check.get('cached_region')}`",
        f"- Token status: `{auth.get('token_status')}`",
        f"- Authentication method: `{payload.get('authentication_method')}`",
        f"- Account type: `{auth.get('account_type')}`",
        f"- Account channel: `{auth.get('account_channel')}`",
        f"- Paper marker required: `{payload['paper_account_marker_required']}`",
        f"- Paper marker verified: `{payload['paper_account_marker_verified']}`",
        f"- User confirmed paper account: `{payload['user_confirmed_paper_account']}`",
        f"- Paper assertion accepted: `{payload['paper_account_assertion_accepted']}`",
        f"- Paper account verified: `{payload['paper_account_verified']}`",
        f"- Paper equity model: `{payload['paper_account_equity_model']}` USD",
        f"- Asset read attempted: `{payload['asset_read_attempted']}`",
        f"- Position read attempted: `{payload['position_read_attempted']}`",
        f"- Order submitted: `{payload['order_submitted']}`",
        f"- Real money actions: `{payload['real_money_actions']}`",
        f"- Policy blockers: `{', '.join(payload['policy_blockers']) or 'none'}`",
    ]
    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
