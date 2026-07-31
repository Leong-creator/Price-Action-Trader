from __future__ import annotations

import unittest
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from scripts.m15_pa004_overcap_cleanup_lib import (
    advance_cleanup_state,
    build_cleanup_plan,
    execution_allowed,
)


def _batch(bucket: str = "pa004_mbf") -> dict:
    runtime = (
        "M10-PA-004-MBF-QC-1d"
        if bucket == "pa004_mbf_qc"
        else "M10-PA-004-MBF-1d"
    )
    return {
        "batch_id": f"epoch|{bucket}|{runtime}|long|AMD|open-1|trade-1",
        "test_epoch_id": "epoch",
        "capital_bucket": bucket,
        "runtime_id": runtime,
        "direction": "long",
        "symbol": "AMD",
        "open_order_id": "open-1",
        "trade_id": "trade-1",
        "remaining_quantity": "2",
        "open_price": "150",
        "metadata": {"strategy_id": runtime.removesuffix("-1d"), "signal_id": "sig-1"},
    }


def _account(available: str = "2") -> dict:
    return {
        "paper_account_verified": True,
        "account_channel": "lb_papertrading",
        "critical_errors": [],
        "positions": [
            {
                "symbol": "AMD.US",
                "quantity": available,
                "available_quantity": available,
            }
        ],
        "open_orders": [],
    }


