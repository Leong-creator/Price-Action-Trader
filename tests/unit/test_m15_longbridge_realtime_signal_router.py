from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from scripts.m15_longbridge_realtime_execution_lib import LEDGER_JSONL as EXECUTION_LEDGER_JSONL
from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config
from scripts.m15_longbridge_realtime_execution_lib import run_realtime_execution
from scripts.m15_longbridge_realtime_signal_router_lib import (
    LEDGER_JSONL,
    SUMMARY_JSON,
    PRICE_ACTION_RUNTIME_SPECS,
    STRATEGY_DIAGNOSTICS_JSON,
    assign_daily_structure_episode_ids,
    breakout_followthrough_repair_signal,
    load_config,
    long_no_candidate_reason,
    realtime_relevant_market_events,
    realtime_structure_instance_id,
    run_realtime_signal_router,
)


class M15LongbridgeRealtimeSignalRouterTest(unittest.TestCase):
    def test_daily_structure_rearms_only_after_completed_detector_reset(self) -> None:
        now = datetime(2026, 8, 6, 14, 0, tzinfo=UTC)
        attempt = {
            "runtime_id": "M10-PA-001-1d",
            "symbol": "AAPL",
            "timeframe": "1d",
            "candidate_emitted": True,
        }
        first_intent = {
            "timeframe": "1d",
            "runtime_id": "M10-PA-001-1d",
            "symbol": "AAPL",
            "direction": "long",
            "created_at": "2026-08-06T14:00:00Z",
            "source_market_event_id": "bar-1",
        }
        first_state = assign_daily_structure_episode_ids(
            [first_intent],
            [attempt],
            {},
            generated_at=now,
            long_test_epoch_id="long-epoch",
            short_test_epoch_id="short-epoch",
        )
        first_id = first_intent["structure_instance_id"]

        later_intent = {
            "timeframe": "1d",
            "runtime_id": "M10-PA-001-1d",
            "symbol": "AAPL",
            "direction": "long",
            "created_at": "2026-08-06T14:05:00Z",
            "source_market_event_id": "bar-2",
        }
        continuous_state = assign_daily_structure_episode_ids(
            [later_intent],
            [attempt],
            first_state,
            generated_at=now,
            long_test_epoch_id="long-epoch",
            short_test_epoch_id="short-epoch",
        )
        self.assertEqual(later_intent["structure_instance_id"], first_id)

        reset_state = assign_daily_structure_episode_ids(
            [],
            [{**attempt, "candidate_emitted": False}],
            continuous_state,
            generated_at=now,
            long_test_epoch_id="long-epoch",
            short_test_epoch_id="short-epoch",
        )
        self.assertEqual(reset_state, {})

        rearmed_intent = {
            "timeframe": "1d",
            "runtime_id": "M10-PA-001-1d",
            "symbol": "AAPL",
            "direction": "long",
            "created_at": "2026-08-06T15:00:00Z",
            "source_market_event_id": "bar-13",
        }
        rearmed_state = assign_daily_structure_episode_ids(
            [rearmed_intent],
            [attempt],
            reset_state,
            generated_at=now,
            long_test_epoch_id="long-epoch",
            short_test_epoch_id="short-epoch",
        )
        self.assertNotEqual(rearmed_intent["structure_instance_id"], first_id)
        self.assertEqual(len(rearmed_state), 1)

    def test_unattempted_daily_structure_state_is_not_rearmed_by_data_gap(self) -> None:
        now = datetime(2026, 8, 6, 14, 0, tzinfo=UTC)
        previous = {
            "epoch|M10-PA-001-1d|AAPL|long|2026-08-06": {
                "structure_instance_id": "existing-episode",
                "test_epoch_id": "epoch",
                "runtime_id": "M10-PA-001-1d",
                "symbol": "AAPL",
                "direction": "long",
                "trading_date": "2026-08-06",
                "episode_started_at": "2026-08-06T13:35:00Z",
            }
        }

        state = assign_daily_structure_episode_ids(
            [],
            [],
            previous,
            generated_at=now,
            long_test_epoch_id="epoch",
            short_test_epoch_id="short-epoch",
        )

        self.assertEqual(state, previous)

    def test_inactive_daily_detector_miss_does_not_rearm_structure(self) -> None:
        now = datetime(2026, 8, 6, 14, 0, tzinfo=UTC)
        previous = {
            "epoch|M10-PA-001-1d|AAPL|long|2026-08-06": {
                "structure_instance_id": "existing-episode",
                "test_epoch_id": "epoch",
                "runtime_id": "M10-PA-001-1d",
                "symbol": "AAPL",
                "direction": "long",
                "trading_date": "2026-08-06",
                "episode_started_at": "2026-08-06T13:35:00Z",
            }
        }
        miss = {
            "runtime_id": "M10-PA-001-1d",
            "symbol": "AAPL",
            "timeframe": "1d",
            "candidate_emitted": False,
            "source_market_event_id": "stale-bar",
        }

        state = assign_daily_structure_episode_ids(
            [],
            [miss],
            previous,
            generated_at=now,
            long_test_epoch_id="epoch",
            short_test_epoch_id="short-epoch",
            active_market_event_ids={"current-bar"},
        )

        self.assertEqual(state, previous)

    def test_daily_structure_id_is_stable_across_five_minute_confirmation_events(self) -> None:
        base = {
            "timeframe": "1d",
            "runtime_id": "M10-PA-001-1d",
            "symbol": "AAPL",
            "direction": "long",
        }
        first = realtime_structure_instance_id(
            base,
            runtime_id="M10-PA-001-1d",
            symbol="AAPL",
            direction="long",
            created_at="2026-08-06T14:00:00Z",
            source_event_id="bar-1",
        )
        second = realtime_structure_instance_id(
            base,
            runtime_id="M10-PA-001-1d",
            symbol="AAPL",
            direction="long",
            created_at="2026-08-06T18:00:00Z",
            source_event_id="bar-2",
        )

        self.assertEqual(first, second)

    def test_intraday_structure_id_changes_with_completed_bar(self) -> None:
        base = {
            "timeframe": "5m",
            "runtime_id": "M10-PA-002-5m",
            "symbol": "AAPL",
            "direction": "long",
        }
        first = realtime_structure_instance_id(
            base,
            runtime_id="M10-PA-002-5m",
            symbol="AAPL",
            direction="long",
            created_at="2026-08-06T14:00:00Z",
            source_event_id="bar-1",
        )
        second = realtime_structure_instance_id(
            base,
            runtime_id="M10-PA-002-5m",
            symbol="AAPL",
            direction="long",
            created_at="2026-08-06T14:05:00Z",
            source_event_id="bar-2",
        )

        self.assertNotEqual(first, second)

    def test_pa002_repaired_requires_followthrough_and_builds_1_3r_target(self) -> None:
        rows = [
            {"open": "99", "high": "100", "low": "98", "close": "99", "event_id": "one"},
            {"open": "99", "high": "101", "low": "99", "close": "100", "event_id": "two"},
            {"open": "101", "high": "104", "low": "102", "close": "103.5", "event_id": "breakout"},
            {"open": "103.5", "high": "105", "low": "103", "close": "104", "event_id": "followthrough"},
        ]

        signal = breakout_followthrough_repair_signal(
            "AAPL",
            rows,
            spec=PRICE_ACTION_RUNTIME_SPECS["M10-PA-002-5m-repaired-v1"],
            generated_at=datetime(2026, 8, 3, 15, 0, tzinfo=UTC),
        )

        self.assertIsNotNone(signal)
        assert signal is not None
        risk = float(signal["limit_price"]) - float(signal["stop_price"])
        reward = float(signal["target_price"]) - float(signal["limit_price"])
        self.assertAlmostEqual(reward / risk, 1.3, places=2)
        self.assertTrue(signal["latest_confirms_entry"])
        self.assertTrue(signal["next_market_day_timeout"])

    def test_router_does_not_read_local_simulation_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event()])
            (root / "m12_46_account_trade_ledger.jsonl").write_text(
                json.dumps({"runtime_id": "M10-PA-004-long-1d", "event_type": "close"}) + "\n",
                encoding="utf-8",
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")

            self.assertEqual(payload["source_mode"], "longbridge_realtime_market_events")
            self.assertTrue(payload["local_simulation_isolated"])
            self.assertEqual(payload["inputs"]["local_simulation_ledger"], "")
            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(
                payload["strategy_signal_diagnostics"]["runtime_count"],
                len(config.allowed_runtime_ids),
            )
            self.assertTrue((config.output_dir / STRATEGY_DIAGNOSTICS_JSON).exists())
            diagnostics = json.loads(
                (config.output_dir / STRATEGY_DIAGNOSTICS_JSON).read_text(encoding="utf-8")
            )
            self.assertTrue(diagnostics["strategy_contract_signature"])
            self.assertTrue(
                all(
                    "strategy_contract_hash" in row
                    for row in diagnostics["runtime_summaries"]
                )
            )
            summary_text = (config.output_dir / SUMMARY_JSON).read_text(encoding="utf-8")
            self.assertNotIn("m12_46_account_trade_ledger", summary_text)

    def test_pa012_diagnostics_distinguish_missing_opening_range_after_restart(self) -> None:
        rows = [
            {
                "event_time": f"2026-07-15T{hour:02d}:{minute:02d}:00Z",
                "next_bar_first_quote_at": "2026-07-15T16:05:01Z",
            }
            for hour, minute in ((16, 0), (16, 5), (16, 10), (16, 15), (16, 20), (16, 25), (16, 30), (16, 35))
        ]
        self.assertEqual(
            long_no_candidate_reason("M10-PA-012-5m", rows),
            "missing_opening_range_context_after_restart",
        )

    def test_legacy_five_minute_runtime_rejects_non_contiguous_context(self) -> None:
        rows = [
            {
                "event_time": event_time,
                "next_bar_first_quote_at": "2026-07-15T16:20:01Z",
            }
            for event_time in (
                "2026-07-15T16:00:00Z",
                "2026-07-15T16:05:00Z",
                "2026-07-15T16:20:00Z",
            )
        ]
        self.assertEqual(
            long_no_candidate_reason("M10-PA-013-5m", rows),
            "non_contiguous_five_minute_context",
        )

    def test_realtime_context_keeps_enough_daily_history_for_pa001(self) -> None:
        rows = [
            {
                "event_id": f"daily-{index}",
                "symbol": "AAPL",
                "timeframe": "1d",
                "event_time": f"2026-06-{index + 1:02d}T20:00:00Z",
                "received_at": (
                    "2026-07-15T13:30:01Z"
                    if index == 29
                    else f"2026-06-{index + 1:02d}T20:00:01Z"
                ),
            }
            for index in range(30)
        ]

        relevant = realtime_relevant_market_events(
            rows,
            "2026-07-15T13:30:00Z",
        )

        self.assertEqual(len(relevant), 30)

    def test_realtime_context_keeps_opening_range_during_midday_restart(self) -> None:
        rows = [
            {
                "event_id": f"five-minute-{index}",
                "symbol": "AAPL",
                "timeframe": "5m",
                "event_time": f"2026-07-15T{13 + ((35 + index * 5) // 60):02d}:{(35 + index * 5) % 60:02d}:00Z",
                "received_at": (
                    "2026-07-15T17:00:01Z"
                    if index == 41
                    else f"2026-07-15T{13 + ((35 + index * 5) // 60):02d}:{(35 + index * 5) % 60:02d}:01Z"
                ),
            }
            for index in range(42)
        ]

        relevant = realtime_relevant_market_events(
            rows,
            "2026-07-15T17:00:00Z",
        )

        self.assertEqual(len(relevant), 42)
        self.assertEqual(relevant[0]["event_time"], "2026-07-15T13:35:00Z")

    def test_embedded_intent_emits_complete_realtime_signal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="bar-embedded",
                        strategy_signal_intents=[
                            {
                                "runtime_id": "M10-PA-013-1d",
                                "strategy_id": "M10-PA-013",
                                "direction": "long",
                                "order_type": "trigger_limit",
                                "trigger_price": "101.00",
                                "limit_price": "101.20",
                                "quantity": "1",
                                "stop_price": "98.00",
                                "target_price": "115.00",
                            }
                        ],
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(signals[0]["runtime_id"], "M10-PA-013-1d")
            self.assertEqual(signals[0]["order_type"], "trigger_limit")
            self.assertEqual(signals[0]["trigger_price"], "101.00")
            self.assertIn("net_profit_after_fees_at_target", signals[0])
            self.assertFalse(signals[0]["local_simulation_source"])

    def test_fractional_quantity_at_least_one_is_floored_before_risk_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="fractional-ge-one",
                        symbol="AAPL",
                        strategy_signal_intents=[
                            self.intent(
                                quantity="24.0964",
                                limit_price="20.00",
                                stop_price="19.50",
                                target_price="21.00",
                            )
                        ],
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(payload["quantity_normalized_count"], 1)
            self.assertEqual(rows[0]["raw_suggested_quantity"], "24.0964")
            self.assertEqual(rows[0]["submitted_quantity"], "24")
            self.assertEqual(rows[0]["quantity_rounding_adjustment"], "0.0964")
            self.assertEqual(rows[0]["quantity_normalization_status"], "rounded_down_to_whole_share")
            self.assertNotIn("blocked_fractional_disabled", rows[0]["blockers"])
            self.assertEqual(rows[0]["notional"], "480.00")
            self.assertEqual(rows[0]["risk_amount"], "12.00")
            self.assertEqual(signals[0]["quantity"], "24")
            self.assertEqual(signals[0]["submitted_quantity"], "24")

    def test_fractional_quantity_below_one_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="fractional-below-one",
                        symbol="AAPL",
                        strategy_signal_intents=[
                            self.intent(
                                quantity="0.9999",
                                limit_price="20.00",
                                stop_price="19.50",
                                target_price="40.00",
                            )
                        ],
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 0)
            self.assertEqual(payload["quantity_below_one_blocked_count"], 1)
            self.assertEqual(signals, [])
            self.assertIn("blocked_quantity_below_one_share", rows[0]["blockers"])
            self.assertNotIn("blocked_fractional_disabled", rows[0]["blockers"])

    def test_ftd_loss_streak_guard_can_emit_independent_longbridge_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                allowed_runtime_ids=["M12-FTD-001-loss-streak-guard-1d"],
                runtime_position_multipliers={"M12-FTD-001-loss-streak-guard-1d": "0.10"},
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="ftd-loss-streak",
                        symbol="SPY",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M12-FTD-001-loss-streak-guard-1d",
                                strategy_id="M12-FTD-001",
                                quantity="1",
                                limit_price="100.00",
                                stop_price="99.00",
                                target_price="115.00",
                            )
                        ],
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(signals[0]["runtime_id"], "M12-FTD-001-loss-streak-guard-1d")
            self.assertEqual(signals[0]["capital_bucket"], "ftd_loss_streak")

    def test_ftd_baseline_and_loss_streak_are_not_merged_by_confluence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                allowed_runtime_ids=[
                    "M12-FTD-001-baseline-1d",
                    "M12-FTD-001-loss-streak-guard-1d",
                ],
                runtime_position_multipliers={
                    "M12-FTD-001-baseline-1d": "0.10",
                    "M12-FTD-001-loss-streak-guard-1d": "0.10",
                },
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="ftd-both",
                        symbol="SPY",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M12-FTD-001-baseline-1d",
                                strategy_id="M12-FTD-001",
                                quantity="1",
                                limit_price="100.00",
                                stop_price="99.00",
                                target_price="115.00",
                            ),
                            self.intent(
                                runtime_id="M12-FTD-001-loss-streak-guard-1d",
                                strategy_id="M12-FTD-001",
                                quantity="1",
                                limit_price="100.00",
                                stop_price="99.00",
                                target_price="115.00",
                            ),
                        ],
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 2)
            self.assertEqual(payload["confluence_merged_support_count"], 0)
            self.assertEqual(
                {row["runtime_id"]: row["capital_bucket"] for row in signals},
                {
                    "M12-FTD-001-baseline-1d": "ftd_baseline",
                    "M12-FTD-001-loss-streak-guard-1d": "ftd_loss_streak",
                },
            )

    def test_profit_and_reward_r_gates_block_weak_longbridge_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="low-profit",
                        symbol="AAPL",
                        strategy_signal_intents=[
                            self.intent(quantity="1", limit_price="100", stop_price="95", target_price="108")
                        ],
                    ),
                    self.market_event(
                        event_id="below-normal-profit",
                        symbol="MSFT",
                        strategy_signal_intents=[
                            self.intent(quantity="1", limit_price="100", stop_price="95", target_price="109")
                        ],
                    ),
                    self.market_event(
                        event_id="low-reward-r",
                        symbol="GOOG",
                        strategy_signal_intents=[
                            self.intent(quantity="3", limit_price="100", stop_price="95", target_price="106")
                        ],
                    ),
                    self.market_event(
                        event_id="strong",
                        symbol="META",
                        strategy_signal_intents=[
                            self.intent(quantity="1", limit_price="100", stop_price="95", target_price="115")
                        ],
                    ),
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            rows = {row["source_market_event_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(payload["low_profit_blocked_count"], 2)
            self.assertEqual(payload["reward_r_blocked_count"], 1)
            self.assertIn("blocked_fee_profit_below_minimum", rows["low-profit"]["blockers"])
            self.assertIn("blocked_fee_profit_below_minimum", rows["below-normal-profit"]["blockers"])
            self.assertIn("blocked_reward_r_below_minimum", rows["low-reward-r"]["blockers"])
            self.assertEqual(signals[0]["symbol"], "META")
            self.assertEqual(signals[0]["profit_quality_gate"], "normal_profit")

    def test_pa001_thresholds_and_pa001_5m_local_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, allowed_runtime_ids=["M10-PA-001-1d", "M10-PA-001-5m"])
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="pa001-low-profit",
                        symbol="AAPL",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-001-1d",
                                strategy_id="M10-PA-001",
                                quantity="1",
                                limit_price="100",
                                stop_price="95",
                                target_price="111.99",
                            )
                        ],
                    ),
                    self.market_event(
                        event_id="pa001-low-r",
                        symbol="MSFT",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-001-1d",
                                strategy_id="M10-PA-001",
                                quantity="3",
                                limit_price="100",
                                stop_price="95",
                                target_price="108",
                            )
                        ],
                    ),
                    self.market_event(
                        event_id="pa001-5m",
                        symbol="GOOG",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-001-5m",
                                strategy_id="M10-PA-001",
                                quantity="2",
                                limit_price="100",
                                stop_price="95",
                                target_price="120",
                            )
                        ],
                    ),
                    self.market_event(
                        event_id="pa001-strong",
                        symbol="META",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-001-1d",
                                strategy_id="M10-PA-001",
                                quantity="1",
                                limit_price="100",
                                stop_price="95",
                                target_price="117",
                            )
                        ],
                    ),
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            rows = {row["source_market_event_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertIn("blocked_fee_profit_below_minimum", rows["pa001-low-profit"]["blockers"])
            self.assertIn("blocked_reward_r_below_minimum", rows["pa001-low-r"]["blockers"])
            self.assertEqual(rows["pa001-5m"]["router_decision_status"], "blocked_repair_runtime_local_only")
            self.assertEqual(signals[0]["symbol"], "META")
            self.assertEqual(signals[0]["minimum_net_profit_after_fees"], "12.00")
            self.assertEqual(signals[0]["minimum_reward_r"], "2")

    def test_repair_auxiliary_and_shadow_intents_do_not_emit_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        strategy_signal_intents=[
                            self.intent(runtime_id="M10-PA-007-1d", strategy_id="M10-PA-007"),
                            self.intent(runtime_id="M10-PA-003", strategy_id="M10-PA-003"),
                            self.intent(runtime_id="M10-PA-004-MBF-1d", strategy_id="M10-PA-004"),
                        ]
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["new_signal_event_count"], 0)
            self.assertEqual(rows[0]["router_decision_status"], "blocked_repair_runtime_local_only")
            self.assertEqual(rows[1]["router_decision_status"], "blocked_auxiliary_module_local_only")
            self.assertEqual(rows[2]["router_decision_status"], "blocked_shadow_runtime_local_only")

    def test_pa004_mbf_and_qc_can_emit_when_explicitly_whitelisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                allowed_runtime_ids=["M10-PA-004-MBF-1d", "M10-PA-004-MBF-QC-1d"],
                runtime_position_multipliers={
                    "M10-PA-004-MBF-1d": "1.0",
                    "M10-PA-004-MBF-QC-1d": "1.0",
                },
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="mbf-intents",
                        strategy_signal_intents=[
                            self.intent(runtime_id="M10-PA-004-MBF-1d", strategy_id="M10-PA-004"),
                            self.intent(runtime_id="M10-PA-004-MBF-QC-1d", strategy_id="M10-PA-004"),
                        ],
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            signals = {row["runtime_id"]: row for row in self.read_jsonl(root / "signals.jsonl")}

            self.assertEqual(payload["new_signal_event_count"], 2)
            self.assertEqual(signals["M10-PA-004-MBF-1d"]["capital_bucket"], "pa004_mbf")
            self.assertEqual(signals["M10-PA-004-MBF-QC-1d"]["capital_bucket"], "pa004_mbf_qc")

    def test_pa004_builtin_detector_generates_signal_from_new_daily_bar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="prev",
                        event_time="2026-06-03T20:00:00Z",
                        open="95",
                        high="98",
                        low="94",
                        close="96",
                        volume="1000000",
                        strategy_signal_intents=[],
                    ),
                    self.market_event(
                        event_id="latest",
                        event_time="2026-06-04T20:00:00Z",
                        open="100",
                        high="105",
                        low="99",
                        close="104",
                        volume="1200000",
                        strategy_signal_intents=[],
                    ),
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T20:00:01Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(signals[0]["runtime_id"], "M10-PA-004-long-1d")
            self.assertEqual(signals[0]["source_market_event_id"], "latest")
            self.assertEqual(signals[0]["side"], "buy")
            self.assertEqual(signals[0]["volume_ratio"], "1.2")
            self.assertIn("quality_score", signals[0])
            self.assertGreaterEqual(int(signals[0]["quantity"]), 1)

    def test_pa004_builtin_detector_blocks_low_close_position_or_no_volume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="prev",
                        event_time="2026-06-03T20:00:00Z",
                        close="100",
                        volume="1000000",
                        strategy_signal_intents=[],
                    ),
                    self.market_event(
                        event_id="low-close",
                        event_time="2026-06-04T20:00:00Z",
                        open="103",
                        high="106",
                        low="100",
                        close="102",
                        volume="1200000",
                        strategy_signal_intents=[],
                    ),
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T20:00:01Z")
            self.assertEqual(payload["new_signal_event_count"], 0)

    def test_ftd_requires_market_confirmation_and_loss_streak_is_stricter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                enabled_detectors=["price_action_realtime_v1"],
                allowed_runtime_ids=[
                    "M12-FTD-001-baseline-1d",
                    "M12-FTD-001-loss-streak-guard-1d",
                ],
                runtime_position_multipliers={
                    "M12-FTD-001-baseline-1d": "1.0",
                    "M12-FTD-001-loss-streak-guard-1d": "1.0",
                },
            )
            aapl_rows = [
                self.market_event(
                    event_id="aapl-prev",
                    symbol="AAPL",
                    event_time="2026-06-03T20:00:00Z",
                    open="99",
                    high="101",
                    low="98",
                    close="100",
                    volume="1000000",
                    strategy_signal_intents=[],
                ),
                self.market_event(
                    event_id="aapl-latest",
                    symbol="AAPL",
                    event_time="2026-06-04T20:00:00Z",
                    open="101",
                    high="103",
                    low="99",
                    close="101.80",
                    volume="1200000",
                    strategy_signal_intents=[],
                ),
            ]
            self.write_jsonl(root / "market_events.jsonl", aapl_rows)

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T20:00:01Z")
            self.assertEqual(payload["new_signal_event_count"], 0)

            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="spy-prev",
                        symbol="SPY",
                        event_time="2026-06-03T20:00:00Z",
                        open="99",
                        high="101",
                        low="98",
                        close="100",
                        volume="1000000",
                        strategy_signal_intents=[],
                    ),
                    self.market_event(
                        event_id="spy-latest",
                        symbol="SPY",
                        event_time="2026-06-04T20:00:00Z",
                        open="100",
                        high="103",
                        low="100",
                        close="102",
                        volume="1200000",
                        strategy_signal_intents=[],
                    ),
                    *aapl_rows,
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T20:00:02Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(signals[0]["runtime_id"], "M12-FTD-001-baseline-1d")
            self.assertEqual(signals[0]["market_confirmation_status"], "confirmed")
            self.assertEqual(signals[0]["market_confirmation_symbols"], "SPY")

    def test_ftd_pullback_guard_confirm_emits_quality_fields_without_market_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                session_started_at="2026-05-01T13:00:00Z",
                enabled_detectors=["price_action_realtime_v1"],
                allowed_runtime_ids=["M12-FTD-001-pullback-guard-confirm-1d"],
                runtime_position_multipliers={"M12-FTD-001-pullback-guard-confirm-1d": "1.0"},
                virtual_capital_buckets={
                    "ftd_pullback_guard": {
                        "label": "FTD pullback guard",
                        "equity": "10000",
                        "max_total_exposure": "6000",
                        "max_symbol_exposure": "1500",
                        "max_risk_per_order": "20",
                        "min_cash_reserve": "4000",
                        "runtime_ids": ["M12-FTD-001-pullback-guard-confirm-1d"],
                    }
                },
            )
            rows: list[dict[str, object]] = []
            for day in range(1, 21):
                rows.append(
                    self.market_event(
                        event_id=f"base-{day}",
                        symbol="AAPL",
                        event_time=f"2026-05-{day + 1:02d}T20:00:00Z",
                        received_at=f"2026-05-{day + 1:02d}T20:00:01Z",
                        open="99.5",
                        high="100.5",
                        low="99",
                        close="100",
                        volume="1000000",
                        strategy_signal_intents=[],
                    )
                )
            rows.extend(
                [
                    self.market_event(
                        event_id="recent-high",
                        symbol="AAPL",
                        event_time="2026-05-22T20:00:00Z",
                        received_at="2026-05-22T20:00:01Z",
                        open="104",
                        high="110",
                        low="99.5",
                        close="100",
                        volume="1000000",
                        strategy_signal_intents=[],
                    ),
                    self.market_event(
                        event_id="setup-bar",
                        symbol="AAPL",
                        event_time="2026-05-23T20:00:00Z",
                        received_at="2026-05-23T20:00:01Z",
                        open="99.8",
                        high="100.8",
                        low="99.2",
                        close="100",
                        volume="1000000",
                        strategy_signal_intents=[],
                    ),
                    self.market_event(
                        event_id="signal-bar",
                        symbol="AAPL",
                        event_time="2026-05-24T20:00:00Z",
                        received_at="2026-05-24T20:00:01Z",
                        open="100",
                        high="104",
                        low="99",
                        close="103",
                        volume="1300000",
                        strategy_signal_intents=[],
                    ),
                    self.market_event(
                        event_id="confirm-bar",
                        symbol="AAPL",
                        event_time="2026-05-25T20:00:00Z",
                        received_at="2026-05-25T20:00:01Z",
                        open="103",
                        high="105",
                        low="102",
                        close="104",
                        volume="1250000",
                        next_bar_first_quote_price="104.20",
                        next_bar_first_quote_at="2026-05-24T20:00:00.100Z",
                        next_bar_entry_source="longbridge_sdk_first_quote_after_bar_close",
                        strategy_signal_intents=[],
                    ),
                ]
            )
            self.write_jsonl(root / "market_events.jsonl", rows)

            payload = run_realtime_signal_router(config, generated_at="2026-05-24T20:00:02Z")
            signals = self.read_jsonl(root / "signals.jsonl")
            ledger_rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(signals[0]["runtime_id"], "M12-FTD-001-pullback-guard-confirm-1d")
            self.assertIn("quality_score", signals[0])
            self.assertIn("signal_quality_score", signals[0])
            self.assertIn("components", signals[0])
            self.assertIn("quality_score_components", signals[0])
            self.assertEqual(signals[0]["quality_score"], "100")
            self.assertEqual(
                signals[0]["components"]["quality_basis"],
                "contract_conditions_passed_no_additional_strategy_gate",
            )
            self.assertEqual(signals[0]["components"], signals[0]["quality_score_components"])
            self.assertEqual(signals[0]["market_confirmation_status"], "audit_not_confirmed")
            self.assertEqual(signals[0]["contract_evidence"]["market_context_is_blocker"], False)
            self.assertEqual(ledger_rows[0]["components"], ledger_rows[0]["quality_score_components"])

    def test_pa004_mbf_variants_emit_independent_single_bucket_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                enabled_detectors=["pa004_followthrough_long"],
                allowed_runtime_ids=["M10-PA-004-MBF-1d", "M10-PA-004-MBF-QC-1d"],
                runtime_position_multipliers={
                    "M10-PA-004-MBF-1d": "1.0",
                    "M10-PA-004-MBF-QC-1d": "1.0",
                },
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="previous-day", symbol="AAPL", event_time="2026-06-03T20:00:00Z",
                        open="99", high="101", low="98", close="100", volume="1000000",
                        strategy_signal_intents=[],
                    ),
                    self.market_event(
                        event_id="current-day", symbol="AAPL", event_time="2026-06-04T14:00:00Z",
                        open="102.5", high="105", low="101", close="104", volume="1200000",
                        next_bar_first_quote_price="104.1",
                        next_bar_first_quote_at="2026-06-04T14:00:00.100Z",
                        next_bar_entry_source="longbridge_sdk_first_quote_after_bar_close",
                        strategy_signal_intents=[],
                    ),
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 2)
            self.assertEqual(
                {row["runtime_id"] for row in signals},
                {"M10-PA-004-MBF-1d", "M10-PA-004-MBF-QC-1d"},
            )
            self.assertEqual(
                {row["capital_bucket"] for row in signals},
                {"pa004_mbf", "pa004_mbf_qc"},
            )

    def test_pa004_mbf_qc_requires_volume_and_next_bar_quote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                enabled_detectors=["pa004_momentum_variants"],
                allowed_runtime_ids=["M10-PA-004-MBF-QC-1d"],
                runtime_position_multipliers={"M10-PA-004-MBF-QC-1d": "1.0"},
            )
            previous = self.market_event(
                event_id="previous-day", symbol="AAPL", event_time="2026-06-03T20:00:00Z",
                open="99", high="101", low="98", close="100", volume="1000000",
                strategy_signal_intents=[],
            )
            weak_volume = self.market_event(
                event_id="weak-volume", symbol="AAPL", event_time="2026-06-04T14:00:00Z",
                open="102.5", high="105", low="101", close="104", volume="1050000",
                next_bar_first_quote_price="104.1",
                next_bar_first_quote_at="2026-06-04T14:00:00.100Z",
                next_bar_entry_source="longbridge_sdk_first_quote_after_bar_close",
                strategy_signal_intents=[],
            )
            self.write_jsonl(root / "market_events.jsonl", [previous, weak_volume])
            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            self.assertEqual(payload["new_signal_event_count"], 0)

            missing_next_quote = {
                **weak_volume,
                "event_id": "missing-next-quote",
                "volume": "1200000",
                "next_bar_first_quote_price": "",
                "next_bar_first_quote_at": "",
            }
            self.write_jsonl(root / "market_events.jsonl", [previous, missing_next_quote])
            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:05:01Z")
            self.assertEqual(payload["new_signal_event_count"], 0)

    def test_quality_sorting_prioritizes_stronger_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, allowed_runtime_ids=["M10-PA-013-1d"])
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="sort-row",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-013-1d",
                                strategy_id="M10-PA-013",
                                symbol="WEAK",
                                quality_score="20",
                                quantity="1",
                                limit_price="100",
                                stop_price="95",
                                target_price="115",
                            ),
                            self.intent(
                                runtime_id="M10-PA-013-1d",
                                strategy_id="M10-PA-013",
                                symbol="STRONG",
                                quality_score="90",
                                quantity="1",
                                limit_price="100",
                                stop_price="95",
                                target_price="115",
                            ),
                        ],
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 2)
            self.assertEqual(signals[0]["symbol"], "STRONG")
            self.assertEqual(signals[0]["quality_score"], "90")

    def test_relative_strength_sorting_is_applied_within_capital_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, allowed_runtime_ids=["M10-PA-013-1d"])
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="spy-prev",
                        symbol="SPY",
                        strategy_signal_intents=[],
                        close="100",
                        event_time="2026-06-03T20:00:00Z",
                    ),
                    self.market_event(
                        event_id="spy-latest",
                        symbol="SPY",
                        strategy_signal_intents=[],
                        close="101",
                        event_time="2026-06-04T20:00:00Z",
                    ),
                    self.market_event(
                        event_id="qqq-prev",
                        symbol="QQQ",
                        strategy_signal_intents=[],
                        close="100",
                        event_time="2026-06-03T20:00:00Z",
                    ),
                    self.market_event(
                        event_id="qqq-latest",
                        symbol="QQQ",
                        strategy_signal_intents=[],
                        close="101",
                        event_time="2026-06-04T20:00:00Z",
                    ),
                    self.market_event(
                        event_id="smh-prev",
                        symbol="SMH",
                        strategy_signal_intents=[],
                        close="200",
                        event_time="2026-06-03T20:00:00Z",
                    ),
                    self.market_event(
                        event_id="smh-latest",
                        symbol="SMH",
                        strategy_signal_intents=[],
                        close="206",
                        event_time="2026-06-04T20:00:00Z",
                    ),
                    self.market_event(
                        event_id="soxx-prev",
                        symbol="SOXX",
                        strategy_signal_intents=[],
                        close="250",
                        event_time="2026-06-03T20:00:00Z",
                    ),
                    self.market_event(
                        event_id="soxx-latest",
                        symbol="SOXX",
                        strategy_signal_intents=[],
                        close="257.5",
                        event_time="2026-06-04T20:00:00Z",
                    ),
                    self.market_event(
                        event_id="aapl-prev",
                        symbol="AAPL",
                        strategy_signal_intents=[],
                        close="100",
                        event_time="2026-06-03T20:00:00Z",
                    ),
                    self.market_event(
                        event_id="aapl-latest",
                        symbol="AAPL",
                        event_time="2026-06-04T20:00:00Z",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-013-1d",
                                strategy_id="M10-PA-013",
                                symbol="AAPL",
                                quality_score="70",
                                limit_price="100",
                                stop_price="95",
                                target_price="115",
                            )
                        ],
                        close="103",
                    ),
                    self.market_event(
                        event_id="nvda-prev",
                        symbol="NVDA",
                        strategy_signal_intents=[],
                        close="100",
                        event_time="2026-06-03T20:00:00Z",
                    ),
                    self.market_event(
                        event_id="nvda-latest",
                        symbol="NVDA",
                        event_time="2026-06-04T20:00:00Z",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-013-1d",
                                strategy_id="M10-PA-013",
                                symbol="NVDA",
                                quality_score="70",
                                limit_price="100",
                                stop_price="95",
                                target_price="115",
                            )
                        ],
                        close="108",
                    ),
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T20:00:01Z")
            signals = self.read_jsonl(root / "signals.jsonl")
            rows = {row["symbol"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["new_signal_event_count"], 2)
            self.assertEqual(signals[0]["symbol"], "NVDA")
            self.assertEqual(signals[0]["industry_strength_scope"], "semiconductor")
            self.assertEqual(signals[0]["relative_strength_audit_state"], "complete")
            self.assertGreater(
                float(rows["NVDA"]["relative_strength_rank_score"]),
                float(rows["AAPL"]["relative_strength_rank_score"]),
            )
            self.assertEqual(rows["AAPL"]["industry_strength_scope"], "market_only")

    def test_pending_cleanup_blocks_only_the_target_capital_bucket_new_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                allowed_runtime_ids=["M10-PA-004-MBF-1d", "M10-PA-004-MBF-QC-1d"],
                runtime_position_multipliers={
                    "M10-PA-004-MBF-1d": "1.0",
                    "M10-PA-004-MBF-QC-1d": "1.0",
                },
                migration_state={
                    "capital_bucket_states": {
                        "pa004_mbf": {"migration_status": "pending_cleanup"},
                    }
                },
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="mbf-pending",
                        strategy_signal_intents=[
                            self.intent(runtime_id="M10-PA-004-MBF-1d", strategy_id="M10-PA-004")
                        ],
                    ),
                    self.market_event(
                        event_id="mbf-qc-open",
                        symbol="MSFT",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-004-MBF-QC-1d",
                                strategy_id="M10-PA-004",
                                symbol="MSFT",
                            )
                        ],
                    ),
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            rows = {row["source_market_event_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertIn("blocked_capital_bucket_pending_cleanup", rows["mbf-pending"]["blockers"])
            self.assertEqual(rows["mbf-pending"]["capital_bucket_migration_status"], "pending_cleanup")
            self.assertEqual(rows["mbf-qc-open"]["capital_bucket_migration_status"], "")
            self.assertEqual(signals[0]["runtime_id"], "M10-PA-004-MBF-QC-1d")

    def test_price_action_realtime_detector_generates_daily_and_5m_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                enabled_detectors=["price_action_realtime_v1"],
                allowed_runtime_ids=[
                    "M10-PA-002-1d",
                    "M10-PA-012-5m",
                    "M12-FTD-001-baseline-1d",
                ],
                runtime_position_multipliers={
                    "M10-PA-002-1d": "1.0",
                    "M10-PA-012-5m": "0.5",
                    "M12-FTD-001-baseline-1d": "0.25",
                },
            )
            daily_events = [
                self.market_event(
                    event_id="msft-d1",
                    symbol="MSFT",
                    event_time="2026-06-02T20:00:00Z",
                    received_at="2026-06-02T20:00:01Z",
                    open="98",
                    high="102",
                    low="97",
                    close="100",
                    volume="1000000",
                    strategy_signal_intents=[],
                ),
                self.market_event(
                    event_id="msft-d2",
                    symbol="MSFT",
                    event_time="2026-06-03T20:00:00Z",
                    received_at="2026-06-03T20:00:01Z",
                    open="100",
                    high="104",
                    low="99",
                    close="101",
                    volume="1200000",
                    strategy_signal_intents=[],
                ),
                self.market_event(
                    event_id="msft-d3",
                    symbol="MSFT",
                    event_time="2026-06-04T20:00:00Z",
                    received_at="2026-06-04T20:00:01Z",
                    open="102",
                    high="108",
                    low="105",
                    close="107",
                    volume="1800000",
                    strategy_signal_intents=[],
                ),
            ]
            intraday_events = [
                self.market_event(
                    event_id=f"nvda-5m-{index}",
                    symbol="NVDA",
                    timeframe="5m",
                    event_time=f"2026-06-04T{hour:02d}:{minute:02d}:00Z",
                    received_at=f"2026-06-04T{hour:02d}:{minute:02d}:01Z",
                    open=str(open_price),
                    high=str(high),
                    low=str(low),
                    close=str(close),
                    strategy_signal_intents=[],
                )
                for index, (hour, minute, open_price, high, low, close) in enumerate(
                    [
                        (13, 30, "100.0", "100.8", "99.7", "100.2"),
                        (13, 35, "100.2", "101.0", "99.9", "100.4"),
                        (13, 40, "100.4", "100.9", "99.8", "100.5"),
                        (13, 45, "100.5", "100.7", "99.9", "100.2"),
                        (13, 50, "100.2", "100.6", "99.8", "100.1"),
                        (13, 55, "100.1", "100.5", "99.9", "100.3"),
                        (14, 0, "100.3", "100.8", "100.1", "100.5"),
                        (14, 5, "100.5", "102.2", "100.8", "102.0"),
                    ]
                )
            ]
            self.write_jsonl(root / "market_events.jsonl", daily_events + intraday_events)

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T20:00:02Z")
            signals = self.read_jsonl(root / "signals.jsonl")
            by_runtime = {row["runtime_id"]: row for row in signals}

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(payload["confluence_merged_support_count"], 0)
            self.assertEqual(set(by_runtime), {"M10-PA-002-1d"})
            self.assertEqual(by_runtime["M10-PA-002-1d"]["order_type"], "trigger_limit")
            self.assertEqual(by_runtime["M10-PA-002-1d"]["capital_bucket"], "experimental")
            self.assertEqual(by_runtime["M10-PA-002-1d"]["confluence_multiplier"], "1")
            self.assertEqual(by_runtime["M10-PA-002-1d"]["confluence_support_runtime_ids"], [])
            self.assertNotIn("M10-PA-012-5m", by_runtime)
            self.assertTrue(all(not row["local_simulation_source"] for row in signals))

    def test_pa002_1d_stays_in_unified_experimental_bucket_without_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                allowed_runtime_ids=["M10-PA-002-1d"],
                runtime_position_multipliers={"M10-PA-002-1d": "0.25"},
                virtual_capital_buckets={
                    "experimental": {
                        "label": "统一实验仓（M10-PA-002-1d/M10-PA-013-1d/M10-PA-008-1d/M10-PA-005-1d/M10-PA-005-5m/M10-PA-012-5m/M10-PA-001-1d）",
                        "equity": "10000",
                        "max_total_exposure": "6000",
                        "max_symbol_exposure": "1000",
                        "max_risk_per_order": "20",
                        "min_cash_reserve": "4000",
                        "runtime_ids": ["M10-PA-002-1d"],
                    },
                },
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="pa002-embedded",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-002-1d",
                                strategy_id="M10-PA-002",
                                order_type="trigger_limit",
                                trigger_price="101",
                                limit_price="101",
                                stop_price="96",
                                target_price="116",
                                quantity="1",
                            )
                        ],
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(signals[0]["capital_bucket"], "experimental")
            self.assertEqual(signals[0]["capital_bucket_label"], "统一实验仓（M10-PA-002-1d/M10-PA-013-1d/M10-PA-008-1d/M10-PA-005-1d/M10-PA-005-5m/M10-PA-012-5m/M10-PA-001-1d）")
            self.assertFalse(signals[0]["additional_bucket_route"])

    def test_pa002_5m_routes_to_dedicated_bucket_as_primary_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                allowed_runtime_ids=["M10-PA-002-5m"],
                runtime_position_multipliers={"M10-PA-002-5m": "1.0"},
                virtual_capital_buckets={
                    "pa002_5m": {
                        "label": "PA002-5m单仓（M10-PA-002-5m）",
                        "equity": "10000",
                        "max_total_exposure": "6000",
                        "max_symbol_exposure": "1500",
                        "max_risk_per_order": "20",
                        "min_cash_reserve": "4000",
                        "runtime_ids": ["M10-PA-002-5m"],
                    },
                },
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="pa002-5m-embedded",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-002-5m",
                                strategy_id="M10-PA-002",
                                order_type="trigger_limit",
                                trigger_price="101",
                                limit_price="101",
                                stop_price="96",
                                target_price="116",
                                quantity="1",
                            )
                        ],
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(signals[0]["runtime_id"], "M10-PA-002-5m")
            self.assertEqual(signals[0]["capital_bucket"], "pa002_5m")
            self.assertEqual(signals[0]["capital_bucket_label"], "PA002-5m单仓（M10-PA-002-5m）")
            self.assertFalse(signals[0]["additional_bucket_route"])

    def test_confluence_merges_same_symbol_same_direction_and_boosts_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                allowed_runtime_ids=["M10-PA-005-1d", "M10-PA-008-1d"],
                runtime_position_multipliers={"M10-PA-005-1d": "0.25", "M10-PA-008-1d": "0.25"},
            )
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="confluence-bar",
                        strategy_signal_intents=[
                            self.intent(
                                runtime_id="M10-PA-005-1d",
                                strategy_id="M10-PA-005",
                                limit_price="100",
                                stop_price="98",
                                target_price="104",
                            ),
                            self.intent(
                                runtime_id="M10-PA-008-1d",
                                strategy_id="M10-PA-008",
                                limit_price="100",
                                stop_price="98",
                                target_price="104",
                            ),
                        ],
                    )
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            signals = self.read_jsonl(root / "signals.jsonl")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(payload["confluence_merged_support_count"], 1)
            self.assertEqual(signals[0]["runtime_id"], "M10-PA-005-1d")
            self.assertEqual(signals[0]["confluence_multiplier"], "1.5")
            self.assertEqual(signals[0]["confluence_support_runtime_ids"], ["M10-PA-008-1d"])
            self.assertEqual(signals[0]["quantity"], "3")
            self.assertIn("merged_into_confluence_primary", {row["router_decision_status"] for row in rows})

    def test_router_deduplicates_existing_signal_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event()])

            run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:02Z")
            signals = self.read_jsonl(root / "signals.jsonl")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(len(signals), 1)
            self.assertEqual(payload["new_signal_event_count"], 0)
            self.assertIn("duplicate_signal_event", rows[0]["blockers"])

    def test_router_deduplicates_same_daily_structure_from_later_bar_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event()])
            run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")

            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="bar-2",
                        received_at="2026-06-04T14:05:00Z",
                        event_time="2026-06-04T14:05:00Z",
                    )
                ],
            )
            payload = run_realtime_signal_router(
                config,
                generated_at="2026-06-04T14:05:01Z",
            )
            signals = self.read_jsonl(root / "signals.jsonl")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

        self.assertEqual(len(signals), 1)
        self.assertEqual(payload["new_signal_event_count"], 0)
        self.assertIn("duplicate_structure_instance", rows[0]["blockers"])

    def test_router_ignores_market_events_before_current_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, session_started_at="2026-06-04T13:30:00Z")
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        event_id="old-session",
                        symbol="TSLA",
                        received_at="2026-06-03T20:00:01Z",
                        event_time="2026-06-03T20:00:00Z",
                        strategy_signal_intents=[],
                    ),
                    self.market_event(
                        event_id="current-session",
                        received_at="2026-06-04T14:00:01Z",
                        event_time="2026-06-04T14:00:00Z",
                    ),
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:02Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["raw_market_event_count"], 2)
            self.assertEqual(payload["current_session_market_event_count"], 1)
            self.assertEqual(payload["stale_market_event_ignored_count"], 1)
            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(signals[0]["source_market_event_id"], "current-session")

    def test_router_rebuilds_pre_epoch_signal_after_new_test_epoch_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epoch = {
                "enabled": True,
                "test_epoch_id": "unit-epoch",
                "status": "active",
                "test_started_at": "2026-06-04T14:05:00Z",
            }
            config = self.make_config(root, epoch_state=epoch)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(received_at="2026-06-04T14:00:00Z")])

            run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:06:00Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(payload["epoch_rebuilt_signal_count"], 1)
            self.assertEqual(len(signals), 2)
            self.assertTrue(signals[-1]["signal_id"].endswith("-unit-epoch"))
            self.assertTrue(signals[-1]["realtime_rebuilt_after_epoch_activation"])
            self.assertEqual(signals[-1]["original_signal_created_at"], "2026-06-04T14:00:00Z")
            self.assertEqual(signals[-1]["created_at"], "2026-06-04T14:06:00Z")

    def test_router_accepts_legacy_activated_epoch_with_activation_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            epoch = {
                "enabled": True,
                "test_epoch_id": "legacy-epoch",
                "status": "activated",
                "test_started_at": "",
                "activated_at": "2026-06-04T14:05:00Z",
            }
            config = self.make_config(root, epoch_state=epoch)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event(received_at="2026-06-04T14:00:00Z")])

            run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:06:00Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["epoch_rebuilt_signal_count"], 1)
            self.assertEqual(payload["test_epoch_status"], "active")
            self.assertEqual(payload["test_started_at"], "2026-06-04T14:05:00Z")
            self.assertEqual(signals[-1]["test_started_at"], "2026-06-04T14:05:00Z")
            self.assertTrue(signals[-1]["signal_id"].endswith("-legacy-epoch"))

    def test_replay_before_session_start_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, session_started_at="2026-06-04T14:00:00Z")
            self.write_jsonl(
                root / "market_events.jsonl",
                [self.market_event(received_at="2026-06-04T13:59:59Z")],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            rows = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["new_signal_event_count"], 0)
            self.assertIn("blocked_replay_market_event_before_session_start", rows[0]["blockers"])

    def test_auto_session_start_uses_current_regular_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, session_started_at="auto")
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(event_id="fresh", received_at="2026-06-04T13:30:01Z"),
                    self.market_event(event_id="old", received_at="2026-06-04T13:29:59Z"),
                ],
            )

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T14:00:01Z")
            rows = {row["source_market_event_id"]: row for row in self.read_jsonl(config.output_dir / LEDGER_JSONL)}

            self.assertEqual(payload["session_started_at"], "2026-06-04T13:30:00Z")
            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertIn("blocked_replay_market_event_before_session_start", rows["old"]["blockers"])

    def test_router_output_can_feed_realtime_execution_without_local_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            router_config = self.make_config(root)
            execution_config = self.make_execution_config(root)
            self.write_jsonl(root / "market_events.jsonl", [self.market_event()])

            run_realtime_signal_router(router_config, generated_at="2026-06-04T14:00:01Z")
            payload = run_realtime_execution(execution_config, generated_at="2026-06-04T14:00:02Z")
            rows = self.read_jsonl(execution_config.output_dir / EXECUTION_LEDGER_JSONL)

            self.assertEqual(payload["ready_order_count"], 1)
            self.assertTrue(payload["local_simulation_isolated"])
            self.assertFalse(rows[0]["m13_m14_gate_used_for_order"])
            self.assertFalse(rows[0]["fast_queue_used_for_order"])

    def make_config(
        self,
        root: Path,
        *,
        session_started_at: str = "2026-06-04T13:00:00Z",
        enabled_detectors: list[str] | None = None,
        allowed_runtime_ids: list[str] | None = None,
        runtime_position_multipliers: dict[str, str] | None = None,
        additional_runtime_bucket_routes: dict[str, list[str]] | None = None,
        virtual_capital_buckets: dict[str, dict] | None = None,
        epoch_state: dict | None = None,
        migration_state: dict | None = None,
    ):
        allowed_runtime_ids = allowed_runtime_ids or ["M10-PA-004-long-1d", "M10-PA-013-1d"]
        runtime_position_multipliers = runtime_position_multipliers or {
            "M10-PA-004-long-1d": "1.0",
            "M10-PA-013-1d": "0.25",
        }
        payload = {
            "stage": "M15.longbridge_realtime_signal_router",
            "title": "长桥模拟账户实时信号路由器",
            "inputs": {
                "market_events": str(root / "market_events.jsonl"),
                "signal_events": str(root / "signals.jsonl"),
            },
            "outputs": {"output_dir": str(root / "out")},
            "realtime_signal_router": {
                "session_started_at": session_started_at,
                "enabled_detectors": enabled_detectors or ["embedded_signal_intents", "pa004_followthrough_long"],
                "max_signal_events_per_run": 50,
                "allowed_runtime_ids": allowed_runtime_ids,
                "runtime_position_multipliers": runtime_position_multipliers,
            },
            "paper_account_model": {
                "equity": "10000",
                "max_total_exposure": "6000",
                "max_symbol_exposure": "1500",
                "max_risk_per_order": "20",
                "min_cash_reserve": "4000",
                "allow_fractional_shares": False,
                "allow_short_selling": False,
                "allow_options": False,
                "minimum_net_profit_after_fees": "5",
                "normal_minimum_net_profit_after_fees": "8",
                "minimum_reward_r": "1.5",
                "runtime_minimum_net_profit_after_fees": {"M10-PA-001": "12"},
                "runtime_minimum_reward_r": {"M10-PA-001": "2.0"},
                "conditional_net_profit_requires_confluence": True,
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_signal_source": False,
            },
        }
        if additional_runtime_bucket_routes:
            payload["realtime_signal_router"]["additional_runtime_bucket_routes"] = additional_runtime_bucket_routes
        if virtual_capital_buckets:
            payload["virtual_capital_buckets"] = virtual_capital_buckets
        if epoch_state is not None:
            self.write_json(root / "epoch.json", epoch_state)
            payload["inputs"]["test_epoch_state"] = str(root / "epoch.json")
        if migration_state is not None:
            self.write_json(root / "migration.json", migration_state)
            payload["inputs"]["capital_bucket_migration_state"] = str(root / "migration.json")
        config_path = root / "router_config.json"
        self.write_json(config_path, payload)
        return load_config(config_path)

    def make_execution_config(self, root: Path):
        self.write_json(
            root / "account_state.json",
            {
                "account_channel": "lb_papertrading",
                "paper_account_verified": True,
                "buying_power": "10000",
                "live_execution": False,
                "real_money_actions": False,
            },
        )
        payload = {
            "stage": "M15.longbridge_realtime_execution",
            "title": "长桥模拟账户实时执行链路",
            "inputs": {
                "realtime_signal_events": str(root / "signals.jsonl"),
                "paper_account_state": str(root / "account_state.json"),
            },
            "outputs": {"output_dir": str(root / "execution")},
            "longbridge_realtime": {
                "required_account_channel": "lb_papertrading",
                "execute_orders": False,
                "paper_trading_approval": False,
                "session_started_at": "2026-06-04T13:00:00Z",
                "allow_replay": False,
                "latency_target_ms": 1000,
                "latency_acceptable_ms": 5000,
                "allowed_runtime_ids": ["M10-PA-004-long-1d", "M10-PA-013-1d"],
            },
            "paper_account_model": {
                "equity": "10000",
                "max_total_exposure": "6000",
                "max_symbol_exposure": "1500",
                "max_risk_per_order": "20",
                "min_cash_reserve": "4000",
                "allow_fractional_shares": False,
                "allow_short_selling": False,
                "allow_options": False,
                "minimum_net_profit_after_fees": "5",
                "normal_minimum_net_profit_after_fees": "8",
                "minimum_reward_r": "1.5",
                "runtime_minimum_net_profit_after_fees": {"M10-PA-001": "12"},
                "runtime_minimum_reward_r": {"M10-PA-001": "2.0"},
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_order_source": False,
            },
        }
        config_path = root / "execution_config.json"
        self.write_json(config_path, payload)
        return load_execution_config(config_path)

    def market_event(self, **overrides: object) -> dict:
        row = {
            "event_id": "bar-1",
            "event_type": "bar_close",
            "received_at": "2026-06-04T14:00:00Z",
            "event_time": "2026-06-04T14:00:00Z",
            "symbol": "AAPL",
            "timeframe": "1d",
            "open": "100",
            "high": "105",
            "low": "99",
            "close": "104",
            "volume": "1000000",
            "strategy_signal_intents": [self.intent()],
        }
        row.update(overrides)
        return row

    def intent(self, **overrides: object) -> dict:
        row = {
            "runtime_id": "M10-PA-004-long-1d",
            "strategy_id": "M10-PA-004",
            "direction": "long",
            "order_type": "limit",
            "limit_price": "104.00",
            "stop_price": "100.00",
            "target_price": "112.00",
        }
        row.update(overrides)
        return row

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def read_jsonl(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
