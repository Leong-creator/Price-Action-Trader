#!/usr/bin/env python3
"""Read-only Windows producer. Stdlib until the explicitly invoked SDK entrypoint.

The supervising controller owns process/connection isolation and hard SDK-call
termination. This process never constructs an account or order context.
"""
from __future__ import annotations

import argparse
import faulthandler
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import importlib.metadata
import json
import os
from pathlib import Path
import queue
import re
import sys
import tempfile
import threading
import time
from typing import Any

MAX_CALLBACKS = 250_000
CALLBACK_STALL_EVIDENCE_SECONDS = 15


class FeedError(RuntimeError):
    """Only fixed, non-secret error codes may cross the wire."""


def timestamp(value: datetime | str) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        raise FeedError('invalid_timestamp')
    # SDK 5.0.0 exposes native-local naive datetimes; invert that conversion.
    return value.astimezone(UTC).isoformat()


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise FeedError('naive_configuration_timestamp')
    return parsed.astimezone(UTC)


def decimal_text(value: Any) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise FeedError('invalid_decimal_field')
    return str(value)


def integer(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise FeedError('invalid_volume_field')
    return value


def enum_text(value: Any) -> str:
    # Native enums use their public string name, never their repr or __dict__.
    result = str(value)
    if len(result) > 80 or not re.fullmatch(r'[A-Za-z0-9_.]+', result):
        raise FeedError('invalid_enum_field')
    return result


def quote_payload(event: Any, *, snapshot: bool = False) -> dict[str, Any]:
    result = {name: decimal_text(getattr(event, name))
              for name in ('last_done', 'open', 'high', 'low', 'turnover')}
    result.update(timestamp=timestamp(event.timestamp), volume=integer(event.volume),
                  trade_status=enum_text(event.trade_status))
    if not snapshot:
        result.update(trade_session=enum_text(event.trade_session),
                      current_volume=integer(event.current_volume),
                      current_turnover=decimal_text(event.current_turnover))
    else:
        result['symbol'] = str(event.symbol)
        result['prev_close'] = decimal_text(event.prev_close)
    return result


def trade_payload(event: Any) -> dict[str, Any]:
    trades = []
    for item in event.trades:
        if not isinstance(item.trade_type, str) or len(item.trade_type) > 32:
            raise FeedError('invalid_trade_type')
        trades.append({'price': decimal_text(item.price), 'volume': integer(item.volume),
                       'timestamp': timestamp(item.timestamp), 'trade_type': item.trade_type,
                       'direction': enum_text(item.direction),
                       'trade_session': enum_text(item.trade_session)})
    # Same-second executions are independent trades: never deduplicate here.
    return {'trades': trades}


def completed_daily(candles: Any, market_date: str, holidays: list[str], required_daily_date: str) -> list[dict[str, Any]]:
    day = date.fromisoformat(market_date)
    required = day - timedelta(days=1)
    while required.weekday() >= 5 or required.isoformat() in holidays:
        required -= timedelta(days=1)
    if required.isoformat() != required_daily_date:
        raise FeedError('required_daily_date_mismatch')
    rows = []
    for item in candles:
        stamp = timestamp(item.timestamp)
        candle_day = utc(stamp).date()
        if candle_day >= day:
            continue
        if candle_day.weekday() >= 5 or candle_day.isoformat() in holidays:
            raise FeedError('daily_context_non_session_date')
        row = {name: decimal_text(getattr(item, name)) for name in ('open', 'high', 'low', 'close', 'turnover')}
        row.update(timestamp=stamp, volume=integer(item.volume))
        rows.append(row)
    rows.sort(key=lambda row: row['timestamp'])
    if len({utc(row['timestamp']).date() for row in rows}) != len(rows):
        raise FeedError('daily_context_duplicate_date')
    rows = rows[-60:]
    if len(rows) != 60:
        raise FeedError('daily_context_incomplete')
    if utc(rows[-1]['timestamp']).date() != required:
        raise FeedError('daily_context_latest_day_missing')
    return rows


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, separators=(',', ':'), allow_nan=False)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        stop = time.monotonic() + .25
        for attempt in range(26):
            try:
                os.replace(temporary, path)
                return
            except OSError as error:
                if (os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32, 33)
                        or attempt == 25 or time.monotonic() >= stop):
                    raise
                time.sleep(.01)
    finally:
        temporary.unlink(missing_ok=True)


