from contextlib import ExitStack
import hashlib
import importlib.machinery
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from scripts import m15_sdk_provenance_lib as provenance


class SdkProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = self.root / ".venv-m15"
        self.site = self.env / "lib/python-test/site-packages"
        self.site.mkdir(parents=True)
        self.python = self.env / "bin/python"
        self.python.parent.mkdir()
        self.python.write_bytes(b"fixture-interpreter")
        self.filename = "longbridge-4.5.0-cp312-cp312-linux_x86_64.whl"
        self.wheel = self.root / self.filename
        self.module_name = "longbridge/openapi" + importlib.machinery.EXTENSION_SUFFIXES[0]
        self.contents = {"longbridge/__init__.py": b"# fixture; must never import\nraise RuntimeError('imported')\n",
                         self.module_name: b"official-native-fixture",
                         "longbridge/openapi.pyi": b"# fixture types",
                         "longbridge-4.5.0.dist-info/METADATA": b"Name: longbridge\nVersion: 4.5.0\n"}
        with zipfile.ZipFile(self.wheel, "w") as archive:
            for name, content in self.contents.items():
                archive.writestr(name, content)
                target = self.site / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        self.anchor = self.root / provenance.TRUST_PATH
        self.anchor.parent.mkdir()
        self.anchor.write_text(json.dumps({"schema_version": "m15.official-sdk-artifact.v1",
            "version": "4.5.0", "filename": self.filename, "sha256": provenance.digest(self.wheel),
            "source_url": "https://files.pythonhosted.org/packages/fixture/" + self.filename}))
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(sys, "prefix", str(self.env)))
        stack.enter_context(patch.object(sys, "executable", str(self.python)))
        stack.enter_context(patch.object(sys, "path", [str(self.site), *sys.path]))
        stack.enter_context(patch.dict(sys.modules, {"longbridge": None, "longbridge.openapi": None}))
        stack.enter_context(patch.dict("os.environ", {}, clear=True))
        stack.enter_context(patch.object(provenance.importlib.metadata, "distribution",
            return_value=SimpleNamespace(version="4.5.0", locate_file=lambda name: self.site / name)))

    def issue(self):
        return provenance.issue_environment_receipt(self.wheel, self.root)

    def check(self):
        return provenance.verify_environment(self.root)

    def test_official_artifact_checks_without_import_or_network(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            receipt = self.issue()
            self.assertTrue(self.check()["verified"])
        self.assertEqual(receipt["module_sha256"], hashlib.sha256(b"official-native-fixture").hexdigest())
        self.assertEqual(receipt["interpreter_path"], str(self.python))

    def test_same_version_patched_binary_is_rejected(self):
        self.issue()
        (self.site / self.module_name).write_bytes(b"patched-same-version")
        self.assertIn("sdk_installed_file_mismatch", str(self.check()["issues"]))
        with self.assertRaisesRegex(ValueError, "sdk_installed_file_mismatch"):
            self.issue()

    def test_arbitrary_wheel_cannot_be_self_signed(self):
        self.wheel.write_bytes(b"untrusted wheel")
        with self.assertRaisesRegex(ValueError, "sdk_wheel_hash_mismatch"):
            self.issue()

    def test_forging_receipt_does_not_bypass_binary_checks(self):
        receipt = self.issue()
        binary = self.site / self.module_name
        binary.write_bytes(b"patched")
        receipt["module_sha256"] = provenance.digest(binary)
        receipt["installed_files"][self.module_name] = provenance.digest(binary)
        (self.root / provenance.RECEIPT_PATH).write_text(json.dumps(receipt))
        self.assertFalse(self.check()["verified"])

    def test_extra_package_module_rejected(self):
        self.issue()
        (self.site / "longbridge/inject.py").write_text("# untrusted")
        self.assertIn("sdk_unexpected_package_files", str(self.check()["issues"]))

    def test_interpreter_drift_rejected(self):
        self.issue()
        self.python.write_bytes(b"different-interpreter")
        self.assertIn("sdk_environment_receipt_drift", str(self.check()["issues"]))

    def test_different_environment_rejected(self):
        self.issue()
        with patch.object(sys, "prefix", str(self.root / ".venv")):
            self.assertIn("sdk_interpreter_not_canonical", str(self.check()["issues"]))

    def test_shadow_import_rejected(self):
        self.issue()
        shadow = self.root / "shadow"
        (shadow / "longbridge").mkdir(parents=True)
        (shadow / "longbridge/__init__.py").write_text("# shadow")
        with patch.object(sys, "path", [str(shadow), *sys.path]):
            self.assertIn("sdk_import_shadowed", str(self.check()["issues"]))

    def test_patch_marker_and_dns_injection_rejected(self):
        self.issue()
        marker = self.env / ".m15-longbridge-sdk-no-first-push.json"
        marker.write_text("{}")
        self.assertIn("sdk_local_patch_marker_present", str(self.check()["issues"]))
        marker.unlink()
        with patch.dict("os.environ", {"LD_PRELOAD": "/tmp/override.so"}):
            self.assertIn("sdk_legacy_process_injection", str(self.check()["issues"]))

    def test_missing_trust_anchor_fails_closed(self):
        self.issue()
        self.anchor.unlink()
        self.assertFalse(self.check()["verified"])

    def test_nonofficial_origin_rejected(self):
        anchor = json.loads(self.anchor.read_text())
        anchor["source_url"] = "https://example.com/" + self.filename
        self.anchor.write_text(json.dumps(anchor))
        with self.assertRaisesRegex(ValueError, "sdk_trusted_artifact_invalid"):
            self.issue()


if __name__ == "__main__":
    unittest.main()
