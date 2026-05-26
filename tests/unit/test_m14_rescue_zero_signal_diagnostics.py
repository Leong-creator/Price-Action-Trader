from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_zero_signal_diagnostics_lib import load_config, run_m14_rescue_zero_signal_diagnostics


class M14RescueZeroSignalDiagnosticsTest(unittest.TestCase):
    PA012_TARGET_STOP_NORMALIZED_RESCUE_ID = (
        "M10-PA-012-m14-modify-20260522-target-stop-risk_normalized_1_0r-shadow"
    )

    def test_diagnostics_classifies_zero_signal_root_causes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_rescue_zero_signal_diagnostics(
                load_config(config_path),
                generated_at="2026-05-26T15:30:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-zero-signal-diagnostics.v1")
            self.assertEqual(result["summary"]["zero_signal_runtime_count"], 4)
            self.assertEqual(result["summary"]["quote_refresh_candidate_runtime_count"], 1)
            self.assertEqual(result["summary"]["quality_filter_blocked_runtime_count"], 1)
            self.assertEqual(result["summary"]["parent_source_absent_runtime_count"], 1)
            self.assertEqual(result["summary"]["parent_detector_zero_signal_runtime_count"], 1)
            self.assertEqual(result["summary"]["potential_signal_if_fresh_quote_count"], 1)
            by_runtime = {row["runtime_id"]: row for row in result["rows"]}
            self.assertEqual(by_runtime["rescue-a-1d"]["dominant_issue"], "stale_quote_source_blocks_candidate")
            self.assertEqual(by_runtime["rescue-b-1d"]["dominant_issue"], "parent_source_absent_for_timeframe")
            self.assertEqual(by_runtime["rescue-c-5m"]["dominant_issue"], "reward_filter_blocks_all")
            self.assertEqual(by_runtime["rescue-c-5m"]["shadow_reward_min_r_pass_counts"]["1.0R"], 1)
            self.assertEqual(by_runtime["rescue-d-1d"]["dominant_issue"], "parent_detector_zero_signal_for_timeframe")
            self.assertEqual(by_runtime["rescue-d-1d"]["parent_audit_input_status"], "connected_zero_signal_today")
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            persisted = json.loads((root / "diagnostics.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            self.assertIn("Quote-refresh candidates", (root / "diagnostics.md").read_text(encoding="utf-8"))

    def test_pa012_target_stop_normalized_shadow_uses_1r_target_before_classifying_zero_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dashboard_path = root / "dashboard.json"
            coverage_path = root / "coverage.json"
            config_path = root / "config.json"
            dashboard_path.write_text(
                json.dumps(
                    {
                        "account_input_audit": {
                            "rows": [
                                self._audit_row(
                                    f"{self.PA012_TARGET_STOP_NORMALIZED_RESCUE_ID}-5m",
                                    self.PA012_TARGET_STOP_NORMALIZED_RESCUE_ID,
                                    "5m",
                                )
                            ]
                        },
                        "signal_watchlist": [
                            self._source_row(
                                "M10-PA-012",
                                "5m",
                                "MSFT",
                                "看涨",
                                "100",
                                "99",
                                "100.50",
                                "cached_quote",
                            )
                        ],
                    }
                ),
                encoding="utf-8",
            )
            coverage_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            self._coverage_row(
                                f"{self.PA012_TARGET_STOP_NORMALIZED_RESCUE_ID}-5m",
                                self.PA012_TARGET_STOP_NORMALIZED_RESCUE_ID,
                                "M10-PA-012",
                            )
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": "m14.rescue-zero-signal-diagnostics.config.v1",
                        "stage": "M14.rescue_zero_signal_diagnostics",
                        "inputs": {
                            "m12_dashboard_data": str(dashboard_path),
                            "m14_rescue_runtime_coverage": str(coverage_path),
                        },
                        "outputs": {
                            "diagnostics_json": str(root / "diagnostics.json"),
                            "diagnostics_md": str(root / "diagnostics.md"),
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

            result = run_m14_rescue_zero_signal_diagnostics(
                load_config(config_path),
                generated_at="2026-05-26T15:30:00Z",
            )

        row = result["rows"][0]
        self.assertEqual(row["dominant_issue"], "stale_quote_source_blocks_candidate")
        self.assertEqual(row["eligible_if_fresh_quote_count"], 1)
        self.assertEqual(row["shadow_reward_min_r_pass_counts"]["1.0R"], 1)
        self.assertNotIn("reward_r_below_min", row["rejection_reason_counts"])

    def test_unsafe_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["broker_connection"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        dashboard_path = root / "dashboard.json"
        coverage_path = root / "coverage.json"
        config_path = root / "config.json"
        dashboard_path.write_text(
            json.dumps(
                {
                    "account_input_audit": {
                        "rows": [
                            self._audit_row("rescue-a-1d", "rescue-a", "1d"),
                            self._audit_row("rescue-b-1d", "rescue-b", "1d"),
                            self._audit_row("rescue-c-5m", "rescue-c", "5m"),
                            self._audit_row("parent-d-1d", "parent-d", "1d", lane="experimental"),
                            self._audit_row("rescue-d-1d", "rescue-d", "1d"),
                            self._audit_row("rescue-live-5m", "rescue-live", "5m", input_status="connected_with_signal_today"),
                        ]
                    },
                    "signal_watchlist": [
                        self._source_row("parent-a", "1d", "AAPL", "看涨", "100", "98", "104", "cached_quote"),
                        self._source_row("parent-c", "5m", "MSFT", "看涨", "100", "99", "100.50", "cached_quote"),
                        self._source_row("parent-c", "5m", "NVDA", "看涨", "100", "99", "101.05", "cached_quote"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        coverage_path.write_text(
            json.dumps(
                {
                    "rows": [
                        self._coverage_row("rescue-a-1d", "rescue-a", "parent-a"),
                        self._coverage_row("rescue-b-1d", "rescue-b", "parent-b"),
                        self._coverage_row("rescue-c-5m", "rescue-c", "parent-c"),
                        self._coverage_row("rescue-d-1d", "rescue-d", "parent-d"),
                        self._coverage_row("rescue-live-5m", "rescue-live", "parent-live"),
                    ]
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.rescue-zero-signal-diagnostics.config.v1",
                    "stage": "M14.rescue_zero_signal_diagnostics",
                    "inputs": {
                        "m12_dashboard_data": str(dashboard_path),
                        "m14_rescue_runtime_coverage": str(coverage_path),
                    },
                    "outputs": {
                        "diagnostics_json": str(root / "diagnostics.json"),
                        "diagnostics_md": str(root / "diagnostics.md"),
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

    def _audit_row(
        self,
        runtime_id: str,
        strategy_id: str,
        timeframe: str,
        *,
        input_status: str = "connected_zero_signal_today",
        lane: str = "rescue",
    ) -> dict[str, str]:
        return {
            "runtime_id": runtime_id,
            "strategy_id": strategy_id,
            "lane": lane,
            "timeframe": timeframe,
            "input_status": input_status,
            "input_source_type": "fixture",
            "source_row_count": "0",
        }

    def _coverage_row(self, runtime_id: str, strategy_id: str, parent_strategy_id: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "parent_strategy_id": parent_strategy_id,
            "runtime_ids": [runtime_id],
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
        quote_source: str,
    ) -> dict[str, str]:
        return {
            "strategy_id": strategy_id,
            "timeframe": timeframe,
            "symbol": symbol,
            "direction": direction,
            "hypothetical_entry_price": entry,
            "hypothetical_stop_price": stop,
            "hypothetical_target_price": target,
            "latest_price_source": quote_source,
            "signal_date": "2026-05-22",
        }


if __name__ == "__main__":
    unittest.main()
