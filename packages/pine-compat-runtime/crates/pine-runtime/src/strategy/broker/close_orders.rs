use super::{
    BrokerState, StrategyOrderFillAlertEvent, StrategyOrderMetadata,
    closed_trades::{AllocatedEntryFill, ClosedTradeFill},
    ledger::TradeAllocation,
};
use crate::RuntimeDiagnostic;

impl BrokerState {
    pub(crate) fn close_all_long(&mut self, bar_index: usize, time: i64, price: f64) {
        if self.position_size <= 0.0 {
            return;
        }
        if !price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.close_all` fill price must be finite".to_owned(),
            });
            return;
        }

        let price = self.long_exit_fill_price(price);
        if !price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.close_all` slipped fill price must be finite".to_owned(),
            });
            return;
        }

        let qty = self.position_size;
        let allocations = self.trade_ledger.allocate_exit_fifo(None, qty);
        if allocations.is_empty() {
            return;
        }

        let exit_commission = self.exit_commission_for_fill(qty, price);
        let metadata = self.take_next_close_metadata();
        for allocation in &allocations {
            let allocated_exit_commission = exit_commission * (allocation.quantity / qty);
            let commission = allocation.entry_commission + allocated_exit_commission;
            let profit = (price - allocation.entry_price) * allocation.quantity - commission;
            self.record_closed_trade_fill(ClosedTradeFill {
                entry_id: allocation.entry_id.clone(),
                exit_id: allocation.entry_id.clone(),
                entry_fill: AllocatedEntryFill {
                    entry_price: allocation.entry_price,
                    entry_bar_index: allocation.entry_bar_index,
                    entry_time: allocation.entry_time,
                    entry_commission: allocation.entry_commission,
                    entry_metadata: allocation.entry_metadata.clone(),
                },
                exit_bar_index: bar_index,
                exit_time: time,
                exit_price: price,
                qty: allocation.quantity,
                profit,
                commission,
                close_metadata: metadata.clone(),
            });
            self.record_order_fill_alert_from_order_metadata(
                &metadata,
                StrategyOrderFillAlertEvent {
                    id: allocation.entry_id.clone(),
                    bar_index,
                    time,
                    direction: "strategy.close_all".to_owned(),
                    qty: allocation.quantity,
                    price,
                    entry_id: Some(allocation.entry_id.clone()),
                    exit_id: Some(allocation.entry_id.clone()),
                    message: String::new(),
                },
            );
        }

        self.cash += qty * price - exit_commission;
        self.order_book.exits_mut().clear_all();
        self.min_equity_before_open_trade = self.min_equity_before_open_trade.min(self.cash);
        self.max_equity_before_open_trade = self.max_equity_before_open_trade.max(self.cash);
        self.clear_open_long_legacy_state();
        self.apply_trade_allocations_and_sync_position(&allocations);
        self.record_position_snapshot(bar_index);
    }

    pub(crate) fn close_long(&mut self, id: String, bar_index: usize, time: i64, price: f64) {
        self.close_long_quantity(id, bar_index, time, price, None);
    }

    pub(crate) fn close_long_qty(
        &mut self,
        id: String,
        bar_index: usize,
        time: i64,
        price: f64,
        qty: f64,
    ) {
        self.close_long_quantity(id, bar_index, time, price, Some(qty));
    }

    pub(crate) fn close_long_qty_percent(
        &mut self,
        id: String,
        bar_index: usize,
        time: i64,
        price: f64,
        qty_percent: f64,
    ) {
        let matching_position_size = self.trade_ledger.open_quantity_for_entry(&id);
        if self.position_size <= 0.0 || matching_position_size <= 0.0 {
            return;
        }
        if !qty_percent.is_finite() || qty_percent <= 0.0 {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_CLOSE_QTY_PERCENT".to_owned(),
                message: "`strategy.close` percent quantity must be finite and positive".to_owned(),
            });
            return;
        }

        let qty = matching_position_size * qty_percent / 100.0;
        if !qty.is_finite() || qty <= 0.0 {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_CLOSE_QTY_PERCENT".to_owned(),
                message: "`strategy.close` percent quantity must be finite and positive".to_owned(),
            });
            return;
        }
        self.close_long_quantity(id, bar_index, time, price, Some(qty));
    }

    pub(crate) fn reduce_long_with_short_order(
        &mut self,
        id: String,
        bar_index: usize,
        time: i64,
        price: f64,
        requested_qty: f64,
        metadata: StrategyOrderMetadata,
    ) {
        if self.position_size <= 0.0 {
            return;
        }
        if !requested_qty.is_finite() || requested_qty <= 0.0 {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_QTY".to_owned(),
                message: "`strategy.order` quantity must be finite and positive".to_owned(),
            });
            return;
        }
        if !price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.order` fill price must be finite".to_owned(),
            });
            return;
        }

        let price = self.long_exit_fill_price(price);
        if !price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.order` slipped fill price must be finite".to_owned(),
            });
            return;
        }

        let qty = requested_qty.min(self.position_size);
        let allocations = self.trade_ledger.allocate_exit_fifo(None, qty);
        if allocations.is_empty() {
            return;
        }

        let exit_commission = self.exit_commission_for_fill(qty, price);
        self.record_order_event(id.clone(), bar_index, time, "strategy.short", qty, price);
        self.record_order_fill_alert_from_order_metadata(
            &metadata,
            StrategyOrderFillAlertEvent {
                id: id.clone(),
                bar_index,
                time,
                direction: "strategy.short".to_owned(),
                qty,
                price,
                entry_id: None,
                exit_id: Some(id.clone()),
                message: String::new(),
            },
        );

        let mut closed_entry_commission = 0.0;
        for allocation in &allocations {
            let allocated_exit_commission = exit_commission * (allocation.quantity / qty);
            let commission = allocation.entry_commission + allocated_exit_commission;
            let profit = (price - allocation.entry_price) * allocation.quantity - commission;
            closed_entry_commission += allocation.entry_commission;
            self.record_closed_trade_fill(ClosedTradeFill {
                entry_id: allocation.entry_id.clone(),
                exit_id: id.clone(),
                entry_fill: AllocatedEntryFill {
                    entry_price: allocation.entry_price,
                    entry_bar_index: allocation.entry_bar_index,
                    entry_time: allocation.entry_time,
                    entry_commission: allocation.entry_commission,
                    entry_metadata: allocation.entry_metadata.clone(),
                },
                exit_bar_index: bar_index,
                exit_time: time,
                exit_price: price,
                qty: allocation.quantity,
                profit,
                commission,
                close_metadata: metadata.clone(),
            });
        }

        self.cash += qty * price - exit_commission;
        if qty >= self.position_size {
            self.order_book.exits_mut().clear_all();
            self.min_equity_before_open_trade = self.min_equity_before_open_trade.min(self.cash);
            self.max_equity_before_open_trade = self.max_equity_before_open_trade.max(self.cash);
            self.clear_open_long_legacy_state();
            self.apply_trade_allocations_and_sync_position(&allocations);
            self.record_position_snapshot(bar_index);
            return;
        }

        self.open_entry_commission -= closed_entry_commission;
        self.apply_trade_allocations_and_sync_position(&allocations);
        self.record_position_snapshot(bar_index);
    }

    fn close_long_quantity(
        &mut self,
        id: String,
        bar_index: usize,
        time: i64,
        price: f64,
        requested_qty: Option<f64>,
    ) {
        let matching_position_size = self.trade_ledger.open_quantity_for_entry(&id);
        if self.position_size <= 0.0 || matching_position_size <= 0.0 {
            return;
        }
        if let Some(requested_qty) = requested_qty
            && (!requested_qty.is_finite() || requested_qty <= 0.0)
        {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_CLOSE_QTY".to_owned(),
                message: "`strategy.close` quantity must be finite and positive".to_owned(),
            });
            return;
        }
        if !price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.close` fill price must be finite".to_owned(),
            });
            return;
        }

        let price = self.long_exit_fill_price(price);
        if !price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.close` slipped fill price must be finite".to_owned(),
            });
            return;
        }

        let qty = requested_qty.map_or(matching_position_size, |qty| {
            qty.min(matching_position_size)
        });
        let allocations = self.allocate_close_rule_exit(Some(&id), qty);
        let entry_fill = AllocatedEntryFill::from_allocations(
            &allocations,
            self.avg_price,
            self.entry_bar_index.unwrap_or(bar_index),
            self.entry_time.unwrap_or(time),
            self.entry_commission_for_closed_quantity(qty),
        );
        let exit_commission = self.exit_commission_for_fill(qty, price);
        let commission = entry_fill.entry_commission + exit_commission;
        let profit = (price - entry_fill.entry_price) * qty - commission;
        let closed_entry_commission = entry_fill.entry_commission;
        let metadata = self.take_next_close_metadata();
        self.record_closed_trade_fill(ClosedTradeFill {
            entry_id: id.clone(),
            exit_id: id.clone(),
            entry_fill,
            exit_bar_index: bar_index,
            exit_time: time,
            exit_price: price,
            qty,
            profit,
            commission,
            close_metadata: metadata.clone(),
        });
        self.record_order_fill_alert_from_order_metadata(
            &metadata,
            StrategyOrderFillAlertEvent {
                id: id.clone(),
                bar_index,
                time,
                direction: "strategy.close".to_owned(),
                qty,
                price,
                entry_id: Some(id.clone()),
                exit_id: Some(id.clone()),
                message: String::new(),
            },
        );

        self.cash += qty * price - exit_commission;
        if qty >= self.position_size {
            self.cancel_exit_for_entry(&id);
            self.min_equity_before_open_trade = self.min_equity_before_open_trade.min(self.cash);
            self.max_equity_before_open_trade = self.max_equity_before_open_trade.max(self.cash);
            self.clear_open_long_legacy_state();
            self.apply_trade_allocations_and_sync_position(&allocations);
            if allocations.is_empty() {
                self.trade_ledger.clear_open_trade();
                self.sync_aggregate_position_from_ledger();
            }
            self.record_position_snapshot(bar_index);
            return;
        }

        self.open_entry_commission -= closed_entry_commission;
        self.apply_trade_allocations_and_sync_position(&allocations);
        self.record_position_snapshot(bar_index);
    }

    pub(super) fn allocate_close_rule_exit(
        &self,
        from_entry: Option<&str>,
        requested_quantity: f64,
    ) -> Vec<TradeAllocation> {
        match (self.close_entries_rule, from_entry) {
            (pine_ir::StrategyCloseEntriesRule::Any, Some(entry_id)) => self
                .trade_ledger
                .allocate_exit_any_for_entry(entry_id, requested_quantity),
            _ => self
                .trade_ledger
                .allocate_exit_fifo(from_entry, requested_quantity),
        }
    }
}
