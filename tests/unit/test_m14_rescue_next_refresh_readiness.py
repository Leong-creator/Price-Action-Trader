from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_next_refresh_readiness_lib import load_config, run_m14_rescue_next_refresh_readiness


class M14RescueNextRefreshReadinessTest(unittest.TestCase):
    def test_builds_next_refresh_watchlist_without_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_rescue_next_refresh_readiness(
                load_config(config_path),
                generated_at="2026-05-26T22:30:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-next-refresh-readiness.v1")
            self.assertEqual(result["summary"]["source_rescue_backlog_rows"], 2)
            self.assertEqual(result["summary"]["watch_rows"], 6)
            self.assertEqual(result["summary"]["fresh_quote_recheck_count"], 1)
            self.assertEqual(result["summary"]["first_ledger_watch_count"], 1)
            self.assertEqual(result["summary"]["broker_rule_shadow_watch_count"], 2)
            self.assertEqual(result["summary"]["target_stop_shadow_compare_count"], 1)
            self.assertEqual(result["summary"]["parent_detector_wait_count"], 1)
            self.assertEqual(result["summary"]["parameter_change_allowed_now_count"], 0)
            self.assertEqual(result["summary"]["m13_registry_mutation_count"], 0)
            self.assertEqual(result["summary"]["m12_account_specs_mutation_count"], 0)
            self.assertEqual(result["summary"]["broker_readiness_status_mutation_count"], 0)
            self.assertFalse(result["m13_registry_mutation"])
            self.assertFalse(result["m12_account_specs_mutation"])
            self.assertFalse(result["broker_readiness_status_mutation"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])

            family_counts = result["summary"]["readiness_family_counts"]
            self.assertEqual(family_counts["fresh_quote_recheck"], 1)
            self.assertEqual(family_counts["first_rescue_ledger_watch"], 1)
            self.assertEqual(family_counts["broker_rule_shadow_recheck"], 2)

            for row in result["rows"]:
                self.assertFalse(row["parameter_change_allowed_now"])
                self.assertFalse(row["m13_registry_mutation"])
                self.assertFalse(row["broker_readiness_status_mutation"])

            md = (root / "next_refresh.md").read_text(encoding="utf-8")
            self.assertIn("M14 Rescue Next Refresh Readiness", md)
            self.assertIn("Parameter changes allowed now: `0`", md)

    def test_config_rejects_live_or_broker_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["paper_trading_approval"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "cannot enable paper_trading_approval"):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        backlog_path = root / "backlog.json"
        zero_path = root / "zero.json"
        ab_path = root / "ab.json"
        target_stop_path = root / "target_stop.json"
        broker_rule_path = root / "broker_rule.json"
        config_path = root / "config.json"
        backlog_path.write_text(
            json.dumps(
                {
                    "rescue_rows": [
                        {"strategy_id": "M10-PA-001-m14-modify-20260522"},
                        {"strategy_id": "M10-PA-008-broker-risk-cap-shadow"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        zero_path.write_text(
            json.dumps(
                {
                    "rows": [
                        self._zero_row(
                            "M10-PA-001-m14-modify-20260522",
                            "M10-PA-001",
                            "M10-PA-001-m14-modify-20260522-1d",
                            "stale_quote_source_blocks_candidate",
                            3,
                        ),
                        self._zero_row(
                            "M10-PA-012-m14-modify-20260522",
                            "M10-PA-012",
                            "M10-PA-012-m14-modify-20260522-5m",
                            "reward_filter_blocks_all",
                            0,
                        ),
                        self._zero_row(
                            "M10-PA-013-m14-modify-20260522",
                            "M10-PA-013",
                            "M10-PA-013-m14-modify-20260522-1d",
                            "parent_detector_zero_signal_for_timeframe",
                            0,
                        ),
                    ]
                }
            ),
            encoding="utf-8",
        )
        ab_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "strategy_id": "M10-PA-008-broker-risk-cap-shadow",
                            "parent_strategy_id": "M10-PA-008",
                            "runtime_ids": ["M10-PA-008-broker-risk-cap-shadow-1d"],
                            "evidence_status": "no_m13_rescue_ledger_evidence_yet",
                            "m13_signal_ledger_row_count": 0,
                            "m13_account_ledger_row_count": 0,
                            "observed_trading_days_count": 0,
                        },
                        {
                            "strategy_id": "M10-PA-011-ORB-R1",
                            "parent_strategy_id": "M10-PA-011",
                            "runtime_ids": ["M10-PA-011-ORB-R1-5m"],
                            "evidence_status": "collecting_ab_evidence",
                            "m13_signal_ledger_row_count": 1,
                            "m13_account_ledger_row_count": 1,
                            "observed_trading_days_count": 1,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        target_stop_path.write_text(
            json.dumps({"summary": {"runtime_with_shadow_candidate_count": 1}}),
            encoding="utf-8",
        )
        broker_rule_path.write_text(
            json.dumps(
                {
                    "rows": [
                        self._broker_rule_row("sig-exposure", "portfolio_exposure_ranker"),
                        self._broker_rule_row("sig-cooldown", "cooldown_quality_veto"),
                    ]
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "stage": "M14.rescue_next_refresh_readiness",
                    "inputs": {
                        "m14_rescue_optimization_backlog": str(backlog_path),
                        "m14_rescue_zero_signal_diagnostics": str(zero_path),
                        "m14_rescue_ab_evidence_tracker": str(ab_path),
                        "m14_rescue_target_stop_shadow_normalization": str(target_stop_path),
                        "m14_2_broker_blocker_rule_shadow_evidence": str(broker_rule_path),
                    },
                    "outputs": {
                        "next_refresh_readiness_json": str(root / "next_refresh.json"),
                        "next_refresh_readiness_md": str(root / "next_refresh.md"),
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

    def _zero_row(
        self,
        strategy_id: str,
        parent_strategy_id: str,
        runtime_id: str,
        dominant_issue: str,
        eligible_count: int,
    ) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "parent_strategy_id": parent_strategy_id,
            "runtime_id": runtime_id,
            "timeframe": runtime_id.rsplit("-", 1)[-1],
            "dominant_issue": dominant_issue,
            "eligible_if_fresh_quote_count": eligible_count,
            "parent_source_row_count": 4,
            "parent_audit_input_status": "connected_zero_signal_today",
            "parent_audit_source_row_count": 0,
            "rejection_reason_counts": {"stale_quote_source": eligible_count},
            "shadow_reward_min_r_pass_counts": {"1.0R": eligible_count},
            "sample_symbols": ["SPY"],
        }

    def _broker_rule_row(self, signal_id: str, rule_family: str) -> dict[str, object]:
        return {
            "strategy_id": "M10-PA-005",
            "runtime_id": "M10-PA-005-5m",
            "timeframe": "5m",
            "signal_id": signal_id,
            "symbol": "XLY",
            "rule_family": rule_family,
            "comparison_contract": "fixture comparison contract",
            "source_reason_codes": ["max_total_exposure_exceeded"],
            "source_quantity": "100",
            "source_risk_amount": "50",
            "source_notional_exposure": "1000",
        }


if __name__ == "__main__":
    unittest.main()
