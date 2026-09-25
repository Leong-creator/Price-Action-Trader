import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


class CanonicalStartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        source = Path(__file__).resolve().parents[2] / "scripts/start_m15_trading_stack_after_boot.sh"
        self.script = self.root / "scripts/start_m15_trading_stack_after_boot.sh"
        shutil.copyfile(source, self.script)
        python = self.root / ".venv-m15/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text('''#!/usr/bin/python3
import os, sys, time
from pathlib import Path
root = Path(__file__).resolve().parents[2]
with (root / 'calls').open('a') as log:
    log.write(' '.join(sys.argv[1:]) + '\\n')
if '--verify' in sys.argv:
    raise SystemExit(int(os.environ.get('TEST_VERIFY_FAILURE', '0')))
if '--daemon' in sys.argv:
    if Path('/proc/self/fd/9').exists():
        (root / 'inherited_lock').touch()
    time.sleep(0.15)
''')
        python.chmod(0o755)

    def run_startup(self, **extra_env):
        return subprocess.Popen(["bash", str(self.script)], cwd=self.root,
            env={**os.environ, **extra_env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_two_triggers_share_lock_without_inheriting_it_to_daemons(self):
        first = self.run_startup(PYTHON_BIN="/nonexistent/untrusted-interpreter")
        deadline = time.monotonic() + 3
        while not (self.root / "calls").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        second = self.run_startup()
        self.assertEqual(second.wait(timeout=5), 0)
        self.assertEqual(first.wait(timeout=5), 0)
        first.communicate()
        second.communicate()
        calls = (self.root / "calls").read_text().splitlines()
        self.assertEqual(sum("--verify" in c for c in calls), 1)
        self.assertEqual(sum("--daemon" in c for c in calls), 1)
        self.assertEqual(sum("run_m15_daily_feed.py launch" in c for c in calls), 1)
        self.assertEqual(sum("run_m15_daily_feed.py status" in c for c in calls), 1)
        self.assertFalse(any("run_m15_longbridge_sdk_runtime.py" in c for c in calls))
        self.assertFalse(any("--dispatch" in c for c in calls))
        self.assertFalse((self.root / "inherited_lock").exists())
        lock = next((self.root / "reports").rglob("startup.flock"))
        with lock.open("w") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_failed_provenance_prevents_runtime_and_watchdog(self):
        process = self.run_startup(TEST_VERIFY_FAILURE="3")
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 3)
        self.assertEqual((self.root / "calls").read_text().splitlines(),
                         ["scripts/run_m15_sdk_provenance.py --verify"])

    def test_retired_keep_alive_rejected_before_startup(self):
        result = subprocess.run(["bash", str(self.script), "--keep-alive"], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / "calls").exists())


if __name__ == "__main__":
    unittest.main()
