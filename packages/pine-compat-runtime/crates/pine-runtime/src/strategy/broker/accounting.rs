use super::BrokerState;
use super::ledger::OpenTrade;
use crate::{PineValue, StrategyEquitySnapshot, StrategyTrade};

fn normalize_zero(value: f64) -> f64 {
    if value == 0.0 { 0.0 } else { value }
}

fn trade_value_percent(amount: f64, entry_price: f64, quantity: f64) -> Option<f64> {
    let denominator = entry_price * quantity.abs();
    if !amount.is_finite() || !denominator.is_finite() || denominator <= 0.0 {
        return None;
    }
    Some(normalize_zero(amount / denominator * 100.0))
}

impl BrokerState {
    pub(crate) fn record_equity(&mut self, bar_index: usize, close: f64) {
        let market_value = self.position_size * close;
        let equity = self.cash + market_value;
        let net_profit = normalize_zero(equity - self.initial_capital);
        self.equity.push(StrategyEquitySnapshot {
            bar_index,
            cash: self.cash,
            market_value,
            equity,
            net_profit,
        });
    }

    pub(crate) fn update_open_trade_extremes(&mut self, high: f64, low: f64) {
        if self.open_trade_count() <= 0 {
            return;
        }
        self.trade_ledger.update_extremes(high, low);
        if self.open_trade_count() != 1 {
            return;
        }
        if high.is_finite() {
            self.open_trade_max_high = Some(
                self.open_trade_max_high
                    .map_or(high, |current| current.max(high)),
            );
        }
        if low.is_finite() {
            self.open_trade_min_low = Some(
                self.open_trade_min_low
                    .map_or(low, |current| current.min(low)),
            );
        }
        self.update_open_trade_max_runup();
        self.update_open_trade_max_drawdown();
    }

    #[must_use]
    pub(crate) fn open_profit(&self, close: f64) -> f64 {
        if self.position_size > 0.0 {
            normalize_zero((close - self.avg_price) * self.position_size)
        } else {
            0.0
        }
    }

    #[must_use]
    pub(crate) fn open_profit_percent(&self, close: f64) -> Option<f64> {
        let open_profit = self.open_profit(close);
        let realized_equity = self.initial_capital + self.realized_profit();
        if !open_profit.is_finite() || !realized_equity.is_finite() || realized_equity <= 0.0 {
            return None;
        }
        Some(normalize_zero(open_profit / realized_equity * 100.0))
    }

    #[must_use]
    pub(crate) fn open_trade_capital_held(&self, close: f64) -> Option<f64> {
        let has_active_margin = self.margin_long.is_active() || self.margin_short.is_active();
        if !has_active_margin {
            return None;
        }
        if self.position_size <= 0.0 {
            return Some(0.0);
        }
        if !self.margin_long.is_active() {
            return None;
        }
        if !close.is_finite() {
            return None;
        }
        Some(normalize_zero(
            self.position_size * close * self.margin_long.value_percent / 100.0,
        ))
    }

    #[must_use]
    pub(crate) fn margin_liquidation_price(&self) -> Option<f64> {
        if self.position_size <= 0.0 || !self.margin_long.is_active() {
            return None;
        }
        let margin_ratio = self.margin_long.value_percent / 100.0;
        if !margin_ratio.is_finite() || margin_ratio <= 0.0 {
            return None;
        }
        let denominator = self.position_size * (1.0 - margin_ratio);
        if !denominator.is_finite() || denominator == 0.0 {
            return None;
        }
        let price = -self.cash / denominator;
        if price.is_finite() {
            Some(normalize_zero(price))
        } else {
            None
        }
    }

    #[must_use]
    pub(crate) fn can_afford_long_entry(&self, qty: f64, fill_price: f64) -> bool {
        if !self.margin_long.is_active() {
            return true;
        }
        let required_margin = qty * fill_price * self.margin_long.value_percent / 100.0;
        required_margin.is_finite() && self.equity_value(fill_price) >= required_margin
    }

