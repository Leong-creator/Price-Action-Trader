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
IMPLEMENTED_M12_RUNTIME_RULES = frozenset(
    {
        "M10-PA-001-1d",
        "M10-PA-001-5m",
        "M10-PA-002-1d",
        "M10-PA-002-5m",
        "M10-PA-004-long-1d",
        "M10-PA-004-MBF-1d",
        "M10-PA-004-MBF-QC-1d",
        "M10-PA-005-1d",
        "M10-PA-005-5m",
        "M10-PA-007-1d",
        "M10-PA-008-1d",
        "M10-PA-009-1d",
        "M10-PA-011-5m",
        "M10-PA-011-ORB-R1-5m",
        "M10-PA-012-5m",
        "M10-PA-013-1d",
        "M10-PA-013-5m",
        "M12-FTD-001-baseline-1d",
        "M12-FTD-001-loss-streak-guard-1d",
    }
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
    {
        "runtime_id": "M10-PA-001-1d",
        "strategy_id": "M10-PA-001",
        "timeframe": "1d",
        "position_size_multiplier": "0.10",
        "repair_priority": "P0",
        "repair_window": "周一交易日前完成规则准备，周一新行情刷新后验收",
        "repair_plan": "修入场质量、止损距离、连续亏损控制；账本转正前只做 0.1 倍修复试验",
        "fix_steps": [
            "提高入场质量门槛：只保留趋势方向明确、回撤后重新转强的信号",
            "限制止损距离：止损过宽时压缩数量或放弃该信号",
            "增加连续亏损冷却：同一运行单元连续亏损后暂停新信号，等下一次高质量信号再恢复",
        ],
        "acceptance_checks": [
            "周一刷新后 M13 账本必须有本运行单元状态",
            "若有信号，账户操作必须写明开仓、平仓或风控阻断原因",
            "风险受限试验阶段仓位保持 0.10 倍",
        ],
        "advance_after_fix": "账本由亏损转为稳定或风控阻断明显下降后，升为风险受限推进",
    },
    {
        "runtime_id": "M10-PA-001-5m",
        "strategy_id": "M10-PA-001",
        "timeframe": "5m",
        "position_size_multiplier": "0.10",
        "repair_priority": "P0",
        "repair_window": "周一交易日前完成规则准备，周一新行情刷新后验收",
        "repair_plan": "修入场质量、止损距离、连续亏损控制；5 分钟单独验收，不和日线混合",
        "fix_steps": [
            "5 分钟只用本周期信号独立判断，不继承日线结论",
            "过滤窄幅震荡里的追价入场",
            "连续亏损后增加冷却，避免同一段弱行情反复试错",
        ],
        "acceptance_checks": [
            "周一刷新后 5 分钟账本必须独立生成",
            "风控阻断必须写明是止损距离、连续亏损还是敞口原因",
            "修复试验阶段仓位保持 0.10 倍",
        ],
        "advance_after_fix": "5 分钟账本转正或风险阻断下降后，单独升为风险受限推进",
    },
    {
        "runtime_id": "M10-PA-002-5m",
        "strategy_id": "M10-PA-002",
        "timeframe": "5m",
        "position_size_multiplier": "0.10",
        "repair_priority": "P0",
        "repair_window": "周一交易日前完成假突破过滤和失败后冷却规则",
        "repair_plan": "修假突破过滤、突破确认、失败后冷却；未修完不进模拟账户",
        "fix_steps": [
            "突破必须有收盘确认，不能只用盘中刺破当作有效突破",
            "突破后若快速回到区间内，标记为假突破并进入冷却",
            "同一标的同一方向失败后延迟下一次入场，避免连续追错",
        ],
        "acceptance_checks": [
            "周一刷新后必须能区分有效突破、假突破和冷却跳过",
            "有信号无账户操作时必须写明 no-op 原因",
            "修复前不进入长桥模拟账户候选",
        ],
        "advance_after_fix": "假突破过滤通过且冷却生效后，先进入 0.10 倍修复试验",
    },
    {
        "runtime_id": "M10-PA-004-MBF-QC-1d",
        "strategy_id": "M10-PA-004-MBF-QC",
        "timeframe": "1d",
        "position_size_multiplier": "0.10",
        "repair_priority": "P1",
        "repair_window": "周一交易日前固定质量确认条件",
        "repair_plan": "修确认条件和入场质量；只作为 PA004 质量确认变体",
        "fix_steps": [
            "只保留强突破后继续站稳的信号",
            "过滤过宽风险距离和低收盘质量信号",
            "保持为 PA004 并行质量确认变体，不覆盖 PA004 主线",
        ],
        "acceptance_checks": [
            "周一刷新后必须和 PA004 主线分开出账本",
            "没有质量确认时输出零信号或具体过滤原因",
            "不得替代 PA004 第一笔长桥模拟账户候选",
        ],
        "advance_after_fix": "连续生成高质量账本后，作为第二批内部模拟对照",
    },
    {
        "runtime_id": "M10-PA-007-1d",
        "strategy_id": "M10-PA-007",
        "timeframe": "1d",
        "position_size_multiplier": "0.10",
        "repair_priority": "P1",
        "repair_window": "周一交易日前固定第二腿图形证据规则",
        "repair_plan": "修第二腿图形识别器；没有稳定图形证据前不交易",
        "fix_steps": [
            "第二腿必须有明确第一腿、回调和第二次失败突破结构",
            "图形证据不足时只输出辅助证据，不生成交易运行单元信号",
            "保留样例证据，方便周一刷新后复核误判来源",
        ],
        "acceptance_checks": [
            "周一刷新后信号必须带第二腿结构证据",
            "没有稳定图形证据时保持零信号或暂停运行单元",
            "不进入第一批长桥模拟账户",
        ],
        "advance_after_fix": "图形证据稳定后，先进入 0.10 倍修复试验",
    },
    {
        "runtime_id": "M10-PA-009-1d",
        "strategy_id": "M10-PA-009",
        "timeframe": "1d",
        "position_size_multiplier": "0.10",
        "repair_priority": "P1",
        "repair_window": "周一交易日前固定弱信号过滤和图形证据规则",
        "repair_plan": "修弱信号过滤和图形证据；账本转正前低仓位修复",
        "fix_steps": [
            "过滤弱楔形、弱反转和没有后续确认的信号",
            "必须输出图形证据来源，不能只凭单根 K 线入场",
            "账本转正前只允许低仓位修复试验",
        ],
        "acceptance_checks": [
            "周一刷新后信号必须说明图形证据或过滤原因",
            "弱信号不能进入账户操作",
            "修复阶段仓位保持 0.10 倍",
        ],
        "advance_after_fix": "弱信号过滤后账本改善，再升为风险受限推进",
    },
    {
        "runtime_id": "M10-PA-011-5m",
        "strategy_id": "M10-PA-011",
        "timeframe": "5m",
        "position_size_multiplier": "0.10",
        "repair_priority": "P0",
        "repair_window": "周一交易日前固定开盘区间失败突破修复规则",
        "repair_plan": "修开盘区间反转高回撤；只允许小仓位试验",
        "fix_steps": [
            "只交易开盘区间失败突破后的回测确认，不追第一下反转",
            "加入最大回撤提醒和小仓位限制",
            "失败后当日同方向冷却，避免开盘噪音反复入场",
        ],
        "acceptance_checks": [
            "周一刷新后必须区分原始开盘反转和 ORB-R1 修复变体",
            "高回撤只触发提醒和仓位折扣，不再直接否掉策略",
            "修复阶段仓位保持 0.10 倍",
        ],
        "advance_after_fix": "回撤下降且账户操作可解释后，继续 5 分钟内部模拟",
    },
    {
        "runtime_id": "M12-FTD-001-baseline-1d",
        "strategy_id": "M12-FTD-001",
        "timeframe": "1d",
        "position_size_multiplier": "0.00",
        "repair_priority": "P1",
        "repair_window": "周一交易日前固定对照基准和趋势过滤对比",
        "repair_plan": "修趋势过滤和连续亏损保护；先作为对照基准",
        "fix_steps": [
            "baseline 只作为对照基准，不进入第一批长桥模拟账户",
            "补趋势过滤对照：弱趋势或横盘阶段不扩大仓位",
            "和 loss-streak-guard 并排比较，不互相覆盖",
        ],
        "acceptance_checks": [
            "周一刷新后 baseline 与 loss-streak-guard 必须分开出账本",
            "报告必须写明趋势过滤是否减少亏损段",
            "第一批长桥模拟账户不允许 FTD001 下单",
        ],
        "advance_after_fix": "趋势过滤和亏损保护有效后，仅作为第二批候选",
    },
    {
        "runtime_id": "M12-FTD-001-loss-streak-guard-1d",
        "strategy_id": "M12-FTD-001",
        "timeframe": "1d",
        "position_size_multiplier": "0.00",
        "repair_priority": "P1",
        "repair_window": "周一交易日前固定连续亏损保护对照",
        "repair_plan": "修连续亏损保护；不进第一批长桥模拟账户",
        "fix_steps": [
            "连续亏损保护必须写明暂停条件和恢复条件",
            "只和 FTD001 baseline 做对照，不覆盖基准账本",
            "若保护降低回撤，再考虑第二批内部模拟候选",
        ],
        "acceptance_checks": [
            "周一刷新后必须能看到连续亏损保护是否触发",
            "触发后必须说明暂停原因和恢复条件",
            "不进入第一批长桥模拟账户",
        ],
        "advance_after_fix": "连续亏损保护有效后，作为第二批风险受限候选",
    },
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
    first_batch = [
        {
            **dict(row),
            "m12_runtime_rule_status": (
                "implemented_in_m12_account_runtime" if row["runtime_id"] in IMPLEMENTED_M12_RUNTIME_RULES else "pending"
            ),
        }
        for row in FIRST_BATCH_ROWS
    ]
    second_batch = [
        {
            "runtime_id": runtime_id,
            "strategy_id": strategy_id,
            "timeframe": timeframe,
            "action_state": action_state,
            "position_size_multiplier": size,
            "plain_status": status,
            "longbridge_paper_scope": "not_first_order_candidate",
            "m12_runtime_rule_status": (
                "implemented_in_m12_account_runtime" if runtime_id in IMPLEMENTED_M12_RUNTIME_RULES else "pending"
            ),
        }
        for runtime_id, strategy_id, timeframe, action_state, size, status in SECOND_BATCH_ROWS
    ]
    repairs = [
        {
            **dict(row),
            "action_state": "repair_now",
            "longbridge_paper_scope": "blocked_until_repaired",
            "broker_paper_start_allowed": False,
            "standalone_repair_trial": True,
            "m12_runtime_rule_status": (
                "implemented_in_m12_account_runtime"
                if row["runtime_id"] in IMPLEMENTED_M12_RUNTIME_RULES
                else "pending"
            ),
        }
        for row in REPAIR_ROWS
    ]
    implemented_rule_count = sum(
        1
        for row in [*first_batch, *second_batch, *repairs]
        if row["m12_runtime_rule_status"] == "implemented_in_m12_account_runtime"
    )
    repair_priority_counts = {
        priority: sum(1 for row in repairs if row["repair_priority"] == priority)
        for priority in sorted({row["repair_priority"] for row in repairs})
    }
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
        "repair_priority_counts": repair_priority_counts,
        "repair_queue_ready_before_monday": True,
        "m12_runtime_rule_implemented_count": implemented_rule_count,
        "m12_runtime_rule_scope": "仓位倍率、收益风险比、止损距离、假突破确认、图形上下文、连续亏损暂停已接入 M12 账户化运行链路",
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
        "repair_execution_queue": repairs,
        "auxiliary_modules": auxiliary,
        "monday_acceptance": monday_acceptance(),
        "longbridge_paper_entry_conditions": longbridge_entry_conditions(),
        "hard_boundaries": default_boundaries(),
        **default_boundaries(),
        "plain_language_result": [
            "周一前先把预演、白名单、仓位、熔断、验收清单和辅助模块定位准备好。",
        "M12 账户化运行链路已接入仓位倍率、质量过滤、止损距离、假突破确认和连续亏损暂停规则。",
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
        {"check": "daily_and_5m_complete", "required_result": "当前种子池日线和当日 5 分钟数据完整"},
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
        "# M15 策略推进准备",
        "",
        f"- 生成时间: `{payload['generated_at']}`",
        f"- 第一批 / 第二批 / 立即修复 / 辅助模块: `{summary['first_batch_internal_sim_count']}/{summary['second_batch_candidate_count']}/{summary['repair_now_count']}/{summary['auxiliary_module_count']}`",
        f"- 修复优先级: `{summary['repair_priority_counts']}`",
        f"- 已接入 M12 账户化运行规则: `{summary['m12_runtime_rule_implemented_count']}` 条",
        f"- 第一笔长桥模拟候选: `{summary['first_paper_order_runtime_id']}`",
        "- 边界: 不读凭证、不连接账户、不提交订单、不启用实盘。",
        "",
        "## 第一批内部模拟",
        "",
        "| 运行单元 | 动作 | 仓位 | 规则状态 | 状态 | 长桥模拟范围 |",
        "|---|---|---:|---|---|---|",
    ]
    for row in payload["first_batch_internal_sim"]:
        lines.append(
            f"| {row['runtime_id']} | {row['action_state']} | {row['position_size_multiplier']} | {row['m12_runtime_rule_status']} | {row['plain_status']} | {row['longbridge_paper_scope']} |"
        )
    lines.extend(["", "## 第二批内部模拟候选", "", "| 运行单元 | 动作 | 仓位 | 规则状态 | 状态 |", "|---|---|---:|---|---|"])
    for row in payload["second_batch_internal_sim_candidates"]:
        lines.append(f"| {row['runtime_id']} | {row['action_state']} | {row['position_size_multiplier']} | {row['m12_runtime_rule_status']} | {row['plain_status']} |")
    lines.extend(["", "## 立即修复队列", ""])
    for row in payload["repair_before_advance"]:
        lines.extend(
            [
                f"### {row['runtime_id']}",
                "",
                f"- 优先级: `{row['repair_priority']}`",
                f"- 周期: `{row['timeframe']}`",
                f"- 仓位: `{row['position_size_multiplier']}`",
                f"- M12 规则状态: `{row['m12_runtime_rule_status']}`",
                f"- 修复窗口: {row['repair_window']}",
                f"- 修复目标: {row['repair_plan']}",
                "- 修复动作:",
            ]
        )
        for item in row["fix_steps"]:
            lines.append(f"  - {item}")
        lines.append("- 验收条件:")
        for item in row["acceptance_checks"]:
            lines.append(f"  - {item}")
        lines.extend(
            [
                f"- 修好后推进: {row['advance_after_fix']}",
                f"- 长桥模拟账户: `{row['longbridge_paper_scope']}`",
                "",
            ]
        )
    lines.extend(["", "## 辅助模块", "", "| 策略 | 用途 | 是否允许独立交易 |", "|---|---|---|"])
    for row in payload["auxiliary_modules"]:
        lines.append(f"| {row['strategy_id']} | {row['module_purpose']} | {row['standalone_trading_allowed']} |")
    lines.extend(["", "## 周一刷新验收", ""])
    for row in payload["monday_acceptance"]:
        lines.append(f"- `{row['check']}`: {row['required_result']}")
    lines.extend(["", "## 长桥模拟账户进入条件", ""])
    for item in payload["longbridge_paper_entry_conditions"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
