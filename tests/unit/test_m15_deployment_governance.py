from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.m15_deployment_governance_lib import (
    branch_allowed_for_development,
    issue_manifest,
    verify_manifest,
)


class M15DeploymentGovernanceTest(unittest.TestCase):
    def git(self, root: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)

    def fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "repo"
        root.mkdir()
        self.git(root, "init", "-b", "codex/fix-test")
        self.git(root, "config", "user.email", "test@example.com")
        self.git(root, "config", "user.name", "Test")
        source = root / "scripts" / "runtime.py"
        source.parent.mkdir()
        source.write_text("print('ok')\n", encoding="utf-8")
        config = root / "config.json"
        config.write_text("{}\n", encoding="utf-8")
        (root / ".gitignore").write_text("reports/runtime/\n", encoding="utf-8")
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", "fixture")
        remote = Path(tmp.name) / "remote.git"
        self.git(root, "remote", "add", "origin", str(remote))
        self.git(root, "init", "--bare", str(remote))
        self.git(root, "push", "-u", "origin", "HEAD")
        return tmp, root, config

    def test_development_branch_policy(self) -> None:
        self.assertTrue(branch_allowed_for_development("codex/fix-market-stream"))
        self.assertTrue(branch_allowed_for_development("feature/m15-stream"))
        self.assertFalse(branch_allowed_for_development("main"))
        self.assertFalse(branch_allowed_for_development("random-work"))

    def test_issue_and_verify_clean_remote_commit(self) -> None:
        tmp, root, config = self.fixture()
        self.addCleanup(tmp.cleanup)
        manifest = root / "reports" / "runtime" / "manifest.json"
        issue_manifest(config, manifest_path=manifest, runtime_files=["scripts/runtime.py"], root=root)
        result = verify_manifest(config, manifest_path=manifest, root=root)
        self.assertTrue(result["verified"])
        self.assertEqual(result["issues"], [])

    def test_dirty_worktree_and_config_drift_fail_closed(self) -> None:
        tmp, root, config = self.fixture()
        self.addCleanup(tmp.cleanup)
        manifest = root / "reports" / "runtime" / "manifest.json"
        issue_manifest(config, manifest_path=manifest, runtime_files=["scripts/runtime.py"], root=root)
        config.write_text(json.dumps({"changed": True}), encoding="utf-8")
        result = verify_manifest(config, manifest_path=manifest, root=root)
        self.assertFalse(result["verified"])
        self.assertIn("dirty_worktree", result["issues"])
        self.assertIn("deployment_config_drift", result["issues"])

    def test_source_drift_fails_closed(self) -> None:
        tmp, root, config = self.fixture()
        self.addCleanup(tmp.cleanup)
        manifest = root / "reports" / "runtime" / "manifest.json"
        issue_manifest(config, manifest_path=manifest, runtime_files=["scripts/runtime.py"], root=root)
        (root / "scripts" / "runtime.py").write_text("print('changed')\n", encoding="utf-8")
        result = verify_manifest(config, manifest_path=manifest, root=root)
        self.assertIn("deployment_source_drift:scripts/runtime.py", result["issues"])
