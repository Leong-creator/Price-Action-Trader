from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_goal_readiness_report_lib import load_config, run_m14_goal_readiness_report


class M14GoalReadinessReportTest(unittest.TestCase):
    def test_report_synthesizes_stage_gate_rescue_and_broker_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_goal_readiness_report(
                load_config(config_path),
                generated_at="2026-05-26T13:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.goal-readiness-report.v1")
            self.assertTrue(result["challenge"]["ten_day_challenge_complete"])
            self.assertTrue(result["internal_simulation_gate"]["can_enter_internal_simulation_for_approved_strategies"])
            self.assertEqual(result["internal_simulation_gate"]["approved_internal_sim_strategy_ids"], ["M10-PA-004"])
            self.assertEqual(result["rescue_status"]["rescue_runtime_connected_strategy_count"], 2)
            self.assertTrue(result["rescue_status"]["rescue_ready_for_ab_evidence_collection"])
            self.assertEqual(result["rescue_ab_evidence"]["m13_ledger_observed_strategy_count"], 2)
            self.assertEqual(result["rescue_ab_evidence"]["rescue_runtime_strategy_count"], 2)
            self.assertEqual(result["rescue_ab_evidence"]["evidence_ready_for_manual_review_count"], 0)
            self.assertEqual(result["rescue_ab_evidence"]["promotion_allowed_count"], 0)
            self.assertEqual(result["rescue_optimization_backlog"]["actionable_before_10d_count"], 2)
            self.assertEqual(result["rescue_optimization_backlog"]["zero_signal_after_connection_count"], 1)
            self.assertEqual(result["rescue_optimization_backlog"]["signal_generated_no_account_operation_count"], 1)
            self.assertEqual(result["rescue_next_refresh_readiness"]["watch_rows"], 4)
            self.assertEqual(result["rescue_next_refresh_readiness"]["fresh_quote_recheck_count"], 1)
            self.assertEqual(result["rescue_next_refresh_readiness"]["first_ledger_watch_count"], 1)
            self.assertEqual(result["rescue_next_refresh_readiness"]["broker_rule_shadow_watch_count"], 2)
            self.assertEqual(result["rescue_next_refresh_readiness"]["parameter_change_allowed_now_count"], 0)
            self.assertEqual(result["rescue_zero_signal_diagnostics"]["zero_signal_runtime_count"], 2)
            self.assertEqual(result["rescue_zero_signal_diagnostics"]["quote_refresh_candidate_runtime_count"], 1)
            self.assertEqual(result["rescue_zero_signal_diagnostics"]["quality_filter_blocked_runtime_count"], 1)
            self.assertEqual(result["rescue_target_stop_diagnostics"]["diagnosed_runtime_count"], 1)
            self.assertEqual(result["rescue_target_stop_diagnostics"]["target_stop_issue_runtime_count"], 1)
            self.assertEqual(
                result["rescue_target_stop_diagnostics"]["dominant_target_stop_issue_counts"],
                {"target_reward_below_1r_after_quality_gates": 1},
            )
            self.assertEqual(result["rescue_target_stop_shadow_normalization"]["diagnosed_runtime_count"], 1)
            self.assertEqual(result["rescue_target_stop_shadow_normalization"]["runtime_with_shadow_candidate_count"], 1)
            self.assertEqual(result["rescue_target_stop_shadow_normalization"]["best_variant_candidate_row_count"], 2)
            self.assertEqual(
                result["rescue_target_stop_shadow_normalization"]["best_variant_id_counts"],
                {"risk_normalized_1_0r": 1},
            )
            self.assertEqual(result["broker_readiness"]["mode"], "paper_dry_run_only")
            self.assertEqual(result["broker_readiness"]["dry_run_ready_count"], 1)
            self.assertEqual(result["broker_readiness"]["blocked_count"], 1)
            self.assertEqual(result["broker_blocker_shadow_repair"]["risk_cap_candidate_count"], 1)
            self.assertEqual(result["broker_blocker_shadow_repair"]["defer_for_exposure_count"], 1)
            self.assertEqual(result["broker_blocker_shadow_repair"]["cooldown_defer_count"], 1)
            self.assertFalse(result["broker_blocker_shadow_repair"]["readiness_status_mutation"])
            self.assertEqual(result["broker_blocker_shadow_ab_prep"]["runtime_registration_candidate_count"], 1)
            self.assertEqual(result["broker_blocker_shadow_ab_prep"]["rule_only_candidate_count"], 2)
            self.assertEqual(result["broker_blocker_shadow_ab_prep"]["original_blocked_rows_preserved_count"], 3)
            self.assertEqual(result["broker_blocker_shadow_ab_prep"]["m13_registry_mutation_count"], 0)
            self.assertFalse(result["broker_blocker_shadow_ab_prep"]["broker_readiness_status_mutation"])
            self.assertEqual(result["broker_blocker_rule_shadow_evidence"]["rule_shadow_evidence_rows"], 2)
            self.assertEqual(result["broker_blocker_rule_shadow_evidence"]["exposure_ranker_rule_count"], 1)
            self.assertEqual(result["broker_blocker_rule_shadow_evidence"]["cooldown_quality_rule_count"], 1)
            self.assertEqual(result["broker_blocker_rule_shadow_evidence"]["runtime_registration_count"], 0)
            self.assertEqual(result["broker_blocker_rule_shadow_evidence"]["original_blocked_rows_preserved_count"], 2)
            self.assertFalse(result["broker_blocker_rule_shadow_evidence"]["runtime_registration_mutation"])
            self.assertFalse(result["broker_blocker_rule_shadow_evidence"]["broker_readiness_status_mutation"])
            self.assertTrue(all(result["execution_boundaries"].values()))
            self.assertFalse(result["goal_completion_assessment"]["goal_complete"])
            self.assertIn("no broker/live/real order approval", result["plain_language_result"])
            self.assertIn("Broker blocker shadow repair has 1 quantity-cap candidate", result["plain_language_result"])
            self.assertIn("Broker blocker shadow A/B prep has 1 runtime-registration candidate", result["plain_language_result"])
            self.assertIn("Broker blocker rule shadow evidence has 2 PA005 rule-only rows", result["plain_language_result"])
            self.assertIn("Next-refresh readiness tracks 4 rescue watch rows", result["plain_language_result"])

            matrix = {row["strategy_id"]: row for row in result["strategy_action_matrix"]}
            self.assertEqual(matrix["M10-PA-004"]["next_action_category"], "continue_internal_simulation")
            self.assertTrue(matrix["M10-PA-004"]["can_enter_internal_simulation"])
            self.assertEqual(matrix["M10-PA-001"]["next_action_category"], "collect_rescue_ab_evidence")
            self.assertEqual(matrix["M10-PA-011"]["next_action_category"], "rebuild_detector_ab_evidence")
            for row in matrix.values():
                self.assertFalse(row["broker_connection"])
                self.assertFalse(row["real_order"])
                self.assertFalse(row["live_execution"])
                self.assertFalse(row["paper_trading_approval"])

            persisted = json.loads((root / "readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["project_stage_label"], result["project_stage_label"])
            md = (root / "readiness.md").read_text(encoding="utf-8")
            self.assertIn("Internal simulated-account ready strategies", md)
            self.assertIn("Rescue A/B Evidence", md)
            self.assertIn("Rescue Optimization Backlog", md)
            self.assertIn("Rescue Next Refresh Readiness", md)
            self.assertIn("Rescue Zero-Signal Diagnostics", md)
            self.assertIn("Rescue Target/Stop Diagnostics", md)
            self.assertIn("Rescue Target/Stop Shadow Normalization", md)
            self.assertIn("Broker Blocker Shadow Repair", md)
            self.assertIn("Broker Blocker Shadow A/B Prep", md)
            self.assertIn("Broker Blocker Rule Shadow Evidence", md)
            self.assertIn("Completion Assessment", md)

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
        summary_path = root / "summary.json"
        gate_path = root / "gate.json"
        rescue_plan_path = root / "rescue_plan.json"
        rescue_coverage_path = root / "rescue_coverage.json"
        rescue_ab_path = root / "rescue_ab.json"
        rescue_backlog_path = root / "rescue_backlog.json"
        next_refresh_path = root / "next_refresh.json"
        zero_signal_path = root / "zero_signal.json"
        target_stop_path = root / "target_stop.json"
        shadow_normalization_path = root / "shadow_normalization.json"
        broker_path = root / "broker.json"
        broker_shadow_repair_path = root / "broker_shadow_repair.json"
        broker_shadow_ab_prep_path = root / "broker_shadow_ab_prep.json"
        broker_rule_shadow_evidence_path = root / "broker_rule_shadow_evidence.json"
        config_path = root / "config.json"
        summary_path.write_text(
            json.dumps(
                {
                    "stage": "M14.strategy_challenge_paper_gate",
                    "trading_date": "2026-05-22",
                    "challenge_progress_label": "10/10",
                    "effective_challenge_trading_days": 10,
                    "required_challenge_trading_days": 10,
                    "data_quality_state": "history_recompute_from_existing_challenge",
                    "recompute_only": True,
                    "m12_current_day_runtime_ready": False,
                    "paper_simulated_only": True,
                    "internal_simulated_account": True,
                    "broker_paper_connection": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                }
            ),
            encoding="utf-8",
        )
        gate_path.write_text(
            json.dumps(
                {
                    "gate_scope": "internal_simulated_account_only",
                    "approved_internal_sim_strategy_ids": ["M10-PA-004"],
                    "paper_simulated_only": True,
                    "internal_simulated_account": True,
                    "broker_paper_connection": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "rows": [
                        self._gate_row("M10-PA-004", "approved_internal_sim_only", "promote"),
                        self._gate_row("M10-PA-001", "not_approved_modify_candidate", "modify"),
                        self._gate_row("M10-PA-011", "not_approved_rejected", "reject"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        rescue_plan_path.write_text(
            json.dumps(
                {
                    "external_references": [
                        {
                            "project": "example",
                            "url": "https://example.test/project",
                            "usable_pattern": "shadow diagnostics",
                            "boundary": "local gates only",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        rescue_coverage_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "connected_rescue_strategy_count": 2,
                    "registered_rescue_strategy_count": 2,
                    "registered_rescue_account_count": 2,
                    "planned_action_covered_count": 2,
                    "planned_action_row_count": 2,
                    "all_registered_rescue_inputs_connected": True,
                    "all_planned_rescue_actions_have_runtime_coverage": True,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "pending_rescue_strategy_ids": [],
                    "pending_planned_action_strategy_ids": [],
                    "next_required_evidence": "10 trading-day A/B ledger evidence",
                    "planned_action_rows": [
                        {
                            "strategy_id": "M10-PA-001",
                            "coverage_status": "covered_by_rescue_runtime",
                            "coverage_strategy_ids": ["M10-PA-001-m14-modify-20260522"],
                        },
                        {
                            "strategy_id": "M10-PA-011",
                            "coverage_status": "covered_by_rescue_runtime",
                            "coverage_strategy_ids": ["M10-PA-011-ORB-R1"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        rescue_ab_path.write_text(
            json.dumps(
                {
                    "min_ab_trading_days": 10,
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "summary": {
                        "rescue_runtime_strategy_count": 2,
                        "m13_ledger_observed_strategy_count": 2,
                        "collecting_evidence_count": 2,
                        "evidence_ready_for_manual_review_count": 0,
                        "no_m13_ledger_evidence_count": 0,
                        "promotion_allowed_count": 0,
                        "pending_evidence_strategy_ids": [
                            "M10-PA-001-m14-modify-20260522",
                            "M10-PA-011-ORB-R1",
                        ],
                        "no_m13_ledger_evidence_strategy_ids": [],
                        "evidence_ready_for_manual_review_strategy_ids": [],
                    },
                    "plain_language_result": "fixture rescue A/B evidence summary",
                }
            ),
            encoding="utf-8",
        )
        rescue_backlog_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "summary": {
                        "rescue_strategy_count": 2,
                        "actionable_before_10d_count": 2,
                        "wait_for_more_ab_evidence_count": 0,
                        "zero_signal_after_connection_count": 1,
                        "signal_generated_no_account_operation_count": 1,
                        "broker_dry_run_blocked_count": 1,
                        "broker_blocker_strategy_count": 1,
                        "high_priority_strategy_ids": [
                            "M10-PA-001-m14-modify-20260522",
                            "M10-PA-011-ORB-R1",
                        ],
                        "broker_blocker_reason_counts": {
                            "max_total_exposure_exceeded": 1
                        },
                    },
                    "plain_language_result": "fixture rescue optimization backlog",
                }
            ),
            encoding="utf-8",
        )
        next_refresh_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "readiness_status_mutation": False,
                    "m13_registry_mutation": False,
                    "m12_account_specs_mutation": False,
                    "broker_readiness_status_mutation": False,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "summary": {
                        "source_rescue_backlog_rows": 2,
                        "watch_rows": 4,
                        "fresh_quote_recheck_count": 1,
                        "first_ledger_watch_count": 1,
                        "broker_rule_shadow_watch_count": 2,
                        "target_stop_shadow_compare_count": 0,
                        "parent_detector_wait_count": 0,
                        "next_refresh_dependent_count": 4,
                        "parameter_change_allowed_now_count": 0,
                        "ready_for_next_m12_47_refresh_count": 4,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                        "broker_or_live_enabled": False,
                        "readiness_family_counts": {
                            "broker_rule_shadow_recheck": 2,
                            "first_rescue_ledger_watch": 1,
                            "fresh_quote_recheck": 1,
                        },
                        "readiness_state_counts": {
                            "ready_for_next_m12_47_refresh": 4,
                        },
                    },
                    "plain_language_result": "fixture rescue next refresh readiness",
                }
            ),
            encoding="utf-8",
        )
        zero_signal_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "summary": {
                        "zero_signal_runtime_count": 2,
                        "zero_signal_strategy_count": 2,
                        "parent_source_available_runtime_count": 2,
                        "parent_source_absent_runtime_count": 0,
                        "quote_refresh_candidate_runtime_count": 1,
                        "quality_filter_blocked_runtime_count": 1,
                        "potential_signal_if_fresh_quote_count": 3,
                        "dominant_issue_counts": {
                            "stale_quote_source_blocks_candidate": 1,
                            "reward_filter_blocks_all": 1,
                        },
                        "rejection_reason_counts": {
                            "stale_quote_source": 3,
                            "reward_r_below_min": 1,
                        },
                    },
                    "plain_language_result": "fixture zero-signal diagnostics",
                }
            ),
            encoding="utf-8",
        )
        target_stop_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "summary": {
                        "diagnosed_runtime_count": 1,
                        "target_stop_issue_runtime_count": 1,
                        "shadow_candidate_runtime_count": 0,
                        "reward_ge_1_0_runtime_count": 0,
                        "reward_ge_1_1_runtime_count": 0,
                        "reward_ge_1_2_runtime_count": 0,
                        "runtime_ids": ["M10-PA-012-m14-modify-20260522-5m"],
                        "strategy_ids": ["M10-PA-012-m14-modify-20260522"],
                        "parent_strategy_ids": ["M10-PA-012"],
                        "dominant_target_stop_issue_counts": {
                            "target_reward_below_1r_after_quality_gates": 1
                        },
                    },
                    "plain_language_result": "fixture target/stop diagnostics",
                }
            ),
            encoding="utf-8",
        )
        shadow_normalization_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "summary": {
                        "diagnosed_runtime_count": 1,
                        "runtime_with_shadow_candidate_count": 1,
                        "runtime_without_shadow_candidate_count": 0,
                        "source_candidate_row_count": 2,
                        "best_variant_candidate_row_count": 2,
                        "best_variant_id_counts": {"risk_normalized_1_0r": 1},
                        "runtime_ids": ["M10-PA-012-m14-modify-20260522-5m"],
                        "strategy_ids": ["M10-PA-012-m14-modify-20260522"],
                        "parent_strategy_ids": ["M10-PA-012"],
                        "opening_range_minutes": 30,
                    },
                    "plain_language_result": "fixture target/stop shadow normalization",
                }
            ),
            encoding="utf-8",
        )
        broker_path.write_text(
            json.dumps(
                {
                    "mode": "paper_dry_run_only",
                    "dry_run_ready_count": 1,
                    "blocked_count": 1,
                    "source_risk_check_count": 2,
                    "broker_connection_enabled": False,
                    "real_order_enabled": False,
                    "live_execution_enabled": False,
                    "paper_trading_approval": False,
                }
            ),
            encoding="utf-8",
        )
        broker_shadow_repair_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "readiness_status_mutation": False,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "summary": {
                        "source_blocked_rows": 3,
                        "shadow_rows": 3,
                        "strategy_count": 2,
                        "risk_cap_candidate_count": 1,
                        "defer_for_exposure_count": 1,
                        "cooldown_defer_count": 1,
                        "would_change_original_readiness_count": 0,
                        "broker_or_live_enabled": False,
                        "shadow_action_counts": {
                            "apply_quantity_cap": 1,
                            "defer_until_exposure_frees": 1,
                            "keep_loss_streak_halt": 1,
                        },
                        "shadow_status_counts": {
                            "defer_not_repair": 2,
                            "shadow_repair_candidate": 1,
                        },
                    },
                    "plain_language_result": "fixture broker blocker shadow repair",
                }
            ),
            encoding="utf-8",
        )
        broker_shadow_ab_prep_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "readiness_status_mutation": False,
                    "m13_registry_mutation": False,
                    "m12_account_specs_mutation": False,
                    "broker_readiness_status_mutation": False,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "summary": {
                        "source_shadow_repair_rows": 3,
                        "ab_prep_rows": 3,
                        "strategy_count": 2,
                        "risk_cap_runtime_candidate_count": 1,
                        "exposure_ranker_rule_candidate_count": 1,
                        "cooldown_quality_rule_candidate_count": 1,
                        "runtime_registration_candidate_count": 1,
                        "rule_only_candidate_count": 2,
                        "original_blocked_rows_preserved_count": 3,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                        "broker_or_live_enabled": False,
                        "prep_action_counts": {
                            "prepare_quantity_cap_shadow_runtime": 1,
                            "prepare_exposure_ranker_shadow_rule": 1,
                            "prepare_cooldown_quality_veto_shadow_rule": 1,
                        },
                        "prep_status_counts": {
                            "ready_for_shadow_runtime_design": 1,
                            "rule_only_prep_not_runtime": 2,
                        },
                    },
                    "plain_language_result": "fixture broker blocker shadow A/B prep",
                }
            ),
            encoding="utf-8",
        )
        broker_rule_shadow_evidence_path.write_text(
            json.dumps(
                {
                    "broker_connection": False,
                    "real_order": False,
                    "live_execution": False,
                    "paper_trading_approval": False,
                    "readiness_status_mutation": False,
                    "runtime_registration_mutation": False,
                    "m13_registry_mutation": False,
                    "m12_account_specs_mutation": False,
                    "broker_readiness_status_mutation": False,
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                    },
                    "summary": {
                        "source_ab_prep_rows": 3,
                        "source_runtime_candidate_rows": 1,
                        "rule_shadow_evidence_rows": 2,
                        "strategy_count": 1,
                        "rule_only_candidate_count": 2,
                        "exposure_ranker_rule_count": 1,
                        "cooldown_quality_rule_count": 1,
                        "ready_for_next_internal_sim_refresh_count": 2,
                        "runtime_registration_count": 0,
                        "original_blocked_rows_preserved_count": 2,
                        "m13_registry_mutation_count": 0,
                        "m12_account_specs_mutation_count": 0,
                        "broker_readiness_status_mutation_count": 0,
                        "broker_or_live_enabled": False,
                        "rule_family_counts": {
                            "cooldown_quality_veto": 1,
                            "portfolio_exposure_ranker": 1,
                        },
                        "shadow_evidence_status_counts": {
                            "ready_for_next_internal_sim_refresh": 2,
                        },
                    },
                    "plain_language_result": "fixture broker blocker rule shadow evidence",
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.goal-readiness-report.config.v1",
                    "stage": "M14.goal_readiness_report",
                    "project_stage_label": "M14 test",
                    "inputs": {
                        "m14_summary": str(summary_path),
                        "m14_paper_trial_gate": str(gate_path),
                        "m14_strategy_rescue_plan": str(rescue_plan_path),
                        "m14_rescue_runtime_coverage": str(rescue_coverage_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_ab_path),
                        "m14_rescue_optimization_backlog": str(rescue_backlog_path),
                        "m14_rescue_next_refresh_readiness": str(next_refresh_path),
                        "m14_rescue_zero_signal_diagnostics": str(zero_signal_path),
                        "m14_rescue_target_stop_diagnostics": str(target_stop_path),
                        "m14_rescue_target_stop_shadow_normalization": str(shadow_normalization_path),
                        "m14_2_broker_readiness_plan": str(broker_path),
                        "m14_2_broker_blocker_shadow_repair": str(broker_shadow_repair_path),
                        "m14_2_broker_blocker_shadow_ab_prep": str(broker_shadow_ab_prep_path),
                        "m14_2_broker_blocker_rule_shadow_evidence": str(broker_rule_shadow_evidence_path),
                    },
                    "outputs": {
                        "readiness_json": str(root / "readiness.json"),
                        "readiness_md": str(root / "readiness.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "internal_simulated_account": True,
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

    def _gate_row(self, strategy_id: str, gate: str, decision: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "display_name": strategy_id,
            "completed_trading_days": 10,
            "decision": decision,
            "decision_reason": "fixture",
            "paper_trial_gate": gate,
            "runtime_ids": [f"{strategy_id}-1d"],
            "broker_paper_connection": False,
            "real_money_actions": False,
            "live_execution": False,
            "paper_trading_approval": False,
        }


if __name__ == "__main__":
    unittest.main()
