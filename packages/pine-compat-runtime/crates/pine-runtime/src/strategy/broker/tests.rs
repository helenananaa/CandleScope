use super::pending_entries::{PendingEntry, PendingEntryDirection, PendingEntryKind};
use super::pending_exits::{
    DeferredBracketLeg, DeferredRelativeExit, DeferredRelativeExitTrigger, ExitQuantityRequest,
    PendingExitBook, PendingExitQuantity, PendingExitReservationFamily, PendingExitTouch,
    PendingTrailingActivation, PendingTrailingExit, PendingTrailingSpec, PendingTrailingState,
    PendingTrailingUpdate, TrailPointsExitSpec, TrailPriceExitSpec,
};
use super::*;

fn pending_entry_count(broker: &BrokerState) -> usize {
    broker.pending_entry_count()
}

fn pending_exit_count(broker: &BrokerState) -> usize {
    broker.pending_exit_count()
}

fn deferred_relative_exit_count(broker: &BrokerState) -> usize {
    broker.order_book.exits().deferred_relative_count()
}

fn pending_exit_ids(broker: &BrokerState) -> Vec<&str> {
    broker
        .pending_exits_in_placement_order()
        .map(|pending_exit| pending_exit.id.as_str())
        .collect()
}

fn broker_with_long_entry() -> BrokerState {
    let mut broker = BrokerState::new(100_000.0);
    broker.entry_long("L".to_owned(), 0, 10, 100.0, 2.0);
    broker
}

fn exit_metadata(label: &str) -> StrategyExitMetadata {
    StrategyExitMetadata {
        comment: Some(format!("{label} comment")),
        comment_profit: Some(format!("{label} profit comment")),
        comment_loss: Some(format!("{label} loss comment")),
        comment_trailing: Some(format!("{label} trailing comment")),
        alert_message: Some(format!("{label} alert")),
        alert_profit: Some(format!("{label} profit alert")),
        alert_loss: Some(format!("{label} loss alert")),
        alert_trailing: Some(format!("{label} trailing alert")),
        disable_alert: true,
    }
}

fn close_metadata(label: &str) -> StrategyOrderMetadata {
    order_metadata(label, true)
}

fn order_metadata(label: &str, disable_alert: bool) -> StrategyOrderMetadata {
    StrategyOrderMetadata {
        comment: Some(format!("{label} comment")),
        alert_message: Some(format!("{label} alert")),
        disable_alert,
    }
}

fn exit_alert_metadata(label: &str, disable_alert: bool) -> StrategyExitMetadata {
    let mut metadata = exit_metadata(label);
    metadata.disable_alert = disable_alert;
    metadata
}

fn margin_broker(initial_capital: f64, margin_long: f64) -> BrokerState {
    BrokerState::new_with_account_settings(
        initial_capital,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::explicit(margin_long),
        StrategyMarginSetting::default(),
    )
}

fn pending_entry_ids(broker: &BrokerState) -> Vec<&str> {
    broker
        .order_book
        .entries()
        .iter()
        .map(|pending_entry| pending_entry.id.as_str())
        .collect()
}

fn trailing_price_trigger(activation_price: f64, offset_price_distance: f64) -> PendingExitTrigger {
    PendingExitTrigger::Trailing(PendingTrailingExit {
        spec: PendingTrailingSpec {
            activation: PendingTrailingActivation::Price(activation_price),
            offset_price_distance,
        },
        state: PendingTrailingState::Inactive,
    })
}

fn trailing_points_trigger(
    ticks: f64,
    activation_price: f64,
    offset_price_distance: f64,
) -> PendingExitTrigger {
    PendingExitTrigger::Trailing(PendingTrailingExit {
        spec: PendingTrailingSpec {
            activation: PendingTrailingActivation::Points {
                ticks,
                price: activation_price,
            },
            offset_price_distance,
        },
        state: PendingTrailingState::Inactive,
    })
}

fn trailing_price_exit(activation_price: f64, offset_price_distance: f64) -> PendingTrailingExit {
    PendingTrailingExit {
        spec: PendingTrailingSpec {
            activation: PendingTrailingActivation::Price(activation_price),
            offset_price_distance,
        },
        state: PendingTrailingState::Inactive,
    }
}

fn assert_active_trailing_stop(broker: &BrokerState, expected_stop_price: f64) {
    let pending_exit = broker.pending_exit().expect("pending exit");
    let PendingExitTrigger::Trailing(trailing) = &pending_exit.trigger else {
        panic!("expected trailing pending exit");
    };
    assert_eq!(
        trailing.state,
        PendingTrailingState::Active {
            stop_price: expected_stop_price,
        }
    );
}

fn assert_active_trailing_stop_by_id(broker: &BrokerState, id: &str, expected_stop_price: f64) {
    let pending_exit = broker
        .pending_exit_by_identity(id, "L")
        .expect("pending exit");
    let PendingExitTrigger::Trailing(trailing) = &pending_exit.trigger else {
        panic!("expected trailing pending exit");
    };
    assert_eq!(
        trailing.state,
        PendingTrailingState::Active {
            stop_price: expected_stop_price,
        }
    );
}

fn ledger_open_trade(id: &str, quantity: f64, entry_price: f64, commission: f64) -> OpenTrade {
    let entry_bar_index = entry_price as usize;
    let entry_time = (entry_price as i64) * 10;
    OpenTrade {
        key: 0,
        id: id.to_owned(),
        direction: TradeDirection::Long,
        quantity,
        entry_price,
        entry_bar_index,
        entry_time,
        entry_commission: commission,
        max_high: Some(entry_price),
        min_low: Some(entry_price),
        equity_on_entry: Some(100_000.0),
        min_equity_before_entry: Some(100_000.0),
        max_equity_before_entry: Some(100_000.0),
        entry_metadata: StrategyOrderMetadata::default(),
    }
}

#[test]
fn trade_ledger_mirrors_current_single_long_entry() {
    let mut broker = BrokerState::new_with_cash_per_contract_commission(100_000.0, 1.5);

    assert!(broker.entry_long("L".to_owned(), 3, 30, 100.0, 2.0));
    broker.update_open_trade_extremes(112.0, 94.0);

    assert_eq!(broker.trade_ledger.open_trades().len(), 1);
    let open_trade = broker.trade_ledger.open_trade().expect("open trade");
    assert_eq!(open_trade.id, "L");
    assert_eq!(open_trade.direction, TradeDirection::Long);
    assert_eq!(open_trade.quantity, broker.position_size);
    assert_eq!(open_trade.entry_price, broker.avg_price);
    assert_eq!(open_trade.entry_bar_index, 3);
    assert_eq!(open_trade.entry_time, 30);
    assert_eq!(open_trade.entry_commission, broker.open_entry_commission);
    assert_eq!(open_trade.max_high, broker.open_trade_max_high);
    assert_eq!(open_trade.min_low, broker.open_trade_min_low);
    assert_eq!(
        open_trade.equity_on_entry,
        broker.open_trade_equity_on_entry
    );
    assert_eq!(
        open_trade.min_equity_before_entry,
        broker.open_trade_min_equity_before_entry
    );
    assert_eq!(
        open_trade.max_equity_before_entry,
        broker.open_trade_max_equity_before_entry
    );

    let net_position = broker.trade_ledger.net_position();
    assert_eq!(net_position.signed_size, broker.position_size);
    assert_eq!(net_position.avg_price, broker.avg_price);
}

#[test]
fn trade_ledger_tracks_partial_and_final_long_reductions() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_limit_qty("XL1".to_owned(), "L".to_owned(), 110.0, 0.75, 0);
    broker.evaluate_pending_exits(1, 20, 110.0, 100.0);

    let open_trade = broker.trade_ledger.open_trade().expect("open trade");
    assert_eq!(broker.trade_ledger.open_trades().len(), 1);
    assert_eq!(broker.position_size, 1.25);
    assert_eq!(open_trade.quantity, broker.position_size);
    assert_eq!(broker.trade_ledger.net_position().signed_size, 1.25);

    broker.close_long("L".to_owned(), 2, 30, 108.0);

    assert!(broker.trade_ledger.open_trade().is_none());
    assert!(broker.trade_ledger.open_trades().is_empty());
    assert_eq!(broker.trade_ledger.net_position(), NetPosition::default());
    assert_eq!(broker.position_size, 0.0);
}

#[test]
fn trade_ledger_allocates_omitted_entry_by_global_fifo() {
    let mut ledger = TradeLedger::default();
    ledger.append_open_trade_for_test(ledger_open_trade("A", 1.0, 100.0, 2.0));
    ledger.append_open_trade_for_test(ledger_open_trade("B", 2.0, 110.0, 6.0));

    assert_eq!(
        ledger.allocate_exit_fifo(None, 2.25),
        vec![
            TradeAllocation {
                trade_index: 0,
                trade_key: 0,
                entry_id: "A".to_owned(),
                entry_price: 100.0,
                entry_bar_index: 100,
                entry_time: 1000,
                quantity: 1.0,
                entry_commission: 2.0,
                entry_metadata: StrategyOrderMetadata::default(),
            },
            TradeAllocation {
                trade_index: 1,
                trade_key: 1,
                entry_id: "B".to_owned(),
                entry_price: 110.0,
                entry_bar_index: 110,
                entry_time: 1100,
                quantity: 1.25,
                entry_commission: 3.75,
                entry_metadata: StrategyOrderMetadata::default(),
            },
        ]
    );
}

#[test]
fn trade_ledger_append_long_rebuilds_weighted_net_position() {
    let mut ledger = TradeLedger::default();
    ledger.append_long(ledger_open_trade("A", 1.0, 100.0, 2.0));
    ledger.append_long(ledger_open_trade("B", 3.0, 110.0, 6.0));

    assert_eq!(
        ledger.net_position(),
        NetPosition {
            signed_size: 4.0,
            avg_price: 107.5,
        }
    );
}

#[test]
fn trade_ledger_assigns_stable_open_trade_keys() {
    let mut ledger = TradeLedger::default();
    ledger.append_long(ledger_open_trade("A", 1.0, 100.0, 2.0));
    ledger.append_long(ledger_open_trade("A", 2.0, 110.0, 4.0));

    assert_eq!(ledger.open_at(0).map(|trade| trade.key), Some(0));
    assert_eq!(ledger.open_at(1).map(|trade| trade.key), Some(1));
    assert_eq!(ledger.open_quantity_for_key(0), 1.0);
    assert_eq!(ledger.open_quantity_for_key(1), 2.0);
    assert_eq!(ledger.open_entry_price_for_key(0), Some(100.0));
    assert_eq!(ledger.open_entry_price_for_key(1), Some(110.0));

    let allocations = ledger.allocate_exit_fifo(Some("A"), 1.0);
    assert_eq!(allocations[0].trade_key, 0);
    ledger.apply_allocations(&allocations);

    assert!(ledger.open_by_key(0).is_none());
    assert_eq!(
        ledger.open_by_key(1).map(|trade| trade.entry_price),
        Some(110.0)
    );

    ledger.append_long(ledger_open_trade("A", 3.0, 120.0, 6.0));
    assert_eq!(ledger.open_at(1).map(|trade| trade.key), Some(2));
    assert_eq!(ledger.open_quantity_for_key(2), 3.0);
}

#[test]
fn trade_ledger_allocates_specific_open_trade_key() {
    let mut ledger = TradeLedger::default();
    ledger.append_long(ledger_open_trade("A", 1.0, 100.0, 2.0));
    ledger.append_long(ledger_open_trade("A", 2.0, 110.0, 4.0));

    let allocations = ledger.allocate_exit_for_key(1, 1.5);
    assert_eq!(
        allocations,
        vec![TradeAllocation {
            trade_index: 1,
            trade_key: 1,
            entry_id: "A".to_owned(),
            entry_price: 110.0,
            entry_bar_index: 110,
            entry_time: 1100,
            quantity: 1.5,
            entry_commission: 3.0,
            entry_metadata: StrategyOrderMetadata::default(),
        }]
    );

    ledger.apply_allocations(&allocations);

    assert_eq!(ledger.open_quantity_for_key(0), 1.0);
    assert_eq!(ledger.open_quantity_for_key(1), 0.5);
    assert_eq!(ledger.open_quantity_for_entry("A"), 1.5);
    assert_eq!(
        ledger.net_position(),
        NetPosition {
            signed_size: 1.5,
            avg_price: 103.33333333333333,
        }
    );
}

#[test]
fn keyed_pending_exit_closes_only_target_same_id_trade() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    );
    assert!(broker.entry_long("A".to_owned(), 0, 10, 100.0, 1.0));
    assert!(broker.entry_long("A".to_owned(), 1, 20, 110.0, 2.0));
    assert_eq!(
        broker.trade_ledger.open_at(0).map(|trade| trade.key),
        Some(0)
    );
    assert_eq!(
        broker.trade_ledger.open_at(1).map(|trade| trade.key),
        Some(1)
    );

    broker
        .order_book
        .exits_mut()
        .replace_or_append(PendingExit {
            id: "X".to_owned(),
            from_entry: "A".to_owned(),
            target_trade_key: Some(1),
            trigger: PendingExitTrigger::Limit(111.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        });

    broker.evaluate_pending_exits(2, 30, 111.0, 100.0);

    assert_eq!(broker.orders.len(), 3);
    assert_eq!(broker.orders[2].id, "X");
    assert_eq!(broker.orders[2].qty, 2.0);
    assert_eq!(broker.orders[2].price, 111.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].id, "A");
    assert_eq!(broker.trades[0].exit_id, "X");
    assert_eq!(broker.trades[0].qty, 2.0);
    assert_eq!(broker.trades[0].entry_price, 110.0);
    assert_eq!(broker.position_size, 1.0);
    assert_eq!(broker.avg_price, 100.0);
    assert!(broker.trade_ledger.open_by_key(0).is_some());
    assert!(broker.trade_ledger.open_by_key(1).is_none());
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn default_pyramiding_limit_allows_only_one_long_entry() {
    let mut broker = BrokerState::new(100_000.0);

    assert!(broker.can_open_long_entry());
    assert!(broker.entry_long("L".to_owned(), 1, 10, 100.0, 1.0));
    assert!(!broker.can_open_long_entry());
    assert!(!broker.entry_long("L2".to_owned(), 2, 20, 101.0, 1.0));
    assert_eq!(broker.orders.len(), 1);
    assert_eq!(broker.trade_ledger.open_count(), 1);
}

#[test]
fn trade_ledger_allocates_matching_entry_by_fifo() {
    let mut ledger = TradeLedger::default();
    ledger.append_open_trade_for_test(ledger_open_trade("A", 1.0, 100.0, 2.0));
    ledger.append_open_trade_for_test(ledger_open_trade("B", 2.0, 110.0, 6.0));
    ledger.append_open_trade_for_test(ledger_open_trade("A", 3.0, 120.0, 12.0));

    assert_eq!(
        ledger.allocate_exit_fifo(Some("A"), 2.5),
        vec![
            TradeAllocation {
                trade_index: 0,
                trade_key: 0,
                entry_id: "A".to_owned(),
                entry_price: 100.0,
                entry_bar_index: 100,
                entry_time: 1000,
                quantity: 1.0,
                entry_commission: 2.0,
                entry_metadata: StrategyOrderMetadata::default(),
            },
            TradeAllocation {
                trade_index: 2,
                trade_key: 2,
                entry_id: "A".to_owned(),
                entry_price: 120.0,
                entry_bar_index: 120,
                entry_time: 1200,
                quantity: 1.5,
                entry_commission: 6.0,
                entry_metadata: StrategyOrderMetadata::default(),
            },
        ]
    );
}

#[test]
fn trade_ledger_allocates_any_rule_by_exact_entry_id_in_ledger_order() {
    let mut ledger = TradeLedger::default();
    ledger.append_open_trade_for_test(ledger_open_trade("older", 1.0, 100.0, 2.0));
    ledger.append_open_trade_for_test(ledger_open_trade("target", 2.0, 110.0, 6.0));
    ledger.append_open_trade_for_test(ledger_open_trade("target", 3.0, 120.0, 12.0));

    assert_eq!(
        ledger.allocate_exit_any_for_entry("target", 3.5),
        vec![
            TradeAllocation {
                trade_index: 1,
                trade_key: 1,
                entry_id: "target".to_owned(),
                entry_price: 110.0,
                entry_bar_index: 110,
                entry_time: 1100,
                quantity: 2.0,
                entry_commission: 6.0,
                entry_metadata: StrategyOrderMetadata::default(),
            },
            TradeAllocation {
                trade_index: 2,
                trade_key: 2,
                entry_id: "target".to_owned(),
                entry_price: 120.0,
                entry_bar_index: 120,
                entry_time: 1200,
                quantity: 1.5,
                entry_commission: 6.0,
                entry_metadata: StrategyOrderMetadata::default(),
            },
        ]
    );
}

