import copy
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts.m15_feed_runtime import daily,bootstrap,daemon_launch

ROOT=Path(__file__).resolve().parents[3]

class Daily(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'repo';self.root.mkdir()
        for folder in ('scripts/m15_feed_runtime','config','.venv-m15/bin','states','windows/venv/Scripts','windows/venv/Lib/site-packages/longbridge','base'):
            (self.root/folder).mkdir(parents=True,exist_ok=True)
        self.config={'schema_version':'m15.daily-feed.v1','production_config':'config/production.json',
            'sessions_root':str(self.base/'sessions'),'windows_environment_receipt':str(self.base/'environment.json'),
            'credential_transfer_plan':str(self.base/'transfer.json'),'source_home':str(self.base/'sourcehome'),
            'distribution':'Ubuntu','user':'fixture','launch_lead_minutes':15,'latest_start_slack_seconds':60,
            'calendar_years':[2026],'early_close_dates':['2026-11-27','2026-12-24'],'task_name_prefix':'Fixture-Daily',
            'account_access':False,'order_access':False,'automatic_retry':False,'automatic_source_fallback':False}
        self.configpath=self.root/'config/daily.json'
        prod=json.loads((ROOT/'config/m15_longbridge_marketdata.production.json').read_text())
        prod['outputs']['output_dir']=str(self.root/'states')
        (self.root/'config/production.json').write_text(json.dumps(prod))
        for name in daily.BUNDLE_MODULES:
            original=ROOT/'scripts/m15_feed_runtime'/name
            (self.root/'scripts/m15_feed_runtime'/name).write_bytes(original.read_bytes() if original.exists() else b'# fixture clock adapter\n')
        for name in ('m15_windows_feed_producer.py','m15_windows_feed_consumer.py','m15_feed_session_acceptance.py','m15_feed_clock.py'):
            (self.root/'scripts'/name).write_text('# fake SDK-free fixture\n')
        for path in ('.venv-m15/bin/python','.venv-m15/pyvenv.cfg','base/python.exe','base/python314.dll','windows/venv/Scripts/python.exe','windows/venv/Lib/site-packages/longbridge/fake.pyd'):
            (self.root/path).write_text('not executable; offline fixture')
        for name in daily.STATE_NAMES:(self.root/'states'/name).write_text('protected')
        env={'windows_root_mnt':str(self.root/'windows'),'windows_root_native':r'X:\fixture',
            'windows_home_mnt':str(self.base/'winhome'),'windows_home_native':r'X:\home',
            'base_python_root_mnt':str(self.root/'base'),'base_python_native':r'X:\python.exe',
            'artifacts':[{'relative_path':p,'sha256':bootstrap.digest(self.root/'windows'/p)} for p in ('venv/Scripts/python.exe','venv/Lib/site-packages/longbridge/fake.pyd')],
            'base_integrity_files':[{'path':str(self.root/'base'/p),'sha256':bootstrap.digest(self.root/'base'/p)} for p in ('python.exe','python314.dll')]}
        daily.write_new(self.base/'environment.json',env)
        self.config['windows_environment_receipt_sha256']=bootstrap.digest(self.base/'environment.json')
        daily.write_new(self.base/'transfer.json',{'files':[{'relative_path':'fake-token'},{'relative_path':'fake-id'}]})
        self.deployment=self.base/'deployment.json';daily.write_new(self.deployment,{'head_sha':'f'*40})
        self.configpath.write_text(json.dumps(self.config))
        self.fakeprod=SimpleNamespace(market_holidays=('2026-12-25',),regular_session_start_time='09:30',regular_session_end_time='16:00',output_dir=self.root/'states')
        p=patch('scripts.m15_longbridge_sdk_runtime_lib.load_config',return_value=self.fakeprod);p.start();self.addCleanup(p.stop)
        p=patch('scripts.m15_longbridge_sdk_runtime_lib.configured_symbols',return_value=tuple(['SPY.US','QQQ.US']+['T%d.US'%i for i in range(145)]));p.start();self.addCleanup(p.stop)
        self.verify=lambda *a:(self.deployment,{'head_sha':'f'*40})

    def prepare(self):return daily.prepare(self.configpath,'2026-09-25',root=self.root,verify_deployment=self.verify)
    def archive(self):return self.base/'sessions/2026-09-25'
    def put(self,name,obj): (self.archive()/name).write_text(json.dumps(obj))
    def test_prepare_copies_exact_sources_and_external_readonly_paths(self):
        receipt=self.prepare();a=self.archive();manifest=daily.read_json(a/'manifest.json')
        self.assertEqual(manifest['case'],'daily-2026-09-25');self.assertEqual(receipt['runtime_deadline_seconds'],24315)
        self.assertEqual((a/'source.py').read_bytes(),(self.root/'scripts/m15_windows_feed_producer.py').read_bytes())
        self.assertEqual(len(manifest['files']),6)
        self.assertFalse((a/'launch-reservation.json').exists())
        self.assertFalse((self.base/'winhome').exists())
        self.assertFalse(daily.read_json(a/'consumer-config.json')['routing']['paper_order_dispatch_enabled'])
        self.assertEqual(receipt['native_action']['execute'],r'X:\python.exe')
        self.assertIn('--manifest-sha256',receipt['native_action']['arguments'])
    def test_same_day_prepare_is_immutable(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,'already_exists'):self.prepare()
    def test_calendar_dst_and_previous_trading_date(self):
        _,day=daily.calendar_for(self.config,'2026-11-02',self.root)
        self.assertEqual(day['market_open_utc'],'2026-11-02T14:30:00+00:00')
        self.assertEqual(day['required_daily_date'],'2026-10-30')
    def test_holiday_weekend_early_close_future_calendar_refused(self):
        for date in ('2026-09-26','2026-12-25','2026-11-27','2027-01-04'):
            with self.subTest(date=date),self.assertRaises(ValueError):daily.calendar_for(self.config,date,self.root)
    def test_environment_mutation_prevents_any_preparation(self):
        (self.root/'windows/venv/Scripts/python.exe').write_text('changed')
        with self.assertRaisesRegex(ValueError,'environment_changed'):self.prepare()
        self.assertFalse(self.archive().exists())
    def test_bootstrap_bad_date_policy_refused(self):
        self.prepare();m=daily.read_json(self.archive()/'manifest.json')
        for key,value in [('window_end_utc','2026-09-25T14:00:05+00:00'),('order_access',True),('automatic_retry',True)]:
            bad=copy.deepcopy(m);bad[key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):bootstrap.validate(bad)
    def test_status_not_prepared_and_missed_start(self):
        now=datetime.fromisoformat('2026-09-25T12:00:00+00:00')
        self.assertEqual(daily.status(self.configpath,root=self.root,now=now)['state'],'not_prepared')
        self.prepare()
        self.assertEqual(daily.status(self.configpath,root=self.root,now=now)['state'],'prepared')
        report=daily.status(self.configpath,root=self.root,now=now+timedelta(hours=2))
        self.assertEqual(report['last_error'],'launch_window_missed');self.assertIsNone(report['data_current'])
    def streaming(self,now):
        r=self.prepare();a=self.archive();self.put('launch-reservation.json',{})
        identity=daemon_launch.identity();identity.update(run_nonce=r['run_id'],manifest_sha256=r['manifest_sha256'])
        self.put('daemon-started.json',identity)
        (a/'consumer-output').mkdir()
        self.live={'run_id':r['run_id'],'phase':'streaming','status':'observing','last_error':None,'observed_at':now.isoformat(),
            'last_processed_at':now.isoformat(),'last_source_receipt':{k:{'received_at':now.isoformat()} for k in ('quote','trade')}}
        self.put('consumer-output/live-status.json',self.live);return r
    def test_status_current_requires_receipt_and_processing_not_counts(self):
        now=datetime.fromisoformat('2026-09-25T14:00:00+00:00');self.streaming(now)
        self.assertTrue(daily.status(self.configpath,root=self.root,now=now)['data_current'])
        self.live['trade_count']=100000000;self.live['last_processed_at']=(now-timedelta(seconds=6)).isoformat();self.put('consumer-output/live-status.json',self.live)
        self.assertFalse(daily.status(self.configpath,root=self.root,now=now)['data_current'])
    def test_status_pid_reuse_is_not_alive(self):
        now=datetime.fromisoformat('2026-09-25T14:00:00+00:00');self.streaming(now)
        r=daily.read_json(self.archive()/'daemon-started.json');r['proc_start_ticks']+=1;self.put('daemon-started.json',r)
        self.assertEqual(daily.status(self.configpath,root=self.root,now=now)['state'],'unknown')
    def test_clock_wrong_run_or_stale_never_current_quality(self):
        now=datetime.fromisoformat('2026-09-25T14:00:00+00:00');receipt=self.streaming(now)
        (self.archive()/'clock/startup').mkdir(parents=True)
        record={'quality_passed':True,'finished_at':now.isoformat(),'run_binding':{'run_id':receipt['run_id'],'run_spec_sha256':bootstrap.digest(self.archive()/'run-spec.json')}}
        self.put('clock/startup/assessment.json',record)
        self.assertTrue(daily.status(self.configpath,root=self.root,now=now)['clock_quality_passed'])
        record['run_binding']['run_id']='different';self.put('clock/startup/assessment.json',record)
        self.assertFalse(daily.status(self.configpath,root=self.root,now=now)['clock_quality_passed'])
        record['run_binding']['run_id']=receipt['run_id'];record['finished_at']=(now-timedelta(seconds=1891)).isoformat();self.put('clock/startup/assessment.json',record)
        self.assertFalse(daily.status(self.configpath,root=self.root,now=now)['clock_quality_passed'])
    def test_completion_exposes_original_cleanup_fields(self):
        now=datetime.fromisoformat('2026-09-25T21:00:00+00:00');r=self.prepare()
        result={'run_nonce':r['run_id'],'status':'completed','exit_verified':True,'credentials_cleaned':True,'bounded_pipeline_passed':True,'clock_quality_passed':True}
        self.put('run-once-result.json',result);self.put('completion.json',{'run_once':result,'exit_fences_cleared':True})
        value=daily.status(self.configpath,root=self.root,now=now)
        self.assertEqual(value['state'],'completed');self.assertTrue(value['completion']['bounded_pipeline_passed'])
        self.assertFalse(value['data_current'])
    def test_launch_only_dispatches_pinned_native_task_and_outside_refuses(self):
        receipt=self.prepare();now=datetime.fromisoformat('2026-09-25T13:15:01+00:00');calls=[]
        def run(args,**kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0,stdout=json.dumps({'dispatched':True,'task_name':receipt['task_name'],'sdk_started':False}).encode())
        with patch.object(daily,'verify_source_deployment',self.verify):
            result=daily.launch(self.configpath,root=self.root,now=now,run=run)
            self.assertFalse(result['sdk_started']);self.assertEqual(len(calls),1)
            self.assertTrue(calls[0][0].endswith('powershell.exe'))
            with self.assertRaisesRegex(ValueError,'outside_launch_window'):daily.launch(self.configpath,root=self.root,now=now+timedelta(minutes=2),run=run)
            self.assertEqual(len(calls),1)

    def test_early_login_waits_without_native_dispatch(self):
        self.prepare()
        with patch.object(daily,'verify_source_deployment',self.verify),patch.object(daily.subprocess,'run') as run:
            result=daily.launch(self.configpath,root=self.root,now=datetime.fromisoformat('2026-09-25T12:00:00+00:00'))
        self.assertEqual(result['status'],'waiting');self.assertFalse(result['dispatched']);run.assert_not_called()

    def test_live_matching_daemon_prevents_second_dispatch_after_window(self):
        now=datetime.fromisoformat('2026-09-25T14:00:00+00:00');self.streaming(now)
        with patch.object(daily,'verify_source_deployment',self.verify),patch.object(daily.subprocess,'run') as run:
            result=daily.launch(self.configpath,root=self.root,now=now)
        self.assertEqual(result['status'],'already_running');run.assert_not_called()

    def test_guardian_full_bundle_hash_verification_without_sdk(self):
        from scripts.m15_feed_runtime import guardian
        self.prepare();m=daily.read_json(self.archive()/'manifest.json');guardian.configure(m)
        window,sha=guardian.verify_inputs(m,self.archive(),self.root/'windows')
        self.assertEqual(window[2]-window[0],24305);self.assertEqual(sha,bootstrap.digest(self.archive()/'manifest.json'))
        (self.root/'scripts/m15_windows_feed_consumer.py').write_text('# changed')
        with self.assertRaisesRegex(RuntimeError,'consumer_source_changed'):guardian.verify_inputs(m,self.archive(),self.root/'windows')
