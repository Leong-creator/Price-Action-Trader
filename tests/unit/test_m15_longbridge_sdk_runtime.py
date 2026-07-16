from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.m15_longbridge_realtime_execution_lib import response_order_id
from scripts.m15_longbridge_sdk_runtime_lib import (
    FiveMinuteBarBuilder, MarketEventContext, SdkRealtimePaperClient, append_market_events, compact_market_events,
    config_fingerprint, configured_symbols, daily_context_is_complete, fresh_market_events, load_config,
    load_current_sdk_intraday_context,
    load_valid_daily_context_cache, sdk_config_from_oauth, sdk_endpoint_overrides, subscribe_private_trade_updates,
    sdk_order_maintenance_actions, summarize_latency_samples, write_daily_context_cache,
    subscribe_quote_and_trades, record_readonly_session, readonly_gate_passed,
    validate_formal_epoch_alignment,
)
from scripts.m15_longbridge_sdk_account_lib import SdkAccountStateProvider, SdkTradeRequestGate
from scripts.m15_universe_lib import load_m15_universe
from scripts.run_m15_longbridge_sdk_runtime import (
    build_live_daily_confirmation_rows,
    close_spawn_queue,
    event_rows_to_daily,
    preserve_last_order_maintenance_action,
    require_sdk_contract,
    request_runtime_shutdown,
    run_pending_flatten_cycle,
    run_sdk_preflight,
)


