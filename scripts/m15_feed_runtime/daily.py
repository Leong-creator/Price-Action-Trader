"""Prepare immutable daily bundles and inspect them without constructing an SDK."""
from __future__ import annotations
from datetime import datetime, date, time as dt_time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import uuid
from zoneinfo import ZoneInfo

from scripts.m15_feed_runtime import bootstrap

STATE_NAMES=('m15_sdk_submission_journal.jsonl','m15_longbridge_sdk_runtime.json',
             'm15_runtime_boot_audit.jsonl','m15_sdk_formal_test_epoch.json',
             'm15_longbridge_virtual_account_epoch.json')
REPO=Path(__file__).resolve().parents[2]
# Daily copies are byte-identical, version-controlled modules, never text templates.
BUNDLE_MODULES=('bootstrap.py','run_once.py','guardian.py','controller.py','bridge_lifecycle.py',
                'daemon_launch.py','launch_host.py','clock_preflight.py','health.py','time_monitor.py')


def require(ok,code):
    if not ok:raise ValueError(code)


def read_json(path):
    return json.loads(bootstrap.read_regular(Path(path)))


def write_new(path, value):
    path=Path(path)
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as out:
        json.dump(value,out,indent=2,sort_keys=True);out.write('\n');out.flush();os.fsync(out.fileno())


def copy_new(source,target):
    data=bootstrap.read_regular(source)
    with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as out:
        out.write(data);out.flush();os.fsync(out.fileno())
    require(bootstrap.digest(source)==bootstrap.digest(target),'bundle_copy_changed')


def resolve(path,root=REPO):
    value=Path(path).expanduser()
    return value if value.is_absolute() else root/value


def config_at(path,root=REPO):
    path=resolve(path,root)
    value=read_json(path)
    require(value.get('schema_version')=='m15.daily-feed.v1','daily_config_schema_invalid')
    for key in ('account_access','order_access','automatic_retry','automatic_source_fallback'):
        require(value.get(key) is False,'daily_feed_authority_invalid')
    require(value.get('launch_lead_minutes')==15 and value.get('latest_start_slack_seconds')==60,
            'daily_start_policy_invalid')
    sessions=resolve(value['sessions_root'],root).resolve()
    require(not sessions.is_relative_to(root.resolve()),'sessions_must_be_outside_repository')
    return path,value


def calendar_for(config,day,root=REPO):
    from scripts.m15_longbridge_sdk_runtime_lib import load_config,required_daily_context_date
    production=load_config(resolve(config['production_config'],root))
    day=date.fromisoformat(day)
    require(day.year in config['calendar_years'],'calendar_year_not_verified')
    require(day.weekday()<5 and day.isoformat() not in production.market_holidays,'non_trading_day')
    require(day.isoformat() not in config['early_close_dates'],'early_close_not_supported')
    ny=ZoneInfo('America/New_York')
    opening=datetime.combine(day,dt_time(9,30),ny).astimezone(timezone.utc)
    closing=datetime.combine(day,dt_time(16),ny).astimezone(timezone.utc)
    require(production.regular_session_start_time=='09:30' and production.regular_session_end_time=='16:00',
            'production_session_hours_changed')
    return production,{
        'market_date':day.isoformat(),'market_open_utc':opening.isoformat(),'market_close_utc':closing.isoformat(),
        'regular_open_utc':opening.isoformat(),'regular_close_utc':closing.isoformat(),
        'window_start_utc':(opening-timedelta(minutes=15)).isoformat(),
        'latest_start_utc':(opening-timedelta(minutes=14)).isoformat(),
        'window_end_utc':(closing+timedelta(seconds=5)).isoformat(),
        'required_daily_date':required_daily_context_date(opening,production.market_holidays),
    }


def unc(path,distribution):
    require(Path(path).is_absolute(),'unc_requires_absolute_linux_path')
    return str(PureWindowsPath('\\\\wsl.localhost')/distribution/str(path).lstrip('/'))


def verify_source_deployment(config_path,config,root=REPO):
    from scripts.m15_deployment_governance_lib import verify_manifest
    path=resolve(config.get('deployment_manifest','reports/runtime/m15_daily_feed_deployment_manifest.json'),root)
    result=verify_manifest(config_path,manifest_path=path,root=root)
    require(result.get('verified') is True,'daily_source_deployment_unverified')
    return path,read_json(path)