class StallEvidence:
    """Local Python stacks only; no inference about native SDK/network health.

    The standard-library C watchdog can dump even when the Python monitor cannot
    run. It is armed only from successful callback progress, never heartbeats.
    Its file stays open until cancellation; only one stall dump is permitted.
    """
    def __init__(self, directory, run_id, *, monotonic=None, handler=None):
        self.directory, self.run_id = directory, run_id
        self.monotonic = monotonic or time.monotonic
        self.handler = handler or faulthandler
        self.handle = None
        self.baseline_bytes = None
        self.deadline = None
        self.progress = None
        self.stall_latched = False
        self.stall_dump_observed = False
        self.closed = False
        self.error = None
        self.callbacks = None

    def summary(self):
        return {'scope': 'python_thread_stacks_only', 'native_network_root_cause': 'unproven',
                'stall_seconds': CALLBACK_STALL_EVIDENCE_SECONDS,
                'baseline_written': self.baseline_bytes is not None,
                'watchdog_deadline_monotonic': self.deadline,
                'stall_deadline_elapsed': self.stall_latched,
                'stall_dump_observed': self.stall_dump_observed,
                'closed': self.closed, 'diagnostic_error': self.error}

    def _error(self, code):
        if self.error is None:
            self.error = code

    def _save(self):
        try:
            atomic_json(self.directory / 'diagnostic.json', {
                'schema_version': 1, 'run_id': self.run_id, **self.summary(),
                'callbacks': self.callbacks,
                'observed_at': timestamp(datetime.now(UTC)),
                'observed_monotonic': self.monotonic()})
        except Exception:
            self._error('diagnostic_write_failed')

    def _observe_dump(self):
        if self.handle is not None and self.baseline_bytes is not None:
            self.stall_dump_observed = (
                os.fstat(self.handle.fileno()).st_size > self.baseline_bytes)
            if self.stall_dump_observed:
                self.stall_latched = True

    def start(self, stats):
        self.callbacks = stats
        try:
            fd = os.open(self.directory / 'stack.private', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self.handle = os.fdopen(fd, 'wb', buffering=0)
            self.handler.dump_traceback(file=self.handle, all_threads=True)
            self.baseline_bytes = os.fstat(self.handle.fileno()).st_size
            self.progress = (sum(stats['enqueued_counts'].values())
                             if stats and stats.get('available') else None)
            current = self.monotonic()
            last_callback = stats.get('last_callback_monotonic') if stats and stats.get('available') else None
            self.deadline = (last_callback if last_callback is not None else current) + CALLBACK_STALL_EVIDENCE_SECONDS
            self.handler.dump_traceback_later(max(.001, self.deadline - current),
                                             repeat=False, file=self.handle, exit=False)
        except Exception:
            self._error('stall_evidence_start_failed')
        self._save()

    def tick(self, stats):
        self.callbacks = stats
        try:
            self._observe_dump()
            current = self.monotonic()
            # Even if a callback resumes after the deadline, never schedule a
            # second dump. The C watchdog may still be completing the first.
            if self.deadline is not None and current >= self.deadline:
                self.stall_latched = True
            if stats and stats.get('available') and not (self.error or self.closed or self.stall_latched):
                progress = sum(stats['enqueued_counts'].values())
                if progress != self.progress and stats['last_callback_monotonic'] is not None:
                    deadline = stats['last_callback_monotonic'] + CALLBACK_STALL_EVIDENCE_SECONDS
                    if deadline > current:
                        self.handler.dump_traceback_later(deadline - current, repeat=False,
                                                         file=self.handle, exit=False)
                        self.deadline = deadline
                        self.progress = progress
        except Exception:
            self._error('stall_evidence_tick_failed')
        self._save()

    def close(self, stats):
        self.callbacks = stats
        try:
            # The fd must not be closed/reused while the C watchdog can write.
            self.handler.cancel_dump_traceback_later()
        except Exception:
            self._error('stall_evidence_cancel_failed')
            self._save()
            return
        try:
            self._observe_dump()
            if self.deadline is not None and self.monotonic() >= self.deadline:
                self.stall_latched = True
            if self.handle is not None:
                self.handle.close()
            self.closed = True
        except Exception:
            self._error('stall_evidence_close_failed')
        self._save()


class Monitor:
    def __init__(self, directory: Path, run_id: str):
        self.directory, self.run_id = directory, run_id
        self.sequence = 0
        self.evidence = None

    def start_evidence(self, callbacks) -> None:
        self.evidence = StallEvidence(self.directory, self.run_id, monotonic=callbacks.monotonic)
        self.evidence.start(callbacks.stats())

    def stage(self, phase: str) -> None:
        self.sequence += 1
        with (self.directory / 'stages.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'run_id': self.run_id, 'sequence': self.sequence,
                         'phase': phase, 'phase_started_monotonic': time.monotonic()}) + '\n')
            handle.flush()

    def health(self, callbacks=None) -> None:
        stats = callbacks.stats() if callbacks is not None else None
        if self.evidence is not None:
            self.evidence.tick(stats)
        atomic_json(self.directory / 'health.json', {'run_id': self.run_id,
                    'phase': 'streaming', 'status': 'observing', 'reason': None,
                    'heartbeat_scope': 'producer_main_loop_only', 'sdk_health': 'unknown',
                    'callbacks': stats,
                    'stall_evidence': self.evidence.summary() if self.evidence is not None else None,
                    'observed_monotonic': time.monotonic(), 'observed_at': timestamp(datetime.now(UTC))})

    def close_evidence(self, callbacks) -> None:
        if self.evidence is not None:
            self.evidence.close(callbacks.stats())

    def finish(self, success: bool, reason=None, *, terminal_sequence=None, spec=None) -> None:
        atomic_json(self.directory / 'summary.json', {'run_id': self.run_id,
                    'schema_version': 1, 'status': 'window_observed' if success else 'failed',
                    'completed_window': success, 'reason': reason,
                    'production_acceptance': False, 'terminal_sequence': terminal_sequence,
                    'window_start_utc': spec['window_start_utc'] if spec else None,
                    'window_end_utc': spec['window_end_utc'] if spec else None})
        self.stage('completed' if success else 'failed')


