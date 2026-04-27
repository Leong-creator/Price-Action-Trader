from __future__ import annotations

import json
import unittest
from pathlib import Path


M10_DIR = Path("reports/strategy_lab/m10_price_action_strategy_refresh")
QUEUE_PATH = M10_DIR / "m10_5_observation_candidate_queue.json"
SCHEMA_PATH = M10_DIR / "m10_5_observation_event_schema.json"
QUALITY_REVIEW_PATH = M10_DIR / "m10_5_pilot_quality_review.md"
HANDOFF_PATH = M10_DIR / "m10_5_paper_gate_handoff.md"


class M10ReadOnlyObservationPlanTests(unittest.TestCase):
    def load_queue(self) -> dict:
        return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))

    def test_observation_queue_contains_wave_a_only(self) -> None:
        queue = self.load_queue()
        by_id = {item["strategy_id"]: item for item in queue["candidate_queue"]}

        self.assertEqual(set(by_id), {"M10-PA-001", "M10-PA-002", "M10-PA-005", "M10-PA-012"})
        self.assertEqual(by_id["M10-PA-001"]["timeframes"], ["1d", "1h", "15m", "5m"])
        self.assertEqual(by_id["M10-PA-002"]["timeframes"], ["1d", "1h", "15m", "5m"])
        self.assertEqual(by_id["M10-PA-005"]["timeframes"], ["1d", "1h", "15m", "5m"])
        self.assertEqual(by_id["M10-PA-012"]["timeframes"], ["15m", "5m"])

    def test_excluded_routes_do_not_enter_observation_queue(self) -> None:
        queue = self.load_queue()
        queued = {item["strategy_id"] for item in queue["candidate_queue"]}
        excluded = set()
        for ids in queue["excluded_strategy_ids"].values():
            excluded.update(ids)

        self.assertTrue({"M10-PA-003", "M10-PA-004", "M10-PA-007", "M10-PA-008", "M10-PA-009", "M10-PA-010", "M10-PA-011"}.issubset(excluded))
        self.assertTrue({"M10-PA-013", "M10-PA-014", "M10-PA-015", "M10-PA-006", "M10-PA-016"}.issubset(excluded))
        self.assertTrue(queued.isdisjoint(excluded))

    def test_schema_and_handoff_guardrails(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        handoff_text = HANDOFF_PATH.read_text(encoding="utf-8").lower()
        combined = json.dumps(schema, ensure_ascii=False).lower() + "\n" + handoff_text

        self.assertTrue(schema["properties"]["paper_simulated_only"]["const"])
        self.assertFalse(schema["properties"]["broker_connection"]["const"])
        self.assertFalse(schema["properties"]["real_orders"]["const"])
        self.assertFalse(schema["properties"]["live_execution"]["const"])
        self.assertIn("continue_observation", schema["properties"]["review_status"]["enum"])
        for forbidden in ("PA-SC-", "SF-", "retain", "promote", "live-ready", "broker_connection=true", "real_orders=true"):
            self.assertNotIn(forbidden.lower(), combined)

    def test_inventory_window_and_lineage_are_referenced(self) -> None:
        queue = self.load_queue()
        review_text = QUALITY_REVIEW_PATH.read_text(encoding="utf-8")

        self.assertEqual(queue["lineage_requirements"]["daily_default_window"], {"start": "2010-06-29", "end": "2026-04-21", "source": "m10_4_dataset_inventory.json"})
        self.assertEqual(queue["lineage_requirements"]["derived_timeframes"], {"15m": "derived_from_5m", "1h": "derived_from_5m"})
        self.assertIn("2010-06-29 ~ 2026-04-21", review_text)
        self.assertIn("derived_from_5m", review_text)

    def test_pilot_quality_review_denies_profitability_claim_and_flags_density(self) -> None:
        queue = self.load_queue()
        review_text = QUALITY_REVIEW_PATH.read_text(encoding="utf-8")
        flags = {
            (item["strategy_id"], result["timeframe"], result["quality_flag"])
            for item in queue["candidate_queue"]
            for result in item["m10_4_results"]
        }

        self.assertIn("M10.4 不证明盈利", review_text)
        self.assertIn(("M10-PA-005", "1h", "definition_breadth_review"), flags)
        self.assertIn(("M10-PA-005", "15m", "definition_breadth_review"), flags)
        self.assertIn(("M10-PA-005", "5m", "definition_breadth_review"), flags)


if __name__ == "__main__":
    unittest.main()