#[test]
fn close_entries_rule_any_internal_close_uses_exact_entry_id_allocation() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    )
    .with_close_entries_rule(StrategyCloseEntriesRule::Any);
    assert_eq!(broker.close_entries_rule, StrategyCloseEntriesRule::Any);
    assert!(broker.entry_long("older".to_owned(), 0, 10, 100.0, 1.0));
    assert!(broker.entry_long("target".to_owned(), 1, 20, 110.0, 2.0));

    broker.close_long("target".to_owned(), 2, 30, 120.0);

    assert_eq!(broker.closed_trade_count(), 1);
    assert_eq!(broker.trades[0].id, "target");
    assert_eq!(broker.trades[0].exit_id, "target");
    assert_eq!(broker.trades[0].qty, 2.0);
    assert_eq!(broker.trades[0].entry_price, 110.0);
    assert_eq!(broker.trades[0].exit_price, 120.0);
    assert_eq!(broker.trades[0].profit, 20.0);
    assert_eq!(broker.open_trade_count(), 1);
    assert_eq!(
        broker
            .trade_ledger
            .open_at(0)
            .map(|trade| trade.id.as_str()),
        Some("older")
    );
    assert_eq!(broker.position_size(), 1.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_entries_rule_any_internal_omitted_exit_stays_fifo() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    )
    .with_close_entries_rule(StrategyCloseEntriesRule::Any);
    assert!(broker.entry_long("older".to_owned(), 0, 10, 100.0, 1.0));
    assert!(broker.entry_long("newer".to_owned(), 1, 20, 110.0, 2.0));

    broker.fill_pending_exit(
        PendingExit {
            id: "X".to_owned(),
            from_entry: String::new(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(120.0),
            quantity: PendingExitQuantity::Fixed(1.5),
            reserved_quantity: 1.5,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        },
        2,
        30,
        120.0,
    );

    assert_eq!(broker.closed_trade_count(), 2);
    assert_eq!(broker.trades[0].id, "older");
    assert_eq!(broker.trades[0].qty, 1.0);
    assert_eq!(broker.trades[0].profit, 20.0);
    assert_eq!(broker.trades[1].id, "newer");
    assert_eq!(broker.trades[1].qty, 0.5);
    assert_eq!(broker.trades[1].profit, 5.0);
    assert_eq!(broker.open_trade_count(), 1);
    assert_eq!(
        broker
            .trade_ledger
            .open_at(0)
            .map(|trade| trade.id.as_str()),
        Some("newer")
    );
    assert_eq!(
        broker.trade_ledger.open_at(0).map(|trade| trade.quantity),
        Some(1.5)
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_entries_rule_any_internal_exit_from_entry_uses_exact_entry_id_allocation() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    )
    .with_close_entries_rule(StrategyCloseEntriesRule::Any);
    assert!(broker.entry_long("older".to_owned(), 0, 10, 100.0, 1.0));
    assert!(broker.entry_long("target".to_owned(), 1, 20, 110.0, 2.0));

    broker.fill_pending_exit(
        PendingExit {
            id: "X".to_owned(),
            from_entry: "target".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(120.0),
            quantity: PendingExitQuantity::Fixed(1.5),
            reserved_quantity: 1.5,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        },
        2,
        30,
        120.0,
    );

    assert_eq!(broker.closed_trade_count(), 1);
    assert_eq!(broker.trades[0].id, "target");
    assert_eq!(broker.trades[0].exit_id, "X");
    assert_eq!(broker.trades[0].qty, 1.5);
    assert_eq!(broker.trades[0].entry_price, 110.0);
    assert_eq!(broker.trades[0].exit_price, 120.0);
    assert_eq!(broker.trades[0].profit, 15.0);
    assert_eq!(broker.open_trade_count(), 2);
    assert_eq!(
        broker
            .trade_ledger
            .open_at(0)
            .map(|trade| (trade.id.as_str(), trade.quantity)),
        Some(("older", 1.0))
    );
    assert_eq!(
        broker
            .trade_ledger
            .open_at(1)
            .map(|trade| (trade.id.as_str(), trade.quantity)),
        Some(("target", 0.5))
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn trade_ledger_applies_allocations_and_rebuilds_net_position() {
    let mut ledger = TradeLedger::default();
    ledger.append_open_trade_for_test(ledger_open_trade("A", 1.0, 100.0, 2.0));
    ledger.append_open_trade_for_test(ledger_open_trade("B", 2.0, 110.0, 6.0));
    ledger.append_open_trade_for_test(ledger_open_trade("C", 3.0, 120.0, 12.0));

    let allocations = ledger.allocate_exit_fifo(None, 3.0);
    ledger.apply_allocations(&allocations);

    let mut expected = ledger_open_trade("C", 3.0, 120.0, 12.0);
    expected.key = 2;
    assert_eq!(ledger.open_trades(), &[expected]);
    assert_eq!(
        ledger.net_position(),
        NetPosition {
            signed_size: 3.0,
            avg_price: 120.0,
        }
    );
}

#[test]
fn order_book_facade_cancels_matching_entry_and_exit_ids() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_limit_long_entry("L".to_owned(), 1.0, 95.0, 0);
    broker.place_exit_stop("L".to_owned(), "L".to_owned(), 90.0, 0);

    assert_eq!(broker.order_book.entries().count(), 1);
    assert_eq!(broker.order_book.exits().count(), 1);

    broker.cancel_pending_order("L");

    assert_eq!(broker.order_book.entries().count(), 0);
    assert_eq!(broker.order_book.exits().count(), 0);
}

#[test]
fn order_book_facade_preserves_pending_entry_fill_behavior() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_limit_long_entry("L".to_owned(), 2.0, 95.0, 0);
    assert_eq!(broker.order_book.entries().count(), 1);

    broker.fill_pending_limit_long_entries(1, 20, 95.0);

    assert_eq!(broker.order_book.entries().count(), 0);
    assert_eq!(broker.position_size(), 2.0);
    assert_eq!(broker.orders.len(), 1);
}

#[test]
fn order_book_facade_preserves_exit_reservations() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 1.25, 0);

    assert_eq!(broker.order_book.exits().count(), 1);
    assert_eq!(
        broker
            .order_book
            .exits()
            .total_reserved_for_entry("L", None),
        1.25
    );
    assert_eq!(
        broker
            .order_book
            .exits()
            .available_unreserved_quantity(broker.position_size, "L", None),
        0.75
    );
}

#[test]
fn cancel_pending_order_removes_matching_pending_entry() {
    let mut broker = BrokerState::new(100_000.0);
    broker.place_pending_limit_long_entry("L".to_owned(), 2.0, 95.0, 0);

    assert_eq!(pending_entry_count(&broker), 1);
    broker.cancel_pending_order("L");
    assert_eq!(pending_entry_count(&broker), 0);

    broker.fill_pending_limit_long_entries(1, 20, 95.0);

    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size(), 0.0);
}

#[test]
fn cancel_pending_order_removes_matching_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit("XL".to_owned(), "L".to_owned(), 110.0, 0);

    assert_eq!(pending_exit_count(&broker), 1);
    broker.cancel_pending_order("XL");
    assert_eq!(pending_exit_count(&broker), 0);

    broker.evaluate_pending_exits(1, 20, 110.0, 100.0);

    assert_eq!(broker.orders.len(), 1);
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size(), 2.0);
}

#[test]
fn cancel_pending_order_unknown_id_is_noop() {
    let mut entry_broker = BrokerState::new(100_000.0);
    entry_broker.place_pending_limit_long_entry("PENDING".to_owned(), 1.0, 95.0, 0);

    entry_broker.cancel_pending_order("OTHER");

    assert_eq!(pending_entry_ids(&entry_broker), vec!["PENDING"]);

    let mut exit_broker = broker_with_long_entry();
    exit_broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 110.0, 0.5, 0);

    exit_broker.cancel_pending_order("OTHER");

    assert_eq!(pending_exit_ids(&exit_broker), vec!["XL"]);
}

#[test]
fn cancel_all_pending_orders_clears_pending_entries_and_exits() {
    let mut entry_broker = BrokerState::new(100_000.0);
    entry_broker.place_pending_limit_long_entry("L1".to_owned(), 1.0, 95.0, 0);
    entry_broker.place_pending_stop_long_entry("L2".to_owned(), 1.0, 105.0, 0);

    assert_eq!(pending_entry_count(&entry_broker), 2);
    entry_broker.cancel_all_pending_orders();
    assert_eq!(pending_entry_count(&entry_broker), 0);

    entry_broker.fill_pending_limit_long_entries(1, 20, 95.0);
    entry_broker.fill_pending_stop_long_entries(1, 20, 105.0);

    assert!(entry_broker.orders.is_empty());
    assert_eq!(entry_broker.position_size(), 0.0);

    let mut exit_broker = broker_with_long_entry();
    exit_broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 110.0, 0.5, 0);
    exit_broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 90.0, 0.5, 0);

    assert_eq!(pending_exit_count(&exit_broker), 2);
    exit_broker.cancel_all_pending_orders();
    assert_eq!(pending_exit_count(&exit_broker), 0);

    exit_broker.evaluate_pending_exits(1, 20, 110.0, 90.0);

    assert_eq!(exit_broker.orders.len(), 1);
    assert!(exit_broker.trades.is_empty());
    assert_eq!(exit_broker.position_size(), 2.0);
}

#[test]
fn pending_exit_book_stores_deferred_relative_exit_attachments() {
    let mut book = PendingExitBook::new();

    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XP".to_owned(),
        from_entry: "L".to_owned(),
        trigger: DeferredRelativeExitTrigger::ProfitTicks {
            ticks: 10.0,
            mintick: 0.5,
        },
        quantity: ExitQuantityRequest::Full,
        last_update_bar_index: 1,
        metadata: StrategyExitMetadata::default(),
    });
    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XL".to_owned(),
        from_entry: "L".to_owned(),
        trigger: DeferredRelativeExitTrigger::LossTicks {
            ticks: 5.0,
            mintick: 0.5,
        },
        quantity: ExitQuantityRequest::Fixed(0.75),
        last_update_bar_index: 2,
        metadata: StrategyExitMetadata::default(),
    });
    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XT".to_owned(),
        from_entry: "L".to_owned(),
        trigger: DeferredRelativeExitTrigger::TrailPoints {
            activation_ticks: 8.0,
            offset_ticks: 3.0,
            mintick: 0.5,
        },
        quantity: ExitQuantityRequest::Percent(50.0),
        last_update_bar_index: 3,
        metadata: StrategyExitMetadata::default(),
    });

    assert_eq!(book.count(), 0);
    assert_eq!(book.deferred_relative_count(), 3);
    assert_eq!(
        book.find_deferred_relative_by_identity("XP", "L")
            .unwrap()
            .trigger,
        DeferredRelativeExitTrigger::ProfitTicks {
            ticks: 10.0,
            mintick: 0.5,
        }
    );
    assert_eq!(
        book.find_deferred_relative_by_identity("XL", "L")
            .unwrap()
            .quantity,
        ExitQuantityRequest::Fixed(0.75)
    );
    assert_eq!(
        book.find_deferred_relative_by_identity("XT", "L")
            .unwrap()
            .last_update_bar_index,
        3
    );
}

#[test]
fn pending_exit_book_replaces_and_clears_deferred_relative_exit_attachments() {
    let mut book = PendingExitBook::new();

    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XP".to_owned(),
        from_entry: "L".to_owned(),
        trigger: DeferredRelativeExitTrigger::ProfitTicks {
            ticks: 10.0,
            mintick: 0.5,
        },
        quantity: ExitQuantityRequest::Full,
        last_update_bar_index: 1,
        metadata: StrategyExitMetadata::default(),
    });
    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XP".to_owned(),
        from_entry: "L".to_owned(),
        trigger: DeferredRelativeExitTrigger::ProfitTicks {
            ticks: 12.0,
            mintick: 0.5,
        },
        quantity: ExitQuantityRequest::Fixed(1.0),
        last_update_bar_index: 2,
        metadata: StrategyExitMetadata::default(),
    });
    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XP".to_owned(),
        from_entry: "OTHER".to_owned(),
        trigger: DeferredRelativeExitTrigger::LossTicks {
            ticks: 4.0,
            mintick: 0.5,
        },
        quantity: ExitQuantityRequest::Full,
        last_update_bar_index: 3,
        metadata: StrategyExitMetadata::default(),
    });

    assert_eq!(book.deferred_relative_count(), 2);
    let replaced = book.find_deferred_relative_by_identity("XP", "L").unwrap();
    assert_eq!(
        replaced.trigger,
        DeferredRelativeExitTrigger::ProfitTicks {
            ticks: 12.0,
            mintick: 0.5,
        }
    );
    assert_eq!(replaced.quantity, ExitQuantityRequest::Fixed(1.0));
    assert_eq!(replaced.last_update_bar_index, 2);

    book.clear_for_entry("L");
    assert_eq!(book.deferred_relative_count(), 1);
    assert!(book.find_deferred_relative_by_identity("XP", "L").is_none());
    assert!(
        book.find_deferred_relative_by_identity("XP", "OTHER")
            .is_some()
    );

    book.cancel_id("XP");
    assert_eq!(book.deferred_relative_count(), 0);

    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XT".to_owned(),
        from_entry: "L".to_owned(),
        trigger: DeferredRelativeExitTrigger::TrailPoints {
            activation_ticks: 8.0,
            offset_ticks: 3.0,
            mintick: 0.5,
        },
        quantity: ExitQuantityRequest::Percent(50.0),
        last_update_bar_index: 4,
        metadata: StrategyExitMetadata::default(),
    });
    book.clear_all();
    assert_eq!(book.deferred_relative_count(), 0);
}

#[test]
fn pending_exit_book_stores_and_takes_deferred_relative_bracket_attachments() {
    let mut book = PendingExitBook::new();

    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XB".to_owned(),
        from_entry: "L".to_owned(),
        trigger: DeferredRelativeExitTrigger::Bracket {
            downside: DeferredBracketLeg::Absolute(95.0),
            upside: DeferredBracketLeg::RelativeProfit {
                ticks: 10.0,
                mintick: 0.5,
            },
        },
        quantity: ExitQuantityRequest::Fixed(1.0),
        last_update_bar_index: 1,
        metadata: StrategyExitMetadata::default(),
    });
    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XB".to_owned(),
        from_entry: "L".to_owned(),
        trigger: DeferredRelativeExitTrigger::Bracket {
            downside: DeferredBracketLeg::RelativeLoss {
                ticks: 8.0,
                mintick: 0.25,
            },
            upside: DeferredBracketLeg::Absolute(112.0),
        },
        quantity: ExitQuantityRequest::Percent(50.0),
        last_update_bar_index: 2,
        metadata: StrategyExitMetadata::default(),
    });
    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XB".to_owned(),
        from_entry: "OTHER".to_owned(),
        trigger: DeferredRelativeExitTrigger::Bracket {
            downside: DeferredBracketLeg::RelativeLoss {
                ticks: 4.0,
                mintick: 0.5,
            },
            upside: DeferredBracketLeg::RelativeProfit {
                ticks: 6.0,
                mintick: 0.5,
            },
        },
        quantity: ExitQuantityRequest::Full,
        last_update_bar_index: 3,
        metadata: StrategyExitMetadata::default(),
    });

    assert_eq!(book.deferred_relative_count(), 2);
    let replaced = book.find_deferred_relative_by_identity("XB", "L").unwrap();
    assert_eq!(
        replaced.trigger,
        DeferredRelativeExitTrigger::Bracket {
            downside: DeferredBracketLeg::RelativeLoss {
                ticks: 8.0,
                mintick: 0.25,
            },
            upside: DeferredBracketLeg::Absolute(112.0),
        }
    );
    assert_eq!(replaced.quantity, ExitQuantityRequest::Percent(50.0));
    assert_eq!(replaced.last_update_bar_index, 2);

    let taken = book.take_deferred_relative_for_entry("L");
    assert_eq!(taken.len(), 1);
    assert_eq!(taken[0].id, "XB");
    assert_eq!(taken[0].from_entry, "L");
    assert_eq!(book.deferred_relative_count(), 1);
    assert!(book.find_deferred_relative_by_identity("XB", "L").is_none());
    assert!(
        book.find_deferred_relative_by_identity("XB", "OTHER")
            .is_some()
    );

    book.cancel_id("XB");
    assert_eq!(book.deferred_relative_count(), 0);

    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XB2".to_owned(),
        from_entry: "L".to_owned(),
        trigger: DeferredRelativeExitTrigger::Bracket {
            downside: DeferredBracketLeg::Absolute(94.0),
            upside: DeferredBracketLeg::RelativeProfit {
                ticks: 12.0,
                mintick: 0.5,
            },
        },
        quantity: ExitQuantityRequest::Full,
        last_update_bar_index: 4,
        metadata: StrategyExitMetadata::default(),
    });
    book.clear_for_entry("L");
    assert_eq!(book.deferred_relative_count(), 0);

    book.replace_or_append_deferred_relative(DeferredRelativeExit {
        id: "XB2".to_owned(),
        from_entry: "L".to_owned(),
        trigger: DeferredRelativeExitTrigger::Bracket {
            downside: DeferredBracketLeg::Absolute(94.0),
            upside: DeferredBracketLeg::RelativeProfit {
                ticks: 12.0,
                mintick: 0.5,
            },
        },
        quantity: ExitQuantityRequest::Full,
        last_update_bar_index: 4,
        metadata: StrategyExitMetadata::default(),
    });
    book.clear_all();
    assert_eq!(book.deferred_relative_count(), 0);
}

#[test]
fn exit_trigger_helpers_classify_single_trigger_reservation_family() {
    assert_eq!(
        PendingExitTrigger::Stop(95.0).reservation_family(),
        PendingExitReservationFamily::SingleTrigger
    );
    assert_eq!(
        PendingExitTrigger::Stop(95.0).single_trigger_side(),
        Some(PendingExitSide::Stop)
    );
    assert_eq!(
        PendingExitTrigger::Limit(105.0).reservation_family(),
        PendingExitReservationFamily::SingleTrigger
    );
    assert_eq!(
        PendingExitTrigger::Limit(105.0).single_trigger_side(),
        Some(PendingExitSide::Limit)
    );
}

#[test]
fn exit_trigger_helpers_classify_bracket_and_trailing_reservation_families() {
    let bracket = PendingExitTrigger::Bracket {
        downside: 95.0,
        upside: 105.0,
    };

    assert_eq!(
        bracket.reservation_family(),
        PendingExitReservationFamily::Bracket
    );
    assert_eq!(bracket.single_trigger_side(), None);
    assert_eq!(
        trailing_price_trigger(105.0, 2.0).reservation_family(),
        PendingExitReservationFamily::Trailing
    );
    assert!(trailing_price_trigger(105.0, 2.0).is_trailing_reservation_candidate());
    assert_eq!(
        trailing_price_trigger(105.0, 2.0).single_trigger_side(),
        None
    );
}

#[test]
fn exit_trigger_helpers_select_single_trigger_touched_candidates() {
    let stop = PendingExitTrigger::Stop(95.0);
    let limit = PendingExitTrigger::Limit(105.0);

    assert_eq!(
        stop.touched_candidate(104.0, 94.0, 0.0),
        Some(PendingExitTouch {
            exit_price: 95.0,
            side: PendingExitSide::Stop,
        })
    );
    assert_eq!(stop.touched_candidate(104.0, 96.0, 0.0), None);
    assert_eq!(
        limit.touched_candidate(106.0, 96.0, 0.0),
        Some(PendingExitTouch {
            exit_price: 105.0,
            side: PendingExitSide::Limit,
        })
    );
    assert_eq!(limit.touched_candidate(104.0, 96.0, 0.0), None);
}

#[test]
fn exit_trigger_helpers_select_bracket_touched_candidates() {
    let bracket = PendingExitTrigger::Bracket {
        downside: 95.0,
        upside: 105.0,
    };

    assert_eq!(
        bracket.touched_candidate(104.0, 94.0, 0.0),
        Some(PendingExitTouch {
            exit_price: 95.0,
            side: PendingExitSide::Stop,
        })
    );
    assert_eq!(
        bracket.touched_candidate(106.0, 96.0, 0.0),
        Some(PendingExitTouch {
            exit_price: 105.0,
            side: PendingExitSide::Limit,
        })
    );
    assert_eq!(
        bracket.touched_candidate(106.0, 94.0, 0.0),
        Some(PendingExitTouch {
            exit_price: 95.0,
            side: PendingExitSide::Stop,
        })
    );
    assert_eq!(bracket.touched_candidate(104.0, 96.0, 0.0), None);
}

#[test]
fn exit_trigger_helpers_exclude_trailing_from_fixed_touch_selection() {
    let trailing = trailing_price_trigger(105.0, 2.0);

    assert_eq!(trailing.touched_candidate(106.0, 94.0, 0.0), None);
}

#[test]
fn trailing_update_helper_activates_without_fill_candidate() {
    let trailing = trailing_price_exit(105.0, 2.0);

    assert_eq!(
        trailing.evaluate_update(110.0, 100.0),
        PendingTrailingUpdate::Persist(PendingTrailingExit {
            spec: PendingTrailingSpec {
                activation: PendingTrailingActivation::Price(105.0),
                offset_price_distance: 2.0,
            },
            state: PendingTrailingState::Active { stop_price: 108.0 },
        })
    );
    assert_eq!(
        trailing.evaluate_update(104.0, 100.0),
        PendingTrailingUpdate::NoChange
    );
}

#[test]
fn trailing_update_helper_selects_active_stop_candidate() {
    let mut trailing = trailing_price_exit(105.0, 2.0);
    trailing.state = PendingTrailingState::Active { stop_price: 108.0 };

    assert_eq!(
        trailing.evaluate_update(115.0, 107.0),
        PendingTrailingUpdate::Candidate(PendingExitTouch {
            exit_price: 108.0,
            side: PendingExitSide::Stop,
        })
    );
}

