import importlib.util
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('controller',Path(__file__).resolve().parents[3]/'scripts/m15_feed_runtime/controller.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class Watchdog(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.case=Path(self.temp.name);self.clock=100.
        p=patch.object(c.time,'monotonic',lambda:self.clock);p.start();self.addCleanup(p.stop)
        self.watch=c.PhaseWatchdog(self.case,'fixture',datetime.now(timezone.utc)+timedelta(hours=1))
        self.rows=[]
    def stage(self, phase):
        self.rows.append({'run_id':'fixture','sequence':len(self.rows)+1,'phase':phase,'phase_started_monotonic':self.clock})
        (self.case/'stages.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in self.rows))
    def test_real_producer_five_phase_history(self):
        for phase in ('initializing','daily_context','subscribing','initial_snapshot'):
            self.stage(phase);self.assertIsNone(self.watch());self.clock+=1
        self.stage('streaming')
        (self.case/'health.json').write_text(json.dumps({'run_id':'fixture','phase':'streaming','status':'observing','observed_monotonic':self.clock}))
        self.assertIsNone(self.watch())
    def test_daily_600_seconds(self):
        self.stage('initializing');self.stage('daily_context');self.clock=699
        self.assertIsNone(self.watch());self.clock=701;self.assertEqual(self.watch(),'daily_context_deadline')
    def test_initial_snapshot_45_seconds(self):
        for phase in ('initializing','daily_context','subscribing','initial_snapshot'):self.stage(phase)
        self.clock=146;self.assertEqual(self.watch(),'initial_snapshot_deadline')
    def test_health_not_extended(self):
        for phase in ('initializing','daily_context','subscribing','initial_snapshot','streaming'):self.stage(phase)
        self.clock=106;self.assertEqual(self.watch(),'health_missing')

if __name__=='__main__':unittest.main()

class CloseDeadline(unittest.TestCase):
    def test_close_grace_still_bounded(self):
        real=datetime
        end=real.fromisoformat('2026-09-25T20:00:05+00:00')
        class Clock:
            value=end+timedelta(seconds=10.01)
            @classmethod
            def now(cls,tz=None):return cls.value
        with tempfile.TemporaryDirectory() as temp, patch.object(c,'datetime',Clock):
            watchdog=c.PhaseWatchdog(Path(temp),'fixture',end)
            self.assertEqual(watchdog(),'window_end_cleanup_deadline')

class MainDurationIntegration(unittest.TestCase):
    def test_main_real_duration_crosses_run_case_gate(self):
        import hashlib
        import sys
        from contextlib import ExitStack
        class ReachedWinBoundary(Exception):pass
        class ForbiddenWin:
            def __init__(self):raise ReachedWinBoundary('real run_case passed duration/path/hash checks')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);case=root/'daily-2026-09-25';case.mkdir()
            source=case/'source.py';source.write_text('# offline dummy source')
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            end=datetime.fromisoformat('2026-09-25T20:00:05+00:00')
            manifest={'case':'daily-2026-09-25','run_nonce':'fixture','window_start_utc':'2026-09-25T13:15:00+00:00','window_end_utc':end.isoformat(),'files':{'source.py':{'sha256':digest},'health.py':{'sha256':'a'*64},'run-spec.json':{'sha256':'b'*64}}}
            real_run_case=c.run_case
            seconds=[]
            def actual_run(case,**kwargs):
                seconds.append(kwargs['seconds'])
                return real_run_case(case,root=root,**kwargs)
            class Clock:
                @classmethod
                def now(cls,tz=None):return datetime.fromisoformat('2026-09-25T13:15:00+00:00')
            with ExitStack() as stack:
                for target,name,value in [(c,'ROOT',root),(c,'PYTHON',root/'fake-python.exe'),(c,'SOURCE_SHA256',digest),(c,'MAX_RUNTIME_SECONDS',24315),(c,'Win',ForbiddenWin),(c,'datetime',Clock),(c,'verify_manifest',lambda case:(manifest,{},end)),(c,'run_case',actual_run),(sys,'argv',['controller.py',str(case)])]:
                    stack.enter_context(patch.object(target,name,value))
                with self.assertRaises(ReachedWinBoundary):c.main()
            self.assertEqual(seconds,[24315])

    def test_run_case_rejects_beyond_frozen_cap_before_windows(self):
        for seconds in (24315.001,0,float('inf'),float('nan')):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError,'deadline_out_of_range'):
                c.run_case(Path('/no-case-needed'),seconds=seconds)
