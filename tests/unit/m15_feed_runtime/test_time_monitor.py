from datetime import datetime
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts.m15_feed_runtime import time_monitor

class FixedClock(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.start=10000.;self.clock=[10001.,501.];self.calls=[]
        self.manifest={'window_start_utc':datetime.fromtimestamp(self.start).isoformat(),'window_end_utc':datetime.fromtimestamp(self.start+3605).isoformat()}
        (self.root/'clock/startup').mkdir(parents=True)
        (self.root/'clock/startup/assessment.json').write_text(json.dumps({'quality_passed':True,'reception_allowed':True}))
        adapter=SimpleNamespace(make_binding=lambda a,c,s:{'checkpoint':c,'scheduled_elapsed_seconds':s})
        p=patch.object(time_monitor,'load',return_value=adapter);p.start();self.addCleanup(p.stop)
        self.monitor=time_monitor.Monitor(self.root,'not-run',self.manifest,now=lambda:self.clock[0],monotonic=lambda:self.clock[1],collect=self.collect)
    def collect(self,python,directory,*,binding):
        self.calls.append(binding);directory.mkdir()
        record={'quality_passed':True,'reception_allowed':True}
        (directory/'assessment.json').write_text(json.dumps(record));return record
    def join(self):
        if self.monitor.thread:self.monitor.thread.join(1)
    def test_fixed_offsets_do_not_drift_with_sample_duration(self):
        self.clock[:]=[11801,2301];self.monitor.poll();self.join()
        self.assertEqual(self.calls[0]['scheduled_elapsed_seconds'],1800)
        self.clock[:]=[13601,4101];self.monitor.poll();self.join()
        self.assertEqual([x['scheduled_elapsed_seconds'] for x in self.calls],[1800,3600])
    def test_poll_is_nonblocking_during_measurement(self):
        entered=threading.Event();release=threading.Event()
        def collect(*args,**kwargs):entered.set();release.wait(2);return self.collect(*args,**kwargs)
        self.monitor.collect=collect;self.clock[1]=2301;self.monitor.poll();self.assertTrue(entered.wait(1))
        self.assertIsNone(self.monitor.poll());self.assertEqual(len(self.calls),0)
        release.set();self.join()
    def test_reception_failure_latches_no_retry(self):
        def collect(*args,**kwargs):r=self.collect(*args,**kwargs);r['reception_allowed']=False;return r
        self.monitor.collect=collect;self.clock[1]=2301;self.monitor.poll();self.join()
        for _ in range(5):self.assertEqual(self.monitor.poll(),'clock_reception_not_allowed')
        self.assertEqual(len(self.calls),1)
    def test_early_failure_no_fake_final_sample(self):
        self.assertEqual(self.monitor.finish()['assessments'],[str(self.root/'clock/startup/assessment.json')])
        self.assertEqual(self.calls,[])
    def test_final_quality_cannot_erase_earlier_bad(self):
        (self.root/'clock/startup/assessment.json').write_text(json.dumps({'quality_passed':False,'reception_allowed':True}))
        self.clock[0]=13606;result=self.monitor.finish()
        self.assertEqual(self.calls[0]['checkpoint'],'final');self.assertFalse(result['quality_passed'])
