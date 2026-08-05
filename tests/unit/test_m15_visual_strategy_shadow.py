from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from scripts.m15_visual_strategy_shadow_lib import (
    STATE_SCHEMA_VERSION,
    ShadowConfig,
    atomic_write_json,
    evaluate_pa004,
    evaluate_pa007,
    evaluate_pa008,
    load_config,
    load_state,
    run_visual_strategy_shadow,
)


class M15VisualStrategyShadowTest(unittest.TestCase):
    def make_config(self, root: Path) -> ShadowConfig:
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

    def bar(self, minute: int, close: str, *, low: str | None = None, high: str | None = None) -> dict[str, str]:
        value = Decimal(close)
        return {
            "symbol": "TEST",
            "market": "US",
            "timeframe": "5m",
            "event_time": f"2026-08-05T14:{minute:02d}:00Z",
            "open": str(value),
            "high": high or str(value + 1),
            "low": low or str(value - 1),
            "close": close,
            "volume": "100",
        }

    def read_audit(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def test_emits_three_condition_audits_per_bar_without_order_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            bars = [self.bar(index, str(10 + index)) for index in range(8)]
            summary = run_visual_strategy_shadow(config, bars=bars, generated_at="2026-08-05T15:00:00Z")
            events = self.read_audit(config.audit_path)

        self.assertEqual(summary["accepted_bar_count"], 8)
        self.assertEqual(summary["audit_event_count"], 24)
        self.assertEqual({event["strategy_id"] for event in events}, {"PA004", "PA007", "PA008"})
        expected = {
            "PA004": {"first_push", "second_push", "boundary_breach", "boundary_failure", "back_in_channel"},
            "PA007": {"first_leg", "second_leg", "trap_level_breach", "failure", "reverse_confirmation"},
            "PA008": {"trend", "trend_break", "second_test", "reversal_confirmation"},
        }
        for event in events:
            self.assertTrue(expected[event["strategy_id"]].issubset(event["conditions"]))
            self.assertEqual(event["detector_base"], "M12.20.visual_detector_implementation")
            self.assertFalse(event["uses_future_data"])
            self.assertFalse(event["backfilled"])
            self.assertFalse(event["order_generation"])
            self.assertFalse(event["broker_connection"])
            self.assertFalse(event["real_orders"])
            self.assertFalse(event["live_execution"])
            self.assertEqual(event["contract_stage"], "shadow-v1")
            self.assertTrue(event["runtime_id"].startswith("M10-PA-"))
        self.assertEqual(summary["paper_promotion_acceptance"]["status"], "blocked")

    def test_restart_deduplicates_same_bar_and_never_backfills_stale_bar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            bars = [self.bar(index, str(10 + index)) for index in range(5)]
            first = run_visual_strategy_shadow(config, bars=bars, generated_at="2026-08-05T15:00:00Z")
            second = run_visual_strategy_shadow(config, bars=bars, generated_at="2026-08-05T15:01:00Z")
            stale = self.bar(2, "99", low="98", high="100")
            third = run_visual_strategy_shadow(config, bars=[stale], generated_at="2026-08-05T15:02:00Z")
            events = self.read_audit(config.audit_path)
            state = load_state(config.state_path)

        self.assertEqual(first["audit_event_count"], 15)
        self.assertEqual(second["audit_event_count"], 0)
        self.assertEqual(second["stale_bar_count"], 4)
        self.assertEqual(second["duplicate_bar_or_event_count"], 1)
        self.assertEqual(third["stale_bar_count"], 1)
        self.assertEqual(len(events), 15)
        self.assertEqual(state["streams"]["US|TEST|5m"]["watermark_event_time"], "2026-08-05T14:04:00Z")

    def test_restart_recovery_matches_uninterrupted_state(self) -> None:
        bars = [self.bar(index, str(10 + index)) for index in range(10)]
        with tempfile.TemporaryDirectory() as one_tmp, tempfile.TemporaryDirectory() as two_tmp:
            one = self.make_config(Path(one_tmp))
            two = self.make_config(Path(two_tmp))
            run_visual_strategy_shadow(one, bars=bars, generated_at="2026-08-05T15:00:00Z")
            run_visual_strategy_shadow(two, bars=bars[:5], generated_at="2026-08-05T14:30:00Z")
            run_visual_strategy_shadow(two, bars=bars[5:], generated_at="2026-08-05T15:00:00Z")
            one_state = load_state(one.state_path)
            two_state = load_state(two.state_path)
            one_events = self.read_audit(one.audit_path)
            two_events = self.read_audit(two.audit_path)

        self.assertEqual(one_state["streams"], two_state["streams"])
        self.assertEqual(one_state["emitted_event_ids"], two_state["emitted_event_ids"])
        self.assertEqual([row["event_id"] for row in one_events], [row["event_id"] for row in two_events])

    def test_future_bars_do_not_change_existing_event_conditions(self) -> None:
        bars = [self.bar(index, str(10 + index)) for index in range(8)]
        with tempfile.TemporaryDirectory() as short_tmp, tempfile.TemporaryDirectory() as long_tmp:
            short = self.make_config(Path(short_tmp))
            long = self.make_config(Path(long_tmp))
            run_visual_strategy_shadow(short, bars=bars[:5], generated_at="2026-08-05T15:00:00Z")
            run_visual_strategy_shadow(long, bars=bars, generated_at="2026-08-05T15:00:00Z")
            short_events = self.read_audit(short.audit_path)
            long_events = self.read_audit(long.audit_path)

        self.assertEqual(
            [(row["event_id"], row["conditions"]) for row in short_events],
            [(row["event_id"], row["conditions"]) for row in long_events[: len(short_events)]],
        )

    def test_atomic_state_write_preserves_previous_state_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            original = {"schema_version": STATE_SCHEMA_VERSION, "detector_version": "old", "streams": {}}
            state_path.write_text(json.dumps(original), encoding="utf-8")
            with patch("scripts.m15_visual_strategy_shadow_lib.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    atomic_write_json(state_path, {"schema_version": STATE_SCHEMA_VERSION, "streams": {"new": {}}})
            restored = json.loads(state_path.read_text(encoding="utf-8"))
            leftovers = list(state_path.parent.glob(f".{state_path.name}.*.tmp"))

        self.assertEqual(restored, original)
        self.assertEqual(leftovers, [])

    def test_corrupt_or_incompatible_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            config.state_path.write_text('{"schema_version":"wrong"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema mismatch"):
                run_visual_strategy_shadow(config, bars=[self.bar(0, "10")])
            config.state_path.write_text("not-json\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot restore"):
                load_state(config.state_path)

    def test_config_rejects_non_shadow_contract_or_order_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            payload = {
                "contract": {"stage": "active"},
                "inputs": {"bars": "bars.jsonl"},
                "state": {"path": "state.json", "history_limit": 20},
                "outputs": {"audit_jsonl": "audit.jsonl", "run_summary": "summary.json"},
                "hard_boundaries": {
                    "broker_connection": False,
                    "real_orders": False,
                    "order_generation": False,
                    "live_execution": False,
                },
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contract-draft-v1 or shadow-v1"):
                load_config(path)
            payload["contract"]["stage"] = "shadow-v1"
            payload["hard_boundaries"]["order_generation"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicitly false"):
                load_config(path)

    def test_paper_promotion_requires_full_labeled_pack_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acceptance_path = root / "acceptance.json"
            evidence = {
                strategy: {
                    "positive_examples": 10,
                    "negative_examples": 10,
                    "boundary_examples": 5,
                    "historical_replay_symbol_count": 300,
                    "covered_regimes": ["strong_trend", "range", "gap", "abnormal_volume"],
                    "no_future_data": True,
                    "restart_parity": True,
                    "realtime_shadow_sessions": 1,
                }
                for strategy in ("PA004", "PA007", "PA008")
            }
            acceptance_path.write_text(json.dumps(evidence), encoding="utf-8")
            base = self.make_config(root)
            config = ShadowConfig(
                input_path=base.input_path,
                state_path=base.state_path,
                audit_path=base.audit_path,
                summary_path=base.summary_path,
                acceptance_path=acceptance_path,
                contract_stage="shadow-v1",
                channel_lookback=base.channel_lookback,
                channel_tolerance=base.channel_tolerance,
                trend_short_window=base.trend_short_window,
                trend_long_window=base.trend_long_window,
                history_limit=base.history_limit,
            )
            summary = run_visual_strategy_shadow(config, bars=[self.bar(0, "10")])

        self.assertEqual(summary["paper_promotion_acceptance"]["status"], "ready")

    def test_pa004_exposes_boundary_failure_and_return_to_channel(self) -> None:
        config = self.make_config(Path("/tmp/not-used"))
        history = [
            self.bar(0, "15", low="10", high="20"),
            self.bar(1, "15", low="11", high="19"),
            self.bar(2, "15", low="10", high="20"),
            self.bar(3, "15", low="11", high="19"),
            self.bar(4, "11", low="9", high="12"),
        ]
        state = {"phase": "second_push", "direction": "long"}
        failed = evaluate_pa004(config, history, state)
        returned = evaluate_pa004(config, history[1:] + [self.bar(5, "14", low="12", high="16")], state)
        self.assertTrue(failed["boundary_breach"])
        self.assertTrue(failed["boundary_failure"])
        self.assertTrue(returned["back_in_channel"])

    def test_pa007_and_pa008_expose_late_confirmation_fields(self) -> None:
        pa007_state = {"phase": "second_leg", "direction": "down", "trap_level": "10"}
        trap_history = [self.bar(0, "12"), self.bar(1, "11"), self.bar(2, "11", low="9", high="12")]
        failure = evaluate_pa007(trap_history, pa007_state)
        confirmation = evaluate_pa007(trap_history[1:] + [self.bar(3, "13", low="11", high="14")], pa007_state)
        self.assertTrue(failure["trap_level_breach"])
        self.assertTrue(failure["failure"])
        self.assertTrue(confirmation["reverse_confirmation"])

        config = self.make_config(Path("/tmp/not-used"))
        trend_state = {"phase": "tested", "direction": "up"}
        trend_history = [
            self.bar(0, "15"),
            self.bar(1, "14"),
            self.bar(2, "13"),
            self.bar(3, "11", low="10", high="12"),
        ]
        reversal = evaluate_pa008(config, trend_history, trend_state)
        self.assertTrue(reversal["reversal_confirmation"])


if __name__ == "__main__":
    unittest.main()
