from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import m15_longbridge_realtime_signal_router_lib as router
from scripts import m15_longbridge_sdk_runtime_lib as sdk_runtime
from scripts import run_m15_longbridge_sdk_runtime as runtime
from scripts.m15_full_strategy_detectors_lib import pa001_daily_long


CLOSE = datetime(2026, 9, 8, 13, 35, tzinfo=UTC)
NOW = CLOSE + timedelta(seconds=2)
SESSION = "2026-09-08T13:30:00Z"


def bar() -> dict:
    return {
        "event_id": "offline-current-5m", "symbol": "TEST", "timeframe": "5m",
        "event_time": runtime.to_iso(CLOSE), "bar_close_at": runtime.to_iso(CLOSE),
        "bar_open_at": runtime.to_iso(CLOSE - timedelta(minutes=5)),
        "received_at": runtime.to_iso(NOW), "bar_final": True,
        "source_mode": "official_sdk_push", "market_data_blocked_reason": "",
        "open": "100", "high": "115", "low": "98", "close": "114", "volume": "1000",
    }


def history(values: list[tuple], *, received_at: datetime | None = None) -> list[dict]:
    rows = []
    for index, (open_price, high, low, close, volume) in enumerate(values):
        at = datetime(2026, 9, 4, 20, tzinfo=UTC) - timedelta(days=len(values) - 1 - index)
        rows.append({
            "event_id": f"offline-daily-{index}", "symbol": "TEST", "timeframe": "1d",
            "event_time": runtime.to_iso(at), "received_at": runtime.to_iso(received_at or CLOSE - timedelta(minutes=6)),
            "bar_final": True, "source_mode": "official_sdk_daily_context",
            **dict(zip(("open", "high", "low", "close", "volume"), map(str, (open_price, high, low, close, volume)))),
        })
    return rows


def quote(state: dict, at: datetime, *, received_at: datetime | None = None,
          values: tuple = (112, 115, 111, 114, 1000), source_mode: str = "official_sdk_push"):
    return runtime.update_live_quote_session_state(
        state, "TEST.US", {"timestamp": at, **dict(zip(("open", "high", "low", "last_done", "volume"), values))},
        received_at=received_at or at, source_mode=source_mode,
    )


def daily(state: dict, *, rows: list[dict] | None = None, now: datetime = NOW,
          active: set[str] | None = None) -> list[dict]:
    rows = sdk_runtime.attach_next_bar_first_quotes(rows or [bar()], state, now=now)
    return runtime.build_live_daily_confirmation_rows(
        rows, generated_at=now, live_quote_session_state=state,
        active_five_minute_event_ids={"offline-current-5m"} if active is None else active,
    )


