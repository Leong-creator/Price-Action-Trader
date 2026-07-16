from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config/examples/m15_longbridge_dashboard.json"


def _resolve(path: str | Path) -> Path:
    value = Path(path).expanduser()
    return value if value.is_absolute() else ROOT / value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    return json.loads(_resolve(path).read_text(encoding="utf-8"))


def _inventory(execution_config: dict[str, Any]) -> dict[str, Any]:
    buckets = execution_config.get("virtual_capital_buckets") or {}
    rows: list[dict[str, Any]] = []
    runtime_ids: list[str] = []
    for bucket_id, bucket in buckets.items():
        ids = list(bucket.get("runtime_ids") or [])
        runtime_ids.extend(ids)
        rows.append(
            {
                "bucket_id": bucket_id,
                "label": bucket.get("label") or bucket_id,
                "direction": bucket.get("position_direction") or "long",
                "runtime_ids": ids,
                "runtime_count": len(ids),
                "equity": bucket.get("equity"),
                "max_total_exposure": bucket.get("max_total_exposure"),
                "max_symbol_exposure": bucket.get("max_symbol_exposure"),
                "max_risk_per_order": bucket.get("max_risk_per_order"),
            }
        )
    long_count = sum(row["runtime_count"] for row in rows if row["direction"] != "short")
    short_count = sum(row["runtime_count"] for row in rows if row["direction"] == "short")
    return {
        "bucket_count": len(rows),
        "runtime_count": len(runtime_ids),
        "long_runtime_count": long_count,
        "short_runtime_count": short_count,
        "runtime_ids": runtime_ids,
        "buckets": rows,
    }


def _local_inventory(registry: dict[str, Any]) -> dict[str, int]:
    strategies = registry.get("strategies") if isinstance(registry.get("strategies"), list) else []
    trading = [row for row in strategies if row.get("module_role") == "independent_runtime"]
    auxiliaries = [row for row in strategies if row.get("module_role") != "independent_runtime"]
    return {
        "parent_strategy_count": len(trading),
        "local_runtime_count": sum(len(row.get("runtime_accounts") or []) for row in trading),
        "auxiliary_module_count": len(auxiliaries),
    }


