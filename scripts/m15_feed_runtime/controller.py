"""Windows-only one-shot supervisor. Importing this module starts nothing."""
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT = PYTHON = None
MAX_RUNTIME_SECONDS = 24315
SOURCE_SHA256 = None


def configure(manifest):
    global ROOT, PYTHON, SOURCE_SHA256, MAX_RUNTIME_SECONDS
    ROOT=Path(manifest['layout']['windows_root_native'])
    PYTHON=ROOT/'venv/Scripts/python.exe'
    SOURCE_SHA256=manifest['files']['source.py']['sha256']
    MAX_RUNTIME_SECONDS=(parse_utc(manifest['window_end_utc'])-parse_utc(manifest['window_start_utc'])).total_seconds()+10


def utc():
    return datetime.now(timezone.utc).isoformat()


class SA(C.Structure):
    _fields_ = [('length', W.DWORD), ('descriptor', W.LPVOID), ('inherit', W.BOOL)]


class SI(C.Structure):
    _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR),
                ('title', W.LPWSTR), ('x', W.DWORD), ('y', W.DWORD),
                ('xsize', W.DWORD), ('ysize', W.DWORD), ('xchars', W.DWORD),
                ('ychars', W.DWORD), ('fill', W.DWORD), ('flags', W.DWORD),
                ('show', W.WORD), ('reserved_size', W.WORD), ('reserved2', W.LPVOID),
                ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]


class SIX(C.Structure):
    _fields_ = [('startup', SI), ('attributes', W.LPVOID)]


class PI(C.Structure):
    _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]


class BASIC_LIMIT(C.Structure):
    _fields_ = [('process_time', C.c_longlong), ('job_time', C.c_longlong),
                ('flags', W.DWORD), ('min_ws', C.c_size_t), ('max_ws', C.c_size_t),
                ('active_limit', W.DWORD), ('affinity', C.c_size_t),
                ('priority', W.DWORD), ('scheduling', W.DWORD)]


class IO_COUNTERS(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in
                ['read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes']]


class LIMIT(C.Structure):
    _fields_ = [('basic', BASIC_LIMIT), ('io', IO_COUNTERS),
                ('process_memory', C.c_size_t), ('job_memory', C.c_size_t),
                ('peak_process_memory', C.c_size_t), ('peak_job_memory', C.c_size_t)]


class ACCOUNTING(C.Structure):
    _fields_ = [('user', C.c_longlong), ('kernel', C.c_longlong),
                ('period_user', C.c_longlong), ('period_kernel', C.c_longlong),
                ('page_faults', W.DWORD), ('total', W.DWORD),
                ('active', W.DWORD), ('terminated', W.DWORD)]


