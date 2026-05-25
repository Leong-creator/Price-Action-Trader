import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m14_strategy_rescue_plan_lib import load_config, run_m14_strategy_rescue_plan


class M14StrategyRescuePlanTest(unittest.TestCase):
    def test_rescue_plan_preserves_approved_and_rescues_losers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary = root / "summary.json"
            gate = root / "gate.json"
            decisions = root / "decisions.jsonl"
            out_json = root / "rescue.json"
            out_md = root / "rescue.md"
            summary.write_text(
                json.dumps(
                    {
                        "trading_date": "2026-05-22",
                        "challenge_progress_label": "10/10",
                    }
                ),
                encoding="utf-8",
            )
            gate.write_text(
                json.dumps(
                    {
                        "approved_internal_sim_strategy_ids": ["M10-PA-004"],
                        "rows": [
                            {
                                "strategy_id": "M10-PA-004",
                                "paper_trial_gate": "approved_internal_sim_only",
                            },
                            {
                                "strategy_id": "M10-PA-001",
                                "paper_trial_gate": "not_approved_modify_candidate",
                            },
                            {
                                "strategy_id": "M10-PA-011",
                                "paper_trial_gate": "not_approved_rejected",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            decisions.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        self.decision("M10-PA-004", "promote", "ten_day_positive_expectancy_internal_sim_candidate", "2", "0.9"),
                        self.decision("M10-PA-001", "modify", "net_pnl_below_minus_2r", "-3.1", "4.1"),
                        self.decision("M10-PA-011", "reject", "ten_days_no_viable_signal", "0", "0"),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            config = replace(
                load_config(),
                m14_summary_path=summary,
                paper_gate_path=gate,
                decision_ledger_path=decisions,
                rescue_plan_json_path=out_json,
                rescue_plan_md_path=out_md,
            )

            plan = run_m14_strategy_rescue_plan(config, generated_at="2026-05-25T18:30:00Z")

            by_strategy = {row["strategy_id"]: row for row in plan["rows"]}
            self.assertEqual(by_strategy["M10-PA-004"]["lane"], "approved_internal_sim")
            self.assertEqual(by_strategy["M10-PA-004"]["rescue_mode"], "do_not_change_baseline")
            self.assertEqual(by_strategy["M10-PA-001"]["lane"], "rescue_candidate")
            self.assertEqual(by_strategy["M10-PA-001"]["rescue_mode"], "entry_quality_and_filter_variant")
            self.assertEqual(by_strategy["M10-PA-011"]["lane"], "detector_rebuild")
            self.assertIn("rebuild", by_strategy["M10-PA-011"]["next_action"])
            self.assertFalse(plan["hard_boundaries"]["broker_connection"])
            self.assertFalse(plan["hard_boundaries"]["real_order"])
            self.assertTrue(out_json.exists())
            self.assertIn("M10-PA-011", out_md.read_text(encoding="utf-8"))

    def test_config_rejects_live_or_broker_boundary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            payload = json.loads(Path("config/examples/m14_strategy_rescue_plan.json").read_text(encoding="utf-8"))
            payload["hard_boundaries"]["live_execution"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(path)

    def decision(self, strategy_id: str, decision: str, reason: str, pnl_r: str, drawdown: str) -> dict[str, str]:
        return {
            "strategy_id": strategy_id,
            "decision": decision,
            "decision_reason": reason,
            "realized_pnl": "0.00",
            "net_pnl_r": pnl_r,
            "max_drawdown_percent": drawdown,
            "signal_days": "3",
            "open_count": "3",
            "close_count": "2",
            "risk_block_ratio": "0",
            "next_variant_id": f"{strategy_id}-variant",
        }


if __name__ == "__main__":
    unittest.main()
