from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_2_broker_blocker_shadow_repair_lib import load_config, run_broker_blocker_shadow_repair


class M142BrokerBlockerShadowRepairTest(unittest.TestCase):
    def test_builds_shadow_actions_without_mutating_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            diagnostics = root / "diagnostics.json"
            output_json = root / "shadow_repair.json"
            output_md = root / "shadow_repair.md"
            config_path = root / "config.json"
            diagnostics.write_text(
                json.dumps(
                    {
                        "input_refs": {"m14_2_broker_readiness_plan": "reports/broker_readiness_plan.json"},
                        "rows": [
                            self._diagnostic_row(
                                "sig-risk",
                                "M10-PA-008",
                                "ADBE",
                                "quantity_cap_stop_geometry",
                                ["max_risk_per_order_exceeded"],
                                "5.2469",
                                "5.2083",
                                "19.2",
                                "100.74",
                                "1290.16",
                            ),
                            self._diagnostic_row(
                                "sig-exposure",
                                "M10-PA-005",
                                "XLY",
                                "portfolio_exposure_ranking",
                                ["max_total_exposure_exceeded"],
                                "173.6422",
                                "476.1904",
                                "0.21",
                                "36.46",
                                "20741.56",
                            ),
                            self._diagnostic_row(
                                "sig-cooldown",
                                "M10-PA-005",
                                "XLV",
                                "loss_streak_cooldown_quality_veto",
                                ["consecutive_losses_limit"],
                                "137.5340",
                                "250",
                                "0.4",
                                "55.01",
                                "20616.35",
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
                        "stage": "M14.2.broker_blocker_shadow_repair",
                        "inputs": {"broker_blocker_diagnostics": str(diagnostics)},
                        "outputs": {
                            "shadow_repair_json": str(output_json),
                            "shadow_repair_md": str(output_md),
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

            result = run_broker_blocker_shadow_repair(
                load_config(config_path),
                generated_at="2026-05-26T21:00:00Z",
            )

            self.assertEqual(result["summary"]["shadow_rows"], 3)
            self.assertEqual(result["summary"]["risk_cap_candidate_count"], 1)
            self.assertEqual(result["summary"]["defer_for_exposure_count"], 1)
            self.assertEqual(result["summary"]["cooldown_defer_count"], 1)
            self.assertEqual(result["summary"]["would_change_original_readiness_count"], 0)
            self.assertFalse(result["readiness_status_mutation"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])

            by_signal = {row["signal_id"]: row for row in result["rows"]}
            self.assertEqual(by_signal["sig-risk"]["shadow_action"], "apply_quantity_cap")
            self.assertEqual(by_signal["sig-risk"]["proposed_quantity"], "5.2083")
            self.assertEqual(by_signal["sig-risk"]["proposed_risk_amount"], "100")
            self.assertEqual(by_signal["sig-risk"]["risk_amount_delta"], "0.74")
            self.assertTrue(by_signal["sig-risk"]["original_readiness_status_remains_blocked"])
            self.assertEqual(by_signal["sig-exposure"]["shadow_action"], "defer_until_exposure_frees")
            self.assertEqual(by_signal["sig-exposure"]["proposed_quantity"], "0")
            self.assertEqual(by_signal["sig-cooldown"]["shadow_action"], "keep_loss_streak_halt")

            summaries = {row["strategy_id"]: row for row in result["strategy_summaries"]}
            self.assertFalse(summaries["M10-PA-005"]["ready_for_next_ab_step"])
            self.assertTrue(summaries["M10-PA-008"]["ready_for_next_ab_step"])
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())

    def test_config_rejects_live_or_broker_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "bad_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M14.2.broker_blocker_shadow_repair",
                        "inputs": {"broker_blocker_diagnostics": str(root / "diagnostics.json")},
                        "outputs": {
                            "shadow_repair_json": str(root / "out.json"),
                            "shadow_repair_md": str(root / "out.md"),
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

    def _diagnostic_row(
        self,
        signal_id: str,
        strategy_id: str,
        symbol: str,
        family: str,
        reasons: list[str],
        source_quantity: str,
        quantity_cap: str,
        risk_per_share: str,
        source_risk_amount: str,
        source_notional: str,
    ) -> dict:
        return {
            "row_id": f"row-{signal_id}",
            "strategy_id": strategy_id,
            "runtime_id": f"{strategy_id}-1d",
            "signal_id": signal_id,
            "source_execution_event_id": f"exec-{signal_id}",
            "trading_date": "2026-05-22",
            "symbol": symbol,
            "timeframe": "1d",
            "direction": "short",
            "reason_codes": reasons,
            "diagnostic_family": family,
            "entry_price": "100",
            "source_quantity": source_quantity,
            "quantity_cap_for_risk_limit": quantity_cap,
            "risk_per_share": risk_per_share,
            "source_risk_amount": source_risk_amount,
            "source_notional_exposure": source_notional,
        }


if __name__ == "__main__":
    unittest.main()
