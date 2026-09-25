from contextlib import ExitStack, redirect_stderr
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import io
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import m15_windows_feed_consumer as consumer
from scripts import run_m15_longbridge_quote_diagnostic as diagnostic
from scripts import run_m15_longbridge_sdk_runtime as runtime


class WindowsFeedConsumerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.symbols = ('SPY.US', 'QQQ.US')
        for module in (consumer.rules, diagnostic, runtime):
            for name in ('configured_symbols', 'configured_trading_symbols'):
                if hasattr(module, name):
                    self.stack.enter_context(patch.object(module, name, return_value=self.symbols))
        self.stack.enter_context(patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')))
        self.stack.enter_context(patch.object(runtime, 'build_sdk_trade_clients', side_effect=AssertionError('orders forbidden')))
        self.start = datetime(2026, 9, 24, 13, 30, 1, tzinfo=UTC)
        self.end = datetime(2026, 9, 24, 13, 40, 5, tzinfo=UTC)
        self.now = self.start
        self.config = replace(runtime.load_config(), output_dir=self.root/'unused',
            market_events_path=self.root/'market', runtime_status_path=self.root/'state',
            readonly_gate_path=self.root/'gate', daily_context_path=self.root/'daily',
            paper_order_dispatch_enabled=False)
        self.c = consumer.FeedConsumer(self.config, self.root/'evidence', str(uuid4()),
                                      self.start, self.end, now=self.now)

    def row(self, kind, payload, **changes):
        return {'run_id': self.c.run_id, 'sequence': self.c.sequence+1, 'kind': kind,
                'emitted_at': self.now.isoformat(), 'payload': payload, **changes}

    def send(self, kind, payload):
        self.c.consume(self.row(kind, payload), now=self.now)

    def daily(self):
        rows = []
        day = datetime(2026, 9, 23, 20, tzinfo=UTC)
        while len(rows) < 60:
            if day.weekday() < 5:
                rows.append({'timestamp': day.isoformat(), 'open': '100', 'high': '101',
                             'low': '99', 'close': '100.123456789', 'volume': 100})
            day -= timedelta(days=1)
        return list(reversed(rows))

    def ready(self):
        for phase in ('initializing', 'daily_context'):
            self.send('stage', {'phase': phase})
        for symbol in self.symbols:
            self.send('daily_context', {'symbol': symbol, 'received_at': self.now.isoformat(),
                                       'candlesticks': self.daily()})
        self.send('stage', {'phase': 'subscribing'})
        self.send('subscribed', {'symbols': list(self.symbols)})
        self.send('stage', {'phase': 'initial_snapshot'})
        self.send('initial_snapshot', {'received_at': self.now.isoformat(), 'quotes': [
            {'symbol': symbol, 'timestamp': self.now.isoformat(), 'last_done': '100', 'volume': 100}
            for symbol in self.symbols]})
        self.send('ready', {})
        self.send('stage', {'phase': 'streaming'})

    def quote(self, symbol):
        self.send('quote', {'symbol': symbol, 'received_at': self.now.isoformat(),
            'event': {'timestamp': self.now.isoformat(), 'last_done': '100', 'volume': 104,
                      'trade_session': 'Intraday'}})

    def trades(self, symbol):
        self.send('trade', {'symbol': symbol, 'received_at': self.now.isoformat(), 'event': {'trades': [
            {'timestamp': self.now.isoformat(), 'price': '100.123456789', 'volume': 1,
             'trade_type': '', 'trade_session': 'Intraday'},
            {'timestamp': self.now.isoformat(), 'price': '101.123456789', 'volume': 3,
             'trade_type': '', 'trade_session': 'Intraday'}]}})

    def test_original_receipts_and_quiet_carry_are_durable_without_entry_credit(self):
        self.ready()
        self.now = self.start.replace(minute=35, second=1)
        self.quote('SPY.US')
        self.trades('SPY.US')
        original = self.now
        self.now = self.start.replace(minute=40, second=2)
        for symbol in self.symbols:
            self.quote(symbol)
        self.send('watermark', {'received_through': self.now.isoformat()})
        rows = [json.loads(line) for line in (self.c.output/'bar-evidence.jsonl').read_text().splitlines()]
        spy = next(row for row in rows if row['bar']['symbol'] == 'SPY')
        quiet = next(row for row in rows if row['bar']['symbol'] == 'QQQ')
        self.assertEqual(spy['trade_callback_receipts']['first_received_at'], original.isoformat())
        self.assertEqual(spy['trade_callback_receipts']['trade_count'], 2)
        self.assertEqual(quiet['classification'], 'blocked_carry')
        self.assertFalse(quiet['eligible_for_strategy_input'])
        self.assertEqual(quiet['bar']['market_data_blocked_reason'], 'no_trade_carry_forward')
        self.assertNotIn('QQQ', {row['symbol'] for row in self.c.evidence.strategy.context.rows()})
        status = self.c.live_status(now=self.now+timedelta(seconds=4))
        self.assertEqual(status['fresh_quote_symbol_count'], 2)
        self.assertEqual(status['current_freshness']['qualified_quote']['receipt_within_existing_2000ms_count'], 0)
        hist = self.c.summary()['latency_evidence']['bar_latest_callback_to_judgment']
        self.assertEqual(hist['count'], 1)
        self.assertGreaterEqual(hist['min'], 301000)

    def test_slow_bar_audit_write_does_not_refresh_or_hide_processing_age(self):
        self.ready()
        self.now = self.start.replace(minute=35, second=1)
        for symbol in self.symbols:
            self.quote(symbol)
            self.trades(symbol)
        self.now = self.start.replace(minute=40, second=2)
        for symbol in self.symbols:
            self.quote(symbol)
        mono = [100.0]
        original = self.c._append_evidence
        def slow(filename, rows):
            original(filename, rows)
            mono[0] += 3
        with patch.object(consumer.time, 'monotonic', side_effect=lambda: mono[0]), \
                patch.object(self.c, '_append_evidence', side_effect=slow):
            with self.assertRaises((ValueError, RuntimeError)):
                self.send('watermark', {'received_through': self.now.isoformat()})
        self.assertEqual(self.c.evidence.strategy.evaluations, 0)
        self.assertIsNotNone(self.c.last_error)

    def test_evidence_write_failure_cannot_leave_healthy_boundary(self):
        self.ready()
        self.now = self.start.replace(minute=35, second=1)
        for symbol in self.symbols:
            self.quote(symbol)
            self.trades(symbol)
        self.now = self.start.replace(minute=40, second=2)
        for symbol in self.symbols:
            self.quote(symbol)
        with patch.object(Path, 'open', side_effect=OSError('private storage detail')):
            with self.assertRaisesRegex(ValueError, '^consumer_evidence_write_failed$'):
                self.send('watermark', {'received_through': self.now.isoformat()})
        self.assertEqual(self.c.last_error['code'], 'consumer_evidence_write_failed')
        self.assertEqual(self.c.evidence.strategy.evaluations, 0)

    def test_actual_builder_and_original_router_equal_timestamp_trades_retained(self):
        self.ready()
        self.now = self.start.replace(minute=35, second=1)
        for symbol in self.symbols:
            self.quote(symbol)
            self.trades(symbol)
        self.now = self.start.replace(minute=40, second=2)
        for symbol in self.symbols:
            self.quote(symbol)
        self.send('watermark', {'received_through': self.now.isoformat()})
        self.assertEqual(self.c.evidence.session.complete_boundary_count, 1)
        self.assertEqual(self.c.evidence.strategy.evaluations, 1)
        self.assertEqual(self.c.trade_count, 4)
        rows = self.c.evidence.strategy.context.rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(Decimal(str(r['volume'])) == 4 for r in rows))
        self.assertTrue(all(Decimal(str(r['high'])) == Decimal('101.123456789') for r in rows))
        self.now = self.end
        self.send('end', {'reason': 'window_completed', 'received_through': self.end.isoformat()})
        result = self.c.summary()
        self.assertTrue(result['bounded_pipeline_observed'])
        self.assertFalse(result['strategy_full_acceptance'])
        record = json.loads((self.root/'evidence/strategy/boundary_decisions.jsonl').read_text())
        self.assertEqual(len(record['allowed_runtime_ids']), 8)
        self.assertTrue(any(x['input_status'] == 'insufficient_declared_context' for x in record['runtime_context']))

    def test_wrong_run_and_sequence_rejected(self):
        for changes in ({'run_id': str(uuid4())}, {'sequence': 2}, {'sequence': True}):
            with self.assertRaises(ValueError):
                self.c.consume(self.row('stage', {'phase': 'initializing'}, **changes), now=self.now)

    def test_stale_partial_daily_rejected_before_router(self):
        self.send('stage', {'phase': 'daily_context'})
        for symbol in self.symbols:
            rows = self.daily()
            rows[-1]['timestamp'] = rows[-2]['timestamp']
            self.send('daily_context', {'symbol': symbol, 'received_at': self.now.isoformat(), 'candlesticks': rows})
        self.send('stage', {'phase': 'subscribing'})
        with self.assertRaisesRegex(RuntimeError, 'daily_context_not_current'):
            self.send('subscribed', {'symbols': list(self.symbols)})
        self.assertEqual(self.c.evidence.strategy.evaluations, 0)

    def test_partial_initial_bucket_and_eof_do_not_create_bar(self):
        self.ready()
        self.assertEqual(self.c.builder.complete_bar_open_not_before.minute, 35)
        self.now = self.start.replace(minute=34)
        self.trades('SPY.US')
        self.now = self.start.replace(minute=35, second=2)
        self.send('watermark', {'received_through': self.now.isoformat()})
        self.assertEqual(self.c.evidence.bar_count, 0)
        self.assertFalse(self.c.summary()['bounded_pipeline_observed'])

    def test_watermark_regression_future_and_event_behind_prefix_rejected(self):
        self.ready()
        self.send('watermark', {'received_through': self.now.isoformat()})
        with self.assertRaisesRegex(ValueError, 'behind_watermark'):
            self.quote('SPY.US')
        with self.assertRaisesRegex(ValueError, 'watermark'):
            self.send('watermark', {'received_through': (self.now+timedelta(seconds=3)).isoformat()})

    def test_source_receipt_not_refreshed_at_linux(self):
        self.ready()
        old = self.now
        self.now += timedelta(seconds=3)
        with self.assertRaisesRegex(ValueError, 'processing_backlog'):
            self.send('trade', {'symbol': 'SPY.US', 'received_at': old.isoformat(), 'event': {'trades': []}})

    def test_future_quote_rejected_before_mutating_builder(self):
        self.ready()
        before = self.c.builder._latest_quote_at['SPY.US']
        with self.assertRaisesRegex(ValueError, 'quote_timestamp_in_future'):
            self.send('quote', {'symbol': 'SPY.US', 'received_at': self.now.isoformat(),
                'event': {'timestamp': (self.now+timedelta(seconds=120)).isoformat(), 'last_done': '777',
                          'trade_session': 'Intraday'}})
        self.assertEqual(self.c.builder._latest_quote_at['SPY.US'], before)
        self.assertEqual(self.c.builder._latest_quote_price['SPY.US'], Decimal('100'))

    def test_opening_session_old_zero_ohlc_quote_does_not_pollute_or_renew(self):
        self.ready()
        self.now += timedelta(seconds=1)
        self.quote('QQQ.US')
        prior_price = self.c.builder._latest_quote_price['QQQ.US']
        prior_state = dict(self.c.evidence.strategy.quote_state['QQQ'])
        prior_activity = self.c.evidence.last_push_at['QQQ.US']
        self.now += timedelta(milliseconds=300)
        # Actual case021 payload: Pre -> Intraday, last trade rolls to 13:20,
        # zero OHLC and volume, while callback delivery remains timely.
        self.send('quote', {'symbol': 'QQQ.US', 'received_at': self.now.isoformat(), 'event': {
            'timestamp': self.now.replace(minute=20, second=0, microsecond=0).isoformat(),
            'last_done': '741.210', 'open': '0', 'high': '0', 'low': '0',
            'volume': 0, 'trade_session': 'TradeSession.Intraday'}})
        self.assertEqual(self.c.builder._latest_quote_price['QQQ.US'], prior_price)
        self.assertEqual(self.c.evidence.strategy.quote_state['QQQ'], prior_state)
        self.assertEqual(self.c.evidence.last_push_at['QQQ.US'], prior_activity)
        self.assertEqual(self.c.quote_classifications['regressed_quote_no_credit'], 1)

    def test_same_second_quote_updates_value_but_not_reference_liveness(self):
        self.ready()
        self.now += timedelta(seconds=1)
        self.quote('QQQ.US')
        source = self.now
        prior_activity = self.c.evidence.last_push_at['QQQ.US']
        self.now += timedelta(milliseconds=100)
        self.send('quote', {'symbol': 'QQQ.US', 'received_at': self.now.isoformat(),
            'event': {'timestamp': source.isoformat(), 'last_done': '101', 'volume': 105,
                      'trade_session': 'Intraday'}})
        self.assertEqual(self.c.builder._latest_quote_price['QQQ.US'], Decimal('101'))
        self.assertEqual(self.c.evidence.last_push_at['QQQ.US'], prior_activity)

    def test_non_regular_quote_does_not_poison_intraday_volume_or_baseline(self):
        # The official snapshot starts on the previous regular trading day;
        # pre-market lives in separate SDK fields and must never replace it.
        yesterday = self.now - timedelta(days=1)
        original_send = self.send
        def snapshot_from_previous_day(kind, payload):
            if kind == 'initial_snapshot':
                for item in payload['quotes']:
                    item.update(timestamp=yesterday.isoformat(), open='99', high='102', low='98', volume=5000000)
            original_send(kind, payload)
        with patch.object(self, 'send', side_effect=snapshot_from_previous_day):
            self.ready()
        previous_source = self.c.quote_source_times['QQQ.US']
        previous_state = dict(self.c.evidence.strategy.quote_state['QQQ'])
        previous_price = self.c.builder._latest_quote_price['QQQ.US']
        self.now += timedelta(milliseconds=100)
        self.send('quote', {'symbol': 'QQQ.US', 'received_at': self.now.isoformat(), 'event': {
            'timestamp': self.now.isoformat(), 'last_done': '735.270', 'open': '0', 'high': '0', 'low': '0',
            'volume': 1132819, 'trade_session': 'TradeSession.Pre'}})
        self.assertEqual(self.c.quote_source_times['QQQ.US'], previous_source)
        self.assertEqual(self.c.evidence.strategy.quote_state['QQQ'], previous_state)
        self.assertEqual(self.c.builder._latest_quote_price['QQQ.US'], previous_price)
        self.assertNotIn('QQQ.US', self.c.evidence.last_push_at)
        self.send('quote', {'symbol': 'QQQ.US', 'received_at': self.now.isoformat(), 'event': {
            'timestamp': self.now.replace(minute=20, second=0, microsecond=0).isoformat(),
            'last_done': '741.210', 'open': '0', 'high': '0', 'low': '0',
            'volume': 0, 'trade_session': 'TradeSession.Intraday'}})
        self.assertEqual(self.c.evidence.strategy.quote_state['QQQ'], previous_state)
        self.now += timedelta(seconds=1)
        self.send('quote', {'symbol': 'QQQ.US', 'received_at': self.now.isoformat(), 'event': {
            'timestamp': self.now.isoformat(), 'last_done': '740', 'open': '740', 'high': '741', 'low': '739',
            'volume': 5, 'trade_session': 'TradeSession.Intraday'}})
        state = self.c.evidence.strategy.quote_state['QQQ']
        self.assertEqual(state['volume'], '5')
        self.assertEqual(state['market_data_blocked_reason'], '')
        self.assertEqual(self.c.builder._latest_quote_price['QQQ.US'], Decimal('740'))

    def test_non_regular_session_does_not_bypass_future_or_backlog_guards(self):
        self.ready()
        self.now += timedelta(seconds=4)
        event = {'timestamp': (self.now+timedelta(seconds=120)).isoformat(),
                 'last_done': '735', 'trade_session': 'Pre'}
        with self.assertRaisesRegex(ValueError, 'quote_timestamp_in_future'):
            self.send('quote', {'symbol': 'QQQ.US', 'received_at': self.now.isoformat(), 'event': event})
        with self.assertRaisesRegex(ValueError, 'processing_backlog'):
            self.send('quote', {'symbol': 'QQQ.US', 'received_at': (self.now-timedelta(seconds=3)).isoformat(), 'event': event})
        for invalid in (None, '', 'Unknown', 0):
            with self.assertRaisesRegex(ValueError, 'quote_session_invalid'):
                self.send('quote', {'symbol': 'QQQ.US', 'received_at': self.now.isoformat(), 'event': {
                    'timestamp': self.now.isoformat(), 'last_done': '735', 'trade_session': invalid}})

    def test_end_never_seals_missing_tail_and_no_late_backfill(self):
        self.ready()
        self.now = self.end+timedelta(milliseconds=50)
        self.send('watermark', {'received_through': self.end.isoformat()})
        self.send('end', {'reason': 'window_completed', 'received_through': self.end.isoformat()})
        self.assertFalse(self.c.summary()['bounded_pipeline_observed'])
        self.assertEqual(self.c.evidence.bar_count, 0)

    def test_strict_precision_timezone_and_trade_classification(self):
        row = consumer.restore_event({'timestamp': self.now.isoformat(), 'last_done': '0.1234567890123456789'}, 'quote')
        self.assertEqual(row['last_done'], Decimal('0.1234567890123456789'))
        for value in ('NaN', 'Infinity', '-1', 1.1):
            with self.assertRaises(ValueError):
                consumer.amount(value)
        with self.assertRaises(ValueError):
            consumer.stamp('2026-09-24T13:30:01')
        with self.assertRaises(ValueError):
            consumer.restore_event({'trades': [{'timestamp': self.now.isoformat(), 'price': '1', 'volume': 1}]}, 'trade')

    def test_windows_monotonic_is_not_reused_and_duplicate_stage_does_not_renew(self):
        self.send('stage', {'phase': 'daily_context', 'started_monotonic': -999999999})
        initial = self.c.evidence.stage_deadline.started
        self.send('stage', {'phase': 'daily_context', 'started_monotonic': 999999999999})
        self.assertEqual(initial, self.c.evidence.stage_deadline.started)
        self.assertGreater(initial, 0)
        self.send('heartbeat', {'phase': 'daily_context'})
        self.assertEqual(initial, self.c.evidence.stage_deadline.started)

    def test_terminal_watermark_cannot_cover_missing_eligible_boundaries(self):
        self.ready()
        self.now = self.end + timedelta(milliseconds=100)
        self.send('watermark', {'received_through': self.end.isoformat()})
        self.send('end', {'reason': 'window_completed', 'received_through': self.end.isoformat()})
        result = self.c.summary()
        self.assertEqual(result['expected_complete_boundary_count'], 1)
        self.assertFalse(result['all_expected_boundaries_observed'])
        self.assertFalse(result['bounded_pipeline_observed'])

    def test_tail_market_event_is_not_used_and_old_bucket_trade_fails(self):
        self.ready()
        self.now = self.end + timedelta(milliseconds=100)
        self.quote('SPY.US')
        self.assertEqual(self.c.ignored_tail_events, 1)
        old = self.end - timedelta(seconds=6)
        with self.assertRaisesRegex(ValueError, 'tail_trade_for_closed_boundary'):
            self.send('trade', {'symbol': 'SPY.US', 'received_at': self.now.isoformat(), 'event': {'trades': [
                {'timestamp': old.isoformat(), 'price': '100', 'volume': 1,
                 'trade_session': 'Intraday', 'trade_type': ''}]}})

    def test_paths_and_dispatch_protected(self):
        with self.assertRaises(ValueError):
            consumer.FeedConsumer(replace(self.config, paper_order_dispatch_enabled=True),
                self.root/'other', str(uuid4()), self.start, self.end, now=self.now)
        with self.assertRaises(ValueError):
            consumer.FeedConsumer(replace(self.config, daily_context_path=consumer.ROOT/'local_data/daily'),
                self.root/'other', str(uuid4()), self.start, self.end, now=self.now)

    def test_cli_consumes_written_prefix_before_testing_silence(self):
        stream = self.root/'wire.ndjson'
        stream.write_text(json.dumps({'kind': 'end'})+'\n')
        output = self.root/'cli'
        output.mkdir()
        observed = []
        class Probe:
            ended = False
            last_error = None
            def __init__(self, *args, **kwargs): pass
            def write_status(self, **kwargs): pass
            def record_error(self, error, **kwargs):
                self.last_error = consumer.safe_exception(error)
            def check(self, **kwargs):
                raise ValueError('wire_false_silence_before_read')
            def consume(self, row, **kwargs):
                observed.append(row)
                self.ended = True
            def summary(self, reason):
                return {'bounded_pipeline_observed': True, 'reason': reason}
        args = ['consumer', '--stream', str(stream), '--config', 'unused', '--output-dir', str(output),
                '--run-id', self.c.run_id, '--window-start-utc', self.start.isoformat(),
                '--window-end-utc', self.end.isoformat()]
        with patch.object(sys, 'argv', args), patch.object(consumer, 'FeedConsumer', Probe), \
                patch.object(consumer.rules, 'load_config', return_value=self.config):
            self.assertEqual(consumer.main(), 0)
        self.assertEqual(len(observed), 1)
        self.assertIsNone(json.loads((output/'summary.json').read_text())['reason'])

    def test_known_runtime_reason_preserved_unknown_prefix_redacted(self):
        self.assertEqual(consumer.safe_exception(RuntimeError('market_data_heartbeat_deadline_exceeded'))['code'],
                         'market_data_heartbeat_deadline_exceeded')
        for error in (RuntimeError('secret_token=abc'), ValueError('wire_private_token=abc'),
                      ValueError('consumer_private_token=abc'), KeyError('secret_token=abc')):
            safe = consumer.safe_exception(error)
            self.assertEqual(safe['code'], 'unclassified_exception')
            self.assertNotIn('abc', json.dumps(safe))
        self.assertEqual(consumer.safe_exception(RuntimeError('sdk_stage_deadline_exceeded:daily_context'))['phase'],
                         'daily_context')
        result = consumer.safe_exception(RuntimeError('sdk_stage_deadline_exceeded:secret_token=abc'))
        self.assertNotIn('abc', json.dumps(result))

    def test_actual_heartbeat_failure_records_fixed_reason_and_live_terminal_status(self):
        self.ready()
        self.c.evidence.ready_since = consumer.time.monotonic()-60
        self.c.evidence.last_progress = consumer.time.monotonic()-6
        with self.assertRaisesRegex(RuntimeError, 'market_data_heartbeat_deadline_exceeded'):
            self.c.check(now=self.now)
        self.c.write_status(now=self.now, force=True)
        state = json.loads((self.root/'evidence/live-status.json').read_text())
        self.assertEqual(state['last_error']['code'], 'market_data_heartbeat_deadline_exceeded')
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(self.c.summary()['reason'], 'market_data_heartbeat_deadline_exceeded')

    def test_live_status_preserves_source_receipt_and_failed_attempt_identity(self):
        self.ready()
        self.now += timedelta(seconds=1)
        self.quote('QQQ.US')
        self.trades('QQQ.US')
        last = self.c.last_consumed_sequence
        source_receipt = self.now.isoformat()
        self.c.write_status(now=self.now, force=True)
        with self.assertRaises(ValueError):
            self.c.consume(self.row('heartbeat', {}, sequence=last+5), now=self.now)
        self.c.write_status(now=self.now+timedelta(seconds=10), force=True)
        state = json.loads((self.root/'evidence/live-status.json').read_text())
        self.assertEqual(state['last_consumed_sequence'], last)
        self.assertEqual(state['attempted_sequence'], last+5)
        self.assertEqual(state['last_source_receipt']['trade']['received_at'], source_receipt)
        self.assertEqual(state['quote_wire_symbol_count'], 1)
        self.assertEqual(state['trade_wire_symbol_count'], 1)
        self.assertEqual(state['strategy_evaluation_count'], 0)

    def test_status_replace_failure_is_fatal_redacted_and_first_fault_is_retained(self):
        self.c.write_status(now=self.now, force=True)
        before = (self.root/'evidence/live-status.json').read_bytes()
        with patch.object(consumer.os, 'replace', side_effect=PermissionError('private_token=abc')):
            with self.assertRaisesRegex(ValueError, 'consumer_status_write_failed'):
                self.c.write_status(now=self.now, force=True)
        self.assertEqual((self.root/'evidence/live-status.json').read_bytes(), before)
        self.assertEqual(self.c.summary()['reason'], 'consumer_status_write_failed')
        self.assertNotIn('abc', json.dumps(self.c.summary()))
        self.c.record_error(RuntimeError('reference_market_data_stalled'))
        self.assertEqual(self.c.last_error['code'], 'consumer_status_write_failed')
        self.assertFalse(list((self.root/'evidence').glob('.live-status-*.tmp')))

    def test_status_write_throttle_does_not_modify_source_fields(self):
        with patch.object(consumer.os, 'replace', wraps=consumer.os.replace) as replace_file:
            self.c.write_status(now=self.now)
            self.c.write_status(now=self.now+timedelta(milliseconds=50))
        self.assertEqual(replace_file.call_count, 1)
        state = json.loads((self.root/'evidence/live-status.json').read_text())
        self.assertEqual(state['last_source_receipt'], {})
        self.assertIsNone(state['last_processed_at'])

    def test_initialization_failure_emits_safe_evidence_without_unvalidated_write(self):
        target = self.root/'must-not-exist'
        args = ['consumer', '--stream', 'unused', '--config', 'unused', '--output-dir', str(target),
                '--run-id', self.c.run_id, '--window-start-utc', self.start.isoformat(),
                '--window-end-utc', self.end.isoformat()]
        stderr = io.StringIO()
        with patch.object(sys, 'argv', args), patch.object(consumer.rules, 'load_config',
                side_effect=RuntimeError('private_token=abc')), redirect_stderr(stderr):
            self.assertEqual(consumer.main(), 4)
        self.assertFalse(target.exists())
        self.assertNotIn('abc', stderr.getvalue())
        self.assertEqual(json.loads(stderr.getvalue())['phase'], 'initializing')


if __name__ == '__main__':
    unittest.main()
