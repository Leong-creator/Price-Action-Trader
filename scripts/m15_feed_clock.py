"""Bounded read-only NTP diagnostic; fixed sample count, no system clock writes.

Minimum valid RTT selection follows the clock-filter rationale of RFC 5905 §10.
This three-sample diagnostic is not the full eight-stage NTP clock algorithm.
"""
import json
import hashlib
from datetime import UTC, datetime
from pathlib import Path
import os
import select
import subprocess
import uuid
import math
import queue
import socket
import struct
import sys
import threading
import time

HOSTS = ('time.windows.com', 'time.cloudflare.com')
SAMPLES_PER_HOST = 3
SAMPLE_SPACING_SECONDS = 2.0
SOCKET_TIMEOUT_SECONDS = 2.5
MAX_CLOCK_BOUND_SECONDS = 0.5
PERIODIC_INTERVAL_SECONDS = 1800
TOTAL_BUDGET_SECONDS = 12.0  # Existing caller retains its 15-second process bound.
NTP_EPOCH = 2208988800


def decode(data, packet, t1, t4, m1, m4):
    if len(data) < 48:
        return {'valid': False, 'error': 'short_response'}
    stamp = lambda position: (struct.unpack_from('!I', data, position)[0]
        + struct.unpack_from('!I', data, position + 4)[0] / 2**32 - NTP_EPOCH)
    t2, t3 = stamp(32), stamp(40)
    delay = (t4-t1) - (t3-t2)
    offset = ((t2-t1) + (t3-t4)) / 2
    leap, version, mode, stratum = data[0] >> 6, (data[0] >> 3) & 7, data[0] & 7, data[1]
    valid = (data[24:32] == packet[40:48] and leap != 3 and 0 < stratum < 16
        and version in (3, 4) and mode == 4 and t2 > 0 and t3 >= t2 and delay >= 0
        and all(math.isfinite(x) for x in (t1,t2,t3,t4,m1,m4,delay,offset))
        and m4 >= m1 and abs((t4-t1)-(m4-m1)) < .05)
    return {'valid': valid, 'stratum': stratum, 'leap': leap, 'version': version, 'mode': mode,
            't1': t1, 't2': t2, 't3': t3, 't4': t4, 'monotonic_elapsed': m4-m1,
            'offset_seconds': offset, 'roundtrip_seconds': delay,
            'origin_matches': data[24:32] == packet[40:48],
            'kiss_of_death': stratum == 0,
            'root_delay_seconds': struct.unpack_from('!i',data,4)[0]/2**16,
            'root_dispersion_seconds': struct.unpack_from('!I',data,8)[0]/2**16}


def probe(address, deadline):
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        return {'valid': False, 'error': 'total_budget_exhausted'}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(min(SOCKET_TIMEOUT_SECONDS, remaining))
            client.connect((address, 123))
            t1, m1 = time.time(), time.monotonic()
            seconds = t1 + NTP_EPOCH
            integral = int(seconds)
            packet = bytearray(48)
            packet[0] = 35  # version 4, client mode 3
            struct.pack_into('!II', packet, 40, integral, int((seconds-integral)*2**32))
            client.send(packet)
            sent_monotonic = time.monotonic()
            local_endpoint = client.getsockname()
            data = client.recv(512)
            t4, m4 = time.time(), time.monotonic()
        return {**decode(data, packet, t1, t4, m1, m4),
                'server_ip': address, 'local_port': local_endpoint[1],
                'send_call_elapsed_seconds': sent_monotonic-m1}
    except Exception as error:
        return {'valid': False, 'server_ip': address, 'error': type(error).__name__}


