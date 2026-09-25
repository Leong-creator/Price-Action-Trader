"""One dated quote-only launch. Imports perform no I/O or SDK operations."""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import subprocess
import time


STATE_NAMES = ('m15_sdk_submission_journal.jsonl', 'm15_longbridge_sdk_runtime.json', 'm15_runtime_boot_audit.jsonl', 'm15_sdk_formal_test_epoch.json', 'm15_longbridge_virtual_account_epoch.json')
ARCHIVE = CASE = EXPECTED_WINDOW = None

@dataclass(frozen=True)
class Layout:
    archive: Path
    windows_root: Path
    source_home: Path
    windows_home_mnt: Path
    windows_home: str
    win_root: str
    lock: Path
    fence: Path
    transfer: Path
    state_root: Path
    base_python_root: Path


def configure(manifest_path, expected_hash=None):
    global ARCHIVE, CASE, EXPECTED_WINDOW
    payload=read_regular(manifest_path)
    require(expected_hash is not None and hashlib.sha256(payload).hexdigest()==expected_hash,'manifest_hash_mismatch')
    pinned=json.loads(payload)
    hashes={e['relative_path']:e['sha256'] for e in pinned['runner']['integrity_files']}
    common_path=Path(__file__).with_name('bootstrap.py')
    require(digest(common_path)==hashes['bootstrap.py'],'bootstrap_source_changed')
    common=load_module(common_path,'daily_bootstrap')
    manifest=common.load_manifest(manifest_path,expected_hash)
    cfg=manifest['layout']
    ARCHIVE=Path(cfg['archive']); CASE=manifest['case']
    EXPECTED_WINDOW=tuple(manifest[k] for k in ('window_start_utc','latest_start_utc','window_end_utc'))
    return manifest,Layout(archive=ARCHIVE,windows_root=Path(cfg['windows_root_mnt']),
        source_home=Path(cfg['source_home']),windows_home_mnt=Path(cfg['windows_home_mnt']),
        windows_home=cfg['windows_home_native'],win_root=cfg['windows_root_native'],
        lock=Path(cfg['lock']),fence=Path(cfg['fence']),transfer=Path(cfg['transfer']),
        state_root=Path(cfg['state_root']),base_python_root=Path(cfg['base_python_root_mnt']))


class Refusal(RuntimeError):
    """Only fixed codes reach safe output; never stringify native exceptions."""


def require(value, code):
    if not value:
        raise Refusal(code)


def stamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(dt.tzinfo is not None, 'timezone_required')
    return dt.timestamp()


def read_regular(path):
    path = Path(path)
    require(not path.is_symlink(), 'symlink_rejected')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as handle:
        require(stat.S_ISREG(os.fstat(handle.fileno()).st_mode), 'regular_file_required')
        return handle.read()


def digest(path):
    return hashlib.sha256(read_regular(path)).hexdigest()


def relative(value):
    p = PurePosixPath(value)
    require(not p.is_absolute() and '..' not in p.parts and str(p) != '.' and '\\' not in str(p), 'invalid_relative_path')
    return Path(*p.parts)


def inside(root, rel):
    p = root / relative(rel)
    require(p.resolve().is_relative_to(root.resolve()), 'path_outside_root')
    for ancestor in (p, *p.parents):
        if ancestor == root.parent:
            break
        require(not ancestor.is_symlink(), 'symlink_rejected')
    return p


