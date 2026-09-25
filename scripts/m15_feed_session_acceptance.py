"""Read-only, fail-closed full-session evidence assessment; grants no trading access.

Offline tests of this assessor are not actual observed trading sessions. Clock
measurements prove sampled clock quality, not uninterrupted UTC accuracy.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() != timedelta(0):
        raise ValueError('timestamp_not_utc')
    return result


def read_json(path):
    return json.loads(Path(path).read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_lines(path):
    with Path(path).open() as source:
        return [json.loads(line) for line in source if line.strip()]


def evaluate_session(consumer_dir, session_spec, completion, clock_evidence, *, session_spec_sha256):
    """Assess original files and separate feed qualification from account trading.

    The caller provides the hash of the immutable session manifest. Inputs are
    read-only; the CLI writes only the separately requested acceptance report.
    """
    directory = Path(consumer_dir)
    spec = session_spec
    run_id = spec.get('run_id', spec.get('run_nonce'))
    result = {'schema_version': 1, 'run_id': run_id, 'market_date': spec.get('market_date'),
        'session_spec_sha256': session_spec_sha256, 'status': 'not_passed',
        'normal_full_session_observation_passed': False, 'trading_qualification': 'not_assessed',
        'account_access': False, 'order_access': False, 'trading_enabled': False,
        'clock_scope': 'fixed_checkpoint_samples_not_continuous_utc_proof',
        'layers': {}, 'evidence_sha256': {}}
    failures = []
    def require(condition, code):
        if not condition:
            failures.append(code)
    try:
        summary = read_json(directory/'summary.json')
        bars = read_lines(directory/'bar-evidence.jsonl')
        boundaries = read_lines(directory/'boundary-evidence.jsonl')
        decisions = read_lines(directory/'strategy/boundary_decisions.jsonl')
        for name in ('summary.json', 'bar-evidence.jsonl', 'boundary-evidence.jsonl', 'strategy/boundary_decisions.jsonl'):
            result['evidence_sha256'][name] = sha(directory/name)
        opened, closed = stamp(spec['market_open_utc']), stamp(spec['market_close_utc'])
        start, end = stamp(spec['window_start_utc']), stamp(spec['window_end_utc'])
        local_open, local_close = opened.astimezone(ZoneInfo('America/New_York')), closed.astimezone(ZoneInfo('America/New_York'))
        symbols = spec['symbols']
        require(len(symbols) == len(set(symbols)) == 147 and all(s.endswith('.US') for s in symbols), 'universe_not_147_unique')
        require(local_open.date().isoformat() == spec['market_date'] == local_close.date().isoformat()
            and local_open.weekday() < 5, 'market_date_invalid')
        normal = (local_open.strftime('%H:%M:%S') == '09:30:00' and local_close.strftime('%H:%M:%S') == '16:00:00'
                  and closed-opened == timedelta(minutes=390))
        require(normal, 'special_or_non_normal_session_not_78_boundary_qualified')
        require(start <= opened and end >= closed+timedelta(seconds=3)
            and stamp(summary['ready_at']) < opened, 'opening_or_closing_coverage_missing')
        require(summary['run_id'] == run_id and summary['window_start_utc'] == spec['window_start_utc']
            and summary['window_end_utc'] == spec['window_end_utc'] and set(summary['symbols']) == set(symbols), 'consumer_manifest_mismatch')
        require(summary.get('last_error') is None and summary.get('status') == 'window_observed'
            and summary.get('full_session_acceptance') is False and summary.get('order_access') is False,
            'consumer_failed_or_scope_changed')
        require(summary.get('maximum_source_delivery_age_ms') == 2000, 'latency_gate_changed')
        expected_closes = {opened+timedelta(minutes=5*i) for i in range(1,79)}
        expected_pairs = {(symbol.removesuffix('.US'), close) for symbol in symbols for close in expected_closes}
        actual = Counter((row['bar']['symbol'], stamp(row['bar']['bar_close_at'])) for row in bars)
        require(set(actual) == expected_pairs and all(n == 1 for n in actual.values()), 'bar_missing_duplicate_or_unexpected')
        require(summary.get('persisted_bar_count') == summary.get('bar_count') == 11466, 'bar_total_mismatch')
        classifications = Counter()
        bar_sequences = {}
        for row in bars:
            bar = row['bar']; close = stamp(bar['bar_close_at']); formed = stamp(row['formed_at'])
            watermark = stamp(row['watermark']); blocked = bar.get('market_data_blocked_reason', '')
            require(row['run_id'] == run_id and stamp(bar['bar_open_at']) == close-timedelta(minutes=5)
                and stamp(bar['event_time']) == close and bar.get('bar_final') is True, 'bar_identity_invalid')
            require(close+timedelta(seconds=2) <= watermark <= formed <= close+timedelta(seconds=5)
                and formed <= end and stamp(bar['received_at']) == watermark, 'bar_not_realtime_or_late')
            if blocked:
                require(row['classification'] == 'blocked_carry' and row['eligible_for_strategy_input'] is False
                    and bar['source_mode'] == 'official_sdk_no_trade_carry_forward'
                    and set(blocked.split(',')) <= {'no_trade_carry_forward', 'no_price_forming_trade'}
                    and 'no_trade_carry_forward' in blocked, 'carry_classification_invalid')
            else:
                receipt = row['trade_callback_receipts']
                require(row['classification'] == 'price_forming_trade' and row['eligible_for_strategy_input'] is True
                    and bar['source_mode'] == 'official_sdk_push' and receipt is not None
                    and receipt['trade_count'] > 0, 'trade_classification_invalid')
            if row['trade_callback_receipts']:
                receipt = row['trade_callback_receipts']
                require(start <= stamp(receipt['first_received_at']) <= stamp(receipt['last_received_at']) <= formed
                    and receipt['max_callback_to_dequeue_ms'] <= 2000, 'original_receipt_late_or_invalid')
            classifications[row['classification']] += 1
            bar_sequences.setdefault(close, set()).add(row['wire_sequence'])
        require(Counter(stamp(row['bar_close_at']) for row in boundaries) == Counter({c: 1 for c in expected_closes}), 'boundary_missing_or_duplicate')
        previous_seq = 0
        for row in boundaries:
            close = stamp(row['bar_close_at'])
            require(row['run_id'] == run_id and row['accepted'] is True and row['error'] is None
                and row['bar_count'] == 147 and row['strategy_evaluations_after'] == row['strategy_evaluations_before']+1
                and row['wire_sequence'] > previous_seq and bar_sequences.get(close) == {row['wire_sequence']}, 'boundary_judgment_failed')
            require(stamp(row['dequeued_at']) <= stamp(row['judgment_finished_at']) <= close+timedelta(seconds=5), 'strategy_judgment_late')
            previous_seq = row['wire_sequence']
        require(summary.get('complete_boundary_count') == summary.get('expected_complete_boundary_count') == 78
            and summary.get('all_expected_boundaries_observed') is True, 'boundary_summary_mismatch')
        decision_closes = Counter(stamp(c) for row in decisions for c in row['boundary_times'])
        require(decision_closes == Counter({c: 1 for c in expected_closes})
            and summary.get('strategy_evaluation_count') == 78, 'strategy_judgments_missing')
        require(all(row.get('order_access') is False and row.get('runtime_context')
            and 'short_detector_diagnostics' in row for row in decisions), 'actual_detector_evidence_missing')
        require(summary.get('daily_context_row_count') == 8820
            and summary.get('daily_context_validation', {}).get('status') == 'passed'
            and summary.get('strategy_input_coverage_observed') is True, 'daily_context_incomplete')
        for name in ('callback_to_dequeue', 'wire_to_dequeue', 'eligible_trade_source_to_callback'):
            hist = summary['latency_evidence'][name]
            require(hist['count'] > 0 and -2000 <= hist['min'] <= hist['max'] <= 2000
                and sum(n for _, n in hist['histogram_ms_upper_edge']) == hist['count'], 'source_or_queue_latency_invalid')
        result['layers']['feed_and_strategy'] = {'passed': not failures, 'failures': sorted(set(failures)),
            'bar_classifications': dict(classifications), 'normal_boundary_count': 78,
            'actual_bar_count': len(bars), 'actual_strategy_judgments': len(decisions),
            'no_signal_is_allowed': True}
        before = len(failures)
        once, guardian, producer = (completion[k] for k in ('run_once', 'guardian', 'producer'))
        require(once.get('run_nonce') == guardian.get('run_nonce') == producer.get('run_id') == run_id, 'completion_identity_mismatch')
        require(completion.get('consumer') == summary, 'completion_consumer_changed')
        require(once.get('status') == 'completed'
            and all(once.get(k) is True for k in ('bounded_pipeline_passed',
                'reception_window_passed', 'diagnostic_window_passed'))
            and not any(once.get(k) for k in ('error', 'archive_error', 'clock_finalization_error',
                'cleanup_error', 'credentials_retained_exit_unverified')),
            'outer_completion_failed')
        require(guardian.get('status') == 'completed'
            and not any(guardian.get(k) for k in ('error', 'error_type', 'cleanup_error_type')),
            'guardian_completion_failed')
        require(all(once.get(k) is True for k in ('exit_verified', 'credentials_cleaned',
            'protected_states_unchanged', 'original_credentials_unchanged')), 'cleanup_not_verified')
        require(guardian.get('child_exitcode') == guardian.get('consumer_exitcode') == 0
            and guardian.get('job_active_processes') == 0
            and all(guardian.get(k) is True for k in ('child_exited','consumer_exited','exit_verified','consumer_passed'))
            and completion.get('exit_fences_cleared') is True, 'exit_not_verified')
        require(producer.get('terminal_sequence') == summary.get('producer_end_sequence') == summary.get('last_consumed_sequence') == summary.get('last_sequence')
            and summary.get('producer_end_observed') is True and producer.get('completed_window') is True
            and producer.get('reason') is None and producer.get('status') == 'window_observed' and stamp(summary['last_watermark']) == end,
            'terminal_sequence_or_tail_incomplete')
        require(producer.get('window_start_utc') == spec['window_start_utc']
            and producer.get('window_end_utc') == spec['window_end_utc'], 'producer_window_mismatch')
        result['layers']['exit_and_cleanup'] = {'passed': len(failures) == before, 'failures': sorted(set(failures[before:]))}
        clock = verify_clock_evidence(clock_evidence, spec, session_spec_sha256)
        result['layers']['clock'] = clock
        require(clock['passed'], 'clock_evidence_not_passed')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError):
        failures.append('missing_malformed_or_unverifiable_evidence')
    result['failures'] = sorted(set(failures))
    result['normal_full_session_observation_passed'] = not failures
    result['status'] = 'passed_observation_only' if not failures else 'not_passed'
    return result


def verify_clock_evidence(clock_evidence, spec, spec_sha256):
    from scripts.m15_feed_clock import assess_time_quality
    failures, measurements, checkpoints = [], [], []
    expected_binding = {'run_id': spec.get('run_id', spec.get('run_nonce')),
        'run_spec_sha256': spec_sha256, 'window_start_utc': spec['window_start_utc'],
        'window_end_utc': spec['window_end_utc']}
    for path in clock_evidence['assessments']:
        path = Path(path)
        assessment = read_json(path)
        binding = assessment['run_binding']
        if any(binding.get(k) != v for k, v in expected_binding.items()):
            failures.append('clock_binding_mismatch')
        raw = []
        for name in ('windows-ntp.json', 'windows-wsl-handshake.json'):
            file = path.parent/name
            document = read_json(file)
            if (sha(file) != assessment['raw_sha256'][name] or
                    document.get('measurement_id') != assessment['measurement_id'] or
                    document.get('run_binding') != binding):
                failures.append('clock_raw_binding_or_hash_mismatch')
            raw.append(document)
        recomputed = assess_time_quality(*raw)
        if (recomputed.get('quality_passed') is not True or
                assessment.get('quality_passed') is not True or
                assessment.get('maximum_clock_bound_seconds') != .5):
            failures.append('clock_quality_failed')
        started, finished = stamp(assessment['started_at']), stamp(assessment['finished_at'])
        if not started <= finished <= started+timedelta(seconds=90):
            failures.append('clock_measurement_duration_invalid')
        measurements.append((started, finished, assessment['measurement_id']))
        checkpoints.append(binding['checkpoint'])
    if not measurements or len({r[2] for r in measurements}) != len(measurements):
        failures.append('clock_measurements_missing_or_duplicate')
    else:
        opened, closed = stamp(spec['market_open_utc']), stamp(spec['market_close_utc'])
        if checkpoints[0] != 'startup' or measurements[0][1] > opened:
            failures.append('clock_startup_missing_or_after_open')
        if checkpoints[-1] != 'final' or measurements[-1][0] < closed:
            failures.append('clock_final_missing_or_before_close')
        for prior, current in zip(measurements, measurements[1:]):
            if not prior[0] < current[0] <= prior[0]+timedelta(seconds=1890):
                failures.append('clock_periodic_coverage_gap')
    return {'passed': not failures, 'failures': sorted(set(failures)),
        'measurement_count': len(measurements), 'scope': 'startup_periodic_final_samples'}


def summarize_consecutive_sessions(reports, *, trading_dates):
    """Only approved exchange dates supplied by calendar evidence count as adjacent."""
    if trading_dates != sorted(set(trading_dates)):
        raise ValueError('trading_dates_must_be_unique_ordered')
    by_date = {r['market_date']: r for r in reports if r.get('normal_full_session_observation_passed') is True}
    duplicate_dates = len(by_date) != sum(r.get('normal_full_session_observation_passed') is True for r in reports)
    runs = [r.get('run_id') for r in by_date.values()]
    streak = best = 0
    for day in trading_dates:
        streak = streak+1 if day in by_date else 0
        best = max(best, streak)
    qualified = not duplicate_dates and len(runs) == len(set(runs)) and best >= 3
    return {'three_consecutive_normal_sessions_observed': qualified,
        'longest_consecutive_sessions': best, 'trading_qualification': 'not_assessed', 'trading_enabled': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('consumer-dir', 'session-spec', 'completion', 'clock-evidence', 'output'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    result = evaluate_session(args.consumer_dir, read_json(args.session_spec), read_json(args.completion),
        read_json(args.clock_evidence), session_spec_sha256=sha(args.session_spec))
    target = Path(args.output).resolve()
    if target.is_relative_to(ROOT):
        raise ValueError('acceptance_output_must_be_external')
    with target.open('x') as output:
        json.dump(result, output, indent=2, allow_nan=False)
        output.write('\n')
    return 0 if result['normal_full_session_observation_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
