from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts import m12_12_daily_observation_loop_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M1212DailyObservationLoopTests(unittest.TestCase):
    def test_config_locks_first_batch_and_simulated_boundary(self) -> None:
        config = MODULE.load_config()
        self.assertEqual(config.first_batch_size, 147)
        self.assertEqual(config.daily_start.isoformat(), "2010-06-29")
        self.assertEqual(config.intraday_current_start.isoformat(), "2026-04-27")
        self.assertEqual(config.daily_observation_strategies, ("M10-PA-001", "M10-PA-002", "M10-PA-012", "M12-FTD-001"))
        self.assertTrue(config.boundary.paper_simulated_only)
        self.assertFalse(config.boundary.trading_connection)
        self.assertFalse(config.boundary.real_money_actions)
        self.assertFalse(config.boundary.live_execution)
        self.assertFalse(config.boundary.paper_trading_approval)

    def test_active_universe_selection_matches_m12_5_seed_order(self) -> None:
        config = MODULE.load_config()
        symbols = MODULE.select_first_batch_symbols(config)
        self.assertEqual(len(symbols), 147)
        self.assertEqual(symbols[:4], ["SPY", "QQQ", "IWM", "DIA"])
        self.assertEqual(symbols[-1], "TSM")

    def test_formal_daily_spec_is_not_benchmark_placeholder_source(self) -> None:
        config = MODULE.load_config()
        spec = MODULE.formal_strategy_spec(config)
        self.assertEqual(spec["strategy_id"], "M12-FTD-001")
        self.assertIn("方方土", spec["title"])
        self.assertIn("M12-BENCH-001", spec["not_source_of_truth"])
        self.assertNotIn("wiki:knowledge/wiki/setups/signal-bar-entry-placeholder.md", spec["source_refs"])
        self.assertFalse(spec["paper_gate_evidence_now"])

    def test_cached_bars_reuses_unchanged_file_and_invalidates_after_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "us_SPY_1d_2026-07-10_2026-07-13_longbridge.csv"
            first_row = {
                "symbol": "SPY",
                "market": "US",
                "timeframe": "1d",
                "timestamp": "2026-07-10T16:00:00",
                "timezone": "America/New_York",
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100.5",
                "volume": "1000",
            }
            second_row = {**first_row, "timestamp": "2026-07-13T16:00:00", "close": "101.5"}
            MODULE.write_cache_csv(path, [first_row])
            MODULE._cached_load_bars.cache_clear()
            with patch("scripts.m12_12_daily_observation_loop_lib.load_scanner_bars", wraps=MODULE.load_scanner_bars) as load:
                self.assertEqual(len(MODULE.cached_load_bars(path)), 1)
                self.assertEqual(len(MODULE.cached_load_bars(path)), 1)
                self.assertEqual(load.call_count, 1)
                MODULE.write_cache_csv(path, [first_row, second_row])
                self.assertEqual(len(MODULE.cached_load_bars(path)), 2)
                self.assertEqual(load.call_count, 2)
            MODULE._cached_load_bars.cache_clear()

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

        self.assertEqual(summary["first50_cache"]["symbol_count"], 147)
        self.assertFalse(summary["first50_cache"]["fake_data_created"])
        self.assertIn("今日机会数", dashboard["top_metrics"])
        self.assertIn("今日机会估算盈亏（未成交）", dashboard["top_metrics"])
        self.assertNotIn("早期日线历史模拟盈利", dashboard["top_metrics"])
        self.assertNotIn("早期日线历史收益率", dashboard["top_metrics"])
        self.assertIn("today_trade_view", dashboard)
        self.assertIn("trade_view_summary", dashboard)
        self.assertEqual(visual["needs_user_review_count"], 10)
        self.assertFalse(visual["paper_gate_evidence_now"])
        self.assertFalse(summary["paper_gate_recheck"]["approval_for_paper_trading_trial"])

    def test_fetch_plan_opens_provider_circuit_after_repeated_longbridge_failures(self) -> None:
        config = MODULE.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            test_config = replace(config, output_dir=Path(tmp), local_data_roots=(Path(tmp) / "empty_local_data",))
            with patch(
                "scripts.m12_12_daily_observation_loop_lib.fetch_target_rows",
                side_effect=RuntimeError("longbridge kline history failed for SPY.US: timeout after 6s"),
            ):
                with patch(
                    "scripts.m12_12_daily_observation_loop_lib.fetch_public_fallback_rows",
                    side_effect=RuntimeError("public fallback unavailable"),
                ):
                    rows = MODULE.run_fetch_plan(
                        test_config,
                        ["SPY", "QQQ", "IWM", "DIA"],
                        generated_at="2026-05-05T14:00:00Z",
                        execute_fetch=True,
                        max_native_fetches=20,
                        force_refresh_current_intraday=True,
                    )

        circuit_rows = [row for row in rows if "fetch_provider_circuit_open_after_3_failures" in row.get("skipped_reason", "")]
        self.assertGreaterEqual(len(circuit_rows), 1)
        self.assertEqual(rows[0]["status"], "deferred")
        self.assertIn("longbridge kline history failed", rows[0]["skipped_reason"])

    def test_intraday_fast_refresh_skips_stale_daily_cache_and_fetches_5m_first(self) -> None:
        config = MODULE.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_dir = root / "longbridge_history"
            history_dir.mkdir(parents=True)
            existing_daily = history_dir / "us_SPY_1d_2010-06-29_2026-06-02_longbridge.csv"
            MODULE.write_cache_csv(
                existing_daily,
                [
                    {
                        "symbol": "SPY",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2010-06-29T16:00:00",
                        "timezone": "America/New_York",
                        "open": "100.00",
                        "high": "101.00",
                        "low": "99.00",
                        "close": "100.50",
                        "volume": "1000",
                    },
                    {
                        "symbol": "SPY",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2026-06-02T16:00:00",
                        "timezone": "America/New_York",
                        "open": "520.00",
                        "high": "525.00",
                        "low": "519.00",
                        "close": "524.00",
                        "volume": "2000",
                    },
                ],
            )
            test_config = replace(
                config,
                local_data_roots=(root,),
                daily_end=date(2026, 6, 3),
                intraday_current_start=date(2026, 6, 3),
                intraday_end=date(2026, 6, 3),
            )

            def fake_fetch(_config, target):
                self.assertEqual(target.timeframe, "5m")
                return [
                    {
                        "symbol": "SPY",
                        "market": "US",
                        "timeframe": "5m",
                        "timestamp": "2026-06-03T09:30:00",
                        "timezone": "America/New_York",
                        "open": "525.00",
                        "high": "526.00",
                        "low": "524.00",
                        "close": "525.50",
                        "volume": "1000",
                    }
                ]

            with patch("scripts.m12_12_daily_observation_loop_lib.fetch_target_rows", side_effect=fake_fetch):
                rows = MODULE.run_fetch_plan(
                    test_config,
                    ["SPY"],
                    generated_at="2026-06-03T13:31:00Z",
                    execute_fetch=True,
                    max_native_fetches=1,
                    force_refresh_current_intraday=True,
                )
            inventory, cache = MODULE.build_cache_inventory(test_config, ["SPY"], "2026-06-03T13:31:00Z", rows)

        self.assertEqual(rows[0]["timeframe"], "5m")
        self.assertEqual(rows[0]["status"], "fetched")
        self.assertEqual(rows[1]["timeframe"], "1d")
        self.assertEqual(rows[1]["status"], "deferred")
        self.assertEqual(rows[1]["skipped_reason"], "daily_cache_deferred_during_intraday_fast_refresh")
        daily_inventory = [row for row in inventory if row["timeframe"] == "1d"][0]
        self.assertEqual(daily_inventory["coverage_status"], "prior_daily_cache_accepted_for_intraday_fast_refresh")
        self.assertTrue(daily_inventory["ready_for_daily_test"])
        self.assertEqual(cache["daily_ready_symbols"], 1)
        self.assertEqual(cache["current_5m_ready_symbols"], 1)

    def test_intraday_fast_refresh_fetches_missing_daily_only_through_previous_session(self) -> None:
        config = MODULE.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_config = replace(
                config,
                local_data_roots=(root,),
                daily_end=date(2026, 6, 3),
                intraday_current_start=date(2026, 6, 3),
                intraday_end=date(2026, 6, 3),
            )

            def fake_fetch(_config, target):
                if target.timeframe == "5m":
                    return [
                        {
                            "symbol": "SPY",
                            "market": "US",
                            "timeframe": "5m",
                            "timestamp": "2026-06-03T09:30:00",
                            "timezone": "America/New_York",
                            "open": "525.00",
                            "high": "526.00",
                            "low": "524.00",
                            "close": "525.50",
                            "volume": "1000",
                        }
                    ]
                self.assertEqual(target.timeframe, "1d")
                self.assertEqual(target.target_end, date(2026, 6, 2))
                return [
                    {
                        "symbol": "SPY",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2010-06-29T16:00:00",
                        "timezone": "America/New_York",
                        "open": "100.00",
                        "high": "101.00",
                        "low": "99.00",
                        "close": "100.50",
                        "volume": "1000",
                    },
                    {
                        "symbol": "SPY",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2026-06-02T16:00:00",
                        "timezone": "America/New_York",
                        "open": "520.00",
                        "high": "525.00",
                        "low": "519.00",
                        "close": "524.00",
                        "volume": "2000",
                    },
                ]

            with patch("scripts.m12_12_daily_observation_loop_lib.fetch_target_rows", side_effect=fake_fetch):
                rows = MODULE.run_fetch_plan(
                    test_config,
                    ["SPY"],
                    generated_at="2026-06-03T13:31:00Z",
                    execute_fetch=True,
                    max_native_fetches=2,
                    force_refresh_current_intraday=True,
                )
            inventory, cache = MODULE.build_cache_inventory(
                test_config,
                ["SPY"],
                "2026-06-03T13:31:00Z",
                rows,
                accept_prior_daily_for_intraday_fast_refresh=True,
            )

        self.assertEqual(rows[0]["timeframe"], "5m")
        self.assertEqual(rows[0]["status"], "fetched")
        self.assertEqual(rows[1]["timeframe"], "1d")
        self.assertEqual(rows[1]["target_end"], "2026-06-02")
        self.assertEqual(rows[1]["status"], "fetched")
        daily_inventory = [row for row in inventory if row["timeframe"] == "1d"][0]
        self.assertEqual(daily_inventory["coverage_status"], "prior_daily_cache_accepted_for_intraday_fast_refresh")
        self.assertTrue(daily_inventory["ready_for_daily_test"])
        self.assertEqual(cache["daily_ready_symbols"], 1)
        self.assertEqual(cache["current_5m_ready_symbols"], 1)

    def test_daily_refresh_extends_existing_cache_instead_of_refetching_full_history(self) -> None:
        config = MODULE.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_dir = root / "longbridge_history"
            history_dir.mkdir(parents=True)
            existing = history_dir / "us_SPY_1d_2010-06-29_2026-07-22_longbridge.csv"
            MODULE.write_cache_csv(
                existing,
                [
                    {
                        "symbol": "SPY",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2026-07-22T16:00:00",
                        "timezone": "America/New_York",
                        "open": "100",
                        "high": "101",
                        "low": "99",
                        "close": "100.5",
                        "volume": "1000",
                    }
                ],
            )
            target = MODULE.FetchTarget(
                symbol="SPY",
                timeframe="1d",
                target_start=date(2010, 6, 29),
                target_end=date(2026, 7, 23),
                fetch_mode="full_daily",
                destination=history_dir / "us_SPY_1d_2010-06-29_2026-07-23_longbridge.csv",
            )

            def fake_fetch(_config, incremental_target):
                self.assertEqual(incremental_target.target_start, date(2026, 7, 23))
                self.assertEqual(incremental_target.target_end, date(2026, 7, 23))
                return [
                    {
                        "symbol": "SPY",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2026-07-23T16:00:00",
                        "timezone": "America/New_York",
                        "open": "101",
                        "high": "102",
                        "low": "100",
                        "close": "101.5",
                        "volume": "1100",
                    }
                ]

            with patch("scripts.m12_12_daily_observation_loop_lib.fetch_target_rows", side_effect=fake_fetch):
                rows = MODULE.fetch_target_rows_with_existing_cache(
                    replace(config, local_data_roots=(root,)),
                    target,
                    existing,
                )

        self.assertEqual([row["timestamp"] for row in rows], ["2026-07-22T16:00:00", "2026-07-23T16:00:00"])

    def test_intraday_prior_daily_accepts_later_ipo_start(self) -> None:
        config = MODULE.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history_dir = root / "longbridge_history"
            history_dir.mkdir(parents=True)
            existing_daily = history_dir / "us_ABNB_1d_2010-06-29_2026-06-02_longbridge.csv"
            MODULE.write_cache_csv(
                existing_daily,
                [
                    {
                        "symbol": "ABNB",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2020-12-10T16:00:00",
                        "timezone": "America/New_York",
                        "open": "146.00",
                        "high": "165.00",
                        "low": "141.00",
                        "close": "144.71",
                        "volume": "1000",
                    },
                    {
                        "symbol": "ABNB",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2026-06-02T16:00:00",
                        "timezone": "America/New_York",
                        "open": "130.00",
                        "high": "132.00",
                        "low": "128.00",
                        "close": "131.00",
                        "volume": "2000",
                    },
                ],
            )
            test_config = replace(config, local_data_roots=(root,), daily_end=date(2026, 6, 3))
            inventory, cache = MODULE.build_cache_inventory(
                test_config,
                ["ABNB"],
                "2026-06-03T13:31:00Z",
                [],
                accept_prior_daily_for_intraday_fast_refresh=True,
            )

        daily_inventory = [row for row in inventory if row["timeframe"] == "1d"][0]
        self.assertEqual(daily_inventory["coverage_status"], "prior_daily_cache_accepted_for_intraday_fast_refresh")
        self.assertTrue(daily_inventory["ready_for_daily_test"])
        self.assertEqual(cache["daily_ready_symbols"], 1)

    def test_public_daily_fallback_appends_current_day_to_existing_cache(self) -> None:
        config = MODULE.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "us_INTC_1d_2010-06-29_2026-05-28_longbridge.csv"
            MODULE.write_cache_csv(
                existing,
                [
                    {
                        "symbol": "INTC",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2010-06-29T16:00:00",
                        "timezone": "America/New_York",
                        "open": "10.00",
                        "high": "11.00",
                        "low": "9.00",
                        "close": "10.50",
                        "volume": "1000",
                    },
                    {
                        "symbol": "INTC",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2026-05-28T16:00:00",
                        "timezone": "America/New_York",
                        "open": "120.00",
                        "high": "121.00",
                        "low": "119.00",
                        "close": "120.89",
                        "volume": "2000",
                    },
                ],
            )
            target = MODULE.FetchTarget(
                symbol="INTC",
                timeframe="1d",
                target_start=date(2010, 6, 29),
                target_end=date(2026, 5, 29),
                fetch_mode="full_daily",
                destination=Path(tmp) / "out.csv",
            )
            with patch(
                "scripts.m12_12_daily_observation_loop_lib.fetch_yahoo_chart_rows",
                return_value=(
                    {
                        "symbol": "INTC",
                        "market": "US",
                        "timeframe": "1d",
                        "timestamp": "2026-05-29T16:00:00",
                        "timezone": "America/New_York",
                        "open": "120.00",
                        "high": "126.64",
                        "low": "117.66",
                        "close": "118.1850",
                        "volume": "53760261",
                    },
                ),
            ):
                rows = MODULE.fetch_public_fallback_rows(config, target, existing)

        self.assertEqual(rows[-1]["timestamp"], "2026-05-29T16:00:00")
        self.assertEqual(rows[-1]["close"], "118.1850")
        self.assertEqual(len(rows), 3)

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
        self.assertIn(cache["symbol_count"], {50, MODULE.load_config().first_batch_size})
        self.assertGreaterEqual(cache["daily_ready_symbols"], 4)
        self.assertGreaterEqual(cache["current_5m_ready_symbols"], 4)
        gate = json.loads((OUTPUT_DIR / "m11_6_paper_gate_recheck.json").read_text(encoding="utf-8"))
        self.assertIn("模拟买卖试运行", gate["plain_language"]["paper_gate"])
        self.assertFalse(gate["approval_for_paper_trading_trial"])
        self.assertNotIn("M12-FTD-001", gate["first_batch_candidate_strategies"])
        self.assertIn("M12-FTD-001", gate["non_gate_daily_factor_strategies"])
        self.assertIn("你尚未明确批准进入模拟交易试运行。", gate["blockers"])
        html = (OUTPUT_DIR / "m12_12_readonly_daily_dashboard.html").read_text(encoding="utf-8")
        for expected_text in ("今日机会估算视图（未成交）", "今日机会明细", "胜率", "最大回撤", "策略状态"):
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
