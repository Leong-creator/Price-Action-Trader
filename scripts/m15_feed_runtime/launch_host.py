"""Native Windows handoff: prove the WSL launch host exited before daemon Windows I/O."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

LINUX_ARCHIVE=ARCHIVE=None


def save_new(path,record):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(record,stream);stream.flush();os.fsync(stream.fileno())


def publish_proof(archive,proof):
    temporary=archive/'host-exit-proof.pending'
    save_new(temporary,proof)
    # Windows rename refuses an existing destination; never replace a previous proof.
    os.rename(temporary,archive/'host-exit-proof.json')


def launch(manifest,sha,*,archive=None,popen=subprocess.Popen,command=None):
    archive=Path(archive or manifest['layout']['archive_unc'])
    linux_archive=manifest['layout']['archive']
    distribution=manifest['layout']['distribution'];user=manifest['layout']['user']
    if os.name!='nt':raise RuntimeError('native_windows_host_required')
    if (archive/'host-exit-proof.json').exists() or (archive/'host-launch-started.json').exists():raise RuntimeError('host_launch_already_used')
    record={'run_nonce':manifest['run_nonce'],'manifest_sha256':sha,'wrapper_pid':os.getpid()}
    save_new(archive/'host-launch-started.json',record)
    command=command or [r'C:\Windows\System32\wsl.exe','--distribution',distribution,'--user',user,'--exec',
             '/usr/bin/python3','-I','-B',linux_archive+'/daemon_launch.py',
             '--manifest',linux_archive+'/manifest.json','--manifest-sha256',sha]
    proc=None
    result=dict(record,status='failed',host_exit_verified=False)
    try:
        proc=popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        save_new(archive/'host-spawned.json',dict(record,host_pid=proc.pid))
        stdout,stderr=proc.communicate(timeout=15)
        result.update(host_pid=proc.pid,host_exitcode=proc.returncode,host_exit_verified=True)
        if proc.returncode!=0:raise RuntimeError('wsl_launch_host_failed')
        ack=json.loads(stdout.decode('utf-8-sig'))
        if (ack.get('ready') is not True or ack.get('run_nonce')!=manifest['run_nonce']
            or ack.get('manifest_sha256')!=sha or type(ack.get('pid')) is not int
            or type(ack.get('proc_start_ticks')) is not int):raise RuntimeError('daemon_ack_invalid')
        proof=dict(record,host_pid=proc.pid,host_exitcode=0,host_exit_verified=True,
                   host_exited_at=datetime.now(timezone.utc).isoformat(),daemon_pid=ack['pid'],
                   daemon_proc_start_ticks=ack['proc_start_ticks'])
        publish_proof(archive,proof)
        result.update(status='handoff_completed',daemon_pid=ack['pid'])
    except BaseException as exc:
        result['error_type']=type(exc).__name__
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5);result['host_exit_verified']=True;result['host_exitcode']=proc.returncode
            except subprocess.TimeoutExpired:result['host_exit_verified']=False
        # Failure never publishes success proof and never starts or retries the SDK.
    save_new(archive/'host-launch-result.json',result)
    return result


def main():
    global ARCHIVE,LINUX_ARCHIVE
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True,type=Path);parser.add_argument('--manifest-sha256',required=True)
    args=parser.parse_args()
    raw=args.manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.manifest_sha256:raise RuntimeError('manifest_hash_mismatch')
    pinned=json.loads(raw)
    hashes={e['relative_path']:e['sha256'] for e in pinned['runner']['integrity_files']}
    common_path=Path(__file__).with_name('bootstrap.py')
    if common_path.is_symlink() or hashlib.sha256(common_path.read_bytes()).hexdigest()!=hashes['bootstrap.py']:raise RuntimeError('bootstrap_source_changed')
    common_spec=importlib.util.spec_from_file_location('native_manifest',Path(__file__).with_name('bootstrap.py'))
    common=importlib.util.module_from_spec(common_spec);common_spec.loader.exec_module(common)
    manifest=common.load_manifest(args.manifest,args.manifest_sha256)
    ARCHIVE=Path(manifest['layout']['archive_unc']);LINUX_ARCHIVE=manifest['layout']['archive']
    payload=args.manifest.read_bytes()
    if hashlib.sha256(payload).hexdigest()!=args.manifest_sha256:raise RuntimeError('manifest_hash_mismatch')
    manifest=json.loads(payload)
    entries={entry['relative_path']:entry['sha256'] for entry in manifest['runner']['integrity_files']}
    for name in ('launch_host.py','daemon_launch.py'):
        if hashlib.sha256((ARCHIVE/name).read_bytes()).hexdigest()!=entries[name]:raise RuntimeError('launcher_source_changed')
    start=datetime.fromisoformat(manifest['window_start_utc']);latest=datetime.fromisoformat(manifest['latest_start_utc'])
    if not start<=datetime.now(timezone.utc)<=latest:raise RuntimeError('outside_launch_window')
    result=launch(manifest,args.manifest_sha256);print(json.dumps(result))
    return 0 if result['status']=='handoff_completed' else 4

if __name__=='__main__':raise SystemExit(main())
