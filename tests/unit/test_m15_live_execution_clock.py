from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from scripts.m15_longbridge_realtime_execution_lib import run_realtime_execution
from tests.unit import test_m15_longbridge_realtime_execution as execution_tests


class LiveExecutionClockTests(unittest.TestCase):
    def execute(self, times, *, snapshot_age=0, signal_changes=None, window=None):
        helper = execution_tests.M15LongbridgeRealtimeExecutionTest()
        client = Mock()
        client.submit_order.return_value = {"submitted": True, "order_id": "fake-paper-order"}
        first = times[0]
        clock = Mock(side_effect=times)
        with TemporaryDirectory() as temp:
            config = helper.make_config(Path(temp), execute_orders=True, paper_trading_approval=True,
                                        max_account_state_age_seconds=45)
            account = {"account_channel": "lb_papertrading", "paper_account_verified": True,
                       "buying_power": "10000", "live_execution": False,
                       "real_money_actions": False,
                       "generated_at": (first - timedelta(seconds=snapshot_age)).isoformat()}
            rows = []
            summary = run_realtime_execution(
                config, generated_at="2026-06-04T14:00:00Z", live_clock=clock,
                submission_window=window, broker_client=client,
                signal_events_override=[helper.signal(**(signal_changes or {}))],
                account_state_override=account, existing_ledger_override=[], emitted_ledger_rows=rows,
            )
        return summary, rows, client

    def test_route_and_queue_time_not_hidden_by_old_generated_at(self):
        now = datetime(2026, 6, 4, 14, 0, 9, tzinfo=UTC)
        result, rows, client = self.execute([now, now])
        self.assertEqual(result["submitted_count"], 0)
        self.assertIn("blocked_delayed_signal_requires_realtime_rebuild", rows[0]["blockers"])
        self.assertEqual(rows[0]["latency_ms"], 9500)
        client.submit_order.assert_not_called()

    def test_fresh_qualified_signal_submits_and_keeps_actual_latency(self):
        now = datetime(2026, 6, 4, 14, tzinfo=UTC)
        result, rows, client = self.execute([now, now, now + timedelta(seconds=1)])
        self.assertEqual(result["submitted_count"], 1)
        self.assertEqual(rows[0]["signal_to_request_ms"], 1500)
        client.submit_order.assert_called_once()

    def test_snapshot_that_expires_during_evaluation_not_used(self):
        now = datetime(2026, 6, 4, 14, tzinfo=UTC)
        result, rows, client = self.execute([now, now, now + timedelta(seconds=2)], snapshot_age=44)
        self.assertEqual(result["submitted_count"], 0)
        self.assertIn("blocked_account_state_stale_at_request", rows[0]["blockers"])
        client.submit_order.assert_not_called()

    def test_session_can_close_between_evaluation_and_request(self):
        now = datetime(2026, 6, 4, 14, tzinfo=UTC)
        result, rows, client = self.execute([now, now, now], window=lambda _: False)
        self.assertEqual(result["submitted_count"], 0)
        self.assertIn("blocked_outside_regular_session_at_request", rows[0]["blockers"])
        client.submit_order.assert_not_called()

    def test_signal_expiry_is_checked_after_capacity_io(self):
        now = datetime(2026, 6, 4, 14, tzinfo=UTC)
        result, rows, client = self.execute([now, now, now + timedelta(seconds=2)],
            signal_changes={"expires_at": (now + timedelta(seconds=1)).isoformat()})
        self.assertEqual(result["submitted_count"], 0)
        self.assertIn("blocked_realtime_signal_expired_at_request", rows[0]["blockers"])
        client.submit_order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
