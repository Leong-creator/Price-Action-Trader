#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "examples" / "m15_strategy_execution_preparation.json"
DEFAULT_DAILY_DIR = (
    ROOT
    / "reports"
    / "strategy_lab"
    / "m10_price_action_strategy_refresh"
    / "daily_observation"
)
DEFAULT_OUTPUT_DIR = DEFAULT_DAILY_DIR / "m15_strategy_execution_preparation"
PREPARATION_JSON = "m15_strategy_execution_preparation.json"
PREPARATION_MD = "m15_strategy_execution_preparation.md"
FORBIDDEN_BOUNDARIES = (
    "broker_connection",
    "real_order",
    "live_execution",
    "paper_trading_approval",
    "credential_injection_allowed_now",
    "manual_m12_37_once",
    "legacy_bug_profit_metric_planning_input",
)


FIRST_BATCH_ROWS = (
    {
        "runtime_id": "M10-PA-004-long-1d",
        "strategy_id": "M10-PA-004",
        "timeframe": "1d",
        "action_state": "advance_internal_sim",
        "position_size_multiplier": "1.0",
        "plain_status": "主推进策略，正常仓位进入下一轮内部模拟",
        "before_monday_tasks": [
            "确认开仓、平仓、止损、止盈链路在内部模拟里都有审计记录",
            "准备第一笔长桥模拟账户限价单预览，但不连接账户、不下单",
        ],
        "monday_refresh_checks": [
            "刷新后复核 M13 当天账本",
            "刷新后复核 M14 gate 仍为推进内部模拟",
            "首笔模拟订单预演只允许从本运行单元开始",
        ],
        "longbridge_paper_scope": "first_order_candidate_after_user_approval",
    },
    {
        "runtime_id": "M10-PA-005-1d",
        "strategy_id": "M10-PA-005",
        "timeframe": "1d",
        "action_state": "risk_limited_advance",
        "position_size_multiplier": "0.25",
        "plain_status": "风险受限推进，日线单独判断，不和 5 分钟混合",
        "before_monday_tasks": [
            "保持日线独立 runtime 账本",
            "仓位固定为 0.25 倍，先不进入第一笔长桥模拟账户",
        ],
        "monday_refresh_checks": [
            "刷新后确认日线账本独立更新",
            "若仍盈利但风险高，继续降仓位推进而不是否掉",
        ],
        "longbridge_paper_scope": "excluded_from_first_order",
    },
    {
        "runtime_id": "M10-PA-005-5m",
        "strategy_id": "M10-PA-005",
        "timeframe": "5m",
        "action_state": "risk_limited_advance",
        "position_size_multiplier": "0.25",
        "plain_status": "风险受限推进，5 分钟单独判断",
        "before_monday_tasks": [
            "准备敞口排序",
            "准备连续亏损暂停",
            "准备低质量信号过滤",
        ],
        "monday_refresh_checks": [
            "刷新后看总敞口阻断是否解除",
            "刷新后看连续亏损暂停是否仍触发",
        ],
        "longbridge_paper_scope": "excluded_until_broker_blockers_clear",
    },
    {
        "runtime_id": "M10-PA-008-1d",
        "strategy_id": "M10-PA-008",
        "timeframe": "1d",
        "action_state": "risk_limited_advance",
        "position_size_multiplier": "0.25",
        "plain_status": "风险受限推进，单笔风险上限先固定",
        "before_monday_tasks": [
            "固定单笔风险不超过 100 的数量限制",
            "准备 M10-PA-008-broker-risk-cap-shadow 首个影子账本检查",
        ],
        "monday_refresh_checks": [
            "刷新后确认风险上限影子账本是否生成",
            "若风险上限仍超标，继续压数量而不是进入长桥模拟账户",
        ],
        "longbridge_paper_scope": "excluded_until_broker_blockers_clear",
    },
)