class WireWriter:
    def __init__(self, stream: Any, run_id: str, now=None):
        self.stream, self.run_id = stream, run_id
        self.now = now or (lambda: datetime.now(UTC))
        self.sequence = 0

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        self.sequence += 1
        record = {'run_id': self.run_id, 'sequence': self.sequence, 'kind': kind,
                  'emitted_at': timestamp(self.now()), 'payload': payload}
        self.stream.write(json.dumps(record, separators=(',', ':'), allow_nan=False) + '\n')
        self.stream.flush()


class CallbackQueue:
    def __init__(self, symbols: list[str], *, maxsize=MAX_CALLBACKS, now=None, monotonic=None):
        self.symbols = frozenset(symbols)
        self.now = now or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self.queue = queue.Queue(maxsize=maxsize)
        self.lock = threading.Lock()
        self.failure = None
        self.closed = False
        self.enqueued_counts = {'quote': 0, 'trade': 0}
        self.last_callback_utc = None
        self.last_callback_monotonic = None

    def capture(self, kind: str, symbol: str, event: Any) -> None:
        # The same lock defines callback receipt order and watermark cuts.
        with self.lock:
            if self.closed or self.failure:
                return
            try:
                received_at = timestamp(self.now())
                received_monotonic = self.monotonic()
                if symbol not in self.symbols or kind not in ('quote', 'trade'):
                    raise FeedError('unexpected_callback_identity')
                payload = quote_payload(event) if kind == 'quote' else trade_payload(event)
                self.queue.put_nowait((kind, {'symbol': symbol, 'received_at': received_at, 'event': payload}))
                self.enqueued_counts[kind] += 1
                self.last_callback_utc = received_at
                self.last_callback_monotonic = received_monotonic
            except queue.Full:
                self.failure = 'callback_queue_overflow'
            except Exception:
                self.failure = 'callback_normalization_failed'

    def stats(self):
        # Never wait for a stuck callback merely to observe it. No SDK or I/O.
        if not self.lock.acquire(blocking=False):
            return {'available': False, 'diagnostic_error': 'callback_stats_lock_busy'}
        try:
            return {'available': True, 'counts_scope': 'successfully_enqueued_callbacks',
                    'enqueued_counts': dict(self.enqueued_counts),
                    'last_callback_utc': self.last_callback_utc,
                    'last_callback_monotonic': self.last_callback_monotonic,
                    'queue_depth': self.queue.qsize(), 'failure': self.failure,
                    'closed': self.closed}
        finally:
            self.lock.release()

    def take_prefix(self, *, close=False):
        with self.lock:
            if self.failure:
                raise FeedError(self.failure)
            prefix = [self.queue.get_nowait() for _ in range(self.queue.qsize())]
            cutoff = timestamp(self.now())
            if close:
                self.closed = True
            return prefix, cutoff

    def check(self):
        with self.lock:
            if self.failure:
                raise FeedError(self.failure)


