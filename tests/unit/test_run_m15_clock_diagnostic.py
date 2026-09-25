import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import run_m15_clock_diagnostic as cli
from scripts.m15_feed_runtime import clock_preflight


class DiagnosticTests(unittest.TestCase):
    def test_cli_no_comparison_makes_exactly_one_assessment(self):
        with patch.object(cli.clock,'collect_time_quality',return_value={'quality_passed':False}) as run,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--windows-python','fake','--output-dir','output']),2)
        run.assert_called_once_with('fake','output')

    def test_adapter_binds_exact_run_spec_and_loads_bundle_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)
            (archive/'run-spec.json').write_text(json.dumps({'run_id':'run','window_start_utc':'2026-09-25T13:00:00Z','window_end_utc':'2026-09-25T20:00:05Z'}))
            (archive/'m15_feed_clock.py').write_text('def collect_time_quality(python,path,*,binding):\n return {"python":python,"path":str(path),"binding":binding}\n')
            result=clock_preflight.check(archive,windows_python='fake')
            self.assertEqual(result['binding']['checkpoint'],'startup')
            self.assertEqual(result['binding']['scheduled_elapsed_seconds'],0)
            self.assertEqual(len(result['binding']['run_spec_sha256']),64)
            self.assertTrue((archive/'clock').is_dir())
            self.assertEqual(Path(result['path']).parts[-2:],('clock','startup'))

if __name__=='__main__':unittest.main()
