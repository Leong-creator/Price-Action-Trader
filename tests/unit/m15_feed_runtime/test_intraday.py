"""SDK-free bounded intraday bundle and diagnostic-only lifecycle contracts."""
import copy
from datetime import datetime,timezone
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts.m15_feed_runtime import bootstrap,daily,bridge_lifecycle,run_once
from scripts import run_m15_daily_feed
from tests.unit.m15_feed_runtime import test_daily as daily_fixture

class Intraday(unittest.TestCase):
    def setUp(self):
        self.fixture=daily_fixture.Daily();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.now=datetime.fromisoformat('2026-09-25T16:00:00+00:00')
    def prepare(self,start='2026-09-25T16:15:00+00:00',end='2026-09-25T16:45:05+00:00',**kwargs):
        f=self.fixture
        return daily.prepare_intraday(f.configpath,'2026-09-25',start,end,root=f.root,
            verify_deployment=f.verify,now=self.now,**kwargs)
    def test_partial_bundle_new_identity_preserves_failed_day(self):
        f=self.fixture;old=f.prepare();old_bytes=(f.archive()/'manifest.json').read_bytes()
        r=self.prepare(diagnostic_capture_after_quality_fault=True);archive=Path(r['manifest_path']).parent
        self.assertEqual(archive.name,'2026-09-25-intraday-161500')
        self.assertEqual(archive.parent,f.archive().parent)
        self.assertEqual(old_bytes,(f.archive()/'manifest.json').read_bytes())
        self.assertNotEqual(r['run_id'],old['run_id']);self.assertEqual(r['runtime_deadline_seconds'],1815)
        m=daily.read_json(archive/'manifest.json');s=daily.read_json(archive/'run-spec.json')
        self.assertEqual(m['case'],'intraday-2026-09-25-161500')
        self.assertTrue(m['diagnostic_capture_after_quality_fault']);self.assertFalse(s['full_session_eligible'])
        self.assertEqual(m['layout']['lock'],daily.read_json(f.archive()/'manifest.json')['layout']['lock'])
        self.assertEqual(m['consumer']['output_dir'],str(archive/'consumer-output'))
        self.assertIn('-Intraday-161500',r['task_name'])
        self.assertFalse((archive/'launch-reservation.json').exists())
    def test_future_bounded_regular_window_required_before_creating_directories(self):
        for start,end in [('2026-09-25T15:59:59+00:00','2026-09-25T16:30:00+00:00'),
                          ('2026-09-25T17:00:00+00:00','2026-09-25T18:00:01+00:00'),
                          ('2026-09-25T19:30:00+00:00','2026-09-25T20:00:06+00:00'),
                          ('2026-09-26T16:00:00+00:00','2026-09-26T16:30:00+00:00'),
                          ('2026-09-25T16:15:00+00:00','2026-09-25T16:16:00+00:00')]:
            with self.subTest(start=start,end=end),self.assertRaises(ValueError):self.prepare(start,end)
        self.assertFalse((self.fixture.base/'sessions').exists())
    def test_closed_window_and_normal_day_scope_cannot_be_forged(self):
        r=self.prepare(diagnostic_capture_after_quality_fault=True);m=daily.read_json(r['manifest_path'])
        for key,value in [('full_session_eligible',True),('session_kind','daily'),('session_key','2026-09-25'),
                          ('window_end_utc','2026-09-25T18:00:00+00:00')]:
            bad=copy.deepcopy(m);bad[key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):bootstrap.validate(bad)
        self.assertFalse(m['full_session_eligible'])
    def test_existing_partial_window_is_never_reused(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,'already_exists'):self.prepare()
    def test_daily_cannot_enable_diagnostic_capture(self):
        f=self.fixture
        with self.assertRaisesRegex(ValueError,'diagnostic_capture_scope_invalid'):
            daily.prepare(f.configpath,'2026-09-25',root=f.root,verify_deployment=f.verify,
                diagnostic_capture_after_quality_fault=True)
        self.assertFalse((f.base/'sessions').exists())
    def test_prior_failed_cleanup_is_still_a_start_blocker(self):
        f=self.fixture;f.prepare();f.put('run-once-started.json',{})
        f.put('run-once-result.json',{'exit_verified':False,'credentials_cleaned':False})
        r=self.prepare();m=daily.read_json(r['manifest_path'])
        with self.assertRaisesRegex(run_once.Refusal,'prior_daily_cleanup_unverified'):run_once.verify_predecessor(m)
        f.put('run-once-result.json',{'exit_verified':True,'credentials_cleaned':True})
        run_once.verify_predecessor(m)
    def test_intraday_dispatch_only_its_pinned_task(self):
        f=self.fixture;r=self.prepare();calls=[]
        def invoke(args,**kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0,stdout=json.dumps({'dispatched':True,'task_name':r['task_name'],'sdk_started':False}).encode())
        with patch.object(daily,'verify_source_deployment',f.verify):
            d=daily.launch(f.configpath,'2026-09-25',root=f.root,session_key=r['session_key'],
                now=datetime.fromisoformat('2026-09-25T16:15:01+00:00'),run=invoke)
        self.assertEqual(d['run_id'],r['run_id']);self.assertEqual(len(calls),1)
    def test_cli_diagnostic_flag_never_silently_attaches_to_daily(self):
        with patch('sys.stdout',new_callable=io.StringIO) as out:
            rc=run_m15_daily_feed.main(['prepare','--config','unused','--market-date','2026-09-25','--diagnostic-capture-after-quality-fault'])
        self.assertEqual(rc,4);self.assertIn('intraday_options_require_prepare_intraday',out.getvalue())

    def test_partial_status_uses_own_identity_and_never_reports_quality_pass(self):
        f=self.fixture;r=self.prepare(diagnostic_capture_after_quality_fault=True);a=Path(r['manifest_path']).parent
        output=a/'consumer-output';output.mkdir()
        (output/'summary.json').write_text(json.dumps({'run_id':r['run_id'],
            'first_quality_fault':{'code':'trade_source_delivery_age_exceeded','run_id':r['run_id']},
            'last_error':{'code':'diagnostic_reference_market_data_stalled'},'reason':None}))
        (a/'run-once-result.json').write_text(json.dumps({'run_nonce':r['run_id'],'status':'observed_not_passed',
            'exit_verified':True,'credentials_cleaned':True,'diagnostic_capture_completed':True,
            'bounded_pipeline_passed':False,'reception_window_passed':False,'diagnostic_window_passed':False}))
        value=daily.status(f.configpath,'2026-09-25',root=f.root,session_key=r['session_key'],now=self.now)
        self.assertEqual(value['state'],'failed');self.assertTrue(value['diagnostic_capture_completed'])
        self.assertFalse(value['diagnostic_window_passed']);self.assertFalse(value['full_session_eligible'])
        self.assertEqual(value['last_error'],'trade_source_delivery_age_exceeded')
        self.assertEqual(value['consumer_terminal_error'],'diagnostic_reference_market_data_stalled')
        self.assertEqual(daily.status(f.configpath,'2026-09-25',root=f.root,now=self.now)['state'],'not_prepared')

    def test_controller_real_manifest_reaches_native_boundary_with_intraday_duration(self):
        from scripts.m15_feed_runtime import controller
        from contextlib import ExitStack
        f=self.fixture;r=self.prepare();a=Path(r['manifest_path']).parent;m=daily.read_json(a/'manifest.json')
        root=f.root/'windows';case=root/m['case'];m['layout']['windows_root_native']=str(root)
        (case/'manifest.json').write_text(json.dumps(m))
        class NativeBoundary(Exception):pass
        class StopBeforeWindows:
            def __init__(self):raise NativeBoundary()
        with ExitStack() as stack:
            for name in ('ROOT','PYTHON','SOURCE_SHA256','MAX_RUNTIME_SECONDS'):
                stack.enter_context(patch.object(controller,name,getattr(controller,name)))
            controller.verify_manifest(case,now=datetime.fromisoformat('2026-09-25T16:15:01+00:00'))
            self.assertEqual(controller.MAX_RUNTIME_SECONDS,1815)
            with patch.object(controller,'Win',StopBeforeWindows),self.assertRaises(NativeBoundary):
                controller.run_case(case,seconds=1815)