    #[must_use]
    pub(crate) fn initial_capital(&self) -> f64 {
        self.initial_capital
    }

    #[must_use]
    pub(crate) fn realized_profit(&self) -> f64 {
        normalize_zero(self.trades.iter().map(|trade| trade.profit).sum())
    }

    #[must_use]
    pub(crate) fn realized_profit_percent(&self) -> f64 {
        self.initial_capital_percent(self.realized_profit())
    }

    #[must_use]
    pub(crate) fn gross_profit(&self) -> f64 {
        normalize_zero(
            self.trades
                .iter()
                .filter(|trade| trade.profit > 0.0)
                .map(|trade| trade.profit)
                .sum(),
        )
    }

    #[must_use]
    pub(crate) fn gross_profit_percent(&self) -> f64 {
        self.initial_capital_percent(self.gross_profit())
    }

    #[must_use]
    pub(crate) fn gross_loss(&self) -> f64 {
        normalize_zero(
            self.trades
                .iter()
                .filter(|trade| trade.profit < 0.0)
                .map(|trade| -trade.profit)
                .sum(),
        )
    }

    #[must_use]
    pub(crate) fn gross_loss_percent(&self) -> f64 {
        self.initial_capital_percent(self.gross_loss())
    }

    #[must_use]
    pub(crate) fn average_trade(&self) -> Option<f64> {
        if self.trades.is_empty() {
            None
        } else {
            Some(normalize_zero(
                self.realized_profit() / self.trades.len() as f64,
            ))
        }
    }

    #[must_use]
    pub(crate) fn average_winning_trade(&self) -> Option<f64> {
        let mut count = 0usize;
        let mut total = 0.0;
        for trade in &self.trades {
            if trade.profit > 0.0 {
                count += 1;
                total += trade.profit;
            }
        }
        if count == 0 {
            None
        } else {
            Some(normalize_zero(total / count as f64))
        }
    }

    #[must_use]
    pub(crate) fn average_losing_trade(&self) -> Option<f64> {
        let mut count = 0usize;
        let mut total = 0.0;
        for trade in &self.trades {
            if trade.profit < 0.0 {
                count += 1;
                total += -trade.profit;
            }
        }
        if count == 0 {
            None
        } else {
            Some(normalize_zero(total / count as f64))
        }
    }

    #[must_use]
    pub(crate) fn average_trade_percent(&self) -> Option<f64> {
        self.average_trade_percent_matching(|_| true, |value| value)
    }

    #[must_use]
    pub(crate) fn average_winning_trade_percent(&self) -> Option<f64> {
        self.average_trade_percent_matching(|profit| profit > 0.0, |value| value)
    }

    #[must_use]
    pub(crate) fn average_losing_trade_percent(&self) -> Option<f64> {
        self.average_trade_percent_matching(|profit| profit < 0.0, |value| -value)
    }

    fn average_trade_percent_matching(
        &self,
        include_profit: impl Fn(f64) -> bool,
        map_percent: impl Fn(f64) -> f64,
    ) -> Option<f64> {
        let mut count = 0usize;
        let mut total = 0.0;
        for (trade, metrics) in self.trades.iter().zip(&self.closed_trade_metrics) {
            if include_profit(trade.profit) {
                count += 1;
                total += map_percent(metrics.profit_percent);
            }
        }
        if count == 0 {
            None
        } else {
            Some(normalize_zero(total / count as f64))
        }
    }

    #[must_use]
    pub(crate) fn max_drawdown(&self) -> f64 {
        normalize_zero(self.max_drawdown)
    }

    #[must_use]
    pub(crate) fn max_drawdown_percent(&self) -> f64 {
        normalize_zero(self.max_drawdown_percent)
    }

    #[must_use]
    pub(crate) fn max_runup(&self) -> f64 {
        normalize_zero(self.max_runup)
    }

    #[must_use]
    pub(crate) fn max_runup_percent(&self) -> f64 {
        normalize_zero(self.max_runup_percent)
    }

