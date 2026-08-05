from __future__ import annotations

import unittest

from scripts.generate_m15_contract_v1_configs import (
    ALL_RUNTIMES,
    LONG_RUNTIMES,
    SHORT_RUNTIMES,
    build_configs,
)


class ContractV1ConfigGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        generated = build_configs("20260806")
        self.by_name = {path.name: payload for path, payload in generated.items()}
        self.router = self.by_name["m15_longbridge_realtime_signal_router.contract_v1.json"]
        self.execution = self.by_name["m15_longbridge_realtime_execution.paper_contract_v1.json"]

    def test_only_frozen_executable_contracts_are_enabled(self) -> None:
        allowed = self.router["realtime_signal_router"]["allowed_runtime_ids"]
        self.assertEqual(allowed, list(ALL_RUNTIMES))
        self.assertEqual(len(allowed), 8)
        self.assertEqual(len(LONG_RUNTIMES), 5)
        self.assertEqual(len(SHORT_RUNTIMES), 3)
        self.assertNotIn("M10-PA-004-long-1d", allowed)
        self.assertNotIn("M10-PA-007-1d", allowed)
        self.assertNotIn("M10-PA-008-1d", allowed)

    def test_every_bucket_is_one_strategy_and_independent(self) -> None:
        buckets = self.execution["virtual_capital_buckets"]
        self.assertEqual(len(buckets), len(ALL_RUNTIMES))
        routed = []
        for bucket in buckets.values():
            self.assertEqual(len(bucket["runtime_ids"]), 1)
            self.assertEqual(bucket["equity"], "10000")
            routed.extend(bucket["runtime_ids"])
        self.assertCountEqual(routed, ALL_RUNTIMES)

    def test_no_daily_order_or_cross_bucket_cap_is_generated(self) -> None:
        realtime = self.execution["longbridge_realtime"]
        self.assertEqual(realtime["daily_new_symbol_limit_by_strategy"], {})
        self.assertNotIn("aggregate_exposure_limit", self.execution)
        self.assertNotIn("max_daily_new_positions", self.execution)

    def test_contract_enforcement_and_epoch_are_enabled(self) -> None:
        self.assertEqual(
            self.execution["strategy_contracts"],
            {"required": True, "directory": "config/m15_strategy_contracts"},
        )
        self.assertEqual(
            self.execution["test_epoch"]["test_epoch_id"],
            "m15-sdk-contract-v1-20260806",
        )
        self.assertTrue(self.execution["test_epoch"]["flatten_existing_positions_before_activation"])
        self.assertEqual(
            self.router["auxiliary_modules_contract"],
            "config/m15_auxiliary_modules_contract_v1.json",
        )

    def test_readiness_and_watchdog_follow_the_contract_runtime(self) -> None:
        readiness = self.by_name["m15_opening_trade_readiness.paper_contract_v1.json"]
        watchdog = self.by_name["m15_background_watchdog.contract_v1.json"]
        self.assertEqual(
            readiness["inputs"]["sdk_runtime_config"],
            "config/examples/m15_longbridge_sdk_runtime.contract_v1.json",
        )
        self.assertEqual(
            readiness["inputs"]["execution_config"],
            "config/examples/m15_longbridge_realtime_execution.paper_contract_v1.json",
        )
        self.assertEqual(
            watchdog["inputs"]["readiness_config"],
            "config/examples/m15_opening_trade_readiness.paper_contract_v1.json",
        )
        runtime = self.by_name["m15_longbridge_sdk_runtime.contract_v1.json"]
        self.assertEqual(
            runtime["formal_test_transition"]["activate_not_before"],
            "2026-08-06T13:30:00Z",
        )


if __name__ == "__main__":
    unittest.main()
