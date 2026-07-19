use super::model::RuntimeDiagnostic;

#[derive(Debug, Clone, PartialEq, Default)]
pub struct StrategyResult {
    pub orders: Vec<StrategyOrderEvent>,
    pub trades: Vec<StrategyTrade>,
    pub position: Vec<StrategyPositionSnapshot>,
    pub equity: Vec<StrategyEquitySnapshot>,
    pub alerts: Vec<StrategyOrderFillAlertOutput>,
    pub diagnostics: Vec<RuntimeDiagnostic>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StrategyOrderEvent {
    pub id: String,
    pub bar_index: usize,
    pub time: i64,
    pub direction: String,
    pub qty: f64,
    pub price: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StrategyOrderFillAlertOutput {
    pub id: String,
    pub bar_index: usize,
    pub time: i64,
    pub direction: String,
    pub qty: f64,
    pub price: f64,
    pub entry_id: Option<String>,
    pub exit_id: Option<String>,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StrategyTrade {
    pub id: String,
    pub exit_id: String,
    pub entry_bar_index: usize,
    pub exit_bar_index: usize,
    pub entry_time: i64,
    pub exit_time: i64,
    pub entry_price: f64,
    pub exit_price: f64,
    pub qty: f64,
    pub profit: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StrategyPositionSnapshot {
    pub bar_index: usize,
    pub size: f64,
    pub avg_price: Option<f64>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct StrategyEquitySnapshot {
    pub bar_index: usize,
    pub cash: f64,
    pub market_value: f64,
    pub equity: f64,
    pub net_profit: f64,
}
