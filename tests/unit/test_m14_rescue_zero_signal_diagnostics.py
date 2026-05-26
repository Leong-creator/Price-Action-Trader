from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_zero_signal_diagnostics_lib import load_config, run_m14_rescue_zero_signal_diagnostics


class M14RescueZeroSignalDiagnosticsTest(unittest.TestCase):
    def test_diagnostics_classifies_zero_signal_root_causes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_rescue_zero_signal_diagnostics(
                load_config(config_path),
                generated_at="2026-05-26T15:30:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-zero-signal-diagnostics.v1")
            self.assertEqual(result["summary"]["zero_signal_runtime_count"], 3)
            self.assertEqual(result["summary"]["quote_refresh_candidate_runtime_count"], 1)
            self.assertEqual(result["summary"]["quality_filter_blocked_runtime_count"], 1)
            self.assertEqual(result["summary"]["parent_source_absent_runtime_count"], 1)
            self.assertEqual(result["summary"]["potential_signal_if_fresh_quote_count"], 1)
            by_runtime = {row["runtime_id"]: row for row in result["rows"]}
            self.assertEqual(by_runtime["rescue-a-1d"]["dominant_issue"], "stale_quote_source_blocks_candidate")
            self.assertEqual(by_runtime["rescue-b-1d"]["dominant_issue"], "parent_source_absent_for_timeframe")
            self.assertEqual(by_runtime["rescue-c-5m"]["dominant_issue"], "reward_filter_blocks_all")
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            persisted = json.loads((root / "diagnostics.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            self.assertIn("Quote-refresh candidates", (root / "diagnostics.md").read_text(encoding="utf-8"))

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
                            self._audit_row("rescue-live-5m", "rescue-live", "5m", input_status="connected_with_signal_today"),
                        ]
                    },
                    "signal_watchlist": [
                        self._source_row("parent-a", "1d", "AAPL", "看涨", "100", "98", "104", "cached_quote"),
                        self._source_row("parent-c", "5m", "MSFT", "看涨", "100", "99", "100.50", "cached_quote"),
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

    def _audit_row(self, runtime_id: str, strategy_id: str, timeframe: str, *, input_status: str = "connected_zero_signal_today") -> dict[str, str]:
        return {
            "runtime_id": runtime_id,
            "strategy_id": strategy_id,
            "lane": "rescue",
            "timeframe": timeframe,
            "input_status": input_status,
            "input_source_type": "fixture",
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
