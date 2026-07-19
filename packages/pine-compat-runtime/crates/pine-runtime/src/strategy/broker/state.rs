use pine_ir::{
    DEFAULT_STRATEGY_INITIAL_CAPITAL, StrategyCloseEntriesRule, StrategyCommission,
    StrategyMarginSetting,
};

use super::{
    BrokerState, StrategyExitMetadata, StrategyOrderMetadata, ledger::TradeLedger,
    order_book::OrderBook,
};
use crate::{StrategyOrderFillAlertOutput, StrategyResult};

impl Default for BrokerState {
    fn default() -> Self {
        Self::new(DEFAULT_STRATEGY_INITIAL_CAPITAL)
    }
}

impl BrokerState {
    #[must_use]
    pub fn new(initial_capital: f64) -> Self {
        Self::new_with_commission(initial_capital, None)
    }

    #[must_use]
    pub fn new_with_cash_per_contract_commission(
        initial_capital: f64,
        commission_per_contract: f64,
    ) -> Self {
        Self::new_with_commission(
            initial_capital,
            Some(StrategyCommission::CashPerContract(commission_per_contract)),
        )
    }

    #[must_use]
    pub fn new_with_commission(
        initial_capital: f64,
        commission: Option<StrategyCommission>,
    ) -> Self {
        Self::new_with_commission_and_slippage(initial_capital, commission, 0.0)
    }

    #[must_use]
    pub fn new_with_commission_and_slippage(
        initial_capital: f64,
        commission: Option<StrategyCommission>,
        slippage_price_offset: f64,
    ) -> Self {
        Self::new_with_commission_slippage_and_limit_verification(
            initial_capital,
            commission,
            slippage_price_offset,
            0.0,
        )
    }

    #[must_use]
    pub fn new_with_commission_slippage_and_limit_verification(
        initial_capital: f64,
        commission: Option<StrategyCommission>,
        slippage_price_offset: f64,
        limit_verification_price_offset: f64,
    ) -> Self {
        Self::new_with_account_settings(
            initial_capital,
            commission,
            slippage_price_offset,
            limit_verification_price_offset,
            StrategyMarginSetting::default(),
            StrategyMarginSetting::default(),
        )
    }

    #[must_use]
    pub fn new_with_account_settings(
        initial_capital: f64,
        commission: Option<StrategyCommission>,
        slippage_price_offset: f64,
        limit_verification_price_offset: f64,
        margin_long: StrategyMarginSetting,
        margin_short: StrategyMarginSetting,
    ) -> Self {
        Self::new_with_account_settings_and_pyramiding(
            initial_capital,
            commission,
            slippage_price_offset,
            limit_verification_price_offset,
            margin_long,
            margin_short,
            1,
        )
    }

    #[must_use]
    pub fn new_with_account_settings_and_pyramiding(
        initial_capital: f64,
        commission: Option<StrategyCommission>,
        slippage_price_offset: f64,
        limit_verification_price_offset: f64,
        margin_long: StrategyMarginSetting,
        margin_short: StrategyMarginSetting,
        pyramiding_limit: usize,
    ) -> Self {
        Self {
            initial_capital,
            commission,
            pyramiding_limit,
            close_entries_rule: StrategyCloseEntriesRule::Fifo,
            margin_long,
            margin_short,
            open_entry_commission: 0.0,
            slippage_price_offset,
            limit_verification_price_offset,
            cash: initial_capital,
            position_size: 0.0,
            avg_price: 0.0,
            next_close_metadata: StrategyOrderMetadata::default(),
            next_exit_metadata: StrategyExitMetadata::default(),
            entry_id: None,
            position_entry_name: None,
            entry_bar_index: None,
            entry_time: None,
            open_trade_max_high: None,
            open_trade_min_low: None,
            open_trade_equity_on_entry: None,
            open_trade_min_equity_before_entry: None,
            open_trade_max_equity_before_entry: None,
            min_equity_before_open_trade: initial_capital,
            max_equity_before_open_trade: initial_capital,
            max_runup: 0.0,
            max_runup_percent: 0.0,
            max_drawdown: 0.0,
            max_drawdown_percent: 0.0,
            max_contracts_held_long: 0.0,
            orders: Vec::new(),
            order_fill_alerts: Vec::new(),
            trades: Vec::new(),
            closed_trade_metrics: Vec::new(),
            position: Vec::new(),
            equity: Vec::new(),
            diagnostics: Vec::new(),
            order_book: OrderBook::new(),
            trade_ledger: TradeLedger::default(),
        }
    }

