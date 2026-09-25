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
import tempfile
import time
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_m15_longbridge_quote_diagnostic as diagnostic
from scripts import m15_longbridge_sdk_runtime_lib as rules

MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_PREFIX_BYTES = 16 * 1024 * 1024

# Exact local codes only. Never copy an arbitrary exception message just because
# it resembles one of our prefixes; native exceptions can contain private data.
SAFE_ERROR_CODES = frozenset('''
wire_timestamp_type wire_timestamp_must_be_utc wire_decimal_type
wire_decimal_invalid wire_decimal_range wire_volume_not_integer wire_event_not_object
wire_trades_not_list wire_trade_not_object wire_trade_classification_required
wire_daily_volume_missing wire_identity_or_window_invalid wire_receipt_outside_window_or_emission
wire_processing_backlog wire_receipt_in_future wire_message_after_end wire_run_id_mismatch
wire_sequence_discontinuity wire_payload_not_object wire_emission_outside_window
wire_emission_clock_regressed wire_emission_in_future wire_transfer_backlog
wire_input_after_window_no_backfill wire_daily_after_subscription
wire_daily_symbol_duplicate_or_unknown wire_daily_count_invalid wire_subscription_or_daily_incomplete
wire_initial_snapshot_order wire_initial_snapshot_count wire_initial_snapshot_symbols
wire_snapshot_must_not_be_push_quote wire_quote_timestamp_in_future wire_ready_order
wire_market_event_before_ready wire_market_symbol_unknown wire_tail_receipt_invalid
wire_tail_trade_for_closed_boundary wire_event_behind_watermark wire_quote_session_invalid
wire_heartbeat_before_ready wire_watermark_outside_prefix wire_watermark_regressed
wire_abnormal_end wire_premature_or_incomplete_end wire_producer_reported_error wire_unknown_kind
consumer_clock_discontinuity consumer_status_write_failed consumer_summary_write_failed consumer_evidence_write_failed
wire_end_deadline_exceeded wire_stream_symlink wire_reader_backlog_or_truncation
wire_line_size_exceeded wire_watermark_in_future wire_trailing_content_after_end wire_partial_line_size_exceeded
wire_nonfinite_json diagnostic_reference_market_data_stalled diagnostic_wire_progress_stalled
wire_stage_after_quality_fault
diagnostic_daily_context_not_current_or_complete diagnostic_stale_strategy_bar
quote_worker_reported_failure bars_before_ready duplicate_boundary
market_data_heartbeat_deadline_exceeded reference_market_data_stalled diagnostic_clock_discontinuity
trade_timestamp_invalid trade_timestamp_in_future trade_after_bar_finalized
trade_source_delivery_age_exceeded trade_processing_backlog invalid_boundary_timestamps
invalid_boundary_rows reference_quotes_stale late_boundary_delivery invalid_boundary_provenance
pipeline_config_must_use_external_paths pipeline_config_must_disable_dispatch
diagnostics_must_not_write_production_output diagnostics_output_must_be_outside_worktree
diagnostics_output_must_be_new_or_empty invalid_sdk_stage_start_time
'''.split())
SAFE_ERROR_TYPES = frozenset('''ValueError RuntimeError KeyError TypeError OSError
FileNotFoundError PermissionError TimeoutError OverflowError JSONDecodeError
UnicodeDecodeError KeyboardInterrupt SystemExit MemoryError'''.split())


