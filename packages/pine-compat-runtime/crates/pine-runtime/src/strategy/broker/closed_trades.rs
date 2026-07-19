use super::{
    BrokerState, ClosedTradeMetrics, StrategyOrderMetadata,
    ledger::{OpenTrade, TradeAllocation},
};
use crate::StrategyTrade;

fn normalize_zero(value: f64) -> f64 {
    if value == 0.0 { 0.0 } else { value }
}

fn closed_trade_profit_percent(entry_price: f64, qty: f64, profit: f64) -> f64 {
    let denominator = entry_price * qty;
    if !profit.is_finite() || !denominator.is_finite() || denominator <= 0.0 {
        return 0.0;
    }
    normalize_zero(profit / denominator * 100.0)
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct AllocatedEntryFill {
    pub(super) entry_price: f64,
    pub(super) entry_bar_index: usize,
    pub(super) entry_time: i64,
    pub(super) entry_commission: f64,
    pub(super) entry_metadata: StrategyOrderMetadata,
}

impl AllocatedEntryFill {
    pub(super) fn from_allocations(
        allocations: &[TradeAllocation],
        fallback_entry_price: f64,
        fallback_entry_bar_index: usize,
        fallback_entry_time: i64,
        fallback_entry_commission: f64,
    ) -> Self {
        let Some(first_allocation) = allocations.first() else {
            return Self {
                entry_price: fallback_entry_price,
                entry_bar_index: fallback_entry_bar_index,
                entry_time: fallback_entry_time,
                entry_commission: fallback_entry_commission,
                entry_metadata: StrategyOrderMetadata::default(),
            };
        };

        Self {
            entry_price: first_allocation.entry_price,
            entry_bar_index: first_allocation.entry_bar_index,
            entry_time: first_allocation.entry_time,
            entry_commission: allocations
                .iter()
                .map(|allocation| allocation.entry_commission)
                .sum(),
            entry_metadata: first_allocation.entry_metadata.clone(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct ClosedTradeFill {
    pub(super) entry_id: String,
    pub(super) exit_id: String,
    pub(super) entry_fill: AllocatedEntryFill,
    pub(super) exit_bar_index: usize,
    pub(super) exit_time: i64,
    pub(super) exit_price: f64,
    pub(super) qty: f64,
    pub(super) profit: f64,
    pub(super) commission: f64,
    pub(super) close_metadata: StrategyOrderMetadata,
}

impl BrokerState {
    pub(super) fn record_closed_trade_fill(&mut self, fill: ClosedTradeFill) {
        self.trades.push(StrategyTrade {
            id: fill.entry_id,
            exit_id: fill.exit_id,
            entry_bar_index: fill.entry_fill.entry_bar_index,
            exit_bar_index: fill.exit_bar_index,
            entry_time: fill.entry_fill.entry_time,
            exit_time: fill.exit_time,
            entry_price: fill.entry_fill.entry_price,
            exit_price: fill.exit_price,
            qty: fill.qty,
            profit: fill.profit,
        });
        self.closed_trade_metrics.push(ClosedTradeMetrics {
            commission: fill.commission,
            profit_percent: closed_trade_profit_percent(
                fill.entry_fill.entry_price,
                fill.qty,
                fill.profit,
            ),
            max_runup: self.current_open_trade_max_runup_for_quantity(fill.qty),
            max_drawdown: self.current_open_trade_max_drawdown_for_quantity(fill.qty),
            entry_comment: fill.entry_fill.entry_metadata.comment.clone(),
            exit_comment: fill.close_metadata.comment.clone(),
            close_metadata: fill.close_metadata,
        });
    }

    pub(super) fn record_open_long_legacy_state(&mut self, trade: &OpenTrade) {
        if self.position_size <= 0.0 {
            self.position_entry_name = Some(trade.id.clone());
        }
        self.position_size = trade.quantity;
        self.max_contracts_held_long = self.max_contracts_held_long.max(trade.quantity);
        self.avg_price = trade.entry_price;
        self.open_entry_commission = trade.entry_commission;
        self.cash -= trade.quantity * trade.entry_price + trade.entry_commission;
        self.entry_id = Some(trade.id.clone());
        self.entry_bar_index = Some(trade.entry_bar_index);
        self.entry_time = Some(trade.entry_time);
        self.open_trade_max_high = trade.max_high;
        self.open_trade_min_low = trade.min_low;
        self.open_trade_equity_on_entry = trade.equity_on_entry;
        self.open_trade_min_equity_before_entry = trade.min_equity_before_entry;
        self.open_trade_max_equity_before_entry = trade.max_equity_before_entry;
    }

    pub(super) fn clear_open_long_legacy_state(&mut self) {
        self.position_size = 0.0;
        self.avg_price = 0.0;
        self.entry_id = None;
        self.position_entry_name = None;
        self.entry_bar_index = None;
        self.entry_time = None;
        self.open_entry_commission = 0.0;
        self.open_trade_max_high = None;
        self.open_trade_min_low = None;
        self.open_trade_equity_on_entry = None;
        self.open_trade_min_equity_before_entry = None;
        self.open_trade_max_equity_before_entry = None;
    }
}
