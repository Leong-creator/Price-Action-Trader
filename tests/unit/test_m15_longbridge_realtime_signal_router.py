from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_longbridge_realtime_execution_lib import LEDGER_JSONL as EXECUTION_LEDGER_JSONL
from scripts.m15_longbridge_realtime_execution_lib import load_config as load_execution_config
from scripts.m15_longbridge_realtime_execution_lib import run_realtime_execution
from scripts.m15_longbridge_realtime_signal_router_lib import (
    LEDGER_JSONL,
    SUMMARY_JSON,
    load_config,
    run_realtime_signal_router,
)


class M15LongbridgeRealtimeSignalRouterTest(unittest.TestCase):
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
            summary_text = (config.output_dir / SUMMARY_JSON).read_text(encoding="utf-8")
            self.assertNotIn("m12_46_account_trade_ledger", summary_text)

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
                                "stop_price": "98.00",
                                "target_price": "110.00",
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

    def test_repair_auxiliary_and_shadow_intents_do_not_emit_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            self.write_jsonl(
                root / "market_events.jsonl",
                [
                    self.market_event(
                        strategy_signal_intents=[
                            self.intent(runtime_id="M10-PA-002-5m", strategy_id="M10-PA-002"),
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
                        strategy_signal_intents=[],
                    ),
                    self.market_event(
                        event_id="latest",
                        event_time="2026-06-04T20:00:00Z",
                        open="100",
                        high="105",
                        low="99",
                        close="104",
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
            self.assertGreaterEqual(int(signals[0]["quantity"]), 1)

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
                    "M10-PA-002-1d": "0.25",
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
                        (14, 5, "100.5", "102.2", "101.5", "102.0"),
                    ]
                )
            ]
            self.write_jsonl(root / "market_events.jsonl", daily_events + intraday_events)

            payload = run_realtime_signal_router(config, generated_at="2026-06-04T20:00:02Z")
            signals = self.read_jsonl(root / "signals.jsonl")
            by_runtime = {row["runtime_id"]: row for row in signals}

            self.assertEqual(payload["new_signal_event_count"], 2)
            self.assertEqual(payload["confluence_merged_support_count"], 1)
            self.assertEqual(set(by_runtime), {"M10-PA-002-1d", "M10-PA-012-5m"})
            self.assertEqual(by_runtime["M10-PA-002-1d"]["order_type"], "trigger_limit")
            self.assertEqual(by_runtime["M10-PA-002-1d"]["confluence_multiplier"], "1.5")
            self.assertEqual(by_runtime["M10-PA-002-1d"]["confluence_support_runtime_ids"], ["M12-FTD-001-baseline-1d"])
            self.assertEqual(by_runtime["M10-PA-012-5m"]["order_type"], "trigger_limit")
            self.assertTrue(all(not row["local_simulation_source"] for row in signals))

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
    ):
        allowed_runtime_ids = allowed_runtime_ids or ["M10-PA-004-long-1d", "M10-PA-013-1d"]
        runtime_position_multipliers = runtime_position_multipliers or {
            "M10-PA-004-long-1d": "1.0",
            "M10-PA-013-1d": "1.0",
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
                "minimum_net_profit_after_fees": "0",
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_signal_source": False,
            },
        }
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