def safe_exception(error):
    name = type(error).__name__
    result = {'code': 'unclassified_exception', 'error_type': name if name in SAFE_ERROR_TYPES else 'Exception'}
    message = str(error)
    if type(error) in (ValueError, RuntimeError) and message in SAFE_ERROR_CODES:
        result['code'] = message
    elif type(error) is RuntimeError and message.startswith('sdk_stage_deadline_exceeded:'):
        result['code'] = 'sdk_stage_deadline_exceeded'
        phase = message.split(':', 1)[1]
        if phase in ('initializing', 'daily_context', 'subscribing', 'initial_snapshot', 'streaming', 'daily_refresh'):
            result['phase'] = phase
    elif type(error) in (ValueError, RuntimeError) and message.startswith((
            'realtime_bar_boundary_deadline_exceeded:', 'missing_boundary:')):
        result['code'] = message.split(':', 1)[0]
        try:
            result['boundary_utc'] = stamp(message.split(':', 1)[1]).isoformat()
        except (ValueError, TypeError, OverflowError):
            pass
    if error.__cause__ is not None:
        cause = type(error.__cause__).__name__
        result['cause_type'] = cause if cause in SAFE_ERROR_TYPES else 'Exception'
    return result


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


class LatencyHistogram:
    """Bounded millisecond histogram; percentile values are upper bin edges."""
    def __init__(self):
        self.bins = Counter()
        self.minimum = self.maximum = None

    def add(self, milliseconds):
        self.bins[math.ceil(milliseconds)] += 1
        self.minimum = milliseconds if self.minimum is None else min(self.minimum, milliseconds)
        self.maximum = milliseconds if self.maximum is None else max(self.maximum, milliseconds)

    def summary(self):
        ordered = sorted(self.bins.items())
        count = sum(self.bins.values())
        def rank(q):
            remaining = math.ceil(count * q)
            for value, n in ordered:
                remaining -= n
                if remaining <= 0:
                    return value
            return None
        return {'count': count, 'unit': 'milliseconds', 'resolution_ms': 1,
            'quantile_method': 'nearest_rank_upper_bin_edge', 'min': self.minimum, 'max': self.maximum,
            'p50': rank(.5), 'p95': rank(.95), 'p99': rank(.99),
            'histogram_ms_upper_edge': [[value, n] for value, n in ordered]}