#[test]
fn trailing_update_helper_ratchets_upward_only() {
    let mut trailing = trailing_price_exit(105.0, 2.0);
    trailing.state = PendingTrailingState::Active { stop_price: 108.0 };

    assert_eq!(
        trailing.evaluate_update(113.0, 109.0),
        PendingTrailingUpdate::Persist(PendingTrailingExit {
            spec: PendingTrailingSpec {
                activation: PendingTrailingActivation::Price(105.0),
                offset_price_distance: 2.0,
            },
            state: PendingTrailingState::Active { stop_price: 111.0 },
        })
    );
    assert_eq!(
        trailing.evaluate_update(109.0, 108.5),
        PendingTrailingUpdate::NoChange
    );
}

#[test]
fn trade_counts_start_flat() {
    let broker = BrokerState::new(100_000.0);

    assert_eq!(broker.closed_trade_count(), 0);
    assert_eq!(broker.open_trade_count(), 0);
}

#[test]
fn pending_market_entry_records_internal_order_without_public_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert_eq!(pending_entry_ids(&broker), vec!["L"]);
    assert_eq!(
        broker.order_book.entries().current().cloned(),
        Some(PendingEntry {
            id: "L".to_owned(),
            direction: PendingEntryDirection::Long,
            kind: PendingEntryKind::Market,
            quantity: 2.0,
            created_bar_index: 0,
            metadata: StrategyOrderMetadata::default(),
            enforce_pyramiding: true,
        })
    );
    assert!(broker.orders.is_empty());
    assert!(broker.trades.is_empty());
    assert!(broker.position.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert!(broker.result().orders.is_empty());
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_replaces_same_id_without_public_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 1.0, 0);
    broker.place_pending_market_long_entry("L".to_owned(), 3.0, 1);

    assert_eq!(pending_entry_count(&broker), 1);
    assert_eq!(
        broker.order_book.entries().current().cloned(),
        Some(PendingEntry {
            id: "L".to_owned(),
            direction: PendingEntryDirection::Long,
            kind: PendingEntryKind::Market,
            quantity: 3.0,
            created_bar_index: 1,
            metadata: StrategyOrderMetadata::default(),
            enforce_pyramiding: true,
        })
    );
    assert!(broker.orders.is_empty());
    assert!(broker.position.is_empty());
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_metadata_survives_until_fill_without_public_output() {
    let mut broker = BrokerState::new(100_000.0);
    let metadata = StrategyOrderMetadata {
        comment: Some("entry comment".to_owned()),
        alert_message: Some("entry alert".to_owned()),
        disable_alert: true,
    };

    broker.place_pending_market_long_entry_with_metadata("L".to_owned(), 2.0, 0, metadata.clone());

    assert_eq!(pending_entry_count(&broker), 1);
    assert_eq!(
        broker
            .order_book
            .entries()
            .current()
            .map(|pending_entry| &pending_entry.metadata),
        Some(&metadata)
    );
    assert!(broker.orders.is_empty());

    broker.fill_pending_market_long_entries(1, 20, 101.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(
        broker
            .trade_ledger
            .open_at(0)
            .map(|open_trade| &open_trade.entry_metadata),
        Some(&metadata)
    );
    assert_eq!(broker.orders.len(), 1);
    assert_eq!(broker.orders[0].id, "L");
    assert_eq!(broker.orders[0].direction, "strategy.long");
    assert_eq!(broker.result().orders.len(), 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_exit_metadata_replaces_same_identity_without_public_output() {
    let mut broker = broker_with_long_entry();
    let first = exit_metadata("first");
    let second = exit_metadata("second");

    broker.with_next_exit_metadata(first.clone(), |broker| {
        broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 1.0, 0);
    });

    assert_eq!(pending_exit_count(&broker), 1);
    assert_eq!(
        broker
            .pending_exit()
            .map(|pending_exit| &pending_exit.metadata),
        Some(&first)
    );
    assert!(broker.orders.len() == 1);

    broker.with_next_exit_metadata(second.clone(), |broker| {
        broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 1.0, 0);
    });

    assert_eq!(pending_exit_count(&broker), 1);
    assert_eq!(
        broker
            .pending_exit()
            .map(|pending_exit| &pending_exit.metadata),
        Some(&second)
    );
    assert_eq!(broker.result().orders.len(), 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn all_entry_exit_metadata_fans_out_to_same_entry_id_pending_exits() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    );
    assert!(broker.entry_long("L".to_owned(), 0, 10, 100.0, 1.0));
    assert!(broker.entry_long("L".to_owned(), 1, 20, 110.0, 2.0));
    let metadata = exit_metadata("all");

    broker.with_next_exit_metadata(metadata.clone(), |broker| {
        broker.place_all_entry_exit_profit_ticks("XP".to_owned(), 10.0, 0.5, 1);
    });

    assert_eq!(pending_exit_count(&broker), 2);
    assert!(
        broker
            .pending_exits_in_placement_order()
            .all(|pending_exit| pending_exit.metadata == metadata)
    );
    assert_eq!(
        broker
            .order_book
            .exits()
            .all_entry_deferred_relative_exits()
            .first()
            .map(|deferred_exit| &deferred_exit.metadata),
        Some(&metadata)
    );
    assert_eq!(broker.result().orders.len(), 2);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_rejects_invalid_quantity() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), f64::NAN, 0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_QTY");
}

#[test]
fn pending_market_entry_does_not_queue_while_position_is_open() {
    let mut broker = broker_with_long_entry();

    broker.place_pending_market_long_entry("L2".to_owned(), 1.0, 1);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 1);
    assert_eq!(broker.open_trade_count(), 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_does_not_fill_on_creation_bar() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.fill_pending_market_long_entries(0, 10, 100.0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.open_trade_count(), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_fills_on_later_bar_price() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.fill_pending_market_long_entries(1, 20, 101.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 1);
    assert_eq!(broker.orders[0].id, "L");
    assert_eq!(broker.orders[0].bar_index, 1);
    assert_eq!(broker.orders[0].time, 20);
    assert_eq!(broker.orders[0].direction, "strategy.long");
    assert_eq!(broker.orders[0].qty, 2.0);
    assert_eq!(broker.orders[0].price, 101.0);
    assert_eq!(broker.position_size, 2.0);
    assert_eq!(broker.open_trade_count(), 1);
    assert_eq!(broker.position.len(), 1);
    assert_eq!(broker.position[0].avg_price, Some(101.0));
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_order_bypasses_entry_pyramiding_limit_for_same_side_long() {
    let mut broker = BrokerState::new(100_000.0);
    assert!(broker.entry_long("E".to_owned(), 0, 10, 100.0, 1.0));

    broker.place_pending_market_long_order("O".to_owned(), 2.0, 1);
    broker.fill_pending_market_long_entries(2, 20, 110.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "O");
    assert_eq!(broker.orders[1].bar_index, 2);
    assert_eq!(broker.orders[1].direction, "strategy.long");
    assert_eq!(broker.orders[1].qty, 2.0);
    assert_eq!(broker.orders[1].price, 110.0);
    assert_eq!(broker.position_size, 3.0);
    assert_eq!(broker.open_trade_count(), 2);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_short_order_reduces_long_without_reversal() {
    let mut broker = BrokerState::new(100_000.0);
    assert!(broker.entry_long("E".to_owned(), 0, 10, 100.0, 1.0));

    broker.place_pending_market_short_order("R".to_owned(), 3.0, 1);
    broker.fill_pending_market_long_entries(2, 20, 110.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "R");
    assert_eq!(broker.orders[1].bar_index, 2);
    assert_eq!(broker.orders[1].direction, "strategy.short");
    assert_eq!(broker.orders[1].qty, 1.0);
    assert_eq!(broker.orders[1].price, 110.0);
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.open_trade_count(), 0);
    assert_eq!(broker.closed_trade_count(), 1);
    assert_eq!(broker.trades[0].id, "E");
    assert_eq!(broker.trades[0].exit_id, "R");
    assert_eq!(broker.trades[0].profit, 10.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_short_order_metadata_records_reduce_alert_and_exit_comment() {
    let mut broker = BrokerState::new(100_000.0);
    assert!(broker.entry_long("E".to_owned(), 0, 10, 100.0, 1.0));
    broker.order_fill_alerts.clear();
    let metadata = order_metadata("reduce", false);

    broker.place_pending_market_short_order_with_metadata("R".to_owned(), 3.0, 1, metadata);
    broker.fill_pending_market_long_entries(2, 20, 110.0);

    assert_eq!(broker.closed_trade_count(), 1);
    assert_eq!(broker.closed_trade_exit_comment(0), Some("reduce comment"));
    assert_eq!(
        broker.order_fill_alerts,
        vec![StrategyOrderFillAlertEvent {
            id: "R".to_owned(),
            bar_index: 2,
            time: 20,
            direction: "strategy.short".to_owned(),
            qty: 1.0,
            price: 110.0,
            entry_id: None,
            exit_id: Some("R".to_owned()),
            message: "reduce alert".to_owned(),
        }]
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn margin_long_allows_affordable_long_entry() {
    let mut broker = margin_broker(100.0, 50.0);

    assert!(broker.entry_long("L".to_owned(), 1, 20, 100.0, 2.0));

    assert_eq!(broker.orders.len(), 1);
    assert_eq!(broker.orders[0].price, 100.0);
    assert_eq!(broker.position_size, 2.0);
    assert_eq!(broker.cash, -100.0);
    assert_eq!(broker.equity_value(100.0), 100.0);
    assert_eq!(broker.open_trade_capital_held(100.0), Some(100.0));
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn margin_long_rejects_overleveraged_long_entry_without_mutating_account() {
    let mut broker = margin_broker(100.0, 50.0);

    assert!(!broker.entry_long("L".to_owned(), 1, 20, 100.0, 3.0));

    assert!(broker.orders.is_empty());
    assert!(broker.trades.is_empty());
    assert!(broker.position.is_empty());
    assert_eq!(broker.cash, 100.0);
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.open_trade_count(), 0);
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_MARGIN");
}

#[test]
fn margin_long_rejects_unaffordable_limit_entry_at_fill_time() {
    let mut broker = margin_broker(100.0, 100.0);

    broker.place_pending_limit_long_entry("L".to_owned(), 2.0, 60.0, 0);
    broker.fill_pending_limit_long_entries(1, 20, 59.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.cash, 100.0);
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_MARGIN");
}

#[test]
fn margin_long_rejects_unaffordable_stop_entry_at_fill_time() {
    let mut broker = margin_broker(100.0, 100.0);

    broker.place_pending_stop_long_entry("L".to_owned(), 2.0, 60.0, 0);
    broker.fill_pending_stop_long_entries(1, 20, 61.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.cash, 100.0);
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_MARGIN");
}

#[test]
fn margin_long_rejects_unaffordable_stop_limit_entry_at_fill_time() {
    let mut broker = margin_broker(100.0, 100.0);

    broker.place_pending_stop_limit_long_entry("L".to_owned(), 2.0, 70.0, 60.0, 0);
    broker.fill_pending_stop_limit_long_entries(1, 20, 71.0, 59.0);
    broker.fill_pending_stop_limit_long_entries(2, 30, 65.0, 59.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.cash, 100.0);
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_MARGIN");
}

#[test]
fn margin_rejected_pending_entry_clears_attached_exits() {
    let mut broker = margin_broker(100.0, 100.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    assert_eq!(pending_exit_count(&broker), 1);
    broker.fill_pending_market_long_entries(1, 20, 100.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_MARGIN");
}

#[test]
fn margin_call_partially_liquidates_long_position() {
    let mut broker = margin_broker(165.0, 25.0);
    assert!(broker.entry_long("L".to_owned(), 1, 20, 4.0, 100.0));
    broker.update_open_trade_extremes(4.0, 3.0);

    assert!(
        (broker
            .margin_liquidation_price()
            .expect("price before margin call")
            - 235.0 / 75.0)
            .abs()
            < 1e-10
    );

    broker.evaluate_margin_call_long(1, 20, 3.0);

    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "Margin Call");
    assert_eq!(broker.orders[1].direction, "strategy.short");
    assert_eq!(broker.orders[1].qty, 52.0);
    assert_eq!(broker.orders[1].price, 3.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].id, "L");
    assert_eq!(broker.trades[0].exit_id, "Margin Call");
    assert_eq!(broker.trades[0].qty, 52.0);
    assert_eq!(broker.trades[0].profit, -52.0);
    assert_eq!(broker.position_size, 48.0);
    assert_eq!(broker.avg_price, 4.0);
    assert_eq!(broker.cash, -79.0);
    assert_eq!(broker.equity_value(3.0), 65.0);
    assert_eq!(broker.open_trade_capital_held(3.0), Some(36.0));
    assert!(
        (broker
            .margin_liquidation_price()
            .expect("price after margin call")
            - 79.0 / 36.0)
            .abs()
            < 1e-10
    );
    assert_eq!(broker.open_trade_count(), 1);
    assert_eq!(broker.closed_trade_count(), 1);
    assert_eq!(
        broker
            .trade_ledger
            .open_trade()
            .expect("open trade after partial margin call")
            .quantity,
        broker.position_size
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn margin_call_clamps_to_full_long_position() {
    let mut broker = margin_broker(100.0, 25.0);
    assert!(broker.entry_long("L".to_owned(), 1, 20, 4.0, 100.0));

    broker.evaluate_margin_call_long(2, 30, 1.0);

    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "Margin Call");
    assert_eq!(broker.orders[1].qty, 100.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].qty, 100.0);
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.avg_price, 0.0);
    assert_eq!(broker.open_trade_count(), 0);
    assert_eq!(broker.closed_trade_count(), 1);
    assert!(broker.trade_ledger.open_trade().is_none());
}

#[test]
fn margin_call_is_noop_when_available_funds_cover_margin() {
    let mut broker = margin_broker(200.0, 25.0);
    assert!(broker.entry_long("L".to_owned(), 1, 20, 4.0, 100.0));

    broker.evaluate_margin_call_long(1, 20, 3.0);

    assert_eq!(broker.orders.len(), 1);
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 100.0);
    assert_eq!(broker.cash, -200.0);
}

#[test]
fn margin_liquidation_price_is_na_without_active_long_margin_state() {
    let mut broker = BrokerState::new(100.0);
    assert_eq!(broker.margin_liquidation_price(), None);
    assert!(broker.entry_long("L".to_owned(), 1, 20, 4.0, 1.0));
    assert_eq!(broker.margin_liquidation_price(), None);

    let mut full_margin = margin_broker(100.0, 100.0);
    assert!(full_margin.entry_long("L".to_owned(), 1, 20, 4.0, 1.0));
    assert_eq!(full_margin.margin_liquidation_price(), None);
}

#[test]
fn pending_market_entry_fill_uses_first_eligible_entry_and_clears_rest() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L1".to_owned(), 1.0, 0);
    broker.place_pending_market_long_entry("L2".to_owned(), 3.0, 0);
    broker.fill_pending_market_long_entries(1, 20, 101.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 1);
    assert_eq!(broker.orders[0].id, "L1");
    assert_eq!(broker.orders[0].qty, 1.0);
    assert_eq!(broker.position_size, 1.0);
    assert!(broker.order_book.entries().find_by_id("L2").is_none());
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_fill_clears_book_when_position_is_already_open() {
    let mut broker = BrokerState::new(100_000.0);
    broker.place_pending_market_long_entry("L".to_owned(), 1.0, 0);
    broker.entry_long("E".to_owned(), 0, 10, 100.0, 2.0);

    broker.fill_pending_market_long_entries(1, 20, 101.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 1);
    assert_eq!(broker.orders[0].id, "E");
    assert_eq!(broker.position_size, 2.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_limit_entry_rejects_invalid_price() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_limit_long_entry("L".to_owned(), 1.0, f64::NAN, 0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_PRICE");
}

#[test]
fn pending_limit_entry_does_not_fill_on_creation_bar() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_limit_long_entry("L".to_owned(), 2.0, 100.0, 0);
    broker.fill_pending_limit_long_entries(0, 10, 99.0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_limit_entry_fills_on_later_low_crossing_bar() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_limit_long_entry("L".to_owned(), 2.0, 100.0, 0);
    broker.fill_pending_limit_long_entries(1, 20, 101.0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert!(broker.orders.is_empty());

    broker.fill_pending_limit_long_entries(2, 30, 99.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 1);
    assert_eq!(broker.orders[0].id, "L");
    assert_eq!(broker.orders[0].bar_index, 2);
    assert_eq!(broker.orders[0].time, 30);
    assert_eq!(broker.orders[0].qty, 2.0);
    assert_eq!(broker.orders[0].price, 100.0);
    assert_eq!(broker.position_size, 2.0);
    assert_eq!(broker.position[0].avg_price, Some(100.0));
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_limit_entries_triggered_together_can_exceed_pyramiding_limit() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        Default::default(),
        Default::default(),
        1,
    );

    broker.place_pending_limit_long_entry("L1".to_owned(), 1.0, 100.0, 0);
    broker.place_pending_limit_long_entry("L2".to_owned(), 3.0, 100.0, 0);

    assert_eq!(pending_entry_count(&broker), 2);

    broker.fill_pending_limit_long_entries(1, 20, 99.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[0].id, "L1");
    assert_eq!(broker.orders[0].bar_index, 1);
    assert_eq!(broker.orders[0].qty, 1.0);
    assert_eq!(broker.orders[0].price, 100.0);
    assert_eq!(broker.orders[1].id, "L2");
    assert_eq!(broker.orders[1].bar_index, 1);
    assert_eq!(broker.orders[1].qty, 3.0);
    assert_eq!(broker.orders[1].price, 100.0);
    assert_eq!(broker.position_size, 4.0);
    assert_eq!(broker.avg_price, 100.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_stop_entry_rejects_invalid_price() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_stop_long_entry("L".to_owned(), 1.0, f64::NAN, 0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_PRICE");
}

#[test]
fn pending_stop_entry_does_not_fill_on_creation_bar() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_stop_long_entry("L".to_owned(), 2.0, 100.0, 0);
    broker.fill_pending_stop_long_entries(0, 10, 101.0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_stop_entry_fills_on_later_high_crossing_bar() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_stop_long_entry("L".to_owned(), 2.0, 100.0, 0);
    broker.fill_pending_stop_long_entries(1, 20, 99.0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert!(broker.orders.is_empty());

    broker.fill_pending_stop_long_entries(2, 30, 101.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 1);
    assert_eq!(broker.orders[0].id, "L");
    assert_eq!(broker.orders[0].bar_index, 2);
    assert_eq!(broker.orders[0].time, 30);
    assert_eq!(broker.orders[0].qty, 2.0);
    assert_eq!(broker.orders[0].price, 100.0);
    assert_eq!(broker.position_size, 2.0);
    assert_eq!(broker.position[0].avg_price, Some(100.0));
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_stop_entries_triggered_together_can_exceed_pyramiding_limit() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        Default::default(),
        Default::default(),
        1,
    );

    broker.place_pending_stop_long_entry("L1".to_owned(), 1.0, 100.0, 0);
    broker.place_pending_stop_long_entry("L2".to_owned(), 3.0, 100.0, 0);

    assert_eq!(pending_entry_count(&broker), 2);

    broker.fill_pending_stop_long_entries(1, 20, 101.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[0].id, "L1");
    assert_eq!(broker.orders[0].bar_index, 1);
    assert_eq!(broker.orders[0].qty, 1.0);
    assert_eq!(broker.orders[0].price, 100.0);
    assert_eq!(broker.orders[1].id, "L2");
    assert_eq!(broker.orders[1].bar_index, 1);
    assert_eq!(broker.orders[1].qty, 3.0);
    assert_eq!(broker.orders[1].price, 100.0);
    assert_eq!(broker.position_size, 4.0);
    assert_eq!(broker.avg_price, 100.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_stop_limit_entry_rejects_invalid_price() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_stop_limit_long_entry("L".to_owned(), 1.0, f64::NAN, 100.0, 0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_PRICE");
}

#[test]
fn pending_stop_limit_entry_activates_without_filling_on_activation_bar() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_stop_limit_long_entry("L".to_owned(), 2.0, 105.0, 100.0, 0);
    broker.fill_pending_stop_limit_long_entries(1, 20, 106.0, 99.0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(
        broker
            .order_book
            .entries()
            .current()
            .map(|entry| entry.kind),
        Some(PendingEntryKind::StopLimit {
            stop_price: 105.0,
            limit_price: 100.0,
            activated_bar_index: Some(1),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_stop_limit_entry_fills_after_activation_on_later_low_crossing_bar() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_stop_limit_long_entry("L".to_owned(), 2.0, 105.0, 100.0, 0);
    broker.fill_pending_stop_limit_long_entries(1, 20, 106.0, 99.0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert!(broker.orders.is_empty());

    broker.fill_pending_stop_limit_long_entries(2, 30, 104.0, 99.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 1);
    assert_eq!(broker.orders[0].id, "L");
    assert_eq!(broker.orders[0].bar_index, 2);
    assert_eq!(broker.orders[0].time, 30);
    assert_eq!(broker.orders[0].qty, 2.0);
    assert_eq!(broker.orders[0].price, 100.0);
    assert_eq!(broker.position_size, 2.0);
    assert_eq!(broker.position[0].avg_price, Some(100.0));
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_stop_limit_entries_triggered_together_can_exceed_pyramiding_limit() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        Default::default(),
        Default::default(),
        1,
    );

    broker.place_pending_stop_limit_long_entry("L1".to_owned(), 1.0, 105.0, 100.0, 0);
    broker.place_pending_stop_limit_long_entry("L2".to_owned(), 3.0, 105.0, 100.0, 0);

    assert_eq!(pending_entry_count(&broker), 2);

    broker.fill_pending_stop_limit_long_entries(1, 20, 106.0, 99.0);

    assert_eq!(pending_entry_count(&broker), 2);
    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size, 0.0);

    broker.fill_pending_stop_limit_long_entries(2, 30, 104.0, 99.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[0].id, "L1");
    assert_eq!(broker.orders[0].bar_index, 2);
    assert_eq!(broker.orders[0].qty, 1.0);
    assert_eq!(broker.orders[0].price, 100.0);
    assert_eq!(broker.orders[1].id, "L2");
    assert_eq!(broker.orders[1].bar_index, 2);
    assert_eq!(broker.orders[1].qty, 3.0);
    assert_eq!(broker.orders[1].price, 100.0);
    assert_eq!(broker.position_size, 4.0);
    assert_eq!(broker.avg_price, 100.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_allows_attached_stop_exit_without_public_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert_eq!(pending_exit_count(&broker), 1);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.orders.is_empty());
    assert!(broker.position.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_attachment_uses_pending_quantity_for_reservations() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 0.75, 0);
    broker.place_exit_limit_qty_percent("XL".to_owned(), "L".to_owned(), 110.0, 75.0, 0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(pending_exit_ids(&broker), vec!["XS", "XL"]);
    assert_eq!(
        broker
            .pending_exit_by_identity("XS", "L")
            .unwrap()
            .reserved_quantity,
        0.75
    );
    assert_eq!(
        broker
            .pending_exit_by_identity("XL", "L")
            .unwrap()
            .reserved_quantity,
        1.25
    );
    assert_eq!(
        broker.pending_exit_by_identity("XL", "L").unwrap().quantity,
        PendingExitQuantity::Fixed(1.5)
    );
    assert!(broker.orders.is_empty());
    assert_eq!(broker.position_size, 0.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_attachment_unknown_from_entry_is_noop() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_stop("XL".to_owned(), "OTHER".to_owned(), 95.0, 0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_stores_entry_relative_profit_attachment() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_profit_ticks("XP".to_owned(), "L".to_owned(), 10.0, 0.01, 0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 1);
    let deferred_exit = broker
        .order_book
        .exits()
        .find_deferred_relative_by_identity("XP", "L")
        .unwrap();
    assert_eq!(
        deferred_exit.trigger,
        DeferredRelativeExitTrigger::ProfitTicks {
            ticks: 10.0,
            mintick: 0.01,
        }
    );
    assert_eq!(deferred_exit.quantity, ExitQuantityRequest::Full);
    assert_eq!(deferred_exit.last_update_bar_index, 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn omitted_profit_template_clears_when_replaced_by_absolute_all_entry_exit() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    );

    broker.entry_long("L1".to_owned(), 1, 10, 100.0, 1.0);
    broker.place_all_entry_exit_profit_ticks("XP".to_owned(), 10.0, 0.01, 1);

    assert_eq!(deferred_relative_exit_count(&broker), 1);

    broker.place_exit_limit("XL".to_owned(), String::new(), 110.0, 2);

    assert_eq!(deferred_relative_exit_count(&broker), 0);

    broker.place_pending_market_long_entry("L2".to_owned(), 3.0, 3);
    broker.fill_pending_market_long_entries(4, 40, 105.0);

    assert_eq!(pending_exit_count(&broker), 1);
    let pending_exit = broker.pending_exit().unwrap();
    assert_eq!(pending_exit.id, "XL");
    assert!(pending_exit.from_entry.is_empty());
    assert_eq!(pending_exit.reserved_quantity, 4.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn omitted_loss_template_replaces_profit_template_for_later_entry() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    );

    broker.entry_long("L1".to_owned(), 1, 10, 100.0, 1.0);
    broker.place_all_entry_exit_profit_ticks("XP".to_owned(), 10.0, 0.01, 1);
    broker.place_all_entry_exit_loss_ticks("XL".to_owned(), 20.0, 0.01, 2);

    assert_eq!(deferred_relative_exit_count(&broker), 1);
    let deferred_exit = broker
        .order_book
        .exits()
        .find_deferred_relative_by_identity("XL", "")
        .unwrap();
    assert_eq!(
        deferred_exit.trigger,
        DeferredRelativeExitTrigger::LossTicks {
            ticks: 20.0,
            mintick: 0.01,
        }
    );

    broker.place_pending_market_long_entry("L2".to_owned(), 3.0, 3);
    broker.fill_pending_market_long_entries(4, 40, 105.0);

    assert!(broker.pending_exit_by_identity("XP", "L2").is_none());
    let pending_exit = broker.pending_exit_by_identity("XL", "L2").unwrap();
    assert_eq!(pending_exit.trigger, PendingExitTrigger::Stop(104.8));
    assert_eq!(pending_exit.reserved_quantity, 3.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn omitted_current_relative_exits_record_open_trade_key_scope() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    );
    assert!(broker.entry_long("L1".to_owned(), 1, 10, 100.0, 1.0));
    assert!(broker.entry_long("L2".to_owned(), 2, 20, 110.0, 2.0));

    broker.place_all_entry_exit_profit_ticks("XP".to_owned(), 10.0, 0.01, 3);

    let first = broker
        .pending_exit_by_identity_and_key("XP", "L1", Some(0))
        .unwrap();
    assert_eq!(first.trigger, PendingExitTrigger::Limit(100.1));
    assert_eq!(first.reserved_quantity, 1.0);
    let second = broker
        .pending_exit_by_identity_and_key("XP", "L2", Some(1))
        .unwrap();
    assert_eq!(second.trigger, PendingExitTrigger::Limit(110.1));
    assert_eq!(second.reserved_quantity, 2.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn omitted_future_relative_exit_resolves_with_open_trade_key_scope() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    );

    broker.place_all_entry_exit_profit_ticks("XP".to_owned(), 10.0, 0.01, 0);
    assert_eq!(deferred_relative_exit_count(&broker), 1);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 1);
    broker.fill_pending_market_long_entries(2, 20, 100.0);

    let pending_exit = broker
        .pending_exit_by_identity_and_key("XP", "L", Some(0))
        .unwrap();
    assert_eq!(pending_exit.trigger, PendingExitTrigger::Limit(100.1));
    assert_eq!(pending_exit.reserved_quantity, 2.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_stores_entry_relative_loss_attachment() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_loss_ticks("XL".to_owned(), "L".to_owned(), 10.0, 0.01, 0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 1);
    let deferred_exit = broker
        .order_book
        .exits()
        .find_deferred_relative_by_identity("XL", "L")
        .unwrap();
    assert_eq!(
        deferred_exit.trigger,
        DeferredRelativeExitTrigger::LossTicks {
            ticks: 10.0,
            mintick: 0.01,
        }
    );
    assert_eq!(deferred_exit.quantity, ExitQuantityRequest::Full);
    assert_eq!(deferred_exit.last_update_bar_index, 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_stores_entry_relative_trail_points_attachment() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_trail_points("XT".to_owned(), "L".to_owned(), 10.0, 5.0, 0.01, 0);

    assert_eq!(pending_entry_count(&broker), 1);
    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 1);
    let deferred_exit = broker
        .order_book
        .exits()
        .find_deferred_relative_by_identity("XT", "L")
        .unwrap();
    assert_eq!(
        deferred_exit.trigger,
        DeferredRelativeExitTrigger::TrailPoints {
            activation_ticks: 10.0,
            offset_ticks: 5.0,
            mintick: 0.01,
        }
    );
    assert_eq!(deferred_exit.quantity, ExitQuantityRequest::Full);
    assert_eq!(deferred_exit.last_update_bar_index, 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_market_entry_resolves_stop_profit_bracket_attachment_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_bracket_stop_profit_ticks(
        "XB".to_owned(),
        "L".to_owned(),
        StopProfitBracketSpec {
            stop_price: 95.0,
            profit_ticks: 10.0,
            mintick: 0.5,
        },
        0,
    );

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 1);
    broker.fill_pending_market_long_entries(1, 20, 100.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XB".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Bracket {
                downside: 95.0,
                upside: 105.0,
            },
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());

    broker.evaluate_pending_exits(1, 20, 105.0, 99.0);

    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "XB");
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].qty, 2.0);
    assert_eq!(broker.orders[1].price, 105.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 105.0);
    assert_eq!(broker.trades[0].profit, 10.0);
}

#[test]
fn pending_market_entry_resolves_loss_limit_bracket_attachment_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_bracket_loss_limit_ticks(
        "XB".to_owned(),
        "L".to_owned(),
        LossLimitBracketSpec {
            loss_ticks: 10.0,
            limit_price: 108.0,
            mintick: 0.5,
        },
        0,
    );

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 1);
    broker.fill_pending_market_long_entries(1, 20, 100.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XB".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Bracket {
                downside: 95.0,
                upside: 108.0,
            },
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());

    broker.evaluate_pending_exits(1, 20, 108.0, 99.0);

    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "XB");
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].qty, 2.0);
    assert_eq!(broker.orders[1].price, 108.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 108.0);
    assert_eq!(broker.trades[0].profit, 16.0);
}

#[test]
fn pending_market_entry_resolves_loss_profit_bracket_attachment_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_bracket_loss_profit_ticks(
        "XB".to_owned(),
        "L".to_owned(),
        LossProfitBracketSpec {
            loss_ticks: 10.0,
            profit_ticks: 12.0,
            mintick: 0.5,
        },
        0,
    );

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 1);
    broker.fill_pending_market_long_entries(1, 20, 100.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XB".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Bracket {
                downside: 95.0,
                upside: 106.0,
            },
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());

    broker.evaluate_pending_exits(1, 20, 106.0, 99.0);

    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "XB");
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].qty, 2.0);
    assert_eq!(broker.orders[1].price, 106.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 106.0);
    assert_eq!(broker.trades[0].profit, 12.0);
}

