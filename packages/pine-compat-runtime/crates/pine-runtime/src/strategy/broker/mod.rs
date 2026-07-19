mod accounting;
mod all_entry_relative_exits;
mod close_orders;
mod closed_trades;
mod deferred_relative_exits;
mod entries;
mod exit_orders;
mod exit_placement;
mod exit_price_orders;
mod exits;
mod fills;
mod ledger;
mod loss_limit_brackets;
mod loss_profit_brackets;
mod order_book;
mod pending_entries;
mod pending_entry_fills;
mod pending_exits;
mod state;
mod stop_profit_brackets;
mod types;

use pine_ir::{StrategyCloseEntriesRule, StrategyCommission, StrategyMarginSetting};

#[cfg(test)]
use ledger::NetPosition;
use ledger::TradeLedger;
#[cfg(test)]
use ledger::{OpenTrade, TradeAllocation, TradeDirection};
pub(crate) use loss_limit_brackets::LossLimitBracketSpec;
pub(crate) use loss_profit_brackets::LossProfitBracketSpec;
use order_book::OrderBook;
use pending_entries::StopLimitEntryPlacement;
use pending_exits::{
    PendingExit, PendingExitQuantity, PendingExitSide, PendingExitTrigger, PendingTrailingUpdate,
};
pub(crate) use pending_exits::{TrailPointsExitSpec, TrailPriceExitSpec};
pub(crate) use stop_profit_brackets::StopProfitBracketSpec;
use types::ClosedTradeMetrics;
pub(crate) use types::{StrategyExitMetadata, StrategyOrderFillAlertEvent, StrategyOrderMetadata};

use crate::{
    RuntimeDiagnostic, StrategyEquitySnapshot, StrategyOrderEvent, StrategyPositionSnapshot,
    StrategyTrade,
};

#[derive(Debug, Clone, PartialEq)]
pub struct BrokerState {
    initial_capital: f64,
    commission: Option<StrategyCommission>,
    pyramiding_limit: usize,
    close_entries_rule: StrategyCloseEntriesRule,
    margin_long: StrategyMarginSetting,
    margin_short: StrategyMarginSetting,
    open_entry_commission: f64,
    slippage_price_offset: f64,
    limit_verification_price_offset: f64,
    cash: f64,
    position_size: f64,
    avg_price: f64,
    next_close_metadata: StrategyOrderMetadata,
    next_exit_metadata: StrategyExitMetadata,
    entry_id: Option<String>,
    position_entry_name: Option<String>,
    entry_bar_index: Option<usize>,
    entry_time: Option<i64>,
    open_trade_max_high: Option<f64>,
    open_trade_min_low: Option<f64>,
    open_trade_equity_on_entry: Option<f64>,
    open_trade_min_equity_before_entry: Option<f64>,
    open_trade_max_equity_before_entry: Option<f64>,
    min_equity_before_open_trade: f64,
    max_equity_before_open_trade: f64,
    max_runup: f64,
    max_runup_percent: f64,
    max_drawdown: f64,
    max_drawdown_percent: f64,
    max_contracts_held_long: f64,
    orders: Vec<StrategyOrderEvent>,
    order_fill_alerts: Vec<StrategyOrderFillAlertEvent>,
    trades: Vec<StrategyTrade>,
    closed_trade_metrics: Vec<ClosedTradeMetrics>,
    position: Vec<StrategyPositionSnapshot>,
    equity: Vec<StrategyEquitySnapshot>,
    diagnostics: Vec<RuntimeDiagnostic>,
    order_book: OrderBook,
    trade_ledger: TradeLedger,
}

impl BrokerState {
    fn expand_persistent_all_entry_exit_for_new_entry(&mut self, bar_index: usize) {
        let position_size = self.position_size;
        if !position_size.is_finite() || position_size <= 0.0 {
            return;
        }
        let Some(pending_exit) = self.order_book.exits_mut().current_mut() else {
            return;
        };
        if pending_exit.from_entry.is_empty()
            && pending_exit.quantity == PendingExitQuantity::Full
            && !pending_exit.multiple_reservation
            && matches!(
                pending_exit.trigger,
                PendingExitTrigger::Stop(_)
                    | PendingExitTrigger::Limit(_)
                    | PendingExitTrigger::Bracket { .. }
                    | PendingExitTrigger::Trailing(_)
            )
        {
            pending_exit.reserved_quantity = position_size;
            pending_exit.last_update_bar_index = bar_index;
        }
    }