def collect_host(host, deadline, out):
    try:
        address = socket.gethostbyname(host)
    except Exception as error:
        for index in range(SAMPLES_PER_HOST):
            out.put({'host': host, 'sample_index': index, 'valid': False,
                     'error': 'dns_' + type(error).__name__})
        return
    previous_start = None
    stopped = False
    for index in range(SAMPLES_PER_HOST):
        if previous_start is not None:
            delay = max(0, previous_start + SAMPLE_SPACING_SECONDS - time.monotonic())
            if delay:
                time.sleep(min(delay, max(0, deadline-time.monotonic())))
        previous_start = time.monotonic()
        if stopped:
            result = {'valid': False, 'error': 'remaining_samples_skipped_after_kiss_of_death'}
        elif previous_start >= deadline:
            result = {'valid': False, 'error': 'total_budget_exhausted'}
        else:
            result = probe(address, deadline)
        out.put({'host': host, 'sample_index': index, **result})
        stopped = stopped or result.get('kiss_of_death', False)


def select_samples(raw):
    selected = []
    for host in HOSTS:
        valid = [row for row in raw if row['host'] == host and row.get('valid') is True
                 and type(row.get('roundtrip_seconds')) in (int,float)
                 and type(row.get('offset_seconds')) in (int,float)
                 and math.isfinite(row['roundtrip_seconds']) and row['roundtrip_seconds'] >= 0
                 and math.isfinite(row['offset_seconds'])]
        if valid:
            chosen = min(valid, key=lambda row: (row['roundtrip_seconds'], row['sample_index']))
            selected.append({**chosen, 'selected_sample_index': chosen['sample_index'],
                             'selection_rule': 'minimum_valid_roundtrip_then_index'})
        else:
            selected.append({'host': host, 'valid': False, 'selected_sample_index': None,
                             'error': 'no_valid_sample', 'selection_rule': 'minimum_valid_roundtrip_then_index'})
    return selected


def collect(*, worker=collect_host, budget=TOTAL_BUDGET_SECONDS):
    wall_start, monotonic_start = time.time(), time.monotonic()
    deadline = monotonic_start + budget
    out = queue.Queue()
    for host in HOSTS:
        # DNS has no stdlib deadline. Daemon workers cannot extend process exit;
        # missing slots are explicitly reported at the fixed global deadline.
        threading.Thread(target=worker, args=(host, deadline, out), daemon=True).start()
    slots = {}
    while len(slots) < len(HOSTS)*SAMPLES_PER_HOST:
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            break
        try:
            row = out.get(timeout=remaining)
        except queue.Empty:
            break
        slots[(row['host'], row['sample_index'])] = row
    raw = [slots.get((host,index), {'host': host, 'sample_index': index, 'valid': False,
                                  'error': 'total_budget_exhausted'})
           for host in HOSTS for index in range(SAMPLES_PER_HOST)]
    wall_elapsed = time.time()-wall_start
    monotonic_elapsed = time.monotonic()-monotonic_start
    continuous = abs(wall_elapsed-monotonic_elapsed) < .05
    selected = select_samples(raw)
    if not continuous:
        selected = [{**row, 'valid': False, 'error': 'wall_clock_changed_during_collection'} for row in selected]
    return {'platform': sys.platform, 'read_only': True, 'samples': selected, 'raw_samples': raw,
            'sampling_plan': {'hosts': list(HOSTS), 'samples_per_host': SAMPLES_PER_HOST,
                              'spacing_seconds': SAMPLE_SPACING_SECONDS, 'total_budget_seconds': budget,
                              'selection_rule': 'minimum_valid_roundtrip_then_index',
                              'selection_uses_offset_or_quality_result': False},
            'collection_wall_elapsed_seconds': wall_elapsed,
            'collection_monotonic_elapsed_seconds': monotonic_elapsed,
            'wall_clock_continuous': continuous}




def _safe_error(error):
    return {'error': type(error).__name__, 'valid': False}


def _source():
    return Path(__file__).read_text(encoding='utf-8')