def save(path, obj, *, update=False):
    data = (json.dumps(obj, indent=2) + '\n').encode()
    target = path.with_name(path.name + '.next') if update else path
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if update:
        os.replace(target, path)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def verify_manifest(manifest, layout):
    require(manifest.get('schema') == 2 and manifest.get('case') == CASE, 'manifest_identity_mismatch')
    keys = ('window_start_utc', 'latest_start_utc', 'window_end_utc')
    window = tuple(stamp(manifest[k]) for k in keys)
    require(window == tuple(map(stamp, EXPECTED_WINDOW)), 'unauthorized_window')
    runner = manifest['runner']
    if 'linux_python' in runner:
        require(digest(Path(runner['linux_python']).resolve())==runner['linux_python_sha256'],'linux_runner_interpreter_changed')
    require(digest(Path(runner['deployment_receipt_path']))==runner['deployment_receipt_sha256'], 'deployment_receipt_changed')
    integrity = runner['integrity_files']
    require(isinstance(integrity, list) and len(integrity) >= 2, 'runner_integrity_missing')
    names = [entry['relative_path'] for entry in integrity]
    require(len(set(names)) == len(names) and {'bootstrap.py','run_once.py','guardian.py','clock_preflight.py','m15_feed_clock.py','bridge_lifecycle.py','daemon_launch.py','launch_host.py','time_monitor.py'} <= set(names), 'runner_integrity_missing')
    for entry in integrity:
        require(digest(inside(layout.archive, entry['relative_path'])) == entry['sha256'], 'runner_integrity_mismatch')
    bases = runner['base_integrity_files']
    expected_bases = {str(layout.base_python_root / name) for name in ('python.exe', 'python314.dll')}
    require(isinstance(bases, list) and len(bases) == 2 and {entry['path'] for entry in bases} == expected_bases, 'base_python_file_set_invalid')
    for entry in bases:
        require(digest(Path(entry['path'])) == entry['sha256'].lower(), 'base_python_changed')
    require(digest(layout.transfer) == runner['credential_transfer_sha256'], 'credential_transfer_changed')
    states = runner['protected_states']
    require(isinstance(states, list) and len(states) == 5, 'protected_state_set_invalid')
    require({entry['name'] for entry in states} == set(STATE_NAMES), 'protected_state_set_invalid')
    for entry in states:
        require(digest(layout.state_root / entry['name']) == entry['sha256'], 'protected_state_changed_before_start')
    return window


def plan_credentials(manifest, layout, stop):
    transfer = json.loads(read_regular(layout.transfer))
    roots = [str(relative(p)) for p in transfer['created_private_roots']]
    require(set(roots) == {'.longbridge', '.config/price-action-trader'}, 'credential_roots_invalid')
    files = []
    for entry in transfer['files']:
        rel = relative(entry['relative_path'])
        require(any(rel.is_relative_to(Path(root)) for root in roots), 'credential_file_outside_owned_root')
        source = inside(layout.source_home, str(rel))
        target = inside(layout.windows_home_mnt, str(rel))
        require(not target.exists() and not target.is_symlink(), 'windows_credential_already_exists')
        data = read_regular(source)
        files.append({'relative_path': str(rel), 'source_sha256': hashlib.sha256(data).hexdigest(), 'copied': False, 'removed': False})
    require(len(files) == 2 and len({e['relative_path'] for e in files}) == 2, 'credential_file_set_invalid')
    client_files = [e for e in files if Path(e['relative_path']).name == 'longbridge_sdk_client_id']
    tokens = [e for e in files if Path(e['relative_path']).parts[0] == '.longbridge']
    require(len(client_files) == 1 and len(tokens) == 1, 'credential_file_set_invalid')
    token = json.loads(read_regular(layout.source_home / tokens[0]['relative_path']))
    require(type(token.get('expires_at')) is int and token['expires_at'] >= stop + 3600, 'credential_expiry_insufficient')
    require(isinstance(token.get('access_token'), str) and bool(token['access_token']), 'credential_access_token_missing')
    client = read_regular(layout.source_home / client_files[0]['relative_path']).decode().strip()
    require(client and token.get('client_id') == client, 'credential_client_mismatch')
    for root in roots:
        p = inside(layout.windows_home_mnt, root)
        require(not p.exists() and not p.is_symlink(), 'windows_credential_root_already_exists')
    return {'run_nonce': manifest['run_nonce'], 'roots': roots, 'created_directories': [], 'files': files, 'phase': 'planned'}


# Executed only immediately before the authorized window launch. No SDK imports.
# DACL is applied before any credential payload is copied into a new directory.
DIRECTORY_HELPER = r'''
import importlib.util,json,os,pathlib,stat,sys
d=json.load(sys.stdin); made=[]; result={'ok':False,'created_directories':made}
try:
    spec=importlib.util.spec_from_file_location('verified_controller',d['controller'])
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    w=m.Win(); sd=w.descriptor()
    try:
        home=pathlib.Path(d['home'])
        for rel in d['directories']:
            p=home.joinpath(*pathlib.PurePosixPath(rel).parts)
            for ancestor in (p.parent,*p.parent.parents):
                if ancestor.exists():
                    st=ancestor.lstat()
                    if getattr(st,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT: raise RuntimeError('reparse_point')
            p.mkdir(); made.append(rel); w.secure_directory(p,sd)
        result['ok']=True
    finally: w.LocalFree(sd)
except BaseException as exc: result['error_type']=type(exc).__name__
print(json.dumps(result))
'''