def prepare(config_path,market_date,*,root=REPO,verify_deployment=verify_source_deployment):
    root=Path(root).resolve()
    config_path,config=config_at(config_path,root)
    production,calendar=calendar_for(config,market_date,root)
    from scripts.m15_longbridge_sdk_runtime_lib import configured_symbols
    symbols=list(configured_symbols(production))
    require(len(symbols)==147 and len(set(symbols))==147,'production_universe_changed')
    deployment_path,deployment=verify_deployment(config_path,config,root)
    receipt_path=resolve(config['windows_environment_receipt'],root)
    require(bootstrap.digest(receipt_path)==config['windows_environment_receipt_sha256'],'windows_environment_receipt_changed')
    environment=read_json(receipt_path)
    windows_root=Path(environment['windows_root_mnt'])
    for row in environment['artifacts']:
        require(bootstrap.digest(windows_root/row['relative_path'])==row['sha256'],'windows_environment_changed')
    for row in environment['base_integrity_files']:
        require(bootstrap.digest(Path(row['path']))==row['sha256'],'windows_base_python_changed')
    sessions=resolve(config['sessions_root'],root)
    archive=sessions/market_date
    case='daily-'+market_date
    windows_case=windows_root/case
    require(not archive.exists() and not windows_case.exists(),'daily_bundle_already_exists')
    transfer=resolve(config['credential_transfer_plan'],root)
    transfer_data=read_json(transfer)
    require(len(transfer_data['files'])==2,'credential_transfer_plan_invalid')
    sessions.mkdir(mode=0o700,parents=True,exist_ok=True)
    archive.mkdir(mode=0o700)
    # A partial prepare is never silently reused. It has no SDK or credentials.
    windows_case.mkdir()
    state_root=resolve(production.output_dir,root)
    layout=dict(archive=str(archive),archive_unc=unc(archive,config['distribution']),sessions_root=str(sessions),
        additional_windows_fences=config.get('additional_windows_fences',[]),
        repo_root=str(root),source_home=config['source_home'],distribution=config['distribution'],user=config['user'],
        windows_root_mnt=str(windows_root),windows_root_native=environment['windows_root_native'],
        windows_home_mnt=environment['windows_home_mnt'],windows_home_native=environment['windows_home_native'],
        base_python_root_mnt=environment['base_python_root_mnt'],base_python_native=environment['base_python_native'],
        lock=str(Path(config['source_home'])/'.cache/price-action-trader/m15_sdk_quote_subscription.lock'),
        fence=str(Path(config['source_home'])/'.cache/price-action-trader/m15_windows_quote_probe_active.json'),
        transfer=str(archive/'credential-transfer.private.json'),state_root=str(state_root))
    nonce=str(uuid.uuid4())
    prod_path=resolve(config['production_config'],root)
    copy_new(prod_path,archive/'production-config.json')
    copy_new(root/'scripts/m15_windows_feed_producer.py',archive/'source.py')
    for name in BUNDLE_MODULES:
        copy_new(root/'scripts/m15_feed_runtime'/name,archive/name)
    copy_new(root/'scripts/m15_feed_clock.py',archive/'m15_feed_clock.py')
    copy_new(transfer,archive/'credential-transfer.private.json')
    copy_new(receipt_path,archive/'windows-environment-receipt.json')
    copy_new(deployment_path,archive/'source-deployment-receipt.json')
    copy_new(config_path,archive/'daily-config.json')
    spec=dict(calendar,run_id=nonce,symbols=symbols,reference_symbols=['SPY.US','QQQ.US'],
        production_config_sha256=bootstrap.digest(prod_path),schema_version=1)
    write_new(archive/'run-spec.json',spec)
    consumer_config=read_json(prod_path)
    consumer_config['outputs']={
        'output_dir':str(archive/'unused-runtime'),
        'market_events':str(archive/'consumer-output/market_events.jsonl'),
        'runtime_status':str(archive/'consumer-output/runtime.json'),
        'readonly_gate':str(archive/'consumer-output/readonly_gate.json')}
    consumer_config['market_data']['daily_context']=str(archive/'consumer-output/daily_context.jsonl')
    consumer_config['routing']['paper_order_dispatch_enabled']=False
    consumer_config['formal_test_transition']['enabled']=False
    write_new(archive/'consumer-config.json',consumer_config)
    files={}
    for name in ('source.py','health.py','run-spec.json','production-config.json','controller.py','bootstrap.py'):
        copy_new(archive/name,windows_case/name)
        files[name]={'archive_name':name,'sha256':bootstrap.digest(archive/name)}
    consumer_python=root/'.venv-m15/bin/python'
    source_paths=[consumer_python,root/'.venv-m15/pyvenv.cfg',archive/'consumer-config.json']
    for folder,pattern in (('scripts','*.py'),('src','*.py'),('config','*.json')):
        source_paths.extend(sorted((root/folder).rglob(pattern)))
    source_paths=list(dict.fromkeys(source_paths))
    consumer_script=root/'scripts/m15_windows_feed_consumer.py'
    consumer=dict(python=str(consumer_python),script=str(consumer_script),script_sha256=bootstrap.digest(consumer_script),
        config=str(archive/'consumer-config.json'),config_sha256=bootstrap.digest(archive/'consumer-config.json'),
        output_dir=str(archive/'consumer-output'),stream_path=str(windows_case/'stdout.private'),
        integrity_files=[{'path':str(p),'sha256':bootstrap.digest(p.resolve() if p==consumer_python else p)} for p in source_paths])
    runtime_names=(*BUNDLE_MODULES,'m15_feed_clock.py','daily-config.json','source-deployment-receipt.json','windows-environment-receipt.json')
    manifest=dict(schema=2,case=case,run_nonce=nonce,**{k:v for k,v in calendar.items() if k not in ('required_daily_date','market_open_utc','market_close_utc')},
        calendar=dict(market_holidays=list(production.market_holidays),early_close_dates=config['early_close_dates'],supported_years=config['calendar_years']),
        account_access=False,order_access=False,automatic_retry=False,automatic_source_fallback=False,layout=layout,files=files,consumer=consumer,
        artifacts=environment['artifacts'],
        runner=dict(integrity_files=[{'relative_path':name,'sha256':bootstrap.digest(archive/name)} for name in runtime_names],
            protected_states=[{'name':name,'sha256':bootstrap.digest(state_root/name)} for name in STATE_NAMES],
            base_integrity_files=environment['base_integrity_files'],credential_transfer_sha256=bootstrap.digest(layout['transfer']),
            deployment_receipt_path=str(deployment_path),deployment_receipt_sha256=bootstrap.digest(deployment_path),
            source_commit=deployment['head_sha'],linux_python='/usr/bin/python3',
            linux_python_sha256=bootstrap.digest(Path('/usr/bin/python3').resolve())))
    bootstrap.validate(manifest)
    write_new(archive/'manifest.json',manifest)
    copy_new(archive/'manifest.json',windows_case/'manifest.json')
    sha=bootstrap.digest(archive/'manifest.json')
    native_script=str(PureWindowsPath(layout['archive_unc'])/'launch_host.py')
    native_manifest=str(PureWindowsPath(layout['archive_unc'])/'manifest.json')
    action={'execute':environment['base_python_native'],
        'arguments':subprocess.list2cmdline(['-I','-S','-B',native_script,'--manifest',native_manifest,'--manifest-sha256',sha])}
    receipt={'schema_version':'m15.daily-feed-prepared.v1','market_date':market_date,'run_id':nonce,
        'manifest_path':str(archive/'manifest.json'),'manifest_sha256':sha,
        'task_name':config['task_name_prefix']+'-'+market_date.replace('-',''),
        'native_action':action,'start_boundary_utc':calendar['window_start_utc'],
        'end_boundary_utc':calendar['latest_start_utc'],'window_end_utc':calendar['window_end_utc'],
        'task_execution_time_limit_seconds':90,'runtime_deadline_seconds':24315,
        'sdk_started':False,'source_commit':deployment['head_sha']}
    write_new(archive/'prepared.json',receipt)
    return receipt


