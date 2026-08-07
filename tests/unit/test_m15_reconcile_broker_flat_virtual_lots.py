from __future__ import annotations

import unittest

from scripts.run_m15_reconcile_broker_flat_virtual_lots import (
    build_broker_flat_adjustments,
)


class M15ReconcileBrokerFlatVirtualLotsTest(unittest.TestCase):
    def test_only_broker_flat_symbol_with_exit_evidence_is_adjusted(self) -> None:
        payload = build_broker_flat_adjustments(
            {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [{"symbol": "GLW.US", "quantity": "5"}],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            },
            {
                "batches": [
                    {"symbol": "LCID", "direction": "long", "remaining_quantity": "56", "open_order_id": "LCID-OPEN"},
                    {"symbol": "GLW", "direction": "long", "remaining_quantity": "5", "open_order_id": "GLW-OPEN"},
                ]
            },
            {
                "rows": [
                    {"symbol": "LCID", "side": "sell", "status": "Filled", "order_id": "LCID-EXIT"},
                    {"symbol": "GLW", "side": "sell", "status": "Filled", "order_id": "GLW-EXIT"},
                ]
            },
            {"adjustments": []},
        )

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["generated_adjustment_count"], 1)
        self.assertEqual(payload["adjustments"][0]["symbol"], "LCID")
        self.assertEqual(payload["adjustments"][0]["open_order_ids"], ["LCID-OPEN"])
        self.assertFalse(payload["adjustments"][0]["include_in_strategy_performance"])
        self.assertIn(
            {"symbol": "GLW", "reason": "broker_position_not_zero"},
            payload["skipped"],
        )

    def test_missing_exit_evidence_does_not_guess(self) -> None:
        payload = build_broker_flat_adjustments(
            {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            },
            {"batches": [{"symbol": "AAL", "direction": "long", "remaining_quantity": "3", "open_order_id": "AAL-OPEN"}]},
            {"rows": []},
            {"adjustments": []},
        )

        self.assertEqual(payload["generated_adjustment_count"], 0)
        self.assertIn(
            {"symbol": "AAL", "reason": "missing_filled_broker_exit_evidence"},
            payload["skipped"],
        )

    def test_old_epoch_excess_is_closed_without_touching_current_real_position(self) -> None:
        payload = build_broker_flat_adjustments(
            {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [{"symbol": "GLW.US", "quantity": "5"}],
                "open_orders": [],
                "live_execution": False,
                "real_money_actions": False,
            },
            {
                "batches": [
                    {"test_epoch_id": "current", "symbol": "GLW", "direction": "long", "remaining_quantity": "5", "open_order_id": "CURRENT-OPEN"},
                    {"test_epoch_id": "old", "symbol": "GLW", "direction": "long", "remaining_quantity": "1", "open_order_id": "OLD-OPEN"},
                ]
            },
            {"rows": [{"symbol": "GLW", "side": "sell", "status": "Filled", "order_id": "OLD-EXIT"}]},
            {"adjustments": []},
            active_test_epoch_ids={"current"},
        )

        self.assertEqual(payload["generated_adjustment_count"], 1)
        self.assertEqual(payload["adjustments"][0]["open_order_ids"], ["OLD-OPEN"])

    def test_open_broker_orders_block_adjustment_write_plan(self) -> None:
        payload = build_broker_flat_adjustments(
            {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "positions": [],
                "open_orders": [{"order_id": "PENDING"}],
                "live_execution": False,
                "real_money_actions": False,
            },
            {"batches": []},
            {"rows": []},
            {"adjustments": []},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertIn("open_orders_present", payload["blockers"])


if __name__ == "__main__":
    unittest.main()
