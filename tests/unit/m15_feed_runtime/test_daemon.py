import importlib.util,json,os,signal,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('test_daemon_module',Path(__file__).resolve().parents[3]/'scripts/m15_feed_runtime/daemon_launch.py')
d=importlib.util.module_from_spec(spec);sys.modules[spec.name]=d;spec.loader.exec_module(d)

class Signals(unittest.TestCase):
    def setUp(self):d._PENDING.clear();d._STOP=False;d._LOG=None
    def tearDown(self):d._PENDING.clear();d._STOP=False
    def test_signal_latch_repeated_calls(self):
        d.signal_handler(signal.SIGTERM,None)
        with patch.object(d,'event') as record:
            for _ in range(5):self.assertTrue(d.stop_requested())
        self.assertEqual(record.call_count,1)
    def test_second_signal_also_recorded(self):
        with patch.object(d,'event') as record:
            d.signal_handler(signal.SIGHUP,None);self.assertTrue(d.stop_requested())
            d.signal_handler(signal.SIGINT,None);self.assertTrue(d.stop_requested())
        self.assertEqual(record.call_count,2)
    def test_no_signal_no_cancel(self):self.assertFalse(d.stop_requested())
    def test_identity_matches_proc(self):
        value=d.identity();self.assertEqual(value['pid'],os.getpid());self.assertGreater(value['proc_start_ticks'],0)

class Launch(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_duplicate_reservation_refuses_before_fork(self):
        d.save_new(self.root/'launch-reservation.json',{})
        with patch.object(d.os,'fork') as fork,self.assertRaises(FileExistsError):d.detach(self.root,'run','sha',lambda:0)
        fork.assert_not_called()
    def test_ack_timeout_retains_reservation(self):
        with patch.object(d.os,'fork',return_value=123),patch.object(d.select,'select',return_value=([],[],[])),self.assertRaisesRegex(RuntimeError,'ack_timeout'):
            d.detach(self.root,'run','sha',lambda:0)
        self.assertTrue((self.root/'launch-reservation.json').exists())
    def test_bad_ack_retains_reservation(self):
        with patch.object(d.os,'fork',return_value=123),patch.object(d.select,'select',return_value=([99],[],[])),patch.object(d.os,'read',return_value=b'{"ready":false}'),self.assertRaisesRegex(RuntimeError,'ack_invalid'):
            d.detach(self.root,'run','sha',lambda:0)
        self.assertTrue((self.root/'launch-reservation.json').exists())
if __name__=='__main__':unittest.main()

class HostProof(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        d._PENDING.clear();d._STOP=False;d._LOG=None
        from datetime import datetime,timezone,timedelta
        now=datetime.now(timezone.utc)
        self.proof={'run_nonce':'fixture','manifest_sha256':'sha','host_exit_verified':True,'host_exitcode':0,'daemon_pid':os.getpid(),'daemon_proc_start_ticks':d.identity()['proc_start_ticks'],'host_pid':123,'wrapper_pid':456,'host_exited_at':now.isoformat()}
        d.save_new(self.root/'host-spawned.json',{'host_pid':123,'wrapper_pid':456,'run_nonce':'fixture','manifest_sha256':'sha'})
        d.save_new(self.root/'daemon-started.json',{'launch_requested_at':(now-timedelta(seconds=1)).isoformat()})
    def test_valid_proof(self):
        d.save_new(self.root/'host-exit-proof.json',self.proof)
        self.assertEqual(d.wait_host_exit(self.root,'fixture','sha')['host_pid'],123)
    def test_killed_host_never_production_passes(self):
        self.proof['host_exitcode']=1;d.save_new(self.root/'host-exit-proof.json',self.proof)
        with self.assertRaisesRegex(RuntimeError,'proof_invalid'):d.wait_host_exit(self.root,'fixture','sha')
    def test_wrong_daemon_identity_refused(self):
        self.proof['daemon_proc_start_ticks']+=1;d.save_new(self.root/'host-exit-proof.json',self.proof)
        with self.assertRaisesRegex(RuntimeError,'proof_invalid'):d.wait_host_exit(self.root,'fixture','sha')
    def test_missing_proof_deadline_without_callback(self):
        with self.assertRaisesRegex(RuntimeError,'no_sdk'):d.wait_host_exit(self.root,'fixture','sha',seconds=0)
    def test_missing_proof_signal_without_callback(self):
        d.signal_handler(signal.SIGTERM,None)
        with self.assertRaisesRegex(RuntimeError,'signal_before'):d.wait_host_exit(self.root,'fixture','sha')
        d._STOP=False

    def test_host_clock_offset_is_audit_not_new_quality_gate(self):
        from datetime import datetime,timezone,timedelta
        self.proof['host_exited_at']=(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat()
        d.save_new(self.root/'host-exit-proof.json',self.proof)
        self.assertEqual(d.wait_host_exit(self.root,'fixture','sha')['host_pid'],123)
