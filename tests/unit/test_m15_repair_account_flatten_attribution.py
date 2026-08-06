from __future__ import annotations

import unittest

from scripts.run_m15_repair_account_flatten_attribution import build_repair_plan


class M15RepairAccountFlattenAttributionTest(unittest.TestCase):
    def test_exact_zero_account_plan_is_ready_and_keeps_epoch(self) -> None:
        plan = build_repair_plan(
            {"positions": []},
            {
                "rows": [
                    {
                        "order_id": "flatten-1",
                        "symbol": "AAPL",
                        "side": "sell",
                        "status": "OrderStatus.Filled",
                        "executed_quantity": "3",
                        "created_at": "2026-08-05T19:45:02Z",
                    }
                ]
            },
            {
                "batches": [
                    {
                        "test_epoch_id": "m15-sdk-validation-20260805",
                        "symbol": "AAPL",
                        "direction": "long",
                        "remaining_quantity": "3",
                    }
                ]
            },
            {
                "last_validation_test_epoch_id": "m15-sdk-validation-20260805",
                "validation_completed_at": "2026-08-05T19:45:00Z",
            },
            set(),
        )

        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["repair_order_count"], 1)
        self.assertEqual(
            plan["rows_to_append"][0]["test_epoch_id"],
            "m15-sdk-validation-20260805",
        )
        self.assertTrue(plan["rows_to_append"][0]["account_flatten_allocation"])

    def test_quantity_mismatch_blocks_entire_repair(self) -> None:
        plan = build_repair_plan(
            {"positions": []},
            {
                "rows": [
                    {
                        "order_id": "flatten-1",
                        "symbol": "AAPL",
                        "side": "sell",
                        "status": "Filled",
                        "executed_quantity": "2",
                        "created_at": "2026-08-05T19:45:02Z",
                    }
                ]
            },
            {
                "batches": [
                    {
                        "test_epoch_id": "epoch",
                        "symbol": "AAPL",
                        "direction": "long",
                        "remaining_quantity": "3",
                    }
                ]
            },
            {
                "test_epoch_id": "epoch",
                "validation_completed_at": "2026-08-05T19:45:00Z",
            },
            set(),
        )

        self.assertEqual(plan["status"], "blocked")
        self.assertIn("flatten_quantity_mismatch:AAPL:2:3", plan["blockers"])


if __name__ == "__main__":
    unittest.main()