def reject_overrides() -> None:
    if any(value and name.startswith(('LONGBRIDGE_', 'LONGPORT_'))
           and name.endswith(('URL', 'REGION')) for name, value in os.environ.items()):
        raise FeedError('official_endpoint_override_rejected')


def load_symbols(config: dict[str, Any], repo_root: Path, spec: dict[str, Any] | None = None) -> list[str]:
    market = config['market_data']
    if market['market'] != 'US' or market['symbol_limit'] != 147 or market.get('use_seed_universe'):
        raise FeedError('unreviewed_universe_configuration')
    if spec is not None and 'symbols' in spec:
        symbols = spec['symbols']
        if (not isinstance(symbols, list) or len(symbols) != 147 or len(set(symbols)) != 147
                or any(not isinstance(s, str) or not re.fullmatch(r'[A-Z0-9.-]+\.US', s) for s in symbols)
                or not {'SPY.US', 'QQQ.US'} <= set(symbols)):
            raise FeedError('invalid_frozen_symbol_set')
        return list(symbols)
    universe = Path(market['universe_path'])
    if not universe.is_absolute():
        universe = repo_root / universe
    raw = json.loads(universe.read_text(encoding='utf-8'))['symbols'][:147]
    if len(raw) != 147 or len(set(raw)) != 147 or any(not re.fullmatch('[A-Z0-9.-]+', s) for s in raw):
        raise FeedError('invalid_universe')
    return [symbol + '.US' for symbol in raw]


