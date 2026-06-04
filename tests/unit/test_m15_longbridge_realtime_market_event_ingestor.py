from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.m15_longbridge_realtime_market_event_ingestor_lib import (
    LEDGER_JSONL,
    SUMMARY_JSON,
    RealtimeMarketEventIngestorConfig,
    build_kline_args,
    load_config,
    run_realtime_market_event_ingestor,
)
from scripts.m15_longbridge_realtime_signal_router_lib import load_config as load_router_config
from scripts.m15_longbridge_realtime_signal_router_lib import run_realtime_signal_router


class M15LongbridgeRealtimeMarketEventIngestorTest(unittest.TestCase):
    def test_ingestor_uses_readonly_kline_and_writes_market_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            commands: list[list[str]] = []

            def fake_runner(cli_path: str, args: list[str], timeout: int):
                commands.append(args)
                self.assertEqual(cli_path, "/usr/bin/longbridge")
                self.assertEqual(timeout, 6)
                return self.kline_rows()

            payload = run_realtime_market_event_ingestor(
                config,
                generated_at="2026-06-04T14:00:01Z",
                command_runner=fake_runner,
                cli_path="/usr/bin/longbridge",
            )
            events = self.read_jsonl(root / "market_events.jsonl")

            self.assertEqual(payload["new_market_event_count"], 8)
            self.assertEqual(len(events), 8)
            self.assertEqual(events[0]["quote_source"], "longbridge_quote_readonly")
            self.assertFalse(events[0]["local_simulation_source"])
            self.assertEqual(commands[0][0], "kline")
            self.assertEqual(commands[0][1], "AAPL.US")
            for command in commands:
                self.assertNotIn("order", command)
                self.assertNotIn("assets", command)
                self.assertNotIn("positions", command)

    def test_cli_missing_defers_without_fake_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            with mock.patch("scripts.m15_longbridge_realtime_market_event_ingestor_lib.shutil.which", return_value=None):
                payload = run_realtime_market_event_ingestor(config, generated_at="2026-06-04T14:00:01Z")

            self.assertEqual(payload["new_market_event_count"], 0)
            self.assertEqual(payload["deferred_count"], 1)
            self.assertFalse((root / "market_events.jsonl").read_text(encoding="utf-8").strip())
            self.assertIn("没有生成假行情事件", payload["plain_language_result"])

    def test_ingestor_deduplicates_existing_market_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, symbols=("AAPL",), timeframes=("1d",))

            run_realtime_market_event_ingestor(
                config,
                generated_at="2026-06-04T14:00:01Z",
                command_runner=lambda *_args: self.kline_rows(),
                cli_path="/usr/bin/longbridge",
            )
            payload = run_realtime_market_event_ingestor(
                config,
                generated_at="2026-06-04T14:00:02Z",
                command_runner=lambda *_args: self.kline_rows(),
                cli_path="/usr/bin/longbridge",
            )
            events = self.read_jsonl(root / "market_events.jsonl")
            ledger = self.read_jsonl(config.output_dir / LEDGER_JSONL)

            self.assertEqual(payload["new_market_event_count"], 0)
            self.assertEqual(len(events), 2)
            self.assertEqual(ledger[0]["ingest_status"], "duplicate_market_event_skipped")

    def test_readonly_guard_blocks_forbidden_command_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            args = build_kline_args(config, symbol="AAPL", timeframe="5m")

            self.assertEqual(args[0], "kline")
            self.assertIn("--session", args)
            with self.assertRaises(ValueError):
                build_kline_args(config, symbol="AAPL", timeframe="2m")

    def test_market_events_can_feed_router_without_local_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ingestor_config = self.make_config(root, symbols=("AAPL",), timeframes=("1d",))
            router_config = self.make_router_config(root)
            (root / "m12_46_account_trade_ledger.jsonl").write_text(
                json.dumps({"runtime_id": "M10-PA-004-long-1d", "event_type": "close"}) + "\n",
                encoding="utf-8",
            )

            run_realtime_market_event_ingestor(
                ingestor_config,
                generated_at="2026-06-04T20:00:01Z",
                command_runner=lambda *_args: [
                    {"time": "2026-06-03T20:00:00Z", "open": "95", "high": "98", "low": "94", "close": "96", "volume": "100"},
                    {"time": "2026-06-04T20:00:00Z", "open": "100", "high": "105", "low": "99", "close": "104", "volume": "120"},
                ],
                cli_path="/usr/bin/longbridge",
            )
            payload = run_realtime_signal_router(router_config, generated_at="2026-06-04T20:00:02Z")
            signals = self.read_jsonl(root / "signals.jsonl")

            self.assertEqual(payload["new_signal_event_count"], 1)
            self.assertEqual(signals[0]["runtime_id"], "M10-PA-004-long-1d")
            self.assertFalse(signals[0]["local_simulation_source"])
            summary_text = (ingestor_config.output_dir / SUMMARY_JSON).read_text(encoding="utf-8")
            self.assertNotIn("m12_46_account_trade_ledger", summary_text)

    def test_hot_symbols_and_cursor_rotate_large_universe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(
                root,
                symbols=("AAPL", "MSFT", "NVDA", "XLU"),
                timeframes=("1d",),
                hot_symbols=("NVDA",),
                max_symbols_per_cycle=2,
            )
            first_commands: list[list[str]] = []
            second_commands: list[list[str]] = []

            first = run_realtime_market_event_ingestor(
                config,
                generated_at="2026-06-04T14:00:01Z",
                command_runner=lambda _cli, args, _timeout: first_commands.append(args) or self.kline_rows(),
                cli_path="/usr/bin/longbridge",
            )
            second = run_realtime_market_event_ingestor(
                config,
                generated_at="2026-06-04T14:00:02Z",
                command_runner=lambda _cli, args, _timeout: second_commands.append(args) or self.kline_rows(),
                cli_path="/usr/bin/longbridge",
            )

            self.assertEqual(first["configured_symbol_count"], 4)
            self.assertEqual(first["cycle_symbol_count"], 2)
            self.assertEqual(first["cycle_symbols"], ["NVDA", "AAPL"])
            self.assertEqual(second["cycle_symbols"], ["NVDA", "MSFT"])
            self.assertEqual([command[1] for command in first_commands], ["NVDA.US", "AAPL.US"])
            self.assertEqual([command[1] for command in second_commands], ["NVDA.US", "MSFT.US"])

    def make_config(
        self,
        root: Path,
        *,
        symbols: tuple[str, ...] = ("AAPL", "XLU"),
        timeframes: tuple[str, ...] = ("1d", "5m"),
        hot_symbols: tuple[str, ...] = (),
        max_symbols_per_cycle: int = 147,
    ) -> RealtimeMarketEventIngestorConfig:
        payload = {
            "stage": "M15.longbridge_realtime_market_event_ingestor",
            "title": "长桥实时行情事件采集器",
            "outputs": {
                "output_dir": str(root / "out"),
                "market_events": str(root / "market_events.jsonl"),
            },
            "longbridge_market_data": {
                "session_started_at": "2026-06-04T13:00:00Z",
                "market": "US",
                "symbols": list(symbols),
                "hot_symbols": list(hot_symbols),
                "use_seed_universe": False,
                "symbol_limit": 147,
                "max_symbols_per_cycle": max_symbols_per_cycle,
                "symbol_cursor_path": str(root / "cursor.json"),
                "timeframes": list(timeframes),
                "kline_count": 2,
                "watch_interval_seconds": 1,
                "cli_timeout_seconds": 6,
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "account_or_order_commands": False,
                "local_simulation_as_market_source": False,
            },
        }
        path = root / "ingestor_config.json"
        self.write_json(path, payload)
        return load_config(path)

    def make_router_config(self, root: Path):
        payload = {
            "stage": "M15.longbridge_realtime_signal_router",
            "title": "长桥模拟账户实时信号路由器",
            "inputs": {
                "market_events": str(root / "market_events.jsonl"),
                "signal_events": str(root / "signals.jsonl"),
            },
            "outputs": {"output_dir": str(root / "router_out")},
            "realtime_signal_router": {
                "session_started_at": "2026-06-04T13:00:00Z",
                "enabled_detectors": ["pa004_followthrough_long"],
                "max_signal_events_per_run": 10,
                "allowed_runtime_ids": ["M10-PA-004-long-1d"],
                "runtime_position_multipliers": {"M10-PA-004-long-1d": "1.0"},
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
            "fee_model": {
                "commission_per_order_side": "1.99",
                "regulatory_fee_per_sell_order": "0.02",
            },
            "hard_boundaries": {
                "paper_simulated_only": True,
                "live_execution": False,
                "real_money_actions": False,
                "local_simulation_as_signal_source": False,
            },
        }
        path = root / "router_config.json"
        self.write_json(path, payload)
        return load_router_config(path)

    def kline_rows(self) -> list[dict[str, str]]:
        return [
            {"time": "2026-06-04T14:00:00Z", "open": "100", "high": "102", "low": "99", "close": "101", "volume": "1000"},
            {"time": "2026-06-04T14:05:00Z", "open": "101", "high": "103", "low": "100", "close": "102", "volume": "1100"},
        ]

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def read_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