class CaptureTail(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.manifest={'session_kind':'intraday_diagnostic','diagnostic_capture_after_quality_fault':True,
            'run_nonce':'fixture','window_start_utc':'2026-09-25T16:15:00+00:00','window_end_utc':'2026-09-25T16:45:05+00:00',
            'consumer':{'output_dir':str(self.root)}}
        self.end=datetime.fromisoformat(self.manifest['window_end_utc']).timestamp()
        self.summary={'schema_version':1,'run_id':'fixture','status':'diagnostic_capture_complete',
            'diagnostic_capture_complete':True,'quality_passed':False,'bounded_pipeline_observed':False,
            'first_quality_fault':{'code':'trade_source_delivery_age_exceeded','run_id':'fixture','wire_sequence':50,
                'strategy_evaluations_frozen_at':1,'completed_boundaries_frozen_at':1,
                'partial_builder_state_frozen':True,'strategy_resume_allowed':False},
            'strategy_evaluation_count':1,'complete_boundary_count':1,
            'last_watermark':self.manifest['window_end_utc'],
            'diagnostic_reference_progress':{symbol+':'+kind:{'received_at':'2026-09-25T16:45:04+00:00',
                'source_event_at':'2026-09-25T16:45:03+00:00','wire_sequence':98}
                for symbol in ('SPY.US','QQQ.US') for kind in ('quote','trade')},
            'strategy_frozen':True,'diagnostic_capture_after_quality_fault':True,'last_error':None,'reason':None,
            'strategy_full_acceptance':False,'full_session_acceptance':False,
            'production_acceptance':False,'account_access':False,'order_access':False,
            'window_start_utc':self.manifest['window_start_utc'],'window_end_utc':self.manifest['window_end_utc'],
            'producer_end_observed':True,'producer_end_sequence':99,'last_consumed_sequence':99,'last_sequence':99}
        self.save()
    def save(self): (self.root/'summary.json').write_text(json.dumps(self.summary))
    def test_capture_is_not_consumer_quality_pass(self):
        self.assertTrue(bridge_lifecycle.diagnostic_capture_completed(self.manifest,5))
        self.assertFalse(bridge_lifecycle.consumer_passed(self.manifest,5))
    def test_missing_eof_scope_or_sequence_never_capture_complete(self):
        for key,value in [('producer_end_observed',False),('last_consumed_sequence',98),('quality_passed',True),('bounded_pipeline_observed',True),('strategy_frozen',False),('last_error',{'code':'wire_sequence_discontinuity'}),
                          ('strategy_full_acceptance',True),('full_session_acceptance',True),('diagnostic_reference_progress',{}),
                          ('strategy_evaluation_count',2),('complete_boundary_count',2),('reason','wire_abnormal_end'),
                          ('first_quality_fault',{'run_id':'wrong','code':'trade_source_delivery_age_exceeded'})]:
            old=self.summary[key];self.summary[key]=value;self.save()
            self.assertFalse(bridge_lifecycle.diagnostic_capture_completed(self.manifest,5));self.summary[key]=old
        self.save();self.manifest['session_kind']='daily'
        self.assertFalse(bridge_lifecycle.diagnostic_capture_completed(self.manifest,5))
    def test_completed_diagnostic_tail_does_not_close_live_windows_pipe(self):
        class Process:
            def __init__(self,codes):self.codes=list(codes);self.returncode=None;self.stdin=io.BytesIO()
            def poll(self):
                value=self.codes.pop(0) if len(self.codes)>1 else self.codes[0];self.returncode=value;return value
            def wait(self,timeout=None):self.returncode=self.codes[-1];return self.returncode
        controller=Process([None,0]);consumer=Process([5])
        result=bridge_lifecycle.supervise(controller,consumer,self.manifest,initial_deadline=10,final_deadline=20,
            now=lambda:self.end,monotonic=lambda:0,sleep=lambda _:None)
        self.assertFalse(controller.stdin.closed);self.assertFalse(result['consumer_passed'])
        self.assertTrue(result['diagnostic_capture_completed']);self.assertIsNone(result['consumer_failure'])
    def test_consumer_flag_only_from_explicit_intraday_manifest(self):
        cfg={'python':'p','script':'s','stream_path':'stream','config':'config','output_dir':'out'}
        with patch.object(bridge_lifecycle,'verify_consumer',return_value=cfg):
            self.assertIn('--diagnostic-capture-after-quality-fault',bridge_lifecycle.command(self.manifest))
            self.manifest['session_kind']='daily'
            with self.assertRaisesRegex(RuntimeError,'diagnostic_capture_scope_invalid'):bridge_lifecycle.command(self.manifest)

    def test_reference_tail_must_be_recent_legal_and_within_terminal_sequence(self):
        row=self.summary['diagnostic_reference_progress']['QQQ.US:trade']
        for key,value in [('received_at','2026-09-25T16:44:34+00:00'),
                          ('source_event_at','2026-09-25T16:45:07+00:00'),('wire_sequence',100)]:
            previous=row[key];row[key]=value;self.save()
            self.assertFalse(bridge_lifecycle.diagnostic_capture_completed(self.manifest,5))
            row[key]=previous

    def test_capture_cross_checks_native_producer_terminal_sequence(self):
        archive=self.root/'archive';archive.mkdir();windows=self.root/'windows';case=windows/'fixture-case';case.mkdir(parents=True)
        (archive/'bridge_lifecycle.py').write_bytes(Path(bridge_lifecycle.__file__).read_bytes())
        producer={'schema_version':1,'run_id':'fixture','status':'window_observed','completed_window':True,
            'reason':None,'production_acceptance':False,'window_start_utc':self.manifest['window_start_utc'],
            'window_end_utc':self.manifest['window_end_utc'],'terminal_sequence':99}
        (case/'summary.json').write_text(json.dumps(producer))
        layout=SimpleNamespace(archive=archive,windows_root=windows)
        safe={'diagnostic_capture_completed':True,'exit_verified':True,'child_exitcode':0,
              'job_active_processes':0,'consumer_exitcode':5}
        with patch.object(run_once,'CASE','fixture-case'):
            self.assertTrue(run_once.diagnostic_capture_completed(self.manifest,layout,safe))
            producer['terminal_sequence']=100;(case/'summary.json').write_text(json.dumps(producer))
            self.assertFalse(run_once.diagnostic_capture_completed(self.manifest,layout,safe))
