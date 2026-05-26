from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_post_refresh_outcome_review_lib import (
    load_config,
    run_m14_rescue_post_refresh_outcome_review,
)


class M14RescuePostRefreshOutcomeReviewTest(unittest.TestCase):
    def test_reviews_passed_watch_rows_after_fresh_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root, fresh=True)

            result = run_m14_rescue_post_refresh_outcome_review(
                load_config(config_path),
                generated_at="2026-05-26T17:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-post-refresh-outcome-review.v1")
            self.assertTrue(result["summary"]["fresh_refresh_observed"])
            self.assertEqual(result["summary"]["watch_rows"], 5)
            self.assertEqual(result["summary"]["passed_count"], 5)
            self.assertEqual(result["summary"]["waiting_count"], 0)
            self.assertEqual(result["summary"]["failed_count"], 0)
            self.assertEqual(result["summary"]["first_ledger_passed_count"], 1)
            self.assertEqual(result["summary"]["fresh_quote_recheck_passed_count"], 1)
            self.assertEqual(result["summary"]["broker_rule_evidence_observed_count"], 1)
            self.assertEqual(result["summary"]["target_stop_shadow_passed_count"], 1)
            self.assertEqual(result["summary"]["parent_detector_passed_count"], 1)
            self.assertFalse(result["summary"]["manual_m12_37_once_allowed"])
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])
            self.assertFalse(result["manual_m12_37_once"])

            rows = {row["readiness_family"]: row for row in result["rows"]}
            self.assertEqual(rows["first_rescue_ledger_watch"]["outcome_status"], "passed")
            self.assertEqual(rows["fresh_quote_recheck"]["outcome_status"], "passed")
            self.assertEqual(rows["broker_rule_shadow_recheck"]["outcome_status"], "evidence_observed")
            self.assertEqual(rows["target_stop_shadow_compare"]["outcome_status"], "passed")
            self.assertEqual(rows["parent_detector_evidence_wait"]["outcome_status"], "passed")

            persisted = json.loads((root / "outcome.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"], result["summary"])
            md = (root / "outcome.md").read_text(encoding="utf-8")
            self.assertIn("M14 Rescue Post-Refresh Outcome Review", md)
            self.assertIn("Manual M12.37 once-mode allowed: `False`", md)

    def test_waits_when_dashboard_is_not_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root, fresh=False)

            result = run_m14_rescue_post_refresh_outcome_review(
                load_config(config_path),
                generated_at="2026-05-26T17:10:00Z",
            )

            self.assertFalse(result["summary"]["fresh_refresh_observed"])
            self.assertEqual(result["summary"]["waiting_count"], 5)
            self.assertEqual(result["summary"]["passed_count"], 0)
            self.assertEqual(result["summary"]["failed_count"], 0)
            self.assertEqual(
                set(result["summary"]["outcome_status_counts"]),
                {"waiting_for_m12_47_fresh_refresh"},
            )

    def test_rejects_unsafe_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root, fresh=True)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["broker_connection"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "broker_connection"):
                load_config(config_path)

    def _write_fixture(self, root: Path, *, fresh: bool) -> Path:
        next_refresh_path = root / "next_refresh.json"
        rescue_ab_path = root / "rescue_ab.json"
        scorecard_path = root / "scorecard.json"
        signal_path = root / "signal.jsonl"
        account_path = root / "account.jsonl"
        dashboard_path = root / "dashboard.json"
        broker_path = root / "broker.json"
        config_path = root / "config.json"

        watch_rows = [
            self._watch_row("first_rescue_ledger_watch", "M10-PA-008-shadow", "M10-PA-008", "M10-PA-008-shadow-1d"),
            self._watch_row("fresh_quote_recheck", "M10-PA-001-shadow", "M10-PA-001", "M10-PA-001-shadow-1d"),
            self._watch_row("broker_rule_shadow_recheck", "M10-PA-005", "M10-PA-005", "M10-PA-005-5m", symbol="XLY"),
            self._watch_row("target_stop_shadow_compare", "M10-PA-012-shadow", "M10-PA-012", "M10-PA-012-shadow-5m"),
            self._watch_row("parent_detector_evidence_wait", "M10-PA-013-shadow", "M10-PA-013", "M10-PA-013-shadow-1d"),
        ]
        next_refresh_path.write_text(json.dumps({"rows": watch_rows}), encoding="utf-8")
        rescue_ab_path.write_text(json.dumps({"summary": {"promotion_allowed_count": 0}}), encoding="utf-8")
        scorecard_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {"strategy_id": "M10-PA-001-shadow", "test_states": "signal_generated", "signal_count": "1"},
                        {"strategy_id": "M10-PA-008-shadow", "test_states": "signal_generated", "signal_count": "1"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        signal_rows = [
            self._signal("M10-PA-008-shadow", "M10-PA-008-shadow-1d", "1d", 1),
            self._signal("M10-PA-001-shadow", "M10-PA-001-shadow-1d", "1d", 2),
            self._signal("M10-PA-012-shadow", "M10-PA-012-shadow-5m", "5m", 3),
            self._signal("M10-PA-013", "M10-PA-013-1d", "1d", 4),
        ]
        signal_path.write_text("\n".join(json.dumps(row) for row in signal_rows) + "\n", encoding="utf-8")
        account_path.write_text(
            json.dumps(
                {
                    "strategy_id": "M10-PA-008-shadow",
                    "runtime_id": "M10-PA-008-shadow-1d",
                    "trading_date": "2026-05-26",
                    "event_type": "open",
                    "test_state": "open",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        dashboard_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "quote_source": "longbridge_quote_readonly" if fresh else "fallback_quotes_only",
                        "scan_date": "2026-05-26",
                        "current_day_runtime_ready": True,
                        "current_day_scan_complete": True,
                        "generated_at": "2026-05-26T21:45:00Z",
                        "market_session": {"status": "交易中", "new_york_date": "2026-05-26"},
                        "data_freshness_warning": "" if fresh else "fallback quotes",
                    }
                }
            ),
            encoding="utf-8",
        )
        broker_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "strategy_id": "M10-PA-005",
                            "runtime_id": "M10-PA-005-5m",
                            "symbol": "XLY",
                            "readiness_status": "blocked",
                            "source_risk_reason_codes": ["max_total_exposure_exceeded"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.rescue-post-refresh-outcome-review.config.v1",
                    "stage": "M14.rescue_post_refresh_outcome_review",
                    "inputs": {
                        "m14_rescue_next_refresh_readiness": str(next_refresh_path),
                        "m14_rescue_ab_evidence_tracker": str(rescue_ab_path),
                        "m13_daily_strategy_scorecard": str(scorecard_path),
                        "m13_strategy_signal_ledger": str(signal_path),
                        "m13_account_operation_ledger": str(account_path),
                        "m12_minute_dashboard_data": str(dashboard_path),
                        "m14_2_broker_readiness_plan": str(broker_path),
                    },
                    "outputs": {
                        "outcome_json": str(root / "outcome.json"),
                        "outcome_md": str(root / "outcome.md"),
                    },
                    "hard_boundaries": {
                        "paper_simulated_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                        "manual_m12_37_once": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _watch_row(
        self,
        family: str,
        strategy_id: str,
        parent_strategy_id: str,
        runtime_id: str,
        *,
        symbol: str = "",
    ) -> dict[str, object]:
        return {
            "row_id": f"{family}-{strategy_id}",
            "source_kind": "fixture",
            "strategy_id": strategy_id,
            "parent_strategy_id": parent_strategy_id,
            "runtime_id": runtime_id,
            "timeframe": runtime_id.rsplit("-", 1)[-1],
            "priority": "P0",
            "readiness_family": family,
            "readiness_state": "ready_for_next_m12_47_refresh",
            "expected_evidence_after_refresh": "fixture expected evidence",
            "pass_action": "fixture pass",
            "fail_action": "fixture fail",
            "source_metrics": {
                "m13_signal_ledger_row_count": 0,
                "m13_account_ledger_row_count": 0,
                "symbol": symbol,
            },
        }

    def _signal(self, strategy_id: str, runtime_id: str, timeframe: str, signal_count: int) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "runtime_id": runtime_id,
            "timeframe": timeframe,
            "trading_date": "2026-05-26",
            "signal_count": signal_count,
            "source_row_count": signal_count,
            "test_state": "signal_generated",
        }


if __name__ == "__main__":
    unittest.main()
