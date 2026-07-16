from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.m12_m14_local_postclose_batch_lib import (
    load_local_postclose_batch_config,
    run_local_postclose_batch,
)


class LocalPostcloseBatchTest(unittest.TestCase):
    def write_reference_configs(self, root: Path) -> tuple[Path, Path]:
        repaired = json.loads((Path("config/examples/m12_local_repaired_universe_snapshot_147.json")).read_text(encoding="utf-8"))
        reference_universe = root / "reference_universe.json"
        reference_symbols = [("PARA" if symbol == "PSKY" else symbol) for symbol in repaired["symbols"]]
        reference_universe.write_text(
            json.dumps(
                {
                    "schema_version": "m12.local-universe-snapshot.v1",
                    "symbols": reference_symbols,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        m12_12_payload = json.loads((Path("config/examples/m12_12_daily_observation_loop.json")).read_text(encoding="utf-8"))
        m12_12_payload["output_dir"] = (root / "reference_m12_12").as_posix()
        m12_12_payload["universe_definition_path"] = reference_universe.as_posix()
        m12_12_config = root / "m12_12.json"
        m12_12_config.write_text(json.dumps(m12_12_payload, ensure_ascii=False), encoding="utf-8")

        m12_29_payload = json.loads((Path("config/examples/m12_29_current_day_scan_dashboard.json")).read_text(encoding="utf-8"))
        m12_29_payload["output_dir"] = (root / "reference_m12_29").as_posix()
        m12_29_payload["source_m12_12_config_path"] = m12_12_config.as_posix()
        m12_29_config = root / "m12_29.json"
        m12_29_config.write_text(json.dumps(m12_29_payload, ensure_ascii=False), encoding="utf-8")
        return m12_12_config, m12_29_config

    def write_batch_config(self, root: Path, *, max_attempts: int = 3) -> Path:
        _, m12_29_config = self.write_reference_configs(root)
        payload = json.loads((Path("config/examples/m12_m14_local_postclose_batch.json")).read_text(encoding="utf-8"))
        payload["retry"]["max_attempts"] = max_attempts
        payload["references"]["m12_12_config_path"] = (root / "m12_12.json").as_posix()
        payload["references"]["m12_29_config_path"] = m12_29_config.as_posix()
        payload["references"]["universe_reference_path"] = (root / "reference_universe.json").as_posix()
        payload["local_repair"]["output_dir"] = (root / "local_output").as_posix()
        config_path = root / "local_batch.json"
        config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return config_path

    def test_local_batch_runs_once_with_repaired_universe_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_local_postclose_batch_config(self.write_batch_config(root))
            fake_m12 = {
                "summary": {
                    "scan_date": "2026-07-15",
                    "quote_source": "longbridge_quote_readonly",
                    "current_day_runtime_ready": True,
                    "current_day_scan_complete": True,
                }
            }
            fake_m13 = {
                "summary": {
                    "ready_for_complete_reliable_testing": True,
                    "blocked_strategy_ids": [],
                },
                "goal_status": {"goal_complete": False},
            }
            fake_m14 = {
                "summary": {
                    "challenge_progress_label": "1/10",
                    "paper_candidate_count": 0,
                },
                "goal_status": {"goal_complete": False},
            }
            with (
                patch("scripts.m12_m14_local_postclose_batch_lib.run_m12_29_current_day_scan_dashboard", return_value=fake_m12),
                patch("scripts.m12_m14_local_postclose_batch_lib.run_m13_daily_strategy_test_runner", return_value=fake_m13),
                patch("scripts.m12_m14_local_postclose_batch_lib.run_m14_strategy_challenge_gate", return_value=fake_m14),
            ):
                result = run_local_postclose_batch(config, generated_at="2026-07-15T21:30:00Z")

            summary = result["summary"]
            self.assertTrue(summary["completed"])
            self.assertEqual(summary["attempt_count"], 1)
            self.assertEqual(summary["local_universe_repair"]["added_symbols"], ["PSKY"])
            self.assertEqual(summary["local_universe_repair"]["removed_symbols"], ["PARA"])
            self.assertIn("M10-PA-003", summary["classification"]["auxiliary_strategy_ids"])
            self.assertIn("AI-TRADER-EXTERNAL", summary["classification"]["source_only_strategy_ids"])
            self.assertTrue((config.local_repair.output_dir / "local_postclose_batch_summary.json").exists())

    def test_local_batch_retries_once_then_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_local_postclose_batch_config(self.write_batch_config(root))
            fake_m12 = {
                "summary": {
                    "scan_date": "2026-07-15",
                    "quote_source": "longbridge_quote_readonly",
                    "current_day_runtime_ready": True,
                    "current_day_scan_complete": True,
                }
            }
            fake_m13 = {
                "summary": {
                    "ready_for_complete_reliable_testing": True,
                    "blocked_strategy_ids": [],
                },
                "goal_status": {"goal_complete": False},
            }
            fake_m14 = {
                "summary": {
                    "challenge_progress_label": "1/10",
                    "paper_candidate_count": 0,
                },
                "goal_status": {"goal_complete": False},
            }
            with (
                patch(
                    "scripts.m12_m14_local_postclose_batch_lib.run_m12_29_current_day_scan_dashboard",
                    side_effect=[RuntimeError("first failure"), fake_m12],
                ),
                patch("scripts.m12_m14_local_postclose_batch_lib.run_m13_daily_strategy_test_runner", return_value=fake_m13),
                patch("scripts.m12_m14_local_postclose_batch_lib.run_m14_strategy_challenge_gate", return_value=fake_m14),
            ):
                result = run_local_postclose_batch(config, generated_at="2026-07-15T21:30:00Z")

            self.assertEqual(result["summary"]["attempt_count"], 2)
            self.assertEqual(result["summary"]["attempts"][0]["error_type"], "RuntimeError")
            self.assertEqual(result["summary"]["attempts"][1]["status"], "success")

    def test_local_batch_rejects_more_than_three_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_batch_config(root, max_attempts=4)
            with self.assertRaisesRegex(ValueError, "max_attempts"):
                load_local_postclose_batch_config(config_path)


if __name__ == "__main__":
    unittest.main()