class Win:
    """Explicit signatures prevent 64-bit handle truncation; no SDK dependency."""
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('windows_only')
        self.k = C.WinDLL('kernel32', use_last_error=True)
        self.a = C.WinDLL('advapi32', use_last_error=True)
        def api(lib, name, result, *args):
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = result, args
            setattr(self, name, fn)
        api(self.k, 'CreateJobObjectW', W.HANDLE, W.LPVOID, W.LPCWSTR)
        api(self.k, 'SetInformationJobObject', W.BOOL, W.HANDLE, C.c_int, W.LPVOID, W.DWORD)
        api(self.k, 'QueryInformationJobObject', W.BOOL, W.HANDLE, C.c_int, W.LPVOID, W.DWORD, W.LPVOID)
        api(self.k, 'TerminateJobObject', W.BOOL, W.HANDLE, W.UINT)
        api(self.k, 'CloseHandle', W.BOOL, W.HANDLE)
        api(self.k, 'CreateEventW', W.HANDLE, W.LPVOID, W.BOOL, W.BOOL, W.LPCWSTR)
        api(self.k, 'SetEvent', W.BOOL, W.HANDLE)
        api(self.k, 'WaitForMultipleObjects', W.DWORD, W.DWORD, W.LPVOID, W.BOOL, W.DWORD)
        api(self.k, 'WaitForSingleObject', W.DWORD, W.HANDLE, W.DWORD)
        api(self.k, 'GetExitCodeProcess', W.BOOL, W.HANDLE, C.POINTER(W.DWORD))
        api(self.k, 'InitializeProcThreadAttributeList', W.BOOL, W.LPVOID, W.DWORD, W.DWORD, C.POINTER(C.c_size_t))
        api(self.k, 'UpdateProcThreadAttribute', W.BOOL, W.LPVOID, W.DWORD, C.c_size_t, W.LPVOID, C.c_size_t, W.LPVOID, W.LPVOID)
        api(self.k, 'DeleteProcThreadAttributeList', None, W.LPVOID)
        api(self.k, 'CreateProcessW', W.BOOL, W.LPCWSTR, W.LPWSTR, W.LPVOID,
            W.LPVOID, W.BOOL, W.DWORD, W.LPVOID, W.LPCWSTR, C.POINTER(SIX), C.POINTER(PI))
        api(self.k, 'ResumeThread', W.DWORD, W.HANDLE)
        api(self.k, 'CreateFileW', W.HANDLE, W.LPCWSTR, W.DWORD, W.DWORD,
            C.POINTER(SA), W.DWORD, W.DWORD, W.HANDLE)
        api(self.k, 'GetCurrentProcess', W.HANDLE)
        api(self.k, 'LocalFree', W.LPVOID, W.LPVOID)
        api(self.a, 'OpenProcessToken', W.BOOL, W.HANDLE, W.DWORD, C.POINTER(W.HANDLE))
        api(self.a, 'GetTokenInformation', W.BOOL, W.HANDLE, C.c_int, W.LPVOID, W.DWORD, C.POINTER(W.DWORD))
        api(self.a, 'ConvertSidToStringSidW', W.BOOL, W.LPVOID, C.POINTER(W.LPWSTR))
        api(self.a, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', W.BOOL, W.LPCWSTR, W.DWORD, C.POINTER(W.LPVOID), W.LPVOID)
        api(self.a, 'GetSecurityDescriptorDacl', W.BOOL, W.LPVOID, C.POINTER(W.BOOL), C.POINTER(W.LPVOID), C.POINTER(W.BOOL))
        api(self.a, 'SetNamedSecurityInfoW', W.DWORD, W.LPWSTR, C.c_int, W.DWORD,
            W.LPVOID, W.LPVOID, W.LPVOID, W.LPVOID)

    @staticmethod
    def check(value):
        if not value:
            raise C.WinError(C.get_last_error())
        return value

    def descriptor(self):
        token = W.HANDLE()
        self.check(self.OpenProcessToken(self.GetCurrentProcess(), 8, C.byref(token)))
        try:
            size = W.DWORD()
            self.GetTokenInformation(token, 1, None, 0, C.byref(size))
            buffer = C.create_string_buffer(size.value)
            self.check(self.GetTokenInformation(token, 1, buffer, size, C.byref(size)))
            sid = C.cast(buffer, C.POINTER(W.LPVOID))[0]
            string = W.LPWSTR()
            self.check(self.ConvertSidToStringSidW(sid, C.byref(string)))
            try:
                text = 'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;' + string.value + ')'
            finally:
                self.LocalFree(C.cast(string, W.LPVOID))
        finally:
            self.CloseHandle(token)
        sd = W.LPVOID()
        self.check(self.ConvertStringSecurityDescriptorToSecurityDescriptorW(text, 1, C.byref(sd), None))
        return sd

    def secure_directory(self, path, descriptor):
        present, defaulted, acl = W.BOOL(), W.BOOL(), W.LPVOID()
        self.check(self.GetSecurityDescriptorDacl(descriptor, C.byref(present), C.byref(acl), C.byref(defaulted)))
        if not present.value or not acl.value:
            raise RuntimeError('private_dacl_missing')
        code = self.SetNamedSecurityInfoW(str(path), 1, 4 | 0x80000000, None, None, acl, None)
        if code:
            raise C.WinError(code)

    def active(self, job):
        info = ACCOUNTING()
        self.check(self.QueryInformationJobObject(job, 1, C.byref(info), C.sizeof(info), None))
        return info.active


def write_json(path, obj, *, exclusive=True):
    with open(path, 'x' if exclusive else 'w', encoding='utf-8') as handle:
        json.dump(obj, handle, indent=2)
        handle.write('\n')


def clean_environment(log_dir):
    env = dict(os.environ)
    removed = sorted(key for key in env if key.upper().startswith(
        ('LONGBRIDGE_', 'LONGPORT_', 'M15_', 'PYTHON', 'LD_')))
    for key in removed:
        del env[key]
    env['LONGBRIDGE_LOG_PATH'] = str(log_dir)
    return env, removed


def run_case(case, *, executable=None, root=None, seconds=60.0,
             expected_hash=None, watch_fd=0, watchdog=None, extra_result=None):
    """Test overrides are internal; official CLI accepts only a fresh case directory."""
    executable=executable or PYTHON
    root=root or ROOT
    expected_hash=expected_hash or SOURCE_SHA256
    if not 0 < seconds <= MAX_RUNTIME_SECONDS:
        raise ValueError('deadline_out_of_range')
    root, case = Path(root).resolve(), Path(case).resolve()
    if case == root or not case.is_relative_to(root) or not case.is_dir():
        raise ValueError('case_must_exist_inside_private_root')
    source = case/'source.py'
    if any((case/name).exists() for name in ('run_started.json', 'run_result.json', 'stdout.private', 'stderr.private', 'sdk-logs')):
        raise ValueError('case_already_used')
    if source.is_symlink() or not source.is_file():
        raise ValueError('source_must_be_regular_file')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != expected_hash:
        raise ValueError('source_hash_mismatch')
    w = Win()
    sd = w.descriptor()
    job = eof_event = None
    handles = []
    attributes = None
    pi = PI()
    resumed = False
    reserved = False
    fence = root/'windows-case-active.json'
    start = time.monotonic()
    result = {'status': 'not_started', 'started_at': utc(), 'source_sha256': digest,
              'external_deadline_seconds': seconds, 'sdk_region_override': None,
              'production_acceptance': False, 'child_exited': False,
              'job_active_processes': None, 'cross_os_flock_atomic': False}
    result.update(extra_result or {})
    try:
        w.secure_directory(case, sd)
        # Root/fence is shared by all cases; parent establishes this root as private.
        w.secure_directory(root, sd)
        write_json(fence, {'state': 'active_exit_confirmation_required', 'case': case.name,
                          'controller_pid': os.getpid(), 'run_nonce':result.get('run_nonce'), 'started_at': result['started_at']})
        reserved = True
        write_json(case/'run_started.json', result)
        log = case/'sdk-logs'
        log.mkdir()
        w.secure_directory(log, sd)
        env, removed = clean_environment(log)
        result['removed_environment_names'] = removed
        result['python'] = str(executable)
        result['official_sdk_log_directory'] = str(log)
        job = w.check(w.CreateJobObjectW(None, None))
        limits = LIMIT()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        w.check(w.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)))
        sa = SA(C.sizeof(SA), sd, True)
        for path, access, disposition in [(case/'stdout.private', 0x40000000, 1),
                                          (case/'stderr.private', 0x40000000, 1),
                                          ('NUL', 0x80000000, 3)]:
            handle = w.CreateFileW(str(path), access, 3, C.byref(sa), disposition, 0x80, None)
            if handle == C.c_void_p(-1).value:
                raise C.WinError(C.get_last_error())
            handles.append(handle)
        size = C.c_size_t()
        w.InitializeProcThreadAttributeList(None, 2, 0, C.byref(size))
        attributes = C.create_string_buffer(size.value)
        w.check(w.InitializeProcThreadAttributeList(attributes, 2, 0, C.byref(size)))
        job_list = (W.HANDLE * 1)(job)
        handle_list = (W.HANDLE * len(handles))(*handles)
        w.check(w.UpdateProcThreadAttribute(attributes, 0, 0x2000D, job_list, C.sizeof(job_list), None, None))
        w.check(w.UpdateProcThreadAttribute(attributes, 0, 0x20002, handle_list, C.sizeof(handle_list), None, None))
        si = SIX()
        si.startup.cb = C.sizeof(si)
        si.startup.flags = 0x100  # STARTF_USESTDHANDLES
        si.startup.stdin, si.startup.stdout, si.startup.stderr = handles[2], handles[0], handles[1]
        si.attributes = C.cast(attributes, W.LPVOID)
        environment = C.create_unicode_buffer('\0'.join(k+'='+v for k, v in sorted(env.items(), key=lambda item:item[0].upper()))+'\0\0')
        command = C.create_unicode_buffer(subprocess.list2cmdline([str(executable), '-I', '-u', str(source)]))
        # Atomic job membership: a crash before ResumeThread still closes Job and kills child.
        flags = 0x80000 | 0x400 | 0x4 | 0x08000000
        w.check(w.CreateProcessW(str(executable), command, None, None, True, flags,
                                environment, str(case), C.byref(si), C.byref(pi)))
        result['child_pid'] = pi.pid
        write_json(fence, {'state': 'active_exit_confirmation_required', 'case': case.name,
                          'controller_pid': os.getpid(), 'child_pid': pi.pid, 'run_nonce':result.get('run_nonce'),
                          'started_at': result['started_at']}, exclusive=False)
        eof_event = w.check(w.CreateEventW(None, True, False, None))
        def watch_control():
            try:
                while os.read(watch_fd, 1):
                    pass
            finally:
                w.SetEvent(eof_event)
        # Parent control pipe is NOT one of the handles inherited by SDK child.
        threading.Thread(target=watch_control, daemon=True).start()
        if w.WaitForSingleObject(eof_event, 0) == 0:
            raise RuntimeError('control_pipe_closed_before_resume')
        if watchdog and watchdog():
            raise RuntimeError('watchdog_rejected_before_resume')
        if w.ResumeThread(pi.thread) == 0xFFFFFFFF:
            raise C.WinError(C.get_last_error())
        resumed = True
        remaining_ms = max(0, int((seconds-(time.monotonic()-start))*1000))
        wait_handles = (W.HANDLE * 2)(pi.process, eof_event)
        deadline = start + seconds
        while True:
            remaining_ms = max(0, int((deadline-time.monotonic())*1000))
            waited = w.WaitForMultipleObjects(2, wait_handles, False, min(100, remaining_ms))
            if waited != 258 or remaining_ms <= 0:
                break
            fault = watchdog() if watchdog else None
            if fault:
                result['watchdog_reason'] = fault
                waited = 3
                break
        if waited == 0:
            result['status'] = 'completed'
        elif waited == 1:
            result['status'] = 'control_pipe_closed'
        elif waited == 3:
            result['status'] = 'watchdog_fault'
        elif waited == 258:
            result['status'] = 'external_deadline_exceeded'
        else:
            raise C.WinError(C.get_last_error())
    except BaseException as exc:
        result['status'] = 'controller_error'
        result['error_type'] = type(exc).__name__
        result['winerror'] = getattr(exc, 'winerror', None)
        raise
    finally:
        cleanup_error = None
        try:
            if job:
                active = w.active(job)
                result['cleanup_terminated_active_processes'] = active
                if active:
                    w.check(w.TerminateJobObject(job, 124))
                finish_by = time.monotonic()+5
                if pi.process:
                    timeout = max(0, int((finish_by-time.monotonic())*1000))
                    result['child_exited'] = w.WaitForSingleObject(pi.process, timeout) == 0
                    code = W.DWORD()
                    w.check(w.GetExitCodeProcess(pi.process, C.byref(code)))
                    result['child_exitcode'] = code.value
                    if result['status'] == 'completed' and code.value != 0:
                        result['status'] = 'failed'
                while w.active(job) and time.monotonic() < finish_by:
                    time.sleep(0.01)
                result['job_active_processes'] = w.active(job)
                if pi.process and (not result['child_exited'] or result['job_active_processes'] != 0):
                    raise RuntimeError('job_exit_not_confirmed')
        except BaseException as exc:
            cleanup_error = type(exc).__name__
            result['status'] = 'exit_not_confirmed'
        finally:
            # Only controller owns the job handle; child cannot keep it alive after parent death.
            if job:
                w.CloseHandle(job)
            for handle in [pi.thread, pi.process, *handles]:
                if handle:
                    w.CloseHandle(handle)
            # eof_event stays open until controller process exit: daemon watcher may still SetEvent.
            if attributes is not None:
                w.DeleteProcThreadAttributeList(attributes)
            w.LocalFree(sd)
        result.update(finished_at=utc(), elapsed_seconds=round(time.monotonic()-start, 3),
                      child_was_resumed=resumed,
                      source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==digest)
        if cleanup_error:
            result['cleanup_error_type'] = cleanup_error
        if watchdog is not None and hasattr(watchdog, 'diagnostics'):
            result['health_read_diagnostics'] = watchdog.diagnostics()
        if reserved:
            write_json(case/'run_result.json', result)
            # Failure/abrupt exits keep the fence; root must verify Windows absence before clearing.
            if result['status'] == 'completed' and result['child_exited'] and result['job_active_processes'] == 0 and result['source_unchanged'] and extra_result is None:
                fence.unlink()
    return result