def create_private_directories(owner, layout):
    directories = set(owner['roots'])
    for entry in owner['files']:
        parent = Path(entry['relative_path']).parent
        while str(parent) not in owner['roots']:
            directories.add(str(parent))
            parent = parent.parent
    ordered = sorted(directories, key=lambda p: (len(Path(p).parts), p))
    request = {'controller': layout.win_root + '\\' + CASE + '\\controller.py', 'home': layout.windows_home, 'directories': ordered}
    proc = subprocess.run([str(layout.windows_root / 'venv/Scripts/python.exe'), '-I', '-S', '-B', '-c', DIRECTORY_HELPER],
                          input=json.dumps(request).encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    require(proc.returncode == 0, 'private_directory_helper_failed')
    reply = json.loads(proc.stdout.decode('utf-8-sig'))
    created = reply.get('created_directories', [])
    require(isinstance(created, list) and all(p in ordered for p in created), 'private_directory_reply_invalid')
    owner['created_directories'] = created
    save(layout.archive / 'credential-ownership.private.json', owner, update=True)
    require(reply.get('ok') is True and created == ordered, 'private_directory_setup_failed')


def copy_credentials(owner, layout):
    for entry in owner['files']:
        source = inside(layout.source_home, entry['relative_path'])
        target = inside(layout.windows_home_mnt, entry['relative_path'])
        data = read_regular(source)
        require(hashlib.sha256(data).hexdigest() == entry['source_sha256'], 'original_credential_changed')
        # Mark the exclusive-create intent before the operation; never overwrite.
        entry['create_intent'] = True
        save(layout.archive / 'credential-ownership.private.json', owner, update=True)
        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as f:
            entry['copied'] = True
            created = os.fstat(f.fileno())
            entry['created_file_identity'] = [created.st_dev, created.st_ino]
            entry['copy_complete'] = False
            save(layout.archive / 'credential-ownership.private.json', owner, update=True)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        require(digest(target) == entry['source_sha256'], 'credential_copy_mismatch')
        entry['copy_complete'] = True
        save(layout.archive / 'credential-ownership.private.json', owner, update=True)
    owner['phase'] = 'copied'
    save(layout.archive / 'credential-ownership.private.json', owner, update=True)


def cleanup_credentials(owner, layout, *, allow_incomplete=False):
    archive = layout.archive / 'credential-copies.private'
    archive.mkdir(mode=0o700)
    # Validate the whole owned set before deleting any credential. Partial-copy
    # recovery is allowed only before invoking the SDK guardian, and only for
    # the exact file exclusively created by this run.
    snapshots = {}
    for index, entry in enumerate(owner['files']):
        if not entry['copied']:
            continue
        target = inside(layout.windows_home_mnt, entry['relative_path'])
        data = read_regular(target)
        actual_sha = hashlib.sha256(data).hexdigest()
        identity = target.stat(follow_symlinks=False)
        current_identity = [identity.st_dev, identity.st_ino]
        if 'created_file_identity' in entry:
            require(current_identity == entry['created_file_identity'], 'credential_copy_changed_preserved')
        if actual_sha != entry['source_sha256']:
            require(allow_incomplete and entry.get('copy_complete') is False
                    and current_identity == entry.get('created_file_identity'),
                    'credential_copy_changed_preserved')
        snapshots[index] = (data, actual_sha, current_identity)
    for index, entry in enumerate(owner['files']):
        if not entry['copied']:
            continue
        target = inside(layout.windows_home_mnt, entry['relative_path'])
        data, actual_sha, identity = snapshots[index]
        backup = archive / ('credential-%d.private' % index)
        with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        current = target.stat(follow_symlinks=False)
        require([current.st_dev, current.st_ino] == identity
                and digest(backup) == actual_sha and digest(target) == actual_sha,
                'credential_archive_mismatch')
        target.unlink()
        entry['removed'] = True
        entry['archived_sha256'] = actual_sha
        entry['archived_incomplete_copy'] = actual_sha != entry['source_sha256']
        save(layout.archive / 'credential-ownership.private.json', owner, update=True)
    for rel in reversed(owner['created_directories']):
        inside(layout.windows_home_mnt, rel).rmdir()
    # A timed-out directory helper may have created roots without returning its
    # ownership list. Do not delete unknown directories or claim them cleaned.
    for rel in [*owner['roots'], *(e['relative_path'] for e in owner['files'])]:
        target = inside(layout.windows_home_mnt, rel)
        require(not target.exists() and not target.is_symlink(), 'credential_cleanup_incomplete')
    owner['phase'] = 'cleaned'
    save(layout.archive / 'credential-ownership.private.json', owner, update=True)


def stream_digest(path):
    require(not Path(path).is_symlink(),'symlink_rejected')
    digestor=hashlib.sha256()
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as source:
        require(stat.S_ISREG(os.fstat(source.fileno()).st_mode),'regular_file_required')
        for chunk in iter(lambda:source.read(1024*1024),b''):digestor.update(chunk)
    return digestor.hexdigest()


def copy_evidence_stream(source,target):
    require(not Path(source).is_symlink(),'symlink_rejected')
    digestor=hashlib.sha256()
    with os.fdopen(os.open(source,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode),'regular_file_required')
        with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as out:
            for chunk in iter(lambda:stream.read(1024*1024),b''):
                digestor.update(chunk);out.write(chunk)
            out.flush();os.fsync(out.fileno())
    return digestor.hexdigest()


def archive_case(layout):
    """Keep private originals until a separate reviewed duplicate cleanup."""
    case = layout.windows_root / CASE
    destination = layout.archive / CASE
    destination.mkdir(mode=0o700)
    allowed = {'run_started.json', 'run_result.json', 'stdout.private', 'stderr.private', 'events.ndjson', 'stages.jsonl', 'health.json', 'summary.json', 'health.json.tmp', 'summary.json.tmp', 'producer-summary.json'}
    files = [p for p in case.iterdir() if p.is_file() and p.name in allowed]
    logs = case / 'sdk-logs'
    if logs.exists():
        require(not logs.is_symlink(), 'case_log_symlink')
        for folder, directories, names in os.walk(logs, followlinks=False):
            require(all(not (Path(folder)/n).is_symlink() for n in directories), 'case_log_symlink')
            files.extend(Path(folder)/n for n in names)
    records = []
    for source in files:
        relative_path = source.relative_to(case)
        target = destination / relative_path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        sha=copy_evidence_stream(source,target)
        require(stream_digest(source)==sha and stream_digest(target)==sha,'case_archive_mismatch')
        records.append({'relative_path': str(relative_path), 'sha256': sha})
    save(layout.archive / 'case-archive-manifest.private.json', {'files': records, 'windows_private_duplicates_retained': True})
    return len(records)


def diagnostic_passed(manifest, layout):
    """Malformed or incomplete evidence is a failed diagnostic, never a pass."""
    try:
        return _diagnostic_passed(manifest, layout)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, Refusal):
        return False


