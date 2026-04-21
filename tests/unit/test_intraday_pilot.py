from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

from src.backtest import BacktestReport, BacktestStats, TradeRecord
from src.strategy.contracts import KnowledgeAtomHit, Signal

from tests._intraday_support import build_session_rows


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "intraday_pilot_lib.py"
SPEC = importlib.util.spec_from_file_location("intraday_pilot_lib", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class IntradayPilotUnitTests(unittest.TestCase):
    def test_load_intraday_config_defaults_to_longbridge_when_source_order_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "intraday.json"
            config_path.write_text(
                json.dumps(
                    {
                        "title": "Intraday Fixture Pilot",
                        "start": "2026-01-05",
                        "end": "2026-01-06",
                        "interval": "15m",
                        "cache_dir": str(Path(temp_dir) / "cache"),
                        "report_dir": str(Path(temp_dir) / "reports"),
                        "instrument": {
                            "ticker": "SPY",
                            "symbol": "SPY",
                            "label": "SPDR S&P 500 ETF",
                            "market": "US",
                            "timezone": "America/New_York"
                        },
                        "risk": {
                            "starting_capital": "25000",
                            "risk_per_trade": "100",
                            "max_total_exposure": "25000",
                            "max_symbol_exposure_ratio": "1.00",
                            "max_daily_loss": "1000",
                            "max_consecutive_losses": 4
                        },
                        "session": {
                            "timezone": "America/New_York",
                            "regular_open": "09:30",
                            "regular_close": "16:00",
                            "expected_bars_per_session": 26,
                            "allow_extended_hours": False
                        },
                        "costs": {
                            "slippage_bps": "2",
                            "fee_per_order": "0"
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            config = MODULE.load_intraday_pilot_config(config_path)

        self.assertEqual(config.source_order, ("longbridge",))

    def test_audit_intraday_sessions_flags_missing_and_out_of_hours(self) -> None:
        rows = build_session_rows(
            date.fromisoformat("2026-01-05"),
            include_out_of_hours=True,
            drop_bar_at="11:00",
        )
        bars = [MODULE.OhlcvRow(**row_to_payload(row)) for row in rows]

        audits = MODULE.audit_intraday_sessions(
            bars,
            timeframe="15m",
            timezone_name="America/New_York",
            expected_bars_per_session=26,
            allow_extended_hours=False,
        )

        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertFalse(audit.complete)
        self.assertFalse(audit.used_for_pilot)
        self.assertEqual(audit.missing_bar_count, 1)
        self.assertEqual(audit.out_of_hours_bar_count, 1)
        self.assertEqual(audit.skipped_reason, "data_gap_or_incomplete_session")

    def test_run_intraday_paper_demo_resets_session_and_applies_costs(self) -> None:
        first = _build_symbol_result(
            session_date="2026-01-05",
            signal_id="sig-loss",
            direction="long",
            entry_price="100",
            stop_price="99",
            target_price="102",
            exit_price="99",
            exit_reason="stop_hit",
        )
        second = _build_symbol_result(
            session_date="2026-01-06",
            signal_id="sig-win",
            direction="long",
            entry_price="100",
            stop_price="99",
            target_price="102",
            exit_price="102",
            exit_reason="target_hit",
        )
        outcome, reset_map = MODULE.run_intraday_paper_demo(
            (first, second),
            risk_settings=MODULE.DemoRiskSettings(
                starting_capital=Decimal("10000"),
                risk_per_trade=Decimal("200"),
                max_total_exposure=Decimal("15000"),
                max_symbol_exposure_ratio=Decimal("1"),
                max_daily_loss=Decimal("1000"),
                max_consecutive_losses=1,
            ),
            costs=MODULE.IntradayCostModel(
                slippage_bps=Decimal("10"),
                fee_per_order=Decimal("1"),
            ),
        )

        self.assertEqual(len(outcome.executed_trades), 2)
        self.assertEqual(len(outcome.blocked_signals), 0)
        self.assertFalse(reset_map["2026-01-05"])
        self.assertTrue(reset_map["2026-01-06"])
        self.assertLess(outcome.executed_trades[1].pnl_cash, Decimal("200"))

    def test_audit_intraday_sessions_accepts_complete_five_minute_session(self) -> None:
        rows = build_session_rows(
            date.fromisoformat("2026-01-05"),
            timeframe="5m",
        )
        bars = [MODULE.OhlcvRow(**row_to_payload(row)) for row in rows]

        audits = MODULE.audit_intraday_sessions(
            bars,
            timeframe="5m",
            timezone_name="America/New_York",
            expected_bars_per_session=78,
            allow_extended_hours=False,
        )

        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertTrue(audit.complete)
        self.assertTrue(audit.used_for_pilot)
        self.assertEqual(audit.missing_bar_count, 0)
        self.assertEqual(audit.out_of_hours_bar_count, 0)
        self.assertEqual(audit.regular_bar_count, 78)
        self.assertEqual(audit.last_bar_timestamp.time().strftime("%H:%M"), "15:55")

    def test_duplicate_signal_is_still_blocked_in_intraday_wrapper(self) -> None:
        first = _build_symbol_result(
            session_date="2026-01-05",
            signal_id="sig-dup",
            direction="long",
            entry_price="100",
            stop_price="99",
            target_price="102",
            exit_price="102",
            exit_reason="target_hit",
        )
        second = _build_symbol_result(
            session_date="2026-01-05",
            signal_id="sig-dup",
            direction="long",
            entry_price="100.5",
            stop_price="99.5",
            target_price="102.5",
            exit_price="102.5",
            exit_reason="target_hit",
            entry_time="11:00:00",
            exit_time="11:30:00",
        )
        outcome, _ = MODULE.run_intraday_paper_demo(
            (first, second),
            risk_settings=MODULE.DemoRiskSettings(
                starting_capital=Decimal("10000"),
                risk_per_trade=Decimal("100"),
                max_total_exposure=Decimal("20000"),
                max_symbol_exposure_ratio=Decimal("1"),
                max_daily_loss=Decimal("1000"),
                max_consecutive_losses=4,
            ),
            costs=MODULE.IntradayCostModel(
                slippage_bps=Decimal("0"),
                fee_per_order=Decimal("0"),
            ),
        )

        self.assertEqual(len(outcome.executed_trades), 1)
        self.assertEqual(len(outcome.blocked_signals), 1)
        self.assertEqual(outcome.blocked_signals[0].reason_codes, ("duplicate_signal",))

    def test_source_family_presence_counts_signals_not_statement_volume(self) -> None:
        signal = _build_signal(
            signal_id="sig-trace",
            session_date="2026-01-05",
            direction="long",
            statement_count=8,
        )
        result = _build_symbol_result_from_signal(
            signal,
            session_date="2026-01-05",
            exit_price="102",
            exit_reason="target_hit",
        )
        executed = MODULE.ExecutedTradeRecord(
            instrument=result.instrument,
            signal=signal,
            trade=result.backtest_report.trades[0],
            quantity=Decimal("1"),
            pnl_cash=Decimal("2"),
            equity_after_close=Decimal("10002"),
        )
        coverage = MODULE.build_knowledge_trace_coverage(
            (result,),
            MODULE.PaperDemoOutcome(
                executed_trades=(executed,),
                blocked_signals=(),
                equity_points=((datetime.now(UTC).isoformat(), 10002.0),),
                ending_equity=Decimal("10002"),
            ),
        )

        self.assertEqual(coverage["overall"]["actual_hit_source_family_presence"]["al_brooks_ppt"], 1)
        self.assertGreater(coverage["overall"]["actual_hit_source_family_item_counts"]["al_brooks_ppt"], 1)
        self.assertEqual(coverage["overall"]["bundle_support_family_presence"]["curated_rule"], 1)

    def test_fetch_intraday_history_rows_supports_longbridge_source(self) -> None:
        instrument = MODULE.InstrumentConfig(
            ticker="SPY",
            symbol="SPY",
            label="SPDR S&P 500 ETF",
            market="US",
            timezone="America/New_York",
            demo_role="fixture",
        )
        with mock.patch.object(
            MODULE,
            "fetch_longbridge_intraday_history_rows",
            return_value=[{"symbol": "SPY"}],
        ) as fetch_mock:
            rows = MODULE.fetch_intraday_history_rows(
                instrument=instrument,
                start=date.fromisoformat("2026-01-05"),
                end=date.fromisoformat("2026-01-06"),
                interval="5m",
                source="longbridge",
                timezone_name="America/New_York",
                allow_extended_hours=False,
            )

        self.assertEqual(rows, [{"symbol": "SPY"}])
        fetch_mock.assert_called_once()

    def test_expected_session_times_supports_five_minute(self) -> None:
        expected = MODULE._expected_session_times("5m")

        self.assertEqual(len(expected), 78)
        self.assertIn("09:30", expected)
        self.assertIn("15:55", expected)


def _build_symbol_result(
    *,
    session_date: str,
    signal_id: str,
    direction: str,
    entry_price: str,
    stop_price: str,
    target_price: str,
    exit_price: str,
    exit_reason: str,
    entry_time: str = "10:15:00",
    exit_time: str = "10:45:00",
) -> MODULE.SymbolBacktestResult:
    signal = _build_signal(
        signal_id=signal_id,
        session_date=session_date,
        direction=direction,
        statement_count=2,
    )
    return _build_symbol_result_from_signal(
        signal,
        session_date=session_date,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        exit_price=exit_price,
        exit_reason=exit_reason,
        entry_time=entry_time,
        exit_time=exit_time,
    )


def _build_signal(
    *,
    signal_id: str,
    session_date: str,
    direction: str,
    statement_count: int,
) -> Signal:
    trace = [
        KnowledgeAtomHit(
            atom_id="concept-1",
            atom_type="concept",
            source_ref="wiki:knowledge/wiki/concepts/market-cycle-overview.md",
            raw_locator={"locator_kind": "chunk_set", "member_count": 2},
            match_reason="curated_context",
            applicability_state="matched",
        ),
        KnowledgeAtomHit(
            atom_id="setup-1",
            atom_type="setup",
            source_ref="wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md",
            raw_locator={"locator_kind": "chunk_set", "member_count": 2},
            match_reason="curated_setup",
            applicability_state="matched",
        ),
        KnowledgeAtomHit(
            atom_id="rule-1",
            atom_type="rule",
            source_ref="wiki:knowledge/wiki/rules/m3-research-reference-pack.md",
            raw_locator={"locator_kind": "chunk_set", "member_count": 2},
            match_reason="curated_rule",
            applicability_state="matched",
        ),
    ]
    for index in range(statement_count):
        trace.append(
            KnowledgeAtomHit(
                atom_id=f"statement-{index}",
                atom_type="statement",
                source_ref="wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md",
                raw_locator={
                    "locator_kind": "page_block",
                    "page_no": 1,
                    "block_index": 0,
                    "fragment_index": index,
                },
                match_reason="supporting_statement",
                applicability_state="supporting",
            )
        )
    return Signal(
        signal_id=signal_id,
        symbol="SPY",
        market="US",
        timeframe="15m",
        direction=direction,
        setup_type="signal_bar_entry_placeholder",
        pa_context="trend",
        entry_trigger="placeholder entry",
        stop_rule="signal-bar low",
        target_rule="2R target",
        invalidation="close back through setup",
        confidence="low",
        source_refs=tuple(
            dict.fromkeys(
                [*(hit.source_ref for hit in trace), "wiki:knowledge/wiki/rules/m3-research-reference-pack.md"]
            )
        ),
        actual_source_refs=tuple(hit.source_ref for hit in trace),
        bundle_support_refs=("wiki:knowledge/wiki/rules/m3-research-reference-pack.md",),
        explanation="unit intraday explanation",
        risk_notes=("research-only placeholder",),
        knowledge_trace=tuple(trace),
        knowledge_debug_trace=(
            KnowledgeAtomHit(
                atom_id="rule-support-1",
                atom_type="rule",
                source_ref="wiki:knowledge/wiki/rules/m3-research-reference-pack.md",
                raw_locator={"locator_kind": "bundle_support_summary", "label": "bundle_support[1 sources/26 chunks]"},
                match_reason="bundle_rule_support",
                applicability_state="supporting",
                reference_tier="bundle_support",
            ),
        ),
    )


def _build_symbol_result_from_signal(
    signal: Signal,
    *,
    session_date: str,
    entry_price: str = "100",
    stop_price: str = "99",
    target_price: str = "102",
    exit_price: str = "102",
    exit_reason: str = "target_hit",
    entry_time: str = "10:15:00",
    exit_time: str = "10:45:00",
) -> MODULE.SymbolBacktestResult:
    bars = [
        MODULE.OhlcvRow(**row_to_payload(row))
        for row in build_session_rows(date.fromisoformat(session_date))
    ][:1]
    signal_bar_timestamp = datetime.fromisoformat(f"{session_date}T10:00:00+00:00")
    entry_timestamp = datetime.fromisoformat(f"{session_date}T{entry_time}+00:00")
    exit_timestamp = datetime.fromisoformat(f"{session_date}T{exit_time}+00:00")
    pnl_per_share = (
        Decimal(exit_price) - Decimal(entry_price)
        if signal.direction == "long"
        else Decimal(entry_price) - Decimal(exit_price)
    )
    pnl_r = pnl_per_share / abs(Decimal(entry_price) - Decimal(stop_price))
    trade = TradeRecord(
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        market=signal.market,
        timeframe=signal.timeframe,
        direction=signal.direction,
        setup_type=signal.setup_type,
        signal_bar_index=1,
        signal_bar_timestamp=signal_bar_timestamp,
        entry_bar_index=2,
        entry_timestamp=entry_timestamp,
        entry_price=Decimal(entry_price),
        stop_price=Decimal(stop_price),
        target_price=Decimal(target_price),
        exit_bar_index=3,
        exit_timestamp=exit_timestamp,
        exit_price=Decimal(exit_price),
        exit_reason=exit_reason,
        risk_per_share=abs(Decimal(entry_price) - Decimal(stop_price)),
        pnl_per_share=pnl_per_share,
        pnl_r=pnl_r,
        bars_held=2,
        source_refs=signal.source_refs,
        explanation=signal.explanation,
        risk_notes=signal.risk_notes,
    )
    report = BacktestReport(
        trades=(trade,),
        stats=BacktestStats(
            total_signals=1,
            trade_count=1,
            closed_trade_count=1,
            win_count=int(trade.pnl_per_share > 0),
            loss_count=int(trade.pnl_per_share < 0),
            win_rate=Decimal("1.0000") if trade.pnl_per_share > 0 else Decimal("0.0000"),
            average_win_r=trade.pnl_r if trade.pnl_per_share > 0 else Decimal("0.0000"),
            average_loss_r=trade.pnl_r if trade.pnl_per_share < 0 else Decimal("0.0000"),
            expectancy_r=trade.pnl_r,
            total_pnl_r=trade.pnl_r,
            profit_factor=None,
            max_drawdown_r=Decimal("0.0000"),
            trades_per_100_bars=Decimal("1.0000"),
            slippage_sensitivity=(),
        ),
        summary="fixture",
        warnings=(),
        assumptions=(),
    )
    return MODULE.SymbolBacktestResult(
        instrument=MODULE.InstrumentConfig(
            ticker="SPY",
            symbol="SPY",
            label="SPDR S&P 500 ETF",
            market="US",
            timezone="America/New_York",
            demo_role="fixture",
        ),
        source="fixture",
        csv_path=ROOT / "tests" / "test_data" / "ohlcv_sample_5m.csv",
        metadata_path=ROOT / "tests" / "test_data" / "README.md",
        bars=tuple(bars),
        bars_count=len(bars),
        signals=(signal,),
        backtest_report=report,
    )


def row_to_payload(row: dict[str, str]) -> dict[str, object]:
    return {
        "symbol": row["symbol"],
        "market": row["market"],
        "timeframe": row["timeframe"],
        "timestamp": datetime.fromisoformat(row["timestamp"]).replace(tzinfo=MODULE.ZoneInfo(row["timezone"])),
        "timezone": row["timezone"],
        "open": Decimal(row["open"]),
        "high": Decimal(row["high"]),
        "low": Decimal(row["low"]),
        "close": Decimal(row["close"]),
        "volume": Decimal(row["volume"]),
    }


if __name__ == "__main__":
    unittest.main()