    #[must_use]
    pub(crate) fn with_close_entries_rule(
        mut self,
        close_entries_rule: StrategyCloseEntriesRule,
    ) -> Self {
        self.close_entries_rule = close_entries_rule;
        self
    }

    fn commission_for_fill(&self, qty: f64, price: f64) -> f64 {
        match self.commission {
            Some(StrategyCommission::CashPerContract(value)) => qty * value,
            Some(StrategyCommission::CashPerOrder(value)) => value,
            Some(StrategyCommission::Percent(value)) => qty * price * (value / 100.0),
            None => 0.0,
        }
    }

    pub(super) fn entry_commission_for_fill(&self, qty: f64, price: f64) -> f64 {
        self.commission_for_fill(qty, price)
    }

    pub(super) fn exit_commission_for_fill(&self, qty: f64, price: f64) -> f64 {
        self.commission_for_fill(qty, price)
    }

    pub(crate) fn with_next_exit_metadata<T>(
        &mut self,
        metadata: StrategyExitMetadata,
        f: impl FnOnce(&mut Self) -> T,
    ) -> T {
        let previous = std::mem::replace(&mut self.next_exit_metadata, metadata);
        let result = f(self);
        self.next_exit_metadata = previous;
        result
    }

    pub(super) fn take_next_exit_metadata(&mut self) -> StrategyExitMetadata {
        std::mem::take(&mut self.next_exit_metadata)
    }

    pub(crate) fn with_next_close_metadata<T>(
        &mut self,
        metadata: StrategyOrderMetadata,
        f: impl FnOnce(&mut Self) -> T,
    ) -> T {
        let previous = std::mem::replace(&mut self.next_close_metadata, metadata);
        let result = f(self);
        self.next_close_metadata = previous;
        result
    }

    pub(super) fn take_next_close_metadata(&mut self) -> StrategyOrderMetadata {
        std::mem::take(&mut self.next_close_metadata)
    }

    pub(super) fn entry_commission_for_closed_quantity(&self, qty: f64) -> f64 {
        if qty >= self.position_size {
            self.open_entry_commission
        } else {
            self.open_entry_commission * (qty / self.position_size)
        }
    }

    pub(super) fn long_entry_fill_price(&self, price: f64) -> f64 {
        price + self.slippage_price_offset
    }

    pub(super) fn long_exit_fill_price(&self, price: f64) -> f64 {
        price - self.slippage_price_offset
    }

    pub(super) fn long_limit_exit_is_verified(&self, limit_price: f64, high: f64) -> bool {
        high >= limit_price + self.limit_verification_price_offset
    }

    #[must_use]
    pub fn result(&self) -> StrategyResult {
        StrategyResult {
            orders: self.orders.clone(),
            trades: self.trades.clone(),
            position: self.position.clone(),
            equity: self.equity.clone(),
            alerts: self
                .order_fill_alerts
                .iter()
                .map(|event| StrategyOrderFillAlertOutput {
                    id: event.id.clone(),
                    bar_index: event.bar_index,
                    time: event.time,
                    direction: event.direction.clone(),
                    qty: event.qty,
                    price: event.price,
                    entry_id: event.entry_id.clone(),
                    exit_id: event.exit_id.clone(),
                    message: event.message.clone(),
                })
                .collect(),
            diagnostics: self.diagnostics.clone(),
        }
    }
}
