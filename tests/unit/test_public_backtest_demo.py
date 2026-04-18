from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from src.backtest import BacktestReport, BacktestStats
from src.strategy.contracts import KnowledgeAtomHit


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "public_backtest_demo_lib.py"
SPEC = importlib.util.spec_from_file_location("public_backtest_demo_lib", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PublicBacktestDemoTests(unittest.TestCase):
    def test_build_ohlcv_row_round_trip_schema(self) -> None:
        instrument = MODULE.InstrumentConfig(
            ticker="NVDA",
            symbol="NVDA",
            label="NVIDIA",
            market="US",
            timezone="America/New_York",
            demo_role="trend",
        )
        row = MODULE.build_ohlcv_row(
            instrument=instrument,
            interval="1d",
            trading_date=MODULE.date.fromisoformat("2024-01-02"),
            open_value="10.10",
            high_value="11.20",
            low_value="9.90",
            close_value="10.80",
            volume_value="1200",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "cache.csv"
            MODULE.write_cache_csv(csv_path, [row])
            loaded = MODULE.load_ohlcv_csv(csv_path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].symbol, "NVDA")
        self.assertEqual(loaded[0].market, "US")
        self.assertEqual(loaded[0].timeframe, "1d")
        self.assertEqual(loaded[0].timezone, "America/New_York")

    def test_compute_demo_quantity_uses_risk_budget_and_equity(self) -> None:
        trade = MODULE.TradeRecord(
            signal_id="sig-1",
            symbol="NVDA",
            market="US",
            timeframe="1d",
            direction="long",
            setup_type="demo_setup",
            signal_bar_index=1,
            signal_bar_timestamp=MODULE.datetime.now(MODULE.UTC),
            entry_bar_index=2,
            entry_timestamp=MODULE.datetime.now(MODULE.UTC),
            entry_price=MODULE.Decimal("50"),
            stop_price=MODULE.Decimal("48"),
            target_price=MODULE.Decimal("54"),
            exit_bar_index=3,
            exit_timestamp=MODULE.datetime.now(MODULE.UTC),
            exit_price=MODULE.Decimal("54"),
            exit_reason="target_hit",
            risk_per_share=MODULE.Decimal("2"),
            pnl_per_share=MODULE.Decimal("4"),
            pnl_r=MODULE.Decimal("2"),
            bars_held=1,
            source_refs=("wiki:test",),
            explanation="demo",
            risk_notes=("demo",),
        )
        quantity = MODULE.compute_demo_quantity(
            trade=trade,
            current_equity=MODULE.Decimal("1000"),
            risk_per_trade=MODULE.Decimal("100"),
        )
        self.assertEqual(quantity, MODULE.Decimal("20"))

    @unittest.skipUnless(MODULE.plt is not None, "matplotlib not available in the active interpreter")
    def test_create_backtest_run_from_cached_fixture_generates_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            cache_dir = temp_root / "cache"
            report_dir = temp_root / "reports"
            config_path = temp_root / "demo.json"
            config_path.write_text(
                json.dumps(
                    {
                        "title": "Unit Demo",
                        "description": "Unit-test smoke demo.",
                        "start": "2026-01-05",
                        "end": "2026-01-05",
                        "interval": "5m",
                        "cache_dir": str(cache_dir),
                        "report_dir": str(report_dir),
                        "source_order": ["yfinance"],
                        "splits": [
                            {
                                "name": "unit_split",
                                "label": "Unit Split",
                                "start": "2026-01-05",
                                "end": "2026-01-05"
                            }
                        ],
                        "regimes": [
                            {
                                "name": "unit_regime",
                                "label": "Unit Regime",
                                "start": "2026-01-05",
                                "end": "2026-01-05"
                            }
                        ],
                        "instruments": [
                            {
                                "ticker": "SAMPLE",
                                "symbol": "SAMPLE",
                                "label": "Sample",
                                "market": "US",
                                "timezone": "America/New_York",
                                "demo_role": "smoke"
                            }
                        ],
                        "risk": {
                            "starting_capital": "10000",
                            "risk_per_trade": "100",
                            "max_total_exposure": "10000",
                            "max_symbol_exposure_ratio": "1.00",
                            "max_daily_loss": "500",
                            "max_consecutive_losses": 4
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = MODULE.load_demo_config(config_path)
            cache_path = MODULE.build_cache_path(config, config.instruments[0], source="yfinance")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "tests" / "test_data" / "ohlcv_sample_5m.csv", cache_path)
            cache_path.with_suffix(".metadata.json").write_text(
                json.dumps({"source": "yfinance", "row_count": 5}, ensure_ascii=False),
                encoding="utf-8",
            )

            outcome = MODULE.create_backtest_run(config, refresh_data=False, run_id="unit_demo")
            output_dir = Path(outcome["report_dir"])

            self.assertTrue((output_dir / "summary.json").exists())
            self.assertTrue((output_dir / "split_summary.json").exists())
            self.assertTrue((output_dir / "regime_breakdown.json").exists())
            self.assertTrue((output_dir / "knowledge_trace_coverage.json").exists())
            self.assertTrue((output_dir / "no_trade_wait.jsonl").exists())
            self.assertTrue((output_dir / "report.md").exists())
            self.assertTrue((output_dir / "trades.csv").exists())
            self.assertTrue((output_dir / "knowledge_trace.json").exists())
            self.assertTrue((output_dir / "equity_curve.png").exists())
            self.assertEqual(outcome["summary"]["boundary"], "paper/simulated")
            report_text = (output_dir / "report.md").read_text(encoding="utf-8")
            trace_payload = json.loads((output_dir / "knowledge_trace.json").read_text(encoding="utf-8"))
            summary_payload = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertTrue(
                "trace 摘要：" in report_text or "当前没有可解释的已完成交易。" in report_text
            )
            self.assertNotIn("\"match_reason\"", report_text)
            self.assertIn("## 4. Walk-forward / Split 摘要", report_text)
            self.assertIn("## 7. no-trade / wait 摘要", report_text)
            self.assertEqual(trace_payload["boundary"], "paper/simulated")
            if trace_payload["executed_trades"]:
                self.assertIn("match_reason", trace_payload["executed_trades"][0]["knowledge_trace"][0])
                self.assertIn("visible_trace", trace_payload["executed_trades"][0])
                self.assertIn("debug_trace", trace_payload["executed_trades"][0])
                self.assertIn("actual_source_refs", trace_payload["executed_trades"][0])
                self.assertIn("bundle_support_refs", trace_payload["executed_trades"][0])
                self.assertIn("evidence_refs", trace_payload["executed_trades"][0]["knowledge_trace"][0])
                self.assertIn("evidence_locator_summary", trace_payload["executed_trades"][0]["knowledge_trace"][0])
                self.assertIn("field_mappings", trace_payload["executed_trades"][0]["knowledge_trace"][0])
            self.assertIn("knowledge_trace_coverage", summary_payload)
            self.assertIn("no_trade_wait_summary", summary_payload)
            self.assertIn("sample_adequacy", summary_payload)
            self.assertEqual(
                summary_payload["sample_adequacy"]["by_split"][0]["minimum_required_executed_trades"],
                MODULE.MIN_REQUIRED_EXECUTED_TRADES_PER_SPLIT,
            )
            self.assertEqual(summary_payload["splits"][0]["name"], "unit_split")
            self.assertEqual(summary_payload["regimes"][0]["name"], "unit_regime")
            self.assertNotIn(b"\r\n", (output_dir / "trades.csv").read_bytes())

    def test_write_knowledge_trace_json_keeps_full_trace_and_blocked_paths(self) -> None:
        signal = self._signal_with_trace(trace_count=5)
        executed = self._executed_trade(signal)
        blocked = MODULE.BlockedSignalRecord(
            instrument=executed.instrument,
            signal=signal,
            entry_timestamp=executed.trade.entry_timestamp,
            reason_codes=("risk_block",),
            message="blocked before fill",
        )
        paper_outcome = MODULE.PaperDemoOutcome(
            executed_trades=(executed,),
            blocked_signals=(blocked,),
            equity_points=((MODULE.datetime.now(MODULE.UTC).isoformat(), 10000.0),),
            ending_equity=MODULE.Decimal("10000"),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "knowledge_trace.json"
            MODULE.write_knowledge_trace_json(
                output_path,
                run_id="unit_trace",
                paper_outcome=paper_outcome,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["executed_trades"][0]["knowledge_trace"]), 5)
        self.assertEqual(payload["executed_trades"][0]["knowledge_trace"], payload["executed_trades"][0]["visible_trace"])
        self.assertEqual(len(payload["blocked_signals"][0]["knowledge_trace"]), 5)
        self.assertTrue(payload["executed_trades"][0]["bundle_support_refs"])
        self.assertTrue(payload["executed_trades"][0]["debug_trace"])
        self.assertIn("evidence_refs", payload["executed_trades"][0]["knowledge_trace"][0])
        self.assertIn("field_mappings", payload["executed_trades"][0]["knowledge_trace"][0])
        self.assertEqual(payload["boundary"], "paper/simulated")

    def test_markdown_report_limits_trace_summary_to_three_items(self) -> None:
        signal = self._signal_with_trace(trace_count=5)
        executed = self._executed_trade(signal)
        summary_row = MODULE.trade_to_summary_row(executed)
        report = self._backtest_report(signal.signal_id)
        result = MODULE.SymbolBacktestResult(
            instrument=executed.instrument,
            source="fixture",
            csv_path=ROOT / "tests" / "test_data" / "ohlcv_sample_5m.csv",
            metadata_path=ROOT / "tests" / "test_data" / "README.md",
            bars=(),
            bars_count=5,
            signals=(signal,),
            backtest_report=report,
        )
        summary = {
            "title": "Unit Trace Report",
            "symbols": [executed.instrument.symbol],
            "time_range": {"start": "2026-01-05", "end": "2026-01-05", "interval": "5m"},
            "splits": [{"name": "unit", "label": "Unit Split", "start": "2026-01-05", "end": "2026-01-05"}],
            "regimes": [{"name": "unit", "label": "Unit Regime", "start": "2026-01-05", "end": "2026-01-05"}],
            "data_source": ["fixture"],
            "cache_dir": "/tmp/cache",
            "report_dir": "/tmp/report",
            "cash_note": "unit test",
            "core_results": {
                "total_pnl": "20.0000",
                "total_return_pct": "0.2000",
                "max_drawdown": "0.0000",
                "max_drawdown_pct": "0.0000",
                "trade_count": 1,
                "blocked_signals": 0,
                "no_trade_wait": 1,
                "win_rate_pct": "100.0000",
                "profit_factor": "N/A",
            },
            "per_symbol": [
                {
                    "symbol": executed.instrument.symbol,
                    "label": executed.instrument.label,
                    "source": "fixture",
                    "bars": 5,
                    "signals": 1,
                    "baseline_trades": 1,
                    "executed_trades": 1,
                    "blocked_signals": 0,
                    "no_trade_wait": 1,
                    "pnl_cash": "20.0000",
                    "win_rate_pct": "100.0000",
                    "trace_curated_signal_pct": "100.0000",
                    "trace_statement_signal_pct": "100.0000",
                }
            ],
            "split_summary_overview": [
                {
                    "label": "Unit Split",
                    "start": "2026-01-05",
                    "end": "2026-01-05",
                    "signal_count": 1,
                    "executed_trades": 1,
                    "blocked_signals": 0,
                    "no_trade_wait": 1,
                    "pnl_cash": "20.0000",
                    "win_rate_pct": "100.0000",
                    "trace_curated_signal_pct": "100.0000",
                    "trace_statement_signal_pct": "100.0000",
                }
            ],
            "regime_breakdown_overview": [
                {
                    "label": "Unit Regime",
                    "start": "2026-01-05",
                    "end": "2026-01-05",
                    "signal_count": 1,
                    "executed_trades": 1,
                    "blocked_signals": 0,
                    "no_trade_wait": 1,
                    "pnl_cash": "20.0000",
                    "win_rate_pct": "100.0000",
                    "trace_curated_signal_pct": "100.0000",
                    "trace_statement_signal_pct": "100.0000",
                }
            ],
            "sample_adequacy": {
                "overall_verdict": "insufficient_sample",
                "by_split": [
                    {
                        "split_name": "unit",
                        "split_label": "Unit Split",
                        "executed_trade_count": 1,
                        "minimum_required_executed_trades": 5,
                        "verdict": "insufficient_sample",
                    }
                ],
            },
            "knowledge_trace_coverage": {
                "total_signals": 1,
                "trace_nonempty_pct": "100.0000",
                "curated_signal_pct": "100.0000",
                "statement_signal_pct": "100.0000",
                "actual_hit_source_family_presence": {"curated_concept": 1, "al_brooks_ppt": 1},
                "actual_hit_source_family_item_counts": {"curated_concept": 1, "al_brooks_ppt": 2},
                "actual_evidence_source_family_presence": {"curated_concept": 1, "al_brooks_ppt": 1},
                "actual_evidence_source_family_item_counts": {"curated_concept": 1, "al_brooks_ppt": 2},
                "bundle_support_family_presence": {"curated_rule": 1},
                "bundle_support_family_item_counts": {"curated_rule": 1},
                "source_family_signal_presence": {"curated_concept": 1, "al_brooks_ppt": 1},
                "curated_vs_statement": {"curated_item_pct": "60.0000", "statement_item_pct": "40.0000"},
            },
            "no_trade_wait_summary": {
                "total_records": 1,
                "actions": {"wait": 1},
                "reason_counts": {"context_not_trend": 1},
                "examples": [
                    {
                        "symbol": "SAMPLE",
                        "timestamp": "2026-01-05T16:00:00+00:00",
                        "action": "wait",
                        "reason_code": "context_not_trend",
                        "reason_detail": "range",
                    }
                ],
            },
            "best_trades": [summary_row],
            "worst_trades": [summary_row],
            "blocked_examples": [],
            "limitations": ["unit test"],
        }
        paper_outcome = MODULE.PaperDemoOutcome(
            executed_trades=(executed,),
            blocked_signals=(),
            equity_points=((MODULE.datetime.now(MODULE.UTC).isoformat(), 10000.0),),
            ending_equity=MODULE.Decimal("10000"),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.md"
            MODULE.write_markdown_report(
                report_path,
                summary=summary,
                symbol_results=(result,),
                paper_outcome=paper_outcome,
            )
            report_text = report_path.read_text(encoding="utf-8")

        self.assertIn("atom-trace-0", report_text)
        self.assertIn("atom-trace-1", report_text)
        self.assertIn("atom-trace-2", report_text)
        self.assertNotIn("atom-trace-3", report_text)
        self.assertNotIn("atom-trace-4", report_text)
        self.assertIn("### 样本充分性", report_text)
        self.assertIn("insufficient_sample（验证诚实但样本不足）", report_text)

    def test_serialize_repo_logical_path_uses_repo_relative_when_possible(self) -> None:
        repo_path = ROOT / "reports" / "backtests" / "m8c1_long_horizon_daily_validation" / "summary.json"
        outside_path = Path("/tmp/pat-outside-summary.json")

        self.assertEqual(
            MODULE.serialize_repo_logical_path(repo_path),
            "reports/backtests/m8c1_long_horizon_daily_validation/summary.json",
        )
        self.assertEqual(MODULE.serialize_repo_logical_path(outside_path), str(outside_path))

    def test_write_trades_csv_uses_lf_line_endings(self) -> None:
        signal = self._signal_with_trace(trace_count=1)
        executed = self._executed_trade(signal)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "trades.csv"
            MODULE.write_trades_csv(output_path, (executed,))
            payload = output_path.read_bytes()

        self.assertNotIn(b"\r\n", payload)
        self.assertTrue(payload.endswith(b"\n"))

    def test_write_no_trade_wait_jsonl_keeps_structured_records(self) -> None:
        signal = self._signal_with_trace(trace_count=3)
        record = MODULE.NoTradeWaitRecord(
            symbol="SAMPLE",
            market="US",
            timeframe="5m",
            timestamp=MODULE.datetime.now(MODULE.UTC),
            action="wait",
            reason_code="context_not_trend",
            reason_detail="recent closes are compressed into a narrow range",
            decision_site="signal_scan",
            pa_context="trading-range",
            regime_summary="recent closes are compressed into a narrow range",
            source_refs=("wiki:knowledge/wiki/concepts/market-cycle-overview.md",),
            actual_source_refs=(),
            bundle_support_refs=("wiki:knowledge/wiki/concepts/market-cycle-overview.md",),
            signal_id=signal.signal_id,
            reason_codes=("context_not_trend",),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "no_trade_wait.jsonl"
            MODULE.write_no_trade_wait_jsonl(output_path, (record,))
            lines = output_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["boundary"], "paper/simulated")
        self.assertEqual(payload["reason_code"], "context_not_trend")
        self.assertEqual(payload["action"], "wait")
        self.assertEqual(payload["source_refs"], [])
        self.assertEqual(payload["actual_source_refs"], [])
        self.assertEqual(
            payload["bundle_support_refs"],
            ["wiki:knowledge/wiki/concepts/market-cycle-overview.md"],
        )
        self.assertEqual(
            payload["legacy_source_refs"],
            ["wiki:knowledge/wiki/concepts/market-cycle-overview.md"],
        )

    def test_trace_coverage_uses_capped_trace_not_raw_statement_population(self) -> None:
        signal = self._signal_with_trace(trace_count=5)
        result = MODULE.SymbolBacktestResult(
            instrument=self._executed_trade(signal).instrument,
            source="fixture",
            csv_path=ROOT / "tests" / "test_data" / "ohlcv_sample_5m.csv",
            metadata_path=ROOT / "tests" / "test_data" / "README.md",
            bars=(),
            bars_count=5,
            signals=(signal,),
            backtest_report=self._backtest_report(signal.signal_id),
        )
        executed = self._executed_trade(signal)
        paper_outcome = MODULE.PaperDemoOutcome(
            executed_trades=(executed,),
            blocked_signals=(),
            equity_points=((MODULE.datetime.now(MODULE.UTC).isoformat(), 10000.0),),
            ending_equity=MODULE.Decimal("10020"),
        )

        coverage = MODULE.build_knowledge_trace_coverage((result,), paper_outcome)

        self.assertEqual(coverage["overall"]["total_signals"], 1)
        self.assertEqual(coverage["overall"]["curated_signals"], 1)
        self.assertEqual(coverage["overall"]["statement_signals"], 1)
        self.assertEqual(coverage["overall"]["actual_hit_source_family_presence"]["al_brooks_ppt"], 1)
        self.assertEqual(coverage["overall"]["actual_evidence_source_family_presence"]["al_brooks_ppt"], 1)
        self.assertEqual(coverage["overall"]["bundle_support_family_presence"]["curated_rule"], 1)
        self.assertLessEqual(
            coverage["overall"]["curated_vs_statement"]["statement_item_count"],
            len(signal.knowledge_trace),
        )

    def _signal_with_trace(self, *, trace_count: int) -> MODULE.Signal:
        trace: list[KnowledgeAtomHit] = []
        if trace_count >= 1:
            trace.append(
                KnowledgeAtomHit(
                    atom_id="atom-trace-0",
                    atom_type="concept",
                    source_ref="wiki:knowledge/wiki/concepts/market-cycle-overview.md",
                    raw_locator={"locator_kind": "page_block", "page_no": 1, "block_index": 0},
                    match_reason="unit_trace",
                    applicability_state="matched",
                )
            )
        if trace_count >= 2:
            trace.append(
                KnowledgeAtomHit(
                    atom_id="atom-trace-1",
                    atom_type="setup",
                    source_ref="wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md",
                    raw_locator={"locator_kind": "page_block", "page_no": 1, "block_index": 1},
                    match_reason="unit_trace",
                    applicability_state="matched",
                )
            )
        for index in range(2, trace_count):
            trace.append(
                KnowledgeAtomHit(
                    atom_id=f"atom-trace-{index}",
                    atom_type="statement",
                    source_ref="wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md",
                    raw_locator={
                        "locator_kind": "page_block",
                        "page_no": 1,
                        "block_index": 2,
                        "fragment_index": index - 2,
                    },
                    match_reason="unit_trace",
                    applicability_state="supporting",
                )
            )
        trace = tuple(trace)
        return MODULE.Signal(
            signal_id="sig-trace",
            symbol="SAMPLE",
            market="US",
            timeframe="5m",
            direction="long",
            setup_type="signal_bar_entry_placeholder",
            pa_context="trend",
            entry_trigger="placeholder entry",
            stop_rule="signal-bar low",
            target_rule="2R target",
            invalidation="close back below prior high",
            confidence="low",
            source_refs=tuple(
                dict.fromkeys(
                    [*(hit.source_ref for hit in trace), "wiki:knowledge/wiki/rules/m3-research-reference-pack.md"]
                )
            ),
            actual_source_refs=tuple(hit.source_ref for hit in trace),
            bundle_support_refs=("wiki:knowledge/wiki/rules/m3-research-reference-pack.md",),
            explanation="unit trace explanation",
            risk_notes=("research-only placeholder",),
            knowledge_trace=trace,
            knowledge_debug_trace=(
                KnowledgeAtomHit(
                    atom_id="rule-support-1",
                    atom_type="rule",
                    source_ref="wiki:knowledge/wiki/rules/m3-research-reference-pack.md",
                    raw_locator={"locator_kind": "bundle_support_summary", "label": "bundle_support[3 sources/42 chunks]"},
                    match_reason="bundle_rule_support",
                    applicability_state="supporting",
                    reference_tier="bundle_support",
                ),
            ),
        )

    def _executed_trade(self, signal: MODULE.Signal) -> MODULE.ExecutedTradeRecord:
        instrument = MODULE.InstrumentConfig(
            ticker="SAMPLE",
            symbol="SAMPLE",
            label="Sample",
            market="US",
            timezone="America/New_York",
            demo_role="smoke",
        )
        trade = MODULE.TradeRecord(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            market=signal.market,
            timeframe=signal.timeframe,
            direction=signal.direction,
            setup_type=signal.setup_type,
            signal_bar_index=2,
            signal_bar_timestamp=MODULE.datetime.now(MODULE.UTC),
            entry_bar_index=3,
            entry_timestamp=MODULE.datetime.now(MODULE.UTC),
            entry_price=MODULE.Decimal("100"),
            stop_price=MODULE.Decimal("99"),
            target_price=MODULE.Decimal("102"),
            exit_bar_index=4,
            exit_timestamp=MODULE.datetime.now(MODULE.UTC),
            exit_price=MODULE.Decimal("102"),
            exit_reason="target_hit",
            risk_per_share=MODULE.Decimal("1"),
            pnl_per_share=MODULE.Decimal("2"),
            pnl_r=MODULE.Decimal("2"),
            bars_held=1,
            source_refs=signal.source_refs,
            explanation=signal.explanation,
            risk_notes=signal.risk_notes,
        )
        return MODULE.ExecutedTradeRecord(
            instrument=instrument,
            signal=signal,
            trade=trade,
            quantity=MODULE.Decimal("10"),
            pnl_cash=MODULE.Decimal("20"),
            equity_after_close=MODULE.Decimal("10020"),
        )

    def _backtest_report(self, signal_id: str) -> BacktestReport:
        trade = self._executed_trade(self._signal_with_trace(trace_count=3)).trade
        trade = MODULE.TradeRecord(
            signal_id=signal_id,
            symbol=trade.symbol,
            market=trade.market,
            timeframe=trade.timeframe,
            direction=trade.direction,
            setup_type=trade.setup_type,
            signal_bar_index=trade.signal_bar_index,
            signal_bar_timestamp=trade.signal_bar_timestamp,
            entry_bar_index=trade.entry_bar_index,
            entry_timestamp=trade.entry_timestamp,
            entry_price=trade.entry_price,
            stop_price=trade.stop_price,
            target_price=trade.target_price,
            exit_bar_index=trade.exit_bar_index,
            exit_timestamp=trade.exit_timestamp,
            exit_price=trade.exit_price,
            exit_reason=trade.exit_reason,
            risk_per_share=trade.risk_per_share,
            pnl_per_share=trade.pnl_per_share,
            pnl_r=trade.pnl_r,
            bars_held=trade.bars_held,
            source_refs=trade.source_refs,
            explanation=trade.explanation,
            risk_notes=trade.risk_notes,
        )
        return BacktestReport(
            trades=(trade,),
            stats=BacktestStats(
                total_signals=1,
                trade_count=1,
                closed_trade_count=1,
                win_count=1,
                loss_count=0,
                win_rate=MODULE.Decimal("1.0000"),
                average_win_r=MODULE.Decimal("2.0000"),
                average_loss_r=MODULE.Decimal("0.0000"),
                expectancy_r=MODULE.Decimal("2.0000"),
                total_pnl_r=MODULE.Decimal("2.0000"),
                profit_factor=None,
                max_drawdown_r=MODULE.Decimal("0.0000"),
                trades_per_100_bars=MODULE.Decimal("20.0000"),
                slippage_sensitivity=(),
            ),
            summary="unit",
            warnings=(),
            assumptions=(),
        )


if __name__ == "__main__":
    unittest.main()