def _run_windows(windows_python, mode, timeout):
    result = subprocess.run([str(windows_python), '-I', '-S', '-u', '-c', _source(), mode],
                            capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('clock_windows_worker_failed')
    return json.loads(result.stdout.decode('utf-8-sig'))


def _read_line(process, buffer, deadline):
    while b'\n' not in buffer[0]:
        remaining = deadline-time.monotonic()
        if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
            raise TimeoutError('clock_handshake_timeout')
        chunk = os.read(process.stdout.fileno(), 65536)
        if not chunk:
            raise EOFError('clock_handshake_eof')
        buffer[0] += chunk
        if len(buffer[0]) > 65536:
            raise ValueError('clock_handshake_oversize')
    line, buffer[0] = buffer[0].split(b'\n', 1)
    return json.loads(line)


def _clock_server():
    # Native Windows helper self-expires even if its WSL parent disappears.
    requests = queue.Queue()
    def read_requests():
        for line in sys.stdin:
            requests.put((line,time.time(),time.monotonic()))
        requests.put(None)
    threading.Thread(target=read_requests,daemon=True).start()
    deadline=time.monotonic()+12
    print(json.dumps({'ready': True, 'platform': sys.platform, 'protocol': 1}), flush=True)
    while time.monotonic()<deadline:
        try:request=requests.get(timeout=max(.001,deadline-time.monotonic()))
        except queue.Empty:return
        if request is None:return
        line,received,mono_received=request
        message=json.loads(line)
        sent,mono_sent=time.time(),time.monotonic()
        print(json.dumps({'id': message['id'], 't2': received, 't3': sent,
                          'windows_monotonic_elapsed': mono_sent-mono_received}), flush=True)


def handshake_sample(reply, index, t1, t4, m1, m4):
    t2, t3 = reply['t2'], reply['t3']
    elapsed = reply['windows_monotonic_elapsed']
    numeric = (t1,t2,t3,t4,m1,m4,elapsed)
    if any(type(value) not in (int,float) or not math.isfinite(value) for value in numeric):
        return {'sample_index': index, 'valid': False, 'error': 'handshake_nonfinite'}
    rtt = (t4-t1)-(t3-t2)
    offset = ((t2-t1)+(t3-t4))/2
    valid = (reply['id'] == index and t3 >= t2 and elapsed >= 0 and m4 >= m1 and rtt >= 0
             and abs((t4-t1)-(m4-m1)) < .05 and abs((t3-t2)-elapsed) < .05)
    return {'sample_index': index, 'valid': valid, 't1_wsl': t1, 't2_windows': t2,
            't3_windows': t3, 't4_wsl': t4, 'wsl_monotonic_elapsed': m4-m1,
            'windows_monotonic_elapsed': elapsed, 'offset_seconds': offset,
            'roundtrip_seconds': rtt, 'offset_meaning': 'windows_minus_wsl'}


def collect_cross_clock(windows_python):
    """Three handshakes after process readiness: startup/DNS excluded from RTT."""
    process = None
    rows = []
    start_wall, start_mono = time.time(), time.monotonic()
    deadline = start_mono+10
    try:
        process = subprocess.Popen([str(windows_python), '-I', '-S', '-u', '-c', _source(), 'clock-server'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        buffer = [b'']
        greeting = _read_line(process, buffer, deadline)
        if greeting != {'ready': True, 'platform': 'win32', 'protocol': 1}:
            raise ValueError('clock_handshake_platform_invalid')
        for index in range(3):
            encoded = (json.dumps({'id': index})+'\n').encode()
            t1, m1 = time.time(), time.monotonic()
            process.stdin.write(encoded)
            process.stdin.flush()
            reply = _read_line(process, buffer, min(deadline, m1+2))
            t4, m4 = time.time(), time.monotonic()
            rows.append(handshake_sample(reply,index,t1,t4,m1,m4))
            if index < 2:
                time.sleep(.1)
    except Exception as error:
        for index in range(len(rows),3):
            rows.append({'sample_index':index, **_safe_error(error)})
    finally:
        if process is not None:
            try:process.stdin.close()
            except OSError:pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            process.stdout.close()
    good = [row for row in rows if row.get('valid')]
    selected = min(good,key=lambda row:(row['roundtrip_seconds'],row['sample_index'])) if good else None
    continuous = abs((time.time()-start_wall)-(time.monotonic()-start_mono)) < .05
    if selected is not None:
        selected = {**selected, 'selected_sample_index': selected['sample_index']}
        if not continuous:
            selected.update(valid=False,error='wall_clock_changed_during_collection')
    return {'raw_samples': rows, 'selected': selected, 'wall_clock_continuous': continuous,
            'sampling_plan': {'sample_count': 3, 'selection_rule': 'minimum_valid_roundtrip_then_index'},
            'startup_excluded': True, 'monotonic_clocks_compared_across_os': False}


def _valid(row):
    return (isinstance(row,dict) and row.get('valid') is True
            and type(row.get('offset_seconds')) in (int,float)
            and type(row.get('roundtrip_seconds')) in (int,float)
            and math.isfinite(row['offset_seconds']) and math.isfinite(row['roundtrip_seconds'])
            and row['roundtrip_seconds'] >= 0)


def assess_time_quality(windows_ntp, cross_clock):
    windows_rows = windows_ntp.get('samples', [])
    if not isinstance(windows_rows,list):windows_rows=[]
    good = [row for row in windows_rows if _valid(row)]
    identity_ok = (windows_ntp.get('platform') == 'win32' and len(windows_rows) == 2
                   and {row.get('host') for row in windows_rows if isinstance(row,dict)} == set(HOSTS))
    reception = identity_ok and bool(good) and windows_ntp.get('wall_clock_continuous') is True
    selected = cross_clock.get('selected')
    cross_valid = _valid(selected) and cross_clock.get('wall_clock_continuous') is True
    windows = []
    wsl = []
    for row in good:
        bound = abs(row['offset_seconds'])+row['roundtrip_seconds']/2
        windows.append({'host': row['host'], 'offset_seconds': row['offset_seconds'],
                        'bound_seconds': bound, 'quality_passed': bound <= MAX_CLOCK_BOUND_SECONDS})
        if cross_valid:
            offset = row['offset_seconds']+selected['offset_seconds']
            uncertainty = (row['roundtrip_seconds']+selected['roundtrip_seconds'])/2
            wsl.append({'host':row['host'],'derived_offset_seconds':offset,
                        'uncertainty_seconds':uncertainty,'bound_seconds':abs(offset)+uncertainty,
                        'quality_passed':abs(offset)+uncertainty <= MAX_CLOCK_BOUND_SECONDS})
    win_ok = (identity_ok and windows_ntp.get('wall_clock_continuous') is True
              and len(windows)==2 and all(row['quality_passed'] for row in windows))
    relation_bound = abs(selected['offset_seconds'])+selected['roundtrip_seconds']/2 if cross_valid else None
    relation_ok = cross_valid and relation_bound <= MAX_CLOCK_BOUND_SECONDS
    wsl_ok = relation_ok and len(wsl)==2 and all(row['quality_passed'] for row in wsl)
    reasons=[]
    if not reception:reasons.append('clock_no_valid_windows_sample')
    elif not win_ok:reasons.append('windows_clock_alignment_unproven')
    if not relation_ok:reasons.append('windows_wsl_relation_unproven')
    if not wsl_ok:reasons.append('wsl_clock_alignment_unproven')
    return {'reception_allowed':reception,'quality_passed':win_ok and wsl_ok,
            'quality_reason':reasons[0] if reasons else None,'quality_reasons':reasons,
            'received_for_diagnosis_only':not (win_ok and wsl_ok),
            'maximum_clock_bound_seconds':MAX_CLOCK_BOUND_SECONDS,
            'windows':{'quality_passed':win_ok,'estimates':windows},
            'wsl':{'quality_passed':wsl_ok,'estimates':wsl},
            'cross_clock':{'quality_passed':relation_ok,'bound_seconds':relation_bound,
                           'offset_meaning':'windows_minus_wsl','selected':selected},
            'samples':windows_rows,
            'scope':'Project measurement bound, not authenticated UTC accuracy or full RFC root-distance.'}


def _save(path, payload):
    with Path(path).open('x',encoding='utf-8') as handle:
        json.dump(payload,handle,indent=2,allow_nan=False)
        handle.write('\n')


def collect_time_quality(windows_python, output_dir, *, binding=None):
    """One bounded, read-only assessment. Caller must use a new output_dir each time.

    Worst case <= 30 seconds including process teardown; never blocks feed I/O
    when called in the supervisor's dedicated diagnostic subprocess/thread.
    """
    output = Path(output_dir)
    output.mkdir(parents=True,exist_ok=False)
    started_at = datetime.now(UTC).isoformat()
    measurement_id = uuid.uuid4().hex
    metadata = {'schema_version':1,'measurement_id':measurement_id,'run_binding':binding}
    try:
        windows = _run_windows(windows_python,'ntp',15)
    except Exception as error:
        windows = {'platform':'win32','samples':[], **_safe_error(error)}
    windows.update(metadata)
    _save(output/'windows-ntp.json',windows)
    try:
        cross = collect_cross_clock(windows_python)
    except Exception as error:
        cross = {'selected':None,'raw_samples':[], **_safe_error(error)}
    cross.update(metadata)
    _save(output/'windows-wsl-handshake.json',cross)
    assessment = assess_time_quality(windows,cross)
    assessment.update(started_at=started_at,finished_at=datetime.now(UTC).isoformat(),
                      evidence_dir=str(output),**metadata,
                      raw_sha256={name:hashlib.sha256((output/name).read_bytes()).hexdigest()
                          for name in ('windows-ntp.json','windows-wsl-handshake.json')})
    _save(output/'assessment.json',assessment)
    return assessment


def check(archive, *, windows_python):
    return collect_time_quality(windows_python,Path(archive)/'clock'/'startup')


def periodic_offsets(window_seconds):
    """Predetermined checkpoints; a failed measurement never adds another one."""
    return tuple(range(PERIODIC_INTERVAL_SECONDS,int(window_seconds),PERIODIC_INTERVAL_SECONDS))


def _windows_diagnostic():
    """Fixed read-only comparison; diagnostic-only, never selects acceptance result."""
    results = {}
    def call(name, args, timeout):
        try:
            result=subprocess.run(['w32tm.exe',*args],capture_output=True,timeout=timeout)
            results[name]={'returncode':result.returncode,
                'stdout':result.stdout.decode('gb18030',errors='replace'),
                'stderr':result.stderr.decode('gb18030',errors='replace')}
        except Exception as error:results[name]=_safe_error(error)
    threads=[]
    for name,args in (('status',['/query','/status','/verbose']),('peers',['/query','/peers','/verbose']),
                      ('source',['/query','/source']),('configuration',['/query','/configuration'])):
        thread=threading.Thread(target=call,args=(name,args,5),daemon=True);thread.start();threads.append(thread)
    addresses={}
    for host in HOSTS:
        try:addresses[host]=socket.gethostbyname(host)
        except Exception as error:addresses[host]=_safe_error(error)
    for host,address in addresses.items():
        if not isinstance(address,str):continue
        args=['/stripchart','/computer:'+address,'/samples:3','/period:2','/rdtsc']
        thread=threading.Thread(target=call,args=(host,args,15),daemon=True);thread.start();threads.append(thread)
    # Same resolved addresses for the custom sampler and Microsoft's probe.
    original_resolver=socket.gethostbyname
    socket.gethostbyname=lambda host:addresses[host] if isinstance(addresses[host],str) else original_resolver(host)
    try:custom=collect()
    finally:socket.gethostbyname=original_resolver
    deadline=time.monotonic()+16
    for thread in threads:thread.join(max(0,deadline-time.monotonic()))
    return {'platform':sys.platform,'read_only':True,'server_ips':addresses,'custom_ntp':custom,
            'w32tm':results,'sampling_plan':'two preselected hosts, each tool fixed three samples, no resync'}


if __name__ == '__main__':
    mode=sys.argv[1] if len(sys.argv)>1 else ''
    if mode=='ntp':print(json.dumps(collect(),allow_nan=False))
    elif mode=='clock-server':_clock_server()
    elif mode=='comparison':print(json.dumps(_windows_diagnostic(),allow_nan=False))
    else:raise SystemExit('worker mode required')
