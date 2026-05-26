from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_2_broker_blocker_diagnostics_lib import load_config, run_broker_blocker_diagnostics


class M142BrokerBlockerDiagnosticsTest(unittest.TestCase):
    def test_builds_sizing_exposure_and_cooldown_diagnostics_without_unblocking_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            broker_plan = root / "broker_readiness_plan.json"
            challenge_config = root / "challenge_config.json"
            ledger = root / "internal_paper.jsonl"
            output_json = root / "broker_blocker_diagnostics.json"
            output_md = root / "broker_blocker_diagnostics.md"
            config_path = root / "config.json"

            challenge_config.write_text(
                json.dumps(
                    {
                        "internal_paper": {
                            "max_risk_per_order": "100",
                            "max_total_exposure": "25000",
                            "max_consecutive_losses": 2,
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger_rows = [
                self._ledger_row(
                    "exec-risk",
                    "M10-PA-008",
                    "M10-PA-008-1d",
                    "sig-risk",
                    "ADBE",
                    "1d",
                    "short",
                    "245.89",
                    "265.09",
                    "207.49",
                    "5.2469",
                    "block",
                    "max_risk_per_order_exceeded",
                ),
                self._ledger_row(
                    "exec-exposure",
                    "M10-PA-005",
                    "M10-PA-005-5m",
                    "sig-exposure",
                    "XLY",
                    "5m",
                    "short",
                    "119.45",
                    "119.66",
                    "119.03",
                    "173.6422",
                    "block",
                    "max_total_exposure_exceeded",
                ),
                self._ledger_row(
                    "exec-cooldown",
                    "M10-PA-005",
                    "M10-PA-005-5m",
                    "sig-cooldown",
                    "XLV",
                    "5m",
                    "long",
                    "149.90",
                    "149.50",
                    "150.68",
                    "137.5340",
                    "halted",
                    "consecutive_losses_limit",
                ),
            ]
            ledger.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in ledger_rows), encoding="utf-8")
            broker_plan.write_text(
                json.dumps(
                    {
                        "internal_paper_execution_ledger_ref": str(ledger),
                        "rows": [
                            self._broker_row("exec-risk", "M10-PA-008", "M10-PA-008-1d", "sig-risk", "ADBE", "1d", "short", "block", ["max_risk_per_order_exceeded"]),
                            self._broker_row("exec-exposure", "M10-PA-005", "M10-PA-005-5m", "sig-exposure", "XLY", "5m", "short", "block", ["max_total_exposure_exceeded"]),
                            self._broker_row("exec-cooldown", "M10-PA-005", "M10-PA-005-5m", "sig-cooldown", "XLV", "5m", "long", "halted", ["consecutive_losses_limit"]),
                            {
                                "readiness_status": "dry_run_ready",
                                "strategy_id": "M10-PA-004",
                                "source_execution_event_id": "exec-ready",
                                "source_risk_reason_codes": ["allow"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M14.2.broker_blocker_diagnostics",
                        "inputs": {
                            "m14_2_broker_readiness_plan": str(broker_plan),
                            "m14_strategy_challenge_config": str(challenge_config),
                        },
                        "outputs": {
                            "diagnostics_json": str(output_json),
                            "diagnostics_md": str(output_md),
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

            result = run_broker_blocker_diagnostics(
                load_config(config_path),
                generated_at="2026-05-26T20:00:00Z",
            )

            self.assertEqual(result["summary"]["source_readiness_rows"], 4)
            self.assertEqual(result["summary"]["blocked_count"], 3)
            self.assertEqual(result["summary"]["blocked_strategy_count"], 2)
            self.assertEqual(result["summary"]["sizing_repair_candidate_count"], 1)
            self.assertEqual(result["summary"]["exposure_ranking_candidate_count"], 1)
            self.assertEqual(result["summary"]["cooldown_candidate_count"], 1)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])

            by_signal = {row["signal_id"]: row for row in result["rows"]}
            self.assertEqual(by_signal["sig-risk"]["diagnostic_family"], "quantity_cap_stop_geometry")
            self.assertEqual(by_signal["sig-risk"]["source_risk_amount"], "100.74")
            self.assertEqual(by_signal["sig-risk"]["quantity_cap_for_risk_limit"], "5.2083")
            self.assertTrue(by_signal["sig-risk"]["preview_blocked"])
            self.assertEqual(by_signal["sig-exposure"]["diagnostic_family"], "portfolio_exposure_ranking")
            self.assertEqual(by_signal["sig-cooldown"]["diagnostic_family"], "loss_streak_cooldown_quality_veto")

            summaries = {row["strategy_id"]: row for row in result["strategy_summaries"]}
            self.assertEqual(summaries["M10-PA-005"]["blocked_count"], 2)
            self.assertIn("cooldown", summaries["M10-PA-005"]["recommended_next_action"])
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())

    def test_config_rejects_live_or_broker_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "bad_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "stage": "M14.2.broker_blocker_diagnostics",
                        "inputs": {
                            "m14_2_broker_readiness_plan": str(root / "plan.json"),
                            "m14_strategy_challenge_config": str(root / "challenge.json"),
                        },
                        "outputs": {
                            "diagnostics_json": str(root / "out.json"),
                            "diagnostics_md": str(root / "out.md"),
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

    def _broker_row(
        self,
        event_id: str,
        strategy_id: str,
        runtime_id: str,
        signal_id: str,
        symbol: str,
        timeframe: str,
        direction: str,
        risk_outcome: str,
        reason_codes: list[str],
    ) -> dict:
        return {
            "readiness_status": "blocked",
            "source_execution_event_id": event_id,
            "strategy_id": strategy_id,
            "runtime_id": runtime_id,
            "trading_date": "2026-05-22",
            "signal_id": signal_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": direction,
            "risk_outcome": risk_outcome,
            "source_risk_reason_codes": reason_codes,
        }

    def _ledger_row(
        self,
        event_id: str,
        strategy_id: str,
        runtime_id: str,
        signal_id: str,
        symbol: str,
        timeframe: str,
        direction: str,
        entry: str,
        stop: str,
        target: str,
        quantity: str,
        risk_outcome: str,
        reason_codes: str,
    ) -> dict:
        return {
            "execution_event_id": event_id,
            "strategy_id": strategy_id,
            "runtime_id": runtime_id,
            "trading_date": "2026-05-22",
            "signal_id": signal_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": direction,
            "entry_price": entry,
            "stop_price": stop,
            "target_price": target,
            "quantity": quantity,
            "risk_outcome": risk_outcome,
            "reason_codes": reason_codes,
        }


if __name__ == "__main__":
    unittest.main()