def produce(sdk: Any, config: dict[str, Any], spec: dict[str, Any], symbols: list[str],
            client_id: str, writer: WireWriter, *, now=None, monotonic=None, sleep=None, monitor=None) -> None:
    now = now or (lambda: datetime.now(UTC))
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    start, end = utc(spec['window_start_utc']), utc(spec['window_end_utc'])
    launched = now()
    if not start <= launched <= utc(spec['latest_start_utc']) or launched >= end:
        raise FeedError('outside_authorized_launch_window')
    if date.fromisoformat(spec['market_date']) != end.date():
        raise FeedError('market_date_window_mismatch')
    deadline = monotonic() + (end - launched).total_seconds()
    callback_queue = CallbackQueue(symbols, now=now, monotonic=monotonic)
    last_watermark = None

    def deadline_check():
        callback_queue.check()
        if now() >= end or monotonic() >= deadline:
            raise FeedError('initialization_window_expired')

    def stage(phase):
        if monitor is not None:
            monitor.stage(phase)
        writer.emit('stage', {'phase': phase})

    def drain(close=False):
        nonlocal last_watermark
        prefix, cutoff = callback_queue.take_prefix(close=close)
        if close:
            cutoff = timestamp(min(utc(cutoff), end))
        for kind, payload in prefix:
            writer.emit(kind, payload)
        callback_queue.check()
        # Cut is captured with the enqueue lock, emitted only after its prefix.
        writer.emit('watermark', {'received_through': cutoff})
        last_watermark = cutoff

    reject_overrides()
    stage('initializing')
    os.environ['LONGBRIDGE_PRINT_QUOTE_PACKAGES'] = 'false'
    oauth = sdk.OAuthBuilder(client_id).build(lambda _url: None)
    sdk_config = sdk.Config.from_oauth(oauth)
    reject_overrides()
    deadline_check()
    context = sdk.QuoteContext(sdk_config)
    context.set_on_quote(lambda symbol, event: callback_queue.capture('quote', symbol, event))
    context.set_on_trades(lambda symbol, event: callback_queue.capture('trade', symbol, event))
    try:
        stage('daily_context')
        daily_deadline = min(deadline, monotonic() + config['market_data']['daily_context_deadline_seconds'])
        for symbol in symbols:
            deadline_check()
            if monotonic() >= daily_deadline:
                raise FeedError('daily_context_deadline_exceeded')
            candles = context.candlesticks(symbol, sdk.Period.Day, 61,
                                          sdk.AdjustType.NoAdjust, sdk.TradeSessions.Intraday)
            deadline_check()
            if monotonic() >= daily_deadline:
                raise FeedError('daily_context_deadline_exceeded')
            rows = completed_daily(candles, spec['market_date'], config['market_data']['market_holidays'], spec['required_daily_date'])
            writer.emit('daily_context', {'symbol': symbol, 'received_at': timestamp(now()), 'candlesticks': rows})
            writer.emit('heartbeat', {'phase': 'daily_context'})
        stage('subscribing')
        context.subscribe(symbols, [sdk.SubType.Quote, sdk.SubType.Trade])
        deadline_check()
        writer.emit('subscribed', {'symbols': symbols, 'received_at': timestamp(now())})
        stage('initial_snapshot')
        snapshots = context.quote(symbols)
        received = timestamp(now())
        deadline_check()
        snapshots = [quote_payload(item, snapshot=True) for item in snapshots]
        if len(snapshots) != len(symbols) or {row['symbol'] for row in snapshots} != set(symbols):
            raise FeedError('initial_snapshot_incomplete')
        writer.emit('initial_snapshot', {'quotes': snapshots, 'received_at': received})
        writer.emit('ready', {'symbols': symbols})
        stage('streaming')
        if monitor is not None:
            monitor.start_evidence(callback_queue)
            monitor.health(callback_queue)
        previous_heartbeat = monotonic()
        while now() < end and monotonic() < deadline:
            drain()
            current = monotonic()
            if current - previous_heartbeat >= 1:
                if monitor is not None:
                    monitor.health(callback_queue)
                writer.emit('heartbeat', {'phase': 'streaming'})
                previous_heartbeat = current
            sleep(.05)
        drain(close=True)
        # A mono-only expiry indicates a clock step; never call it a passed window.
        if now() < end:
            raise FeedError('monotonic_deadline_before_window_end')
        writer.emit('end', {'reason': 'window_completed', 'received_through': last_watermark})
    finally:
        if monitor is not None:
            monitor.close_evidence(callback_queue)
        with callback_queue.lock:
            callback_queue.closed = True
        # SDK lifetime ends with process exit; external Job/controller verifies it.
        del context


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='production-config.json')
    parser.add_argument('--run-spec', default='run-spec.json')
    parser.add_argument('--repo-root', default='.')
    args = parser.parse_args(argv)
    writer = None
    monitor = None
    try:
        config = json.loads(Path(args.config).read_text(encoding='utf-8'))
        spec = json.loads(Path(args.run_spec).read_text(encoding='utf-8'))
        writer = WireWriter(sys.stdout, spec['run_id'])
        monitor = Monitor(Path.cwd(), spec['run_id'])
        symbols = load_symbols(config, Path(args.repo_root), spec)
        if importlib.metadata.version('longbridge') != '5.0.0':
            raise FeedError('official_sdk_version_mismatch')
        reject_overrides()
        client = Path(config['oauth']['client_id_file']).expanduser().read_text(encoding='utf-8').strip()
        if not client:
            raise FeedError('missing_oauth_client_id')
        import longbridge.openapi as sdk
        produce(sdk, config, spec, symbols, client, writer, monitor=monitor)
        monitor.finish(True, terminal_sequence=writer.sequence, spec=spec)
        return 0
    except Exception as error:
        reason = str(error) if type(error) is FeedError else 'producer_failed'
        if monitor is not None:
            try:
                monitor.finish(False, reason)
            except Exception:
                pass
        if writer is not None:
            try:
                writer.emit('error', {'reason': reason, 'error_type': type(error).__name__,
                                      'error_code': getattr(error, 'code', None) if type(getattr(error, 'code', None)) is int else None})
            except Exception:
                pass
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
