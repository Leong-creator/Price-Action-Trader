"""Producer contract tests; fake SDK only, no credentials or broker connections."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest import mock

from scripts import m15_windows_feed_producer as p


NOW = datetime(2026, 9, 24, 14, 15, tzinfo=UTC)


def quote(snapshot=False):
    row = dict(timestamp=NOW, last_done=Decimal('100.123456789012345678'),
               open=Decimal('99.1'), high=Decimal('101'), low=Decimal('98'),
               turnover=Decimal('123456789.987654321'), volume=10,
               trade_status='Normal', trade_session='Intraday', current_volume=2,
               current_turnover=Decimal('200.2'))
    if snapshot:row.update(symbol='SPY.US', prev_close=Decimal('99'))
    return NS(**row)


def trades():
    return NS(trades=[NS(timestamp=NOW, price=Decimal('100.123456789012345678'),
                        volume=volume, trade_type='I', direction='Up', trade_session='Intraday')
                      for volume in (2, 3)])


def candles():
    rows=[]; day=NOW
    while len(rows)<61:
        if day.weekday()<5:
            rows.append(NS(timestamp=day, open=Decimal('1'), high=Decimal('2'), low=Decimal('1'),
                           close=Decimal('2'), turnover=Decimal('200'), volume=100))
        day-=timedelta(days=1)
    return list(reversed(rows))


class ProducerTests(unittest.TestCase):
    def setUp(self):
        guard=mock.patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def test_decimal_exact_and_all_same_timestamp_trades_preserved(self):
        result=p.trade_payload(trades())
        self.assertEqual([r['volume'] for r in result['trades']],[2,3])
        self.assertEqual(result['trades'][0]['price'],'100.123456789012345678')
        self.assertEqual(result['trades'][0]['trade_type'],'I')
        self.assertEqual(result['trades'][0]['trade_session'],'Intraday')
        self.assertEqual(p.quote_payload(quote())['turnover'],'123456789.987654321')

    def test_missing_or_float_price_rejected_not_zero_filled(self):
        row=quote();del row.open
        with self.assertRaises(AttributeError):p.quote_payload(row)
        row=quote();row.last_done=100.1
        with self.assertRaises(p.FeedError):p.quote_payload(row)
        with self.assertRaises(p.FeedError):p.decimal_text(Decimal('NaN'))

    def test_naive_sdk_time_roundtrip(self):
        naive=datetime.fromtimestamp(NOW.timestamp())
        self.assertEqual(p.timestamp(naive), NOW.isoformat())
        with self.assertRaises(p.FeedError):p.utc('2026-09-24T14:15:00')

    def test_sixty_daily_rows_exclude_incomplete_today(self):
        rows=p.completed_daily(candles(), '2026-09-24', [], '2026-09-23')
        self.assertEqual(len(rows),60)
        self.assertTrue(rows[-1]['timestamp'].startswith('2026-09-23'))
        self.assertNotIn('2026-09-24', ''.join(r['timestamp'] for r in rows))

    def test_daily_missing_duplicate_latest_and_config_rejected(self):
        for data, required in [(candles()[:-2], '2026-09-23'),
                               (candles()[:-1]+[candles()[-2]], '2026-09-23'),
                               (candles(), '2026-09-22')]:
            with self.subTest(required=required, size=len(data)):
                with self.assertRaises(p.FeedError):p.completed_daily(data,'2026-09-24',[],required)

    def test_sixty_one_completed_rows_select_latest_sixty(self):
        data=candles()
        for row in data:row.timestamp-=timedelta(days=7)
        # End 9/17 and select 60 from 61 before the requested market day 9/18.
        rows=p.completed_daily(data,'2026-09-18',[],'2026-09-17')
        self.assertEqual(len(rows),60)
        self.assertEqual(rows[0]['timestamp'],p.timestamp(data[1].timestamp))

    def test_callback_cut_keeps_receipt_order_and_later_callback_outside_prefix(self):
        clock=[NOW]
        inbox=p.CallbackQueue(['SPY.US'],now=lambda:clock[0])
        inbox.capture('quote','SPY.US',quote())
        prefix,cut=inbox.take_prefix()
        clock[0]+=timedelta(seconds=1)
        inbox.capture('trade','SPY.US',trades())
        self.assertEqual([kind for kind,_ in prefix],['quote'])
        self.assertEqual(prefix[0][1]['received_at'],NOW.isoformat())
        self.assertEqual(cut,NOW.isoformat())
        later,latercut=inbox.take_prefix(close=True)
        self.assertEqual(later[0][0],'trade')
        self.assertGreater(later[0][1]['received_at'],cut)
        inbox.capture('quote','SPY.US',quote())
        self.assertEqual(inbox.queue.qsize(),0)

    def test_overflow_and_unknown_symbol_fail_closed(self):
        inbox=p.CallbackQueue(['SPY.US'],maxsize=1)
        inbox.capture('quote','SPY.US',quote());inbox.capture('trade','SPY.US',trades())
        with self.assertRaisesRegex(p.FeedError,'callback_queue_overflow'):inbox.take_prefix()
        inbox=p.CallbackQueue(['SPY.US']);inbox.capture('quote','hidden-secret',quote())
        with self.assertRaisesRegex(p.FeedError,'callback_normalization_failed'):inbox.check()

    def test_stats_count_only_successful_enqueue_and_do_not_wait_for_lock(self):
        inbox=p.CallbackQueue(['SPY.US'],maxsize=2,now=lambda:NOW,monotonic=lambda:12.5)
        inbox.capture('quote','SPY.US',quote());inbox.capture('trade','SPY.US',trades())
        inbox.capture('quote','SPY.US',quote())
        stats=inbox.stats()
        self.assertEqual(stats['enqueued_counts'],{'quote':1,'trade':1})
        self.assertEqual(stats['last_callback_utc'],NOW.isoformat())
        self.assertEqual(stats['last_callback_monotonic'],12.5)
        self.assertEqual(stats['queue_depth'],2)
        self.assertEqual(stats['failure'],'callback_queue_overflow')
        with inbox.lock:
            self.assertEqual(inbox.stats(),{'available':False,'diagnostic_error':'callback_stats_lock_busy'})

    def test_normalization_failure_does_not_count_as_callback_progress(self):
        inbox=p.CallbackQueue(['SPY.US'])
        inbox.capture('quote','SPY.US',object())
        self.assertEqual(inbox.stats()['enqueued_counts'],{'quote':0,'trade':0})
        self.assertIsNone(inbox.stats()['last_callback_monotonic'])
        self.assertEqual(inbox.stats()['failure'],'callback_normalization_failed')

    def test_stall_watchdog_renews_only_on_callback_progress_and_never_after_stall(self):
        clock=[100.0];handler=mock.Mock()
        def baseline(*,file,all_threads):file.write(b'baseline\n')
        handler.dump_traceback.side_effect=baseline
        inbox=p.CallbackQueue(['SPY.US'],now=lambda:NOW,monotonic=lambda:clock[0])
        with tempfile.TemporaryDirectory() as directory:
            evidence=p.StallEvidence(Path(directory),'run',monotonic=lambda:clock[0],handler=handler)
            evidence.start(inbox.stats())
            self.assertEqual(handler.dump_traceback_later.call_args.args,(15,))
            for value in (101,103,110):clock[0]=value;evidence.tick(inbox.stats())
            self.assertEqual(handler.dump_traceback_later.call_count,1)
            clock[0]=111;inbox.capture('quote','SPY.US',quote())
            clock[0]=112;evidence.tick(inbox.stats())
            self.assertEqual(handler.dump_traceback_later.call_args.args,(14,))
            self.assertEqual(evidence.deadline,126)
            clock[0]=127;evidence.tick(inbox.stats())
            clock[0]=128;inbox.capture('trade','SPY.US',trades());evidence.tick(inbox.stats())
            self.assertEqual(handler.dump_traceback_later.call_count,2)
            handle=evidence.handle
            handler.cancel_dump_traceback_later.side_effect=lambda:self.assertFalse(handle.closed)
            evidence.close(inbox.stats())
            self.assertTrue(handle.closed)
            saved=json.loads((Path(directory)/'diagnostic.json').read_text())
            self.assertTrue(saved['stall_deadline_elapsed'])
            self.assertFalse(saved['stall_dump_observed']) # Fake timer does not prove a dump.
            self.assertEqual(saved['native_network_root_cause'],'unproven')

    def test_actual_c_watchdog_dumps_once_without_python_monitor_ticks(self):
        # Isolate process-global faulthandler. No SDK imports or sockets.
        program='''import json, sys, time
from pathlib import Path
from scripts import m15_windows_feed_producer as p
p.CALLBACK_STALL_EVIDENCE_SECONDS=.08
root=Path(sys.argv[1]); q=p.CallbackQueue(['SPY.US'])
e=p.StallEvidence(root,'offline'); e.start(q.stats())
time.sleep(.18)
e.tick(q.stats()); size=e.handle.tell()
time.sleep(.12)
e.tick(q.stats()); e.close(q.stats())
assert e.stall_dump_observed
assert (root/'stack.private').read_text().count('Timeout (') == 1
assert (root/'stack.private').stat().st_size == size
assert e.closed
'''
        with tempfile.TemporaryDirectory() as directory:
            completed=subprocess.run([sys.executable,'-c',program,directory],capture_output=True,text=True,
                                     cwd=Path(__file__).resolve().parents[2],timeout=5)
            self.assertEqual(completed.returncode,0,completed.stderr)
            self.assertEqual(completed.stdout,'')
            self.assertEqual(completed.stderr,'')
            if os.name != 'nt':
                self.assertEqual((Path(directory)/'stack.private').stat().st_mode & 0o777,0o600)

    def test_actual_c_watchdog_cancellation_leaves_only_baseline(self):
        program='''import sys, time
from pathlib import Path
from scripts import m15_windows_feed_producer as p
p.CALLBACK_STALL_EVIDENCE_SECONDS=.15
root=Path(sys.argv[1]); q=p.CallbackQueue(['SPY.US'])
e=p.StallEvidence(root,'offline'); e.start(q.stats()); e.close(q.stats())
before=(root/'stack.private').read_bytes()
time.sleep(.3)
assert (root/'stack.private').read_bytes() == before
assert b'Timeout (' not in before
assert before and e.closed
'''
        with tempfile.TemporaryDirectory() as directory:
            completed=subprocess.run([sys.executable,'-c',program,directory],capture_output=True,text=True,
                                     cwd=Path(__file__).resolve().parents[2],timeout=5)
            self.assertEqual(completed.returncode,0,completed.stderr)
            self.assertEqual(completed.stdout,'');self.assertEqual(completed.stderr,'')

    def test_initial_watchdog_deadline_uses_last_callback_not_streaming_start(self):
        clock=[10.0];handler=mock.Mock()
        inbox=p.CallbackQueue(['SPY.US'],now=lambda:NOW,monotonic=lambda:clock[0])
        inbox.capture('quote','SPY.US',quote());clock[0]=14
        with tempfile.TemporaryDirectory() as directory:
            evidence=p.StallEvidence(Path(directory),'run',monotonic=lambda:clock[0],handler=handler)
            evidence.start(inbox.stats())
            self.assertEqual(handler.dump_traceback_later.call_args.args,(11,))
            self.assertEqual(evidence.deadline,25)
            evidence.close(inbox.stats())

    def test_diagnostic_failure_uses_fixed_code_and_never_overwrites_existing_stack(self):
        with tempfile.TemporaryDirectory() as directory:
            stack=Path(directory)/'stack.private';stack.write_text('original')
            evidence=p.StallEvidence(Path(directory),'run',handler=mock.Mock())
            evidence.start(p.CallbackQueue(['SPY.US']).stats())
            self.assertEqual(evidence.error,'stall_evidence_start_failed')
            self.assertEqual(stack.read_text(),'original')
            self.assertNotIn(directory,(Path(directory)/'diagnostic.json').read_text())
            evidence.close(None)

    def test_sequence_single_ordered_stream(self):
        output=io.StringIO();writer=p.WireWriter(output,'run',now=lambda:NOW)
        writer.emit('heartbeat',{});writer.emit('end',{'reason':'window_completed'})
        rows=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([row['sequence'] for row in rows],[1,2])
        self.assertTrue(all(row['run_id']=='run' for row in rows))

    def test_defaults_load_exact_production_147_without_sdk_import(self):
        root=Path(__file__).resolve().parents[2]
        config=json.loads((root/'config/m15_longbridge_marketdata.production.json').read_text(encoding='utf-8'))
        symbols=p.load_symbols(config,root)
        self.assertEqual(len(symbols),147)
        self.assertEqual(symbols[:2],['SPY.US','QQQ.US'])

    def test_signed_spec_symbols_avoid_unmanifested_universe_file(self):
        symbols=['SPY.US','QQQ.US']+['S'+str(i)+'.US' for i in range(145)]
        config={'market_data':{'market':'US','symbol_limit':147,'use_seed_universe':False}}
        self.assertEqual(p.load_symbols(config,Path('/no-file'),{'symbols':symbols}),symbols)
        with self.assertRaises(p.FeedError):p.load_symbols(config,Path('/no-file'),{'symbols':symbols[:-1]})

    def test_monitor_files_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor=p.Monitor(Path(directory),'run')
            monitor.stage('daily_context');monitor.stage('streaming');monitor.health();monitor.finish(True)
            stages=[json.loads(line) for line in (Path(directory)/'stages.jsonl').read_text().splitlines()]
            self.assertEqual([row['phase'] for row in stages],['daily_context','streaming','completed'])
            self.assertEqual(json.loads((Path(directory)/'health.json').read_text())['status'],'observing')
            health=json.loads((Path(directory)/'health.json').read_text())
            self.assertEqual(health['heartbeat_scope'],'producer_main_loop_only')
            self.assertEqual(health['sdk_health'],'unknown')
            summary=json.loads((Path(directory)/'summary.json').read_text())
            self.assertTrue(summary['completed_window']);self.assertFalse(summary['production_acceptance'])

    def fake_run(self, *, late_daily=False, monitor=None, fail_stream=False):
        clock=[NOW]; mono=[0.0]; calls=[]; callbacks={}
        def sleep(seconds):clock[0]+=timedelta(seconds=seconds);mono[0]+=seconds
        class Context:
            def __init__(self, config):calls.append(('context',config))
            def set_on_quote(self,callback):callbacks['quote']=callback
            def set_on_trades(self,callback):callbacks['trade']=callback
            def candlesticks(self,symbol,period,count,adjust,sessions):
                calls.append(('daily',symbol,count))
                if late_daily:sleep(4)
                return candles()
            def subscribe(self,symbols,kinds):
                calls.append(('subscribe',symbols,kinds))
                callbacks['quote']('SPY.US',quote())
                callbacks['trade']('SPY.US',trades())
            def quote(self,symbols):return [quote(snapshot=True)]
        sdk=NS(OAuthBuilder=lambda _client:NS(build=lambda _callback:'oauth'),
               Config=NS(from_oauth=lambda _oauth:'default_config'), QuoteContext=Context,
               Period=NS(Day='day'),AdjustType=NS(NoAdjust='noadjust'),
               TradeSessions=NS(Intraday='intraday'),SubType=NS(Quote='quote',Trade='trade'))
        spec={'window_start_utc':NOW.isoformat(),'latest_start_utc':(NOW+timedelta(seconds=1)).isoformat(),
              'window_end_utc':(NOW+timedelta(seconds=3)).isoformat(), 'market_date':'2026-09-24',
              'required_daily_date':'2026-09-23'}
        config={'market_data':{'daily_context_deadline_seconds':600,'market_holidays':[]}}
        output=io.StringIO();writer=p.WireWriter(output,'run',now=lambda:clock[0])
        if fail_stream:
            original=writer.emit
            def emit(kind,payload):
                if kind=='watermark':raise OSError('private exception detail')
                original(kind,payload)
            writer.emit=emit
        p.produce(sdk,config,spec,['SPY.US'],'fake-client',writer,now=lambda:clock[0],
                  monotonic=lambda:mono[0],sleep=sleep,monitor=monitor)
        return [json.loads(line) for line in output.getvalue().splitlines()],calls

    def test_mock_sdk_single_subscription_complete_wire_watermark_and_end(self):
        rows,calls=self.fake_run()
        self.assertEqual([call[0] for call in calls],['context','daily','subscribe'])
        self.assertEqual(calls[1][2],61)
        self.assertEqual(calls[2][2],['quote','trade'])
        kinds=[row['kind'] for row in rows]
        self.assertLess(kinds.index('daily_context'),kinds.index('subscribed'))
        self.assertLess(kinds.index('trade'),kinds.index('watermark'))
        self.assertEqual(rows[-1]['kind'],'end')
        self.assertEqual(rows[-1]['payload']['reason'],'window_completed')
        self.assertEqual(rows[-1]['payload']['received_through'], (NOW+timedelta(seconds=3)).isoformat())
        self.assertEqual([row['sequence'] for row in rows],list(range(1,len(rows)+1)))

    def test_blocking_sdk_call_returning_after_deadline_cannot_subscribe(self):
        with self.assertRaisesRegex(p.FeedError,'initialization_window_expired'):self.fake_run(late_daily=True)

    def test_producer_cancels_watchdog_on_success_and_wire_failure(self):
        for fail in (False,True):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as directory:
                monitor=p.Monitor(Path(directory),'run')
                with mock.patch.object(p,'faulthandler') as handler:
                    if fail:
                        with self.assertRaises(OSError):self.fake_run(monitor=monitor,fail_stream=True)
                    else:self.fake_run(monitor=monitor)
                    handler.dump_traceback.assert_called_once()
                    handler.cancel_dump_traceback_later.assert_called_once()
                self.assertTrue(monitor.evidence.handle.closed)
                saved=json.loads((Path(directory)/'diagnostic.json').read_text())
                self.assertEqual(saved['callbacks']['enqueued_counts'],{'quote':1,'trade':1})
                self.assertNotIn('private exception detail',json.dumps(saved))

    def test_endpoint_override_rejected_without_disclosing_value(self):
        with mock.patch.dict('os.environ',{'LONGBRIDGE_QUOTE_WS_URL':'secret-value'}):
            with self.assertRaisesRegex(p.FeedError,'official_endpoint_override_rejected'):p.reject_overrides()


if __name__=='__main__':unittest.main()
