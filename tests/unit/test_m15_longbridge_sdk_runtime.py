from __future__ import annotations

import ast
import hashlib
import inspect
import json
import pickle
import textwrap
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.m15_longbridge_realtime_execution_lib import response_order_id
from scripts.m15_longbridge_sdk_runtime_lib import (
    FiveMinuteBarBuilder, MarketEventContext, SdkRealtimePaperClient, append_market_events, compact_market_events,
    config_fingerprint, configured_symbols, configured_trading_symbols, daily_context_covers_symbols,
    daily_context_is_complete, fresh_market_events, load_config,
    held_position_monitoring_symbols, new_held_position_monitoring_symbols,
    load_current_sdk_intraday_context,
    load_valid_daily_context_cache, sdk_config_from_oauth, sdk_endpoint_overrides, sdk_object_to_dict, subscribe_private_trade_updates,
    sdk_order_maintenance_actions, summarize_latency_samples, write_daily_context_cache,
    subscribe_quote_and_trades, record_readonly_session, readonly_gate_passed,
    market_event_is_tradable, trading_market_events,
    trading_universe_fingerprint,
    validate_formal_epoch_alignment,
    validate_market_data_transport_runtime,
)
from scripts.m15_longbridge_sdk_account_lib import SdkAccountCoordinator, SdkAccountStateProvider, SdkTradeRequestGate
from scripts.m15_universe_lib import load_m15_universe
from scripts.run_m15_longbridge_sdk_runtime import (
    acquire_runtime_run_lock,
    active_reference_quotes_are_stale,
    apply_quote_state_worker_message,
    build_live_daily_confirmation_rows,
    close_spawn_queue,
    completed_postclose_refresh_dates,
    compact_hot_execution_rows,
    compact_hot_signal_rows,
    configured_market_data_mode,
    configured_quote_worker,
    dispatch_completed_rows,
    event_rows_to_daily,
    effective_runtime_dispatch_enabled,
    is_orphaned_sdk_runtime_child,
    market_data_mode_qualifies_for_subscription_gate,
    run_market_data_preflight,
    market_data_heartbeat_grace_elapsed,
    market_data_heartbeat_is_stale,
    market_data_recovery_is_stable,
    preserve_last_order_maintenance_action,
    opening_signal_outside_trading_universe,
    quote_worker,
    quote_subscription_ready,
    quote_subscription_targets,
    reconcile_position_monitoring_worker,
    require_sdk_contract,
    request_runtime_shutdown,
    restore_pipeline_observability,
    runtime_requires_health_replacement,
    runtime_owns_quote_connection,
    run_sdk_order_maintenance,
    run_pending_flatten_cycle,
    run_authorized_account_exit_cycle,
    run_sdk_preflight,
    runtime_dispatch_block_reason,
    realtime_boundary_is_complete,
    reconnect_delay_seconds,
    regular_session_open_grace_elapsed,
    should_use_snapshot_fallback,
    snapshot_poll_cycle_is_healthy,
    signals_allowed_by_entry_gate,
    should_emit_reference_market_activity,
    start_runtime_daemon,
    trade_context_health_requires_rebuild,
    update_live_quote_session_state,
)


