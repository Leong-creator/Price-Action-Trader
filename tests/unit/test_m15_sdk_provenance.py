from contextlib import ExitStack
import hashlib
import importlib.machinery
import json
import os
import shutil
from pathlib import Path
import sys
import subprocess
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
        self.filename = "longbridge-5.0.0-cp312-cp312-linux_x86_64.whl"
        self.wheel = self.root / self.filename
        self.module_name = "longbridge/longbridge" + importlib.machinery.EXTENSION_SUFFIXES[0]
        self.contents = {"longbridge/__init__.py": b"# fixture; must never import\nraise RuntimeError('imported')\n",
                         self.module_name: b"official-native-fixture",
                         "longbridge/openapi.py": b"",
                         "longbridge/openapi.pyi": b"# fixture types",
                         "longbridge-5.0.0.dist-info/METADATA": b"Name: longbridge\nVersion: 5.0.0\n"}
        with zipfile.ZipFile(self.wheel, "w") as archive:
            for name, content in self.contents.items():
                archive.writestr(name, content)
                target = self.site / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        self.anchor = self.root / provenance.TRUST_PATH
        self.anchor.parent.mkdir()
        self.anchor.write_text(json.dumps({"schema_version": "m15.official-sdk-artifact.v1",
            "version": "5.0.0", "filename": self.filename, "sha256": provenance.digest(self.wheel),
            "source_url": "https://files.pythonhosted.org/packages/fixture/" + self.filename}))
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(sys, "prefix", str(self.env)))
        stack.enter_context(patch.object(sys, "executable", str(self.python)))
        stack.enter_context(patch.object(sys, "path", [str(self.site), *sys.path]))
        stack.enter_context(patch.dict(sys.modules, {"longbridge": None, "longbridge.longbridge": None,
                                                   "longbridge.openapi": None}))
        stack.enter_context(patch.dict("os.environ", {}, clear=True))
        stack.enter_context(patch.object(provenance.importlib.metadata, "distribution",
            return_value=SimpleNamespace(version="5.0.0", locate_file=lambda name: self.site / name)))

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

    def test_official_native_alias_layout_before_after_import(self):
        before = self.issue()
        api = SimpleNamespace()
        native = SimpleNamespace(__file__=str(self.site / self.module_name), openapi=api)
        package = SimpleNamespace(__file__=str(self.site / "longbridge/__init__.py"), openapi=api)
        with patch.dict(sys.modules, {"longbridge": package, "longbridge.longbridge": native,
                                     "longbridge.openapi": api}):
            after = self.check()
            self.assertTrue(after["verified"], after)
            self.assertEqual(before, after["environment"])
            self.assertEqual(after["environment"]["module_path"], str(self.site / self.module_name))

    def test_alias_substitution_is_rejected_even_without_a_file(self):
        self.issue()
        api = SimpleNamespace()
        native = SimpleNamespace(__file__=str(self.site / self.module_name), openapi=api)
        package = SimpleNamespace(__file__=str(self.site / "longbridge/__init__.py"), openapi=api)
        with patch.dict(sys.modules, {"longbridge": package, "longbridge.longbridge": native,
                                     "longbridge.openapi": SimpleNamespace()}):
            self.assertIn("sdk_loaded_alias_shadowed", str(self.check()["issues"]))

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


class RealOfficialWheelCompatibilityTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("M15_OFFICIAL_TEST_ROOT") and os.environ.get("M15_OFFICIAL_TEST_WHEEL"),
                         "Set explicit official environment/wheel paths for offline compatibility check")
    def test_real_official_wheel_before_and_after_sdk_import(self):
        root = Path(os.environ["M15_OFFICIAL_TEST_ROOT"]).resolve()
        wheel = Path(os.environ["M15_OFFICIAL_TEST_WHEEL"]).resolve()
        code = '''
import importlib.util, json, pathlib, socket, sys
socket.socket = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network forbidden"))
spec = importlib.util.spec_from_file_location("provenance_under_test", sys.argv[1])
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
root, wheel = pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
# Read the independently reviewed anchor supplied to this test, without writing
# either production receipts or any SDK installation files.
original_anchor = p.trusted_artifact
p.trusted_artifact = lambda ignored: original_anchor(pathlib.Path(sys.argv[4]))
original_digest = p.digest
p.digest = lambda path: original_digest(pathlib.Path(sys.argv[4]) / p.TRUST_PATH) if path == root / p.TRUST_PATH else original_digest(path)
before = p.inspect_environment(wheel, root)
import longbridge
from longbridge import openapi
after = p.inspect_environment(wheel, root)
assert before == after
assert openapi is sys.modules["longbridge.longbridge"].openapi
assert before["module_path"].endswith(".so")
assert "/longbridge/longbridge." in before["module_path"]
assert not getattr(openapi, "__file__", None)
print(json.dumps({"verified": True, "module_path": after["module_path"], "same_before_after_import": True}))
'''
        result = subprocess.run([str(root / ".venv-m15/bin/python"), "-B", "-c", code,
                                 str(Path(provenance.__file__).resolve()), str(root), str(wheel),
                                 str(Path(__file__).resolve().parents[2])],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["same_before_after_import"])

    @unittest.skipUnless(os.environ.get("M15_OFFICIAL_TEST_ROOT") and os.environ.get("M15_OFFICIAL_TEST_WHEEL"),
                         "Set explicit official environment/wheel paths for offline compatibility check")
    def test_real_official_native_tampering_in_disposable_environment(self):
        official_root = Path(os.environ["M15_OFFICIAL_TEST_ROOT"]).resolve()
        wheel = Path(os.environ["M15_OFFICIAL_TEST_WHEEL"]).resolve()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = root / ".venv-m15"
            subprocess.run([str(official_root / ".venv-m15/bin/python"), "-m", "venv",
                            "--without-pip", str(env)], check=True, capture_output=True, timeout=30)
            python = env / "bin/python"
            site = Path(subprocess.check_output([str(python), "-c",
                        "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(site)
            (root / provenance.TRUST_PATH).parent.mkdir()
            shutil.copyfile(Path(__file__).resolve().parents[2] / provenance.TRUST_PATH,
                            root / provenance.TRUST_PATH)
            code = '''
import importlib.util, pathlib, socket, sys
socket.socket = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network forbidden"))
spec = importlib.util.spec_from_file_location("provenance_under_test", sys.argv[1])
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
root, wheel = pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
receipt = p.issue_environment_receipt(wheel, root)
assert p.verify_environment(root)["verified"]
# Native extension is not imported/mapped; mutate only this temporary copy.
with pathlib.Path(receipt["module_path"]).open("r+b") as binary:
    byte = binary.read(1)
    binary.seek(0)
    binary.write(bytes([byte[0] ^ 1]))
result = p.verify_environment(root)
assert not result["verified"] and "sdk_installed_file_mismatch" in str(result["issues"]), result
print("official-native-tamper-rejected")
'''
            result = subprocess.run([str(python), "-B", "-c", code, str(Path(provenance.__file__).resolve()),
                                     str(root), str(wheel)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("official-native-tamper-rejected", result.stdout)


if __name__ == "__main__":
    unittest.main()