    fn can_open_long_entry(&self) -> bool {
        self.trade_ledger.open_count() < self.pyramiding_limit
    }

    pub(crate) fn cancel_exit_for_entry(&mut self, entry_id: &str) {
        self.order_book.exits_mut().clear_for_entry(entry_id);
    }

    pub(crate) fn cancel_pending_order(&mut self, id: &str) {
        self.order_book.cancel_id(id);
    }

    pub(crate) fn cancel_all_pending_orders(&mut self) {
        self.order_book.clear_all();
    }

    #[allow(dead_code)]
    pub(crate) fn place_pending_market_long_entry(
        &mut self,
        id: String,
        qty: f64,
        created_bar_index: usize,
    ) {
        self.place_pending_market_long_entry_with_metadata(
            id,
            qty,
            created_bar_index,
            StrategyOrderMetadata::default(),
        );
    }

    pub(crate) fn place_pending_market_long_entry_with_metadata(
        &mut self,
        id: String,
        qty: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
    ) {
        if !self.can_open_long_entry() {
            return;
        }
        self.order_book
            .entries_mut()
            .place_market_long_with_metadata(
                id,
                qty,
                created_bar_index,
                metadata,
                &mut self.diagnostics,
            );
    }

    #[allow(dead_code)]
    pub(crate) fn place_pending_market_long_order(
        &mut self,
        id: String,
        qty: f64,
        created_bar_index: usize,
    ) {
        self.place_pending_market_long_order_with_metadata(
            id,
            qty,
            created_bar_index,
            StrategyOrderMetadata::default(),
        );
    }

    pub(crate) fn place_pending_market_long_order_with_metadata(
        &mut self,
        id: String,
        qty: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
    ) {
        self.order_book
            .entries_mut()
            .place_market_long_without_pyramiding_with_metadata(
                id,
                qty,
                created_bar_index,
                metadata,
                &mut self.diagnostics,
            );
    }

    #[allow(dead_code)]
    pub(crate) fn place_pending_market_short_order(
        &mut self,
        id: String,
        qty: f64,
        created_bar_index: usize,
    ) {
        self.place_pending_market_short_order_with_metadata(
            id,
            qty,
            created_bar_index,
            StrategyOrderMetadata::default(),
        );
    }

    pub(crate) fn place_pending_market_short_order_with_metadata(
        &mut self,
        id: String,
        qty: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
    ) {
        self.order_book.entries_mut().place_market_short_order(
            id,
            qty,
            created_bar_index,
            metadata,
            &mut self.diagnostics,
        );
    }

    #[allow(dead_code)]
    pub(crate) fn place_pending_limit_long_entry(
        &mut self,
        id: String,
        qty: f64,
        limit: f64,
        created_bar_index: usize,
    ) {
        self.place_pending_limit_long_entry_with_metadata(
            id,
            qty,
            limit,
            created_bar_index,
            StrategyOrderMetadata::default(),
        );
    }

    pub(crate) fn place_pending_limit_long_entry_with_metadata(
        &mut self,
        id: String,
        qty: f64,
        limit: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
    ) {
        if !self.can_open_long_entry() {
            return;
        }
        self.order_book
            .entries_mut()
            .place_limit_long_with_metadata(
                id,
                qty,
                limit,
                created_bar_index,
                metadata,
                &mut self.diagnostics,
            );
    }

    #[allow(dead_code)]
    pub(crate) fn place_pending_limit_long_order(
        &mut self,
        id: String,
        qty: f64,
        limit: f64,
        created_bar_index: usize,
    ) {
        self.place_pending_limit_long_order_with_metadata(
            id,
            qty,
            limit,
            created_bar_index,
            StrategyOrderMetadata::default(),
        );
    }

    pub(crate) fn place_pending_limit_long_order_with_metadata(
        &mut self,
        id: String,
        qty: f64,
        limit: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
    ) {
        self.order_book
            .entries_mut()
            .place_limit_long_without_pyramiding_with_metadata(
                id,
                qty,
                limit,
                created_bar_index,
                metadata,
                &mut self.diagnostics,
            );
    }

