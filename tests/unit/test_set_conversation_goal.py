from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(module_name: str, relative_path: str):
    module_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SET_GOAL = load_module("set_conversation_goal", "scripts/set_conversation_goal.py")


class SetConversationGoalTest(unittest.TestCase):
    def test_build_goal_record_normalizes_goal_and_preserves_constraints(self) -> None:
        record = SET_GOAL.build_goal_record(
            "  只读检查   M12.47 守护器状态  ",
            generated_at="2026-05-22T12:00:00Z",
            context="status check",
        )

        self.assertEqual(record["schema_version"], "conversation.goal.v1")
        self.assertEqual(record["goal"], "只读检查 M12.47 守护器状态")
        self.assertEqual(record["generated_at"], "2026-05-22T12:00:00Z")
        self.assertEqual(record["context"], "status check")
        self.assertIn("Do not connect real broker accounts", " ".join(record["hard_constraints"]))

    def test_build_goal_record_rejects_empty_goal(self) -> None:
        with self.assertRaises(ValueError):
            SET_GOAL.build_goal_record("   ")

    def test_write_goal_files_outputs_json_and_markdown(self) -> None:
        record = SET_GOAL.build_goal_record(
            "修复目标设置入口",
            generated_at="2026-05-22T12:00:00Z",
            source="unit-test",
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = SET_GOAL.write_goal_files(record, Path(tmp))

            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
            markdown = paths["markdown"].read_text(encoding="utf-8")

        self.assertEqual(payload["goal"], "修复目标设置入口")
        self.assertIn("Goal: 修复目标设置入口", markdown)
        self.assertIn("below_AGENTS_active_plan_implement_status", markdown)


if __name__ == "__main__":
    unittest.main()
