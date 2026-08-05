from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.m15_visual_strategy_acceptance_lib import (
    generate_acceptance_evidence,
    load_acceptance_config,
)
from scripts.m15_visual_strategy_shadow_lib import ShadowConfig, run_visual_strategy_shadow


class M15VisualStrategyAcceptanceTest(unittest.TestCase):
    def bar(
        self,
        symbol: str,
        day: int,
        open_price: str,
        high: str,
        low: str,
        close: str,
        volume: str,
    ) -> dict[str, str]:
        return {
            "symbol": symbol,
            "market": "US",
            "timeframe": "1d",
            "event_time": f"2026-01-{day:02d}T05:00:00Z",
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }

    def make_shadow_config(self, root: Path) -> ShadowConfig:
        return ShadowConfig(
            input_path=root / "bars.jsonl",
            state_path=root / "state.json",
            audit_path=root / "audit.jsonl",
            summary_path=root / "summary.json",
            channel_lookback=4,
            channel_tolerance=Decimal("0.10"),
            trend_short_window=2,
            trend_long_window=4,
            history_limit=16,
        )

    def write_jsonl(self, path: Path, rows: list[dict[str, str]]) -> None:
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def write_acceptance_config(self, root: Path, *, expected_symbol_count: int = 2) -> Path:
        path = root / "acceptance_config.json"
        payload = {
            "inputs": {
                "shadow_config": str(root / "shadow_config.json"),
                "shadow_run_summary": str(root / "summary.json"),
                "shadow_state": str(root / "state.json"),
                "shadow_audit_jsonl": str(root / "audit.jsonl"),
                "historical_replay_bars": str(root / "historical_replay_bars.jsonl"),
                "realtime_shadow_ledger": str(root / "realtime_shadow_ledger.jsonl"),
            },
            "outputs": {"acceptance_json": str(root / "acceptance.json")},
            "hard_boundaries": {
                "order_generation": False,
                "broker_connection": False,
                "real_orders": False,
                "live_execution": False,
            },
            "proofs": {
                "expected_symbol_count": expected_symbol_count,
                "expected_bars_per_symbol": 6,
                "segmented_chunk_size": 2,
                "negative_horizon_bars": 2,
                "realtime_shadow_sessions": 0,
            },
            "example_limits": {
                "positive_examples": 2,
                "negative_examples": 2,
                "boundary_examples": 1,
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_shadow_config(self, root: Path) -> None:
        payload = {
            "contract": {"stage": "shadow-v1"},
            "inputs": {"bars": str(root / "bars.jsonl")},
            "state": {"path": str(root / "state.json"), "history_limit": 16},
            "outputs": {
                "audit_jsonl": str(root / "audit.jsonl"),
                "run_summary": str(root / "summary.json"),
                "acceptance_json": str(root / "acceptance.json"),
            },
            "detector": {
                "channel_lookback": 4,
                "channel_tolerance": "0.10",
                "trend_short_window": 2,
                "trend_long_window": 4,
            },
            "hard_boundaries": {
                "broker_connection": False,
                "real_orders": False,
                "order_generation": False,
                "live_execution": False,
            },
        }
        (root / "shadow_config.json").write_text(json.dumps(payload), encoding="utf-8")

    def write_ledger(self, root: Path, rows: list[dict[str, object]]) -> None:
        (root / "realtime_shadow_ledger.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_acceptance_generation_keeps_reviewed_counts_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars = [
                self.bar("AAA", 1, "10", "11", "9", "10", "100"),
                self.bar("AAA", 2, "10", "11", "9.8", "10.8", "100"),
                self.bar("AAA", 3, "10.8", "11.2", "9.1", "9.7", "100"),
                self.bar("AAA", 4, "9.8", "10.2", "9.0", "9.1", "100"),
                self.bar("AAA", 5, "9.0", "10.6", "8.9", "10.5", "100"),
                self.bar("AAA", 6, "10.5", "10.8", "10.2", "10.7", "250"),
                self.bar("BBB", 1, "20", "21", "19", "20", "100"),
                self.bar("BBB", 2, "20", "22", "20", "21.8", "100"),
                self.bar("BBB", 3, "21.6", "23", "21.5", "22.9", "100"),
                self.bar("BBB", 4, "23.5", "24.0", "23.0", "23.9", "350"),
                self.bar("BBB", 5, "24.8", "25.2", "24.4", "24.9", "100"),
                self.bar("BBB", 6, "25.0", "25.1", "24.2", "24.3", "100"),
            ]
            self.write_jsonl(root / "bars.jsonl", bars)
            self.write_shadow_config(root)
            self.write_ledger(
                root,
                [
                    {
                        "schema_version": "m15.visual-strategy-shadow-session.v1",
                        "business_date": "2026-08-01",
                        "status": "completed",
                        "session_complete": True,
                        "required_symbol_count": 2,
                        "complete_symbol_count": 2,
                        "mode": "read_only_sdk_session_shadow",
                        "source_mode": "longbridge_sdk_rth_5m_aggregate",
                    },
                    {
                        "schema_version": "m15.visual-strategy-shadow-session.v1",
                        "business_date": "2026-08-01",
                        "status": "completed",
                        "session_complete": True,
                        "required_symbol_count": 2,
                        "complete_symbol_count": 2,
                        "mode": "read_only_sdk_session_shadow",
                        "source_mode": "longbridge_sdk_rth_5m_aggregate",
                    },
                    {
                        "business_date": "2026-08-02",
                        "status": "running",
                        "session_complete": False,
                        "required_symbol_count": 300,
                        "complete_symbol_count": 299,
                        "source_mode": "readonly_shadow",
                    },
                    {
                        "schema_version": "m15.visual-strategy-shadow-session.v1",
                        "business_date": "2026-08-03",
                        "status": "completed",
                        "session_complete": True,
                        "required_symbol_count": 300,
                        "complete_symbol_count": 300,
                        "mode": "read_only_sdk_session_shadow",
                        "source_mode": "historical_replay",
                    },
                ],
            )
            shadow_config = self.make_shadow_config(root)
            run_visual_strategy_shadow(shadow_config, bars=bars, generated_at="2026-08-05T11:20:00Z")
            acceptance_config_path = self.write_acceptance_config(root)

            evidence = generate_acceptance_evidence(
                load_acceptance_config(acceptance_config_path),
                generated_at="2026-08-05T11:30:00Z",
            )

        self.assertEqual(evidence["hard_boundaries"]["order_generation"], False)
        self.assertEqual(evidence["hard_boundaries"]["broker_connection"], False)
        self.assertTrue(evidence["replay_proofs"]["historical_replay_symbol_count"]["passed"])
        self.assertTrue(evidence["replay_proofs"]["no_future_data"]["passed"])
        self.assertTrue(evidence["replay_proofs"]["restart_parity"]["passed"])
        self.assertEqual(evidence["realtime_shadow_ledger_summary"]["completed_unique_business_dates"], 1)
        for strategy in ("PA004", "PA007", "PA008"):
            self.assertEqual(evidence[strategy]["positive_examples"], 0)
            self.assertEqual(evidence[strategy]["negative_examples"], 0)
            self.assertEqual(evidence[strategy]["boundary_examples"], 0)
            self.assertEqual(evidence[strategy]["reviewed_counts"]["positive_examples"], 0)
            self.assertEqual(evidence[strategy]["human_review_passed_counts"]["positive_examples"], 0)
            self.assertEqual(evidence[strategy]["realtime_shadow_sessions"], 1)

    def test_acceptance_output_is_written_and_build_promotion_fields_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars = [self.bar("AAA", day, "10", "11", "9", str(10 + day / 10), "100") for day in range(1, 7)]
            bars += [self.bar("BBB", day, "20", "21", "19", str(20 + day / 10), "100") for day in range(1, 7)]
            self.write_jsonl(root / "bars.jsonl", bars)
            self.write_shadow_config(root)
            self.write_ledger(root, [])
            shadow_config = self.make_shadow_config(root)
            run_visual_strategy_shadow(shadow_config, bars=bars, generated_at="2026-08-05T11:20:00Z")
            acceptance_config_path = self.write_acceptance_config(root)

            config = load_acceptance_config(acceptance_config_path)
            generate_acceptance_evidence(config, generated_at="2026-08-05T11:30:00Z")
            written = json.loads(config.output_path.read_text(encoding="utf-8"))

        self.assertIn("PA004", written)
        self.assertIn("positive_examples", written["PA004"])
        self.assertIn("historical_replay_symbol_count", written["PA004"])
        self.assertIn("candidate_examples", written["PA004"])
        self.assertEqual(written["PA004"]["realtime_shadow_sessions"], 0)

    def test_historical_replay_requires_every_symbol_bar_and_audit_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars = [self.bar("AAA", day, "10", "11", "9", "10", "100") for day in range(1, 7)]
            bars += [self.bar("BBB", day, "20", "21", "19", "20", "100") for day in range(1, 6)]
            self.write_jsonl(root / "bars.jsonl", bars)
            self.write_shadow_config(root)
            self.write_ledger(root, [])
            shadow_config = self.make_shadow_config(root)
            run_visual_strategy_shadow(shadow_config, bars=bars, generated_at="2026-08-05T11:20:00Z")

            evidence = generate_acceptance_evidence(
                load_acceptance_config(self.write_acceptance_config(root)),
                generated_at="2026-08-05T11:30:00Z",
            )

        proof = evidence["replay_proofs"]["historical_replay_symbol_count"]
        self.assertFalse(proof["passed"])
        self.assertEqual(proof["observed_bar_count"], 11)
        self.assertEqual(proof["expected_bar_count"], 12)
        self.assertEqual(proof["observed_bars_per_symbol_values"], [5, 6])

    def test_frozen_replay_baseline_does_not_drift_with_live_daily_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars = [self.bar("AAA", day, "10", "11", "9", "10", "100") for day in range(1, 7)]
            bars += [self.bar("BBB", day, "20", "21", "19", "20", "100") for day in range(1, 7)]
            self.write_jsonl(root / "bars.jsonl", bars)
            self.write_shadow_config(root)
            self.write_ledger(root, [])
            run_visual_strategy_shadow(
                self.make_shadow_config(root),
                bars=bars,
                generated_at="2026-08-05T11:20:00Z",
            )
            config = load_acceptance_config(self.write_acceptance_config(root))
            first = generate_acceptance_evidence(config, generated_at="2026-08-05T11:30:00Z")
            frozen_rows = [
                json.loads(line)
                for line in config.historical_replay_bars_path.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            ]
            shifted = bars[1:6] + [self.bar("AAA", 7, "10", "11", "9", "10", "100")]
            shifted += bars[7:12] + [self.bar("BBB", 7, "20", "21", "19", "20", "100")]
            self.write_jsonl(root / "bars.jsonl", shifted)
            second = generate_acceptance_evidence(config, generated_at="2026-08-05T12:30:00Z")

        self.assertTrue(first["replay_proofs"]["audit_matches_replay"]["passed"])
        self.assertEqual(len(frozen_rows), 12)
        self.assertEqual(
            {(row["symbol"], row["event_time"]) for row in frozen_rows},
            {(row["symbol"], row["event_time"]) for row in bars},
        )
        self.assertTrue(second["replay_proofs"]["audit_matches_replay"]["passed"])
        self.assertTrue(second["replay_proofs"]["no_future_data"]["passed"])


if __name__ == "__main__":
    unittest.main()
