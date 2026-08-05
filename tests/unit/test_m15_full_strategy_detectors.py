from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from scripts.m15_full_strategy_detectors_lib import (
    pa001_daily_long,
    pa002_five_minute_long,
    pa012_five_minute_long,
)
from scripts.m15_longbridge_sdk_runtime_lib import attach_next_bar_first_quotes
from scripts.run_m15_longbridge_sdk_runtime import historical_daily_context_before_session
from scripts.m15_longbridge_realtime_signal_router_lib import (
    PRICE_ACTION_RUNTIME_SPECS,
    ftd_pullback_guard_confirm_signal,
)


class M15FullStrategyDetectorsTest(unittest.TestCase):
    def bar(
        self,
        index: int,
        *,
        timeframe: str = "5m",
        open_price: float = 99,
        high: float = 100,
        low: float = 98,
        close: float = 99,
        start: datetime | None = None,
        next_quote: float | None = None,
        volume: float = 1000,
    ) -> dict[str, object]:
        base = start or datetime(2026, 8, 3, 13, 30, tzinfo=UTC)
        step = timedelta(days=index) if timeframe == "1d" else timedelta(minutes=5 * index)
        event_time = base + step
        row: dict[str, object] = {
            "event_id": f"{timeframe}-{index}",
            "symbol": "TEST",
            "timeframe": timeframe,
            "event_time": event_time.isoformat().replace("+00:00", "Z"),
            "bar_open_at": (event_time - (timedelta(days=1) if timeframe == "1d" else timedelta(minutes=5))).isoformat().replace("+00:00", "Z"),
            "bar_close_at": event_time.isoformat().replace("+00:00", "Z"),
            "received_at": event_time.isoformat().replace("+00:00", "Z"),
            "bar_final": True,
            "open": str(open_price),
            "high": str(high),
            "low": str(low),
            "close": str(close),
            "volume": str(volume),
        }
        if next_quote is not None:
            row["next_bar_first_quote_price"] = str(next_quote)
            row["next_bar_first_quote_at"] = (event_time + timedelta(milliseconds=50)).isoformat().replace("+00:00", "Z")
            row["next_bar_entry_source"] = "longbridge_sdk_first_quote_after_bar_close"
        return row

    def test_sdk_bar_gets_first_quote_after_close_as_next_bar_entry(self) -> None:
        row = self.bar(1)
        quote_at = datetime.fromisoformat(str(row["bar_close_at"]).replace("Z", "+00:00")) + timedelta(milliseconds=25)
        enriched = attach_next_bar_first_quotes(
            [row],
            {
                "TEST": {
                    "close": "101.25",
                    "received_at": quote_at.isoformat().replace("+00:00", "Z"),
                    "source_event_at": quote_at.isoformat().replace("+00:00", "Z"),
                }
            },
        )
        self.assertEqual(enriched[0]["next_bar_first_quote_price"], "101.25")
        self.assertEqual(enriched[0]["next_bar_entry_source"], "longbridge_sdk_first_quote_after_bar_close")

    def test_sdk_daily_context_excludes_current_partial_day_and_keeps_prior_history(self) -> None:
        rows = [
            self.bar(0, timeframe="1d"),
            self.bar(1, timeframe="1d"),
            self.bar(2, timeframe="1d"),
        ]
        result = historical_daily_context_before_session(
            rows,
            generated_at=datetime(2026, 8, 5, 15, 0, tzinfo=UTC),
        )
        self.assertEqual([row["event_id"] for row in result], ["1d-0", "1d-1"])

    def test_pa002_uses_strict_twenty_bar_range_and_next_quote(self) -> None:
        rows = [self.bar(index, high=100, low=90, close=95) for index in range(20)]
        rows.append(self.bar(20, open_price=99, high=103, low=99, close=102.5))
        rows.append(self.bar(21, open_price=102.5, high=104, low=101.5, close=103, next_quote=103.2))
        signal = pa002_five_minute_long("TEST", rows)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal["limit_price"], "103.2")
        self.assertEqual(signal["stop_price"], "99")
        self.assertEqual(signal["target_price"], "113.2")
        self.assertEqual(signal["contract_evidence"]["range_lookback_bars"], 20)
        self.assertEqual(signal["entry_timing"], "next_bar_first_quote")

    def test_pa002_does_not_emit_without_next_bar_quote(self) -> None:
        rows = [self.bar(index, high=100, low=90, close=95) for index in range(20)]
        rows.extend([
            self.bar(20, open_price=99, high=103, low=99, close=102.5),
            self.bar(21, open_price=102.5, high=104, low=101.5, close=103),
        ])
        self.assertIsNone(pa002_five_minute_long("TEST", rows))

    def test_pa012_uses_six_bar_opening_range_and_measured_target(self) -> None:
        rows = [self.bar(index, high=101, low=99, close=100) for index in range(6)]
        rows.append(self.bar(6, open_price=100.5, high=103, low=100.5, close=102.5))
        rows.append(self.bar(7, open_price=102.5, high=104, low=102, close=103, next_quote=103.1))
        signal = pa012_five_minute_long("TEST", rows)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal["stop_price"], "99")
        self.assertEqual(signal["target_price"], "105.1")
        self.assertEqual(signal["contract_evidence"]["forced_exit_time_ny"], "15:55")

    def test_pa001_requires_h2_style_pullback_and_uses_two_r(self) -> None:
        closes = [100 + index for index in range(14)] + [112, 111, 112, 111, 112, 111, 112]
        lows = [value - 1 for value in closes]
        lows[15] = 109
        lows[17] = 108
        lows[19] = 109
        rows = [
            self.bar(
                index,
                timeframe="1d",
                open_price=close - 0.5,
                high=close + 1,
                low=lows[index],
                close=close,
            )
            for index, close in enumerate(closes)
        ]
        rows.append(self.bar(21, timeframe="1d", open_price=112, high=115, low=111, close=114, next_quote=114.2))
        signal = pa001_daily_long("TEST", rows)
        self.assertIsNotNone(signal)
        assert signal is not None
        risk = float(signal["limit_price"]) - float(signal["stop_price"])
        reward = float(signal["target_price"]) - float(signal["limit_price"])
        self.assertAlmostEqual(reward / risk, 2.0, places=6)
        self.assertGreaterEqual(signal["contract_evidence"]["countertrend_bar_count"], 2)
        self.assertGreaterEqual(signal["contract_evidence"]["confirmed_pullback_low_count"], 2)

    def test_ftd_contract_requires_follow_through_and_keeps_market_context_audit_only(self) -> None:
        rows = [
            self.bar(index, timeframe="1d", open_price=100, high=101, low=98, close=100, volume=1000)
            for index in range(21)
        ]
        rows[-1]["high"] = "104"
        rows.append(self.bar(21, timeframe="1d", open_price=100, high=103, low=99.5, close=102, volume=1200))
        rows.append(self.bar(22, timeframe="1d", open_price=102, high=104, low=101, close=103, volume=1100))
        rows.append(self.bar(23, timeframe="1d", open_price=103, high=105, low=102, close=104, volume=1100, next_quote=104.2))

        signal = ftd_pullback_guard_confirm_signal(
            "TEST",
            rows,
            spec=PRICE_ACTION_RUNTIME_SPECS["M12-FTD-001-pullback-guard-confirm-1d"],
            grouped_events={('TEST', '1d'): rows},
            generated_at=datetime(2026, 8, 5, 20, 0, tzinfo=UTC),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal["entry_timing"], "next_bar_first_quote")
        self.assertEqual(signal["contract_evidence"]["target_model"], "2R")
        self.assertFalse(signal["contract_evidence"]["market_context_is_blocker"])


if __name__ == "__main__":
    unittest.main()