    #[must_use]
    pub(crate) fn max_contracts_held_all(&self) -> f64 {
        self.max_contracts_held_long()
    }

    #[must_use]
    pub(crate) fn max_contracts_held_long(&self) -> f64 {
        normalize_zero(self.max_contracts_held_long)
    }

    #[must_use]
    pub(crate) fn max_contracts_held_short(&self) -> f64 {
        0.0
    }

    #[must_use]
    pub(crate) fn equity_value(&self, close: f64) -> f64 {
        normalize_zero(self.cash + self.position_size * close)
    }

    fn initial_capital_percent(&self, value: f64) -> f64 {
        if !value.is_finite() || !self.initial_capital.is_finite() || self.initial_capital <= 0.0 {
            return 0.0;
        }
        normalize_zero(value / self.initial_capital * 100.0)
    }

    #[must_use]
    pub(crate) fn position_size(&self) -> f64 {
        self.position_size
    }

    #[must_use]
    pub fn closed_trade_count(&self) -> i64 {
        i64::try_from(self.trades.len()).unwrap_or(i64::MAX)
    }

    #[must_use]
    pub(crate) fn first_closed_trade_index(&self) -> i64 {
        // The local broker retains every closed trade, so the oldest retained
        // trade keeps its original zero-based index even before one exists.
        0
    }

    #[must_use]
    pub(crate) fn closed_trade(&self, trade_num: i64) -> Option<&StrategyTrade> {
        let index = usize::try_from(trade_num).ok()?;
        self.trades.get(index)
    }

    #[must_use]
    pub(crate) fn closed_trade_max_runup(&self, trade_num: i64) -> Option<f64> {
        let index = usize::try_from(trade_num).ok()?;
        self.closed_trade_metrics
            .get(index)
            .map(|metrics| metrics.max_runup)
    }

    #[must_use]
    pub(crate) fn closed_trade_profit_percent(&self, trade_num: i64) -> Option<f64> {
        let trade = self.closed_trade(trade_num)?;
        trade_value_percent(trade.profit, trade.entry_price, trade.qty)
    }

    #[must_use]
    pub(crate) fn closed_trade_max_runup_percent(&self, trade_num: i64) -> Option<f64> {
        let trade = self.closed_trade(trade_num)?;
        let amount = self.closed_trade_max_runup(trade_num)?;
        trade_value_percent(amount, trade.entry_price, trade.qty)
    }

    #[must_use]
    pub(crate) fn closed_trade_commission(&self, trade_num: i64) -> Option<f64> {
        let index = usize::try_from(trade_num).ok()?;
        self.closed_trade_metrics
            .get(index)
            .map(|metrics| metrics.commission)
    }

    #[must_use]
    pub(crate) fn closed_trade_max_drawdown(&self, trade_num: i64) -> Option<f64> {
        let index = usize::try_from(trade_num).ok()?;
        self.closed_trade_metrics
            .get(index)
            .map(|metrics| metrics.max_drawdown)
    }

    #[must_use]
    pub(crate) fn closed_trade_max_drawdown_percent(&self, trade_num: i64) -> Option<f64> {
        let trade = self.closed_trade(trade_num)?;
        let amount = self.closed_trade_max_drawdown(trade_num)?;
        trade_value_percent(amount, trade.entry_price, trade.qty)
    }

    #[must_use]
    pub(crate) fn closed_trade_entry_comment(&self, trade_num: i64) -> Option<&str> {
        let index = usize::try_from(trade_num).ok()?;
        self.closed_trade_metrics
            .get(index)
            .and_then(|metrics| metrics.entry_comment.as_deref())
    }

    #[must_use]
    pub(crate) fn closed_trade_exit_comment(&self, trade_num: i64) -> Option<&str> {
        let index = usize::try_from(trade_num).ok()?;
        self.closed_trade_metrics
            .get(index)
            .and_then(|metrics| metrics.exit_comment.as_deref())
    }

