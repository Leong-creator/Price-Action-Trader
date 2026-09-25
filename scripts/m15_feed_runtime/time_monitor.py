"""Fixed-cadence clock evidence; no SDK, retries, or consumer-loop blocking."""
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import threading
import time


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


class Monitor:
    def __init__(self,archive,windows_python,manifest,*,now=time.time,monotonic=time.monotonic,collect=None):
        self.archive=Path(archive);self.windows_python=windows_python;self.manifest=manifest
        self.now=now;self.monotonic=monotonic
        self.start=datetime.fromisoformat(manifest['window_start_utc']).timestamp()
        self.end=datetime.fromisoformat(manifest['window_end_utc']).timestamp()
        self.anchor=monotonic()-(now()-self.start)
        self.pending=list(range(1800,int(self.end-self.start),1800))
        self.thread=None;self.failure=None;self.lock=threading.Lock();self.paths=[]
        self.adapter=load(self.archive/'clock_preflight.py','monitor_clock_adapter')
        self.collect=collect or self.adapter.load_core(self.archive).collect_time_quality
        startup=self.archive/'clock/startup/assessment.json'
        self.paths.append(startup)
        self.closed=False

    def sample(self,checkpoint,offset):
        target=self.archive/'clock'/('final' if checkpoint=='final' else 'periodic-%06d'%offset)
        try:
            result=self.collect(self.windows_python,target,
                binding=self.adapter.make_binding(self.archive,checkpoint,offset))
            with self.lock:
                self.paths.append(target/'assessment.json')
                if result.get('reception_allowed') is not True:self.failure='clock_reception_not_allowed'
        except BaseException as exc:
            with self.lock:self.failure='clock_measurement_failed'
            target.parent.mkdir(exist_ok=True)
            error=target.parent/(target.name+'-failure.json')
            with error.open('x') as out:
                json.dump({'checkpoint':checkpoint,'scheduled_elapsed_seconds':offset,
                           'error_type':type(exc).__name__,'reception_allowed':False},out)

    def poll(self):
        if self.failure:return self.failure
        if self.closed:return None
        if self.thread is not None and self.thread.is_alive():return None
        if self.pending and self.monotonic()>=self.anchor+self.pending[0]:
            offset=self.pending.pop(0)
            self.thread=threading.Thread(target=self.sample,args=('periodic',offset),daemon=True)
            self.thread.start()
        return self.failure

    def finish(self):
        self.closed=True
        if self.thread is not None:
            self.thread.join(timeout=35)
            if self.thread.is_alive():self.failure='clock_measurement_exit_unknown'
        if self.now()>=self.end and self.failure!='clock_measurement_exit_unknown':
            self.sample('final',int(self.end-self.start))
        assessments=[]
        for path in self.paths:
            try:assessments.append(json.loads(path.read_text()))
            except (OSError,ValueError):self.failure=self.failure or 'clock_evidence_missing'
        return {'assessments':[str(p) for p in self.paths],
                'quality_passed':bool(assessments) and not self.failure and all(a.get('quality_passed') is True for a in assessments),
                'reception_allowed':not self.failure and all(a.get('reception_allowed') is True for a in assessments),
                'failure':self.failure,'remaining_periodic_offsets':self.pending}
