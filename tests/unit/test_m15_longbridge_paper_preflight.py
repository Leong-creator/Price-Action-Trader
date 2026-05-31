from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from scripts.m15_longbridge_paper_preflight_lib import (
    load_config,
    run_m15_longbridge_paper_preflight,
)


class M15LongbridgePaperPreflightTest(unittest.TestCase):
    def test_preflight_uses_only_runtime_candidates_and_never_connects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_path = root / "m14_paper_trial_gate.json"
            output_dir = root / "out"
            gate_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "runtime_id": "M10-PA-004-long-1d",
                                "strategy_id": "M10-PA-004",
                                "timeframe": "1d",
                                "action_state": "advance_internal_sim",
                                "paper_trial_gate": "advance_internal_sim",
                                "position_size_multiplier": "1.0",
                                "paper_candidate": True,
                                "gate_reason": "Runtime advances in internal simulation.",
                            },
                            {
                                "runtime_id": "M10-PA-005-5m",
                                "strategy_id": "M10-PA-005",
                                "timeframe": "5m",
                                "action_state": "risk_limited_advance",
                                "paper_trial_gate": "risk_limited_internal_sim",
                                "position_size_multiplier": "0.25",
                                "paper_candidate": True,
                                "gate_reason": "Runtime advances with position size multiplier 0.25.",
                            },
                            {
                                "runtime_id": "M10-PA-001-1d",
                                "strategy_id": "M10-PA-001",
                                "timeframe": "1d",
                                "action_state": "pause_runtime",
                                "paper_trial_gate": "pause_runtime",
                                "position_size_multiplier": "0",
                                "paper_candidate": False,
                                "gate_reason": "fallback/no-fetch day",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = replace(load_config(), paper_gate_path=gate_path, output_dir=output_dir)
            payload = run_m15_longbridge_paper_preflight(
                config,
                generated_at="2026-05-27T00:00:00Z",
                cli_probe=lambda _: {"available": "true", "path": "/usr/bin/longbridge", "version": "longbridge 0.17.1", "error": ""},
            )

        self.assertEqual(payload["paper_preflight_status"], "ready_for_user_paper_credential_approval")
        self.assertEqual(payload["candidate_count"], 2)
        self.assertEqual(payload["first_paper_order_candidate_count"], 1)
        by_runtime = {row["runtime_id"]: row for row in payload["candidates"]}
        self.assertEqual(by_runtime["M10-PA-005-5m"]["position_size_multiplier"], "0.25")
        self.assertFalse(by_runtime["M10-PA-005-5m"]["eligible_for_first_paper_order"])
        self.assertTrue(by_runtime["M10-PA-004-long-1d"]["eligible_for_first_paper_order"])
        self.assertFalse(payload["broker_connection_attempted"])
        self.assertFalse(payload["order_submitted"])
        self.assertFalse(payload["live_token_allowed"])
        self.assertFalse(payload["credential_injection_allowed_now"])
        self.assertEqual(payload["first_paper_order_strategy_whitelist"], ["M10-PA-004"])

    def test_missing_cli_blocks_even_when_candidates_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_path = root / "m14_paper_trial_gate.json"
            gate_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "runtime_id": "M10-PA-004-long-1d",
                                "strategy_id": "M10-PA-004",
                                "action_state": "advance_internal_sim",
                                "paper_trial_gate": "advance_internal_sim",
                                "position_size_multiplier": "1.0",
                                "paper_candidate": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = replace(load_config(), paper_gate_path=gate_path, output_dir=root / "out")
            payload = run_m15_longbridge_paper_preflight(
                config,
                generated_at="2026-05-27T00:00:00Z",
                cli_probe=lambda _: {"available": "false", "path": "", "version": "", "error": "cli_not_found"},
            )

        self.assertEqual(payload["paper_preflight_status"], "blocked_cli_missing")
        self.assertEqual(payload["candidate_count"], 1)
        self.assertFalse(payload["broker_connection_attempted"])

    def test_fallback_summary_blocks_paper_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_path = root / "m14_paper_trial_gate.json"
            gate_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "runtime_id": "M10-PA-004-long-1d",
                                "strategy_id": "M10-PA-004",
                                "action_state": "advance_internal_sim",
                                "paper_trial_gate": "advance_internal_sim",
                                "position_size_multiplier": "1.0",
                                "paper_candidate": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            gate_path.with_name("m14_strategy_challenge_summary.json").write_text(
                json.dumps({"m12_quote_source": "fallback_quotes_only"}, ensure_ascii=False),
                encoding="utf-8",
            )
            config = replace(load_config(), paper_gate_path=gate_path, output_dir=root / "out")
            payload = run_m15_longbridge_paper_preflight(
                config,
                generated_at="2026-05-27T00:00:00Z",
                cli_probe=lambda _: {"available": "true", "path": "/usr/bin/longbridge", "version": "longbridge 0.17.1", "error": ""},
            )

        self.assertEqual(payload["paper_preflight_status"], "blocked_fallback_or_no_fetch_data")
        self.assertEqual(payload["candidate_count"], 0)
        self.assertTrue(payload["fallback_or_no_fetch_data"])

    def test_policy_blocks_live_token_or_non_limit_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_path = root / "m14_paper_trial_gate.json"
            gate_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "runtime_id": "M10-PA-004-long-1d",
                                "strategy_id": "M10-PA-004",
                                "action_state": "advance_internal_sim",
                                "paper_trial_gate": "advance_internal_sim",
                                "position_size_multiplier": "1.0",
                                "paper_candidate": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = replace(
                load_config(),
                paper_gate_path=gate_path,
                output_dir=root / "out",
                token_mode="live",
                live_token_allowed=True,
                default_order_type="market",
            )
            payload = run_m15_longbridge_paper_preflight(
                config,
                generated_at="2026-05-27T00:00:00Z",
                cli_probe=lambda _: {"available": "true", "path": "/usr/bin/longbridge", "version": "longbridge 0.17.1", "error": ""},
            )

        self.assertEqual(payload["paper_preflight_status"], "blocked_preflight_policy")
        self.assertIn("paper_token_only_required", payload["policy_blockers"])
        self.assertIn("live_token_forbidden", payload["policy_blockers"])
        self.assertIn("limit_orders_only_required", payload["policy_blockers"])
        self.assertFalse(payload["broker_connection_attempted"])
        self.assertFalse(payload["order_submitted"])

    def test_non_whitelisted_strategy_and_symbol_are_not_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate_path = root / "m14_paper_trial_gate.json"
            gate_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "runtime_id": "M10-PA-013-1d",
                                "strategy_id": "M10-PA-013",
                                "timeframe": "1d",
                                "symbol": "TSLA",
                                "action_state": "risk_limited_advance",
                                "paper_trial_gate": "risk_limited_internal_sim",
                                "position_size_multiplier": "0.5",
                                "paper_candidate": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = replace(
                load_config(),
                paper_gate_path=gate_path,
                output_dir=root / "out",
                symbol_whitelist=("AAPL",),
            )
            payload = run_m15_longbridge_paper_preflight(
                config,
                generated_at="2026-05-27T00:00:00Z",
                cli_probe=lambda _: {"available": "true", "path": "/usr/bin/longbridge", "version": "longbridge 0.17.1", "error": ""},
            )

        self.assertEqual(payload["paper_preflight_status"], "blocked_no_runtime_candidates")
        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(payload["blocked_candidate_count"], 1)
        self.assertIn("strategy_not_in_first_batch_whitelist", payload["blocked_candidates"][0]["blockers"])
        self.assertIn("symbol_not_in_whitelist", payload["blocked_candidates"][0]["blockers"])


if __name__ == "__main__":
    unittest.main()
