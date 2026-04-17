from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_shadow_session.py"


def _load_script_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("pat_run_shadow_session", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DatasetManifestContractTests(unittest.TestCase):
    def test_sample_manifest_is_valid_and_resolves_local_files(self) -> None:
        module = _load_script_module()
        manifest = module.load_dataset_manifest(module.SAMPLE_MANIFEST_PATH)

        self.assertEqual(manifest.dataset_name, "sample_us_5m_recorded_session")
        self.assertEqual(manifest.market, "US")
        self.assertEqual(manifest.timeframe, "5m")
        self.assertEqual(manifest.session_type, "simulated")
        self.assertTrue(manifest.ohlcv_path.exists())
        self.assertTrue(manifest.news_path.exists())
        self.assertIn("m8d_shadow_paper", manifest.approved_for)
        self.assertTrue(manifest.regime_tags)

    def test_invalid_manifest_fails_fast(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory(prefix="pat-m8d-invalid-manifest-") as temp_dir:
            dataset_root = Path(temp_dir)
            csv_path = dataset_root / "bars.csv"
            csv_path.write_text(
                "symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume\n",
                encoding="utf-8",
            )
            manifest_path = dataset_root / "dataset.manifest.json"
            manifest_path.write_text(
                """{
  "dataset_name": "bad_dataset",
  "dataset_version": "1",
  "source_type": "local_export",
  "market": "US",
  "symbol": "SAMPLE",
  "timeframe": "5m",
  "time_range": {
    "start": "2026-01-05T09:35:00-05:00",
    "end": "2026-01-05T09:30:00-05:00"
  },
  "regime_tags": ["trend_up"],
  "origin": "invalid test",
  "approved_for": ["live_execution"],
  "limitations": ["invalid on purpose"],
  "files": {
    "ohlcv": "bars.csv"
  },
  "session_type": "paper"
}""",
                encoding="utf-8",
            )

            with self.assertRaises(module.DatasetManifestError) as ctx:
                module.load_dataset_manifest(manifest_path)

        message = str(ctx.exception)
        self.assertIn("timezone", message)
        self.assertIn("approved_for", message)
        self.assertIn("time_range.start", message)

    def test_missing_manifest_returns_deferred_result(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory(prefix="pat-m8d-no-history-") as temp_dir:
            missing_root = Path(temp_dir) / "missing-history"
            original_dirs = module.DISCOVERY_DIRS
            try:
                module.DISCOVERY_DIRS = (missing_root,)
                self.assertEqual(module.discover_dataset_manifests(), [])
                deferred = module.build_deferred_result(
                    "manifest not provided",
                    discovered_manifests=(),
                )
            finally:
                module.DISCOVERY_DIRS = original_dirs

        self.assertEqual(deferred["status"], "deferred")
        self.assertEqual(deferred["boundary"], "paper/simulated")


if __name__ == "__main__":
    unittest.main()
