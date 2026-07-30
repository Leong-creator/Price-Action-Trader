from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.m15_longbridge_realtime_position_manager_lib import (
    cached_or_refreshed_fill_attribution,
    fill_attribution_account_signature,
)


class M15LongbridgeHotPathStateTest(unittest.TestCase):
    def test_fill_attribution_signature_ignores_quote_only_changes(self) -> None:
        account_state = {
            "orders": [
                {
                    "order_id": "order-1",
                    "status": "filled",
                    "executed_quantity": "2",
                    "executed_price": "10",
                }
            ],
            "executions": [
                {
                    "order_id": "order-1",
                    "trade_id": "trade-1",
                    "quantity": "2",
                    "price": "10",
                }
            ],
            "positions": [
                {
                    "symbol": "AAPL.US",
                    "quantity": "2",
                    "available": "2",
                    "current_price": "11",
                }
            ],
        }
        execution_rows = [
            {
                "order_id": "order-1",
                "test_epoch_id": "m15-sdk-formal-test",
                "capital_bucket": "pa002",
                "runtime_id": "M10-PA-002-5m",
                "strategy_id": "M10-PA-002",
                "signal_id": "signal-1",
                "stop_price": "9",
                "target_price": "12",
            }
        ]
        original = fill_attribution_account_signature(account_state, execution_rows)
        account_state["positions"][0]["current_price"] = "11.5"
        self.assertEqual(
            original,
            fill_attribution_account_signature(account_state, execution_rows),
        )

    def test_fill_attribution_signature_changes_with_broker_or_local_identity(self) -> None:
        account_state = {
            "orders": [{"order_id": "order-1", "status": "new"}],
            "positions": [{"symbol": "AAPL.US", "quantity": "2", "available": "2"}],
        }
        execution_rows = [
            {
                "order_id": "order-1",
                "runtime_id": "M10-PA-002-5m",
                "signal_id": "signal-1",
            }
        ]
        original = fill_attribution_account_signature(account_state, execution_rows)
        account_state["orders"][0]["status"] = "filled"
        broker_changed = fill_attribution_account_signature(account_state, execution_rows)
        self.assertNotEqual(original, broker_changed)
        execution_rows[0]["runtime_id"] = "M10-PA-013-5m"
        self.assertNotEqual(
            broker_changed,
            fill_attribution_account_signature(account_state, execution_rows),
        )

    def test_fill_attribution_cache_reuses_unchanged_broker_facts(self) -> None:
        cache: dict[str, object] = {}
        account_state = {
            "orders": [{"order_id": "order-1", "status": "filled"}],
            "positions": [{"symbol": "AAPL.US", "quantity": "1", "available": "1"}],
        }
        execution_rows = [{"order_id": "order-1", "runtime_id": "M10-PA-002-5m"}]
        with patch(
            "scripts.m15_longbridge_realtime_position_manager_lib.refresh_fill_attribution_state",
            return_value={"batches": [{"open_order_id": "order-1"}]},
        ) as refresh:
            first = cached_or_refreshed_fill_attribution(
                object(), account_state, execution_rows, cache
            )
            second = cached_or_refreshed_fill_attribution(
                object(), account_state, execution_rows, cache
            )
        self.assertEqual(first, second)
        self.assertEqual(refresh.call_count, 1)


if __name__ == "__main__":
    unittest.main()
