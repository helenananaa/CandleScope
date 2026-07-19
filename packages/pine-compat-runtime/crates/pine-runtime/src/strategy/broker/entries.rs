use super::{
    BrokerState, StrategyOrderMetadata,
    ledger::{OpenTrade, TradeAllocation, TradeDirection},
    types::{EntryFill, EntryPyramidingMode},
};
use crate::RuntimeDiagnostic;

impl BrokerState {
    #[allow(dead_code)]
    pub(crate) fn entry_long(
        &mut self,
        id: String,
        bar_index: usize,
        time: i64,
        price: f64,
        qty: f64,
    ) -> bool {
        self.entry_long_with_metadata(
            id,
            bar_index,
            time,
            price,
            qty,
            StrategyOrderMetadata::default(),
        )
    }

    pub(crate) fn entry_long_with_metadata(
        &mut self,
        id: String,
        bar_index: usize,
        time: i64,
        price: f64,
        qty: f64,
        metadata: StrategyOrderMetadata,
    ) -> bool {
        self.entry_long_internal(
            EntryFill {
                id,
                bar_index,
                time,
                price,
                qty,
                metadata,
            },
            EntryPyramidingMode::EnforceLimit,
        )
    }

    pub(super) fn entry_long_internal(
        &mut self,
        fill: EntryFill,
        pyramiding_mode: EntryPyramidingMode,
    ) -> bool {
        if !fill.qty.is_finite() || fill.qty <= 0.0 {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_QTY".to_owned(),
                message: "`strategy.entry` quantity must be positive".to_owned(),
            });
            return false;
        }
        if !fill.price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.entry` fill price must be finite".to_owned(),
            });
            return false;
        }
        if pyramiding_mode == EntryPyramidingMode::EnforceLimit && !self.can_open_long_entry() {
            return false;
        }

        let fill_price = self.long_entry_fill_price(fill.price);
        if !fill_price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.entry` slipped fill price must be finite".to_owned(),
            });
            return false;
        }
        if !self.can_afford_long_entry(fill.qty, fill_price) {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_MARGIN".to_owned(),
                message: "`strategy.entry` requires more margin than available equity".to_owned(),
            });
            return false;
        }

        let equity_on_entry = self.cash;
        let min_equity_before_entry = self.min_equity_before_open_trade;
        let max_equity_before_entry = self.max_equity_before_open_trade;
        let alert_id = fill.id.clone();
        let alert_metadata = fill.metadata.clone();
        let open_trade = OpenTrade {
            key: 0,
            id: fill.id.clone(),
            direction: TradeDirection::Long,
            quantity: fill.qty,
            entry_price: fill_price,
            entry_bar_index: fill.bar_index,
            entry_time: fill.time,
            entry_commission: self.entry_commission_for_fill(fill.qty, fill_price),
            max_high: Some(fill_price),
            min_low: Some(fill_price),
            equity_on_entry: Some(equity_on_entry),
            min_equity_before_entry: Some(min_equity_before_entry),
            max_equity_before_entry: Some(max_equity_before_entry),
            entry_metadata: fill.metadata,
        };
        if matches!(
            pyramiding_mode,
            EntryPyramidingMode::BypassLimit | EntryPyramidingMode::SameTickPriceException
        ) {
            self.record_open_long_trade_exceeding_pyramiding(open_trade);
        } else {
            self.record_open_long_trade(open_trade);
        }
        self.record_order_event(
            fill.id,
            fill.bar_index,
            fill.time,
            "strategy.long",
            fill.qty,
            fill_price,
        );
        self.record_order_fill_alert_from_order_metadata(
            &alert_metadata,
            super::StrategyOrderFillAlertEvent {
                id: alert_id.clone(),
                bar_index: fill.bar_index,
                time: fill.time,
                direction: "strategy.long".to_owned(),
                qty: fill.qty,
                price: fill_price,
                entry_id: Some(alert_id),
                exit_id: None,
                message: String::new(),
            },
        );
        self.record_position_snapshot(fill.bar_index);
        true
    }

    fn record_open_long_trade(&mut self, open_trade: OpenTrade) {
        self.record_open_long_legacy_state(&open_trade);
        if self.pyramiding_limit <= 1 {
            self.trade_ledger.open_long(open_trade);
        } else {
            self.trade_ledger.append_long(open_trade);
        }
        self.sync_aggregate_position_from_ledger();
    }

    fn record_open_long_trade_exceeding_pyramiding(&mut self, open_trade: OpenTrade) {
        self.record_open_long_legacy_state(&open_trade);
        self.trade_ledger.append_long(open_trade);
        self.sync_aggregate_position_from_ledger();
    }

    pub(super) fn sync_aggregate_position_from_ledger(&mut self) {
        let net_position = self.trade_ledger.net_position();
        self.position_size = net_position.signed_size;
        self.avg_price = net_position.avg_price;
        self.max_contracts_held_long = self.max_contracts_held_long.max(self.position_size);
    }

    pub(super) fn apply_trade_allocations_and_sync_position(
        &mut self,
        allocations: &[TradeAllocation],
    ) {
        self.trade_ledger.apply_allocations(allocations);
        self.sync_aggregate_position_from_ledger();
    }
}
