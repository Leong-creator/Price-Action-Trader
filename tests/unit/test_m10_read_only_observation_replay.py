from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from scripts.m10_historical_pilot_lib import CandidateEvent
from scripts.m10_read_only_observation_lib import (
    OBSERVATION_STRATEGY_IDS,
    build_candidate_observation_event,
    load_json,
    load_observation_config,
    load_observation_queue,
    run_m10_read_only_observation,
    validate_observation_event,
)
from scripts.m10_historical_pilot_lib import DatasetRecord


M10_DIR = Path("reports/strategy_lab/m10_price_action_strategy_refresh")
OUTPUT_DIR = M10_DIR / "read_only_observation" / "m10_6_replay"


class M10ReadOnlyObservationReplayTests(unittest.TestCase):
    def test_config_and_queue_scope_are_locked(self) -> None:
        config = load_observation_config()
        queue = load_observation_queue(config.observation_queue_path)

        self.assertEqual([item["strategy_id"] for item in queue["candidate_queue"]], list(OBSERVATION_STRATEGY_IDS))
        by_id = {item["strategy_id"]: item["timeframes"] for item in queue["candidate_queue"]}
        self.assertEqual(by_id["M10-PA-012"], ["15m", "5m"])
        self.assertEqual(by_id["M10-PA-001"], ["1d", "1h", "15m", "5m"])
        self.assertIn(Path("/home/hgl/projects/Price-Action-Trader/local_data"), config.cache_roots)
        self.assertTrue(config.recorded_replay_only)

    def test_event_shape_conforms_to_m10_5_schema(self) -> None:
        schema = load_json(M10_DIR / "m10_5_observation_event_schema.json")
        spec = load_json(M10_DIR / "backtest_specs" / "M10-PA-001.json")
        event = CandidateEvent(
            strategy_id="M10-PA-001",
            symbol="SPY",
            timeframe="5m",
            direction="long",
            signal_index=10,
            entry_index=11,
            signal_timestamp=datetime.fromisoformat("2024-04-01T10:20:00-04:00"),
            entry_timestamp=datetime.fromisoformat("2024-04-01T10:25:00-04:00"),
            entry_price=Decimal("100.50"),
            stop_price=Decimal("99.50"),
            target_price=Decimal("102.50"),
            risk_per_share=Decimal("1.00"),
            setup_notes="trend_pullback_second_entry",
        )
        record = DatasetRecord(
            symbol="SPY",
            timeframe="5m",
            status="available",
            csv_path=Path("/tmp/us_SPY_5m_2024-04-01_2026-04-21_longbridge.csv"),
            source="longbridge",
            lineage="native_cache",
            requested_start=datetime.fromisoformat("2024-04-01T00:00:00").date(),
            requested_end=datetime.fromisoformat("2026-04-21T00:00:00").date(),
            actual_start="2024-04-01T09:30:00-04:00",
            actual_end="2026-04-21T15:55:00-04:00",
            row_count=100,
            checksum_sha256="abc",
        )

        row = build_candidate_observation_event(
            event=event,
            spec=spec,
            spec_ref="reports/strategy_lab/m10_price_action_strategy_refresh/backtest_specs/M10-PA-001.json",
            record=record,
            quality_flag="normal_density_review",
            schema=schema,
        )
        validate_observation_event(row, schema)

        self.assertTrue(row["paper_simulated_only"])
        self.assertFalse(row["broker_connection"])
        self.assertFalse(row["real_orders"])
        self.assertFalse(row["live_execution"])
        self.assertEqual(row["review_status"], "continue_observation")

    def test_missing_data_writes_deferred_without_fake_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = replace(
                load_observation_config(),
                symbols=("SPY",),
                cache_roots=(Path(tmp) / "missing_cache",),
                output_dir=Path(tmp) / "m10_6",
            )

            summary = run_m10_read_only_observation(config)
            ledger_path = config.output_dir / "m10_6_observation_ledger.jsonl"
            deferred_path = config.output_dir / "m10_6_deferred_inputs.json"

            self.assertEqual(summary["event_count"], 0)
            self.assertGreater(summary["deferred_input_count"], 0)
            self.assertEqual(ledger_path.read_text(encoding="utf-8"), "\n")
            deferred = json.loads(deferred_path.read_text(encoding="utf-8"))
            self.assertEqual(deferred["deferred_count"], summary["deferred_input_count"])

    def test_generated_artifacts_preserve_lineage_and_boundaries(self) -> None:
        summary_path = OUTPUT_DIR / "m10_6_observation_summary.json"
        manifest_path = OUTPUT_DIR / "m10_6_input_manifest.json"
        ledger_path = OUTPUT_DIR / "m10_6_observation_ledger.jsonl"
        self.assertTrue(summary_path.exists(), "Run scripts/run_m10_read_only_observation.py before full validation")

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        first_event = json.loads(next(line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()))

        self.assertEqual(summary["queue_strategy_ids"], list(OBSERVATION_STRATEGY_IDS))
        self.assertEqual(summary["lineage_counts"]["derived_from_5m"], 8)
        self.assertEqual(summary["lineage_counts"]["native_cache"], 8)
        self.assertFalse(summary["broker_connection"])
        self.assertFalse(summary["live_execution"])
        self.assertFalse(summary["real_orders"])
        self.assertTrue(first_event["paper_simulated_only"])
        self.assertIn("derived_from_5m", json.dumps(manifest, ensure_ascii=False))

    def test_generated_outputs_do_not_contain_legacy_or_execution_result_claims(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                OUTPUT_DIR / "m10_6_observation_ledger.jsonl",
                OUTPUT_DIR / "m10_6_observation_summary.json",
                OUTPUT_DIR / "m10_6_observation_report.md",
            ]
        )
        for forbidden in ("PA-SC-", "SF-", "retain", "promote", "live-ready", "order_id", "fill_price", "position", "cash", "pnl"):
            self.assertNotIn(forbidden.lower(), combined.lower())


if __name__ == "__main__":
    unittest.main()
