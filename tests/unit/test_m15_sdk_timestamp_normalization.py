"""SDK timestamp boundary regression tests; no broker connections or runtime start."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
import multiprocessing
import os
import socket
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.m15_longbridge_sdk_runtime_lib import sdk_object_to_dict, sdk_plain_value
from scripts.run_m15_longbridge_sdk_runtime import (
    strict_event_datetime,
    update_live_quote_session_state,
)


SOURCE_AT = datetime(2026, 9, 21, 13, 30, 1, tzinfo=UTC)
RECEIVED_AT = SOURCE_AT + timedelta(seconds=1)


def _forbid_connection(*_args, **_kwargs):
    raise AssertionError("network_connections_prohibited")


def _sdk_payload_worker(connection, host_timezone: str, case: str):
    """Only this child changes TZ; machine and parent timezone stay untouched."""
    os.environ["TZ"] = host_timezone
    time.tzset()
    try:
        with patch.object(socket.socket, "connect", _forbid_connection), patch.object(
            socket, "create_connection", _forbid_connection
        ):
            epoch = SOURCE_AT.timestamp() + (10 if case == "future" else 0)
            timestamp = datetime.fromtimestamp(epoch)
            if case == "aware":
                timestamp = datetime.fromtimestamp(epoch, timezone(timedelta(hours=-4)))
            elif case == "invalid":
                timestamp = "not-a-timestamp"
            quote = SimpleNamespace(
                timestamp=timestamp,
                last_done=Decimal("101.25"), open=Decimal("100.00"),
                high=Decimal("102.00"), low=Decimal("99.00"),
                volume=100,
            )
            payload = sdk_object_to_dict(quote)
            # The actual Pipe serializes the same aware datetime/Decimal payload
            # that the quote worker sends, not a hand-normalized test substitute.
            connection.send({"payload": payload, "raw_timestamp": timestamp,
                             "host_timezone": host_timezone})
    finally:
        connection.close()


class InvalidTimezone(tzinfo):
    def utcoffset(self, _value):
        raise ValueError("invalid_sdk_timezone")


class SdkTimestampNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.connect_guard = patch.object(socket.socket, "connect", _forbid_connection)
        self.connect_guard.start()
        self.addCleanup(self.connect_guard.stop)
        self.create_guard = patch.object(socket, "create_connection", _forbid_connection)
        self.create_guard.start()
        self.addCleanup(self.create_guard.stop)

    def _through_ipc(self, host_timezone: str, case: str = "naive"):
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        worker = context.Process(target=_sdk_payload_worker, args=(send, host_timezone, case))
        worker.start()
        send.close()
        try:
            self.assertTrue(receive.poll(10), "SDK normalization worker did not return")
            result = receive.recv()
            worker.join(timeout=5)
            self.assertEqual(worker.exitcode, 0)
            return result
        finally:
            receive.close()
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=5)
            worker.close()

    @unittest.skipUnless(hasattr(time, "tzset"), "Child-only TZ tests require tzset")
    def test_local_naive_sdk_time_crosses_ipc_and_updates_parent_quote_state(self):
        original_tz = os.environ.get("TZ")
        original_tzname = time.tzname
        for host_timezone, expected_hour in (("Asia/Shanghai", 21), ("UTC", 13)):
            with self.subTest(host_timezone=host_timezone):
                result = self._through_ipc(host_timezone)
                raw = result["raw_timestamp"]
                self.assertIsNone(raw.tzinfo)
                self.assertEqual(raw.hour, expected_hour)
                # This is the pre-fix rejection; strict input checks stay strict.
                self.assertIsNone(strict_event_datetime(raw))
                payload = result["payload"]
                self.assertEqual(payload["timestamp"], SOURCE_AT)
                self.assertEqual(payload["timestamp"].utcoffset(), timedelta(0))
                state = {}
                updated = update_live_quote_session_state(
                    state, "SPY.US", payload, received_at=RECEIVED_AT,
                    source_mode="official_sdk_push",
                )
                self.assertIsNotNone(updated)
                self.assertEqual(strict_event_datetime(state["SPY"]["source_event_at"]), SOURCE_AT)
                self.assertEqual(state["SPY"]["session_date"], "2026-09-21")
                self.assertEqual(state["SPY"]["market_data_blocked_reason"], "")
                self.assertEqual(state["SPY"]["close"], "101.25")
                self.assertTrue(state["SPY"]["bar_quote_snapshots"])
        self.assertEqual(os.environ.get("TZ"), original_tz)
        self.assertEqual(time.tzname, original_tzname)

    @unittest.skipUnless(hasattr(time, "tzset"), "Child-only TZ tests require tzset")
    def test_aware_sdk_time_is_utc_after_ipc_and_updates_parent(self):
        result = self._through_ipc("Asia/Shanghai", "aware")
        self.assertEqual(result["raw_timestamp"].utcoffset(), timedelta(hours=-4))
        self.assertEqual(result["payload"]["timestamp"], SOURCE_AT)
        self.assertEqual(result["payload"]["timestamp"].utcoffset(), timedelta(0))
        state = {}
        self.assertIsNotNone(update_live_quote_session_state(
            state, "QQQ.US", result["payload"], received_at=RECEIVED_AT,
            source_mode="official_sdk_push",
        ))

    @unittest.skipUnless(hasattr(time, "tzset"), "Child-only TZ tests require tzset")
    def test_future_sdk_time_still_rejected_by_parent_after_normalization_and_ipc(self):
        result = self._through_ipc("Asia/Shanghai", "future")
        self.assertGreater(result["payload"]["timestamp"], RECEIVED_AT)
        state = {}
        self.assertIsNone(update_live_quote_session_state(
            state, "SPY.US", result["payload"], received_at=RECEIVED_AT,
            source_mode="official_sdk_push",
        ))
        self.assertEqual(state, {})

    @unittest.skipUnless(hasattr(time, "tzset"), "Child-only TZ tests require tzset")
    def test_malformed_timestamp_not_reinterpreted_after_ipc(self):
        result = self._through_ipc("UTC", "invalid")
        self.assertEqual(result["payload"]["timestamp"], "not-a-timestamp")
        state = {}
        self.assertIsNone(update_live_quote_session_state(
            state, "SPY.US", result["payload"], received_at=RECEIVED_AT,
            source_mode="official_sdk_push",
        ))
        self.assertEqual(state, {})

    def test_aware_utc_and_nested_trade_timestamp_preserve_instant(self):
        aware = SOURCE_AT.astimezone(timezone(timedelta(hours=8)))
        payload = sdk_object_to_dict(SimpleNamespace(trades=[SimpleNamespace(
            timestamp=aware, price=Decimal("100.10"), volume=7,
        )]))
        self.assertEqual(payload["trades"][0]["timestamp"], SOURCE_AT)
        self.assertIs(payload["trades"][0]["timestamp"].tzinfo, UTC)
        self.assertEqual(sdk_plain_value(SOURCE_AT), SOURCE_AT)
        self.assertIs(sdk_plain_value(SOURCE_AT).tzinfo, UTC)

    def test_invalid_datetime_conversion_propagates_instead_of_claiming_utc(self):
        invalid = datetime(2026, 9, 21, 13, 30, tzinfo=InvalidTimezone())
        with self.assertRaisesRegex(ValueError, "invalid_sdk_timezone"):
            sdk_plain_value(invalid)

    def test_non_datetime_semantics_and_general_strict_validation_unchanged(self):
        amount = Decimal("1.2300")
        self.assertIs(sdk_plain_value(amount), amount)
        self.assertEqual(sdk_plain_value(date(2026, 9, 21)), "2026-09-21")
        self.assertEqual(sdk_plain_value({1: (None, True, 7, 1.5, "text", amount)}),
                         {"1": [None, True, 7, 1.5, "text", amount]})
        for value in ("not-a-timestamp", "2026-09-21T13:30:01", datetime(2026, 9, 21, 13, 30, 1)):
            with self.subTest(value=value):
                self.assertIsNone(strict_event_datetime(value))


if __name__ == "__main__":
    unittest.main()
