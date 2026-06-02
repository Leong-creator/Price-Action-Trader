from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.m15_all_strategy_order_preview_lib import AllStrategyOrderPreviewConfig, run_all_strategy_order_preview


class M15AllStrategyOrderPreviewTest(unittest.TestCase):
    def test_builds_all_strategy_local_order_previews_without_broker_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._write_fixture(root)

            payload = run_all_strategy_order_preview(config, generated_at="2026-06-01T18:30:00Z")

            self.assertEqual(payload["preview_status"], "local_preview_created_m14_stale_submit_blocked")
            self.assertEqual(payload["summary"]["trading_runtime_count"], 2)
            self.assertEqual(payload["summary"]["auxiliary_module_count"], 1)
            self.assertEqual(payload["summary"]["order_preview_count"], 3)
            self.assertEqual(payload["summary"]["open_order_preview_count"], 2)
            self.assertEqual(payload["summary"]["close_order_preview_count"], 1)
            self.assertFalse(payload["hard_boundaries"]["broker_connection"])
            self.assertFalse(payload["hard_boundaries"]["credential_read"])
            self.assertFalse(payload["longbridge_paper_preview_policy"]["submit_orders"])

            rows = [
                json.loads(line)
                for line in (root / "out" / "m15_all_strategy_order_preview_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            by_runtime = {row["runtime_id"]: row for row in rows if row["local_event_type"] == "open"}
            self.assertEqual(
                by_runtime["M10-PA-004-long-1d"]["longbridge_paper_order_preview_status"],
                "local_order_preview_created_ready_after_user_approval",
            )
            self.assertEqual(by_runtime["M10-PA-004-long-1d"]["broker_order_side"], "buy")
            self.assertEqual(by_runtime["M10-PA-004-long-1d"]["source_quantity"], "10")
            self.assertEqual(by_runtime["M10-PA-004-long-1d"]["quantity"], "10")
            self.assertFalse(by_runtime["M10-PA-004-long-1d"]["fractional_shares_allowed"])
            self.assertIn("order_submission_disabled", by_runtime["M10-PA-004-long-1d"]["blockers"])
            self.assertFalse(by_runtime["M10-PA-004-long-1d"]["order_submitted"])
            self.assertEqual(by_runtime["M10-PA-001-1d"]["longbridge_paper_order_preview_status"], "repair_runtime_order_preview_created_submit_blocked")
            self.assertIn("repair_runtime_submit_blocked", by_runtime["M10-PA-001-1d"]["blockers"])
            self.assertIn("short_selling_disabled", by_runtime["M10-PA-001-1d"]["blockers"])
            self.assertEqual(payload["comparison_summary"]["matched_count"], 3)
            self.assertNotIn("historical_net_profit", json.dumps(payload, ensure_ascii=False))

    def test_fallback_quotes_keep_only_local_comparison_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._write_fixture(root, quote_source="fallback_quotes_only", m14_date="2026-06-01")

            payload = run_all_strategy_order_preview(config, generated_at="2026-06-01T18:30:00Z")

            self.assertEqual(payload["preview_status"], "blocked_quote_source_order_preview_only")
            self.assertIn("fallback_or_no_fetch_data", payload["quote_source_blockers"])
            self.assertEqual(payload["summary"]["order_preview_count"], 3)
            self.assertFalse(payload["hard_boundaries"]["broker_connection"])

    def test_integer_shares_and_breakout_trigger_limit_are_supported_without_fractional_or_short_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._write_fixture(root, m14_date="2026-06-01")
            extra = {
                "event_type": "open",
                "event_time": "2026-06-01T16:00:00Z",
                "signal_time": "2026-06-01T10:00:00-04:00",
                "trading_date": "2026-06-01",
                "runtime_id": "M10-PA-013-1d",
                "strategy_id": "M10-PA-013",
                "symbol": "CCC",
                "timeframe": "1d",
                "direction": "看涨",
                "entry_order_type": "trigger_limit",
                "entry_style": "breakout",
                "entry_price": "100",
                "stop_price": "99",
                "target_price": "102",
                "quantity": "0.7",
                "position_size_multiplier": "1.00",
            }
            with config.account_trade_ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(extra, ensure_ascii=False, sort_keys=True) + "\n")
            with config.account_operation_ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(extra, ensure_ascii=False, sort_keys=True) + "\n")
            gate = json.loads(config.paper_gate_path.read_text(encoding="utf-8"))
            gate["rows"].append(
                {
                    "runtime_id": "M10-PA-013-1d",
                    "strategy_id": "M10-PA-013",
                    "timeframe": "1d",
                    "runtime_role": "trading_runtime",
                    "action_state": "advance_internal_sim",
                    "paper_trial_gate": "approved_internal_sim_only",
                    "position_size_multiplier": "1",
                    "paper_candidate": True,
                }
            )
            config.paper_gate_path.write_text(json.dumps(gate, ensure_ascii=False), encoding="utf-8")

            payload = run_all_strategy_order_preview(config, generated_at="2026-06-01T18:30:00Z")

            rows = [
                json.loads(line)
                for line in (root / "out" / "m15_all_strategy_order_preview_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            row = next(item for item in rows if item["runtime_id"] == "M10-PA-013-1d")
            self.assertEqual(row["order_type"], "trigger_limit")
            self.assertEqual(row["source_quantity"], "0.7")
            self.assertEqual(row["quantity"], "0")
            self.assertIn("integer_quantity_below_one", row["blockers"])
            self.assertEqual(row["longbridge_paper_order_preview_status"], "blocked_missing_order_fields")
            self.assertFalse(payload["longbridge_paper_preview_policy"]["allow_fractional_shares"])
            self.assertFalse(payload["longbridge_paper_preview_policy"]["allow_short_selling"])
            self.assertIn("trigger_limit", payload["longbridge_paper_preview_policy"]["allowed_order_types"])

    def test_rejects_config_that_enables_order_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            files = self._write_input_files(root)
            with self.assertRaisesRegex(ValueError, "submit orders"):
                AllStrategyOrderPreviewConfig(
                    stage="M15.all_strategy_order_preview",
                    title="bad",
                    dashboard_path=files["dashboard"],
                    runtime_state_path=files["runtime_state"],
                    account_trade_ledger_path=files["m12_ledger"],
                    account_operation_ledger_path=files["m13_ledger"],
                    paper_gate_path=files["gate"],
                    output_dir=root / "out",
                    token_mode="paper",
                    live_token_allowed=False,
                    broker_connection_enabled=False,
                    submit_orders=True,
                    paper_trading_approval=False,
                    default_order_type="limit",
                    allowed_order_types=("limit", "trigger_limit"),
                    breakout_order_type="trigger_limit",
                    regular_hours_only=True,
                    max_orders_per_day=5,
                    max_risk_per_order=Decimal("12"),
                    quantity_policy="integer_floor_no_fractional",
                    paper_account_equity=Decimal("6000"),
                    max_total_exposure=Decimal("3600"),
                    min_cash_reserve=Decimal("2400"),
                    max_symbol_exposure=Decimal("600"),
                    allow_fractional_shares=False,
                    allow_short_selling=False,
                    allow_options=False,
                    risk_tiers={
                        "primary": {"max_strategy_exposure": Decimal("900"), "max_risk_per_order": Decimal("12")},
                        "standard": {"max_strategy_exposure": Decimal("600"), "max_risk_per_order": Decimal("8")},
                        "risk_limited": {"max_strategy_exposure": Decimal("450"), "max_risk_per_order": Decimal("6")},
                        "repair": {"max_strategy_exposure": Decimal("0"), "max_risk_per_order": Decimal("0")},
                    },
                    primary_runtime_ids=("M10-PA-004-long-1d",),
                    hard_boundaries={
                        "paper_simulated_only": True,
                        "local_record_only": True,
                        "broker_connection": False,
                        "real_order": False,
                        "live_execution": False,
                        "paper_trading_approval": False,
                        "credential_read": False,
                        "manual_m12_37_once": False,
                    },
                )

    def _write_fixture(
        self,
        root: Path,
        *,
        quote_source: str = "longbridge_quote_readonly",
        m14_date: str = "2026-05-22",
    ) -> AllStrategyOrderPreviewConfig:
        files = self._write_input_files(root, quote_source=quote_source, m14_date=m14_date)
        return AllStrategyOrderPreviewConfig(
            stage="M15.all_strategy_order_preview",
            title="全策略长桥模拟账户订单预演",
            dashboard_path=files["dashboard"],
            runtime_state_path=files["runtime_state"],
            account_trade_ledger_path=files["m12_ledger"],
            account_operation_ledger_path=files["m13_ledger"],
            paper_gate_path=files["gate"],
            output_dir=root / "out",
            token_mode="paper",
            live_token_allowed=False,
            broker_connection_enabled=False,
            submit_orders=False,
            paper_trading_approval=False,
            default_order_type="limit",
            allowed_order_types=("limit", "trigger_limit"),
            breakout_order_type="trigger_limit",
            regular_hours_only=True,
            max_orders_per_day=5,
            max_risk_per_order=Decimal("12"),
            quantity_policy="integer_floor_no_fractional",
            paper_account_equity=Decimal("6000"),
            max_total_exposure=Decimal("3600"),
            min_cash_reserve=Decimal("2400"),
            max_symbol_exposure=Decimal("600"),
            allow_fractional_shares=False,
            allow_short_selling=False,
            allow_options=False,
            risk_tiers={
                "primary": {"max_strategy_exposure": Decimal("900"), "max_risk_per_order": Decimal("12")},
                "standard": {"max_strategy_exposure": Decimal("600"), "max_risk_per_order": Decimal("8")},
                "risk_limited": {"max_strategy_exposure": Decimal("450"), "max_risk_per_order": Decimal("6")},
                "repair": {"max_strategy_exposure": Decimal("0"), "max_risk_per_order": Decimal("0")},
            },
            primary_runtime_ids=("M10-PA-004-long-1d",),
            hard_boundaries={
                "paper_simulated_only": True,
                "local_record_only": True,
                "broker_connection": False,
                "real_order": False,
                "live_execution": False,
                "paper_trading_approval": False,
                "credential_read": False,
                "manual_m12_37_once": False,
            },
        )

    def _write_input_files(
        self,
        root: Path,
        *,
        quote_source: str = "longbridge_quote_readonly",
        m14_date: str = "2026-05-22",
    ) -> dict[str, Path]:
        dashboard = root / "dashboard.json"
        runtime_state = root / "runtime_state.json"
        m12_ledger = root / "m12_trade_ledger.jsonl"
        m13_ledger = root / "m13_operation_ledger.jsonl"
        gate = root / "m14_paper_trial_gate.json"
        dashboard.write_text(
            json.dumps(
                {
                    "summary": {
                        "scan_date": "2026-06-01",
                        "quote_source": quote_source,
                        "data_freshness_warning": "fallback snapshot" if "fallback" in quote_source else "",
                    },
                    "paper_simulated_only": True,
                    "paper_trading_approval": False,
                    "live_execution": False,
                    "real_money_actions": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        runtime_state.write_text(
            json.dumps(
                {
                    "accounts": {
                        "M10-PA-004-long-1d": {
                            "strategy_id": "M10-PA-004",
                            "display_name": "PA004 日线账户",
                            "timeframe": "1d",
                            "lane": "mainline",
                        },
                        "M10-PA-001-1d": {
                            "strategy_id": "M10-PA-001",
                            "display_name": "PA001 日线账户",
                            "timeframe": "1d",
                            "lane": "mainline",
                        },
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        m12_rows = [
            {
                "event_type": "open",
                "event_time": "2026-06-01T14:00:00Z",
                "signal_time": "2026-06-01T09:30:00-04:00",
                "trading_date": "2026-06-01",
                "runtime_id": "M10-PA-004-long-1d",
                "strategy_id": "M10-PA-004",
                "symbol": "AAA",
                "timeframe": "1d",
                "direction": "看涨",
                "entry_price": "10",
                "stop_price": "9",
                "target_price": "12",
                "quantity": "10",
                "position_size_multiplier": "1.00",
            },
            {
                "event_type": "close",
                "event_time": "2026-06-01T15:00:00Z",
                "signal_time": "2026-06-01T09:30:00-04:00",
                "trading_date": "2026-06-01",
                "runtime_id": "M10-PA-004-long-1d",
                "strategy_id": "M10-PA-004",
                "symbol": "AAA",
                "timeframe": "1d",
                "direction": "看涨",
                "entry_price": "10",
                "exit_price": "12",
                "stop_price": "9",
                "target_price": "12",
                "quantity": "10",
            },
            {
                "event_type": "open",
                "event_time": "2026-06-01T14:10:00Z",
                "signal_time": "2026-06-01T09:35:00-04:00",
                "trading_date": "2026-06-01",
                "runtime_id": "M10-PA-001-1d",
                "strategy_id": "M10-PA-001",
                "symbol": "BBB",
                "timeframe": "1d",
                "direction": "看跌",
                "entry_price": "20",
                "stop_price": "21",
                "target_price": "18",
                "quantity": "5",
                "position_size_multiplier": "0.10",
            },
        ]
        m12_ledger.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in m12_rows), encoding="utf-8")
        m13_ledger.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in m12_rows), encoding="utf-8")
        gate.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "runtime_id": "M10-PA-004-long-1d",
                            "strategy_id": "M10-PA-004",
                            "timeframe": "1d",
                            "runtime_role": "trading_runtime",
                            "action_state": "advance_internal_sim",
                            "paper_trial_gate": "approved_internal_sim_only",
                            "position_size_multiplier": "1",
                        },
                        {
                            "runtime_id": "M10-PA-001-1d",
                            "strategy_id": "M10-PA-001",
                            "timeframe": "1d",
                            "runtime_role": "trading_runtime",
                            "action_state": "repair_now",
                            "paper_trial_gate": "repair_now",
                            "position_size_multiplier": "0.1",
                        },
                        {
                            "runtime_id": "M10-PA-003",
                            "strategy_id": "M10-PA-003",
                            "runtime_role": "auxiliary_module",
                            "action_state": "auxiliary_module",
                            "display_action": "辅助模块：启用为质量评分和排序模块，不作为独立交易策略",
                            "auxiliary_module_purpose": "质量评分和排序模块",
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        gate.with_name("m14_strategy_challenge_summary.json").write_text(
            json.dumps({"trading_date": m14_date}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "dashboard": dashboard,
            "runtime_state": runtime_state,
            "m12_ledger": m12_ledger,
            "m13_ledger": m13_ledger,
            "gate": gate,
        }


if __name__ == "__main__":
    unittest.main()
