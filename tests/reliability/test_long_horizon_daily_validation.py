from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from src.backtest import BacktestStats
from src.strategy.contracts import KnowledgeAtomHit

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "public_backtest_demo_lib.py"
ARTIFACT_ROOT = ROOT / "reports" / "backtests" / "m8c1_long_horizon_daily_validation"
SPEC = importlib.util.spec_from_file_location("public_backtest_demo_lib", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LongHorizonDailyValidationReliabilityTests(unittest.TestCase):
    def test_no_trade_wait_records_are_structured_and_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "sample.csv"
            csv_path.write_text((ROOT / "tests" / "test_data" / "ohlcv_sample_5m.csv").read_text(encoding="utf-8"), encoding="utf-8")
            metadata_path = Path(temp_dir) / "sample.metadata.json"
            metadata_path.write_text(json.dumps({"source": "fixture", "row_count": 5}), encoding="utf-8")
            record = MODULE.DatasetCacheRecord(
                instrument=MODULE.InstrumentConfig(
                    ticker="SAMPLE",
                    symbol="SAMPLE",
                    label="Sample",
                    market="US",
                    timezone="America/New_York",
                    demo_role="fixture",
                ),
                source="fixture",
                csv_path=csv_path,
                metadata_path=metadata_path,
                row_count=5,
            )
            result = MODULE.run_symbol_backtest(record)
            paper_outcome = MODULE.PaperDemoOutcome(
                executed_trades=(),
                blocked_signals=(),
                equity_points=((MODULE.datetime.now(MODULE.UTC).isoformat(), 10000.0),),
                ending_equity=MODULE.Decimal("10000"),
            )

            records = MODULE.build_no_trade_wait_records((result,), paper_outcome)

        self.assertTrue(records)
        self.assertTrue(all(item.action in {"wait", "no-trade"} for item in records))
        self.assertTrue(all(item.reason_code for item in records))
        self.assertTrue(all(item.source_refs for item in records))
        self.assertTrue(all(item.actual_source_refs == () for item in records))
        self.assertTrue(all(item.bundle_support_refs for item in records))

    def test_window_summary_captures_signals_and_no_trade_wait(self) -> None:
        signal = _build_signal("sig-window")
        result = _build_symbol_result(signal)
        paper_outcome = MODULE.PaperDemoOutcome(
            executed_trades=(_build_executed_trade(signal),),
            blocked_signals=(),
            equity_points=((MODULE.datetime.now(MODULE.UTC).isoformat(), 10000.0),),
            ending_equity=MODULE.Decimal("10020"),
        )
        no_trade_wait = (
            MODULE.NoTradeWaitRecord(
                symbol="SAMPLE",
                market="US",
                timeframe="1d",
                timestamp=MODULE.datetime.fromisoformat("2024-01-03T16:00:00+00:00"),
                action="wait",
                reason_code="context_not_trend",
                reason_detail="range",
                decision_site="signal_scan",
                pa_context="trading-range",
                regime_summary="range",
                source_refs=("wiki:knowledge/wiki/concepts/market-cycle-overview.md",),
                actual_source_refs=(),
                bundle_support_refs=("wiki:knowledge/wiki/concepts/market-cycle-overview.md",),
            ),
        )
        windows = (
            MODULE.WindowConfig(
                name="sample_split",
                label="Sample Split",
                start=MODULE.date.fromisoformat("2024-01-01"),
                end=MODULE.date.fromisoformat("2024-01-31"),
            ),
        )

        payload = MODULE.build_window_summary(
            windows=windows,
            symbol_results=(result,),
            paper_outcome=paper_outcome,
            no_trade_wait_records=no_trade_wait,
            bucket_type="split",
        )

        window = payload["windows"][0]
        self.assertEqual(window["signal_count"], 1)
        self.assertEqual(window["executed_trades"], 1)
        self.assertEqual(window["no_trade_wait"], 1)

    def test_trace_coverage_counts_source_family_presence_per_signal(self) -> None:
        signal = _build_signal("sig-family")
        coverage = MODULE.build_knowledge_trace_coverage(
            (_build_symbol_result(signal),),
            MODULE.PaperDemoOutcome(
                executed_trades=(_build_executed_trade(signal),),
                blocked_signals=(),
                equity_points=((MODULE.datetime.now(MODULE.UTC).isoformat(), 10000.0),),
                ending_equity=MODULE.Decimal("10020"),
            ),
        )

        self.assertEqual(coverage["overall"]["total_signals"], 1)
        self.assertEqual(coverage["overall"]["curated_signals"], 1)
        self.assertEqual(
            coverage["overall"]["actual_hit_source_family_presence"]["al_brooks_ppt"],
            1,
        )
        self.assertEqual(
            coverage["overall"]["bundle_support_family_presence"]["curated_rule"],
            1,
        )

    def test_checked_in_daily_artifacts_keep_summary_report_and_coverage_consistent(self) -> None:
        summary = _load_artifact_json("summary.json")
        coverage = _load_artifact_json("knowledge_trace_coverage.json")
        report_text = (ARTIFACT_ROOT / "report.md").read_text(encoding="utf-8")

        self.assertEqual(summary["run_id"], "m8c1_long_horizon_daily_validation")
        self.assertEqual(summary["knowledge_trace_coverage"], coverage["overall"])
        for key in (
            "actual_hit_source_family_presence",
            "actual_evidence_source_family_presence",
            "bundle_support_family_presence",
        ):
            self.assertIn(key, summary["knowledge_trace_coverage"])
            self.assertIn(key, coverage["overall"])

        self.assertIn("actual hit family 分布", report_text)
        self.assertIn("actual evidence family 分布", report_text)
        self.assertIn("bundle support family 分布", report_text)
        self.assertIn("actual refs：", report_text)
        self.assertIn("bundle support：", report_text)
        self.assertIn("### 样本充分性", report_text)
        self.assertNotRegex(report_text, r"(?<!actual )knowledge refs:")

    def test_checked_in_daily_summary_uses_repo_relative_paths_and_sample_adequacy(self) -> None:
        summary = _load_artifact_json("summary.json")
        report_text = (ARTIFACT_ROOT / "report.md").read_text(encoding="utf-8")

        self.assertFalse(os.path.isabs(summary["cache_dir"]))
        self.assertFalse(os.path.isabs(summary["report_dir"]))
        self.assertTrue(all(not os.path.isabs(item["cache_csv"]) for item in summary["per_symbol"]))
        self.assertEqual(summary["sample_adequacy"]["overall_verdict"], "insufficient_sample")
        self.assertEqual(
            {item["split_name"]: item["verdict"] for item in summary["sample_adequacy"]["by_split"]},
            {
                "in_sample": "adequate",
                "validation": "insufficient_sample",
                "out_of_sample": "insufficient_sample",
            },
        )
        self.assertIn("validation", report_text)
        self.assertIn("out_of_sample", report_text)
        self.assertIn("验证诚实但样本不足", report_text)

    def test_checked_in_daily_trade_and_trace_payloads_split_actual_and_bundle_support(self) -> None:
        summary = _load_artifact_json("summary.json")
        knowledge_trace = _load_artifact_json("knowledge_trace.json")
        trade_row = (summary["best_trades"] or summary["worst_trades"])[0]
        executed = knowledge_trace["executed_trades"][0]

        self.assertTrue(
            {
                "source_refs",
                "bundle_support_refs",
                "legacy_source_refs",
                "knowledge_trace_summary",
            }.issubset(trade_row)
        )
        self.assertTrue(set(trade_row["source_refs"]).isdisjoint(set(trade_row["bundle_support_refs"])))
        self.assertTrue(set(trade_row["source_refs"]).issubset(set(trade_row["legacy_source_refs"])))
        self.assertTrue(set(trade_row["bundle_support_refs"]).issubset(set(trade_row["legacy_source_refs"])))
        self.assertNotIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", trade_row["source_refs"])
        self.assertIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", trade_row["bundle_support_refs"])
        self.assertIn("wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md", trade_row["source_refs"])
        self.assertIn("wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md", trade_row["source_refs"])

        self.assertTrue(
            {
                "actual_source_refs",
                "bundle_support_refs",
                "legacy_source_refs",
                "knowledge_trace",
                "visible_trace",
                "debug_trace",
            }.issubset(executed)
        )
        self.assertTrue(set(executed["actual_source_refs"]).isdisjoint(set(executed["bundle_support_refs"])))
        self.assertNotIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", executed["actual_source_refs"])
        self.assertIn("wiki:knowledge/wiki/rules/m3-research-reference-pack.md", executed["bundle_support_refs"])
        self.assertIn(
            "wiki:knowledge/wiki/rules/breakout-follow-through-failed-breakout-minimal.md",
            executed["actual_source_refs"],
        )
        self.assertIn(
            "wiki:knowledge/wiki/rules/tight-channel-trend-resumption-minimal.md",
            executed["actual_source_refs"],
        )
        self.assertNotIn(b"\r\n", (ARTIFACT_ROOT / "trades.csv").read_bytes())

    def test_checked_in_daily_actual_trace_contains_more_than_one_promoted_rule_theme(self) -> None:
        knowledge_trace = _load_artifact_json("knowledge_trace.json")

        rule_hits = [
            hit
            for trade in knowledge_trace["executed_trades"]
            for hit in trade["visible_trace"]
            if hit["atom_type"] == "rule"
        ]
        self.assertTrue(rule_hits)
        self.assertTrue(
            {
                "trend_vs_range_filter",
                "breakout_follow_through_failed_breakout",
                "tight_channel_trend_resumption",
            }.issubset({hit["promotion_theme"] for hit in rule_hits})
        )
        promoted_hits = [
            hit
            for hit in rule_hits
            if hit["promotion_theme"] in {"breakout_follow_through_failed_breakout", "tight_channel_trend_resumption"}
        ]
        self.assertTrue(promoted_hits)
        self.assertTrue(
            all(
                "wiki:knowledge/wiki/sources/fangfangtu-price-action-transcript.md" in hit["evidence_refs"]
                and "wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md" in hit["evidence_refs"]
                for hit in promoted_hits
            )
        )

    def test_checked_in_daily_no_trade_wait_payload_uses_actual_refs_field(self) -> None:
        records = [
            json.loads(line)
            for line in (ARTIFACT_ROOT / "no_trade_wait.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]

        self.assertTrue(records)
        self.assertTrue(all(item["source_refs"] == item["actual_source_refs"] for item in records))
        self.assertTrue(all("legacy_source_refs" in item for item in records))
        self.assertTrue(any(not item["source_refs"] and item["bundle_support_refs"] for item in records))
        self.assertTrue(any(item["source_refs"] and item["bundle_support_refs"] for item in records))
        for item in records:
            self.assertTrue(set(item["source_refs"]).issubset(set(item["legacy_source_refs"])))
            self.assertTrue(set(item["bundle_support_refs"]).issubset(set(item["legacy_source_refs"])))


def _build_signal(signal_id: str) -> MODULE.Signal:
    trace = (
        KnowledgeAtomHit(
            atom_id="concept-1",
            atom_type="concept",
            source_ref="wiki:knowledge/wiki/concepts/market-cycle-overview.md",
            raw_locator={"locator_kind": "chunk_set", "member_count": 2},
            match_reason="curated_context",
            applicability_state="matched",
        ),
        KnowledgeAtomHit(
            atom_id="statement-1",
            atom_type="statement",
            source_ref="wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md",
            raw_locator={"locator_kind": "page_block", "page_no": 1, "block_index": 0, "fragment_index": 0},
            match_reason="supporting_statement",
            applicability_state="supporting",
        ),
        KnowledgeAtomHit(
            atom_id="statement-2",
            atom_type="statement",
            source_ref="wiki:knowledge/wiki/sources/al-brooks-price-action-ppt-1-36-units.md",
            raw_locator={"locator_kind": "page_block", "page_no": 1, "block_index": 0, "fragment_index": 1},
            match_reason="supporting_statement",
            applicability_state="supporting",
        ),
    )
    return MODULE.Signal(
        signal_id=signal_id,
        symbol="SAMPLE",
        market="US",
        timeframe="1d",
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
        explanation="unit explanation",
        risk_notes=("research-only placeholder",),
        knowledge_trace=trace,
        knowledge_debug_trace=(
            KnowledgeAtomHit(
                atom_id="rule-support-1",
                atom_type="rule",
                source_ref="wiki:knowledge/wiki/rules/m3-research-reference-pack.md",
                raw_locator={"locator_kind": "bundle_support_summary", "label": "bundle_support[1 sources/12 chunks]"},
                match_reason="bundle_rule_support",
                applicability_state="supporting",
                reference_tier="bundle_support",
            ),
        ),
    )


def _build_executed_trade(signal: MODULE.Signal) -> MODULE.ExecutedTradeRecord:
    instrument = MODULE.InstrumentConfig(
        ticker="SAMPLE",
        symbol="SAMPLE",
        label="Sample",
        market="US",
        timezone="America/New_York",
        demo_role="fixture",
    )
    trade = MODULE.TradeRecord(
        signal_id=signal.signal_id,
        symbol=signal.symbol,
        market=signal.market,
        timeframe=signal.timeframe,
        direction=signal.direction,
        setup_type=signal.setup_type,
        signal_bar_index=1,
        signal_bar_timestamp=MODULE.datetime.fromisoformat("2024-01-02T16:00:00+00:00"),
        entry_bar_index=2,
        entry_timestamp=MODULE.datetime.fromisoformat("2024-01-03T16:00:00+00:00"),
        entry_price=MODULE.Decimal("100"),
        stop_price=MODULE.Decimal("99"),
        target_price=MODULE.Decimal("102"),
        exit_bar_index=3,
        exit_timestamp=MODULE.datetime.fromisoformat("2024-01-05T16:00:00+00:00"),
        exit_price=MODULE.Decimal("102"),
        exit_reason="target_hit",
        risk_per_share=MODULE.Decimal("1"),
        pnl_per_share=MODULE.Decimal("2"),
        pnl_r=MODULE.Decimal("2"),
        bars_held=2,
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


def _build_symbol_result(signal: MODULE.Signal) -> MODULE.SymbolBacktestResult:
    report = MODULE.BacktestReport(
        trades=(_build_executed_trade(signal).trade,),
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
        summary="fixture",
        warnings=(),
        assumptions=(),
    )
    instrument = MODULE.InstrumentConfig(
        ticker="SAMPLE",
        symbol="SAMPLE",
        label="Sample",
        market="US",
        timezone="America/New_York",
        demo_role="fixture",
    )
    return MODULE.SymbolBacktestResult(
        instrument=instrument,
        source="fixture",
        csv_path=ROOT / "tests" / "test_data" / "ohlcv_sample_5m.csv",
        metadata_path=ROOT / "tests" / "test_data" / "README.md",
        bars=(),
        bars_count=5,
        signals=(signal,),
        backtest_report=report,
    )


def _load_artifact_json(name: str) -> dict[str, object]:
    return json.loads((ARTIFACT_ROOT / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