fn assert_pending_entry_stores_trail_points_active_entry_attachment(
    place_entry: impl Fn(&mut BrokerState),
) {
    let mut trail_broker = BrokerState::new(100_000.0);
    place_entry(&mut trail_broker);
    trail_broker.place_exit_trail_points("XT".to_owned(), "L".to_owned(), 10.0, 5.0, 0.01, 0);
    assert_eq!(pending_entry_count(&trail_broker), 1);
    assert_eq!(pending_exit_count(&trail_broker), 0);
    assert_eq!(deferred_relative_exit_count(&trail_broker), 1);
    assert!(trail_broker.diagnostics.is_empty());
}

#[test]
fn active_pending_entries_store_trail_points_active_entry_attachments() {
    assert_pending_entry_stores_trail_points_active_entry_attachment(|broker| {
        broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    });
    assert_pending_entry_stores_trail_points_active_entry_attachment(|broker| {
        broker.place_pending_limit_long_entry("L".to_owned(), 2.0, 95.0, 0);
    });
    assert_pending_entry_stores_trail_points_active_entry_attachment(|broker| {
        broker.place_pending_stop_long_entry("L".to_owned(), 2.0, 105.0, 0);
    });
    assert_pending_entry_stores_trail_points_active_entry_attachment(|broker| {
        broker.place_pending_stop_limit_long_entry("L".to_owned(), 2.0, 105.0, 95.0, 0);
    });
}

#[test]
fn pending_market_entry_resolves_profit_attachment_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_profit_ticks("XP".to_owned(), "L".to_owned(), 10.0, 0.5, 0);

    broker.fill_pending_market_long_entries(1, 20, 100.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XP".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(105.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());

    broker.evaluate_pending_exits(1, 20, 105.0, 99.0);

    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "XP");
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].qty, 2.0);
    assert_eq!(broker.orders[1].price, 105.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 105.0);
    assert_eq!(broker.trades[0].profit, 10.0);
}

#[test]
fn pending_market_entry_resolves_loss_attachment_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_loss_ticks("XL".to_owned(), "L".to_owned(), 10.0, 0.5, 0);

    broker.fill_pending_market_long_entries(1, 20, 100.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());

    broker.evaluate_pending_exits(1, 20, 101.0, 95.0);

    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "XL");
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].qty, 2.0);
    assert_eq!(broker.orders[1].price, 95.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 95.0);
    assert_eq!(broker.trades[0].profit, -10.0);
}

#[test]
fn pending_market_entry_resolves_trail_points_attachment_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_market_long_entry("L".to_owned(), 2.0, 0);
    broker.place_exit_trail_points("XT".to_owned(), "L".to_owned(), 10.0, 4.0, 0.5, 0);

    broker.fill_pending_market_long_entries(1, 20, 100.0);

    assert_eq!(pending_entry_count(&broker), 0);
    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XT".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: trailing_points_trigger(10.0, 105.0, 2.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());

    broker.evaluate_pending_exits(1, 20, 106.0, 103.0);

    assert_eq!(
        broker.pending_exit().unwrap().trigger,
        PendingExitTrigger::Trailing(PendingTrailingExit {
            spec: PendingTrailingSpec {
                activation: PendingTrailingActivation::Points {
                    ticks: 10.0,
                    price: 105.0,
                },
                offset_price_distance: 2.0,
            },
            state: PendingTrailingState::Active { stop_price: 104.0 },
        })
    );
    assert!(broker.trades.is_empty());

    broker.evaluate_pending_exits(2, 30, 106.0, 104.0);

    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "XT");
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].qty, 2.0);
    assert_eq!(broker.orders[1].price, 104.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 104.0);
    assert_eq!(broker.trades[0].profit, 8.0);
}

#[test]
fn pending_limit_entry_resolves_profit_attachment_fixed_quantity_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_limit_long_entry("L".to_owned(), 2.0, 95.0, 0);
    broker.place_exit_profit_ticks_qty("XP".to_owned(), "L".to_owned(), 10.0, 0.5, 0.75, 0);

    broker.fill_pending_limit_long_entries(1, 20, 95.0);

    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XP".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(100.0),
            quantity: PendingExitQuantity::Fixed(0.75),
            reserved_quantity: 0.75,
            multiple_reservation: true,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_limit_entry_resolves_loss_attachment_fixed_quantity_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_limit_long_entry("L".to_owned(), 2.0, 100.0, 0);
    broker.place_exit_loss_ticks_qty("XL".to_owned(), "L".to_owned(), 10.0, 0.5, 0.75, 0);

    broker.fill_pending_limit_long_entries(1, 20, 100.0);

    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Fixed(0.75),
            reserved_quantity: 0.75,
            multiple_reservation: true,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_limit_entry_resolves_trail_points_attachment_fixed_quantity_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_limit_long_entry("L".to_owned(), 2.0, 95.0, 0);
    broker.place_exit_trail_points_qty(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPointsExitSpec {
            activation_ticks: 10.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.75,
        0,
    );

    broker.fill_pending_limit_long_entries(1, 20, 95.0);

    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XT".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: trailing_points_trigger(10.0, 100.0, 2.0),
            quantity: PendingExitQuantity::Fixed(0.75),
            reserved_quantity: 0.75,
            multiple_reservation: true,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_stop_entry_resolves_profit_attachment_percent_quantity_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_stop_long_entry("L".to_owned(), 2.0, 100.0, 0);
    broker.place_exit_profit_ticks_qty_percent("XP".to_owned(), "L".to_owned(), 10.0, 0.5, 50.0, 0);

    broker.fill_pending_stop_long_entries(1, 20, 100.0);

    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XP".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(105.0),
            quantity: PendingExitQuantity::Fixed(1.0),
            reserved_quantity: 1.0,
            multiple_reservation: true,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_stop_entry_resolves_loss_attachment_percent_quantity_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_stop_long_entry("L".to_owned(), 2.0, 100.0, 0);
    broker.place_exit_loss_ticks_qty_percent("XL".to_owned(), "L".to_owned(), 10.0, 0.5, 50.0, 0);

    broker.fill_pending_stop_long_entries(1, 20, 100.0);

    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Fixed(1.0),
            reserved_quantity: 1.0,
            multiple_reservation: true,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_stop_entry_resolves_trail_points_attachment_percent_quantity_after_fill() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_pending_stop_long_entry("L".to_owned(), 2.0, 100.0, 0);
    broker.place_exit_trail_points_qty_percent(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPointsExitSpec {
            activation_ticks: 10.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        50.0,
        0,
    );

    broker.fill_pending_stop_long_entries(1, 20, 100.0);

    assert_eq!(deferred_relative_exit_count(&broker), 0);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XT".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: trailing_points_trigger(10.0, 105.0, 2.0),
            quantity: PendingExitQuantity::Fixed(1.0),
            reserved_quantity: 1.0,
            multiple_reservation: true,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn trade_counts_track_long_entry_and_no_pyramiding_noop() {
    let mut broker = BrokerState::new(100_000.0);

    broker.entry_long("L".to_owned(), 0, 10, 100.0, 2.0);
    assert_eq!(broker.closed_trade_count(), 0);
    assert_eq!(broker.open_trade_count(), 1);

    broker.entry_long("L2".to_owned(), 1, 20, 105.0, 1.0);
    assert_eq!(broker.closed_trade_count(), 0);
    assert_eq!(broker.open_trade_count(), 1);
}

#[test]
fn open_trade_count_reads_trade_ledger_count() {
    let mut broker = BrokerState::new(100_000.0);
    broker
        .trade_ledger
        .append_long(ledger_open_trade("A", 1.0, 100.0, 2.0));
    broker
        .trade_ledger
        .append_long(ledger_open_trade("B", 1.0, 110.0, 2.0));

    assert_eq!(broker.open_trade_count(), 2);
}

#[test]
fn open_trade_fields_read_trade_ledger_entries() {
    let mut broker = BrokerState::new(100_000.0);
    let mut first = ledger_open_trade("A", 1.0, 100.0, 2.0);
    first.max_high = Some(112.0);
    first.min_low = Some(95.0);
    broker.trade_ledger.append_long(first);
    broker
        .trade_ledger
        .append_long(ledger_open_trade("B", 3.0, 110.0, 6.0));

    assert_eq!(broker.open_trade_entry_price(0), Some(100.0));
    assert_eq!(broker.open_trade_entry_id(0), Some("A"));
    assert_eq!(broker.open_trade_entry_bar_index(0), Some(100));
    assert_eq!(broker.open_trade_entry_time(0), Some(1000));
    assert_eq!(broker.open_trade_size(0), Some(1.0));
    assert_eq!(broker.open_trade_profit(0, 112.0), Some(12.0));
    assert_eq!(broker.open_trade_commission(0), Some(2.0));
    assert_eq!(broker.open_trade_max_runup(0), Some(12.0));
    assert_eq!(broker.open_trade_max_drawdown(0), Some(5.0));

    assert_eq!(broker.open_trade_entry_price(1), Some(110.0));
    assert_eq!(broker.open_trade_entry_id(1), Some("B"));
    assert_eq!(broker.open_trade_entry_bar_index(1), Some(110));
    assert_eq!(broker.open_trade_entry_time(1), Some(1100));
    assert_eq!(broker.open_trade_size(1), Some(3.0));
    assert_eq!(broker.open_trade_profit(1, 112.0), Some(6.0));
    assert_eq!(broker.open_trade_commission(1), Some(6.0));
    assert_eq!(broker.open_trade_max_runup(1), Some(0.0));
    assert_eq!(broker.open_trade_max_drawdown(1), Some(0.0));

    assert_eq!(broker.open_trade_entry_price(2), None);
    assert_eq!(broker.open_trade_entry_price(-1), None);
}

#[test]
fn trade_counts_track_matching_close() {
    let mut broker = broker_with_long_entry();

    broker.close_long("L".to_owned(), 1, 20, 110.0);

    assert_eq!(broker.closed_trade_count(), 1);
    assert_eq!(broker.open_trade_count(), 0);
}

#[test]
fn entry_rejects_non_finite_fill_price() {
    let mut broker = BrokerState::new(100_000.0);

    broker.entry_long("L".to_owned(), 0, 10, f64::NAN, 2.0);

    assert_eq!(broker.closed_trade_count(), 0);
    assert_eq!(broker.open_trade_count(), 0);
    assert!(broker.orders.is_empty());
    assert!(broker.position.is_empty());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_PRICE");
}

#[test]
fn close_rejects_non_finite_fill_price_without_closing_position() {
    let mut broker = broker_with_long_entry();

    broker.close_long("L".to_owned(), 1, 20, f64::INFINITY);

    assert_eq!(broker.closed_trade_count(), 0);
    assert_eq!(broker.open_trade_count(), 1);
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 2.0);
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_PRICE");
}

#[test]
fn trade_counts_track_filled_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.evaluate_pending_exits(1, 20, 100.0, 94.0);

    assert_eq!(broker.closed_trade_count(), 1);
    assert_eq!(broker.open_trade_count(), 0);
}

