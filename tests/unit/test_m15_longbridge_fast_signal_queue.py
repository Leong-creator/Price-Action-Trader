from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m15_longbridge_fast_signal_queue_lib import load_config, run_fast_signal_queue


class M15LongbridgeFastSignalQueueTest(unittest.TestCase):
    def test_builds_current_day_open_queue_without_waiting_for_m13(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), action_state="paper_candidate")
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        self.assertEqual(payload["fast_queue_status"], "fast_signal_queue_ready")
        self.assertEqual(payload["current_day_strategy_confirmation_status"], "confirmed")
        self.assertTrue(payload["fast_path_no_m13_wait"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["m13_comparison_status"], "fast_queue_no_m13_wait")
        self.assertEqual(rows[0]["longbridge_paper_order_preview_status"], "local_order_preview_created_ready_after_user_approval")
        self.assertFalse(rows[0]["paper_trading_approval"])
        self.assertEqual(rows[0]["signal_fingerprint"], rows[0]["preview_id"])

    def test_stale_strategy_confirmation_blocks_submission_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), action_state="paper_candidate", m14_date="2026-06-01")
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")

        self.assertEqual(payload["fast_queue_status"], "fast_queue_created_m14_stale_submit_blocked")
        self.assertEqual(payload["current_day_strategy_confirmation_status"], "blocked")
        self.assertIn("m14_not_recomputed_for_current_scan_date", payload["current_day_blockers"])

    def test_repair_runtime_stays_local_queue_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), action_state="repair_now")
            run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        self.assertEqual(rows[0]["longbridge_paper_order_preview_status"], "repair_runtime_order_preview_created_submit_blocked")
        self.assertIn("repair_runtime_submit_blocked", rows[0]["blockers"])

    def test_ignores_close_and_old_date_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), action_state="paper_candidate", extra_rows=[
                self._source_row(event_type="close", trading_date="2026-06-02"),
                self._source_row(event_type="open", trading_date="2026-06-01"),
            ])
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        self.assertEqual(payload["summary"]["new_open_signal_count"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["local_event_type"], "open")
        self.assertEqual(rows[0]["trading_date"], "2026-06-02")

    def test_breakout_signal_uses_trigger_limit_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="paper_candidate",
                source_overrides={"entry_trigger": "breakout above range", "trigger_price": "101.50"},
            )
            run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        self.assertEqual(rows[0]["order_type"], "trigger_limit")
        self.assertEqual(rows[0]["trigger_price"], "101.5")

    def test_breakout_display_name_uses_trigger_limit_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="paper_candidate",
                source_overrides={
                    "display_name": "Breakout runtime",
                    "strategy_id": "M10-PA-002",
                    "runtime_id": "M10-PA-002-1d",
                    "trigger_price": "316.12",
                },
            )
            run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        self.assertEqual(rows[0]["order_type"], "trigger_limit")
        self.assertEqual(rows[0]["trigger_price"], "316.12")

    def test_breakout_strategy_id_uses_trigger_limit_order_without_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="paper_candidate",
                source_overrides={
                    "strategy_id": "M10-PA-002",
                    "runtime_id": "M10-PA-002-1d",
                    "trigger_price": "316.12",
                },
            )
            run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        self.assertEqual(rows[0]["order_type"], "trigger_limit")
        self.assertEqual(rows[0]["trigger_price"], "316.12")

    def test_open_signal_with_later_close_is_not_submit_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="paper_candidate",
                source_overrides={
                    "event_time": "2026-06-02T14:00:00Z",
                    "signal_time": "2026-06-02T14:00:00Z",
                    "symbol": "AAPL",
                },
                extra_rows=[
                    self._source_row(
                        event_type="close",
                        event_time="2026-06-02T14:05:00Z",
                        signal_time="2026-06-02T14:00:00Z",
                        symbol="AAPL",
                    )
                ],
            )
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:06:00Z")
            rows = self._rows(config)

        self.assertEqual(payload["summary"]["ready_after_user_approval_count"], 0)
        self.assertEqual(payload["summary"]["signal_superseded_by_close_count"], 1)
        self.assertEqual(rows[0]["longbridge_paper_order_preview_status"], "signal_superseded_by_close_submit_blocked")
        self.assertIn("signal_superseded_by_close", rows[0]["blockers"])
        self.assertEqual(rows[0]["latest_close_event_time_after_open"], "2026-06-02T14:05:00Z")

    def test_old_open_signal_expires_before_submit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="paper_candidate",
                source_overrides={
                    "event_time": "2026-06-02T14:00:00Z",
                    "signal_time": "2026-06-02T14:00:00Z",
                    "timeframe": "5m",
                },
            )
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:16:00Z")
            rows = self._rows(config)

        self.assertEqual(payload["summary"]["ready_after_user_approval_count"], 0)
        self.assertEqual(payload["summary"]["signal_age_expired_count"], 1)
        self.assertEqual(rows[0]["longbridge_paper_order_preview_status"], "signal_age_expired_submit_blocked")
        self.assertEqual(rows[0]["signal_age_seconds"], "960")
        self.assertIn("signal_age_expired", rows[0]["blockers"])

    def test_daily_signal_does_not_expire_on_5m_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="paper_candidate",
                source_overrides={
                    "event_time": "2026-06-02T14:00:00Z",
                    "signal_time": "2026-06-02T14:00:00Z",
                    "timeframe": "1d",
                },
            )
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:30:00Z")
            rows = self._rows(config)

        self.assertEqual(payload["summary"]["ready_after_user_approval_count"], 1)
        self.assertEqual(payload["summary"]["signal_age_expired_count"], 0)
        self.assertEqual(rows[0]["max_signal_age_seconds"], "23400")
        self.assertNotIn("signal_age_expired", rows[0]["blockers"])

    def test_blocks_order_when_target_profit_does_not_cover_fees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="paper_candidate",
                source_overrides={
                    "symbol": "VTI",
                    "entry_price": "373.99",
                    "stop_price": "368.99",
                    "target_price": "374.18",
                    "quantity": "1",
                },
            )
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        self.assertEqual(payload["summary"]["ready_after_user_approval_count"], 0)
        self.assertEqual(payload["summary"]["fee_profit_blocked_count"], 1)
        self.assertEqual(rows[0]["longbridge_paper_order_preview_status"], "local_order_preview_created_fee_profit_blocked")
        self.assertIn("net_profit_after_fees_not_positive", rows[0]["blockers"])

    def test_high_price_symbol_can_rank_first_when_net_profit_is_better(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="paper_candidate",
                source_overrides={
                    "symbol": "NOW",
                    "entry_price": "700.00",
                    "stop_price": "695.00",
                    "target_price": "750.00",
                    "quantity": "2",
                },
                extra_rows=[
                    self._source_row(
                        runtime_id="M10-PA-013-1d",
                        strategy_id="M10-PA-013",
                        symbol="INTC",
                        entry_price="100.00",
                        stop_price="95.00",
                        target_price="112.00",
                        quantity="10",
                    )
                ],
                extra_gate_rows=[
                    {
                        "runtime_id": "M10-PA-013-1d",
                        "strategy_id": "M10-PA-013",
                        "action_state": "paper_candidate",
                        "paper_trial_gate": "paper_candidate",
                    }
                ],
            )
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        ready = [row for row in rows if row["longbridge_paper_order_preview_status"] == "local_order_preview_created_ready_after_user_approval"]
        self.assertEqual(payload["summary"]["ready_after_user_approval_count"], 2)
        self.assertEqual(ready[0]["symbol"], "NOW")
        self.assertEqual(ready[0]["submission_priority_rank"], "1")
        self.assertGreater(float(ready[0]["net_profit_after_fees_at_target"]), float(ready[1]["net_profit_after_fees_at_target"]))

    def test_same_symbol_same_direction_merges_and_sizes_same_family_confluence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="risk_limited_advance",
                source_overrides={
                    "runtime_id": "M10-PA-004-MBF-1d",
                    "strategy_id": "M10-PA-004-MBF",
                    "lane": "primary",
                    "symbol": "NOW",
                    "entry_price": "134.18",
                    "stop_price": "130.83",
                    "target_price": "140.89",
                    "quantity": "16.3761",
                },
                extra_rows=[
                    self._source_row(
                        runtime_id="M10-PA-004-MBF-QC-m14-modify-20260522-1d",
                        strategy_id="M10-PA-004-MBF-QC-m14-modify-20260522",
                        lane="rescue",
                        symbol="NOW",
                        entry_price="134.18",
                        stop_price="130.83",
                        target_price="139.21",
                        quantity="29.9343",
                    )
                ],
                extra_gate_rows=[
                    {
                        "runtime_id": "M10-PA-004-MBF-QC-m14-modify-20260522-1d",
                        "strategy_id": "M10-PA-004-MBF-QC-m14-modify-20260522",
                        "action_state": "risk_limited_advance",
                        "paper_trial_gate": "paper_candidate",
                    }
                ],
            )
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        primary = [row for row in rows if row.get("confluence_role") == "primary"][0]
        support = [row for row in rows if row.get("confluence_role") == "support"][0]
        self.assertEqual(payload["summary"]["ready_after_user_approval_count"], 1)
        self.assertEqual(primary["runtime_id"], "M10-PA-004-MBF-1d")
        self.assertEqual(primary["confluence_multiplier"], "1.25")
        self.assertEqual(primary["quantity"], "3")
        self.assertEqual(primary["estimated_open_risk"], "10.05")
        self.assertEqual(support["longbridge_paper_order_preview_status"], "merged_into_confluence_primary")
        self.assertEqual(support["merged_primary_signal_fingerprint"], primary["signal_fingerprint"])

    def test_independent_family_confluence_caps_multiplier_at_175(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="risk_limited_advance",
                source_overrides={
                    "runtime_id": "M10-PA-004-MBF-1d",
                    "strategy_id": "M10-PA-004-MBF",
                    "symbol": "NOW",
                    "entry_price": "134.18",
                    "stop_price": "130.83",
                    "target_price": "140.89",
                    "quantity": "16.3761",
                },
                extra_rows=[
                    self._source_row(
                        runtime_id="M10-PA-004-MBF-QC-m14-modify-20260522-1d",
                        strategy_id="M10-PA-004-MBF-QC-m14-modify-20260522",
                        symbol="NOW",
                        entry_price="134.18",
                        stop_price="130.83",
                        target_price="139.21",
                        quantity="29.9343",
                    ),
                    self._source_row(
                        runtime_id="M10-PA-013-5m",
                        strategy_id="M10-PA-013",
                        timeframe="5m",
                        symbol="NOW",
                        entry_price="134.18",
                        stop_price="130.83",
                        target_price="140.89",
                        quantity="16.3761",
                    ),
                ],
                extra_gate_rows=[
                    {
                        "runtime_id": "M10-PA-004-MBF-QC-m14-modify-20260522-1d",
                        "strategy_id": "M10-PA-004-MBF-QC-m14-modify-20260522",
                        "action_state": "risk_limited_advance",
                        "paper_trial_gate": "paper_candidate",
                    },
                    {
                        "runtime_id": "M10-PA-013-5m",
                        "strategy_id": "M10-PA-013",
                        "action_state": "risk_limited_advance",
                        "paper_trial_gate": "paper_candidate",
                    },
                ],
            )
            run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        primary = [row for row in rows if row.get("confluence_role") == "primary"][0]
        self.assertEqual(primary["confluence_multiplier"], "1.75")
        self.assertEqual(primary["quantity"], "5")
        self.assertLessEqual(float(primary["notional"]), 1500.0)
        self.assertLessEqual(float(primary["estimated_open_risk"]), 20.0)

    def test_stale_snapshot_blocks_all_ready_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(Path(tmp), action_state="paper_candidate", scan_date="2026-06-01", m14_date="2026-06-01")
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        self.assertEqual(payload["fast_queue_status"], "stale_snapshot_waiting_for_current_refresh")
        self.assertEqual(payload["summary"]["ready_after_user_approval_count"], 0)
        self.assertEqual(rows[0]["longbridge_paper_order_preview_status"], "stale_snapshot_submit_blocked")
        self.assertEqual(rows[0]["submission_priority_rank"], "")
        self.assertIn("stale_snapshot_submit_blocked", rows[0]["blockers"])

    def test_premarket_against_signal_blocks_bullish_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="paper_candidate",
                source_overrides={"symbol": "QCOM"},
                extended_session_monitor={
                    "premarket_rows": [
                        {
                            "symbol": "QCOM",
                            "session": "盘前",
                            "move_percent": "-6.86",
                            "extended_price": "233.80",
                            "quote_timestamp": "2026-06-02T13:30:00Z",
                        }
                    ]
                },
            )
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        self.assertEqual(payload["summary"]["ready_after_user_approval_count"], 0)
        self.assertEqual(rows[0]["longbridge_paper_order_preview_status"], "premarket_against_signal_blocked")
        self.assertIn("premarket_against_signal_blocked", rows[0]["blockers"])

    def test_premarket_overheat_waits_for_first_5m_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(
                Path(tmp),
                action_state="paper_candidate",
                source_overrides={"symbol": "NOW"},
                extended_session_monitor={
                    "premarket_rows": [
                        {
                            "symbol": "NOW",
                            "session": "盘前",
                            "move_percent": "9.00",
                            "extended_price": "135.56",
                            "quote_timestamp": "2026-06-02T13:30:00Z",
                        }
                    ]
                },
            )
            payload = run_fast_signal_queue(config, generated_at="2026-06-02T14:00:00Z")
            rows = self._rows(config)

        self.assertEqual(payload["summary"]["ready_after_user_approval_count"], 0)
        self.assertEqual(rows[0]["longbridge_paper_order_preview_status"], "wait_first_5m_confirmation")
        self.assertIn("wait_first_5m_confirmation", rows[0]["blockers"])

    def _write_config(
        self,
        root: Path,
        *,
        action_state: str,
        scan_date: str = "2026-06-02",
        m14_date: str = "2026-06-02",
        extra_rows: list[dict[str, str]] | None = None,
        extra_gate_rows: list[dict[str, str]] | None = None,
        source_overrides: dict[str, str] | None = None,
        extended_session_monitor: dict[str, object] | None = None,
    ):
        dashboard = root / "dashboard.json"
        ledger = root / "ledger.jsonl"
        paper_gate = root / "m14_paper_trial_gate.json"
        summary = root / "m14_strategy_challenge_summary.json"
        decision = root / "m14_strategy_decision_ledger.jsonl"
        extended = root / "extended.json"
        out = root / "out"
        dashboard.write_text(
            json.dumps({"summary": {"scan_date": scan_date, "quote_source": "longbridge_quote_readonly"}}),
            encoding="utf-8",
        )
        default_gate_row = {
            "runtime_id": str((source_overrides or {}).get("runtime_id", "M10-PA-004-long-1d")),
            "strategy_id": str((source_overrides or {}).get("strategy_id", "M10-PA-004")),
            "action_state": action_state,
            "paper_trial_gate": "paper_candidate",
            "position_size_multiplier": "1.0",
        }
        paper_gate.write_text(
            json.dumps(
                {
                    "rows": [default_gate_row, *(extra_gate_rows or [])]
                }
            ),
            encoding="utf-8",
        )
        summary.write_text(json.dumps({"trading_date": m14_date}), encoding="utf-8")
        decision.write_text(
            json.dumps(
                {
                    "runtime_id": default_gate_row["runtime_id"],
                    "strategy_id": default_gate_row["strategy_id"],
                    "trading_date": m14_date,
                    "generated_at": "2026-06-02T13:59:00Z",
                    "net_pnl_r": "1.0",
                    "realized_pnl": "25.00",
                    "max_drawdown_percent": "5",
                    "risk_block_ratio": "0",
                    "total_signal_count": "5",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        extended.write_text(json.dumps(extended_session_monitor or {"premarket_rows": []}), encoding="utf-8")
        rows = [self._source_row(trading_date=scan_date, **(source_overrides or {}))]
        rows.extend(extra_rows or [])
        ledger.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        return replace(
            load_config(),
            dashboard_path=dashboard,
            account_trade_ledger_path=ledger,
            paper_gate_path=paper_gate,
            strategy_decision_ledger_path=decision,
            extended_session_monitor_path=extended,
            output_dir=out,
        )

    @staticmethod
    def _source_row(**overrides: str) -> dict[str, str]:
        row = {
            "trading_date": "2026-06-02",
            "event_type": "open",
            "event_time": "2026-06-02T14:00:01Z",
            "signal_time": "2026-06-02T14:00:01Z",
            "runtime_id": "M10-PA-004-long-1d",
            "strategy_id": "M10-PA-004",
            "timeframe": "1d",
            "lane": "primary",
            "symbol": "NVDA",
            "direction": "long",
            "entry_price": "100.00",
            "stop_price": "95.00",
            "target_price": "112.00",
            "quantity": "10",
        }
        row.update(overrides)
        return row

    @staticmethod
    def _rows(config) -> list[dict[str, str]]:
        return [
            json.loads(line)
            for line in (config.output_dir / "m15_longbridge_fast_signal_queue_ledger.jsonl").read_text().splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    unittest.main()
