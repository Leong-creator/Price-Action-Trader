"""Offline fake-credential/fake-guardian tests; no Windows process or SDK."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
from unittest.mock import patch
import unittest


spec = importlib.util.spec_from_file_location('run_once_under_test', Path(__file__).resolve().parents[3]/'scripts/m15_feed_runtime/run_once.py')
r = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r
spec.loader.exec_module(r)


class RunOnceTests(unittest.TestCase):
    def setUp(self):
        r.CASE='daily-2026-09-25'
        r.EXPECTED_WINDOW=('2026-09-25T13:15:00+00:00','2026-09-25T13:16:00+00:00','2026-09-25T20:00:05+00:00')
        acceptance=patch.object(r,'write_acceptance');acceptance.start();self.addCleanup(acceptance.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        b = Path(self.tmp.name)
        for n in ('archive', 'windows', 'home', 'winhome', 'states', 'cache', 'base'):
            (b/n).mkdir()
        (b/'winhome/.config').mkdir()
        self.layout = r.Layout(archive=b/'archive', windows_root=b/'windows', source_home=b/'home',
                              windows_home_mnt=b/'winhome', windows_home='Z:\\fake', win_root='Z:\\fake-root',
                              lock=b/'cache/lock', fence=b/'cache/fence', transfer=b/'transfer.json', state_root=b/'states', base_python_root=b/'base')
        self.layout.lock.touch()
        (self.layout.windows_root/r.CASE).mkdir()
        self.manifest = {'schema': 2, 'market_date':'2026-09-25','case': r.CASE, 'run_nonce': 'offline-only-nonce-0000001',
                         **dict(zip(('window_start_utc', 'latest_start_utc', 'window_end_utc'), r.EXPECTED_WINDOW)),
                         'runner': {'integrity_files': [], 'protected_states': [], 'base_integrity_files': []}}
        for name in ('python.exe', 'python314.dll'):
            p = self.layout.base_python_root/name
            p.write_text('fake offline base')
            self.manifest['runner']['base_integrity_files'].append({'path': str(p), 'sha256': r.digest(p)})
        for name, text in [('run_once.py', 'test fixture'), ('guardian.py', 'def configure(*args): return None\ndef verify_inputs(*args): return None\n'), ('clock_preflight.py', '# fake'), ('bootstrap.py', '# fake'), ('m15_feed_clock.py', '# fake'), ('time_monitor.py', '# fake'), ('bridge_lifecycle.py', '# fake'), ('daemon_launch.py', '# fake'), ('launch_host.py', '# fake')]:
            p = self.layout.archive/name
            p.write_text(text)
            self.manifest['runner']['integrity_files'].append({'relative_path': name, 'sha256': r.digest(p)})
        receipt=self.layout.archive/'deployment.json';receipt.write_text('{}')
        self.manifest['runner'].update(deployment_receipt_path=str(receipt),deployment_receipt_sha256=r.digest(receipt))
        for name in r.STATE_NAMES:
            p = self.layout.state_root/name
            p.write_text('protected fake state\n')
            self.manifest['runner']['protected_states'].append({'name': name, 'sha256': r.digest(p)})
        self.token_rel = '.longbridge/openapi/tokens/fake-client'
        self.client_rel = '.config/price-action-trader/longbridge_sdk_client_id'
        for rel in (self.token_rel, self.client_rel):
            (self.layout.source_home/rel).parent.mkdir(parents=True, exist_ok=True)
        self.token = {'client_id': 'fake-client', 'access_token': 'offline-fake-secret', 'refresh_token': 'offline-fake-refresh',
                      'expires_at': int(r.stamp(r.EXPECTED_WINDOW[2]) + 7200)}
        (self.layout.source_home/self.token_rel).write_text(json.dumps(self.token))
        (self.layout.source_home/self.client_rel).write_text('fake-client')
        self.layout.transfer.write_text(json.dumps({'files': [{'relative_path': rel} for rel in (self.token_rel, self.client_rel)],
                                                     'created_private_roots': ['.longbridge', '.config/price-action-trader']}))
        self.manifest['runner']['credential_transfer_sha256'] = r.digest(self.layout.transfer)
        self.now = r.stamp(r.EXPECTED_WINDOW[0]) + 2
        self.calls = 0
        predecessor=patch.object(r, 'verify_predecessor'); predecessor.start(); self.addCleanup(predecessor.stop)

    def write_manifest(self):
        p = self.layout.archive/'manifest.json'
        p.write_text(json.dumps(self.manifest))
        return p, r.digest(p)

    def make_dirs(self, owner, layout):
        dirs = {'.longbridge', '.longbridge/openapi', '.longbridge/openapi/tokens', '.config/price-action-trader'}
        for rel in sorted(dirs, key=lambda p: (len(Path(p).parts), p)):
            (layout.windows_home_mnt/rel).mkdir()
            owner['created_directories'].append(rel)
        r.save(layout.archive/'credential-ownership.private.json', owner, update=True)

    def invoke(self, manifest, fd):
        self.calls += 1
        self.assertGreaterEqual(fd, 0)
        self.assertTrue((self.layout.windows_home_mnt/self.token_rel).is_file())
        return {'status': 'completed', 'exit_verified': True, 'child_exited': True, 'job_active_processes': 0}

    def run_case(self, **kw):
        path, sha = self.write_manifest()
        return r.run_once(path, sha, layout=self.layout, now=lambda: self.now,
                          make_dirs=kw.pop('make_dirs', self.make_dirs), invoke=kw.pop('invoke', self.invoke),
                          summarize=kw.pop('summarize', lambda *args: True), check_clock=kw.pop('check_clock', lambda *args: {'reception_allowed': True, 'quality_passed': True}), **kw)

    def test_clock_unproven_allows_reception_but_never_passes(self):
        result=self.run_case(check_clock=lambda *args: {'reception_allowed':True,'quality_passed':False,'quality_reason':'clock_alignment_unproven'})
        self.assertEqual(self.calls,1)
        self.assertTrue(result['reception_window_passed'])
        self.assertFalse(result['diagnostic_window_passed'])
        self.assertTrue(result['received_for_diagnosis_only'])
        self.assertEqual(result['status'],'observed_not_passed')
        self.assertTrue((self.layout.archive/'launch-clock-assessment.json').exists())

    def test_clock_reason_code_preserved_without_exception_message(self):
        def reject(*args): raise RuntimeError('clock_no_valid_sample')
        result=self.run_case(check_clock=reject)
        self.assertEqual(result['failure_phase'],'clock_preflight')
        self.assertEqual(result['error_code'],'clock_no_valid_sample')
        self.assertFalse(result['sdk_started'])
        self.assertEqual(self.calls,0)

    def test_unknown_clock_exception_is_not_exposed(self):
        def reject(*args): raise RuntimeError('secret_token_do_not_print')
        result=self.run_case(check_clock=reject)
        self.assertEqual(result['error_code'],'clock_preflight_exception')
        self.assertNotIn('secret_token',json.dumps(result))
        self.assertEqual(self.calls,0)

    def test_clock_subprocess_timeout_keeps_safe_code(self):
        def reject(*args): raise subprocess.TimeoutExpired('secret_command',15,output='secret_payload')
        result=self.run_case(check_clock=reject)
        self.assertEqual(result['error_code'],'clock_query_timeout')
        self.assertNotIn('secret_',json.dumps(result))
        self.assertEqual(self.calls,0)

    def test_clock_failure_refuses_before_credentials_or_sdk(self):
        def reject(*a): raise RuntimeError('clock_alignment_unproven')
        result=self.run_case(check_clock=reject)
        self.assertFalse(result['sdk_started'])
        self.assertEqual(self.calls,0)
        self.assertFalse((self.layout.archive/'run-once-started.json').exists())
        self.assertFalse((self.layout.windows_home_mnt/'.longbridge').exists())

    def test_before_window_never_opens_lock_or_copies(self):
        self.now -= 10
        self.layout.lock.unlink()
        result = self.run_case()
        self.assertEqual(result['error'], 'outside_launch_window')
        self.assertFalse(self.layout.lock.exists())
        self.assertFalse((self.layout.archive/'run-once-started.json').exists())
        self.assertEqual(self.calls, 0)

    def test_after_window_refused(self):
        self.now = r.stamp(r.EXPECTED_WINDOW[1]) + 1
        self.assertEqual(self.run_case()['error'], 'outside_launch_window')
        self.assertEqual(self.calls, 0)

    def test_changed_manifest_refused_without_copy(self):
        path, _ = self.write_manifest()
        result = r.run_once(path, '0'*64, layout=self.layout, now=lambda: self.now)
        self.assertEqual(result['error'], 'manifest_hash_mismatch')

    def test_competing_lock_refused(self):
        with self.layout.lock.open('r+') as fd:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_case()
        self.assertEqual(result['error'], 'BlockingIOError')
        self.assertEqual(self.calls, 0)

    def test_legacy_windows_fence_refuses_new_root(self):
        legacy=self.layout.archive/'legacy-fence.json';legacy.write_text('old unresolved run')
        self.manifest['layout']={'additional_windows_fences':[str(legacy)]}
        result=self.run_case()
        self.assertEqual(result['error'],'legacy_windows_fence_exists')
        self.assertEqual(self.calls,0)
        self.assertFalse((self.layout.windows_home_mnt/self.token_rel).exists())

    def test_existing_fence_refused(self):
        self.layout.fence.write_text('existing')
        self.assertEqual(self.run_case()['error'], 'active_fence_exists')

    def test_integrity_failure_before_credentials(self):
        self.manifest['runner']['integrity_files'][0]['sha256'] = '0'*64
        self.assertEqual(self.run_case()['error'], 'runner_integrity_mismatch')
        self.assertFalse((self.layout.archive/'credential-ownership.private.json').exists())

    def test_old_state_mismatch_refused(self):
        (self.layout.state_root/r.STATE_NAMES[0]).write_text('changed')
        self.assertEqual(self.run_case()['error'], 'protected_state_changed_before_start')

    def test_existing_windows_root_not_overwritten(self):
        root = self.layout.windows_home_mnt/'.longbridge'
        root.mkdir(); (root/'unknown').write_text('user data')
        result = self.run_case()
        self.assertEqual(result['error'], 'windows_credential_root_already_exists')
        self.assertEqual((root/'unknown').read_text(), 'user data')
        self.assertEqual(self.calls, 0)

    def test_expired_credentials_never_copied(self):
        self.token['expires_at'] = int(r.stamp(r.EXPECTED_WINDOW[2]) + 3599)
        (self.layout.source_home/self.token_rel).write_text(json.dumps(self.token))
        result = self.run_case()
        self.assertEqual(result['error'], 'credential_expiry_insufficient')
        self.assertFalse((self.layout.windows_home_mnt/'.longbridge').exists())

    def test_success_archives_then_cleans_only_owned_files(self):
        result = self.run_case()
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['credentials_cleaned'])
        self.assertTrue(result['protected_states_unchanged'])
        self.assertTrue(result['original_credentials_unchanged'])
        self.assertFalse((self.layout.windows_home_mnt/'.longbridge').exists())
        self.assertTrue((self.layout.windows_home_mnt/'.config').is_dir())
        saved = list((self.layout.archive/'credential-copies.private').iterdir())
        self.assertEqual(len(saved), 2)
        for p in saved:
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('offline-fake-secret', json.dumps(result))

    def test_unconfirmed_exit_keeps_credentials(self):
        def invoke(*args):
            return {'status': 'failed', 'exit_verified': False, 'child_exited': False, 'job_active_processes': 1}
        result = self.run_case(invoke=invoke)
        self.assertTrue(result['credentials_retained_exit_unverified'])
        self.assertTrue((self.layout.windows_home_mnt/self.token_rel).exists())

    def test_guardian_exception_redacted_and_keeps_credentials(self):
        def invoke(*args):
            raise ValueError('offline-fake-secret')
        result = self.run_case(invoke=invoke)
        self.assertEqual(result['error'], 'ValueError')
        self.assertIsNone(result['sdk_started'])
        self.assertTrue(result['credentials_retained_exit_unverified'])
        self.assertNotIn('offline-fake-secret', json.dumps(result))

    def test_changed_copy_not_deleted(self):
        def invoke(manifest, fd):
            result = self.invoke(manifest, fd)
            (self.layout.windows_home_mnt/self.token_rel).write_text('unknown new content')
            return result
        result = self.run_case(invoke=invoke)
        self.assertEqual(result['cleanup_error'], 'credential_copy_changed_preserved')
        self.assertEqual((self.layout.windows_home_mnt/self.token_rel).read_text(), 'unknown new content')

    def test_original_change_reported_without_rewrite(self):
        def invoke(manifest, fd):
            result = self.invoke(manifest, fd)
            (self.layout.source_home/self.client_rel).write_text('another-client')
            return result
        result = self.run_case(invoke=invoke)
        self.assertFalse(result['original_credentials_unchanged'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual((self.layout.source_home/self.client_rel).read_text(), 'another-client')

    def test_expired_start_after_setup_cleans_without_guardian(self):
        def make(owner, layout):
            self.make_dirs(owner, layout)
            self.now = r.stamp(r.EXPECTED_WINDOW[1]) + 1
        result = self.run_case(make_dirs=make)
        self.assertEqual(result['error'], 'outside_launch_window_after_credentials')
        self.assertTrue(result['credentials_cleaned'])
        self.assertEqual(self.calls, 0)

    def test_second_attempt_never_reuses_case(self):
        self.assertEqual(self.run_case()['status'], 'completed')
        self.assertEqual(self.run_case()['error'], 'run_already_used')
        self.assertEqual(self.calls, 1)

    def test_base_interpreter_drift_refused(self):
        (self.layout.base_python_root/'python314.dll').write_text('changed')
        self.assertEqual(self.run_case()['error'], 'base_python_changed')

    def test_transfer_drift_refused(self):
        self.layout.transfer.write_text('{}')
        self.assertEqual(self.run_case()['error'], 'credential_transfer_changed')

    def test_exit_zero_does_not_pass_window(self):
        result = self.run_case(summarize=lambda *args: False)
        self.assertEqual(result['status'], 'observed_not_passed')
        self.assertFalse(result['diagnostic_window_passed'])
        self.assertTrue(result['credentials_cleaned'])

    def summary_fixture(self):
        folder=self.layout.archive/r.CASE;folder.mkdir()
        (self.layout.archive/'bridge_lifecycle.py').write_text((Path(__file__).resolve().parents[3]/'scripts/m15_feed_runtime/bridge_lifecycle.py').read_text())
        output=self.layout.archive/'consumer-output';output.mkdir()
        self.manifest['consumer']={'output_dir':str(output)}
        safe={'consumer_passed':True,'consumer_exitcode':0}
        (self.layout.archive/'guardian-result.json').write_text(json.dumps(safe))
        s={'run_id':self.manifest['run_nonce'],'producer_end_observed':True,'bounded_pipeline_observed':True,'reason':None,'complete_boundary_count':3,'strategy_evaluation_count':21}
        s.update(schema_version=1,status='window_observed',window_start_utc=self.manifest['window_start_utc'],window_end_utc=self.manifest['window_end_utc'],producer_end_sequence=99,last_sequence=99,all_expected_boundaries_observed=True,expected_complete_boundary_count=3,production_acceptance=False,account_access=False,order_access=False)
        (output/'summary.json').write_text(json.dumps(s))
        p=folder/'summary.json'
        summary={'run_id':self.manifest['run_nonce'],'status':'window_observed','completed_window':True,'reason':None}
        summary.update(schema_version=1,window_start_utc=self.manifest['window_start_utc'],window_end_utc=self.manifest['window_end_utc'],terminal_sequence=99,production_acceptance=False)
        p.write_text(json.dumps(summary))
        return p,summary,s

    def test_bridge_evidence_passes(self):
        self.summary_fixture();self.assertTrue(r.diagnostic_passed(self.manifest,self.layout))

    def test_bridge_missing_producer_summary_fails(self):
        p,_,_=self.summary_fixture();p.unlink();self.assertFalse(r.diagnostic_passed(self.manifest,self.layout))

    def test_bridge_wrong_producer_nonce_fails(self):
        p,s,_=self.summary_fixture();s['run_id']='other';p.write_text(json.dumps(s));self.assertFalse(r.diagnostic_passed(self.manifest,self.layout))

    def test_bridge_no_terminal_eof_fails(self):
        _,_,s=self.summary_fixture();s['producer_end_observed']=False
        (self.layout.archive/'consumer-output/summary.json').write_text(json.dumps(s))
        self.assertFalse(r.diagnostic_passed(self.manifest,self.layout))

    def test_bridge_guardian_failure_fails(self):
        self.summary_fixture()
        (self.layout.archive/'guardian-result.json').write_text(json.dumps({'consumer_passed':False,'consumer_exitcode':0}))
        self.assertFalse(r.diagnostic_passed(self.manifest,self.layout))

    def test_directory_helper_timeout_reports_incomplete_cleanup(self):
        f = self
        def helper(*a, **kw):
            (f.layout.windows_home_mnt / '.longbridge').mkdir()
            raise subprocess.TimeoutExpired('fake helper', 20)
        with patch.object(r.subprocess, 'run', helper):
            result = f.run_case(make_dirs=r.create_private_directories)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue((f.layout.windows_home_mnt / '.longbridge').exists())
        self.assertFalse(result['credentials_cleaned'])
        self.assertEqual(result['cleanup_error'], 'credential_cleanup_incomplete')
        self.assertEqual(json.loads(self.layout.fence.read_text())['state'],'credential_cleanup_incomplete')
        self.assertEqual(f.calls, 0)

    def test_short_write_archives_and_removes_owned_incomplete_credential(self):
        f = self
        original_fdopen = r.os.fdopen
        target = f.layout.windows_home_mnt / f.token_rel
        class PartialWriter:
            def __init__(self, wrapped): self.wrapped = wrapped
            def __enter__(self): return self
            def __exit__(self, *args): return self.wrapped.__exit__(*args)
            def write(self, data):
                self.wrapped.write(data[:24]); self.wrapped.flush()
                raise OSError('injected fake disk failure')
            def __getattr__(self, name): return getattr(self.wrapped, name)
        def fdopen(fd, mode, *a, **kw):
            import os
            is_target = mode == 'wb' and os.readlink('/proc/self/fd/%d' % fd) == str(target)
            handle = original_fdopen(fd, mode, *a, **kw)
            return PartialWriter(handle) if is_target else handle
        with patch.object(r.os, 'fdopen', fdopen): result = f.run_case()
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('cleanup_error', result)
        self.assertFalse(target.exists())
        self.assertEqual((f.layout.archive/'credential-copies.private/credential-0.private').stat().st_size, 24)
        self.assertTrue(result['credentials_cleaned'])
        self.assertEqual(f.calls, 0)

    def test_missing_error_fields_rejected(self):
        f = self
        path, summary, _ = f.summary_fixture()
        del summary['reason']
        path.write_text(json.dumps(summary))
        self.assertFalse(r.diagnostic_passed(f.manifest, f.layout))

    def test_malformed_symbol_row_returns_false(self):
        f = self
        path, summary, _ = f.summary_fixture()
        summary['completed_window'] = 'true'
        path.write_text(json.dumps(summary))
        self.assertFalse(r.diagnostic_passed(f.manifest, f.layout))

    def test_cleanup_precedes_large_evidence_archive(self):
        original=r.archive_case
        def archive(layout):
            self.assertFalse((layout.windows_home_mnt/self.token_rel).exists())
            return original(layout)
        with patch.object(r,'archive_case',side_effect=archive):
            self.assertTrue(self.run_case()['credentials_cleaned'])

    def test_archive_failure_still_cleans_known_credential_after_exit(self):
        f = self
        with patch.object(r, 'archive_case', side_effect=OSError('fake archive full')):
            result = f.run_case()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['exit_verified'])
        self.assertTrue(result['credentials_cleaned'])
        self.assertFalse((f.layout.windows_home_mnt / f.token_rel).exists())

    def test_incomplete_copy_replacement_is_preserved(self):
        owner = r.plan_credentials(self.manifest, self.layout, r.stamp(r.EXPECTED_WINDOW[2]))
        r.save(self.layout.archive/'credential-ownership.private.json', owner)
        self.make_dirs(owner, self.layout)
        target = self.layout.windows_home_mnt/self.token_rel
        target.write_bytes(b'fake partial')
        original = target.stat()
        owner['files'][0].update(copied=True, copy_complete=False,
                                created_file_identity=[original.st_dev, original.st_ino])
        target.rename(target.with_name('held-original'))
        target.write_bytes(b'unknown replacement')
        with self.assertRaisesRegex(r.Refusal, 'credential_copy_changed_preserved'):
            r.cleanup_credentials(owner, self.layout, allow_incomplete=True)
        self.assertEqual(target.read_bytes(), b'unknown replacement')

    def test_partial_copy_not_removed_after_guardian_invocation(self):
        def invoke(manifest, fd):
            result = self.invoke(manifest, fd)
            (self.layout.windows_home_mnt/self.token_rel).write_bytes(b'changed')
            return result
        result = self.run_case(invoke=invoke)
        self.assertFalse(result['credentials_cleaned'])
        self.assertEqual(result['cleanup_error'], 'credential_copy_changed_preserved')


if __name__ == '__main__':
    unittest.main()

class CompletionExport(unittest.TestCase):
    def test_preserves_raw_results_and_passes_spec_sha(self):
        with tempfile.TemporaryDirectory() as raw:
            a=Path(raw);repo=a/'repo';(repo/'scripts').mkdir(parents=True)
            case=a/'case';case.mkdir();consumer=a/'consumer';consumer.mkdir()
            for path,data in ((a/'guardian-result.json',{'exit_verified':True}),(case/'summary.json',{'terminal_sequence':123}),
                              (consumer/'summary.json',{'producer_end_sequence':123}),(a/'run-spec.json',{'run_id':'fixture'}),
                              (a/'clock-evidence.json',{'assessments':['original-path']})):
                path.write_text(json.dumps(data))
            evaluator=repo/'scripts/m15_feed_session_acceptance.py'
            evaluator.write_text("def evaluate_session(directory,spec,completion,clock,*,session_spec_sha256):\n assert completion['producer']['terminal_sequence']==123\n assert clock['assessments']==['original-path']\n return {'normal_full_session_observation_passed':False,'bound_sha':session_spec_sha256}\n")
            manifest={'layout':{'repo_root':str(repo)},'consumer':{'output_dir':str(consumer),'integrity_files':[{'path':str(evaluator),'sha256':r.digest(evaluator)}]}}
            layout=type('Layout',(),{'archive':a,'fence':a/'fence','windows_root':a/'windows'})()
            result={'exit_verified':True,'credentials_cleaned':True}
            with patch.object(r,'CASE','case'):r.write_acceptance(manifest,layout,result)
            self.assertEqual(json.loads((a/'completion.json').read_text())['run_once'],result)
            self.assertEqual(json.loads((a/'feed_session_acceptance.json').read_text())['bound_sha'],r.digest(a/'run-spec.json'))

class BoundedArchive(unittest.TestCase):
    def test_multichunk_evidence_preserves_exact_hash_without_whole_file_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp);source=a/'source';target=a/'target'
            data=b'1234567'*(1024*1024)
            source.write_bytes(data)
            with patch.object(r,'read_regular',side_effect=AssertionError('whole-file read forbidden')):
                sha=r.copy_evidence_stream(source,target)
                self.assertEqual(r.stream_digest(source),sha)
                self.assertEqual(r.stream_digest(target),sha)
            self.assertEqual(sha,hashlib.sha256(data).hexdigest())
            with self.assertRaises(FileExistsError):r.copy_evidence_stream(source,target)
