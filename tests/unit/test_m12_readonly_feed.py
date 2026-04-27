from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import m12_readonly_feed_lib as MODULE


class M12ReadonlyFeedTests(unittest.TestCase):
    def test_config_scope_and_boundaries_are_locked(self) -> None:
        config = MODULE.load_readonly_feed_config()
        self.assertEqual(config.strategy_scope, ("M10-PA-001", "M10-PA-002", "M10-PA-012"))
        self.assertEqual(config.timeframes, ("1d", "1h", "15m", "5m"))
        MODULE.validate_config_boundaries(config)
        bad = _config_with(config, real_orders=True)
        with self.assertRaisesRegex(ValueError, "disabled"):
            MODULE.validate_config_boundaries(bad)

    def test_runner_uses_readonly_quote_and_kline_commands_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_path = Path(tmpdir) / "auth.json"
            auth_path.write_text(json.dumps({"auth_status": "valid_readonly_market_data"}), encoding="utf-8")
            config = _minimal_config(Path(tmpdir), auth_path)
            with (
                mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/longbridge"),
                mock.patch.object(MODULE.subprocess, "run", side_effect=_feed_responses()) as run_mock,
            ):
                manifest = MODULE.run_m12_readonly_feed(config, generated_at="2026-04-27T00:00:00Z")

        self.assertEqual(manifest["ledger_row_count"], 2)
        self.assertEqual(manifest["deferred_count"], 0)
        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(commands[0][1], "quote")
        self.assertEqual(commands[1][1], "kline")
        self.assertEqual(commands[2][1], "kline")
        for command in commands:
            self.assertIn(command[1], {"quote", "kline"})
            self.assertNotIn(command[1], MODULE.FORBIDDEN_LEDGER_KEYS)

    def test_auth_not_ready_generates_deferred_without_fake_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_path = Path(tmpdir) / "auth.json"
            auth_path.write_text(json.dumps({"auth_status": "auth_required_or_connectivity_failed"}), encoding="utf-8")
            config = _minimal_config(Path(tmpdir), auth_path)
            with mock.patch.object(MODULE.subprocess, "run") as run_mock:
                manifest = MODULE.run_m12_readonly_feed(config, generated_at="2026-04-27T00:00:00Z")
            self.assertEqual(manifest["ledger_row_count"], 0)
            self.assertEqual(manifest["deferred_count"], 1)
            run_mock.assert_not_called()

    def test_ledger_row_has_bar_close_semantics_and_no_execution_account_keys(self) -> None:
        config = MODULE.ReadonlyFeedConfig(
            title="test",
            run_id="test",
            symbols=("SPY",),
            market="US",
            timeframes=("5m",),
            strategy_scope=("M10-PA-001", "M10-PA-002", "M10-PA-012"),
            auth_preflight_path=Path("/tmp/auth.json"),
            observation_queue_path=Path("/tmp/queue.json"),
            output_dir=Path("/tmp/out"),
            paper_simulated_only=True,
            broker_connection=False,
            real_orders=False,
            live_execution=False,
        )
        row = MODULE.build_ledger_row(
            config,
            symbol="SPY",
            timeframe="5m",
            raw_bar={"time": "2026-04-27 09:35:00", "open": "1", "high": "2", "low": "1", "close": "2", "volume": "100"},
            generated_at="2026-04-27T00:00:00Z",
        )
        MODULE.validate_ledger_row(row)
        self.assertEqual(row["observation_semantics"], "regular_session_bar_close_observation_only")
        self.assertEqual(row["lineage"]["quote_snapshot_role"], "liveness_only")
        self.assertFalse(MODULE.find_forbidden_keys(row))

    def test_outputs_keep_no_live_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_path = Path(tmpdir) / "auth.json"
            auth_path.write_text(json.dumps({"auth_status": "valid_readonly_market_data"}), encoding="utf-8")
            config = _minimal_config(Path(tmpdir), auth_path)
            with (
                mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/longbridge"),
                mock.patch.object(MODULE.subprocess, "run", side_effect=_feed_responses()),
            ):
                MODULE.run_m12_readonly_feed(config, generated_at="2026-04-27T00:00:00Z")
            combined = "\n".join(path.read_text(encoding="utf-8") for path in Path(tmpdir).glob("m12_1_*"))
        lowered = combined.lower()
        self.assertIn('"broker_connection": false', lowered)
        self.assertIn('"real_orders": false', lowered)
        self.assertIn('"live_execution": false', lowered)
        self.assertNotIn("broker_connection=true", lowered)
        self.assertNotIn("real_orders=true", lowered)
        self.assertNotIn("live-ready", lowered)


def _minimal_config(tmpdir: Path, auth_path: Path) -> MODULE.ReadonlyFeedConfig:
    return MODULE.ReadonlyFeedConfig(
        title="test",
        run_id="test",
        symbols=("SPY",),
        market="US",
        timeframes=("1d", "5m"),
        strategy_scope=("M10-PA-001", "M10-PA-002", "M10-PA-012"),
        auth_preflight_path=auth_path,
        observation_queue_path=Path("/tmp/queue.json"),
        output_dir=tmpdir,
        paper_simulated_only=True,
        broker_connection=False,
        real_orders=False,
        live_execution=False,
    )


def _config_with(config: MODULE.ReadonlyFeedConfig, **overrides: object) -> MODULE.ReadonlyFeedConfig:
    payload = {
        "title": config.title,
        "run_id": config.run_id,
        "symbols": config.symbols,
        "market": config.market,
        "timeframes": config.timeframes,
        "strategy_scope": config.strategy_scope,
        "auth_preflight_path": config.auth_preflight_path,
        "observation_queue_path": config.observation_queue_path,
        "output_dir": config.output_dir,
        "paper_simulated_only": config.paper_simulated_only,
        "broker_connection": config.broker_connection,
        "real_orders": config.real_orders,
        "live_execution": config.live_execution,
    }
    payload.update(overrides)
    return MODULE.ReadonlyFeedConfig(**payload)


def _feed_responses() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(returncode=0, stdout=json.dumps([{"symbol": "SPY.US", "last": "500"}]), stderr=""),
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"time": "2026-04-27 00:00:00", "open": "500", "high": "505", "low": "499", "close": "504", "volume": "1000"}]),
            stderr="",
        ),
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"time": "2026-04-27 09:35:00", "open": "500", "high": "501", "low": "499", "close": "500.5", "volume": "100"}]),
            stderr="",
        ),
    ]


if __name__ == "__main__":
    unittest.main()
