"""Consume an audited Windows SDK wire stream using the existing Linux strategy pipeline.

This module constructs no SDK, account or order client. The external supervisor
owns the only Windows quote process, its credentials, connection lock and exit.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import sys
import time
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_m15_longbridge_quote_diagnostic as diagnostic
from scripts import m15_longbridge_sdk_runtime_lib as rules

MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_PREFIX_BYTES = 16 * 1024 * 1024


def stamp(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError('wire_timestamp_type')
    value = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError('wire_timestamp_must_be_utc')
    return value.astimezone(UTC)


def amount(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('wire_decimal_type')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('wire_decimal_invalid') from exc
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        raise ValueError('wire_decimal_range')
    return number


def quantity(value):
    number = amount(value)
    if number != number.to_integral_value():
        raise ValueError('wire_volume_not_integer')
    return int(number)


def restore_event(payload, kind):
    if not isinstance(payload, dict):
        raise ValueError('wire_event_not_object')
    row = dict(payload)
    if kind == 'trade':
        trades = row.get('trades')
        if not isinstance(trades, list):
            raise ValueError('wire_trades_not_list')
        restored = []
        for trade in trades:
            if not isinstance(trade, dict):
                raise ValueError('wire_trade_not_object')
            item = dict(trade)
            item.update(timestamp=stamp(item['timestamp']), price=amount(item['price'], positive=True),
                        volume=quantity(item['volume']))
            if not isinstance(item.get('trade_session'), str) or not isinstance(item.get('trade_type'), str):
                raise ValueError('wire_trade_classification_required')
            restored.append(item)
        row['trades'] = restored
    else:
        row['timestamp'] = stamp(row['timestamp'])
        fields = ('open', 'high', 'low', 'close') if kind == 'daily' else ('last_done',)
        for key in fields:
            row[key] = amount(row[key], positive=True)
        for key in ('open', 'high', 'low', 'close', 'last_done', 'turnover', 'current_turnover'):
            if key in row:
                # SDK opening/session snapshots may legitimately have zero OHLC.
                # The existing quote-state gate marks them non-actionable.
                row[key] = amount(row[key], positive=(key == 'last_done' or
                    (kind == 'daily' and key not in ('turnover', 'current_turnover'))))
        if 'volume' in row:
            row['volume'] = quantity(row['volume'])
        elif kind == 'daily':
            raise ValueError('wire_daily_volume_missing')
    return row


class FeedConsumer:
    def __init__(self, config, output, run_id, start, end, *, now=None):
        self.start, self.end = stamp(start), stamp(end)
        now = stamp(now or datetime.now(UTC))
        if str(UUID(run_id)) != run_id or not self.start < self.end:
            raise ValueError('wire_identity_or_window_invalid')
        self.output = Path(output).resolve()
        diagnostic.validate_pipeline_paths(config, self.output)
        diagnostic.validate_output_dir(self.output, config.output_dir)
        self.output.mkdir(parents=True, exist_ok=True)
        self.config, self.run_id = config, run_id
        self.symbols = tuple(rules.configured_symbols(config))
        self.evidence = diagnostic.PipelineProbeEvidence(config, self.output)
        self.sequence = 0
        self.daily = {}
        self.subscribed = False
        self.ready = False
        self.builder = None
        self.watermark = None
        self.emitted = None
        self.ended = False
        self.counts = Counter()
        self.trade_count = 0
        self.ignored_tail_events = 0
        self.end_sequence = None
        self.quote_source_times = {}
        self.quote_classifications = Counter()
        self.started_wall, self.started_mono = now, time.monotonic()

    def _emit(self, message, now):
        self.evidence.consume(message, now)

    def _receipt(self, value, emitted, now):
        received = stamp(value)
        if received < self.start or received > emitted or received >= self.end:
            raise ValueError('wire_receipt_outside_window_or_emission')
        if now - received > timedelta(milliseconds=self.config.maximum_source_delivery_age_ms):
            raise ValueError('wire_processing_backlog')
        if received > now + timedelta(seconds=2):
            raise ValueError('wire_receipt_in_future')
        return received

    def consume(self, row, *, now=None):
        now = stamp(now or datetime.now(UTC))
        if self.ended:
            raise ValueError('wire_message_after_end')
        if not isinstance(row, dict) or row.get('run_id') != self.run_id:
            raise ValueError('wire_run_id_mismatch')
        seq = row.get('sequence')
        if type(seq) is not int or seq != self.sequence + 1:
            raise ValueError('wire_sequence_discontinuity')
        kind, payload = row.get('kind'), row.get('payload')
        if not isinstance(payload, dict):
            raise ValueError('wire_payload_not_object')
        emitted = stamp(row['emitted_at'])
        if emitted < self.start or emitted > self.end + timedelta(seconds=5):
            raise ValueError('wire_emission_outside_window')
        if self.emitted is not None and emitted < self.emitted:
            raise ValueError('wire_emission_clock_regressed')
        if emitted > now + timedelta(seconds=2):
            raise ValueError('wire_emission_in_future')
        if now - emitted > timedelta(milliseconds=self.config.maximum_source_delivery_age_ms):
            raise ValueError('wire_transfer_backlog')
        tail = now > self.end
        if tail and kind not in ('end', 'watermark', 'quote', 'trade'):
            raise ValueError('wire_input_after_window_no_backfill')
        self.sequence, self.emitted = seq, emitted
        self.counts[kind] += 1
        if kind == 'stage':
            # Windows monotonic values have an unrelated origin. Only the first
            # local receipt advances the existing absolute phase deadline.
            phase = payload['phase']
            self._emit({'kind': 'sdk_stage', 'phase': phase, 'started_monotonic': time.monotonic()}, now)
        elif kind == 'daily_context':
            if self.subscribed:
                raise ValueError('wire_daily_after_subscription')
            symbol = payload['symbol']
            if symbol not in self.symbols or symbol in self.daily:
                raise ValueError('wire_daily_symbol_duplicate_or_unknown')
            received = self._receipt(payload['received_at'], emitted, now)
            candles = payload['candlesticks']
            if not isinstance(candles, list) or len(candles) != self.config.daily_context_bars:
                raise ValueError('wire_daily_count_invalid')
            self.daily[symbol] = rules.daily_candlestick_event_rows(symbol,
                [restore_event(item, 'daily') for item in candles], received)
        elif kind == 'subscribed':
            if self.subscribed or tuple(payload['symbols']) != self.symbols or set(self.daily) != set(self.symbols):
                raise ValueError('wire_subscription_or_daily_incomplete')
            daily = [item for symbol in self.symbols for item in self.daily[symbol]]
            self._emit({'kind': 'daily_context', 'rows': daily, 'failures': [],
                        'source_mode': 'official_sdk_daily_context'}, now)
            self.subscribed = True
        elif kind == 'initial_snapshot':
            if not self.subscribed or self.builder is not None:
                raise ValueError('wire_initial_snapshot_order')
            received = self._receipt(payload['received_at'], emitted, now)
            quotes = payload['quotes']
            if not isinstance(quotes, list) or len(quotes) != len(self.symbols):
                raise ValueError('wire_initial_snapshot_count')
            if {item['symbol'] for item in quotes} != set(self.symbols):
                raise ValueError('wire_initial_snapshot_symbols')
            self.builder = rules.FiveMinuteBarBuilder(self.config.bar_minutes,
                complete_bar_open_not_before=rules.floor_bar_open(now, self.config.bar_minutes) + timedelta(minutes=self.config.bar_minutes),
                boundary_batch_mode=True, market_holidays=self.config.market_holidays,
                boundary_settle_seconds=self.config.maximum_source_delivery_age_ms / 1000)
            rows = []
            for item in quotes:
                # SecurityQuote's top-level fields are separate from its
                # pre_market_quote/post_market_quote objects. The producer
                # serializes those top-level fields only, not a PushQuote.
                if 'trade_session' in item:
                    raise ValueError('wire_snapshot_must_not_be_push_quote')
                event = restore_event(item, 'quote')
                if event['timestamp'] > received + timedelta(seconds=2):
                    raise ValueError('wire_quote_timestamp_in_future')
                self.builder.seed_quote(item['symbol'], event, received_at=received)
                self.quote_source_times[item['symbol']] = event['timestamp']
                rows.append({'symbol': item['symbol'], 'payload': event, 'received_at': received.isoformat(),
                             'source_mode': 'official_sdk_initial_snapshot'})
            self._emit({'kind': 'quote_state_batch', 'rows': rows}, now)
        elif kind == 'ready':
            if self.ready or self.builder is None:
                raise ValueError('wire_ready_order')
            partial = rules.floor_bar_open(now, self.config.bar_minutes) + timedelta(minutes=self.config.bar_minutes)
            self.builder.complete_bar_open_not_before = partial
            self._emit({'kind': 'ready', 'partial_bar_suppressed_until': partial.isoformat()}, now)
            self.ready = True
        elif kind in ('quote', 'trade'):
            if not self.ready:
                raise ValueError('wire_market_event_before_ready')
            symbol = payload['symbol']
            if symbol not in self.symbols:
                raise ValueError('wire_market_symbol_unknown')
            received = stamp(payload['received_at'])
            if received >= self.end or tail:
                if received < self.start or received > emitted or received > now + timedelta(seconds=2):
                    raise ValueError('wire_tail_receipt_invalid')
                if now - received > timedelta(milliseconds=self.config.maximum_source_delivery_age_ms):
                    raise ValueError('wire_processing_backlog')
                event = restore_event(payload['event'], kind)
                # Tail data is excluded from observation and cannot repair a
                # missing boundary. A late trade for an already eligible bucket
                # would make its sealed bar untrustworthy, so it still fails.
                if kind == 'trade':
                    last_eligible = rules.floor_bar_open(self.end - timedelta(
                        seconds=self.config.maximum_source_delivery_age_ms / 1000), self.config.bar_minutes)
                    if any(trade['timestamp'] < last_eligible for trade in event['trades']):
                        raise ValueError('wire_tail_trade_for_closed_boundary')
                self.ignored_tail_events += 1
                return
            received = self._receipt(received, emitted, now)
            if self.watermark is not None and received <= self.watermark:
                raise ValueError('wire_event_behind_watermark')
            event = restore_event(payload['event'], kind)
            if kind == 'quote':
                if event['timestamp'] > received + timedelta(seconds=2):
                    raise ValueError('wire_quote_timestamp_in_future')
                session = event.get('trade_session')
                if not isinstance(session, str) or session not in (
                        'Intraday', 'TradeSession.Intraday', 'Pre', 'TradeSession.Pre',
                        'Post', 'TradeSession.Post', 'Overnight', 'TradeSession.Overnight'):
                    raise ValueError('wire_quote_session_invalid')
                if session.split('.')[-1] != 'Intraday':
                    self.quote_classifications['non_intraday_quote_no_credit'] += 1
                    return
                source = event['timestamp']
                previous = self.quote_source_times.get(symbol)
                if previous is not None and source < previous:
                    self.quote_classifications['regressed_quote_no_credit'] += 1
                    return
                if received - source > timedelta(milliseconds=self.config.maximum_source_delivery_age_ms):
                    self.quote_classifications['old_quote_no_credit'] += 1
                    return
                self.builder.seed_quote(symbol, event, received_at=received)
                if previous is not None and source == previous:
                    # Same-second price/volume changes are real data. Preserve
                    # them without treating an unchanged source time as liveness.
                    self.evidence.rules.update_live_quote_session_state(
                        self.evidence.strategy.quote_state, symbol, event,
                        received_at=received, source_mode='official_sdk_push')
                    self.quote_classifications['same_timestamp_no_liveness_credit'] += 1
                    return
                self.quote_source_times[symbol] = source
                self.quote_classifications['fresh_quote'] += 1
                self._emit({'kind': 'quote_state', 'symbol': symbol, 'payload': event,
                            'received_at': received.isoformat(), 'source_mode': 'official_sdk_push'}, now)
            else:
                # Every real trade is retained: equal timestamps are NOT IDs.
                self.trade_count += len(event['trades'])
                self.builder.on_trade(symbol, event, received_at=received,
                    maximum_source_delivery_age_ms=self.config.maximum_source_delivery_age_ms, processed_at=now)
                if symbol in ('SPY.US', 'QQQ.US') and event['trades']:
                    self._emit({'kind': 'market_activity', 'symbol': symbol,
                        'received_at': received.isoformat(), 'source_mode': 'official_sdk_trade_push'}, now)
        elif kind in ('watermark', 'heartbeat'):
            if not self.ready:
                if kind != 'heartbeat' or payload.get('phase') != self.evidence.stage_deadline.phase:
                    raise ValueError('wire_heartbeat_before_ready')
                # Progress is observable, but does not reset phase.started.
                return
            if not tail:
                self._emit({'kind': 'heartbeat'}, now)
            if kind == 'watermark':
                through = stamp(payload['received_through'])
                if through < self.start or through > self.end or through > emitted or through > now:
                    raise ValueError('wire_watermark_outside_prefix')
                if self.watermark is not None and through < self.watermark:
                    raise ValueError('wire_watermark_regressed')
                self.watermark = through
                if tail or through == self.end:
                    return  # Terminal prefix evidence never seals a bar.
                bars = self.builder.complete_boundary(self.symbols, through)
                if bars:
                    self._emit({'kind': 'bars', 'rows': bars}, now)
        elif kind == 'end':
            if not self.ready or payload.get('reason') != 'window_completed':
                raise ValueError('wire_abnormal_end')
            through = stamp(payload['received_through'])
            if through != self.end or now < self.end or emitted < self.end:
                raise ValueError('wire_premature_or_incomplete_end')
            # End is evidence only: never fabricate a final bar after cutoff.
            self.ended = True
            self.end_sequence = seq
        elif kind == 'error':
            raise ValueError('wire_producer_reported_error')
        else:
            raise ValueError('wire_unknown_kind')

    def check(self, *, now=None):
        now = stamp(now or datetime.now(UTC))
        elapsed = time.monotonic() - self.started_mono
        if not math.isfinite(elapsed) or abs((now - self.started_wall).total_seconds() - elapsed) > 2:
            raise ValueError('consumer_clock_discontinuity')
        if now > self.end + timedelta(seconds=5):
            raise ValueError('wire_end_deadline_exceeded')
        if now <= self.end:
            self.evidence.check_deadlines(now)

    def summary(self, reason=None):
        strategy = self.evidence.strategy.summary()
        session = self.evidence.session
        boundaries = session.complete_boundary_count if session else 0
        eligible = ([close for close in session.expected
            if close - timedelta(minutes=self.config.bar_minutes) >= session.not_before
            and close + timedelta(milliseconds=self.config.maximum_source_delivery_age_ms) < self.end]
            if session else [])
        all_boundaries = bool(eligible and set(eligible) == session.boundaries)
        traded = session.realtime_tradable_bar_count if session else 0
        passed = bool(reason is None and self.ended and all_boundaries and traded > 0
                      and self.trade_count > 0 and strategy['strategy_input_coverage_observed']
                      and strategy['strategy_evaluation_count'] > 0)
        return {'schema_version': 1, 'run_id': self.run_id,
            'status': 'window_observed' if passed else ('failed' if reason else 'incomplete'),
            'reason': reason, 'producer_end_observed': self.ended, 'bounded_pipeline_observed': passed,
            'complete_boundary_count': boundaries, 'bar_count': self.evidence.bar_count,
            'window_start_utc': self.start.isoformat(), 'window_end_utc': self.end.isoformat(),
            'expected_complete_boundary_count': len(eligible),
            'all_expected_boundaries_observed': all_boundaries,
            'producer_end_sequence': self.end_sequence,
            'ignored_tail_events': self.ignored_tail_events,
            'quote_classifications': dict(self.quote_classifications),
            'realtime_tradable_bar_count': traded, 'trade_count': self.trade_count,
            'last_sequence': self.sequence, 'message_counts': dict(self.counts),
            'last_watermark': self.watermark.isoformat() if self.watermark else None,
            'strategy_full_acceptance': False, 'full_session_acceptance': False,
            'production_acceptance': False, 'account_access': False, 'order_access': False, **strategy}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stream', 'config', 'output-dir', 'run-id', 'window-start-utc', 'window-end-utc'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    config = rules.load_config(args.config)
    output = Path(args.output_dir)
    consumer = FeedConsumer(config, output, args.run_id, args.window_start_utc, args.window_end_utc)
    stream_path = Path(args.stream)
    stream = None
    pending = b''
    reason = None
    try:
        while not consumer.ended:
            now = datetime.now(UTC)
            if stream is None:
                if stream_path.is_symlink():
                    raise ValueError('wire_stream_symlink')
                if stream_path.exists():
                    stream = stream_path.open('rb')
                else:
                    consumer.check(now=now)
                    time.sleep(.02)
                    continue
            # Consume one finite already-written prefix before liveness checks;
            # a current event on disk must not be mistaken for a silent feed.
            available = os.fstat(stream.fileno()).st_size - stream.tell()
            if available < 0 or available > MAX_PREFIX_BYTES:
                raise ValueError('wire_reader_backlog_or_truncation')
            chunk = stream.read(available)
            if not chunk:
                consumer.check(now=now)
                time.sleep(.02)
                continue
            pending += chunk
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                if len(line) > MAX_LINE_BYTES:
                    raise ValueError('wire_line_size_exceeded')
                row = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('wire_nonfinite_json')))
                if row.get('kind') == 'watermark':
                    through = stamp(row['payload']['received_through'])
                    ahead = (through - datetime.now(UTC)).total_seconds()
                    if ahead > 2:
                        raise ValueError('wire_watermark_in_future')
                    if ahead > 0:
                        # Separate OS clock offsets cannot justify early seals.
                        # This wait is bounded and still counts as processing age.
                        time.sleep(ahead)
                consumer.consume(row, now=datetime.now(UTC))
                if consumer.ended:
                    if pending or stream.read(1):
                        raise ValueError('wire_trailing_content_after_end')
                    break
            if len(pending) > MAX_LINE_BYTES:
                raise ValueError('wire_partial_line_size_exceeded')
            if not consumer.ended:
                consumer.check(now=datetime.now(UTC))
    except BaseException as exc:
        # Only local fixed error names are exposed; never serialize raw input.
        reason = str(exc) if type(exc) is ValueError and str(exc).startswith(('wire_', 'consumer_')) else type(exc).__name__
    finally:
        if stream is not None:
            stream.close()
    result = consumer.summary(reason)
    with (output / 'summary.json').open('x', encoding='utf-8') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    return 0 if result['bounded_pipeline_observed'] else 4


if __name__ == '__main__':
    raise SystemExit(main())