class FeedConsumer:
    def __init__(self, config, output, run_id, start, end, *, now=None, diagnostic_capture_after_quality_fault=False):
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
        self.last_consumed_sequence = 0
        self.attempted_sequence = None
        self.last_processed_at = None
        self.last_consumed_watermark = None
        self.last_source_receipt = {}
        self.quote_wire_symbols, self.trade_wire_symbols = set(), set()
        self.fresh_quote_symbols = set()
        self.last_error = None
        self._last_status_write = None
        self.started_wall, self.started_mono = now, time.monotonic()
        self.ready_at = None
        self.latest_by_symbol = {'quote': {}, 'trade': {}, 'qualified_quote': {}, 'qualified_trade': {}}
        self.latencies = {name: LatencyHistogram() for name in (
            'callback_to_dequeue', 'wire_to_dequeue', 'eligible_trade_source_to_callback',
            'bar_oldest_callback_to_judgment', 'bar_latest_callback_to_judgment', 'router_duration')}
        self.bucket_receipts = {}
        self.persisted_bar_count = 0
        self.diagnostic_capture_after_quality_fault = diagnostic_capture_after_quality_fault
        self.first_quality_fault = None
        self.diagnostic_raw_counts = Counter()
        self.diagnostic_reference_progress = {}
        self.diagnostic_trade_label_age_max_ms = None

    def _diagnostic_activity(self, kind, symbol, event, received, *, advance=True):
        """Separate raw source progress from usable strategy data; never feeds builder."""
        events = [event] if kind == 'quote' else event['trades']
        for item in events:
            if item['timestamp'] > received + timedelta(seconds=2):
                raise ValueError('wire_quote_timestamp_in_future' if kind == 'quote' else 'trade_timestamp_in_future')
            session = item.get('trade_session')
            if not isinstance(session, str) or session not in ('Intraday', 'TradeSession.Intraday',
                    'Pre', 'TradeSession.Pre', 'Post', 'TradeSession.Post', 'Overnight', 'TradeSession.Overnight'):
                raise ValueError('wire_quote_session_invalid' if kind == 'quote' else 'wire_trade_classification_required')
            if not advance:
                continue
            if kind == 'trade' and self.first_quality_fault is not None:
                age = (received-item['timestamp']).total_seconds()*1000
                self.diagnostic_trade_label_age_max_ms = (age if self.diagnostic_trade_label_age_max_ms is None
                    else max(self.diagnostic_trade_label_age_max_ms, age))
            if symbol not in ('SPY.US', 'QQQ.US') or session.split('.')[-1] != 'Intraday':
                continue
            if kind == 'trade' and item['trade_type'] not in {'', 'A', 'B', 'D', 'E', 'F', 'K', 'S', 'X', '1', 'C', 'G', 'H', 'I', 'V', 'W'}:
                continue
            key = symbol + ':' + kind
            previous = self.diagnostic_reference_progress.get(key)
            if previous is None or item['timestamp'] > previous['source_event_at']:
                last = previous['received_at'] if previous else self.ready_at
                if self.first_quality_fault is not None and last is not None and received-last > timedelta(seconds=30):
                    raise ValueError('diagnostic_reference_market_data_stalled')
                self.diagnostic_reference_progress[key] = {'source_event_at': item['timestamp'],
                    'received_at': received, 'wire_sequence': self.sequence}

    def _latch_trade_quality_fault(self, symbol, event, received, now):
        # Identify the first execution which can reach the original source-age
        # guard. The original on_trade may already have appended earlier items;
        # freeze that state and never replay this batch or finish those bars.
        candidates = []
        for item in event['trades']:
            source = item['timestamp']
            opened = rules.floor_bar_open(source, self.config.bar_minutes)
            local = source.astimezone(rules.NEW_YORK)
            if (item['price'] > 0 and item['trade_session'].split('.')[-1].lower() == 'intraday'
                    and item['trade_type'] in {'', 'A', 'B', 'D', 'E', 'F', 'K', 'S', 'X', '1', 'C', 'G', 'H', 'I', 'V', 'W'}
                    and local.weekday() < 5 and local.date().isoformat() not in self.config.market_holidays
                    and (local.hour > 9 or local.hour == 9 and local.minute >= 30) and local.hour < 16
                    and (self.builder.complete_bar_open_not_before is None or opened >= self.builder.complete_bar_open_not_before)
                    and received-source > timedelta(milliseconds=self.config.maximum_source_delivery_age_ms)):
                candidates.append(item)
        if not candidates:
            raise ValueError('trade_source_delivery_age_exceeded')
        item = candidates[0]
        self.first_quality_fault = {'code': 'trade_source_delivery_age_exceeded',
            'run_id': self.run_id, 'wire_sequence': self.sequence, 'symbol': symbol,
            'source_event_at': item['timestamp'].isoformat(), 'received_at': received.isoformat(),
            'dequeued_at': now.isoformat(), 'source_label_age_ms': (received-item['timestamp']).total_seconds()*1000,
            'source_timestamp_gap_ms': (received-item['timestamp']).total_seconds()*1000,
            'timestamp_precision_seconds': 1, 'local_clock_offset_applied': False, 'age_basis': 'integer_second_source_label_not_exact_execution_latency',
            'trade_type': item['trade_type'], 'trade_session': item['trade_session'],
            'strategy_evaluations_frozen_at': self.evidence.strategy.evaluations,
            'completed_boundaries_frozen_at': self.evidence.session.complete_boundary_count,
            'partial_builder_state_frozen': True, 'strategy_resume_allowed': False}
        self.diagnostic_trade_label_age_max_ms = self.first_quality_fault['source_label_age_ms']
        self._append_evidence('quality-faults.jsonl', [self.first_quality_fault])

    def _check_diagnostic_progress(self, now):
        if self.last_processed_at is None or now-self.last_processed_at > timedelta(
                seconds=self.config.market_data_heartbeat_deadline_seconds):
            raise ValueError('diagnostic_wire_progress_stalled')
        for symbol in ('SPY.US', 'QQQ.US'):
            for kind in ('quote', 'trade'):
                progress = self.diagnostic_reference_progress.get(symbol + ':' + kind)
                last = progress['received_at'] if progress else self.ready_at
                if last is None or now-last > timedelta(seconds=30):
                    raise ValueError('diagnostic_reference_market_data_stalled')

    def _diagnostic_state(self):
        return {'diagnostic_capture_after_quality_fault': self.diagnostic_capture_after_quality_fault,
            'first_quality_fault': self.first_quality_fault,
            'strategy_frozen': self.first_quality_fault is not None,
            'quality_passed': False if self.first_quality_fault else None,
            'diagnostic_raw_counts_after_fault': dict(self.diagnostic_raw_counts),
            'diagnostic_trade_source_timestamp_gap_max_ms': self.diagnostic_trade_label_age_max_ms,
            'diagnostic_reference_progress': {key: {name: value.isoformat() if isinstance(value, datetime) else value
                for name, value in row.items()} for key, row in self.diagnostic_reference_progress.items()},
            'diagnostic_progress_basis': 'source_timestamp_advancement_not_strategy_quality'}

    def _append_evidence(self, filename, rows):
        try:
            with (self.output/filename).open('a', encoding='utf-8') as out:
                for row in rows:
                    out.write(json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n')
                out.flush()
                os.fsync(out.fileno())
        except (OSError, ValueError, TypeError) as error:
            raise ValueError('consumer_evidence_write_failed') from error

    def _record_boundary(self, bars, now):
        # Preserve the builder output verbatim. Its received_at is bar sealing
        # time, not callback receipt; the separate receipt range prevents that
        # timestamp from disguising delayed input.
        boundary_begin = time.monotonic()
        records = []
        receipt_ranges = []
        for bar in bars:
            key = (bar['symbol'] + '.US', stamp(bar['bar_open_at']))
            receipts = self.bucket_receipts.pop(key, None)
            if receipts:
                receipt_ranges.append(receipts)
            records.append({'schema_version': 1, 'run_id': self.run_id,
                'wire_sequence': self.sequence, 'watermark': self.watermark.isoformat(),
                'formed_at': now.isoformat(), 'bar': dict(bar),
                'classification': ('blocked_carry' if bar['market_data_blocked_reason'] else 'price_forming_trade'),
                'trade_callback_receipts': ({k: v.isoformat() if isinstance(v, datetime) else v
                    for k, v in receipts.items()} if receipts else None),
                'eligible_for_strategy_input': not bool(bar['market_data_blocked_reason'])})
        self._append_evidence('bar-evidence.jsonl', records)
        self.persisted_bar_count += len(records)
        before = self.evidence.strategy.evaluations
        begin = time.monotonic()
        judgment_started = now + timedelta(seconds=max(0, begin-boundary_begin))
        failure = None
        try:
            self._emit({'kind': 'bars', 'rows': bars}, judgment_started)
        except BaseException as error:
            failure = safe_exception(error)
            self.record_error(error, now=now, during='boundary_judgment')
            raise
        finally:
            duration = max(0, time.monotonic() - begin)
            finished = judgment_started + timedelta(seconds=duration)
            self.latencies['router_duration'].add(duration*1000)
            for receipts in receipt_ranges:
                for key, field in (('bar_oldest_callback_to_judgment', 'first_received_at'),
                                   ('bar_latest_callback_to_judgment', 'last_received_at')):
                    self.latencies[key].add((finished-receipts[field]).total_seconds()*1000)
            self._append_evidence('boundary-evidence.jsonl', [{'schema_version': 1,
                'run_id': self.run_id, 'wire_sequence': self.sequence,
                'bar_close_at': bars[0]['bar_close_at'], 'watermark': self.watermark.isoformat(),
                'dequeued_at': now.isoformat(), 'judgment_started_at': judgment_started.isoformat(),
                'judgment_finished_at': finished.isoformat(),
                'duration_ms': duration*1000, 'bar_count': len(bars),
                'strategy_evaluations_before': before,
                'strategy_evaluations_after': self.evidence.strategy.evaluations,
                'accepted': failure is None, 'error': failure}])

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

    def record_error(self, error, *, now=None, during='runner'):
        if self.last_error is None:
            self.last_error = {**safe_exception(error), 'observed_at': stamp(now or datetime.now(UTC)).isoformat(),
                'during': during, 'attempted_sequence': self.attempted_sequence,
                'last_consumed_sequence': self.last_consumed_sequence}

    def consume(self, row, *, now=None):
        now = stamp(now or datetime.now(UTC))
        seq = row.get('sequence') if isinstance(row, dict) else None
        self.attempted_sequence = seq if type(seq) is int and 0 < seq < 2**63 else None
        try:
            self._consume_record(row, now=now)
        except BaseException as error:
            self.record_error(error, now=now, during='consume')
            raise
        self.last_consumed_sequence = self.sequence
        self.last_processed_at = now
        kind, payload = row['kind'], row['payload']
        if self.first_quality_fault is not None:
            self.diagnostic_raw_counts[kind] += 1
            if kind == 'trade':
                self.diagnostic_raw_counts['trade_executions'] += len(payload['event']['trades'])
        if kind == 'watermark':
            self.last_consumed_watermark = self.watermark
        if kind in ('quote', 'trade') and now <= self.end:
            received = stamp(payload['received_at'])
            if self.start <= received < self.end:
                events = [payload['event']] if kind == 'quote' else payload['event']['trades']
                if events:
                    covered = self.quote_wire_symbols if kind == 'quote' else self.trade_wire_symbols
                    covered.add(payload['symbol'])
                    self.latest_by_symbol[kind][payload['symbol']] = {'received_at': received,
                        'source_event_at': max(stamp(event['timestamp']) for event in events)}
                    self.latencies['callback_to_dequeue'].add((now-received).total_seconds()*1000)
                    self.latencies['wire_to_dequeue'].add((now-stamp(row['emitted_at'])).total_seconds()*1000)
                    self.last_source_receipt[kind] = {'received_at': received.isoformat(),
                        'source_event_at': max(stamp(event['timestamp']) for event in events).isoformat(),
                        'wire_sequence': self.sequence}

    def _consume_record(self, row, *, now):
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
            if self.first_quality_fault is not None:
                raise ValueError('wire_stage_after_quality_fault')
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
            self.ready_at = now
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
                if self.diagnostic_capture_after_quality_fault:
                    self._diagnostic_activity(kind, symbol, event, received, advance=False)
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
            if self.diagnostic_capture_after_quality_fault:
                self._diagnostic_activity(kind, symbol, event, received)
            if self.first_quality_fault is not None:
                if kind == 'trade':
                    self.trade_count += len(event['trades'])
                return
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
                self.fresh_quote_symbols.add(symbol)
                self.latest_by_symbol['qualified_quote'][symbol] = {'received_at': received, 'source_event_at': source}
                self._emit({'kind': 'quote_state', 'symbol': symbol, 'payload': event,
                            'received_at': received.isoformat(), 'source_mode': 'official_sdk_push'}, now)
            else:
                # Every real trade is retained: equal timestamps are NOT IDs.
                self.trade_count += len(event['trades'])
                try:
                    self.builder.on_trade(symbol, event, received_at=received,
                        maximum_source_delivery_age_ms=self.config.maximum_source_delivery_age_ms, processed_at=now)
                except ValueError as error:
                    if not self.diagnostic_capture_after_quality_fault or str(error) != 'trade_source_delivery_age_exceeded':
                        raise
                    self._latch_trade_quality_fault(symbol, event, received, now)
                    return
                for trade in event['trades']:
                    opened = rules.floor_bar_open(trade['timestamp'], self.config.bar_minutes)
                    key = (symbol, opened)
                    if (key not in self.builder._bars or
                            trade['trade_session'].split('.')[-1].lower() != 'intraday' or
                            trade['trade_type'] not in {'', 'A', 'B', 'D', 'E', 'F', 'K', 'S', 'X', '1', 'C', 'G', 'H', 'I', 'V', 'W'}):
                        continue
                    previous = self.latest_by_symbol['qualified_trade'].get(symbol)
                    if previous is None or trade['timestamp'] > previous['source_event_at']:
                        self.latest_by_symbol['qualified_trade'][symbol] = {
                            'received_at': received, 'source_event_at': trade['timestamp']}
                    self.latencies['eligible_trade_source_to_callback'].add(
                        (received-trade['timestamp']).total_seconds()*1000)
                    receipt = self.bucket_receipts.setdefault(key, {'first_received_at': received,
                        'last_received_at': received, 'trade_count': 0, 'max_callback_to_dequeue_ms': 0})
                    receipt['first_received_at'] = min(receipt['first_received_at'], received)
                    receipt['last_received_at'] = max(receipt['last_received_at'], received)
                    receipt['trade_count'] += 1
                    receipt['max_callback_to_dequeue_ms'] = max(receipt['max_callback_to_dequeue_ms'],
                        (now-received).total_seconds()*1000)
                if symbol in ('SPY.US', 'QQQ.US') and event['trades']:
                    self._emit({'kind': 'market_activity', 'symbol': symbol,
                        'received_at': received.isoformat(), 'source_mode': 'official_sdk_trade_push'}, now)
        elif kind in ('watermark', 'heartbeat'):
            if not self.ready:
                if kind != 'heartbeat' or payload.get('phase') != self.evidence.stage_deadline.phase:
                    raise ValueError('wire_heartbeat_before_ready')
                # Progress is observable, but does not reset phase.started.
                return
            if not tail and self.first_quality_fault is None:
                self._emit({'kind': 'heartbeat'}, now)
            if kind == 'watermark':
                through = stamp(payload['received_through'])
                if through < self.start or through > self.end or through > emitted or through > now:
                    raise ValueError('wire_watermark_outside_prefix')
                if self.watermark is not None and through < self.watermark:
                    raise ValueError('wire_watermark_regressed')
                self.watermark = through
                if tail or through == self.end or self.first_quality_fault is not None:
                    return  # Terminal prefix evidence never seals a bar.
                bars = self.builder.complete_boundary(self.symbols, through)
                if bars:
                    self._record_boundary(bars, now)
        elif kind == 'end':
            if not self.ready or payload.get('reason') != 'window_completed':
                raise ValueError('wire_abnormal_end')
            through = stamp(payload['received_through'])
            if through != self.end or now < self.end or emitted < self.end:
                raise ValueError('wire_premature_or_incomplete_end')
            if self.first_quality_fault is not None:
                self._check(now=now)
                if self.watermark != self.end:
                    raise ValueError('wire_premature_or_incomplete_end')
            # End is evidence only: never fabricate a final bar after cutoff.
            self.ended = True
            self.end_sequence = seq
        elif kind == 'error':
            raise ValueError('wire_producer_reported_error')
        else:
            raise ValueError('wire_unknown_kind')

    def check(self, *, now=None):
        try:
            self._check(now=now)
        except BaseException as error:
            self.record_error(error, now=now, during='deadline_check')
            raise

    def _check(self, *, now=None):
        now = stamp(now or datetime.now(UTC))
        elapsed = time.monotonic() - self.started_mono
        if not math.isfinite(elapsed) or abs((now - self.started_wall).total_seconds() - elapsed) > 2:
            raise ValueError('consumer_clock_discontinuity')
        if now > self.end + timedelta(seconds=5):
            raise ValueError('wire_end_deadline_exceeded')
        if self.first_quality_fault is not None:
            self._check_diagnostic_progress(min(now, self.end))
        elif now <= self.end:
            self.evidence.check_deadlines(now)

    def live_status(self, *, now=None):
        now = stamp(now or datetime.now(UTC))
        freshness = {}
        for kind, symbols in self.latest_by_symbol.items():
            ages = {symbol: {'received_at': row['received_at'].isoformat(),
                'source_event_at': row['source_event_at'].isoformat(),
                'receipt_age_ms': (now-row['received_at']).total_seconds()*1000,
                'source_age_ms': (now-row['source_event_at']).total_seconds()*1000}
                for symbol, row in symbols.items()}
            freshness[kind] = {'symbols': ages, 'never_observed_symbols': sorted(set(self.symbols)-set(ages)),
                'receipt_within_existing_2000ms_count': sum(-2000 <= row['receipt_age_ms'] <=
                    self.config.maximum_source_delivery_age_ms for row in ages.values()),
                'basis': 'age_at_observed_at_quiet_symbols_not_inferred_failed'}
        session = self.evidence.session
        return {'schema_version': 1, 'run_id': self.run_id,
            'observed_at': stamp(now or datetime.now(UTC)).isoformat(),
            'status': ('failed' if self.last_error else
                       'diagnostic_capture_complete' if self.ended and self.first_quality_fault else
                       'finished' if self.ended else
                       'diagnostic_capture_quality_failed' if self.first_quality_fault else
                       'observing' if self.ready else 'initializing'),
            'phase': self.evidence.stage_deadline.phase,
            'last_consumed_sequence': self.last_consumed_sequence,
            'attempted_sequence': self.attempted_sequence,
            'last_processed_at': self.last_processed_at.isoformat() if self.last_processed_at else None,
            'last_source_receipt': self.last_source_receipt,
            'current_freshness': freshness,
            'quote_wire_symbol_count': len(self.quote_wire_symbols),
            'trade_wire_symbol_count': len(self.trade_wire_symbols),
            'fresh_quote_symbol_count': len(self.fresh_quote_symbols),
            'coverage_basis': 'cumulative_consumed_events_since_start_not_current_freshness',
            'trade_count': self.trade_count,
            'last_watermark': self.last_consumed_watermark.isoformat() if self.last_consumed_watermark else None,
            'attempted_watermark': self.watermark.isoformat() if self.watermark else None,
            'complete_boundary_count': session.complete_boundary_count if session else 0,
            'bar_count': self.evidence.bar_count,
            'strategy_evaluation_count': self.evidence.strategy.evaluations,
            'producer_end_observed': self.ended, 'last_error': self.last_error, **self._diagnostic_state(),
            'production_acceptance': False, 'full_session_acceptance': False}

    def write_status(self, *, now=None, force=False):
        mono = time.monotonic()
        if not force and self._last_status_write is not None and mono - self._last_status_write < 1:
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.output,
                    prefix='.live-status-', suffix='.tmp', delete=False) as out:
                temporary = Path(out.name)
                json.dump(self.live_status(now=now), out, separators=(',', ':'), allow_nan=False)
                out.write('\n'); out.flush(); os.fsync(out.fileno())
            os.replace(temporary, self.output/'live-status.json')
            self._last_status_write = mono
        except BaseException as error:
            failure = ValueError('consumer_status_write_failed')
            failure.__cause__ = error
            self.record_error(failure, now=now, during='status_write')
            raise failure from error
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def summary(self, reason=None):
        reason = self.last_error['code'] if self.last_error else reason
        strategy = self.evidence.strategy.summary()
        session = self.evidence.session
        boundaries = session.complete_boundary_count if session else 0
        eligible = ([close for close in session.expected
            if close - timedelta(minutes=self.config.bar_minutes) >= session.not_before
            and close + timedelta(milliseconds=self.config.maximum_source_delivery_age_ms) < self.end]
            if session else [])
        all_boundaries = bool(eligible and set(eligible) == session.boundaries)
        traded = session.realtime_tradable_bar_count if session else 0
        passed = bool(self.first_quality_fault is None and reason is None and self.ended and all_boundaries and traded > 0
                      and self.trade_count > 0 and strategy['strategy_input_coverage_observed']
                      and strategy['strategy_evaluation_count'] > 0)
        capture_complete = bool(self.first_quality_fault is not None and reason is None and self.ended
            and self.watermark == self.end and len(self.diagnostic_reference_progress) == 4)
        return {'schema_version': 1, 'run_id': self.run_id,
            'status': 'diagnostic_capture_complete' if capture_complete else 'window_observed' if passed else ('failed' if reason else 'incomplete'),
            'diagnostic_capture_complete': capture_complete, **self._diagnostic_state(),
            'reason': reason, 'producer_end_observed': self.ended, 'bounded_pipeline_observed': passed,
            'complete_boundary_count': boundaries, 'bar_count': self.evidence.bar_count,
            'window_start_utc': self.start.isoformat(), 'window_end_utc': self.end.isoformat(),
            'expected_complete_boundary_count': len(eligible),
            'all_expected_boundaries_observed': all_boundaries,
            'producer_end_sequence': self.end_sequence,
            'ignored_tail_events': self.ignored_tail_events,
            'ready_at': self.ready_at.isoformat() if self.ready_at else None,
            'symbols': list(self.symbols), 'persisted_bar_count': self.persisted_bar_count,
            'maximum_source_delivery_age_ms': self.config.maximum_source_delivery_age_ms,
            'latency_evidence': {name: hist.summary() for name, hist in self.latencies.items()},
            'quote_classifications': dict(self.quote_classifications),
            'realtime_tradable_bar_count': traded, 'trade_count': self.trade_count,
            'last_sequence': self.sequence, 'message_counts': dict(self.counts),
            'last_consumed_sequence': self.last_consumed_sequence,
            'last_error': self.last_error,
            'last_watermark': self.watermark.isoformat() if self.watermark else None,
            'strategy_full_acceptance': False, 'full_session_acceptance': False,
            'production_acceptance': False, 'account_access': False, 'order_access': False, **strategy}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stream', 'config', 'output-dir', 'run-id', 'window-start-utc', 'window-end-utc'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--diagnostic-capture-after-quality-fault', action='store_true',
        help='Only for a separately authorized intraday diagnostic; freezes strategy on source-age failure and retains raw capture.')
    args = parser.parse_args()
    output = Path(args.output_dir)
    try:
        config = rules.load_config(args.config)
        consumer = FeedConsumer(config, output, args.run_id, args.window_start_utc, args.window_end_utc,
            diagnostic_capture_after_quality_fault=args.diagnostic_capture_after_quality_fault)
    except BaseException as error:
        # Paths have not necessarily passed validation: do not write to them.
        print(json.dumps({'status': 'failed', 'phase': 'initializing', 'error': safe_exception(error)}), file=sys.stderr)
        return 4
    stream_path = Path(args.stream)
    stream = None
    pending = b''
    reason = None
    try:
        consumer.write_status(force=True)
        while not consumer.ended:
            now = datetime.now(UTC)
            if stream is None:
                if stream_path.is_symlink():
                    raise ValueError('wire_stream_symlink')
                if stream_path.exists():
                    stream = stream_path.open('rb')
                else:
                    consumer.check(now=now)
                    consumer.write_status(now=now)
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
                consumer.write_status(now=now)
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
                consumer.write_status()
    except BaseException as exc:
        consumer.record_error(exc)
        reason = consumer.last_error['code']
    finally:
        if stream is not None:
            stream.close()
    try:
        consumer.write_status(force=True)
    except BaseException as error:
        consumer.record_error(error)
        reason = consumer.last_error['code']
    result = consumer.summary(reason)
    try:
        with (output / 'summary.json').open('x', encoding='utf-8') as out:
            json.dump(result, out, indent=2)
            out.write('\n')
    except BaseException as error:
        consumer.record_error(ValueError('consumer_summary_write_failed'), during='summary_write')
        try:
            consumer.write_status(force=True)
        except BaseException:
            pass  # Safe stderr plus nonzero exit remains authoritative.
        print(json.dumps({'status': 'failed', 'last_error': consumer.last_error,
            'summary_write_error': safe_exception(error)}), file=sys.stderr)
        return 4
    return 5 if result.get('diagnostic_capture_complete') is True else 0 if result['bounded_pipeline_observed'] else 4


if __name__ == '__main__':
    raise SystemExit(main())
