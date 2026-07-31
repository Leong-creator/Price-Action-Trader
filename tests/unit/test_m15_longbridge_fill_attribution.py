from __future__ import annotations

import unittest
from decimal import Decimal

from scripts.m15_longbridge_fill_attribution_lib import (
    add_completed_trade_performance,
    apply_account_reconciliation_adjustments,
    build_virtual_position_layers,
    rebuild_fill_attribution,
    rebuild_fill_attribution_from_history,
)


class M15LongbridgeFillAttributionTest(unittest.TestCase):
    def test_completed_trade_is_not_inflated_by_multiple_exit_fill_events(self) -> None:
        result = rebuild_fill_attribution(
            [
                self.local_row(
                    order_id="open-1",
                    signal_id="open",
                    symbol="AAPL",
                    side="buy",
                    quantity="4",
                    runtime_id="M10-PA-004-long-1d",
                    capital_bucket="pa004",
                    test_epoch_id="formal-epoch",
                    position_action="open_long",
                ),
                self.local_row(
                    order_id="exit-1",
                    signal_id="exit-1",
                    symbol="AAPL",
                    side="sell",
                    quantity="2",
                    runtime_id="M10-PA-004-long-1d",
                    capital_bucket="pa004",
                    test_epoch_id="formal-epoch",
                    position_action="take_profit",
                    source_open_order_id="open-1",
                    source_open_trade_id="open-trade",
                ),
                self.local_row(
                    order_id="exit-2",
                    signal_id="exit-2",
                    symbol="AAPL",
                    side="sell",
                    quantity="2",
                    runtime_id="M10-PA-004-long-1d",
                    capital_bucket="pa004",
                    test_epoch_id="formal-epoch",
                    position_action="take_profit",
                    source_open_order_id="open-1",
                    source_open_trade_id="open-trade",
                ),
            ],
            [
                self.broker_row(
                    order_id="open-1",
                    trade_id="open-trade",
                    symbol="AAPL.US",
                    side="Buy",
                    status="Filled",
                    executed_quantity="4",
                    executed_price="100",
                    created_at="2026-07-21T14:00:00Z",
                ),
                self.broker_row(
                    order_id="exit-1",
                    trade_id="exit-trade-1",
                    symbol="AAPL.US",
                    side="Sell",
                    status="Filled",
                    executed_quantity="2",
                    executed_price="104",
                    created_at="2026-07-21T15:00:00Z",
                ),
                self.broker_row(
                    order_id="exit-2",
                    trade_id="exit-trade-2",
                    symbol="AAPL.US",
                    side="Sell",
                    status="Filled",
                    executed_quantity="2",
                    executed_price="106",
                    created_at="2026-07-21T16:00:00Z",
                ),
            ],
            broker_net_positions={"AAPL": "0"},
        )

        result = add_completed_trade_performance(
            result,
            commission_per_order_side=Decimal("1.99"),
            regulatory_fee_per_sell_order=Decimal("0.02"),
        )

        self.assertEqual(result["summary"]["open_batch_count"], 0)
        self.assertEqual(result["summary"]["exit_fill_event_count"], 2)
        self.assertEqual(result["summary"]["completed_trade_count"], 1)
        self.assertEqual(result["summary"]["gross_realized_pnl"], "20.00")
        self.assertEqual(result["summary"]["estimated_fees"], "6.01")
        self.assertEqual(result["summary"]["estimated_net_realized_pnl"], "13.99")
        self.assertEqual(result["strategy_performance"][0]["completed_trade_count"], 1)
        self.assertEqual(result["strategy_performance"][0]["win_rate_after_estimated_fees_pct"], "100.0000")

        fault_tagged = add_completed_trade_performance(
            result,
            commission_per_order_side=Decimal("1.99"),
            regulatory_fee_per_sell_order=Decimal("0.02"),
            fault_days={"2026-07-21": ["blocked_account_state_stale"]},
        )
        self.assertEqual(fault_tagged["summary"]["normal_completed_trade_count"], 0)
        self.assertEqual(fault_tagged["summary"]["fault_day_completed_trade_count"], 1)
        self.assertEqual(fault_tagged["strategy_performance"], [])
        self.assertEqual(
            fault_tagged["strategy_performance_including_fault_days"][0][
                "completed_trade_count"
            ],
            1,
        )
        self.assertTrue(fault_tagged["completed_trades"][0]["fault_day"])

    def test_account_reconciliation_closes_only_approved_order_ids_and_preserves_future_position(self) -> None:
        payload = {
            "batches": [
                {"symbol": "LCID", "direction": "long", "open_order_id": "old-1", "remaining_quantity": "5.0000"},
                {"symbol": "LCID", "direction": "long", "open_order_id": "future-1", "remaining_quantity": "2.0000"},
            ],
            "events": [],
            "anomalies": [{"symbol": "LCID", "code": "old_mismatch"}],
            "summary": {},
        }
        result = apply_account_reconciliation_adjustments(
            payload,
            {
                "approved": True,
                "adjustments": [{
                    "approved": True,
                    "adjustment_id": "cleanup-lcid",
                    "symbol": "LCID",
                    "open_order_ids": ["old-1"],
                    "resolve_symbol_anomalies": True,
                    "evidence_order_id": "manual-sell",
                }],
            },
            broker_net_positions={"LCID": "2"},
        )
        self.assertEqual(result["account_reconciliation_adjustments"][0]["status"], "applied")
        self.assertEqual(result["batches"][0]["remaining_quantity"], "0.0000")
        self.assertEqual(result["batches"][1]["remaining_quantity"], "2.0000")
        self.assertTrue(result["symbol_checks"][0]["matches_broker_net"])
        self.assertEqual(result["summary"]["account_reconciliation_adjustment_count"], 1)
        self.assertEqual(result["summary"]["anomaly_count"], 0)
        self.assertFalse(result["events"][0]["include_in_strategy_performance"])

        result = apply_account_reconciliation_adjustments(
            {
                "batches": [
                    {"symbol": "LCID", "direction": "long", "open_order_id": "old-1", "remaining_quantity": "5.0000"},
                    {"symbol": "LCID", "direction": "long", "open_order_id": "future-1", "remaining_quantity": "2.0000"},
                ],
                "events": [],
                "anomalies": [{"symbol": "LCID", "code": "old_mismatch"}],
                "summary": {},
            },
            {
                "approved": True,
                "adjustments": [{
                    "approved": True,
                    "adjustment_id": "cleanup-lcid",
                    "symbol": "LCID",
                    "open_order_ids": ["old-1"],
                    "resolve_symbol_anomalies": True,
                    "evidence_order_id": "manual-sell",
                }],
            },
            broker_net_positions={"LCID": "3"},
        )
        self.assertEqual(
            result["account_reconciliation_adjustments"][0]["status"],
            "not_applied_projected_broker_position_mismatch",
        )
        self.assertEqual(result["batches"][0]["remaining_quantity"], "5.0000")

    def test_repeated_unmatched_fill_does_not_accumulate_duplicate_anomalies(self) -> None:
        broker = [{
            "order_id": "exit-missing",
            "trade_id": "trade-missing",
            "status": "filled",
            "executed_quantity": "1",
            "executed_price": "90",
            "symbol": "AAPL",
        }]
        first = rebuild_fill_attribution([], broker, broker_net_positions={})
        second = rebuild_fill_attribution([], broker, broker_net_positions={}, existing_state=first)
        third = rebuild_fill_attribution([], broker, broker_net_positions={}, existing_state=second)

        self.assertEqual(third["summary"]["anomaly_count"], 1)
        self.assertEqual(third["summary"]["excluded_event_count"], 1)

    def test_unmatched_fill_can_be_repaired_when_exact_metadata_arrives_later(self) -> None:
        broker = [self.broker_row(
            order_id="late-order",
            trade_id="late-trade",
            symbol="AAPL.US",
            side="Buy",
            status="Filled",
            executed_quantity="2",
            executed_price="100",
            created_at="2026-07-21T14:00:00Z",
        )]
        first = rebuild_fill_attribution([], broker, broker_net_positions={"AAPL": "2"})
        repaired = rebuild_fill_attribution(
            [self.local_row(
                order_id="late-order",
                signal_id="late-signal",
                symbol="AAPL",
                side="buy",
                quantity="2",
                runtime_id="M10-PA-004-long-1d",
                capital_bucket="pa004",
                test_epoch_id="formal-epoch",
                position_action="open_long",
            )],
            broker,
            broker_net_positions={"AAPL": "2"},
            existing_state=first,
        )

        self.assertEqual(first["summary"]["matched_event_count"], 0)
        self.assertEqual(repaired["summary"]["matched_event_count"], 1)
        self.assertEqual(repaired["summary"]["anomaly_count"], 0)
        self.assertEqual(repaired["batches"][0]["open_order_id"], "late-order")
        self.assertTrue(repaired["symbol_checks"][0]["matches_broker_net"])

    def test_legacy_exit_can_use_unique_source_order_trade_without_guessing(self) -> None:
        result = rebuild_fill_attribution(
            [
                self.local_row(order_id="open-unique", signal_id="open", symbol="AAPL", side="buy", quantity="2", runtime_id="M10-PA-004-long-1d", capital_bucket="pa004", test_epoch_id="formal-epoch", position_action="open_long"),
                self.local_row(order_id="exit-unique", signal_id="exit", symbol="AAPL", side="sell", quantity="2", runtime_id="M10-PA-004-long-1d", capital_bucket="pa004", test_epoch_id="formal-epoch", position_action="close_long", source_open_order_id="open-unique"),
            ],
            [
                self.broker_row(order_id="open-unique", trade_id="trade-unique", symbol="AAPL.US", side="Buy", status="Filled", executed_quantity="2", executed_price="100", created_at="2026-07-21T14:00:00Z"),
                self.broker_row(order_id="exit-unique", trade_id="exit-trade", symbol="AAPL.US", side="Sell", status="Filled", executed_quantity="2", executed_price="105", created_at="2026-07-21T15:00:00Z"),
            ],
            broker_net_positions={"AAPL": "0"},
        )

        exit_event = next(row for row in result["events"] if row["order_id"] == "exit-unique")
        self.assertEqual(exit_event["attribution_status"], "matched_fill_batch")
        self.assertEqual(exit_event["source_open_trade_id"], "trade-unique")
        self.assertEqual(exit_event["realized_pnl"], "10.00")

    def test_gild_partial_fill_and_cancel_release_reservation(self) -> None:
        result = rebuild_fill_attribution_from_history(
            [
                self.local_row(
                    order_id="gild-open-1",
                    signal_id="gild-open-signal",
                    symbol="GILD",
                    side="buy",
                    quantity="10",
                    runtime_id="M12-FTD-001-baseline-1d",
                    capital_bucket="ftd_baseline",
                    test_epoch_id="formal-epoch",
                    position_action="open_long",
                )
            ],
            [
                self.broker_row(
                    order_id="gild-open-1",
                    trade_id="gild-trade-1",
                    symbol="GILD.US",
                    side="Buy",
                    status="PartiallyFilled",
                    executed_quantity="4",
                    executed_price="130.00",
                    created_at="2026-07-20T14:30:00Z",
                ),
                self.broker_row(
                    order_id="gild-open-1",
                    trade_id="",
                    symbol="GILD.US",
                    side="Buy",
                    status="Canceled",
                    executed_quantity="4",
                    executed_price="130.00",
                    created_at="2026-07-20T14:40:00Z",
                ),
            ],
            broker_net_positions={"GILD": "4"},
        )

        self.assertEqual(result["summary"]["anomaly_count"], 0)
        self.assertEqual(result["batches"][0]["batch_id"], "formal-epoch|ftd_baseline|M12-FTD-001-baseline-1d|long|GILD|gild-open-1|gild-trade-1")
        self.assertEqual(result["batches"][0]["filled_quantity"], "4.0000")
        self.assertEqual(result["batches"][0]["remaining_quantity"], "4.0000")
        self.assertEqual(result["reservations"][0]["reserved_quantity"], "0.0000")
        self.assertTrue(result["reservations"][0]["reservation_released"])
        self.assertTrue(result["symbol_checks"][0]["matches_broker_net"])

    def test_lcid_cross_epoch_exit_is_excluded_from_strategy_performance(self) -> None:
        result = rebuild_fill_attribution(
            [
                self.local_row(
                    order_id="lcid-open-old",
                    signal_id="lcid-open-old",
                    symbol="LCID",
                    side="buy",
                    quantity="3",
                    runtime_id="M10-PA-002-5m",
                    capital_bucket="pa002_5m",
                    test_epoch_id="old-epoch",
                    position_action="open_long",
                ),
                self.local_row(
                    order_id="lcid-exit-new",
                    signal_id="lcid-exit-new",
                    symbol="LCID",
                    side="sell",
                    quantity="3",
                    runtime_id="M10-PA-002-5m",
                    capital_bucket="pa002_5m",
                    test_epoch_id="formal-epoch",
                    position_action="take_profit",
                    source_open_order_id="lcid-open-old",
                    source_open_trade_id="lcid-open-trade-1",
                ),
            ],
            [
                self.broker_row(
                    order_id="lcid-open-old",
                    trade_id="lcid-open-trade-1",
                    symbol="LCID.US",
                    side="Buy",
                    status="Filled",
                    executed_quantity="3",
                    executed_price="2.10",
                    created_at="2026-07-18T14:30:00Z",
                ),
                self.broker_row(
                    order_id="lcid-exit-new",
                    trade_id="lcid-exit-trade-1",
                    symbol="LCID.US",
                    side="Sell",
                    status="Filled",
                    executed_quantity="3",
                    executed_price="2.35",
                    created_at="2026-07-20T15:00:00Z",
                ),
            ],
            broker_net_positions={"LCID": "0"},
        )

        exit_event = next(row for row in result["events"] if row["order_id"] == "lcid-exit-new")
        self.assertEqual(exit_event["attribution_status"], "cross_epoch_exit_attribution_rejected")
        self.assertFalse(exit_event["include_in_bucket_performance"])
        self.assertFalse(exit_event["include_in_strategy_performance"])
        self.assertEqual(result["anomalies"][0]["code"], "cross_epoch_exit_attribution_rejected")

    def test_partial_exit_requires_exact_source_open_batch(self) -> None:
        result = rebuild_fill_attribution(
            [
                self.local_row(
                    order_id="gild-open-2",
                    signal_id="gild-open-2",
                    symbol="GILD",
                    side="buy",
                    quantity="5",
                    runtime_id="M12-FTD-001-baseline-1d",
                    capital_bucket="ftd_baseline",
                    test_epoch_id="formal-epoch",
                    position_action="open_long",
                ),
                self.local_row(
                    order_id="gild-exit-2",
                    signal_id="gild-exit-2",
                    symbol="GILD",
                    side="sell",
                    quantity="2",
                    runtime_id="M12-FTD-001-baseline-1d",
                    capital_bucket="ftd_baseline",
                    test_epoch_id="formal-epoch",
                    position_action="take_profit",
                    source_open_order_id="gild-open-2",
                    source_open_trade_id="gild-open-trade-1",
                ),
            ],
            [
                self.broker_row(
                    order_id="gild-open-2",
                    trade_id="gild-open-trade-1",
                    symbol="GILD.US",
                    side="Buy",
                    status="Filled",
                    executed_quantity="5",
                    executed_price="130.00",
                    created_at="2026-07-20T14:30:00Z",
                ),
                self.broker_row(
                    order_id="gild-exit-2",
                    trade_id="gild-exit-trade-1",
                    symbol="GILD.US",
                    side="Sell",
                    status="PartiallyFilled",
                    executed_quantity="2",
                    executed_price="131.50",
                    created_at="2026-07-20T15:10:00Z",
                ),
            ],
            broker_net_positions={"GILD": "3"},
        )

        exit_event = next(row for row in result["events"] if row["order_id"] == "gild-exit-2")
        batch = next(row for row in result["batches"] if row["open_order_id"] == "gild-open-2")
        self.assertEqual(exit_event["attribution_status"], "matched_fill_batch")
        self.assertEqual(exit_event["realized_pnl"], "3.00")
        self.assertEqual(batch["remaining_quantity"], "3.0000")
        self.assertTrue(result["symbol_checks"][0]["matches_broker_net"])

    def test_same_symbol_cross_bucket_is_allowed_and_nets_to_broker_position(self) -> None:
        result = rebuild_fill_attribution(
            [
                self.local_row(
                    order_id="aapl-bucket-a",
                    signal_id="aapl-a",
                    symbol="AAPL",
                    side="buy",
                    quantity="2",
                    runtime_id="M10-PA-004-long-1d",
                    capital_bucket="pa004_long",
                    test_epoch_id="formal-epoch",
                    position_action="open_long",
                ),
                self.local_row(
                    order_id="aapl-bucket-b",
                    signal_id="aapl-b",
                    symbol="AAPL",
                    side="buy",
                    quantity="3",
                    runtime_id="M10-PA-013-1d",
                    capital_bucket="experimental",
                    test_epoch_id="formal-epoch",
                    position_action="open_long",
                ),
            ],
            [
                self.broker_row(
                    order_id="aapl-bucket-a",
                    trade_id="aapl-trade-a",
                    symbol="AAPL.US",
                    side="Buy",
                    status="Filled",
                    executed_quantity="2",
                    executed_price="210.00",
                    created_at="2026-07-20T14:30:00Z",
                ),
                self.broker_row(
                    order_id="aapl-bucket-b",
                    trade_id="aapl-trade-b",
                    symbol="AAPL.US",
                    side="Buy",
                    status="Filled",
                    executed_quantity="3",
                    executed_price="211.00",
                    created_at="2026-07-20T14:31:00Z",
                ),
            ],
            broker_net_positions={"AAPL": "5"},
        )

        self.assertEqual(len(result["batches"]), 2)
        self.assertEqual({row["capital_bucket"] for row in result["batches"]}, {"pa004_long", "experimental"})
        self.assertEqual(result["symbol_checks"][0]["virtual_net_quantity"], "5.0000")
        self.assertTrue(result["symbol_checks"][0]["matches_broker_net"])

    def test_excess_exit_is_marked_as_anomaly_and_excluded(self) -> None:
        result = rebuild_fill_attribution(
            [
                self.local_row(
                    order_id="gild-open-3",
                    signal_id="gild-open-3",
                    symbol="GILD",
                    side="buy",
                    quantity="2",
                    runtime_id="M12-FTD-001-baseline-1d",
                    capital_bucket="ftd_baseline",
                    test_epoch_id="formal-epoch",
                    position_action="open_long",
                ),
                self.local_row(
                    order_id="gild-exit-3",
                    signal_id="gild-exit-3",
                    symbol="GILD",
                    side="sell",
                    quantity="3",
                    runtime_id="M12-FTD-001-baseline-1d",
                    capital_bucket="ftd_baseline",
                    test_epoch_id="formal-epoch",
                    position_action="take_profit",
                    source_open_order_id="gild-open-3",
                    source_open_trade_id="gild-open-trade-3",
                ),
            ],
            [
                self.broker_row(
                    order_id="gild-open-3",
                    trade_id="gild-open-trade-3",
                    symbol="GILD.US",
                    side="Buy",
                    status="Filled",
                    executed_quantity="2",
                    executed_price="130.00",
                    created_at="2026-07-20T14:30:00Z",
                ),
                self.broker_row(
                    order_id="gild-exit-3",
                    trade_id="gild-exit-trade-3",
                    symbol="GILD.US",
                    side="Sell",
                    status="Filled",
                    executed_quantity="3",
                    executed_price="131.00",
                    created_at="2026-07-20T15:10:00Z",
                ),
            ],
            broker_net_positions={"GILD": "2"},
        )

        exit_event = next(row for row in result["events"] if row["order_id"] == "gild-exit-3")
        batch = next(row for row in result["batches"] if row["open_order_id"] == "gild-open-3")
        self.assertEqual(exit_event["attribution_status"], "exit_quantity_exceeds_open_batch")
        self.assertFalse(exit_event["include_in_strategy_performance"])
        self.assertEqual(result["anomalies"][0]["code"], "exit_quantity_exceeds_open_batch")
        self.assertEqual(batch["remaining_quantity"], "2.0000")

    def test_virtual_position_layers_use_actual_holding_prices_and_show_reconciliation_delta(self) -> None:
        payload = add_completed_trade_performance(
            rebuild_fill_attribution(
                [
                    self.local_row(
                        order_id="aapl-open-a",
                        signal_id="aapl-open-a",
                        symbol="AAPL",
                        side="buy",
                        quantity="2",
                        runtime_id="R1",
                        capital_bucket="bucket-a",
                        test_epoch_id="formal-epoch",
                        position_action="open_long",
                    ),
                    self.local_row(
                        order_id="aapl-open-b",
                        signal_id="aapl-open-b",
                        symbol="AAPL",
                        side="buy",
                        quantity="3",
                        runtime_id="R2",
                        capital_bucket="bucket-b",
                        test_epoch_id="formal-epoch",
                        position_action="open_long",
                    ),
                    self.local_row(
                        order_id="msft-open",
                        signal_id="msft-open",
                        symbol="MSFT",
                        side="buy",
                        quantity="1",
                        runtime_id="R3",
                        capital_bucket="bucket-c",
                        test_epoch_id="formal-epoch",
                        position_action="open_long",
                    ),
                    self.local_row(
                        order_id="msft-exit",
                        signal_id="msft-exit",
                        symbol="MSFT",
                        side="sell",
                        quantity="1",
                        runtime_id="R3",
                        capital_bucket="bucket-c",
                        test_epoch_id="formal-epoch",
                        position_action="take_profit",
                        source_open_order_id="msft-open",
                        source_open_trade_id="msft-trade",
                    ),
                ],
                [
                    self.broker_row(
                        order_id="aapl-open-a",
                        trade_id="aapl-trade-a",
                        symbol="AAPL.US",
                        side="Buy",
                        status="Filled",
                        executed_quantity="2",
                        executed_price="100",
                        created_at="2026-07-31T14:30:00Z",
                    ),
                    self.broker_row(
                        order_id="aapl-open-b",
                        trade_id="aapl-trade-b",
                        symbol="AAPL.US",
                        side="Buy",
                        status="Filled",
                        executed_quantity="3",
                        executed_price="101",
                        created_at="2026-07-31T14:35:00Z",
                    ),
                    self.broker_row(
                        order_id="msft-open",
                        trade_id="msft-trade",
                        symbol="MSFT.US",
                        side="Buy",
                        status="Filled",
                        executed_quantity="1",
                        executed_price="200",
                        created_at="2026-07-31T14:40:00Z",
                    ),
                    self.broker_row(
                        order_id="msft-exit",
                        trade_id="msft-exit-trade",
                        symbol="MSFT.US",
                        side="Sell",
                        status="Filled",
                        executed_quantity="1",
                        executed_price="210",
                        created_at="2026-07-31T15:00:00Z",
                    ),
                ],
                broker_net_positions={"AAPL": "6"},
            ),
            commission_per_order_side=Decimal("1.99"),
            regulatory_fee_per_sell_order=Decimal("0.02"),
        )
        payload["completed_trades"][0]["open_market_date"] = "2026-07-31"
        payload["completed_trades"][0]["opened_at"] = "2026-07-31T14:40:00Z"
        for batch in payload["batches"]:
            batch.setdefault("metadata", {})
            batch["metadata"]["submitted_at"] = "2026-07-31T14:30:00Z"

        layers = build_virtual_position_layers(
            payload,
            [
                {"symbol": "AAPL.US", "quantity": "6", "cost_price": "99", "market_price": "110", "unrealized_pnl": "66.00"},
                {"symbol": "TSLA.US", "quantity": "1", "cost_price": "250", "market_price": "260", "unrealized_pnl": "10.00"},
            ],
            market_date="2026-07-31",
        )

        self.assertEqual(layers["actual_account_total"]["gross_market_value"], "920.00")
        self.assertEqual(layers["attributed_virtual_total"]["gross_market_value"], "550.00")
        self.assertEqual(layers["attributed_virtual_total"]["unrealized_pnl"], "47.00")
        self.assertEqual(layers["unreconciled_delta"]["gross_market_value"], "370.00")
        self.assertEqual(layers["today_buy_flow"]["bought_then_sold_count"], 1)
        self.assertEqual(layers["today_buy_flow"]["still_held_batch_count"], 2)
        self.assertEqual(layers["today_buy_flow"]["still_held_unrealized_pnl"], "47.00")
        self.assertEqual(layers["cross_bucket_concentration"][0]["symbol"], "AAPL")
        self.assertEqual(layers["cross_bucket_concentration"][0]["bucket_count"], 2)
        aapl_row = next(row for row in layers["symbol_rows"] if row["symbol"] == "AAPL")
        self.assertEqual(aapl_row["actual_net_quantity"], "6.0000")
        self.assertEqual(aapl_row["attributed_net_quantity"], "5.0000")
        self.assertEqual(aapl_row["unreconciled_net_quantity"], "1.0000")
        tsla_row = next(row for row in layers["symbol_rows"] if row["symbol"] == "TSLA")
        self.assertEqual(tsla_row["attributed_net_quantity"], "0.0000")
        self.assertEqual(tsla_row["unreconciled_gross_market_value"], "260.00")

    def test_virtual_position_layers_do_not_fake_valuation_when_broker_price_missing(self) -> None:
        payload = {
            "batches": [
                {
                    "batch_id": "epoch|bucket-a|R1|long|AAPL|open-1|trade-1",
                    "capital_bucket": "bucket-a",
                    "runtime_id": "R1",
                    "direction": "long",
                    "symbol": "AAPL",
                    "remaining_quantity": "2",
                    "open_price": "100",
                }
            ],
            "completed_trades": [],
        }
        layers = build_virtual_position_layers(
            payload,
            [{"symbol": "AAPL.US", "quantity": "2", "cost_price": "100"}],
        )

        self.assertFalse(layers["actual_account_total"]["valuation_available"])
        self.assertEqual(layers["actual_account_total"]["gross_market_value"], "")
        self.assertEqual(layers["actual_account_total"]["unrealized_pnl"], "")
        self.assertFalse(layers["attributed_virtual_total"]["valuation_available"])
        self.assertEqual(layers["attributed_virtual_total"]["gross_market_value"], "")
        self.assertEqual(layers["attributed_virtual_total"]["unrealized_pnl"], "")
        self.assertFalse(layers["runtime_rows"][0]["valuation_available"])
        self.assertEqual(layers["runtime_rows"][0]["gross_market_value"], "")
        self.assertEqual(layers["bucket_rows"][0]["unrealized_pnl"], "")
        self.assertFalse(layers["symbol_rows"][0]["attributed_valuation_available"])
        self.assertEqual(
            layers["symbol_rows"][0]["attributed_gross_market_value"],
            "",
        )
        self.assertEqual(layers["unreconciled_delta"]["net_quantity"], "0.0000")
        self.assertEqual(layers["unreconciled_delta"]["gross_market_value"], "")

    @staticmethod
    def local_row(
        *,
        order_id: str,
        signal_id: str,
        symbol: str,
        side: str,
        quantity: str,
        runtime_id: str,
        capital_bucket: str,
        test_epoch_id: str,
        position_action: str,
        source_open_order_id: str = "",
        source_open_trade_id: str = "",
    ) -> dict[str, str]:
        return {
            "order_id": order_id,
            "signal_id": signal_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "runtime_id": runtime_id,
            "capital_bucket": capital_bucket,
            "test_epoch_id": test_epoch_id,
            "position_action": position_action,
            "source_open_order_id": source_open_order_id,
            "source_open_trade_id": source_open_trade_id,
        }

    @staticmethod
    def broker_row(
        *,
        order_id: str,
        trade_id: str,
        symbol: str,
        side: str,
        status: str,
        executed_quantity: str,
        executed_price: str,
        created_at: str,
    ) -> dict[str, str]:
        return {
            "order_id": order_id,
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side,
            "status": status,
            "executed_quantity": executed_quantity,
            "executed_price": executed_price,
            "created_at": created_at,
        }


if __name__ == "__main__":
    unittest.main()
