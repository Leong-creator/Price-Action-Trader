import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('bridge',Path(__file__).resolve().parents[3]/'scripts/m15_feed_runtime/bridge_lifecycle.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class Proc:
    def __init__(self, rc=None, timeout=False):
        self.returncode=rc; self.stdin=io.BytesIO(); self.timeout=timeout;self.terminated=False
    def poll(self): return self.returncode
    def wait(self,timeout=None):
        if self.timeout and self.returncode is None: raise subprocess.TimeoutExpired('fake',timeout)
        if self.returncode is None: self.returncode=4 if self.stdin.closed else 0
        return self.returncode
    def terminate(self): self.terminated=True;self.returncode=-15
    def kill(self): self.returncode=-9

class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)
        self.manifest={'run_nonce':'fixture','window_start_utc':'2026-09-24T15:15:00+00:00','window_end_utc':'2026-09-24T16:00:05+00:00','consumer':{'output_dir':str(self.output)}}
        self.end=b.datetime.fromisoformat(self.manifest['window_end_utc']).timestamp()
        self.good={'run_id':'fixture','producer_end_observed':True,'bounded_pipeline_observed':True,'reason':None,'complete_boundary_count':3,'strategy_evaluation_count':21}
        self.good.update(schema_version=1,status='window_observed',window_start_utc=self.manifest['window_start_utc'],window_end_utc=self.manifest['window_end_utc'],producer_end_sequence=99,last_sequence=99,all_expected_boundaries_observed=True,expected_complete_boundary_count=3,production_acceptance=False,account_access=False,order_access=False)
    def save(self, obj=None): (self.output/'summary.json').write_text(json.dumps(self.good if obj is None else obj))
    def test_missing_summary(self):self.assertFalse(b.consumer_passed(self.manifest,0))
    def test_malformed_summary(self):
        (self.output/'summary.json').write_text('{');self.assertFalse(b.consumer_passed(self.manifest,0))
    def test_missing_eof(self):
        self.good['producer_end_observed']=False;self.save();self.assertFalse(b.consumer_passed(self.manifest,0))
    def test_wrong_identity(self):
        self.good['run_id']='foreign';self.save();self.assertFalse(b.consumer_passed(self.manifest,0))
    def test_no_strategy(self):
        self.good['strategy_evaluation_count']=0;self.save();self.assertFalse(b.consumer_passed(self.manifest,0))
    def test_nonzero_exit(self):self.save();self.assertFalse(b.consumer_passed(self.manifest,4))
    def test_good_terminal(self):self.save();self.assertTrue(b.consumer_passed(self.manifest,0))
    def supervise(self, c, p, wall=None):
        return b.supervise(c,p,self.manifest,initial_deadline=10,final_deadline=20,now=lambda:self.end if wall is None else wall,monotonic=lambda:0,sleep=lambda _:None)
    def test_consumer_fail_closes_windows_pipe(self):
        controller=Proc(); consumer=Proc(4)
        result=self.supervise(controller,consumer)
        self.assertTrue(controller.stdin.closed);self.assertFalse(result['consumer_passed'])
    def test_early_consumer_success_rejected(self):
        self.save();controller=Proc();result=self.supervise(controller,Proc(0),self.end-1)
        self.assertTrue(controller.stdin.closed);self.assertFalse(result['consumer_passed'])
    def test_windows_unknown_raises(self):
        controller=Proc(timeout=True)
        with self.assertRaisesRegex(RuntimeError,'fence_retained'):self.supervise(controller,Proc(4))
        self.assertTrue(controller.stdin.closed)
    def test_windows_exit_consumer_missing_eof_fails(self):
        self.good['producer_end_observed']=False;self.save()
        result=self.supervise(Proc(0),Proc(0));self.assertFalse(result['consumer_passed'])
    def test_wall_clock_jump_deadline_not_passed(self):
        self.save();result=self.supervise(Proc(0),Proc(0),self.end+26)
        self.assertFalse(result['consumer_passed'])
    def test_success(self):
        self.save();self.assertTrue(self.supervise(Proc(0),Proc(0))['consumer_passed'])
    def test_consumer_hang_terminated(self):
        self.save(); consumer=Proc(timeout=True)
        # fake process completes termination; no second wait is needed.
        result=self.supervise(Proc(0),consumer)
        self.assertTrue(consumer.terminated);self.assertFalse(result['consumer_passed'])

class SignalShutdown(Lifecycle):
    pass
for name in [name for name in vars(Lifecycle) if name.startswith('test_')]:
    setattr(SignalShutdown,name,None)

def signal_closes_pipe(self):
    import sys
    from types import SimpleNamespace
    controller=Proc();consumer=Proc(4)
    with patch.dict(sys.modules,{'pat_launch_state':SimpleNamespace(stop_requested=lambda:True)}):
        result=self.supervise(controller,consumer,self.end-100)
    self.assertTrue(controller.stdin.closed)
    self.assertEqual(result['consumer_failure'],'supervisor_signal_stop')
    self.assertFalse(result['consumer_passed'])

def signal_unknown_exit_retains(self):
    import sys
    from types import SimpleNamespace
    controller=Proc(timeout=True)
    with patch.dict(sys.modules,{'pat_launch_state':SimpleNamespace(stop_requested=lambda:True)}),self.assertRaisesRegex(RuntimeError,'fence_retained'):
        self.supervise(controller,Proc(4),self.end-100)
    self.assertTrue(controller.stdin.closed)

SignalShutdown.test_signal_closes_pipe_and_fails_window=signal_closes_pipe
SignalShutdown.test_signal_unknown_windows_exit_retains=signal_unknown_exit_retains

if __name__=='__main__':unittest.main()

class ClosingWindow(Lifecycle):
    # Only run additions; base behavior remains in Lifecycle.
    pass
for _name in [name for name in vars(Lifecycle) if name.startswith('test_')]:
    setattr(ClosingWindow, _name, None)

def midnight(self):
    from zoneinfo import ZoneInfo
    local=b.datetime.fromisoformat(self.manifest['window_end_utc']).astimezone(ZoneInfo('Asia/Shanghai'))
    self.assertEqual(local.isoformat(),'2026-09-25T00:00:05+08:00')
    start=b.datetime.fromisoformat(self.manifest['window_start_utc'])
    self.assertEqual(self.end-start.timestamp(),2705)

def early_short_window_refused(self):
    self.save();controller=Proc()
    old_end=b.datetime.fromisoformat('2026-09-24T14:45:05+00:00').timestamp()
    result=self.supervise(controller,Proc(0),old_end)
    self.assertTrue(controller.stdin.closed);self.assertFalse(result['consumer_passed'])

def close_tail_allowed(self):
    self.save()
    self.assertTrue(self.supervise(Proc(0),Proc(0),self.end+1)['consumer_passed'])

ClosingWindow.test_beijing_next_day_and_exact_duration=midnight
ClosingWindow.test_old_short_window_no_longer_success=early_short_window_refused
ClosingWindow.test_close_tail_with_terminal_evidence_allowed=close_tail_allowed
