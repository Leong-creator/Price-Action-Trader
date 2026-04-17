from __future__ import annotations

import importlib.util
import sys
import unittest
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_shadow_session.py"


def _load_shadow_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("pat_run_shadow_session", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ShadowPaperConsistencyTests(unittest.TestCase):
    def test_sample_manifest_keeps_same_upstream_decisions_across_shadow_and_paper(self) -> None:
        module = _load_shadow_module()
        manifest = module.load_dataset_manifest(module.SAMPLE_MANIFEST_PATH)

        shadow_run = module.run_shadow_session(
            manifest,
            mode="shadow",
        )
        paper_run = module.run_shadow_session(
            manifest,
            mode="paper",
        )

        self.assertEqual(
            (
                shadow_run["dataset"]["dataset_name"],
                shadow_run["summary"]["bar_count"],
                shadow_run["summary"]["signal_count"],
                shadow_run["summary"]["trade_count"],
                tuple(shadow_run["summary"]["warnings"]),
                tuple(shadow_run["review_traceability"]["source_refs"]),
            ),
            (
                paper_run["dataset"]["dataset_name"],
                paper_run["summary"]["bar_count"],
                paper_run["summary"]["signal_count"],
                paper_run["summary"]["trade_count"],
                tuple(paper_run["summary"]["warnings"]),
                tuple(paper_run["review_traceability"]["source_refs"]),
            ),
        )
        self.assertEqual(shadow_run["mode"], "shadow")
        self.assertEqual(paper_run["mode"], "paper")
        self.assertEqual(shadow_run["boundary"], "paper/simulated")
        self.assertEqual(paper_run["boundary"], "paper/simulated")

    def test_shadow_runner_stays_paper_only_and_traceable(self) -> None:
        module = _load_shadow_module()
        manifest = module.load_dataset_manifest(module.SAMPLE_MANIFEST_PATH)
        result = module.run_shadow_session(
            manifest,
            mode="shadow",
        )

        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["live_execution"])
        self.assertFalse(result["broker_connected"])
        self.assertEqual(result["session"]["session_type"], "simulated")
        self.assertEqual(result["session"]["requested_mode"], "shadow")
        self.assertTrue(result["review_traceability"]["items"])
        item = result["review_traceability"]["items"][0]
        self.assertTrue(item["kb_source_refs"])
        self.assertTrue(item["pa_explanation"])
        self.assertTrue(item["risk_notes"])
        self.assertIn("news_source_refs", item)
        log_text = " ".join(
            [
                result["mode"],
                result["boundary"],
                result["session"]["input_mode"],
                item["trade_outcome"]["status"],
            ]
        ).lower()
        self.assertNotIn("live", log_text)
        self.assertNotIn("broker", log_text)


if __name__ == "__main__":
    unittest.main()
