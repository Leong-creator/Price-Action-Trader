from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m15_longbridge_paper_order_submitter_lib import (
    CommandResult,
    load_config,
    run_paper_submitter,
    watch_paper_submitter,
)


class M15LongbridgePaperOrderSubmitterTest(unittest.TestCase):
    def test_blocks_outside_regular_session_and_stale_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), scan_date="2026-06-01", source_event_time="2026-06-02T07:30:00Z")
            payload = run_paper_submitter(
                config,
                generated_at="2026-06-02T07:00:00Z",
                command_runner=self._runner(),
            )

        self.assertEqual(payload["submission_status"], "blocked_global_gate")
        self.assertIn("not_us_regular_session", payload["global_blockers"])
        self.assertIn("preview_not_current_market_date", payload["global_blockers"])
        self.assertEqual(payload["submitted_order_count"], 0)
        self.assertFalse(payload["real_money_actions"])

    def test_submits_only_paper_limit_order_during_regular_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), scan_date="2026-06-02", source_event_time="2026-06-02T14:00:01Z")
            payload = run_paper_submitter(
                config,
                generated_at="2026-06-02T14:00:00Z",
                command_runner=self._runner(),
            )
            self.assertEqual(payload["submission_status"], "paper_orders_submitted")
            self.assertEqual(payload["submitted_order_count"], 1)
            rows = [
                json.loads(line)
                for line in (config.output_dir / "m15_longbridge_paper_order_submitter_ledger.jsonl").read_text().splitlines()
                if line.strip()
            ]
            self.assertEqual(rows[0]["submission_status"], "submitted")
            self.assertEqual(rows[0]["longbridge_order_id"], "paper-order-1")
            self.assertFalse(rows[0]["real_money_actions"])
            self.assertFalse(rows[0]["live_execution"])

    def test_refreshes_account_state_after_successful_submission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), scan_date="2026-06-02", source_event_time="2026-06-02T14:00:01Z")
            submitted = False

            def runner(args: list[str]) -> CommandResult:
                nonlocal submitted
                if args[1:4] == ["auth", "status", "--format"]:
                    return CommandResult(
                        0,
                        json.dumps({"account": {"account_channel": "lb_papertrading", "account_type": "M"}, "token": {"status": "valid"}}),
                        "",
                    )
                if args[1:3] == ["assets", "--format"]:
                    buy_power = "102335.94" if submitted else "102524.64"
                    return CommandResult(0, json.dumps([{"buy_power": buy_power, "total_cash": "102524.64"}]), "")
                if args[1:3] == ["positions", "--format"]:
                    return CommandResult(0, json.dumps([]), "")
                if args[1:3] == ["order", "--format"]:
                    orders = [
                        {
                            "order_id": "paper-order-1",
                            "symbol": "NVDA.US",
                            "status": "New",
                            "executed_quantity": "0",
                        }
                    ] if submitted else []
                    return CommandResult(0, json.dumps(orders), "")
                if args[1:3] == ["order", "buy"]:
                    submitted = True
                    return CommandResult(0, json.dumps({"order_id": "paper-order-1"}), "")
                return CommandResult(1, "", "unexpected command")

            payload = run_paper_submitter(
                config,
                generated_at="2026-06-02T14:00:00Z",
                command_runner=runner,
            )
            account_state = json.loads((config.output_dir / "m15_longbridge_paper_account_state.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["submission_status"], "paper_orders_submitted")
        self.assertTrue(payload["post_submit_account_refresh_performed"])
        self.assertEqual(account_state["buying_power"], "102335.94")
        self.assertEqual(account_state["position_row_count"], 0)
        self.assertEqual(account_state["open_order_count"], 1)
        self.assertEqual(account_state["submitted_signal_fingerprints"], ["preview-1"])

    def test_non_paper_account_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), scan_date="2026-06-02", source_event_time="2026-06-02T14:00:01Z")
            payload = run_paper_submitter(
                config,
                generated_at="2026-06-02T14:00:00Z",
                command_runner=self._runner(account_channel="live"),
            )

        self.assertEqual(payload["submission_status"], "blocked_global_gate")
        self.assertIn("longbridge_account_channel_not_paper", payload["global_blockers"])
        self.assertEqual(payload["submitted_order_count"], 0)

    def test_does_not_migrate_local_orders_before_new_paper_account_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), scan_date="2026-06-02", source_event_time="2026-06-02T07:00:00Z")
            payload = run_paper_submitter(
                config,
                generated_at="2026-06-02T14:00:00Z",
                command_runner=self._runner(),
            )

        self.assertEqual(payload["submission_status"], "no_eligible_orders")
        self.assertEqual(payload["eligible_order_count"], 0)
        self.assertEqual(payload["submitted_order_count"], 0)
        self.assertTrue(payload["ignore_local_sim_positions_before_start"])

    def test_fast_queue_signal_submits_without_waiting_for_m13_recompute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                scan_date="2026-06-02",
                source_event_time="2026-06-02T14:00:01Z",
                source_mode="fast_signal_queue",
                m13_comparison_status="fast_queue_no_m13_wait",
                current_day_strategy_confirmation_status="confirmed",
            )
            payload = run_paper_submitter(
                config,
                generated_at="2026-06-02T14:00:00Z",
                command_runner=self._runner(),
            )

        self.assertEqual(payload["submission_status"], "paper_orders_submitted")
        self.assertEqual(payload["order_source_mode"], "fast_signal_queue")
        self.assertEqual(payload["submitted_order_count"], 1)

    def test_fast_queue_requires_current_day_strategy_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                scan_date="2026-06-02",
                source_event_time="2026-06-02T14:00:01Z",
                source_mode="fast_signal_queue",
                m13_comparison_status="fast_queue_no_m13_wait",
                current_day_strategy_confirmation_status="blocked",
            )
            payload = run_paper_submitter(
                config,
                generated_at="2026-06-02T14:00:00Z",
                command_runner=self._runner(),
            )

        self.assertEqual(payload["submission_status"], "blocked_global_gate")
        self.assertIn("strategy_list_not_confirmed_for_today", payload["global_blockers"])
        self.assertEqual(payload["submitted_order_count"], 0)

    def test_fast_queue_stale_snapshot_blocks_submitter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                scan_date="2026-06-02",
                source_event_time="2026-06-02T14:00:01Z",
                source_mode="fast_signal_queue",
                m13_comparison_status="fast_queue_no_m13_wait",
                current_day_strategy_confirmation_status="confirmed",
                snapshot_freshness_status="stale_snapshot",
                fast_queue_status="stale_snapshot_waiting_for_current_refresh",
            )
            payload = run_paper_submitter(
                config,
                generated_at="2026-06-02T14:00:00Z",
                command_runner=self._runner(),
            )

        self.assertEqual(payload["submission_status"], "blocked_global_gate")
        self.assertIn("fast_queue_stale_snapshot", payload["global_blockers"])
        self.assertEqual(payload["submitted_order_count"], 0)

    def test_trigger_limit_order_command_uses_lit_and_trigger_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                scan_date="2026-06-02",
                source_event_time="2026-06-02T14:00:01Z",
                source_mode="fast_signal_queue",
                m13_comparison_status="fast_queue_no_m13_wait",
                current_day_strategy_confirmation_status="confirmed",
                order_type="trigger_limit",
                trigger_price="101.50",
            )
            run_paper_submitter(
                config,
                generated_at="2026-06-02T14:00:00Z",
                command_runner=self._runner(),
            )
            rows = [
                json.loads(line)
                for line in (config.output_dir / "m15_longbridge_paper_order_submitter_ledger.jsonl").read_text().splitlines()
                if line.strip()
            ]

        self.assertIn("--order-type", rows[0]["command"])
        self.assertIn("LIT", rows[0]["command"])
        self.assertIn("--trigger-price", rows[0]["command"])
        self.assertIn("101.50", rows[0]["command"])

    def test_submitter_consumes_only_confluence_primary_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                scan_date="2026-06-02",
                source_event_time="2026-06-02T14:00:01Z",
                source_mode="fast_signal_queue",
                m13_comparison_status="fast_queue_no_m13_wait",
                current_day_strategy_confirmation_status="confirmed",
                quantity="2",
                notional="268.36",
                estimated_open_risk="6.70",
                signal_fingerprint="primary-now",
                confluence_role="primary",
            )
            support = {
                "preview_id": "support-now",
                "signal_fingerprint": "support-now",
                "runtime_id": "M10-PA-004-MBF-QC-m14-modify-20260522-1d",
                "strategy_id": "M10-PA-004-MBF-QC-m14-modify-20260522",
                "symbol": "NVDA",
                "trading_date": "2026-06-02",
                "broker_order_side": "buy",
                "local_event_type": "open",
                "longbridge_paper_order_preview_status": "merged_into_confluence_primary",
                "m13_comparison_status": "fast_queue_no_m13_wait",
                "blockers": ["merged_into_confluence_primary"],
                "order_type": "limit",
                "quantity": "1",
                "limit_price": "100.00",
                "notional": "100.00",
                "estimated_open_risk": "5.00",
                "source_event_time": "2026-06-02T14:00:01Z",
                "merged_primary_signal_fingerprint": "primary-now",
            }
            with config.order_preview_ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(support, ensure_ascii=False) + "\n")
            payload = run_paper_submitter(
                config,
                generated_at="2026-06-02T14:00:00Z",
                command_runner=self._runner(),
            )
            rows = [
                json.loads(line)
                for line in (config.output_dir / "m15_longbridge_paper_order_submitter_ledger.jsonl").read_text().splitlines()
                if line.strip()
            ]

        self.assertEqual(payload["submitted_order_count"], 1)
        self.assertEqual(rows[0]["signal_fingerprint"], "primary-now")
        self.assertEqual(rows[0]["quantity"], "2")

    def test_backoff_interval_when_longbridge_account_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), scan_date="2026-06-02", source_event_time="2026-06-02T14:00:01Z")
            payload = run_paper_submitter(
                config,
                generated_at="2026-06-02T14:00:00Z",
                command_runner=self._runner(assets_ok=False),
            )

        self.assertEqual(payload["next_interval_seconds"], 60)
        self.assertIn("assets_probe_failed", payload["backoff_reasons"])
        self.assertIn("assets_read_failed", payload["global_blockers"])

    def test_watch_loop_runs_fast_queue_command_not_full_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[list[str]] = []
            config = self._write_config(Path(tmp), scan_date="2026-06-02", source_event_time="2026-06-02T14:00:01Z")
            config = replace(
                config,
                run_queue_before_submit=True,
                queue_command=("python", "queue"),
                run_preview_before_submit=True,
                preview_command=("python", "preview"),
            )

            def runner(args: list[str]) -> CommandResult:
                calls.append(args)
                if args == ["python", "queue"]:
                    return CommandResult(0, "{}", "")
                return self._runner()(args)

            watch_paper_submitter(config, command_runner=runner, max_iterations=1)

        self.assertIn(["python", "queue"], calls)
        self.assertNotIn(["python", "preview"], calls)

    def _write_config(
        self,
        root: Path,
        *,
        scan_date: str,
        source_event_time: str,
        source_mode: str = "all_strategy_order_preview",
        m13_comparison_status: str = "matched",
        current_day_strategy_confirmation_status: str = "",
        order_type: str = "limit",
        trigger_price: str = "",
        quantity: str = "1",
        notional: str = "100.00",
        estimated_open_risk: str = "5.00",
        signal_fingerprint: str = "preview-1",
        confluence_role: str = "",
        snapshot_freshness_status: str = "current_market_date",
        fast_queue_status: str = "fast_signal_queue_ready",
    ):
        connection = root / "connection.json"
        summary = root / "preview.json"
        ledger = root / "preview.jsonl"
        out = root / "out"
        connection.write_text(
            json.dumps({"paper_account_verified": True, "connection_check_status": "connected_oauth_user_confirmed_paper_account"}),
            encoding="utf-8",
        )
        summary.write_text(
            json.dumps(
                {
                    "preview_status": "local_preview_created_for_all_strategy_orders",
                    "fast_queue_status": fast_queue_status,
                    "source_mode": source_mode,
                    "scan_date": scan_date,
                    "m14_trading_date": scan_date,
                    "quote_source": "longbridge_quote_readonly",
                    "current_day_strategy_confirmation_status": current_day_strategy_confirmation_status,
                    "snapshot_freshness_status": snapshot_freshness_status,
                }
            ),
            encoding="utf-8",
        )
        ledger.write_text(
            json.dumps(
                {
                    "preview_id": "preview-1",
                    "signal_fingerprint": signal_fingerprint,
                    "runtime_id": "M10-PA-004-long-1d",
                    "strategy_id": "M10-PA-004",
                    "symbol": "NVDA",
                    "trading_date": scan_date,
                    "broker_order_side": "buy",
                    "local_event_type": "open",
                    "longbridge_paper_order_preview_status": "local_order_preview_created_ready_after_user_approval",
                    "m13_comparison_status": m13_comparison_status,
                    "blockers": [
                        "broker_connection_disabled",
                        "order_submission_disabled",
                        "paper_trading_approval_false",
                    ],
                    "order_type": order_type,
                    "trigger_price": trigger_price,
                    "quantity": quantity,
                    "limit_price": "100.00",
                    "notional": notional,
                    "estimated_open_risk": estimated_open_risk,
                    "confluence_role": confluence_role,
                    "source_event_time": source_event_time,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return replace(
            load_config(),
            connection_check_path=connection,
            order_preview_summary_path=summary,
            order_preview_ledger_path=ledger,
            output_dir=out,
            cli_name="longbridge",
            paper_account_start_at="2026-06-02T07:18:05Z",
            run_queue_before_submit=False,
            queue_command=(),
            preview_command=(),
            watch_interval_seconds=1,
        )

    @staticmethod
    def _runner(*, account_channel: str = "lb_papertrading", assets_ok: bool = True):
        def run(args: list[str]) -> CommandResult:
            if args[1:4] == ["auth", "status", "--format"]:
                return CommandResult(
                    0,
                    json.dumps({"account": {"account_channel": account_channel, "account_type": "M"}, "token": {"status": "valid"}}),
                    "",
                )
            if args[1:3] == ["assets", "--format"]:
                if not assets_ok:
                    return CommandResult(1, "", "rate limited")
                return CommandResult(0, json.dumps([{"buy_power": "102524.64", "total_cash": "102524.64"}]), "")
            if args[1:3] == ["positions", "--format"]:
                return CommandResult(0, json.dumps([]), "")
            if args[1:3] == ["order", "--format"]:
                return CommandResult(0, json.dumps([]), "")
            if args[1:3] == ["order", "buy"]:
                return CommandResult(0, json.dumps({"order_id": "paper-order-1"}), "")
            return CommandResult(1, "", "unexpected command")

        return run


if __name__ == "__main__":
    unittest.main()