#[test]
fn full_quantity_pending_exit_still_closes_whole_position() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.evaluate_pending_exits(1, 20, 100.0, 94.0);

    assert_eq!(broker.orders[1].qty, 2.0);
    assert_eq!(broker.trades[0].qty, 2.0);
    assert_eq!(broker.position_size, 0.0);
}

#[test]
fn trade_counts_ignore_mismatched_close_and_exit() {
    let mut broker = broker_with_long_entry();

    broker.close_long("OTHER".to_owned(), 1, 20, 110.0);
    broker.place_exit_stop("XL".to_owned(), "OTHER".to_owned(), 95.0, 1);

    assert_eq!(broker.closed_trade_count(), 0);
    assert_eq!(broker.open_trade_count(), 1);
}

#[test]
fn place_exit_while_flat_is_noop_without_pending_state() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn place_exit_limit_while_flat_is_noop_without_pending_state() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_exit_limit("XL".to_owned(), "L".to_owned(), 110.0, 0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn place_exit_profit_ticks_while_flat_is_noop_without_pending_state() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_exit_profit_ticks("XP".to_owned(), "L".to_owned(), 10.0, 0.5, 0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn place_exit_loss_ticks_while_flat_is_noop_without_pending_state() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_exit_loss_ticks("XL".to_owned(), "L".to_owned(), 5.0, 0.5, 0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn place_exit_while_long_records_pending_stop() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.pending_exit_by_identity("XL", "L").is_some());
    assert!(broker.pending_exit_by_identity("XL", "OTHER").is_none());
    assert_eq!(pending_exit_ids(&broker), vec!["XL"]);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn place_exit_replaces_existing_pending_stop() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);
    broker.place_exit_stop("XL2".to_owned(), "L".to_owned(), 90.0, 1);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.pending_exit_by_identity("XL", "L").is_none());
    assert!(broker.pending_exit_by_identity("XL2", "L").is_some());
    assert_eq!(pending_exit_ids(&broker), vec!["XL2"]);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL2".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(90.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        })
    );
}

#[test]
fn omitted_quantity_single_trigger_with_new_identity_replaces_instead_of_appending() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);
    broker.place_exit_limit("XL".to_owned(), "L".to_owned(), 110.0, 1);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.pending_exit_by_identity("XS", "L").is_none());
    assert_eq!(pending_exit_ids(&broker), vec!["XL"]);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(110.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn reservation_helpers_track_reserved_and_available_quantity() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XL".to_owned(), "L".to_owned(), 95.0, 1.25, 0);

    assert_eq!(
        broker
            .order_book
            .exits()
            .total_reserved_for_entry("L", None),
        1.25
    );
    assert_eq!(
        broker
            .order_book
            .exits()
            .available_unreserved_quantity(broker.position_size, "L", None),
        0.75
    );
    assert_eq!(
        broker.order_book.exits().available_unreserved_quantity(
            broker.position_size,
            "L",
            Some(("XL", "L"))
        ),
        2.0
    );
}

#[test]
fn reservation_resolver_rejects_zero_available_quantity() {
    let mut broker = broker_with_long_entry();

    let resolved =
        broker.resolve_exit_quantity_request_for_available(ExitQuantityRequest::Full, 2.0, 0.0);

    assert_eq!(resolved, None);
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_QTY");
}

#[test]
fn reservation_resolver_reserves_full_available_quantity() {
    let mut broker = broker_with_long_entry();

    let resolved =
        broker.resolve_exit_quantity_request_for_available(ExitQuantityRequest::Full, 2.0, 2.0);

    assert_eq!(resolved, Some((PendingExitQuantity::Full, 2.0)));
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn reservation_resolver_clamps_fixed_quantity_to_available_quantity() {
    let mut broker = broker_with_long_entry();

    let resolved = broker.resolve_exit_quantity_request_for_available(
        ExitQuantityRequest::Fixed(2.0),
        2.0,
        0.75,
    );

    assert_eq!(resolved, Some((PendingExitQuantity::Fixed(2.0), 0.75)));
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn reservation_resolver_clamps_percent_quantity_to_available_quantity() {
    let mut broker = broker_with_long_entry();

    let resolved = broker.resolve_exit_quantity_request_for_available(
        ExitQuantityRequest::Percent(50.0),
        2.0,
        0.75,
    );

    assert_eq!(resolved, Some((PendingExitQuantity::Fixed(1.0), 0.75)));
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn reservation_resolver_clamps_over_100_percent_to_available_quantity() {
    let mut broker = broker_with_long_entry();

    let resolved = broker.resolve_exit_quantity_request_for_available(
        ExitQuantityRequest::Percent(150.0),
        2.0,
        2.0,
    );

    assert_eq!(resolved, Some((PendingExitQuantity::Fixed(3.0), 2.0)));
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn multiple_fixed_stop_exits_fill_in_placement_order() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS1".to_owned(), "L".to_owned(), 95.0, 0.75, 0);
    broker.place_exit_stop_qty("XS2".to_owned(), "L".to_owned(), 94.0, 0.5, 0);

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(pending_exit_ids(&broker), vec!["XS1", "XS2"]);

    broker.evaluate_pending_exits(1, 20, 100.0, 93.0);

    assert_eq!(broker.orders[1].id, "XS1");
    assert_eq!(broker.orders[1].qty, 0.75);
    assert_eq!(broker.orders[1].price, 95.0);
    assert_eq!(broker.orders[2].id, "XS2");
    assert_eq!(broker.orders[2].qty, 0.5);
    assert_eq!(broker.orders[2].price, 94.0);
    assert_eq!(broker.trades.len(), 2);
    assert_eq!(broker.position_size, 0.75);
    assert_eq!(pending_exit_count(&broker), 0);
}

#[test]
fn multiple_fixed_limit_exits_fill_in_placement_order() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit_qty("XL1".to_owned(), "L".to_owned(), 105.0, 0.75, 0);
    broker.place_exit_limit_qty("XL2".to_owned(), "L".to_owned(), 106.0, 0.5, 0);

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(pending_exit_ids(&broker), vec!["XL1", "XL2"]);

    broker.evaluate_pending_exits(1, 20, 107.0, 100.0);

    assert_eq!(broker.orders[1].id, "XL1");
    assert_eq!(broker.orders[1].qty, 0.75);
    assert_eq!(broker.orders[1].price, 105.0);
    assert_eq!(broker.orders[2].id, "XL2");
    assert_eq!(broker.orders[2].qty, 0.5);
    assert_eq!(broker.orders[2].price, 106.0);
    assert_eq!(broker.trades.len(), 2);
    assert_eq!(broker.position_size, 0.75);
    assert_eq!(pending_exit_count(&broker), 0);
}

#[test]
fn replacing_one_fixed_exit_releases_only_that_reservation() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS1".to_owned(), "L".to_owned(), 95.0, 0.5, 0);
    broker.place_exit_stop_qty("XS2".to_owned(), "L".to_owned(), 94.0, 0.75, 0);

    broker.place_exit_stop_qty("XS1".to_owned(), "L".to_owned(), 93.0, 1.25, 1);

    assert_eq!(pending_exit_ids(&broker), vec!["XS1", "XS2"]);
    let replaced = broker.pending_exit_by_identity("XS1", "L").unwrap();
    assert_eq!(replaced.trigger, PendingExitTrigger::Stop(93.0));
    assert_eq!(replaced.quantity, PendingExitQuantity::Fixed(1.25));
    assert_eq!(replaced.reserved_quantity, 1.25);
    let preserved = broker.pending_exit_by_identity("XS2", "L").unwrap();
    assert_eq!(preserved.reserved_quantity, 0.75);
    assert_eq!(
        broker
            .order_book
            .exits()
            .total_reserved_for_entry("L", None),
        2.0
    );
}

#[test]
fn new_fixed_exit_clamps_to_remaining_unreserved_quantity() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit_qty("XL1".to_owned(), "L".to_owned(), 105.0, 1.5, 0);
    broker.place_exit_limit_qty("XL2".to_owned(), "L".to_owned(), 106.0, 1.0, 0);

    assert_eq!(pending_exit_count(&broker), 2);
    let clamped = broker.pending_exit_by_identity("XL2", "L").unwrap();
    assert_eq!(clamped.quantity, PendingExitQuantity::Fixed(1.0));
    assert_eq!(clamped.reserved_quantity, 0.5);
    assert_eq!(
        broker
            .order_book
            .exits()
            .total_reserved_for_entry("L", None),
        2.0
    );
}

#[test]
fn fixed_exit_with_no_unreserved_quantity_is_rejected() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS1".to_owned(), "L".to_owned(), 95.0, 1.0, 0);
    broker.place_exit_stop_qty("XS2".to_owned(), "L".to_owned(), 94.0, 1.0, 0);

    broker.place_exit_stop_qty("XS3".to_owned(), "L".to_owned(), 93.0, 0.5, 0);

    assert_eq!(pending_exit_ids(&broker), vec!["XS1", "XS2"]);
    assert!(broker.pending_exit_by_identity("XS3", "L").is_none());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_QTY");
}

#[test]
fn fixed_exit_after_percent_exit_shares_reservation_pool() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty_percent("XP".to_owned(), "L".to_owned(), 95.0, 50.0, 0);

    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 94.0, 0.5, 0);

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(pending_exit_ids(&broker), vec!["XP", "XS"]);
    assert_eq!(
        broker.pending_exit_by_identity("XP", "L").unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );
    assert_eq!(
        broker
            .pending_exit_by_identity("XP", "L")
            .unwrap()
            .reserved_quantity,
        1.0
    );
    assert_eq!(
        broker
            .pending_exit_by_identity("XS", "L")
            .unwrap()
            .reserved_quantity,
        0.5
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn two_percent_stop_exits_reserve_expected_absolute_quantities() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty_percent("XP1".to_owned(), "L".to_owned(), 95.0, 25.0, 0);
    broker.place_exit_stop_qty_percent("XP2".to_owned(), "L".to_owned(), 94.0, 50.0, 0);

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(pending_exit_ids(&broker), vec!["XP1", "XP2"]);
    let first = broker.pending_exit_by_identity("XP1", "L").unwrap();
    assert_eq!(first.quantity, PendingExitQuantity::Fixed(0.5));
    assert_eq!(first.reserved_quantity, 0.5);
    let second = broker.pending_exit_by_identity("XP2", "L").unwrap();
    assert_eq!(second.quantity, PendingExitQuantity::Fixed(1.0));
    assert_eq!(second.reserved_quantity, 1.0);

    broker.evaluate_pending_exits(1, 20, 100.0, 93.0);

    assert_eq!(broker.orders[1].id, "XP1");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders[2].id, "XP2");
    assert_eq!(broker.orders[2].qty, 1.0);
    assert_eq!(broker.position_size, 0.5);
}

#[test]
fn percent_replacement_releases_old_reservation_first() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty_percent("XP1".to_owned(), "L".to_owned(), 95.0, 25.0, 0);
    broker.place_exit_stop_qty_percent("XP2".to_owned(), "L".to_owned(), 94.0, 25.0, 0);

    broker.place_exit_stop_qty_percent("XP1".to_owned(), "L".to_owned(), 93.0, 75.0, 1);

    assert_eq!(pending_exit_ids(&broker), vec!["XP1", "XP2"]);
    let replaced = broker.pending_exit_by_identity("XP1", "L").unwrap();
    assert_eq!(replaced.trigger, PendingExitTrigger::Stop(93.0));
    assert_eq!(replaced.quantity, PendingExitQuantity::Fixed(1.5));
    assert_eq!(replaced.reserved_quantity, 1.5);
    let preserved = broker.pending_exit_by_identity("XP2", "L").unwrap();
    assert_eq!(preserved.reserved_quantity, 0.5);
    assert_eq!(
        broker
            .order_book
            .exits()
            .total_reserved_for_entry("L", None),
        2.0
    );
}

#[test]
fn over_100_percent_exit_reserves_remaining_unreserved_quantity() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 0.75, 0);
    broker.place_exit_stop_qty_percent("XP".to_owned(), "L".to_owned(), 94.0, 150.0, 0);

    let percent = broker.pending_exit_by_identity("XP", "L").unwrap();
    assert_eq!(percent.quantity, PendingExitQuantity::Fixed(3.0));
    assert_eq!(percent.reserved_quantity, 1.25);
    assert_eq!(
        broker
            .order_book
            .exits()
            .total_reserved_for_entry("L", None),
        2.0
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn percent_exit_with_no_unreserved_quantity_is_rejected() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty_percent("XP1".to_owned(), "L".to_owned(), 95.0, 50.0, 0);
    broker.place_exit_stop_qty_percent("XP2".to_owned(), "L".to_owned(), 94.0, 50.0, 0);

    broker.place_exit_stop_qty_percent("XP3".to_owned(), "L".to_owned(), 93.0, 25.0, 0);

    assert_eq!(pending_exit_ids(&broker), vec!["XP1", "XP2"]);
    assert!(broker.pending_exit_by_identity("XP3", "L").is_none());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_QTY");
}

#[test]
fn mixed_side_both_touched_processes_downside_only() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 0.5, 0);
    broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 110.0, 0.75, 0);

    broker.evaluate_pending_exits(1, 20, 111.0, 94.0);

    assert_eq!(broker.orders[1].id, "XS");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.position_size, 1.5);
    assert_eq!(pending_exit_ids(&broker), vec!["XL"]);
}

#[test]
fn mixed_side_multiple_downside_candidates_fill_in_placement_order() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS1".to_owned(), "L".to_owned(), 95.0, 0.5, 0);
    broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 110.0, 0.25, 0);
    broker.place_exit_stop_qty("XS2".to_owned(), "L".to_owned(), 94.0, 0.75, 0);

    broker.evaluate_pending_exits(1, 20, 111.0, 93.0);

    assert_eq!(broker.orders[1].id, "XS1");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders[2].id, "XS2");
    assert_eq!(broker.orders[2].qty, 0.75);
    assert_eq!(broker.position_size, 0.75);
    assert_eq!(pending_exit_ids(&broker), vec!["XL"]);
}

#[test]
fn mixed_side_partial_then_full_fill_updates_counts_position_and_equity() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 0.5, 0);
    broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 110.0, 1.5, 0);

    broker.evaluate_pending_exits(1, 20, 111.0, 94.0);

    assert_eq!(broker.position_size, 1.5);
    assert_eq!(broker.position.last().unwrap().size, 1.5);
    assert_eq!(broker.position.last().unwrap().avg_price, Some(100.0));
    assert_eq!(broker.closed_trade_count(), 1);
    assert_eq!(broker.open_trade_count(), 1);
    assert_eq!(broker.realized_profit(), -2.5);
    assert_eq!(broker.equity_value(106.0), 100_006.5);
    broker.record_equity(1, 106.0);
    let partial_equity = broker.equity.last().unwrap();
    assert_eq!(partial_equity.cash, 99_847.5);
    assert_eq!(partial_equity.market_value, 159.0);
    assert_eq!(partial_equity.equity, 100_006.5);
    assert_eq!(partial_equity.net_profit, 6.5);
    assert_eq!(pending_exit_ids(&broker), vec!["XL"]);

    broker.evaluate_pending_exits(2, 30, 111.0, 100.0);

    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.position.last().unwrap().size, 0.0);
    assert_eq!(broker.position.last().unwrap().avg_price, None);
    assert_eq!(broker.closed_trade_count(), 2);
    assert_eq!(broker.open_trade_count(), 0);
    assert_eq!(broker.realized_profit(), 12.5);
    assert_eq!(broker.equity_value(106.0), 100_012.5);
    broker.record_equity(2, 106.0);
    let final_equity = broker.equity.last().unwrap();
    assert_eq!(final_equity.cash, 100_012.5);
    assert_eq!(final_equity.market_value, 0.0);
    assert_eq!(final_equity.equity, 100_012.5);
    assert_eq!(final_equity.net_profit, 12.5);
    assert_eq!(pending_exit_count(&broker), 0);
}

#[test]
fn full_close_cancels_remaining_multiple_pending_exits() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS1".to_owned(), "L".to_owned(), 95.0, 0.75, 0);
    broker.place_exit_stop_qty("XS2".to_owned(), "L".to_owned(), 94.0, 0.75, 0);

    broker.close_long("L".to_owned(), 1, 20, 110.0);

    assert_eq!(broker.position_size, 0.0);
    assert_eq!(pending_exit_count(&broker), 0);
}