def diagnostic_capture_completed(manifest,layout,safe):
    """Cross-check both terminal sequences without granting quality acceptance."""
    try:
        bridge=load_module(layout.archive/'bridge_lifecycle.py','verified_capture_completion')
        if (safe.get('diagnostic_capture_completed') is not True or safe.get('exit_verified') is not True
                or safe.get('child_exitcode')!=0 or safe.get('job_active_processes')!=0
                or not bridge.diagnostic_capture_completed(manifest,safe.get('consumer_exitcode'))):
            return False
        producer=json.loads(read_regular(layout.windows_root/CASE/'summary.json'))
        consumer=json.loads(read_regular(Path(manifest['consumer']['output_dir'])/'summary.json'))
        return (producer.get('schema_version')==1 and producer.get('run_id')==manifest['run_nonce']
            and producer.get('status')=='window_observed' and producer.get('completed_window') is True
            and 'reason' in producer and producer['reason'] is None
            and producer.get('production_acceptance') is False
            and all(stamp(producer[k])==stamp(manifest[k]) for k in ('window_start_utc','window_end_utc'))
            and producer.get('terminal_sequence')==consumer['producer_end_sequence'])
    except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError):
        return False


def _diagnostic_passed(manifest, layout):
    """Only complete producer plus EOF-aware original-pipeline evidence can pass."""
    bridge = load_module(layout.archive/'bridge_lifecycle.py', 'verified_bridge_acceptance')
    safe = json.loads(read_regular(layout.archive/'guardian-result.json'))
    evidence=layout.archive/CASE if (layout.archive/CASE).exists() else layout.windows_root/CASE
    summary = json.loads(read_regular(evidence/'summary.json'))
    consumer = json.loads(read_regular(Path(manifest['consumer']['output_dir'])/'summary.json'))
    return (safe.get('consumer_passed') is True
            and bridge.consumer_passed(manifest, safe.get('consumer_exitcode'))
            and summary.get('run_id') == manifest['run_nonce']
            and summary.get('schema_version') == 1
            and all(stamp(summary[k]) == stamp(manifest[k]) for k in ('window_start_utc','window_end_utc'))
            and summary.get('production_acceptance') is False
            and type(summary.get('terminal_sequence')) is int
            and summary['terminal_sequence'] == consumer.get('producer_end_sequence')
            and summary.get('status') == 'window_observed'
            and summary.get('completed_window') is True
            and 'reason' in summary and summary['reason'] is None)


