from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_2_broker_blocker_shadow_ab_prep_lib import (
    load_config,
    run_broker_blocker_shadow_ab_prep,
)


class M142BrokerBlockerShadowAbPrepTest(unittest.TestCase):
    def test_builds_shadow_ab_prep_without_mutating_runtime_or_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shadow_repair = root / "shadow_repair.json"
            output_json = root / "shadow_ab_prep.json"
            output_md = root / "shadow_ab_prep.md"
            config_path = root / "config.json"
            shadow_repair.write_text(
                json.dumps(
                    {
                        "input_refs": {
                            "broker_blocker_diagnostics": "reports/broker_blocker_diagnostics.json",
                            "source_broker_readiness_plan": "reports/broker_readiness_plan.json",
                        },
                        "rows": [
                            self._repair_row(
                                "sig-risk",
                                "M10-PA-008",
                                "M10-PA-008-1d",
                                "ADBE",
                                "apply_quantity_cap",
                                "shadow_repair_candidate",
                                ["max_risk_per_order_exceeded"],
                                "5.2469",
                                "5.2083",
                                "100.74",
                                "100",
                            ),
                            self._repair_row(
                                "sig-exposure",
                                "M10-PA-005",
                                "M10-PA-005-5m",
                                "XLY",
                                "defer_until_exposure_frees",
                                "defer_not_repair",
                                ["max_total_exposure_exceeded"],
                                "173.6422",
                                "0",
                                "36.46",
                                "0",
                            ),
                            self._repair_row(
                                "sig-cooldown",
                                "M10-PA-005",
                                "M10-PA-005-5m",
                                "XLV",
                                "keep_loss_streak_halt",
                                "defer_not_repair",
                                ["consecutive_losses_limit"],
                                "137.534",
                                "0",
                                "55.01",
                                "0",
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
                        "stage": "M14.2.broker_blocker_shadow_ab_prep",
                        "inputs": {"broker_blocker_shadow_repair": str(shadow_repair)},
                        "outputs": {
                            "shadow_ab_prep_json": str(output_json),
                            "shadow_ab_prep_md": str(output_md),
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

            result = run_broker_blocker_shadow_ab_prep(
                load_config(config_path),
                generated_at="2026-05-26T21:30:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.2.broker-blocker-shadow-ab-prep.v1")
            self.assertEqual(result["summary"]["ab_prep_rows"], 3)
            self.assertEqual(result["summary"]["runtime_registration_candidate_count"], 1)
            self.assertEqual(result["summary"]["rule_only_candidate_count"], 2)
            self.assertEqual(result["summary"]["risk_cap_runtime_candidate_count"], 1)
            self.assertEqual(result["summary"]["exposure_ranker_rule_candidate_count"], 1)
            self.assertEqual(result["summary"]["cooldown_quality_rule_candidate_count"], 1)
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

            by_signal = {row["signal_id"]: row for row in result["rows"]}
            self.assertEqual(
                by_signal["sig-risk"]["prep_action"],
                "prepare_quantity_cap_shadow_runtime",
            )
            self.assertTrue(by_signal["sig-risk"]["ready_for_shadow_runtime_registration"])
            self.assertEqual(
                by_signal["sig-risk"]["proposed_shadow_runtime_id"],
                "M10-PA-008-broker-risk-cap-shadow-1d",
            )
            self.assertEqual(
                by_signal["sig-exposure"]["prep_action"],
                "prepare_exposure_ranker_shadow_rule",
            )
            self.assertFalse(by_signal["sig-exposure"]["ready_for_shadow_runtime_registration"])
            self.assertEqual(
                by_signal["sig-cooldown"]["prep_action"],
                "prepare_cooldown_quality_veto_shadow_rule",
            )
            for row in result["rows"]:
                self.assertTrue(row["original_readiness_status_remains_blocked"])
                self.assertFalse(row["m13_registry_mutation"])
                self.assertFalse(row["broker_readiness_status_mutation"])

            summaries = {row["strategy_id"]: row for row in result["strategy_summaries"]}
            self.assertEqual(summaries["M10-PA-008"]["runtime_registration_candidate_count"], 1)
            self.assertEqual(summaries["M10-PA-005"]["rule_only_candidate_count"], 2)
            self.assertTrue(output_json.exists())
            self.assertIn("Broker Blocker Shadow A/B Prep", output_md.read_text(encoding="utf-8"))

    def test_config_rejects_live_or_broker_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "bad_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M14.2.broker_blocker_shadow_ab_prep",
                        "inputs": {"broker_blocker_shadow_repair": str(root / "shadow_repair.json")},
                        "outputs": {
                            "shadow_ab_prep_json": str(root / "out.json"),
                            "shadow_ab_prep_md": str(root / "out.md"),
                        },
                        "hard_boundaries": {
                            "paper_simulated_only": True,
                            "broker_connection": True,
                            "real_order": False,
                            "live_execution": False,
                            "paper_trading_approval": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "cannot enable broker_connection"):
                load_config(config_path)

    def _repair_row(
        self,
        signal_id: str,
        strategy_id: str,
        runtime_id: str,
        symbol: str,
        shadow_action: str,
        shadow_repair_status: str,
        reason_codes: list[str],
        source_quantity: str,
        proposed_quantity: str,
        source_risk: str,
        proposed_risk: str,
    ) -> dict:
        return {
            "row_id": f"row-{signal_id}",
            "strategy_id": strategy_id,
            "runtime_id": runtime_id,
            "signal_id": signal_id,
            "trading_date": "2026-05-22",
            "symbol": symbol,
            "timeframe": runtime_id.rsplit("-", 1)[-1],
            "direction": "short",
            "shadow_action": shadow_action,
            "shadow_repair_status": shadow_repair_status,
            "original_reason_codes": reason_codes,
            "expected_blocker_reduction": reason_codes,
            "source_quantity": source_quantity,
            "proposed_quantity": proposed_quantity,
            "source_risk_amount": source_risk,
            "proposed_risk_amount": proposed_risk,
            "source_notional_exposure": "1000",
            "proposed_notional_exposure": "900",
        }


if __name__ == "__main__":
    unittest.main()
