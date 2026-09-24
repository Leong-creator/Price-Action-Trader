#!/usr/bin/env python3
"""Read-only Windows producer. Stdlib until the explicitly invoked SDK entrypoint.

The supervising controller owns process/connection isolation and hard SDK-call
termination. This process never constructs an account or order context.
"""
from __future__ import annotations

import argparse
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


class Monitor:
    def __init__(self, directory: Path, run_id: str):
        self.directory, self.run_id = directory, run_id
        self.sequence = 0

    def stage(self, phase: str) -> None:
        self.sequence += 1
        with (self.directory / 'stages.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'run_id': self.run_id, 'sequence': self.sequence,
                         'phase': phase, 'phase_started_monotonic': time.monotonic()}) + '\n')
            handle.flush()

    def health(self) -> None:
        atomic_json(self.directory / 'health.json', {'run_id': self.run_id,
                    'phase': 'streaming', 'status': 'observing', 'reason': None,
                    'observed_monotonic': time.monotonic(), 'observed_at': timestamp(datetime.now(UTC))})

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
    def __init__(self, symbols: list[str], *, maxsize=MAX_CALLBACKS, now=None):
        self.symbols = frozenset(symbols)
        self.now = now or (lambda: datetime.now(UTC))
        self.queue = queue.Queue(maxsize=maxsize)
        self.lock = threading.Lock()
        self.failure = None
        self.closed = False

    def capture(self, kind: str, symbol: str, event: Any) -> None:
        # The same lock defines callback receipt order and watermark cuts.
        with self.lock:
            if self.closed or self.failure:
                return
            try:
                received_at = timestamp(self.now())
                if symbol not in self.symbols or kind not in ('quote', 'trade'):
                    raise FeedError('unexpected_callback_identity')
                payload = quote_payload(event) if kind == 'quote' else trade_payload(event)
                self.queue.put_nowait((kind, {'symbol': symbol, 'received_at': received_at, 'event': payload}))
            except queue.Full:
                self.failure = 'callback_queue_overflow'
            except Exception:
                self.failure = 'callback_normalization_failed'

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
    callback_queue = CallbackQueue(symbols, now=now)
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
            monitor.health()
        previous_heartbeat = monotonic()
        while now() < end and monotonic() < deadline:
            drain()
            current = monotonic()
            if current - previous_heartbeat >= 1:
                if monitor is not None:
                    monitor.health()
                writer.emit('heartbeat', {'phase': 'streaming'})
                previous_heartbeat = current
            sleep(.05)
        drain(close=True)
        # A mono-only expiry indicates a clock step; never call it a passed window.
        if now() < end:
            raise FeedError('monotonic_deadline_before_window_end')
        writer.emit('end', {'reason': 'window_completed', 'received_through': last_watermark})
    finally:
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
