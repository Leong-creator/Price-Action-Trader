"""SDK-free bridge lifecycle checks. Paths and source hashes come from a pinned manifest."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time



def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def read(path):
    path = Path(path)
    require(path.is_absolute() and not path.is_symlink(), 'consumer_path_invalid')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'consumer_file_not_regular')
        return stream.read()


def verify_consumer(manifest):
    cfg = manifest['consumer']
    root=Path(manifest['layout']['archive'])
    stream=Path(manifest['layout']['windows_root_mnt'])/manifest['case']/'stdout.private'
    require(Path(cfg['output_dir']) == root/'consumer-output', 'consumer_output_not_authorized')
    require(Path(cfg['stream_path']) == stream, 'consumer_stream_not_authorized')
    require(Path(cfg['config']) == root/'consumer-config.json', 'consumer_config_not_authorized')
    require(Path(cfg['script']).name == 'm15_windows_feed_consumer.py', 'consumer_entry_invalid')
    require(Path(cfg['python']) == Path(manifest['layout']['repo_root'])/'.venv-m15/bin/python', 'consumer_interpreter_invalid')
    for path, sha in [(cfg['script'], cfg['script_sha256']), (cfg['config'],cfg['config_sha256'])]:
        require(hashlib.sha256(read(path)).hexdigest() == sha, 'consumer_source_changed')
    entries = cfg['integrity_files']
    require(isinstance(entries, list) and len(entries) >= 3, 'consumer_integrity_missing')
    paths = [entry['path'] for entry in entries]
    require(len(set(paths)) == len(paths) and {cfg['python'],cfg['script'],cfg['config']} <= set(paths), 'consumer_integrity_missing')
    for entry in entries:
        require(hashlib.sha256(read(Path(entry['path']).resolve() if entry['path'] == cfg['python'] else entry['path'])).hexdigest() == entry['sha256'], 'consumer_dependency_changed')
    return cfg


def command(manifest):
    c = verify_consumer(manifest)
    return [c['python'], '-B', c['script'], '--stream',c['stream_path'], '--config',c['config'],
            '--output-dir',c['output_dir'], '--run-id',manifest['run_nonce'],
            '--window-start-utc',manifest['window_start_utc'],'--window-end-utc',manifest['window_end_utc']]


def consumer_passed(manifest, returncode):
    """Exit zero without intact matching terminal evidence is failure."""
    try:
        cfg=manifest['consumer']
        s=json.loads(read(Path(cfg['output_dir'])/'summary.json'))
        return (returncode == 0 and s.get('run_id') == manifest['run_nonce']
                and s.get('schema_version') == 1 and s.get('status') == 'window_observed'
                and all(datetime.fromisoformat(s[k]) == datetime.fromisoformat(manifest[k]) for k in ('window_start_utc','window_end_utc'))
                and s.get('producer_end_observed') is True
                and type(s.get('producer_end_sequence')) is int and s['producer_end_sequence'] > 0
                and s.get('last_sequence') == s['producer_end_sequence']
                and s.get('all_expected_boundaries_observed') is True
                and type(s.get('expected_complete_boundary_count')) is int
                and s['expected_complete_boundary_count'] == s.get('complete_boundary_count')
                and s.get('production_acceptance') is False and s.get('account_access') is False and s.get('order_access') is False
                and s.get('bounded_pipeline_observed') is True
                and 'reason' in s and s['reason'] is None
                and type(s.get('complete_boundary_count')) is int and s['complete_boundary_count'] > 0
                and type(s.get('strategy_evaluation_count')) is int and s['strategy_evaluation_count'] > 0)
    except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError):
        return False


def stop_consumer(proc):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    return proc is None or proc.poll() is not None


def supervise(controller, consumer, manifest, *, initial_deadline, final_deadline,
              now=time.time, monotonic=time.monotonic, sleep=time.sleep, clock_monitor=None):
    """Consumer failure closes the controller's existing Windows Job control pipe."""
    end=datetime.fromisoformat(manifest['window_end_utc']).timestamp()
    reason=None
    while controller.poll() is None:
        cancellation = sys.modules.get('pat_launch_state')
        if cancellation is not None and cancellation.stop_requested():
            reason='supervisor_signal_stop'
            break
        if clock_monitor is not None and clock_monitor.poll():
            reason=clock_monitor.failure
            break
        rc=consumer.poll()
        if rc is not None:
            if now() < end or not consumer_passed(manifest, rc):
                reason='consumer_failed_or_incomplete'
                break
        if monotonic() >= initial_deadline or now() > end+15:
            reason='bridge_deadline_exceeded'
            break
        sleep(0.1)
    if reason is not None:
        controller.stdin.close()
        final_deadline = min(final_deadline, monotonic()+10)
    try:
        controller.wait(timeout=max(0, min(final_deadline-monotonic(), end+25-now())))
    except subprocess.TimeoutExpired:
        if not controller.stdin.closed:
            controller.stdin.close()
        raise RuntimeError('windows_exit_not_verified_fence_retained')
    # EOF result should be available before producer exit; allow bounded final flush.
    try:
        consumer.wait(timeout=max(0, min(5, final_deadline-monotonic(), end+25-now())))
    except subprocess.TimeoutExpired:
        reason=reason or 'consumer_exit_deadline'
        stop_consumer(consumer)
    passed = reason is None and consumer_passed(manifest, consumer.returncode)
    if now() > end+25:
        passed=False
        reason=reason or 'bridge_utc_deadline_exceeded'
    return {'consumer_exitcode':consumer.returncode, 'consumer_exited':consumer.poll() is not None,
            'consumer_passed':passed,'consumer_failure':reason if reason else None}