def build_dashboard(config: dict[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    inputs = config["inputs"]
    runtime = _read_json(_resolve(inputs["sdk_runtime_status"]))
    account = _read_json(_resolve(inputs["account_state"]))
    account_summary = _read_json(_resolve(inputs["account_state_summary"]))
    execution = _read_json(_resolve(inputs["execution_status"]))
    epoch = _read_json(_resolve(inputs["epoch_state"]))
    formal_epoch = _read_json(_resolve(inputs["formal_epoch_marker"]))
    reconciliation = _read_json(_resolve(inputs["order_reconciliation"]))
    pnl = _read_json(_resolve(inputs["pnl_reconciliation"]))
    execution_config = _read_json(_resolve(inputs["execution_config"]))
    local_registry = _read_json(_resolve(inputs["local_runtime_registry"]))
    inventory = _inventory(execution_config)
    coverage = str(runtime.get("subscription_coverage") or "")
    try:
        subscribed_count = int(coverage.split("/", 1)[0])
    except (ValueError, IndexError):
        subscribed_count = runtime.get("subscribed_symbol_count")

    position_count = int(account.get("position_row_count") or len(account.get("positions") or []))
    open_order_count = int(account.get("open_order_count") or len(account.get("open_orders") or []))
    pending_count = int(execution.get("pending_confirmation_count") or 0)
    epoch_status = formal_epoch.get("status") or epoch.get("status") or "unknown"
    entries_enabled = bool(runtime.get("new_position_submission_enabled", False))
    if epoch_status != "active":
        entries_enabled = False

    source_checks = {
        "sdk_runtime": bool(runtime),
        "account": bool(account),
        "execution": bool(execution),
        "orders": bool(reconciliation),
        "pnl": bool(pnl),
    }
    trustworthy = all(source_checks.values()) and bool(account.get("paper_account_verified"))
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "1.0",
        "stage": "M15.longbridge_dashboard",
        "title": "长桥模拟账户",
        "generated_at": timestamp,
        "source_of_truth": "longbridge_sdk_paper_account",
        "local_simulation_isolated": True,
        "legacy_queue_used": False,
        "legacy_cli_used": False,
        "data_status": "trustworthy" if trustworthy else "temporarily_unavailable",
        "source_checks": source_checks,
        "runtime": {
            "runtime_engine": runtime.get("runtime_engine"),
            "status": runtime.get("status"),
            "sdk_connected": runtime.get("sdk_connected"),
            "paper_account_verified": account.get("paper_account_verified"),
            "account_channel": account.get("account_channel"),
            "configured_symbol_count": runtime.get("configured_symbol_count"),
            "subscribed_symbol_count": subscribed_count,
            "daily_context_row_count": runtime.get("daily_context_row_count"),
            "daily_context_complete": runtime.get("daily_context_complete")
            if runtime.get("daily_context_complete") is not None
            else runtime.get("daily_context_state") == "complete",
            "last_event_at": runtime.get("last_event_at"),
            "account_snapshot_generated_at": account.get("generated_at"),
            "dispatch_enabled": runtime.get("paper_order_dispatch_enabled"),
            "new_position_submission_enabled": entries_enabled,
            "config_fingerprint": runtime.get("config_fingerprint"),
        },
        "formal_test": {
            "status": epoch_status,
            "test_epoch_id": formal_epoch.get("test_epoch_id") or epoch.get("test_epoch_id"),
            "short_test_epoch_id": formal_epoch.get("short_test_epoch_id"),
            "test_started_at": formal_epoch.get("test_started_at") or epoch.get("test_started_at"),
            "activation_blocker": formal_epoch.get("activation_blocker") or epoch.get("activation_blocker"),
            "positions": position_count,
            "open_orders": open_order_count,
            "pending_orders": pending_count,
        },
        "account": {
            "cash": account.get("cash"),
            "usd_available_cash": account.get("usd_available_cash"),
            "total_equity": account.get("account_total_equity_estimate"),
            "buying_power": account_summary.get("buying_power"),
            "today_pnl": account_summary.get("account_today_total_pnl"),
            "today_pnl_source": account_summary.get("account_today_total_pnl_source"),
            "position_count": position_count,
            "open_order_count": open_order_count,
        },
        "pnl": {
            "account_pnl": pnl.get("account_pnl"),
            "today_account_pnl": pnl.get("today_account_pnl"),
            "trading_pnl": pnl.get("trading_pnl"),
            "current_holdings": pnl.get("current_holdings"),
            "source_status": pnl.get("source_status"),
        },
        "orders": {
            "summary": reconciliation.get("summary") or {},
            "rows": reconciliation.get("rows") or [],
        },
        "strategy_inventory": inventory,
        "inventory_interface": {
            **_local_inventory(local_registry),
            "longbridge_tradable_runtime_count": inventory["runtime_count"],
        },
        "notes": [
            "所有长桥成绩只统计长桥实际订单、成交和持仓。",
            "本地研究与修复系统不参与长桥启动、风控、下单或盈亏。",
            "正式测试未激活时，配置中的运行单元全部禁止新开仓。",
        ],
    }


def _render_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>长桥模拟账户</title><style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f5f6f8;color:#17202a}}header,main{{max-width:1400px;margin:auto;padding:16px}}header{{background:#fff;border-bottom:1px solid #dfe3e8;max-width:none}}h1{{font-size:20px;margin:0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}.card{{background:#fff;border:1px solid #dfe3e8;border-radius:6px;padding:12px}}.v{{font-size:22px;font-weight:650;margin-top:6px}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{text-align:left;border-bottom:1px solid #e7eaee;padding:8px;font-size:13px}}.bad{{color:#a61b1b}}.ok{{color:#136b36}}</style></head>
<body><header><h1>长桥模拟账户</h1></header><main><div id=\"app\"></div><script>
const d={data}; const v=x=>x===null||x===undefined||x===''?'暂不可计算':x;
const cls=d.data_status==='trustworthy'?'ok':'bad';
const cards=[['数据状态',d.data_status],['SDK连接',d.runtime.sdk_connected],['订阅标的',`${{v(d.runtime.subscribed_symbol_count)}}/${{v(d.runtime.configured_symbol_count)}}`],['正式测试',d.formal_test.status],['当日盈亏',d.account.today_pnl],['账户净值',d.account.total_equity],['持仓',d.account.position_count],['挂单',d.account.open_order_count],['父级策略',d.inventory_interface.parent_strategy_count],['本地运行单元',d.inventory_interface.local_runtime_count],['长桥运行单元',d.inventory_interface.longbridge_tradable_runtime_count],['辅助模块',d.inventory_interface.auxiliary_module_count]];
document.getElementById('app').innerHTML=`<section class=\"grid\">${{cards.map(x=>`<div class=\"card\"><div>${{x[0]}}</div><div class=\"v ${{x[0]==='数据状态'?cls:''}}\">${{v(x[1])}}</div></div>`).join('')}}</section><h2>策略与虚拟仓</h2><table><thead><tr><th>仓位</th><th>方向</th><th>运行单元</th><th>资金</th><th>敞口上限</th></tr></thead><tbody>${{d.strategy_inventory.buckets.map(x=>`<tr><td>${{x.label}}</td><td>${{x.direction==='short'?'做空':'做多'}}</td><td>${{x.runtime_ids.join(', ')}}</td><td>${{v(x.equity)}}</td><td>${{v(x.max_total_exposure)}}</td></tr>`).join('')}}</tbody></table>`;
</script></main></body></html>"""


def run_dashboard(config: dict[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    payload = build_dashboard(config, generated_at=generated_at)
    outputs = config["outputs"]
    json_path = _resolve(outputs["json"])
    html_path = _resolve(outputs["html"])
    _write_json(json_path, payload)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(_render_html(payload), encoding="utf-8")
    return payload
