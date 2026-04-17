from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
import sys
import types

from tests.reliability._support import _bar, end_of_data_bars, future_tail_bars, sideways_bars


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_shadow_session.py"


def _load_shadow_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("pat_run_shadow_session_regime", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RegimeRobustnessTests(unittest.TestCase):
    def test_local_history_exports_remain_honest_across_regimes(self) -> None:
        module = _load_shadow_module()
        cases = (
            ("trend_up", future_tail_bars(), 1, "stop_hit", ()),
            ("range", sideways_bars(), 0, None, ("no structured signals provided",)),
            ("gap_heavy", end_of_data_bars(), 1, "end_of_data", ("reached the end of available bars",)),
        )

        for regime_tag, bars_fixture, expected_trade_count, expected_exit_reason, warning_markers in cases:
            with self.subTest(regime_tag=regime_tag):
                manifest_path = self._write_manifest(
                    regime_tag,
                    bars_fixture,
                )
                manifest = module.load_dataset_manifest(manifest_path)
                report = module.run_shadow_session(manifest, mode="shadow")

                self.assertEqual(report["dataset"]["regime_tags"], [regime_tag])
                self.assertEqual(report["summary"]["trade_count"], expected_trade_count)
                if expected_exit_reason is None:
                    self.assertEqual(report["summary"]["signal_count"], 0)
                    self.assertEqual(report["review_traceability"]["items"], [])
                else:
                    self.assertTrue(report["review_traceability"]["items"])
                    self.assertEqual(
                        report["review_traceability"]["items"][0]["trade_outcome"]["exit_reason"],
                        expected_exit_reason,
                    )
                    self.assertTrue(report["review_traceability"]["items"][0]["kb_source_refs"])
                    self.assertTrue(report["review_traceability"]["items"][0]["pa_explanation"])
                    self.assertTrue(report["review_traceability"]["items"][0]["risk_notes"])

                for marker in warning_markers:
                    self.assertTrue(any(marker in warning for warning in report["summary"]["warnings"]))

    def test_user_export_like_market_and_timeframe_tags_survive_load(self) -> None:
        module = _load_shadow_module()
        hk_bars = (
            _bar(0, market="HK", timeframe="15m", open_="50.0", high="50.3", low="49.8", close="50.1"),
            _bar(1, market="HK", timeframe="15m", open_="50.1", high="50.6", low="50.0", close="50.4"),
            _bar(2, market="HK", timeframe="15m", open_="50.4", high="51.0", low="50.3", close="50.9"),
        )

        manifest_path = self._write_manifest(
            "trend_up",
            hk_bars,
            market="HK",
            timeframe="15m",
            timezone="Asia/Hong_Kong",
        )
        manifest = module.load_dataset_manifest(manifest_path)
        report = module.run_shadow_session(manifest, mode="shadow")

        self.assertEqual(report["dataset"]["market"], "HK")
        self.assertEqual(report["dataset"]["timeframe"], "15m")
        self.assertEqual(report["dataset"]["timezone"], "Asia/Hong_Kong")
        self.assertEqual(report["summary"]["signal_count"], 1)

    def _write_manifest(
        self,
        regime_tag: str,
        bars,
        *,
        market: str = "US",
        timeframe: str = "5m",
        timezone: str | None = None,
    ) -> Path:
        rows = ["symbol,market,timeframe,timestamp,timezone,open,high,low,close,volume"]
        for bar in bars:
            rows.append(
                ",".join(
                    (
                        bar.symbol,
                        market,
                        timeframe,
                        bar.timestamp.replace(tzinfo=None).isoformat(),
                        timezone or bar.timezone,
                        str(bar.open),
                        str(bar.high),
                        str(bar.low),
                        str(bar.close),
                        str(bar.volume),
                    )
                )
            )

        temp_dir = Path(tempfile.mkdtemp(prefix="pat-m8d-regime-"))
        csv_path = temp_dir / "ohlcv.csv"
        csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        manifest_path = temp_dir / "dataset.manifest.json"
        manifest_path.write_text(
            f"""{{
  "dataset_name": "regime_{regime_tag}",
  "dataset_version": "1",
  "source_type": "local_export",
  "market": "{market}",
  "symbol": "SAMPLE",
  "timeframe": "{timeframe}",
  "timezone": "{timezone or bars[0].timezone}",
  "time_range": {{
    "start": "{bars[0].timestamp.isoformat()}",
    "end": "{bars[-1].timestamp.isoformat()}"
  }},
  "regime_tags": ["{regime_tag}"],
  "origin": "temporary regime robustness fixture",
  "approved_for": ["offline_replay", "m8d_shadow_paper"],
  "limitations": ["temporary local fixture only"],
  "files": {{
    "ohlcv": "ohlcv.csv"
  }},
  "session_type": "simulated"
}}""",
            encoding="utf-8",
        )
        return manifest_path


if __name__ == "__main__":
    unittest.main()