#[test]
fn omitted_quantity_exit_replaces_explicit_reservation_pool() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 0.5, 0);
    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 94.0, 110.0, 0.75, 0);
    broker.place_exit_trail_price_qty(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );

    broker.place_exit_limit("XFULL".to_owned(), "L".to_owned(), 111.0, 1);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.pending_exit_by_identity("XS", "L").is_none());
    assert!(broker.pending_exit_by_identity("XB", "L").is_none());
    assert!(broker.pending_exit_by_identity("XT", "L").is_none());
    assert_eq!(pending_exit_ids(&broker), vec!["XFULL"]);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XFULL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(111.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn explicit_reservation_after_omitted_quantity_replaces_full_then_appends_supported_reservations() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XFULL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 94.0, 0.5, 1);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.pending_exit_by_identity("XFULL", "L").is_none());
    let first_explicit = broker.pending_exit_by_identity("XS", "L").unwrap();
    assert_eq!(first_explicit.quantity, PendingExitQuantity::Fixed(0.5));
    assert_eq!(first_explicit.reserved_quantity, 0.5);
    assert!(first_explicit.multiple_reservation);

    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 93.0, 110.0, 0.75, 1);
    broker.place_exit_trail_price_qty(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.25,
        1,
    );

    assert_eq!(pending_exit_count(&broker), 3);
    assert_eq!(pending_exit_ids(&broker), vec!["XS", "XB", "XT"]);
    assert_eq!(
        broker
            .order_book
            .exits()
            .total_reserved_for_entry("L", None),
        1.5
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn fixed_quantity_is_stored_on_supported_pending_exit_families() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 1.0, 0);
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 110.0, 1.0, 0);
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_profit_ticks_qty("XP".to_owned(), "L".to_owned(), 10.0, 0.5, 1.0, 0);
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_loss_ticks_qty("XL".to_owned(), "L".to_owned(), 5.0, 0.5, 1.0, 0);
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 1.0, 0);
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price_qty(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.0,
        0,
    );
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_points_qty(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPointsExitSpec {
            activation_ticks: 10.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.0,
        0,
    );
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );
}

#[test]
fn percent_quantity_resolves_on_supported_pending_exit_families() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty_percent("XS".to_owned(), "L".to_owned(), 95.0, 50.0, 0);
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_limit_qty_percent("XL".to_owned(), "L".to_owned(), 110.0, 100.0, 0);
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(2.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_profit_ticks_qty_percent("XP".to_owned(), "L".to_owned(), 10.0, 0.5, 50.0, 0);
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_loss_ticks_qty_percent("XL".to_owned(), "L".to_owned(), 5.0, 0.5, 50.0, 0);
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty_percent("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 50.0, 0);
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price_qty_percent(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        50.0,
        0,
    );
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );

    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_points_qty_percent(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPointsExitSpec {
            activation_ticks: 10.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        50.0,
        0,
    );
    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(1.0)
    );
}

#[test]
fn percent_quantity_larger_than_position_closes_full_position() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit_qty_percent("XL".to_owned(), "L".to_owned(), 110.0, 150.0, 0);

    assert_eq!(
        broker.pending_exit().unwrap().quantity,
        PendingExitQuantity::Fixed(3.0)
    );

    broker.evaluate_pending_exits(1, 20, 111.0, 100.0);

    assert_eq!(broker.orders[1].qty, 2.0);
    assert_eq!(broker.trades[0].qty, 2.0);
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.entry_id, None);
}

#[test]
fn unchanged_repeated_quantity_keeps_original_eligibility_bar() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_stop_qty("XL".to_owned(), "L".to_owned(), 95.0, 1.0, 0);
    broker.place_exit_stop_qty("XL".to_owned(), "L".to_owned(), 95.0, 1.0, 1);

    assert_eq!(broker.pending_exit().unwrap().last_update_bar_index, 0);
}

#[test]
fn changed_repeated_quantity_replaces_pending_exit() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_stop_qty("XL".to_owned(), "L".to_owned(), 95.0, 1.0, 0);
    broker.place_exit_stop_qty("XL".to_owned(), "L".to_owned(), 95.0, 0.5, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Fixed(0.5),
            reserved_quantity: 0.5,
            multiple_reservation: true,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        })
    );
}

#[test]
fn invalid_fixed_quantity_records_diagnostic_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XL".to_owned(), "L".to_owned(), 95.0, 1.0, 0);
    let original_pending_exit = broker.pending_exit().cloned();

    broker.place_exit_stop_qty("BAD".to_owned(), "L".to_owned(), 94.0, 0.0, 1);
    broker.place_exit_limit_qty("BAD2".to_owned(), "L".to_owned(), 110.0, f64::NAN, 2);

    assert_eq!(broker.pending_exit().cloned(), original_pending_exit);
    assert_eq!(broker.diagnostics.len(), 2);
    assert!(
        broker
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code == "E_STRATEGY_EXIT_QTY")
    );
}

#[test]
fn invalid_percent_quantity_records_diagnostic_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty_percent("XL".to_owned(), "L".to_owned(), 95.0, 50.0, 0);
    let original_pending_exit = broker.pending_exit().cloned();

    broker.place_exit_stop_qty_percent("BAD".to_owned(), "L".to_owned(), 94.0, 0.0, 1);
    broker.place_exit_limit_qty_percent("BAD2".to_owned(), "L".to_owned(), 110.0, f64::NAN, 2);

    assert_eq!(broker.pending_exit().cloned(), original_pending_exit);
    assert_eq!(broker.diagnostics.len(), 2);
    assert!(
        broker
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code == "E_STRATEGY_EXIT_QTY_PERCENT")
    );
}

#[test]
fn percent_quantity_while_flat_is_noop_before_percent_resolution() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_exit_stop_qty_percent("XL".to_owned(), "L".to_owned(), 95.0, f64::NAN, 0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn percent_quantity_mismatched_entry_is_noop_before_percent_resolution() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("KEEP".to_owned(), "L".to_owned(), 95.0, 0);
    let original_pending_exit = broker.pending_exit().cloned();

    broker.place_exit_stop_qty_percent("BAD".to_owned(), "OTHER".to_owned(), 94.0, f64::NAN, 1);

    assert_eq!(broker.pending_exit().cloned(), original_pending_exit);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_long_cancels_matching_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.close_long("L".to_owned(), 1, 20, 110.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 1);
}

#[test]
fn close_long_metadata_is_recorded_in_internal_closed_trade_metrics() {
    let mut broker = broker_with_long_entry();
    let metadata = close_metadata("close");

    broker.with_next_close_metadata(metadata.clone(), |broker| {
        broker.close_long("L".to_owned(), 1, 20, 110.0);
    });

    assert_eq!(broker.trades.len(), 1);
    assert_eq!(
        broker
            .closed_trade_metrics
            .first()
            .map(|metrics| &metrics.close_metadata),
        Some(&metadata)
    );
    assert_eq!(broker.result().trades.len(), 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_all_metadata_is_recorded_for_each_internal_closed_trade_metric() {
    let mut broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    );
    assert!(broker.entry_long("L1".to_owned(), 0, 10, 100.0, 1.0));
    assert!(broker.entry_long("L2".to_owned(), 1, 20, 110.0, 2.0));
    let metadata = close_metadata("close all");

    broker.with_next_close_metadata(metadata.clone(), |broker| {
        broker.close_all_long(2, 30, 120.0);
    });

    assert_eq!(broker.trades.len(), 2);
    assert_eq!(broker.closed_trade_metrics.len(), 2);
    assert!(
        broker
            .closed_trade_metrics
            .iter()
            .all(|metrics| metrics.close_metadata == metadata)
    );
    assert_eq!(broker.result().trades.len(), 2);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn entry_metadata_records_internal_order_fill_alert_without_public_output() {
    let mut broker = BrokerState::new(100_000.0);
    let metadata = order_metadata("entry", false);

    assert!(broker.entry_long_with_metadata("L".to_owned(), 1, 20, 100.0, 2.0, metadata));

    assert_eq!(
        broker.order_fill_alerts,
        vec![StrategyOrderFillAlertEvent {
            id: "L".to_owned(),
            bar_index: 1,
            time: 20,
            direction: "strategy.long".to_owned(),
            qty: 2.0,
            price: 100.0,
            entry_id: Some("L".to_owned()),
            exit_id: None,
            message: "entry alert".to_owned(),
        }]
    );
    assert_eq!(broker.result().orders.len(), 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn disabled_entry_metadata_suppresses_internal_order_fill_alert() {
    let mut broker = BrokerState::new(100_000.0);
    let metadata = order_metadata("entry", true);

    assert!(broker.entry_long_with_metadata("L".to_owned(), 1, 20, 100.0, 2.0, metadata));

    assert!(broker.order_fill_alerts.is_empty());
    assert_eq!(broker.result().orders.len(), 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_metadata_records_internal_order_fill_alerts() {
    let mut close_broker = broker_with_long_entry();
    close_broker.order_fill_alerts.clear();
    let metadata = order_metadata("close", false);

    close_broker.with_next_close_metadata(metadata, |broker| {
        broker.close_long("L".to_owned(), 1, 20, 110.0);
    });

    assert_eq!(
        close_broker.order_fill_alerts,
        vec![StrategyOrderFillAlertEvent {
            id: "L".to_owned(),
            bar_index: 1,
            time: 20,
            direction: "strategy.close".to_owned(),
            qty: 2.0,
            price: 110.0,
            entry_id: Some("L".to_owned()),
            exit_id: Some("L".to_owned()),
            message: "close alert".to_owned(),
        }]
    );

    let mut close_all_broker = BrokerState::new_with_account_settings_and_pyramiding(
        100_000.0,
        None,
        0.0,
        0.0,
        StrategyMarginSetting::default(),
        StrategyMarginSetting::default(),
        2,
    );
    assert!(close_all_broker.entry_long("L1".to_owned(), 0, 10, 100.0, 1.0));
    assert!(close_all_broker.entry_long("L2".to_owned(), 1, 20, 110.0, 2.0));
    close_all_broker.order_fill_alerts.clear();
    let metadata = order_metadata("close all", false);

    close_all_broker.with_next_close_metadata(metadata, |broker| {
        broker.close_all_long(2, 30, 120.0);
    });

    assert_eq!(
        close_all_broker
            .order_fill_alerts
            .iter()
            .map(|event| (
                event.id.as_str(),
                event.direction.as_str(),
                event.qty,
                event.message.as_str()
            ))
            .collect::<Vec<_>>(),
        vec![
            ("L1", "strategy.close_all", 1.0, "close all alert"),
            ("L2", "strategy.close_all", 2.0, "close all alert"),
        ]
    );
    assert_eq!(close_all_broker.result().trades.len(), 2);
    assert!(close_all_broker.diagnostics.is_empty());
}

#[test]
fn exit_metadata_records_leg_specific_internal_order_fill_alert_messages() {
    let mut profit_broker = broker_with_long_entry();
    profit_broker.order_fill_alerts.clear();
    let metadata = exit_alert_metadata("exit", false);
    profit_broker.with_next_exit_metadata(metadata, |broker| {
        broker.place_exit_limit("XP".to_owned(), "L".to_owned(), 110.0, 0);
    });

    profit_broker.evaluate_pending_exits(1, 20, 110.0, 100.0);

    assert_eq!(profit_broker.order_fill_alerts.len(), 1);
    assert_eq!(
        profit_broker.order_fill_alerts[0].message,
        "exit profit alert"
    );
    assert_eq!(
        profit_broker.order_fill_alerts[0].exit_id,
        Some("XP".to_owned())
    );
    assert_eq!(profit_broker.result().trades.len(), 1);

    let mut loss_broker = broker_with_long_entry();
    loss_broker.order_fill_alerts.clear();
    let metadata = exit_alert_metadata("exit", false);
    loss_broker.with_next_exit_metadata(metadata, |broker| {
        broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);
    });

    loss_broker.evaluate_pending_exits(1, 20, 100.0, 95.0);

    assert_eq!(loss_broker.order_fill_alerts.len(), 1);
    assert_eq!(loss_broker.order_fill_alerts[0].message, "exit loss alert");
    assert_eq!(
        loss_broker.order_fill_alerts[0].exit_id,
        Some("XS".to_owned())
    );
    assert_eq!(loss_broker.result().trades.len(), 1);
}

#[test]
fn disabled_exit_metadata_suppresses_internal_order_fill_alert() {
    let mut broker = broker_with_long_entry();
    broker.order_fill_alerts.clear();
    let metadata = exit_alert_metadata("exit", true);
    broker.with_next_exit_metadata(metadata, |broker| {
        broker.place_exit_limit("XP".to_owned(), "L".to_owned(), 110.0, 0);
    });

    broker.evaluate_pending_exits(1, 20, 110.0, 100.0);

    assert!(broker.order_fill_alerts.is_empty());
    assert_eq!(broker.result().trades.len(), 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_long_fixed_quantity_reduces_position_and_keeps_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.close_long_qty("L".to_owned(), 1, 20, 110.0, 0.75);

    assert_eq!(pending_exit_count(&broker), 1);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].qty, 0.75);
    assert_eq!(broker.trades[0].profit, 7.5);
    assert_eq!(broker.position_size, 1.25);
    assert_eq!(broker.avg_price, 100.0);
    assert_eq!(broker.trade_ledger.net_position().signed_size, 1.25);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_long_fixed_quantity_clamps_full_and_cancels_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.close_long_qty("L".to_owned(), 1, 20, 110.0, 5.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].qty, 2.0);
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.trade_ledger.net_position(), NetPosition::default());
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_long_invalid_fixed_quantity_preserves_position_and_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.close_long_qty("L".to_owned(), 1, 20, 110.0, f64::NAN);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 2.0);
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_CLOSE_QTY");
}

#[test]
fn close_long_percent_quantity_reduces_position_and_keeps_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.close_long_qty_percent("L".to_owned(), 1, 20, 110.0, 25.0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].qty, 0.5);
    assert_eq!(broker.trades[0].profit, 5.0);
    assert_eq!(broker.position_size, 1.5);
    assert_eq!(broker.avg_price, 100.0);
    assert_eq!(broker.trade_ledger.net_position().signed_size, 1.5);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_long_percent_quantity_clamps_full_and_cancels_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.close_long_qty_percent("L".to_owned(), 1, 20, 110.0, 150.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].qty, 2.0);
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.trade_ledger.net_position(), NetPosition::default());
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_long_invalid_percent_quantity_preserves_position_and_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.close_long_qty_percent("L".to_owned(), 1, 20, 110.0, f64::NAN);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 2.0);
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_CLOSE_QTY_PERCENT");
}

#[test]
fn mismatched_entry_id_is_noop_without_pending_state() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_stop("XL".to_owned(), "OTHER".to_owned(), 95.0, 0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn limit_with_mismatched_entry_is_noop_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_limit("XL".to_owned(), "OTHER".to_owned(), 110.0, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn repeated_entry_noop_leaves_pending_exit_untouched() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.entry_long("L2".to_owned(), 1, 20, 105.0, 1.0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
}

#[test]
fn pending_stop_is_not_eligible_on_creation_bar() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.evaluate_pending_exits(0, 10, 100.0, 90.0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 2.0);
}

#[test]
fn pending_stop_fills_on_later_crossing_bar() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);

    broker.evaluate_pending_exits(1, 20, 100.0, 94.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "XL");
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].price, 95.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].id, "L");
    assert_eq!(broker.trades[0].exit_bar_index, 1);
    assert_eq!(broker.trades[0].exit_price, 95.0);
    assert_eq!(broker.trades[0].profit, -10.0);
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.position.last().unwrap().avg_price, None);
}

#[test]
fn unchanged_repeated_exit_keeps_original_eligibility_bar() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 1);

    broker.evaluate_pending_exits(1, 20, 100.0, 94.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 95.0);
}

#[test]
fn changed_repeated_exit_replaces_price_and_delays_eligibility() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 95.0, 0);
    broker.place_exit_stop("XL".to_owned(), "L".to_owned(), 90.0, 1);

    broker.evaluate_pending_exits(1, 20, 100.0, 89.0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.trades.is_empty());

    broker.evaluate_pending_exits(2, 30, 100.0, 89.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 90.0);
}

#[test]
fn pending_limit_fills_on_later_crossing_bar() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit("XL".to_owned(), "L".to_owned(), 110.0, 0);

    broker.evaluate_pending_exits(1, 20, 111.0, 100.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].price, 110.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 110.0);
    assert_eq!(broker.trades[0].profit, 20.0);
}

#[test]
fn pending_stop_partial_quantity_reduces_position() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XL".to_owned(), "L".to_owned(), 95.0, 0.75, 0);

    broker.evaluate_pending_exits(1, 20, 100.0, 94.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.orders[1].qty, 0.75);
    assert_eq!(broker.trades[0].qty, 0.75);
    assert_eq!(broker.trades[0].profit, -3.75);
    assert_eq!(broker.position_size, 1.25);
    assert_eq!(broker.avg_price, 100.0);
    assert_eq!(broker.entry_id.as_deref(), Some("L"));
    assert_eq!(broker.entry_bar_index, Some(0));
    assert_eq!(broker.entry_time, Some(10));
    assert_eq!(broker.position.last().unwrap().size, 1.25);
    assert_eq!(broker.position.last().unwrap().avg_price, Some(100.0));
    assert_eq!(broker.open_trade_count(), 1);
    assert_eq!(broker.closed_trade_count(), 1);
}

#[test]
fn pending_limit_partial_quantity_reduces_position() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 110.0, 0.5, 0);

    broker.evaluate_pending_exits(1, 20, 111.0, 100.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.trades[0].qty, 0.5);
    assert_eq!(broker.trades[0].profit, 5.0);
    assert_eq!(broker.position_size, 1.5);
    assert_eq!(broker.position.last().unwrap().avg_price, Some(100.0));
}

#[test]
fn fixed_quantity_larger_than_position_closes_full_position() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 110.0, 5.0, 0);

    broker.evaluate_pending_exits(1, 20, 111.0, 100.0);

    assert_eq!(broker.orders[1].qty, 2.0);
    assert_eq!(broker.trades[0].qty, 2.0);
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(broker.avg_price, 0.0);
    assert_eq!(broker.entry_id, None);
    assert_eq!(broker.open_trade_count(), 0);
    assert_eq!(broker.position.last().unwrap().avg_price, None);
}

#[test]
fn partial_fill_then_final_exit_closes_open_trade_count() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("X1".to_owned(), "L".to_owned(), 95.0, 0.5, 0);
    broker.evaluate_pending_exits(1, 20, 100.0, 94.0);

    assert_eq!(broker.open_trade_count(), 1);
    assert_eq!(broker.closed_trade_count(), 1);

    broker.place_exit_limit("X2".to_owned(), "L".to_owned(), 110.0, 2);
    broker.evaluate_pending_exits(3, 40, 111.0, 100.0);

    assert_eq!(broker.open_trade_count(), 0);
    assert_eq!(broker.closed_trade_count(), 2);
    assert_eq!(broker.trades[1].qty, 1.5);
    assert_eq!(broker.trades[1].profit, 15.0);
}

#[test]
fn partial_fill_splits_realized_and_open_profit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 110.0, 0.5, 0);
    broker.evaluate_pending_exits(1, 20, 111.0, 100.0);

    assert_eq!(broker.realized_profit(), 5.0);
    assert_eq!(broker.open_profit(106.0), 9.0);
    assert_eq!(broker.equity_value(106.0), 100_014.0);

    broker.record_equity(1, 106.0);
    let equity = broker.equity.last().unwrap();
    assert_eq!(equity.cash, 99_855.0);
    assert_eq!(equity.market_value, 159.0);
    assert_eq!(equity.equity, 100_014.0);
    assert_eq!(equity.net_profit, 14.0);
}

