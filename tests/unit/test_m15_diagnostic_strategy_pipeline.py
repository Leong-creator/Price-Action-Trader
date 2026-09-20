from __future__ import annotations

import asyncio
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts import run_m15_longbridge_quote_diagnostic as diagnostic
from scripts import run_m15_longbridge_sdk_runtime as runtime
from scripts import m15_longbridge_sdk_quote_transport_lib as transport
from scripts import m15_longbridge_sdk_runtime_lib as sdk_rules
from scripts.m15_marketdata_diagnostics_lib import append_diagnostic_snapshot, acquire_quote_owner_lock


class DiagnosticStrategyPipelineTests(unittest.TestCase):
    def test_json_audit_copy_does_not_change_live_datetime_decimal(self):
        timestamp = datetime(2026, 9, 21, 13, 50, tzinfo=UTC)
        message = {'kind': 'quote_state_batch', 'payload': {'timestamp': timestamp, 'last_done': Decimal('500.12')}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'audit.jsonl'
            append_diagnostic_snapshot(path, message)
            saved = json.loads(path.read_text())
        self.assertEqual(saved['payload']['timestamp'], timestamp.isoformat())
        self.assertEqual(saved['payload']['last_done'], '500.12')
        self.assertIs(message['payload']['timestamp'], timestamp)
        self.assertIsInstance(message['payload']['last_done'], Decimal)

    def test_inherited_lock_is_same_owner_and_caller_survives_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'lock'
            with acquire_quote_owner_lock(path) as original:
                with acquire_quote_owner_lock(path, inherited_fd=original.fileno()):
                    pass
                with self.assertRaisesRegex(RuntimeError, 'another_quote_owner'):
                    acquire_quote_owner_lock(path)
            with acquire_quote_owner_lock(path):
                pass

    def test_window_rejects_early_late_naive_and_changed_window(self):
        args = ('2026-09-21T13:50:00Z', '2026-09-21T13:51:00Z', '2026-09-21T14:20:00Z')
        for now in (datetime(2026,9,21,13,49,tzinfo=UTC), datetime(2026,9,21,13,51,1,tzinfo=UTC)):
            with self.assertRaisesRegex(ValueError, 'outside_authorized'):
                diagnostic.validate_market_window(*args, now=now)
        end = diagnostic.validate_market_window(*args, now=datetime(2026,9,21,13,50,tzinfo=UTC))
        self.assertEqual(end, datetime(2026,9,21,14,20,tzinfo=UTC))
        with self.assertRaisesRegex(ValueError, 'timezone'):
            diagnostic.validate_market_window(args[0][:-1], *args[1:])

    def test_all_account_contexts_are_rejected_and_restored(self):
        constructors = {name: lambda: object() for name in ('TradeContext','AsyncTradeContext','PortfolioContext','AsyncPortfolioContext')}
        sdk = SimpleNamespace(**constructors)
        with diagnostic.quote_only_sdk_guard(sdk):
            for name in constructors:
                with self.assertRaisesRegex(RuntimeError, 'account_or_order_access_forbidden'):
                    getattr(sdk,name)()
        for name, original in constructors.items():
            self.assertIs(getattr(sdk,name), original)

    def test_pipeline_paths_require_isolation_and_dispatch_off(self):
        config = runtime.load_config()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(ValueError, 'external_paths'):
                diagnostic.validate_pipeline_paths(config, output)
            config = replace(config, output_dir=output/'unused', market_events_path=output/'market.jsonl',
                runtime_status_path=output/'state.json', readonly_gate_path=output/'gate.json', daily_context_path=output/'daily.jsonl')
            with self.assertRaisesRegex(ValueError, 'disable_dispatch'):
                diagnostic.validate_pipeline_paths(config, output)
            diagnostic.validate_pipeline_paths(replace(config, paper_order_dispatch_enabled=False), output)

    def test_no_boundaries_cannot_claim_pipeline_observed(self):
        config = runtime.load_config()
        messages = queue.Queue(); messages.cancel_join_thread=lambda:None; messages.close=lambda:None
        stop = threading.Event()
        child = SimpleNamespace(pid=123, exitcode=0, start=lambda:None, is_alive=lambda:not stop.is_set(),
            join=lambda timeout:None, terminate=stop.set, kill=stop.set)
        context = SimpleNamespace(Queue=lambda **kwargs:messages, Event=lambda:stop, Process=lambda **kwargs:child)
        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostic.mp,'get_context',return_value=context), \
                patch.object(socket,'create_connection',side_effect=AssertionError('network forbidden')):
            result=asyncio.run(diagnostic.collect_pipeline(config,'unused',0.01,Path(directory),asyncio.Event()))
        self.assertEqual(result['status'],'incomplete')
        self.assertFalse(result['bounded_pipeline_observed'])
        self.assertEqual(result['strategy_evaluation_count'],0)
        self.assertEqual(result['strategy_status'],'not_evaluated_no_accepted_boundary')

    def test_quote_only_carry_bars_never_claim_trade_pipeline_observed(self):
        result = {"status":"duration_completed", "worker_process_exited":True, "worker_exitcode":0,
            "worker_forced_cleanup":False, "strategy_input_coverage_observed":True, "strategy_evaluation_count":1}
        evidence=SimpleNamespace(latest_diagnostics={"stages":{}}, bar_count=147,
            session=SimpleNamespace(realtime_tradable_bar_count=0,no_trade_carry_forward_count=147))
        flags=diagnostic.pipeline_observation_flags(result,evidence)
        self.assertFalse(flags["bounded_pipeline_observed"])
        self.assertEqual(flags["no_trade_carry_forward_bar_count"],147)
        self.assertFalse(flags["full_session_acceptance"])
        evidence.latest_diagnostics={"stages":{
            "raw":{"stage":"raw_callback","kind":"trade","count":5},
            "dequeued":{"stage":"dequeued","kind":"trade","count":5}}}
        evidence.session.realtime_tradable_bar_count=1
        self.assertTrue(diagnostic.pipeline_observation_flags(result,evidence)["bounded_pipeline_observed"])
        result["status"]="failed"
        self.assertFalse(diagnostic.pipeline_observation_flags(result,evidence)["bounded_pipeline_observed"])

    def test_observation_clock_rejects_suspend_and_backward_jump(self):
        wall = [datetime(2026, 9, 21, 13, 50, tzinfo=UTC)]
        mono = [100.0]
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None): return wall[0]
        with patch.object(diagnostic, "datetime", Clock), patch.object(diagnostic, "time", SimpleNamespace(monotonic=lambda:mono[0])):
            clock = diagnostic.PipelineObservationClock(1800, datetime(2026,9,21,14,20,tzinfo=UTC))
            wall[0] += timedelta(minutes=40)
            mono[0] += 1
            with self.assertRaisesRegex(RuntimeError, "clock_discontinuity"):
                clock.can_observe()
            wall[0] = datetime(2026,9,21,13,49,tzinfo=UTC)
            with self.assertRaisesRegex(RuntimeError, "clock_discontinuity"):
                clock.can_observe()

    def test_utc_boundary_is_strict_even_if_monotonic_is_slightly_behind(self):
        wall = [datetime(2026,9,21,13,50,tzinfo=UTC)]; mono=[100.0]
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return wall[0]
        with patch.object(diagnostic,"datetime",Clock), patch.object(diagnostic,"time",SimpleNamespace(monotonic=lambda:mono[0])):
            clock=diagnostic.PipelineObservationClock(1800,datetime(2026,9,21,14,20,tzinfo=UTC))
            wall[0]+=timedelta(minutes=30); mono[0]+=1799.9
            self.assertFalse(clock.can_observe())

    def _collector_shutdown_fixture(self, *, shutdown_error=False, primary_error=False, suspend_on_dequeue=False, suspend_on_shutdown=False):
        # Positive earlier evidence must not mask a shutdown failure or resumed late input.
        stages={"raw":{"stage":"raw_callback","kind":"trade","count":9},
                "dequeued":{"stage":"dequeued","kind":"trade","count":9}}
        evidence=SimpleNamespace(latest_diagnostics={"stages":stages}, message_counts={}, bar_count=147,
            worker_safe_error={}, session=SimpleNamespace(complete_boundary_count=1,realtime_tradable_bar_count=147,no_trade_carry_forward_count=0),
            strategy=SimpleNamespace(summary=lambda:{"strategy_input_coverage_observed":True,"strategy_evaluation_count":1}))
        consumed=[]
        def consume(message, now):
            consumed.append(message)
            if primary_error: raise RuntimeError("primary_failure_preserved")
        evidence.consume=consume; evidence.check_deadlines=lambda now:None
        wall=[datetime(2026,9,21,13,50,tzinfo=UTC)]; mono=[100.0]
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return wall[0]
        class Messages(queue.Queue):
            def get_nowait(inner):
                message=super(Messages,inner).get_nowait()
                if suspend_on_dequeue and not child_stop.is_set(): wall[0]+=timedelta(minutes=40)
                return message
        messages=Messages(); messages.cancel_join_thread=lambda:None; messages.close=lambda:None
        if primary_error or suspend_on_dequeue: messages.put({"kind":"bars","rows":[]})
        class Stop(threading.Event):
            def set(inner):
                super(Stop,inner).set()
                if suspend_on_shutdown: wall[0]+=timedelta(minutes=40)
                if shutdown_error:
                    messages.put({"kind":"error","reason":"official_sdk_quote_worker_failed:RuntimeError:PRIVATE-SHOULD-NOT-LEAK",
                                  "safe_error":{"error_category":"request_timeout","error_type":"RuntimeError"}})
        child_stop=Stop()
        child=SimpleNamespace(pid=123,exitcode=0,start=lambda:None,is_alive=lambda:not child_stop.is_set(),
            join=lambda timeout:None,terminate=child_stop.set,kill=child_stop.set)
        context=SimpleNamespace(Queue=lambda **kwargs:messages,Event=lambda:child_stop,Process=lambda **kwargs:child)
        async def advance(_seconds):
            wall[0]+=timedelta(seconds=1); mono[0]+=1
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(diagnostic,"PipelineProbeEvidence",return_value=evidence), \
                patch.object(diagnostic.mp,"get_context",return_value=context), \
                patch.object(diagnostic,"datetime",Clock), \
                patch.object(diagnostic,"time",SimpleNamespace(monotonic=lambda:mono[0])), \
                patch.object(diagnostic.asyncio,"sleep",side_effect=advance):
            output=Path(directory)
            result=asyncio.run(diagnostic._collect_pipeline(SimpleNamespace(),"unused",0.5,output,asyncio.Event()))
            audit=(output/"worker_messages.jsonl").read_text() if (output/"worker_messages.jsonl").exists() else ""
            shutdown=(output/"shutdown_messages.jsonl").read_text() if (output/"shutdown_messages.jsonl").exists() else ""
        return result,consumed,audit,shutdown

    def test_exited_zero_worker_with_shutdown_error_cannot_pass_previous_good_evidence(self):
        result,_,_,shutdown=self._collector_shutdown_fixture(shutdown_error=True)
        self.assertEqual(result["worker_exitcode"],0)
        self.assertEqual(result["status"],"failed")
        self.assertEqual(result["reason"],"quote_worker_shutdown_reported_failure")
        self.assertFalse(result["bounded_pipeline_observed"])
        self.assertEqual(result["shutdown_errors"][0]["safe_error"]["error_category"],"request_timeout")
        self.assertNotIn("PRIVATE-SHOULD-NOT-LEAK",shutdown)

    def test_primary_failure_survives_additional_shutdown_error(self):
        result,_,_,_=self._collector_shutdown_fixture(primary_error=True,shutdown_error=True)
        self.assertEqual(result["reason"],"primary_failure_preserved")
        self.assertEqual(result["status"],"failed")
        self.assertIn("shutdown_errors",result)

    def test_suspend_after_dequeue_does_not_audit_or_consume_late_input(self):
        result,consumed,audit,shutdown=self._collector_shutdown_fixture(suspend_on_dequeue=True)
        self.assertEqual(result["reason"],"diagnostic_clock_discontinuity")
        self.assertFalse(result["bounded_pipeline_observed"])
        self.assertEqual(consumed,[])
        self.assertEqual(audit,"")
        self.assertIn('"kind": "bars"',shutdown)  # Evidence only, never a strategy invocation.

    def test_suspend_during_cleanup_cannot_turn_into_successful_observation(self):
        result,_,_,_=self._collector_shutdown_fixture(suspend_on_shutdown=True)
        self.assertEqual(result["status"],"failed")
        self.assertEqual(result["reason"],"diagnostic_clock_discontinuity")
        self.assertFalse(result["bounded_pipeline_observed"])

    def test_normal_cutoff_with_confirmed_worker_exit_keeps_observation_semantics(self):
        result,consumed,_,_=self._collector_shutdown_fixture()
        self.assertEqual(result["status"],"duration_completed")
        self.assertTrue(result["bounded_pipeline_observed"])
        self.assertFalse(result["full_session_acceptance"])
        self.assertEqual(consumed,[])

    def test_formal_daily_gate_rejects_duplicate_stale_partial_and_short_inputs_before_router(self):
        symbols=("SPY.US", "QQQ.US")
        now=datetime(2026,9,21,13,50,tzinfo=UTC)
        def make_rows(latest, count=60):
            return [{"symbol":symbol.removesuffix(".US"), "timeframe":"1d",
                     "event_time":(latest-timedelta(days=index)).isoformat()}
                    for symbol in symbols for index in range(count)]
        complete=make_rows(datetime(2026,9,18,20,tzinfo=UTC))
        duplicate=[dict(row, event_time="2026-09-18T20:00:00+00:00") for row in complete]
        stale=make_rows(datetime(2026,9,17,20,tzinfo=UTC))
        partial=make_rows(datetime(2026,9,21,13,30,tzinfo=UTC))
        short=make_rows(datetime(2026,9,18,20,tzinfo=UTC),59)
        for label, rows in (("duplicate",duplicate),("stale",stale),("partial",partial),("short",short)):
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory, \
                    patch.object(diagnostic,"configured_symbols",return_value=symbols):
                strategy=diagnostic.DiagnosticStrategyPipeline(runtime.load_config(),runtime,Path(directory))
                with patch.object(strategy.router,"run_realtime_signal_router",side_effect=AssertionError("router must remain blocked")):
                    with self.assertRaisesRegex(RuntimeError,"daily_context_not_current_or_complete"):
                        strategy.consume_inputs({"kind":"daily_context","rows":rows,"failures":[]},now,None)
                    with self.assertRaisesRegex(RuntimeError,"daily_context_not_current_or_complete"):
                        strategy.evaluate([],now)
                summary=strategy.summary()
                self.assertFalse(summary["strategy_input_coverage_observed"])
                self.assertEqual(summary["daily_context_validation"]["status"],"failed")
                self.assertEqual(summary["daily_context_validation"]["required_completed_session"],"2026-09-18")
                self.assertEqual(strategy.evaluations,0)
        with tempfile.TemporaryDirectory() as directory, patch.object(diagnostic,"configured_symbols",return_value=symbols):
            strategy=diagnostic.DiagnosticStrategyPipeline(runtime.load_config(),runtime,Path(directory))
            strategy.consume_inputs({"kind":"daily_context","rows":complete,"failures":[]},now,None)
            self.assertEqual(strategy.daily_validation["status"],"passed")
            self.assertEqual(strategy.daily_validation["symbols"]["SPY"]["distinct_date_count"],60)

    def test_fake_sdk_real_worker_ipc_parent_state_bar_builder_and_original_router(self):
        """Only SDK inputs are fake; worker, serialization, parent helpers and router are real."""
        import longbridge.openapi as sdk
        symbols=('SPY.US','QQQ.US')
        clock=[datetime(2026,9,21,13,50,tzinfo=UTC)]
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return clock[0].astimezone(tz) if tz is not None else clock[0].astimezone().replace(tzinfo=None)
        instances=[]
        class Quote:
            def __init__(self, config): instances.append(self)
            def set_on_quote(self, callback): self.on_quote=callback
            def set_on_trades(self, callback): self.on_trade=callback
            def subscribe(self, requested, types):
                self.symbols=list(requested)
                self.types=list(types)
            def subscriptions(self): return [{'symbol':s,'sub_types':self.types} for s in self.symbols]
            def quote(self, requested):
                return [{'symbol':s,'timestamp':clock[0].astimezone().replace(tzinfo=None),
                    'last_done':Decimal('100'),'open':Decimal('100'),'high':Decimal('101'),'low':Decimal('99'),'volume':100} for s in requested]
            def candlesticks(self,symbol,period,count,adjust,sessions):
                day=datetime(2026,9,18,20,tzinfo=UTC); rows=[]
                while len(rows)<count:
                    if day.weekday()<5:
                        rows.append({'timestamp':day,'open':Decimal('100'),'high':Decimal('101'),
                            'low':Decimal('99'),'close':Decimal('100'),'volume':100})
                    day-=timedelta(days=1)
                return list(reversed(rows))
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            output=Path(directory)
            config=replace(runtime.load_config(),daily_context_path=output/'absent-daily.jsonl',paper_order_dispatch_enabled=False)
            for module in (runtime, transport, diagnostic, sdk_rules):
                if hasattr(module,'configured_symbols'): stack.enter_context(patch.object(module,'configured_symbols',return_value=symbols))
                if hasattr(module,'configured_trading_symbols'): stack.enter_context(patch.object(module,'configured_trading_symbols',return_value=symbols))
            stack.enter_context(patch.object(transport,'load_config',return_value=config))
            stack.enter_context(patch.object(transport,'read_client_id',return_value='offline-client'))
            stack.enter_context(patch.object(transport,'datetime',Clock))
            stack.enter_context(patch.object(sdk,'QuoteContext',Quote))
            stack.enter_context(patch.object(sdk,'OAuthBuilder',lambda _:SimpleNamespace(build=lambda _:object())))
            stack.enter_context(patch.object(sdk,'Config',SimpleNamespace(from_oauth=lambda _:object())))
            evidence=diagnostic.PipelineProbeEvidence(config,output)
            stop=threading.Event()
            ipc=mp.get_context('spawn').Queue(maxsize=64)
            self.addCleanup(ipc.join_thread)
            self.addCleanup(ipc.close)
            observed=[]
            class Sink:
                def put(self,message,timeout=None):
                    ipc.put(message,timeout=timeout)
                    received=ipc.get(timeout=2)
                    observed.append(received['kind'])
                    append_diagnostic_snapshot(output/'worker_messages.jsonl',received)
                    evidence.consume(received,clock[0])
                    if received['kind']=='ready':
                        quote=instances[0]
                        for moment in (datetime(2026,9,21,13,55,1,tzinfo=UTC),datetime(2026,9,21,14,0,1,tzinfo=UTC)):
                            clock[0]=moment
                            for symbol in symbols:
                                quote.on_quote(symbol,{'timestamp':moment.astimezone().replace(tzinfo=None),
                                    'last_done':Decimal('100'),'open':Decimal('100'),'high':Decimal('101'),'low':Decimal('99'),'volume':200})
                                quote.on_trade(symbol,{'trades':[{'timestamp':moment.astimezone().replace(tzinfo=None),
                                    'price':Decimal('100'),'volume':1,'trade_type':'','trade_session':'Intraday'}]})
                        clock[0]=datetime(2026,9,21,14,0,3,tzinfo=UTC)
                    if received['kind'] in ('bars','error'): stop.set()
                put_nowait=put
            stack.enter_context(patch.object(socket,'create_connection',side_effect=AssertionError('network forbidden')))
            stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')))
            stack.enter_context(patch.object(runtime,'build_sdk_trade_clients',side_effect=AssertionError('orders forbidden')))
            stack.enter_context(patch.object(runtime,'SdkAccountProcessCoordinator',side_effect=AssertionError('accounts forbidden')))
            diagnostic._quote_only_pipeline_worker('unused',Sink(),stop,(),str(output),None)
            self.assertNotIn('error',observed, (output/'worker_messages.jsonl').read_text()[-1600:])
            self.assertEqual(instances[0].symbols,list(symbols))
            self.assertIn('daily_context',observed)
            self.assertEqual(evidence.bar_count,2)
            self.assertEqual(evidence.session.complete_boundary_count,1)
            self.assertEqual(len(evidence.strategy.quote_state),2)
            self.assertEqual(len(evidence.strategy.daily_rows),120)
            self.assertEqual(evidence.strategy.evaluations,1)
            summary=evidence.strategy.summary()
            self.assertTrue(summary['strategy_input_coverage_observed'])
            self.assertFalse(summary['strategy_full_acceptance'])
            decision=json.loads((output/'strategy/boundary_decisions.jsonl').read_text())
            self.assertEqual(len(decision['allowed_runtime_ids']),8)
            pa002=next(row for row in decision['runtime_context'] if row['runtime_id']=='M10-PA-002-5m')
            self.assertEqual(pa002['input_status'],'insufficient_declared_context')
            self.assertEqual(pa002['observed_rows_min'],1)
            self.assertFalse(decision['order_access'])