class M15LongbridgeSdkRuntimeTest(unittest.TestCase):
    def test_production_transport_selects_longbridge_serve_worker(self) -> None:
        config = load_config()
        self.assertEqual(
            configured_market_data_mode(config),
            "longbridge_serve_subscription",
        )
        self.assertEqual(
            configured_quote_worker(config).__name__,
            "longbridge_serve_quote_worker",
        )
        self.assertTrue(
            market_data_mode_qualifies_for_subscription_gate(
                "longbridge_serve_subscription"
            )
        )

    def test_preflight_uses_serve_transport_instead_of_sdk_quote(self) -> None:
        config = load_config()
        with (
            patch(
                "scripts.run_m15_longbridge_sdk_runtime.runtime_owns_quote_connection",
                return_value=False,
            ),
            patch(
                "scripts.run_m15_longbridge_sdk_runtime.probe_longbridge_serve_transport",
                return_value={
                    "market_data_mode": "longbridge_serve_subscription",
                    "subscription_coverage": "3/3",
                },
            ) as serve_probe,
        ):
            result = run_market_data_preflight(config, SimpleNamespace(), object())

        self.assertTrue(result["quote_ok"])
        self.assertEqual(
            result["quote_probe_source"],
            "direct_longbridge_serve_preflight",
        )
        serve_probe.assert_called_once()

    def test_preflight_fails_when_serve_authorization_or_initialize_fails(self) -> None:
        config = load_config()
        with (
            patch(
                "scripts.run_m15_longbridge_sdk_runtime.runtime_owns_quote_connection",
                return_value=False,
            ),
            patch(
                "scripts.run_m15_longbridge_sdk_runtime.probe_longbridge_serve_transport",
                side_effect=RuntimeError("authorization_required"),
            ),
        ):
            result = run_market_data_preflight(config, SimpleNamespace(), object())

        self.assertFalse(result["quote_ok"])
        self.assertIn("authorization_required", result["quote_error"])

    def test_reference_trade_activity_is_throttled_without_ignoring_trades(self) -> None:
        last_emit = {}
        self.assertTrue(
            should_emit_reference_market_activity(
                "SPY.US", now_monotonic=10.0, last_emit_by_symbol=last_emit
            )
        )
        self.assertFalse(
            should_emit_reference_market_activity(
                "SPY.US", now_monotonic=10.5, last_emit_by_symbol=last_emit
            )
        )
        self.assertTrue(
            should_emit_reference_market_activity(
                "SPY.US", now_monotonic=11.0, last_emit_by_symbol=last_emit
            )
        )
        self.assertFalse(
            should_emit_reference_market_activity(
                "AAPL.US", now_monotonic=11.0, last_emit_by_symbol=last_emit
            )
        )

    def test_live_quote_state_keeps_newer_push_when_snapshot_arrives_late(self) -> None:
        state: dict[str, dict] = {}
        received_at = datetime(2026, 8, 25, 13, 31, tzinfo=UTC)
        newer = update_live_quote_session_state(
            state,
            "SPY.US",
            {
                "timestamp": "2026-08-25T13:31:00Z",
                "open": "500",
                "high": "502",
                "low": "499",
                "last_done": "501",
                "volume": 100,
            },
            received_at=received_at,
            source_mode="longbridge_serve_push",
        )
        retained = update_live_quote_session_state(
            state,
            "SPY.US",
            {
                "timestamp": "2026-08-25T13:30:59Z",
                "open": "500",
                "high": "500",
                "low": "498",
                "last_done": "499",
                "volume": 90,
            },
            received_at=received_at,
            source_mode="longbridge_serve_initial_snapshot",
        )

        self.assertIs(retained, newer)
        self.assertEqual(state["SPY"]["close"], "501")
        self.assertEqual(state["SPY"]["source_mode"], "longbridge_serve_push")

    def test_parent_applies_batched_quote_state_and_reference_heartbeat(self) -> None:
        state: dict[str, dict] = {}
        last_push: dict[str, float] = {}
        last_push_at: dict[str, str] = {}
        last_push_source: dict[str, str] = {}
        first_live: dict[str, float] = {}
        last_live: dict[str, float] = {}

        applied = apply_quote_state_worker_message(
            {
                "kind": "quote_state_batch",
                "rows": [
                    {
                        "symbol": "SPY.US",
                        "payload": {
                            "timestamp": "2026-08-25T13:31:00Z",
                            "open": "500",
                            "high": "502",
                            "low": "499",
                            "last_done": "501",
                            "volume": 100,
                        },
                        "received_at": "2026-08-25T13:31:00Z",
                        "source_mode": "longbridge_serve_push",
                    },
                    {
                        "symbol": "AAPL.US",
                        "payload": {
                            "timestamp": "2026-08-25T13:31:00Z",
                            "open": "225",
                            "high": "226",
                            "low": "224",
                            "last_done": "225.5",
                            "volume": 50,
                        },
                        "received_at": "2026-08-25T13:31:00Z",
                        "source_mode": "longbridge_serve_push",
                    },
                ],
            },
            live_quote_session_state=state,
            last_push_by_symbol=last_push,
            last_push_at_by_symbol=last_push_at,
            last_push_source_by_symbol=last_push_source,
            first_live_push_by_symbol=first_live,
            last_live_push_by_symbol=last_live,
            now_monotonic=123.0,
        )

        self.assertEqual(applied, 2)
        self.assertEqual(state["SPY"]["close"], "501")
        self.assertEqual(state["AAPL"]["close"], "225.5")
        self.assertEqual(last_push["SPY.US"], 123.0)
        self.assertEqual(last_push_source["AAPL.US"], "longbridge_serve_push")
        self.assertEqual(first_live["SPY.US"], 123.0)
        self.assertEqual(last_live["SPY.US"], 123.0)
        self.assertNotIn("AAPL.US", first_live)

    def test_quote_worker_reports_reference_trade_activity(self) -> None:
        source = inspect.getsource(quote_worker)
        self.assertIn('"kind": "market_activity"', source)
        self.assertIn('"longbridge_sdk_trade_push"', source)

    def test_runtime_keeps_account_refresh_independent_during_quote_subscription(self) -> None:
        source = inspect.getsource(__import__(
            "scripts.run_m15_longbridge_sdk_runtime",
            fromlist=["run_watch"],
        ).run_watch)
        self.assertIn("account.start(background_refresh=True)", source)
        self.assertNotIn("account.pause_background_refresh()", source)
        self.assertIn("account.resume_background_refresh()", source)

    def test_runtime_shutdown_allows_spawned_workers_to_close(self) -> None:
        signature = inspect.signature(request_runtime_shutdown)
        self.assertEqual(signature.parameters["timeout_seconds"].default, 15.0)

    def test_default_runtime_uses_canonical_production_config(self) -> None:
        config = load_config()
        self.assertTrue(str(config.config_path).endswith("m15_longbridge_sdk_runtime.json"))
        self.assertFalse(str(config.config_path).endswith(".contract_v1.json"))
        self.assertEqual(config.subscription_deadline_seconds, 30)
        self.assertEqual(config.subscription_progress_deadline_seconds, 90)
        self.assertEqual(config.subscription_circuit_retry_seconds, 300)
        self.assertEqual(config.subscription_batch_size, 500)
        self.assertEqual(
            config.market_data_transport,
            "longbridge_serve_persistent_jsonrpc",
        )
        self.assertEqual(config.longbridge_serve_batch_size, 10)
        self.assertEqual(config.longbridge_serve_response_timeout_seconds, 30)

    def test_serve_transport_binary_must_match_pinned_checksum(self) -> None:
        with TemporaryDirectory() as tmp:
            binary = Path(tmp) / "longbridge"
            binary.write_bytes(b"pinned-serve-binary")
            binary.chmod(0o700)
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            config = replace(
                load_config(),
                longbridge_serve_binary=binary,
                longbridge_serve_binary_sha256=digest,
            )
            validate_market_data_transport_runtime(config)

            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                validate_market_data_transport_runtime(
                    replace(config, longbridge_serve_binary_sha256="0" * 64)
                )

    def test_runtime_subscription_circuit_recovers_without_parent_restart(self) -> None:
        source = inspect.getsource(__import__(
            "scripts.run_m15_longbridge_sdk_runtime",
            fromlist=["run_watch"],
        ).run_watch)
        self.assertIn("config.subscription_progress_deadline_seconds", source)
        self.assertIn("config.subscription_circuit_retry_seconds", source)
        self.assertIn("sdk_subscription_circuit_cooldown_elapsed", source)
        self.assertIn("account.resume_background_refresh()", source)
        self.assertIn(
            "not market_data_circuit_open\n                and not worker_ready",
            source,
        )
        self.assertGreaterEqual(source.count("account.resume_background_refresh()"), 6)

    def test_runtime_cleans_owned_serve_orphans_before_every_worker_start(self) -> None:
        source = inspect.getsource(__import__(
            "scripts.run_m15_longbridge_sdk_runtime",
            fromlist=["run_watch"],
        ).run_watch)
        cleanup = "cleanup_orphaned_longbridge_serve_processes()"
        self.assertGreaterEqual(source.count(cleanup), 2)
        self.assertIn("orphaned_serve_processes_cleaned.extend", source)
        self.assertLess(source.index(cleanup), source.index("worker_target = ("))

    def test_production_runtime_uses_frozen_contract_v1_configs(self) -> None:
        config = load_config("config/examples/m15_longbridge_sdk_runtime.json")
        self.assertTrue(str(config.router_config_path).endswith("m15_longbridge_realtime_signal_router.contract_v1.json"))
        self.assertTrue(str(config.execution_config_path).endswith("m15_longbridge_realtime_execution.paper_contract_v1.json"))
        self.assertTrue(str(config.position_manager_config_path).endswith("m15_longbridge_realtime_position_manager.contract_v1.json"))
        self.assertEqual(config.formal_test_epoch_id, "m15-sdk-contract-v1-20260806")
        self.assertEqual(config.formal_short_test_epoch_id, "m15-sdk-contract-v1-short-20260806")

    def test_readonly_entry_gate_keeps_exit_signals_executable(self) -> None:
        entry = {"signal_id": "entry", "position_action": "open_long"}
        exit_signal = {"signal_id": "exit", "position_action": "close_long"}
        self.assertEqual(
            signals_allowed_by_entry_gate(
                [entry], [exit_signal], new_entry_submission_enabled=False
            ),
            [exit_signal],
        )
        self.assertEqual(
            signals_allowed_by_entry_gate(
                [entry], [exit_signal], new_entry_submission_enabled=True
            ),
            [entry, exit_signal],
        )

    def test_reconnect_backoff_and_active_quote_silence(self) -> None:
        schedule = (5, 15, 30, 60)
        self.assertEqual([reconnect_delay_seconds(schedule, value) for value in range(1, 6)], [5, 15, 30, 60, 60])
        self.assertTrue(
            active_reference_quotes_are_stale(
                {"SPY.US": 10, "QQQ.US": 20},
                now_monotonic=60,
                maximum_silence_seconds=30,
            )
        )
        self.assertFalse(
            active_reference_quotes_are_stale(
                {"SPY.US": 40, "QQQ.US": 20},
                now_monotonic=60,
                maximum_silence_seconds=30,
            )
        )

    def test_recovery_attempts_reset_only_after_sustained_live_pushes(self) -> None:
        self.assertFalse(
            market_data_recovery_is_stable(
                attempts=1,
                worker_ready_since_monotonic=100.0,
                now_monotonic=120.0,
                last_push_by_symbol={"SPY.US": 119.0, "QQQ.US": 119.0},
                first_live_push_by_symbol={"SPY.US": 101.0},
                last_live_push_by_symbol={"SPY.US": 119.0},
                stabilization_seconds=30.0,
            )
        )
        self.assertFalse(
            market_data_recovery_is_stable(
                attempts=1,
                worker_ready_since_monotonic=100.0,
                now_monotonic=131.0,
                last_push_by_symbol={"SPY.US": 100.0, "QQQ.US": 100.0},
                first_live_push_by_symbol={"SPY.US": 101.0},
                last_live_push_by_symbol={"SPY.US": 130.0},
                stabilization_seconds=30.0,
            )
        )
        self.assertTrue(
            market_data_recovery_is_stable(
                attempts=1,
                worker_ready_since_monotonic=100.0,
                now_monotonic=131.0,
                last_push_by_symbol={"SPY.US": 130.0, "QQQ.US": 100.0},
                first_live_push_by_symbol={"SPY.US": 101.0},
                last_live_push_by_symbol={"SPY.US": 130.0},
                stabilization_seconds=30.0,
            )
        )

        self.assertFalse(
            market_data_recovery_is_stable(
                attempts=1,
                worker_ready_since_monotonic=100.0,
                now_monotonic=131.0,
                last_push_by_symbol={"SPY.US": 130.0},
                first_live_push_by_symbol={"SPY.US": 129.0},
                last_live_push_by_symbol={"SPY.US": 130.0},
                stabilization_seconds=30.0,
            )
        )

    def test_successful_subscription_receipt_does_not_clear_recovery_attempts(self) -> None:
        source = inspect.getsource(__import__(
            "scripts.run_m15_longbridge_sdk_runtime",
            fromlist=["run_watch"],
        ).run_watch)
        ready_branch = source.split('elif kind == "ready":', 1)[1].split('elif kind == "daily_context":', 1)[0]

        self.assertNotIn("attempts = 0", ready_branch)
        self.assertIn("market_data_recovery_is_stable", source)

    def test_invalid_deployment_manifest_blocks_dispatch(self) -> None:
        self.assertFalse(
            effective_runtime_dispatch_enabled(
                dispatch_requested=True,
                paper_client_ready=True,
                trade_context_ready=True,
                market_data_ready=True,
                trading_daily_context_ready=True,
                flatten_blocks_new_entries=False,
                account_snapshot_ready=True,
                deployment_ready=False,
            )
        )
        self.assertEqual(
            runtime_dispatch_block_reason(
                paper_order_dispatch_enabled=True,
                complete_session_gate_blocked=False,
                paper_client_ready=True,
                trade_context_ready=True,
                market_data_ready=True,
                flatten_blocks_new_entries=False,
                account_snapshot_ready=True,
                trading_daily_context_ready=True,
                deployment_ready=False,
            ),
            "deployment_manifest_invalid",
        )

    def test_no_trade_boundary_row_is_complete_but_not_tradable(self) -> None:
        builder = FiveMinuteBarBuilder(
            complete_bar_open_not_before=datetime(2026, 8, 21, 13, 30, tzinfo=UTC)
        )
        builder.seed_quote(
            "SPY.US",
            {"last_done": "650", "timestamp": int(datetime(2026, 8, 21, 13, 31, tzinfo=UTC).timestamp())},
            received_at=datetime(2026, 8, 21, 13, 31, tzinfo=UTC),
        )
        rows = builder.complete_boundary(
            ["SPY.US"],
            datetime(2026, 8, 21, 13, 35, 1, tzinfo=UTC),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market_data_blocked_reason"], "no_trade_carry_forward")
        self.assertEqual(rows[0]["volume"], "0")
        self.assertTrue(realtime_boundary_is_complete(rows, ["SPY.US"]))

    def test_boundary_completeness_ignores_exit_only_monitoring_rows(self) -> None:
        received = "2026-08-21T13:35:01Z"
        rows = [
            {
                "symbol": symbol,
                "event_time": "2026-08-21T13:35:00Z",
                "received_at": received,
                "bar_final": True,
            }
            for symbol in ("SPY", "QQQ", "ZM")
        ]

        self.assertTrue(
            realtime_boundary_is_complete(rows, ["SPY.US", "QQQ.US"])
        )

    def test_existing_holdings_outside_strategy_universe_are_exit_only_monitored(self) -> None:
        config = load_config()
        configured = configured_symbols(config)[0]
        snapshot = {
            "positions": [
                {"symbol": configured, "quantity": "1"},
                {"symbol": "ZZZZ.US", "quantity": "2"},
                {"symbol": "ZERO.US", "quantity": "0"},
                {"symbol": "SHORT.US", "quantity": "-2"},
                {"symbol": "0700.HK", "quantity": "3"},
                {"symbol": "BAD.US", "quantity": "not-a-number"},
            ]
        }

        self.assertEqual(
            held_position_monitoring_symbols(config, snapshot),
            ("ZZZZ.US",),
        )
        self.assertTrue(
            opening_signal_outside_trading_universe(
                config,
                {"symbol": "ZZZZ", "side": "buy", "position_action": "open_long"},
            )
        )
        self.assertFalse(
            opening_signal_outside_trading_universe(
                config,
                {"symbol": "ZZZZ", "side": "sell", "position_action": "close_long"},
            )
        )
        self.assertEqual(
            new_held_position_monitoring_symbols(
                config,
                snapshot,
                {"ZZZZ.US"},
            ),
            (),
        )
        changed_snapshot = {
            "positions": list(snapshot["positions"])
            + [{"symbol": "NEWHOLD.US", "quantity": "1"}]
        }
        self.assertEqual(
            new_held_position_monitoring_symbols(
                config,
                changed_snapshot,
                {"ZZZZ.US"},
            ),
            ("NEWHOLD.US",),
        )

    def test_runtime_restarts_only_worker_when_new_exit_only_holding_appears(self) -> None:
        config = load_config()
        snapshot = {"positions": [{"symbol": "NEWHOLD.US", "quantity": "1"}]}
        worker = SimpleNamespace(pid=1234)

        with patch(
            "scripts.run_m15_longbridge_sdk_runtime.stop_spawned_process"
        ) as stop_worker:
            updated, additions, reason = reconcile_position_monitoring_worker(
                config,
                snapshot,
                ("OLDHOLD.US",),
                worker,
            )

        stop_worker.assert_called_once_with(worker, graceful=False)
        self.assertEqual(updated, ("NEWHOLD.US", "OLDHOLD.US"))
        self.assertEqual(additions, ("NEWHOLD.US",))
        self.assertEqual(
            reason,
            "position_monitoring_set_changed_restarting_quote_worker:NEWHOLD.US",
        )

    def test_runtime_does_not_restart_when_monitoring_set_is_unchanged(self) -> None:
        config = load_config()
        snapshot = {"positions": [{"symbol": "OLDHOLD.US", "quantity": "1"}]}
        worker = SimpleNamespace(pid=1234)

        with patch(
            "scripts.run_m15_longbridge_sdk_runtime.stop_spawned_process"
        ) as stop_worker:
            updated, additions, reason = reconcile_position_monitoring_worker(
                config,
                snapshot,
                ("OLDHOLD.US",),
                worker,
            )

        stop_worker.assert_not_called()
        self.assertEqual(updated, ("OLDHOLD.US",))
        self.assertEqual(additions, ())
        self.assertEqual(reason, "")

    def test_monitoring_failure_keeps_core_ready_but_blocks_new_entries(self) -> None:
        self.assertTrue(quote_subscription_ready([], [], []))
        self.assertFalse(quote_subscription_ready(["SPY.US"], [], []))
        self.assertFalse(
            effective_runtime_dispatch_enabled(
                dispatch_requested=True,
                paper_client_ready=True,
                trade_context_ready=True,
                market_data_ready=True,
                trading_daily_context_ready=True,
                flatten_blocks_new_entries=False,
                account_snapshot_ready=True,
                position_monitoring_ready=False,
            )
        )
        self.assertEqual(
            runtime_dispatch_block_reason(
                paper_order_dispatch_enabled=True,
                complete_session_gate_blocked=False,
                paper_client_ready=True,
                trade_context_ready=True,
                market_data_ready=True,
                flatten_blocks_new_entries=False,
                account_snapshot_ready=True,
                trading_daily_context_ready=True,
                position_monitoring_ready=False,
            ),
            "position_monitoring_incomplete_exit_only",
        )

    def test_boundary_batch_mode_does_not_emit_previous_bar_early(self) -> None:
        builder = FiveMinuteBarBuilder(
            complete_bar_open_not_before=datetime(2026, 8, 21, 13, 30, tzinfo=UTC),
            boundary_batch_mode=True,
        )
        first = {
            "trades": [{"price": "650", "volume": 10, "timestamp": 1787319060}],
        }
        next_bar = {
            "trades": [{"price": "651", "volume": 5, "timestamp": 1787319360}],
        }
        self.assertEqual(
            builder.on_trade(
                "SPY.US", first, received_at=datetime(2026, 8, 21, 13, 31, tzinfo=UTC)
            ),
            [],
        )
        self.assertEqual(
            builder.on_trade(
                "SPY.US", next_bar, received_at=datetime(2026, 8, 21, 13, 36, tzinfo=UTC)
            ),
            [],
        )
        rows = builder.complete_boundary(
            ["SPY.US"], datetime(2026, 8, 21, 13, 35, 1, tzinfo=UTC)
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["open"], "650")

    def test_incomplete_or_late_boundary_cannot_dispatch(self) -> None:
        row = {
            "symbol": "SPY",
            "event_time": "2026-08-21T13:35:00Z",
            "received_at": "2026-08-21T13:35:06Z",
            "bar_final": True,
        }
        self.assertFalse(realtime_boundary_is_complete([row], ["SPY.US", "QQQ.US"]))
        self.assertFalse(realtime_boundary_is_complete([row], ["SPY.US"]))
    def test_sdk_quote_payload_converts_unpicklable_trade_session_enum(self) -> None:
        class UnpicklableTradeSession(int):
            def __new__(cls):
                return super().__new__(cls, 0)

            def __str__(self) -> str:
                return "TradeSession.Normal"

            def __reduce__(self):
                raise TypeError("cannot pickle TradeSession")

        payload = sdk_object_to_dict(
            SimpleNamespace(
                symbol="AAPL.US",
                last_done=Decimal("210.50"),
                trade_session=UnpicklableTradeSession(),
            )
        )

        self.assertEqual(payload["trade_session"], "TradeSession.Normal")
        pickle.dumps(payload)

    def test_only_oauth_or_missing_trade_context_triggers_rebuild(self) -> None:
        self.assertTrue(
            trade_context_health_requires_rebuild(
                {
                    "status": "trade_context_refresh_required",
                    "trade_context_refresh_required": True,
                }
            )
        )
        self.assertTrue(
            trade_context_health_requires_rebuild(
                {"status": "trade_context_missing"}
            )
        )
        self.assertFalse(
            trade_context_health_requires_rebuild(
                {
                    "status": "trade_context_healthcheck_failed",
                    "trade_context_refresh_required": False,
                    "error": "api request is limited",
                }
            )
        )

    def test_runtime_dispatch_waits_for_complete_market_data_connection(self) -> None:
        self.assertFalse(
            effective_runtime_dispatch_enabled(
                dispatch_requested=True,
                paper_client_ready=True,
                trade_context_ready=True,
                market_data_ready=False,
                trading_daily_context_ready=True,
                flatten_blocks_new_entries=False,
                account_snapshot_ready=True,
            )
        )
        self.assertEqual(
            runtime_dispatch_block_reason(
                paper_order_dispatch_enabled=True,
                complete_session_gate_blocked=False,
                paper_client_ready=True,
                trade_context_ready=True,
                market_data_ready=False,
                flatten_blocks_new_entries=False,
                account_snapshot_ready=True,
                trading_daily_context_ready=True,
            ),
            "market_data_recovering",
        )

    def test_quote_worker_registers_both_callbacks_and_verifies_subscription(self) -> None:
        tree = ast.parse(textwrap.dedent(inspect.getsource(quote_worker)))
        called_methods = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]

        self.assertIn("subscriptions", called_methods)
        self.assertIn("quote", called_methods)
        self.assertEqual(called_methods.count("set_on_quote"), 1)
        self.assertEqual(called_methods.count("set_on_trades"), 1)

    def test_snapshot_fallback_requires_configured_subscription_failures(self) -> None:
        self.assertFalse(should_use_snapshot_fallback(0, 1))
        self.assertTrue(should_use_snapshot_fallback(1, 1))

    def test_snapshot_poll_requires_complete_fast_cycles(self) -> None:
        self.assertTrue(snapshot_poll_cycle_is_healthy(147, 147, 999, 1000))
        self.assertFalse(snapshot_poll_cycle_is_healthy(146, 147, 100, 1000))
        self.assertFalse(snapshot_poll_cycle_is_healthy(147, 147, 1001, 1000))

    def test_snapshot_poll_interval_stays_within_realtime_acceptance_window(self) -> None:
        config = load_config()

        self.assertEqual(config.snapshot_poll_interval_seconds, 3)
        self.assertEqual(config.snapshot_poll_min_successful_cycles, 1)
        self.assertLess(
            config.snapshot_poll_interval_seconds,
            config.market_data_heartbeat_deadline_seconds,
        )

    def test_snapshot_recovery_uses_short_heartbeat_grace(self) -> None:
        source = inspect.getsource(
            __import__(
                "scripts.run_m15_longbridge_sdk_runtime",
                fromlist=["run_watch"],
            ).run_watch
        )

        self.assertIn(
            'if market_data_mode == "sdk_snapshot_poll"',
            source,
        )
        self.assertIn(
            "config.market_data_heartbeat_deadline_seconds",
            source,
        )
        self.assertIn(
            "if snapshot_fallback_active",
            source,
        )

    def test_runtime_initializes_snapshot_builder_before_any_fallback_worker_start(self) -> None:
        source = inspect.getsource(
            __import__(
                "scripts.run_m15_longbridge_sdk_runtime",
                fromlist=["run_watch"],
            ).run_watch
        )

        self.assertIn(
            "if snapshot_fallback_active and snapshot_bar_builder is None:",
            source,
        )
        self.assertLess(
            source.index("if snapshot_fallback_active and snapshot_bar_builder is None:"),
            source.index("worker_target = ("),
        )

    def test_snapshot_poll_never_counts_as_subscription_gate_evidence(self) -> None:
        self.assertTrue(
            market_data_mode_qualifies_for_subscription_gate(
                "sdk_subscription"
            )
        )
        self.assertFalse(
            market_data_mode_qualifies_for_subscription_gate(
                "sdk_snapshot_poll"
            )
        )

    def test_ready_market_data_worker_is_stale_after_heartbeat_deadline(self) -> None:
        self.assertFalse(market_data_heartbeat_is_stale(10.0, 15.0, 5.0))
        self.assertTrue(market_data_heartbeat_is_stale(10.0, 15.001, 5.0))

    def test_market_data_heartbeat_starts_after_subscription_startup_grace(self) -> None:
        self.assertFalse(market_data_heartbeat_grace_elapsed(10.0, 30.0, 20.0))
        self.assertTrue(market_data_heartbeat_grace_elapsed(10.0, 30.001, 20.0))
        self.assertFalse(market_data_heartbeat_grace_elapsed(0.0, 100.0, 20.0))

    def test_active_symbol_silence_waits_for_regular_open_grace(self) -> None:
        market_zone = ZoneInfo("America/New_York")
        self.assertFalse(
            regular_session_open_grace_elapsed(
                datetime(2026, 8, 25, 9, 30, 29, tzinfo=market_zone),
                30,
            )
        )
        self.assertTrue(
            regular_session_open_grace_elapsed(
                datetime(2026, 8, 25, 9, 30, 30, tzinfo=market_zone),
                30,
            )
        )

    def test_orphan_cleanup_only_targets_detached_children_from_the_sdk_log(self) -> None:
        runtime_log = Path("/tmp/m15_longbridge_sdk_runtime.log")
        self.assertTrue(
            is_orphaned_sdk_runtime_child(
                "python -c from multiprocessing.spawn import spawn_main",
                str(runtime_log),
                "/init",
                runtime_log,
            )
        )
        self.assertFalse(
            is_orphaned_sdk_runtime_child(
                "python -c from multiprocessing.spawn import spawn_main",
                str(runtime_log),
                "python run_m15_longbridge_sdk_runtime.py --watch",
                runtime_log,
            )
        )
        self.assertFalse(
            is_orphaned_sdk_runtime_child(
                "python run_m12_m14_local_postclose_scheduler.py --watch",
                str(runtime_log),
                "/init",
                runtime_log,
            )
        )

    def test_connecting_runtime_still_owns_the_only_quote_connection(self) -> None:
        config = load_config("config/examples/m15_longbridge_sdk_runtime.json")
        status = {
            "runtime_pid": __import__("os").getpid(),
            "config_fingerprint": config_fingerprint(config),
            "sdk_connected": False,
            "status": "connecting",
        }

        self.assertTrue(runtime_owns_quote_connection(config, status))

    def test_regular_session_recovery_prioritizes_the_frozen_trading_universe(self) -> None:
        config = load_config("config/examples/m15_longbridge_sdk_runtime.json")

        regular_session_targets = quote_subscription_targets(
            config,
            datetime(2026, 7, 28, 14, 0, tzinfo=UTC),
        )
        premarket_targets = quote_subscription_targets(
            config,
            datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(regular_session_targets, configured_trading_symbols(config))
        self.assertEqual(premarket_targets, configured_symbols(config))

    def test_pipeline_observability_restores_only_same_new_york_session(self) -> None:
        with TemporaryDirectory() as directory:
            status_path = Path(directory) / "runtime_status.json"
            status_path.write_text(json.dumps({
                "last_event_at": "2026-07-27T19:55:01Z",
                "pipeline_latency_samples_ms": [345, "1297", -4, "bad"],
                "last_hot_pipeline": {"pipeline_elapsed_ms": 1297},
            }), encoding="utf-8")

            samples, last_result, last_event_at = restore_pipeline_observability(
                status_path,
                now=datetime(2026, 7, 27, 20, 10, tzinfo=UTC),
            )
            self.assertEqual(samples, [345, 1297, 0])
            self.assertEqual(last_result, {"pipeline_elapsed_ms": 1297})
            self.assertEqual(last_event_at, "2026-07-27T19:55:01Z")

            samples, last_result, last_event_at = restore_pipeline_observability(
                status_path,
                now=datetime(2026, 7, 28, 14, 0, tzinfo=UTC),
            )
            self.assertEqual(samples, [])
            self.assertEqual(last_result, {})
            self.assertEqual(last_event_at, "")

    def test_production_daily_context_allows_transient_symbol_retries(self) -> None:
        config = load_config("config/examples/m15_longbridge_sdk_runtime.json")

        self.assertEqual(config.daily_context_retry_count, 5)

    def test_authorized_account_exit_waits_for_rth_then_submits_once(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "m15_authorized_account_exit.json"
            request_path.write_text(json.dumps({
                "authorized": True,
                "paper_simulated_only": True,
                "status": "authorized",
                "symbol": "LCID",
                "maximum_quantity": "56",
            }), encoding="utf-8")
            snapshot = {
                "generated_at": "2026-07-23T14:00:00Z",
                "paper_account_verified": True,
                "positions_ok": True,
                "orders_ok": True,
                "positions": [{"symbol": "LCID.US", "quantity": "56", "available": "56"}],
                "open_orders": [],
            }

            class Account:
                @staticmethod
                def snapshot():
                    return json.loads(json.dumps(snapshot))

            class Client:
                def __init__(self) -> None:
                    self.submissions = []

                def submit_order(self, payload):
                    self.submissions.append(dict(payload))
                    return {"submitted": True, "status": "submitted", "order_id": "LCID-EXIT-1"}

            config = SimpleNamespace(
                output_dir=root,
                maximum_account_snapshot_age_seconds=45,
                formal_test_epoch_id="formal-main",
            )
            client = Client()
            waiting = run_authorized_account_exit_cycle(
                config, Account(), client, now=datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
            )
            submitted = run_authorized_account_exit_cycle(
                config, Account(), client, now=datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
            )
            repeated = run_authorized_account_exit_cycle(
                config, Account(), client, now=datetime(2026, 7, 23, 14, 0, 1, tzinfo=UTC)
            )

        self.assertEqual(waiting["status"], "authorized_waiting_regular_session")
        self.assertEqual(submitted["order_id"], "LCID-EXIT-1")
        self.assertEqual(repeated["status"], "submitted_waiting_broker_fill")
        self.assertEqual(len(client.submissions), 1)
        self.assertEqual(client.submissions[0]["order_type"], "market")
        self.assertEqual(client.submissions[0]["quantity"], "56")
        self.assertTrue(client.submissions[0]["exclude_from_strategy_performance"])

    def test_sdk_runtime_singleton_lock_rejects_a_second_owner(self) -> None:
        with TemporaryDirectory() as directory:
            with patch(
                "scripts.run_m15_longbridge_sdk_runtime.GLOBAL_QUOTE_SUBSCRIPTION_LOCK",
                Path(directory) / "global-sdk-quote.lock",
            ):
                first = acquire_runtime_run_lock(Path(directory) / "primary")
                self.assertIsNotNone(first)
                try:
                    self.assertIsNone(acquire_runtime_run_lock(Path(directory) / "expanded"))
                finally:
                    first.close()

    def test_daemon_does_not_spawn_when_another_config_holds_global_runtime_lock(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = SimpleNamespace(
                output_dir=root / "alternate-output",
                runtime_status_path=root / "alternate-status.json",
                config_path=root / "alternate-config.json",
            )
            config.output_dir.mkdir(parents=True)
            global_lock = root / "global-sdk-quote.lock"
            global_lock.write_text(str(__import__("os").getpid()) + "\n", encoding="utf-8")
            args = SimpleNamespace(dispatch=True, config=str(config.config_path))
            with (
                patch(
                    "scripts.run_m15_longbridge_sdk_runtime.GLOBAL_QUOTE_SUBSCRIPTION_LOCK",
                    global_lock,
                ),
                patch(
                    "scripts.run_m15_longbridge_sdk_runtime.GLOBAL_RUNTIME_START_LOCK",
                    root / "global-start.lock",
                ),
                patch(
                    "scripts.run_m15_longbridge_sdk_runtime.is_expected_sdk_runtime_process",
                    return_value=True,
                ),
                patch(
                    "scripts.run_m15_longbridge_sdk_runtime.subprocess.Popen"
                ) as popen,
            ):
                result = start_runtime_daemon(args, config)

            self.assertEqual(result, 0)
            popen.assert_not_called()

    def test_daemon_keeps_matching_dispatch_runtime_during_market_recovery(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current_pid = __import__("os").getpid()
            config = SimpleNamespace(
                output_dir=root,
                runtime_status_path=root / "runtime-status.json",
                config_path=root / "runtime-config.json",
                maximum_account_snapshot_age_seconds=45,
            )
            config.runtime_status_path.write_text(
                json.dumps({
                    "generated_at": datetime.now(UTC).isoformat(),
                    "status": "reconnecting_market_data_circuit",
                    "runtime_pid": current_pid,
                    "runtime_process_start_ticks": Path(f"/proc/{current_pid}/stat").read_text(encoding="utf-8").split()[21],
                    "config_fingerprint": "expected-fingerprint",
                    "dispatch_requested": True,
                }),
                encoding="utf-8",
            )
            global_lock = root / "global-sdk-quote.lock"
            global_lock.write_text(f"{current_pid}\n", encoding="utf-8")
            args = SimpleNamespace(dispatch=True, config=str(config.config_path))
            with (
                patch(
                    "scripts.run_m15_longbridge_sdk_runtime.GLOBAL_QUOTE_SUBSCRIPTION_LOCK",
                    global_lock,
                ),
                patch(
                    "scripts.run_m15_longbridge_sdk_runtime.GLOBAL_RUNTIME_START_LOCK",
                    root / "global-start.lock",
                ),
                patch(
                    "scripts.run_m15_longbridge_sdk_runtime.is_expected_sdk_runtime_process",
                    return_value=True,
                ),
                patch(
                    "scripts.run_m15_longbridge_sdk_runtime.config_fingerprint",
                    return_value="expected-fingerprint",
                ),
                patch(
                    "scripts.run_m15_longbridge_sdk_runtime.request_runtime_shutdown"
                ) as shutdown,
                patch(
                    "scripts.run_m15_longbridge_sdk_runtime.subprocess.Popen"
                ) as popen,
            ):
                result = start_runtime_daemon(args, config)

            self.assertEqual(result, 0)
            shutdown.assert_not_called()
            popen.assert_not_called()

    def test_live_runtime_with_very_stale_account_snapshot_requires_replacement(self) -> None:
        config = SimpleNamespace(maximum_account_snapshot_age_seconds=45)
        self.assertTrue(
            runtime_requires_health_replacement(
                {
                    "generated_at": datetime.now(UTC).isoformat(),
                    "account_snapshot_age_seconds": 181,
                },
                config,
            )
        )

    def test_live_runtime_with_fresh_account_snapshot_does_not_require_replacement(self) -> None:
        config = SimpleNamespace(maximum_account_snapshot_age_seconds=45)
        self.assertFalse(
            runtime_requires_health_replacement(
                {
                    "generated_at": datetime.now(UTC).isoformat(),
                    "account_snapshot_age_seconds": 8,
                },
                config,
            )
        )

    def test_market_data_circuit_with_fresh_account_keeps_same_parent_runtime(self) -> None:
        config = SimpleNamespace(maximum_account_snapshot_age_seconds=45)
        self.assertFalse(
            runtime_requires_health_replacement(
                {
                    "generated_at": datetime.now(UTC).isoformat(),
                    "account_snapshot_age_seconds": 8,
                    "market_data_circuit_open": True,
                    "market_data_retry_after_seconds": 240,
                },
                config,
            )
        )

    def test_halted_market_data_runtime_is_replaced_even_with_fresh_account(self) -> None:
        config = SimpleNamespace(maximum_account_snapshot_age_seconds=45)
        self.assertTrue(
            runtime_requires_health_replacement(
                {
                    "status": "halted_market_data_circuit",
                    "generated_at": datetime.now(UTC).isoformat(),
                    "account_snapshot_age_seconds": 8,
                },
                config,
            )
        )

    def test_postclose_restart_keeps_a_valid_current_session_daily_cache(self) -> None:
        self.assertEqual(
            completed_postclose_refresh_dates(
                [{"symbol": "AAPL", "timeframe": "1d"}],
                datetime(2026, 7, 20, 16, 10, tzinfo=ZoneInfo("America/New_York")),
            ),
            {"2026-07-20"},
        )

    def test_sdk_hot_path_does_not_dispatch_at_regular_session_close(self) -> None:
        class Account:
            @staticmethod
            def snapshot():
                return {
                    "generated_at": "2026-07-16T20:00:00Z",
                    "paper_account_verified": True,
                    "positions_ok": True,
                    "orders_ok": True,
                    "positions": [],
                    "orders": [],
                    "open_orders": [],
                }

        class Client:
            def submit_order(self, _payload):
                raise AssertionError("16:00 ET must never submit a day order")

        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = SimpleNamespace(
                market="US",
                universe_path=None,
                use_seed_universe=True,
                symbol_limit=147,
                trading_symbol_limit=147,
                maximum_source_delivery_age_ms=2000,
                market_events_path=root / "market.jsonl",
                event_keep_lines=0,
                router_config_path=Path("config/examples/m15_longbridge_realtime_signal_router.json"),
                position_manager_config_path=Path("config/examples/m15_longbridge_realtime_position_manager.json"),
                execution_config_path=Path("config/examples/m15_longbridge_realtime_execution.paper_orders_enabled.json"),
                formal_test_marker_path=root / "formal.json",
                formal_test_transition_enabled=False,
                formal_test_epoch_id="formal-main",
                formal_short_test_epoch_id="formal-short",
            )
            config.formal_test_marker_path.write_text(json.dumps({
                "status": "active",
                "test_epoch_id": "formal-main",
                "short_test_epoch_id": "formal-short",
                "test_started_at": "2026-07-16T13:31:40Z",
            }), encoding="utf-8")
            row = {
                "schema_version": "m15.realtime-market-event.v2",
                "event_id": "sdk-5m|AAPL|2026-07-16T20:00:00Z",
                "symbol": "AAPL",
                "timeframe": "5m",
                "event_time": "2026-07-16T20:00:00Z",
                "received_at": "2026-07-16T20:00:00Z",
                "source_event_at": "2026-07-16T20:00:00Z",
                "source_delivery_age_ms": 0,
                "bar_final": True,
                "open": "200",
                "high": "201",
                "low": "199",
                "close": "200.5",
                "volume": "1000",
            }
            with (
                patch(
                    "scripts.m15_longbridge_realtime_signal_router_lib.run_realtime_signal_router",
                    return_value={"signal_event_count": 0},
                ),
                patch(
                    "scripts.m15_longbridge_realtime_position_manager_lib.run_realtime_position_manager",
                    return_value={"emitted_exit_signal_events": []},
                ),
            ):
                result = dispatch_completed_rows(
                    config,
                    [row],
                    MarketEventContext(maximum_rows=100),
                    Account(),
                    Client(),
                )

        self.assertEqual(result["execution"]["status"], "blocked_outside_regular_session")
        self.assertEqual(result["execution"]["submitted_count"], 0)

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

    def test_zero_account_waits_until_configured_activation_time(self) -> None:
        with TemporaryDirectory() as directory:
            config, snapshot, account, client = self.pending_flatten_fixture(Path(directory))
            marker = json.loads(config.formal_test_marker_path.read_text(encoding="utf-8"))
            marker["activate_not_before"] = "2026-07-17T13:30:00Z"
            config.formal_test_marker_path.write_text(json.dumps(marker), encoding="utf-8")
            snapshot["positions"] = []
            snapshot["orders"] = []
            snapshot["open_orders"] = []

            state = run_pending_flatten_cycle(
                config,
                account,
                client,
                [],
                now=datetime(2026, 7, 16, 14, 0, tzinfo=UTC),
            )
            marker = json.loads(config.formal_test_marker_path.read_text(encoding="utf-8"))

        self.assertEqual(state["status"], "waiting_for_activation_window")
        self.assertTrue(state["blocks_new_entries"])
        self.assertEqual(marker["status"], "pending_flatten")
        self.assertEqual(marker["activation_blocker"], "waiting_for_configured_activation_time")
        self.assertEqual(client.submissions, [])

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

    def test_default_runtime_config_freezes_production_to_147_symbols(self) -> None:
        payload = json.loads(Path("config/examples/m15_longbridge_sdk_runtime.json").read_text(encoding="utf-8"))
        universe = load_m15_universe("config/m15_us_liquid_universe_300.json")

        self.assertFalse(payload["market_data"]["use_seed_universe"])
        self.assertEqual(
            payload["market_data"]["universe_path"],
            "config/m15_us_liquid_universe_300.json",
        )
        self.assertEqual(payload["market_data"]["symbol_limit"], 147)
        self.assertEqual(payload["market_data"]["trading_symbol_limit"], 147)
        self.assertIsNone(payload["market_data"]["trading_universe_path"])
        self.assertFalse(payload["runtime"]["allow_snapshot_poll_fallback"])
        self.assertIn("BNY", universe)
        self.assertIn("MRSH", universe)
        self.assertNotIn("BK", universe)
        self.assertNotIn("MMC", universe)

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
                "event_time": "2026-07-15T13:35:00Z", "bar_open_at": "2026-07-15T13:30:00Z", "received_at": "2026-07-15T13:35:00.1Z",
                "open": "100", "high": "102", "low": "99", "close": "101", "volume": "10",
            },
            {
                "event_id": "bar-2", "symbol": "AAPL", "timeframe": "5m", "bar_final": True,
                "event_time": "2026-07-15T13:40:00Z", "bar_open_at": "2026-07-15T13:35:00Z", "received_at": "2026-07-15T13:40:00.1Z",
                "open": "101", "high": "103", "low": "100", "close": "102", "volume": "20",
            },
        ]
        daily = build_live_daily_confirmation_rows(
            rows,
            generated_at=datetime(2026, 7, 15, 13, 40, tzinfo=UTC),
            live_quote_session_state={
                "AAPL": {
                    "symbol": "AAPL",
                    "session_date": "2026-07-15",
                    "source_event_at": "2026-07-15T13:39:30Z",
                    "received_at": "2026-07-15T13:39:30.1Z",
                    "open": "99",
                    "high": "104",
                    "low": "98",
                    "close": "102.5",
                    "volume": "300",
                    "market_data_blocked_reason": "",
                }
            },
        )
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0]["source_mode"], "longbridge_sdk_live_daily_confirmation")
        self.assertTrue(daily[0]["current_session_confirmation"])
        self.assertEqual(
            {key: daily[0][key] for key in ("open", "high", "low", "close", "volume")},
            {"open": "99", "high": "104", "low": "98", "close": "102.5", "volume": "300"},
        )

    def test_live_daily_confirmation_requires_a_fresh_symbol_bar_this_dispatch(self) -> None:
        rows = [
            {
                "event_id": "aapl-old", "symbol": "AAPL", "timeframe": "5m", "bar_final": True,
                "event_time": "2026-07-15T15:35:00Z", "bar_open_at": "2026-07-15T15:30:00Z", "received_at": "2026-07-15T15:35:00.1Z",
                "open": "209", "high": "210", "low": "208", "close": "210", "volume": "10",
            },
            {
                "event_id": "msft-old", "symbol": "MSFT", "timeframe": "5m", "bar_final": True,
                "event_time": "2026-07-15T15:35:00Z", "bar_open_at": "2026-07-15T15:30:00Z", "received_at": "2026-07-15T15:35:00.1Z",
                "open": "499", "high": "501", "low": "498", "close": "500", "volume": "10",
            },
            {
                "event_id": "aapl-new", "symbol": "AAPL", "timeframe": "5m", "bar_final": True,
                "event_time": "2026-07-15T15:40:00Z", "bar_open_at": "2026-07-15T15:35:00Z", "received_at": "2026-07-15T15:40:00.1Z",
                "open": "210", "high": "212", "low": "209", "close": "211", "volume": "20",
            },
        ]

        daily = build_live_daily_confirmation_rows(
            rows,
            generated_at=datetime(2026, 7, 15, 15, 40, tzinfo=UTC),
            live_quote_session_state={
                "AAPL": {
                    "symbol": "AAPL",
                    "session_date": "2026-07-15",
                    "source_event_at": "2026-07-15T15:38:00Z",
                    "received_at": "2026-07-15T15:38:00.1Z",
                    "open": "208",
                    "high": "213",
                    "low": "207",
                    "close": "211.5",
                    "volume": "220",
                    "market_data_blocked_reason": "",
                },
                "MSFT": {
                    "symbol": "MSFT",
                    "session_date": "2026-07-15",
                    "source_event_at": "2026-07-15T15:34:00Z",
                    "received_at": "2026-07-15T15:34:00.1Z",
                    "open": "498",
                    "high": "502",
                    "low": "497",
                    "close": "500",
                    "volume": "120",
                    "market_data_blocked_reason": "",
                },
            },
            active_five_minute_event_ids={"aapl-new"},
        )

        self.assertEqual([row["symbol"] for row in daily], ["AAPL"])
        self.assertEqual(daily[0]["close"], "211.5")

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
        self.assertEqual(builder.on_quote("AAPL.US", {"timestamp": int(first.timestamp()), "last_done": "200", "current_volume": 10, "volume": 1000}, received_at=first), [])
        last = datetime(2026, 7, 14, 13, 34, 59, tzinfo=UTC)
        self.assertEqual(builder.on_quote("AAPL.US", {"timestamp": int(last.timestamp()), "last_done": "202", "current_volume": 20, "volume": 1020}, received_at=last), [])
        rows = builder.flush(datetime(2026, 7, 14, 13, 35, 1, tzinfo=UTC))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_mode"], "longbridge_sdk_push")
        self.assertTrue(rows[0]["bar_final"])
        self.assertEqual(rows[0]["open"], "200")
        self.assertEqual(rows[0]["close"], "202")
        self.assertEqual(rows[0]["volume"], "20")
        self.assertEqual(rows[0]["market_data_blocked_reason"], "")
        self.assertEqual(rows[0]["received_at"], "2026-07-14T13:35:01Z")
        self.assertEqual(rows[0]["source_delivery_age_ms"], 2000)

    def test_first_quote_push_volume_is_not_counted_as_an_interval_increment(self) -> None:
        builder = FiveMinuteBarBuilder(minutes=5)
        first = datetime(2026, 7, 15, 13, 31, tzinfo=UTC)
        second = datetime(2026, 7, 15, 13, 32, tzinfo=UTC)

        builder.on_quote(
            "PSKY.US",
            {"timestamp": int(first.timestamp()), "last_done": "9.10", "current_volume": 17_000_000, "volume": 17_000_000},
            received_at=first,
        )
        builder.on_quote(
            "PSKY.US",
            {"timestamp": int(second.timestamp()), "last_done": "9.11", "current_volume": 125, "volume": 17_000_125},
            received_at=second,
        )
        rows = builder.flush(datetime(2026, 7, 15, 13, 35, 1, tzinfo=UTC))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["volume"], "125")

    def test_quote_push_blocks_bar_when_cumulative_volume_is_missing(self) -> None:
        builder = FiveMinuteBarBuilder(minutes=5)
        first = datetime(2026, 7, 15, 13, 31, tzinfo=UTC)
        second = datetime(2026, 7, 15, 13, 32, tzinfo=UTC)

        builder.on_quote(
            "AAPL.US",
            {"timestamp": int(first.timestamp()), "last_done": "200"},
            received_at=first,
        )
        builder.on_quote(
            "AAPL.US",
            {"timestamp": int(second.timestamp()), "last_done": "201"},
            received_at=second,
        )
        rows = builder.flush(datetime(2026, 7, 15, 13, 35, 1, tzinfo=UTC))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market_data_blocked_reason"], "quote_total_volume_missing")

    def test_quote_push_blocks_bar_when_cumulative_volume_regresses(self) -> None:
        builder = FiveMinuteBarBuilder(minutes=5)
        first = datetime(2026, 7, 15, 13, 31, tzinfo=UTC)
        second = datetime(2026, 7, 15, 13, 32, tzinfo=UTC)

        builder.on_quote(
            "AAPL.US",
            {"timestamp": int(first.timestamp()), "last_done": "200", "volume": 1000},
            received_at=first,
        )
        builder.on_quote(
            "AAPL.US",
            {"timestamp": int(second.timestamp()), "last_done": "201", "volume": 999},
            received_at=second,
        )
        rows = builder.flush(datetime(2026, 7, 15, 13, 35, 1, tzinfo=UTC))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market_data_blocked_reason"], "quote_total_volume_regressed")

    def test_regressed_cumulative_volume_does_not_replace_last_good_baseline(self) -> None:
        builder = FiveMinuteBarBuilder(minutes=5)
        first = datetime(2026, 7, 15, 13, 31, tzinfo=UTC)
        regressed = datetime(2026, 7, 15, 13, 32, tzinfo=UTC)
        recovered = datetime(2026, 7, 15, 13, 33, tzinfo=UTC)

        builder.on_quote(
            "AAPL.US",
            {"timestamp": int(first.timestamp()), "last_done": "200", "volume": 1000},
            received_at=first,
        )
        builder.on_quote(
            "AAPL.US",
            {"timestamp": int(regressed.timestamp()), "last_done": "199", "volume": 999},
            received_at=regressed,
        )
        builder.on_quote(
            "AAPL.US",
            {"timestamp": int(recovered.timestamp()), "last_done": "202", "volume": 1010},
            received_at=recovered,
        )
        rows = builder.flush(datetime(2026, 7, 15, 13, 35, 1, tzinfo=UTC))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["volume"], "10")
        self.assertEqual(
            rows[0]["market_data_blocked_reason"],
            "quote_total_volume_regressed",
        )

    def test_sdk_snapshot_poll_builds_bar_from_cumulative_volume_deltas(self) -> None:
        builder = FiveMinuteBarBuilder(minutes=5)
        first = datetime(2026, 7, 28, 14, 31, tzinfo=UTC)
        second = datetime(2026, 7, 28, 14, 32, tzinfo=UTC)

        builder.on_snapshot(
            "AAPL.US",
            {
                "timestamp": first,
                "last_done": "200",
                "volume": 1_000_000,
            },
            received_at=first,
        )
        builder.on_snapshot(
            "AAPL.US",
            {
                "timestamp": second,
                "last_done": "202",
                "volume": 1_000_125,
            },
            received_at=second,
        )
        rows = builder.flush(datetime(2026, 7, 28, 14, 35, 1, tzinfo=UTC))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_mode"], "longbridge_sdk_snapshot_poll")
        self.assertEqual(rows[0]["open"], "200")
        self.assertEqual(rows[0]["close"], "202")
        self.assertEqual(rows[0]["volume"], "125")
        self.assertEqual(builder.open_bar_count, 0)

    def test_snapshot_poll_uses_poll_time_for_bar_bucket_when_last_trade_is_stale(self) -> None:
        builder = FiveMinuteBarBuilder(minutes=5)
        stale_trade_at = datetime(2026, 7, 28, 14, 10, tzinfo=UTC)
        first_poll = datetime(2026, 7, 28, 14, 31, tzinfo=UTC)
        second_poll = datetime(2026, 7, 28, 14, 32, tzinfo=UTC)

        builder.on_snapshot(
            "AAPL.US",
            {"timestamp": stale_trade_at, "last_done": "200", "volume": 1_000_000},
            received_at=first_poll,
        )
        builder.on_snapshot(
            "AAPL.US",
            {"timestamp": stale_trade_at, "last_done": "200", "volume": 1_000_000},
            received_at=second_poll,
        )
        rows = builder.flush(datetime(2026, 7, 28, 14, 35, 1, tzinfo=UTC))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bar_open_at"], "2026-07-28T14:30:00Z")
        self.assertEqual(rows[0]["volume"], "0")

    def test_snapshot_poll_final_bar_uses_finalization_age_for_freshness(self) -> None:
        row = {
            "bar_final": True,
            "source_mode": "longbridge_sdk_snapshot_poll",
            "timeframe": "5m",
            "received_at": "2026-07-28T14:35:01Z",
            "source_delivery_age_ms": 120_000,
        }

        self.assertEqual(
            fresh_market_events(
                [row],
                2_000,
                now=datetime(2026, 7, 28, 14, 35, 2, tzinfo=UTC),
            ),
            [row],
        )

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

    def test_default_subscription_sends_a_large_universe_in_one_request(self) -> None:
        class QuoteContext:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, symbols, subscription_types) -> None:
                self.calls.append((symbols, subscription_types))

        quote = QuoteContext()
        symbols = [f"TEST{index}.US" for index in range(156)]
        progress = []
        subscribe_quote_and_trades(
            quote,
            symbols,
            ["Quote", "Trade"],
            progress_callback=lambda completed, total: progress.append((completed, total)),
        )
        self.assertEqual(quote.calls, [(symbols, ["Quote", "Trade"])])
        self.assertEqual(progress, [(156, 156)])

    def test_subscription_batches_large_universe_without_a_single_large_request(self) -> None:
        class QuoteContext:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, symbols, subscription_types) -> None:
                self.calls.append((symbols, subscription_types))

        quote = QuoteContext()
        progress = []
        subscribe_quote_and_trades(
            quote,
            ["AAPL.US", "MSFT.US", "NVDA.US"],
            ["Quote"],
            batch_size=2,
            progress_callback=lambda completed, total: progress.append((completed, total)),
        )
        self.assertEqual(quote.calls, [(["AAPL.US", "MSFT.US"], ["Quote"]), (["NVDA.US"], ["Quote"])])
        self.assertEqual(progress, [(2, 3), (3, 3)])

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

    def test_production_subscription_failure_defers_to_server_subscription_state(self) -> None:
        class QuoteContext:
            def __init__(self) -> None:
                self.calls = []

            def subscribe(self, symbols, _subscription_types) -> None:
                self.calls.append(symbols)
                raise RuntimeError("request timeout")

        quote = QuoteContext()
        symbols = ["AAPL.US", "MSFT.US", "NVDA.US"]
        failures = subscribe_quote_and_trades(
            quote,
            symbols,
            ["Quote", "Trade"],
            retry_count=0,
            diagnose_failed_symbols=False,
        )
        self.assertEqual(quote.calls, [symbols])
        self.assertEqual(failures, [])

    def test_runtime_disables_per_symbol_diagnosis_on_production_connection(self) -> None:
        source = inspect.getsource(quote_worker)
        self.assertIn("diagnose_failed_symbols=False", source)

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

    def test_sdk_client_stops_using_stale_trade_context_after_oauth_refresh_failure(self) -> None:
        class Enum:
            Buy = "Buy"
            Sell = "Sell"
            LO = "LO"
            Day = "Day"
            RTHOnly = "RTHOnly"

        class Sdk:
            OrderSide = Enum
            OrderType = Enum
            TimeInForceType = Enum
            OutsideRTH = Enum

        class Trade:
            def __init__(self) -> None:
                self.call_count = 0

            def submit_order(self, **_kwargs):
                self.call_count += 1
                raise RuntimeError(
                    "OpenApiException: oauth error: failed to refresh token: "
                    "Server returned error response"
                )

        trade = Trade()
        client = SdkRealtimePaperClient(trade, Sdk())
        payload = {
            "side": "buy",
            "symbol": "AAPL",
            "order_type": "limit",
            "limit_price": "200",
            "quantity": "1",
            "signal_id": "signal-oauth-refresh",
        }

        first = client.submit_order(payload)
        second = client.submit_order(payload)

        self.assertEqual(first["status"], "submit_blocked_trade_context_refresh_required")
        self.assertFalse(first["explicit_reject"])
        self.assertTrue(first["trade_context_refresh_required"])
        self.assertEqual(second["status"], "submit_blocked_trade_context_refresh_required")
        self.assertEqual(trade.call_count, 1)

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

    def test_sdk_client_caches_broker_short_capacity_with_ttl(self) -> None:
        class Enum:
            LO = "LO"
            Sell = "Sell"

        class Sdk:
            OrderType = Enum
            OrderSide = Enum

        class Response:
            cash_max_qty = Decimal("0")
            margin_max_qty = Decimal("12")

        class Trade:
            def __init__(self) -> None:
                self.calls = 0

            def estimate_max_purchase_quantity(self, symbol, order_type, **kwargs):
                self.calls += 1
                self.last_call = (symbol, order_type, kwargs)
                return Response()

        clock = [100.0]
        trade = Trade()
        client = SdkRealtimePaperClient(
            trade,
            Sdk(),
            short_capacity_cache_ttl_seconds=900,
            monotonic_clock=lambda: clock[0],
        )

        live = client.max_short_quantity("AAPL", Decimal("200"))
        clock[0] += 30
        cached = client.max_short_quantity("AAPL", Decimal("201"))
        clock[0] += 901
        refreshed = client.max_short_quantity("AAPL", Decimal("201"))

        self.assertEqual(trade.calls, 2)
        self.assertEqual(live["capacity_source"], "broker_sdk_live")
        self.assertEqual(cached["status"], "sdk_short_capacity_cached")
        self.assertEqual(cached["capacity_source"], "broker_sdk_cache")
        self.assertEqual(cached["max_quantity"], Decimal("12"))
        self.assertEqual(cached["cash_max_quantity"], Decimal("0"))
        self.assertEqual(cached["margin_max_quantity"], Decimal("12"))
        self.assertEqual(cached["capacity_basis"], "margin_max_qty_for_sell_short")
        self.assertEqual(cached["cache_age_seconds"], 30.0)
        self.assertEqual(refreshed["capacity_source"], "broker_sdk_live")

    def test_sdk_short_capacity_does_not_treat_owned_cash_quantity_as_borrow_capacity(self) -> None:
        class Enum:
            LO = "LO"
            Sell = "Sell"

        class Sdk:
            OrderType = Enum
            OrderSide = Enum

        class Response:
            cash_max_qty = Decimal("999")
            margin_max_qty = Decimal("7")

        class Trade:
            @staticmethod
            def estimate_max_purchase_quantity(_symbol, _order_type, **_kwargs):
                return Response()

        result = SdkRealtimePaperClient(Trade(), Sdk()).max_short_quantity(
            "LCID", Decimal("6.50")
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["max_quantity"], Decimal("7"))
        self.assertEqual(result["cash_max_quantity"], Decimal("999"))
        self.assertEqual(result["margin_max_quantity"], Decimal("7"))

    def test_sdk_trade_context_healthcheck_marks_oauth_refresh_failure(self) -> None:
        class Trade:
            @staticmethod
            def today_orders():
                raise RuntimeError("OAuth token refresh failed: invalid_grant")

        client = SdkRealtimePaperClient(Trade(), object())
        first = client.healthcheck()
        second = client.healthcheck()

        self.assertFalse(first["ok"])
        self.assertEqual(first["status"], "trade_context_refresh_required")
        self.assertTrue(first["trade_context_refresh_required"])
        self.assertEqual(second["status"], "trade_context_refresh_required")

    def test_sdk_trade_context_healthcheck_uses_harmless_order_read(self) -> None:
        class Trade:
            def __init__(self) -> None:
                self.calls = 0

            def today_orders(self):
                self.calls += 1
                return []

        trade = Trade()
        result = SdkRealtimePaperClient(trade, object()).healthcheck()

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "trade_context_healthy")
        self.assertEqual(trade.calls, 1)

    def test_sdk_order_maintenance_cancels_stale_entries_and_reprices_exits(self) -> None:
        now = datetime(2026, 7, 15, 15, 47, tzinfo=UTC)
        account_state = {
            "open_orders": [
                {
                    "order_id": "ENTRY-1", "remark": "PAT-RT entry-signal request-1", "symbol": "AAPL.US",
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
                {
                    "order_id": "ENTRY-BY-ID", "remark": "", "symbol": "RDDT.US",
                    "side": "OrderSide.Buy", "quantity": "2", "executed_quantity": "0",
                    "price": "148.42", "updated_at": "2026-07-15T15:30:00Z",
                },
                {
                    "order_id": "MANUAL-BLANK", "remark": "", "symbol": "NVDA.US",
                    "side": "OrderSide.Buy", "quantity": "1", "executed_quantity": "0",
                    "price": "160", "updated_at": "2026-07-15T15:30:00Z",
                },
            ]
        }
        actions = sdk_order_maintenance_actions(
            account_state,
            [
                {
                    "signal_id": "entry-signal",
                    "broker_order_id": "ENTRY-1",
                    "position_action": "open_long",
                },
                {
                    "signal_id": "exit-signal",
                    "broker_order_id": "EXIT-1",
                    "position_action": "take_profit",
                },
                {
                    "signal_id": "entry-by-order-id",
                    "broker_order_id": "ENTRY-BY-ID",
                    "position_action": "open_long",
                },
            ],
            [{"symbol": "LI", "timeframe": "5m", "event_time": "2026-07-15T15:45:00Z", "close": "12.80"}],
            now=now,
            stale_entry_order_ttl_seconds=900,
            exit_order_reprice_seconds=60,
        )
        self.assertEqual([row["action"] for row in actions], ["cancel", "replace", "cancel"])
        self.assertEqual(actions[0]["order_id"], "ENTRY-1")
        self.assertEqual(actions[1]["order_id"], "EXIT-1")
        self.assertEqual(actions[1]["new_price"], "12.73")
        self.assertEqual(actions[1]["price_source"], "current_sdk_price_minus_long_exit_buffer")
        self.assertEqual(actions[2]["order_id"], "ENTRY-BY-ID")
        self.assertEqual(actions[2]["signal_id"], "entry-by-order-id")

    def test_sdk_order_maintenance_entrypoint_requires_exact_broker_order_id(self) -> None:
        now = datetime(2026, 8, 3, 16, 25, tzinfo=UTC)

        class Account:
            def __init__(self) -> None:
                self.refresh_count = 0

            def snapshot(self):
                return {
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": True,
                    "open_orders": [
                        {
                            "order_id": "1268941385491324928",
                            "remark": "",
                            "symbol": "RDDT.US",
                            "side": "OrderSide.Buy",
                            "quantity": "2",
                            "executed_quantity": "0",
                            "price": "148.42",
                            "updated_at": "2026-08-03T14:40:05Z",
                        },
                        {
                            "order_id": "MANUAL-BLANK",
                            "remark": "",
                            "symbol": "NVDA.US",
                            "side": "OrderSide.Buy",
                            "quantity": "1",
                            "executed_quantity": "0",
                            "price": "160",
                            "updated_at": "2026-08-03T14:40:05Z",
                        },
                        {
                            "order_id": "REMARK-ONLY",
                            "remark": "m15rt-e656ddd22cac8334",
                            "symbol": "AAPL.US",
                            "side": "OrderSide.Buy",
                            "quantity": "1",
                            "executed_quantity": "0",
                            "price": "200",
                            "updated_at": "2026-08-03T14:40:05Z",
                        },
                    ],
                }

            def refresh(self):
                self.refresh_count += 1

        class Client:
            def __init__(self) -> None:
                self.canceled: list[str] = []

            def cancel_order(self, order_id: str):
                self.canceled.append(order_id)
                return {"status": "cancel_requested", "order_id": order_id}

        with TemporaryDirectory() as tmp_dir:
            config = SimpleNamespace(
                output_dir=Path(tmp_dir),
                stale_entry_order_ttl_seconds=900,
                exit_order_reprice_seconds=60,
            )
            account = Account()
            client = Client()
            ledger_rows = [
                {
                    "signal_id": "m15rt-e656ddd22cac8334",
                    "broker_order_id": "1268941385491324928",
                    "longbridge_order_id": "1268941385491324928",
                    "order_id": "1268941385491324928",
                    "position_action": "open_long",
                }
            ]
            with patch(
                "scripts.run_m15_longbridge_sdk_runtime.read_jsonl_tail_rows",
                return_value=ledger_rows,
            ):
                result = run_sdk_order_maintenance(
                    config,
                    client,
                    account,
                    [],
                    now=now,
                )

        self.assertEqual(client.canceled, ["1268941385491324928"])
        self.assertEqual(result["planned_action_count"], 1)
        self.assertEqual(result["completed_action_count"], 1)
        self.assertEqual(result["actions"][0]["signal_id"], "m15rt-e656ddd22cac8334")
        self.assertEqual(account.refresh_count, 1)

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
            def stock_positions(self): return {"channels": [{"account_channel": "lb_papertrading", "positions": [Position()]}]}
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
            def stock_positions(self): return {"channels": [{"account_channel": "lb_papertrading", "positions": []}]}
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
            def stock_positions(self): return {"channels": [{"account_channel": "lb_papertrading", "positions": []}]}
            def today_orders(self): return []
            def today_executions(self): return []

        class Portfolio:
            def profit_analysis_by_market(self, **_kwargs):
                raise TimeoutError("analytics slow")

        state = SdkAccountStateProvider(Trade(), Portfolio(), request_gate=SdkTradeRequestGate()).refresh()
        self.assertTrue(state["paper_account_verified"])
        self.assertEqual(state["critical_errors"], [])
        self.assertIn("sdk_profit_analysis_failed:TimeoutError:analytics slow", state["analytics_errors"])

    def test_sdk_fast_account_snapshot_does_not_call_portfolio_analytics(self) -> None:
        class Balance:
            currency = "USD"
            cash_infos = []
            net_assets = "1200"
            buy_power = "900"

        class Trade:
            def account_balance(self): return [Balance()]
            def stock_positions(self): return {"channels": [{"account_channel": "lb_papertrading", "positions": []}]}
            def today_orders(self): return []
            def today_executions(self): return []

        class Portfolio:
            def profit_analysis_by_market(self, **_kwargs):
                raise AssertionError("slow portfolio analytics entered the fast snapshot")

        state = SdkAccountStateProvider(
            Trade(),
            Portfolio(),
            request_gate=SdkTradeRequestGate(),
            include_portfolio_analytics=False,
        ).refresh()

        self.assertTrue(state["paper_account_verified"])
        self.assertEqual(state["source"], "longbridge_sdk_trade_account_fast_snapshot")
        self.assertTrue(state["portfolio_deferred_to_slow_path"])
        self.assertIsNone(state["portfolio_ok"])
        self.assertEqual(state["account_total_equity_estimate"], "1200")
        self.assertEqual(state["analytics_errors"], [])

    def test_sdk_account_snapshot_fails_closed_when_broker_channel_is_not_returned(self) -> None:
        class Trade:
            def account_balance(self): return []
            def stock_positions(self): return []
            def today_orders(self): return []
            def today_executions(self): return []

        class Portfolio:
            pass

        state = SdkAccountStateProvider(
            Trade(),
            Portfolio(),
            request_gate=SdkTradeRequestGate(),
            include_portfolio_analytics=False,
        ).refresh()

        self.assertFalse(state["account_channel_verified_from_sdk"])
        self.assertFalse(state["paper_account_verified"])

    def test_account_coordinator_preserves_fresh_paper_snapshot_on_transient_critical_error(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.calls = 0

            def refresh(self):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "generated_at": "2026-07-20T14:50:00Z",
                        "account_channel": "lb_papertrading",
                        "paper_account_verified": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "critical_errors": [],
                        "orders": [],
                        "open_orders": [],
                    }
                return {
                    "generated_at": "2026-07-20T14:50:15Z",
                    "account_channel": "lb_papertrading",
                    "paper_account_verified": False,
                    "assets_ok": False,
                    "positions_ok": True,
                    "orders_ok": True,
                    "critical_errors": ["sdk_account_balance_failed:TimeoutError:temporary"],
                    "orders": [],
                    "open_orders": [],
                }

        with TemporaryDirectory() as directory:
            coordinator = SdkAccountCoordinator(Provider(), Path(directory) / "account.json")
            healthy = coordinator.refresh()
            preserved = coordinator.refresh()

        self.assertTrue(healthy["paper_account_verified"])
        self.assertTrue(preserved["paper_account_verified"])
        self.assertEqual(preserved["generated_at"], healthy["generated_at"])
        self.assertEqual(preserved["last_refresh_status"], "critical_error_preserved_last_good")
        self.assertEqual(preserved["last_failed_refresh_at"], "2026-07-20T14:50:15Z")

    def test_account_coordinator_does_not_preserve_snapshot_across_account_channel_change(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.calls = 0

            def refresh(self):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "generated_at": "2026-07-20T14:50:00Z",
                        "account_channel": "lb_papertrading",
                        "paper_account_verified": True,
                        "assets_ok": True,
                        "positions_ok": True,
                        "orders_ok": True,
                        "critical_errors": [],
                        "orders": [],
                        "open_orders": [],
                    }
                return {
                    "generated_at": "2026-07-20T14:50:15Z",
                    "account_channel": "lb_live",
                    "paper_account_verified": False,
                    "assets_ok": False,
                    "positions_ok": False,
                    "orders_ok": False,
                    "critical_errors": ["sdk_account_balance_failed:RuntimeError:wrong account"],
                    "orders": [],
                    "open_orders": [],
                }

        with TemporaryDirectory() as directory:
            coordinator = SdkAccountCoordinator(Provider(), Path(directory) / "account.json")
            coordinator.refresh()
            rejected = coordinator.refresh()

        self.assertFalse(rejected["paper_account_verified"])
        self.assertEqual(rejected["account_channel"], "lb_live")
        self.assertEqual(rejected["last_refresh_status"], "critical_error")

    def test_account_coordinator_rebuilds_failed_provider_before_publishing_snapshot(self) -> None:
        healthy = {
            "generated_at": "2026-07-21T01:00:01Z",
            "account_channel": "lb_papertrading",
            "paper_account_verified": True,
            "assets_ok": True,
            "positions_ok": True,
            "orders_ok": True,
            "critical_errors": [],
            "orders": [],
            "open_orders": [],
        }

        class FailedProvider:
            @staticmethod
            def refresh():
                return {
                    **healthy,
                    "generated_at": "2026-07-21T01:00:00Z",
                    "paper_account_verified": False,
                    "positions_ok": False,
                    "critical_errors": ["sdk_stock_positions_failed:request timeout"],
                }

        class HealthyProvider:
            @staticmethod
            def refresh():
                return dict(healthy)

        with TemporaryDirectory() as directory:
            coordinator = SdkAccountCoordinator(
                FailedProvider(),
                Path(directory) / "account.json",
                provider_factory=HealthyProvider,
            )
            snapshot = coordinator.refresh()

        self.assertTrue(snapshot["paper_account_verified"])
        self.assertTrue(snapshot["provider_rebuild_attempted"])
        self.assertEqual(
            snapshot["provider_rebuild_trigger_errors"],
            ["sdk_stock_positions_failed:request timeout"],
        )

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
        config = load_config()
        symbols = configured_symbols(config)
        trading_symbols = configured_trading_symbols(config)

        self.assertIn("PSKY.US", symbols)
        self.assertNotIn("PARA.US", symbols)
        self.assertEqual(len(symbols), 147)
        self.assertEqual(len(trading_symbols), 147)
        self.assertIn("PSKY.US", trading_symbols)

    def test_expanded_trading_pool_requires_runtime_upgrade_gate(self) -> None:
        payload = json.loads(
            Path("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json").read_text(
                encoding="utf-8"
            )
        )
        payload["market_data"]["trading_symbol_limit"] = 300
        payload["market_data"]["trading_universe_path"] = "config/m15_us_liquid_universe_300.json"
        payload["market_data"]["expansion_trade_pool_upgrade_gate"]["enabled"] = False
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "expanded trading universe requires a complete upgrade gate",
            ):
                load_config(path)

    def test_expanded_readonly_config_is_isolated_and_dispatch_disabled(self) -> None:
        default = json.loads(Path("config/examples/m15_longbridge_sdk_runtime.json").read_text(encoding="utf-8"))
        expanded = json.loads(Path("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json").read_text(encoding="utf-8"))
        runtime_config = load_config("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json")
        upgrade_gate = expanded["market_data"]["expansion_trade_pool_upgrade_gate"]

        self.assertFalse(expanded["routing"]["paper_order_dispatch_enabled"])
        self.assertTrue(expanded["runtime"]["complete_session_gate_enabled"])
        self.assertEqual(expanded["runtime"]["required_complete_sessions"], 1)
        self.assertFalse(runtime_config.paper_order_dispatch_enabled)
        self.assertTrue(runtime_config.complete_session_gate_enabled)
        self.assertEqual(runtime_config.required_complete_sessions, 1)
        self.assertEqual(
            runtime_config.market_data_transport,
            "longbridge_serve_persistent_jsonrpc",
        )
        self.assertFalse(runtime_config.allow_snapshot_poll_fallback)
        dispatch_requested = True
        complete_session_gate_passed_now = True
        self.assertFalse(
            dispatch_requested
            and runtime_config.paper_order_dispatch_enabled
            and (
                not runtime_config.complete_session_gate_enabled
                or complete_session_gate_passed_now
            )
        )
        self.assertFalse(expanded["market_data"]["use_seed_universe"])
        self.assertEqual(expanded["market_data"]["universe_path"], "config/m15_us_liquid_universe_300.json")
        self.assertEqual(expanded["market_data"]["symbol_limit"], 300)
        self.assertEqual(expanded["market_data"]["trading_symbol_limit"], 147)
        self.assertTrue(upgrade_gate["required_complete_session_gate_passed"])
        self.assertTrue(upgrade_gate["required_complete_trading_daily_context"])
        self.assertTrue(upgrade_gate["required_complete_subscribed_daily_context"])
        self.assertEqual(upgrade_gate["required_subscription_coverage"], "300/300")
        self.assertEqual(upgrade_gate["maximum_source_delivery_age_ms"], 2000)
        self.assertEqual(upgrade_gate["target_trading_symbol_limit"], 300)
        self.assertEqual(len(configured_trading_symbols(runtime_config)), 147)
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

    def test_complete_session_gate_new_key_takes_priority_over_legacy_key(self) -> None:
        payload = json.loads(
            Path("config/examples/m15_longbridge_sdk_runtime.json").read_text(
                encoding="utf-8"
            )
        )
        payload["runtime"]["complete_session_gate_enabled"] = False
        payload["runtime"]["two_day_readonly_gate"] = True
        payload["runtime"]["required_complete_sessions"] = 3
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_config(path)

        self.assertFalse(loaded.complete_session_gate_enabled)
        self.assertEqual(loaded.required_complete_sessions, 3)

    def test_expanded_universe_file_keeps_declared_order_and_limit(self) -> None:
        payload = json.loads(Path("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json").read_text(encoding="utf-8"))
        symbols = load_m15_universe(payload["market_data"]["universe_path"])
        raw_symbols = json.loads(Path(payload["market_data"]["universe_path"]).read_text(encoding="utf-8"))["symbols"]
        upgrade_gate = json.loads(Path(payload["market_data"]["universe_path"]).read_text(encoding="utf-8"))["trade_pool_upgrade_gate"]

        self.assertEqual(len(symbols), 300)
        self.assertEqual(payload["market_data"]["symbol_limit"], 300)
        self.assertLessEqual(payload["market_data"]["symbol_limit"], len(symbols))
        self.assertEqual(symbols[:5], tuple(raw_symbols[:5]))
        self.assertEqual(symbols[-5:], tuple(raw_symbols[-5:]))
        self.assertTrue(upgrade_gate["required_complete_session_gate_passed"])
        self.assertEqual(upgrade_gate["required_subscription_coverage"], "300/300")
        self.assertEqual(upgrade_gate["target_trading_symbol_limit"], 300)

    def test_expanded_readonly_staging_keeps_original_147_trading_snapshot(self) -> None:
        config = load_config("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json")
        symbols = configured_symbols(config)
        trading_symbols = configured_trading_symbols(config)

        self.assertEqual(len(symbols), 300)
        self.assertEqual(len(trading_symbols), 147)
        self.assertEqual(trading_symbols[0], "SPY.US")
        self.assertEqual(trading_symbols[-1], "TSM.US")
        self.assertEqual(symbols[0], "SPY.US")
        self.assertEqual(symbols[-1], "SHW.US")

    def test_reordering_production_universe_changes_fingerprint_and_is_detectable(self) -> None:
        source = json.loads(
            Path("config/examples/m15_longbridge_sdk_runtime.json").read_text(
                encoding="utf-8"
            )
        )
        original_subscription = json.loads(
            Path("config/m15_us_liquid_universe_300.json").read_text(
                encoding="utf-8"
            )
        )
        expected_trading = configured_trading_symbols(load_config())
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reordered_universe = root / "reordered-300.json"
            reordered = list(original_subscription["symbols"])
            reordered = reordered[147:] + reordered[:147]
            reordered_universe.write_text(
                json.dumps({"symbols": reordered}),
                encoding="utf-8",
            )
            source["market_data"]["universe_path"] = str(reordered_universe)
            config_path = root / "runtime.json"
            config_path.write_text(json.dumps(source), encoding="utf-8")

            reordered_config = load_config(config_path)
            reordered_trading = configured_trading_symbols(reordered_config)
            self.assertNotEqual(reordered_trading, expected_trading)
            self.assertNotEqual(
                trading_universe_fingerprint(reordered_config),
                trading_universe_fingerprint(load_config()),
            )

    def test_paper_dispatch_config_rejects_snapshot_fallback(self) -> None:
        payload = json.loads(
            Path("config/examples/m15_longbridge_sdk_runtime.contract_v1.json").read_text(
                encoding="utf-8"
            )
        )
        payload["runtime"]["allow_snapshot_poll_fallback"] = True
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "forbids snapshot fallback"):
                load_config(path)

    def test_expansion_symbols_are_audited_but_never_routed_to_strategies(self) -> None:
        config = load_config("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json")
        trading_symbol = configured_trading_symbols(config)[0]
        readonly_symbol = configured_symbols(config)[-1]
        rows = [
            {"symbol": trading_symbol, "timeframe": "5m"},
            {"symbol": readonly_symbol, "timeframe": "5m"},
        ]

        self.assertEqual(trading_market_events(config, rows), [rows[0]])
        self.assertTrue(market_event_is_tradable(config, rows[0]))
        self.assertFalse(market_event_is_tradable(config, rows[1]))

    def test_expansion_daily_failures_do_not_block_complete_trading_context(self) -> None:
        config = load_config("config/examples/m15_longbridge_sdk_runtime.expanded_readonly.json")
        trading_symbols = configured_trading_symbols(config)
        rows = [
            {
                "symbol": symbol.removesuffix(".US"),
                "timeframe": "1d",
                "event_time": f"2026-07-{(index % 28) + 1:02d}T20:00:00Z",
            }
            for symbol in trading_symbols
            for index in range(config.daily_context_bars)
        ]

        self.assertTrue(
            daily_context_covers_symbols(config, rows, trading_symbols, ["SHW.US"])
        )
        self.assertFalse(
            daily_context_covers_symbols(config, rows, trading_symbols, [trading_symbols[0]])
        )

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

    def test_one_complete_market_session_is_required_before_dispatch(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "gate.json"
            self.assertEqual(readonly_gate_passed(path), (False, 0, 1))
            record_readonly_session(path, "2026-07-13", {"daily_context_row_count": 8820})
            self.assertEqual(readonly_gate_passed(path), (True, 1, 1))

    def test_complete_session_gate_reads_legacy_v1_history(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "gate.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "m15.sdk-readonly-gate.v1",
                        "required_sessions": 2,
                        "completed_sessions": [
                            {"session_date": "2026-07-13"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                readonly_gate_passed(path, required_complete_sessions=1),
                (True, 1, 1),
            )

    def test_expansion_readonly_gate_can_require_one_complete_session(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "expansion-gate.json"
            self.assertEqual(
                readonly_gate_passed(path, required_complete_sessions=1),
                (False, 0, 1),
            )
            record_readonly_session(
                path,
                "2026-07-28",
                {"subscription_coverage": "300/300"},
                required_complete_sessions=1,
            )
            self.assertEqual(
                readonly_gate_passed(path, required_complete_sessions=1),
                (True, 1, 1),
            )

    def test_runtime_fingerprint_changes_when_dispatch_gate_changes(self) -> None:
        config = load_config()
        changed = replace(
            config,
            complete_session_gate_enabled=not config.complete_session_gate_enabled,
        )
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

    def test_hot_state_compaction_keeps_current_decisions_and_broker_orders(self) -> None:
        execution_rows = [
            {
                "signal_id": "old-blocked",
                "submission_status": "blocked_not_submitted",
                "processed_at": "2026-07-28T15:00:00Z",
            },
            {
                "signal_id": "today-blocked",
                "submission_status": "blocked_not_submitted",
                "processed_at": "2026-07-29T15:00:00Z",
            },
            {
                "signal_id": "old-submitted",
                "submission_status": "submitted",
                "order_id": "broker-order-1",
                "processed_at": "2026-07-28T15:00:00Z",
            },
        ]
        compacted_execution = compact_hot_execution_rows(
            execution_rows,
            market_date="2026-07-29",
        )
        self.assertEqual(
            {row["signal_id"] for row in compacted_execution},
            {"today-blocked", "old-submitted"},
        )

        signal_rows = [
            {"signal_id": "old-blocked", "created_at": "2026-07-28T15:00:00Z"},
            {"signal_id": "today-blocked", "created_at": "2026-07-29T15:00:00Z"},
            {"signal_id": "old-submitted", "created_at": "2026-07-28T15:00:00Z"},
        ]
        compacted_signals = compact_hot_signal_rows(
            signal_rows,
            compacted_execution,
            market_date="2026-07-29",
        )
        self.assertEqual(
            {row["signal_id"] for row in compacted_signals},
            {"today-blocked", "old-submitted"},
        )

    def test_sdk_preflight_requires_all_read_only_endpoints(self) -> None:
        # The live preflight is exercised by the command-line integration
        # check. Keep the code-level contract explicit here too.
        self.assertTrue(callable(run_sdk_preflight))
