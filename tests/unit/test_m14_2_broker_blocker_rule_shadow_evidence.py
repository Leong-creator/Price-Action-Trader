from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_2_broker_blocker_rule_shadow_evidence_lib import (
    load_config,
    run_broker_blocker_rule_shadow_evidence,
)


class M142BrokerBlockerRuleShadowEvidenceTest(unittest.TestCase):
    def test_builds_rule_shadow_evidence_without_runtime_or_readiness_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shadow_ab_prep = root / "shadow_ab_prep.json"
            output_json = root / "rule_shadow_evidence.json"
            output_md = root / "rule_shadow_evidence.md"
            config_path = root / "config.json"
            shadow_ab_prep.write_text(
                json.dumps(
                    {
                        "input_refs": {
                            "broker_blocker_shadow_repair": "reports/broker_blocker_shadow_repair.json",
                            "source_broker_blocker_diagnostics": "reports/broker_blocker_diagnostics.json",
                            "source_broker_readiness_plan": "reports/broker_readiness_plan.json",
                        },
                        "rows": [
                            self._prep_row(
                                "sig-risk",
                                "M10-PA-008",
                                "ADBE",
                                "prepare_quantity_cap_shadow_runtime",
                                "runtime_candidate_shadow",
                                "max_risk_per_order_exceeded",
                            ),
                            self._prep_row(
                                "sig-exposure",
                                "M10-PA-005",
                                "XLY",
                                "prepare_exposure_ranker_shadow_rule",
                                "rule_only_shadow",
                                "max_total_exposure_exceeded",
                            ),
                            self._prep_row(
                                "sig-cooldown",
                                "M10-PA-005",
                                "XLV",
                                "prepare_cooldown_quality_veto_shadow_rule",
                                "rule_only_shadow",
                                "consecutive_losses_limit",
                            ),
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M14.2.broker_blocker_rule_shadow_evidence",
                        "inputs": {"broker_blocker_shadow_ab_prep": str(shadow_ab_prep)},
                        "outputs": {
                            "rule_shadow_evidence_json": str(output_json),
                            "rule_shadow_evidence_md": str(output_md),
                        },
                        "hard_boundaries": {
                            "paper_simulated_only": True,
                            "broker_connection": False,
                            "real_order": False,
                            "live_execution": False,
                            "paper_trading_approval": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = run_broker_blocker_rule_shadow_evidence(
                load_config(config_path),
                generated_at="2026-05-26T22:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.2.broker-blocker-rule-shadow-evidence.v1")
            self.assertEqual(result["summary"]["source_ab_prep_rows"], 3)
            self.assertEqual(result["summary"]["source_runtime_candidate_rows"], 1)
            self.assertEqual(result["summary"]["rule_shadow_evidence_rows"], 2)
            self.assertEqual(result["summary"]["strategy_count"], 1)
            self.assertEqual(result["summary"]["exposure_ranker_rule_count"], 1)
            self.assertEqual(result["summary"]["cooldown_quality_rule_count"], 1)
            self.assertEqual(result["summary"]["ready_for_next_internal_sim_refresh_count"], 2)
            self.assertEqual(result["summary"]["runtime_registration_count"], 0)
            self.assertEqual(result["summary"]["original_blocked_rows_preserved_count"], 2)
            self.assertEqual(result["summary"]["m13_registry_mutation_count"], 0)
            self.assertEqual(result["summary"]["m12_account_specs_mutation_count"], 0)
            self.assertEqual(result["summary"]["broker_readiness_status_mutation_count"], 0)
            self.assertFalse(result["runtime_registration_mutation"])
            self.assertFalse(result["m13_registry_mutation"])
            self.assertFalse(result["m12_account_specs_mutation"])
            self.assertFalse(result["broker_readiness_status_mutation"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])

            by_signal = {row["signal_id"]: row for row in result["rows"]}
            self.assertNotIn("sig-risk", by_signal)
            self.assertEqual(by_signal["sig-exposure"]["rule_family"], "portfolio_exposure_ranker")
            self.assertEqual(
                by_signal["sig-exposure"]["shadow_rule_decision"],
                "defer_until_exposure_headroom_returns",
            )
            self.assertEqual(by_signal["sig-cooldown"]["rule_family"], "cooldown_quality_veto")
            self.assertEqual(
                by_signal["sig-cooldown"]["shadow_rule_decision"],
                "preserve_loss_streak_halt_and_veto_lower_quality_later_entries",
            )
            for row in result["rows"]:
                self.assertFalse(row["would_create_runtime"])
                self.assertFalse(row["ready_for_shadow_runtime_registration"])
                self.assertFalse(row["runtime_registration_mutation"])
                self.assertTrue(row["original_readiness_status_remains_blocked"])
                self.assertFalse(row["m13_registry_mutation"])
                self.assertFalse(row["broker_readiness_status_mutation"])

            self.assertEqual(result["strategy_summaries"][0]["strategy_id"], "M10-PA-005")
            self.assertEqual(result["strategy_summaries"][0]["runtime_registration_count"], 0)
            self.assertTrue(output_json.exists())
            self.assertIn("Broker Blocker Rule Shadow Evidence", output_md.read_text(encoding="utf-8"))

    def test_config_rejects_live_or_broker_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "bad_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M14.2.broker_blocker_rule_shadow_evidence",
                        "inputs": {"broker_blocker_shadow_ab_prep": str(root / "shadow_ab_prep.json")},
                        "outputs": {
                            "rule_shadow_evidence_json": str(root / "out.json"),
                            "rule_shadow_evidence_md": str(root / "out.md"),
                        },
                        "hard_boundaries": {
                            "paper_simulated_only": True,
                            "broker_connection": False,
                            "real_order": True,
                            "live_execution": False,
                            "paper_trading_approval": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "cannot enable real_order"):
                load_config(config_path)

    def _prep_row(
        self,
        signal_id: str,
        strategy_id: str,
        symbol: str,
        prep_action: str,
        shadow_scope: str,
        reason_code: str,
    ) -> dict:
        return {
            "row_id": f"row-{signal_id}",
            "strategy_id": strategy_id,
            "runtime_id": f"{strategy_id}-5m",
            "signal_id": signal_id,
            "trading_date": "2026-05-22",
            "symbol": symbol,
            "timeframe": "5m",
            "direction": "short",
            "prep_action": prep_action,
            "prep_status": "rule_only_prep_not_runtime",
            "shadow_scope": shadow_scope,
            "source_shadow_action": "defer_until_exposure_frees",
            "source_shadow_repair_status": "defer_not_repair",
            "source_reason_codes": [reason_code],
            "expected_blocker_reduction": [reason_code],
            "proposed_shadow_strategy_id": f"{strategy_id}-shadow",
            "proposed_variant_id": "broker_rule_shadow",
            "source_quantity": "100",
            "source_risk_amount": "50",
            "source_notional_exposure": "1000",
            "proposed_quantity": "0",
            "proposed_risk_amount": "0",
            "proposed_notional_exposure": "0",
        }


if __name__ == "__main__":
    unittest.main()