class DailyContextRetentionTest(unittest.TestCase):
    def current(self) -> dict:
        state = {}
        quote(state, CLOSE - timedelta(seconds=1))
        quote(state, CLOSE + timedelta(seconds=1), values=(112, 116, 111, 114.2, 1100))
        return daily(state)[0]

    def test_sixty_prior_bars_survive_duplicates_and_preopen_or_intraday_initialization(self):
        for received in (CLOSE - timedelta(minutes=6), CLOSE - timedelta(minutes=1)):
            with self.subTest(received=received):
                prior = history([(100, 101, 99, 100, 1000)] * 80, received_at=received)
                current = self.current()
                kept = router.realtime_relevant_market_events(prior + prior + [current], SESSION, generated_at=NOW)
                self.assertEqual(len(kept), 61)
                self.assertEqual(len({row["event_time"] for row in kept}), 61)
                self.assertEqual([row["event_id"] for row in kept[:-1]], [row["event_id"] for row in prior[-60:]])
                self.assertEqual(kept[-1], current)

    def test_pa001_twenty_two_bars_reach_unchanged_detector_and_router(self):
        closes = [100 + i for i in range(14)] + [112, 111, 112, 111, 112, 111, 112]
        lows = [value - 1 for value in closes]
        lows[15], lows[17], lows[19] = 109, 108, 109
        prior = history([(close - 0.5, close + 1, lows[i], close, 1000) for i, close in enumerate(closes)])
        current = self.current()
        kept = router.realtime_relevant_market_events(prior + prior + [current], SESSION, generated_at=NOW)
        self.assertEqual(len(kept), 22)
        self.assertIsNone(pa001_daily_long("TEST", kept[-21:]))
        signal = pa001_daily_long("TEST", kept)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["limit_price"], "114.2")
        self.assertEqual(signal["stop_price"], "108")
        self.assertEqual(signal["source_market_event_id"], current["event_id"])
        self.assert_router_emits_only_current_once(prior, current, "M10-PA-001-1d")

    def test_ftd_twenty_four_bars_reach_unchanged_detector_and_router(self):
        values = [(100, 101, 98, 100, 1000)] * 21
        values[-1] = (100, 104, 98, 100, 1000)
        values += [(100, 103, 99.5, 102, 1200), (102, 104, 101, 103, 1100)]
        prior = history(values)
        state = {}
        quote(state, CLOSE - timedelta(seconds=1), values=(103, 105, 102, 104, 1100))
        quote(state, CLOSE + timedelta(seconds=1), values=(103, 106, 102, 104.2, 1200))
        current = daily(state)[0]
        kept = router.realtime_relevant_market_events(prior + prior + [current], SESSION, generated_at=NOW)
        self.assertEqual(len(kept), 24)
        spec = router.PRICE_ACTION_RUNTIME_SPECS["M12-FTD-001-pullback-guard-confirm-1d"]
        self.assertIsNone(router.ftd_pullback_guard_confirm_signal("TEST", kept[-23:], spec=spec, grouped_events={}, generated_at=NOW))
        signal = router.ftd_pullback_guard_confirm_signal("TEST", kept, spec=spec, grouped_events={}, generated_at=NOW)
        self.assertIsNotNone(signal)
        self.assertEqual(Decimal(signal["limit_price"]), Decimal("104.2"))
        self.assertEqual(signal["source_market_event_id"], current["event_id"])
        self.assert_router_emits_only_current_once(prior, current, "M12-FTD-001-pullback-guard-confirm-1d")

    def assert_router_emits_only_current_once(self, prior, current, expected_runtime):
        config = router.load_config(runtime.load_config().router_config_path)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = replace(config, output_dir=root, signal_events_path=root / "signals.jsonl",
                             test_epoch_state_path=root / "epoch.json", capital_bucket_migration_state_path=root / "migration.json")
            emitted = []
            kwargs = dict(generated_at=runtime.to_iso(NOW), market_events_override=prior + prior + [current],
                          existing_signal_ids_override=set(), emitted_signal_events=emitted)
            router.run_realtime_signal_router(config, active_market_event_ids=set(), **kwargs)
            self.assertEqual(emitted, [])
            router.run_realtime_signal_router(config, active_market_event_ids={current["event_id"]}, **kwargs)
            selected = [signal for signal in emitted if signal["runtime_id"] == expected_runtime]
            self.assertEqual(len(selected), 1)
            self.assertTrue(all(signal["source_market_event_id"] == current["event_id"] for signal in emitted))
            seen = {signal["signal_id"] for signal in emitted}
            emitted.clear()
            kwargs["existing_signal_ids_override"] = seen
            router.run_realtime_signal_router(config, active_market_event_ids={current["event_id"]}, **kwargs)
            self.assertEqual(emitted, [])

    def test_future_daily_row_and_history_only_never_become_current(self):
        prior = history([(100, 101, 99, 100, 1000)] * 60)
        future = dict(self.current(), event_time=runtime.to_iso(CLOSE + timedelta(minutes=5)))
        self.assertEqual(router.realtime_relevant_market_events(prior + [future], SESSION, generated_at=NOW), [])


