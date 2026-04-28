from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m12_12_daily_observation_loop_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1212DailyObservationLoopTests(unittest.TestCase):
    def test_config_locks_first_batch_and_simulated_boundary(self) -> None:
        config = MODULE.load_config()
        self.assertEqual(config.first_batch_size, 50)
        self.assertEqual(config.daily_start.isoformat(), "2010-06-29")
        self.assertEqual(config.intraday_current_start.isoformat(), "2026-04-27")
        self.assertEqual(config.daily_observation_strategies, ("M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001"))
        self.assertTrue(config.boundary.paper_simulated_only)
        self.assertFalse(config.boundary.trading_connection)
        self.assertFalse(config.boundary.real_money_actions)
        self.assertFalse(config.boundary.live_execution)
        self.assertFalse(config.boundary.paper_trading_approval)

    def test_first50_selection_matches_m12_5_seed_order(self) -> None:
        config = MODULE.load_config()
        symbols = MODULE.select_first_batch_symbols(config)
        self.assertEqual(len(symbols), 50)
        self.assertEqual(symbols[:4], ["SPY", "QQQ", "IWM", "DIA"])
        self.assertEqual(symbols[-1], "PANW")

    def test_formal_daily_spec_is_not_benchmark_placeholder_source(self) -> None:
        config = MODULE.load_config()
        spec = MODULE.formal_strategy_spec(config)
        self.assertEqual(spec["strategy_id"], "M12-FTD-001")
        self.assertIn("方方土", spec["title"])
        self.assertIn("M12-BENCH-001", spec["not_source_of_truth"])
        self.assertNotIn("wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md", spec["source_refs"])
        self.assertFalse(spec["paper_gate_evidence_now"])

    def test_temp_run_without_fetch_writes_honest_deferred_outputs(self) -> None:
        config = MODULE.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            summary = MODULE.run_m12_12_daily_observation_loop(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
                execute_fetch=False,
            )
            dashboard = json.loads((Path(tmp) / "m12_12_dashboard_data.json").read_text(encoding="utf-8"))
            visual = json.loads((Path(tmp) / "m12_12_visual_confirmation_packet.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["first50_cache"]["symbol_count"], 50)
        self.assertFalse(summary["first50_cache"]["fake_data_created"])
        self.assertIn("今日机会数", dashboard["top_metrics"])
        self.assertIn("今日机会估算盈亏（未成交）", dashboard["top_metrics"])
        self.assertIn("早期日线历史模拟盈利", dashboard["top_metrics"])
        self.assertIn("today_trade_view", dashboard)
        self.assertIn("trade_view_summary", dashboard)
        self.assertEqual(visual["needs_user_review_count"], 10)
        self.assertFalse(visual["paper_gate_evidence_now"])
        self.assertFalse(summary["paper_gate_recheck"]["approval_for_paper_trading_trial"])

    def test_checked_in_artifacts_are_client_facing_and_no_real_trading_boundary(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_12_daily_observation_loop.py before full validation")
        expected = {
            "m12_12_loop_summary.json",
            "m12_12_first50_cache_summary.json",
            "m12_12_daily_report.md",
            "m12_12_readonly_daily_dashboard.html",
            "m12_12_dashboard_trade_view.csv",
            "m12_12_formal_daily_strategy_source_reextract.md",
            "m12_13_all_strategy_status_matrix.json",
            "m11_6_paper_gate_recheck.json",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("*")})
        summary = json.loads((OUTPUT_DIR / "m12_12_loop_summary.json").read_text(encoding="utf-8"))
        cache = summary["first50_cache"]
        self.assertEqual(cache["symbol_count"], 50)
        self.assertGreaterEqual(cache["daily_ready_symbols"], 4)
        self.assertGreaterEqual(cache["current_5m_ready_symbols"], 4)
        gate = json.loads((OUTPUT_DIR / "m11_6_paper_gate_recheck.json").read_text(encoding="utf-8"))
        self.assertIn("模拟买卖试运行", gate["plain_language"]["paper_gate"])
        self.assertFalse(gate["approval_for_paper_trading_trial"])
        self.assertNotIn("M12-FTD-001", gate["first_batch_candidate_strategies"])
        self.assertIn("M12-FTD-001", gate["non_gate_daily_factor_strategies"])
        self.assertIn("你尚未明确批准进入模拟交易试运行。", gate["blockers"])
        html = (OUTPUT_DIR / "m12_12_readonly_daily_dashboard.html").read_text(encoding="utf-8")
        for expected_text in ("今日机会估算视图（未成交）", "今日机会明细", "早期日线历史模拟盈利", "胜率", "最大回撤", "策略状态"):
            self.assertIn(expected_text, html)
        self.assertIn("候选是一条“策略 x 标的 x 周期”的可观察机会", html)
        self.assertIn("不是实际成交，不是模拟买卖试运行", html)
        self.assertIn("长历史5分钟完整度", html)
        self.assertIn("日线策略定位", html)
        self.assertIn("早期日线资金曲线", html)
        report = (OUTPUT_DIR / "m12_12_daily_report.md").read_text(encoding="utf-8")
        self.assertIn("候选不是已经成交的交易", report)
        self.assertIn("今日机会估算视图（未成交）", report)
        self.assertIn("不能说“两年日内历史已完整”", report)
        self.assertIn("不作为模拟交易准入候选", report)
        reextract = (OUTPUT_DIR / "m12_12_formal_daily_strategy_source_reextract.md").read_text(encoding="utf-8")
        self.assertIn("当前来源是方方土", reextract)
        self.assertIn("不能因为某个参数收益好", reextract)
        self.assertTrue((OUTPUT_DIR / "m12_12_handoff.md").exists())
        lowered = html.lower()
        for forbidden in ("live-ready", "real_orders=true", "broker_connection=true", "needs_read_only_bar_close_review", "更像交易记录"):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