    #[allow(dead_code)]
    pub(crate) fn place_pending_stop_long_entry(
        &mut self,
        id: String,
        qty: f64,
        stop: f64,
        created_bar_index: usize,
    ) {
        self.place_pending_stop_long_entry_with_metadata(
            id,
            qty,
            stop,
            created_bar_index,
            StrategyOrderMetadata::default(),
        );
    }

    pub(crate) fn place_pending_stop_long_entry_with_metadata(
        &mut self,
        id: String,
        qty: f64,
        stop: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
    ) {
        if !self.can_open_long_entry() {
            return;
        }
        self.order_book.entries_mut().place_stop_long_with_metadata(
            id,
            qty,
            stop,
            created_bar_index,
            metadata,
            &mut self.diagnostics,
        );
    }

    #[allow(dead_code)]
    pub(crate) fn place_pending_stop_long_order(
        &mut self,
        id: String,
        qty: f64,
        stop: f64,
        created_bar_index: usize,
    ) {
        self.place_pending_stop_long_order_with_metadata(
            id,
            qty,
            stop,
            created_bar_index,
            StrategyOrderMetadata::default(),
        );
    }

    pub(crate) fn place_pending_stop_long_order_with_metadata(
        &mut self,
        id: String,
        qty: f64,
        stop: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
    ) {
        self.order_book
            .entries_mut()
            .place_stop_long_without_pyramiding_with_metadata(
                id,
                qty,
                stop,
                created_bar_index,
                metadata,
                &mut self.diagnostics,
            );
    }

    #[allow(dead_code)]
    pub(crate) fn place_pending_stop_limit_long_entry(
        &mut self,
        id: String,
        qty: f64,
        stop: f64,
        limit: f64,
        created_bar_index: usize,
    ) {
        self.place_pending_stop_limit_long_entry_with_metadata(
            id,
            qty,
            stop,
            limit,
            created_bar_index,
            StrategyOrderMetadata::default(),
        );
    }

    pub(crate) fn place_pending_stop_limit_long_entry_with_metadata(
        &mut self,
        id: String,
        qty: f64,
        stop: f64,
        limit: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
    ) {
        if !self.can_open_long_entry() {
            return;
        }
        self.order_book
            .entries_mut()
            .place_stop_limit_long_with_metadata(
                StopLimitEntryPlacement {
                    id,
                    quantity: qty,
                    stop_price: stop,
                    limit_price: limit,
                    created_bar_index,
                    metadata,
                },
                &mut self.diagnostics,
            );
    }

    #[allow(dead_code)]
    pub(crate) fn place_pending_stop_limit_long_order(
        &mut self,
        id: String,
        qty: f64,
        stop: f64,
        limit: f64,
        created_bar_index: usize,
    ) {
        self.place_pending_stop_limit_long_order_with_metadata(
            id,
            qty,
            stop,
            limit,
            created_bar_index,
            StrategyOrderMetadata::default(),
        );
    }

    pub(crate) fn place_pending_stop_limit_long_order_with_metadata(
        &mut self,
        id: String,
        qty: f64,
        stop: f64,
        limit: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
    ) {
        self.order_book
            .entries_mut()
            .place_stop_limit_long_without_pyramiding_with_metadata(
                StopLimitEntryPlacement {
                    id,
                    quantity: qty,
                    stop_price: stop,
                    limit_price: limit,
                    created_bar_index,
                    metadata,
                },
                &mut self.diagnostics,
            );
    }

    #[allow(dead_code)]
    fn pending_entry_count(&self) -> usize {
        self.order_book.entries().count()
    }

    fn has_pending_entry(&self, id: &str) -> bool {
        self.order_book.entries().quantity_for_id(id).is_some()
    }

    fn open_position_size_for_entry(&self, id: &str) -> f64 {
        if id.is_empty() {
            return self.position_size;
        }
        self.trade_ledger.open_quantity_for_entry(id)
    }

