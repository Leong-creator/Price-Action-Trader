from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_target_stop_diagnostics_lib import load_config, run_m14_rescue_target_stop_diagnostics


class M14RescueTargetStopDiagnosticsTest(unittest.TestCase):
    def test_diagnostics_identifies_reward_geometry_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_rescue_target_stop_diagnostics(
                load_config(config_path),
                generated_at="2026-05-26T17:15:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-target-stop-diagnostics.v1")
            self.assertEqual(result["summary"]["diagnosed_runtime_count"], 2)
            self.assertEqual(result["summary"]["target_stop_issue_runtime_count"], 1)
            self.assertEqual(result["summary"]["shadow_candidate_runtime_count"], 1)
            self.assertEqual(
                result["summary"]["dominant_target_stop_issue_counts"]["target_reward_below_1r_after_quality_gates"],
                1,
            )

            by_runtime = {row["runtime_id"]: row for row in result["rows"]}
            blocked = by_runtime["pa012-rescue-5m"]
            self.assertEqual(blocked["source_row_count"], 4)
            self.assertEqual(blocked["non_leveraged_bullish_valid_count"], 2)
            self.assertEqual(blocked["risk_gate_pass_count"], 1)
            self.assertEqual(blocked["reward_ge_1_0_count"], 0)
            self.assertEqual(blocked["dominant_target_stop_issue"], "target_reward_below_1r_after_quality_gates")
            self.assertIn("target_reward_below_1r", blocked["sample_rows"][0]["blockers"])

            shadow = by_runtime["shadow-rescue-5m"]
            self.assertEqual(shadow["dominant_target_stop_issue"], "has_shadow_candidate_after_target_stop_normalization")
            self.assertEqual(shadow["reward_ge_1_0_count"], 1)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])

            persisted = json.loads((root / "target_stop.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "target_stop.md").read_text(encoding="utf-8")
            self.assertIn("Target/stop issue runtimes", md)
            self.assertIn("pa012-rescue-5m", md)

    def test_unsafe_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["real_order"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        dashboard_path = root / "dashboard.json"
        zero_path = root / "zero_signal.json"
        config_path = root / "config.json"
        dashboard_path.write_text(
            json.dumps(
                {
                    "signal_watchlist": [
                        self._source_row("M10-PA-012", "5m", "AAPL", "看涨", "100", "99", "100.40"),
                        self._source_row("M10-PA-012", "5m", "SQQQ", "看涨", "100", "99", "101.50"),
                        self._source_row("M10-PA-012", "5m", "MSFT", "看跌", "100", "99", "101.50"),
                        self._source_row("M10-PA-012", "5m", "NVDA", "看涨", "100", "90", "105.00"),
                        self._source_row("M10-PA-099", "5m", "AMZN", "看涨", "200", "198", "202.40"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        zero_path.write_text(
            json.dumps(
                {
                    "rows": [
                        self._zero_row("pa012-rescue-5m", "M10-PA-012-m14-modify-20260522", "M10-PA-012"),
                        self._zero_row("shadow-rescue-5m", "M10-PA-099-m14-modify-20260522", "M10-PA-099"),
                        {
                            "runtime_id": "quote-rescue-5m",
                            "strategy_id": "M10-PA-001-m14-modify-20260522",
                            "parent_strategy_id": "M10-PA-001",
                            "timeframe": "5m",
                            "dominant_issue": "stale_quote_source_blocks_candidate",
                            "rejection_reason_counts": {"stale_quote_source": 1},
                        },
                    ],
                    "paper_simulated_only": True,
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.rescue-target-stop-diagnostics.config.v1",
                    "stage": "M14.rescue_target_stop_diagnostics",
                    "inputs": {
                        "m12_dashboard_data": str(dashboard_path),
                        "m14_rescue_zero_signal_diagnostics": str(zero_path),
                    },
                    "outputs": {
                        "diagnostics_json": str(root / "target_stop.json"),
                        "diagnostics_md": str(root / "target_stop.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _zero_row(self, runtime_id: str, strategy_id: str, parent_strategy_id: str) -> dict[str, object]:
        return {
            "runtime_id": runtime_id,
            "strategy_id": strategy_id,
            "parent_strategy_id": parent_strategy_id,
            "timeframe": "5m",
            "dominant_issue": "reward_filter_blocks_all",
            "rejection_reason_counts": {"reward_r_below_min": 1},
            "shadow_reward_min_r_pass_counts": {"1.0R": 0, "1.1R": 0, "1.2R": 0},
        }

    def _source_row(
        self,
        strategy_id: str,
        timeframe: str,
        symbol: str,
        direction: str,
        entry: str,
        stop: str,
        target: str,
    ) -> dict[str, str]:
        return {
            "strategy_id": strategy_id,
            "timeframe": timeframe,
            "symbol": symbol,
            "direction": direction,
            "hypothetical_entry_price": entry,
            "hypothetical_stop_price": stop,
            "hypothetical_target_price": target,
            "latest_price_source": "cached_quote",
        }


if __name__ == "__main__":
    unittest.main()