#[test]
fn profit_ticks_create_limit_from_average_entry_price() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_profit_ticks("XP".to_owned(), "L".to_owned(), 10.0, 0.5, 0);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XP".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(105.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
}

#[test]
fn loss_ticks_create_stop_from_average_entry_price() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_loss_ticks("XL".to_owned(), "L".to_owned(), 5.0, 0.5, 0);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(97.5),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
}

#[test]
fn place_exit_bracket_records_pending_bracket() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XB".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Bracket {
                downside: 95.0,
                upside: 110.0,
            },
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn bracket_tick_helpers_resolve_prices_from_average_entry_price() {
    let mut broker = broker_with_long_entry();

    let downside = broker
        .exit_loss_price_from_ticks(5.0, 0.5)
        .expect("loss ticks should resolve");
    let upside = broker
        .exit_profit_price_from_ticks(10.0, 0.5)
        .expect("profit ticks should resolve");
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), downside, upside, 0);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XB".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Bracket {
                downside: 97.5,
                upside: 105.0,
            },
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn place_exit_trail_price_records_pending_trailing_exit() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XT".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: trailing_price_trigger(105.0, 2.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn place_exit_trail_points_records_entry_relative_activation() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_points("XT".to_owned(), "L".to_owned(), 10.0, 4.0, 0.5, 0);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XT".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: trailing_points_trigger(10.0, 105.0, 2.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn trailing_while_flat_is_noop_without_pending_state() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn trailing_with_mismatched_entry_is_noop_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_trail_price("XT".to_owned(), "OTHER".to_owned(), 105.0, 4.0, 0.5, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn invalid_trailing_activation_price_records_diagnostic_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), f64::NAN, 4.0, 0.5, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_PRICE");
}

#[test]
fn invalid_trailing_offset_ticks_record_diagnostic_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 0.0, 0.5, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_TICKS");
}

#[test]
fn unchanged_repeated_trailing_keeps_original_eligibility_bar() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 1);

    assert_eq!(broker.pending_exit().unwrap().last_update_bar_index, 0);
}

#[test]
fn unchanged_repeated_trailing_preserves_active_state() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);
    let pending = broker.pending_exit_mut().expect("trailing pending exit");
    let PendingExitTrigger::Trailing(trailing) = &mut pending.trigger else {
        panic!("expected trailing pending exit");
    };
    trailing.state = PendingTrailingState::Active { stop_price: 103.0 };

    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XT".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Trailing(PendingTrailingExit {
                spec: PendingTrailingSpec {
                    activation: PendingTrailingActivation::Price(105.0),
                    offset_price_distance: 2.0,
                },
                state: PendingTrailingState::Active { stop_price: 103.0 },
            }),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
}

#[test]
fn changed_repeated_trailing_replaces_spec_and_delays_eligibility() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 106.0, 4.0, 0.5, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XT".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: trailing_price_trigger(106.0, 2.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        })
    );
}

#[test]
fn omitted_quantity_trailing_with_new_identity_replaces_and_resets_eligibility() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price("XT1".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);
    broker.place_exit_trail_price("XT2".to_owned(), "L".to_owned(), 106.0, 6.0, 0.5, 1);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.pending_exit_by_identity("XT1", "L").is_none());
    assert_eq!(pending_exit_ids(&broker), vec!["XT2"]);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XT2".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: trailing_price_trigger(106.0, 3.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        })
    );

    broker.evaluate_pending_exits(1, 20, 110.0, 100.0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert_eq!(
        broker.pending_exit().unwrap().trigger,
        trailing_price_trigger(106.0, 3.0)
    );
    assert!(broker.trades.is_empty());
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_long_cancels_matching_trailing_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);

    broker.close_long("L".to_owned(), 1, 20, 110.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 1);
}

#[test]
fn multiple_fixed_qty_trailing_exits_reserve_and_activate_independently() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );
    broker.place_exit_trail_price_qty(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 110.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.0,
        0,
    );

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(pending_exit_ids(&broker), vec!["XT1", "XT2"]);
    assert_eq!(
        broker
            .pending_exit_by_identity("XT1", "L")
            .expect("XT1")
            .reserved_quantity,
        0.5
    );
    assert_eq!(
        broker
            .pending_exit_by_identity("XT2", "L")
            .expect("XT2")
            .reserved_quantity,
        1.0
    );

    broker.evaluate_pending_exits(1, 20, 106.0, 104.0);

    assert_active_trailing_stop_by_id(&broker, "XT1", 104.0);
    assert_eq!(
        broker
            .pending_exit_by_identity("XT2", "L")
            .expect("XT2")
            .trigger,
        trailing_price_trigger(110.0, 2.0)
    );
    assert!(broker.trades.is_empty());
}

#[test]
fn multiple_fixed_qty_trailing_exits_fill_in_placement_order() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );
    broker.place_exit_trail_price_qty(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 6.0,
            mintick: 0.5,
        },
        1.0,
        0,
    );
    broker.evaluate_pending_exits(1, 20, 110.0, 109.0);

    broker.evaluate_pending_exits(2, 30, 115.0, 107.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.orders[1].id, "XT1");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders[1].price, 108.0);
    assert_eq!(broker.orders[2].id, "XT2");
    assert_eq!(broker.orders[2].qty, 1.0);
    assert_eq!(broker.orders[2].price, 107.0);
    assert_eq!(broker.position_size, 0.5);
}

#[test]
fn fixed_qty_trailing_replacement_releases_only_that_reservation() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );
    broker.place_exit_trail_price_qty(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 106.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.0,
        0,
    );

    broker.place_exit_trail_price_qty(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 107.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.0,
        1,
    );

    assert_eq!(pending_exit_ids(&broker), vec!["XT1", "XT2"]);
    assert_eq!(
        broker
            .pending_exit_by_identity("XT1", "L")
            .expect("XT1")
            .reserved_quantity,
        1.0
    );
    assert_eq!(
        broker
            .pending_exit_by_identity("XT2", "L")
            .expect("XT2")
            .reserved_quantity,
        1.0
    );
}

#[test]
fn fixed_qty_trailing_reservation_clamps_to_remaining_unreserved_quantity() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.5,
        0,
    );
    broker.place_exit_trail_price_qty(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 106.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.0,
        0,
    );

    assert_eq!(
        broker
            .pending_exit_by_identity("XT2", "L")
            .expect("XT2")
            .reserved_quantity,
        0.5
    );
}

#[test]
fn fixed_qty_trailing_with_no_unreserved_quantity_is_rejected() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.0,
        0,
    );
    broker.place_exit_trail_price_qty(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 106.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.0,
        0,
    );
    broker.place_exit_trail_price_qty(
        "XT3".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 107.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );

    assert_eq!(pending_exit_count(&broker), 2);
    assert!(broker.pending_exit_by_identity("XT3", "L").is_none());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_QTY");
}

#[test]
fn full_fixed_qty_trailing_fill_clears_remaining_pending_exits() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.5,
        0,
    );
    broker.place_exit_trail_price_qty(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 6.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );
    broker.evaluate_pending_exits(1, 20, 110.0, 109.0);

    broker.evaluate_pending_exits(2, 30, 115.0, 107.0);

    assert_eq!(broker.position_size, 0.0);
    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 2);
}

#[test]
fn invalid_fixed_qty_trailing_replacement_preserves_existing_pending_trailing_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price_qty(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );
    broker.place_exit_trail_price_qty(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 106.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );

    broker.place_exit_trail_price_qty(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 107.0,
            offset_ticks: 0.0,
            mintick: 0.5,
        },
        1.0,
        1,
    );

    assert_eq!(pending_exit_ids(&broker), vec!["XT1", "XT2"]);
    assert_eq!(
        broker
            .pending_exit_by_identity("XT1", "L")
            .expect("XT1")
            .trigger,
        trailing_price_trigger(105.0, 2.0)
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_TICKS");
}

#[test]
fn unfilled_fixed_qty_trailing_exits_ratchet_and_persist_state() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );
    broker.place_exit_trail_price_qty(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 6.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );
    broker.evaluate_pending_exits(1, 20, 110.0, 109.0);

    broker.evaluate_pending_exits(2, 30, 113.0, 109.0);

    assert_active_trailing_stop_by_id(&broker, "XT1", 111.0);
    assert_active_trailing_stop_by_id(&broker, "XT2", 110.0);
    assert!(broker.trades.is_empty());
}

#[test]
fn two_percent_trailing_exits_reserve_expected_absolute_quantities() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty_percent(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        25.0,
        0,
    );
    broker.place_exit_trail_price_qty_percent(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 6.0,
            mintick: 0.5,
        },
        50.0,
        0,
    );

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(
        broker
            .pending_exit_by_identity("XT1", "L")
            .expect("XT1")
            .reserved_quantity,
        0.5
    );
    assert_eq!(
        broker
            .pending_exit_by_identity("XT2", "L")
            .expect("XT2")
            .reserved_quantity,
        1.0
    );
}

#[test]
fn percent_and_fixed_trailing_exits_share_reservation_pool() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty(
        "XF".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.75,
        0,
    );
    broker.place_exit_trail_price_qty_percent(
        "XP".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 6.0,
            mintick: 0.5,
        },
        75.0,
        0,
    );

    assert_eq!(
        broker
            .pending_exit_by_identity("XP", "L")
            .expect("XP")
            .reserved_quantity,
        1.25
    );
}

#[test]
fn percent_trailing_replacement_releases_old_reservation_first() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty_percent(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        25.0,
        0,
    );
    broker.place_exit_trail_price_qty_percent(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 6.0,
            mintick: 0.5,
        },
        25.0,
        0,
    );

    broker.place_exit_trail_price_qty_percent(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 106.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        75.0,
        1,
    );

    assert_eq!(
        broker
            .pending_exit_by_identity("XT1", "L")
            .expect("XT1")
            .reserved_quantity,
        1.5
    );
    assert_eq!(
        broker
            .pending_exit_by_identity("XT2", "L")
            .expect("XT2")
            .reserved_quantity,
        0.5
    );
}

#[test]
fn over_100_percent_trailing_reserves_remaining_unreserved_quantity() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty(
        "XF".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.75,
        0,
    );
    broker.place_exit_trail_price_qty_percent(
        "XP".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 6.0,
            mintick: 0.5,
        },
        150.0,
        0,
    );

    assert_eq!(
        broker
            .pending_exit_by_identity("XP", "L")
            .expect("XP")
            .reserved_quantity,
        1.25
    );
}

#[test]
fn percent_trailing_with_no_unreserved_quantity_is_rejected() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_trail_price_qty_percent(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        50.0,
        0,
    );
    broker.place_exit_trail_price_qty_percent(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 6.0,
            mintick: 0.5,
        },
        50.0,
        0,
    );
    broker.place_exit_trail_price_qty_percent(
        "XT3".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 8.0,
            mintick: 0.5,
        },
        25.0,
        0,
    );

    assert_eq!(pending_exit_count(&broker), 2);
    assert!(broker.pending_exit_by_identity("XT3", "L").is_none());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_QTY");
}

#[test]
fn invalid_percent_trailing_replacement_preserves_existing_pending_trailing_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price_qty_percent(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        25.0,
        0,
    );
    broker.place_exit_trail_price_qty_percent(
        "XT2".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 6.0,
            mintick: 0.5,
        },
        25.0,
        0,
    );

    broker.place_exit_trail_price_qty_percent(
        "XT1".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 106.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.0,
        1,
    );

    assert_eq!(pending_exit_ids(&broker), vec!["XT1", "XT2"]);
    assert_eq!(
        broker
            .pending_exit_by_identity("XT1", "L")
            .expect("XT1")
            .trigger,
        trailing_price_trigger(105.0, 2.0)
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_QTY_PERCENT");
}

#[test]
fn invalid_bracket_downside_price_records_diagnostic_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), f64::NAN, 110.0, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_PRICE");
}

#[test]
fn invalid_bracket_upside_price_records_diagnostic_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit("XL".to_owned(), "L".to_owned(), 110.0, 0);

    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, f64::INFINITY, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(110.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_PRICE");
}

#[test]
fn invalid_bracket_ticks_record_diagnostic_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    let price = broker.exit_profit_price_from_ticks(0.0, 0.01);

    assert_eq!(price, None);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_TICKS");
}

#[test]
fn invalid_bracket_mintick_records_diagnostic_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit("XL".to_owned(), "L".to_owned(), 110.0, 0);

    let price = broker.exit_loss_price_from_ticks(5.0, f64::NAN);

    assert_eq!(price, None);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(110.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_MINTICK");
}

#[test]
fn bracket_while_flat_is_noop_without_pending_state() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn stop_profit_bracket_while_flat_is_noop_without_pending_state() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_exit_bracket_stop_profit_ticks(
        "XB".to_owned(),
        "L".to_owned(),
        StopProfitBracketSpec {
            stop_price: 95.0,
            profit_ticks: 10.0,
            mintick: 0.5,
        },
        0,
    );

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn loss_limit_bracket_while_flat_is_noop_without_pending_state() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_exit_bracket_loss_limit_ticks(
        "XB".to_owned(),
        "L".to_owned(),
        LossLimitBracketSpec {
            loss_ticks: 10.0,
            limit_price: 110.0,
            mintick: 0.5,
        },
        0,
    );

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn loss_profit_bracket_while_flat_is_noop_without_pending_state() {
    let mut broker = BrokerState::new(100_000.0);

    broker.place_exit_bracket_loss_profit_ticks(
        "XB".to_owned(),
        "L".to_owned(),
        LossProfitBracketSpec {
            loss_ticks: 10.0,
            profit_ticks: 12.0,
            mintick: 0.5,
        },
        0,
    );

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn bracket_with_mismatched_entry_is_noop_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_bracket("XB".to_owned(), "OTHER".to_owned(), 95.0, 110.0, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn stop_profit_bracket_with_mismatched_entry_is_noop_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_bracket_stop_profit_ticks(
        "XB".to_owned(),
        "OTHER".to_owned(),
        StopProfitBracketSpec {
            stop_price: 95.0,
            profit_ticks: 10.0,
            mintick: 0.5,
        },
        1,
    );

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn loss_limit_bracket_with_mismatched_entry_is_noop_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_bracket_loss_limit_ticks(
        "XB".to_owned(),
        "OTHER".to_owned(),
        LossLimitBracketSpec {
            loss_ticks: 10.0,
            limit_price: 110.0,
            mintick: 0.5,
        },
        1,
    );

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn loss_profit_bracket_with_mismatched_entry_is_noop_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_bracket_loss_profit_ticks(
        "XB".to_owned(),
        "OTHER".to_owned(),
        LossProfitBracketSpec {
            loss_ticks: 10.0,
            profit_ticks: 12.0,
            mintick: 0.5,
        },
        1,
    );

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn unchanged_repeated_bracket_keeps_original_eligibility_bar() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 0);
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 1);

    assert_eq!(broker.pending_exit().unwrap().last_update_bar_index, 0);
}

#[test]
fn changed_repeated_bracket_replaces_price_and_delays_eligibility() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 0);
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 94.0, 110.0, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XB".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Bracket {
                downside: 94.0,
                upside: 110.0,
            },
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        })
    );
}

#[test]
fn omitted_quantity_bracket_with_new_identity_replaces_instead_of_appending() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_bracket("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 0);
    broker.place_exit_bracket("XB2".to_owned(), "L".to_owned(), 94.0, 111.0, 1);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.pending_exit_by_identity("XB1", "L").is_none());
    assert_eq!(pending_exit_ids(&broker), vec!["XB2"]);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XB2".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Bracket {
                downside: 94.0,
                upside: 111.0,
            },
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn single_trigger_and_bracket_replace_each_other_and_reset_eligibility() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XB".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Bracket {
                downside: 95.0,
                upside: 110.0,
            },
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        })
    );

    broker.place_exit_limit("XL".to_owned(), "L".to_owned(), 111.0, 2);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(111.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 2,
            metadata: StrategyExitMetadata::default(),
        })
    );
}

#[test]
fn pending_bracket_is_not_eligible_on_creation_bar() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 0);

    broker.evaluate_pending_exits(0, 10, 111.0, 94.0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 2.0);
}

#[test]
fn pending_bracket_downside_only_hit_fills_at_downside_price() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 0);

    broker.evaluate_pending_exits(1, 20, 109.0, 94.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "XB");
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].price, 95.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 95.0);
    assert_eq!(broker.trades[0].profit, -10.0);
    assert_eq!(broker.position_size, 0.0);
}

#[test]
fn pending_bracket_upside_only_hit_fills_at_upside_price() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 0);

    broker.evaluate_pending_exits(1, 20, 111.0, 96.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "XB");
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].price, 110.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 110.0);
    assert_eq!(broker.trades[0].profit, 20.0);
    assert_eq!(broker.position_size, 0.0);
}

#[test]
fn pending_bracket_both_hit_fills_at_downside_price_without_diagnostic() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 0);

    broker.evaluate_pending_exits(1, 20, 111.0, 94.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].price, 95.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 95.0);
    assert_eq!(broker.trades[0].profit, -10.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn pending_bracket_no_hit_remains_pending() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket("XB".to_owned(), "L".to_owned(), 95.0, 110.0, 0);

    broker.evaluate_pending_exits(1, 20, 109.0, 96.0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 2.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn multiple_fixed_qty_brackets_reserve_and_fill_downside_in_placement_order() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 0.75, 0);
    broker.place_exit_bracket_qty("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 0.5, 0);

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(pending_exit_ids(&broker), vec!["XB1", "XB2"]);

    broker.evaluate_pending_exits(1, 20, 109.0, 94.0);

    assert_eq!(broker.orders[1].id, "XB1");
    assert_eq!(broker.orders[1].qty, 0.75);
    assert_eq!(broker.orders[1].price, 95.0);
    assert_eq!(broker.orders[2].id, "XB2");
    assert_eq!(broker.orders[2].qty, 0.5);
    assert_eq!(broker.orders[2].price, 96.0);
    assert_eq!(broker.trades.len(), 2);
    assert_eq!(broker.position_size, 0.75);
    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn multiple_fixed_qty_brackets_reserve_and_fill_upside_in_placement_order() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 0.5, 0);
    broker.place_exit_bracket_qty("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 0.75, 0);

    broker.evaluate_pending_exits(1, 20, 112.0, 97.0);

    assert_eq!(broker.orders[1].id, "XB1");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders[1].price, 110.0);
    assert_eq!(broker.orders[2].id, "XB2");
    assert_eq!(broker.orders[2].qty, 0.75);
    assert_eq!(broker.orders[2].price, 111.0);
    assert_eq!(broker.trades.len(), 2);
    assert_eq!(broker.position_size, 0.75);
    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn fixed_qty_bracket_replacement_releases_only_that_reservation() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 1.0, 0);
    broker.place_exit_bracket_qty("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 0.5, 0);

    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), 94.0, 109.0, 1.5, 1);

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(pending_exit_ids(&broker), vec!["XB1", "XB2"]);
    let replaced = broker
        .pending_exit_by_identity("XB1", "L")
        .expect("replacement should exist");
    assert_eq!(
        replaced.trigger,
        PendingExitTrigger::Bracket {
            downside: 94.0,
            upside: 109.0,
        }
    );
    assert_eq!(replaced.quantity, PendingExitQuantity::Fixed(1.5));
    assert_eq!(replaced.reserved_quantity, 1.5);
    assert_eq!(replaced.last_update_bar_index, 1);
    assert_eq!(
        broker
            .pending_exit_by_identity("XB2", "L")
            .expect("other bracket should remain")
            .reserved_quantity,
        0.5
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn fixed_qty_bracket_reservation_clamps_to_remaining_unreserved_quantity() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 1.5, 0);
    broker.place_exit_bracket_qty("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 1.0, 0);

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(
        broker
            .pending_exit_by_identity("XB2", "L")
            .expect("clamped bracket should exist")
            .reserved_quantity,
        0.5
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn fixed_qty_bracket_with_no_unreserved_quantity_is_rejected() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 2.0, 0);
    broker.place_exit_bracket_qty("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 0.5, 0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.pending_exit_by_identity("XB2", "L").is_none());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_QTY");
}

