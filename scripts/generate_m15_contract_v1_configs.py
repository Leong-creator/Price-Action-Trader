#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m15_strategy_contracts_lib import ROOT, write_state_atomic


LONG_RUNTIMES = (
    "M10-PA-001-1d",
    "M10-PA-002-5m",
    "M10-PA-012-5m",
    "M10-PA-004-MBF-QC-1d",
    "M12-FTD-001-pullback-guard-confirm-1d",
)
SHORT_RUNTIMES = (
    "M10-PA-002-5m-short",
    "M10-PA-013-5m-short",
    "M10-PA-011-ORB-R1-5m-short",
)
ALL_RUNTIMES = LONG_RUNTIMES + SHORT_RUNTIMES
BUCKET_IDS = {
    "M10-PA-001-1d": "pa001_daily_contract_v1",
    "M10-PA-002-5m": "pa002_5m_contract_v1",
    "M10-PA-012-5m": "pa012_5m_contract_v1",
    "M10-PA-004-MBF-QC-1d": "pa004_mbf_qc_contract_v1",
    "M12-FTD-001-pullback-guard-confirm-1d": "ftd_pullback_guard_confirm_v1",
    "M10-PA-002-5m-short": "pa002_5m_short_contract_v1",
    "M10-PA-013-5m-short": "pa013_5m_short_contract_v1",
    "M10-PA-011-ORB-R1-5m-short": "pa011_orb_r1_short_contract_v1",
}
LABELS = {
    "M10-PA-001-1d": "PA001日线完整执行测试仓",
    "M10-PA-002-5m": "PA002五分钟完整执行测试仓",
    "M10-PA-012-5m": "PA012五分钟完整执行测试仓",
    "M10-PA-004-MBF-QC-1d": "PA004-MBF-QC实验合同仓",
    "M12-FTD-001-pullback-guard-confirm-1d": "FTD长回调保护确认仓",
    "M10-PA-002-5m-short": "PA002五分钟受限做空仓",
    "M10-PA-013-5m-short": "PA013五分钟受限做空仓",
    "M10-PA-011-ORB-R1-5m-short": "PA011-ORB-R1五分钟受限做空仓",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def capital_buckets() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for runtime_id in ALL_RUNTIMES:
        short = runtime_id in SHORT_RUNTIMES
        result[BUCKET_IDS[runtime_id]] = {
            "label": f"{LABELS[runtime_id]}（{runtime_id}）",
            "position_direction": "short" if short else "long",
            "equity": "10000",
            "max_total_exposure": "2000" if short else "6000",
            "max_symbol_exposure": "750" if short else "1500",
            "max_risk_per_order": "10" if short else "20",
            "min_cash_reserve": "8000" if short else "4000",
            "runtime_ids": [runtime_id],
        }
    return result


def paper_account_model() -> dict[str, Any]:
    return {
        "equity": "10000",
        "max_total_exposure": "6000",
        "max_symbol_exposure": "1500",
        "max_risk_per_order": "20",
        "min_cash_reserve": "4000",
        "allow_fractional_shares": False,
        "allow_short_selling": True,
        "allow_options": False,
        "allow_margin_financing": False,
        "minimum_net_profit_after_fees": "5",
        "normal_minimum_net_profit_after_fees": "8",
        "minimum_reward_r": "1.5",
        "runtime_minimum_net_profit_after_fees": {
            "M10-PA-001-1d": "12",
            "M10-PA-002-5m-short": "12",
            "M10-PA-013-5m-short": "12",
            "M10-PA-011-ORB-R1-5m-short": "15",
        },
        "runtime_minimum_reward_r": {
            "M10-PA-001-1d": "2.0",
            "M10-PA-002-5m-short": "2.0",
            "M10-PA-013-5m-short": "2.0",
            "M10-PA-011-ORB-R1-5m-short": "2.25",
        },
        "conditional_net_profit_requires_confluence": False,
    }


def build_configs(epoch_date: str) -> dict[Path, dict[str, Any]]:
    long_epoch = f"m15-sdk-contract-v1-{epoch_date}"
    short_epoch = f"m15-sdk-contract-v1-short-{epoch_date}"
    buckets = capital_buckets()

    router = read_json(ROOT / "config/examples/m15_longbridge_realtime_signal_router.json")
    router["title"] = "长桥SDK完整策略合同实时信号路由器"
    router["realtime_signal_router"]["enabled_detectors"] = [
        "pa004_momentum_variants",
        "price_action_realtime_v1",
    ]
    router["realtime_signal_router"]["allowed_runtime_ids"] = list(ALL_RUNTIMES)
    router["realtime_signal_router"]["runtime_position_multipliers"] = {
        runtime_id: "1.0" for runtime_id in ALL_RUNTIMES
    }
    router["realtime_signal_router"]["additional_runtime_bucket_routes"] = {}
    router["virtual_capital_buckets"] = copy.deepcopy(buckets)
    router["paper_account_model"] = paper_account_model()
    router["paper_short_testing"] = {
        "enabled": True,
        "test_epoch_id": short_epoch,
        "test_started_at": f"{epoch_date[:4]}-{epoch_date[4:6]}-{epoch_date[6:]}T13:30:00Z",
        "runtime_ids": list(SHORT_RUNTIMES),
    }
    router["strategy_contracts"] = {
        "required": True,
        "directory": "config/m15_strategy_contracts",
    }
    router["auxiliary_modules_contract"] = "config/m15_auxiliary_modules_contract_v1.json"

    execution = read_json(ROOT / "config/examples/m15_longbridge_realtime_execution.paper_orders_enabled.json")
    execution["title"] = "长桥SDK完整策略合同实时执行链路（仅模拟账户）"
    execution["longbridge_realtime"]["allowed_runtime_ids"] = list(ALL_RUNTIMES)
    execution["longbridge_realtime"]["daily_new_symbol_limit_by_strategy"] = {}
    execution["virtual_capital_buckets"] = copy.deepcopy(buckets)
    execution["paper_account_model"] = paper_account_model()
    execution["paper_short_testing"] = copy.deepcopy(router["paper_short_testing"])
    execution["strategy_contracts"] = copy.deepcopy(router["strategy_contracts"])
    execution["test_epoch"] = {
        "enabled": True,
        "test_epoch_id": long_epoch,
        "state_path": "reports/strategy_lab/m10_price_action_strategy_refresh/daily_observation/m15_longbridge_realtime_execution/m15_longbridge_virtual_account_epoch.json",
        "flatten_existing_positions_before_activation": True,
        "archive_previous_records": True,
    }
    execution["runtime_layering"] = {
        "longbridge_realtime_candidates": list(ALL_RUNTIMES),
        "local_repair_or_shadow_only": [
            "M10-PA-001-5m",
            "M10-PA-004-long-1d",
            "M10-PA-007-1d",
            "M10-PA-008-1d",
            "M10-PA-009-1d",
            "M10-PA-011-5m",
            "all m14-modify variants",
            "all broker-risk-cap-shadow variants",
            "all target-stop-shadow variants",
        ],
        "auxiliary_modules_local_only": [
            "M10-PA-003",
            "M10-PA-006",
            "M10-PA-010",
            "M10-PA-014",
            "M10-PA-015",
            "M10-PA-016",
            "AI-TRADER-EXTERNAL",
        ],
        "paper_contract_v1": list(ALL_RUNTIMES),
        "visual_shadow_only": ["M10-PA-004-long-1d", "M10-PA-007-1d", "M10-PA-008-1d"],
        "retired_simplified_versions": [
            "M10-PA-002-5m-repaired-v1",
            "M12-FTD-001-baseline-1d",
            "M12-FTD-001-loss-streak-guard-1d",
            "M10-PA-004-MBF-1d",
            "M10-PA-013-5m",
            "M10-PA-011-ORB-R1-5m",
        ],
    }

    position = read_json(ROOT / "config/examples/m15_longbridge_realtime_position_manager.json")
    position["longbridge_position_manager"]["max_exit_events_per_run"] = 300
    position["longbridge_position_manager"]["maximum_holding_sessions_by_runtime"] = {
        "M10-PA-001-1d": 5,
        "M10-PA-004-MBF-QC-1d": 5,
        "M12-FTD-001-pullback-guard-confirm-1d": 5,
    }
    position["longbridge_position_manager"]["market_holidays"] = read_json(
        ROOT / "config/examples/m12_47_session_supervisor.json"
    ).get("market_holidays", [])
    position["longbridge_position_manager"]["test_epoch_id"] = long_epoch
    position["longbridge_position_manager"]["test_started_at"] = f"{epoch_date[:4]}-{epoch_date[4:6]}-{epoch_date[6:]}T13:30:00Z"
    position["longbridge_position_manager"]["paper_short_testing"] = {
        "enabled": True,
        "test_epoch_id": short_epoch,
        "runtime_ids": list(SHORT_RUNTIMES),
    }

    runtime = read_json(ROOT / "config/examples/m15_longbridge_sdk_runtime.json")
    runtime["title"] = "长桥SDK完整策略合同模拟账户运行层"
    runtime["routing"]["router_config"] = "config/examples/m15_longbridge_realtime_signal_router.contract_v1.json"
    runtime["routing"]["execution_config"] = "config/examples/m15_longbridge_realtime_execution.paper_contract_v1.json"
    runtime["routing"]["position_manager_config"] = "config/examples/m15_longbridge_realtime_position_manager.contract_v1.json"
    runtime["formal_test_transition"]["test_epoch_id"] = long_epoch
    runtime["formal_test_transition"]["short_test_epoch_id"] = short_epoch
    runtime["formal_test_transition"]["activate_not_before"] = (
        f"{epoch_date[:4]}-{epoch_date[4:6]}-{epoch_date[6:]}T13:30:00Z"
    )

    readiness = read_json(ROOT / "config/examples/m15_opening_trade_readiness.paper_orders_enabled.json")
    readiness["inputs"]["sdk_runtime_config"] = "config/examples/m15_longbridge_sdk_runtime.contract_v1.json"
    readiness["inputs"]["execution_config"] = (
        "config/examples/m15_longbridge_realtime_execution.paper_contract_v1.json"
    )

    watchdog = read_json(ROOT / "config/examples/m15_background_watchdog.json")
    watchdog["inputs"]["m15_sdk_runtime_config"] = "config/examples/m15_longbridge_sdk_runtime.contract_v1.json"
    watchdog["inputs"]["readiness_config"] = (
        "config/examples/m15_opening_trade_readiness.paper_contract_v1.json"
    )
    watchdog["inputs"]["m15_dashboard_config"] = (
        "config/examples/m15_longbridge_dashboard.contract_v1.json"
    )

    dashboard = read_json(ROOT / "config/examples/m15_longbridge_dashboard.json")
    dashboard["inputs"]["execution_config"] = (
        "config/examples/m15_longbridge_realtime_execution.paper_contract_v1.json"
    )

    return {
        ROOT / "config/examples/m15_longbridge_realtime_signal_router.contract_v1.json": router,
        ROOT / "config/examples/m15_longbridge_realtime_execution.paper_contract_v1.json": execution,
        ROOT / "config/examples/m15_longbridge_realtime_position_manager.contract_v1.json": position,
        ROOT / "config/examples/m15_longbridge_sdk_runtime.contract_v1.json": runtime,
        ROOT / "config/examples/m15_opening_trade_readiness.paper_contract_v1.json": readiness,
        ROOT / "config/examples/m15_background_watchdog.contract_v1.json": watchdog,
        ROOT / "config/examples/m15_longbridge_dashboard.contract_v1.json": dashboard,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate frozen M15 contract-v1 paper configuration.")
    parser.add_argument("--epoch-date", required=True, help="New York market date as YYYYMMDD")
    args = parser.parse_args()
    if len(args.epoch_date) != 8 or not args.epoch_date.isdigit():
        parser.error("--epoch-date must use YYYYMMDD")
    for path, payload in build_configs(args.epoch_date).items():
        write_state_atomic(path, payload)
        print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
