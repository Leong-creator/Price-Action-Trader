from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.m15_pa002_repaired_state_lib import consume_next_eligible_signal, sync_repaired_state


class M15Pa002RepairedStateTest(unittest.TestCase):
    def test_two_actual_losses_skip_exactly_one_next_eligible_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attribution = root / "attribution.json"
            state_path = root / "state.json"
            attribution.write_text(
                json.dumps(
                    {
                        "completed_trades": [
                            self.trade("one", "-1.00", "2026-08-03T14:00:00Z"),
                            self.trade("two", "-2.00", "2026-08-03T15:00:00Z"),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            state = sync_repaired_state(attribution, state_path, generated_at="2026-08-03T15:01:00Z")

            self.assertEqual(state["pending_skip_count"], 1)
            self.assertTrue(
                consume_next_eligible_signal(
                    state,
                    state_path,
                    signal_id="eligible-one",
                    consumed_at="2026-08-03T15:05:00Z",
                )
            )
            self.assertFalse(
                consume_next_eligible_signal(
                    state,
                    state_path,
                    signal_id="eligible-two",
                    consumed_at="2026-08-03T15:10:00Z",
                )
            )
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["pending_skip_count"], 0)
            self.assertFalse(persisted["local_simulation_used"])

    def test_win_resets_loss_streak_and_sync_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attribution = root / "attribution.json"
            state_path = root / "state.json"
            attribution.write_text(
                json.dumps(
                    {
                        "completed_trades": [
                            self.trade("one", "-1.00", "2026-08-03T14:00:00Z"),
                            self.trade("two", "2.00", "2026-08-03T15:00:00Z"),
                            self.trade("three", "-3.00", "2026-08-03T16:00:00Z"),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            first = sync_repaired_state(attribution, state_path)
            second = sync_repaired_state(attribution, state_path)

            self.assertEqual(first["consecutive_losses"], 1)
            self.assertEqual(first["pending_skip_count"], 0)
            self.assertEqual(second["newly_processed_trade_count"], 0)

    @staticmethod
    def trade(batch_id: str, pnl: str, closed_at: str) -> dict[str, str]:
        return {
            "batch_id": batch_id,
            "runtime_id": "M10-PA-002-5m-repaired-v1",
            "gross_realized_pnl": pnl,
            "estimated_net_pnl": pnl,
            "closed_at": closed_at,
        }


if __name__ == "__main__":
    unittest.main()