def today(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York')).date().isoformat()


def process_alive(record):
    try:
        pid=record['pid'];ticks=record['proc_start_ticks']
        require(type(pid) is int and pid>0 and type(ticks) is int,'daemon_identity_invalid')
        data=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
        return data[0]!='Z' and int(data[19])==ticks
    except FileNotFoundError:return False
    except (OSError,ValueError,KeyError,TypeError,IndexError):return None


def maybe(path):
    try:return read_json(path)
    except (OSError,ValueError,RuntimeError):return None


def status(config_path,market_date=None,*,root=REPO,now=None):
    now=now or datetime.now(timezone.utc);day=market_date or today(now)
    _,config=config_at(config_path,root)
    report={'schema_version':'m15.daily-feed-status.v1','market_date':day,'run_id':None,
        'state':'not_prepared','process_alive':None,'data_current':None,'received_transport_current':None,'clock_quality_passed':None,
        'last_error':None,'completion':None,'acceptance':None,'observed_at':now.isoformat()}
    try:calendar_for(config,day,root)
    except ValueError as exc:
        report.update(state='non_trading_day' if str(exc)=='non_trading_day' else 'unknown',last_error=str(exc));return report
    archive=resolve(config['sessions_root'],root)/day
    if not archive.exists():return report
    receipt=maybe(archive/'prepared.json')
    if not receipt:report.update(state='unknown',last_error='prepared_receipt_missing_or_invalid');return report
    try:
        manifest=bootstrap.load_manifest(archive/'manifest.json',receipt['manifest_sha256'])
        require(receipt['run_id']==manifest['run_nonce'],'prepared_identity_mismatch')
    except (OSError,ValueError,KeyError,RuntimeError):
        report.update(state='unknown',last_error='daily_manifest_invalid');return report
    run_id=manifest['run_nonce'];report['run_id']=run_id
    completion=maybe(archive/'completion.json');result=maybe(archive/'run-once-result.json')
    if completion:report['completion']={'path':str(archive/'completion.json'),'exit_fences_cleared':completion.get('exit_fences_cleared'),
        **{key:completion.get('run_once',{}).get(key) for key in ('exit_verified','credentials_cleaned','bounded_pipeline_passed')}}
    acceptance=maybe(archive/'feed_session_acceptance.json')
    if acceptance:report['acceptance']={'path':str(archive/'feed_session_acceptance.json'),
        'normal_full_session_observation_passed':acceptance.get('normal_full_session_observation_passed')}
    assessments=sorted((archive/'clock').glob('*/assessment.json'))
    clock_records=[maybe(path) for path in assessments]
    if clock_records:
        try:
            spec_sha=bootstrap.digest(archive/'run-spec.json')
            valid=all(c and c.get('quality_passed') is True and c.get('run_binding',{}).get('run_id')==run_id
                and c['run_binding'].get('run_spec_sha256')==spec_sha for c in clock_records)
            latest_clock=max(bootstrap.utc(c['finished_at']) for c in clock_records if c)
            age=(now-latest_clock).total_seconds()
            report['clock_quality_passed']=bool(valid and -0.5<=age<=1890)
        except (OSError,ValueError,TypeError,KeyError,RuntimeError):report['clock_quality_passed']=False
    daemon=maybe(archive/'daemon-started.json')
    if daemon and daemon.get('run_nonce')==run_id and daemon.get('manifest_sha256')==receipt['manifest_sha256']:
        report['process_alive']=process_alive(daemon)
    if result:
        if result.get('run_nonce')!=run_id:report.update(state='unknown',last_error='result_identity_mismatch');return report
        clean=result.get('exit_verified') is True and result.get('credentials_cleaned') is True
        report['state']='completed' if clean and result.get('status') in {'completed','observed_not_passed'} else 'failed'
        report['clock_quality_passed']=result.get('clock_quality_passed',report['clock_quality_passed'])
        report['last_error']=result.get('error') or result.get('cleanup_error')
        report['data_current']=False
        return report
    used=any((archive/name).exists() for name in ('launch-reservation.json','host-launch-started.json','run-once-started.json'))
    start=bootstrap.utc(manifest['window_start_utc']);latest=bootstrap.utc(manifest['latest_start_utc'])
    if not used:
        report['state']='prepared' if now<start else 'waiting' if now<=latest else 'failed'
        if now>latest:report['last_error']='launch_window_missed'
        return report
    if report['process_alive'] is not True:
        report.update(state='unknown',last_error='started_without_verified_live_daemon');return report
    live=maybe(Path(manifest['consumer']['output_dir'])/'live-status.json')
    if not live:report['state']='starting';return report
    if live.get('run_id')!=run_id:report.update(state='unknown',last_error='consumer_status_identity_mismatch');return report
    report.update(state='streaming' if live.get('phase')=='streaming' and live.get('status')=='observing' else 'starting',
        last_error=live.get('last_error'),source_receipt=live.get('last_source_receipt'),
        processing_updated_at=live.get('last_processed_at'),consumer_observed_at=live.get('observed_at'),
        counts={key:live.get(key) for key in ('bar_count','complete_boundary_count','strategy_evaluation_count','trade_count','quote_wire_symbol_count','trade_wire_symbol_count')})
    try:
        def fresh(value,limit):
            age=(now-bootstrap.utc(value)).total_seconds();return -0.5<=age<=limit
        receipts=live['last_source_receipt']
        transport=(fresh(live['observed_at'],5) and fresh(live['last_processed_at'],5)
            and all(fresh(receipts[k]['received_at'],2) for k in ('quote','trade')))
        report['received_transport_current']=transport
        qualified=live['current_freshness']
        report['data_current']=transport and all(
            fresh(qualified[k]['symbols'][symbol]['received_at'],30)
            and fresh(qualified[k]['symbols'][symbol]['source_event_at'],30)
            for k in ('qualified_quote','qualified_trade') for symbol in ('SPY.US','QQQ.US'))
        report['data_current_basis']='qualified SPY/QQQ quote and eligible intraday trade source/receipt within existing 30s reference deadline; transport within 2s; processing/status within 5s; not fresh coverage of all 147 symbols'
    except (ValueError,TypeError,KeyError,AttributeError,RuntimeError):report['data_current']=None
    if live.get('status')=='failed':report.update(state='failed',data_current=False)
    return report


def launch(config_path,market_date=None,*,root=REPO,now=None,run=subprocess.run):
    """Dispatch only the pre-registered native task, never host its Windows SDK."""
    import base64
    now=now or datetime.now(timezone.utc);day=market_date or today(now)
    config_path,config=config_at(config_path,root)
    calendar_for(config,day,root)
    verify_source_deployment(config_path,config,root)
    archive=resolve(config['sessions_root'],root)/day
    receipt=read_json(archive/'prepared.json')
    manifest=bootstrap.load_manifest(archive/'manifest.json',receipt['manifest_sha256'])
    require(receipt['run_id']==manifest['run_nonce'],'prepared_identity_mismatch')
    start,latest,_=bootstrap.validate(manifest)
    if now<start:
        return {'status':'waiting','dispatched':False,'sdk_started':False,'market_date':day,'run_id':manifest['run_nonce']}
    used=any((archive/name).exists() for name in ('launch-reservation.json','host-launch-started.json','run-once-started.json'))
    if used:
        daemon=maybe(archive/'daemon-started.json')
        if daemon and daemon.get('run_nonce')==manifest['run_nonce'] and daemon.get('manifest_sha256')==receipt['manifest_sha256'] and process_alive(daemon) is True and not (archive/'run-once-result.json').exists():
            return {'status':'already_running','dispatched':False,'sdk_started':False,'market_date':day,'run_id':manifest['run_nonce']}
    require(start<=now<=latest,'outside_launch_window')
    require(not any((archive/name).exists() for name in ('launch-reservation.json','host-launch-started.json','run-once-started.json')),'daily_launch_already_used')
    task={'name':receipt['task_name'],**receipt['native_action']}
    payload=base64.b64encode(json.dumps(task).encode()).decode()
    script="""$ErrorActionPreference='Stop'
$d=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%s'))|ConvertFrom-Json
$t=Get-ScheduledTask -TaskName $d.name -TaskPath '\\'
if (@($t.Actions).Count -ne 1 -or $t.Actions[0].Execute -cne $d.execute -or $t.Actions[0].Arguments -cne $d.arguments) {throw 'daily_task_action_mismatch'}
if ($t.Settings.RestartCount -gt 0 -or [string]$t.Settings.MultipleInstances -ne 'IgnoreNew') {throw 'daily_task_retry_policy_invalid'}
Start-ScheduledTask -InputObject $t
@{task_name=$d.name;dispatched=$true;sdk_started=$false}|ConvertTo-Json -Compress
"""%payload
    encoded=base64.b64encode(script.encode('utf-16le')).decode()
    proc=run(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
             stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
    require(proc.returncode==0,'native_daily_task_dispatch_failed')
    reply=json.loads(proc.stdout.decode('utf-8-sig'))
    require(reply.get('dispatched') is True and reply.get('task_name')==task['name'],'native_dispatch_reply_invalid')
    return dict(reply,market_date=day,run_id=manifest['run_nonce'],manifest_sha256=receipt['manifest_sha256'])