    fn last_open_trade_key_and_price_for_entry(&self, id: &str) -> Option<(u64, f64)> {
        let mut result = None;
        for index in 0..self.trade_ledger.open_count() {
            let Some(open_trade) = self.trade_ledger.open_at(index) else {
                continue;
            };
            if open_trade.id == id {
                result = Some((open_trade.key, open_trade.entry_price));
            }
        }
        result
    }

    fn first_open_entry_price_for_entry(&self, id: &str) -> Option<f64> {
        self.trade_ledger.first_open_entry_price_for_entry(id)
    }

    fn has_open_position_for_entry(&self, id: &str) -> bool {
        if id.is_empty() {
            return self.position_size > 0.0;
        }
        self.open_position_size_for_entry(id) > 0.0
    }

    pub(crate) fn reject_entry_relative_exit_for_pending_entry(
        &mut self,
        from_entry: &str,
    ) -> bool {
        if self.position_size > 0.0
            || self
                .order_book
                .entries()
                .quantity_for_id(from_entry)
                .is_none()
        {
            return false;
        }

        self.diagnostics.push(RuntimeDiagnostic {
            code: "E_STRATEGY_EXIT_ENTRY".to_owned(),
            message: "`strategy.exit` from_entry must match the current long entry".to_owned(),
        });
        true
    }

    fn pending_exit(&self) -> Option<&PendingExit> {
        self.order_book.exits().current()
    }

    #[allow(dead_code)]
    fn pending_exit_mut(&mut self) -> Option<&mut PendingExit> {
        self.order_book.exits_mut().current_mut()
    }

    #[allow(dead_code)]
    fn pending_exit_count(&self) -> usize {
        self.order_book.exits().count()
    }

    #[allow(dead_code)]
    fn pending_exit_by_identity(&self, id: &str, from_entry: &str) -> Option<&PendingExit> {
        self.order_book.exits().find_by_identity(id, from_entry)
    }

    #[allow(dead_code)]
    fn pending_exit_by_identity_and_key(
        &self,
        id: &str,
        from_entry: &str,
        target_trade_key: Option<u64>,
    ) -> Option<&PendingExit> {
        self.order_book
            .exits()
            .find_by_identity_and_key(id, from_entry, target_trade_key)
    }

    #[allow(dead_code)]
    fn pending_exits_in_placement_order(&self) -> impl Iterator<Item = &PendingExit> {
        self.order_book.exits().iter()
    }

    pub(crate) fn evaluate_pending_exits(
        &mut self,
        bar_index: usize,
        time: i64,
        high: f64,
        low: f64,
    ) {
        if self.pending_exit_count() > 1 {
            self.evaluate_multiple_pending_exits(bar_index, time, high, low);
            return;
        }

        let Some(mut pending_exit) = self.pending_exit().cloned() else {
            return;
        };
        if pending_exit.last_update_bar_index >= bar_index {
            return;
        }
        if self.position_size <= 0.0 || !self.has_open_position_for_entry(&pending_exit.from_entry)
        {
            if self.position_size <= 0.0 && self.has_pending_entry(&pending_exit.from_entry) {
                return;
            }
            self.order_book
                .exits_mut()
                .clear_for_entry(&pending_exit.from_entry);
            return;
        }
        let triggered_price = match &mut pending_exit.trigger {
            PendingExitTrigger::Stop(price) if low <= *price => Some(*price),
            PendingExitTrigger::Limit(price) if self.long_limit_exit_is_verified(*price, high) => {
                Some(*price)
            }
            PendingExitTrigger::Bracket { downside, upside } => {
                if low <= *downside {
                    Some(*downside)
                } else if self.long_limit_exit_is_verified(*upside, high) {
                    Some(*upside)
                } else {
                    None
                }
            }
            PendingExitTrigger::Trailing(trailing) => match trailing.evaluate_update(high, low) {
                PendingTrailingUpdate::NoChange => return,
                PendingTrailingUpdate::Persist(updated_trailing) => {
                    pending_exit.trigger = PendingExitTrigger::Trailing(updated_trailing);
                    self.order_book.exits_mut().replace_all(pending_exit);
                    return;
                }
                PendingTrailingUpdate::Candidate(touch) => Some(touch.exit_price),
            },
            _ => None,
        };
        if let Some(exit_price) = triggered_price {
            let from_entry = pending_exit.from_entry.clone();
            self.fill_pending_exit(pending_exit, bar_index, time, exit_price);
            if self.position_size <= 0.0 {
                self.order_book.exits_mut().clear_all();
            } else {
                self.order_book.exits_mut().clear_for_entry(&from_entry);
            }
        }
    }

