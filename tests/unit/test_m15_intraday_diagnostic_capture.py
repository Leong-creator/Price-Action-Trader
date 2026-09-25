"""Bounded capture after one specific quality failure; real builder, no SDK."""
from datetime import timedelta
import copy
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import m15_windows_feed_consumer as consumer
from tests.unit import test_m15_windows_feed_consumer as strict_tests


class IntradayCaptureTests(unittest.TestCase):
    row = strict_tests.WindowsFeedConsumerTests.row
    send = strict_tests.WindowsFeedConsumerTests.send
    daily = strict_tests.WindowsFeedConsumerTests.daily
    ready = strict_tests.WindowsFeedConsumerTests.ready
    quote = strict_tests.WindowsFeedConsumerTests.quote
    trades = strict_tests.WindowsFeedConsumerTests.trades

    def setUp(self):
        strict_tests.WindowsFeedConsumerTests.setUp(self)
        self.c = consumer.FeedConsumer(self.config, self.root/'diagnostic', self.c.run_id,
            self.start, self.end, now=self.now, diagnostic_capture_after_quality_fault=True)
        self.stack.enter_context(patch.object(consumer.time, 'monotonic',
            side_effect=lambda: self.c.started_mono+(self.now-self.start).total_seconds()))
        self.ready()

    def refs(self):
        for symbol in self.symbols:
            self.quote(symbol)
            self.trades(symbol)

    def old_trade_payload(self, *, source=None, received=None, trade_type='I'):
        return {'symbol': 'SPY.US', 'received_at': (received or self.now).isoformat(),
            'event': {'trades': [{'timestamp': (source or self.now.replace(second=0,microsecond=0)).isoformat(),
                'price': '100', 'volume': 1, 'trade_type': trade_type, 'trade_session': 'Intraday'}]}}

    def fault(self):
        self.now = self.start.replace(minute=35, second=2, microsecond=49167)
        self.refs()
        payload = self.old_trade_payload()
        self.send('trade', payload)
        self.assertEqual(self.c.first_quality_fault['code'], 'trade_source_delivery_age_exceeded')
        return payload

    def test_exact_2049ms_fixture_freezes_strategy_and_completes_raw_capture(self):
        self.fault()
        first = copy.deepcopy(self.c.first_quality_fault)
        self.assertAlmostEqual(first['source_timestamp_gap_ms'], 2049.167)
        self.assertIs(first['local_clock_offset_applied'], False)
        self.assertEqual(first['source_event_at'], '2026-09-24T13:35:00+00:00')
        self.assertEqual(first['timestamp_precision_seconds'], 1)
        before = copy.deepcopy(self.c.builder._bars)
        self.stack.enter_context(patch.object(self.c.builder, 'on_trade', side_effect=AssertionError('frozen builder')))
        self.stack.enter_context(patch.object(self.c.builder, 'seed_quote', side_effect=AssertionError('frozen quotes')))
        self.stack.enter_context(patch.object(self.c.builder, 'complete_boundary', side_effect=AssertionError('no bars after fault')))
        self.stack.enter_context(patch.object(self.c.evidence.strategy, 'evaluate', side_effect=AssertionError('no strategy after fault')))
        while self.now < self.end-timedelta(seconds=10):
            self.now += timedelta(seconds=10)
            self.refs()
            self.send('watermark', {'received_through': self.now.isoformat()})
            self.c.check(now=self.now)
        self.now = self.end
        self.send('watermark', {'received_through': self.now.isoformat()})
        self.send('end', {'reason': 'window_completed', 'received_through': self.now.isoformat()})
        result = self.c.summary()
        self.assertTrue(result['diagnostic_capture_complete'])
        self.assertEqual(result['status'], 'diagnostic_capture_complete')
        for key in ('bounded_pipeline_observed', 'quality_passed', 'full_session_acceptance', 'account_access', 'order_access'):
            self.assertIs(result[key], False, key)
        self.assertIsNone(self.c.last_error)
        self.assertEqual(self.c.first_quality_fault, first)
        self.assertEqual(self.c.builder._bars, before)
        self.assertEqual(result['producer_end_sequence'], result['last_consumed_sequence'])
        self.assertGreater(result['diagnostic_raw_counts_after_fault']['trade_executions'], 10)
        stored = json.loads((self.c.output/'quality-faults.jsonl').read_text())
        self.assertEqual(stored, first)

    def test_pre_fault_real_strategy_judgment_does_not_override_quality_failure(self):
        self.now = self.start.replace(minute=35, second=1)
        self.refs()
        self.now = self.start.replace(minute=40, second=2)
        self.refs()
        self.send('watermark', {'received_through': self.now.isoformat()})
        self.assertEqual(self.c.evidence.strategy.evaluations, 1)
        self.now += timedelta(microseconds=49167)
        self.send('trade', self.old_trade_payload())
        self.assertEqual(self.c.first_quality_fault['strategy_evaluations_frozen_at'], 1)
        self.now = self.end
        self.send('watermark', {'received_through': self.now.isoformat()})
        self.send('end', {'reason': 'window_completed', 'received_through': self.now.isoformat()})
        result = self.c.summary()
        self.assertTrue(result['all_expected_boundaries_observed'])
        self.assertEqual(result['strategy_evaluation_count'], 1)
        self.assertTrue(result['diagnostic_capture_complete'])
        self.assertFalse(result['bounded_pipeline_observed'])

    def test_partially_appended_fault_batch_is_frozen_and_never_replayed(self):
        self.now = self.start.replace(minute=35, second=2, microsecond=49167)
        self.refs()
        payload = self.old_trade_payload()
        fresh = dict(payload['event']['trades'][0], timestamp=self.now.isoformat(), volume=7, trade_type='')
        payload['event']['trades'].insert(0, fresh)
        self.send('trade', payload)
        key = ('SPY.US', consumer.rules.floor_bar_open(self.now, 5))
        self.assertEqual(self.c.builder._bars[key]['volume'], 11)
        frozen = copy.deepcopy(self.c.builder._bars)
        self.now += timedelta(seconds=1)
        self.send('trade', self.old_trade_payload())
        self.assertEqual(self.c.builder._bars, frozen)
        self.assertEqual(self.c.evidence.strategy.evaluations, 0)

    def test_zero_price_before_late_trade_is_fatal_not_wrong_quality_candidate(self):
        self.now = self.start.replace(minute=35, second=2, microsecond=49167)
        payload = self.old_trade_payload()
        payload['event']['trades'].insert(0, dict(payload['event']['trades'][0], price='0'))
        with self.assertRaisesRegex(ValueError, '^wire_decimal_range$'):
            self.send('trade', payload)
        self.assertIsNone(self.c.first_quality_fault)

    def test_cli_flag_and_diagnostic_exit_code_remain_separate_from_success(self):
        stream = self.root/'wire.ndjson'
        stream.write_text(json.dumps({'kind': 'end'})+'\n')
        output = self.root/'cli'
        output.mkdir()
        observed = []
        class Probe:
            ended = False
            last_error = None
            def __init__(self, *args, **kwargs):
                observed.append(kwargs['diagnostic_capture_after_quality_fault'])
            def write_status(self, **kwargs): pass
            def record_error(self, error, **kwargs): self.last_error = consumer.safe_exception(error)
            def consume(self, row, **kwargs): self.ended = True
            def summary(self, reason):
                return {'bounded_pipeline_observed': False, 'diagnostic_capture_complete': True,
                    'quality_passed': False, 'reason': reason}
        args = ['consumer', '--stream', str(stream), '--config', 'unused', '--output-dir', str(output),
            '--run-id', self.c.run_id, '--window-start-utc', self.start.isoformat(),
            '--window-end-utc', self.end.isoformat(), '--diagnostic-capture-after-quality-fault']
        with patch.object(sys, 'argv', args), patch.object(consumer, 'FeedConsumer', Probe), \
                patch.object(consumer.rules, 'load_config', return_value=self.config):
            self.assertEqual(consumer.main(), 5)
        self.assertEqual(observed, [True])
        self.assertIs(json.loads((output/'summary.json').read_text())['bounded_pipeline_observed'], False)

    def test_default_strict_mode_still_stops_at_identical_trade(self):
        self.c.diagnostic_capture_after_quality_fault = False
        self.now = self.start.replace(minute=35, second=2, microsecond=49167)
        with self.assertRaisesRegex(ValueError, '^trade_source_delivery_age_exceeded$'):
            self.send('trade', self.old_trade_payload())
        self.assertIsNone(self.c.first_quality_fault)
        self.assertEqual(self.c.last_error['code'], 'trade_source_delivery_age_exceeded')

    def test_heartbeats_and_repeated_source_timestamps_cannot_renew_four_streams(self):
        self.fault()
        original = self.now
        while self.now < original+timedelta(seconds=31):
            self.now += timedelta(seconds=1)
            for symbol in self.symbols:
                self.send('quote', {'symbol': symbol, 'received_at': self.now.isoformat(),
                    'event': {'timestamp': original.isoformat(), 'last_done': '100',
                        'volume': 104, 'trade_session': 'Intraday'}})
                value = self.old_trade_payload(source=original)
                value['symbol'] = symbol
                self.send('trade', value)
            self.send('heartbeat', {'phase': 'streaming'})
        with self.assertRaisesRegex(ValueError, '^diagnostic_reference_market_data_stalled$'):
            self.c.check(now=self.now)
        self.assertFalse(self.c.summary()['diagnostic_capture_complete'])

    def test_one_missing_reference_trade_stops_even_when_other_streams_and_heartbeats_continue(self):
        self.fault()
        for _ in range(4):
            self.now += timedelta(seconds=8)
            self.quote('SPY.US'); self.quote('QQQ.US'); self.trades('SPY.US')
            self.send('heartbeat', {'phase': 'streaming'})
        with self.assertRaisesRegex(ValueError, '^diagnostic_reference_market_data_stalled$'):
            self.c.check(now=self.now)

    def assert_fatal_drain(self, code, action):
        self.fault()
        first = copy.deepcopy(self.c.first_quality_fault)
        with self.assertRaisesRegex(ValueError, '^'+code+'$'):
            action()
        self.assertFalse(self.c.summary()['diagnostic_capture_complete'])
        self.assertTrue(self.c.summary()['strategy_frozen'])
        self.assertEqual(self.c.first_quality_fault, first)

    def test_drain_sequence_gap_stops(self):
        self.assert_fatal_drain('wire_sequence_discontinuity', lambda:
            self.c.consume(self.row('heartbeat', {}, sequence=self.c.sequence+2), now=self.now))

    def test_drain_future_trade_stops(self):
        self.assert_fatal_drain('trade_timestamp_in_future', lambda:
            self.send('trade', self.old_trade_payload(source=self.now+timedelta(seconds=3))))

    def test_drain_processing_backlog_stops(self):
        self.assert_fatal_drain('wire_processing_backlog', lambda:
            self.send('trade', self.old_trade_payload(received=self.now-timedelta(seconds=3))))

    def test_drain_future_watermark_stops(self):
        self.assert_fatal_drain('wire_watermark_outside_prefix', lambda:
            self.send('watermark', {'received_through': (self.now+timedelta(seconds=1)).isoformat()}))

    def test_drain_clock_jump_stops(self):
        def jumped():
            with patch.object(consumer.time, 'monotonic', return_value=self.c.started_mono):
                self.c.check(now=self.now)
        self.assert_fatal_drain('consumer_clock_discontinuity', jumped)

    def test_drain_wire_silence_stops(self):
        def silent():
            self.now += timedelta(seconds=6)
            self.c.check(now=self.now)
        self.assert_fatal_drain('diagnostic_wire_progress_stalled', silent)

    def test_new_source_after_31_second_gap_does_not_erase_missing_continuity(self):
        def resumed():
            self.now += timedelta(seconds=31)
            self.quote('SPY.US')
        self.assert_fatal_drain('diagnostic_reference_market_data_stalled', resumed)

    def test_end_without_complete_watermark_cannot_pass(self):
        self.fault()
        while self.now < self.end-timedelta(seconds=10):
            self.now += timedelta(seconds=10)
            self.refs()
        self.now = self.end
        with self.assertRaisesRegex(ValueError, '^wire_premature_or_incomplete_end$'):
            self.send('end', {'reason': 'window_completed', 'received_through': self.end.isoformat()})
        self.assertFalse(self.c.summary()['diagnostic_capture_complete'])

    def test_other_trade_failure_is_not_captured_and_first_quality_fault_survives_later_fault(self):
        self.now = self.start.replace(minute=35, second=2)
        with self.assertRaisesRegex(ValueError, '^trade_timestamp_in_future$'):
            self.send('trade', self.old_trade_payload(source=self.now+timedelta(seconds=3)))
        self.assertIsNone(self.c.first_quality_fault)

    def test_quality_evidence_write_failure_stops_capture(self):
        self.now = self.start.replace(minute=35, second=2, microsecond=49167)
        with patch.object(Path, 'open', side_effect=OSError('private path')):
            with self.assertRaisesRegex(ValueError, '^consumer_evidence_write_failed$'):
                self.send('trade', self.old_trade_payload())
        self.assertIsNotNone(self.c.first_quality_fault)
        self.assertEqual(self.c.last_error['code'], 'consumer_evidence_write_failed')
        self.assertFalse(self.c.summary()['diagnostic_capture_complete'])


if __name__ == '__main__':
    unittest.main()