class Pa004OvercapCleanupTest(unittest.TestCase):
    def test_builds_exact_batch_market_exit(self) -> None:
        plan = build_cleanup_plan(
            {"batches": [_batch()]},
            _account(),
            cleanup_epoch_id="cleanup-1",
            generated_at=datetime(2026, 7, 31, 15, 0, tzinfo=UTC),
        )
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["planned_batch_count"], 1)
        order = plan["orders"][0]
        self.assertEqual(order["order_type"], "market")
        self.assertEqual(order["side"], "sell")
        self.assertEqual(order["source_open_order_id"], "open-1")
        self.assertEqual(order["source_open_trade_id"], "trade-1")
        self.assertEqual(order["capital_bucket"], "pa004_mbf")

    def test_blocks_when_plan_exceeds_actual_available_quantity(self) -> None:
        plan = build_cleanup_plan(
            {"batches": [_batch()]},
            _account("1"),
            cleanup_epoch_id="cleanup-1",
        )
        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(
            plan["blockers"][0]["code"],
            "planned_quantity_exceeds_broker_available",
        )

    def test_blocks_non_paper_account_channel_before_submission(self) -> None:
        account = _account()
        account["account_channel"] = "lb_live"
        plan = build_cleanup_plan(
            {"batches": [_batch()]},
            account,
            cleanup_epoch_id="cleanup-1",
        )
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(
            any(
                row["code"] == "paper_account_channel_mismatch"
                for row in plan["blockers"]
            )
        )

        class Client:
            def submit_order(self, payload: dict) -> dict:
                raise AssertionError("non-paper cleanup must never submit")

        plan["status"] = "pending_cleanup"
        with tempfile.TemporaryDirectory() as temp_dir:
            state = advance_cleanup_state(
                plan,
                account,
                Client(),
                now=datetime(2026, 7, 31, 14, 0, tzinfo=UTC),
                execution_ledger_path=Path(temp_dir) / "ledger.jsonl",
            )
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["reason"], "paper_account_channel_mismatch")

    def test_only_affected_bucket_is_blocked_and_rebaselined(self) -> None:
        plan = build_cleanup_plan(
            {"batches": [_batch("pa004_mbf")]},
            _account(),
            cleanup_epoch_id="cleanup-1",
        )
        self.assertEqual(plan["target_buckets"], ["pa004_mbf"])
        self.assertEqual(list(plan["capital_bucket_states"]), ["pa004_mbf"])

        request_id = plan["orders"][0]["client_request_id"]
        plan["status"] = "submitted_waiting_broker_fill"
        plan["submissions"] = {
            request_id: {
                "order_id": "close-1",
                "status": "submitted_waiting_broker_fill",
            }
        }
        account = _account()
        account["orders"] = [{"order_id": "close-1", "status": "Filled"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            state = advance_cleanup_state(
                plan,
                account,
                object(),
                now=datetime(2026, 7, 31, 14, 1, tzinfo=UTC),
                execution_ledger_path=Path(temp_dir) / "ledger.jsonl",
            )
        self.assertEqual(list(state["bucket_baselines"]), ["pa004_mbf"])
        self.assertNotIn("pa004_mbf_qc", state["capital_bucket_states"])

    def test_blocks_existing_sell_order(self) -> None:
        account = _account()
        account["open_orders"] = [
            {"symbol": "AMD.US", "side": "sell", "status": "new", "order_id": "sell-1"}
        ]
        plan = build_cleanup_plan(
            {"batches": [_batch()]},
            account,
            cleanup_epoch_id="cleanup-1",
        )
        self.assertTrue(
            any(row["code"] == "existing_open_sell_order" for row in plan["blockers"])
        )

    def test_ignores_other_buckets_and_closed_batches(self) -> None:
        other = _batch()
        other["capital_bucket"] = "experimental"
        closed = _batch("pa004_mbf_qc")
        closed["remaining_quantity"] = "0"
        plan = build_cleanup_plan(
            {"batches": [other, closed]},
            _account(),
            cleanup_epoch_id="cleanup-1",
        )
        self.assertEqual(plan["planned_batch_count"], 0)
        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(plan["blockers"], [{"code": "no_target_open_batches"}])

    def test_execute_requires_rth_market_date_and_digest(self) -> None:
        plan = build_cleanup_plan(
            {"batches": [_batch()]},
            _account(),
            cleanup_epoch_id="cleanup-1",
            generated_at=datetime(2026, 7, 31, 14, 0, tzinfo=UTC),
        )
        allowed, reasons = execution_allowed(
            plan,
            now=datetime(2026, 7, 31, 14, 0, tzinfo=UTC),
            expected_market_date="2026-07-31",
            expected_plan_digest=plan["plan_digest"],
        )
        self.assertTrue(allowed)
        self.assertEqual(reasons, [])

        allowed, reasons = execution_allowed(
            plan,
            now=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
            expected_market_date="2026-07-31",
            expected_plan_digest="wrong",
        )
        self.assertFalse(allowed)
        self.assertIn("outside_regular_session", reasons)
        self.assertIn("plan_digest_mismatch", reasons)

    def test_runtime_submits_one_exact_batch_and_writes_attribution_ledger(self) -> None:
        class Client:
            def submit_order(self, payload: dict) -> dict:
                self.payload = payload
                return {"submitted": True, "status": "submitted", "order_id": "close-1"}

        plan = build_cleanup_plan(
            {"batches": [_batch()]},
            _account(),
            cleanup_epoch_id="cleanup-1",
        )
        plan["status"] = "pending_cleanup"
        plan["blocks_new_entries"] = True
        client = Client()
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = Path(temp_dir) / "ledger.jsonl"
            state = advance_cleanup_state(
                plan,
                _account(),
                client,
                now=datetime(2026, 7, 31, 14, 0, tzinfo=UTC),
                execution_ledger_path=ledger,
            )
            self.assertEqual(state["last_submitted_order_id"], "close-1")
            self.assertEqual(client.payload["source_open_order_id"], "open-1")
            self.assertEqual(client.payload["source_open_trade_id"], "trade-1")
            row = ledger.read_text(encoding="utf-8")
            self.assertIn('"submission_status": "submitted"', row)
            self.assertIn('"source_open_trade_id": "trade-1"', row)

    def test_runtime_completes_after_broker_fill_and_sets_new_baselines(self) -> None:
        plan = build_cleanup_plan(
            {"batches": [_batch()]},
            _account(),
            cleanup_epoch_id="cleanup-1",
        )
        request_id = plan["orders"][0]["client_request_id"]
        plan["status"] = "submitted_waiting_broker_fill"
        plan["submissions"] = {
            request_id: {"order_id": "close-1", "status": "submitted_waiting_broker_fill"}
        }
        account = _account()
        account["orders"] = [{"order_id": "close-1", "status": "Filled"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            state = advance_cleanup_state(
                plan,
                account,
                object(),
                now=datetime(2026, 7, 31, 14, 1, tzinfo=UTC),
                execution_ledger_path=Path(temp_dir) / "ledger.jsonl",
            )
        self.assertEqual(state["status"], "complete")
        self.assertFalse(state["blocks_new_entries"])
        self.assertTrue(
            state["bucket_baselines"]["pa004_mbf"]["exclude_prior_batches"]
        )