def verify_predecessor(manifest):
    # Previous-day incomplete starts remain blocking even if a marker was moved.
    parent=Path(manifest['layout']['sessions_root'])
    current=Path(manifest['layout']['archive'])
    for folder in parent.iterdir():
        if folder==current or not folder.is_dir() or not (folder/'run-once-started.json').exists():
            continue
        path=folder/'run-once-result.json'
        require(path.is_file(), 'prior_daily_exit_unverified')
        record=json.loads(read_regular(path))
        require(record.get('exit_verified') is True and record.get('credentials_cleaned') is True,
                'prior_daily_cleanup_unverified')


def require_not_cancelled():
    cancellation=sys.modules.get('pat_launch_state')
    require(cancellation is None or not cancellation.stop_requested(), 'supervisor_signal_before_launch')


def run_once(manifest_path, expected_hash, *, layout=None, now=time.time,
             make_dirs=create_private_directories, invoke=None, summarize=None, check_clock=None):
    """Test seams are internal. CLI accepts no credential/path/window overrides."""
    if layout is None:
        _,layout=configure(manifest_path,expected_hash)
    result = {'status': 'refused', 'sdk_started': False, 'exit_verified': False,
              'credentials_cleaned': False, 'protected_states_unchanged': None,
              'original_credentials_unchanged': None, 'production_acceptance': False,
              'diagnostic_window_passed': False}
    owner = None
    fd = None
    attempted = False
    guardian_called = False
    manifest = None
    monitor = None
    try:
        require_not_cancelled()
        require(Path(manifest_path) == layout.archive / 'manifest.json', 'manifest_path_not_allowed')
        payload = read_regular(manifest_path)
        require(hashlib.sha256(payload).hexdigest() == expected_hash, 'manifest_hash_mismatch')
        manifest = json.loads(payload)
        result.update(run_nonce=manifest['run_nonce'],market_date=manifest['market_date'])
        window = tuple(stamp(manifest[k]) for k in ('window_start_utc', 'latest_start_utc', 'window_end_utc'))
        require(window == tuple(map(stamp, EXPECTED_WINDOW)), 'unauthorized_window')
        require(window[0] <= now() <= window[1], 'outside_launch_window')
        # Nothing is locked, reserved or copied for an early/late invocation.
        fd = os.open(layout.lock, os.O_RDWR | os.O_NOFOLLOW)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(window[0] <= now() <= window[1], 'outside_launch_window_after_lock')
        require(not layout.fence.exists() and not (layout.windows_root / 'windows-case-active.json').exists(), 'active_fence_exists')
        require(not (layout.archive / 'run-once-result.json').exists(), 'run_already_used')
        verify_manifest(manifest, layout)
        for blocked_path in manifest.get('layout',{}).get('additional_windows_fences',[]):
            require(not Path(blocked_path).exists() and not Path(blocked_path).is_symlink(),'legacy_windows_fence_exists')
        verify_predecessor(manifest)
        guardian = load_module(layout.archive / 'guardian.py', 'verified_guardian')
        guardian.configure(manifest)
        guardian.verify_inputs(manifest, layout.archive, layout.windows_root)
        try:
            if check_clock is None:
                clock = load_module(layout.archive / 'clock_preflight.py', 'verified_clock_preflight')
                clock_result = clock.check(layout.archive, windows_python=str(layout.windows_root/'venv/Scripts/python.exe'))
            else:
                clock_result = check_clock(layout.archive)
        except Exception as exc:
            result['failure_phase'] = 'clock_preflight'
            known_codes = {'clock_platform_invalid', 'clock_samples_missing',
                           'clock_no_valid_sample', 'clock_query_failed',
                           'clock_sample_invalid', 'clock_alignment_unproven'}
            result['error_code'] = (str(exc) if type(exc) is RuntimeError and str(exc) in known_codes
                                    else 'clock_query_timeout' if isinstance(exc, subprocess.TimeoutExpired)
                                    else 'clock_preflight_exception')
            result['error_type'] = type(exc).__name__
            raise
        require(clock_result.get('reception_allowed') is True, 'clock_reception_not_allowed')
        require(type(clock_result.get('quality_passed')) is bool, 'clock_quality_missing')
        result['clock_result'] = clock_result
        result['received_for_diagnosis_only'] = not clock_result['quality_passed']
        save(layout.archive / 'launch-clock-assessment.json', clock_result)
        require(window[0] <= now() <= window[1], 'outside_launch_window_after_clock_check')
        save(layout.archive / 'run-once-started.json', {'run_nonce': manifest['run_nonce'], 'started_at': datetime.fromtimestamp(now(), timezone.utc).isoformat(), 'manifest_sha256': expected_hash})
        attempted = True
        require_not_cancelled()
        owner = plan_credentials(manifest, layout, window[2])
        save(layout.archive / 'credential-ownership.private.json', owner)
        make_dirs(owner, layout)
        copy_credentials(owner, layout)
        require(window[0] <= now() <= window[1], 'outside_launch_window_after_credentials')
        verify_manifest(manifest, layout)
        require_not_cancelled()
        if invoke is None:
            time_module=load_module(layout.archive/'time_monitor.py','verified_time_monitor')
            monitor=time_module.Monitor(layout.archive,str(layout.windows_root/'venv/Scripts/python.exe'),manifest)
        guardian_called = True
        result['sdk_started'] = None  # A guardian exception cannot prove no child started.
        safe = invoke(manifest, fd) if invoke is not None else guardian.run_guarded(manifest, lock_fd=fd, archive=layout.archive, root=layout.windows_root, win_root=layout.win_root, fence=layout.fence, lock_path=layout.lock, clock_monitor=monitor)
        verified = safe.get('exit_verified') is True and safe.get('child_exited') is True and safe.get('job_active_processes') == 0
        result.update(sdk_started=True, exit_verified=verified, guardian_status=safe.get('status') if safe.get('status') in {'completed', 'failed', 'external_deadline_exceeded', 'control_pipe_closed', 'watchdog_fault'} else 'unknown')
        require(verified, 'guardian_exit_unverified_credentials_retained')
        result['diagnostic_capture_completed']=diagnostic_capture_completed(manifest,layout,safe)
        window_passed = bool(summarize(manifest, layout)) if summarize else diagnostic_passed(manifest, layout)
        result['bounded_pipeline_passed'] = safe.get('status') == 'completed' and window_passed
        result['reception_window_passed'] = result['bounded_pipeline_passed']
        result['diagnostic_window_passed'] = result['reception_window_passed'] and clock_result['quality_passed']
        result['status'] = ('completed' if result['diagnostic_window_passed'] else 'observed_not_passed') if safe.get('status') == 'completed' else 'failed'
    except BaseException as exc:
        result['status'] = 'failed' if attempted else 'refused'
        result['error'] = str(exc) if isinstance(exc, Refusal) else type(exc).__name__
    finally:
        if monitor is not None:
            try:
                clock_evidence=monitor.finish()
                save(layout.archive/'clock-evidence.json',clock_evidence)
                result['clock_quality_passed']=clock_evidence['quality_passed']
                if not clock_evidence['quality_passed']:
                    result['diagnostic_window_passed']=False
                    if result['status']=='completed':result['status']='observed_not_passed'
            except BaseException as exc:
                result['clock_quality_passed']=False
                result['clock_finalization_error']=type(exc).__name__
                result['status']='failed'
        if owner is not None:
            try:
                result['original_credentials_unchanged'] = all(digest(layout.source_home / e['relative_path']) == e['source_sha256'] for e in owner['files'])
            except BaseException:
                result['original_credentials_unchanged'] = False
            if not guardian_called or result['exit_verified']:
                try:
                    cleanup_credentials(owner, layout, allow_incomplete=not guardian_called)
                    result['credentials_cleaned'] = True
                except BaseException as exc:
                    if not layout.fence.exists():
                        save(layout.fence, {'case':CASE,'run_nonce':manifest['run_nonce'],'state':'credential_cleanup_incomplete'})
                    result['cleanup_error'] = str(exc) if isinstance(exc, Refusal) else type(exc).__name__
                    result['status'] = 'failed'
            else:
                result['credentials_retained_exit_unverified'] = True
        if attempted:
            if result['exit_verified']:
                try:
                    result['case_evidence_files_archived']=archive_case(layout)
                    result['windows_private_evidence_duplicate_cleanup_pending']=True
                except BaseException as exc:
                    result['archive_error']=type(exc).__name__
                    result['status']='failed'
            try:
                result['protected_states_unchanged'] = all(digest(layout.state_root / e['name']) == e['sha256'] for e in manifest['runner']['protected_states'])
            except BaseException:
                result['protected_states_unchanged'] = False
            if result['protected_states_unchanged'] is not True or result['original_credentials_unchanged'] is False:
                result['status'] = 'failed'
            try:
                save(layout.archive / 'run-once-result.json', result)
            except BaseException:
                result['status'] = 'failed'
                result['result_write_failed'] = True
            try:
                write_acceptance(manifest,layout,result)
            except BaseException as exc:
                try:save(layout.archive/'acceptance-export-failure.json',{'error_type':type(exc).__name__,'run_id':manifest['run_nonce']})
                except BaseException:result['acceptance_export_failed']=True
        else:
            try:
                save(layout.archive / ('refusal_%d_%d.json' % (time.time_ns(), os.getpid())), result)
            except BaseException:
                result['refusal_record_write_failed'] = True
        if fd is not None:
            os.close(fd)
    return result


