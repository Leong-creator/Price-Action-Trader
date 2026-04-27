from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts import m12_core_daily_observation_lib as MODULE


OUTPUT_DIR = MODULE.M12_2_DIR


class M12CoreDailyObservationTests(unittest.TestCase):
    def test_config_boundaries_and_tier_a_scope_are_locked(self) -> None:
        config = MODULE.load_daily_observation_config()
        MODULE.validate_config_boundaries(config)
        queue = MODULE.build_tier_a_queue(MODULE.load_json(config.observation_queue_path), MODULE.load_json(config.paper_gate_candidate_path))

        self.assertEqual(tuple(queue), MODULE.TIER_A_STRATEGY_IDS)
        self.assertNotIn("M10-PA-008", queue)
        self.assertNotIn("M10-PA-009", queue)
        self.assertEqual(queue["M10-PA-012"]["timeframes"], ["15m", "5m"])

    def test_generated_events_use_m12_1_feed_and_do_not_fabricate_triggers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(MODULE.load_daily_observation_config(), output_dir=Path(tmp))
            status = MODULE.run_m12_core_daily_observation(config, generated_at="2026-04-27T12:00:00Z")
            events = [json.loads(line) for line in (Path(tmp) / "m12_2_observation_events.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(status["tier_a_strategy_ids"], list(MODULE.TIER_A_STRATEGY_IDS))
        self.assertEqual(status["event_count"], 32)
        self.assertEqual(status["candidate_event_count"], 0)
        self.assertEqual(status["skip_no_trade_count"], 32)
        self.assertTrue(events)
        for event in events:
            self.assertEqual(event["stage"], "M12.2.core_strategy_daily_observation")
            self.assertEqual(event["event_or_skip"]["kind"], "skip_no_trade")
            self.assertEqual(event["hypothetical_trade"]["direction"], "none")
            self.assertIsNone(event["hypothetical_trade"]["entry_price"])
            self.assertTrue(event["source_refs"])
            self.assertIn("backtest_specs", event["spec_ref"])

    def test_timeframe_selection_uses_m10_13_primary_queue_not_raw_feed_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(MODULE.load_daily_observation_config(), output_dir=Path(tmp))
            MODULE.run_m12_core_daily_observation(config, generated_at="2026-04-27T12:00:00Z")
            events = [json.loads(line) for line in (Path(tmp) / "m12_2_observation_events.jsonl").read_text(encoding="utf-8").splitlines()]

        observed = {(event["strategy_id"], event["timeframe"]) for event in events}
        self.assertNotIn(("M10-PA-001", "1h"), observed)
        self.assertNotIn(("M10-PA-002", "5m"), observed)
        self.assertNotIn(("M10-PA-012", "1d"), observed)
        self.assertNotIn(("M10-PA-012", "1h"), observed)
        self.assertIn(("M10-PA-001", "1d"), observed)
        self.assertIn(("M10-PA-002", "1h"), observed)
        self.assertIn(("M10-PA-012", "5m"), observed)

    def test_generated_outputs_keep_no_live_or_execution_account_claims(self) -> None:
        self.assertTrue(OUTPUT_DIR.exists(), "Run scripts/run_m12_core_daily_observation.py before full validation")
        combined = "\n".join(path.read_text(encoding="utf-8") for path in OUTPUT_DIR.glob("m12_2_*") if path.is_file())
        lowered = combined.lower()
        for forbidden in ("PA-SC-", "SF-", "live-ready", "order_id", "fill_price", "position", "cash", "pnl"):
            self.assertNotIn(forbidden.lower(), lowered)
        self.assertIn('"broker_connection": false', lowered)
        self.assertIn('"real_orders": false', lowered)
        self.assertIn('"live_execution": false', lowered)


if __name__ == "__main__":
    unittest.main()
