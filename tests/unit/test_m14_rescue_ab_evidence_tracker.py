from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m14_rescue_ab_evidence_tracker_lib import load_config, run_m14_rescue_ab_evidence_tracker


class M14RescueAbEvidenceTrackerTest(unittest.TestCase):
    def test_tracker_counts_rescue_variant_evidence_without_auto_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)

            result = run_m14_rescue_ab_evidence_tracker(
                load_config(config_path),
                generated_at="2026-05-26T14:00:00Z",
            )

            self.assertEqual(result["schema_version"], "m14.rescue-ab-evidence-tracker.v1")
            self.assertEqual(result["summary"]["rescue_runtime_strategy_count"], 3)
            self.assertEqual(result["summary"]["m13_ledger_observed_strategy_count"], 2)
            self.assertEqual(result["summary"]["no_m13_ledger_evidence_count"], 1)
            self.assertEqual(result["summary"]["collecting_evidence_count"], 1)
            self.assertEqual(result["summary"]["evidence_ready_for_manual_review_count"], 1)
            self.assertEqual(result["summary"]["promotion_allowed_count"], 0)
            self.assertFalse(result["broker_connection"])
            self.assertFalse(result["real_order"])
            self.assertFalse(result["live_execution"])
            self.assertFalse(result["paper_trading_approval"])

            rows = {row["strategy_id"]: row for row in result["rows"]}
            self.assertEqual(rows["M10-PA-001-m14-modify-20260522"]["observed_trading_days_count"], 2)
            self.assertEqual(rows["M10-PA-001-m14-modify-20260522"]["signal_count"], 3)
            self.assertEqual(rows["M10-PA-001-m14-modify-20260522"]["open_count"], 1)
            self.assertEqual(rows["M10-PA-001-m14-modify-20260522"]["evidence_status"], "collecting_ab_evidence")
            self.assertEqual(
                rows["M10-PA-001-m14-modify-20260522"]["promotion_blocked_reason"],
                "needs_10_trading_days_ab_evidence",
            )

            self.assertEqual(rows["M10-PA-002-m14-modify-20260522"]["observed_trading_days_count"], 10)
            self.assertEqual(rows["M10-PA-002-m14-modify-20260522"]["evidence_status"], "evidence_ready_for_manual_review")
            self.assertTrue(rows["M10-PA-002-m14-modify-20260522"]["ready_for_manual_review"])
            self.assertFalse(rows["M10-PA-002-m14-modify-20260522"]["can_promote"])
            self.assertEqual(
                rows["M10-PA-002-m14-modify-20260522"]["promotion_blocked_reason"],
                "manual_m14_review_and_metrics_gate_required",
            )

            self.assertEqual(rows["M10-PA-011-ORB-R1"]["evidence_status"], "no_m13_rescue_ledger_evidence_yet")
            self.assertEqual(rows["M10-PA-011-ORB-R1"]["promotion_blocked_reason"], "no_m13_rescue_ledger_rows_yet")

            self.assertEqual(rows["M10-PA-001-m14-modify-20260522"]["parent_strategy_evidence_counted"], False)
            self.assertEqual(rows["M10-PA-001-m14-modify-20260522"]["parent_paper_trial_gate"], "not_approved_modify_candidate")

            persisted = json.loads((root / "tracker.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"]["promotion_allowed_count"], 0)
            md = (root / "tracker.md").read_text(encoding="utf-8")
            self.assertIn("parent strategy evidence does not count", md)

    def test_tracker_does_not_count_parent_strategy_ledger_as_rescue_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            signal_path = root / "signal.jsonl"
            account_path = root / "account.jsonl"
            signal_rows = [json.loads(line) for line in signal_path.read_text(encoding="utf-8").splitlines() if line]
            account_rows = [json.loads(line) for line in account_path.read_text(encoding="utf-8").splitlines() if line]
            signal_rows = [row for row in signal_rows if row["strategy_id"] == "M10-PA-001"]
            account_rows = [row for row in account_rows if row["strategy_id"] == "M10-PA-001"]
            self._write_jsonl(signal_path, signal_rows)
            self._write_jsonl(account_path, account_rows)

            result = run_m14_rescue_ab_evidence_tracker(
                load_config(config_path),
                generated_at="2026-05-26T14:00:00Z",
            )

            rows = {row["strategy_id"]: row for row in result["rows"]}
            self.assertEqual(rows["M10-PA-001-m14-modify-20260522"]["observed_trading_days_count"], 0)
            self.assertEqual(rows["M10-PA-001-m14-modify-20260522"]["evidence_status"], "no_m13_rescue_ledger_evidence_yet")
            self.assertFalse(rows["M10-PA-001-m14-modify-20260522"]["can_promote"])

    def test_unsafe_config_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = self._write_fixture(root)
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            payload["hard_boundaries"]["real_order"] = True
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(config_path)

    def _write_fixture(self, root: Path) -> Path:
        coverage_path = root / "coverage.json"
        gate_path = root / "gate.json"
        scorecard_path = root / "scorecard.json"
        signal_path = root / "signal.jsonl"
        account_path = root / "account.jsonl"
        config_path = root / "config.json"
        coverage_path.write_text(
            json.dumps(
                {
                    "all_registered_rescue_inputs_connected": True,
                    "all_planned_rescue_actions_have_runtime_coverage": True,
                    "rows": [
                        self._coverage_row("M10-PA-001-m14-modify-20260522", "M10-PA-001", ["M10-PA-001-m14-modify-20260522-1d"]),
                        self._coverage_row("M10-PA-002-m14-modify-20260522", "M10-PA-002", ["M10-PA-002-m14-modify-20260522-1d"]),
                        self._coverage_row("M10-PA-011-ORB-R1", "M10-PA-011", ["M10-PA-011-ORB-R1-5m"]),
                    ],
                }
            ),
            encoding="utf-8",
        )
        gate_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {"strategy_id": "M10-PA-001", "decision": "modify", "paper_trial_gate": "not_approved_modify_candidate"},
                        {"strategy_id": "M10-PA-002", "decision": "modify", "paper_trial_gate": "not_approved_modify_candidate"},
                        {"strategy_id": "M10-PA-011", "decision": "reject", "paper_trial_gate": "not_approved_rejected"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        scorecard_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {"strategy_id": "M10-PA-001-m14-modify-20260522", "ledger_state_count": "2", "test_states": "signal_generated,zero_signal"},
                        {"strategy_id": "M10-PA-002-m14-modify-20260522", "ledger_state_count": "10", "test_states": "zero_signal"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        signal_rows = [
            self._signal_row("M10-PA-001", "M10-PA-001-1d", "2026-05-01", 5),
            self._signal_row("M10-PA-001-m14-modify-20260522", "M10-PA-001-m14-modify-20260522-1d", "2026-05-01", 3),
            self._signal_row("M10-PA-001-m14-modify-20260522", "M10-PA-001-m14-modify-20260522-1d", "2026-05-04", 0),
        ]
        account_rows = [
            self._account_row("M10-PA-001", "M10-PA-001-1d", "2026-05-01", "close"),
            self._account_row("M10-PA-001-m14-modify-20260522", "M10-PA-001-m14-modify-20260522-1d", "2026-05-01", "open"),
            self._account_row("M10-PA-001-m14-modify-20260522", "M10-PA-001-m14-modify-20260522-1d", "2026-05-04", "no_account_operation"),
        ]
        for day in range(1, 11):
            trading_date = f"2026-06-{day:02d}"
            signal_rows.append(self._signal_row("M10-PA-002-m14-modify-20260522", "M10-PA-002-m14-modify-20260522-1d", trading_date, 0))
            account_rows.append(
                self._account_row(
                    "M10-PA-002-m14-modify-20260522",
                    "M10-PA-002-m14-modify-20260522-1d",
                    trading_date,
                    "no_account_operation",
                )
            )
        self._write_jsonl(signal_path, signal_rows)
        self._write_jsonl(account_path, account_rows)
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": "m14.rescue-ab-evidence-tracker.config.v1",
                    "stage": "M14.rescue_ab_evidence_tracker",
                    "min_ab_trading_days": 10,
                    "inputs": {
                        "m14_rescue_runtime_coverage": str(coverage_path),
                        "m14_paper_trial_gate": str(gate_path),
                        "m13_daily_strategy_scorecard": str(scorecard_path),
                        "m13_strategy_signal_ledger": str(signal_path),
                        "m13_account_operation_ledger": str(account_path),
                    },
                    "outputs": {
                        "tracker_json": str(root / "tracker.json"),
                        "tracker_md": str(root / "tracker.md"),
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

    def _coverage_row(self, strategy_id: str, parent_strategy_id: str, runtime_ids: list[str]) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "parent_strategy_id": parent_strategy_id,
            "coverage_status": "connected_not_promoted",
            "runtime_ids": runtime_ids,
            "timeframes": ["1d"],
            "variant_ids": ["m14_modify_20260522"],
        }

    def _signal_row(self, strategy_id: str, runtime_id: str, trading_date: str, signal_count: int) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "runtime_id": runtime_id,
            "trading_date": trading_date,
            "test_state": "signal_generated" if signal_count else "zero_signal",
            "signal_count": signal_count,
            "source_row_count": signal_count + 1,
        }

    def _account_row(self, strategy_id: str, runtime_id: str, trading_date: str, event_type: str) -> dict[str, object]:
        return {
            "strategy_id": strategy_id,
            "runtime_id": runtime_id,
            "trading_date": trading_date,
            "event_type": event_type,
            "test_state": event_type if event_type in {"open", "close", "risk_blocked"} else "zero_signal",
        }

    def _write_jsonl(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