def write_acceptance(manifest,layout,result):
    """Independent whole-day judgment, preserving raw lifecycle and source records."""
    def record(path):
        try:return json.loads(read_regular(path))
        except (OSError,ValueError):return {}
    completion={'run_once':result,'guardian':record(layout.archive/'guardian-result.json'),
        'producer':record(layout.archive/CASE/'summary.json'),
        'consumer':record(Path(manifest['consumer']['output_dir'])/'summary.json'),
        'exit_fences_cleared':not layout.fence.exists() and not (layout.windows_root/'windows-case-active.json').exists()}
    save(layout.archive/'completion.json',completion)
    evaluator=Path(manifest['layout']['repo_root'])/'scripts/m15_feed_session_acceptance.py'
    entries={e['path']:e['sha256'] for e in manifest['consumer']['integrity_files']}
    require(str(evaluator) in entries and digest(evaluator)==entries[str(evaluator)],'acceptance_source_changed')
    sys.path.insert(0,manifest['layout']['repo_root'])
    module=load_module(evaluator,'frozen_session_acceptance')
    spec=record(layout.archive/'run-spec.json')
    report=module.evaluate_session(Path(manifest['consumer']['output_dir']),spec,completion,
        record(layout.archive/'clock-evidence.json'),session_spec_sha256=digest(layout.archive/'run-spec.json'))
    save(layout.archive/'feed_session_acceptance.json',report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    result = run_once(args.manifest, args.manifest_sha256)
    print(json.dumps(result))
    return 0 if result['status'] == 'completed' else 4


if __name__ == '__main__':
    raise SystemExit(main())
