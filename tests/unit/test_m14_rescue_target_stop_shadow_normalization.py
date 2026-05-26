from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_target_stop_shadow_normalization_lib import (
    load_config,
    run_m14_rescue_target_stop_shadow_normalization,
)


class M14RescueTargetStopShadowNormalizationTest(unittest.TestCase):
    def test_shadow_normalization_builds_pa012_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_rescue_target_stop_shadow_normalization(
                load_config(config_path),
                generated_at="2026-05-26T18:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-target-stop-shadow-normalization.v1")
            self.assertEqual(result["summary"]["diagnosed_runtime_count"], 1)
            self.assertEqual(result["summary"]["runtime_with_shadow_candidate_count"], 1)
            self.assertEqual(result["summary"]["source_candidate_row_count"], 2)
            self.assertEqual(result["summary"]["best_variant_candidate_row_count"], 2)
            self.assertEqual(result["summary"]["best_variant_id_counts"], {"risk_normalized_1_0r": 1})
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])

            row = result["rows"][0]
            self.assertEqual(row["runtime_id"], "pa012-rescue-5m")
            self.assertEqual(row["eligible_source_row_count"], 2)
            self.assertEqual(row["current_reward_ge_1_0_count"], 0)
            self.assertEqual(row["best_variant_id"], "risk_normalized_1_0r")
            self.assertEqual(row["best_variant_candidate_count"], 2)
            self.assertIn("shadow-only", row["recommended_action"])

            variants = {item["variant_id"]: item for item in row["variant_summaries"]}
            self.assertEqual(variants["risk_normalized_1_0r"]["candidate_count"], 2)
            self.assertEqual(variants["risk_normalized_1_1r"]["reward_ge_1_1_count"], 2)
            self.assertEqual(variants["opening_range_height_30m"]["evaluated_row_count"], 2)

            persisted = json.loads((root / "normalization.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "normalization.md").read_text(encoding="utf-8")
            self.assertIn("M14 Rescue Target/Stop Shadow Normalization", md)
            self.assertIn("risk_normalized_1_0r", md)

    def test_unsafe_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["live_execution"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        dashboard_path = root / "dashboard.json"
        diagnostics_path = root / "target_stop.json"
        config_path = root / "config.json"
        aapl_path = root / "aapl_5m.csv"
        msft_path = root / "msft_5m.csv"
        self._write_kline(aapl_path, "AAPL", "100", "101.8", "99.8")
        self._write_kline(msft_path, "MSFT", "200", "203.2", "199.7")
        dashboard_path.write_text(
            json.dumps(
                {
                    "signal_watchlist": [
                        self._source_row("AAPL", "看涨", "100", "99", "100.40", aapl_path),
                        self._source_row("MSFT", "看涨", "200", "198", "201.50", msft_path),
                        self._source_row("SQQQ", "看涨", "100", "99", "101.40", aapl_path),
                        self._source_row("NVDA", "看涨", "100", "90", "105.00", aapl_path),
                        self._source_row("SPY", "看跌", "100", "99", "101.50", aapl_path),
                    ],
                }
            ),
            encoding="utf-8",
        )
        diagnostics_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "runtime_id": "pa012-rescue-5m",
                            "strategy_id": "M10-PA-012-m14-modify-20260522",
                            "parent_strategy_id": "M10-PA-012",
                            "timeframe": "5m",
                            "dominant_target_stop_issue": "target_reward_below_1r_after_quality_gates",
                        }
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
                    "schema_version": "m14.rescue-target-stop-shadow-normalization.config.v1",
                    "stage": "M14.rescue_target_stop_shadow_normalization",
                    "opening_range_minutes": 30,
                    "inputs": {
                        "m12_dashboard_data": str(dashboard_path),
                        "m14_rescue_target_stop_diagnostics": str(diagnostics_path),
                    },
                    "outputs": {
                        "normalization_json": str(root / "normalization.json"),
                        "normalization_md": str(root / "normalization.md"),
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

    def _source_row(
        self,
        symbol: str,
        direction: str,
        entry: str,
        stop: str,
        target: str,
        data_path: Path,
    ) -> dict[str, str]:
        return {
            "strategy_id": "M10-PA-012",
            "timeframe": "5m",
            "symbol": symbol,
            "direction": direction,
            "hypothetical_entry_price": entry,
            "hypothetical_stop_price": stop,
            "hypothetical_target_price": target,
            "latest_price_source": "cached_quote",
            "signal_time": "2026-05-22T10:10:00",
            "data_path": str(data_path),
        }

    def _write_kline(self, path: Path, symbol: str, open_price: str, high: str, low: str) -> None:
        path.write_text(
            "\n".join(
                [
                    "symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume",
                    f"{symbol},US,5m,2026-05-22T09:30:00,America/New_York,{open_price},{high},{low},{open_price},1000",
                    f"{symbol},US,5m,2026-05-22T09:35:00,America/New_York,{open_price},{high},{low},{open_price},1000",
                    f"{symbol},US,5m,2026-05-22T10:05:00,America/New_York,{open_price},{high},{low},{open_price},1000",
                ]
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