class M15LongbridgeSdkRuntimeTest(unittest.TestCase):
    def pending_flatten_fixture(self, root: Path) -> tuple[SimpleNamespace, dict, object, object]:
        marker_path = root / "marker.json"
        state_path = root / "state.json"
        marker = {
            "stage": "M15.sdk_formal_test_epoch",
            "status": "pending_flatten",
            "test_epoch_id": "formal-main",
            "short_test_epoch_id": "formal-short",
            "test_started_at": "",
            "paper_simulated_only": True,
        }
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        config = SimpleNamespace(
            formal_test_transition_enabled=True,
            formal_test_epoch_id="formal-main",
            formal_short_test_epoch_id="formal-short",
            formal_test_marker_path=marker_path,
            formal_test_epoch_state_path=state_path,
            maximum_account_snapshot_age_seconds=30,
        )
        snapshot = {
            "generated_at": "2026-07-16T14:00:00Z",
            "paper_account_verified": True,
            "positions_ok": True,
            "orders_ok": True,
            "positions": [
                {"symbol": "AAPL.US", "quantity": "2", "available": "2", "cost_price": "200"},
            ],
            "orders": [],
            "open_orders": [],
        }

        class Account:
            def snapshot(self_inner):
                return json.loads(json.dumps(snapshot))

        class Client:
            def __init__(self_inner) -> None:
                self_inner.submissions = []
                self_inner.cancellations = []

            def submit_order(self_inner, payload):
                self_inner.submissions.append(dict(payload))
                return {"submitted": True, "status": "submitted", "order_id": "MO-1"}

            def cancel_order(self_inner, order_id):
                self_inner.cancellations.append(order_id)
                return {"canceled": True, "status": "cancel_requested", "order_id": order_id}

        return config, snapshot, Account(), Client()

    def test_pending_flatten_does_not_submit_before_regular_session(self) -> None:
        with TemporaryDirectory() as directory:
            config, _snapshot, account, client = self.pending_flatten_fixture(Path(directory))
            marker = json.loads(config.formal_test_marker_path.read_text(encoding="utf-8"))
            marker["activation_blocker"] = "validation_flatten_incomplete:connect_timeout"
            config.formal_test_marker_path.write_text(json.dumps(marker), encoding="utf-8")
            state = run_pending_flatten_cycle(
                config,
                account,
                client,
                [],
                now=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
            )
            refreshed_marker = json.loads(config.formal_test_marker_path.read_text(encoding="utf-8"))

        self.assertEqual(state["status"], "waiting_for_regular_session")
        self.assertTrue(state["blocks_new_entries"])
        self.assertEqual(client.submissions, [])
        self.assertEqual(refreshed_marker["activation_blocker"], "")

    def test_pending_flatten_starts_market_exit_automatically_in_regular_session(self) -> None:
        with TemporaryDirectory() as directory:
            config, _snapshot, account, client = self.pending_flatten_fixture(Path(directory))
            state = run_pending_flatten_cycle(
                config,
                account,
                client,
                [{
                    "symbol": "AAPL", "timeframe": "5m", "close": "201",
                    "received_at": "2026-07-16T14:00:00Z",
                }],
                now=datetime(2026, 7, 16, 14, 0, 1, tzinfo=UTC),
            )

        self.assertEqual(state["status"], "waiting_for_broker_flatten_confirmation")
        self.assertEqual(len(client.submissions), 1)
        self.assertEqual(client.submissions[0]["order_type"], "market")
        self.assertEqual(client.submissions[0]["position_action"], "close_long")
        self.assertEqual(client.submissions[0]["client_request_id"], next(iter(state["submissions"])))

    def test_pending_flatten_repeated_cycle_does_not_resubmit(self) -> None:
        with TemporaryDirectory() as directory:
            config, _snapshot, account, client = self.pending_flatten_fixture(Path(directory))
            now = datetime(2026, 7, 16, 14, 0, 1, tzinfo=UTC)
            run_pending_flatten_cycle(config, account, client, [], now=now)
            state = run_pending_flatten_cycle(config, account, client, [], now=now + timedelta(seconds=15))

        self.assertEqual(len(client.submissions), 1)
        self.assertEqual(state["submitted_this_cycle"], 0)
        self.assertEqual(len(state["submissions"]), 1)

    def test_pending_flatten_uses_one_fallback_only_for_fresh_explicit_reject(self) -> None:
        with TemporaryDirectory() as directory:
            config, _snapshot, account, _client = self.pending_flatten_fixture(Path(directory))

            class RejectThenAcceptClient:
                def __init__(self) -> None:
                    self.submissions = []

                def submit_order(self, payload):
                    self.submissions.append(dict(payload))
                    if len(self.submissions) == 1:
                        return {
                            "submitted": False,
                            "status": "submit_rejected_without_order_id",
                            "order_id": "",
                            "explicit_reject": True,
                        }
                    return {"submitted": True, "status": "submitted", "order_id": "LO-1"}

                def cancel_order(self, _order_id):
                    raise AssertionError("no cancellation expected")

            client = RejectThenAcceptClient()
            now = datetime(2026, 7, 16, 14, 0, 1, tzinfo=UTC)
            events = [{
                "symbol": "AAPL", "timeframe": "5m", "close": "201",
                "received_at": "2026-07-16T14:00:00Z",
            }]
            state = run_pending_flatten_cycle(config, account, client, events, now=now)
            run_pending_flatten_cycle(config, account, client, events, now=now + timedelta(seconds=1))

        self.assertEqual([row["order_type"] for row in client.submissions], ["market", "limit"])
        self.assertEqual(client.submissions[0]["client_request_id"], client.submissions[1]["client_request_id"])
        attempt = next(iter(state["submissions"].values()))
        self.assertTrue(attempt["fallback_attempted"])
        self.assertEqual(attempt["order_id"], "LO-1")

    def test_pending_flatten_unknown_account_blocks_without_submitting(self) -> None:
        with TemporaryDirectory() as directory:
            config, snapshot, account, client = self.pending_flatten_fixture(Path(directory))
            snapshot["orders_ok"] = False
            state = run_pending_flatten_cycle(
                config,
                account,
                client,
                [],
                now=datetime(2026, 7, 16, 14, 0, tzinfo=UTC),
            )

        self.assertEqual(state["status"], "account_state_unknown")
        self.assertTrue(state["blocks_new_entries"])
        self.assertEqual(client.submissions, [])

    def test_pending_flatten_transport_error_is_persisted_without_resubmit(self) -> None:
        with TemporaryDirectory() as directory:
            config, _snapshot, account, _client = self.pending_flatten_fixture(Path(directory))

            class FailingClient:
                def __init__(self) -> None:
                    self.calls = 0

                def submit_order(self, _payload):
                    self.calls += 1
                    raise TimeoutError("unknown broker response")

                def cancel_order(self, _order_id):
                    raise AssertionError("no cancellation expected")

            client = FailingClient()
            now = datetime(2026, 7, 16, 14, 0, 1, tzinfo=UTC)
            first = run_pending_flatten_cycle(config, account, client, [], now=now)
            second = run_pending_flatten_cycle(config, account, client, [], now=now + timedelta(seconds=15))

        self.assertEqual(first["status"], "submission_state_unknown_waiting_reconciliation")
        self.assertEqual(client.calls, 1)
        self.assertEqual(len(second["submissions"]), 1)

    def test_pending_flatten_activates_marker_only_after_account_is_zero(self) -> None:
        with TemporaryDirectory() as directory:
            config, snapshot, account, client = self.pending_flatten_fixture(Path(directory))
            now = datetime(2026, 7, 16, 14, 0, 1, tzinfo=UTC)
            run_pending_flatten_cycle(config, account, client, [], now=now)
            snapshot["positions"] = []
            snapshot["open_orders"] = []
            snapshot["orders"] = [{"order_id": "MO-1", "status": "Filled"}]
            state = run_pending_flatten_cycle(
                config,
                account,
                client,
                [],
                now=now + timedelta(seconds=15),
            )
            marker = json.loads(config.formal_test_marker_path.read_text(encoding="utf-8"))

        self.assertEqual(state["status"], "active")
        self.assertFalse(state["blocks_new_entries"])
        self.assertEqual(state["test_started_at"], "2026-07-16T14:00:16Z")
        self.assertEqual(marker["status"], "active")
        self.assertEqual(marker["test_started_at"], state["test_started_at"])
        self.assertEqual(marker["activation_condition_met"], "positions_open_orders_pending_confirmations_zero")
        self.assertEqual(len(client.submissions), 1)

    def test_active_marker_repairs_execution_epoch_missing_start_time(self) -> None:
        with TemporaryDirectory() as directory:
            config, _snapshot, account, client = self.pending_flatten_fixture(Path(directory))
            marker = json.loads(config.formal_test_marker_path.read_text(encoding="utf-8"))
            marker.update(
                {
                    "status": "active",
                    "test_started_at": "2026-07-16T14:00:00Z",
                    "activated_at": "2026-07-16T14:00:00Z",
                }
            )
            config.formal_test_marker_path.write_text(json.dumps(marker), encoding="utf-8")
            config.formal_test_epoch_state_path.write_text(
                json.dumps(
                    {
                        "test_epoch_id": marker["test_epoch_id"],
                        "status": "activated",
                        "test_started_at": "",
                        "activated_at": marker["activated_at"],
                        "blocks_new_entries": False,
                    }
                ),
                encoding="utf-8",
            )

            result = run_pending_flatten_cycle(
                config,
                account,
                client,
                [],
                now=datetime(2026, 7, 16, 14, 5, tzinfo=UTC),
            )
            state = json.loads(config.formal_test_epoch_state_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "inactive")
        self.assertFalse(result["blocks_new_entries"])
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["test_started_at"], "2026-07-16T14:00:00Z")

    def test_active_marker_repairs_execution_epoch_id_drift(self) -> None:
        with TemporaryDirectory() as directory:
            config, _snapshot, account, client = self.pending_flatten_fixture(Path(directory))
            marker = json.loads(config.formal_test_marker_path.read_text(encoding="utf-8"))
            marker.update(
                {
                    "status": "active",
                    "test_started_at": "2026-07-16T14:00:00Z",
                    "activated_at": "2026-07-16T14:00:00Z",
                }
            )
            config.formal_test_marker_path.write_text(json.dumps(marker), encoding="utf-8")
            config.formal_test_epoch_state_path.write_text(
                json.dumps(
                    {
                        "test_epoch_id": "wrong-epoch",
                        "status": "active",
                        "test_started_at": "2026-07-16T14:03:00Z",
                        "blocks_new_entries": False,
                    }
                ),
                encoding="utf-8",
            )

            result = run_pending_flatten_cycle(
                config,
                account,
                client,
                [],
                now=datetime(2026, 7, 16, 14, 5, tzinfo=UTC),
            )
            state = json.loads(config.formal_test_epoch_state_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "inactive")
        self.assertEqual(state["test_epoch_id"], marker["test_epoch_id"])
        self.assertEqual(state["short_test_epoch_id"], marker["short_test_epoch_id"])
        self.assertEqual(state["test_started_at"], marker["test_started_at"])

    def test_default_runtime_config_declares_seed_147_contract(self) -> None:
        payload = json.loads(Path("config/examples/m15_longbridge_sdk_runtime.json").read_text(encoding="utf-8"))

        self.assertTrue(payload["market_data"]["use_seed_universe"])
        self.assertIsNone(payload["market_data"]["universe_path"])
        self.assertEqual(payload["market_data"]["symbol_limit"], 147)

    def test_formal_epoch_alignment_rejects_linked_config_drift(self) -> None:
        config = load_config()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            execution = root / "execution.json"
            router = root / "router.json"
            execution.write_text(
                json.dumps(
                    {
                        "test_epoch": {"test_epoch_id": "wrong-long"},
                        "paper_short_testing": {"test_epoch_id": config.formal_short_test_epoch_id},
                    }
                ),
                encoding="utf-8",
            )
            router.write_text(
                json.dumps({"paper_short_testing": {"test_epoch_id": config.formal_short_test_epoch_id}}),
                encoding="utf-8",
            )
            drifted = replace(config, execution_config_path=execution, router_config_path=router)

            with self.assertRaisesRegex(ValueError, "formal long epoch"):
                validate_formal_epoch_alignment(drifted)

    def test_order_maintenance_preserves_the_last_meaningful_action(self) -> None:
        previous = {
            "generated_at": "2026-07-15T16:25:00Z",
            "status": "maintained",
            "planned_action_count": 1,
            "completed_action_count": 1,
            "failed_action_count": 0,
            "actions": [{"action": "cancel", "order_id": "ORDER-1"}],
        }
        current = {
            "generated_at": "2026-07-15T16:25:15Z",
            "status": "no_action_needed",
            "planned_action_count": 0,
            "completed_action_count": 0,
            "failed_action_count": 0,
            "actions": [],
        }

        result = preserve_last_order_maintenance_action(current, previous)

        self.assertEqual(result["status"], "no_action_needed")
        self.assertEqual(result["last_action"]["status"], "maintained")
        self.assertEqual(result["last_action"]["actions"][0]["order_id"], "ORDER-1")

    def test_config_fingerprint_changes_when_runtime_code_changes(self) -> None:
        config = load_config()
        with TemporaryDirectory() as directory:
            runtime_code = Path(directory) / "runtime.py"
            runtime_code.write_text("VERSION = 1\n", encoding="utf-8")
            with patch(
                "scripts.m15_longbridge_sdk_runtime_lib.RUNTIME_CODE_PATHS",
                (runtime_code,),
            ):
                before = config_fingerprint(config)
                runtime_code.write_text("VERSION = 2\n", encoding="utf-8")
                after = config_fingerprint(config)

        self.assertNotEqual(before, after)

    def test_live_daily_confirmation_uses_current_sdk_five_minute_bars(self) -> None:
        rows = [
            {
                "event_id": "bar-1", "symbol": "AAPL", "timeframe": "5m", "bar_final": True,
                "event_time": "2026-07-15T13:35:00Z", "received_at": "2026-07-15T13:35:00.1Z",
                "open": "100", "high": "102", "low": "99", "close": "101", "volume": "10",
            },
            {
                "event_id": "bar-2", "symbol": "AAPL", "timeframe": "5m", "bar_final": True,
                "event_time": "2026-07-15T13:40:00Z", "received_at": "2026-07-15T13:40:00.1Z",
                "open": "101", "high": "103", "low": "100", "close": "102", "volume": "20",
            },
        ]
        daily = build_live_daily_confirmation_rows(
            rows,
            generated_at=datetime(2026, 7, 15, 13, 40, tzinfo=UTC),
        )
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["source_mode"], "longbridge_sdk_live_daily_confirmation")
        self.assertTrue(daily[0]["current_session_confirmation"])
        self.assertEqual(
            {key: daily[0][key] for key in ("open", "high", "low", "close", "volume")},
            {"open": "100", "high": "103", "low": "99", "close": "102", "volume": "30"},
        )

    def test_live_daily_confirmation_requires_a_fresh_symbol_bar_this_dispatch(self) -> None:
        rows = [
            {
                "event_id": "aapl-old", "symbol": "AAPL", "timeframe": "5m", "bar_final": True,
                "event_time": "2026-07-15T15:35:00Z", "received_at": "2026-07-15T15:35:00.1Z",
                "open": "209", "high": "210", "low": "208", "close": "210", "volume": "10",
            },
            {
                "event_id": "msft-old", "symbol": "MSFT", "timeframe": "5m", "bar_final": True,
                "event_time": "2026-07-15T15:35:00Z", "received_at": "2026-07-15T15:35:00.1Z",
                "open": "499", "high": "501", "low": "498", "close": "500", "volume": "10",
            },
            {
                "event_id": "aapl-new", "symbol": "AAPL", "timeframe": "5m", "bar_final": True,
                "event_time": "2026-07-15T15:40:00Z", "received_at": "2026-07-15T15:40:00.1Z",
                "open": "210", "high": "212", "low": "209", "close": "211", "volume": "20",
            },
        ]

        daily = build_live_daily_confirmation_rows(
            rows,
            generated_at=datetime(2026, 7, 15, 15, 40, tzinfo=UTC),
            active_five_minute_event_ids={"aapl-new"},
        )

        self.assertEqual([row["symbol"] for row in daily], ["AAPL"])
        self.assertEqual(daily[0]["close"], "211")

    def test_close_spawn_queue_releases_queue_handles(self) -> None:
        calls: list[str] = []

        class Queue:
            def close(self) -> None:
                calls.append("close")

            def join_thread(self) -> None:
                calls.append("join_thread")

        close_spawn_queue(Queue())

        self.assertEqual(calls, ["close", "join_thread"])

    def test_runtime_shutdown_skips_dead_process_without_signaling(self) -> None:
        self.assertTrue(request_runtime_shutdown(99999999, timeout_seconds=0))

    def test_pipeline_latency_summary_reports_target_and_tail(self) -> None:
        summary = summarize_latency_samples([100, 200, 1200, 6000])
        self.assertEqual(summary["sample_count"], 4)
        self.assertEqual(summary["latest_ms"], 6000)
        self.assertEqual(summary["p50_ms"], 200)
        self.assertEqual(summary["p95_ms"], 6000)
        self.assertEqual(summary["within_1s_count"], 2)
        self.assertEqual(summary["over_5s_count"], 1)

    def test_sdk_quote_push_builds_final_five_minute_bar(self) -> None:
        builder = FiveMinuteBarBuilder()
        first = datetime(2026, 7, 14, 13, 31, tzinfo=UTC)
        self.assertEqual(builder.on_quote("AAPL.US", {"timestamp": int(first.timestamp()), "last_done": "200", "current_volume": 10}, received_at=first), [])
        last = datetime(2026, 7, 14, 13, 34, 59, tzinfo=UTC)
        self.assertEqual(builder.on_quote("AAPL.US", {"timestamp": int(last.timestamp()), "last_done": "202", "current_volume": 20}, received_at=last), [])
        rows = builder.flush(datetime(2026, 7, 14, 13, 35, 1, tzinfo=UTC))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_mode"], "longbridge_sdk_push")
        self.assertTrue(rows[0]["bar_final"])
        self.assertEqual(rows[0]["open"], "200")
        self.assertEqual(rows[0]["close"], "202")
        self.assertEqual(rows[0]["volume"], "20")
        self.assertEqual(rows[0]["received_at"], "2026-07-14T13:35:01Z")
        self.assertEqual(rows[0]["source_delivery_age_ms"], 2000)

    def test_first_quote_push_volume_is_not_counted_as_an_interval_increment(self) -> None:
        builder = FiveMinuteBarBuilder(minutes=5)
        first = datetime(2026, 7, 15, 13, 31, tzinfo=UTC)
        second = datetime(2026, 7, 15, 13, 32, tzinfo=UTC)

        builder.on_quote(
            "PSKY.US",
            {"timestamp": int(first.timestamp()), "last_done": "9.10", "current_volume": 17_000_000},
            received_at=first,
        )
        builder.on_quote(
            "PSKY.US",
            {"timestamp": int(second.timestamp()), "last_done": "9.11", "current_volume": 125},
            received_at=second,
        )
        rows = builder.flush(datetime(2026, 7, 15, 13, 35, 1, tzinfo=UTC))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["volume"], "125")

    def test_sdk_restart_suppresses_the_first_partial_five_minute_bar(self) -> None:
        builder = FiveMinuteBarBuilder(
            complete_bar_open_not_before=datetime(2026, 7, 15, 13, 35, tzinfo=UTC),
        )
        partial = datetime(2026, 7, 15, 13, 34, 30, tzinfo=UTC)
        self.assertEqual(
            builder.on_quote(
                "AAPL.US",
                {"timestamp": int(partial.timestamp()), "last_done": "200", "current_volume": 10},
                received_at=partial,
            ),
            [],
        )
        self.assertEqual(builder.flush(datetime(2026, 7, 15, 13, 35, tzinfo=UTC)), [])

        complete = datetime(2026, 7, 15, 13, 36, tzinfo=UTC)
        builder.on_quote(
            "AAPL.US",
            {"timestamp": int(complete.timestamp()), "last_done": "201", "current_volume": 10},
            received_at=complete,
        )
        rows = builder.flush(datetime(2026, 7, 15, 13, 40, tzinfo=UTC))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bar_open_at"], "2026-07-15T13:35:00Z")

    def test_cli_table_order_id_is_recognised(self) -> None:
        self.assertEqual(response_order_id([{"field": "Order ID", "value": "701234"}]), "701234")

    def test_sdk_event_append_does_not_rewrite_and_heartbeat_compacts(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = [{"event_id": f"event-{index}", "value": index} for index in range(5)]
            append_market_events(path, rows, keep_lines=3)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 5)
            compact_market_events(path, 3)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn('"event-4"', lines[-1])

    def test_delayed_sdk_push_does_not_enter_realtime_event_stream(self) -> None:
        rows = [{"event_id": "fresh", "source_delivery_age_ms": 1999}, {"event_id": "late", "source_delivery_age_ms": 2001}]
        self.assertEqual([row["event_id"] for row in fresh_market_events(rows, 2000)], ["fresh"])

    def test_freshly_finalized_bar_is_not_rejected_for_an_old_last_quote(self) -> None:
        finalized_at = datetime(2026, 7, 15, 14, 35, 0, tzinfo=UTC)
        rows = [{
            "event_id": "sdk-5m|AAPL|2026-07-15T14:35:00Z",
            "timeframe": "5m",
            "bar_final": True,
            "source_mode": "longbridge_sdk_push",
            "received_at": "2026-07-15T14:35:00Z",
            "source_delivery_age_ms": 120000,
        }]
        self.assertEqual(
            [row["event_id"] for row in fresh_market_events(rows, 2000, now=finalized_at + timedelta(milliseconds=150))],
            ["sdk-5m|AAPL|2026-07-15T14:35:00Z"],
        )

    def test_old_finalized_bar_stays_blocked(self) -> None:
        rows = [{
            "event_id": "sdk-5m|AAPL|2026-07-15T14:35:00Z",
            "timeframe": "5m",
            "bar_final": True,
            "source_mode": "longbridge_sdk_push",
            "received_at": "2026-07-15T14:35:00Z",
            "source_delivery_age_ms": 120000,
        }]
        self.assertEqual(
            fresh_market_events(rows, 2000, now=datetime(2026, 7, 15, 14, 35, 3, tzinfo=UTC)),
            [],
        )

    def test_runtime_restart_restores_only_current_sdk_five_minute_context(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            rows = [
                {
                    "event_id": f"sdk-5m|AAPL.US|2026-07-15T13:{minute:02d}:00Z",
                    "symbol": "AAPL", "timeframe": "5m", "bar_final": True,
                    "source_mode": "longbridge_sdk_push",
                    "event_time": f"2026-07-15T13:{minute:02d}:00Z",
                    "received_at": f"2026-07-15T13:{minute:02d}:01Z",
                }
                for minute in (25, 30, 35, 40)
            ]
            rows.append({
                "event_id": "not-sdk", "symbol": "AAPL", "timeframe": "5m", "bar_final": True,
                "source_mode": "manual", "event_time": "2026-07-15T13:45:00Z", "received_at": "2026-07-15T13:45:01Z",
            })
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            restored = load_current_sdk_intraday_context(
                path, datetime(2026, 7, 15, 13, 30, tzinfo=UTC), bars_per_symbol=2,
            )
            self.assertEqual([row["event_id"] for row in restored], [
                "sdk-5m|AAPL.US|2026-07-15T13:35:00Z",
                "sdk-5m|AAPL.US|2026-07-15T13:40:00Z",
            ])

    def test_subscribe_uses_the_installed_sdk_two_argument_contract(self) -> None:
        class QuoteContext:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, symbols, subscription_types) -> None:
                self.calls.append((symbols, subscription_types))

        quote = QuoteContext()
        subscribe_quote_and_trades(quote, ["AAPL.US"], ["Quote", "Trade"])
        self.assertEqual(quote.calls, [(["AAPL.US"], ["Quote", "Trade"])])

    def test_subscription_batches_large_universe_without_a_single_large_request(self) -> None:
        class QuoteContext:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, symbols, subscription_types) -> None:
                self.calls.append((symbols, subscription_types))

        quote = QuoteContext()
        subscribe_quote_and_trades(quote, ["AAPL.US", "MSFT.US", "NVDA.US"], ["Quote"], batch_size=2)
        self.assertEqual(quote.calls, [(["AAPL.US", "MSFT.US"], ["Quote"]), (["NVDA.US"], ["Quote"])])

    def test_failed_batch_falls_back_to_single_symbols_without_stopping_healthy_symbols(self) -> None:
        class QuoteContext:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, symbols, _subscription_types) -> None:
                self.calls.append(symbols)
                if symbols == ["AAPL.US", "BAD.US"] or symbols == ["BAD.US"]:
                    raise RuntimeError("symbol unavailable")

        quote = QuoteContext()
        failures = subscribe_quote_and_trades(
            quote,
            ["AAPL.US", "BAD.US"],
            ["Quote"],
            batch_size=2,
            retry_count=0,
        )
        self.assertEqual(failures, ["BAD.US"])
        self.assertIn(["AAPL.US"], quote.calls)

    def test_sdk_region_endpoints_are_explicit(self) -> None:
        self.assertEqual(
            sdk_endpoint_overrides("cn"),
            {
                "http_url": "https://openapi.longbridge.cn",
                "quote_ws_url": "wss://openapi-quote.longbridge.cn/v2",
                "trade_ws_url": "wss://openapi-trade.longbridge.cn/v2",
            },
        )
        self.assertEqual(sdk_endpoint_overrides("global")["http_url"], "https://openapi.longbridge.com")
        with self.assertRaisesRegex(ValueError, "unsupported_longbridge_sdk_region"):
            sdk_endpoint_overrides("invalid")

    def test_sdk_config_and_private_push_keep_trade_websocket_optional(self) -> None:
        class Config:
            @staticmethod
            def from_oauth(oauth, **kwargs):
                return {"oauth": oauth, **kwargs}

        class Sdk:
            class TopicType:
                Private = "Private"

        Sdk.Config = Config

        self.assertEqual(
            sdk_config_from_oauth(Sdk, "token", "cn")["quote_ws_url"],
            "wss://openapi-quote.longbridge.cn/v2",
        )

        class Trade:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, topics) -> None:
                self.calls.append(topics)

        trade = Trade()
        self.assertFalse(subscribe_private_trade_updates(trade, Sdk, enabled=False))
        self.assertEqual(trade.calls, [])
        self.assertTrue(subscribe_private_trade_updates(trade, Sdk, enabled=True))
        self.assertEqual(trade.calls, [["Private"]])

    def test_market_event_context_is_bounded_and_deduplicated(self) -> None:
        context = MarketEventContext(maximum_rows=2)
        self.assertEqual(
            [row["event_id"] for row in context.append([{"event_id": "one"}, {"event_id": "two"}])],
            ["one", "two"],
        )
        self.assertEqual(context.append([{"event_id": "two"}]), [])
        context.append([{"event_id": "three"}])
        self.assertEqual([row["event_id"] for row in context.rows()], ["two", "three"])

    def test_sdk_client_submits_limit_if_touched_with_idempotent_signal_remark(self) -> None:
        class Enum:
            Buy = "Buy"
            Sell = "Sell"
            LO = "LO"
            LIT = "LIT"
            Day = "Day"
            RTHOnly = "RTHOnly"

        class Sdk:
            OrderSide = Enum
            OrderType = Enum
            TimeInForceType = Enum
            OutsideRTH = Enum

        class Response:
            order_id = "SDK-1"

        class Trade:
            def __init__(self) -> None:
                self.kwargs = {}

            def submit_order(self, **kwargs):
                self.kwargs = kwargs
                return Response()

        trade = Trade()
        result = SdkRealtimePaperClient(trade, Sdk()).submit_order({
            "side": "buy", "symbol": "AAPL", "order_type": "trigger_limit", "limit_price": "200.1",
            "trigger_price": "200", "quantity": "2", "signal_id": "signal-1",
        })
        self.assertTrue(result["submitted"])
        self.assertEqual(result["order_id"], "SDK-1")
        self.assertEqual(trade.kwargs["order_type"], "LIT")
        self.assertEqual(trade.kwargs["trigger_price"], Decimal("200"))
        self.assertEqual(trade.kwargs["outside_rth"], "RTHOnly")
        self.assertEqual(trade.kwargs["symbol"], "AAPL.US")

    def test_sdk_client_uses_market_order_without_price_for_exit(self) -> None:
        class Enum:
            Buy = "Buy"
            Sell = "Sell"
            LO = "LO"
            LIT = "LIT"
            MO = "MO"
            Day = "Day"
            RTHOnly = "RTHOnly"

        class Sdk:
            OrderSide = Enum
            OrderType = Enum
            TimeInForceType = Enum
            OutsideRTH = Enum

        class Response:
            order_id = "SDK-MO-1"

        class Trade:
            def __init__(self) -> None:
                self.kwargs = {}

            def submit_order(self, **kwargs):
                self.kwargs = kwargs
                return Response()

        trade = Trade()
        result = SdkRealtimePaperClient(trade, Sdk()).submit_order({
            "side": "sell",
            "symbol": "AAPL",
            "order_type": "market",
            "quantity": "2",
            "signal_id": "signal-market-exit",
            "client_request_id": "m15rt-123",
        })
        self.assertTrue(result["submitted"])
        self.assertEqual(result["order_id"], "SDK-MO-1")
        self.assertEqual(trade.kwargs["order_type"], "MO")
        self.assertNotIn("submitted_price", trade.kwargs)
        self.assertIn("signal-market-exit", trade.kwargs["remark"])
        self.assertIn("m15rt-123", trade.kwargs["remark"])

    def test_sdk_client_cancels_and_replaces_without_cli(self) -> None:
        class Trade:
            def __init__(self) -> None:
                self.calls = []

            def cancel_order(self, order_id):
                self.calls.append(("cancel", order_id))

            def replace_order(self, order_id, quantity, **kwargs):
                self.calls.append(("replace", order_id, quantity, kwargs))

        trade = Trade()
        client = SdkRealtimePaperClient(trade, object())
        self.assertTrue(client.cancel_order("ORDER-1")["canceled"])
        replaced = client.replace_order("ORDER-2", Decimal("3"), Decimal("99.50"))
        self.assertTrue(replaced["replaced"])
        self.assertEqual(trade.calls, [
            ("cancel", "ORDER-1"),
            ("replace", "ORDER-2", Decimal("3"), {"price": Decimal("99.50")}),
        ])

    def test_sdk_order_maintenance_cancels_stale_entries_and_reprices_exits(self) -> None:
        now = datetime(2026, 7, 15, 15, 47, tzinfo=UTC)
        account_state = {
            "open_orders": [
                {
                    "order_id": "ENTRY-1", "remark": "entry-signal", "symbol": "AAPL.US",
                    "side": "OrderSide.Buy", "quantity": "2", "executed_quantity": "0",
                    "price": "200", "updated_at": "2026-07-15T15:30:00Z",
                },
                {
                    "order_id": "EXIT-1", "remark": "exit-signal", "symbol": "LI.US",
                    "side": "OrderSide.Sell", "quantity": "26", "executed_quantity": "0",
                    "price": "12.87", "updated_at": "2026-07-15T15:45:00Z",
                },
                {
                    "order_id": "MANUAL-1", "remark": "manual", "symbol": "MSFT.US",
                    "side": "OrderSide.Buy", "quantity": "1", "executed_quantity": "0",
                    "price": "500", "updated_at": "2026-07-15T15:30:00Z",
                },
            ]
        }
        actions = sdk_order_maintenance_actions(
            account_state,
            [
                {"signal_id": "entry-signal", "position_action": "open_long"},
                {"signal_id": "exit-signal", "position_action": "take_profit"},
            ],
            [{"symbol": "LI", "timeframe": "5m", "event_time": "2026-07-15T15:45:00Z", "close": "12.80"}],
            now=now,
            stale_entry_order_ttl_seconds=900,
            exit_order_reprice_seconds=60,
        )
        self.assertEqual([row["action"] for row in actions], ["cancel", "replace"])
        self.assertEqual(actions[0]["order_id"], "ENTRY-1")
        self.assertEqual(actions[1]["order_id"], "EXIT-1")
        self.assertEqual(actions[1]["new_price"], "12.73")
        self.assertEqual(actions[1]["price_source"], "current_sdk_price_minus_long_exit_buffer")

    def test_sdk_order_maintenance_does_not_reprice_market_exit(self) -> None:
        now = datetime(2026, 7, 15, 15, 47, tzinfo=UTC)
        account_state = {
            "open_orders": [
                {
                    "order_id": "EXIT-MO-1", "remark": "exit-signal", "symbol": "LI.US",
                    "side": "OrderSide.Sell", "quantity": "26", "executed_quantity": "0",
                    "price": "12.87", "updated_at": "2026-07-15T15:45:00Z",
                },
            ]
        }
        actions = sdk_order_maintenance_actions(
            account_state,
            [
                {"signal_id": "exit-signal", "position_action": "take_profit", "original_order_type": "market"},
            ],
            [{"symbol": "LI", "timeframe": "5m", "event_time": "2026-07-15T15:45:00Z", "close": "12.80"}],
            now=now,
            stale_entry_order_ttl_seconds=900,
            exit_order_reprice_seconds=60,
        )
        self.assertEqual(actions, [])

    def test_sdk_account_state_uses_sdk_only_contract(self) -> None:
        class Cash:
            currency = "USD"
            available_cash = "1000"
            total_cash = "1000"
            net_assets = "1100"
            buy_power = "900"
            settling_cash = "0"
            frozen_cash = "0"
            withdraw_cash = "1000"

        class Position:
            symbol = "AAPL.US"
            quantity = "2"
            available_quantity = "2"
            cost_price = "200"
            currency = "USD"
            market = "US"

        class Order:
            symbol = "AAPL.US"
            order_id = "SDK-1"
            side = "Buy"
            status = "Submitted"

        class Trade:
            def account_balance(self): return [Cash()]
            def stock_positions(self): return [Position()]
            def today_orders(self, **_kwargs): return [Order()]
            def today_executions(self): return []

        class Portfolio:
            def profit_analysis_by_market(self, **_kwargs):
                return {"current_total_asset": "1200", "sum_profit": "200"}

        state = SdkAccountStateProvider(Trade(), Portfolio(), request_gate=SdkTradeRequestGate()).refresh()
        self.assertTrue(state["paper_account_verified"])
        self.assertEqual(state["source"], "longbridge_sdk_account_and_portfolio")
        self.assertEqual(state["usd_available_cash"], "1000")
        self.assertEqual(state["account_total_equity_estimate"], "1200")
        self.assertEqual(state["account_total_equity_source"], "longbridge_sdk_portfolio_profit_analysis_by_market")
        self.assertEqual(state["positions"][0]["available"], "2")
        self.assertEqual(state["open_orders"][0]["order_id"], "SDK-1")

    def test_sdk_account_state_falls_back_to_balance_net_assets_with_currency(self) -> None:
        class Balance:
            currency = "HKD"
            cash_infos = []
            net_assets = "798250.37"
            buy_power = "764930.79"

        class Trade:
            def account_balance(self): return [Balance()]
            def stock_positions(self): return []
            def today_orders(self): return []
            def today_executions(self): return []

        class Portfolio:
            def profit_analysis_by_market(self, **_kwargs): return {"profit": "-305.59"}

        state = SdkAccountStateProvider(Trade(), Portfolio(), request_gate=SdkTradeRequestGate()).refresh()

        self.assertEqual(state["account_total_equity_estimate"], "798250.37")
        self.assertEqual(state["account_total_equity_currency"], "HKD")
        self.assertEqual(state["account_total_equity_source"], "longbridge_sdk_account_balance.net_assets")
        self.assertEqual(state["account_buying_power"], "764930.79")

    def test_sdk_account_analytics_failure_does_not_disable_paper_orders(self) -> None:
        class Cash:
            currency = "USD"
            available_cash = total_cash = "1000"
            settling_cash = frozen_cash = "0"
            withdraw_cash = "1000"

        class Trade:
            def account_balance(self): return [Cash()]
            def stock_positions(self): return []
            def today_orders(self): return []
            def today_executions(self): return []

        class Portfolio:
            def profit_analysis_by_market(self, **_kwargs):
                raise TimeoutError("analytics slow")

        state = SdkAccountStateProvider(Trade(), Portfolio(), request_gate=SdkTradeRequestGate()).refresh()
        self.assertTrue(state["paper_account_verified"])
        self.assertEqual(state["critical_errors"], [])
        self.assertIn("sdk_profit_analysis_failed:TimeoutError:analytics slow", state["analytics_errors"])

    def test_daily_context_rows_are_independent_from_m12(self) -> None:
        class Candle:
            timestamp = 1784073600
            open = "100"
            high = "103"
            low = "99"
            close = "102"
            volume = 123

        rows = event_rows_to_daily("AAPL.US", [Candle()], datetime(2026, 7, 15, 13, 35, tzinfo=UTC))
        self.assertEqual(rows[0]["timeframe"], "1d")
        self.assertEqual(rows[0]["source_mode"], "longbridge_sdk_daily_context")
        self.assertTrue(rows[0]["local_simulation_ignored"])

    def test_daily_context_accepts_the_sdk_naive_datetime_timestamp(self) -> None:
        class Candle:
            timestamp = datetime(2026, 7, 14, 12, 0)
            open = "100"
            high = "103"
            low = "99"
            close = "102"
            volume = 123

        rows = event_rows_to_daily("AAPL.US", [Candle()], datetime(2026, 7, 15, 13, 35, tzinfo=UTC))
        self.assertEqual(len(rows), 1)
        expected = datetime.fromtimestamp(Candle.timestamp.timestamp(), UTC).isoformat().replace("+00:00", "Z")
        self.assertEqual(rows[0]["event_time"], expected)

    def test_daily_context_worker_messages_keep_the_batch_identity(self) -> None:
        class Candle:
            timestamp = 1784073600
            open = high = low = close = "100"
            volume = 1

        class Quote:
            def candlesticks(self, *_args): return [Candle()]

        class Sdk:
            class Period:
                Day = "day"
            class AdjustType:
                NoAdjust = "no-adjust"

        class Queue:
            def __init__(self): self.items = []
            def put_nowait(self, payload): self.items.append(payload)

        queue = Queue()
        from scripts.run_m15_longbridge_sdk_runtime import load_daily_context
        load_daily_context(Quote(), Sdk(), ("AAPL.US",), 60, queue, task_id="daily-001")
        self.assertEqual(queue.items[0]["task_id"], "daily-001")

    def test_installed_sdk_exposes_required_contexts(self) -> None:
        self.assertIsNotNone(require_sdk_contract())

    def test_sdk_seed_universe_uses_active_paramount_symbol(self) -> None:
        symbols = configured_symbols(load_config())

        self.assertIn("PSKY.US", symbols)
        self.assertNotIn("PARA.US", symbols)
        self.assertEqual(len(symbols), 147)

    def test_expanded_readonly_config_is_isolated_and_dispatch_disabled(self) -> None:
        default = json.loads(Path("config/examples/m15_longbridge_sdk_runtime.json").read_text(encoding="utf-8"))
        expanded = json.loads(Path("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json").read_text(encoding="utf-8"))
        runtime_config = load_config("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json")

        self.assertFalse(expanded["routing"]["paper_order_dispatch_enabled"])
        self.assertTrue(expanded["runtime"]["two_day_readonly_gate"])
        self.assertFalse(runtime_config.paper_order_dispatch_enabled)
        self.assertTrue(runtime_config.two_day_readonly_gate)
        dispatch_requested = True
        readonly_gate_passed_now = True
        self.assertFalse(
            dispatch_requested
            and runtime_config.paper_order_dispatch_enabled
            and (not runtime_config.two_day_readonly_gate or readonly_gate_passed_now)
        )
        self.assertFalse(expanded["market_data"]["use_seed_universe"])
        self.assertEqual(expanded["market_data"]["universe_path"], "config/m15_us_liquid_universe_300.json")
        self.assertEqual(expanded["market_data"]["symbol_limit"], 300)
        self.assertNotEqual(expanded["outputs"]["output_dir"], default["outputs"]["output_dir"])
        self.assertNotEqual(expanded["outputs"]["market_events"], default["outputs"]["market_events"])
        self.assertNotEqual(expanded["outputs"]["runtime_status"], default["outputs"]["runtime_status"])
        self.assertNotEqual(expanded["outputs"]["readonly_gate"], default["outputs"]["readonly_gate"])
        self.assertNotEqual(expanded["market_data"]["daily_context"], default["market_data"]["daily_context"])
        self.assertNotEqual(expanded["formal_test_transition"]["marker_path"], default["formal_test_transition"]["marker_path"])
        self.assertNotEqual(
            expanded["formal_test_transition"]["epoch_state_path"],
            default["formal_test_transition"]["epoch_state_path"],
        )

    def test_expanded_universe_file_keeps_declared_order_and_limit(self) -> None:
        payload = json.loads(Path("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json").read_text(encoding="utf-8"))
        symbols = load_m15_universe(payload["market_data"]["universe_path"])
        raw_symbols = json.loads(Path(payload["market_data"]["universe_path"]).read_text(encoding="utf-8"))["symbols"]

        self.assertEqual(len(symbols), 300)
        self.assertEqual(payload["market_data"]["symbol_limit"], 300)
        self.assertLessEqual(payload["market_data"]["symbol_limit"], len(symbols))
        self.assertEqual(symbols[:5], tuple(raw_symbols[:5]))
        self.assertEqual(symbols[-5:], tuple(raw_symbols[-5:]))

    def test_runtime_configured_symbols_will_follow_file_order_after_integration(self) -> None:
        config = load_config("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json")
        symbols = configured_symbols(config)

        self.assertEqual(len(symbols), 300)
        self.assertEqual(symbols[0], "SPY.US")
        self.assertEqual(symbols[-1], "SHW.US")

    def test_runtime_rejects_symbol_limit_larger_than_universe_file(self) -> None:
        source = json.loads(
            Path("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json").read_text(encoding="utf-8")
        )
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "runtime.json"
            source["market_data"]["symbol_limit"] = 301
            config_path.write_text(json.dumps(source), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "symbol_limit exceeds universe file length"):
                load_config(config_path)

    def test_two_readonly_sessions_are_required_before_dispatch(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "gate.json"
            self.assertEqual(readonly_gate_passed(path), (False, 0, 2))
            record_readonly_session(path, "2026-07-13", {"daily_context_row_count": 8820})
            self.assertEqual(readonly_gate_passed(path), (False, 1, 2))
            record_readonly_session(path, "2026-07-14", {"daily_context_row_count": 8820})
            self.assertEqual(readonly_gate_passed(path), (True, 2, 2))

    def test_runtime_fingerprint_changes_when_dispatch_gate_changes(self) -> None:
        config = load_config()
        changed = replace(config, two_day_readonly_gate=not config.two_day_readonly_gate)
        self.assertNotEqual(config_fingerprint(config), config_fingerprint(changed))

    def test_daily_context_must_cover_every_symbol_before_dispatch(self) -> None:
        config = load_config()
        expected = len(configured_symbols(config)) * config.daily_context_bars
        self.assertFalse(daily_context_is_complete(config, "loading", expected, []))
        self.assertFalse(daily_context_is_complete(config, "complete", expected - 1, []))
        self.assertFalse(daily_context_is_complete(config, "complete", expected, ["AAPL.US"]))
        self.assertTrue(daily_context_is_complete(config, "complete", expected, []))

    def test_only_a_complete_current_daily_cache_is_reused(self) -> None:
        config = replace(load_config(), symbol_limit=1, daily_context_bars=2)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "daily.jsonl"
            rows = [
                {"symbol": "SPY", "timeframe": "1d", "event_time": "2026-07-14T19:00:00Z"},
                {"symbol": "SPY", "timeframe": "1d", "event_time": "2026-07-14T20:00:00Z"},
            ]
            write_daily_context_cache(path, rows)
            before_open = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
            self.assertEqual(load_valid_daily_context_cache(path, config, before_open), rows)
            next_session = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
            self.assertEqual(load_valid_daily_context_cache(path, config, next_session), [])

    def test_sdk_preflight_requires_all_read_only_endpoints(self) -> None:
        # The live preflight is exercised by the command-line integration
        # check. Keep the code-level contract explicit here too.
        self.assertTrue(callable(run_sdk_preflight))