def parse_utc(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone_required')
    return parsed.astimezone(timezone.utc)


def verify_manifest(case, now=None):
    now = now or datetime.now(timezone.utc)
    manifest = json.loads((case/'manifest.json').read_text(encoding='utf-8'))
    common_path=case/'bootstrap.py'
    if common_path.is_symlink() or hashlib.sha256(common_path.read_bytes()).hexdigest()!=manifest['files']['bootstrap.py']['sha256']:
        raise ValueError('bootstrap_source_changed')
    bootstrap_spec=importlib.util.spec_from_file_location('windows_daily_bootstrap',common_path)
    bootstrap=importlib.util.module_from_spec(bootstrap_spec);bootstrap_spec.loader.exec_module(bootstrap)
    bootstrap.validate(manifest)
    if manifest['schema'] != 2 or manifest['case'] != case.name:
        raise ValueError('manifest_identity_mismatch')
    start, latest, end = [parse_utc(manifest[k]) for k in
                         ('window_start_utc', 'latest_start_utc', 'window_end_utc')]
    if not start <= now <= latest < end or (end-start).total_seconds() != 24305:
        raise ValueError('outside_authorized_start_window')
    expected = {'source.py','health.py','run-spec.json','production-config.json','controller.py','bootstrap.py'}
    if set(manifest['files']) != expected:
        raise ValueError('manifest_files_invalid')
    for name, info in manifest['files'].items():
        path = case/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
            raise ValueError('diagnostic_file_hash_mismatch')
    configure(manifest)
    for info in manifest['artifacts']:
        path = (ROOT/info['relative_path']).resolve()
        if not path.is_relative_to(ROOT.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
            raise ValueError('runtime_artifact_hash_mismatch')
    spec = json.loads((case/'run-spec.json').read_text(encoding='utf-8'))
    for key in ('window_start_utc','latest_start_utc','window_end_utc'):
        if parse_utc(spec[key]) != parse_utc(manifest[key]):
            raise ValueError('window_mismatch')
    if spec['run_id'] != manifest['run_nonce']:
        raise ValueError('run_identity_mismatch')
    return manifest, spec, end


def read_health_text(path):
    """Atomic replacement reader: allow the writer to replace an open file on Windows."""
    # https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
    if os.name != 'nt':
        return path.read_text(encoding='utf-8')
    import msvcrt
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle.restype = W.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)
    if handle == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        return stream.read()


def safe_file_error(exc):
    return {'error_type': type(exc).__name__,
            'errno': getattr(exc, 'errno', None), 'winerror': getattr(exc, 'winerror', None)}


class PhaseWatchdog:
    def __init__(self, case, run_id, end, stage_seconds=45, health_seconds=5):
        self.case, self.run_id, self.end = case, run_id, end
        self.stage_seconds, self.health_seconds = stage_seconds, health_seconds
        self.started = time.monotonic()
        self.first_stage = None
        self.last_sequence = 0
        self.last_phase = None
        self.phase_started = None
        self.last_poll = self.started
        self.last_good_health_time = None
        self.last_good_health_read_at = None
        self.health_read_errors_total = 0
        self.health_read_errors_consecutive = 0
        self.health_read_errors_max_consecutive = 0
        self.first_health_read_error = None
        self.last_health_read_error = None

    def diagnostics(self):
        return {'health_deadline_seconds': self.health_seconds,
                'health_read_errors_total': self.health_read_errors_total,
                'health_read_errors_consecutive': self.health_read_errors_consecutive,
                'health_read_errors_max_consecutive': self.health_read_errors_max_consecutive,
                'first_health_read_error': self.first_health_read_error,
                'last_health_read_error': self.last_health_read_error,
                'last_good_health_monotonic': self.last_good_health_time,
                'last_good_health_read_at_monotonic': self.last_good_health_read_at,
                'streaming_phase_started_monotonic': self.phase_started if self.last_phase == 'streaming' else None}

    def check_health(self, stamp, now):
        try:
            value = json.loads(read_health_text(self.case/'health.json'))
        except (OSError, ValueError) as exc:
            completed = time.monotonic()
            self.health_read_errors_total += 1
            self.health_read_errors_consecutive += 1
            self.health_read_errors_max_consecutive = max(self.health_read_errors_max_consecutive, self.health_read_errors_consecutive)
            evidence = dict(safe_file_error(exc), observed_monotonic=completed)
            self.last_health_read_error = evidence
            if self.first_health_read_error is None:
                self.first_health_read_error = evidence
            if completed < now:
                return 'watchdog_clock_regressed'
            # Failed reads cannot move either the valid timestamp or the first-stream anchor.
            anchor = self.last_good_health_time if self.last_good_health_time is not None else stamp
            if completed-anchor > self.health_seconds:
                return 'health_missing' if isinstance(exc, FileNotFoundError) else 'invalid_health_record'
            return None
        completed = time.monotonic()
        if completed < now:
            return 'watchdog_clock_regressed'
        try:
            if value['run_id'] != self.run_id or value['phase'] != 'streaming':
                return 'health_identity_mismatch'
            if value['status'] != 'observing':
                return 'sample_health_failure'
            health_time = float(value['observed_monotonic'])
        except (ValueError, KeyError, TypeError, OverflowError):
            return 'invalid_health_record'
        if not math.isfinite(health_time) or health_time > completed+0.5 or completed-health_time > self.health_seconds:
            return 'health_stale'
        if health_time < stamp or (self.last_good_health_time is not None and health_time < self.last_good_health_time):
            return 'health_clock_regressed'
        self.last_good_health_time = health_time
        self.last_good_health_read_at = completed
        self.health_read_errors_consecutive = 0
        return None

    def __call__(self):
        now = time.monotonic()
        if now < self.last_poll:
            return 'watchdog_clock_regressed'
        self.last_poll = now
        if datetime.now(timezone.utc) > self.end:
            # Brief time solely to flush the end-of-window result; no extension of sample window.
            if (datetime.now(timezone.utc)-self.end).total_seconds() > 10:
                return 'window_end_cleanup_deadline'
        path = self.case/'stages.jsonl'
        if not path.exists():
            return 'initialization_deadline' if now-self.started > self.stage_seconds else None
        try:
            raw = path.read_bytes()
            lines = raw.split(b'\n')[:-1]  # a partially written final line cannot advance the stage
            if not lines:
                return 'initialization_deadline' if now-self.started > self.stage_seconds else None
            if len(raw) > 32768 or len(lines) > 7:
                return 'invalid_stage_history'
            previous = None
            for index, line in enumerate(lines, 1):
                item = json.loads(line)
                if item['run_id'] != self.run_id or item['sequence'] != index:
                    return 'stage_identity_or_sequence_mismatch'
                phase = item['phase']
                if (previous is None and phase != 'initializing') or (previous is not None and
                    phase not in {'initializing':{'daily_context','failed'},'daily_context':{'subscribing','failed'},'subscribing':{'initial_snapshot','failed'},'initial_snapshot':{'streaming','failed'},
                                  'streaming':{'completed','failed'},'completed':set(),'failed':set()}[previous]):
                    return 'invalid_stage_transition'
                previous = phase
            stamp = float(item['phase_started_monotonic'])
            if not math.isfinite(stamp) or not self.started-5 <= stamp <= now+0.5:
                return 'invalid_stage_clock'
            if len(lines) < self.last_sequence:
                return 'stage_history_rewound'
            if len(lines) == self.last_sequence and stamp != self.phase_started:
                return 'stage_deadline_rewritten'
            self.last_sequence, self.last_phase, self.phase_started = len(lines), phase, stamp
            if phase in {'initializing','daily_context','subscribing','initial_snapshot'}:
                # Initial stage cannot postpone the time counted from controller initialization.
                base = min(stamp, self.started) if phase == 'initializing' else stamp
                if now-base > (600 if phase == 'daily_context' else self.stage_seconds):
                    return phase+'_deadline'
            elif phase == 'streaming':
                return self.check_health(stamp, now)
            elif phase == 'failed':
                return 'sample_reported_failure'
            elif phase == 'completed':
                if datetime.now(timezone.utc) < self.end:
                    return 'sample_completed_early'
        except (OSError, ValueError, KeyError, TypeError):
            return 'invalid_stage_record'
        return None


def terminal_fault(watchdog, end, now=None):
    fault = watchdog()
    if fault:
        return fault
    if watchdog.last_phase != 'completed' or (now or datetime.now(timezone.utc)) < end:
        return 'missing_complete_window_terminal_stage'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    args = parser.parse_args()
    case = args.case.resolve()
    manifest, spec, end = verify_manifest(case)
    if case != ROOT/manifest['case']:
        raise ValueError('unexpected_case')
    helper_sha = manifest['files']['health.py']['sha256']
    config_sha = manifest['files']['run-spec.json']['sha256']
    extra = dict(run_nonce=manifest['run_nonce'], helper_sha256=helper_sha,
                 config_sha256=config_sha, window_start_utc=manifest['window_start_utc'],
                 window_end_utc=manifest['window_end_utc'])
    watchdog = PhaseWatchdog(case, manifest['run_nonce'], end)
    result = run_case(case, seconds=min(MAX_RUNTIME_SECONDS, (end-datetime.now(timezone.utc)).total_seconds()+10),
                      expected_hash=manifest['files']['source.py']['sha256'],
                      watchdog=watchdog, extra_result=extra)
    if result['status'] == 'completed':
        final_fault = terminal_fault(watchdog, end)
        if final_fault:
            result['status'] = 'failed'
            result['watchdog_reason'] = final_fault or 'missing_complete_window_terminal_stage'
    result['helper_unchanged'] = hashlib.sha256((case/'health.py').read_bytes()).hexdigest() == helper_sha
    result['config_unchanged'] = hashlib.sha256((case/'run-spec.json').read_bytes()).hexdigest() == config_sha
    result['all_inputs_unchanged'] = all(hashlib.sha256((case/name).read_bytes()).hexdigest()==info['sha256']
                                         for name, info in manifest['files'].items())
    result['health_read_diagnostics'] = watchdog.diagnostics()
    # This is lifecycle evidence, never a declaration of market-data acceptance.
    write_json(case/'run_result.json', result, exclusive=False)
    print(json.dumps({key:result.get(key) for key in ('status','child_exited','job_active_processes','run_nonce')}))
    return 0 if result['status'] == 'completed' else 4


if __name__ == '__main__':
    raise SystemExit(main())
