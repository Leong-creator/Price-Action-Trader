from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_optimization_backlog_lib import load_config, run_m14_rescue_optimization_backlog


class M14RescueOptimizationBacklogTest(unittest.TestCase):
    def test_backlog_flags_pre_10_day_work_and_broker_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_rescue_optimization_backlog(
                load_config(config_path),
                generated_at="2026-05-26T15:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-optimization-backlog.v1")
            self.assertEqual(result["summary"]["rescue_strategy_count"], 3)
            self.assertEqual(result["summary"]["actionable_before_10d_count"], 2)
            self.assertEqual(result["summary"]["zero_signal_after_connection_count"], 1)
            self.assertEqual(result["summary"]["signal_generated_no_account_operation_count"], 1)
            self.assertEqual(result["summary"]["broker_dry_run_blocked_count"], 2)
            self.assertEqual(result["summary"]["broker_blocker_strategy_count"], 2)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])

            rows = {row["strategy_id"]: row for row in result["rescue_rows"]}
            self.assertEqual(rows["M10-PA-001-m14-modify-20260522"]["issue_type"], "zero_signal_after_connection")
            self.assertEqual(rows["M10-PA-001-m14-modify-20260522"]["priority"], "P0")
            self.assertTrue(rows["M10-PA-001-m14-modify-20260522"]["pre_10_day_actionable"])
            self.assertEqual(
                rows["M10-PA-001-m14-modify-20260522"]["optimization_family"],
                "detector_threshold_source_mapping_timeframe",
            )

            self.assertEqual(rows["M10-PA-011-ORB-R1"]["issue_type"], "signal_generated_no_account_operation")
            self.assertIn("signal-to-account bridge", rows["M10-PA-011-ORB-R1"]["recommended_action"])

            self.assertEqual(rows["M10-PA-002-m14-modify-20260522"]["issue_type"], "collect_more_ab_evidence")
            self.assertFalse(rows["M10-PA-002-m14-modify-20260522"]["pre_10_day_actionable"])

            blockers = {row["strategy_id"]: row for row in result["broker_dry_run_blockers"]}
            self.assertEqual(blockers["M10-PA-008"]["priority"], "P0")
            self.assertEqual(blockers["M10-PA-005"]["priority"], "P1")

            persisted = json.loads((root / "backlog.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"]["actionable_before_10d_count"], 2)
            md = (root / "backlog.md").read_text(encoding="utf-8")
            self.assertIn("M14 Rescue Optimization Backlog", md)
            self.assertIn("Broker Dry-run Blockers", md)

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
        plan_path = root / "rescue_plan.json"
        evidence_path = root / "rescue_ab.json"
        broker_path = root / "broker.json"
        config_path = root / "config.json"
        plan_path.write_text(
            json.dumps(
                {
                    "rows": [
                        self._plan_row("M10-PA-001", "M10-PA-001-m14-modify-20260522", "entry_quality_and_filter_variant"),
                        self._plan_row("M10-PA-011", "M10-PA-011-ORB-R1", "rebuild_detector_before_abandon"),
                        self._plan_row("M10-PA-002", "M10-PA-002-m14-modify-20260522", "entry_quality_and_filter_variant"),
                    ]
                }
            ),
            encoding="utf-8",
        )
        evidence_path.write_text(
            json.dumps(
                {
                    "rows": [
                        self._evidence_row("M10-PA-001-m14-modify-20260522", "M10-PA-001", 1, 0, 0, 0),
                        self._evidence_row("M10-PA-011-ORB-R1", "M10-PA-011", 1, 3, 3, 0),
                        self._evidence_row("M10-PA-002-m14-modify-20260522", "M10-PA-002", 3, 2, 2, 1),
                    ]
                }
            ),
            encoding="utf-8",
        )
        broker_path.write_text(
            json.dumps(
                {
                    "rows": [
                        self._broker_row("M10-PA-005", "blocked", ["max_total_exposure_exceeded"]),
                        self._broker_row("M10-PA-008", "blocked", ["max_risk_per_order_exceeded"]),
                        self._broker_row("M10-PA-004", "dry_run_ready", ["allow"]),
                    ]
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.rescue-optimization-backlog.config.v1",
                    "stage": "M14.rescue_optimization_backlog",
                    "min_ab_trading_days": 10,
                    "inputs": {
                        "m14_strategy_rescue_plan": str(plan_path),
                        "m14_rescue_ab_evidence_tracker": str(evidence_path),
                        "m14_2_broker_readiness_plan": str(broker_path),
                    },
                    "outputs": {
                        "backlog_json": str(root / "backlog.json"),
                        "backlog_md": str(root / "backlog.md"),
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

    def _plan_row(self, strategy_id: str, next_variant_id: str, rescue_mode: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "decision": "modify",
            "decision_reason": "fixture",
            "next_variant_id": next_variant_id,
            "rescue_mode": rescue_mode,
            "optimization_hypothesis": "fixture hypothesis",
        }

    def _evidence_row(
        self,
        strategy_id: str,
        parent_strategy_id: str,
        observed_days: int,
        signal_count: int,
        source_row_count: int,
        open_count: int,
    ) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "parent_strategy_id": parent_strategy_id,
            "runtime_ids": [f"{strategy_id}-1d"],
            "evidence_status": "collecting_ab_evidence",
            "observed_trading_days_count": observed_days,
            "signal_count": signal_count,
            "source_row_count": source_row_count,
            "open_count": open_count,
            "close_count": 0,
            "risk_blocked_count": 0,
            "m13_account_ledger_row_count": 1,
        }

    def _broker_row(self, strategy_id: str, status: str, reasons: list[str]) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "readiness_status": status,
            "source_risk_reason_codes": reasons,
            "signal_id": f"{strategy_id}-signal",
            "symbol": "SPY",
        }


if __name__ == "__main__":
    unittest.main()
