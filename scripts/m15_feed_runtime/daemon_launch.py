"""One detached attempt, with private standard streams and cooperative signal shutdown."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import sys
import time

ARCHIVE=None
_PENDING=[]
_STOP=False
_LOG=None


def save_new(path, value):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as out:
        json.dump(value,out);out.write('\n');out.flush();os.fsync(out.fileno())


def event(kind, **fields):
    if _LOG is not None:
        data=dict(kind=kind,observed_at=datetime.now(timezone.utc).isoformat(),pid=os.getpid(),**fields)
        os.write(_LOG,(json.dumps(data)+'\n').encode());os.fsync(_LOG)


def signal_handler(number,_frame):
    # No exception, filesystem or process operations in the handler.
    global _STOP
    _STOP=True
    _PENDING.append(number)


def stop_requested():
    while _PENDING:
        number=_PENDING.pop(0)
        event('termination_signal',signal_number=number,signal_name=signal.Signals(number).name)
    return _STOP


def identity():
    # stat comm may include spaces or parentheses: parse after its last ')'.
    data=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    return {'pid':os.getpid(),'parent_pid':os.getppid(),'session_id':os.getsid(0),
            'process_group_id':os.getpgrp(),'proc_start_ticks':int(data[19])}


def detach(archive, run_id, manifest_sha, callback, *, ack_seconds=5):
    """callback is an internal offline seam; CLI always runs the pinned run_once."""
    archive=Path(archive)
    reservation={'run_nonce':run_id,'manifest_sha256':manifest_sha,'launcher_pid':os.getpid(),'launch_requested_at':datetime.now(timezone.utc).isoformat()}
    save_new(archive/'launch-reservation.json',reservation)
    read_fd,write_fd=os.pipe()
    child=os.fork()
    if child:
        os.close(write_fd)
        try:
            ready,_,_=select.select([read_fd],[],[],ack_seconds)
            if not ready:
                raise RuntimeError('daemon_ack_timeout_reservation_retained')
            raw=os.read(read_fd,16384)
            ack=json.loads(raw)
            if ack.get('run_nonce')!=run_id or ack.get('manifest_sha256')!=manifest_sha or ack.get('ready') is not True:
                raise RuntimeError('daemon_ack_invalid_reservation_retained')
            if type(ack.get('pid')) is not int or type(ack.get('proc_start_ticks')) is not int:
                raise RuntimeError('daemon_ack_identity_invalid')
            os.waitpid(child,0)
            return ack
        finally:
            os.close(read_fd)
    try:
        os.close(read_fd)
        os.setsid()
        grandchild=os.fork()
        if grandchild:os._exit(0)
        os.chdir(archive)
        os.umask(0o077)
        null=os.open('/dev/null',os.O_RDONLY)
        stdout=os.open(archive/'daemon-stdout.private',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        stderr=os.open(archive/'daemon-stderr.private',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        for source,target in ((null,0),(stdout,1),(stderr,2)):os.dup2(source,target)
        for raw_fd in os.listdir('/proc/self/fd'):
            fd=int(raw_fd)
            if fd not in (0,1,2,write_fd):
                try:os.close(fd)
                except OSError:pass
        global _LOG
        _LOG=os.open(archive/'daemon-events.jsonl',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        sys.modules['pat_launch_state']=sys.modules[__name__]
        for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,signal_handler)
        ack=dict(reservation,**identity(),ready=True)
        save_new(archive/'daemon-started.json',ack)
        event('daemon_started',run_nonce=run_id,manifest_sha256=manifest_sha)
        try:os.write(write_fd,(json.dumps(ack)+'\n').encode())
        except BrokenPipeError:event('launcher_ack_pipe_closed')
        os.close(write_fd)
        code=4
        try:
            code=int(callback())
        except BaseException as exc:
            event('unhandled_exception',error_type=type(exc).__name__)
        finally:
            stop_requested()
            event('daemon_finished',exit_code=code,termination_requested=_STOP)
            save_new(archive/'daemon-result.json',dict(ack,exit_code=code,termination_requested=_STOP))
        os._exit(code)
    except BaseException:
        # No unverified lifetime cleanup here: reservation/fence are evidence.
        os._exit(70)


def wait_host_exit(archive,run_id,sha,*,seconds=20):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if stop_requested():raise RuntimeError('signal_before_host_handoff')
        path=Path(archive)/'host-exit-proof.json'
        if path.exists():
            if path.is_symlink():raise RuntimeError('host_proof_symlink')
            proof=json.loads(path.read_text())
            mine=identity()
            spawned=json.loads((Path(archive)/'host-spawned.json').read_text())
            started=json.loads((Path(archive)/'daemon-started.json').read_text())
            exited_at=datetime.fromisoformat(proof['host_exited_at'])
            requested_at=datetime.fromisoformat(started['launch_requested_at'])
            if exited_at.tzinfo is None or requested_at.tzinfo is None:
                raise RuntimeError('host_exit_proof_time_invalid')
            if (proof.get('run_nonce')!=run_id or proof.get('manifest_sha256')!=sha
                or proof.get('host_exit_verified') is not True or proof.get('host_exitcode')!=0
                or type(proof.get('host_pid')) is not int or proof['host_pid'] <= 0
                or spawned.get('host_pid')!=proof['host_pid']
                or spawned.get('run_nonce')!=run_id or spawned.get('manifest_sha256')!=sha
                or spawned.get('wrapper_pid')!=proof.get('wrapper_pid')
                or proof.get('daemon_pid')!=mine['pid']
                or proof.get('daemon_proc_start_ticks')!=mine['proc_start_ticks']):
                raise RuntimeError('host_exit_proof_invalid')
            event('host_exit_proven',host_pid=proof.get('host_pid'))
            return proof
        time.sleep(.1)
    raise RuntimeError('host_exit_proof_deadline_no_sdk')


def run_pinned(manifest_path,sha):
    manifest=json.loads(Path(manifest_path).read_text())
    wait_host_exit(ARCHIVE,manifest['run_nonce'],sha)
    spec=importlib.util.spec_from_file_location('detached_run_once',ARCHIVE/'run_once.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    result=module.run_once(manifest_path,sha)
    return 0 if result['status']=='completed' else 4


def main():
    global ARCHIVE
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--manifest-sha256',required=True)
    args=parser.parse_args()
    raw=args.manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.manifest_sha256:raise RuntimeError('manifest_hash_mismatch')
    pinned=json.loads(raw)
    hashes={e['relative_path']:e['sha256'] for e in pinned['runner']['integrity_files']}
    common_path=Path(__file__).with_name('bootstrap.py')
    if common_path.is_symlink() or hashlib.sha256(common_path.read_bytes()).hexdigest()!=hashes['bootstrap.py']:raise RuntimeError('bootstrap_source_changed')
    common_spec=importlib.util.spec_from_file_location('launch_manifest',Path(__file__).with_name('bootstrap.py'))
    common=importlib.util.module_from_spec(common_spec);common_spec.loader.exec_module(common)
    manifest=common.load_manifest(args.manifest,args.manifest_sha256)
    ARCHIVE=Path(manifest['layout']['archive'])
    payload=args.manifest.read_bytes()
    if hashlib.sha256(payload).hexdigest()!=args.manifest_sha256:raise RuntimeError('manifest_hash_mismatch')
    manifest=json.loads(payload)
    # Pin runner code before detaching; run_once verifies all dependencies again before any SDK.
    entries={e['relative_path']:e['sha256'] for e in manifest['runner']['integrity_files']}
    for name in ('run_once.py','daemon_launch.py'):
        path=ARCHIVE/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=entries[name]:raise RuntimeError('launcher_source_changed')
    start=datetime.fromisoformat(manifest['window_start_utc']).timestamp()
    latest=datetime.fromisoformat(manifest['latest_start_utc']).timestamp()
    if not start<=time.time()<=latest:raise RuntimeError('outside_launch_window')
    ack=detach(ARCHIVE,manifest['run_nonce'],args.manifest_sha256,
               lambda:run_pinned(args.manifest,args.manifest_sha256))
    print(json.dumps(ack))
    return 0

if __name__=='__main__':raise SystemExit(main())
