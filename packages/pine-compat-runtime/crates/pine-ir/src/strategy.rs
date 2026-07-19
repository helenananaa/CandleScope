pub const DEFAULT_STRATEGY_INITIAL_CAPITAL: f64 = 100_000.0;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum StrategyDefaultQuantity {
    Fixed(f64),
    Cash(f64),
    PercentOfEquity(f64),
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum StrategyCommission {
    CashPerContract(f64),
    CashPerOrder(f64),
    Percent(f64),
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StrategyMarginSetting {
    pub value_percent: f64,
    pub explicit: bool,
}

impl StrategyMarginSetting {
    #[must_use]
    pub fn explicit(value_percent: f64) -> Self {
        Self {
            value_percent,
            explicit: true,
        }
    }

    #[must_use]
    pub fn is_active(self) -> bool {
        self.explicit && self.value_percent > 0.0
    }
}

impl Default for StrategyMarginSetting {
    fn default() -> Self {
        Self {
            value_percent: 0.0,
            explicit: false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StrategyCloseEntriesRule {
    Fifo,
    Any,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StrategySettings {
    pub initial_capital: f64,
    pub default_qty: Option<StrategyDefaultQuantity>,
    pub commission: Option<StrategyCommission>,
    pub pyramiding_limit: usize,
    pub slippage_ticks: f64,
    pub backtest_fill_limit_ticks: f64,
    pub margin_long: StrategyMarginSetting,
    pub margin_short: StrategyMarginSetting,
    pub close_entries_rule: StrategyCloseEntriesRule,
}

impl Default for StrategySettings {
    fn default() -> Self {
        Self {
            initial_capital: DEFAULT_STRATEGY_INITIAL_CAPITAL,
            default_qty: Some(StrategyDefaultQuantity::Fixed(1.0)),
            commission: None,
            pyramiding_limit: 1,
            slippage_ticks: 0.0,
            backtest_fill_limit_ticks: 0.0,
            margin_long: StrategyMarginSetting::default(),
            margin_short: StrategyMarginSetting::default(),
            close_entries_rule: StrategyCloseEntriesRule::Fifo,
        }
    }
}

impl StrategySettings {
    #[must_use]
    pub fn default_entry_qty(self, equity: f64, price: f64) -> Option<f64> {
        self.default_qty.and_then(|default_qty| match default_qty {
            StrategyDefaultQuantity::Fixed(qty) => Some(qty),
            StrategyDefaultQuantity::Cash(cash) => {
                if !price.is_finite() || price <= 0.0 {
                    return None;
                }
                Some(cash / price)
            }
            StrategyDefaultQuantity::PercentOfEquity(percent) => {
                if !equity.is_finite() || !price.is_finite() || equity <= 0.0 || price <= 0.0 {
                    return None;
                }
                Some(equity * percent / 100.0 / price)
            }
        })
    }

    #[must_use]
    pub fn commission_cash_per_contract(self) -> f64 {
        match self.commission {
            Some(StrategyCommission::CashPerContract(value)) => value,
            Some(StrategyCommission::CashPerOrder(_))
            | Some(StrategyCommission::Percent(_))
            | None => 0.0,
        }
    }
}