    fn evaluate_multiple_pending_exits(
        &mut self,
        bar_index: usize,
        time: i64,
        high: f64,
        low: f64,
    ) {
        let pending_exits: Vec<PendingExit> = self.order_book.exits().iter().cloned().collect();
        if pending_exits.is_empty() {
            return;
        }
        if self.position_size <= 0.0 {
            if self.position_size <= 0.0 {
                let attached_pending_entry_ids: Vec<String> = pending_exits
                    .iter()
                    .filter(|pending_exit| self.has_pending_entry(&pending_exit.from_entry))
                    .map(|pending_exit| pending_exit.from_entry.clone())
                    .collect();
                if !attached_pending_entry_ids.is_empty() {
                    for pending_exit in pending_exits {
                        if !attached_pending_entry_ids
                            .iter()
                            .any(|entry_id| entry_id == &pending_exit.from_entry)
                        {
                            self.order_book
                                .exits_mut()
                                .clear_for_entry(&pending_exit.from_entry);
                        }
                    }
                    return;
                }
            }
            return;
        }

        let mut touched_candidates = Vec::new();
        let mut state_updates = Vec::new();
        for pending_exit in pending_exits {
            if pending_exit.last_update_bar_index >= bar_index {
                continue;
            }
            if !self.has_open_position_for_entry(&pending_exit.from_entry) {
                self.order_book
                    .exits_mut()
                    .clear_for_entry(&pending_exit.from_entry);
                continue;
            }

            match pending_exit.trigger.clone() {
                PendingExitTrigger::Trailing(trailing) => {
                    match trailing.evaluate_update(high, low) {
                        PendingTrailingUpdate::NoChange => {}
                        PendingTrailingUpdate::Persist(updated_trailing) => {
                            let mut updated_pending_exit = pending_exit;
                            updated_pending_exit.trigger =
                                PendingExitTrigger::Trailing(updated_trailing);
                            state_updates.push(updated_pending_exit);
                        }
                        PendingTrailingUpdate::Candidate(touch) => {
                            touched_candidates.push((pending_exit, touch.exit_price, touch.side));
                        }
                    }
                }
                _ => {
                    if let Some(touch) = pending_exit.trigger.touched_candidate(
                        high,
                        low,
                        self.limit_verification_price_offset,
                    ) {
                        touched_candidates.push((pending_exit, touch.exit_price, touch.side));
                    }
                }
            }
        }

        let winning_side = if touched_candidates
            .iter()
            .any(|(_, _, side)| *side == PendingExitSide::Stop)
        {
            PendingExitSide::Stop
        } else if touched_candidates
            .iter()
            .any(|(_, _, side)| *side == PendingExitSide::Limit)
        {
            PendingExitSide::Limit
        } else {
            for updated_pending_exit in state_updates {
                self.order_book
                    .exits_mut()
                    .replace_or_append(updated_pending_exit);
            }
            return;
        };

        let mut filled_identities = Vec::new();
        for (pending_exit, exit_price, side) in touched_candidates {
            if side != winning_side {
                continue;
            }
            if self.position_size <= 0.0 {
                break;
            }
            if !self.has_open_position_for_entry(&pending_exit.from_entry) {
                self.order_book
                    .exits_mut()
                    .clear_for_entry(&pending_exit.from_entry);
                continue;
            }
            filled_identities.push((
                pending_exit.id.clone(),
                pending_exit.from_entry.clone(),
                pending_exit.target_trade_key,
            ));
            self.fill_pending_exit(pending_exit, bar_index, time, exit_price);
        }

        if self.position_size <= 0.0 {
            self.order_book.exits_mut().clear_all();
        } else {
            for updated_pending_exit in state_updates {
                self.order_book
                    .exits_mut()
                    .replace_or_append(updated_pending_exit);
            }
            self.order_book
                .exits_mut()
                .remove_identities(&filled_identities);
        }
    }
}

#[cfg(test)]
mod tests;