#[test]
fn full_fixed_qty_bracket_fill_clears_remaining_pending_exits() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 1.0, 0);
    broker.place_exit_bracket_qty("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 1.0, 0);

    broker.evaluate_pending_exits(1, 20, 109.0, 94.0);

    assert_eq!(broker.trades.len(), 2);
    assert_eq!(broker.position_size, 0.0);
    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn invalid_fixed_qty_bracket_replacement_preserves_existing_pending_bracket() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 1.0, 0);

    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), f64::NAN, 109.0, 1.5, 1);

    assert_eq!(pending_exit_count(&broker), 1);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XB1".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Bracket {
                downside: 95.0,
                upside: 110.0,
            },
            quantity: PendingExitQuantity::Fixed(1.0),
            reserved_quantity: 1.0,
            multiple_reservation: true,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_PRICE");
}

#[test]
fn fixed_qty_bracket_shares_reservation_pool_with_single_trigger() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 1.0, 0);

    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 94.0, 110.0, 1.0, 1);

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(pending_exit_ids(&broker), vec!["XS", "XB"]);
    assert!(broker.pending_exit_by_identity("XS", "L").is_some());
    assert!(broker.pending_exit_by_identity("XB", "L").is_some());
    assert_eq!(
        broker
            .order_book
            .exits()
            .total_reserved_for_entry("L", None),
        2.0
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn mixed_stop_and_bracket_downside_fill_in_placement_order() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 0.5, 0);
    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 96.0, 111.0, 0.75, 0);

    broker.evaluate_pending_exits(1, 20, 110.0, 94.0);

    assert_eq!(broker.orders[1].id, "XS");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders[1].price, 95.0);
    assert_eq!(broker.orders[2].id, "XB");
    assert_eq!(broker.orders[2].qty, 0.75);
    assert_eq!(broker.orders[2].price, 96.0);
    assert_eq!(broker.position_size, 0.75);
    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn mixed_limit_and_bracket_upside_fill_in_placement_order() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 110.0, 0.5, 0);
    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 95.0, 111.0, 0.75, 0);

    broker.evaluate_pending_exits(1, 20, 112.0, 97.0);

    assert_eq!(broker.orders[1].id, "XL");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders[1].price, 110.0);
    assert_eq!(broker.orders[2].id, "XB");
    assert_eq!(broker.orders[2].qty, 0.75);
    assert_eq!(broker.orders[2].price, 111.0);
    assert_eq!(broker.position_size, 0.75);
    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn mixed_downside_candidate_wins_over_bracket_upside_candidate() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 90.0, 111.0, 0.75, 0);
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 94.0, 0.5, 0);

    broker.evaluate_pending_exits(1, 20, 112.0, 93.0);

    assert_eq!(broker.orders[1].id, "XS");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders[1].price, 94.0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.position_size, 1.5);
    assert_eq!(pending_exit_ids(&broker), vec!["XB"]);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn same_identity_single_trigger_and_bracket_replacement_releases_reservation() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("X".to_owned(), "L".to_owned(), 95.0, 1.5, 0);

    broker.place_exit_bracket_qty("X".to_owned(), "L".to_owned(), 94.0, 110.0, 2.0, 1);

    assert_eq!(pending_exit_count(&broker), 1);
    let pending = broker
        .pending_exit_by_identity("X", "L")
        .expect("replacement should exist");
    assert_eq!(
        pending.trigger,
        PendingExitTrigger::Bracket {
            downside: 94.0,
            upside: 110.0,
        }
    );
    assert_eq!(pending.reserved_quantity, 2.0);
    assert_eq!(pending.last_update_bar_index, 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_long_cancels_mixed_single_trigger_and_bracket_reservations() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 0.5, 0);
    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 94.0, 110.0, 0.75, 0);

    broker.close_long("L".to_owned(), 1, 20, 105.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn mixed_trailing_and_stop_downside_fill_in_placement_order() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price_qty(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 103.0, 0.75, 0);

    broker.evaluate_pending_exits(1, 20, 110.0, 106.0);
    assert_active_trailing_stop_by_id(&broker, "XT", 108.0);

    broker.evaluate_pending_exits(2, 30, 109.0, 102.0);

    assert_eq!(broker.orders[1].id, "XT");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders[1].price, 108.0);
    assert_eq!(broker.orders[2].id, "XS");
    assert_eq!(broker.orders[2].qty, 0.75);
    assert_eq!(broker.orders[2].price, 103.0);
    assert_eq!(broker.position_size, 0.75);
    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn mixed_trailing_and_bracket_downside_fill_in_placement_order() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 107.0, 115.0, 0.75, 0);
    broker.place_exit_trail_price_qty(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );

    broker.evaluate_pending_exits(1, 20, 110.0, 109.0);
    assert_active_trailing_stop_by_id(&broker, "XT", 108.0);

    broker.evaluate_pending_exits(2, 30, 114.0, 106.0);

    assert_eq!(broker.orders[1].id, "XB");
    assert_eq!(broker.orders[1].qty, 0.75);
    assert_eq!(broker.orders[1].price, 107.0);
    assert_eq!(broker.orders[2].id, "XT");
    assert_eq!(broker.orders[2].qty, 0.5);
    assert_eq!(broker.orders[2].price, 108.0);
    assert_eq!(broker.position_size, 0.75);
    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn mixed_trailing_downside_wins_over_upside_candidates_and_preserves_them() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 111.0, 0.5, 0);
    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 95.0, 112.0, 0.5, 0);
    broker.place_exit_trail_price_qty(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );

    broker.evaluate_pending_exits(1, 20, 110.0, 106.0);
    assert_active_trailing_stop_by_id(&broker, "XT", 108.0);

    broker.evaluate_pending_exits(2, 30, 113.0, 107.0);

    assert_eq!(broker.orders[1].id, "XT");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders[1].price, 108.0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.position_size, 1.5);
    assert_eq!(pending_exit_ids(&broker), vec!["XL", "XB"]);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn mixed_inactive_trailing_activation_and_upside_fill_same_bar_preserves_trailing() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price_qty(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );
    broker.place_exit_limit_qty("XL".to_owned(), "L".to_owned(), 109.0, 0.75, 0);

    broker.evaluate_pending_exits(1, 20, 110.0, 103.0);

    assert_eq!(broker.orders[1].id, "XL");
    assert_eq!(broker.orders[1].qty, 0.75);
    assert_eq!(broker.orders[1].price, 109.0);
    assert_eq!(broker.position_size, 1.25);
    assert_eq!(pending_exit_ids(&broker), vec!["XT"]);
    assert_active_trailing_stop_by_id(&broker, "XT", 108.0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn same_identity_replacement_between_trailing_and_other_families_releases_reservation() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price_qty(
        "X".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.5,
        0,
    );
    broker.place_exit_stop_qty("Y".to_owned(), "L".to_owned(), 94.0, 0.5, 0);

    broker.place_exit_stop_qty("X".to_owned(), "L".to_owned(), 95.0, 1.5, 1);

    let replaced = broker
        .pending_exit_by_identity("X", "L")
        .expect("single-trigger replacement should exist");
    assert_eq!(replaced.trigger, PendingExitTrigger::Stop(95.0));
    assert_eq!(replaced.reserved_quantity, 1.5);
    assert_eq!(replaced.last_update_bar_index, 1);
    assert!(broker.diagnostics.is_empty());

    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("X".to_owned(), "L".to_owned(), 95.0, 110.0, 1.5, 0);
    broker.place_exit_stop_qty("Y".to_owned(), "L".to_owned(), 94.0, 0.5, 0);

    broker.place_exit_trail_price_qty(
        "X".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        1.5,
        1,
    );

    let replaced = broker
        .pending_exit_by_identity("X", "L")
        .expect("trailing replacement should exist");
    assert_eq!(replaced.trigger, trailing_price_trigger(105.0, 2.0));
    assert_eq!(replaced.reserved_quantity, 1.5);
    assert_eq!(replaced.last_update_bar_index, 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn close_long_cancels_mixed_single_bracket_and_trailing_reservations() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop_qty("XS".to_owned(), "L".to_owned(), 95.0, 0.5, 0);
    broker.place_exit_bracket_qty("XB".to_owned(), "L".to_owned(), 94.0, 110.0, 0.5, 0);
    broker.place_exit_trail_price_qty(
        "XT".to_owned(),
        "L".to_owned(),
        TrailPriceExitSpec {
            activation_price: 105.0,
            offset_ticks: 4.0,
            mintick: 0.5,
        },
        0.5,
        0,
    );

    broker.close_long("L".to_owned(), 1, 20, 105.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 1);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn two_percent_brackets_reserve_expected_absolute_quantities() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty_percent("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 25.0, 0);
    broker.place_exit_bracket_qty_percent("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 50.0, 0);

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(pending_exit_ids(&broker), vec!["XB1", "XB2"]);
    let first = broker.pending_exit_by_identity("XB1", "L").unwrap();
    assert_eq!(first.quantity, PendingExitQuantity::Fixed(0.5));
    assert_eq!(first.reserved_quantity, 0.5);
    let second = broker.pending_exit_by_identity("XB2", "L").unwrap();
    assert_eq!(second.quantity, PendingExitQuantity::Fixed(1.0));
    assert_eq!(second.reserved_quantity, 1.0);

    broker.evaluate_pending_exits(1, 20, 112.0, 97.0);

    assert_eq!(broker.orders[1].id, "XB1");
    assert_eq!(broker.orders[1].qty, 0.5);
    assert_eq!(broker.orders[1].price, 110.0);
    assert_eq!(broker.orders[2].id, "XB2");
    assert_eq!(broker.orders[2].qty, 1.0);
    assert_eq!(broker.orders[2].price, 111.0);
    assert_eq!(broker.position_size, 0.5);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn percent_and_fixed_brackets_share_reservation_pool() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 0.75, 0);
    broker.place_exit_bracket_qty_percent("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 75.0, 0);

    assert_eq!(pending_exit_count(&broker), 2);
    assert_eq!(
        broker
            .pending_exit_by_identity("XB2", "L")
            .expect("percent bracket should exist")
            .quantity,
        PendingExitQuantity::Fixed(1.5)
    );
    assert_eq!(
        broker
            .pending_exit_by_identity("XB2", "L")
            .expect("percent bracket should exist")
            .reserved_quantity,
        1.25
    );
    assert_eq!(
        broker
            .order_book
            .exits()
            .total_reserved_for_entry("L", None),
        2.0
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn percent_bracket_replacement_releases_old_reservation_first() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty_percent("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 25.0, 0);
    broker.place_exit_bracket_qty_percent("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 25.0, 0);

    broker.place_exit_bracket_qty_percent("XB1".to_owned(), "L".to_owned(), 94.0, 109.0, 75.0, 1);

    assert_eq!(pending_exit_ids(&broker), vec!["XB1", "XB2"]);
    let replaced = broker.pending_exit_by_identity("XB1", "L").unwrap();
    assert_eq!(
        replaced.trigger,
        PendingExitTrigger::Bracket {
            downside: 94.0,
            upside: 109.0,
        }
    );
    assert_eq!(replaced.quantity, PendingExitQuantity::Fixed(1.5));
    assert_eq!(replaced.reserved_quantity, 1.5);
    assert_eq!(replaced.last_update_bar_index, 1);
    let preserved = broker.pending_exit_by_identity("XB2", "L").unwrap();
    assert_eq!(preserved.reserved_quantity, 0.5);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn over_100_percent_bracket_reserves_remaining_unreserved_quantity() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 0.75, 0);
    broker.place_exit_bracket_qty_percent("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 150.0, 0);

    let percent = broker.pending_exit_by_identity("XB2", "L").unwrap();
    assert_eq!(percent.quantity, PendingExitQuantity::Fixed(3.0));
    assert_eq!(percent.reserved_quantity, 1.25);
    assert_eq!(
        broker
            .order_book
            .exits()
            .total_reserved_for_entry("L", None),
        2.0
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn percent_bracket_with_no_unreserved_quantity_is_rejected() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty_percent("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 50.0, 0);
    broker.place_exit_bracket_qty_percent("XB2".to_owned(), "L".to_owned(), 96.0, 111.0, 50.0, 0);

    broker.place_exit_bracket_qty_percent("XB3".to_owned(), "L".to_owned(), 97.0, 112.0, 25.0, 0);

    assert_eq!(pending_exit_ids(&broker), vec!["XB1", "XB2"]);
    assert!(broker.pending_exit_by_identity("XB3", "L").is_none());
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_QTY");
}

#[test]
fn invalid_percent_bracket_replacement_preserves_existing_pending_bracket() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_bracket_qty_percent("XB1".to_owned(), "L".to_owned(), 95.0, 110.0, 25.0, 0);

    broker.place_exit_bracket_qty_percent(
        "XB1".to_owned(),
        "L".to_owned(),
        94.0,
        109.0,
        f64::NAN,
        1,
    );

    assert_eq!(pending_exit_count(&broker), 1);
    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XB1".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Bracket {
                downside: 95.0,
                upside: 110.0,
            },
            quantity: PendingExitQuantity::Fixed(0.5),
            reserved_quantity: 0.5,
            multiple_reservation: true,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_QTY_PERCENT");
}

#[test]
fn pending_trailing_is_not_eligible_on_creation_bar() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);

    broker.evaluate_pending_exits(0, 10, 110.0, 100.0);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XT".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: trailing_price_trigger(105.0, 2.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 2.0);
}

#[test]
fn pending_trailing_activation_does_not_fill_on_activation_bar() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);

    broker.evaluate_pending_exits(1, 20, 110.0, 100.0);

    assert_active_trailing_stop(&broker, 108.0);
    assert!(
        broker
            .orders
            .iter()
            .all(|order| order.direction != "strategy.exit")
    );
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 2.0);
}

#[test]
fn pending_trailing_ratchets_after_activation_without_filling() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);
    broker.evaluate_pending_exits(1, 20, 110.0, 109.0);

    broker.evaluate_pending_exits(2, 30, 113.0, 109.0);

    assert_active_trailing_stop(&broker, 111.0);
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 2.0);
}

#[test]
fn pending_trailing_stop_never_decreases() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);
    broker.evaluate_pending_exits(1, 20, 110.0, 109.0);

    broker.evaluate_pending_exits(2, 30, 109.0, 108.5);

    assert_active_trailing_stop(&broker, 108.0);
    assert!(broker.trades.is_empty());
    assert_eq!(broker.position_size, 2.0);
}

#[test]
fn pending_trailing_active_stop_fills_before_ratchet() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_trail_price("XT".to_owned(), "L".to_owned(), 105.0, 4.0, 0.5, 0);
    broker.evaluate_pending_exits(1, 20, 110.0, 109.0);

    broker.evaluate_pending_exits(2, 30, 115.0, 107.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.orders.len(), 2);
    assert_eq!(broker.orders[1].id, "XT");
    assert_eq!(broker.orders[1].direction, "strategy.exit");
    assert_eq!(broker.orders[1].price, 108.0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 108.0);
    assert_eq!(broker.trades[0].profit, 16.0);
    assert_eq!(broker.position_size, 0.0);
}

#[test]
fn invalid_profit_ticks_record_diagnostic_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_profit_ticks("XP".to_owned(), "L".to_owned(), 0.0, 0.01, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_TICKS");
}

#[test]
fn invalid_exit_mintick_records_diagnostic_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit("XL".to_owned(), "L".to_owned(), 110.0, 0);

    broker.place_exit_loss_ticks("XS".to_owned(), "L".to_owned(), 5.0, f64::NAN, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(110.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert_eq!(broker.diagnostics.len(), 1);
    assert_eq!(broker.diagnostics[0].code, "E_STRATEGY_EXIT_MINTICK");
}

#[test]
fn profit_ticks_without_matching_entry_is_noop_without_pending_state() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_profit_ticks("XP".to_owned(), "OTHER".to_owned(), 10.0, 0.01, 0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn profit_ticks_with_mismatched_entry_is_noop_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);

    broker.place_exit_profit_ticks("XP".to_owned(), "OTHER".to_owned(), 10.0, 0.5, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XS".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn loss_ticks_with_mismatched_entry_is_noop_without_changing_pending_exit() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_limit("XLIMIT".to_owned(), "L".to_owned(), 110.0, 0);

    broker.place_exit_loss_ticks("XL".to_owned(), "OTHER".to_owned(), 5.0, 0.5, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XLIMIT".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(110.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 0,
            metadata: StrategyExitMetadata::default(),
        })
    );
    assert!(broker.diagnostics.is_empty());
}

#[test]
fn unchanged_repeated_profit_ticks_keep_original_eligibility_bar() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_profit_ticks("XP".to_owned(), "L".to_owned(), 10.0, 1.0, 0);
    broker.place_exit_profit_ticks("XP".to_owned(), "L".to_owned(), 10.0, 1.0, 1);

    broker.evaluate_pending_exits(1, 20, 111.0, 100.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 110.0);
}

#[test]
fn changed_repeated_profit_ticks_delay_eligibility() {
    let mut broker = broker_with_long_entry();
    broker.place_exit_profit_ticks("XP".to_owned(), "L".to_owned(), 10.0, 1.0, 0);
    broker.place_exit_profit_ticks("XP".to_owned(), "L".to_owned(), 11.0, 1.0, 1);

    broker.evaluate_pending_exits(1, 20, 112.0, 100.0);

    assert_eq!(pending_exit_count(&broker), 1);
    assert!(broker.trades.is_empty());

    broker.evaluate_pending_exits(2, 30, 112.0, 100.0);

    assert_eq!(pending_exit_count(&broker), 0);
    assert_eq!(broker.trades.len(), 1);
    assert_eq!(broker.trades[0].exit_price, 111.0);
}

#[test]
fn profit_ticks_replace_stop_and_loss_ticks_replace_limit() {
    let mut broker = broker_with_long_entry();

    broker.place_exit_stop("XS".to_owned(), "L".to_owned(), 95.0, 0);
    broker.place_exit_profit_ticks("XP".to_owned(), "L".to_owned(), 10.0, 1.0, 1);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XP".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Limit(110.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 1,
            metadata: StrategyExitMetadata::default(),
        })
    );

    broker.place_exit_loss_ticks("XL".to_owned(), "L".to_owned(), 5.0, 1.0, 2);

    assert_eq!(
        broker.pending_exit().cloned(),
        Some(PendingExit {
            id: "XL".to_owned(),
            from_entry: "L".to_owned(),
            target_trade_key: None,
            trigger: PendingExitTrigger::Stop(95.0),
            quantity: PendingExitQuantity::Full,
            reserved_quantity: 2.0,
            multiple_reservation: false,
            last_update_bar_index: 2,
            metadata: StrategyExitMetadata::default(),
        })
    );
}
