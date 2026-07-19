use super::StrategyOrderMetadata;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum TradeDirection {
    Long,
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct OpenTrade {
    pub(super) key: u64,
    pub(super) id: String,
    pub(super) direction: TradeDirection,
    pub(super) quantity: f64,
    pub(super) entry_price: f64,
    pub(super) entry_bar_index: usize,
    pub(super) entry_time: i64,
    pub(super) entry_commission: f64,
    pub(super) max_high: Option<f64>,
    pub(super) min_low: Option<f64>,
    pub(super) equity_on_entry: Option<f64>,
    pub(super) min_equity_before_entry: Option<f64>,
    pub(super) max_equity_before_entry: Option<f64>,
    pub(super) entry_metadata: StrategyOrderMetadata,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub(super) struct NetPosition {
    pub(super) signed_size: f64,
    pub(super) avg_price: f64,
}

impl Default for NetPosition {
    fn default() -> Self {
        Self {
            signed_size: 0.0,
            avg_price: 0.0,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct TradeAllocation {
    pub(super) trade_index: usize,
    pub(super) trade_key: u64,
    pub(super) entry_id: String,
    pub(super) entry_price: f64,
    pub(super) entry_bar_index: usize,
    pub(super) entry_time: i64,
    pub(super) quantity: f64,
    pub(super) entry_commission: f64,
    pub(super) entry_metadata: StrategyOrderMetadata,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub(super) struct TradeLedger {
    open_trades: Vec<OpenTrade>,
    net_position: NetPosition,
    next_trade_key: u64,
}

impl TradeLedger {
    pub(super) fn open_long(&mut self, trade: OpenTrade) {
        self.open_trades.clear();
        self.append_long(trade);
    }

    #[allow(dead_code)]
    pub(super) fn append_long(&mut self, mut trade: OpenTrade) {
        trade.key = self.next_trade_key;
        self.next_trade_key = self.next_trade_key.saturating_add(1);
        self.open_trades.push(trade);
        self.rebuild_net_position();
    }

    pub(super) fn clear_open_trade(&mut self) {
        self.open_trades.clear();
        self.net_position = NetPosition::default();
    }

    pub(super) fn update_extremes(&mut self, high: f64, low: f64) {
        for open_trade in &mut self.open_trades {
            if high.is_finite() {
                open_trade.max_high = Some(
                    open_trade
                        .max_high
                        .map_or(high, |current| current.max(high)),
                );
            }
            if low.is_finite() {
                open_trade.min_low =
                    Some(open_trade.min_low.map_or(low, |current| current.min(low)));
            }
        }
    }

    #[allow(dead_code)]
    pub(super) fn allocate_exit_fifo(
        &self,
        from_entry: Option<&str>,
        requested_quantity: f64,
    ) -> Vec<TradeAllocation> {
        if !requested_quantity.is_finite() || requested_quantity <= 0.0 {
            return Vec::new();
        }

        let mut remaining = requested_quantity;
        let mut allocations = Vec::new();
        for (trade_index, trade) in self.open_trades.iter().enumerate() {
            if from_entry.is_some_and(|entry_id| trade.id != entry_id) {
                continue;
            }
            if remaining <= 0.0 {
                break;
            }

            let quantity = remaining.min(trade.quantity);
            if quantity <= 0.0 {
                continue;
            }
            allocations.push(Self::allocation_for_trade(trade_index, trade, quantity));
            remaining -= quantity;
        }
        allocations
    }

    #[allow(dead_code)]
    pub(super) fn allocate_exit_any_for_entry(
        &self,
        entry_id: &str,
        requested_quantity: f64,
    ) -> Vec<TradeAllocation> {
        if !requested_quantity.is_finite() || requested_quantity <= 0.0 {
            return Vec::new();
        }

        let mut remaining = requested_quantity;
        let mut allocations = Vec::new();
        for (trade_index, trade) in self.open_trades.iter().enumerate() {
            if trade.id != entry_id {
                continue;
            }
            if remaining <= 0.0 {
                break;
            }

            let quantity = remaining.min(trade.quantity);
            if quantity <= 0.0 {
                continue;
            }
            allocations.push(Self::allocation_for_trade(trade_index, trade, quantity));
            remaining -= quantity;
        }
        allocations
    }

    #[allow(dead_code)]
    pub(super) fn allocate_exit_for_key(
        &self,
        trade_key: u64,
        requested_quantity: f64,
    ) -> Vec<TradeAllocation> {
        if !requested_quantity.is_finite() || requested_quantity <= 0.0 {
            return Vec::new();
        }

        let Some((trade_index, trade)) = self
            .open_trades
            .iter()
            .enumerate()
            .find(|(_, trade)| trade.key == trade_key)
        else {
            return Vec::new();
        };

        let quantity = requested_quantity.min(trade.quantity);
        if quantity <= 0.0 {
            return Vec::new();
        }

        vec![Self::allocation_for_trade(trade_index, trade, quantity)]
    }

    #[allow(dead_code)]
    pub(super) fn apply_allocations(&mut self, allocations: &[TradeAllocation]) {
        for allocation in allocations.iter().rev() {
            let Some(open_trade) = self.open_trades.get_mut(allocation.trade_index) else {
                continue;
            };
            if open_trade.id != allocation.entry_id
                || !allocation.quantity.is_finite()
                || allocation.quantity <= 0.0
            {
                continue;
            }

            if allocation.quantity >= open_trade.quantity {
                self.open_trades.remove(allocation.trade_index);
            } else {
                open_trade.quantity -= allocation.quantity;
                open_trade.entry_commission -= allocation.entry_commission;
            }
        }
        self.rebuild_net_position();
    }

    fn allocation_for_trade(
        trade_index: usize,
        trade: &OpenTrade,
        quantity: f64,
    ) -> TradeAllocation {
        let entry_commission = trade.entry_commission * (quantity / trade.quantity);
        TradeAllocation {
            trade_index,
            trade_key: trade.key,
            entry_id: trade.id.clone(),
            entry_price: trade.entry_price,
            entry_bar_index: trade.entry_bar_index,
            entry_time: trade.entry_time,
            quantity,
            entry_commission,
            entry_metadata: trade.entry_metadata.clone(),
        }
    }

    fn rebuild_net_position(&mut self) {
        let signed_size: f64 = self.open_trades.iter().map(|trade| trade.quantity).sum();
        if signed_size <= 0.0 {
            self.net_position = NetPosition::default();
            return;
        }

        let weighted_entry_value: f64 = self
            .open_trades
            .iter()
            .map(|trade| trade.quantity * trade.entry_price)
            .sum();
        self.net_position = NetPosition {
            signed_size,
            avg_price: weighted_entry_value / signed_size,
        };
    }

    #[cfg(test)]
    pub(super) fn open_trade(&self) -> Option<&OpenTrade> {
        self.open_trades.first()
    }

    #[cfg(test)]
    pub(super) fn open_trades(&self) -> &[OpenTrade] {
        &self.open_trades
    }

    pub(super) fn open_at(&self, index: usize) -> Option<&OpenTrade> {
        self.open_trades.get(index)
    }

    #[allow(dead_code)]
    pub(super) fn open_by_key(&self, key: u64) -> Option<&OpenTrade> {
        self.open_trades.iter().find(|trade| trade.key == key)
    }

    #[cfg(test)]
    pub(super) fn append_open_trade_for_test(&mut self, trade: OpenTrade) {
        self.append_long(trade);
    }

    pub(super) fn net_position(&self) -> NetPosition {
        self.net_position
    }

    pub(super) fn open_count(&self) -> usize {
        self.open_trades.len()
    }

    pub(super) fn open_quantity_for_entry(&self, entry_id: &str) -> f64 {
        self.open_trades
            .iter()
            .filter(|trade| trade.id == entry_id)
            .map(|trade| trade.quantity)
            .sum()
    }

    #[allow(dead_code)]
    pub(super) fn open_quantity_for_key(&self, key: u64) -> f64 {
        self.open_trades
            .iter()
            .filter(|trade| trade.key == key)
            .map(|trade| trade.quantity)
            .sum()
    }

    pub(super) fn first_open_entry_price_for_entry(&self, entry_id: &str) -> Option<f64> {
        self.open_trades
            .iter()
            .find(|trade| trade.id == entry_id)
            .map(|trade| trade.entry_price)
    }

    #[allow(dead_code)]
    pub(super) fn open_entry_price_for_key(&self, key: u64) -> Option<f64> {
        self.open_by_key(key).map(|trade| trade.entry_price)
    }
}
