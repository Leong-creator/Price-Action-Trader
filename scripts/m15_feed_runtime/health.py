"""Standard-library-only continuity accounting; no broker or project imports."""
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import queue
import threading
import time

UTC = timezone.utc
REFERENCES = ('SPY.US', 'QQQ.US')
# Existing production source constants; these are not newly relaxed tolerances.
CALLBACK_QUEUE_MAXSIZE = 250_000
FUTURE_TOLERANCE_SECONDS = 2


def instant(value):
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        stamp = datetime.fromtimestamp(value, UTC)
    elif isinstance(value, str):
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('event_timestamp_invalid')
    if stamp.tzinfo is None:
        raise ValueError('event_timestamp_timezone_missing')
    return stamp.astimezone(UTC)


def sdk_instant(value):
    # Official v5.0.0 python/src/time.rs IntoPyObject calls
    # PyDateTime::from_timestamp(unix_timestamp, None): naive LOCAL datetime.
    # Invert that documented conversion; never relabel local wall time as UTC.
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.astimezone(UTC)
    return instant(value)


@dataclass(frozen=True)
class Limits:
    delivery_ms: int
    silence_seconds: int
    heartbeat_seconds: int
    subscription_seconds: int
    worker_heartbeat_seconds: int
    config_sha256: str

    @classmethod
    def from_file(cls, path, expected_sha256):
        data = Path(path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected_sha256:
            raise ValueError('production_config_hash_mismatch')
        config = json.loads(data)
        market, runtime = config['market_data'], config['runtime']
        # Required keys are present in the production JSON. 5 seconds is the
        # existing load_config default in m15_longbridge_sdk_runtime_lib.py.
        values = (market['maximum_source_delivery_age_ms'], runtime['market_data_stall_seconds'],
                  runtime['heartbeat_interval_seconds'], runtime['subscription_deadline_seconds'],
                  runtime.get('market_data_heartbeat_deadline_seconds', 5))
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError('invalid_production_threshold')
        # The authorized comparison freezes current production limits.
        if values != (2000, 30, 1, 45, 5):
            raise ValueError('production_thresholds_changed_requires_review')
        return cls(*values, digest)


@dataclass(frozen=True)
class Window:
    market_date: str
    start: datetime
    latest_start: datetime
    open: datetime
    end: datetime
    close: datetime

    @classmethod
    def from_spec(cls, spec):
        result = cls(spec['market_date'], *(instant(spec[key]) for key in
            ['window_start_utc', 'latest_start_utc', 'regular_open_utc', 'window_end_utc', 'regular_close_utc']))
        # The reviewed manifest authorizes the specific market date. Validate its
        # configuration here; do not infer a holiday/DST calendar on Windows.
        market_day = date.fromisoformat(result.market_date)
        if (market_day.isoformat() != result.market_date or market_day.weekday() >= 5
                or result.open != instant(result.market_date+'T13:30:00Z')
                or result.close != instant(result.market_date+'T20:00:00Z')):
            raise ValueError('unreviewed_market_date_or_regular_session')
        opening = result.start <= result.latest_start < result.open < result.end <= result.close
        intraday = result.open <= result.start <= result.latest_start < result.end <= result.close
        if not (opening or intraday):
            raise ValueError('invalid_observation_window')
        if result.end-result.start > timedelta(minutes=20):
            raise ValueError('window_exceeds_authorized_twenty_minutes')
        return result

    @property
    def subscription_deadline(self):
        return self.latest_start if self.start >= self.open else self.open

    def validate_launch(self, now):
        if not self.start <= instant(now) <= self.latest_start:
            raise ValueError('outside_authorized_launch_window_no_wait_or_connect')

    def regular(self, stamp):
        return self.open <= instant(stamp) < self.close


class Inbox:
    """Callbacks copy only explicit scalar fields into a bounded queue; no writes."""
    def __init__(self, maxsize=CALLBACK_QUEUE_MAXSIZE):
        self.queue = queue.Queue(maxsize=maxsize)
        self.overflow = threading.Event()
        self.callback_error = threading.Event()
        self.closed = threading.Event()

    def close(self):
        self.closed.set()

    def capture(self, kind, symbol, event, *, now=None, monotonic=None):
        received = now or datetime.now(UTC)
        received_monotonic = time.monotonic() if monotonic is None else monotonic
        try:
            if self.closed.is_set():return
            events = (event,) if kind == 'quote' else event.trades
            count = 0
            for item in events:
                if self.closed.is_set():return
                count += 1
                # Datetime is immutable. Do not retain SDK context/event objects in queue.
                stamp = item.timestamp
                if not isinstance(stamp, (datetime, int, float, str)):
                    raise ValueError('invalid_timestamp_field')
                self.queue.put_nowait({'kind': kind, 'symbol': str(symbol),
                    'event_at': stamp, 'received_at': received,
                    'received_monotonic': received_monotonic})
            if kind == 'trade' and count == 0:
                self.queue.put_nowait({'kind': 'empty_trade_push', 'symbol': str(symbol),
                    'event_at': None, 'received_at': received,
                    'received_monotonic': received_monotonic})
        except queue.Full:
            self.overflow.set()
        except Exception:
            # Never save exception objects/strings that might contain SDK payloads.
            self.callback_error.set()


class Health:
    def __init__(self, symbols, limits, window):
        self.symbols = tuple(symbols)
        if len(set(symbols)) != len(symbols) or not set(REFERENCES) <= set(symbols):
            raise ValueError('invalid_symbol_set')
        self.limits, self.window = limits, window
        self.failure = None
        self.subscribed = False
        self.subscribed_at = None
        self.references = {}
        self.reference_flows = {symbol:{kind:{'last_fresh_received_at':None,
            'last_fresh_event_at':None,'last_fresh_received_monotonic':None,
            'max_gap_seconds':0.0,'fresh_event_count':0,'currently_silent_seconds':None}
            for kind in ('quote','trade')} for symbol in REFERENCES}
        self.max_queue_depth = 0
        self.max_queue_delay_ms = 0
        self.regular_events = 0
        self.last_check = None
        self.rows = {symbol: {kind: {'received_events': 0, 'regular_received_events': 0,
            'fresh_regular_events': 0, 'duplicate_events': 0, 'stale_initial_events': 0,
            'last_received_at': None, 'last_event_at': None, 'last_fresh_received_at': None}
            for kind in ('quote','trade')} for symbol in symbols}

    def fail(self, reason):
        if self.failure is None:
            self.failure = reason

    def subscription_succeeded(self, now):
        self.subscribed = True
        self.subscribed_at = instant(now)

    def process(self, event, *, now, monotonic):
        kind, symbol = event['kind'], event['symbol']
        received = instant(event['received_at'])
        received_mono = event['received_monotonic']
        lag_ms = (monotonic-received_mono)*1000
        self.max_queue_delay_ms = max(self.max_queue_delay_ms, lag_ms)
        regular = self.window.regular(received)
        record = {'record_type':'market_event','kind':kind,'symbol':symbol,
                  'received_at':received.isoformat(),'processed_at':instant(now).isoformat(),
                  'queue_delay_ms':round(lag_ms,3),'regular_session':regular,
                  'event_at':None,'classification':'invalid'}
        if symbol not in self.rows or kind not in ('quote','trade','empty_trade_push'):
            record['symbol']='<unexpected>'
            self.fail('unexpected_callback_identity'); return record
        if lag_ms < 0:
            self.fail('monotonic_clock_regressed'); return record
        if lag_ms > self.limits.delivery_ms:
            self.fail('processing_backlog'); record['classification']='processing_backlog'; return record
        # Receipt, not delayed processing or flush time, defines this window.
        # Keep the event record and actual queue-delay validation, but never let
        # an event received at/after the cutoff fill coverage or renew a flow.
        if received >= self.window.end:
            record['classification']='outside_observation_window_no_continuity_credit'; return record
        if kind == 'empty_trade_push':
            record['classification']='empty_trade_push_not_evidence_of_no_trades'; return record
        row = self.rows[symbol][kind]
        row['received_events'] += 1
        row['last_received_at'] = received.isoformat()
        if regular:
            row['regular_received_events'] += 1
            self.regular_events += 1
        try:
            source = sdk_instant(event['event_at'])
        except (ValueError,TypeError,OverflowError,OSError):
            self.fail('event_timestamp_invalid'); return record
        record['event_at'] = source.isoformat()
        record['timestamp_interpretation'] = ('official_sdk_local_naive_to_utc'
            if isinstance(event['event_at'],datetime) and event['event_at'].tzinfo is None
            else 'explicit_timestamp_to_utc')
        age_ms = (received-source).total_seconds()*1000
        record['source_delivery_age_ms'] = round(age_ms,3)
        if source > received+timedelta(seconds=FUTURE_TOLERANCE_SECONDS):
            self.fail('event_timestamp_in_future'); record['classification']='future'; return record
        # Quote.timestamp is the latest trade time, not the push send time.
        # Repeated last-trade times provide neither freshness nor liveness;
        # they may age past the delivery limit without proving a late push.
        # Queue and future-time validation above still apply to every Quote.
        if (kind == 'quote' and row['last_event_at'] is not None
                and source == instant(row['last_event_at'])):
            row['duplicate_events'] += 1
            record['classification']='same_timestamp_does_not_renew_liveness'
            return record
        # All Trade age checks retain their original ordering. A new, old
        # Quote remains rejected except for its first subscription snapshot.
        if regular and source >= self.window.open and age_ms > self.limits.delivery_ms:
            # Official Quote.timestamp is the latest trade time, not the push
            # delivery time. A first subscription snapshot may therefore be old.
            # Preserve its ordering baseline, but never grant freshness/liveness.
            if (kind == 'quote' and row['received_events'] == 1 and self.subscribed
                    and self.subscribed_at is not None and source <= self.subscribed_at):
                row['last_event_at'] = source.isoformat()
                row['stale_initial_events'] += 1
                record['classification'] = 'initial_quote_last_trade_old'
                return record
            reason = 'quote_last_trade_not_fresh' if kind == 'quote' else 'source_delivery_late'
            self.fail(reason); record['classification']=reason; return record
        previous = instant(row['last_event_at']) if row['last_event_at'] else None
        if previous is not None and source < previous:
            record['classification']=('out_of_order_trade_no_liveness_credit' if kind=='trade' else 'regressed_event_time')
            # Existing project aggregation accepts timely out-of-order trades
            # inside the same bucket. Observe them without renewing reference time.
            if regular and kind!='trade':self.fail('event_timestamp_regressed')
            return record
        if previous is not None and source == previous:
            row['duplicate_events'] += 1
            record['classification']='same_timestamp_does_not_renew_liveness'
            return record
        row['last_event_at'] = source.isoformat()
        if not regular:
            record['classification']='outside_regular_session_no_continuity_credit'; return record
        if source < self.window.open:
            row['stale_initial_events'] += 1
            record['classification']='historical_initial_push_no_liveness_credit'; return record
        row['fresh_regular_events'] += 1
        row['last_fresh_received_at'] = received.isoformat()
        if symbol in REFERENCES:
            self.references[symbol] = (received_mono, received)
            flow=self.reference_flows[symbol][kind]
            previous_mono=flow['last_fresh_received_monotonic']
            gap=(received_mono-previous_mono if previous_mono is not None else
                 (received-max(self.window.open,self.subscribed_at or self.window.open)).total_seconds())
            flow['max_gap_seconds']=max(flow['max_gap_seconds'],gap)
            flow['last_fresh_received_at']=received.isoformat()
            flow['last_fresh_event_at']=source.isoformat()
            flow['last_fresh_received_monotonic']=received_mono
            flow['currently_silent_seconds']=0.0
            flow['fresh_event_count']+=1
            # A late arriving event cannot erase an already elapsed gap.
            if gap >= self.limits.silence_seconds:
                self.fail('reference_flow_stalled:'+symbol+':'+kind)
        record['classification']='fresh_regular_event'
        return record

    def check(self, *, now, monotonic, queue_depth, overflow=False, callback_error=False):
        now = instant(now)
        # Final processing/fsync may finish after the observation cutoff. The
        # reference tail ends at the cutoff, not when summary writing completes.
        if now > self.window.end:
            monotonic -= (now-self.window.end).total_seconds()
            now = self.window.end
        self.last_check = now
        self.max_queue_depth=max(self.max_queue_depth,queue_depth)
        if overflow:self.fail('callback_queue_overflow')
        if callback_error:self.fail('callback_field_error')
        if self.subscribed and self.window.regular(now):
            grace_start=max(self.window.open,self.subscribed_at)
            grace_elapsed=(now-grace_start).total_seconds()
            for symbol in REFERENCES:
                for kind,flow in self.reference_flows[symbol].items():
                    previous_mono=flow['last_fresh_received_monotonic']
                    silence=monotonic-previous_mono if previous_mono is not None else grace_elapsed
                    flow['currently_silent_seconds']=max(0.0,silence)
                    flow['max_gap_seconds']=max(flow['max_gap_seconds'],silence)
                    if grace_elapsed >= self.limits.silence_seconds and silence >= self.limits.silence_seconds:
                        self.fail('reference_flow_stalled:'+symbol+':'+kind)
        return self.failure

    def snapshot(self, *, now, monotonic, queue_depth):
        return {'status':'failed' if self.failure else 'observing', 'reason':self.failure,
            'observed_at':instant(now).isoformat(),'observed_monotonic':monotonic,
            'queue_depth':queue_depth,'maximum_queue_depth':self.max_queue_depth,
            'maximum_queue_delay_ms':round(self.max_queue_delay_ms,3),
            'regular_event_count':self.regular_events,'subscribed':self.subscribed,
            'subscription_succeeded_at':self.subscribed_at.isoformat() if self.subscribed_at else None,
            'reference_flows':self.reference_flows,
            'symbols':self.rows,'full_sessions_passed':0,'production_acceptance':False}

    def summary(self, *, now, monotonic, queue_depth):
        self.check(now=now,monotonic=monotonic,queue_depth=queue_depth)
        result=self.snapshot(now=now,monotonic=monotonic,queue_depth=queue_depth)
        completed=instant(now)>=self.window.end and queue_depth==0
        covered=[symbol for symbol,row in self.rows.items() if any(x['fresh_regular_events'] for x in row.values())]
        no_trade=[symbol for symbol,row in self.rows.items() if row['trade']['regular_received_events']==0]
        trade_observed=any(row['trade']['fresh_regular_events'] for row in self.rows.values())
        references_complete=all(flow['fresh_event_count']>0 and flow['max_gap_seconds']<self.limits.silence_seconds
                                for flows in self.reference_flows.values() for flow in flows.values())
        eligible=bool(completed and self.subscribed and self.window.start<=self.subscribed_at<=self.window.subscription_deadline
                      and self.subscribed_at<self.window.end
                      and len(covered)==len(self.symbols) and trade_observed and references_complete and not self.failure)
        result.update(status='failed' if self.failure else ('window_observed' if completed else 'incomplete'),
            diagnostic_window_passed=eligible, completed_window=completed,
            subscription_deadline_utc=self.window.subscription_deadline.isoformat(),
            fresh_regular_symbol_count=len(covered),no_regular_trade_push_symbols=no_trade,
            fresh_regular_trade_observed=trade_observed,
            no_trade_interpretation='No Trade push observed; does not prove no executions on exchange',
            reference_flow_continuity_passed=references_complete and not self.failure,
            diagnostic_scope='Four reference flows (SPY/QQQ Quote and Trade) each below 30-second gaps plus 147-symbol fresh event coverage; not dual-stream completeness proof for other 145 symbols',
            kline_validation_performed=False,strategy_validation_performed=False)
        return result
