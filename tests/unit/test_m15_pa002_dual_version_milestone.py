from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from scripts.m15_pa002_dual_version_milestone_lib import (
    DEFAULT_OUTPUT_SUBDIR,
    run_pa002_dual_version_milestone_evaluator,
)


class M15Pa002DualVersionMilestoneTest(unittest.TestCase):
    def test_waits_for_postmarket_cutoff_on_trading_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_config = self.write_account_config(root)
            self.write_fill_attribution(root / "account_output", [self.trade("2026-07-31", "2026-08-03")])

            payload = run_pa002_dual_version_milestone_evaluator(
                account_config,
                generated_at=datetime(2026, 8, 3, 19, 0, tzinfo=UTC),  # 15:00 New York
            )

            self.assertEqual(payload["evaluation_status"], "waiting_for_postmarket_cutoff")
            self.assertEqual(payload["milestone_phase"], "collecting_sample_before_technical_review")
            review = json.loads((root / "account_output" / DEFAULT_OUTPUT_SUBDIR / "m15_pa002_dual_version_review.json").read_text(encoding="utf-8"))
            self.assertEqual(review["evaluation_status"], "waiting_for_postmarket_cutoff")

    def test_technical_review_only_uses_non_fault_completed_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_config = self.write_account_config(root)
            trades = [
                self.trade("2026-07-24", "2026-07-28", version="baseline", net="4.00"),
                self.trade("2026-07-25", "2026-07-29", version="baseline", net="-2.00"),
                self.trade("2026-07-28", "2026-07-30", version="baseline", net="3.00"),
                self.trade("2026-07-29", "2026-07-31", version="repair", runtime_id="M10-PA-002-5m-repaired-v1", bucket="pa002_5m_repaired_v1", net="6.00"),
                self.trade("2026-07-30", "2026-08-03", version="repair", runtime_id="M10-PA-002-5m-repaired-v1", bucket="pa002_5m_repaired_v1", net="8.00"),
                self.trade("2026-07-30", "2026-08-03", runtime_id="M10-PA-002-1d", bucket="experimental", net="999.00"),
                self.trade("2026-07-31", "2026-08-03", version="baseline", net="-20.00", fault_day=True),
            ]
            self.write_fill_attribution(root / "account_output", trades)

            payload = run_pa002_dual_version_milestone_evaluator(
                account_config,
                generated_at=datetime(2026, 8, 3, 20, 30, tzinfo=UTC),  # 16:30 New York
            )

            self.assertEqual(payload["evaluation_status"], "evaluated")
            self.assertEqual(payload["aggregate"]["effective_trading_day_count"], 5)
            self.assertEqual(payload["aggregate"]["completed_trade_count"], 5)
            self.assertEqual(payload["aggregate"]["normal_completed_trade_count"], 5)
            self.assertEqual(payload["source_status"]["fill_attribution_anomaly_count"], 0)
            self.assertEqual(payload["milestone_phase"], "collecting_sample_before_technical_review")
            self.assertEqual(payload["recommendation"]["code"], "collect_more_effective_days")
            labels = {row["version_label"] for row in payload["version_summaries"]}
            self.assertIn("baseline", labels)
            self.assertIn("repaired_v1", labels)
            baseline = next(row for row in payload["version_summaries"] if row["version_label"] == "baseline")
            self.assertEqual(baseline["completed_trade_count"], 3)

    def test_final_review_requires_fifteen_effective_days_and_hundred_completed_trades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            account_config = self.write_account_config(root)
            trades = []
            day_pairs = [
                ("2026-07-13", "2026-07-14"),
                ("2026-07-14", "2026-07-15"),
                ("2026-07-15", "2026-07-16"),
                ("2026-07-16", "2026-07-17"),
                ("2026-07-17", "2026-07-20"),
                ("2026-07-20", "2026-07-21"),
                ("2026-07-21", "2026-07-22"),
                ("2026-07-22", "2026-07-23"),
                ("2026-07-23", "2026-07-24"),
                ("2026-07-24", "2026-07-27"),
                ("2026-07-27", "2026-07-28"),
                ("2026-07-28", "2026-07-29"),
                ("2026-07-29", "2026-07-30"),
                ("2026-07-30", "2026-07-31"),
                ("2026-07-31", "2026-08-03"),
            ]
            for version in ("baseline", "repair"):
                runtime_id = BASELINE_RUNTIME if version == "baseline" else "M10-PA-002-5m-repaired-v1"
                bucket = "pa002_5m" if version == "baseline" else "pa002_5m_repaired_v1"
                for index in range(100):
                    open_day, close_day = day_pairs[index % len(day_pairs)]
                    net = ("4.00" if index % 10 < 7 else "-2.00") if version == "repair" else "-1.25"
                    trades.append(
                        self.trade(
                            open_day,
                            close_day,
                            version=version,
                            runtime_id=runtime_id,
                            bucket=bucket,
                            net=net,
                            symbol=f"SYM{index % 10}",
                        )
                    )
            self.write_fill_attribution(root / "account_output", trades)

            payload = run_pa002_dual_version_milestone_evaluator(
                account_config,
                generated_at=datetime(2026, 8, 3, 21, 0, tzinfo=UTC),
            )

            self.assertEqual(payload["aggregate"]["effective_trading_day_count"], 15)
            self.assertEqual(payload["aggregate"]["completed_trade_count"], 200)
            self.assertEqual(payload["milestone_phase"], "final_review_ready")
            self.assertEqual(payload["recommendation"]["code"], "final_review_manual_compare_best_version")
            repaired = next(row for row in payload["version_summaries"] if row["version_label"] == "repaired_v1")
            self.assertTrue(repaired["final_quality_gate_passed"])
            self.assertGreaterEqual(float(repaired["average_win_loss_ratio_after_estimated_fees"]), 1.2)
            first = payload["notification"]["notification_dedup_key"]
            second = run_pa002_dual_version_milestone_evaluator(
                account_config,
                generated_at=datetime(2026, 8, 3, 21, 0, tzinfo=UTC),
            )["notification"]["notification_dedup_key"]
            self.assertEqual(first, second)
            review_md = (root / "account_output" / DEFAULT_OUTPUT_SUBDIR / "m15_pa002_dual_version_review.md").read_text(encoding="utf-8")
            self.assertIn("M15 PA002 双版本盘后里程碑评估", review_md)
            self.assertIn("通知去重键", review_md)

    @staticmethod
    def write_account_config(root: Path) -> Path:
        config_path = root / "account_config.json"
        config_path.write_text(
            json.dumps(
                {
                    "stage": "M15.longbridge_realtime_account_state",
                    "outputs": {"output_dir": str(root / "account_output")},
                    "longbridge_account_state": {
                        "required_account_channel": "lb_papertrading",
                        "cli_timeout_seconds": 6,
                        "historical_order_start_date": "2026-06-01",
                        "unfilled_order_detail_lookup_limit": 120,
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "live_execution": False,
                        "real_money_actions": False,
                        "manual_m12_37_once": False,
                        "margin_financing": False,
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return config_path

    @staticmethod
    def write_fill_attribution(output_dir: Path, completed_trades: list[dict[str, object]]) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "m15_longbridge_fill_attribution_v2.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-08-03T20:25:00Z",
                    "completed_trades": completed_trades,
                    "anomalies": [
                        {"runtime_id": "M10-PA-004-long-1d", "reason": "unrelated_test_anomaly"}
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def trade(
        open_market_date: str,
        close_market_date: str,
        *,
        version: str = "baseline",
        runtime_id: str = "M10-PA-002-5m",
        bucket: str = "pa002_5m",
        net: str = "1.00",
        fault_day: bool = False,
        symbol: str = "AAPL",
    ) -> dict[str, object]:
        return {
            "batch_id": f"{runtime_id}:{open_market_date}:{close_market_date}:{net}",
            "runtime_id": runtime_id,
            "capital_bucket": bucket,
            "symbol": symbol,
            "open_market_date": open_market_date,
            "close_market_date": close_market_date,
            "opened_at": f"{open_market_date}T14:35:00Z",
            "closed_at": f"{close_market_date}T19:55:00Z",
            "gross_realized_pnl": net,
            "estimated_fees": "1.00",
            "estimated_net_pnl": net,
            "fault_day": fault_day,
            "direction": "long",
            "version": version,
        }


BASELINE_RUNTIME = "M10-PA-002-5m"


if __name__ == "__main__":
    unittest.main()
