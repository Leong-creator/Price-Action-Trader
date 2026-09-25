"""Bounded one-shot Windows observation guardian; never imports an SDK."""
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
import time
from datetime import datetime, timezone

ARCHIVE = ROOT = WIN_ROOT = CASE = FENCE = LOCK = EXPECTED_WINDOW = None
PRODUCTS = ('run_started.json', 'run_result.json', 'stdout.private', 'stderr.private', 'sdk-logs')
EXIT_STATUSES = {'completed', 'failed', 'external_deadline_exceeded', 'control_pipe_closed', 'watchdog_fault'}


def configure(manifest):
    global ARCHIVE, ROOT, WIN_ROOT, CASE, FENCE, LOCK, EXPECTED_WINDOW
    cfg=manifest['layout']
    ARCHIVE=Path(cfg['archive']);ROOT=Path(cfg['windows_root_mnt']);WIN_ROOT=cfg['windows_root_native']
    CASE=manifest['case'];FENCE=Path(cfg['fence']);LOCK=Path(cfg['lock'])
    EXPECTED_WINDOW=tuple(manifest[k] for k in ('window_start_utc','latest_start_utc','window_end_utc'))


def bridge_module(archive):
    spec=importlib.util.spec_from_file_location('verified_bridge_lifecycle', Path(archive)/'bridge_lifecycle.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'timezone_required')
    return parsed.timestamp()


def digest(path):
    require(path.is_file() and not path.is_symlink(), 'regular_file_required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root, relative):
    relative = PurePosixPath(relative)
    require(not relative.is_absolute() and '..' not in relative.parts and str(relative) != '.', 'invalid_relative_path')
    candidate = root.joinpath(*relative.parts)
    require(candidate.resolve().is_relative_to(root.resolve()), 'artifact_outside_root')
    return candidate


def save_new(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as handle:
        json.dump(value, handle, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())


def verify_inputs(manifest, archive, root):
    encoded = (archive/'manifest.json').read_bytes()
    require(json.loads(encoded) == manifest, 'manifest_argument_mismatch')
    require((root/CASE/'manifest.json').read_bytes() == encoded, 'manifest_copy_mismatch')
    require(manifest.get('schema') == 2 and manifest.get('case') == CASE, 'manifest_identity_mismatch')
    nonce = manifest.get('run_nonce')
    require(isinstance(nonce, str) and len(nonce) >= 16, 'run_nonce_missing')
    fields = ('window_start_utc', 'latest_start_utc', 'window_end_utc')
    window = tuple(stamp(manifest[k]) for k in fields)
    require(window == tuple(map(stamp, EXPECTED_WINDOW)), 'unauthorized_market_window')
    require(set(manifest['files']) == {'source.py', 'health.py', 'run-spec.json', 'production-config.json', 'controller.py', 'bootstrap.py'}, 'manifest_file_set_mismatch')
    for name, entry in manifest['files'].items():
        expected = entry['sha256']
        require(digest(inside(archive, entry['archive_name'])) == expected, 'archive_artifact_changed:'+name)
        require(digest(root/CASE/name) == expected, 'windows_artifact_changed:'+name)
    artifacts = manifest['artifacts']
    require(isinstance(artifacts, list) and len(artifacts) >= 2, 'venv_artifacts_missing')
    names = [entry['relative_path'] for entry in artifacts]
    require(len(set(names)) == len(names) and 'venv/Scripts/python.exe' in names, 'venv_interpreter_missing_or_duplicate')
    require(any(name.startswith('venv/Lib/site-packages/longbridge/') and name.endswith('.pyd') for name in names), 'native_sdk_artifact_missing')
    for entry in artifacts:
        require(entry['relative_path'].startswith('venv/'), 'artifact_not_in_venv')
        require(digest(inside(root, entry['relative_path'])) == entry['sha256'], 'venv_artifact_changed')
    bridge_module(archive).verify_consumer(manifest)
    return window, hashlib.sha256(encoded).hexdigest()


def verify_exit(result, proc, manifest, started, now, case, archive, root):
    status = result.get('status')
    files = manifest['files']
    return (proc.poll() is not None
        and status in EXIT_STATUSES
        and proc.returncode == (0 if status == 'completed' else 4)
        and result.get('child_exited') is True
        and result.get('job_active_processes') == 0
        and type(result.get('child_pid')) is int and result['child_pid'] > 0
        and type(result.get('child_exitcode')) is int and result['child_exitcode'] != 259
        and (status != 'completed' or result['child_exitcode'] == 0)
        and not result.get('cleanup_error_type')
        and started <= stamp(result.get('started_at', '1970-01-01T00:00:00+00:00')) <= now
        and result.get('run_nonce') == manifest['run_nonce']
        and result.get('source_sha256') == files['source.py']['sha256']
        and result.get('helper_sha256') == files['health.py']['sha256']
        and result.get('config_sha256') == files['run-spec.json']['sha256']
        and result.get('source_unchanged') is True and result.get('helper_unchanged') is True
        and result.get('all_inputs_unchanged') is True
        and all(stamp(result.get(k, '1970-01-01T00:00:00+00:00')) == stamp(manifest[k])
                for k in ('window_start_utc', 'window_end_utc'))
        and all(digest(case/name) == entry['sha256'] for name, entry in files.items())
        and (case/'manifest.json').read_bytes() == (archive/'manifest.json').read_bytes())


def run_guarded(manifest, *, lock_fd=None, archive=None, root=None, win_root=None,
                fence=None, lock_path=None, popen=subprocess.Popen,
                now=time.time, monotonic=time.monotonic, clock_monitor=None):
    """Private test overrides never exposed by CLI; caller may pass its held global lock fd."""
    configure(manifest)
    archive, root, fence, lock_path = map(Path, (archive or ARCHIVE, root or ROOT, fence or FENCE, lock_path or LOCK))
    win_root=win_root or WIN_ROOT
    window, manifest_sha = verify_inputs(manifest, archive, root)
    start, latest, end = window
    require(start <= now() <= latest, 'outside_launch_window')
    case = root/CASE
    require(not (root/'windows-case-active.json').exists() and not fence.exists(), 'active_probe_fence_exists')
    require(all(not (case/name).exists() for name in PRODUCTS), 'case_already_used')
    require(all(not (archive/name).exists() for name in ('guardian-started.json', 'guardian-result.json', 'controller-stdout.private', 'controller-stderr.private')), 'guardian_already_used')
    owned = None
    if lock_fd is None:
        owned = lock_path.open('a+')
        lock_fd = owned.fileno()
    try:
        actual, expected = os.fstat(lock_fd), lock_path.stat()
        require((actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino), 'incorrect_global_lock_fd')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(start <= now() <= latest, 'outside_launch_window_after_lock')
        # Verify again under exclusion; no long wait or credential work occurs here.
        verify_inputs(manifest, archive, root)
        require(not (root/'windows-case-active.json').exists(), 'windows_fence_appeared')
        started = now()
        require(start <= started <= latest, 'outside_launch_window_before_reservation')
        final_deadline = monotonic() + max(0, end + 25 - started)
        initial_deadline = final_deadline - 10
        record = {'case': CASE, 'run_nonce': manifest['run_nonce'], 'manifest_sha256': manifest_sha,
                  'state': 'active_exit_verification_required', 'guardian_pid': os.getpid(), 'started_unix': started}
        save_new(fence, record)
        proc = None
        consumer = None
        bridge = bridge_module(archive)
        try:
            save_new(archive/'guardian-started.json', record)
            with open(archive/'controller-stdout.private', 'xb') as out, open(archive/'controller-stderr.private', 'xb') as err:
                os.chmod(out.name, 0o600)
                os.chmod(err.name, 0o600)
                require(start <= now() <= latest, 'outside_launch_window_before_process')
                require(not Path(manifest['consumer']['output_dir']).exists(), 'consumer_output_already_exists')
                consumer_out = open(archive/'consumer-stdout.private', 'xb')
                consumer_err = open(archive/'consumer-stderr.private', 'xb')
                os.chmod(consumer_out.name, 0o600)
                os.chmod(consumer_err.name, 0o600)
                try:
                    consumer = popen(bridge.command(manifest), stdin=subprocess.DEVNULL, stdout=consumer_out, stderr=consumer_err, cwd=manifest['layout']['repo_root'], start_new_session=True)
                finally:
                    consumer_out.close(); consumer_err.close()
                proc = popen([str(root/'venv/Scripts/python.exe'), '-I', '-u',
                              win_root+'\\'+CASE+r'\controller.py', win_root+'\\'+CASE],
                             stdin=subprocess.PIPE, stdout=out, stderr=err)
                bridge_safe = bridge.supervise(proc, consumer, manifest, clock_monitor=clock_monitor,
                    initial_deadline=initial_deadline, final_deadline=final_deadline,
                    now=now, monotonic=monotonic)
                result_path = case/'run_result.json'
                result = json.loads(result_path.read_text()) if result_path.is_file() else {}
                verified = verify_exit(result, proc, manifest, started, now(), case, archive, root)
                safe = {k: result.get(k) for k in ('status', 'elapsed_seconds', 'child_exitcode', 'child_exited', 'job_active_processes', 'source_unchanged', 'helper_unchanged')}
                safe.update(bridge_safe)
                if safe['consumer_passed'] is not True and safe.get('status') == 'completed':
                    safe['status'] = 'failed'
                bridge.verify_consumer(manifest)
                safe.update(windows_controller_exitcode=proc.returncode, exit_verified=verified,
                            run_nonce=manifest['run_nonce'], production_acceptance=False)
                save_new(archive/'guardian-result.json', safe)
                require(verified, 'windows_exit_not_verified_fence_retained')
                wfence = root/'windows-case-active.json'
                if wfence.exists():
                    value = json.loads(wfence.read_text())
                    require(value.get('case') == CASE and value.get('child_pid') == result['child_pid']
                            and value.get('run_nonce') == manifest['run_nonce'], 'windows_fence_identity_mismatch')
                    save_new(archive/'closed-windows-fence.json', value)
                    wfence.unlink()
                value = json.loads(fence.read_text())
                require(value == record, 'linux_fence_identity_mismatch')
                save_new(archive/'closed-linux-fence.json', value)
                fence.unlink()
                return safe
        finally:
            if proc is not None and proc.stdin is not None and not proc.stdin.closed:
                proc.stdin.close()
            bridge.stop_consumer(consumer)
            # An unconfirmed Windows lifetime always leaves persistent exclusion in place.
    finally:
        if owned is not None:
            owned.close()


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args();manifest=json.loads(args.manifest.read_text())
    configure(manifest)
    result = run_guarded(manifest)
    print(json.dumps(result))
    return 0 if result['status'] == 'completed' else 4


if __name__ == '__main__':
    raise SystemExit(main())
