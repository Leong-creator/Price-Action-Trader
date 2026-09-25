"""Original-file assessor adversarial tests; never contacts clocks or SDK."""
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from scripts import m15_feed_session_acceptance as a


class SessionAcceptanceTests(unittest.TestCase):
    def test_missing_evidence_cannot_pass_or_grant_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            result = a.evaluate_session(directory, {'run_id': 'test'}, {}, {}, session_spec_sha256='test')
        self.assertFalse(result['normal_full_session_observation_passed'])
        self.assertFalse(result['trading_enabled'])
        self.assertEqual(result['trading_qualification'], 'not_assessed')

    def test_consecutive_exchange_days_not_calendar_days_duplicates_or_gaps(self):
        dates = ['2026-09-24', '2026-09-25', '2026-09-28', '2026-09-29']
        reports = [{'market_date': day, 'run_id': str(i), 'normal_full_session_observation_passed': True}
            for i, day in enumerate(dates[:3])]
        self.assertTrue(a.summarize_consecutive_sessions(reports, trading_dates=dates)['three_consecutive_normal_sessions_observed'])
        self.assertFalse(a.summarize_consecutive_sessions(reports[::2], trading_dates=dates)['three_consecutive_normal_sessions_observed'])
        self.assertFalse(a.summarize_consecutive_sessions(reports+[reports[0]], trading_dates=dates)['three_consecutive_normal_sessions_observed'])
        with self.assertRaises(ValueError):
            a.summarize_consecutive_sessions(reports, trading_dates=dates[::-1])

    def test_clock_original_hash_binding_sampling_and_recomputed_quality(self):
        from scripts import m15_feed_clock as clock
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            opened = datetime(2026, 9, 24, 13, 30, tzinfo=UTC)
            closed = opened+timedelta(minutes=390)
            spec = {'run_id': 'bound-run', 'market_open_utc': opened.isoformat(),
                'market_close_utc': closed.isoformat(), 'window_start_utc': (opened-timedelta(minutes=5)).isoformat(),
                'window_end_utc': (closed+timedelta(seconds=5)).isoformat()}
            paths = []
            moment = opened-timedelta(minutes=5)
            while moment < closed:
                paths.append(self.clock_sample(root, len(paths), moment, spec, clock,
                    'startup' if not paths else 'periodic'))
                moment += timedelta(seconds=1800)
            paths.append(self.clock_sample(root, len(paths), closed+timedelta(seconds=10), spec, clock, 'final'))
            evidence = {'assessments': [str(p) for p in paths]}
            self.assertTrue(a.verify_clock_evidence(evidence, spec, 'spec-hash')['passed'])
            self.assertFalse(a.verify_clock_evidence({'assessments': evidence['assessments'][1:]}, spec, 'spec-hash')['passed'])
            self.assertFalse(a.verify_clock_evidence({'assessments': evidence['assessments'][:2]+evidence['assessments'][3:]}, spec, 'spec-hash')['passed'])
            self.assertFalse(a.verify_clock_evidence(evidence, spec, 'different-manifest')['passed'])
            raw_file = paths[1].parent/'windows-ntp.json'
            raw = a.read_json(raw_file)
            raw['samples'][0]['offset_seconds'] = 1
            raw_file.write_text(json.dumps(raw))
            failed = a.verify_clock_evidence(evidence, spec, 'spec-hash')
            self.assertIn('clock_raw_binding_or_hash_mismatch', failed['failures'])
            self.assertIn('clock_quality_failed', failed['failures'])

    def clock_sample(self, root, index, moment, spec, clock, checkpoint):
        directory = root/str(index); directory.mkdir()
        binding = {'run_id': spec['run_id'], 'run_spec_sha256': 'spec-hash',
            'window_start_utc': spec['window_start_utc'], 'window_end_utc': spec['window_end_utc'],
            'checkpoint': checkpoint, 'scheduled_elapsed_seconds': index*1800}
        metadata = {'measurement_id': str(index), 'run_binding': binding}
        windows = {'platform': 'win32', 'wall_clock_continuous': True, 'samples': [
            {'host': host, 'valid': True, 'offset_seconds': .01, 'roundtrip_seconds': .02}
            for host in clock.HOSTS], **metadata}
        cross = {'wall_clock_continuous': True, 'selected': {
            'valid': True, 'offset_seconds': .01, 'roundtrip_seconds': .02}, **metadata}
        for name, value in (('windows-ntp.json', windows), ('windows-wsl-handshake.json', cross)):
            (directory/name).write_text(json.dumps(value))
        assessment = clock.assess_time_quality(windows, cross)
        assessment.update(metadata, started_at=moment.isoformat(), finished_at=(moment+timedelta(seconds=1)).isoformat(),
            raw_sha256={name: a.sha(directory/name) for name in ('windows-ntp.json', 'windows-wsl-handshake.json')})
        path = directory/'assessment.json'; path.write_text(json.dumps(assessment))
        return path


if __name__ == '__main__':
    unittest.main()