class BoundaryQuoteInputsTest(unittest.TestCase):
    def test_before_quote_seals_daily_after_quote_supplies_entry_without_repricing_daily(self):
        state = {}
        quote(state, CLOSE - timedelta(seconds=1))
        sealed = daily(state)[0]
        self.assertEqual(sealed["next_bar_first_quote_price"], "")
        quote(state, CLOSE + timedelta(seconds=1), values=(112, 200, 90, 150, 9000))
        combined = daily(state)[0]
        self.assertEqual([combined[key] for key in ("open", "high", "low", "close", "volume")], ["112", "115", "111", "114", "1000"])
        self.assertEqual(combined["source_event_at"], runtime.to_iso(CLOSE - timedelta(seconds=1)))
        self.assertEqual(combined["next_bar_first_quote_price"], "150")
        self.assertEqual(combined["next_bar_first_quote_at"], runtime.to_iso(CLOSE + timedelta(seconds=1)))

    def test_later_next_bar_quote_does_not_replace_first_observed_entry(self):
        state = {}
        quote(state, CLOSE - timedelta(seconds=1))
        quote(state, CLOSE, values=(112, 116, 111, 115, 1001))
        quote(state, CLOSE + timedelta(seconds=1), values=(112, 120, 111, 119, 1002))
        result = daily(state)[0]
        self.assertEqual(result["close"], "114")
        self.assertEqual(result["next_bar_first_quote_price"], "115")
        self.assertEqual(result["next_bar_first_quote_at"], runtime.to_iso(CLOSE))

    def test_after_only_quote_cannot_supply_prior_daily_ohlcv(self):
        state = {}
        quote(state, CLOSE + timedelta(seconds=1))
        self.assertEqual(daily(state), [])

    def test_delayed_before_quote_is_not_a_next_bar_entry(self):
        state = {}
        quote(state, CLOSE - timedelta(seconds=1), received_at=CLOSE + timedelta(seconds=1))
        self.assertEqual(daily(state)[0]["next_bar_first_quote_price"], "")

    def test_naive_or_inconsistent_bar_timestamps_cannot_seal_daily(self):
        state = {}
        quote(state, CLOSE - timedelta(seconds=1))
        for fields in (
            {"event_time": "2026-09-08T13:35:00"},
            {"bar_open_at": "2026-09-08T13:30:00"},
            {"bar_close_at": runtime.to_iso(CLOSE + timedelta(minutes=5))},
            {"bar_open_at": runtime.to_iso(CLOSE - timedelta(minutes=10))},
        ):
            with self.subTest(fields=fields):
                self.assertEqual(daily(state, rows=[dict(bar(), **fields)]), [])
        self.assertEqual(daily(state, now=NOW.replace(tzinfo=None)), [])

    def test_next_bucket_and_next_session_do_not_refresh_an_old_entry(self):
        for offset in (timedelta(minutes=5), timedelta(days=1)):
            with self.subTest(offset=offset):
                state = {}
                quote(state, CLOSE + offset)
                result = sdk_runtime.attach_next_bar_first_quotes([bar()], state, now=CLOSE + offset)
                self.assertNotIn("next_bar_first_quote_price", result[0])

    def test_out_of_order_quote_does_not_rewrite_sealed_snapshot(self):
        state = {}
        quote(state, CLOSE - timedelta(seconds=1))
        quote(state, CLOSE + timedelta(seconds=1))
        expected = daily(state)
        quote(state, CLOSE - timedelta(seconds=2), received_at=NOW, values=(112, 200, 90, 150, 9000))
        self.assertEqual(daily(state), expected)

    def test_future_receipt_cannot_supply_entry_or_future_bar_confirmation(self):
        state = {}
        quote(state, CLOSE - timedelta(seconds=1))
        quote(state, CLOSE + timedelta(seconds=3))
        self.assertEqual(daily(state)[0]["next_bar_first_quote_price"], "")
        future_bar = dict(bar(), event_time=runtime.to_iso(CLOSE + timedelta(minutes=5)))
        self.assertEqual(daily(state, rows=[future_bar]), [])

    def test_future_source_and_invalid_timestamps_cannot_replace_valid_state(self):
        state = {}
        expected = quote(state, CLOSE - timedelta(seconds=1))
        self.assertIs(quote(state, CLOSE + timedelta(seconds=3), received_at=NOW), expected)
        for stamp in (None, "invalid", "2026-09-08T13:35:01"):
            result = runtime.update_live_quote_session_state(state, "TEST", {"timestamp": stamp}, received_at=NOW, source_mode="official_sdk_push")
            self.assertIs(result, expected)

    def test_initial_snapshot_or_blocked_quote_cannot_supply_daily_or_entry(self):
        state = {}
        quote(state, CLOSE - timedelta(seconds=1), source_mode="official_sdk_initial_snapshot")
        quote(state, CLOSE + timedelta(seconds=1))
        self.assertEqual(daily(state), [])
        state = {}
        quote(state, CLOSE - timedelta(seconds=1))
        quote(state, CLOSE + timedelta(seconds=1), values=(112, 115, 111, 114, None))
        self.assertEqual(daily(state), [])

    def test_inactive_symbol_and_prior_session_quotes_cannot_replay(self):
        state = {}
        quote(state, CLOSE - timedelta(seconds=1))
        quote(state, CLOSE + timedelta(seconds=1))
        self.assertEqual(daily(state, active={"different-current-event"}), [])
        quote(state, CLOSE + timedelta(days=1, seconds=1))
        self.assertEqual(daily(state), [])

    def test_old_enrichment_is_removed_when_no_valid_next_quote_exists(self):
        row = dict(bar(), next_bar_first_quote_price="999", next_bar_first_quote_at=runtime.to_iso(NOW), next_bar_entry_source="old")
        result = sdk_runtime.attach_next_bar_first_quotes([row], {}, now=NOW)[0]
        self.assertNotIn("next_bar_first_quote_price", result)
        self.assertEqual(row["next_bar_first_quote_price"], "999")

    def test_quote_snapshots_remain_bounded_without_nested_indexes(self):
        state = {}
        for index in range(1000):
            quote(state, CLOSE + timedelta(seconds=index))
        snapshots = state["TEST"]["bar_quote_snapshots"]
        self.assertLessEqual(len(snapshots), 2)
        for bucket in snapshots.values():
            self.assertEqual(set(bucket), {"first", "last"})
            self.assertTrue(all("bar_quote_snapshots" not in row for row in bucket.values()))


if __name__ == "__main__":
    unittest.main()