SECOND_BATCH_ROWS = (
    ("M10-PA-013-1d", "M10-PA-013", "1d", "risk_limited_advance", "0.50", "表现较好，先补新行情账本，不进第一笔长桥模拟账户"),
    ("M10-PA-013-5m", "M10-PA-013", "5m", "risk_limited_advance", "0.50", "过滤弱支撑/阻力失败信号后继续内部模拟"),
    ("M10-PA-012-5m", "M10-PA-012", "5m", "risk_limited_advance", "0.50", "修目标价和止损几何，先跑 1 倍风险目标价影子账本"),
    ("M10-PA-002-1d", "M10-PA-002", "1d", "risk_limited_advance", "0.25", "加强突破质量和回撤控制后继续内部模拟"),
    ("M10-PA-004-MBF-1d", "M10-PA-004-MBF", "1d", "risk_limited_advance", "0.50", "作为 PA004 并行变体对照，不覆盖主线 PA004"),
)

REPAIR_ROWS = (
    ("M10-PA-001-1d", "M10-PA-001", "1d", "0.10", "修入场质量、止损距离、连续亏损控制；账本转正前只做 0.1 倍修复试验"),
    ("M10-PA-001-5m", "M10-PA-001", "5m", "0.10", "修入场质量、止损距离、连续亏损控制；账本转正前只做 0.1 倍修复试验"),
    ("M10-PA-002-5m", "M10-PA-002", "5m", "0.10", "修假突破过滤、突破确认、失败后冷却；未修完不进模拟账户"),
    ("M10-PA-004-MBF-QC-1d", "M10-PA-004-MBF-QC", "1d", "0.10", "修确认条件和入场质量；只作为 PA004 质量确认变体"),
    ("M10-PA-007-1d", "M10-PA-007", "1d", "0.10", "修第二腿图形识别器；没有稳定图形证据前不交易"),
    ("M10-PA-009-1d", "M10-PA-009", "1d", "0.10", "修弱信号过滤和图形证据；账本转正前低仓位修复"),
    ("M10-PA-011-5m", "M10-PA-011", "5m", "0.10", "修开盘区间反转高回撤；只允许小仓位试验"),
    ("M12-FTD-001-baseline-1d", "M12-FTD-001", "1d", "0.00", "修趋势过滤和连续亏损保护；先作为对照基准"),
    ("M12-FTD-001-loss-streak-guard-1d", "M12-FTD-001", "1d", "0.00", "修连续亏损保护；不进第一批长桥模拟账户"),
)

AUXILIARY_ROWS = (
    ("M10-PA-003", "质量评分和排序模块，给主策略打分"),
    ("M10-PA-006", "限价入场过滤模块，过滤差入场"),
    ("M10-PA-010", "图形识别资料模块，帮助视觉策略补证据"),
    ("M10-PA-014", "目标价计算模块，服务止盈目标"),
    ("M10-PA-015", "止损和仓位模块，服务风控和数量计算"),
    ("M10-PA-016", "区间加仓辅助模块，服务已有主策略"),
    ("AI-TRADER-EXTERNAL", "外部参考信号，只做对照，不复制交易，不覆盖本项目判断"),
)


@dataclass(frozen=True, slots=True)
class StrategyExecutionPreparationConfig:
    stage: str
    output_dir: Path
    hard_boundaries: dict[str, bool]


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> StrategyExecutionPreparationConfig:
    config_path = resolve_repo_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    config = StrategyExecutionPreparationConfig(
        stage=str(payload.get("stage", "M15.strategy_execution_preparation")),
        output_dir=resolve_repo_path(payload.get("output_dir", DEFAULT_OUTPUT_DIR)),
        hard_boundaries={str(key): bool(value) for key, value in payload.get("hard_boundaries", default_boundaries()).items()},
    )
    validate_config(config)
    return config


