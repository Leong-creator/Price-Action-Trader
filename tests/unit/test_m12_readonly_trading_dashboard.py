from __future__ import annotations

import json
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m12_readonly_trading_dashboard_lib as MODULE


OUTPUT_DIR = MODULE.OUTPUT_DIR


class M12ReadonlyTradingDashboardTests(unittest.TestCase):
    def test_dashboard_summary_uses_current_readonly_artifacts(self) -> None:
        config = MODULE.load_dashboard_config()
        with tempfile.TemporaryDirectory() as tmp:
            dashboard = MODULE.run_m12_readonly_trading_dashboard(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )

        summary = dashboard["summary"]
        self.assertEqual(dashboard["stage"], "M12.11.readonly_trading_dashboard")
        self.assertFalse(dashboard["paper_trading_approval"])
        self.assertFalse(dashboard["trading_connection"])
        self.assertFalse(dashboard["real_money_actions"])
        self.assertFalse(dashboard["live_execution"])
        self.assertEqual(summary["readonly_symbol_count"], 4)
        self.assertEqual(summary["readonly_feed_rows"], 16)
        self.assertEqual(summary["readonly_observation_events"], 32)
        self.assertEqual(summary["readonly_skip_no_trade"], 32)
        self.assertEqual(summary["scanner_candidates"], 12)
        self.assertEqual(summary["scanner_deferred_symbols"], 143)
        self.assertEqual(summary["cache_target_complete_symbols"], 0)
        self.assertEqual(summary["paper_gate_decision"], "not_approved")
        self.assertEqual(summary["pa005_decision"], "reject_for_now_after_geometry_review")
        self.assertTrue(summary["pa005_geometry_event_id_unique"])
        self.assertEqual(summary["simulated_portfolio_proxy_final_equity"], "105728.18")
        self.assertNotEqual(summary["simulated_portfolio_proxy_not_executable_reason"], "unavailable")
        self.assertEqual(summary["simulated_equity_curve_count"], 10)
        self.assertEqual(config.title, "M12.11 只读交易看板")
        for curve in dashboard["simulated_equity_curves"]:
            self.assertTrue((MODULE.ROOT / curve["simulated_equity_curve_ref"]).exists())
            self.assertEqual(curve["curve_semantics"], "simulated_historical_equity_curve")

    def test_dashboard_input_refs_and_image_paths_are_locked(self) -> None:
        config = MODULE.load_dashboard_config()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            dashboard = MODULE.run_m12_readonly_trading_dashboard(
                replace(config, output_dir=output_dir),
                generated_at="2026-04-28T00:00:00Z",
            )

            expected_refs = {
                "feed_manifest",
                "feed_ledger",
                "observation_events",
                "scanner_candidates",
                "strategy_dashboard",
                "cache_summary",
                "definition_summary",
                "gate_summary",
                "scorecard_summary",
                "decision_matrix",
            }
            self.assertEqual(set(dashboard["input_refs"]), expected_refs)
            for ref in dashboard["input_refs"].values():
                self.assertFalse(Path(ref).is_absolute())
                self.assertTrue((MODULE.ROOT / ref).exists())

            html = (output_dir / "m12_11_readonly_trading_dashboard.html").read_text(encoding="utf-8")
            image_refs = re.findall(r'<img src="([^"]+)"', html)
            self.assertEqual(len(image_refs), dashboard["summary"]["simulated_equity_curve_count"])
            for ref in image_refs:
                self.assertFalse(Path(ref).is_absolute())
                self.assertFalse(ref.startswith(("http://", "https://", "file://")))
                resolved = (output_dir / ref).resolve()
                resolved.relative_to(MODULE.ROOT)
                self.assertTrue(resolved.exists())

    def test_scanner_candidates_use_hypothetical_and_readonly_fields(self) -> None:
        config = MODULE.load_dashboard_config()
        with tempfile.TemporaryDirectory() as tmp:
            dashboard = MODULE.run_m12_readonly_trading_dashboard(
                replace(config, output_dir=Path(tmp)),
                generated_at="2026-04-28T00:00:00Z",
            )

        self.assertEqual(len(dashboard["scanner_candidates"]), 12)
        sample = dashboard["scanner_candidates"][0]
        for field in (
            "hypothetical_entry_price",
            "hypothetical_stop_price",
            "hypothetical_target_price",
            "hypothetical_risk_per_share",
            "readonly_last_price",
            "hypothetical_pnl_per_share",
            "hypothetical_unrealized_r",
        ):
            self.assertIn(field, sample)
        for forbidden in ("entry_price", "stop_price", "target_price", "pnl"):
            self.assertNotIn(forbidden, sample)

    def test_strategy_status_overlays_m12_10_definition_decisions(self) -> None:
        config = MODULE.load_dashboard_config()
        with tempfile.TemporaryDirectory() as tmp:
            dashboard = MODULE.run_m12_readonly_trading_dashboard(replace(config, output_dir=Path(tmp)))
        rows = {row["strategy_id"]: row for row in dashboard["strategy_statuses"]}

        self.assertEqual(rows["M10-PA-005"]["dashboard_status"], "reject_for_now_after_geometry_review")
        self.assertEqual(rows["M10-PA-004"]["dashboard_status"], "visual_only_not_backtestable_without_manual_labels")
        self.assertEqual(rows["M10-PA-007"]["dashboard_status"], "visual_only_not_backtestable_without_manual_labels")
        self.assertEqual(rows["M10-PA-008"]["dashboard_status"], "manual_visual_review_required")
        self.assertEqual(rows["M10-PA-009"]["dashboard_status"], "manual_visual_review_required")
        self.assertEqual(rows["M10-PA-001"]["scanner_candidates"], "6")
        self.assertEqual(rows["M10-PA-012"]["scanner_candidates"], "6")
        self.assertEqual(rows["M10-PA-002"]["scanner_candidates"], "0")
        self.assertEqual(rows["M10-PA-006"]["display_title"], "Trading Range BLSHS Limit Framework")
        self.assertEqual(rows["M10-PA-015"]["display_title"], "Protective Stops and Risk Sizing")

    def test_visible_dashboard_text_is_client_facing_chinese(self) -> None:
        config = MODULE.load_dashboard_config()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            MODULE.run_m12_readonly_trading_dashboard(
                replace(config, output_dir=output_dir),
                generated_at="2026-04-28T00:00:00Z",
            )

            html = (output_dir / "m12_11_readonly_trading_dashboard.html").read_text(encoding="utf-8")
            visible_html = html.split("<script", maxsplit=1)[0]
            snapshot = (output_dir / "m12_11_dashboard_snapshot.md").read_text(encoding="utf-8")

        for expected in (
            "M12.11 只读交易看板",
            "今日候选机会",
            "策略状态",
            "模拟资金曲线",
            "只读行情参考",
            "假设入场价",
            "模拟收益",
            "最大回撤",
            "不接交易账户",
        ):
            self.assertIn(expected, visible_html)
        for old_label in (
            "Read-only Trading Dashboard",
            "Scanner Candidates",
            "Strategy Status",
            "Simulated Equity Curves",
            "Hyp Entry",
            "Sim Net",
        ):
            self.assertNotIn(old_label, visible_html)
        self.assertIn("# M12.11 只读交易看板快照", snapshot)
        self.assertIn("今日候选机会", snapshot)

    def test_observation_events_do_not_convert_skips_into_triggers(self) -> None:
        config = MODULE.load_dashboard_config()
        with tempfile.TemporaryDirectory() as tmp:
            dashboard = MODULE.run_m12_readonly_trading_dashboard(replace(config, output_dir=Path(tmp)))

        self.assertEqual(len(dashboard["observation_events"]), 32)
        self.assertEqual({row["event_kind"] for row in dashboard["observation_events"]}, {"skip_no_trade"})
        for row in dashboard["observation_events"]:
            self.assertEqual(row["hypothetical_entry_price"], "unavailable")
            self.assertEqual(row["hypothetical_stop_price"], "unavailable")
            self.assertEqual(row["hypothetical_target_price"], "unavailable")

    def test_generated_outputs_keep_dashboard_boundaries(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_readonly_trading_dashboard.py before full validation")
        expected = {
            "m12_11_dashboard_data.json",
            "m12_11_readonly_trading_dashboard.html",
            "m12_11_dashboard_snapshot.md",
            "m12_11_handoff.md",
        }
        self.assertTrue(expected <= {path.name for path in OUTPUT_DIR.glob("m12_11_*")})

        dashboard = json.loads((OUTPUT_DIR / "m12_11_dashboard_data.json").read_text(encoding="utf-8"))
        self.assertEqual(dashboard["summary"]["paper_gate_decision"], "not_approved")
        self.assertFalse(dashboard["paper_trading_approval"])
        self.assertFalse(dashboard["trading_connection"])
        self.assertFalse(dashboard["real_money_actions"])
        self.assertFalse(dashboard["live_execution"])

        combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in OUTPUT_DIR.glob("m12_11_*") if path.is_file())
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "order_id", "fill_price", "account_id", "broker_connection=true", "paper approval"):
            self.assertNotIn(forbidden.lower(), lowered)
        for forbidden in ("order", "fill", "account", "broker", "position", "cash"):
            self.assertIsNone(re.search(rf"\b{re.escape(forbidden)}\b", lowered), forbidden)
        self.assertIn("hypothetical_entry_price", combined)
        self.assertIn("simulated_net_profit", combined)
        self.assertIn("readonly_last_price", combined)

    def test_config_rejects_dashboard_boundary_drift(self) -> None:
        config = MODULE.load_dashboard_config()
        with self.assertRaises(ValueError):
            MODULE.validate_dashboard_config(replace(config, trading_connection=True))
        with self.assertRaises(ValueError):
            MODULE.validate_dashboard_config(replace(config, real_money_actions=True))
        with self.assertRaises(ValueError):
            MODULE.validate_dashboard_config(replace(config, live_execution=True))
        with self.assertRaises(ValueError):
            MODULE.validate_dashboard_config(replace(config, paper_trading_approval=True))


if __name__ == "__main__":
    unittest.main()
