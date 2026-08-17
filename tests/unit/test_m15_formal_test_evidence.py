from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_formal_test_evidence_lib import (
    generate_formal_test_evidence,
    load_config,
)


RUNTIMES = [
    "M10-PA-001-1d",
    "M10-PA-002-5m",
    "M10-PA-012-5m",
    "M10-PA-004-MBF-QC-1d",
    "M12-FTD-001-pullback-guard-confirm-1d",
    "M10-PA-002-5m-short",
    "M10-PA-013-5m-short",
    "M10-PA-011-ORB-R1-5m-short",
]


class FormalTestEvidenceTest(unittest.TestCase):
    def write_json(self, path: Path, payload: object) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_jsonl(self, path: Path, rows: list[dict[str, object]]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def fixture(
        self,
        root: Path,
        *,
        session_complete: bool = True,
        signal_ready_runtime: str = "",
        add_order: bool = False,
    ) -> Path:
        coverage = {
            "business_date": "2026-08-17",
            "expected_boundary_count_so_far": 78,
            "complete_boundary_count": 78 if session_complete else 77,
            "accepted_row_count_so_far": 11_466 if session_complete else 11_319,
            "partial_boundary_count": 0,
            "missing_boundary_count": 0 if session_complete else 1,
            "duplicate_count": 0,
            "invalid_row_count": 0,
            "session_complete": session_complete,
        }
        self.write_json(
            root / "runtime.json",
            {
                "runtime_engine": "sdk",
                "sdk_connected": True,
                "five_minute_session_coverage": coverage,
            },
        )
        self.write_json(
            root / "account.json",
            {"paper_account_verified": True, "account_channel": "lb_papertrading"},
        )
        self.write_json(
            root / "execution.json",
            {
                "longbridge_realtime": {"allowed_runtime_ids": RUNTIMES},
                "strategy_contracts": {"directory": str(root / "contracts")},
                "runtime_layering": {
                    "visual_shadow_only": [
                        "M10-PA-004-long-1d",
                        "M10-PA-007-1d",
                        "M10-PA-008-1d",
                    ],
                    "retired_simplified_versions": ["old-a", "old-b"],
                },
            },
        )
        contract_hashes = {runtime_id: f"hash-{index}" for index, runtime_id in enumerate(RUNTIMES)}
        for runtime_id, contract_hash in contract_hashes.items():
            self.write_json(
                root / "contracts" / f"{runtime_id}.json",
                {"runtime_id": runtime_id, "contract_hash": contract_hash},
            )
        detector_attempt_rows = []
        decision_rows = []
        for runtime_id in RUNTIMES:
            emitted = runtime_id == signal_ready_runtime
            detector_attempt_rows.append(
                {
                    "runtime_id": runtime_id,
                    "market_event_time": "2026-08-17T19:00:00Z",
                    "strategy_contract_hash": contract_hashes[runtime_id],
                    "candidate_emitted": emitted,
                    "no_candidate_reason": "structure_not_confirmed" if not emitted else "",
                }
            )
            if emitted:
                decision_rows.append(
                    {
                        "runtime_id": runtime_id,
                        "created_at": "2026-08-17T19:00:00Z",
                        "strategy_contract_hash": contract_hashes[runtime_id],
                        "router_decision_status": "signal_event_ready",
                    }
                )
        self.write_json(
            root / "diagnostics.json",
            {
                "generated_at": "2026-08-17T20:01:00Z",
                "detector_attempt_rows": detector_attempt_rows,
                "decision_rows": decision_rows,
            },
        )
        execution_rows = []
        reconciliation_rows = []
        if add_order:
            execution_rows.append(
                {
                    "runtime_id": signal_ready_runtime,
                    "created_at": "2026-08-17T19:00:00Z",
                    "longbridge_order_id": "order-1",
                    "submission_status": "submitted",
                    "test_epoch_id": "formal",
                    "strategy_contract_hash": contract_hashes[signal_ready_runtime],
                }
            )
            reconciliation_rows.append(
                {"order_id": "order-1", "canonical_status": "Filled"}
            )
        self.write_jsonl(root / "execution-ledger.jsonl", execution_rows)
        self.write_json(root / "reconciliation.json", {"rows": reconciliation_rows})
        self.write_json(
            root / "fill.json",
            {
                "strategy_performance": [
                    {"runtime_id": runtime_id, "completed_trade_count": 2}
                    for runtime_id in RUNTIMES
                ]
            },
        )
        self.write_json(
            root / "epoch.json",
            {"test_epoch_id": "formal", "short_test_epoch_id": "short-formal"},
        )
        self.write_json(
            root / "visual.json",
            {
                strategy: {
                    "runtime_id": f"M10-{strategy}",
                    "no_future_data": True,
                    "restart_parity": True,
                    "realtime_shadow_sessions": 0,
                    "human_review_passed_counts": {},
                }
                for strategy in ("PA004", "PA007", "PA008")
            },
        )
        self.write_json(root / "calendar.json", {"market_holidays": []})
        config = {
            "stage": "M15.formal_test_evidence",
            "inputs": {
                "sdk_runtime_status": str(root / "runtime.json"),
                "account_state": str(root / "account.json"),
                "execution_config": str(root / "execution.json"),
                "strategy_signal_diagnostics": str(root / "diagnostics.json"),
                "execution_ledger": str(root / "execution-ledger.jsonl"),
                "order_reconciliation": str(root / "reconciliation.json"),
                "fill_attribution": str(root / "fill.json"),
                "formal_epoch": str(root / "epoch.json"),
                "visual_acceptance": str(root / "visual.json"),
                "market_calendar": str(root / "calendar.json"),
            },
            "outputs": {
                "session_ledger_jsonl": str(root / "ledger.jsonl"),
                "summary_json": str(root / "summary.json"),
                "report_md": str(root / "report.md"),
            },
            "acceptance": {
                "required_symbol_count": 147,
                "required_boundary_count": 78,
                "stable_session_target": 3,
                "operational_session_target": 5,
                "performance_minimum_clean_days": 20,
                "performance_minimum_completed_trades": 30,
            },
        }
        return self.write_json(root / "config.json", config)

    def test_missing_market_calendar_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.fixture(root)
            (root / "calendar.json").unlink()

            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_complete_session_records_four_independent_layers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = generate_formal_test_evidence(
                load_config(self.fixture(root)),
                generated_at="2026-08-17T20:10:00Z",
            )

            self.assertTrue(result["layers"]["market_session"]["complete"])
            self.assertTrue(result["layers"]["strategy_operation"]["complete"])
            self.assertTrue(result["layers"]["broker_execution"]["complete"])
            self.assertEqual(result["layers"]["performance_sample"]["status"], "insufficient")
            self.assertEqual(result["inventory"]["executable_contract_count"], 8)
            self.assertEqual(result["inventory"]["visual_contract_draft_count"], 3)
            self.assertEqual(result["progress"]["consecutive_clean_session_count"], 1)
            self.assertEqual(len((root / "ledger.jsonl").read_text().splitlines()), 1)

    def test_incomplete_market_session_is_not_counted_as_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = generate_formal_test_evidence(
                load_config(self.fixture(root, session_complete=False)),
                generated_at="2026-08-17T20:10:00Z",
            )

            self.assertEqual(result["layers"]["market_session"]["status"], "incomplete")
            self.assertEqual(result["progress"]["consecutive_clean_session_count"], 0)
            self.assertFalse(result["formal_performance_baseline"]["status"] == "eligible_to_start")

    def test_non_sdk_or_non_paper_runtime_is_not_counted_as_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(self.fixture(root))
            runtime = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
            runtime["runtime_engine"] = "cli"
            self.write_json(root / "runtime.json", runtime)

            result = generate_formal_test_evidence(
                config,
                generated_at="2026-08-17T20:10:00Z",
            )

            self.assertFalse(result["sdk_paper_runtime_ready"])
            self.assertEqual(result["progress"]["consecutive_clean_session_count"], 0)
            for layer_name in ("market_session", "strategy_operation", "broker_execution"):
                self.assertEqual(
                    result["layers"][layer_name]["status"],
                    "blocked_runtime_prerequisite",
                )

    def test_ready_signal_without_order_or_blocker_is_an_execution_fault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = generate_formal_test_evidence(
                load_config(self.fixture(root, signal_ready_runtime=RUNTIMES[0])),
                generated_at="2026-08-17T20:10:00Z",
            )

            broker = result["layers"]["broker_execution"]
            self.assertEqual(broker["status"], "needs_attention")
            self.assertEqual(broker["unexplained_signal_drop_count"], 1)
            self.assertEqual(result["progress"]["consecutive_clean_session_count"], 0)

    def test_ready_signal_with_real_order_is_operational(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = generate_formal_test_evidence(
                load_config(
                    self.fixture(
                        root,
                        signal_ready_runtime=RUNTIMES[0],
                        add_order=True,
                    )
                ),
                generated_at="2026-08-17T20:10:00Z",
            )

            row = result["layers"]["broker_execution"]["runtime_rows"][0]
            self.assertEqual(row["status"], "broker_order_created")
            self.assertEqual(row["filled_or_partial_order_count"], 1)

    def test_old_epoch_or_contract_order_does_not_explain_current_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(
                self.fixture(
                    root,
                    signal_ready_runtime=RUNTIMES[0],
                    add_order=True,
                )
            )
            rows = [json.loads(line) for line in (root / "execution-ledger.jsonl").read_text().splitlines()]
            rows[0]["test_epoch_id"] = "old-epoch"
            self.write_jsonl(root / "execution-ledger.jsonl", rows)

            result = generate_formal_test_evidence(
                config,
                generated_at="2026-08-17T20:10:00Z",
            )

            broker = result["layers"]["broker_execution"]
            self.assertEqual(broker["unexplained_signal_drop_count"], 1)
            self.assertEqual(broker["excluded_noncurrent_execution_row_count"], 1)

    def test_old_contract_hash_order_does_not_explain_current_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(
                self.fixture(
                    root,
                    signal_ready_runtime=RUNTIMES[0],
                    add_order=True,
                )
            )
            rows = [json.loads(line) for line in (root / "execution-ledger.jsonl").read_text().splitlines()]
            rows[0]["strategy_contract_hash"] = "old-contract-hash"
            self.write_jsonl(root / "execution-ledger.jsonl", rows)

            result = generate_formal_test_evidence(
                config,
                generated_at="2026-08-17T20:10:00Z",
            )

            broker = result["layers"]["broker_execution"]
            self.assertEqual(broker["unexplained_signal_drop_count"], 1)
            self.assertEqual(broker["excluded_noncurrent_execution_row_count"], 1)

    def test_thirty_trades_before_twenty_clean_days_remains_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(self.fixture(root))
            fill = json.loads((root / "fill.json").read_text(encoding="utf-8"))
            for row in fill["strategy_performance"]:
                row["completed_trade_count"] = 30
            self.write_json(root / "fill.json", fill)

            result = generate_formal_test_evidence(
                config,
                generated_at="2026-08-17T20:10:00Z",
            )

            performance = result["layers"]["performance_sample"]
            self.assertEqual(performance["status"], "insufficient")
            self.assertFalse(performance["counts_as_clean_formal_performance"])
            self.assertTrue(all(row["status"] == "insufficient" for row in performance["runtime_rows"]))

    def test_thirty_trades_after_twenty_clean_days_is_sufficient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(self.fixture(root))
            fill = json.loads((root / "fill.json").read_text(encoding="utf-8"))
            for row in fill["strategy_performance"]:
                row["completed_trade_count"] = 30
            self.write_json(root / "fill.json", fill)
            self.write_jsonl(
                root / "ledger.jsonl",
                [
                    {
                        "business_date": f"2026-07-{day:02d}",
                        "market_session": {"complete": True},
                    }
                    for day in range(1, 20)
                ],
            )

            result = generate_formal_test_evidence(
                config,
                generated_at="2026-08-17T20:10:00Z",
            )

            performance = result["layers"]["performance_sample"]
            self.assertEqual(performance["status"], "sufficient")
            self.assertTrue(performance["counts_as_clean_formal_performance"])
            self.assertTrue(all(row["status"] == "sufficient" for row in performance["runtime_rows"]))

    def test_visual_contracts_never_gain_order_permission_from_machine_proofs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = generate_formal_test_evidence(
                load_config(self.fixture(root)),
                generated_at="2026-08-17T20:10:00Z",
            )

            rows = result["layers"]["visual_contract_drafts"]["runtime_rows"]
            self.assertTrue(all(row["stage"] == "contract_draft_v1" for row in rows))
            self.assertTrue(all(row["paper_orders_allowed"] is False for row in rows))

    def test_weekend_is_not_recorded_as_waiting_or_failed_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(self.fixture(root, session_complete=False))
            runtime = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
            runtime["five_minute_session_coverage"].update(
                {
                    "business_date": "2026-08-16",
                    "expected_boundary_count_so_far": 0,
                    "complete_boundary_count": 0,
                    "accepted_row_count_so_far": 0,
                    "missing_boundary_count": 0,
                }
            )
            self.write_json(root / "runtime.json", runtime)
            result = generate_formal_test_evidence(
                config,
                generated_at="2026-08-16T16:00:00Z",
            )

            self.assertEqual(
                result["layers"]["market_session"]["status"],
                "not_applicable_non_trading_day",
            )
            self.assertEqual(
                result["layers"]["strategy_operation"]["status"],
                "not_applicable_non_trading_day",
            )
            self.assertFalse((root / "ledger.jsonl").exists())

    def test_configured_market_holiday_is_not_recorded_as_failed_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_config(self.fixture(root, session_complete=False))
            runtime = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
            runtime["five_minute_session_coverage"].update(
                {
                    "business_date": "2026-05-25",
                    "expected_boundary_count_so_far": 0,
                    "complete_boundary_count": 0,
                    "accepted_row_count_so_far": 0,
                    "missing_boundary_count": 0,
                }
            )
            self.write_json(root / "runtime.json", runtime)
            self.write_json(root / "calendar.json", {"market_holidays": ["2026-05-25"]})

            result = generate_formal_test_evidence(
                config,
                generated_at="2026-05-25T16:00:00Z",
            )

            self.assertEqual(
                result["layers"]["market_session"]["status"],
                "not_applicable_non_trading_day",
            )
            self.assertFalse((root / "ledger.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
