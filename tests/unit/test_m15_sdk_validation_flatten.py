from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

from scripts.m15_sdk_validation_flatten_lib import (
    activate_formal_epoch_payload,
    build_flatten_plan,
    flatten_confirmation,
    formal_epoch_payload,
    in_regular_session,
    market_date,
    next_regular_session_start,
    pending_formal_epoch_payload,
    runtime_flatten_order_payload,
)


class M15SdkValidationFlattenTest(unittest.TestCase):
    def test_builds_long_sell_and_short_cover_from_broker_positions(self) -> None:
        plan, blockers = build_flatten_plan(
            {
                "positions": [
                    {"symbol": "AAPL.US", "quantity": "3", "available": "3", "cost_price": "100"},
                    {"symbol": "TSLA.US", "quantity": "2", "available": "2", "cost_price": "200", "side": "short"},
                ]
            },
            {"AAPL.US": Decimal("110"), "TSLA.US": Decimal("190")},
        )

        self.assertEqual(blockers, [])
        self.assertEqual(plan[0]["side"], "sell")
        self.assertEqual(plan[0]["position_action"], "close_long")
        self.assertEqual(plan[0]["order_type"], "market")
        self.assertEqual(plan[0]["limit_price"], "")
        self.assertEqual(plan[0]["reference_price"], "110")
        self.assertEqual(plan[0]["reference_price_source"], "official_sdk_quote")
        self.assertEqual(plan[1]["side"], "buy")
        self.assertEqual(plan[1]["position_action"], "close_short")
        self.assertEqual(plan[1]["order_type"], "market")
        self.assertEqual(plan[1]["reference_price"], "190")

    def test_refuses_partial_flatten_when_a_position_direction_is_unknown(self) -> None:
        plan, blockers = build_flatten_plan(
            {"positions": [{"symbol": "AAPL.US", "quantity": "1", "available": "1", "side": "borrowed"}]},
            {"AAPL.US": Decimal("100")},
        )

        self.assertEqual(plan, [])
        self.assertEqual(blockers, ["unknown_position_direction:AAPL.US"])

    def test_regular_session_uses_new_york_time(self) -> None:
        self.assertTrue(in_regular_session(datetime(2026, 7, 15, 14, 0, tzinfo=UTC)))
        self.assertFalse(in_regular_session(datetime(2026, 7, 15, 12, 0, tzinfo=UTC)))
        self.assertEqual(market_date(datetime(2026, 7, 15, 1, 0, tzinfo=UTC)), "2026-07-14")

    def test_flatten_confirmation_requires_no_positions_and_no_open_orders(self) -> None:
        pending = flatten_confirmation(
            {
                "positions": [{"symbol": "AAPL.US", "quantity": "1"}],
                "open_orders": [{"order_id": "SDK-1"}],
                "orders": [{"order_id": "SDK-1"}],
            },
            ["SDK-1"],
        )
        self.assertFalse(pending["complete"])
        complete = flatten_confirmation(
            {"positions": [], "open_orders": [], "orders": [{"order_id": "SDK-1", "status": "Filled"}]},
            ["SDK-1"],
        )
        self.assertTrue(complete["complete"])
        self.assertEqual(complete["remaining_position_count"], 0)

    def test_flatten_confirmation_requires_pending_confirmations_to_clear(self) -> None:
        result = flatten_confirmation(
            {
                "positions": [],
                "open_orders": [],
                "orders": [],
                "pending_confirmations": [{"client_request_id": "m15rt-1"}],
            },
            [],
        )

        self.assertFalse(result["complete"])
        self.assertEqual(result["pending_confirmation_count"], 1)

    def test_market_flatten_stops_when_official_sdk_quote_is_missing(self) -> None:
        plan, blockers = build_flatten_plan(
            {"positions": [{"symbol": "AAPL.US", "quantity": "1", "available": "1"}]},
            {},
        )

        self.assertEqual(plan, [])
        self.assertEqual(blockers, ["sdk_quote_missing:AAPL.US"])

    def test_runtime_flatten_payload_has_stable_request_id(self) -> None:
        intent = {
            "symbol": "AAPL.US", "side": "sell", "position_action": "close_long",
            "order_type": "market", "quantity": "2", "limit_price": "",
        }
        first = runtime_flatten_order_payload(intent, test_epoch_id="formal-main")
        second = runtime_flatten_order_payload(intent, test_epoch_id="formal-main")

        self.assertEqual(first["client_request_id"], second["client_request_id"])
        self.assertTrue(first["market_exit_no_reprice"])

    def test_formal_epoch_starts_at_next_regular_session(self) -> None:
        prepared = datetime(2026, 7, 15, 19, 50, tzinfo=UTC)
        start = next_regular_session_start(prepared)
        self.assertEqual(start, datetime(2026, 7, 16, 13, 30, tzinfo=UTC))
        marker = formal_epoch_payload(
            test_epoch_id="formal-main",
            short_test_epoch_id="formal-short",
            test_started_at=start,
            prepared_at=prepared,
        )
        self.assertEqual(marker["status"], "scheduled")
        self.assertEqual(marker["test_started_at"], "2026-07-16T13:30:00Z")
        self.assertTrue(marker["paper_simulated_only"])

    def test_failed_cleanup_can_prepare_a_pending_flatten_epoch(self) -> None:
        marker = pending_formal_epoch_payload(
            test_epoch_id="formal-main",
            short_test_epoch_id="formal-short",
            prepared_at=datetime(2026, 7, 16, 3, 0, tzinfo=UTC),
            reason="validation_flatten_incomplete:connect_timeout",
        )

        self.assertEqual(marker["status"], "pending_flatten")
        self.assertEqual(marker["test_started_at"], "")
        self.assertIn("connect_timeout", marker["activation_blocker"])
        self.assertTrue(marker["paper_simulated_only"])

    def test_activation_payload_marks_zero_account_condition(self) -> None:
        marker = pending_formal_epoch_payload(
            test_epoch_id="formal-main",
            short_test_epoch_id="formal-short",
            prepared_at=datetime(2026, 7, 16, 3, 0, tzinfo=UTC),
            reason="waiting",
        )
        active = activate_formal_epoch_payload(
            marker,
            activated_at=datetime(2026, 7, 16, 14, 5, tzinfo=UTC),
        )

        self.assertEqual(active["status"], "active")
        self.assertEqual(active["test_started_at"], "2026-07-16T14:05:00Z")
        self.assertEqual(active["activation_condition_met"], "positions_open_orders_pending_confirmations_zero")
