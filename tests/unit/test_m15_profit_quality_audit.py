from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_profit_quality_audit_lib import ProfitQualityAuditConfig, run_profit_quality_audit


class M15ProfitQualityAuditTest(unittest.TestCase):
    def test_splits_today_profit_into_new_old_and_unrealized_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._write_fixture(root, quote_source="longbridge_quote_readonly")

            payload = run_profit_quality_audit(config, generated_at="2026-06-01T18:00:00Z")

            self.assertEqual(payload["audit_status"], "simulated_mark_to_market_only")
            self.assertEqual(payload["category_summary"]["total_today_pnl"], "850.00")
            buckets = {row["bucket"]: row for row in payload["category_summary"]["buckets"]}
            self.assertEqual(buckets["today_opened_and_closed"]["pnl"], "100.00")
            self.assertEqual(buckets["prior_position_closed_today"]["pnl"], "500.00")
            self.assertEqual(buckets["today_open_position_unrealized"]["pnl"], "50.00")
            self.assertEqual(buckets["prior_open_position_unrealized"]["pnl"], "200.00")
            self.assertIn("不是账户现金利润", payload["quality_notes"][0])
            self.assertFalse(payload["boundary_flags"]["broker_connection"])
            self.assertFalse(payload["hard_boundaries"]["real_order"])
            self.assertNotIn("historical_net_profit", json.dumps(payload, ensure_ascii=False))

    def test_fallback_quotes_make_profit_not_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._write_fixture(root, quote_source="fallback_quotes_only")

            payload = run_profit_quality_audit(config, generated_at="2026-06-01T18:00:00Z")

            self.assertEqual(payload["audit_status"], "not_verifiable_from_fresh_quotes")
            self.assertTrue(payload["fallback_or_no_fetch_data"])

    def test_rejects_config_that_enables_live_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dashboard = root / "dashboard.json"
            state = root / "state.json"
            dashboard.write_text("{}", encoding="utf-8")
            state.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "cannot enable live_execution"):
                ProfitQualityAuditConfig(
                    stage="M15.profit_quality_audit",
                    dashboard_path=dashboard,
                    runtime_state_path=state,
                    output_dir=root / "out",
                    hard_boundaries={
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": True,
                        "paper_trading_approval": False,
                        "manual_m12_37_once": False,
                    },
                )

    def _write_fixture(self, root: Path, *, quote_source: str) -> ProfitQualityAuditConfig:
        dashboard = root / "dashboard.json"
        state = root / "state.json"
        output_dir = root / "out"
        dashboard.write_text(
            json.dumps(
                {
                    "generated_at": "2026-06-01T17:00:00Z",
                    "paper_simulated_only": True,
                    "paper_trading_approval": False,
                    "live_execution": False,
                    "real_money_actions": False,
                    "trading_connection": False,
                    "summary": {
                        "scan_date": "2026-06-01",
                        "quote_source": quote_source,
                        "data_freshness_warning": "fallback snapshot" if "fallback" in quote_source else "",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        state.write_text(
            json.dumps(
                {
                    "accounts": {
                        "R1": {
                            "display_name": "测试账户",
                            "strategy_id": "S1",
                            "timeframe": "1d",
                            "lane": "mainline",
                            "today_total_pnl": "850",
                            "today_realized_pnl": "600",
                            "today_unrealized_pnl": "250",
                            "today_closed_count": 2,
                            "today_opened_count": 2,
                            "equity": "20850",
                            "closed_trades": [
                                {
                                    "symbol": "AAA",
                                    "timeframe": "1d",
                                    "direction": "看涨",
                                    "realized_pnl": "100",
                                    "entry_price": "10",
                                    "exit_price": "11",
                                    "quantity": "100",
                                    "exit_reason": "止盈",
                                    "exit_price_source": quote_source,
                                    "opened_at": "2026-06-01T14:00:00Z",
                                    "signal_time": "2026-06-01T09:30:00-04:00",
                                    "event_time": "2026-06-01T15:00:00Z",
                                },
                                {
                                    "symbol": "BBB",
                                    "timeframe": "1d",
                                    "direction": "看涨",
                                    "realized_pnl": "500",
                                    "entry_price": "20",
                                    "exit_price": "25",
                                    "quantity": "100",
                                    "exit_reason": "持仓到期退出",
                                    "exit_price_source": quote_source,
                                    "opened_at": "2026-05-30T14:00:00Z",
                                    "signal_time": "2026-05-29T16:00:00-04:00",
                                    "event_time": "2026-06-01T15:00:00Z",
                                },
                            ],
                            "open_positions": [
                                {
                                    "symbol": "CCC",
                                    "timeframe": "1d",
                                    "direction": "看涨",
                                    "current_pnl": "50",
                                    "entry_price": "30",
                                    "latest_price": "31",
                                    "quantity": "50",
                                    "latest_price_source": quote_source,
                                    "opened_at": "2026-06-01T14:30:00Z",
                                    "signal_time": "2026-06-01T09:30:00-04:00",
                                },
                                {
                                    "symbol": "DDD",
                                    "timeframe": "1d",
                                    "direction": "看涨",
                                    "current_pnl": "200",
                                    "entry_price": "40",
                                    "latest_price": "42",
                                    "quantity": "100",
                                    "latest_price_source": quote_source,
                                    "opened_at": "2026-05-29T14:30:00Z",
                                    "signal_time": "2026-05-29T09:30:00-04:00",
                                },
                            ],
                        }
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return ProfitQualityAuditConfig(
            stage="M15.profit_quality_audit",
            dashboard_path=dashboard,
            runtime_state_path=state,
            output_dir=output_dir,
            hard_boundaries={
                "paper_simulated_only": True,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
                "manual_m12_37_once": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