def validate_config(config: StrategyExecutionPreparationConfig) -> None:
    if config.stage != "M15.strategy_execution_preparation":
        raise ValueError("M15 strategy execution preparation stage drift")
    if not config.hard_boundaries.get("paper_simulated_only", False):
        raise ValueError("M15 preparation must stay paper/simulated only")
    if not config.hard_boundaries.get("internal_simulated_account", False):
        raise ValueError("M15 preparation must keep internal simulated account enabled")
    for key in FORBIDDEN_BOUNDARIES:
        if config.hard_boundaries.get(key, False):
            raise ValueError(f"M15 preparation cannot enable {key}")


def run_m15_strategy_execution_preparation(
    config: StrategyExecutionPreparationConfig | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    generated_at = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = build_payload(config, generated_at)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.output_dir / PREPARATION_JSON, payload)
    (config.output_dir / PREPARATION_MD).write_text(render_markdown(payload), encoding="utf-8")
    return payload


def build_payload(config: StrategyExecutionPreparationConfig, generated_at: str) -> dict[str, Any]:
    first_batch = [dict(row) for row in FIRST_BATCH_ROWS]
    second_batch = [
        {
            "runtime_id": runtime_id,
            "strategy_id": strategy_id,
            "timeframe": timeframe,
            "action_state": action_state,
            "position_size_multiplier": size,
            "plain_status": status,
            "longbridge_paper_scope": "not_first_order_candidate",
        }
        for runtime_id, strategy_id, timeframe, action_state, size, status in SECOND_BATCH_ROWS
    ]
    repairs = [
        {
            "runtime_id": runtime_id,
            "strategy_id": strategy_id,
            "timeframe": timeframe,
            "action_state": "repair_now",
            "position_size_multiplier": size,
            "repair_plan": repair_plan,
            "longbridge_paper_scope": "blocked_until_repaired",
        }
        for runtime_id, strategy_id, timeframe, size, repair_plan in REPAIR_ROWS
    ]
    auxiliary = [
        {
            "strategy_id": strategy_id,
            "runtime_role": "auxiliary_module",
            "module_purpose": purpose,
            "standalone_trading_allowed": False,
            "display_action": f"辅助模块：启用为{purpose}，不作为独立交易策略",
            "broker_paper_start_allowed": False,
        }
        for strategy_id, purpose in AUXILIARY_ROWS
    ]
    summary = {
        "first_batch_internal_sim_count": len(first_batch),
        "second_batch_candidate_count": len(second_batch),
        "repair_now_count": len(repairs),
        "auxiliary_module_count": len(auxiliary),
        "first_paper_order_strategy_id": "M10-PA-004",
        "first_paper_order_runtime_id": "M10-PA-004-long-1d",
        "longbridge_paper_earliest_status": "等待周一正常刷新、下单预演通过、用户单独批准模拟令牌和首笔模拟订单",
        "broker_connection": False,
        "order_submitted": False,
        "live_execution": False,
    }
    return {
        "schema_version": "m15.strategy-execution-preparation.v1",
        "stage": config.stage,
        "generated_at": generated_at,
        "summary": summary,
        "first_batch_internal_sim": first_batch,
        "second_batch_internal_sim_candidates": second_batch,
        "repair_before_advance": repairs,
        "auxiliary_modules": auxiliary,
        "monday_acceptance": monday_acceptance(),
        "longbridge_paper_entry_conditions": longbridge_entry_conditions(),
        "hard_boundaries": default_boundaries(),
        **default_boundaries(),
        "plain_language_result": [
            "周一前先把预演、白名单、仓位、熔断、验收清单和辅助模块定位准备好。",
            "第一批只推进 M10-PA-004、M10-PA-005、M10-PA-008 到下一轮内部模拟。",
            "第一笔长桥模拟账户试单只允许 M10-PA-004，且必须等用户单独批准令牌和首笔订单。",
            "辅助模块不是废弃策略，而是正式服务主策略的筛选、风控、目标价、仓位、加仓和图形证据模块。",
        ],
    }


