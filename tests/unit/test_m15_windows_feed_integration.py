"""Offline full-universe wire integration: actual producer, builder and router."""
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import copy
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import m15_windows_feed_producer as producer
from scripts import m15_windows_feed_consumer as consumer


class FullUniverseBridgeTests(unittest.TestCase):
    def test_real_wire_147_daily_context_bar_and_original_router(self):
        self.assert_full_wire(datetime(2026, 9, 24, 14, 15, 1, tzinfo=UTC),
                              datetime(2026, 9, 24, 14, 25, 5, tzinfo=UTC))

    def test_final_regular_session_boundary_without_postclose_trade_backfill(self):
        self.assert_full_wire(datetime(2026, 9, 24, 19, 50, 1, tzinfo=UTC),
                              datetime(2026, 9, 24, 20, 0, 5, tzinfo=UTC))

    def test_normal_full_day_147_times_78_original_pipeline_and_assessor(self):
        self.assert_full_wire(datetime(2026, 9, 24, 13, 25, 1, tzinfo=UTC),
            datetime(2026, 9, 24, 20, 0, 5, tzinfo=UTC), accelerated=True, acceptance=True)

    def assert_full_wire(self, start, end, *, accelerated=False, acceptance=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            config = replace(consumer.rules.load_config(), output_dir=root/'unused',
                market_events_path=root/'market', runtime_status_path=root/'state',
                readonly_gate_path=root/'gate', daily_context_path=root/'daily',
                paper_order_dispatch_enabled=False, paper_validation_approved=False,
                paper_validation_market_date='', formal_test_transition_enabled=False)
            symbols = list(consumer.rules.configured_symbols(config))
            self.assertEqual(len(symbols), 147)
            clock, mono, callbacks, calls = [start], [1000.0], {}, []
            stack.enter_context(patch.object(socket.socket, 'connect', side_effect=AssertionError('no network')))
            stack.enter_context(patch.object(consumer.time, 'monotonic', side_effect=lambda: mono[0]))
            feed = consumer.FeedConsumer(config, root/'evidence', str(uuid4()), start, end, now=start)
            class Sink:
                def write(self, value):
                    row = json.loads(value)
                    feed.consume(row, now=clock[0])
                def flush(self):
                    pass
            def quote(symbol):
                return NS(symbol=symbol, timestamp=clock[0], last_done=Decimal('100.123456789'),
                    open=Decimal('100'), high=Decimal('102'), low=Decimal('99'), prev_close=Decimal('100'),
                    volume=100, turnover=Decimal('10012.3456789'),
                    trade_status='Normal', trade_session='Intraday',
                    current_volume=0, current_turnover=Decimal('0'))
            def trade():
                return NS(trades=[NS(timestamp=clock[0], price=Decimal(price), volume=volume,
                    trade_type='', direction='Neutral', trade_session='Intraday')
                    for price, volume in [('100.123456789', 1), ('101.123456789', 3)]])
            daily = []
            day = datetime(2026, 9, 23, 13, 30, tzinfo=UTC)
            while len(daily) < 61:
                if day.weekday() < 5 and day.date().isoformat() not in config.market_holidays:
                    daily.append(NS(timestamp=day, open=Decimal('100'), high=Decimal('102'),
                        low=Decimal('99'), close=Decimal('100.123456789'), volume=100,
                        turnover=Decimal('10012.3456789')))
                day -= timedelta(days=1)
            class Context:
                def __init__(self, cfg):
                    calls.append(('context', cfg))
                def set_on_quote(self, callback):
                    callbacks['quote'] = callback
                def set_on_trades(self, callback):
                    callbacks['trade'] = callback
                def candlesticks(self, symbol, period, count, adjust, sessions):
                    calls.append(('daily', symbol, count))
                    return list(reversed(daily))
                def subscribe(self, targets, kinds):
                    calls.append(('subscribe', list(targets), list(kinds)))
                def quote(self, targets):
                    return [quote(symbol) for symbol in targets]
            sdk = NS(OAuthBuilder=lambda _: NS(build=lambda _: 'fake_oauth'),
                Config=NS(from_oauth=lambda _: 'official_defaults'), QuoteContext=Context,
                Period=NS(Day='Day'), AdjustType=NS(NoAdjust='NoAdjust'),
                TradeSessions=NS(Intraday='Intraday'), SubType=NS(Quote='Quote', Trade='Trade'))
            first_full_open = start.replace(second=0, microsecond=0)+timedelta(minutes=5)
            sent_bar_trades = set()
            last_second = [None]
            def advance(seconds):
                if accelerated:
                    next_settle = consumer.rules.floor_bar_open(clock[0], 5) + timedelta(seconds=2)
                    if next_settle <= clock[0]:
                        next_settle += timedelta(minutes=5)
                    seconds = min(10, (next_settle-clock[0]).total_seconds(), (end-clock[0]).total_seconds())
                clock[0] += timedelta(seconds=seconds)
                mono[0] += seconds
                second = clock[0].replace(microsecond=0)
                if second != last_second[0] and clock[0] < end:
                    last_second[0] = second
                    for symbol in ('SPY.US', 'QQQ.US'):
                        callbacks['quote'](symbol, quote(symbol))
                        if clock[0] < end.replace(second=0, microsecond=0):
                            callbacks['trade'](symbol, trade())
                bucket = clock[0].replace(minute=clock[0].minute//5*5, second=0, microsecond=0)
                if bucket not in sent_bar_trades and first_full_open <= bucket < end.replace(second=0, microsecond=0):
                    sent_bar_trades.add(bucket)
                    for symbol in symbols:
                        callbacks['quote'](symbol, quote(symbol))
                        callbacks['trade'](symbol, trade())
            spec = {'run_id': feed.run_id, 'market_date':'2026-09-24',
                'required_daily_date':'2026-09-23', 'window_start_utc':start.isoformat(),
                'latest_start_utc':(start+timedelta(seconds=60)).isoformat(),
                'window_end_utc':end.isoformat()}
            producer.produce(sdk, {'market_data':{'daily_context_deadline_seconds':600,
                'market_holidays':list(config.market_holidays)}}, spec, symbols, 'fake_client',
                producer.WireWriter(Sink(), feed.run_id, now=lambda:clock[0]),
                now=lambda:clock[0], monotonic=lambda:mono[0], sleep=advance)
            result = feed.summary()
            self.assertEqual(sum(call[0]=='context' for call in calls), 1)
            self.assertEqual(sum(call[0]=='subscribe' for call in calls), 1)
            self.assertEqual(sum(call[0]=='daily' for call in calls), 147)
            self.assertEqual(result['daily_context_row_count'], 8820)
            expected = int((end.replace(second=0, microsecond=0)-first_full_open).total_seconds()//300)
            self.assertEqual(result['complete_boundary_count'], expected)
            self.assertEqual(result['bar_count'], 147*expected)
            self.assertEqual(result['strategy_evaluation_count'], expected)
            self.assertTrue(result['bounded_pipeline_observed'])
            rows = feed.evidence.strategy.context.rows()
            nonreference = [r for r in rows if r['symbol'] not in ('SPY', 'QQQ')]
            self.assertEqual(len(nonreference),145*expected)
            self.assertTrue(all(Decimal(str(r['volume'])) == 4 for r in nonreference))
            self.assertTrue(all(Decimal(str(r['high'])) == Decimal('101.123456789') for r in nonreference))
            self.assertFalse(result['full_session_acceptance'])
            self.assertFalse(result['order_access'])
            persisted = [json.loads(line) for line in (root/'evidence/bar-evidence.jsonl').read_text().splitlines()]
            self.assertEqual(len(persisted), 147*expected)
            self.assertEqual(len({(row['bar']['symbol'], row['bar']['bar_close_at']) for row in persisted}), 147*expected)
            self.assertTrue(all(row['trade_callback_receipts']['max_callback_to_dequeue_ms'] == 0 for row in persisted))
            self.assertEqual(result['latency_evidence']['bar_latest_callback_to_judgment']['count'], 147*expected)
            if acceptance:
                from scripts import m15_feed_session_acceptance as assessor
                (root/'evidence/summary.json').write_text(json.dumps(result))
                spec.update(market_open_utc='2026-09-24T13:30:00+00:00', market_close_utc='2026-09-24T20:00:00+00:00', symbols=symbols)
                once = {'run_nonce': feed.run_id, 'status': 'completed',
                    **dict.fromkeys(('bounded_pipeline_passed', 'reception_window_passed',
                    'diagnostic_window_passed', 'exit_verified', 'credentials_cleaned',
                    'protected_states_unchanged', 'original_credentials_unchanged'), True)}
                guardian = {'run_nonce': feed.run_id, 'status': 'completed', 'child_exitcode': 0, 'consumer_exitcode': 0,
                    'job_active_processes': 0, **dict.fromkeys(('child_exited', 'consumer_exited', 'exit_verified', 'consumer_passed'), True)}
                complete = {'run_once': once, 'guardian': guardian, 'consumer': result, 'exit_fences_cleared': True,
                    'producer': {'run_id': feed.run_id, 'terminal_sequence': result['last_sequence'],
                        'completed_window': True, 'reason': None, 'status': 'window_observed',
                        'window_start_utc': spec['window_start_utc'], 'window_end_utc': spec['window_end_utc']}}
                # This fixture exercises the feed/exit assessor, not real UTC quality.
                with patch.object(assessor, 'verify_clock_evidence', return_value={'passed': True, 'scope': 'test_only'}):
                    passed = assessor.evaluate_session(root/'evidence', spec, complete, {}, session_spec_sha256='test')
                    self.assertTrue(passed['normal_full_session_observation_passed'], passed['failures'])
                    self.assertFalse(passed['trading_enabled'])
                    for field, value in (('status', 'failed'), ('bounded_pipeline_passed', False),
                            ('reception_window_passed', False), ('diagnostic_window_passed', False),
                            ('archive_error', 'OSError'), ('clock_finalization_error', 'RuntimeError')):
                        failed_completion = copy.deepcopy(complete)
                        failed_completion['run_once'][field] = value
                        rejected = assessor.evaluate_session(root/'evidence', spec, failed_completion, {}, session_spec_sha256='test')
                        self.assertIn('outer_completion_failed', rejected['failures'], field)
                        self.assertFalse(rejected['normal_full_session_observation_passed'])
                    failed_guardian = copy.deepcopy(complete)
                    failed_guardian['guardian']['status'] = 'failed'
                    rejected = assessor.evaluate_session(root/'evidence', spec, failed_guardian, {}, session_spec_sha256='test')
                    self.assertIn('guardian_completion_failed', rejected['failures'])
                    for label, mutate in (
                        ('duplicate', lambda rows: rows+[rows[0]]),
                        ('missing', lambda rows: rows[1:]),
                        ('late', lambda rows: [dict(rows[0], formed_at='2026-09-24T20:01:00+00:00')]+rows[1:]),
                        ('carry_falsely_tradable', lambda rows: [dict(rows[0], classification='blocked_carry')]+rows[1:])):
                        altered = mutate(copy.deepcopy(persisted))
                        (root/'evidence/bar-evidence.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in altered))
                        rejected = assessor.evaluate_session(root/'evidence', spec, complete, {}, session_spec_sha256='test')
                        self.assertFalse(rejected['normal_full_session_observation_passed'], label)
                    (root/'evidence/bar-evidence.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in persisted))
                    changed = copy.deepcopy(complete); changed['producer']['terminal_sequence'] -= 1
                    rejected = assessor.evaluate_session(root/'evidence', spec, changed, {}, session_spec_sha256='test')
                    self.assertIn('terminal_sequence_or_tail_incomplete', rejected['failures'])
                with patch.object(assessor, 'verify_clock_evidence', return_value={'passed': False}):
                    rejected = assessor.evaluate_session(root/'evidence', spec, complete, {}, session_spec_sha256='test')
                    self.assertIn('clock_evidence_not_passed', rejected['failures'])


if __name__ == '__main__':
    unittest.main()