    #[must_use]
    pub fn winning_trade_count(&self) -> i64 {
        i64::try_from(
            self.trades
                .iter()
                .filter(|trade| trade.profit > 0.0)
                .count(),
        )
        .unwrap_or(i64::MAX)
    }

    #[must_use]
    pub fn losing_trade_count(&self) -> i64 {
        i64::try_from(
            self.trades
                .iter()
                .filter(|trade| trade.profit < 0.0)
                .count(),
        )
        .unwrap_or(i64::MAX)
    }

    #[must_use]
    pub fn even_trade_count(&self) -> i64 {
        i64::try_from(
            self.trades
                .iter()
                .filter(|trade| normalize_zero(trade.profit) == 0.0)
                .count(),
        )
        .unwrap_or(i64::MAX)
    }

    #[must_use]
    pub fn open_trade_count(&self) -> i64 {
        i64::try_from(self.trade_ledger.open_count()).unwrap_or(i64::MAX)
    }

    fn open_trade_at(&self, trade_num: i64) -> Option<&OpenTrade> {
        let index = usize::try_from(trade_num).ok()?;
        self.trade_ledger.open_at(index)
    }

    #[must_use]
    pub(crate) fn open_trade_entry_price(&self, trade_num: i64) -> Option<f64> {
        self.open_trade_at(trade_num).map(|trade| trade.entry_price)
    }

    #[must_use]
    pub(crate) fn open_trade_entry_id(&self, trade_num: i64) -> Option<&str> {
        self.open_trade_at(trade_num).map(|trade| trade.id.as_str())
    }

    #[must_use]
    pub(crate) fn open_trade_entry_comment(&self, trade_num: i64) -> Option<&str> {
        self.open_trade_at(trade_num)
            .and_then(|trade| trade.entry_metadata.comment.as_deref())
    }

    #[must_use]
    pub(crate) fn open_trade_entry_bar_index(&self, trade_num: i64) -> Option<usize> {
        self.open_trade_at(trade_num)
            .map(|trade| trade.entry_bar_index)
    }

    #[must_use]
    pub(crate) fn open_trade_entry_time(&self, trade_num: i64) -> Option<i64> {
        self.open_trade_at(trade_num).map(|trade| trade.entry_time)
    }

    #[must_use]
    pub(crate) fn open_trade_size(&self, trade_num: i64) -> Option<f64> {
        self.open_trade_at(trade_num).map(|trade| trade.quantity)
    }

    #[must_use]
    pub(crate) fn open_trade_profit(&self, trade_num: i64, close: f64) -> Option<f64> {
        self.open_trade_at(trade_num)
            .map(|trade| normalize_zero((close - trade.entry_price) * trade.quantity))
    }

    #[must_use]
    pub(crate) fn open_trade_profit_percent(&self, trade_num: i64, close: f64) -> Option<f64> {
        let trade = self.open_trade_at(trade_num)?;
        let amount = normalize_zero((close - trade.entry_price) * trade.quantity);
        trade_value_percent(amount, trade.entry_price, trade.quantity)
    }

    #[must_use]
    pub(crate) fn open_trade_commission(&self, trade_num: i64) -> Option<f64> {
        self.open_trade_at(trade_num)
            .map(|trade| normalize_zero(trade.entry_commission))
    }

    #[must_use]
    pub(crate) fn open_trade_max_runup(&self, trade_num: i64) -> Option<f64> {
        self.open_trade_at(trade_num).and_then(|trade| {
            let max_high = trade.max_high?;
            Some(normalize_zero(
                (max_high - trade.entry_price).max(0.0) * trade.quantity,
            ))
        })
    }

    #[must_use]
    pub(crate) fn open_trade_max_runup_percent(&self, trade_num: i64) -> Option<f64> {
        let trade = self.open_trade_at(trade_num)?;
        let max_high = trade.max_high?;
        let amount = normalize_zero((max_high - trade.entry_price).max(0.0) * trade.quantity);
        trade_value_percent(amount, trade.entry_price, trade.quantity)
    }

