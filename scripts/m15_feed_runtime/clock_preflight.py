"""Thin loader of the exact clock module frozen into the current run bundle."""
import hashlib
import importlib.util
import json
from pathlib import Path


def make_binding(archive, checkpoint, scheduled_elapsed_seconds=0):
    archive=Path(archive)
    data=(archive/'run-spec.json').read_bytes()
    spec=json.loads(data)
    return {'run_id':spec['run_id'],'run_spec_sha256':hashlib.sha256(data).hexdigest(),
            'window_start_utc':spec['window_start_utc'],'window_end_utc':spec['window_end_utc'],
            'checkpoint':checkpoint,'scheduled_elapsed_seconds':scheduled_elapsed_seconds}


def load_core(archive):
    path=Path(archive)/'m15_feed_clock.py'
    spec=importlib.util.spec_from_file_location('frozen_feed_clock',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(archive, *, windows_python):
    archive=Path(archive)
    (archive/'clock').mkdir(exist_ok=True)
    return load_core(archive).collect_time_quality(windows_python,archive/'clock'/'startup',
            binding=make_binding(archive,'startup'))
