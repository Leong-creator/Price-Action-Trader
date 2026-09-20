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