    #[must_use]
    pub(crate) fn open_trade_max_drawdown(&self, trade_num: i64) -> Option<f64> {
        self.open_trade_at(trade_num).and_then(|trade| {
            let min_low = trade.min_low?;
            Some(normalize_zero(
                (trade.entry_price - min_low).max(0.0) * trade.quantity,
            ))
        })
    }

    #[must_use]
    pub(crate) fn open_trade_max_drawdown_percent(&self, trade_num: i64) -> Option<f64> {
        let trade = self.open_trade_at(trade_num)?;
        let min_low = trade.min_low?;
        let amount = normalize_zero((trade.entry_price - min_low).max(0.0) * trade.quantity);
        trade_value_percent(amount, trade.entry_price, trade.quantity)
    }

    #[must_use]
    pub(super) fn current_open_trade_max_runup_for_quantity(&self, qty: f64) -> f64 {
        let Some(max_high) = self.open_trade_max_high else {
            return 0.0;
        };
        normalize_zero((max_high - self.avg_price).max(0.0) * qty)
    }

    fn current_open_strategy_max_runup(&self) -> Option<f64> {
        if self.open_trade_count() != 1 {
            return None;
        }
        let equity_on_entry = self.open_trade_equity_on_entry?;
        let min_equity_before_entry = self.open_trade_min_equity_before_entry?;
        let max_high = self.open_trade_max_high?;
        Some(normalize_zero(
            (equity_on_entry - min_equity_before_entry
                + (max_high - self.avg_price).max(0.0) * self.position_size)
                .max(0.0),
        ))
    }

    fn update_open_trade_max_runup(&mut self) {
        if let Some(runup) = self.current_open_strategy_max_runup() {
            self.max_runup = self.max_runup.max(runup);
            if let Some(percent) = self.current_open_strategy_percent(runup) {
                self.max_runup_percent = self.max_runup_percent.max(percent);
            }
        }
    }

    fn current_open_strategy_max_drawdown(&self) -> Option<f64> {
        if self.open_trade_count() != 1 {
            return None;
        }
        let equity_on_entry = self.open_trade_equity_on_entry?;
        let max_equity_before_entry = self.open_trade_max_equity_before_entry?;
        let min_low = self.open_trade_min_low?;
        Some(normalize_zero(
            (max_equity_before_entry - equity_on_entry
                + (self.avg_price - min_low).max(0.0) * self.position_size)
                .max(0.0),
        ))
    }

    fn update_open_trade_max_drawdown(&mut self) {
        if let Some(drawdown) = self.current_open_strategy_max_drawdown() {
            self.max_drawdown = self.max_drawdown.max(drawdown);
            if let Some(percent) = self.current_open_strategy_percent(drawdown) {
                self.max_drawdown_percent = self.max_drawdown_percent.max(percent);
            }
        }
    }

    fn current_open_strategy_percent(&self, amount: f64) -> Option<f64> {
        if self.open_trade_count() != 1 {
            return None;
        }
        let denominator = self.avg_price * self.position_size;
        if !amount.is_finite() || !denominator.is_finite() || denominator <= 0.0 {
            return None;
        }
        Some(normalize_zero(amount / denominator * 100.0))
    }

    #[must_use]
    pub(super) fn current_open_trade_max_drawdown_for_quantity(&self, qty: f64) -> f64 {
        let Some(min_low) = self.open_trade_min_low else {
            return 0.0;
        };
        normalize_zero((self.avg_price - min_low).max(0.0) * qty)
    }

    #[must_use]
    pub(crate) fn position_avg_price_value(&self) -> PineValue {
        if self.position_size > 0.0 {
            PineValue::Float(self.avg_price)
        } else {
            PineValue::Na
        }
    }

    #[must_use]
    pub(crate) fn position_entry_name_value(&self) -> PineValue {
        if self.position_size <= 0.0 {
            return PineValue::Na;
        }
        self.position_entry_name
            .as_ref()
            .map_or(PineValue::Na, |name| PineValue::String(name.clone()))
    }
}
