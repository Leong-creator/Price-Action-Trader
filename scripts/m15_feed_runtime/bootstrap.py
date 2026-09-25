"""Portable manifest validation shared by unchanged per-day runtime source files."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

SCHEMA = 2
RUNTIME_NAMES = ('bootstrap.py', 'run_once.py', 'guardian.py', 'controller.py',
                 'bridge_lifecycle.py', 'daemon_launch.py', 'launch_host.py',
                 'clock_preflight.py', 'm15_feed_clock.py', 'health.py')


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def read_regular(path):
    path=Path(path)
    require(path.is_file() and not path.is_symlink(), 'manifest_regular_file_required')
    return path.read_bytes()


def digest(path):
    return hashlib.sha256(read_regular(path)).hexdigest()


def utc(value):
    value=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(value.tzinfo is not None and value.utcoffset()==timedelta(0), 'manifest_utc_required')
    return value


def validate(manifest):
    require(manifest.get('schema') == SCHEMA, 'manifest_schema_invalid')
    day=manifest['market_date']
    require(re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) is not None, 'market_date_invalid')
    require(manifest['case']=='daily-'+day, 'daily_case_identity_invalid')
    require(re.fullmatch(r'[0-9a-f-]{36}',manifest['run_nonce']) is not None, 'run_nonce_invalid')
    start,latest,end=[utc(manifest[k]) for k in ('window_start_utc','latest_start_utc','window_end_utc')]
    opening,closing=[utc(manifest[k]) for k in ('regular_open_utc','regular_close_utc')]
    require(opening.date().isoformat()==closing.date().isoformat()==day and opening.weekday()<5,
            'non_trading_date_invalid')
    require(day not in manifest['calendar']['market_holidays'], 'market_holiday_refused')
    require(day not in manifest['calendar']['early_close_dates'], 'early_close_not_supported')
    require(int(day[:4]) in manifest['calendar']['supported_years'], 'calendar_year_not_verified')
    require(opening.hour in (13,14) and opening.minute==30 and opening.second==0
            and closing-opening==timedelta(hours=6,minutes=30), 'normal_session_hours_invalid')
    require(start==opening-timedelta(minutes=15) and latest==start+timedelta(seconds=60)
            and end==closing+timedelta(seconds=5), 'daily_window_invalid')
    layout=manifest['layout']
    archive=Path(layout['archive'])
    require(archive.name==day and archive.parent==Path(layout['sessions_root']), 'session_directory_invalid')
    require(not archive.is_relative_to(Path(layout['repo_root'])), 'session_must_be_outside_repository')
    require(Path(layout['transfer'])==archive/'credential-transfer.private.json', 'transfer_path_invalid')
    require(Path(manifest['consumer']['output_dir'])==archive/'consumer-output', 'consumer_output_invalid')
    require(manifest.get('account_access') is False and manifest.get('order_access') is False and manifest.get('automatic_retry') is False
            and manifest.get('automatic_source_fallback') is False,
            'daily_feed_must_be_read_only')
    return start,latest,end


def load_manifest(path, expected_hash=None):
    path=Path(path)
    require(path.name=='manifest.json', 'manifest_filename_invalid')
    raw=read_regular(path)
    if expected_hash is not None:
        require(hashlib.sha256(raw).hexdigest()==expected_hash, 'manifest_hash_mismatch')
    manifest=json.loads(raw)
    validate(manifest)
    allowed=Path(manifest['layout']['archive_unc'] if os.name=='nt' else manifest['layout']['archive'])/'manifest.json'
    require(path==allowed, 'manifest_path_not_authorized')
    return manifest


def sibling(path, name):
    spec=importlib.util.spec_from_file_location(name,Path(path))
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def runtime_module(directory, filename, manifest, name):
    directory=Path(directory)
    entries={item['relative_path']:item['sha256'] for item in manifest['runner']['integrity_files']}
    require(filename in entries and digest(directory/filename)==entries[filename], 'runtime_module_changed')
    return sibling(directory/filename,name)