def monday_acceptance() -> list[dict[str, str]]:
    return [
        {"check": "m12_47_alive", "required_result": "M12.47 守护器存活"},
        {"check": "regular_us_session", "required_result": "当前市场窗口为美股常规交易时段"},
        {"check": "m12_37_owned_by_supervisor", "required_result": "M12.37 只能由 M12.47 自动拉起"},
        {"check": "quote_source", "required_result": "行情来源必须为 longbridge_quote_readonly"},
        {"check": "daily_and_5m_complete", "required_result": "第一批 50 只日线和当日 5 分钟数据完整"},
        {"check": "m13_current_day_ledger", "required_result": "M13 生成当天策略账本"},
        {"check": "m14_recompute", "required_result": "M14 重算内部模拟、修复队列、影子参数和长桥预演"},
        {"check": "no_fallback_or_old_snapshot", "required_result": "备用行情或旧快照当天不允许进入长桥模拟账户"},
    ]


def longbridge_entry_conditions() -> list[str]:
    return [
        "至少 1 次周一正常交易窗口完整刷新通过",
        "M10-PA-004 的限价单预演通过",
        "M10-PA-005 和 M10-PA-008 的风控阻断已修复，或明确排除在第一笔模拟订单之外",
        "用户单独批准模拟账户令牌注入",
        "用户单独批准首次模拟订单",
        "未经批准不连接账户、不下单",
    ]


def default_boundaries() -> dict[str, bool]:
    return {
        "paper_simulated_only": True,
        "internal_simulated_account": True,
        "broker_connection": False,
        "real_order": False,
        "live_execution": False,
        "paper_trading_approval": False,
        "credential_injection_allowed_now": False,
        "manual_m12_37_once": False,
        "legacy_bug_profit_metric_planning_input": False,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# M15 Strategy Execution Preparation",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- First batch / second batch / repair / auxiliary: `{summary['first_batch_internal_sim_count']}/{summary['second_batch_candidate_count']}/{summary['repair_now_count']}/{summary['auxiliary_module_count']}`",
        f"- First paper order candidate: `{summary['first_paper_order_runtime_id']}`",
        "- Boundary: no credentials, no broker connection, no order submission, no live execution.",
        "",
        "## First Batch",
        "",
        "| Runtime | Action | Size | Status | Paper scope |",
        "|---|---|---:|---|---|",
    ]
    for row in payload["first_batch_internal_sim"]:
        lines.append(
            f"| {row['runtime_id']} | {row['action_state']} | {row['position_size_multiplier']} | {row['plain_status']} | {row['longbridge_paper_scope']} |"
        )
    lines.extend(["", "## Second Batch", "", "| Runtime | Action | Size | Status |", "|---|---|---:|---|"])
    for row in payload["second_batch_internal_sim_candidates"]:
        lines.append(f"| {row['runtime_id']} | {row['action_state']} | {row['position_size_multiplier']} | {row['plain_status']} |")
    lines.extend(["", "## Repair Queue", "", "| Runtime | Size | Repair plan |", "|---|---:|---|"])
    for row in payload["repair_before_advance"]:
        lines.append(f"| {row['runtime_id']} | {row['position_size_multiplier']} | {row['repair_plan']} |")
    lines.extend(["", "## Auxiliary Modules", "", "| Strategy | Purpose | Standalone trading |", "|---|---|---|"])
    for row in payload["auxiliary_modules"]:
        lines.append(f"| {row['strategy_id']} | {row['module_purpose']} | {row['standalone_trading_allowed']} |")
    lines.extend(["", "## Monday Acceptance", ""])
    for row in payload["monday_acceptance"]:
        lines.append(f"- `{row['check']}`: {row['required_result']}")
    lines.extend(["", "## Longbridge Paper Entry Conditions", ""])
    for item in payload["longbridge_paper_entry_conditions"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
